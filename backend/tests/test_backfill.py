from dataclasses import replace
from datetime import date
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from hoops_gm.ingest import backfill
from hoops_gm.ingest.backfill import (
    _league_game_finder_season_type,
    _participation_games_in_scope,
    _require_matching_season_game_ids,
    _validate_summary_game_identity,
)
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.importers import ImportCounts
from hoops_gm.ingest.nba.client import NbaStatsClient
from hoops_gm.ingest.nba.models import NbaGameRecord, PlayerBoxScoreRecord


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


def _log(game_id: str) -> PlayerBoxScoreRecord:
    return PlayerBoxScoreRecord(
        nba_player_id=10,
        nba_game_id=game_id,
        nba_team_id=1,
        player_name="Test Player",
    )


def test_season_sources_must_name_exactly_the_same_games() -> None:
    games = [
        _game("0022500001", date(2025, 10, 21)),
        _game("0022500002", date(2025, 10, 22)),
    ]

    _require_matching_season_game_ids(
        games,
        [_log("0022500001"), _log("0022500002"), _log("0022500002")],
        season="2025-26",
        season_type="Regular Season",
    )

    with pytest.raises(
        SourceContractError,
        match=r"LeagueGameFinder=2, PlayerGameLogs=2.*0022500002.*0022500003",
    ):
        _require_matching_season_game_ids(
            games,
            [_log("0022500001"), _log("0022500003")],
            season="2025-26",
            season_type="Regular Season",
        )


def test_season_backfill_reconciles_both_sources_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Source:
        def league_game_finder(self, *, season: str, season_type: str) -> object:
            del season, season_type
            return object()

        def player_game_logs(self, *, season: str, season_type: str) -> object:
            del season, season_type
            return object()

    games = [_game("0022500001", date(2025, 10, 21))]
    logs = [_log("0022500002")]
    monkeypatch.setattr(backfill, "parse_league_game_finder", lambda *args, **kwargs: games)
    monkeypatch.setattr(backfill, "parse_player_game_logs", lambda *args, **kwargs: logs)

    def unexpected_write(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("season persistence ran before source reconciliation")

    monkeypatch.setattr(backfill, "import_games", unexpected_write)
    monkeypatch.setattr(backfill, "import_box_scores", unexpected_write)

    with pytest.raises(SourceContractError, match="game identity mismatch"):
        backfill.backfill_season(
            cast(Session, object()),
            nba=cast(NbaStatsClient, Source()),
            season="2025-26",
        )


def test_nba_identity_backfill_imports_teams_before_players(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anchors must be imported in dependency order, from official NBA identity only."""

    class Source:
        def static_teams(self) -> object:
            return "teams-payload"

        def common_all_players(self, *, season: str, only_current: bool) -> object:
            assert season == "2025-26"
            assert only_current is False
            return "players-payload"

    order: list[str] = []
    monkeypatch.setattr(backfill, "parse_teams", lambda payload: [payload])
    monkeypatch.setattr(backfill, "parse_common_all_players", lambda payload: [payload])

    def record(name: str) -> Any:
        def importer(session: Session, records: Any) -> ImportCounts:
            del session
            order.append(f"{name}:{records[0]}")
            return ImportCounts(created=len(records))

        return importer

    monkeypatch.setattr(backfill, "import_teams", record("teams"))
    monkeypatch.setattr(backfill, "import_nba_players", record("players"))

    result = backfill.backfill_nba_identity(
        cast(Session, object()),
        nba=cast(NbaStatsClient, Source()),
        season="2025-26",
        progress=lambda _: None,
    )

    assert order == ["teams:teams-payload", "players:players-payload"]
    assert result.steps["teams"].created == 1
    assert result.steps["nba players"].created == 1
