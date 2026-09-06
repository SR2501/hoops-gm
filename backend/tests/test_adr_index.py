"""Regression tests for ``scripts/check_adr_index.py``.

The real-tree assertion is paired with mutations and empty-set controls so a
parser that stops finding ADRs or rows cannot report a vacuous success.
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


def kinds(defects: list[object]) -> list[str]:
    return [defect.kind for defect in defects]  # type: ignore[attr-defined]


def write_decisions(
    root: Path,
    *,
    files: tuple[str, ...] = ("ADR-001-one.md",),
    rows: tuple[tuple[str, str], ...] = (("001", "ADR-001-one.md"),),
) -> Path:
    decisions = root / "docs" / "decisions"
    decisions.mkdir(parents=True)
    for filename in files:
        (decisions / filename).write_text(f"# {filename}\n", encoding="utf-8")
    table = "\n".join(
        f"| [{number}]({target}) | Title | **Proposed** | Summary |" for number, target in rows
    )
    (decisions / "README.md").write_text(
        "# Decision log\n\n"
        "## Index\n\n"
        "| # | Title | Status | Summary |\n"
        "|---|---|---|---|\n"
        f"{table}\n\n"
        "## Accepted\n",
        encoding="utf-8",
    )
    return decisions


def test_the_real_adr_set_is_populated() -> None:
    filenames = {
        path.name
        for path in REAL_DECISIONS.iterdir()
        if path.is_file() and path.name.startswith("ADR-")
    }

    assert len(filenames) >= 15, "the control expected a populated ADR directory"
    assert "ADR-001-local-first.md" in filenames
    assert "ADR-020-board-reading-keyed-by-board.md" in filenames


def test_the_real_adr_index_is_consistent(checker: ModuleType) -> None:
    defects = checker.find_defects(REAL_DECISIONS)
    assert defects == [], "\n".join(defect.render() for defect in defects)


def test_a_new_adr_without_a_row_is_caught(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(
        tmp_path,
        files=("ADR-001-one.md", "ADR-002-two.md"),
    )

    defects = checker.find_defects(decisions)

    assert "missing-index-row" in kinds(defects)
    assert "ADR-002-two.md" in defects[-1].message


def test_a_broken_relative_link_is_caught(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(
        tmp_path,
        rows=(("001", "ADR-001-renamed.md"),),
    )

    defects = checker.find_defects(decisions)

    assert "missing-index-target" in kinds(defects)
    assert "missing-index-row" in kinds(defects)


def test_link_existence_is_case_sensitive_like_git(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(
        tmp_path,
        rows=(("001", "adr-001-one.md"),),
    )

    assert "missing-index-target" in kinds(checker.find_defects(decisions))


def test_a_duplicate_row_is_caught(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(
        tmp_path,
        rows=(("001", "ADR-001-one.md"), ("001", "ADR-001-one.md")),
    )

    assert "duplicate-index-target" in kinds(checker.find_defects(decisions))


def test_an_index_row_cannot_point_to_a_non_adr_file(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(
        tmp_path,
        rows=(("001", "README.md"), ("001", "ADR-001-one.md")),
    )

    assert "non-adr-index-target" in kinds(checker.find_defects(decisions))


def test_an_external_index_link_is_not_a_relative_file(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(
        tmp_path,
        rows=(("001", "https://example.com/ADR-001-one.md"),),
    )

    assert "invalid-relative-link" in kinds(checker.find_defects(decisions))


def test_no_adr_files_cannot_pass_vacuously(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(tmp_path, files=(), rows=())

    defects = checker.find_defects(decisions)

    assert "no-adr-files" in kinds(defects)
    assert "no-index-rows" in kinds(defects)


def test_no_index_rows_cannot_pass_vacuously(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(tmp_path, rows=())

    defects = checker.find_defects(decisions)

    assert "no-index-rows" in kinds(defects)
    assert "missing-index-row" in kinds(defects)


def test_a_missing_index_section_is_caught(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(tmp_path)
    (decisions / "README.md").write_text("# Decision log\n", encoding="utf-8")

    assert "missing-index-section" in kinds(checker.find_defects(decisions))


def test_a_malformed_table_row_is_not_silently_skipped(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(tmp_path)
    readme = decisions / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "| [001](ADR-001-one.md) |", "| 001 ADR-001-one.md |"
        ),
        encoding="utf-8",
    )

    assert "malformed-index-row" in kinds(checker.find_defects(decisions))


def test_plain_english_declares_why_it_is_out_of_scope() -> None:
    text = (REAL_DECISIONS / "PLAIN-ENGLISH.md").read_text(encoding="utf-8")

    assert "Frozen historical walkthrough" in text
    assert "not extended for later decisions" in text
    assert "README.md" in text and "authoritative" in text


def test_main_returns_zero_for_the_real_index(checker: ModuleType) -> None:
    assert checker.main([str(REAL_DECISIONS)]) == 0


def test_main_returns_one_for_a_broken_index(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(
        tmp_path,
        rows=(("001", "ADR-001-missing.md"),),
    )

    assert checker.main([str(decisions)]) == 1


def test_the_script_runs_as_a_subprocess_against_the_real_tree() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "every ADR-NNN-*.md" in result.stdout
    assert "PLAIN-ENGLISH.md" in result.stdout
