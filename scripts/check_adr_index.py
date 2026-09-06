#!/usr/bin/env python3
"""Check the authoritative ADR index in both directions.

Runs in CI through ``backend/tests/test_adr_index.py`` and is runnable locally:

    python scripts/check_adr_index.py

The check establishes two narrow facts:

1. every ``docs/decisions/ADR-NNN-*.md`` file is linked from the ``## Index``
   table in ``docs/decisions/README.md``;
2. every ADR row in that table links to an ADR file that exists.

Both directions matter. The first catches a newly written ADR omitted from the
table. The second catches a stale link after a rename, which looks plausible in
rendered Markdown until somebody clicks it.

``PLAIN-ENGLISH.md`` is intentionally out of scope. It declares itself a frozen
historical walkthrough of ADR-001 through ADR-009, not a second authoritative
index. This check also does not compare titles, statuses, or summaries with ADR
bodies, validate ADR contents, require contiguous numbering, or inspect links
outside README's ``## Index`` section.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DECISIONS_DIR = REPO_ROOT / "docs" / "decisions"
INDEX_FILENAME = "README.md"

ADR_FILENAME_RE = re.compile(r"^ADR-\d{3}-.+\.md$")
INDEX_HEADING_RE = re.compile(r"^## +Index\s*$")
H2_RE = re.compile(r"^## ")
INDEX_ROW_RE = re.compile(r"^\|\s*\[(\d{3})\]\(([^)]+)\)\s*\|")
TABLE_HEADER_RE = re.compile(r"^\|\s*#\s*\|")
TABLE_SEPARATOR_RE = re.compile(r"^\|\s*:?-+")


@dataclass(frozen=True)
class IndexRow:
    """One ADR row in README's authoritative index."""

    number: str
    target: str
    line: int


@dataclass(frozen=True)
class Defect:
    """One inconsistency that makes the index untrustworthy."""

    kind: str
    message: str
    line: int | None = None

    def render(self) -> str:
        where = f"line {self.line}: " if self.line is not None else ""
        return f"[{self.kind}] {where}{self.message}"


def parse_index(text: str) -> tuple[list[IndexRow], list[Defect]]:
    """Parse ADR rows from the unique ``## Index`` section."""
    lines = text.splitlines()
    headings = [index for index, line in enumerate(lines) if INDEX_HEADING_RE.match(line)]
    if not headings:
        return [], [
            Defect(
                "missing-index-section",
                "README.md has no '## Index' section; a scan of no rows cannot pass",
            )
        ]
    if len(headings) > 1:
        return [], [
            Defect(
                "duplicate-index-section",
                f"README.md has {len(headings)} '## Index' sections; "
                "which one is authoritative is unanswerable",
                headings[0] + 1,
            )
        ]

    start = headings[0] + 1
    end = next(
        (index for index in range(start, len(lines)) if H2_RE.match(lines[index])),
        len(lines),
    )
    rows: list[IndexRow] = []
    defects: list[Defect] = []
    for index in range(start, end):
        line = lines[index]
        match = INDEX_ROW_RE.match(line)
        if match:
            rows.append(IndexRow(number=match.group(1), target=match.group(2), line=index + 1))
        elif (
            line.startswith("|")
            and not TABLE_HEADER_RE.match(line)
            and not TABLE_SEPARATOR_RE.match(line)
        ):
            defects.append(
                Defect(
                    "malformed-index-row",
                    f"{line!r} is a table row the parser cannot read; "
                    "expected the first cell to be '[NNN](relative-link)'",
                    index + 1,
                )
            )

    if not rows:
        defects.append(
            Defect(
                "no-index-rows",
                "README.md's '## Index' section contains no ADR rows; "
                "every bidirectional check would otherwise be vacuous",
                headings[0] + 1,
            )
        )
    return rows, defects


