"""Typed records from the NBA's official transaction feeds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class NbaPlayerMovementRecord:
    """One row from the NBA player-movement archive.

    ``nba_player_id`` is absent for consideration-only trade rows. Those rows
    remain in the parsed result rather than disappearing silently.
    """

    transaction_type: str
    transaction_date: date
    transaction_description: str
    nba_team_id: int
    team_slug: str
    nba_player_id: int | None
    player_slug: str | None
    related_team_id: int | None
    group_sort: str


@dataclass(frozen=True)
class GLeagueTransactionRecord:
    """One row from the NBA G League transaction archive."""

    transaction_type: str
    transaction_date: date
    transaction_description: str
    g_league_team_id: int | None
    team_slug: str | None
    nba_player_id: int
    player_slug: str
    related_team_id: int | None
    group_sort: str
