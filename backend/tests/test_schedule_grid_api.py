"""The schedule-grid API: one operational proof, and one test per refusal.

The shape of this file is deliberate. Every fail-closed case starts from the
**same seeded, genuinely valid database** and breaks exactly one thing, so a
409 is evidence that the broken thing caused it rather than evidence that the
endpoint was never reachable in the first place. The previous version of this
endpoint was permanently unavailable and its tests all passed, because they
only ever asserted refusals.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
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
from hoops_gm.db.lineage import (
    NBA_SCHEDULE_ARTIFACT_KEY,
    SCHEDULE_COMPLETENESS_SUMMARY_KEY,
    record_refresh,
)
from hoops_gm.db.models.enums import RefreshArtifactType
from hoops_gm.db.models.identity import NbaTeam
from hoops_gm.db.models.league import League, ScoringPeriod
from hoops_gm.db.models.lineage import RefreshRun
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.dev.seed_schedule_grid import (
    DEFAULT_FIXTURES_DIR,
    SCHEDULE_FIXTURE,
    SEASON,
    TEAMS_FIXTURE,
    SeedResult,
    load_fixture,
    resolved_schedule_payload,
    seed_schedule_grid,
    weekly_periods,
)
from hoops_gm.ingest.importers import import_league_settings, import_schedule, import_teams
from hoops_gm.ingest.league_settings import (
    BRIDGE_SOURCE,
    PlayoffRules,
    SettingEvidence,
    SourcedSetting,
    parse_official_league_settings,
)
from hoops_gm.ingest.nba.parsers import parse_teams
from hoops_gm.ingest.nba.schedule import parse_schedule

EASTERN = ZoneInfo("America/New_York")
GRID_URL = "/api/v1/leagues/{league_id}/schedule-grid/current"


def _seed(app: FastAPI) -> SeedResult:
    with app.state.database.session() as session:
        return seed_schedule_grid(session)


def _error_of(response: Any) -> str:
    code: str = response.json()["error"]
    return code


def _schedule_refresh(session: Session) -> RefreshRun:
    refresh = session.scalar(
        select(RefreshRun).where(
            RefreshRun.artifact_type == RefreshArtifactType.SCHEDULE,
            RefreshRun.artifact_key == NBA_SCHEDULE_ARTIFACT_KEY,
            RefreshRun.season == SEASON,
        )
    )
    assert refresh is not None
    return refresh


def _import_teams_and_schedule(session: Session) -> None:
    """Everything the seed does up to, but not including, the league."""

    import_teams(session, parse_teams(load_fixture(DEFAULT_FIXTURES_DIR, TEAMS_FIXTURE)))
    import_schedule(
        session,
        parse_schedule(
            resolved_schedule_payload(load_fixture(DEFAULT_FIXTURES_DIR, SCHEDULE_FIXTURE)),
            season=SEASON,
        ),
    )


def _league(session: Session, *, fantrax_league_id: str) -> League:
    league = League(
        name=f"League {fantrax_league_id}",
        season=SEASON,
        fantrax_league_id=fantrax_league_id,
        scoring_type="h2h_categories",
        draft_type="auction",
    )
    session.add(league)
    session.flush()
    return league


def _project_periods(
    session: Session,
    league: League,
    periods: list[tuple[int, date, date, bool]],
) -> ScoringPeriodProjectionResult:
    """Give ``league`` exactly these period windows, through the real pipeline.

    A test-local twin of the seed's settings builder, because the seed's is
    pinned to one Fantrax league id and these tests need a second league whose
    weeks deliberately contain no games.
    """

    assert league.fantrax_league_id is not None
    playoff_numbers = tuple(number for number, _, _, is_playoff in periods if is_playoff)
    assert playoff_numbers, "the settings contract cannot express known zero-playoff periods"
    payload: dict[str, object] = {
        "seasonYear": int(league.season[:4]),
        "startDate": min(start for _, start, _, _ in periods).isoformat(),
        "endDate": max(end for _, _, end, _ in periods).isoformat(),
        "scoringPeriods": [
            {
                "number": number,
                "startDate": datetime.combine(start, time.min, tzinfo=EASTERN).isoformat(),
                "endDate": datetime.combine(end, time(23, 59, 59), tzinfo=EASTERN).isoformat(),
            }
            for number, start, end, _ in periods
        ],
    }
    document = parse_official_league_settings(
        payload,
        source_league_id=league.fantrax_league_id,
        capture_ref=f"sha256:grid-test-{league.id}",
    ).model_copy(
        update={
            "playoffs": SourcedSetting(
                value=PlayoffRules(period_numbers=playoff_numbers),
                evidence=(
                    SettingEvidence(
                        source=BRIDGE_SOURCE,
                        status="observed",
                        source_path="League Rules > Playoffs",
                        capture_ref=f"bridge_payload:grid-test-{league.id}",
                    ),
                ),
            )
        }
    )
    import_league_settings(
        session,
        league=league,
        document=document,
        source_payload_sha256=hashlib.sha256(document.canonical_json().encode()).hexdigest(),
        observed_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    calendar = derive_deadline_calendar(session, league).calendar
    activate_deadline_calendar(session, league, calendar.version)
    return project_scoring_periods(session, league, projected_at=datetime(2026, 8, 20, tzinfo=UTC))


# --------------------------------------------------------------------------
# Operational proof
# --------------------------------------------------------------------------


def test_current_grid_serves_a_real_seeded_season(app: FastAPI, client: TestClient) -> None:
    """The single test that distinguishes "fails closed" from "works"."""

    seeded = _seed(app)

    response = client.get(GRID_URL.format(league_id=seeded.league_id))

    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["league_id", "season", "lineage", "teams", "periods", "counts"]
    assert body["league_id"] == seeded.league_id
    assert body["season"] == SEASON
    assert body["lineage"]["schedule"]["version"] == seeded.schedule_version
    assert body["lineage"]["schedule"]["source_game_count"] == seeded.resolved_game_count
    assert body["lineage"]["schedule"]["resolved_game_count"] == seeded.resolved_game_count
    assert body["lineage"]["schedule"]["persisted_team_row_count"] == 2 * seeded.resolved_game_count
    assert body["lineage"]["schedule"]["unresolved_game_ids"] == []
    assert sum(row["games"] for row in body["counts"]) == seeded.scheduled_team_games
    assert seeded.scheduled_team_games > 0


def test_current_grid_is_dense_and_labelled_over_every_team_and_period(
    app: FastAPI, client: TestClient
) -> None:
    seeded = _seed(app)

    body = client.get(GRID_URL.format(league_id=seeded.league_id)).json()

    teams = body["teams"]
    periods = body["periods"]
    assert len(teams) == seeded.team_count == 30
    assert len(periods) == seeded.period_count
    assert [team["team_id"] for team in teams] == sorted(team["team_id"] for team in teams)
    assert [period["period_number"] for period in periods] == sorted(
        period["period_number"] for period in periods
    )
    # Dense: one explicit row per (period, team), zeros included.
    assert len(body["counts"]) == len(periods) * len(teams)
    assert {(row["period_number"], row["team_id"]) for row in body["counts"]} == {
        (period["period_number"], team["team_id"]) for period in periods for team in teams
    }
    assert 0 in {row["games"] for row in body["counts"]}
    assert [(row["period_number"], row["team_id"]) for row in body["counts"]] == sorted(
        (row["period_number"], row["team_id"]) for row in body["counts"]
    )


def test_current_grid_labels_match_the_persisted_rows_they_describe(
    app: FastAPI, client: TestClient
) -> None:
    """Labels are not decoration; a wrong one silently mislabels a whole row."""

    seeded = _seed(app)

    body = client.get(GRID_URL.format(league_id=seeded.league_id)).json()

    with app.state.database.session() as session:
        expected_teams = {
            team_id: (nba_team_id, abbreviation, name)
            for team_id, nba_team_id, abbreviation, name in session.execute(
                select(NbaTeam.id, NbaTeam.nba_team_id, NbaTeam.abbreviation, NbaTeam.name)
            )
        }
        expected_periods = {
            number: (start, end, is_playoff)
            for number, start, end, is_playoff in session.execute(
                select(
                    ScoringPeriod.period_number,
                    ScoringPeriod.start_date,
                    ScoringPeriod.end_date,
                    ScoringPeriod.is_playoff,
                ).where(ScoringPeriod.league_id == seeded.league_id)
            )
        }
    for team in body["teams"]:
        assert expected_teams[team["team_id"]] == (
            team["nba_team_id"],
            team["abbreviation"],
            team["name"],
        )
    for period in body["periods"]:
        start, end, is_playoff = expected_periods[period["period_number"]]
        assert (start.isoformat(), end.isoformat(), is_playoff) == (
            period["start_date"],
            period["end_date"],
            period["is_playoff"],
        )
    assert any(period["is_playoff"] for period in body["periods"])


def test_current_grid_counts_agree_with_the_persisted_schedule(
    app: FastAPI, client: TestClient
) -> None:
    seeded = _seed(app)

    body = client.get(GRID_URL.format(league_id=seeded.league_id)).json()

    periods = {
        period["period_number"]: (
            date.fromisoformat(period["start_date"]),
            date.fromisoformat(period["end_date"]),
        )
        for period in body["periods"]
    }
    with app.state.database.session() as session:
        entries = list(
            session.execute(select(TeamScheduleEntry.team_id, TeamScheduleEntry.game_date))
        )
    expected = {
        (number, team_id): 0
        for number in periods
        for team_id in {row["team_id"] for row in body["teams"]}
    }
    for team_id, game_date in entries:
        for number, (start, end) in periods.items():
            if start <= game_date <= end:
                expected[(number, team_id)] += 1
    assert {
        (row["period_number"], row["team_id"]): row["games"] for row in body["counts"]
    } == expected


def test_seeding_twice_converges_rather_than_advancing_lineage(
    app: FastAPI, client: TestClient
) -> None:
    """A re-seed must not look like new evidence, or "current" means nothing."""

    first = _seed(app)
    second = _seed(app)

    assert second.league_id == first.league_id
    assert second.schedule_version == first.schedule_version
    response = client.get(GRID_URL.format(league_id=first.league_id))
    assert response.status_code == 200
    assert response.json()["lineage"]["schedule"]["version"] == first.schedule_version


def test_current_grid_does_not_commit_lineage_lock_reservations(
    app: FastAPI, client: TestClient
) -> None:
    """A read must not advance any refresh row's own audit timestamps."""

    seeded = _seed(app)
    sentinel = datetime(2000, 1, 1, tzinfo=UTC)
    with app.state.database.session() as session:
        session.execute(update(RefreshRun).values(updated_at=sentinel))
    with app.state.database.session() as session:
        before = dict(session.execute(select(RefreshRun.id, RefreshRun.updated_at)).all())

    assert client.get(GRID_URL.format(league_id=seeded.league_id)).status_code == 200

    with app.state.database.session() as session:
        after = dict(session.execute(select(RefreshRun.id, RefreshRun.updated_at)).all())
    assert after == before
    assert set(after.values()) == {sentinel}


