from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from hoops_gm.db.models.league import League, ScoringPeriod
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.importers import import_schedule, import_teams
from hoops_gm.ingest.nba import (
    NbaStatsClient,
    NbaTeamRecord,
    parse_schedule,
    parse_teams,
    scheduled_game_counts,
)

pytestmark = pytest.mark.adapter_contract
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_schedule_fixture_resolves_games_and_reconciles_the_two_time_fields() -> None:
    result = parse_schedule(load("nba_scheduleleaguev2_2026_27.json"), season="2026-27")

    assert result.source_game_count == 12
    assert len(result.games) == 10
    assert result.unresolved_game_ids == ("0022601201", "0022601202")
    assert result.games[0].game.game_date == date(2026, 10, 20)
    assert result.games[0].game.tipoff_utc is not None
    assert result.games[0].game.tipoff_utc.hour == 19


def test_schedule_team_ids_and_tricodes_agree_with_static_team_source() -> None:
    result = parse_schedule(load("nba_scheduleleaguev2_2026_27.json"), season="2026-27")
    static = {
        team.nba_team_id: team.abbreviation for team in parse_teams(load("nba_static_teams.json"))
    }

    for record in result.games:
        assert static[record.home_nba_team_id] == record.home_tricode
        assert static[record.away_nba_team_id] == record.away_tricode


def test_schedule_parser_rejects_a_mismatched_time_sibling() -> None:
    payload = load("nba_scheduleleaguev2_2026_27.json")
    payload["leagueSchedule"]["gameDates"][0]["games"][0]["gameDateTimeUTC"] = (
        "2026-10-20T20:00:00Z"
    )

    with pytest.raises(SourceContractError, match="inconsistent EST/UTC"):
        parse_schedule(payload, season="2026-27")


def test_schedule_client_uses_the_official_schedule_endpoint() -> None:
    calls: list[dict[str, object]] = []

    class Endpoint:
        def get_dict(self) -> dict[str, object]:
            return {"leagueSchedule": {"seasonYear": "2026-27", "gameDates": []}}

    def factory(endpoint: str, **kwargs: object) -> Endpoint:
        calls.append({"endpoint": endpoint, **kwargs})
        return Endpoint()

    client = NbaStatsClient(endpoint_factory=factory)
    client.schedule_league(season="2026-27")

    assert calls == [
        {
            "endpoint": "ScheduleLeagueV2",
            "timeout": 60.0,
            "league_id": "00",
            "season": "2026-27",
        }
    ]


def test_schedule_import_is_idempotent_and_counts_against_scoring_periods(session: Any) -> None:
    result = parse_schedule(load("nba_scheduleleaguev2_2026_27.json"), season="2026-27")
    team_ids = {
        team_id
        for record in result.games
        for team_id in (record.home_nba_team_id, record.away_nba_team_id)
    }
    import_teams(
        session,
        [
            NbaTeamRecord(team_id, f"T{team_id % 10_000_000:07d}", f"Team {team_id}")
            for team_id in sorted(team_ids)
        ],
    )
    league = League(
        name="Test league",
        season="2026-27",
        scoring_type="h2h_categories",
        draft_type="auction",
    )
    session.add(league)
    session.flush()
    session.add(
        ScoringPeriod(
            league_id=league.id,
            period_number=1,
            start_date=date(2026, 10, 19),
            end_date=date(2026, 10, 25),
        )
    )
    session.flush()

    first = import_schedule(session, result.games)
    second = import_schedule(session, result.games)
    counts = scheduled_game_counts(session, league_id=league.id, season="2026-27")

    assert first.created == 30
    assert second.updated == 30
    assert session.scalars(select(TeamScheduleEntry)).all()
    assert len(counts) == 6
    assert {row.games for row in counts} == {1}
