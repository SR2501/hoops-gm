"""Resolve this repository's two recurring rebase conflicts, verifying before staging.

    python scripts/resolve_doc_conflicts.py && git add -A && git rebase --continue

**This tool is committed because its failure mode is loud.** The distinction is
deliberate and is the rule, not a preference: commit a tool that *refuses* when
it is wrong, describe a tool that *under-approximates* when it is wrong. The
call-graph closure used to argue a function is off the cohort's derivation path
is the second kind — run blindly it emits a confident "not reachable" that is
false, and blesses a provenance claim nobody checked — so that one lives in
prose. This one exits non-zero and stages nothing, so the worst a blind run does
is stop the work.

**Staging is not resolution.** A lane committed ``<<<<<<< HEAD`` into
``docs/handoff.md``: its resolver raised on a block whose HEAD side was empty,
``git add`` ran anyway because resolve-and-stage were one command and only the
second exit status was read, and ``rebase --continue`` committed the markers
into an append-only file nobody re-reads. This script therefore **never calls
git**. It resolves, then asserts no marker survives anywhere in the tree, and
exits non-zero if one does. Staging is the caller's separate step, gated on the
exit status.

Three lanes needed this in one night, and the lane that did not have it shipped
the markers.

Two files, two different rules:

``docs/handoff.md`` is **append-only**. The resolution is every lane's entries in
order, main's side first. Nothing is chosen over anything, because discarding
either side deletes a record of work that happened.

``docs/backlog.md``'s header is **recomputed from the finished file**, never
reconciled from the two sides. Neither side is a usable input: each was computed
before the other lane's items landed. Measured — one lane found main at
39/71/111 and its own branch at 40/69/110 when the truth was 40/71/112. Neither
was right, and no reconciliation of the two could have reached the answer.
"""

from __future__ import annotations

import collections
import pathlib
import re
import sys

# Git writes a conflict separator as *exactly* seven equals signs on their own
# line, while the open/close markers are seven characters followed by a space and
# a ref. Matching `=======` as a *prefix* therefore fires on any line that merely
# starts with seven equals signs — an RST table border, or a markdown setext H1
# underline. That is not hypothetical: it refused a tree with zero real markers,
# and worse, a border on the *ours* side of a genuine conflict flipped the parser
# to "theirs" early and wrote the real separator into the file. So the separator
# is matched by equality and the others require their trailing space.
#
# `|||||||` is included because `merge.conflictStyle = diff3` emits a base
# section; nothing here resolves diff3, but the detector must refuse a tree that
# contains one rather than pass it silently.
CONFLICT_BEGIN = "<<<<<<< "
CONFLICT_SEPARATOR = "======="
CONFLICT_BASE = "||||||| "
CONFLICT_END = ">>>>>>> "

# The one region `resolve_backlog` is allowed to collapse. Matched on the count
# line's own shape rather than on a heading's absence, because "contains no
# heading" is true of an item's body as well as of the header, and that
# ambiguity is what let a dependency edge be deleted at exit 0.
_HEADER_COUNT = re.compile(
    r"\*\*\d+ done - \d+ blocked - \d+ pending - \d+ total\*\*"
)
_RECOUNT_NOTE = "Recomputed from the status markers in this finished file"

# Binary by extension, skipped without comment. Reporting a PDF as "not
# scanned" on every run is how the report gets deleted — a guard that cries
# wolf is the one the next person loosens, and this repository commits binary
# fixtures. The report exists for a *text* file the scan could not decode,
# which is the case that scanned clean and was claimed as covered.
BINARY_SUFFIXES = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".zip",
     ".gz", ".db", ".sqlite", ".sqlite3", ".xlsx", ".docx", ".pptx", ".parquet"}
)


def is_conflict_marker(line: str) -> bool:
    """Whether a line is a git conflict marker, not something that resembles one."""
    return (
        line.startswith(CONFLICT_BEGIN)
        or line.startswith(CONFLICT_BASE)
        or line.startswith(CONFLICT_END)
        or line == CONFLICT_SEPARATOR
    )
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
}


