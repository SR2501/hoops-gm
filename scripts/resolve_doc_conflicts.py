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
_HEADER_COUNT = re.compile(r"\*\*\d+ done - \d+ blocked - \d+ pending - \d+ total\*\*")
_RECOUNT_NOTE = "Recomputed from the status markers in this finished file"


def _block_content_lines(block: str) -> list[str]:
    """The lines of a conflict block that are content, classified by position.

    **A marker is structure because of where it is, not because of how it
    starts.** Every previous form asked `line.startswith(CONFLICT_BEGIN)`, so a
    line of *content* beginning `<<<<<<< ` was read as structure, skipped, and
    the block judged to hold nothing but count lines — then deleted at exit 0
    under "Safe to stage", which is the sentence this whole change exists to
    make true.

    The separator was already matched by equality; that is the fix this file is
    named after. It was never carried to the other three markers. And the same
    reasoning was written one function over in the same commit —
    `resolve_append_only` refuses a begin marker seen inside an open block
    precisely because it is *content, not structure* — so the argument existed,
    correct, in this file, and did not reach here.

    Review's generalisation, which is the reason this is a separate function:
    **a predicate built on a classifier inherits every place the classifier is
    wrong**, and `is_conflict_marker` is shared by three call sites needing
    three different answers. `resolve_append_only` asks "is this structure
    here?", `is_conflict_marker` asks "could this be a marker anywhere?" — a
    deliberately broad question, because it guards staging and a false positive
    there is safe — and this asks "is this something I would be deleting?".
    One function answering all three is why the third was wrong.

    Position is unambiguous for a block matched by the collapse regex: the
    begin marker is the first line and the end marker the last. The separator
    is the first line equal to `=======`; a second one is content. Base
    markers cannot reach here — `resolve_backlog` refuses on any `|||||||` in
    the file before the collapse runs.
    """
    lines = block.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if not lines:
        return []
    last = len(lines) - 1
    content: list[str] = []
    seen_separator = False
    for index, line in enumerate(lines):
        if index in (0, last):
            continue
        if not seen_separator and line == CONFLICT_SEPARATOR:
            seen_separator = True
            continue
        content.append(line)
    return content


def _has_content(block: str) -> bool:
    """True when a conflict block holds any non-blank content line."""
    return any(line.strip() for line in _block_content_lines(block))


def _is_only_count_lines(block: str) -> bool:
    """True when a conflict block holds at least one count line and nothing else.

    Two conditions, and the fourth iteration of this defect was the second one
    missing. The predicate that licenses deleting a block is not "contains the
    thing I can regenerate" but "contains *nothing else*" — and **that alone is
    vacuously true of an empty block.**

    Review found that with real `git merge` output, not a constructed case: two
    lanes deleting the same paragraph and leaving a different number of
    trailing blank lines produces a conflict whose entire content is blank.
    The old form skipped the markers, skipped the blanks, and returned True
    having never seen a count line. The header was then injected where one
    already existed outside, and the script refused with a message saying both
    sides' headers had survived — which was false, because this function had
    just manufactured the second one.

    The general shape, in the reviewer's words: **the predicate that licenses
    the deletion and the predicate the repair depends on are two different
    predicates, written in two places, and they disagree at the edges.** So
    this one now answers exactly the question the repair asks — *was a count
    line here* — rather than a question that merely correlates with it.

    A note-only conflict returns False deliberately: the recount parenthetical
    is accumulated incident history and merging it by hand is the correct
    outcome rather than a cost. Review built the canonical two-lane case and
    confirmed the alternative was not a working resolution but a **corrupted
    document that passed every check the script had** — a regenerated note
    closing at one line and the orphaned tail of the original resuming
    mid-sentence at the next, exit 0, "Safe to stage".
    """
    saw_count = False
    for line in _block_content_lines(block):
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADER_COUNT.fullmatch(stripped):
            saw_count = True
            continue
        return False
    return saw_count


