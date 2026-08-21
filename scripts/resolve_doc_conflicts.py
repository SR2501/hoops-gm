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

MARKERS = ("<<<<<<<", "=======", ">>>>>>>")
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
        if line.startswith("<<<<<<<"):
            mode = "ours"
            continue
        if line.startswith("=======") and mode == "ours":
            mode = "theirs"
            continue
        if line.startswith(">>>>>>>") and mode == "theirs":
            out.extend(ours)
            out.extend(theirs)
            ours, theirs = [], []
            mode = "normal"
            continue
        if mode == "ours":
            ours.append(line)
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
    had_conflict = "<<<<<<<" in text
    text = re.sub(r"<<<<<<< HEAD\n.*?>>>>>>> [^\n]*\n", "__NOTE__\n", text, flags=re.DOTALL)
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
    if had_conflict:
        note = (
            "(Recomputed from the status markers in this finished file, never\n"
            f"reconciled from two headers: {len(headings)} `###` headings and\n"
            f"{len(markers)} markers, 1:1, no duplicate item names. Neither side of a\n"
            "rebase conflict is a usable input here, because each was computed before\n"
            "the other lane's items landed.)"
        )
        text = text.replace("__NOTE__", note)
    header = (
        f"**{counts['done']} done - {counts['blocked']} blocked - "
        f"{counts['pending']} pending - {total} total**"
    )
    text = re.sub(
        r"^\*\*\d+ done - \d+ blocked - \d+ pending - \d+ total\*\*$",
        header,
        text,
        count=1,
        flags=re.MULTILINE,
    )
    path.write_text(text, encoding="utf-8")
    print(f"  backlog header recomputed: {header}")


def surviving_markers() -> list[str]:
    """Every conflict marker left anywhere in the tree."""
    found: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or SKIP_DIRS & set(path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.split("\n"), 1):
            if line.startswith(MARKERS):
                found.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line[:40]}")
    return found


def main() -> int:
    resolve_append_only(REPO_ROOT / "docs/handoff.md")
    resolve_backlog(REPO_ROOT / "docs/backlog.md")

    # Verify BEFORE the caller stages anything. This is the entire point.
    survivors = surviving_markers()
    if survivors:
        print("CONFLICT MARKERS SURVIVE - do not stage:")
        for line in survivors[:20]:
            print("   ", line)
        return 1

    entries = sum(
        1
        for line in (REPO_ROOT / "docs/handoff.md")
        .read_text(encoding="utf-8")
        .split("\n")
        if re.match(r"^## \d{4}-\d{2}-\d{2}", line)
    )
    print(f"  handoff dated entries: {entries}")
    print("VERIFIED: no conflict marker in any text file. Safe to stage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
