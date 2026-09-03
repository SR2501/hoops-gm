"""Loud live smoke tests for the official NBA transaction archives."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from hoops_gm.ingest.nba_transactions import (
    G_LEAGUE_TYPE_DESCRIPTIONS,
    NBA_PLAYER_MOVEMENT_TYPES,
    NbaOfficialTransactionsClient,
)

pytestmark = pytest.mark.live_smoke
NO_CACHE = timedelta(0)


@pytest.fixture(scope="module")
def transactions() -> NbaOfficialTransactionsClient:
    return NbaOfficialTransactionsClient()


def test_nba_player_movement_archive_retains_historical_roster_changes(
    transactions: NbaOfficialTransactionsClient,
) -> None:
    """FAILS IF: the NBA archive disappears, shrinks, or changes shape/vocabulary."""
    records = transactions.nba_player_movements(max_age=NO_CACHE)

    assert len(records) >= 9700, "NBA player-movement history unexpectedly shrank"
    assert {record.transaction_type for record in records} == NBA_PLAYER_MOVEMENT_TYPES
    assert min(record.transaction_date for record in records) <= date(2015, 7, 1)
    assert max(record.transaction_date for record in records) >= date(2026, 9, 2)
    assert any(
        record.nba_player_id == 201144
        and record.transaction_date == date(2026, 2, 3)
        and record.transaction_type == "Trade"
        and record.related_team_id == 1610612750
        for record in records
    ), "the historical Mike Conley trade anchor disappeared"


def test_g_league_archive_retains_assignment_and_recall_evidence(
    transactions: NbaOfficialTransactionsClient,
) -> None:
    """FAILS IF: the G League archive loses assignment/recall history or drifts."""
    records = transactions.g_league_transactions(max_age=NO_CACHE)

    assert len(records) >= 14000, "G League transaction history unexpectedly shrank"
    assert {record.transaction_type for record in records} == set(G_LEAGUE_TYPE_DESCRIPTIONS)
    assert min(record.transaction_date for record in records) <= date(2021, 8, 3)
    assert max(record.transaction_date for record in records) >= date(2026, 8, 31)
    assert any(
        record.nba_player_id == 1630164
        and record.transaction_date == date(2022, 11, 15)
        and record.transaction_description == "Assigned"
        for record in records
    ), "the historical James Wiseman assignment anchor disappeared"
    assert any(
        record.nba_player_id == 1630164
        and record.transaction_date == date(2022, 12, 15)
        and record.transaction_description == "Recalled"
        for record in records
    ), "the historical James Wiseman recall anchor disappeared"
