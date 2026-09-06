"""Tests for ``scripts/check_adr_index.py``.

`docs/decisions/README.md` was found missing rows for ADR-013 and ADR-014 on
2026-08-21, and reading the table is not how the gap was found — nothing
compared it against the directory until this script existed. Two indexes over
one directory (this one, and `PLAIN-ENGLISH.md`) were drifting independently,
neither with a test.

Both directions matter and neither is provable by the other:

``test_an_adr_file_with_no_index_row_is_reported`` reproduces the actual
2026-08-21 defect — a file on disk the table never mentions.

``test_an_index_row_whose_link_is_broken_is_reported`` is the one a human
reading rendered Markdown cannot see: a plausible title beside a dead relative
link looks identical to a working one until the link is clicked, which is how
the ADR-015 row was actually verified.

``test_the_real_readme_index_is_clean`` asserts against the real file, and the
two mutation tests beside it exist so that assertion is not merely accurate
and non-independent — they take the real file, break it one specific way, and
require the checker to notice.
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
REAL_DECISIONS_DIR = REPO_ROOT / "docs" / "decisions"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_adr_index", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- building synthetic decisions directories --------------------------------


def _write_decisions_dir(
    tmp_path: Path,
    *,
    adr_files: dict[str, str] | None = None,
    index_rows: list[str] | None = None,
    readme: str | None = None,
) -> Path:
    """A minimal ``docs/decisions/`` with a valid README.md unless overridden."""
    decisions = tmp_path / "decisions"
    decisions.mkdir()

    for name, body in (adr_files or {}).items():
        (decisions / name).write_text(body, encoding="utf-8")

    if readme is None:
        rows = index_rows if index_rows is not None else []
        readme = (
            "# Decision log\n\n## Index\n\n"
            "| # | Title | Status | Summary |\n"
            "|---|---|---|---|\n" + "".join(f"{row}\n" for row in rows) + "\n"
            "## Accepted\n\nProse after the table.\n"
        )
    (decisions / "README.md").write_text(readme, encoding="utf-8")
    return decisions


def _row(number: str, link: str, title: str = "A title") -> str:
    return f"| [{number}]({link}) | {title} | **Accepted** | A summary |"


# --- the empty-set guards, which every other test depends on ----------------


def test_a_missing_readme_fails(checker: ModuleType, tmp_path: Path) -> None:
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    (decisions / "ADR-001-example.md").write_text("body\n", encoding="utf-8")

    problems = checker.find_defects(decisions)

    assert len(problems) == 1
    assert "not found" in problems[0]


def test_a_readme_with_no_index_heading_fails(checker: ModuleType, tmp_path: Path) -> None:
    """A parser that stops matching the heading must not report a clean index."""
    decisions = _write_decisions_dir(
        tmp_path,
        adr_files={"ADR-001-example.md": "body\n"},
        readme="# Decision log\n\nNo index heading at all here.\n",
    )

    problems = checker.find_defects(decisions)

    assert len(problems) == 1
    assert "no rows found" in problems[0]


def test_an_index_with_no_rows_fails(checker: ModuleType, tmp_path: Path) -> None:
    decisions = _write_decisions_dir(
        tmp_path, adr_files={"ADR-001-example.md": "body\n"}, index_rows=[]
    )

    problems = checker.find_defects(decisions)

    assert len(problems) == 1
    assert "no rows found" in problems[0]


def test_no_adr_files_at_all_fails(checker: ModuleType, tmp_path: Path) -> None:
    """A directory with a well-formed but empty-of-ADRs index is still vacuous."""
    decisions = _write_decisions_dir(
        tmp_path, adr_files={}, index_rows=[_row("001", "ADR-001-example.md")]
    )

    problems = checker.find_defects(decisions)

    assert len(problems) == 1
    assert "no ADR-0NN-*.md files found" in problems[0]


# --- direction 1: every ADR file has a row -----------------------------------


def test_an_adr_file_with_no_index_row_is_reported(checker: ModuleType, tmp_path: Path) -> None:
    """The actual 2026-08-21 defect: ADR-013 and ADR-014 had no row at all."""
    decisions = _write_decisions_dir(
        tmp_path,
        adr_files={
            "ADR-001-example.md": "body\n",
            "ADR-002-other.md": "body\n",
        },
        index_rows=[_row("001", "ADR-001-example.md")],
    )

    problems = checker.find_defects(decisions)

    assert len(problems) == 1
    assert "ADR-002-other.md" in problems[0]
    assert "no row" in problems[0]


def test_a_fully_indexed_directory_passes(checker: ModuleType, tmp_path: Path) -> None:
    decisions = _write_decisions_dir(
        tmp_path,
        adr_files={
            "ADR-001-example.md": "body\n",
            "ADR-002-other.md": "body\n",
        },
        index_rows=[
            _row("001", "ADR-001-example.md"),
            _row("002", "ADR-002-other.md"),
        ],
    )

    assert checker.find_defects(decisions) == []


def test_the_amendments_table_is_not_mistaken_for_the_index(
    checker: ModuleType, tmp_path: Path
) -> None:
    """`## Index` scoping matters: a lower table reuses the identical row shape.

    A row for ``ADR-002-other.md`` sitting only in an "Amendments" table below
    `## Index` must not satisfy direction 1 - that table records an
    amendment's own status, not the ADR's index entry.
    """
    readme = (
        "# Decision log\n\n## Index\n\n"
        "| # | Title | Status | Summary |\n"
        "|---|---|---|---|\n" + _row("001", "ADR-001-example.md") + "\n\n"
        "## Amendments awaiting acceptance\n\n"
        "| ADR | Amendment | Dated | Written by |\n"
        "|---|---|---|---|\n" + _row("002", "ADR-002-other.md") + "\n"
    )
    decisions = _write_decisions_dir(
        tmp_path,
        adr_files={
            "ADR-001-example.md": "body\n",
            "ADR-002-other.md": "body\n",
        },
        readme=readme,
    )

    problems = checker.find_defects(decisions)

    assert len(problems) == 1
    assert "ADR-002-other.md" in problems[0]


# --- direction 2: every index row's link resolves ----------------------------


def test_an_index_row_whose_link_is_broken_is_reported(checker: ModuleType, tmp_path: Path) -> None:
    """The one a reader cannot see: a plausible title beside a dead link."""
    decisions = _write_decisions_dir(
        tmp_path,
        adr_files={"ADR-001-example.md": "body\n"},
        index_rows=[_row("001", "ADR-001-renamed.md")],
    )

    problems = checker.find_defects(decisions)

    assert len(problems) == 2  # the broken link, and ADR-001-example.md unindexed
    assert any("ADR-001-renamed.md" in p and "does not resolve" in p for p in problems)


def test_both_directions_can_fail_independently_in_the_same_run(
    checker: ModuleType, tmp_path: Path
) -> None:
    decisions = _write_decisions_dir(
        tmp_path,
        adr_files={
            "ADR-001-example.md": "body\n",
            "ADR-002-unindexed.md": "body\n",
        },
        index_rows=[_row("003", "ADR-003-missing.md")],
    )

    problems = checker.find_defects(decisions)

    assert len(problems) == 3
    assert any("ADR-001-example.md" in p for p in problems)
    assert any("ADR-002-unindexed.md" in p for p in problems)
    assert any("ADR-003-missing.md" in p and "does not resolve" in p for p in problems)


# --- the real file, plus the mutations that keep those claims independent ---


def test_the_real_readme_index_is_clean(checker: ModuleType) -> None:
    problems = checker.find_defects(REAL_DECISIONS_DIR)
    assert problems == [], "\n".join(problems)


def test_deleting_every_real_adr_file_is_noticed(checker: ModuleType, tmp_path: Path) -> None:
    """Delete the source of truth and see whether it notices.

    Copies the real README.md verbatim but supplies no ADR files at all, which
    must fail rather than silently pass on an empty set.
    """
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    real_readme = (REAL_DECISIONS_DIR / "README.md").read_text(encoding="utf-8")
    (decisions / "README.md").write_text(real_readme, encoding="utf-8")

    problems = checker.find_defects(decisions)

    assert len(problems) == 1
    assert "no ADR-0NN-*.md files found" in problems[0]


def test_removing_a_real_index_row_is_noticed(checker: ModuleType, tmp_path: Path) -> None:
    """Independence check for `test_the_real_readme_index_is_clean`.

    An assertion that the real index is clean would keep passing if the parser
    stopped reading `## Index` rows at all. This copies the real directory and
    deletes one row, and requires the checker to notice the file it no longer
    mentions.
    """
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    for path in REAL_DECISIONS_DIR.iterdir():
        if path.is_file():
            (decisions / path.name).write_bytes(path.read_bytes())

    real_readme = (REAL_DECISIONS_DIR / "README.md").read_text(encoding="utf-8")
    mutated = real_readme.replace(
        "| [002](ADR-002-production-vs-availability.md)",
        "| [XXX](REMOVED-002.md)",
        1,
    )
    assert mutated != real_readme, "the row this test mutates is no longer in README.md"
    (decisions / "README.md").write_text(mutated, encoding="utf-8")

    problems = checker.find_defects(decisions)

    assert any("ADR-002-production-vs-availability.md" in p for p in problems)


def test_breaking_a_real_link_is_noticed(checker: ModuleType, tmp_path: Path) -> None:
    """The other independence check: mutate a real link's target, not its row."""
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    for path in REAL_DECISIONS_DIR.iterdir():
        if path.is_file():
            (decisions / path.name).write_bytes(path.read_bytes())

    real_readme = (REAL_DECISIONS_DIR / "README.md").read_text(encoding="utf-8")
    mutated = real_readme.replace(
        "(ADR-002-production-vs-availability.md)",
        "(ADR-002-production-vs-availability-typo.md)",
        1,
    )
    assert mutated != real_readme, "the link this test mutates is no longer in README.md"
    (decisions / "README.md").write_text(mutated, encoding="utf-8")

    problems = checker.find_defects(decisions)

    assert any(
        "ADR-002-production-vs-availability-typo.md" in p and "does not resolve" in p
        for p in problems
    )


# --- the CLI entry point -----------------------------------------------------


def test_the_script_runs_as_a_subprocess_against_the_real_directory() -> None:
    """Executed the way CI executes it, not merely imported.

    ``main`` returning 0 in-process does not establish that the file runs: an
    import-time error or a missing shebang path is invisible to every other
    test here.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "every index row's link resolves" in result.stdout


def test_main_reports_a_nonzero_exit_and_the_problem_on_stderr(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(checker, "find_defects", lambda: ["ADR-999-fake.md: no row"])

    exit_code = checker.main()

    assert exit_code == 1
    assert "ADR-999-fake.md: no row" in capsys.readouterr().err
