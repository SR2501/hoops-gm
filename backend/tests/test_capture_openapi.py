"""The OpenAPI recording cannot silently drift or be reformatted."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "capture_openapi.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capture_openapi", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_leaf_diff_separates_added_removed_and_changed_paths() -> None:
    module = _load_script()

    diff = module._compare(
        {"same": 1, "changed": "old", "removed": [True]},
        {"same": 1, "changed": "new", "added": {"leaf": False}},
    )

    assert diff.added == ("$.added.leaf",)
    assert diff.removed == ("$.removed[0]",)
    assert diff.changed == ("$.changed",)


def test_recording_reader_refuses_a_format_change(tmp_path: Path) -> None:
    module = _load_script()
    recording = tmp_path / "openapi.json"
    recording.write_text('{\n  "openapi": "3.1.0"\n}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="does not round-trip byte for byte"):
        module._read_round_trippable(recording)


def test_committed_recording_matches_the_served_document() -> None:
    module = _load_script()

    recorded = module._read_round_trippable(module.RECORDING)

    assert module._compare(recorded, module._served_openapi()).clean
