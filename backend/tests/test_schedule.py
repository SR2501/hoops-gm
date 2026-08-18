from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.lineage import check_cohort, current_refresh
from hoops_gm.db.models.enums import RefreshArtifactType, SeasonType
from hoops_gm.db.models.identity import NbaTeam
from hoops_gm.db.models.league import League, ScoringPeriod
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.importers import import_schedule, import_teams
from hoops_gm.ingest.nba import (
    NbaStatsClient,
    NbaTeamRecord,
    ScheduledGameCount,
    build_schedule_density,
    parse_schedule,
    parse_teams,
    playoff_scheduled_game_counts,
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
    assert len(counts) == len(team_ids)
    assert sum(row.games for row in counts) == 6
    assert {row.games for row in counts} == {0, 1}


def test_schedule_import_registers_a_refresh_that_converges_on_re_import(session: Any) -> None:
    """The schedule refresh registry is a side effect of ``import_schedule``.

    A re-import that changes nothing must not invent a new schedule cohort:
    downstream ``schedule_version`` stamps (``schedule_context.py``) would
    otherwise go stale for no reason every time the importer merely confirms
    what it already knew.
    """
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

    import_schedule(session, result.games)
    first_run = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key="nba-schedule",
        season="2026-27",
    )
    assert first_run is not None
    assert first_run.season == "2026-27"
    assert first_run.summary["team_schedule_rows"] == 20

    import_schedule(session, result.games)
    second_run = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key="nba-schedule",
        season="2026-27",
    )
    assert second_run is not None

    assert second_run.id == first_run.id, "identical facts must not open a new cohort"
    assert second_run.version == first_run.version
    assert second_run.refreshed_at >= first_run.refreshed_at

    entries = session.scalars(
        select(TeamScheduleEntry).where(
            TeamScheduleEntry.season == "2026-27",
            TeamScheduleEntry.season_type == SeasonType.REGULAR,
        )
    ).all()
    density = build_schedule_density(
        entries,
        schedule_version=second_run.version,
        schedule_refreshed_at=second_run.refreshed_at,
    )

    assert {row.schedule_version for row in density} == {second_run.version}
    assert {row.schedule_refreshed_at for row in density} == {second_run.refreshed_at}
    assert (
        check_cohort(session, schedule_version=density[0].schedule_version)[0].status == "current"
    )

    stale_density = build_schedule_density(
        entries,
        schedule_version="stale-schedule-version",
        schedule_refreshed_at=second_run.refreshed_at,
    )
    assert (
        check_cohort(session, schedule_version=stale_density[0].schedule_version)[0].status
        == "stale"
    )


