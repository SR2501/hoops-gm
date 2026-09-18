"""Producer-to-HTTP contract tests for recorded-draft production candidates."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import hoops_gm.dev.seed_demo as seed_demo_module
from hoops_gm.api.routes import production_candidates
from hoops_gm.availability.reliability import (
    RELIABILITY_SOURCE_KEY,
    publish_reliability_cohorts,
)
from hoops_gm.db.lineage import current_refresh, record_refresh
from hoops_gm.db.models.enums import ExternalSource, RefreshArtifactType
from hoops_gm.db.models.identity import NbaTeam, Player, PlayerExternalId
from hoops_gm.db.models.projections import Projection, ProjectionImport
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog
from hoops_gm.dev.seed_demo import DemoSeedResult, seed_demo
from hoops_gm.dev.seed_draft import CanonicalDraftPlayer, seed_drafts
from hoops_gm.dev.seed_projections import (
    DEMO_DISPLAY_NAME,
    DEMO_FILENAME,
    seed_projections,
)
from hoops_gm.dev.seed_schedule_grid import DEFAULT_FIXTURES_DIR
from hoops_gm.ingest.importers import import_box_scores
from hoops_gm.ingest.nba.models import PlayerBoxScoreRecord
from hoops_gm.projections.blending import (
    BlendProfile,
    MissingProjectionDataError,
    ReleasedProjectionImport,
    StaleProjectionInputError,
)
from hoops_gm.projections.blending import (
    release_projection_import as canonical_release_projection_import,
)

SOURCE = "basketball_monster"
RATE_FIELDS = {
    "points_per_game",
    "rebounds_per_game",
    "assists_per_game",
    "steals_per_game",
    "blocks_per_game",
    "turnovers_per_game",
    "three_pointers_made_per_game",
    "field_goals_made_per_game",
    "field_goals_attempted_per_game",
    "free_throws_made_per_game",
    "free_throws_attempted_per_game",
}
CATEGORY_KEYS = {"pts", "reb", "ast", "stl", "blk", "fg3m", "to", "fg_pct", "ft_pct"}


def _app(client: TestClient) -> FastAPI:
    return cast("FastAPI", client.app)


def _seed_candidates(client: TestClient) -> DemoSeedResult:
    with _app(client).state.database.session() as session:
        return seed_demo(session)


def _seed_genuine_scoring_mismatch(client: TestClient) -> int:
    """Compose real writers around the standalone seed's broader first import."""

    with _app(client).state.database.session() as session:
        projections = seed_projections(session)
        auction_players = tuple(
            CanonicalDraftPlayer(player_id=player_id, player_label=player_label)
            for player_id, player_label in session.execute(
                select(Projection.player_id, Player.full_name)
                .join(Player, Player.id == Projection.player_id)
                .where(Projection.projection_import_id == projections.projection_import_id)
                .order_by(Projection.player_id)
            )
        )
        drafts = seed_drafts(session, auction_players=auction_players)
        recorded_scoring = seed_demo_module._recorded_auction_scoring(DEFAULT_FIXTURES_DIR)
        seed_demo_module._seed_auction_scoring_profile(
            session,
            auction_league_id=drafts.auction_league_id,
            recorded_scoring=recorded_scoring,
        )
        return drafts.auction_draft_id


def _get(client: TestClient, draft_id: int, *, source: str = SOURCE) -> Any:
    return client.get(
        f"/api/v1/drafts/{draft_id}/production-candidates",
        params={"source": source},
    )


def _all_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(value)
        for item in value.values():
            keys.update(_all_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_all_keys(item))
    return keys


