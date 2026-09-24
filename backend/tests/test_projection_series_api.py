"""Real-importer/producer HTTP contracts for explicit current-within-series reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hoops_gm.api.routes import production_candidates, projections
from hoops_gm.db.models.enums import ExternalSource, ScoringType
from hoops_gm.db.models.league import League
from hoops_gm.db.models.projections import ProjectionImport
from hoops_gm.dev.seed_demo import DemoSeedResult, seed_demo
from hoops_gm.dev.seed_projections import DEMO_DISPLAY_NAME
from hoops_gm.ingest.projections import import_projection_csv
from hoops_gm.projections.blending import PROJECTION_RELEASE_SCHEMA_VERSION

FIXTURES = Path(__file__).parent / "fixtures" / "projections"
SOURCE = "basketball_monster"


def _database(client: TestClient) -> Any:
    return cast(FastAPI, client.app).state.database


@pytest.fixture
def recorded(client: TestClient) -> DemoSeedResult:
    with _database(client).session() as session:
        return seed_demo(session)


def _import(client: TestClient, *, key: str, fixture: str | None = None) -> int:
    with _database(client).session() as session:
        outcome = import_projection_csv(
            session,
            source=ExternalSource.BASKETBALL_MONSTER,
            display_name=DEMO_DISPLAY_NAME,
            season="2026-27",
            csv_bytes=(FIXTURES / f"series_{fixture or key}.csv").read_bytes(),
            original_filename=f"synthetic-series-{fixture or key}.csv",
            assumed_scoring_type=ScoringType.H2H_EACH_CATEGORY,
            series_key=key,
            series_display_name=key.title(),
        )
        return outcome.projection_import.id


def _url(recorded: DemoSeedResult, surface: str) -> str:
    if surface == "projections":
        return f"/api/v1/leagues/{recorded.projections.league_id}/projections/current"
    return f"/api/v1/drafts/{recorded.drafts.auction_draft_id}/production-candidates"


@pytest.mark.parametrize("surface", ["projections", "production_candidates"])
def test_legacy_call_then_ambiguous_omission_and_explicit_choices(
    client: TestClient, recorded: DemoSeedResult, surface: str
) -> None:
    url = _url(recorded, surface)
    legacy = client.get(url, params={"source": SOURCE})
    assert legacy.status_code == 200
    assert legacy.json()["series"] == {
        "key": "legacy",
        "display_name": "Unspecified legacy series",
        "provenance": "legacy_unspecified",
    }
    identifiers = {key: _import(client, key=key) for key in ("josh", "bonus")}
    omitted = client.get(url, params={"source": SOURCE})
    assert omitted.status_code == 409
    assert omitted.json()["error"] == f"{surface}_series_required"
    assert omitted.json()["request_id"]
    selected = {}
    for key in ("josh", "bonus"):
        response = client.get(url, params={"source": SOURCE, "series_key": key})
        assert response.status_code == 200
        body = response.json()
        assert body["series"] == {
            "key": key,
            "display_name": key.title(),
            "provenance": "operator_declared",
        }
        assert body["source_display_name"] == DEMO_DISPLAY_NAME
        lineage = body["lineage"]["projection_import"]
        assert lineage["series_key"] == key
        assert lineage["import_id"] == identifiers[key]
        assert lineage["release_schema_version"] == PROJECTION_RELEASE_SCHEMA_VERSION
        selected[key] = lineage
    assert (
        selected["josh"]["projection_values_sha256"]
        != selected["bonus"]["projection_values_sha256"]
    )
    assert client.get(url, params={"source": SOURCE, "series_key": "legacy"}).status_code == 200


def test_catalogs_use_real_context_and_do_not_claim_admission(
    client: TestClient, recorded: DemoSeedResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    josh = _import(client, key="josh")
    bonus = _import(client, key="bonus")
    latest = _import(client, key="josh", fixture="josh_v2")
    with _database(client).session() as session:
        row = session.get(ProjectionImport, latest)
        assert row is not None
        row.profile_verified = False

    def forbidden_release(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("inventory must not release or score a projection")

    monkeypatch.setattr(projections, "release_projection_import", forbidden_release)
    monkeypatch.setattr(production_candidates, "release_projection_import", forbidden_release)
    routes = (
        (
            f"/api/v1/leagues/{recorded.projections.league_id}/projections/series",
            recorded.projections.league_id,
        ),
        (
            f"/api/v1/drafts/{recorded.drafts.auction_draft_id}/projection-series",
            recorded.drafts.auction_league_id,
        ),
    )
    assert routes[0][1] != routes[1][1]
    for route, expected_league in routes:
        response = client.get(route, params={"source": SOURCE})
        assert response.status_code == 200
        body = response.json()
        assert body["league_id"] == expected_league
        assert body["season"] == "2026-27"
        assert body["selection_required"] is True
        entries = {entry["key"]: entry for entry in body["series"]}
        assert list(entries) == ["bonus", "josh", "legacy"]
        assert entries["josh"]["latest_import"]["import_id"] == latest != josh
        assert entries["bonus"]["latest_import"]["import_id"] == bonus
        assert entries["legacy"]["provenance"] == "legacy_unspecified"
        assert "projection_values_sha256" not in entries["josh"]["latest_import"]
        empty = client.get(route, params={"source": "manual"})
        assert empty.status_code == 200
        assert empty.json()["series"] == []
        assert empty.json()["source_display_name"] is None
        assert empty.json()["selection_required"] is False
        assert client.get(route, params={"source": "nba"}).status_code == 400


@pytest.mark.parametrize("surface", ["projections", "production_candidates"])
def test_sole_named_series_preserves_omitted_request_compatibility(
    client: TestClient, recorded: DemoSeedResult, surface: str
) -> None:
    url = _url(recorded, surface)
    legacy = client.get(url, params={"source": SOURCE})
    assert legacy.status_code == 200
    legacy_id = legacy.json()["lineage"]["projection_import"]["import_id"]
    josh = _import(client, key="josh")
    with _database(client).session() as session:
        old = session.get(ProjectionImport, legacy_id)
        assert old is not None
        session.delete(old)
    omitted = client.get(url, params={"source": SOURCE})
    explicit = client.get(url, params={"source": SOURCE, "series_key": "josh"})
    assert omitted.status_code == explicit.status_code == 200
    omitted_body, explicit_body = omitted.json(), explicit.json()
    assert omitted_body["lineage"]["projection_import"]["import_id"] == josh
    assert omitted_body["series"]["key"] == "josh"
    if surface == "production_candidates":
        omitted_body.pop("generated_at")
        explicit_body.pop("generated_at")
    assert omitted_body == explicit_body


@pytest.mark.parametrize("surface", ["projections", "production_candidates"])
def test_catalog_corrupt_series_is_a_typed_refusal(
    client: TestClient, recorded: DemoSeedResult, surface: str
) -> None:
    josh = _import(client, key="josh")
    with _database(client).session() as session:
        row = session.get(ProjectionImport, josh)
        assert row is not None
        row.series_key = "Josh"
    route = (
        f"/api/v1/leagues/{recorded.projections.league_id}/projections/series"
        if surface == "projections"
        else f"/api/v1/drafts/{recorded.drafts.auction_draft_id}/projection-series"
    )
    response = client.get(route, params={"source": SOURCE})
    assert response.status_code == 409
    assert response.json()["error"] == "projection_series_incomplete_evidence"
    assert response.json()["request_id"]


@pytest.mark.parametrize("surface", ["projections", "production_candidates"])
def test_newest_invalid_series_refuses_without_older_or_other_series_fallback(
    client: TestClient, recorded: DemoSeedResult, surface: str
) -> None:
    old = _import(client, key="josh")
    bonus = _import(client, key="bonus")
    newest = _import(client, key="josh", fixture="josh_v2")
    assert old != newest
    with _database(client).session() as session:
        row = session.get(ProjectionImport, newest)
        assert row is not None
        row.profile_verified = False
    url = _url(recorded, surface)
    refused = client.get(url, params={"source": SOURCE, "series_key": "josh"})
    assert refused.status_code == 409
    assert refused.json()["error"] == (
        "projections_incomplete_evidence"
        if surface == "projections"
        else "production_candidates_input_evidence_refused"
    )
    good = client.get(url, params={"source": SOURCE, "series_key": "bonus"})
    assert good.status_code == 200
    assert good.json()["lineage"]["projection_import"]["import_id"] == bonus


@pytest.mark.parametrize("surface", ["projections", "production_candidates"])
def test_invalid_and_missing_explicit_selections_never_fall_back(
    client: TestClient, recorded: DemoSeedResult, surface: str
) -> None:
    _import(client, key="josh")
    url = _url(recorded, surface)
    for key in ("", "Josh", " josh", "josh\n", "../josh", "x" * 65):
        response = client.get(url, params={"source": SOURCE, "series_key": key})
        assert response.status_code == 422, (key, response.json())
        assert response.json()["error"] == "validation_error"
    repeated = client.get(
        url, params=[("source", SOURCE), ("series_key", "josh"), ("series_key", "bonus")]
    )
    assert repeated.status_code == 422
    assert repeated.json()["error"] == "validation_error"
    for source, key in ((SOURCE, "absent"), ("manual", "josh")):
        response = client.get(url, params={"source": source, "series_key": key})
        assert response.status_code == 404
        assert response.json()["error"] == f"{surface}_series_not_imported"
    league_id = (
        recorded.projections.league_id
        if surface == "projections"
        else recorded.drafts.auction_league_id
    )
    with _database(client).session() as session:
        league = session.get(League, league_id)
        assert league is not None
        league.season = "2025-26"
    response = client.get(url, params={"source": SOURCE, "series_key": "josh"})
    assert response.status_code == 404
    assert response.json()["error"] == f"{surface}_series_not_imported"


@pytest.mark.parametrize("surface", ["projections", "production_candidates"])
def test_omitted_selection_becoming_ambiguous_during_read_is_refused(
    client: TestClient, recorded: DemoSeedResult, surface: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = projections if surface == "projections" else production_candidates
    original = module.release_projection_import
    written = False

    def release_then_add_series(*args: Any, **kwargs: Any) -> Any:
        nonlocal written
        released = original(*args, **kwargs)
        if not written:
            written = True
            _import(client, key="josh")
        return released

    monkeypatch.setattr(module, "release_projection_import", release_then_add_series)
    response = client.get(_url(recorded, surface), params={"source": SOURCE})
    assert written
    assert response.status_code == 409
    assert response.json()["error"] == f"{surface}_series_required"


@pytest.mark.parametrize("surface", ["projections", "production_candidates"])
def test_explicit_selection_survives_another_series_import_during_read(
    client: TestClient, recorded: DemoSeedResult, surface: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    josh = _import(client, key="josh")
    module = projections if surface == "projections" else production_candidates
    original = module.release_projection_import
    written = False

    def release_then_add_bonus(*args: Any, **kwargs: Any) -> Any:
        nonlocal written
        released = original(*args, **kwargs)
        if not written:
            written = True
            _import(client, key="bonus")
        return released

    monkeypatch.setattr(module, "release_projection_import", release_then_add_bonus)
    response = client.get(_url(recorded, surface), params={"source": SOURCE, "series_key": "josh"})
    assert written
    assert response.status_code == 200
    assert response.json()["series"]["key"] == "josh"
    assert response.json()["lineage"]["projection_import"]["import_id"] == josh


@pytest.mark.parametrize("surface", ["projections", "production_candidates"])
def test_newer_import_in_the_selected_series_during_read_uses_existing_refusal(
    client: TestClient, recorded: DemoSeedResult, surface: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    josh = _import(client, key="josh")
    module = projections if surface == "projections" else production_candidates
    original = module.release_projection_import
    written: list[int] = []

    def release_then_replace_josh(*args: Any, **kwargs: Any) -> Any:
        released = original(*args, **kwargs)
        if not written:
            written.append(_import(client, key="josh", fixture="josh_v2"))
        return released

    monkeypatch.setattr(module, "release_projection_import", release_then_replace_josh)
    response = client.get(_url(recorded, surface), params={"source": SOURCE, "series_key": "josh"})
    assert len(written) == 1 and written[0] != josh
    assert response.status_code == 409
    assert response.json()["error"] == (
        "projections_not_current"
        if surface == "projections"
        else "production_candidates_inconsistent_snapshot"
    )


def test_openapi_publishes_selection_catalog_and_release_domain(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    for path in (
        "/api/v1/leagues/{league_id}/projections/current",
        "/api/v1/drafts/{draft_id}/production-candidates",
    ):
        parameters = {item["name"]: item for item in schema["paths"][path]["get"]["parameters"]}
        assert parameters["series_key"]["required"] is False
    for path in (
        "/api/v1/leagues/{league_id}/projections/series",
        "/api/v1/drafts/{draft_id}/projection-series",
    ):
        assert "get" in schema["paths"][path]
        assert set(schema["paths"][path]) == {"get"}
    for model in ("ProjectionImportLineage", "ProjectionImportLineageOut"):
        fields = schema["components"]["schemas"][model]
        assert {"series_key", "release_schema_version"} <= set(fields["required"])
        assert (
            fields["properties"]["release_schema_version"]["$ref"]
            == "#/components/schemas/ProjectionReleaseSchema"
        )
    assert (
        schema["components"]["schemas"]["ProjectionReleaseSchema"]["const"]
        == PROJECTION_RELEASE_SCHEMA_VERSION
    )
