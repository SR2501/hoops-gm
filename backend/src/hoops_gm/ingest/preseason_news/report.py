"""Write a local, auditable preseason-news snapshot for draft-day consumers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hoops_gm.ingest.preseason_news.models import (
    PreseasonNewsItem,
    PreseasonNewsResolution,
    PreseasonNewsSnapshot,
)
from hoops_gm.ingest.preseason_news.parser import RSS_URL, SOURCE

REPORT_SCHEMA_VERSION = 1


def write_preseason_news_report(
    path: Path,
    *,
    snapshot: PreseasonNewsSnapshot,
    resolution: PreseasonNewsResolution,
) -> None:
    """Atomically publish resolved items and explicit identity refusals."""
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "source": SOURCE,
        "source_url": RSS_URL,
        "source_observed_at": snapshot.observed_at.isoformat(),
        "source_payload_sha256": snapshot.source_payload_sha256,
        "feed_ttl_minutes": snapshot.feed.ttl_minutes,
        "item_count": len(snapshot.feed.items),
        "resolved_count": len(resolution.resolved),
        "unresolved_count": len(resolution.unresolved),
        "items": [
            {
                **_item_payload(result.item),
                "player_id": result.player_id,
                "identity_source": "fantrax_rotowire",
                "crosswalk_external_name": result.crosswalk_external_name,
            }
            for result in resolution.resolved
        ],
        "unresolved": [
            {**_item_payload(result.item), "reason": result.reason}
            for result in resolution.unresolved
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _item_payload(item: PreseasonNewsItem) -> dict[str, Any]:
    return {
        "guid": item.guid,
        "rotowire_player_id": item.rotowire_player_id,
        "player_name": item.player_name,
        "headline": item.headline,
        "description": item.description,
        "published_at": item.published_at.isoformat(),
        "published_at_raw": item.published_at_raw,
        "link": item.link,
    }