def test_the_composed_fixture_reaches_the_full_producer_http_boundary(
    client: TestClient,
) -> None:
    before = datetime.now(UTC)
    seeded = _seed_candidates(client)
    response = _get(client, seeded.drafts.auction_draft_id)
    after = datetime.now(UTC)

    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["draft_id"] == seeded.drafts.auction_draft_id
    assert body["league_id"] == seeded.drafts.auction_league_id
    assert body["draft_last_sequence"] == seeded.drafts.auction_last_sequence
    assert body["source"] == SOURCE
    assert body["source_display_name"] == DEMO_DISPLAY_NAME
    assert body["source_original_filename"] == DEMO_FILENAME
    assert body["claim"] == "projection_relative_production_ranking"
    assert body["value_scope"] == "production_only"
    assert body["availability_included"] is False
    assert body["calibration_status"] == "not_established_for_current_selected_source"
    assert body["source_freshness"] == "not_established_beyond_current_import"
    generated_at = datetime.fromisoformat(body["generated_at"].replace("Z", "+00:00"))
    assert before <= generated_at <= after

    assert body["limitations"] == {
        "strategy_included": False,
        "punt_adjustment_included": False,
        "budget_or_affordability_included": False,
        "position_fit_included": False,
        "fantrax_roster_eligibility_included": False,
        "partial_browser_increment": True,
    }
    assert body["lineage"]["availability_model_version"] is None
    assert body["lineage"]["punt_config"] is None
    assert (
        body["lineage"]["projection_import"]["import_id"] == seeded.projections.projection_import_id
    )
    assert body["lineage"]["projection_import"]["projection_count"] == 60
    assert body["lineage"]["projection_import"]["source"] == SOURCE
    assert body["lineage"]["projection_import"]["assumed_scoring_type"] == ("h2h_each_category")
    assert body["lineage"]["blend"]["mode"] == "ephemeral_identity_single_source"
    assert body["lineage"]["blend"]["persisted"] is False
    assert body["lineage"]["blend"]["manual_override_count"] == 0
    assert body["lineage"]["blend"]["weight_basis"] == "user_configured"
    assert body["lineage"]["score"]["input_kind"] == "production_blend"
    assert body["lineage"]["score"]["output_layer"] == "terminal"
    assert "input_layer" not in body["lineage"]["score"]

    reference = body["reference"]
    assert reference["count"] == 60
    assert len(reference["player_ids"]) == 60
    assert len(set(reference["player_ids"])) == 60
    assert reference["scored_before_draft_exclusion"] is True
    assert reference["draft_exclusion_policy"] == (
        "exclude_resolved_holdings_after_full_reference_scoring"
    )
    assert len(reference["resolved_drafted_player_ids"]) == 7
    assert reference["excluded_drafted_player_ids"] == reference["resolved_drafted_player_ids"]
    assert reference["drafted_player_ids_outside_reference"] == []
    assert reference["candidate_count"] == 53

    replacement = body["replacement"]
    assert replacement == {
        "state": "unavailable_insufficient_projected_pool",
        "team_count": 12,
        "roster_size": 13,
        "structural_roster_count": 156,
        "replacement_ordinal": 157,
        "projected_count": 60,
        "structural_roster_covered": False,
        "structural_roster_shortfall": 96,
        "replacement_ordinal_shortfall": 97,
        "replacement_player_id": None,
        "replacement_total_z": None,
    }

    scale_order = [scale["category_key"] for scale in body["category_scales"]]
    weight_order = [
        category["category_key"] for category in body["lineage"]["blend"]["category_weights"]
    ]
    assert len(scale_order) == 9
    assert set(scale_order) == CATEGORY_KEYS
    assert weight_order == scale_order
    assert all(
        weight["source"] == SOURCE
        and weight["raw_weight"] == 1.0
        and weight["normalized_weight"] == 1.0
        for weight in body["lineage"]["blend"]["category_weights"]
    )

    health_context = body["health_context"]
    assert health_context["status"] == "available"
    assert health_context["reason"] is None
    assert health_context["season"] == seeded.reliability.season
    assert health_context["publication"]["artifact_key"] == RELIABILITY_SOURCE_KEY
    assert health_context["row_source_provenance"] == "not_recorded"
    assert health_context["counting_rule"] == (
        "player_game_log_rows_in_window_including_zero_seconds"
    )
    assert health_context["ranking_input"] is False
    assert len(health_context["observation_rows_sha256"]) == 64

    candidates = body["candidates"]
    assert len(candidates) == 53
    assert [candidate["ordinal"] for candidate in candidates] == sorted(
        candidate["ordinal"] for candidate in candidates
    )
    candidate_ids = {candidate["player_id"] for candidate in candidates}
    assert candidate_ids == set(reference["player_ids"]) - set(
        reference["excluded_drafted_player_ids"]
    )
    assert all(candidate["value_above_replacement"] is None for candidate in candidates)
    assert all(set(candidate["rates_per_game"]) == RATE_FIELDS for candidate in candidates)
    assert all(
        [component["category_key"] for component in candidate["components"]] == scale_order
        for candidate in candidates
    )
    health_states = Counter(candidate["health"]["status"] for candidate in candidates)
    assert health_states == {"observed": 5, "no_observations": 48}
    assert sorted(
        candidate["health"]["credited_appearances"]
        for candidate in candidates
        if candidate["health"]["status"] == "observed"
    ) == [2, 2, 2, 2, 2]

    forbidden = {
        "budget_context",
        "draft_name",
        "expected_games",
        "p_play",
        "price",
        "max_bid",
        "g_score",
        "confidence_probability",
        "best_pick",
        "recommendation",
        "primary_position",
    }
    assert forbidden.isdisjoint(_all_keys(body))
    with _app(client).state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(ProjectionImport)) == 1