def test_playoff_schedule_counts_complete_league_scoped_team_period_grid(
    session: Session,
) -> None:
    teams = [
        NbaTeam(nba_team_id=1, abbreviation="ONE", name="One"),
        NbaTeam(nba_team_id=2, abbreviation="TWO", name="Two"),
        NbaTeam(nba_team_id=3, abbreviation="THREE", name="Three"),
        NbaTeam(nba_team_id=4, abbreviation="FOUR", name="Four"),
    ]
    leagues = [
        League(
            name="Primary",
            season="2026-27",
            scoring_type="h2h_categories",
            draft_type="auction",
        ),
        League(
            name="Other",
            season="2026-27",
            scoring_type="h2h_categories",
            draft_type="auction",
        ),
        League(
            name="No playoffs",
            season="2026-27",
            scoring_type="h2h_categories",
            draft_type="auction",
        ),
    ]
    session.add_all([*teams, *leagues])
    session.flush()
    session.add_all(
        [
            ScoringPeriod(
                league_id=leagues[0].id,
                period_number=7,
                start_date=date(2027, 3, 1),
                end_date=date(2027, 3, 7),
                is_playoff=True,
            ),
            ScoringPeriod(
                league_id=leagues[0].id,
                period_number=8,
                start_date=date(2027, 3, 8),
                end_date=date(2027, 3, 14),
                is_playoff=True,
            ),
            ScoringPeriod(
                league_id=leagues[0].id,
                period_number=9,
                start_date=date(2027, 3, 22),
                end_date=date(2027, 3, 28),
                is_playoff=True,
            ),
            ScoringPeriod(
                league_id=leagues[0].id,
                period_number=6,
                start_date=date(2027, 2, 22),
                end_date=date(2027, 2, 28),
                is_playoff=False,
            ),
            ScoringPeriod(
                league_id=leagues[1].id,
                period_number=20,
                start_date=date(2027, 3, 8),
                end_date=date(2027, 3, 14),
                is_playoff=True,
            ),
            ScoringPeriod(
                league_id=leagues[2].id,
                period_number=1,
                start_date=date(2027, 3, 1),
                end_date=date(2027, 3, 7),
                is_playoff=False,
            ),
        ]
    )
    _add_schedule_game(session, 101, date(2027, 3, 1), teams[0], teams[1])
    _add_schedule_game(session, 102, date(2027, 3, 7), teams[0], teams[2])
    _add_schedule_game(session, 103, date(2027, 3, 8), teams[1], teams[2])
    _add_schedule_game(session, 104, date(2027, 3, 14), teams[0], teams[1])
    _add_schedule_game(session, 105, date(2027, 3, 15), teams[0], teams[1])
    _add_schedule_game(
        session,
        106,
        date(2027, 3, 1),
        teams[0],
        teams[1],
        season="2025-26",
    )
    _add_schedule_game(
        session,
        107,
        date(2027, 3, 1),
        teams[0],
        teams[1],
        season_type=SeasonType.PLAYOFFS,
    )
    session.flush()

    primary = playoff_scheduled_game_counts(session, league_id=leagues[0].id, season="2026-27")

    assert primary == [
        ScheduledGameCount(7, teams[0].id, 2),
        ScheduledGameCount(7, teams[1].id, 1),
        ScheduledGameCount(7, teams[2].id, 1),
        ScheduledGameCount(7, teams[3].id, 0),
        ScheduledGameCount(8, teams[0].id, 1),
        ScheduledGameCount(8, teams[1].id, 2),
        ScheduledGameCount(8, teams[2].id, 1),
        ScheduledGameCount(8, teams[3].id, 0),
        ScheduledGameCount(9, teams[0].id, 0),
        ScheduledGameCount(9, teams[1].id, 0),
        ScheduledGameCount(9, teams[2].id, 0),
        ScheduledGameCount(9, teams[3].id, 0),
    ]
    assert {
        row.period_number
        for row in playoff_scheduled_game_counts(session, league_id=leagues[1].id, season="2026-27")
    } == {20}
    assert playoff_scheduled_game_counts(session, league_id=leagues[2].id, season="2026-27") == []