def test_schedule_grid_contract_is_advertised_in_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert GRID_URL.format(league_id="{league_id}") in paths
    responses = paths[GRID_URL.format(league_id="{league_id}")]["get"]["responses"]
    for status in ("403", "404", "409", "422"):
        schema = responses[status]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


def test_current_grid_rejects_non_loopback_callers(tmp_path: Path) -> None:
    settings = Settings(
        environment="development",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        bridge_secret_path=tmp_path / "bridge_secret",
        _env_file=None,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        # Same drop/create as the shared ``client`` fixture: against Postgres
        # every test shares one external database, and creating without
        # dropping inherits an earlier test's rows.
        Base.metadata.drop_all(app.state.database.engine)
        Base.metadata.create_all(app.state.database.engine)
        seeded = _seed(app)

        response = client.get(GRID_URL.format(league_id=seeded.league_id))

    assert response.status_code == 403
    assert _error_of(response) == "schedule_grid_local_only"
    assert "counts" not in response.json()


def test_current_grid_serves_a_loopback_proxy_peer_outside_test_environment(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment="development",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        bridge_secret_path=tmp_path / "bridge_secret",
        _env_file=None,
    )
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 5173)) as client:
        Base.metadata.drop_all(app.state.database.engine)
        Base.metadata.create_all(app.state.database.engine)
        seeded = _seed(app)

        response = client.get(GRID_URL.format(league_id=seeded.league_id))

    assert response.status_code == 200
    assert sum(row["games"] for row in response.json()["counts"]) > 0