def test_source_is_required_and_only_the_snapshot_conflict_is_retryable(
    client: TestClient,
) -> None:
    missing = client.get("/api/v1/drafts/1/production-candidates")
    assert missing.status_code == 422
    assert missing.json()["error"] == "validation_error"

    unsupported = _get(client, 1, source="nba")
    assert unsupported.status_code == 400
    assert unsupported.json()["error"] == "production_candidates_source_unsupported"

    absent = _get(client, 999)
    assert absent.status_code == 404
    assert absent.json()["error"] == "production_candidates_draft_not_found"


def test_supported_but_unimported_source_is_distinct_from_an_unsupported_one(
    client: TestClient,
) -> None:
    seeded = _seed_candidates(client)
    response = _get(client, seeded.drafts.auction_draft_id, source="fantasypros")
    assert response.status_code == 409
    assert response.json()["error"] == "production_candidates_source_not_imported"


def test_a_draft_without_an_active_scoring_profile_is_refused(
    client: TestClient,
) -> None:
    seeded = _seed_candidates(client)
    existing = client.get(f"/api/v1/drafts/{seeded.drafts.snake_draft_id}")
    assert existing.status_code == 200, existing.text
    state = existing.json()
    created = client.post(
        "/api/v1/drafts",
        json={
            "league_id": seeded.drafts.snake_league_id,
            "name": "[demo] Profile-free candidate draft",
            "is_mock": True,
            "tool_usage": "blind",
            "participants": [
                {
                    "team_slot": participant["team_slot"],
                    "source_seat": participant["source_seat"],
                    "display_name": participant["display_name"],
                    "is_owner": participant["is_owner"],
                    "fantasy_team_id": participant["fantasy_team_id"],
                }
                for participant in state["participants"]
            ],
        },
    )
    assert created.status_code == 201, created.text

    response = _get(client, created.json()["id"])
    assert response.status_code == 409
    assert response.json()["error"] == "production_candidates_scoring_profile_unavailable"


def test_a_genuine_incompatible_first_import_is_still_refused(
    client: TestClient,
) -> None:
    draft_id = _seed_genuine_scoring_mismatch(client)

    response = _get(client, draft_id)

    assert response.status_code == 409
    assert response.json()["error"] == "production_candidates_input_evidence_refused"
    assert "h2h_categories" in response.json()["detail"]
    assert "h2h_each_category" in response.json()["detail"]


def test_an_unresolved_nominee_is_allowed_but_an_unresolved_live_holding_refuses(
    client: TestClient,
) -> None:
    seeded = _seed_candidates(client)
    draft_id = seeded.drafts.auction_draft_id
    state = client.get(f"/api/v1/drafts/{draft_id}").json()
    participant_id = state["participants"][0]["id"]

    nomination = client.post(
        f"/api/v1/drafts/{draft_id}/events",
        json={
            "event_type": "nomination",
            "participant_id": participant_id,
            "player_label": "Unresolved Nominee",
            "amount": "1.00",
        },
    )
    assert nomination.status_code == 201, nomination.text
    assert _get(client, draft_id).status_code == 200

    sale = client.post(
        f"/api/v1/drafts/{draft_id}/events",
        json={
            "event_type": "sale",
            "participant_id": participant_id,
            "amount": "2.00",
        },
    )
    assert sale.status_code == 201, sale.text
    refused = _get(client, draft_id)
    assert refused.status_code == 409
    assert refused.json()["error"] == "production_candidates_draft_identity_incomplete"


