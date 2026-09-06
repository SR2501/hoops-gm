"""Attach RotoWire news to players only through the existing crosswalk."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import ExternalSource
from hoops_gm.db.models.identity import PlayerExternalId
from hoops_gm.ingest.preseason_news.models import (
    PreseasonNewsItem,
    PreseasonNewsResolution,
    ResolvedPreseasonNewsItem,
    UnresolvedPreseasonNewsItem,
)
from hoops_gm.ingest.preseason_news.name_evidence import name_evidence_agrees


def resolve_preseason_news(
    session: Session, items: Sequence[PreseasonNewsItem]
) -> PreseasonNewsResolution:
    """Resolve exact RotoWire IDs and independently verify their player names.

    The source namespace already exists because Fantrax ``getPlayerIds`` carries
    ``rotowireId``. No name matcher is introduced here: name is only a veto over
    the exact-id join. A missing or contradictory row remains unresolved.
    """
    links = list(
        session.scalars(
            select(PlayerExternalId).where(
                PlayerExternalId.source == ExternalSource.FANTRAX_ROTOWIRE,
                PlayerExternalId.current_for_source == ExternalSource.FANTRAX_ROTOWIRE.value,
            )
        )
    )
    if not links:
        raise RuntimeError(
            "no current fantrax_rotowire links exist; run "
            "`python -m hoops_gm.ingest.backfill crosswalk` before preseason news ingest"
        )
    by_external_id = {link.external_id: link for link in links}

    resolved: list[ResolvedPreseasonNewsItem] = []
    unresolved: list[UnresolvedPreseasonNewsItem] = []
    for item in items:
        link = by_external_id.get(item.rotowire_player_id)
        if link is None:
            unresolved.append(
                UnresolvedPreseasonNewsItem(
                    item=item,
                    reason=(
                        f"RotoWire id {item.rotowire_player_id!r} has no current "
                        "fantrax_rotowire crosswalk row"
                    ),
                )
            )
            continue
        if not link.external_name:
            unresolved.append(
                UnresolvedPreseasonNewsItem(
                    item=item,
                    reason=(
                        f"crosswalk row for RotoWire id {item.rotowire_player_id!r} "
                        "has no external_name evidence"
                    ),
                )
            )
            continue
        if not name_evidence_agrees(link.external_name, item.player_name):
            unresolved.append(
                UnresolvedPreseasonNewsItem(
                    item=item,
                    reason=(
                        f"feed name {item.player_name!r} contradicts crosswalk name "
                        f"{link.external_name!r} for RotoWire id {item.rotowire_player_id!r}"
                    ),
                )
            )
            continue
        resolved.append(
            ResolvedPreseasonNewsItem(
                item=item,
                player_id=link.player_id,
                crosswalk_external_name=link.external_name,
            )
        )

    return PreseasonNewsResolution(resolved=tuple(resolved), unresolved=tuple(unresolved))
