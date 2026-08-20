"""The schedule-grid API: one operational proof, and one test per refusal.

The shape of this file is deliberate, and the reason is narrower than it looks.
PR #36's tests *did* assert 200 — three times — and still shipped an endpoint
that could never return one. They passed because a test-local helper wrote the
refresh summary itself, in the flat shape #36's hand-rolled reader wanted and
``import_schedule`` has never written. **The tests played the producer.**

So the rule here is not "assert a 200", which #36 already satisfied. It is that
the success-path database state is built by the **production writers** —
``hoops_gm.dev.seed_schedule_grid`` calling ``import_teams``,
``import_schedule``, ``import_league_settings``, ``derive_deadline_calendar``
and ``project_scoring_periods`` — and never by this file. **Most** refusal
tests then start from that same seeded, genuinely valid database and break
exactly one thing, so a 409 is evidence that the broken thing caused it rather
than evidence the endpoint was never reachable in the first place.

A minority deliberately do not, and saying "every" would have been false. Four
have no valid state to break: the unknown-league and non-integer-id cases touch
an empty database or none at all, the no-registered-refresh case has a league
and nothing else, and the no-settings case is hand-built partial state rather
than seed-then-break. An earlier version of this docstring said "two", which
was itself the kind of uncounted claim this file exists to avoid.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, update
from sqlalchemy.orm import Session

from hoops_gm.api.routes.schedule_grid import _grid_periods, _grid_teams
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
from hoops_gm.db.models.enums import RefreshArtifactType, SeasonType
from hoops_gm.db.models.identity import NbaTeam
from hoops_gm.db.models.league import League, ScoringPeriod
from hoops_gm.db.models.lineage import RefreshRun
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.db.session import Database, acquire_transaction_lock
from hoops_gm.dev.seed_schedule_grid import (
    DEFAULT_FIXTURES_DIR,
    SCHEDULE_FIXTURE,
    SEASON,
    TEAMS_FIXTURE,
    DemoSeedRefused,
    SeedResult,
    load_fixture,
    main,
    reconcile_dropped_games,
    redacted_url,
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
from hoops_gm.ingest.nba.schedule import parse_schedule, scheduled_game_counts

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


@pytest.mark.sqlite_only
def test_current_grid_does_not_commit_lineage_lock_reservations(
    app: FastAPI, client: TestClient
) -> None:
    """A read must not advance any refresh row's own audit timestamps.

    SQLite-only by construction, not by convenience. A lineage lock is a real
    write there — ``acquire_transaction_lock`` issues a no-op UPDATE to take the
    database-wide write reservation — so ``updated_at`` moves unless the route
    rolls back. On PostgreSQL the same call is ``pg_advisory_xact_lock``, which
    touches no row, so this test would pass with the rollback deleted and would
    be advertising a guarantee it was not checking.
    """

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


def test_current_grid_takes_lineage_locks_in_the_codebase_canonical_order(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """League settings before the NBA schedule, or PostgreSQL can deadlock.

    ``_locked_projection_context`` and ``_lock_calendar_inputs`` both take these
    two scopes settings-first. On PostgreSQL each is a ``pg_advisory_xact_lock``
    held to commit, so a reader taking them schedule-first while a calendar
    derivation holds settings is a textbook ABBA deadlock — and SQLite cannot
    show it, because its lock degrades to one database-wide reservation.
    """

    seeded = _seed(app)
    taken: list[str] = []

    def _record(session: Session, *, scope_key: str, write_reservation: Any) -> None:
        taken.append(scope_key)
        acquire_transaction_lock(session, scope_key=scope_key, write_reservation=write_reservation)

    monkeypatch.setattr("hoops_gm.db.lineage.acquire_transaction_lock", _record)

    assert client.get(GRID_URL.format(league_id=seeded.league_id)).status_code == 200

    settings_scope = f"source\x00league-settings:{seeded.league_id}\x00{SEASON}"
    schedule_scope = f"schedule\x00{NBA_SCHEDULE_ARTIFACT_KEY}\x00{SEASON}"
    projection_scope = f"schedule\x00league-scoring-periods:{seeded.league_id}\x00{SEASON}"
    # The whole sequence, not a prefix. `_locked_projection_context` takes the
    # same two scopes in the same order later in the request, so asserting only
    # `taken[:2]` would be satisfied by that call alone and would still pass
    # with the route's own acquisitions deleted — leaving
    # `_verified_schedule_evidence` reading lineage outside any lock, which is
    # the reason they are there.
    assert taken == [
        settings_scope,
        schedule_scope,
        settings_scope,
        schedule_scope,
        projection_scope,
    ]


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


def _development_app(tmp_path: Path, test_database_url: str | None) -> FastAPI:
    """An app outside ``environment="test"``, on whichever database CI is using.

    ``require_loopback_host``'s escape hatch is keyed on the test environment,
    so the 403 path and the genuine-peer 200 path can only be reached from an
    app configured as ``development``. Taking the database from the session
    fixture rather than hardcoding SQLite is what lets both paths run on the
    PostgreSQL lane — and it is what makes the drop-then-create below load
    bearing, since ``TEST_DATABASE_URL`` points every test at one shared
    external database where an earlier test's rows would otherwise survive.
    """

    return create_app(
        Settings(
            environment="development",
            database_url=test_database_url or f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
            bridge_secret_path=tmp_path / "bridge_secret",
            _env_file=None,
        )
    )


def test_current_grid_rejects_non_loopback_callers(
    tmp_path: Path, test_database_url: str | None
) -> None:
    app = _development_app(tmp_path, test_database_url)
    with TestClient(app) as client:
        Base.metadata.drop_all(app.state.database.engine)
        Base.metadata.create_all(app.state.database.engine)
        seeded = _seed(app)

        response = client.get(GRID_URL.format(league_id=seeded.league_id))

    assert response.status_code == 403
    assert _error_of(response) == "schedule_grid_local_only"
    assert "counts" not in response.json()


def test_current_grid_serves_a_loopback_proxy_peer_outside_test_environment(
    tmp_path: Path, test_database_url: str | None
) -> None:
    app = _development_app(tmp_path, test_database_url)
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
    # Pins the branch: schedule staleness reaches the same code, so the code
    # alone cannot say which fired.
    assert "no active deadline calendar" in response.json()["detail"]
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
    assert "counts" not in response.json()


def test_current_grid_rejects_a_non_regular_season_cohort(app: FastAPI, client: TestClient) -> None:
    """`verify_refresh` fingerprints the block's season type; counts are REGULAR.

    They agree today only because `import_schedule` hard-codes REGULAR. A
    playoff cohort registered under this artifact key would otherwise verify one
    cohort and count another, and return 200 with a lineage block that does not
    describe the numbers beside it.
    """

    seeded = _seed(app)
    with app.state.database.session() as session:
        refresh = _schedule_refresh(session)
        block = dict(refresh.summary[SCHEDULE_COMPLETENESS_SUMMARY_KEY])  # type: ignore[call-overload]
        block["season_type"] = SeasonType.PLAYOFFS.value
        refresh.summary = {**refresh.summary, SCHEDULE_COMPLETENESS_SUMMARY_KEY: block}

    response = client.get(GRID_URL.format(league_id=seeded.league_id))

    assert response.status_code == 409
    assert _error_of(response) == "schedule_grid_incomplete_evidence"
    assert "regular-season games only" in response.json()["detail"]
    assert "counts" not in response.json()


def test_current_grid_refuses_a_team_id_it_cannot_label(app: FastAPI, client: TestClient) -> None:
    """A partially-labelled grid still looks like an answer, so refuse instead."""

    seeded = _seed(app)
    with app.state.database.session() as session:
        rows = scheduled_game_counts(session, league_id=seeded.league_id, season=SEASON)
        missing_team_id = max(row.team_id for row in rows) + 1
        unlabelled = replace(rows[0], team_id=missing_team_id)

        with pytest.raises(HTTPException) as caught:
            _grid_teams(session, [unlabelled])

    assert caught.value.status_code == 409
    assert caught.value.headers == {"X-Bridge-Error": "schedule_grid_incomplete_evidence"}
    assert "have no team row" in str(caught.value.detail)
    # The message must name the id, or an operator cannot act on it.
    assert str(missing_team_id) in str(caught.value.detail)


def test_current_grid_refuses_a_period_number_it_cannot_date(
    app: FastAPI, client: TestClient
) -> None:
    seeded = _seed(app)
    with app.state.database.session() as session:
        rows = scheduled_game_counts(session, league_id=seeded.league_id, season=SEASON)
        missing_period = max(row.period_number for row in rows) + 1
        undated = replace(rows[0], period_number=missing_period)

        with pytest.raises(HTTPException) as caught:
            _grid_periods(session, league_id=seeded.league_id, rows=[undated])

    assert caught.value.status_code == 409
    assert caught.value.headers == {"X-Bridge-Error": "schedule_grid_incomplete_evidence"}
    assert "has no row for" in str(caught.value.detail)
    assert str(missing_period) in str(caught.value.detail)


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
    # The route's own wording, not `_locked_projection_context`'s. Both map to
    # this code, so a looser assertion would still pass with the route's
    # verification deleted.
    assert "no longer matches the persisted schedule content" in response.json()["detail"]
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
    assert "do not match active deadline calendar" in response.json()["detail"]


def test_current_grid_rejects_a_non_integer_league_id(client: TestClient) -> None:
    """The advertised 422 is behaviour, not just an OpenAPI entry."""

    response = client.get(GRID_URL.format(league_id="not-a-league"))

    assert response.status_code == 422
    assert _error_of(response) == "validation_error"
    assert "counts" not in response.json()


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


def test_seed_counts_a_neutral_site_game_for_both_teams(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    """Neutral-site games are a recurring annual class, not an edge case.

    NBA Cup knockouts in Las Vegas plus the international slate are roughly five
    regular-season games every year, and they are what the historical
    1,225-vs-1,230 defect turned out to be: `LeagueGameFinder` repeats the same
    `MATCHUP` string on both team rows, so a parser deriving the side from the
    separator resolved both rows identically and lost the game.

    This grid cannot inherit that defect, and the mechanism is worth stating
    rather than assuming. `parse_schedule` reads `ScheduleLeagueV2`, which
    carries explicit `homeTeam.teamId` and `awayTeam.teamId` objects — no
    `MATCHUP` string exists on this path — and `import_schedule` writes two
    mirrored `team_schedule` rows per game unconditionally. The test proves it
    against a payload carrying `isNeutral: true` rather than trusting that
    reading.
    """

    payload = load_fixture(DEFAULT_FIXTURES_DIR, SCHEDULE_FIXTURE)
    neutral_date = payload["leagueSchedule"]["gameDates"][0]
    template = neutral_date["games"][0]
    home_nba_id, away_nba_id = 1610612747, 1610612744  # LAL, GSW: in neither existing game
    neutral_date["games"].append(
        {
            **template,
            "gameId": "0022600099",
            "gameLabel": "Emirates NBA Cup",
            "isNeutral": True,
            "arenaName": "T-Mobile Arena",
            "arenaCity": "Las Vegas",
            "homeTeam": {**template["homeTeam"], "teamId": home_nba_id, "teamTricode": "LAL"},
            "awayTeam": {**template["awayTeam"], "teamId": away_nba_id, "teamTricode": "GSW"},
        }
    )
    (tmp_path / SCHEDULE_FIXTURE).write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / TEAMS_FIXTURE).write_text(
        json.dumps(load_fixture(DEFAULT_FIXTURES_DIR, TEAMS_FIXTURE)), encoding="utf-8"
    )

    with app.state.database.session() as session:
        seeded = seed_schedule_grid(session, fixtures_dir=tmp_path)

    assert seeded.resolved_game_count == 11
    body = client.get(GRID_URL.format(league_id=seeded.league_id)).json()
    assert body["lineage"]["schedule"]["persisted_team_row_count"] == 22
    nba_id_by_team_id = {team["team_id"]: team["nba_team_id"] for team in body["teams"]}
    counted = {
        nba_id_by_team_id[row["team_id"]]
        for row in body["counts"]
        if row["period_number"] == 1 and row["games"] > 0
    }
    # Both sides of the neutral game, not just the nominal home team.
    assert {home_nba_id, away_nba_id} <= counted


def test_seed_refuses_a_database_holding_a_league_with_no_fantrax_id(
    app: FastAPI, client: TestClient
) -> None:
    """`fantrax_league_id` is nullable, so a NULL row must not read as absent.

    A league created before Fantrax pairing is exactly this shape, and scalar-
    selecting the nullable column would return `None` for it — skipping the
    refusal for the one row it was written to catch.
    """

    with app.state.database.session() as session:
        league = League(
            name="Unpaired league",
            season=SEASON,
            fantrax_league_id=None,
            scoring_type="h2h_categories",
            draft_type="auction",
        )
        session.add(league)

    with pytest.raises(DemoSeedRefused, match="which this seed did not create"):
        _seed(app)

    with app.state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(NbaGame)) == 0
        assert session.scalar(select(func.count()).select_from(RefreshRun)) == 0


def test_seed_takes_lineage_locks_in_the_codebase_canonical_order(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seed composes two importers that each lock a different scope.

    `import_schedule` takes `nba-schedule`; `import_league_settings` takes
    league-settings. Called in the obvious order they acquire the two in the
    exact inverse of the order the route and the calendar functions use, and on
    PostgreSQL a re-seed racing a dashboard poll is `40P01`. Static enumeration
    of lock sites cannot see this — the ordering exists only when the two
    functions are composed at runtime — so this test instruments the lock itself.
    """

    taken: list[str] = []

    def _record(session: Session, *, scope_key: str, write_reservation: Any) -> None:
        taken.append(scope_key)
        acquire_transaction_lock(session, scope_key=scope_key, write_reservation=write_reservation)

    monkeypatch.setattr("hoops_gm.db.lineage.acquire_transaction_lock", _record)

    seeded = _seed(app)

    settings_scope = f"source\x00league-settings:{seeded.league_id}\x00{SEASON}"
    schedule_scope = f"schedule\x00{NBA_SCHEDULE_ARTIFACT_KEY}\x00{SEASON}"
    assert settings_scope in taken
    assert schedule_scope in taken
    assert taken.index(settings_scope) < taken.index(schedule_scope), (
        f"seed acquired lineage scopes in the order {taken}, which inverts the codebase's "
        "league-settings-before-nba-schedule order"
    )


