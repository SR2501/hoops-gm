"""Refresh lineage: the schedule/projection/model cohort registry.

Covers ``hoops_gm.db.lineage`` (the service functions) and the
``/api/v1/lineage`` router built on top of them. Deliberately does not test
anything about what a version *means* — see ``db/models/lineage.py``'s module
docstring for that boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.exc import OperationalError

from hoops_gm.core.config import Settings
from hoops_gm.db.base import Base
from hoops_gm.db.lineage import (
    check_cohort,
    content_fingerprint,
    current_refresh,
    lock_refresh_scope,
    record_refresh,
)
from hoops_gm.db.models.enums import RefreshArtifactType
from hoops_gm.db.models.lineage import RefreshRun
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
