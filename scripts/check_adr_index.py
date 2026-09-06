#!/usr/bin/env python3
"""Fail when the decision log's index and its ADR files can drift apart.

Runs in CI and is runnable locally:

    python scripts/check_adr_index.py
    python scripts/check_adr_index.py --summary "$GITHUB_STEP_SUMMARY"

``docs/decisions/`` holds one file per architecture decision and one index over
them in ``README.md``. The two are maintained by hand, on different lines, by
different lanes, and **nothing resolved one against the other** until this
script existed. On 2026-08-21 the index was found missing rows for ADR-013 and
ADR-014; ADR-017 was absent from the same table until 2026-08-27 and was noticed
only because the lane writing ADR-018 happened to look. Both defects surfaced by
accident - a merge conflict landing on adjacent rows, a second author reading
the table - which is a detector with no coverage guarantee: it fires only when
two lanes touch the same table in the same window.

**What fails and why, in both directions.** The item this implements
(``adr-index-consistency-test``) is deliberate that only one of the two
directions is visible to a human reading the rendered table:

1. every ``docs/decisions/ADR-0NN-*.md`` has a row in the ``README.md`` index -
   a missing row is invisible to anyone reading the table, because a table does
   not show the rows it lacks; and
2. every index row's relative link resolves to a file that exists - the one a
   rename breaks and a reader cannot see, because a plausible title beside a
   broken relative link renders identically to a working one until it is
   clicked. The ADR-015 row was verified by a reviewer resolving the link, not
   by its author reading the table.

Alongside those two it also refuses the shapes that make either direction
unanswerable: a row whose number disagrees with the file its link names (a
rename that moved the target but not the label), the same ADR indexed twice, and
two files claiming one number. And it guards its own instruments: an empty ADR
set, an index section it cannot find, or a table it parsed to zero rows all fail
loudly, because a checker that examines nothing and reports success is the exact
failure mode this repository keeps finding in its verification tools.

**Scope, stated because the pass is easy to over-read.** Only the ``## Index``
table is read. The ``## Amendments awaiting acceptance`` table below it reuses
the same ``| [NNN](target) |`` row syntax and is *not* an index of files, so
reading it as one would invent duplicate rows for every amended ADR. The
``Status`` column is not checked against each ADR's declared status - it is
nuanced (an ``Accepted`` body can carry a ``Proposed`` amendment, recorded in a
separate table) and the item scoped this to file/row correspondence on purpose.
``PLAIN-ENGLISH.md`` is a second, prose index over the same directory, but it is
deliberately selective and self-declares as frozen at ADR-009 in its own header,
so requiring a paragraph per ADR would be wrong; it is out of scope, and it says
so where a reader looks. See the item in ``docs/backlog.md`` for that decision.

Exit code 1 means a defect was found. Exit code 0 means every ADR file is
indexed and every index link resolves.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DECISIONS = REPO_ROOT / "docs" / "decisions"
INDEX_FILENAME = "README.md"

#: ``ADR-014-read-endpoints-detect-not-lock.md``. The number is captured; the
#: rest of the slug is required so ``README.md`` and ``PLAIN-ENGLISH.md`` are not
#: mistaken for decision files, and so a numberless ``ADR-`` file is reported
#: rather than silently dropped from the set it is supposed to be counted in.
ADR_FILENAME_RE = re.compile(r"^ADR-(\d+)-.+\.md$")
#: Any ``ADR-*.md`` at all, so a file that looks like a decision but cannot be
#: read as one becomes a defect instead of a silent omission.
ADR_GLOB = "ADR-*.md"
#: A markdown table row whose first cell is an index link: ``| [014](ADR-014-...md) |``.
#: Anchored at the row start with the link as the first cell, so prose that
#: merely mentions an ADR - and the amendments table, which puts a different kind
#: of row under a different heading - are not read as index entries.
INDEX_ROW_RE = re.compile(r"^\|\s*\[(\d+)\]\(([^)]+)\)\s*\|")
#: The ADR number embedded in a link target, e.g. the ``14`` in
#: ``ADR-014-read-endpoints-detect-not-lock.md``.
TARGET_NUMBER_RE = re.compile(r"^ADR-(\d+)-")
#: ``## Index`` starts the section this reads; the next level-2 heading ends it.
#: The index is one table among several in the file, so the boundary matters:
#: ``## Accepted`` and ``## Amendments awaiting acceptance`` follow it.
INDEX_HEADING_RE = re.compile(r"^## +Index\s*$")
ANY_H2_RE = re.compile(r"^## ")


@dataclass(frozen=True)
class AdrFile:
    """One decision file on disk."""

    number: int
    filename: str


@dataclass(frozen=True)
class IndexRow:
    """One row of the ``## Index`` table."""

    number: int
    target: str
    line: int


