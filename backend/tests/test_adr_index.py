"""Executable coverage for ``scripts/check_adr_index.py``.

The real-file assertion is paired with mutations in both directions. Without
those controls, a parser that silently found no ADRs or no index rows could
report the repository consistent without comparing anything.
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
DECISIONS = REPO_ROOT / "docs" / "decisions"


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
    *,
    files: tuple[str, ...] = ("ADR-001-first.md",),
    rows: tuple[str, ...] = ("| [001](ADR-001-first.md) | First | **Accepted** | Summary |",),
) -> Path:
    decisions = root / "decisions"
    decisions.mkdir()
    for filename in files:
        (decisions / filename).write_text(f"# {filename}\n", encoding="utf-8")
    readme = "\n".join(
        (
            "# Decision log",
            "",
            "## Index",
            "",
            "| # | Title | Status | Summary |",
            "|---|---|---|---|",
            *rows,
            "",
            "## Accepted",
            "",
            "Narrative links outside the index do not define membership.",
            "",
        )
    )
    (decisions / "README.md").write_text(readme, encoding="utf-8")
    return decisions


def test_the_repository_index_is_consistent(checker: ModuleType) -> None:
    assert checker.consistency_problems(DECISIONS) == []


def test_an_adr_file_missing_from_the_index_is_caught(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(
        tmp_path,
        files=("ADR-001-first.md", "ADR-002-unindexed.md"),
    )

    problems = checker.consistency_problems(decisions)

    assert problems == ["ADR-002-unindexed.md has no row in README.md's Index section"]


def test_an_index_link_to_a_missing_file_is_caught(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(
        tmp_path,
        rows=(
            "| [001](ADR-001-first.md) | First | **Accepted** | Summary |",
            "| [002](ADR-002-renamed.md) | Renamed | **Proposed** | Summary |",
        ),
    )

    problems = checker.consistency_problems(decisions)

    assert problems == ["index link 'ADR-002-renamed.md' does not resolve to a file"]


def test_a_malformed_index_row_is_not_silently_skipped(checker: ModuleType, tmp_path: Path) -> None:
    decisions = write_decisions(
        tmp_path,
        rows=("| 001 | First | **Accepted** | Link disappeared |",),
    )

    problems = checker.consistency_problems(decisions)

    assert any("is not a linked table row" in problem for problem in problems)
    assert any("ADR-001-first.md has no row" in problem for problem in problems)


def test_links_resolve_relative_to_the_readme_not_the_process(
    checker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decisions = write_decisions(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert checker.consistency_problems(decisions) == []


def test_a_missing_index_section_fails_instead_of_passing_vacuously(
    checker: ModuleType, tmp_path: Path
) -> None:
    decisions = write_decisions(tmp_path)
    (decisions / "README.md").write_text("# Decision log\n", encoding="utf-8")

    problems = checker.consistency_problems(decisions)

    assert "'## Index' section not found" in problems
    assert any("has no row" in problem for problem in problems)


def test_no_adr_files_fails_instead_of_passing_vacuously(
    checker: ModuleType, tmp_path: Path
) -> None:
    decisions = write_decisions(tmp_path, files=())

    assert checker.consistency_problems(decisions) == [
        "no ADR files matched ADR-0NN-*.md; refusing to report a vacuously consistent index"
    ]


def test_plain_english_declares_why_it_is_not_a_second_index() -> None:
    text = (DECISIONS / "PLAIN-ENGLISH.md").read_text(encoding="utf-8")

    assert "Frozen historical walkthrough" in text
    assert "not extended for later decisions" in text
    assert "README.md" in text and "authoritative record" in text


def test_the_script_runs_as_a_subprocess_against_the_real_index() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "indexes all" in result.stdout
    assert "every ADR index link resolves" in result.stdout