def test_complete_production_is_all_or_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = _seed_candidates(client)

    def refuse_incomplete(_session: Session, _profile: BlendProfile) -> NoReturn:
        raise MissingProjectionDataError(
            "basketball_monster import lacks ['steals_per_game'] for player 1 category 'stl'; "
            "weights are never silently renormalized"
        )

    monkeypatch.setattr(production_candidates, "blend_projections", refuse_incomplete)
    response = _get(client, seeded.drafts.auction_draft_id)
    assert response.status_code == 409
    assert response.json()["error"] == "production_candidates_incomplete_production"


def test_a_moved_canonical_release_is_the_one_retryable_refusal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = _seed_candidates(client)
    real_release = canonical_release_projection_import
    calls = 0

    def move_on_second_release(
        session: Session,
        *,
        import_id: int,
        source: ExternalSource,
    ) -> ReleasedProjectionImport:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise StaleProjectionInputError("newer projection import became current")
        return real_release(session, import_id=import_id, source=source)

    monkeypatch.setattr(
        production_candidates,
        "release_projection_import",
        move_on_second_release,
    )
    response = _get(client, seeded.drafts.auction_draft_id)
    assert calls == 2
    assert response.status_code == 409
    assert response.json()["error"] == "production_candidates_inconsistent_snapshot"


def test_moved_source_display_provenance_is_a_snapshot_conflict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = _seed_candidates(client)
    real_metadata = production_candidates._projection_display_metadata
    calls = 0

    def move_on_second_read(
        session: Session,
        *,
        release: ReleasedProjectionImport,
    ) -> production_candidates._ProjectionDisplayMetadata:
        nonlocal calls
        calls += 1
        metadata = real_metadata(session, release=release)
        if calls == 2:
            return replace(metadata, display_name=f"{metadata.display_name} moved")
        return metadata

    monkeypatch.setattr(
        production_candidates,
        "_projection_display_metadata",
        move_on_second_read,
    )
    response = _get(client, seeded.drafts.auction_draft_id)

    assert calls == 2
    assert response.status_code == 409
    assert response.json()["error"] == "production_candidates_inconsistent_snapshot"


def test_no_publication_produces_the_explicit_unavailable_health_shape(
    session: Session,
) -> None:
    snapshot = production_candidates._read_health_snapshot(
        session,
        candidate_player_ids=(11, 12),
    )
    context = production_candidates._health_context_out(snapshot)
    assert context.model_dump(mode="json") == {
        "status": "unavailable",
        "reason": "no_attributable_publication",
        "season": None,
        "season_type": None,
        "window_start": None,
        "as_of_date": None,
        "publication": None,
        "row_source_provenance": "not_recorded",
        "counting_rule": "player_game_log_rows_in_window_including_zero_seconds",
        "observation_rows_sha256": None,
        "ranking_input": False,
    }
    assert dict(snapshot.appearances) == {11: None, 12: None}


def test_corrupt_published_window_is_a_typed_refusal_not_unknown_success(
    client: TestClient,
) -> None:
    seeded = _seed_candidates(client)
    with _app(client).state.database.session() as session:
        run = current_refresh(
            session,
            RefreshArtifactType.SOURCE,
            artifact_key=RELIABILITY_SOURCE_KEY,
            season=seeded.reliability.season,
        )
        assert run is not None
        summary = dict(run.summary)
        summary["window_start"] = "not-a-date"
        record_refresh(
            session,
            artifact_type=run.artifact_type,
            artifact_key=run.artifact_key,
            version=run.version,
            source=run.source,
            season=run.season,
            summary=summary,
            refreshed_at=run.refreshed_at,
        )

    response = _get(client, seeded.drafts.auction_draft_id)
    assert response.status_code == 409
    assert response.json()["error"] == "production_candidates_input_evidence_refused"