def resolve_append_only(path: pathlib.Path) -> None:
    """Keep both sides of every conflict, main's first."""
    if not path.is_file():
        return
    out: list[str] = []
    ours: list[str] = []
    theirs: list[str] = []
    mode = "normal"
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.startswith(CONFLICT_BEGIN):
            # A begin marker seen while already inside a block is content, not
            # structure — a doc quoting a marker verbatim. The previous form
            # restarted the block, which *consumed* the quoted line and exited
            # zero. `docs/handoff.md` quotes markers today; inline backticks
            # survive only because they do not start the line.
            if mode != "normal":
                sys.exit(
                    f"{path}: conflict begin marker inside an open block "
                    f"(mode={mode}). This is either a malformed conflict or a "
                    "document quoting a marker at line start. Refusing to "
                    "write, because the previous behaviour silently deleted it."
                )
            mode = "ours"
            continue
        if line.startswith(CONFLICT_BASE) and mode in {"ours", "base"}:
            mode = "base"
            continue
        if line == CONFLICT_SEPARATOR and mode in {"ours", "base"}:
            mode = "theirs"
            continue
        if line.startswith(CONFLICT_END) and mode == "theirs":
            out.extend(ours)
            out.extend(theirs)
            ours, theirs = [], []
            mode = "normal"
            continue
        if mode == "ours":
            ours.append(line)
        elif mode == "base":
            continue
        elif mode == "theirs":
            theirs.append(line)
        else:
            out.append(line)
    if mode != "normal" or ours or theirs:
        sys.exit(f"{path}: unterminated conflict block; refusing to write")
    path.write_text("\n".join(out), encoding="utf-8")


