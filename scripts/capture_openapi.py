"""Record the served OpenAPI document, or fail when the recording has drifted."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
RECORDING = REPO_ROOT / "frontend" / "src" / "test" / "fixtures" / "openapi.recorded.json"


@dataclass(frozen=True)
class OpenApiDiff:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not (self.added or self.removed or self.changed)


def _serialized(document: object) -> bytes:
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    return f"{text}\r\n".encode()


def _flatten(value: object, *, path: str = "$") -> dict[str, object]:
    if isinstance(value, dict):
        if not value:
            return {path: {}}
        leaves: dict[str, object] = {}
        for key in sorted(value):
            leaves.update(_flatten(value[key], path=f"{path}.{key}"))
        return leaves
    if isinstance(value, list):
        if not value:
            return {path: []}
        leaves = {}
        for index, item in enumerate(value):
            leaves.update(_flatten(item, path=f"{path}[{index}]"))
        return leaves
    return {path: value}


def _compare(recorded: object, served: object) -> OpenApiDiff:
    recorded_leaves = _flatten(recorded)
    served_leaves = _flatten(served)
    recorded_paths = set(recorded_leaves)
    served_paths = set(served_leaves)
    return OpenApiDiff(
        added=tuple(sorted(served_paths - recorded_paths)),
        removed=tuple(sorted(recorded_paths - served_paths)),
        changed=tuple(
            sorted(
                path
                for path in recorded_paths & served_paths
                if recorded_leaves[path] != served_leaves[path]
            )
        ),
    )


def _read_round_trippable(path: Path) -> object:
    raw = path.read_bytes()
    document: object = json.loads(raw)
    if _serialized(document) != raw:
        raise ValueError(
            f"{path} does not round-trip byte for byte; refusing to hide a reformat as drift"
        )
    return document


def _served_openapi() -> dict[str, Any]:
    sys.path.insert(0, str(BACKEND_SRC))
    from hoops_gm.app import create_app
    from hoops_gm.core.config import Settings

    settings = Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        environment="test",
        host="127.0.0.1",
    )
    return create_app(settings=settings).openapi()


def _print_diff(diff: OpenApiDiff) -> None:
    for label, paths in (
        ("added", diff.added),
        ("removed", diff.removed),
        ("changed", diff.changed),
    ):
        print(f"{label}: {len(paths)}")
        for path in paths:
            print(f"  {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of updating when the served document differs",
    )
    args = parser.parse_args(argv)

    try:
        recorded = _read_round_trippable(RECORDING)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    served = _served_openapi()
    diff = _compare(recorded, served)
    _print_diff(diff)
    if args.check:
        return 0 if diff.clean else 1

    RECORDING.write_bytes(_serialized(served))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
