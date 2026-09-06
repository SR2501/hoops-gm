"""Negative controls for ``scripts/check_adr_index.py``.

A consistency checker that passes on a consistent repository has demonstrated
nothing: so would a checker that returns ``[]`` unconditionally. Every invariant
below is therefore driven by a mutation that must make it fire, and two of the
tests exist because the first version of this checker - written as a throwaway
diagnostic - reported **eighteen** confident disagreements that were all false.

Both of its bugs are pinned here:

* ADR headers use ``**Status:**`` (ADR-001..015) and ``- **Status:**``
  (ADR-017 onward). Matching one shape reports every file in the other as having
  no status line at all.
* ``README.md`` contains more than one table, so scanning the whole file lets a
  later table's rows overwrite index rows.

The reserved-number exemption gets a mutation of its own, because an exemption
that fires unconditionally is indistinguishable from no check at all.
"""

from __future__ import annotations

import importlib.util
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


_README = """# Decisions

## Index

| ADR | Title | Status | Summary |
| --- | --- | --- | --- |
| [001](ADR-001-alpha.md) | Alpha | **Accepted** | First. |
| [002](ADR-002-beta.md) | Beta | **Proposed** | Second. |
| [003](ADR-003-gamma.md) | Gamma | **Reserved** | Held free. |

**003 is unwritten and reserved.** Another document references it by number.

## Conventions

| ADR | Note | Status |
| --- | --- | --- |
| [001](ADR-001-alpha.md) | Example row | **Superseded** |
"""

# Deliberately two shapes: the baseline itself exercises both, so a regex that
# handles only one fails here rather than in a year.
_ALPHA = "# ADR-001: Alpha\n\n**Status:** Accepted\n\nBody.\n"
_BETA = "# ADR-002: Beta\n\n- **Status:** Proposed\n- **Date:** 2026-09-06\n\nBody.\n"


def _synthetic(tmp_path: Path, *, readme: str = _README) -> Path:
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    (decisions / "README.md").write_text(readme, encoding="utf-8")
    (decisions / "ADR-001-alpha.md").write_text(_ALPHA, encoding="utf-8")
    (decisions / "ADR-002-beta.md").write_text(_BETA, encoding="utf-8")
    return decisions


def test_synthetic_baseline_is_clean(checker: ModuleType, tmp_path: Path) -> None:
    """The control. Every mutation below is a one-line edit away from this."""
    assert checker.problems(_synthetic(tmp_path)) == []


def test_real_repository_index_is_consistent(checker: ModuleType) -> None:
    found = checker.problems(REAL_DECISIONS)
    assert found == [], "docs/decisions/README.md has drifted from the ADR files:\n" + "\n".join(
        found
    )


def test_file_missing_from_index_is_reported(checker: ModuleType, tmp_path: Path) -> None:
    """Invariant A - the drift that actually happened, to ADR-017, in August."""
    decisions = _synthetic(tmp_path)
    (decisions / "ADR-004-delta.md").write_text(
        "# ADR-004: Delta\n\n**Status:** Proposed\n", encoding="utf-8"
    )

    found = checker.problems(decisions)

    assert any("ADR-004" in line and "no row" in line for line in found), found


def test_index_row_without_a_file_is_reported(checker: ModuleType, tmp_path: Path) -> None:
    """Invariant B - a row pointing at a file nobody wrote, and not reserved."""
    readme = _README.replace(
        "| [002](ADR-002-beta.md) | Beta | **Proposed** | Second. |",
        "| [002](ADR-002-beta.md) | Beta | **Proposed** | Second. |\n"
        "| [009](ADR-009-nope.md) | Nope | **Proposed** | Never written. |",
    )
    decisions = _synthetic(tmp_path, readme=readme)

    found = checker.problems(decisions)

    assert any("ADR-009" in line and "does not exist" in line for line in found), found


