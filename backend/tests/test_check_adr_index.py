"""Tests for ``scripts/check_adr_index.py``.

Written to be independent of the very file it guards, because the failure this
repository keeps finding is a verification tool that examines an empty set and
reports success. Three groups below exist specifically to make that impossible
here.

``test_no_adr_files_fails`` and its index-side siblings point the checker at
directories holding nothing to iterate over and assert it **fails** rather than
reporting a clean index. Every correspondence check is vacuous if one of those
regresses.

``test_the_real_decision_log_is_clean`` asserts against the live
``docs/decisions/`` directory, and the mutation tests beside it keep that
assertion honest: they take the real index, break it in one specific way, and
require the checker to notice. A clean-file assertion alone would keep passing if
the parser quietly stopped resolving rows.

``test_the_historical_missing_row_is_caught`` reproduces the actual defect from
2026-08-21: an ADR file present on disk with no row in the index.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_adr_index.py"
REAL_DECISIONS = Path(__file__).resolve().parents[2] / "docs" / "decisions"


@pytest.fixture(scope="module")
def adr() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_adr_index", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- building synthetic decision directories --------------------------------


def index_row(number: int, target: str | None = None, *, title: str = "A decision") -> str:
    target = target if target is not None else f"ADR-{number:03d}-slug.md"
    return f"| [{number:03d}]({target}) | {title} | **Accepted** | Summary |"


def readme(*rows: str, heading: str = "## Index", tail: str = "") -> str:
    table = "\n".join(
        [
            "# Decision log",
            "",
            heading,
            "",
            "| # | Title | Status | Summary |",
            "|---|---|---|---|",
            *rows,
            "",
        ]
    )
    return table + tail + "\n"


def make_log(
    tmp_path: Path,
    adr_numbers: Sequence[int],
    *,
    rows: Sequence[str] | None = None,
    readme_text: str | None = None,
    extra_files: Sequence[str] = (),
) -> Path:
    """Materialise a decisions directory: one file per number, plus an index.

    By default the index has exactly one correct row per ADR file, so every
    fixture is a *consistent* log unless a test deliberately breaks it.
    """
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    for number in adr_numbers:
        (decisions / f"ADR-{number:03d}-slug.md").write_text(
            f"# ADR-{number:03d}\n", encoding="utf-8"
        )
    for name in extra_files:
        (decisions / name).write_text("# stray\n", encoding="utf-8")

    if readme_text is None:
        table_rows = rows if rows is not None else [index_row(n) for n in adr_numbers]
        readme_text = readme(*table_rows)
    (decisions / "README.md").write_text(readme_text, encoding="utf-8")
    return decisions


def kinds(defects: Sequence[object]) -> list[str]:
    return [d.kind for d in defects]  # type: ignore[attr-defined]


# --- the empty-set guards, which every other test depends on ----------------


def test_no_adr_files_fails(adr: ModuleType, tmp_path: Path) -> None:
    """A clean index over an empty directory is the failure to refuse."""
    decisions = make_log(tmp_path, [], rows=[])
    _, _, defects = adr.check(decisions)

    assert "no-adr-files" in kinds(defects)


def test_no_index_section_fails(adr: ModuleType, tmp_path: Path) -> None:
    """If the '## Index' heading is gone, the subject cannot be located."""
    decisions = make_log(
        tmp_path,
        [1],
        readme_text="# Decision log\n\n## Something else\n\nNo index here.\n",
    )
    _, _, defects = adr.check(decisions)

    assert "missing-index-section" in kinds(defects)


def test_an_index_section_with_no_rows_fails(adr: ModuleType, tmp_path: Path) -> None:
    """A table that parsed to zero rows contradicts nothing and must say so."""
    decisions = make_log(
        tmp_path,
        [1],
        readme_text="# Decision log\n\n## Index\n\nProse, but no table rows.\n",
    )
    _, _, defects = adr.check(decisions)

    assert "no-index-rows" in kinds(defects)


def test_a_missing_readme_fails(adr: ModuleType, tmp_path: Path) -> None:
    """A vanished index is a failure, not a directory that happens to pass."""
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    (decisions / "ADR-001-slug.md").write_text("# ADR-001\n", encoding="utf-8")

    _, _, defects = adr.check(decisions)

    assert "missing-index-file" in kinds(defects)


# --- the real log, plus the mutations that keep the claim independent -------


def test_the_real_decision_log_is_clean(adr: ModuleType) -> None:
    _, _, defects = adr.check(REAL_DECISIONS)

    assert defects == [], "\n".join(d.render() for d in defects)


def test_the_real_log_parses_a_populated_set(adr: ModuleType) -> None:
    """Assert the presence expected, not merely the absence of defects."""
    adrs, rows, _ = adr.check(REAL_DECISIONS)

    assert len(adrs) > 10, "docs/decisions holds ~19 ADRs; this found almost none"
    assert len(rows) == len(adrs), "every real ADR file should have exactly one index row"
    numbers = {a.number for a in adrs}
    assert 1 in numbers and 20 in numbers


def test_deleting_one_real_row_is_noticed(adr: ModuleType, tmp_path: Path) -> None:
    """Independence check: an ADR file with its row removed must be caught.

    A 'the real log is clean' assertion would keep passing if the parser stopped
    resolving rows entirely; this requires it to genuinely miss a deletion.
    """
    text = (REAL_DECISIONS / "README.md").read_text(encoding="utf-8")
    marker = "| [020](ADR-020-board-reading-keyed-by-board.md) |"
    assert marker in text, "the real index no longer contains the row this test deletes"
    without_row = "\n".join(line for line in text.splitlines() if not line.startswith(marker))

    decisions = _clone_real(tmp_path, readme_text=without_row + "\n")
    _, _, defects = adr.check(decisions)

    assert "adr-missing-from-index" in kinds(defects)


def test_renaming_one_real_file_breaks_its_link(adr: ModuleType, tmp_path: Path) -> None:
    """Direction 2 on the real data: rename the target the index still points at.

    This is the defect a reader cannot see - the row renders identically while
    its link resolves to nothing.
    """
    decisions = _clone_real(tmp_path)
    target = decisions / "ADR-015-blend-recipe-durable-binding-transient.md"
    assert target.is_file(), "the real ADR this test renames is gone"
    target.rename(decisions / "ADR-015-renamed.md")

    _, _, defects = adr.check(decisions)

    broken = [d for d in defects if d.kind == "index-link-broken"]
    assert broken, "a renamed target left the index link resolving; it was not caught"
    assert "ADR-015" in broken[0].render()


def _clone_real(tmp_path: Path, *, readme_text: str | None = None) -> Path:
    """Copy the real decisions directory so a test can mutate it in isolation."""
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    for path in REAL_DECISIONS.iterdir():
        if path.is_file():
            (decisions / path.name).write_bytes(path.read_bytes())
    if readme_text is not None:
        (decisions / "README.md").write_text(readme_text, encoding="utf-8")
    return decisions


# --- Direction 1: every file has a row --------------------------------------


def test_the_historical_missing_row_is_caught(adr: ModuleType, tmp_path: Path) -> None:
    """The actual defect of 2026-08-21: ADR-013/ADR-014 present, unindexed."""
    decisions = make_log(tmp_path, [12, 13, 14], rows=[index_row(12)])
    _, _, defects = adr.check(decisions)

    missing = [d for d in defects if d.kind == "adr-missing-from-index"]
    assert {m.message.split()[0] for m in missing} == {
        "ADR-013-slug.md",
        "ADR-014-slug.md",
    }


def test_a_fully_indexed_reserved_gap_is_clean(adr: ModuleType, tmp_path: Path) -> None:
    """A reserved, unwritten number (016) with no file and no row is consistent.

    The real log does exactly this, so a check that demanded a contiguous
    sequence would fail the live directory.
    """
    decisions = make_log(tmp_path, [15, 17], rows=[index_row(15), index_row(17)])
    _, _, defects = adr.check(decisions)

    assert defects == []


# --- Direction 2: every row resolves ----------------------------------------


def test_a_broken_index_link_is_caught(adr: ModuleType, tmp_path: Path) -> None:
    """A row pointing at a filename that does not exist on disk."""
    decisions = make_log(
        tmp_path,
        [1],
        rows=[index_row(1, "ADR-001-renamed-away.md")],
    )
    _, _, defects = adr.check(decisions)

    broken = [d for d in defects if d.kind == "index-link-broken"]
    assert broken
    assert "ADR-001-renamed-away.md" in broken[0].render()


def test_a_row_label_disagreeing_with_its_target_is_caught(adr: ModuleType, tmp_path: Path) -> None:
    """A [014] label linking to the ADR-015 file: a rename that half-updated."""
    decisions = make_log(
        tmp_path,
        [14, 15],
        rows=[
            "| [014](ADR-015-slug.md) | Mislabelled | *Proposed* | Summary |",
            index_row(15),
        ],
    )
    _, _, defects = adr.check(decisions)

    assert "index-row-number-mismatch" in kinds(defects)


def test_a_row_target_that_is_not_an_adr_filename_is_caught(
    adr: ModuleType, tmp_path: Path
) -> None:
    decisions = make_log(
        tmp_path,
        [1],
        rows=["| [001](not-an-adr.md) | Odd | **Accepted** | Summary |"],
    )
    _, _, defects = adr.check(decisions)

    assert "index-row-unreadable-target" in kinds(defects)


# --- the shapes that make a direction unanswerable --------------------------


def test_a_duplicate_index_row_is_caught(adr: ModuleType, tmp_path: Path) -> None:
    """The rebase defect: both sides of a hunk kept, one ADR indexed twice."""
    decisions = make_log(tmp_path, [1], rows=[index_row(1), index_row(1)])
    _, _, defects = adr.check(decisions)

    assert "duplicate-index-row" in kinds(defects)


def test_two_files_claiming_one_number_is_caught(adr: ModuleType, tmp_path: Path) -> None:
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    (decisions / "ADR-001-one.md").write_text("# a\n", encoding="utf-8")
    (decisions / "ADR-001-two.md").write_text("# b\n", encoding="utf-8")
    (decisions / "README.md").write_text(readme(index_row(1, "ADR-001-one.md")), encoding="utf-8")

    _, _, defects = adr.check(decisions)

    assert "duplicate-adr-file" in kinds(defects)


def test_an_adr_named_file_without_a_number_is_reported_not_skipped(
    adr: ModuleType, tmp_path: Path
) -> None:
    """A dropped file takes itself out of the coverage set and the index looks
    complete against a truncated reality."""
    decisions = make_log(tmp_path, [1], extra_files=["ADR-draft-notes.md"])
    _, _, defects = adr.check(decisions)

    assert "unreadable-adr-filename" in kinds(defects)


# --- the amendments table must not be read as an index ----------------------


def test_a_later_table_reusing_the_row_syntax_is_not_read_as_the_index(
    adr: ModuleType, tmp_path: Path
) -> None:
    """The real ``## Amendments awaiting acceptance`` table reuses this exact row
    shape. Reading past the index section would invent duplicate rows for every
    amended ADR and fail a consistent file.
    """
    amendments = (
        "\n## Amendments awaiting acceptance\n\n"
        "| ADR | Amendment | Dated | Written by |\n"
        "|---|---|---|---|\n"
        "| [001](ADR-001-slug.md) | Some amendment | 2026-08-23 | `quant` |\n"
    )
    decisions = make_log(
        tmp_path,
        [1],
        readme_text=readme(index_row(1), tail=amendments),
    )
    rows, parse_defects = adr.parse_index((decisions / "README.md").read_text(encoding="utf-8"))

    assert [r.number for r in rows] == [1], "the amendments row leaked into the index"
    assert parse_defects == []
    _, _, defects = adr.check(decisions)
    assert defects == []


# --- the clean report states what it did not check --------------------------


def test_a_clean_report_bounds_its_own_claim(adr: ModuleType, tmp_path: Path) -> None:
    """ "No defects" is the sentence most likely to be over-read.

    The clean branch must name what it did not verify - the Status column and
    PLAIN-ENGLISH.md - in the report itself, not only in a docstring.
    """
    decisions = make_log(tmp_path, [1])
    adrs, rows, defects = adr.check(decisions)
    assert defects == []
    report = adr.render_report(adrs, rows, defects, decisions)

    assert "narrow claim" in report
    assert "Status" in report
    assert "PLAIN-ENGLISH.md" in report


def test_a_defective_report_lists_each_defect(adr: ModuleType, tmp_path: Path) -> None:
    decisions = make_log(tmp_path, [1, 2], rows=[index_row(1)])
    adrs, rows, defects = adr.check(decisions)
    report = adr.render_report(adrs, rows, defects, decisions)

    assert "adr-missing-from-index" in report


# --- the command line -------------------------------------------------------


def test_main_exits_zero_on_the_real_log(adr: ModuleType) -> None:
    assert adr.main([str(REAL_DECISIONS)]) == 0


def test_main_exits_one_on_a_broken_link(adr: ModuleType, tmp_path: Path) -> None:
    decisions = make_log(tmp_path, [1], rows=[index_row(1, "ADR-001-gone.md")])
    assert adr.main([str(decisions)]) == 1


def test_main_exits_one_when_the_directory_is_missing(adr: ModuleType, tmp_path: Path) -> None:
    assert adr.main([str(tmp_path / "absent")]) == 1


def test_the_summary_file_is_appended_to_never_truncated(adr: ModuleType, tmp_path: Path) -> None:
    """$GITHUB_STEP_SUMMARY is shared with every other step in the job."""
    decisions = make_log(tmp_path, [1])
    summary = tmp_path / "summary.md"
    summary.write_text("earlier step output\n", encoding="utf-8")

    assert adr.main([str(decisions), "--summary", str(summary)]) == 0

    written = summary.read_text(encoding="utf-8")
    assert written.startswith("earlier step output\n")
    assert "ADR index consistency" in written


def test_the_script_runs_as_a_subprocess_against_the_real_log() -> None:
    """Executed the way CI executes it, not merely imported.

    ``main`` returning 0 in-process does not establish that the file runs: an
    import-time error or a stdout encoding the runner cannot emit are invisible
    to every other test here.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "ADR index consistency" in result.stdout