def test_current_grid_returns_typed_not_found_for_unknown_leagues(client: TestClient) -> None:
    response = client.get(GRID_URL.format(league_id=999999))

    assert response.status_code == 404
    assert _error_of(response) == "schedule_grid_league_not_found"


def test_current_grid_rejects_a_season_with_no_registered_schedule_refresh(
    app: FastAPI, client: TestClient
) -> None:
    with app.state.database.session() as session:
        league_id = _league(session, fantrax_league_id="no-schedule").id

    response = client.get(GRID_URL.format(league_id=league_id))

    assert response.status_code == 409
    assert _error_of(response) == "schedule_grid_not_current"
    assert "no current NBA schedule refresh" in response.json()["detail"]
    assert "counts" not in response.json()


def test_current_grid_rejects_a_league_with_no_settings_or_calendar(
    app: FastAPI, client: TestClient
) -> None:
    with app.state.database.session() as session:
        _import_teams_and_schedule(session)
        league_id = _league(session, fantrax_league_id="no-settings").id

    response = client.get(GRID_URL.format(league_id=league_id))

    assert response.status_code == 409
    assert _error_of(response) == "schedule_grid_not_current"
    assert "counts" not in response.json()


def test_current_grid_rejects_a_schedule_refresh_without_completeness_evidence(
    app: FastAPI, client: TestClient
) -> None:
    """A legacy or hand-registered refresh cannot populate the contract."""

    seeded = _seed(app)
    with app.state.database.session() as session:
        refresh = _schedule_refresh(session)
        refresh.summary = {"team_schedule_rows": 2 * seeded.resolved_game_count}

    response = client.get(GRID_URL.format(league_id=seeded.league_id))

    assert response.status_code == 409
    body = response.json()
    assert set(body) == {"error", "detail", "request_id"}
    assert body["error"] == "schedule_grid_incomplete_evidence"
    assert SCHEDULE_COMPLETENESS_SUMMARY_KEY in body["detail"]
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert "counts" not in body


