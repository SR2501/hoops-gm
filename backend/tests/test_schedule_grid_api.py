from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.app import create_app
from hoops_gm.calendar import (
    ScoringPeriodProjectionResult,
    activate_deadline_calendar,
    derive_deadline_calendar,
    project_scoring_periods,
)
from hoops_gm.core.config import Settings
from hoops_gm.db.base import Base
from hoops_gm.db.lineage import NBA_SCHEDULE_ARTIFACT_KEY, record_refresh
from hoops_gm.db.models.enums import RefreshArtifactType, SeasonType
from hoops_gm.db.models.identity import NbaTeam
from hoops_gm.db.models.league import League, ScoringPeriod
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.ingest.importers import import_league_settings
from hoops_gm.ingest.league_settings import (
    BRIDGE_SOURCE,
    LeagueSettingsDocument,
    PlayoffRules,
    SettingEvidence,
    SourcedSetting,
    parse_official_league_settings,
)

SEASON = "2026-27"
EASTERN = ZoneInfo("America/New_York")


def _league(session: Session) -> League:
    league = League(
        name="Schedule grid league",
        season=SEASON,
        fantrax_league_id="schedule-grid-league",
        scoring_type="h2h_categories",
        draft_type="auction",
    )
    session.add(league)
    session.flush()
    return league


def _register_schedule(
    session: Session,
    *,
    version: str = "schedule-v1",
    refreshed_at: datetime = datetime(2026, 8, 18, 12, tzinfo=UTC),
) -> None:
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version=version,
        source="test",
        season=SEASON,
        refreshed_at=refreshed_at,
    )


def _settings_document(league: League) -> LeagueSettingsDocument:
    periods = [
        (2, date(2026, 10, 27), date(2026, 11, 2), False),
        (1, date(2026, 10, 20), date(2026, 10, 26), True),
    ]
    payload: dict[str, object] = {
        "seasonYear": 2026,
        "startDate": "2026-10-20",
        "endDate": "2026-11-02",
        "scoringPeriods": [
            {
                "number": number,
                "startDate": datetime.combine(start, time.min, tzinfo=EASTERN).isoformat(),
                "endDate": datetime.combine(end, time(23, 59, 59), tzinfo=EASTERN).isoformat(),
            }
            for number, start, end, _ in sorted(periods)
        ],
    }
    return parse_official_league_settings(
        payload,
        source_league_id=league.fantrax_league_id or "",
        capture_ref="sha256:schedule-grid",
    ).model_copy(
        update={
            "playoffs": SourcedSetting(
                value=PlayoffRules(period_numbers=(1,)),
                evidence=(
                    SettingEvidence(
                        source=BRIDGE_SOURCE,
                        status="observed",
                        source_path="League Rules > Playoffs",
                        capture_ref="bridge_payload:schedule-grid",
                    ),
                ),
            )
        }
    )


def _activate_current_periods(
    session: Session,
    league: League,
) -> ScoringPeriodProjectionResult:
    document = _settings_document(league)
    canonical_json = document.canonical_json()
    import_league_settings(
        session,
        league=league,
        document=document,
        source_payload_sha256=hashlib.sha256(canonical_json.encode()).hexdigest(),
        observed_at=datetime(2026, 8, 18, tzinfo=UTC),
    )
    calendar = derive_deadline_calendar(session, league).calendar
    activate_deadline_calendar(session, league, calendar.version)
    return project_scoring_periods(
        session,
        league,
        projected_at=datetime(2026, 8, 19, tzinfo=UTC),
    )


def _team(session: Session, nba_id: int, abbreviation: str, *, active: bool = True) -> NbaTeam:
    team = NbaTeam(
        nba_team_id=nba_id,
        abbreviation=abbreviation,
        name=abbreviation,
        is_active=active,
    )
    session.add(team)
    session.flush()
    return team


def _game(
    session: Session,
    number: int,
    game_date: date,
    home: NbaTeam,
    away: NbaTeam,
) -> None:
    game = NbaGame(
        nba_game_id=str(number),
        season=SEASON,
        season_type=SeasonType.REGULAR,
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
                season=SEASON,
                season_type=SeasonType.REGULAR,
                game_date=game_date,
                is_home=True,
            ),
            TeamScheduleEntry(
                game_id=game.id,
                team_id=away.id,
                opponent_team_id=home.id,
                season=SEASON,
                season_type=SeasonType.REGULAR,
                game_date=game_date,
                is_home=False,
            ),
        ]
    )


def _seed_current_grid(
    app: FastAPI,
) -> tuple[int, list[int], ScoringPeriodProjectionResult]:
    with app.state.database.session() as session:
        league = _league(session)
        teams = [
            _team(session, 3, "THR"),
            _team(session, 1, "ONE"),
            _team(session, 2, "TWO"),
        ]
        _game(session, 1, date(2026, 10, 20), teams[1], teams[2])
        _register_schedule(session)
        projection = _activate_current_periods(session, league)
        return league.id, [team.id for team in teams], projection