def test_available_publication_preserves_absent_source_metadata_as_null(
    client: TestClient,
) -> None:
    seeded = _seed_candidates(client)
    with _app(client).state.database.session() as session:
        run = current_refresh(
            session,
            RefreshArtifactType.SOURCE,
            artifact_key=RELIABILITY_SOURCE_KEY,
            season=seeded.reliability.season,
        )
        assert run is not None
        record_refresh(
            session,
            artifact_type=run.artifact_type,
            artifact_key=run.artifact_key,
            version="",
            source="",
            season=run.season,
            summary=run.summary,
            refreshed_at=run.refreshed_at + timedelta(seconds=1),
        )

    response = _get(client, seeded.drafts.auction_draft_id)
    assert response.status_code == 200, response.text
    publication = response.json()["health_context"]["publication"]
    assert publication["source"] is None
    assert publication["source_version"] is None


def test_a_zero_second_game_log_remains_a_credited_appearance(
    client: TestClient,
) -> None:
    seeded = _seed_candidates(client)
    with _app(client).state.database.session() as session:
        row = session.execute(
            select(
                PlayerExternalId.external_id,
                NbaGame.nba_game_id,
                NbaTeam.nba_team_id,
                Player.full_name,
            )
            .join(
                PlayerGameLog,
                PlayerGameLog.player_id == PlayerExternalId.player_id,
            )
            .join(NbaGame, NbaGame.id == PlayerGameLog.game_id)
            .join(NbaTeam, NbaTeam.id == PlayerGameLog.team_id)
            .join(Player, Player.id == PlayerGameLog.player_id)
            .where(
                PlayerExternalId.source == ExternalSource.NBA,
                PlayerExternalId.current_for_source.is_not(None),
            )
            .order_by(PlayerGameLog.id)
            .limit(1)
        ).one()
        import_box_scores(
            session,
            [
                PlayerBoxScoreRecord(
                    nba_player_id=int(row.external_id),
                    nba_game_id=row.nba_game_id,
                    nba_team_id=row.nba_team_id,
                    player_name=row.full_name,
                    seconds_played=0,
                )
            ],
        )
        refresh = current_refresh(
            session,
            RefreshArtifactType.SOURCE,
            artifact_key=RELIABILITY_SOURCE_KEY,
            season=seeded.reliability.season,
        )
        assert refresh is not None
        summary = refresh.summary
        as_of_date = datetime.fromisoformat(cast("str", summary["as_of_date"])).date()
        publish_reliability_cohorts(
            session,
            season=seeded.reliability.season,
            as_of_date=as_of_date,
            refreshed_at=refresh.refreshed_at + timedelta(seconds=1),
        )

    response = _get(client, seeded.drafts.auction_draft_id)
    assert response.status_code == 200, response.text
    observed = [
        candidate
        for candidate in response.json()["candidates"]
        if candidate["health"]["status"] == "observed"
    ]
    assert len(observed) == 5
    assert sorted(candidate["health"]["credited_appearances"] for candidate in observed) == [
        2,
        2,
        2,
        2,
        2,
    ]


def test_openapi_publishes_the_closed_source_and_score_contract(client: TestClient) -> None:
    document = _app(client).openapi()
    operation = document["paths"]["/api/v1/drafts/{draft_id}/production-candidates"]["get"]
    source_parameter = next(
        parameter for parameter in operation["parameters"] if parameter["name"] == "source"
    )
    assert source_parameter["required"] is True
    assert source_parameter["schema"]["enum"] == [
        "basketball_monster",
        "fantasypros",
        "hashtag",
        "darko",
        "manual",
    ]

    schemas = document["components"]["schemas"]
    score_schema = schemas["ScoreLineageOut"]
    assert "input_layer" not in score_schema["properties"]
    assert score_schema["properties"]["input_kind"]["const"] == "production_blend"
    assert score_schema["properties"]["output_layer"]["const"] == "terminal"
    response_schema = schemas["ProductionCandidatesResponse"]
    assert response_schema["properties"]["source_display_name"]["type"] == "string"
    assert response_schema["properties"]["source_original_filename"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert response_schema["additionalProperties"] is False
