"""The OpenAPI recording cannot silently drift or be reformatted."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
from types import ModuleType

import pytest

from hoops_gm.core.bridge_pairing import BridgePairing

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


def test_recording_format_is_platform_independent_lf() -> None:
    module = _load_script()

    serialized = module._serialized({"openapi": "3.1.0"})
    assert serialized.endswith(b"}\n")
    assert b"\r\n" not in serialized


def test_served_document_uses_disposable_pairing_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setenv("BRIDGE_SECRET_PATH", str(tmp_path / "not-the-capture-secret"))
    reads: list[Path] = []
    original_read = BridgePairing._read_secret

    def read_disposable_secret(pairing: BridgePairing) -> str | None:
        path = pairing.secret_path
        assert path.parent.parent == tmp_path
        assert path.parent.is_dir()
        assert not path.exists()
        reads.append(path)
        return original_read(pairing)

    monkeypatch.setattr(BridgePairing, "_read_secret", read_disposable_secret)

    document = module._served_openapi()

    assert document["openapi"].startswith("3.")
    assert len(reads) == 1
    assert not reads[0].parent.exists()


def test_committed_recording_matches_the_served_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    monkeypatch.setenv("LOG_LEVEL", "NOT_A_LEVEL")
    monkeypatch.setenv("PORT", "not-a-port")
    monkeypatch.setenv("CORS_ORIGINS", "not-json")

    recorded = module._read_round_trippable(module.RECORDING)

    assert module._compare(recorded, module._served_openapi()).clean
