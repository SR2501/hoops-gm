from dataclasses import replace
from datetime import date

import pytest

from hoops_gm.ingest.backfill import (
    _league_game_finder_season_type,
    _participation_games_in_scope,
    _validate_summary_game_identity,
)
from hoops_gm.ingest.errors import SourceContractError
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


@pytest.mark.parametrize(
    ("source_label", "parsed"),
    [("Regular Season", "regular"), ("Playoffs", "playoffs")],
)
def test_league_game_finder_season_type_maps_only_supported_labels(
    source_label: str, parsed: str
) -> None:
    assert _league_game_finder_season_type(source_label) == parsed


def test_league_game_finder_season_type_rejects_unsupported_labels() -> None:
    with pytest.raises(ValueError, match="unsupported NBA season type 'Pre Season'"):
        _league_game_finder_season_type("Pre Season")


def test_summary_identity_must_agree_with_schedule_identity() -> None:
    schedule = _game("0022500001", date(2025, 10, 21))
    summary = replace(schedule, tipoff_utc=None)

    _validate_summary_game_identity(schedule, summary)

    with pytest.raises(SourceContractError, match="home_team_id=1/2"):
        _validate_summary_game_identity(
            schedule,
            replace(summary, home_team_id=2, away_team_id=1),
        )