# Binary content is skipped without comment. Reporting a committed PDF as "not
# scanned" on every run is how the report gets deleted — a guard that cries wolf
# is the one the next person loosens. Decided by a NUL byte in the first 8 KiB
# rather than by a suffix list: review pointed out that a hardcoded set is an
# allowlist by omission, and `.webp`, `.ttf`, `.mp4`, `.wasm` and `.so` were all
# plausible here and all absent from mine. A sniff has nothing to maintain and
# cannot go stale when someone commits a new format.
def _looks_binary(path: pathlib.Path) -> bool:
    try:
        return b"\x00" in path.read_bytes()[:8192]
    except OSError:
        return False


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
    # `newline="\n"`, and it is load-bearing rather than tidiness. Without it,
    # Python's text mode translates every `\n` to `\r\n` on Windows, so running
    # this tool rewrites all 28,596 lines of `docs/handoff.md`. `core.autocrlf`
    # does **not** save you: measured on 2026-08-27, the staged blob kept its
    # CRLF while `origin/main` was LF, and `git diff --numstat` reported the
    # entire append-only log as changed. That reads exactly like the
    # catastrophic append-only breach every check here exists to detect, and it
    # is produced by the tool the lanes are told to run.
    path.write_text("\n".join(out), encoding="utf-8", newline="\n")


