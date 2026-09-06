"""The committed schedule-grid specimen is produced by its Pydantic response model."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import BaseModel

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "capture_schedule_grid_contract.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capture_schedule_grid_contract", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_committed_contract_matches_a_serialized_schedule_grid_response() -> None:
    module = _load_script()

    assert module._strict_equal(module._read_document(module.CONTRACT), module._response_document())


def test_contract_comparison_is_semantic_not_byte_based(tmp_path: Path) -> None:
    module = _load_script()
    reformatted = tmp_path / "schedule-grid.json"
    reformatted.write_text(
        module._serialized(module._response_document()).replace("  ", "    "),
        encoding="utf-8",
    )

    assert module._strict_equal(module._read_document(reformatted), module._response_document())


def test_contract_comparison_rejects_a_scalar_annotation_change() -> None:
    module = _load_script()

    class IntegerCount(BaseModel):
        games: int

    class BooleanCount(BaseModel):
        games: bool

    integer_document = IntegerCount(games=1).model_dump(mode="json")
    boolean_document = BooleanCount(games=True).model_dump(mode="json")
    assert integer_document == boolean_document  # Proves ordinary dict equality misses the drift.

    assert not module._strict_equal(integer_document, boolean_document)


def test_check_exits_nonzero_for_an_equivalent_value_with_a_different_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_script()
    contract = tmp_path / "schedule-grid.json"
    recorded = module._response_document()
    contract.write_text(module._serialized(recorded), encoding="utf-8")
    assert module._strict_equal(module._read_document(contract), module._response_document())

    actual = module._response_document()
    periods = actual["periods"]
    assert isinstance(periods, list)
    first_period = periods[0]
    assert isinstance(first_period, dict)
    assert first_period["is_playoff"] is False
    first_period["is_playoff"] = 0
    assert first_period["is_playoff"] == recorded["periods"][0]["is_playoff"]

    monkeypatch.setattr(module, "CONTRACT", contract)
    monkeypatch.setattr(module, "_response_document", lambda: actual)

    assert module.main(["--check"]) == 1