@dataclass(frozen=True)
class Defect:
    """Something the pair claims that cannot be true."""

    kind: str
    message: str
    line: int | None = None

    def render(self) -> str:
        where = f"line {self.line}: " if self.line is not None else ""
        return f"[{self.kind}] {where}{self.message}"


def discover_adrs(decisions_dir: Path) -> tuple[list[AdrFile], list[Defect]]:
    """Find the ADR files on disk, reporting any that cannot be read as one.

    A file matching ``ADR-*.md`` whose name the number pattern cannot parse is a
    defect, not a skip: dropping it would remove it from the very set the index
    is checked against, and the index would then look complete against a
    truncated reality.
    """
    adrs: list[AdrFile] = []
    defects: list[Defect] = []
    for path in sorted(decisions_dir.glob(ADR_GLOB)):
        match = ADR_FILENAME_RE.match(path.name)
        if match is None:
            defects.append(
                Defect(
                    "unreadable-adr-filename",
                    f"{path.name!r} matches {ADR_GLOB} but not the "
                    "'ADR-NNN-slug.md' convention; it cannot be checked against "
                    "the index and must not be silently dropped from the set",
                )
            )
            continue
        adrs.append(AdrFile(number=int(match.group(1)), filename=path.name))
    return adrs, defects


def parse_index(text: str) -> tuple[list[IndexRow], list[Defect]]:
    """Parse the ``## Index`` table's link rows out of ``README.md``.

    Reads only the ``## Index`` section. Everything is reported rather than
    skipped when it cannot be found, because a parser that stops matching
    returns an empty table and an empty table contradicts nothing.
    """
    lines = text.splitlines()
    defects: list[Defect] = []

    start: int | None = None
    for index, line in enumerate(lines):
        if INDEX_HEADING_RE.match(line):
            start = index
            break
    if start is None:
        defects.append(
            Defect(
                "missing-index-section",
                "no '## Index' heading found in the decision log; the index this "
                "checks cannot be located, and a check that cannot find its "
                "subject must not report it consistent",
            )
        )
        return [], defects

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if ANY_H2_RE.match(lines[index]):
            end = index
            break

    rows: list[IndexRow] = []
    for offset in range(start + 1, end):
        match = INDEX_ROW_RE.match(lines[offset])
        if match is None:
            continue
        rows.append(
            IndexRow(
                number=int(match.group(1)),
                target=match.group(2),
                line=offset + 1,
            )
        )

    if not rows:
        defects.append(
            Defect(
                "no-index-rows",
                "the '## Index' section holds no '| [NNN](target) |' rows; either "
                "the table is empty or its row format changed under this parser, "
                "and both make every correspondence check below vacuous",
                start + 1,
            )
        )
    return rows, defects


def find_defects(
    adrs: Sequence[AdrFile], rows: Sequence[IndexRow], decisions_dir: Path
) -> list[Defect]:
    """Every claim the file set and the index make that cannot both be true.

    The empty-set guard is first and is not a formality: with no ADR files every
    'is this file indexed' loop is vacuous and the run reports a clean index over
    a directory it never read.
    """
    defects: list[Defect] = []
    if not adrs:
        defects.append(
            Defect(
                "no-adr-files",
                f"no ADR files found in {decisions_dir.as_posix()}. Either the "
                "directory is empty or the naming convention changed under this "
                "check; both make the index-coverage check vacuous",
            )
        )

    for number, count in sorted(Counter(a.number for a in adrs).items()):
        if count > 1:
            names = ", ".join(a.filename for a in adrs if a.number == number)
            defects.append(
                Defect(
                    "duplicate-adr-file",
                    f"ADR-{number:03d} is claimed by {count} files ({names}); a "
                    "row naming that number cannot say which file it means",
                )
            )

    row_numbers: Counter[int] = Counter(r.number for r in rows)
    for number, count in sorted(row_numbers.items()):
        if count > 1:
            where = ", ".join(str(r.line) for r in rows if r.number == number)
            defects.append(
                Defect(
                    "duplicate-index-row",
                    f"ADR-{number:03d} has {count} index rows (lines {where}); a "
                    "second row is the state a conflict resolution that keeps both "
                    "sides leaves behind",
                )
            )

    for row in rows:
        target_match = TARGET_NUMBER_RE.match(row.target)
        if target_match is None:
            defects.append(
                Defect(
                    "index-row-unreadable-target",
                    f"the ADR-{row.number:03d} row links to {row.target!r}, which "
                    "is not an 'ADR-NNN-...' filename; the row cannot be resolved "
                    "to a numbered decision",
                    row.line,
                )
            )
        elif int(target_match.group(1)) != row.number:
            defects.append(
                Defect(
                    "index-row-number-mismatch",
                    f"the row labelled [{row.number:03d}] links to {row.target!r}, "
                    f"which is ADR-{int(target_match.group(1)):03d}; the label and "
                    "the file it points at disagree, which is what a rename that "
                    "moved the target but not the label produces",
                    row.line,
                )
            )

        if not (decisions_dir / row.target).is_file():
            defects.append(
                Defect(
                    "index-link-broken",
                    f"the ADR-{row.number:03d} row links to {row.target!r}, which "
                    f"does not exist in {decisions_dir.as_posix()}. A broken "
                    "relative link renders as a working one until it is clicked; "
                    "this is the direction a rename breaks and a reader cannot see",
                    row.line,
                )
            )

    indexed = set(row_numbers)
    for adr in sorted(adrs, key=lambda a: a.number):
        if adr.number not in indexed:
            defects.append(
                Defect(
                    "adr-missing-from-index",
                    f"{adr.filename} has no row in the '## Index' table. A missing "
                    "row is invisible to anyone reading the table, because a table "
                    "does not show the rows it lacks - add a row for it",
                )
            )

    return defects


