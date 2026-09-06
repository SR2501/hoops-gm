"""Check that the ADR index in ``docs/decisions/README.md`` agrees with the files.

The index has drifted before: the README itself records that ADR-017 was absent
from the table until 2026-08-27. This makes that class of drift fail loudly.

**Three invariants, kept separate because they fail differently.**

A. Every ``ADR-NNN-*.md`` file appears as a row in the index.
B. Every index row resolves to a file that exists.
C. The status in the index equals the status in the ADR file.

**The reserved-number exception, and why it is read rather than hardcoded.**
ADR-016 is deliberately unwritten: four coordinator-register entries reference
"whenever ADR-016 is written", so the number is held free rather than reused. A
checker that flagged it would be demanding the index *stop* explaining itself -
the same inverse-vacuity failure recorded in ``docs/governance/gates.md``, where
a citation check made honest disclosure of a withheld artifact unrepresentable.

So invariant B exempts a number only when README.md **declares it in prose**, in
the exact form ``**016 is unwritten and reserved.**``. Widening the exemption
therefore requires writing a sentence a reviewer will see, and cannot be done by
editing a list of exceptions nobody reads.

**What this cannot see.** It compares two records of the same decision; it has no
opinion on whether the summary is accurate, whether an ``Accepted`` status is
justified, or whether an ADR should exist at all. Agreement is not correctness.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DECISIONS = REPO_ROOT / "docs" / "decisions"

# ADR headers use two shapes in this repository: `**Status:** X` (ADR-001..015)
# and `- **Status:** X` (ADR-017 onward). Matching only one silently reports
# every file in the other shape as having no status at all.
_STATUS = re.compile(r"^-?\s*\*\*Status:\*\*\s*(.+?)\s*$", re.M)

# | [021](ADR-021-draft-day-without-availability.md) | Title | **Proposed** | ...
_ROW = re.compile(r"^\|\s*\[(\d+)\]\(([^)]+)\)\s*\|([^|]*)\|([^|]*)\|", re.M)

_RESERVED = re.compile(r"\*\*(\d+) is unwritten and reserved\.\*\*")

_ADR_FILE = re.compile(r"^ADR-(\d+)")


def index_section(readme: str) -> str:
    """Return only the ``## Index`` section.

    README.md holds more than one table. Scanning the whole file lets rows from a
    later table overwrite index rows, which produced eighteen confident false
    disagreements the first time this was written.
    """
    start = readme.find("## Index")
    if start == -1:
        return ""
    nxt = readme.find("\n## ", start + 1)
    return readme[start : nxt if nxt != -1 else len(readme)]


def statuses_from_files(decisions: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(decisions.glob("ADR-*.md")):
        match = _ADR_FILE.match(path.name)
        if match is None:
            continue
        status = _STATUS.search(path.read_text(encoding="utf-8"))
        found[match.group(1)] = status.group(1).strip() if status else ""
    return found


def rows_from_index(section: str) -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    for match in _ROW.finditer(section):
        number, target, _title, status = match.groups()
        rows[number] = (target.strip(), status.strip().strip("*").strip())
    return rows


def reserved_numbers(readme: str) -> set[str]:
    return set(_RESERVED.findall(readme))


def _leading_word(value: str) -> str:
    """First word before any comma.

    A file may legitimately carry detail after the status - ADR-020 reads
    ``Accepted, including both amendments`` - while the index carries the bare
    word. Comparing the whole string would report that as drift.
    """
    head = value.split(",")[0].strip()
    return head.split()[0].lower() if head else ""


def problems(decisions: Path) -> list[str]:
    readme_path = decisions / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    files = statuses_from_files(decisions)
    rows = rows_from_index(index_section(readme))
    reserved = reserved_numbers(readme)

    found: list[str] = []

    for number in sorted(set(files) - set(rows)):
        found.append(f"ADR-{number} has a file but no row in the index table")

    for number in sorted(rows):
        target, _status = rows[number]
        if (decisions / target).exists():
            continue
        if number in reserved:
            continue
        found.append(
            f"ADR-{number} is listed in the index but {target} does not exist, "
            f"and README.md does not declare {number} reserved"
        )

    for number in sorted(set(files) & set(rows)):
        file_status = files[number]
        index_status = rows[number][1]
        if not file_status:
            found.append(f"ADR-{number} file has no '**Status:**' line")
            continue
        if _leading_word(file_status) != _leading_word(index_status):
            found.append(
                f"ADR-{number} status disagrees: file says {file_status!r}, "
                f"index says {index_status!r}"
            )

    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--decisions",
        type=Path,
        default=DECISIONS,
        help="directory holding the ADRs and their README index",
    )
    args = parser.parse_args(argv)
    decisions: Path = args.decisions

    found = problems(decisions)
    if found:
        print(f"ADR index is inconsistent with {decisions}:")
        for line in found:
            print(f"  - {line}")
        return 1

    files = statuses_from_files(decisions)
    reserved = reserved_numbers((decisions / "README.md").read_text(encoding="utf-8"))
    print(
        f"ADR index consistent: {len(files)} ADRs, "
        f"{len(reserved)} reserved number(s) {sorted(reserved)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
