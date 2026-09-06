"""Loud live smoke test for the draft-day preseason news source."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hoops_gm.ingest.fantrax_official import FantraxOfficialClient
from hoops_gm.ingest.preseason_news import PreseasonNewsClient
from hoops_gm.ingest.preseason_news.name_evidence import name_evidence_agrees

pytestmark = pytest.mark.live_smoke
NO_CACHE = timedelta(0)


def test_latest_news_is_fresh_and_joins_the_live_fantrax_identity_surface() -> None:
    """FAILS IF: the feed stalls, changes contract, or loses its Fantrax ID seam."""
    snapshot = PreseasonNewsClient().latest(max_age=NO_CACHE)
    fantrax = FantraxOfficialClient().get_player_ids(max_age=NO_CACHE)
    fantrax_by_rotowire = {
        player.rotowire_id: player for player in fantrax.players if player.rotowire_id is not None
    }

    assert snapshot.feed.items, "RotoWire returned no NBA news items"
    newest = snapshot.feed.items[0]
    assert datetime.now(UTC) - newest.published_at <= timedelta(days=14), (
        f"newest NBA news item is stale: {newest.published_at.isoformat()}"
    )
    overlapping = [
        item for item in snapshot.feed.items if item.rotowire_player_id in fantrax_by_rotowire
    ]
    assert overlapping, "no current news item shares a RotoWire id with Fantrax getPlayerIds"
    for item in overlapping:
        fantrax_player = fantrax_by_rotowire[item.rotowire_player_id]
        assert name_evidence_agrees(item.player_name, fantrax_player.name), (
            f"RotoWire id {item.rotowire_player_id} names {item.player_name!r} in the "
            f"feed but {fantrax_player.name!r} in Fantrax"
        )