def check(decisions_dir: Path) -> tuple[list[AdrFile], list[IndexRow], list[Defect]]:
    """Read the directory and its index, and return everything found.

    Combines the filesystem discovery, the index parse and the cross-check the
    way ``main`` reports them, so a test can exercise the whole pipeline against
    a temporary directory.
    """
    adrs, discover_defects = discover_adrs(decisions_dir)

    index_path = decisions_dir / INDEX_FILENAME
    if not index_path.is_file():
        return (
            adrs,
            [],
            [
                *discover_defects,
                Defect(
                    "missing-index-file",
                    f"no {INDEX_FILENAME} in {decisions_dir.as_posix()}; the index "
                    "this checks is absent, which is a failure and not a pass",
                ),
            ],
        )

    rows, parse_defects = parse_index(index_path.read_text(encoding="utf-8"))
    defects = [*discover_defects, *parse_defects, *find_defects(adrs, rows, decisions_dir)]
    return adrs, rows, defects


def render_report(
    adrs: Sequence[AdrFile], rows: Sequence[IndexRow], defects: Sequence[Defect], source: Path
) -> str:
    """Markdown, so the same text serves a terminal and a CI job summary."""
    out: list[str] = [
        "## ADR index consistency",
        "",
        f"`{source.as_posix()}` - **{len(adrs)} ADR file(s)**, **{len(rows)} index row(s)**.",
        "",
        "### Defects",
        "",
    ]
    if defects:
        out.append(
            f"**{len(defects)} found.** Each is a file the index omits, a link it "
            "carries that does not resolve, or an instrument that read nothing."
        )
        out.append("")
        out.extend(f"- {defect.render()}" for defect in defects)
    else:
        out.append(
            "Every ADR file on disk has an index row, and every index row's "
            "relative link resolves to a file that exists. That is a **narrow "
            "claim**: it is *not* that the index is correct. The `Status` column "
            "is not checked against each ADR's declared status, a row's title may "
            "misdescribe its decision, and `PLAIN-ENGLISH.md` - the prose index "
            "over the same directory, deliberately frozen at ADR-009 - is out of "
            "scope by design. See `docs/backlog.md`."
        )
    out.append("")
    return "\n".join(out)


def _safe_stdout() -> None:
    """A defect message can quote a filename verbatim.

    That name is arbitrary directory content, and printing it through a cp1252
    Windows console can raise ``UnicodeEncodeError`` - which would report a crash
    where the script had in fact done its job and found a defect.
    """
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="backslashreplace")


def main(argv: Sequence[str] | None = None) -> int:
    _safe_stdout()
    parser = argparse.ArgumentParser(
        description="Fail when a decision file is missing from the index, or an index link breaks."
    )
    parser.add_argument(
        "decisions",
        nargs="?",
        type=Path,
        default=DEFAULT_DECISIONS,
        help="path to the decisions directory (default: docs/decisions)",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="also append the report here, e.g. $GITHUB_STEP_SUMMARY",
    )
    args = parser.parse_args(argv)

    decisions_dir: Path = args.decisions
    if not decisions_dir.is_dir():
        print(f"error: {decisions_dir} is not a directory", file=sys.stderr)
        return 1

    adrs, rows, defects = check(decisions_dir)

    report = render_report(adrs, rows, defects, decisions_dir)
    print(report)
    sys.stdout.flush()
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(report + "\n")

    if defects:
        print(
            f"\nFAILED: {len(defects)} defect(s) in {decisions_dir.as_posix()}.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
