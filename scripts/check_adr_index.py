#!/usr/bin/env python3
"""`docs/decisions/README.md`'s index must not drift from the files it indexes.

Runs in CI and is runnable locally:

    python scripts/check_adr_index.py

`docs/decisions/README.md` carries a hand-maintained Markdown table, one row
per ADR. `README.md` was found missing rows for ADR-013 and ADR-014 on
2026-08-21 — added by hand later, by different lanes, on different days,
because nothing had ever compared the table against the directory. Two indexes
over the same directory drift independently and neither had a test:
`PLAIN-ENGLISH.md` is the other one, and it declares itself frozen at ADR-009
in its own header rather than being extended — a decision recorded in the file
itself, not something this script adjudicates.

**Both directions are asserted, because only one is visible to a human reading
the table.**

1. Every `docs/decisions/ADR-0NN-*.md` file has a row in the README index.
   Missing this is what happened on 2026-08-21: a reader scanning the table
   sees a plausible, complete-looking list and has no way to notice an entry
   that was never added.
2. Every index row's relative link resolves to a file that exists. A renamed
   or deleted ADR file leaves a row whose title reads exactly as it always
   did — the break is only visible if the link is actually clicked, which is
   how ADR-015's row was verified: by a reviewer resolving the link, not by
   its author reading the table.

**What this does not check.** It reads the `## Index` table only, not the
"Amendments awaiting acceptance" table further down the same file, which
uses the identical `| [NNN](...)` row shape for a different claim (an
amendment's own status, not the ADR's index entry). It does not check
`PLAIN-ENGLISH.md` at all: that document is prose, not a table, and states
its own scope ("covers ADR-001 through ADR-009 ... not extended for later
decisions") in its header, which is the "say so in the file" this item asks
for when a document is deliberately out of scope. It does not check whether
an ADR's *content* is current, only whether the index can find it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DECISIONS_DIR = REPO / "docs" / "decisions"
README_NAME = "README.md"

#: `ADR-013-forward-schedule-completeness.md`, not `README.md` or
#: `PLAIN-ENGLISH.md` themselves.
ADR_FILE_RE = re.compile(r"^ADR-\d{3}-.+\.md$")

#: `| [013](ADR-013-forward-schedule-completeness.md) | Title | Status | Summary |`.
#: Anchored at the line start and requiring the leading `| [`, so prose
#: elsewhere in the file that happens to contain a Markdown link is not
#: mistaken for a table row.
INDEX_ROW_RE = re.compile(r"^\| \[(\d+)\]\(([^)]+)\)\s*\|")


def _index_rows(readme_text: str) -> list[tuple[int, str, str]]:
    """``(line_no, number, link_target)`` for every row of the ``## Index`` table.

    Deliberately scoped to that one section. The "Amendments awaiting
    acceptance" table lower in the same file reuses the exact same
    ``| [NNN](...)`` shape, and a broken link there is a different claim from
    the one this item asks for — conflating the two would fail the build for
    a defect this item was never filed to find.
    """
    lines = readme_text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## Index")
    except StopIteration:
        return []

    rows: list[tuple[int, str, str]] = []
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("## "):
            break
        match = INDEX_ROW_RE.match(line)
        if match:
            rows.append((index + 1, match.group(1), match.group(2)))
    return rows


def find_defects(decisions_dir: Path = DECISIONS_DIR) -> list[str]:
    """Every way the index and the directory disagree.

    Returns an empty list only when both directions hold. A `README.md` that
    cannot be read, or that has no `## Index` table at all, is reported as a
    defect rather than silently skipped — a check that finds nothing here has
    not established that there is nothing wrong.
    """
    readme_path = decisions_dir / README_NAME
    if not readme_path.is_file():
        return [f"{readme_path}: not found"]

    text = readme_path.read_text(encoding="utf-8")
    rows = _index_rows(text)
    if not rows:
        return [
            f"no rows found under a '## Index' heading in {readme_path}; either the "
            "heading was renamed or the table's row format changed, and a check that "
            "matches nothing must not report the index consistent"
        ]

    if not decisions_dir.is_dir():
        return [f"{decisions_dir}: not a directory"]

    adr_files = sorted(
        path.name
        for path in decisions_dir.iterdir()
        if path.is_file() and ADR_FILE_RE.match(path.name)
    )
    if not adr_files:
        return [f"no ADR-0NN-*.md files found in {decisions_dir}; the check would be vacuous"]

    problems: list[str] = []

    linked_targets = {link for _, _, link in rows}
    for name in adr_files:
        if name not in linked_targets:
            problems.append(
                f"{name}: no row in the '## Index' table links to it "
                "(direction 1: every ADR file needs an index row)"
            )

    for line_no, number, link in rows:
        if not (decisions_dir / link).is_file():
            problems.append(
                f"README.md:{line_no}: index row {number} links to '{link}', which does "
                "not resolve to a file in docs/decisions/ "
                "(direction 2: every index row's link must resolve)"
            )

    return problems


def main() -> int:
    problems = find_defects()
    if problems:
        print(
            "docs/decisions/README.md's '## Index' table disagrees with the files on disk:",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(file=sys.stderr)
        print(
            "Fix: add the missing row, or correct the relative link. Do not delete "
            "the ADR file or the row instead - that turns this green by erasing the "
            "thing it exists to notice.",
            file=sys.stderr,
        )
        return 1

    print(
        f"{README_NAME}: every ADR-0NN-*.md file has an index row, and every index "
        "row's link resolves to a file that exists."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
