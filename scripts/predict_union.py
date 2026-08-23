"""Predict the union of dated `docs/handoff.md` entries before resolving a conflict.

**Why a prediction rather than a second count.** Two methods agreeing cannot
exclude the case where both are wrong in the same direction, and this project
has hit exactly that: on 2026-08-21 one lane measured `main` at 39/71/111 and
its own branch at 40/69/110 when the truth was 40/71/112, so no reconciliation
of the two could have reached the answer. A value derived *before* the merge,
from the base and the two sides, is a third fact rather than a third opinion —
it comes from the arithmetic of the merge itself, not from reading the result.

    union = base + (ours - base) + (theirs - base)

Run it **before** `git rebase`, while the three commits are still separately
addressable, then compare its answer to what `scripts/resolve_doc_conflicts.py`
reports and to an independent count of the resolved file. Three values, of
which the first was computed from different facts than the other two.

    python scripts/predict_union.py <base> <ours> <theirs>
    python scripts/predict_union.py "$(git merge-base HEAD origin/main)" HEAD origin/main

**What it assumes, and what it cannot see.** It assumes each side only
*appended* entries, which is what `docs/handoff.md`'s append-only rule requires.
If a side edited or deleted an existing entry the arithmetic is wrong, and
wrong quietly — so the prediction is necessary and not sufficient. Pair it with

    git diff --numstat origin/main -- docs/handoff.md

and require the removed-lines column to be zero. **A correct entry count
survives an entry being swapped rather than dropped**; only the numstat sees
that. The two checks answer different questions and neither substitutes.

It also counts headings by pattern, so it inherits the usual hazard: a heading
that does not match is indistinguishable from an absent one. The pattern here
is deliberately anchored on the ISO date rather than on any prose, because
prose varies — one entry's `—` em-dash separator silently failed a narrower
grep during the audit lane's rebase and was briefly reported as a lost entry.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

#: Anchored on `## YYYY-MM-DD` only. Everything after the date is prose and
#: varies between lanes — separators, agent names, em-dashes versus hyphens.
DATED_ENTRY = re.compile(r"^## \d{4}-\d{2}-\d{2}", re.MULTILINE)

HANDOFF = "docs/handoff.md"


def count_entries(ref: str, *, path: str = HANDOFF) -> int:
    """Count dated entries in ``path`` as of ``ref``.

    Reads the blob out of git rather than the working tree, so all three sides
    can be counted from one checkout and none of them needs to exist on disk.
    ``encoding="utf-8"`` is explicit: this file is UTF-8 and Windows defaults
    to cp1252, which fails here with a `UnicodeDecodeError` that surfaces
    several statements later as an unrelated `TypeError`.
    """
    completed = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True,
        check=True,
    )
    return len(DATED_ENTRY.findall(completed.stdout.decode("utf-8")))


def predict(base: int, ours: int, theirs: int) -> int:
    """The union implied by the merge, assuming both sides only appended."""
    return base + (ours - base) + (theirs - base)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", help="merge base, e.g. $(git merge-base HEAD origin/main)")
    parser.add_argument("ours", help="your side, usually HEAD")
    parser.add_argument("theirs", help="the other side, usually origin/main")
    parser.add_argument("--path", default=HANDOFF, help=f"file to count (default: {HANDOFF})")
    args = parser.parse_args(argv)

    try:
        base = count_entries(args.base, path=args.path)
        ours = count_entries(args.ours, path=args.path)
        theirs = count_entries(args.theirs, path=args.path)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        print(f"could not read {args.path} at one of the three refs: {stderr}", file=sys.stderr)
        return 2

    if base == 0:
        # A zero base means the pattern matched nothing, not that the file is
        # empty — the same "a search that misses looks like an absence" hazard
        # the docstring describes. Refuse rather than predicting from it.
        print(
            f"no dated entries matched in {args.path} at {args.base}. "
            f"The pattern found nothing, which is not the same as there being "
            f"nothing; check the heading format before trusting any count.",
            file=sys.stderr,
        )
        return 2

    union = predict(base, ours, theirs)
    print(f"base   ({args.base}): {base}")
    print(f"ours   ({args.ours}): {ours}   ({ours - base:+d})")
    print(f"theirs ({args.theirs}): {theirs}   ({theirs - base:+d})")
    print()
    print(f"PREDICTED UNION = {base} + {ours - base} + {theirs - base} = {union}")
    print()
    print("Now resolve, then check BOTH:")
    print(f"  - the resolved file counts {union} dated entries")
    print("  - `git diff --numstat <theirs> -- " + args.path + "` removes 0 lines")
    print("The first cannot see a dropped entry that was replaced; the second can.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