def test_current_grid_rejects_a_malformed_completeness_block(
    app: FastAPI, client: TestClient
) -> None:
    seeded = _seed(app)
    with app.state.database.session() as session:
        refresh = _schedule_refresh(session)
        refresh.summary = {SCHEDULE_COMPLETENESS_SUMMARY_KEY: "not an object"}

    response = client.get(GRID_URL.format(league_id=seeded.league_id))

    assert response.status_code == 409
    assert _error_of(response) == "schedule_grid_incomplete_evidence"
    assert "malformed" in response.json()["detail"]


def test_current_grid_rejects_a_summary_that_is_not_an_object(
    app: FastAPI, client: TestClient
) -> None:
    seeded = _seed(app)
    with app.state.database.session() as session:
        # A JSON array rather than NULL: ``summary`` is NOT NULL, and forcing a
        # NULL here would fail on Postgres for a reason unrelated to the route.
        session.execute(
            update(RefreshRun)
            .where(RefreshRun.id == _schedule_refresh(session).id)
            .values(summary=["not", "an", "object"])
        )

    response = client.get(GRID_URL.format(league_id=seeded.league_id))

    assert response.status_code == 409
    assert _error_of(response) == "schedule_grid_incomplete_evidence"
    assert "summary is not an object" in response.json()["detail"]


def test_current_grid_rejects_completeness_claiming_unresolved_games(
    app: FastAPI, client: TestClient
) -> None:
    seeded = _seed(app)
    with app.state.database.session() as session:
        refresh = _schedule_refresh(session)
        block = dict(refresh.summary[SCHEDULE_COMPLETENESS_SUMMARY_KEY])  # type: ignore[call-overload]
        block["unresolved_game_ids"] = ["0022601201"]
        refresh.summary = {**refresh.summary, SCHEDULE_COMPLETENESS_SUMMARY_KEY: block}

    response = client.get(GRID_URL.format(league_id=seeded.league_id))

    assert response.status_code == 409
    assert _error_of(response) == "schedule_grid_incomplete_evidence"
    assert "unresolved" in response.json()["detail"]
    assert seeded.league_id


def test_current_grid_rejects_evidence_after_a_schedule_row_is_removed(
    app: FastAPI, client: TestClient
) -> None:
    seeded = _seed(app)
    with app.state.database.session() as session:
        entry = session.scalar(select(TeamScheduleEntry).limit(1))
        assert entry is not None
        session.delete(entry)

    response = client.get(GRID_URL.format(league_id=seeded.league_id))

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "schedule_grid_incomplete_evidence"
    assert str(2 * seeded.resolved_game_count) in body["detail"]
    assert "counts" not in body