def test_status_disagreement_is_reported(checker: ModuleType, tmp_path: Path) -> None:
    """Invariant C - the index still says Proposed after the owner accepted it.

    This is the expensive one: an ADR the owner has accepted, still advertised
    as a proposal, is read by the next agent as a decision it may reopen.
    """
    decisions = _synthetic(tmp_path)
    (decisions / "ADR-002-beta.md").write_text(
        _BETA.replace("Proposed", "Accepted"), encoding="utf-8"
    )

    found = checker.problems(decisions)

    assert any("ADR-002" in line and "disagrees" in line for line in found), found


def test_dash_prefixed_status_is_read(checker: ModuleType, tmp_path: Path) -> None:
    """The first bug: ADR-002 uses ``- **Status:**`` and must not read as blank.

    Asserted from both sides. A regex matching only ``**Status:**`` would report
    "no Status line" on the clean baseline, and - worse - would report *nothing*
    when that file's status genuinely drifts, because an empty status short-
    circuits the comparison.
    """
    decisions = _synthetic(tmp_path)
    assert checker.statuses_from_files(decisions)["002"] == "Proposed"

    clean = checker.problems(decisions)
    assert not any("no '**Status:**' line" in line for line in clean), clean


def test_rows_outside_the_index_section_are_ignored(checker: ModuleType, tmp_path: Path) -> None:
    """The second bug: the ``## Conventions`` table also has an ADR-001 row.

    It says ``Superseded`` where the index says ``Accepted``. Scanning the whole
    file lets it overwrite the index row and manufacture a disagreement - which
    is precisely how eighteen false findings were produced.
    """
    decisions = _synthetic(tmp_path)
    rows = checker.rows_from_index(
        checker.index_section((decisions / "README.md").read_text(encoding="utf-8"))
    )

    assert rows["001"][1] == "Accepted", rows
    assert set(rows) == {"001", "002", "003"}, rows


def test_reserved_number_is_exempt_from_invariant_b(checker: ModuleType, tmp_path: Path) -> None:
    """ADR-003 is listed with no file and must pass, because prose says so.

    The live counterpart is ADR-016, held free because four coordinator-register
    entries reference "whenever ADR-016 is written". A checker that flagged it
    would be demanding the index stop explaining itself.
    """
    decisions = _synthetic(tmp_path)
    assert checker.reserved_numbers((decisions / "README.md").read_text(encoding="utf-8")) == {
        "003"
    }
    assert checker.problems(decisions) == []


def test_reserved_exemption_is_load_bearing(checker: ModuleType, tmp_path: Path) -> None:
    """Delete the sentence, keep everything else, and ADR-003 must now fail.

    Without this, an exemption that matched every number would look identical to
    a working one on every consistent repository.
    """
    readme = _README.replace(
        "**003 is unwritten and reserved.** Another document references it by number.\n",
        "",
    )
    decisions = _synthetic(tmp_path, readme=readme)

    found = checker.problems(decisions)

    assert any("ADR-003" in line and "does not exist" in line for line in found), found


def test_detail_after_the_status_word_is_not_drift(checker: ModuleType, tmp_path: Path) -> None:
    """ADR-020 reads ``Accepted, including both amendments``; the index says
    ``Accepted``. Comparing whole strings would report that as drift and train
    everyone to ignore the checker."""
    decisions = _synthetic(tmp_path)
    (decisions / "ADR-001-alpha.md").write_text(
        _ALPHA.replace("Accepted", "Accepted, including both amendments"), encoding="utf-8"
    )

    assert checker.problems(decisions) == []


def test_cli_exit_codes(checker: ModuleType, tmp_path: Path) -> None:
    """Exit 1 on drift, 0 when clean - the only part CI actually reads."""
    decisions = _synthetic(tmp_path)
    assert checker.main(["--decisions", str(decisions)]) == 0

    (decisions / "ADR-002-beta.md").write_text(
        _BETA.replace("Proposed", "Accepted"), encoding="utf-8"
    )
    assert checker.main(["--decisions", str(decisions)]) == 1
