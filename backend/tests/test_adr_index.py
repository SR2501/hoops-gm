"""Regression tests for ``scripts/check_adr_index.py``.

The live assertion is paired with destructive synthetic cases so a parser that
stops seeing either the ADR files or the README rows cannot report false green.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_adr_index.py"
REAL_DECISIONS = REPO_ROOT / "docs" / "decisions"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_adr_index", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_decisions(
    root: Path,
    files: tuple[str, ...],
    rows: tuple[tuple[str, str], ...],
    *,
    index_heading: str = "## Index",
) -> Path:
    decisions = root / "docs" / "decisions"
    decisions.mkdir(parents=True)
    for filename in files:
        (decisions / filename).write_text(f"# {filename}\n", encoding="utf-8")
    table = [
        "# Decision log",
        "",
        index_heading,
        "",
        "| # | Title | Status | Summary |",
        "|---|---|---|---|",
    ]
    table.extend(
        f"| [{number}]({link}) | Decision {number} | **Accepted** | Summary |"
        for number, link in rows
    )
    table.extend(["", "## Accepted", "", "Detail."])
    (decisions / "README.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    return decisions


def kinds(defects: list[object]) -> list[str]:
    return [defect.kind for defect in defects]  # type: ignore[attr-defined]


def test_the_real_decision_index_is_populated_and_consistent(checker: ModuleType) -> None:
    rows, files, defects = checker.check_index(REAL_DECISIONS)

    assert defects == []
    assert len(files) >= 19, "the real directory scan found almost no ADR files"
    assert len(rows) == len(files)
    assert {path.name for path in files} >= {
        "ADR-001-local-first.md",
        "ADR-020-board-reading-keyed-by-board.md",
    }


def test_the_historical_missing_rows_are_caught(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(
        tmp_path,
        ("ADR-013-forward-schedule.md", "ADR-014-read-endpoints.md"),
        (),
    )

    _, _, defects = checker.check_index(decisions)

    assert kinds(defects).count("unindexed-adr") == 2
    assert "empty-index" in kinds(defects)


def test_a_rename_that_leaves_a_broken_link_is_caught(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(
        tmp_path,
        ("ADR-015-new-title.md",),
        (("015", "ADR-015-old-title.md"),),
    )

    _, _, defects = checker.check_index(decisions)

    assert kinds(defects) == ["broken-index-link", "unindexed-adr"]


def test_every_file_is_checked_even_when_other_rows_are_valid(
    checker: ModuleType, tmp_path: Path
) -> None:
    decisions = write_decisions(
        tmp_path,
        ("ADR-001-one.md", "ADR-002-two.md"),
        (("001", "ADR-001-one.md"),),
    )

    _, _, defects = checker.check_index(decisions)

    assert kinds(defects) == ["unindexed-adr"]
    assert "ADR-002-two.md" in defects[0].message


def test_rows_after_the_index_section_are_not_mistaken_for_index_rows(
    checker: ModuleType, tmp_path: Path
) -> None:
    decisions = write_decisions(
        tmp_path,
        ("ADR-001-one.md",),
        (("001", "ADR-001-one.md"),),
    )
    readme = decisions / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8")
        + "| [999](ADR-999-does-not-exist.md) | Amendment | Proposed | Later table |\n",
        encoding="utf-8",
    )

    rows, _, defects = checker.check_index(decisions)

    assert [row.number for row in rows] == ["001"]
    assert defects == []


def test_an_empty_or_unrecognised_index_cannot_pass(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(
        tmp_path,
        ("ADR-001-one.md",),
        (),
        index_heading="## Decision index",
    )

    _, _, defects = checker.check_index(decisions)

    assert kinds(defects) == ["missing-index", "unindexed-adr"]


def test_a_duplicate_target_is_caught(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(
        tmp_path,
        ("ADR-001-one.md",),
        (("001", "ADR-001-one.md"), ("001", "./ADR-001-one.md")),
    )

    _, _, defects = checker.check_index(decisions)

    assert kinds(defects) == ["duplicate-index-target"]


def test_missing_inputs_fail_instead_of_becoming_empty_sets(
    checker: ModuleType, tmp_path: Path
) -> None:
    _, _, missing_directory = checker.check_index(tmp_path / "absent")
    assert kinds(missing_directory) == ["missing-decisions-directory"]

    decisions = tmp_path / "docs" / "decisions"
    decisions.mkdir(parents=True)
    _, _, missing_readme = checker.check_index(decisions)
    assert kinds(missing_readme) == ["missing-readme"]

    (decisions / "README.md").write_text("# Decision log\n\n## Index\n", encoding="utf-8")
    _, _, no_files = checker.check_index(decisions)
    assert kinds(no_files) == ["no-adr-files"]


def test_plain_english_declares_why_it_is_not_a_current_index() -> None:
    text = (REAL_DECISIONS / "PLAIN-ENGLISH.md").read_text(encoding="utf-8")

    assert "Frozen historical walkthrough" in text
    assert "ADR-001 through" in text and "ADR-009" in text
    assert "[`README.md`](README.md) index" in text


def test_the_script_runs_as_a_subprocess_against_the_real_index() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "both directions agree" in result.stdout
    assert "PLAIN-ENGLISH.md is not checked" in result.stdout
    assert "Titles, statuses, summaries" in result.stdout