def resolve_backlog(path: pathlib.Path) -> None:
    """Drop the conflicted note block, then recompute the header from the file."""
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    had_conflict = CONFLICT_BEGIN in text
    slugs_before = set(re.findall(r"^### `([^`]+)`", text, re.M))

    # Collapse a conflicted block **only when it is the header count region**,
    # which is the one region this function knows how to resolve.
    #
    # Two earlier forms were both wrong, and the second is the instructive one.
    # The original replaced every conflict block, both sides, with a
    # placeholder — so when two lanes added items in the same region it
    # silently deleted all of them and exited zero. On 2026-08-21 that removed
    # three entries a lane had merged minutes earlier, and every check we had
    # agreed the result was fine: a recount of the finished file is *internally
    # consistent after a deletion*, because a dropped item takes its heading
    # and its marker with it.
    #
    # The fix for that exempted any block containing `### `. Review found it
    # **narrowed the defect rather than removing it**: a conflict inside an
    # item's *body* — its `- **Depends on:**` edges, its description — carries
    # no heading and no status marker, so it was still collapsed, the slug
    # guard below still saw no change, the 1:1 check still balanced, and the
    # script still printed "Safe to stage". That is worse than the original in
    # one specific way: deleting a dependency edge makes a blocked item look
    # **ready**, and `AGENTS.md` defines readiness as every dependency done.
    #
    # So: anchor to the count region and refuse on everything else. A resolver
    # that only knows how to resolve one region should say so on the others
    # rather than treating "I have no rule for this" as "delete both sides".
    def _collapse(match: "re.Match[str]") -> str:
        block = match.group(0)
        if _HEADER_COUNT.search(block) or _RECOUNT_NOTE in block:
            return "__NOTE__\n"
        excerpt = "\n".join(block.strip().split("\n")[:6])
        sys.exit(
            f"{path}: a conflict block outside the header count region. This "
            "script only knows how to resolve the count block; collapsing "
            "anything else deletes both sides. Resolve by hand and keep both "
            "sides' content — note that a body conflict can delete a "
            "'**Depends on:**' edge without changing any heading, marker or "
            f"total, so no other check here can see it.\n\n{excerpt}"
        )

    text = re.sub(
        r"<<<<<<< HEAD\n.*?>>>>>>> [^\n]*\n", _collapse, text, flags=re.DOTALL
    )

    # And the guard that does not depend on the mechanism above being right:
    # no item **slug** may leave this function that entered it. A total can be
    # recounted correctly and still be wrong; only the *set* sees a deletion.
    #
    # Stated at the strength it reaches, deliberately: this compares slugs, so
    # it sees a lost *item* and is blind to lost *content within* one. Before
    # the anchor above, that gap was reachable; it is the reason the anchor
    # exists rather than a caveat on this guard. Both are kept because they
    # fail independently — the anchor was verified by mutating it away and
    # watching this one still refuse.
    slugs_after = set(re.findall(r"^### `([^`]+)`", text, re.M))
    if lost := sorted(slugs_before - slugs_after):
        sys.exit(
            f"{path}: resolution would drop {len(lost)} backlog item(s): "
            f"{', '.join(lost)}. Refusing to write. Resolve this file by hand "
            "and diff its slug set against main."
        )

    lines = text.split("\n")
    headings = [line for line in lines if line.startswith("### ")]
    markers = [
        line
        for line in lines
        if re.match(r"^- \[[ x]\] \*\*(done|pending|blocked)\*\*", line)
    ]
    names = [m.group(1) for h in headings if (m := re.match(r"^### `([^`]+)`", h))]
    dupes = sorted(n for n, k in collections.Counter(names).items() if k > 1)
    if not (len(headings) == len(markers) == len(names)) or dupes:
        sys.exit(
            f"backlog is not 1:1: {len(headings)} headings, {len(markers)} markers, "
            f"{len(names)} named, duplicates {dupes}"
        )
    counts = collections.Counter(
        m.group(1)
        for line in markers
        if (m := re.match(r"^- \[[ x]\] \*\*(\w+)\*\*", line)) is not None
    )
    total = sum(counts.values())
    header = (
        f"**{counts['done']} done - {counts['blocked']} blocked - "
        f"{counts['pending']} pending - {total} total**"
    )
    if had_conflict:
        note = (
            "(Recomputed from the status markers in this finished file, never\n"
            f"reconciled from two headers: {len(headings)} `###` headings and\n"
            f"{len(markers)} markers, 1:1, no duplicate item names. Neither side of a\n"
            "rebase conflict is a usable input here, because each was computed before\n"
            "the other lane's items landed.)"
        )
        # The note carries the header when the conflicted block *was* the header
        # region, which is the only region we collapse. Found by the first test
        # ever written for this file: `re.sub` below matched nothing because the
        # header line had been collapsed into `__NOTE__`, the file was written
        # with no header at all, and the script printed
        # "backlog header recomputed: ..." regardless. A substitution that
        # matches nothing is not an error to `re.sub`, so the print was a claim
        # about an edit that did not happen.
        text = text.replace("__NOTE__", f"{header}\n\n{note}")

    text, substitutions = re.subn(
        r"^\*\*\d+ done - \d+ blocked - \d+ pending - \d+ total\*\*$",
        header,
        text,
        count=1,
        flags=re.MULTILINE,
    )

    # Assert the presence we expect rather than the absence of what we fear:
    # exactly one header line, in the file we are about to write. Counting is
    # cheap and it is the only thing that distinguishes "substituted", "carried
    # in on the note" and "silently absent" — all three of which reach this
    # line with `substitutions` telling a different story about each.
    written = len(
        re.findall(
            r"^\*\*\d+ done - \d+ blocked - \d+ pending - \d+ total\*\*$",
            text,
            flags=re.MULTILINE,
        )
    )
    if written != 1:
        sys.exit(
            f"{path}: expected exactly one header count line after resolution, "
            f"found {written}. Refusing to write. Two means both sides' headers "
            "survived; zero means the header was collapsed and not restored."
        )

    path.write_text(text, encoding="utf-8")
    print(f"  backlog header recomputed: {header}")