def resolve_backlog(path: pathlib.Path) -> None:
    """Drop the conflicted note block, then recompute the header from the file."""
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    had_conflict = CONFLICT_BEGIN in text
    slugs_before = set(re.findall(r"^### `([^`]+)`", text, re.M))

    # Refuse diff3/zdiff3 here, by name, before the slug comparison. Otherwise
    # a heading present only in the `|||||||` base section — meaning both lanes
    # deleted it, so removing it is the *correct* resolution — is counted in
    # `slugs_before` and reported as a loss. The refusal was right and the
    # reason was false, which sends the operator to diff a slug set against
    # main for an item that is legitimately gone.
    if CONFLICT_BASE in text:
        sys.exit(
            f"{path}: this file was conflicted with diff3/zdiff3 markers "
            "(`|||||||`). This script resolves the two-sided form only. Note "
            "that a heading appearing solely in the base section means both "
            "sides deleted it, which is not a loss - resolve by hand."
        )

    # Collapse a conflicted block **only when its entire content is the count
    # line** — nothing else. Three iterations of one defect got us here, and
    # the distinction that ends it is a reviewer's:
    #
    #   "This block contains the thing I know how to regenerate" is not the
    #   same predicate as "this block contains nothing else", and only the
    #   second one licenses deleting it.
    #
    # v1 collapsed every block, both sides, and silently deleted three items a
    # lane had merged minutes earlier. v2 exempted blocks containing `### `,
    # which still ate an item's `**Depends on:**` edges — worse, because
    # `AGENTS.md` defines a task as ready when every dependency is done, so a
    # deleted edge makes a blocked item look **ready**. v3 anchored to blocks
    # *containing* a count line, which still ate the intro sentence: in the
    # real file that sentence is line 3 and the count is line 5, so one
    # ordinary hunk covers both.
    #
    # Each iteration narrowed which blocks may collapse and never changed how
    # much of the block is deleted — still all of it, both sides. So the
    # predicate is now about the whole content, and everything else refuses.
    # A refusal is strictly better than a silent deletion: the operator keeps
    # both sides' prose and merges the accumulated incident notes by hand,
    # which is what those notes are for.
    def _collapse(match: re.Match[str]) -> str:
        block = match.group(0)
        if _is_only_count_lines(block):
            return "__NOTE__\n"
        excerpt = "\n".join(block.strip().split("\n")[:8])
        if not _has_content(block):
            sys.exit(
                f"{path}: a conflict block containing no content at all - a "
                "whitespace-only conflict, which two lanes deleting the same "
                "paragraph will produce. There is no header here to "
                "regenerate, so collapsing it would inject one the file does "
                "not need. Resolve by hand; keeping either side is correct.\n"
                f"\n{excerpt}"
            )
        sys.exit(
            f"{path}: this conflict block holds more than the header count "
            "line, and this script only knows how to regenerate that. "
            "Collapsing it would delete both sides of everything else. "
            "Resolve by hand, keep both sides' content, then re-run.\n\n"
            "Note that a body conflict can delete a '**Depends on:**' edge "
            "without changing any heading, marker or total, so no other check "
            f"here can see it.\n\n{excerpt}"
        )

    text = re.sub(r"<<<<<<< HEAD\n.*?>>>>>>> [^\n]*\n", _collapse, text, flags=re.DOTALL)

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
        line for line in lines if re.match(r"^- \[[ x]\] \*\*(done|pending|blocked)\*\*", line)
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
        # **The integers that used to be interpolated here are gone, and their
        # absence is the point.** This note read
        # "{len(headings)} `###` headings and {len(markers)} markers, 1:1", which
        # is a second copy of the count, in prose, in the file whose entire
        # header discipline is that a second copy is stale on arrival.
        # `backlog_graph.py` checks only the header *line*, so the prose copy was
        # the one nothing guarded.
        #
        # The `demo-one-command` lane deleted exactly this restatement from
        # `docs/backlog.md` on 2026-08-23 and wrote down why — "the property is
        # worth stating and the integers were not". **It fixed the artefact and
        # not the generator**, so this function put them straight back on the
        # next conflict, which is what happened on 2026-08-27 and is how this was
        # found. AGENTS.md: "Do not restate that count here or anywhere else."
        #
        # The property is still stated. Only the numbers are gone, and the
        # 1:1 correspondence they claimed is *enforced* twelve lines above by the
        # `sys.exit` on `len(headings) != len(markers)` — which is a check rather
        # than a sentence, and cannot go stale.
        note = (
            "(Recomputed from the status markers in this finished file, never\n"
            "reconciled from two headers; the `###` headings and the status markers\n"
            "correspond 1:1, with no duplicate item names. Neither side of a\n"
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

    text = re.sub(
        r"^\*\*\d+ done - \d+ blocked - \d+ pending - \d+ total\*\*$",
        header,
        text,
        count=1,
        flags=re.MULTILINE,
    )

    # Assert the presence we expect rather than the absence of what we fear:
    # exactly one header line, in the file we are about to write. Counting the
    # finished text rather than trusting the substitution's return value,
    # because the substitution reports how many lines it *replaced* and the
    # question is how many exist — those differ precisely in the case that
    # caused this, where it replaced none and the note had carried one in.
    #
    # **Do not simplify this away on the grounds that the block predicates
    # already refuse.** They cannot see one case and this is what covers it: a
    # line of content beginning `>>>>>>> ` terminates the collapse regex early,
    # so the block is truncated *before* `_block_content_lines` is ever called
    # and no amount of position-classification reaches it. Review demonstrated
    # the path — the truncated block collapses, the note injects a header, one
    # already exists outside, and this refuses seven lines before the write.
    # `>>>>>>> ` as content is the one marker position cannot classify.
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
            f"found {written}. Refusing to write.\n\n"
            "This counts the lines that exist; it does not know which "
            "mechanism produced them, so it names the possibilities rather "
            "than asserting one - an earlier version asserted 'both sides' "
            "headers survived' for a second header this script had itself "
            "injected one line earlier, and sent the operator looking for a "
            "duplicate that the merge never contained.\n\n"
            "Two can mean both sides' headers survived a block the collapse "
            "regex did not match - a stash-style `<<<<<<< Updated upstream` "
            "label, for instance, since the regex is anchored on HEAD. Zero "
            "can mean the header was collapsed and not restored. Read the "
            "file rather than trusting either reading of this number."
        )

    # `newline="\n"`: see the note on the conflict-stripping write above. This
    # one rewrites `docs/backlog.md`, whose header is derived and recomputed on
    # nearly every branch, so it is the more frequently executed of the two.
    path.write_text(text, encoding="utf-8", newline="\n")
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
        if _looks_binary(path):
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
            "first), then refuses to let you stage if any conflict marker\n"
            "survives anywhere in the tree.\n"
            "\n"
            "For docs/backlog.md it resolves ONE narrow case: a conflict whose\n"
            "entire content is the header count line. Anything else refuses,\n"
            "including a conflict on the recount note, and including one hunk\n"
            "covering the count line together with the prose above it - which\n"
            "is the ordinary two-lane shape, because those lines sit two apart.\n"
            "\n"
            "A refusal there is the expected outcome and not a malfunction.\n"
            "Earlier versions collapsed those blocks and deleted both sides at\n"
            "exit 0: three merged items once, an item's '**Depends on:**' edges\n"
            "another time - which makes a blocked item look ready - and the\n"
            "file's own intro sentence a third. Keep both sides by hand and\n"
            "re-run; the accumulated notes are why the file is worth merging.\n"
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
            "content rather than an unresolved merge - check the line itself."
        )
        return 1

    entries = sum(
        1
        for line in (REPO_ROOT / "docs/handoff.md").read_text(encoding="utf-8").split("\n")
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
