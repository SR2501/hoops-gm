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
union, 1 for a genuine content mismatch, and 2 when the comparison itself is
not trustworthy (bad refs, wrong merge base, empty input, or slug collisions).
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

BACKLOG = "docs/backlog.md"
SLUG = re.compile(r"^### `([^`]+)`")
OPERATIONAL_ERROR = 2


def slugs_from_text(text: str) -> list[str]:
    """Every `### `slug`` heading, retaining cardinality for collision checks."""
    return [match.group(1) for line in text.splitlines() if (match := SLUG.match(line))]


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def repo_root() -> Path:
    """Resolve the repository independently of the caller's working directory."""
    script_dir = Path(__file__).resolve().parent
    return Path(_git(script_dir, "rev-parse", "--show-toplevel"))


def slugs_at(repo: Path, ref: str) -> list[str]:
    return slugs_from_text(_git(repo, "show", f"{ref}:{BACKLOG}"))


def _validated_slug_set(slugs: list[str], label: str) -> set[str]:
    if not slugs:
        raise ValueError(f"{label} parsed zero backlog items")

    duplicates = sorted(slug for slug, count in Counter(slugs).items() if count > 1)
    if duplicates:
        raise ValueError(f"{label} contains duplicate slug headings: {duplicates}")
    return set(slugs)


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        print("error: expected exactly three refs", file=sys.stderr)
        return OPERATIONAL_ERROR

    base_ref, mine_ref, main_ref = argv[1], argv[2], argv[3]
    try:
        repo = repo_root()
        computed_base = _git(repo, "merge-base", mine_ref, main_ref)
        claimed_base = _git(repo, "rev-parse", f"{base_ref}^{{commit}}")
        if claimed_base != computed_base:
            raise ValueError(
                f"{base_ref} resolves to {claimed_base}, which is not the merge base "
                f"of {mine_ref} and {main_ref}; expected {computed_base}"
            )

        base = _validated_slug_set(slugs_at(repo, base_ref), f"merge base {base_ref}")
        mine = _validated_slug_set(slugs_at(repo, mine_ref), f"your branch {mine_ref}")
        theirs = _validated_slug_set(slugs_at(repo, main_ref), f"their main {main_ref}")
        merged = _validated_slug_set(
            slugs_from_text((repo / BACKLOG).read_text(encoding="utf-8")),
            "merged working tree",
        )
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            detail = exc.stderr.strip() or str(exc)
        else:
            detail = str(exc)
        print(f"operational error: {detail}", file=sys.stderr)
        return OPERATIONAL_ERROR

    added_by_me = mine - base
    added_by_them = theirs - base
    dropped_by_me = base - mine
    dropped_by_them = base - theirs
    collisions = sorted(added_by_me & added_by_them)
    if collisions:
        print(
            "operational error: slugs independently added by both branches: "
            f"{collisions}. Compare the item bodies and assign distinct slugs before "
            "resolving.",
            file=sys.stderr,
        )
        return OPERATIONAL_ERROR

    # Never let one branch's deletion erase an item the other branch preserved.
    # A deliberate deletion must be made explicitly on both inputs before this
    # union changes; subtracting either branch's drops recreated the loss this
    # tool exists to catch.
    expected = mine | theirs

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
