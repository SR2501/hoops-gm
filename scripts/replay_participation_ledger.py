"""Replay a participation season from exact raw captures, with no network path.

The production NBA client intentionally refreshes season-level listings after
12 hours. That is correct for normal ingestion and wrong for reproducing a
published census. This command replaces its endpoint factory with a manifest-
pinned reader: every request must resolve to one named gzip capture whose
uncompressed SHA-256 matches, and every manifest entry must be consumed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hoops_gm.core.config import Settings
from hoops_gm.db.session import Database
from hoops_gm.ingest.backfill import backfill_season
from hoops_gm.ingest.nba.client import NbaStatsClient
from hoops_gm.ingest.rawstore import canonical_params
from hoops_gm.ingest.throttle import RateLimiter


@dataclass(frozen=True)
class _RecordedEndpoint:
    payload: Any

    def get_dict(self) -> Any:
        return self.payload


class PinnedCaptureFactory:
    """Serve exactly the captures named by a frozen manifest."""

    def __init__(self, raw_root: Path, manifest_path: Path, *, season: str) -> None:
        self.raw_root = raw_root.resolve()
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError("pinned replay manifest schema_version must be 1")
        if payload.get("season") != season:
            raise ValueError(f"manifest season {payload.get('season')!r} does not match {season!r}")

        entries: dict[tuple[str, str], dict[str, Any]] = {}
        for entry in payload.get("entries", []):
            endpoint = str(entry["endpoint"])
            params = canonical_params(entry["params"])
            key = (endpoint, params)
            if key in entries:
                raise ValueError(f"duplicate pinned request {endpoint} {params}")
            entries[key] = entry
        if not entries:
            raise ValueError("pinned replay manifest contains no entries")
        self.entries = entries
        self.consumed: set[tuple[str, str]] = set()

    def __call__(self, endpoint: str, **kwargs: Any) -> _RecordedEndpoint:
        kwargs.pop("timeout", None)
        params = canonical_params(kwargs)
        key = (endpoint, params)
        entry = self.entries.get(key)
        if entry is None:
            raise ValueError(f"request is not pinned: {endpoint} {params}")

        capture = (self.raw_root / str(entry["path"])).resolve()
        if not capture.is_relative_to(self.raw_root):
            raise ValueError(f"capture path escapes raw root: {entry['path']}")
        if not capture.is_file():
            raise FileNotFoundError(capture)

        with gzip.open(capture, "rb") as handle:
            body = handle.read()
        observed = hashlib.sha256(body).hexdigest()
        expected = str(entry["content_sha256"])
        if observed != expected:
            raise ValueError(
                f"capture digest mismatch for {endpoint} {params}: "
                f"expected {expected}, observed {observed}"
            )

        self.consumed.add(key)
        return _RecordedEndpoint(json.loads(body))

    def require_all_consumed(self) -> None:
        unused = sorted(set(self.entries) - self.consumed)
        if unused:
            raise RuntimeError(
                f"{len(unused)} pinned replay requests were not consumed: {unused[:5]}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("raw_root", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("season")
    args = parser.parse_args()

    factory = PinnedCaptureFactory(args.raw_root, args.manifest, season=args.season)
    client = NbaStatsClient(
        store=None,
        limiter=RateLimiter(0),
        endpoint_factory=factory,
    )
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{args.database.resolve().as_posix()}",
        _env_file=None,
    )
    database = Database.from_settings(settings)
    try:
        with database.session() as session:
            result = backfill_season(
                session,
                nba=client,
                season=args.season,
                with_participation=True,
            )
    finally:
        database.dispose()

    factory.require_all_consumed()
    skipped = sum(step.skipped for step in result.steps.values())
    if result.failures or skipped:
        raise RuntimeError(
            f"offline replay did not converge: failures={result.failures}, skipped={skipped}"
        )
    print(result.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
