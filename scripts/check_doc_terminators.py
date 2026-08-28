"""`docs/handoff.md` must end with a newline, and the reason is not tidiness.

**The file's own entry count silently undercounts without it.**
`scripts/predict_union.py` finds dated entries with `^## \\d{4}-\\d{2}-\\d{2}`,
anchored at a line start. Append to a file that does not end with a newline and
the new heading is welded onto the last line:

    b'...reviewer and I have SQLite only.## 2026-08-26 - backend - ...'

The entry is **present in the file, invisible to the counter, and completely
normal in a diff.** Driven rather than argued, with a positive control on the
extractor first so the zero means something:

    terminated base   + naive append -> 1 heading found
    unterminated base + naive append -> 0 headings found

And `open(path, "a").write("## ...")` - the natural way to append - produces the
second. So the instrument used to verify that an append was append-only can
itself lose the entry it is verifying.

## Why this is a gate rather than a note

**This has now happened twice in one day.** The first occurrence was healed
incidentally by the next merge and filed as "self-heals, no repair needed",
which was true of the instance and false of the class - the second occurrence
arrived hours later on a different lane's merge. A check that fires on the
commit that breaks it costs one CI job; an instance fix costs a rediscovery
every time.

`docs/backlog.md` is checked too. Its header is derived and recomputed by
`scripts/resolve_doc_conflicts.py`, so the same welding hazard applies to the
tools that read it.

## What it cannot see

A terminator is not append-only. A file can end with a newline and have had an
entry rewritten, reordered or deleted - the byte-prefix check against the merge
base is what sees that, and this is not a substitute for it. It also says
nothing about a heading whose *date* is malformed, which is invisible to the
same pattern for a different reason.

    python scripts/check_doc_terminators.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Files whose readers anchor on a line start, so a missing terminator welds the
#: next append onto the last line. All three are append-heavy and all three are
#: read by a counting tool.
#:
#: `docs/governance/coordinator-register.md` was **added on 2026-08-28, after an
#: unterminated append to it passed this very check.** It had been omitted since
#: the file was written, and the omission is the same class of defect the check
#: exists to catch: the register is appended to by the same `## ` heading
#: convention as the handoff, is counted by the same `^## ` pattern, and is
#: larger than either of the other two. The gate's domain was narrower than the
#: hazard it was built for. See `c350`.
CHECKED = (
    "docs/handoff.md",
    "docs/backlog.md",
    "docs/governance/coordinator-register.md",
)


def unterminated(paths: tuple[str, ...] = CHECKED) -> list[str]:
    """Which of ``paths`` do not end with a newline.

    Reads bytes, not text: `read_text` with universal newlines would hide the
    distinction this exists to find.
    """
    missing = []
    for relative in paths:
        path = REPO / relative
        if not path.is_file():
            # A file that is gone is not a file that passes. The append-only
            # machinery is meaningless without it, so say so rather than skip.
            missing.append(f"{relative}: not found at {path}")
            continue
        data = path.read_bytes()
        if not data:
            missing.append(f"{relative}: empty")
        elif not data.endswith(b"\n"):
            missing.append(f"{relative}: does not end with a newline; last bytes {data[-30:]!r}")
    return missing


def main() -> int:
    problems = unterminated()
    if problems:
        print(
            "A dated-entry heading appended to these files would not start a line,", file=sys.stderr
        )
        print(
            "so predict_union.py would not count it and a diff would look normal:", file=sys.stderr
        )
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(file=sys.stderr)
        print("Fix: append a single newline to the end of the file.", file=sys.stderr)
        return 1

    for relative in CHECKED:
        print(f"{relative}: ends with a newline")
    print()
    print("A terminator is not append-only. This says the NEXT append will start a")
    print("line; it says nothing about whether a previous entry was rewritten.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