def test_current_grid_rejects_a_same_row_count_schedule_mutation(
    app: FastAPI, client: TestClient
) -> None:
    """The failure a row count cannot see: same rows, different facts."""

    seeded = _seed(app)
    moved = date(2027, 2, 2)
    with app.state.database.session() as session:
        game = session.scalar(select(NbaGame).order_by(NbaGame.id).limit(1))
        assert game is not None
        game.game_date = moved
        session.execute(
            update(TeamScheduleEntry)
            .where(TeamScheduleEntry.game_id == game.id)
            .values(game_date=moved)
        )
    with app.state.database.session() as session:
        assert session.scalar(select(TeamScheduleEntry).where(TeamScheduleEntry.game_date == moved))
        assert (
            len(list(session.execute(select(TeamScheduleEntry.id))))
            == 2 * seeded.resolved_game_count
        )

    response = client.get(GRID_URL.format(league_id=seeded.league_id))

    assert response.status_code == 409
    assert _error_of(response) == "schedule_grid_not_current"
    assert "no longer matches the persisted schedule content" in response.json()["detail"]


def test_current_grid_rejects_a_newer_schedule_refresh_that_does_not_verify(
    app: FastAPI, client: TestClient
) -> None:
    seeded = _seed(app)
    with app.state.database.session() as session:
        refresh = _schedule_refresh(session)
        record_refresh(
            session,
            artifact_type=RefreshArtifactType.SCHEDULE,
            artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
            version="not-the-content-fingerprint",
            source="test",
            season=SEASON,
            summary=dict(refresh.summary),
            refreshed_at=datetime(2027, 1, 1, tzinfo=UTC),
        )

    response = client.get(GRID_URL.format(league_id=seeded.league_id))

    assert response.status_code == 409
    assert _error_of(response) == "schedule_grid_not_current"
    assert "not-the-content-fingerprint" in response.json()["detail"]


def test_current_grid_rejects_scoring_periods_that_no_longer_match_the_calendar(
    app: FastAPI, client: TestClient
) -> None:
    seeded = _seed(app)
    with app.state.database.session() as session:
        period = session.scalar(
            select(ScoringPeriod)
            .where(ScoringPeriod.league_id == seeded.league_id)
            .order_by(ScoringPeriod.period_number)
            .limit(1)
        )
        assert period is not None
        period.end_date = period.start_date

    response = client.get(GRID_URL.format(league_id=seeded.league_id))

    assert response.status_code == 409
    assert _error_of(response) == "schedule_grid_not_current"


def test_current_grid_never_returns_a_success_shaped_empty_grid(
    app: FastAPI, client: TestClient
) -> None:
    seeded = _seed(app)
    with app.state.database.session() as session:
        session.execute(update(NbaTeam).values(is_active=False))

    response = client.get(GRID_URL.format(league_id=seeded.league_id))

    assert response.status_code == 409
    assert _error_of(response) == "schedule_grid_incomplete"
    assert "has no rows" in response.json()["detail"]
    assert "counts" not in response.json()


def test_current_grid_rejects_a_wholly_zero_grid(app: FastAPI, client: TestClient) -> None:
    """Verified games exist, but none land in this league's weeks.

    Returning 630 explicit zeroes here would be a well-formed answer that says
    "nobody plays all season", which is never true and is exactly the shape a
    reader would trust.
    """

    _seed(app)
    empty_weeks: list[tuple[int, date, date, bool]] = [
        (1, date(2026, 11, 30), date(2026, 12, 6), False),
        (2, date(2026, 12, 7), date(2026, 12, 13), True),
    ]
    with app.state.database.session() as session:
        league = _league(session, fantrax_league_id="empty-weeks")
        league_id = league.id
        _project_periods(session, league, empty_weeks)

    response = client.get(GRID_URL.format(league_id=league_id))

    assert response.status_code == 409
    assert _error_of(response) == "schedule_grid_incomplete_evidence"
    assert "none of them fall inside a scoring period" in response.json()["detail"]
    assert "counts" not in response.json()


# --------------------------------------------------------------------------
# The seed itself
# --------------------------------------------------------------------------


def test_seed_weekly_periods_cover_every_game_date_in_whole_weeks() -> None:
    periods = weekly_periods(date(2026, 10, 20), date(2027, 3, 14))

    assert periods[0][1] == date(2026, 10, 19)
    assert periods[0][1].weekday() == 0
    assert periods[-1][2] == date(2027, 3, 14)
    assert periods[-1][2].weekday() == 6
    assert all(end - start == (periods[0][2] - periods[0][1]) for _, start, end, _ in periods)
    assert [number for number, _, _, _ in periods] == list(range(1, len(periods) + 1))
    assert [is_playoff for _, _, _, is_playoff in periods][-2:] == [True, True]


def test_seed_reports_a_missing_fixture_directory_rather_than_failing_obscurely(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError, match="backend/tests/fixtures"):
        load_fixture(tmp_path, TEAMS_FIXTURE)