def test_seed_cli_prints_the_redacted_url_not_the_raw_one(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins `main` -> `redacted_url`, which is the wiring that keeps regressing.

    Asserted at the seam rather than on a password substring, because a SQLite
    URL has no credential to look for and this must not depend on the dialect.
    This path has now been fixed twice — `URL.password`, then the libpq
    query-argument hole — so it is the one most likely to be reverted.
    """

    monkeypatch.setattr(
        "hoops_gm.dev.seed_schedule_grid.redacted_url", lambda _url: "REDACTED-BY-SEAM"
    )
    url = f"sqlite:///{(tmp_path / 'seed.db').as_posix()}"
    capsys.readouterr()

    assert main(["--database-url", url]) == 0

    out = capsys.readouterr().out
    assert "REDACTED-BY-SEAM" in out
    assert url not in out


def test_seed_cli_masks_credentials_in_both_url_positions() -> None:
    """`render_as_string(hide_password=True)` masks userinfo only.

    libpq takes `password`/`sslpassword` as query arguments and SQLAlchemy
    forwards them, so a query-string credential is real and would otherwise be
    printed to stdout verbatim.
    """

    masked = redacted_url(
        "postgresql+psycopg://alice:userinfo-secret@db.example.com:5432/hoops"
        "?password=query-secret&sslpassword=ssl-secret&sslmode=require"
    )

    assert "userinfo-secret" not in masked
    assert "query-secret" not in masked
    assert "ssl-secret" not in masked
    assert "sslmode=require" in masked
    assert "alice" in masked


def test_seed_cli_refusal_exits_non_zero_without_a_traceback(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The refusal path is an operator message and an exit code, not a crash.

    Deliberately does not parse captured stdout as JSON. The seed's own output
    is already asserted through `SeedResult`, and reading the global capture
    buffer couples this test to whatever else happened to write to it.
    """

    url = f"sqlite:///{(tmp_path / 'seed.db').as_posix()}"
    database = Database.from_settings(
        Settings(environment="development", database_url=url, _env_file=None)
    )
    try:
        Base.metadata.create_all(database.engine)
        with database.session() as session:
            session.add(
                League(
                    name="Someone else's league",
                    season=SEASON,
                    fantrax_league_id="not-the-demo",
                    scoring_type="h2h_categories",
                    draft_type="auction",
                )
            )
    finally:
        database.dispose()
    capsys.readouterr()

    assert main(["--database-url", url]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refusing to seed: " in captured.err
    assert "not-the-demo" in captured.err
    assert "Traceback" not in captured.err


def test_seed_cli_leaves_no_schema_behind_when_it_refuses(tmp_path: Path) -> None:
    """A refusal must not have already written DDL to the operator's database.

    `create_all` used to run before the guard, so pointing the seed at a real
    Alembic-built database that was behind head added the missing model tables,
    the seed then refused, and the next `alembic upgrade head` failed with
    "relation already exists". The tool whose headline property is that it
    refuses to touch a real database had already written to it.
    """

    url = f"sqlite:///{(tmp_path / 'partial.db').as_posix()}"
    database = Database.from_settings(
        Settings(environment="development", database_url=url, _env_file=None)
    )
    try:
        Base.metadata.create_all(
            database.engine, tables=[Base.metadata.tables[League.__tablename__]]
        )
        with database.session() as session:
            session.add(
                League(
                    name="Someone else's league",
                    season=SEASON,
                    fantrax_league_id="not-the-demo",
                    scoring_type="h2h_categories",
                    draft_type="auction",
                )
            )
    finally:
        database.dispose()

    assert main(["--database-url", url]) == 2

    verify = Database.from_settings(
        Settings(environment="development", database_url=url, _env_file=None)
    )
    try:
        tables = set(inspect(verify.engine).get_table_names())
    finally:
        verify.dispose()
    assert League.__tablename__ in tables
    assert NbaGame.__tablename__ not in tables
    assert TeamScheduleEntry.__tablename__ not in tables
    assert RefreshRun.__tablename__ not in tables


def test_seed_reconciliation_refuses_a_filter_that_leaves_unresolved_games(
    tmp_path: Path,
) -> None:
    """The second arm: filtered, but something unassigned survived."""

    recorded = parse_schedule(load_fixture(DEFAULT_FIXTURES_DIR, SCHEDULE_FIXTURE), season=SEASON)
    del tmp_path

    with pytest.raises(DemoSeedRefused, match="still reports unresolved games"):
        reconcile_dropped_games(recorded, recorded)


def test_seed_weekly_periods_cover_every_game_date_in_whole_weeks() -> None:
    periods = weekly_periods(date(2026, 10, 20), date(2027, 3, 14))

    assert periods[0][1] == date(2026, 10, 19)
    assert periods[0][1].weekday() == 0
    assert periods[-1][2] == date(2027, 3, 14)
    assert periods[-1][2].weekday() == 6
    assert all(end - start == (periods[0][2] - periods[0][1]) for _, start, end, _ in periods)
    assert [number for number, _, _, _ in periods] == list(range(1, len(periods) + 1))
    assert [is_playoff for _, _, _, is_playoff in periods][-2:] == [True, True]


@pytest.mark.parametrize(
    ("first", "last"),
    [
        (date(2026, 10, 19), date(2026, 10, 25)),  # one Mon-Sun week
        (date(2026, 10, 19), date(2026, 11, 1)),  # exactly two weeks
    ],
)
def test_seed_refuses_a_span_too_short_to_have_a_playoff_tail(first: date, last: date) -> None:
    """Otherwise the naive tail slice marks the entire season as playoffs."""

    with pytest.raises(DemoSeedRefused, match="playoff weeks are a tail"):
        weekly_periods(first, last)


def test_seed_reconciliation_refuses_a_filter_that_drops_a_resolved_game() -> None:
    """The check that makes over-removal loud instead of silent.

    The TBD filter runs upstream of `parse_schedule`, so a dropped game vanishes
    from both sides of `import_schedule`'s completeness comparison at once. If
    the NBA redrew the Cup and the fixture were re-recorded with six unassigned
    games, a filter bug could silently import a season six games short and still
    register `unresolved_game_ids: []`.
    """

    recorded = parse_schedule(load_fixture(DEFAULT_FIXTURES_DIR, SCHEDULE_FIXTURE), season=SEASON)
    payload = resolved_schedule_payload(load_fixture(DEFAULT_FIXTURES_DIR, SCHEDULE_FIXTURE))
    payload["leagueSchedule"]["gameDates"][0]["games"].pop()
    over_filtered = parse_schedule(payload, season=SEASON)

    with pytest.raises(DemoSeedRefused, match="changed the resolved cohort"):
        reconcile_dropped_games(recorded, over_filtered)


def test_seed_reconciliation_reports_exactly_the_recorded_unresolved_games() -> None:
    recorded = parse_schedule(load_fixture(DEFAULT_FIXTURES_DIR, SCHEDULE_FIXTURE), season=SEASON)
    filtered = parse_schedule(
        resolved_schedule_payload(load_fixture(DEFAULT_FIXTURES_DIR, SCHEDULE_FIXTURE)),
        season=SEASON,
    )

    assert reconcile_dropped_games(recorded, filtered) == ("0022601201", "0022601202")
    assert recorded.source_game_count == 12
    assert filtered.source_game_count == 10


def test_seed_result_reports_the_as_recorded_source_count_beside_the_imported_one(
    app: FastAPI, client: TestClient
) -> None:
    """The registered block describes the filtered document; this states so."""

    seeded = _seed(app)

    assert seeded.resolved_game_count == 10
    assert seeded.as_recorded_source_game_count == 12
    assert seeded.dropped_game_ids == ("0022601201", "0022601202")


def test_seed_refuses_a_database_holding_a_league_it_did_not_create(
    app: FastAPI, client: TestClient
) -> None:
    """`nba_games`, `team_schedule` and the schedule refresh are not league-scoped.

    Aiming the seed at the operator's working database would make a ten-game
    fixture the current registered season cohort for every consumer keyed to
    schedule version.
    """

    with app.state.database.session() as session:
        _league(session, fantrax_league_id="the-operators-real-league")

    with pytest.raises(DemoSeedRefused, match="the-operators-real-league"):
        _seed(app)

    with app.state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(NbaGame)) == 0
        assert session.scalar(select(func.count()).select_from(TeamScheduleEntry)) == 0
        assert session.scalar(select(func.count()).select_from(RefreshRun)) == 0


def test_seed_refuses_a_database_holding_an_out_of_cohort_game_for_the_season(
    app: FastAPI, client: TestClient
) -> None:
    seeded = _seed(app)
    with app.state.database.session() as session:
        team_ids = list(session.scalars(select(NbaTeam.id).order_by(NbaTeam.id).limit(2)))
        session.add(
            NbaGame(
                nba_game_id="0022699999",
                season=SEASON,
                season_type=SeasonType.REGULAR,
                game_date=date(2027, 1, 5),
                home_team_id=team_ids[0],
                away_team_id=team_ids[1],
            )
        )

    with pytest.raises(DemoSeedRefused, match="0022699999"):
        _seed(app)

    assert seeded.league_id


def test_seed_reports_a_missing_fixture_directory_rather_than_failing_obscurely(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError, match="backend/tests/fixtures"):
        load_fixture(tmp_path, TEAMS_FIXTURE)
