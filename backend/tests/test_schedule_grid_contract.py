"""The committed schedule-grid specimen is produced by its Pydantic response model."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

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

    assert module._read_document(module.CONTRACT) == module._response_document()


def test_contract_comparison_is_semantic_not_byte_based(tmp_path: Path) -> None:
    module = _load_script()
    reformatted = tmp_path / "schedule-grid.json"
    reformatted.write_text(
        module._serialized(module._response_document()).replace("  ", "    "),
        encoding="utf-8",
    )

    assert module._read_document(reformatted) == module._response_document()
