#!/usr/bin/env python3
"""Check that the ADR files and the decision-log index cannot drift apart.

Runs in CI through the backend test suite and is runnable locally:

    python scripts/check_adr_index.py

The check is deliberately bidirectional:

1. every ``docs/decisions/ADR-0NN-*.md`` file must be linked from the
   ``README.md`` Index section;
2. every ADR link in that section must resolve to a file.

The second direction catches renames that leave a plausible-looking but broken
Markdown link. The first catches an ADR added without an index row.

``PLAIN-ENGLISH.md`` is intentionally outside this check. It declares itself a
frozen historical walkthrough through ADR-009; requiring one entry per ADR
would turn a deliberately selective document into a second authoritative
index.

This does not validate row titles, statuses, summaries, ADR contents, or links
outside the README's Index section. It establishes membership and link
resolution only.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DECISIONS_DIR = REPO_ROOT / "docs" / "decisions"
ADR_FILE_RE = re.compile(r"^ADR-0\d{2}-[^/]+\.md$")
INDEX_HEADING = "## Index"
INDEX_ROW_RE = re.compile(r"^\|\s*\[[^\]]+\]\((?P<link>[^)]+)\)\s*\|")


def adr_files(decisions_dir: Path) -> set[Path]:
    """Return the ADR files governed by the README index."""
    return {
        path.resolve()
        for path in decisions_dir.iterdir()
        if path.is_file() and ADR_FILE_RE.fullmatch(path.name)
    }


def index_links(readme_text: str) -> tuple[list[str], list[str]]:
    """Return ADR link targets from the README Index section and parse problems."""
    lines = readme_text.splitlines()
    headings = [index for index, line in enumerate(lines) if line.strip() == INDEX_HEADING]
    if not headings:
        return [], [f"{INDEX_HEADING!r} section not found"]
    if len(headings) > 1:
        return [], [f"{INDEX_HEADING!r} occurs {len(headings)} times"]

    start = headings[0] + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    links: list[str] = []
    problems: list[str] = []
    for line_number, line in enumerate(lines[start:end], start=start + 1):
        if not line.startswith("|"):
            continue
        first_cell = line.split("|", 2)[1].strip()
        if first_cell == "#" or set(first_cell) <= {"-", ":"}:
            continue
        match = INDEX_ROW_RE.match(line)
        if match is None:
            problems.append(
                f"line {line_number} in the README Index is not a linked table row: {line!r}"
            )
            continue
        links.append(match.group("link"))
    if not links:
        problems.append("the README Index section contains no ADR rows")
    return links, problems


def resolve_index_link(readme: Path, link: str) -> tuple[Path | None, str | None]:
    """Resolve one Markdown link target relative to the README."""
    parsed = urlsplit(link)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None, f"index link {link!r} is not a relative file link"

    relative = Path(unquote(parsed.path))
    if relative.is_absolute():
        return None, f"index link {link!r} is not relative to {readme.parent}"
    return (readme.parent / relative).resolve(), None


def consistency_problems(decisions_dir: Path = DEFAULT_DECISIONS_DIR) -> list[str]:
    """Return every membership or link-resolution problem in the ADR index."""
    if not decisions_dir.is_dir():
        return [f"decision directory not found: {decisions_dir}"]

    readme = decisions_dir / "README.md"
    if not readme.is_file():
        return [f"decision index not found: {readme}"]

    files = adr_files(decisions_dir)
    if not files:
        return [
            "no ADR files matched ADR-0NN-*.md; refusing to report a vacuously consistent index"
        ]

    links, problems = index_links(readme.read_text(encoding="utf-8"))
    indexed: set[Path] = set()
    for link in links:
        target, problem = resolve_index_link(readme, link)
        if problem is not None:
            problems.append(problem)
            continue
        assert target is not None
        indexed.add(target)
        if not target.is_file():
            problems.append(f"index link {link!r} does not resolve to a file")

    for missing in sorted(files - indexed):
        problems.append(f"{missing.name} has no row in {readme.name}'s Index section")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if len(args) > 1:
        print("usage: check_adr_index.py [DECISIONS_DIR]", file=sys.stderr)
        return 2

    decisions_dir = Path(args[0]) if args else DEFAULT_DECISIONS_DIR
    problems = consistency_problems(decisions_dir)
    if problems:
        print("ADR index consistency check failed:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    files = adr_files(decisions_dir)
    print(
        f"{decisions_dir / 'README.md'} indexes all {len(files)} ADR files, "
        "and every ADR index link resolves."
    )
    print(
        "PLAIN-ENGLISH.md is excluded: it declares itself a frozen historical "
        "walkthrough, not an authoritative index."
    )
    print("Titles, statuses, summaries, ADR contents, and non-index links were not checked.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