def surviving_markers() -> tuple[list[str], list[str]]:
    """Every conflict marker left in the tree, and every file not read.

    Returns both because the previous form returned only the first and `main`
    printed "no conflict marker in any text file" — a verdict covering files it
    had skipped. A file that cannot be decoded is not a file without markers;
    a latin-1 `.md` holding a complete conflict block scanned clean. This
    script's own subject is a check reporting a pass it did not earn.
    """
    found: list[str] = []
    unread: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or SKIP_DIRS & set(path.parts):
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            unread.append(f"{path.relative_to(REPO_ROOT)}: {type(exc).__name__}")
            continue
        for number, line in enumerate(text.split("\n"), 1):
            if is_conflict_marker(line):
                found.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line[:40]}")
    return found, unread


def main(argv: list[str] | None = None) -> int:
    """Resolve doc conflicts, verify, and report — or explain, if asked.

    This takes no options **and must say so rather than ignore them.** It
    previously read no arguments at all, so `--help` performed a full
    resolution and rewrote `docs/handoff.md` in the caller's tree. Nothing was
    lost that time, but a script that mutates tracked files when asked for help
    is one `--dry-run` away from a bad afternoon — the caller who types an
    unrecognised flag is precisely the caller who does not yet know what the
    tool does.

    So an unrecognised argument **refuses before touching anything**, which is
    the same order this script already enforces on itself: verify, then act.
    """
    args = sys.argv[1:] if argv is None else argv
    if args:
        usage = (
            "usage: resolve_doc_conflicts.py\n"
            "\n"
            "Resolves conflicts in docs/handoff.md (keeps both sides, main's\n"
            "first) and docs/backlog.md (recounts the header from the finished\n"
            "file), then refuses to let you stage if any conflict marker\n"
            "survives anywhere in the tree.\n"
            "\n"
            "Takes no options. It does not stage; run git add yourself after\n"
            "this exits 0.\n"
        )
        if args in (["-h"], ["--help"]):
            print(usage)
            return 0
        print(f"unrecognised argument(s): {' '.join(args)}\n\n{usage}", file=sys.stderr)
        return 2

    resolve_append_only(REPO_ROOT / "docs/handoff.md")
    resolve_backlog(REPO_ROOT / "docs/backlog.md")

    # Verify BEFORE the caller stages anything. This is the entire point.
    survivors, unread = surviving_markers()
    if survivors:
        # A stop that gives the operator nothing to resolve it with is a stop
        # they will learn to override, and they will override it using whatever
        # reason is nearest to hand. On 2026-08-21 the nearest reason was a
        # coordinator broadcast that this check false-positives on lines of
        # seven equals signs — true, and the reason this file was being fixed.
        # A true claim used as a general licence is worse than a false one,
        # because checking it confirms it and the check does not reveal that
        # its scope was narrower than its use. So the discriminator ships with
        # the stop, where it reaches everyone who trips it and cannot be
        # forgotten in transit.
        print("CONFLICT MARKERS SURVIVE - do not stage:")
        for line in survivors[:20]:
            print("   ", line)
        print()
        print("Before overriding, confirm this is not a real conflict:")
        print("    git diff --name-only --diff-filter=U")
        print(
            "If that lists none of the files above, the hit is in committed "
            "content rather than an unresolved merge \u2014 check the line itself."
        )
        return 1

    entries = sum(
        1
        for line in (REPO_ROOT / "docs/handoff.md")
        .read_text(encoding="utf-8")
        .split("\n")
        if re.match(r"^## \d{4}-\d{2}-\d{2}", line)
    )
    print(f"  handoff dated entries: {entries}")
    if unread:
        # Reported rather than swallowed: the verdict below is about the files
        # this scan could read, and saying so is the difference between a pass
        # and a pass it earned.
        print(f"NOT SCANNED - {len(unread)} file(s) could not be read:")
        for line in unread[:20]:
            print("   ", line)
        print("The verdict below does not cover them.")
    print("VERIFIED: no conflict marker in any text file this scan could read.")
    if not unread:
        print("Safe to stage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
