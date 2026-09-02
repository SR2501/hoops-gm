from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.adapter_contract

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "replay_participation_ledger.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("replay_participation_ledger", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifest(
    tmp_path: Path,
    *,
    body: bytes = b'{"resultSets": []}',
    digest: str | None = None,
    relative_path: str = "nba_stats/Test/abc/capture.json.gz",
) -> tuple[Path, Path]:
    raw_root = tmp_path / "raw"
    capture = raw_root / relative_path
    capture.parent.mkdir(parents=True)
    with gzip.open(capture, "wb") as handle:
        handle.write(body)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "season": "2022-23",
                "entries": [
                    {
                        "endpoint": "Test",
                        "params": {"season": "2022-23"},
                        "path": relative_path,
                        "content_sha256": digest or hashlib.sha256(body).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return raw_root, manifest


def test_pinned_factory_returns_only_the_exact_recorded_request(tmp_path: Path) -> None:
    module = _load_script()
    raw_root, manifest = _manifest(tmp_path)
    factory = module.PinnedCaptureFactory(raw_root, manifest, season="2022-23")

    endpoint = factory("Test", timeout=60, season="2022-23")

    assert endpoint.get_dict() == {"resultSets": []}
    factory.require_all_consumed()
    with pytest.raises(ValueError, match="request is not pinned"):
        factory("Other", season="2022-23")


def test_pinned_factory_refuses_changed_capture_bytes(tmp_path: Path) -> None:
    module = _load_script()
    raw_root, manifest = _manifest(tmp_path, digest="0" * 64)
    factory = module.PinnedCaptureFactory(raw_root, manifest, season="2022-23")

    with pytest.raises(ValueError, match="capture digest mismatch"):
        factory("Test", season="2022-23")


def test_pinned_factory_refuses_an_unconsumed_manifest_entry(tmp_path: Path) -> None:
    module = _load_script()
    raw_root, manifest = _manifest(tmp_path)
    factory = module.PinnedCaptureFactory(raw_root, manifest, season="2022-23")

    with pytest.raises(RuntimeError, match="1 pinned replay requests were not consumed"):
        factory.require_all_consumed()


def test_pinned_factory_refuses_a_capture_outside_the_raw_root(tmp_path: Path) -> None:
    module = _load_script()
    raw_root, manifest = _manifest(tmp_path)
    payload: dict[str, Any] = json.loads(manifest.read_text(encoding="utf-8"))
    payload["entries"][0]["path"] = "../capture.json.gz"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    factory = module.PinnedCaptureFactory(raw_root, manifest, season="2022-23")

    with pytest.raises(ValueError, match="escapes raw root"):
        factory("Test", season="2022-23")
