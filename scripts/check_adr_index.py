#!/usr/bin/env python3
"""Check that the decision log's authoritative index and ADR files agree.

Runs locally with no third-party dependencies:

    python scripts/check_adr_index.py

``docs/decisions/README.md`` is the authoritative index. This checks both
directions of the relationship:

1. every ``ADR-NNN-*.md`` file in the directory is linked from the README's
   ``## Index`` table;
2. every row parsed from that table has a relative link whose target exists.

The second direction catches a rename that leaves a plausible-looking broken
link. The first catches the historical defect: ADR files existed while their
rows were absent.

``PLAIN-ENGLISH.md`` is deliberately out of scope. Its own opening notice says
it is a frozen historical walkthrough of ADR-001 through ADR-009, not a second
current index. Requiring one section per ADR would turn that deliberate scope
into a false completeness claim.

What this does not cover: displayed ADR numbers, titles, statuses, summaries,
or links elsewhere in the README. It parses the current first-cell inline-link
table convention; changing that convention fails as an empty or malformed
index rather than silently passing.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DECISIONS = REPO_ROOT / "docs" / "decisions"
INDEX_HEADING = "## Index"
ADR_GLOB = "ADR-[0-9][0-9][0-9]-*.md"
INDEX_ROW_RE = re.compile(r"^\|\s*\[(?P<number>\d{3})\]\((?P<link>[^)]+)\)\s*\|")


@dataclass(frozen=True)
class IndexRow:
    """One ADR row in the README index."""

    number: str
    link: str
    line: int


@dataclass(frozen=True)
class Defect:
    """One disagreement between the directory and its index."""

    kind: str
    message: str
    line: int | None = None

    def render(self) -> str:
        where = f"line {self.line}: " if self.line is not None else ""
        return f"[{self.kind}] {where}{self.message}"


def parse_index(text: str) -> tuple[list[IndexRow], list[Defect]]:
    """Parse only the README's ``## Index`` section."""
    lines = text.splitlines()
    headings = [index for index, line in enumerate(lines) if line == INDEX_HEADING]
    if not headings:
        return [], [Defect("missing-index", f"{INDEX_HEADING!r} heading not found")]
    if len(headings) > 1:
        return [], [
            Defect(
                "duplicate-index",
                f"{len(headings)} {INDEX_HEADING!r} headings found; the authoritative "
                "table is ambiguous",
                headings[0] + 1,
            )
        ]

    start = headings[0] + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    rows: list[IndexRow] = []
    defects: list[Defect] = []
    for index in range(start, end):
        line = lines[index]
        match = INDEX_ROW_RE.match(line)
        if match:
            rows.append(
                IndexRow(
                    number=match.group("number"),
                    link=match.group("link"),
                    line=index + 1,
                )
            )
        elif line.lstrip().startswith("| ["):
            defects.append(
                Defect(
                    "malformed-index-row",
                    "index data row is not a first-cell inline link of the form "
                    "'| [NNN](ADR-NNN-title.md) | ... |'",
                    index + 1,
                )
            )

    if not rows:
        defects.append(
            Defect(
                "empty-index",
                f"no ADR rows parsed below {INDEX_HEADING!r}; a check over zero rows is vacuous",
                headings[0] + 1,
            )
        )
    return rows, defects


def _relative_target(readme: Path, row: IndexRow) -> tuple[Path | None, Defect | None]:
    parsed = urlsplit(row.link)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None, Defect(
            "non-relative-index-link",
            f"ADR {row.number} uses non-relative link {row.link!r}",
            row.line,
        )

    relative = Path(unquote(parsed.path))
    if relative.is_absolute():
        return None, Defect(
            "non-relative-index-link",
            f"ADR {row.number} uses absolute link {row.link!r}",
            row.line,
        )
    return (readme.parent / relative).resolve(), None


def check_index(
    decisions: Path = DEFAULT_DECISIONS,
) -> tuple[list[IndexRow], list[Path], list[Defect]]:
    """Return parsed rows, discovered ADR files, and consistency defects."""
    if not decisions.is_dir():
        return [], [], [Defect("missing-decisions-directory", f"{decisions} does not exist")]

    readme = decisions / "README.md"
    if not readme.is_file():
        return [], [], [Defect("missing-readme", f"{readme} does not exist")]

    files = sorted(decisions.glob(ADR_GLOB))
    if not files:
        return (
            [],
            [],
            [
                Defect(
                    "no-adr-files",
                    f"no files matched {ADR_GLOB!r} in {decisions}; coverage would be vacuous",
                )
            ],
        )

    rows, defects = parse_index(readme.read_text(encoding="utf-8"))
    indexed_targets: list[Path] = []
    for row in rows:
        target, defect = _relative_target(readme, row)
        if defect is not None:
            defects.append(defect)
            continue
        assert target is not None
        indexed_targets.append(target)
        if not target.is_file():
            defects.append(
                Defect(
                    "broken-index-link",
                    f"ADR {row.number} links to {row.link!r}, which resolves to no file",
                    row.line,
                )
            )

    indexed = set(indexed_targets)
    for path in files:
        if path.resolve() not in indexed:
            defects.append(
                Defect(
                    "unindexed-adr",
                    f"{path.name} exists but has no row in the README index",
                )
            )

    for target, count in Counter(indexed_targets).items():
        if count > 1:
            defects.append(
                Defect(
                    "duplicate-index-target",
                    f"{target.name} is linked by {count} index rows",
                )
            )

    return rows, files, defects


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) > 1:
        print("usage: check_adr_index.py [DECISIONS_DIRECTORY]", file=sys.stderr)
        return 2
    decisions = Path(args[0]) if args else DEFAULT_DECISIONS

    rows, files, defects = check_index(decisions)
    if defects:
        for defect in defects:
            print(defect.render(), file=sys.stderr)
        print(
            f"FAILED: {len(defects)} ADR index defect(s); "
            f"discovered {len(files)} files and parsed {len(rows)} rows.",
            file=sys.stderr,
        )
        return 1

    print(
        f"{decisions}: {len(files)} ADR files, {len(rows)} README index rows; "
        "both directions agree."
    )
    print(
        "PLAIN-ENGLISH.md is not checked: it declares itself a frozen ADR-001 through "
        "ADR-009 walkthrough."
    )
    print("Titles, statuses, summaries, and displayed ADR numbers are outside this check.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
