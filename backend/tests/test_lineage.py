"""Refresh lineage: the schedule/projection/model cohort registry.

Covers ``hoops_gm.db.lineage`` (the service functions) and the
``/api/v1/lineage`` router built on top of them. Deliberately does not test
anything about what a version *means* — see ``db/models/lineage.py``'s module
docstring for that boundary.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from hoops_gm.core.config import Settings
from hoops_gm.db.base import Base
from hoops_gm.db.lineage import (
    NBA_SCHEDULE_ARTIFACT_KEY,
    SCHEDULE_COMPLETENESS_SUMMARY_KEY,
    check_cohort,
    content_fingerprint,
    current_refresh,
    effective_current_version,
    lock_refresh_scope,
    record_refresh,
    schedule_completeness,
    schedule_content_version,
)
from hoops_gm.db.models.enums import RefreshArtifactType, SeasonType
from hoops_gm.db.models.identity import NbaTeam
from hoops_gm.db.models.lineage import RefreshRun
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.db.session import Database

# --------------------------------------------------------------------------
# content_fingerprint
# --------------------------------------------------------------------------


def test_content_fingerprint_is_deterministic() -> None:
    parts = ["1:2:3:2026-10-20:True", "4:5:6:2026-10-21:False"]

    assert content_fingerprint(parts) == content_fingerprint(list(parts))


def test_content_fingerprint_changes_when_the_facts_change() -> None:
    before = content_fingerprint(["1:2:3:2026-10-20:True"])
    after = content_fingerprint(["1:2:3:2026-10-21:True"])

    assert before != after


def test_content_fingerprint_is_sensitive_to_element_boundaries() -> None:
    """Concatenating without a separator would let ``"ab", "c"`` collide with ``"a", "bc"``."""
    joined = content_fingerprint(["ab", "c"])
    split = content_fingerprint(["a", "bc"])

    assert joined != split


# --------------------------------------------------------------------------
# record_refresh / current_refresh
# --------------------------------------------------------------------------


def test_record_refresh_creates_a_row(session: Any) -> None:
    run = record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        version="abc123",
        source="nba_api:ScheduleLeagueV2",
        season="2026-27",
        summary={"team_schedule_rows": 30},
    )

    assert run.id is not None
    assert run.artifact_type == RefreshArtifactType.SCHEDULE
    assert run.artifact_key == "default"
    assert run.version == "abc123"
    assert run.season == "2026-27"
    assert run.season_key == "2026-27"
    assert run.summary == {"team_schedule_rows": 30}


def test_record_refresh_is_idempotent_by_type_key_and_version(session: Any) -> None:
    first = record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        version="abc123",
        source="first-run",
        summary={"team_schedule_rows": 30},
    )
    second = record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        version="abc123",
        source="second-run",
        summary={"team_schedule_rows": 30},
    )

    assert first.id == second.id, (
        "the same (artifact_type, artifact_key, version) must not duplicate"
    )
    assert second.source == "second-run", "re-registering touches the row rather than no-op"
    rows = session.query(RefreshRun).all()
    assert len(rows) == 1


def test_record_refresh_opens_a_new_row_for_a_different_version(session: Any) -> None:
    record_refresh(session, artifact_type=RefreshArtifactType.SCHEDULE, version="v1", source="s")
    record_refresh(session, artifact_type=RefreshArtifactType.SCHEDULE, version="v2", source="s")

    rows = session.query(RefreshRun).all()
    assert len(rows) == 2


def test_record_refresh_separates_artifact_keys(session: Any) -> None:
    first = record_refresh(
        session,
        artifact_type=RefreshArtifactType.SOURCE,
        artifact_key="nba-schedule",
        version="v1",
        source="s",
    )
    second = record_refresh(
        session,
        artifact_type=RefreshArtifactType.SOURCE,
        artifact_key="injury-report",
        version="v1",
        source="s",
    )

    assert first.id != second.id
    assert (
        current_refresh(
            session,
            RefreshArtifactType.SOURCE,
            artifact_key="nba-schedule",
        )
        == first
    )
    assert (
        current_refresh(
            session,
            RefreshArtifactType.SOURCE,
            artifact_key="injury-report",
        )
        == second
    )


def test_record_refresh_preserves_the_same_version_for_each_season(session: Any) -> None:
    first = record_refresh(
        session,
        artifact_type=RefreshArtifactType.MODEL,
        artifact_key="off-night",
        version="derivation-v1",
        season="2026-27",
        source="s",
    )
    second = record_refresh(
        session,
        artifact_type=RefreshArtifactType.MODEL,
        artifact_key="off-night",
        version="derivation-v1",
        season="2027-28",
        source="s",
    )

    assert first.id != second.id
    assert first.season == "2026-27"
    assert second.season == "2027-28"
    assert (
        current_refresh(
            session,
            RefreshArtifactType.MODEL,
            artifact_key="off-night",
            season="2026-27",
        )
        == first
    )


def test_current_refresh_returns_none_when_nothing_registered(session: Any) -> None:
    assert current_refresh(session, RefreshArtifactType.MODEL) is None


def test_current_refresh_returns_the_most_recently_refreshed_row(session: Any) -> None:
    now = datetime.now(UTC)
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.PROJECTION,
        version="older",
        source="s",
        refreshed_at=now - timedelta(days=1),
    )
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.PROJECTION,
        version="newer",
        source="s",
        refreshed_at=now,
    )

    current = current_refresh(session, RefreshArtifactType.PROJECTION)

    assert current is not None
    assert current.version == "newer"


def test_current_refresh_is_scoped_to_its_own_artifact_type(session: Any) -> None:
    record_refresh(session, artifact_type=RefreshArtifactType.SCHEDULE, version="s1", source="s")

    assert current_refresh(session, RefreshArtifactType.MODEL) is None
    assert current_refresh(session, RefreshArtifactType.PROJECTION) is None


def test_current_refresh_can_scope_by_key_and_season_including_null(session: Any) -> None:
    now = datetime.now(UTC)
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SOURCE,
        artifact_key="nba-schedule",
        version="unscoped",
        source="s",
        refreshed_at=now,
    )
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SOURCE,
        artifact_key="nba-schedule",
        version="2026",
        season="2026-27",
        source="s",
        refreshed_at=now + timedelta(seconds=1),
    )

    unscoped = current_refresh(
        session,
        RefreshArtifactType.SOURCE,
        artifact_key="nba-schedule",
        season=None,
    )
    scoped = current_refresh(
        session,
        RefreshArtifactType.SOURCE,
        artifact_key="nba-schedule",
        season="2026-27",
    )

    assert unscoped is not None
    assert unscoped.version == "unscoped"
    assert scoped is not None
    assert scoped.version == "2026"


@pytest.mark.sqlite_only
def test_lock_refresh_scope_reserves_sqlite_writer_for_an_empty_scope(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'lock.db').as_posix()}?timeout=0.05",
        _env_file=None,
    )
    database = Database.from_settings(settings)
    Base.metadata.create_all(database.engine)
    try:
        with database.session() as seed_session:
            original = record_refresh(
                seed_session,
                artifact_type=RefreshArtifactType.SCHEDULE,
                version="sched-1",
                season="2026-27",
                source="fixture",
            )
            original_refreshed_at = original.refreshed_at

        lock_session = database.session_factory()
        competing_session = database.session_factory()
        try:
            lock_refresh_scope(
                lock_session,
                artifact_type=RefreshArtifactType.SOURCE,
                artifact_key="not-published-yet",
                season=None,
            )

            with pytest.raises(OperationalError, match="database is locked"):
                competing_session.execute(
                    update(RefreshRun)
                    .where(RefreshRun.id == original.id)
                    .values(source="competing-writer")
                )
        finally:
            competing_session.rollback()
            competing_session.close()
            lock_session.rollback()
            lock_session.close()

        with database.session() as verify_session:
            stored = verify_session.get(RefreshRun, original.id)
            assert stored is not None
            assert stored.refreshed_at == original_refreshed_at
            assert stored.source == "fixture"
    finally:
        Base.metadata.drop_all(database.engine)
        database.dispose()


# --------------------------------------------------------------------------
# check_cohort
# --------------------------------------------------------------------------


def test_check_cohort_reports_current_for_a_matching_claim(session: Any) -> None:
    record_refresh(
        session, artifact_type=RefreshArtifactType.SCHEDULE, version="sched-1", source="s"
    )

    [result] = check_cohort(session, schedule_version="sched-1")

    assert result.status == "current"
    assert result.current_version == "sched-1"


def test_check_cohort_reports_stale_for_a_superseded_claim(session: Any) -> None:
    record_refresh(
        session, artifact_type=RefreshArtifactType.SCHEDULE, version="sched-1", source="s"
    )
    record_refresh(
        session, artifact_type=RefreshArtifactType.SCHEDULE, version="sched-2", source="s"
    )

    [result] = check_cohort(session, schedule_version="sched-1")

    assert result.status == "stale"
    assert result.current_version == "sched-2"


def test_check_cohort_reports_unknown_when_nothing_was_ever_registered(session: Any) -> None:
    [result] = check_cohort(session, model_version="v1")

    assert result.status == "unknown"
    assert result.current_version is None
    assert result.current_refreshed_at is None


def test_check_cohort_only_checks_fields_the_caller_supplied(session: Any) -> None:
    record_refresh(
        session, artifact_type=RefreshArtifactType.SCHEDULE, version="sched-1", source="s"
    )

    results = check_cohort(session, schedule_version="sched-1")

    assert len(results) == 1
    assert results[0].artifact_type == RefreshArtifactType.SCHEDULE


def test_check_cohort_evaluates_a_full_cohort_independently_per_artifact(session: Any) -> None:
    record_refresh(
        session, artifact_type=RefreshArtifactType.SCHEDULE, version="sched-1", source="s"
    )
    record_refresh(session, artifact_type=RefreshArtifactType.MODEL, version="model-1", source="s")

    results = check_cohort(
        session,
        schedule_version="sched-1",
        model_version="wrong-model",
        projection_version="never-registered",
    )
    by_type = {r.artifact_type: r.status for r in results}

    assert by_type[RefreshArtifactType.SCHEDULE] == "current"
    assert by_type[RefreshArtifactType.MODEL] == "stale"
    assert by_type[RefreshArtifactType.PROJECTION] == "unknown"


def test_check_cohort_still_byte_compares_a_manually_registered_schedule(session: Any) -> None:
    """Legacy and hand-registered rows keep the original contract.

    A refresh registered without completeness metadata has no recorded cohort
    scope to recompute from — the honest answer is the stored label, not a
    fingerprint over rows that may have nothing to do with it. Deployments and
    tests that register a schedule version by hand must keep working.
    """
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version="manual-schedule-v1",
        source="operator",
        season="2026-27",
        summary={"note": "registered by hand"},
    )

    [result] = check_cohort(session, schedule_version="manual-schedule-v1")

    assert schedule_completeness({"note": "registered by hand"}) is None
    assert result.status == "current"
    assert result.current_version == "manual-schedule-v1"


def test_schedule_completeness_rejects_a_corrupt_block(session: Any) -> None:
    """Present-but-malformed is a corrupt registry, not an old one.

    Falling back to the weaker string comparison there would silently turn an
    unverifiable refresh into a verified-looking one, which is the exact
    direction of failure this seam exists to close.
    """
    del session

    with pytest.raises(ValueError, match="source_game_count"):
        schedule_completeness(
            {
                SCHEDULE_COMPLETENESS_SUMMARY_KEY: {
                    "season": "2026-27",
                    "season_type": "regular",
                    "resolved_game_count": 1230,
                    "unresolved_game_ids": [],
                    "persisted_team_row_count": 2460,
                }
            }
        )


def test_schedule_completeness_distinguishes_present_null_from_an_absent_legacy_key() -> None:
    assert schedule_completeness({"note": "legacy"}) is None

    with pytest.raises(ValueError, match="is not an object"):
        schedule_completeness({SCHEDULE_COMPLETENESS_SUMMARY_KEY: None})


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"source_game_count": -1, "persisted_team_row_count": -2}, "negative count"),
        ({"unresolved_game_ids": ["0022600001"]}, "unresolved game id"),
        ({"source_game_count": 6}, "source game"),
        ({"persisted_team_row_count": 11}, "persisted team row"),
    ],
    ids=["negative", "unresolved", "source-vs-resolved", "rows-vs-games"],
)
def test_schedule_completeness_rejects_logically_inconsistent_metadata(
    session: Any, overrides: dict[str, Any], expected: str
) -> None:
    """A block whose arithmetic cannot describe one import is wrong, not weak.

    Every one of these is a shape the importer can never produce, so reading
    one back means the registry was written by something else. Fail closed:
    the alternative is answering "current" from numbers that already
    contradict each other.
    """
    del session
    block: dict[str, Any] = {
        "season": "2026-27",
        "season_type": "regular",
        "source_game_count": 5,
        "resolved_game_count": 5,
        "unresolved_game_ids": [],
        "persisted_team_row_count": 10,
    }
    block.update(overrides)

    with pytest.raises(ValueError, match=expected):
        schedule_completeness({SCHEDULE_COMPLETENESS_SUMMARY_KEY: block})


def test_effective_current_version_refuses_a_block_scoped_to_another_season(
    session: Any,
) -> None:
    """The block must describe the refresh row it is attached to.

    A refresh scoped to 2026-27 carrying completeness metadata for 2025-26
    would otherwise be validated against a different season's rows entirely —
    the claim would be checked, just against the wrong facts.
    """
    run = record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version="whatever",
        source="operator",
        season="2026-27",
        summary={
            SCHEDULE_COMPLETENESS_SUMMARY_KEY: {
                "season": "2025-26",
                "season_type": "regular",
                "source_game_count": 5,
                "resolved_game_count": 5,
                "unresolved_game_ids": [],
                "persisted_team_row_count": 10,
            }
        },
    )

    with pytest.raises(ValueError, match="scoped to season"):
        effective_current_version(session, run)
    with pytest.raises(ValueError, match="scoped to season"):
        check_cohort(session, schedule_version="whatever")


def test_effective_current_version_refuses_a_forged_verified_looking_version(
    session: Any,
) -> None:
    """Metadata claiming a cohort the fingerprint does not cover is refused.

    This is the one way a self-consistent block could still lie: register the
    fingerprint of an *empty* cohort while claiming ten persisted rows, and
    the recomputed version matches the stored label. It would then read as a
    verified refresh over a season that has no schedule at all.
    """
    run = record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version=schedule_content_version(session, season="2026-27"),
        source="operator",
        season="2026-27",
        summary={
            SCHEDULE_COMPLETENESS_SUMMARY_KEY: {
                "season": "2026-27",
                "season_type": "regular",
                "source_game_count": 5,
                "resolved_game_count": 5,
                "unresolved_game_ids": [],
                "persisted_team_row_count": 10,
            }
        },
    )

    with pytest.raises(ValueError, match="fingerprints 0"):
        effective_current_version(session, run)


def test_schedule_content_version_is_empty_cohort_stable(session: Any) -> None:
    """An empty cohort still has a version, and it is not a claimed one.

    Deleting every row must not make an old registered version validate again
    by accident, so the scope header is fingerprinted even with no rows.
    """
    empty = schedule_content_version(session, season="2026-27")

    assert empty == schedule_content_version(session, season="2026-27")
    assert empty != schedule_content_version(session, season="2025-26")


# --------------------------------------------------------------------------
# HTTP contract
# --------------------------------------------------------------------------


def test_lineage_current_is_empty_when_nothing_registered(client: TestClient) -> None:
    response = client.get("/api/v1/lineage/current")

    assert response.status_code == 200
    assert response.json() == []


def test_lineage_current_lists_registered_refreshes(app: FastAPI, client: TestClient) -> None:
    with app.state.database.session() as session:
        record_refresh(
            session,
            artifact_type=RefreshArtifactType.SCHEDULE,
            version="sched-1",
            source="nba_api:ScheduleLeagueV2",
            season="2026-27",
            summary={"team_schedule_rows": 2460},
        )

    response = client.get("/api/v1/lineage/current")

    assert response.status_code == 200
    [entry] = response.json()
    assert entry["artifact_type"] == "schedule"
    assert entry["artifact_key"] == "default"
    assert entry["version"] == "sched-1"
    assert entry["season"] == "2026-27"
    assert entry["summary"] == {"team_schedule_rows": 2460}


def test_lineage_current_lists_each_keyed_season_scope(app: FastAPI, client: TestClient) -> None:
    with app.state.database.session() as session:
        for season in ("2026-27", "2027-28"):
            record_refresh(
                session,
                artifact_type=RefreshArtifactType.MODEL,
                artifact_key="off-night",
                version="derivation-v1",
                source="quant",
                season=season,
            )

    response = client.get("/api/v1/lineage/current")

    assert response.status_code == 200
    assert {
        (entry["artifact_key"], entry["season"], entry["version"]) for entry in response.json()
    } == {
        ("off-night", "2026-27", "derivation-v1"),
        ("off-night", "2027-28", "derivation-v1"),
    }


def test_lineage_validate_accepts_a_matching_cohort(app: FastAPI, client: TestClient) -> None:
    with app.state.database.session() as session:
        record_refresh(
            session, artifact_type=RefreshArtifactType.SCHEDULE, version="sched-1", source="s"
        )

    response = client.post("/api/v1/lineage/validate", json={"schedule_version": "sched-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["checks"][0]["status"] == "current"


def test_lineage_validate_accepts_an_exact_keyed_season_claim(
    app: FastAPI, client: TestClient
) -> None:
    with app.state.database.session() as session:
        record_refresh(
            session,
            artifact_type=RefreshArtifactType.SCHEDULE,
            artifact_key="nba-schedule",
            version="sched-1",
            source="s",
            season="2026-27",
        )

    response = client.post(
        "/api/v1/lineage/validate",
        json={
            "claims": [
                {
                    "artifact_type": "schedule",
                    "artifact_key": "nba-schedule",
                    "season": "2026-27",
                    "version": "sched-1",
                }
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["checks"] == [
        {
            "artifact_type": "schedule",
            "artifact_key": "nba-schedule",
            "season": "2026-27",
            "claimed_version": "sched-1",
            "status": "current",
            "current_version": "sched-1",
            "current_refreshed_at": body["checks"][0]["current_refreshed_at"],
        }
    ]


def test_lineage_http_never_promotes_an_unregistered_schedule_fingerprint(
    app: FastAPI,
    client: TestClient,
) -> None:
    with app.state.database.session() as session:
        run = _register_test_schedule(session)
        registered_version = run.version
        game = session.scalar(select(NbaGame))
        assert game is not None
        game.game_date = game.game_date + timedelta(days=1)
        for entry in session.scalars(
            select(TeamScheduleEntry).where(TeamScheduleEntry.game_id == game.id)
        ):
            entry.game_date = game.game_date
        session.flush()
        observed_version = schedule_content_version(session, season="2026-27")

    for claimed_version in (registered_version, observed_version):
        response = client.post(
            "/api/v1/lineage/validate",
            json={
                "claims": [
                    {
                        "artifact_type": "schedule",
                        "artifact_key": NBA_SCHEDULE_ARTIFACT_KEY,
                        "season": "2026-27",
                        "version": claimed_version,
                    }
                ]
            },
        )

        assert response.status_code == 200
        [check] = response.json()["checks"]
        assert check["status"] == "stale"
        assert check["current_version"] is None
        assert check["current_refreshed_at"] is None
        assert response.json()["accepted"] is False

    current_response = client.get("/api/v1/lineage/current")
    assert current_response.status_code == 200
    assert current_response.json() == []


def test_lineage_http_fails_loudly_for_present_null_schedule_metadata(app: FastAPI) -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        Base.metadata.drop_all(app.state.database.engine)
        Base.metadata.create_all(app.state.database.engine)
        with app.state.database.session() as session:
            record_refresh(
                session,
                artifact_type=RefreshArtifactType.SCHEDULE,
                artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
                version="invalid-metadata",
                source="operator",
                season="2026-27",
                summary={SCHEDULE_COMPLETENESS_SUMMARY_KEY: None},
            )

        responses = [
            client.get("/api/v1/lineage/current"),
            client.post(
                "/api/v1/lineage/validate",
                json={
                    "claims": [
                        {
                            "artifact_type": "schedule",
                            "artifact_key": NBA_SCHEDULE_ARTIFACT_KEY,
                            "season": "2026-27",
                            "version": "invalid-metadata",
                        }
                    ]
                },
            ),
        ]

    for response in responses:
        assert response.status_code == 500
        assert response.json()["error"] == "internal_error"


def test_lineage_validate_reports_stale_and_unknown(app: FastAPI, client: TestClient) -> None:
    with app.state.database.session() as session:
        record_refresh(
            session, artifact_type=RefreshArtifactType.SCHEDULE, version="sched-2", source="s"
        )

    response = client.post(
        "/api/v1/lineage/validate",
        json={"schedule_version": "sched-1", "model_version": "m1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    by_type = {check["artifact_type"]: check["status"] for check in body["checks"]}
    assert by_type["schedule"] == "stale"
    assert by_type["model"] == "unknown"


def test_lineage_validate_rejects_an_empty_claim(client: TestClient) -> None:
    """Asserting nothing must not read as "everything is fine"."""
    response = client.post("/api/v1/lineage/validate", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["checks"] == []
    assert body["accepted"] is False


def test_lineage_validate_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post(
        "/api/v1/lineage/validate", json={"schedule_version": "x", "typo_field": "y"}
    )

    assert response.status_code == 422


def test_lineage_contract_is_advertised_in_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/lineage/current" in paths
    assert "/api/v1/lineage/validate" in paths


def _register_test_schedule(session: Any) -> RefreshRun:
    home = NbaTeam(nba_team_id=1, abbreviation="HME", name="Home")
    away = NbaTeam(nba_team_id=2, abbreviation="AWY", name="Away")
    session.add_all([home, away])
    session.flush()
    game = NbaGame(
        nba_game_id="0022600001",
        season="2026-27",
        season_type=SeasonType.REGULAR,
        game_date=date(2026, 10, 20),
        home_team_id=home.id,
        away_team_id=away.id,
    )
    session.add(game)
    session.flush()
    session.add_all(
        [
            TeamScheduleEntry(
                season="2026-27",
                season_type=SeasonType.REGULAR,
                game_id=game.id,
                team_id=home.id,
                opponent_team_id=away.id,
                game_date=game.game_date,
                is_home=True,
            ),
            TeamScheduleEntry(
                season="2026-27",
                season_type=SeasonType.REGULAR,
                game_id=game.id,
                team_id=away.id,
                opponent_team_id=home.id,
                game_date=game.game_date,
                is_home=False,
            ),
        ]
    )
    session.flush()
    version = schedule_content_version(session, season="2026-27")
    return record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version=version,
        source="test",
        season="2026-27",
        summary={
            SCHEDULE_COMPLETENESS_SUMMARY_KEY: {
                "season": "2026-27",
                "season_type": "regular",
                "source_game_count": 1,
                "resolved_game_count": 1,
                "unresolved_game_ids": [],
                "persisted_team_row_count": 2,
            }
        },
    )