def find_defects(decisions_dir: Path = DEFAULT_DECISIONS_DIR) -> list[Defect]:
    """Compare ADR files with README index targets."""
    if not decisions_dir.is_dir():
        return [
            Defect(
                "missing-decisions-directory",
                f"decision directory does not exist: {decisions_dir}",
            )
        ]

    index_path = decisions_dir / INDEX_FILENAME
    if not index_path.is_file():
        return [Defect("missing-index", f"ADR index does not exist: {index_path}")]

    adr_files = {
        path.name
        for path in decisions_dir.iterdir()
        if path.is_file() and ADR_FILENAME_RE.fullmatch(path.name)
    }
    rows, defects = parse_index(index_path.read_text(encoding="utf-8"))
    if not adr_files:
        defects.append(
            Defect(
                "no-adr-files",
                f"no ADR-NNN-*.md files found in {decisions_dir}; "
                "a clean comparison over an empty directory proves nothing",
            )
        )

    all_relative_files = {
        path.relative_to(decisions_dir).as_posix()
        for path in decisions_dir.rglob("*")
        if path.is_file()
    }
    targets: list[str] = []
    for row in rows:
        target, target_defect = _resolve_target(row, all_relative_files)
        if target_defect is not None:
            defects.append(target_defect)
            continue
        assert target is not None
        targets.append(target)
        if target not in adr_files:
            defects.append(
                Defect(
                    "non-adr-index-target",
                    f"ADR-{row.number} links to {row.target!r}, which exists but is "
                    "not an ADR-NNN-*.md file",
                    row.line,
                )
            )

    for target, count in sorted(Counter(targets).items()):
        if count > 1:
            defects.append(
                Defect(
                    "duplicate-index-target",
                    f"{target!r} is linked by {count} index rows; an ADR has more than one entry",
                )
            )

    indexed_adrs = set(targets) & adr_files
    for filename in sorted(adr_files - indexed_adrs):
        defects.append(
            Defect(
                "missing-index-row",
                f"{filename!r} exists but has no row in README.md's '## Index' table",
            )
        )
    return defects


def _resolve_target(
    row: IndexRow, all_relative_files: set[str]
) -> tuple[str | None, Defect | None]:
    """Resolve one Markdown target using repository-case-sensitive semantics."""
    split = urlsplit(row.target)
    if split.scheme or split.netloc or not split.path:
        return None, Defect(
            "invalid-relative-link",
            f"ADR-{row.number} uses {row.target!r}; index targets must be relative file links",
            row.line,
        )

    decoded = unquote(split.path)
    if "\\" in decoded:
        return None, Defect(
            "invalid-relative-link",
            f"ADR-{row.number} uses a backslash in {row.target!r}; Markdown paths use '/'",
            row.line,
        )

    pure = PurePosixPath(decoded)
    if pure.is_absolute() or ".." in pure.parts:
        return None, Defect(
            "invalid-relative-link",
            f"ADR-{row.number} uses {row.target!r}; the ADR index must stay inside its directory",
            row.line,
        )

    normalized = PurePosixPath(*[part for part in pure.parts if part != "."]).as_posix()
    if normalized not in all_relative_files:
        return None, Defect(
            "missing-index-target",
            f"ADR-{row.number} links to {row.target!r}, but that exact relative "
            "file does not exist",
            row.line,
        )
    return normalized, None


def render_report(decisions_dir: Path, defects: Sequence[Defect]) -> str:
    """Render a bounded claim suitable for terminal and CI output."""
    lines = ["ADR index consistency"]
    if defects:
        lines.append(f"FAILED: {len(defects)} defect(s) found.")
        lines.extend(f"  {defect.render()}" for defect in defects)
    else:
        lines.append(
            f"OK: every ADR-NNN-*.md in {decisions_dir.as_posix()} has a README index row, "
            "and every ADR index row names an existing ADR file."
        )
    lines.extend(
        [
            "",
            "Scope: README.md's authoritative '## Index' table only.",
            "Not checked: titles, statuses, summaries, ADR body structure, number gaps,",
            "links outside that table, or PLAIN-ENGLISH.md's frozen selective walkthrough.",
        ]
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check docs/decisions/README.md's ADR index in both directions."
    )
    parser.add_argument(
        "decisions_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_DECISIONS_DIR,
        help="decision directory containing README.md and ADR files",
    )
    args = parser.parse_args(argv)
    defects = find_defects(args.decisions_dir)
    print(render_report(args.decisions_dir, defects))
    if defects:
        print(
            f"\nFix README.md's index or the broken ADR path; {len(defects)} defect(s) remain.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