def test_current_grid_returns_complete_ordered_zero_explicit_matrix_and_lineage(
    app: FastAPI,
    client: TestClient,
) -> None:
    league_id, team_ids, projection = _seed_current_grid(app)

    response = client.get(f"/api/v1/leagues/{league_id}/schedule-grid/current")

    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["league_id", "season", "lineage", "counts"]
    assert body["league_id"] == league_id
    assert body["season"] == SEASON
    assert body["counts"] == [
        {"period_number": 1, "team_id": team_id, "games": games}
        for team_id, games in sorted([(team_ids[0], 0), (team_ids[1], 1), (team_ids[2], 1)])
    ] + [{"period_number": 2, "team_id": team_id, "games": 0} for team_id in sorted(team_ids)]
    lineage = projection.lineage
    assert body["lineage"] == {
        "schedule": {
            "refresh_id": lineage.schedule_refresh_id,
            "version": lineage.schedule_version,
            "refreshed_at": lineage.schedule_refreshed_at.isoformat().replace("+00:00", "Z"),
        },
        "scoring_period_projection": {
            "refresh_id": lineage.projection_refresh_id,
            "version": lineage.projection_version,
            "refreshed_at": lineage.projection_refreshed_at.isoformat().replace("+00:00", "Z"),
        },
        "deadline_calendar": {
            "id": lineage.deadline_calendar_id,
            "version": lineage.deadline_calendar_version,
        },
        "settings_snapshot": {
            "id": lineage.settings_snapshot_id,
            "version": lineage.settings_snapshot_version,
        },
    }


def test_current_grid_rejects_non_loopback_callers(tmp_path: Path) -> None:
    settings = Settings(
        environment="development",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        bridge_secret_path=tmp_path / "bridge_secret",
        _env_file=None,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.database.engine)
        with app.state.database.session() as session:
            league_id = _league(session).id

        response = client.get(f"/api/v1/leagues/{league_id}/schedule-grid/current")

    assert response.status_code == 403
    assert response.json()["error"] == "schedule_grid_local_only"


def test_current_grid_rejects_unknown_scoring_period_projection(
    app: FastAPI,
    client: TestClient,
) -> None:
    with app.state.database.session() as session:
        league = _league(session)
        league_id = league.id
        _register_schedule(session)
        document = _settings_document(league)
        canonical_json = document.canonical_json()
        import_league_settings(
            session,
            league=league,
            document=document,
            source_payload_sha256=hashlib.sha256(canonical_json.encode()).hexdigest(),
            observed_at=datetime(2026, 8, 18, tzinfo=UTC),
        )
        calendar = derive_deadline_calendar(session, league).calendar
        activate_deadline_calendar(session, league, calendar.version)

    response = client.get(f"/api/v1/leagues/{league_id}/schedule-grid/current")

    assert response.status_code == 409
    assert response.json()["error"] == "schedule_grid_not_current"
    assert "counts" not in response.json()


def test_current_grid_rejects_missing_settings_and_calendar(
    app: FastAPI,
    client: TestClient,
) -> None:
    with app.state.database.session() as session:
        league = _league(session)
        league_id = league.id
        _register_schedule(session)

    response = client.get(f"/api/v1/leagues/{league_id}/schedule-grid/current")

    assert response.status_code == 409
    assert response.json()["error"] == "schedule_grid_not_current"
    assert "counts" not in response.json()


def test_current_grid_rejects_a_calendar_bound_to_stale_settings(
    app: FastAPI,
    client: TestClient,
) -> None:
    league_id, _, _ = _seed_current_grid(app)
    with app.state.database.session() as session:
        league = session.get(League, league_id)
        assert league is not None
        document = _settings_document(league).model_copy(update={"source_end_date": "2026-11-03"})
        import_league_settings(
            session,
            league=league,
            document=document,
            source_payload_sha256=hashlib.sha256(document.canonical_json().encode()).hexdigest(),
            observed_at=datetime(2026, 8, 20, tzinfo=UTC),
        )

    response = client.get(f"/api/v1/leagues/{league_id}/schedule-grid/current")

    assert response.status_code == 409
    assert response.json()["error"] == "schedule_grid_not_current"
    assert "counts" not in response.json()


def test_current_grid_rejects_stale_schedule_lineage(
    app: FastAPI,
    client: TestClient,
) -> None:
    league_id, _, _ = _seed_current_grid(app)
    with app.state.database.session() as session:
        _register_schedule(
            session,
            version="schedule-v2",
            refreshed_at=datetime(2026, 8, 20, tzinfo=UTC),
        )

    response = client.get(f"/api/v1/leagues/{league_id}/schedule-grid/current")

    assert response.status_code == 409
    assert response.json()["error"] == "schedule_grid_not_current"
    assert "counts" not in response.json()


def test_current_grid_rejects_mismatched_materialized_periods(
    app: FastAPI,
    client: TestClient,
) -> None:
    league_id, _, _ = _seed_current_grid(app)
    with app.state.database.session() as session:
        period = session.scalar(
            select(ScoringPeriod).where(
                ScoringPeriod.league_id == league_id,
                ScoringPeriod.period_number == 1,
            )
        )
        assert period is not None
        period.end_date = date(2026, 10, 25)

    response = client.get(f"/api/v1/leagues/{league_id}/schedule-grid/current")

    assert response.status_code == 409
    assert response.json()["error"] == "schedule_grid_not_current"
    assert "counts" not in response.json()


def test_current_grid_never_returns_success_shaped_empty_data(
    app: FastAPI,
    client: TestClient,
) -> None:
    with app.state.database.session() as session:
        league = _league(session)
        league_id = league.id
        _team(session, 1, "ONE", active=False)
        _register_schedule(session)
        _activate_current_periods(session, league)

    response = client.get(f"/api/v1/leagues/{league_id}/schedule-grid/current")

    assert response.status_code == 409
    assert response.json()["error"] == "schedule_grid_incomplete"
    assert "counts" not in response.json()


def test_schedule_grid_contract_is_advertised_in_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/leagues/{league_id}/schedule-grid/current" in paths
