"""Compare the backlog's `### ` slug sets across a rebase.

**This exists because a recount cannot see a dropped item.** A recount of the
finished file agrees with itself perfectly after a deletion: remove three
entries and recount, and the header matches the items that remain. That is
exactly what happened on 2026-08-21, when `scripts/resolve_doc_conflicts.py`
silently dropped `projections-import-cli`,
`projection-import-process-concurrency` and `projections-seed` while resolving
a conflict, printed a recomputed header, and exited successfully.

So the two checks see different failures and neither substitutes for the other:

- `scripts/backlog_graph.py` fails when the header disagrees with the items it
  parses. It cannot detect a dropped item.
- This script fails when the merged file is not exactly the union of both
  lanes' items. It says nothing about the header.

Run both after resolving a `docs/backlog.md` conflict.

Compare against **your own merge base**, not against `origin/main`. Against
`origin/main` this reports another lane's merges as your deletions the moment
your base has moved. The two agree exactly when run immediately after a rebase,
because at that instant they are the same commit -- which is why using
`origin/main` appears to work right up until it does not.

Usage:
    python scripts/slugcheck.py <merge-base> <your-branch> <origin/main>

Exits 0 when the working tree's `docs/backlog.md` holds exactly the expected
union, 1 otherwise.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

BACKLOG = "docs/backlog.md"
SLUG = re.compile(r"^### `([^`]+)`")


def slugs_from_text(text: str) -> set[str]:
    """Every `### `slug`` heading in the file, which is what an item *is*."""
    return {match.group(1) for line in text.splitlines() if (match := SLUG.match(line))}


def slugs_at(ref: str) -> set[str]:
    completed = subprocess.run(
        ["git", "show", f"{ref}:{BACKLOG}"],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    )
    return slugs_from_text(completed.stdout)


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        print("error: expected exactly three refs")
        return 2

    base_ref, mine_ref, main_ref = argv[1], argv[2], argv[3]
    base = slugs_at(base_ref)
    mine = slugs_at(mine_ref)
    theirs = slugs_at(main_ref)
    merged = slugs_from_text(Path(BACKLOG).read_text(encoding="utf-8"))

    added_by_me = mine - base
    added_by_them = theirs - base
    dropped_by_me = base - mine
    dropped_by_them = base - theirs
    expected = (base | added_by_me | added_by_them) - dropped_by_me - dropped_by_them

    print(f"merge base  {base_ref}: {len(base)} items")
    print(
        f"your branch {mine_ref}: {len(mine)} items, "
        f"added {sorted(added_by_me)}, dropped {sorted(dropped_by_me)}"
    )
    print(
        f"their main  {main_ref}: {len(theirs)} items, "
        f"added {sorted(added_by_them)}, dropped {sorted(dropped_by_them)}"
    )
    print(f"merged working tree: {len(merged)} items")

    missing = expected - merged
    unexpected = merged - expected
    if missing or unexpected:
        print(
            f"MISMATCH - missing from the merged file: {sorted(missing)}; "
            f"unexpected in the merged file: {sorted(unexpected)}"
        )
        print(
            "A resolution must not add or lose an item. Re-resolve from both "
            "sides rather than editing the count to agree."
        )
        return 1

    print("OK - the merged slug set is exactly the union of both lanes, nothing dropped")
    print(
        "That is a narrow claim: it says nothing about whether the header is "
        "right. Run scripts/backlog_graph.py for that."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
