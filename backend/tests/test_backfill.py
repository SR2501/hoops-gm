from datetime import date

import pytest

from hoops_gm.ingest.backfill import _participation_games_in_scope
from hoops_gm.ingest.nba.models import NbaGameRecord


def _game(game_id: str, game_date: date) -> NbaGameRecord:
    return NbaGameRecord(
        nba_game_id=game_id,
        season="2025-26",
        season_type="regular",
        game_date=game_date,
        home_team_id=1,
        away_team_id=2,
    )


def test_participation_scope_applies_inclusive_dates_before_limit() -> None:
    games = [
        _game("before", date(2025, 12, 7)),
        _game("first", date(2025, 12, 8)),
        _game("second", date(2025, 12, 9)),
        _game("last", date(2026, 1, 4)),
        _game("after", date(2026, 1, 5)),
    ]

    selected = _participation_games_in_scope(
        games,
        start=date(2025, 12, 8),
        end=date(2026, 1, 4),
        limit_games=2,
    )

    assert [game.nba_game_id for game in selected] == ["first", "second"]


def test_participation_scope_treats_zero_limit_as_zero_games() -> None:
    selected = _participation_games_in_scope(
        [_game("game", date(2025, 12, 8))],
        start=None,
        end=None,
        limit_games=0,
    )

    assert selected == []


def test_participation_scope_rejects_inverted_dates() -> None:
    with pytest.raises(ValueError, match="after end date"):
        _participation_games_in_scope(
            [],
            start=date(2026, 1, 4),
            end=date(2025, 12, 8),
            limit_games=None,
        )


def test_participation_scope_rejects_negative_limit() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _participation_games_in_scope([], start=None, end=None, limit_games=-1)