def test_schedule_density_uses_team_schedule_only_for_calendar_arithmetic() -> None:
    refreshed_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    rows = [
        TeamScheduleEntry(
            id=1,
            team_id=42,
            game_id=101,
            opponent_team_id=2,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 15),
            is_home=True,
        ),
        TeamScheduleEntry(
            id=2,
            team_id=42,
            game_id=102,
            opponent_team_id=3,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 16),
            is_home=False,
        ),
        TeamScheduleEntry(
            id=3,
            team_id=42,
            game_id=103,
            opponent_team_id=4,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 17),
            is_home=False,
        ),
        TeamScheduleEntry(
            id=4,
            team_id=42,
            game_id=104,
            opponent_team_id=5,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 18),
            is_home=False,
        ),
        TeamScheduleEntry(
            id=5,
            team_id=42,
            game_id=105,
            opponent_team_id=6,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 20),
            is_home=False,
        ),
        TeamScheduleEntry(
            id=6,
            team_id=3,
            game_id=99,
            opponent_team_id=8,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 14),
            is_home=True,
        ),
        TeamScheduleEntry(
            id=7,
            team_id=3,
            game_id=102,
            opponent_team_id=42,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 16),
            is_home=True,
        ),
    ]

    density = build_schedule_density(
        rows,
        schedule_version="schedule-v1",
        schedule_refreshed_at=refreshed_at,
    )
    team_density = [row for row in density if row.team_id == 42]
    by_date = {row.game_date: row for row in team_density}

    assert {row.schedule_version for row in density} == {"schedule-v1"}
    assert {row.schedule_refreshed_at for row in density} == {refreshed_at}
    assert {row.season for row in density} == {"2026-27"}
    assert {row.season_type for row in density} == {SeasonType.REGULAR}
    assert by_date[date(2026, 10, 15)].rest_days_differential is None
    assert by_date[date(2026, 10, 16)].is_back_to_back is True
    assert by_date[date(2026, 10, 16)].rest_days == 0
    assert by_date[date(2026, 10, 16)].rest_days_differential == -1
    assert by_date[date(2026, 10, 17)].games_in_4_days == 3
    assert by_date[date(2026, 10, 17)].is_3_in_4 is True
    assert by_date[date(2026, 10, 18)].games_in_5_days == 4
    assert by_date[date(2026, 10, 18)].is_4_in_5 is True
    assert by_date[date(2026, 10, 18)].games_in_6_days == 4
    assert by_date[date(2026, 10, 18)].is_4_in_6 is True
    assert by_date[date(2026, 10, 18)].road_trip_length == 3
    assert by_date[date(2026, 10, 18)].road_trip_structure == (3, 4, 5)
    assert by_date[date(2026, 10, 20)].rest_days == 1
    assert by_date[date(2026, 10, 20)].road_trip_length == 4
    assert by_date[date(2026, 10, 20)].road_trip_structure == (3, 4, 5, 6)


def test_schedule_density_requires_refresh_lineage() -> None:
    with pytest.raises(ValueError, match="schedule_version"):
        build_schedule_density(
            [],
            schedule_version="",
            schedule_refreshed_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        build_schedule_density(
            [],
            schedule_version="schedule-v1",
            schedule_refreshed_at=datetime(2026, 8, 18, 12, 0),
        )


@pytest.mark.parametrize(
    ("second_season", "second_season_type"),
    [
        ("2025-26", SeasonType.REGULAR),
        ("2026-27", SeasonType.PLAYOFFS),
    ],
)
def test_schedule_density_rejects_mixed_season_cohorts(
    second_season: str,
    second_season_type: SeasonType,
) -> None:
    rows = [
        TeamScheduleEntry(
            id=1,
            team_id=42,
            game_id=101,
            opponent_team_id=2,
            season="2026-27",
            season_type=SeasonType.REGULAR,
            game_date=date(2026, 10, 15),
            is_home=True,
        ),
        TeamScheduleEntry(
            id=2,
            team_id=42,
            game_id=102,
            opponent_team_id=3,
            season=second_season,
            season_type=second_season_type,
            game_date=date(2026, 10, 16),
            is_home=False,
        ),
    ]

    with pytest.raises(ValueError, match="one season and season type"):
        build_schedule_density(
            rows,
            schedule_version="schedule-v1",
            schedule_refreshed_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
        )


def _add_schedule_game(
    session: Session,
    number: int,
    game_date: date,
    home: NbaTeam,
    away: NbaTeam,
    *,
    season: str = "2026-27",
    season_type: SeasonType = SeasonType.REGULAR,
) -> None:
    game = NbaGame(
        nba_game_id=str(number),
        season=season,
        season_type=season_type,
        game_date=game_date,
        home_team_id=home.id,
        away_team_id=away.id,
    )
    session.add(game)
    session.flush()
    session.add_all(
        [
            TeamScheduleEntry(
                game_id=game.id,
                team_id=home.id,
                opponent_team_id=away.id,
                season=season,
                season_type=season_type,
                game_date=game_date,
                is_home=True,
            ),
            TeamScheduleEntry(
                game_id=game.id,
                team_id=away.id,
                opponent_team_id=home.id,
                season=season,
                season_type=season_type,
                game_date=game_date,
                is_home=False,
            ),
        ]
    )
