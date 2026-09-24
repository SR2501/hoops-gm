"""Projection blending: immutable lineage, layer purity, and per-game math."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import (
    CategoryKind,
    ExternalSource,
    FieldEvidence,
    MatchMethod,
    ScoringType,
)
from hoops_gm.db.models.identity import Player, PlayerExternalId
from hoops_gm.db.models.league import (
    League,
    LeagueScoringCategory,
    LeagueScoringProfile,
)
from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot
from hoops_gm.db.models.projections import (
    Projection,
    ProjectionImport,
    ProjectionProfileVersion,
    ProjectionSource,
    SourceGamesPlayedAssumption,
)
from hoops_gm.db.projection_series import current_projection_import_id
from hoops_gm.dev.seed_projections import PLAYERS_FIXTURE
from hoops_gm.dev.seed_schedule_grid import DEFAULT_FIXTURES_DIR, load_fixture
from hoops_gm.ingest.importers import import_nba_players
from hoops_gm.ingest.nba.parsers import parse_common_all_players
from hoops_gm.ingest.projections import get_or_create_projection_source, import_projection_csv
from hoops_gm.projections import blending
from hoops_gm.projections.blending import (
    PROJECTION_RELEASE_SCHEMA_VERSION,
    BlendCatalog,
    BlendedCategoryValue,
    BlendInputLayer,
    BlendProfile,
    InvalidBlendProfileError,
    LayerPurityError,
    ManualProjectionOverride,
    MissingProjectionDataError,
    ReleasedProjectionImport,
    StaleProjectionInputError,
    UnknownProjectionInputError,
    WeightBasis,
    activate_blend_profile,
    blend_active_projections,
    blend_profile_content_sha256,
    blend_projections,
    current_blend_profile,
    define_blend_profile,
    release_projection_import,
    validate_blend_profile_integrity,
)
from hoops_gm.scoring.profiles import NINE_CATEGORY_DEFINITIONS
from hoops_gm.valuation.zscore import score_production_zscores

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
SEASON = "2026-27"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _scoring_profile(
    session: Session,
    *,
    season: str = SEASON,
    name: str = "League",
) -> tuple[League, LeagueScoringProfile]:
    league = League(
        name=name,
        season=season,
        scoring_type=ScoringType.H2H_EACH_CATEGORY,
    )
    session.add(league)
    session.flush()
    snapshot = LeagueSettingsSnapshot(
        league_id=league.id,
        version=1,
        schema_version="test-v1",
        settings={},
        source_summary={},
        source_payload_sha256=_sha(f"{name}-settings"),
        observed_at=NOW,
    )
    session.add(snapshot)
    session.flush()
    profile = LeagueScoringProfile(
        league_id=league.id,
        name="default",
        version=1,
        scoring_type=ScoringType.H2H_EACH_CATEGORY,
        settings_snapshot_id=snapshot.id,
        active_league_id=league.id,
    )
    session.add(profile)
    session.flush()
    session.add_all(
        (
            LeagueScoringCategory(
                profile_id=profile.id,
                key="pts",
                label="PTS",
                kind=CategoryKind.COUNTING,
                direction=1,
                display_order=1,
            ),
            LeagueScoringCategory(
                profile_id=profile.id,
                key="fg_pct",
                label="FG%",
                kind=CategoryKind.RATIO,
                direction=1,
                display_order=2,
                numerator_stat="field_goals_made",
                denominator_stat="field_goals_attempted",
            ),
            LeagueScoringCategory(
                profile_id=profile.id,
                key="ft_pct",
                label="FT%",
                kind=CategoryKind.RATIO,
                direction=1,
                display_order=3,
                numerator_stat="free_throws_made",
                denominator_stat="free_throws_attempted",
            ),
        )
    )
    session.flush()
    return league, profile


def _player(session: Session, name: str = "Blend Player") -> Player:
    player = Player(full_name=name, normalized_name=name.lower().replace(" ", ""))
    session.add(player)
    session.flush()
    return player


def _projection_import(
    session: Session,
    *,
    source: ExternalSource,
    players: dict[int, dict[str, float | None]],
    season: str = SEASON,
    imported_at: datetime = NOW,
    scoring_type: ScoringType | None = ScoringType.H2H_EACH_CATEGORY,
    suffix: str = "a",
    assumed_games: float | None = None,
    series_key: str = "legacy",
    series_display_name: str | None = None,
) -> ProjectionImport:
    source_row = session.scalar(select(ProjectionSource).where(ProjectionSource.source == source))
    if source_row is None:
        source_row = ProjectionSource(
            source=source,
            display_name=source.value,
            assumed_scoring_type=scoring_type,
        )
        session.add(source_row)
        session.flush()
    profile_id = f"{source.value}-verified"
    profile = session.scalar(
        select(ProjectionProfileVersion).where(
            ProjectionProfileVersion.source_id == source_row.id,
            ProjectionProfileVersion.profile_id == profile_id,
            ProjectionProfileVersion.profile_version == "1",
        )
    )
    if profile is None:
        profile = ProjectionProfileVersion(
            source_id=source_row.id,
            profile_id=profile_id,
            profile_version="1",
            verified=True,
            verified_seasons=[season],
            verification_evidence="test fixture",
            definition_sha256=_sha(f"{source.value}-definition"),
            definition={},
        )
        session.add(profile)
        session.flush()
    projection_import = ProjectionImport(
        source_id=source_row.id,
        series_key=series_key,
        series_display_name=(
            series_display_name or (None if series_key == "legacy" else series_key)
        ),
        profile_version_id=profile.id,
        season=season,
        imported_at=imported_at,
        content_sha256=_sha(f"{source.value}-{season}-{suffix}"),
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        profile_verified=True,
        profile_definition_sha256=profile.definition_sha256,
        profile_lineage={},
        row_count=len(players),
        matched_count=len(players),
        needs_review_count=0,
        unmatched_count=0,
        rejected_count=0,
        assumed_scoring_type=scoring_type,
    )
    session.add(projection_import)
    session.flush()
    for player_id, values in players.items():
        projection = Projection(
            projection_import_id=projection_import.id,
            player_id=player_id,
            season=season,
            **values,
        )
        session.add(projection)
        session.flush()
        if assumed_games is not None:
            session.add(
                SourceGamesPlayedAssumption(
                    projection_id=projection.id,
                    assumed_games_played=assumed_games,
                    assumed_games_played_raw=str(assumed_games),
                )
            )
    session.flush()
    return projection_import


def _source_values(
    *,
    points: float = 10,
    fgm: float = 1,
    fga: float = 2,
    ftm: float = 9,
    fta: float = 10,
) -> dict[str, float | None]:
    return {
        "points_per_game": points,
        "field_goals_made_per_game": fgm,
        "field_goals_attempted_per_game": fga,
        "free_throws_made_per_game": ftm,
        "free_throws_attempted_per_game": fta,
    }


def _nine_category_scoring_profile(
    session: Session,
) -> tuple[League, LeagueScoringProfile]:
    league = League(
        name="Nine Category League",
        season=SEASON,
        scoring_type=ScoringType.H2H_EACH_CATEGORY,
        team_count=1,
        roster_size=1,
    )
    session.add(league)
    session.flush()
    snapshot = LeagueSettingsSnapshot(
        league_id=league.id,
        version=1,
        schema_version="test-v1",
        settings={},
        source_summary={},
        source_payload_sha256=_sha("nine-category-settings"),
        observed_at=NOW,
    )
    session.add(snapshot)
    session.flush()
    profile = LeagueScoringProfile(
        league_id=league.id,
        name="default",
        version=1,
        scoring_type=ScoringType.H2H_EACH_CATEGORY,
        settings_snapshot_id=snapshot.id,
        active_league_id=league.id,
    )
    session.add(profile)
    session.flush()
    session.add_all(
        LeagueScoringCategory(
            profile_id=profile.id,
            key=definition.key,
            label=definition.label,
            kind=definition.kind,
            direction=definition.direction,
            display_order=display_order,
            numerator_stat=definition.numerator_stat,
            denominator_stat=definition.denominator_stat,
        )
        for display_order, definition in enumerate(
            NINE_CATEGORY_DEFINITIONS.values(),
            start=1,
        )
    )
    session.flush()
    return league, profile


def _nine_category_values(
    *,
    points: float,
    fgm: float,
    fga: float,
    ftm: float,
    fta: float,
) -> dict[str, float | None]:
    return {
        "points_per_game": points,
        "rebounds_per_game": 5,
        "assists_per_game": 4,
        "steals_per_game": 1,
        "blocks_per_game": 1,
        "three_pointers_made_per_game": 2,
        "three_pointers_attempted_per_game": 3,
        "turnovers_per_game": 2,
        "field_goals_made_per_game": fgm,
        "field_goals_attempted_per_game": fga,
        "free_throws_made_per_game": ftm,
        "free_throws_attempted_per_game": fta,
    }


def _weights(
    first: ExternalSource = ExternalSource.MANUAL,
    second: ExternalSource = ExternalSource.BASKETBALL_MONSTER,
) -> dict[str, dict[ExternalSource, int]]:
    return {
        "pts": {first: 1, second: 1},
        "fg_pct": {first: 1, second: 3},
        "ft_pct": {first: 3, second: 1},
    }


def _setup(
    session: Session,
) -> tuple[League, LeagueScoringProfile, Player, ProjectionImport, ProjectionImport]:
    league, scoring = _scoring_profile(session)
    player = _player(session)
    manual = _projection_import(
        session,
        source=ExternalSource.MANUAL,
        players={player.id: _source_values()},
        assumed_games=1,
    )
    monster = _projection_import(
        session,
        source=ExternalSource.BASKETBALL_MONSTER,
        players={player.id: _source_values(points=20, fgm=9, fga=10, ftm=1, fta=2)},
        assumed_games=82,
    )
    return league, scoring, player, manual, monster


def _category(result_category: BlendedCategoryValue, field: str) -> Fraction:
    return dict(result_category.values)[field]


def test_blend_is_order_invariant_and_normalizes_exactly(session: Session) -> None:
    league, scoring, _player_row, manual, monster = _setup(session)
    manual_release = release_projection_import(
        session, import_id=manual.id, source=ExternalSource.MANUAL
    )
    monster_release = release_projection_import(
        session,
        import_id=monster.id,
        source=ExternalSource.BASKETBALL_MONSTER,
    )
    catalog, first = define_blend_profile(
        session,
        BlendCatalog(),
        league_id=league.id,
        name="default",
        scoring_profile_id=scoring.id,
        sources=(manual_release, monster_release),
        category_weights=_weights(),
    )
    reversed_weights = {
        category: dict(reversed(tuple(weights.items())))
        for category, weights in reversed(tuple(_weights().items()))
    }
    same_catalog, second = define_blend_profile(
        session,
        catalog,
        league_id=league.id,
        name="default",
        scoring_profile_id=scoring.id,
        sources=(monster_release, manual_release),
        category_weights=reversed_weights,
    )

    assert same_catalog is catalog
    assert second is first
    fg_weights = next(item for item in first.category_weights if item.category_key == "fg_pct")
    assert [item.normalized_weight for item in fg_weights.weights] == [
        Fraction(3, 4),
        Fraction(1, 4),
    ]
    assert (
        blend_projections(session, first).content_sha256
        == blend_projections(session, second).content_sha256
    )


def test_ratio_categories_blend_made_and_attempt_volume_not_raw_percentages(
    session: Session,
) -> None:
    league, scoring, _player_row, manual, monster = _setup(session)
    releases = (
        release_projection_import(session, import_id=manual.id, source=ExternalSource.MANUAL),
        release_projection_import(
            session,
            import_id=monster.id,
            source=ExternalSource.BASKETBALL_MONSTER,
        ),
    )
    _catalog, profile = define_blend_profile(
        session,
        BlendCatalog(),
        league_id=league.id,
        name="default",
        scoring_profile_id=scoring.id,
        sources=releases,
        category_weights=_weights(),
    )

    row = blend_projections(session, profile).projections[0]
    by_category = {category.category_key: category for category in row.categories}
    assert _category(by_category["pts"], "points_per_game") == 15
    assert _category(by_category["fg_pct"], "field_goals_made_per_game") == 7
    assert _category(by_category["fg_pct"], "field_goals_attempted_per_game") == 8
    assert _category(by_category["ft_pct"], "free_throws_made_per_game") == 7
    assert _category(by_category["ft_pct"], "free_throws_attempted_per_game") == 8
    assert "field_goal_percentage" not in dict(by_category["fg_pct"].values)


def test_games_played_assumptions_are_not_inputs_or_outputs(session: Session) -> None:
    league, scoring, _player_row, manual, monster = _setup(session)
    releases = (
        release_projection_import(session, import_id=manual.id, source=ExternalSource.MANUAL),
        release_projection_import(
            session,
            import_id=monster.id,
            source=ExternalSource.BASKETBALL_MONSTER,
        ),
    )
    _catalog, profile = define_blend_profile(
        session,
        BlendCatalog(),
        league_id=league.id,
        name="default",
        scoring_profile_id=scoring.id,
        sources=releases,
        category_weights=_weights(),
    )
    before = blend_projections(session, profile)
    assumptions = session.scalars(select(SourceGamesPlayedAssumption)).all()
    assumptions[0].assumed_games_played = 82
    assumptions[1].assumed_games_played = 1
    session.flush()
    after = blend_projections(session, profile)

    assert after == before
    assert all(
        "games" not in field
        for row in after.projections
        for category in row.categories
        for field, _value in category.values
    )


@pytest.mark.parametrize(
    "layer",
    [
        BlendInputLayer.RANKING,
        BlendInputLayer.MARKET,
        BlendInputLayer.VALUATION,
        BlendInputLayer.RECOMMENDATION,
        BlendInputLayer.MOCK_OUTCOME,
        BlendInputLayer.AVAILABILITY,
        BlendInputLayer.EXPECTED_GAMES,
    ],
)
def test_non_projection_layers_are_rejected(session: Session, layer: BlendInputLayer) -> None:
    league, scoring, _player_row, manual, monster = _setup(session)
    manual_release = release_projection_import(
        session, import_id=manual.id, source=ExternalSource.MANUAL
    )
    monster_release = release_projection_import(
        session,
        import_id=monster.id,
        source=ExternalSource.BASKETBALL_MONSTER,
    )

    with pytest.raises(LayerPurityError):
        define_blend_profile(
            session,
            BlendCatalog(),
            league_id=league.id,
            name="default",
            scoring_profile_id=scoring.id,
            sources=(replace(manual_release, input_layer=layer), monster_release),
            category_weights=_weights(),
        )


@pytest.mark.parametrize(
    "basis",
    [
        WeightBasis.LEARNED_ACCURACY,
        WeightBasis.MARKET_CALIBRATED,
        WeightBasis.MOCK_CALIBRATED,
    ],
)
def test_unregistered_learned_weight_paths_are_rejected(
    session: Session, basis: WeightBasis
) -> None:
    league, scoring, _player_row, manual, monster = _setup(session)
    releases = (
        release_projection_import(session, import_id=manual.id, source=ExternalSource.MANUAL),
        release_projection_import(
            session,
            import_id=monster.id,
            source=ExternalSource.BASKETBALL_MONSTER,
        ),
    )

    with pytest.raises(LayerPurityError, match="user configuration"):
        define_blend_profile(
            session,
            BlendCatalog(),
            league_id=league.id,
            name="default",
            scoring_profile_id=scoring.id,
            sources=releases,
            category_weights=_weights(),
            weight_basis=basis,
        )


def test_manual_override_is_separate_auditable_lineage(session: Session) -> None:
    league, scoring, player, manual, monster = _setup(session)
    override = ManualProjectionOverride(
        override_id="owner-pts-001",
        league_id=league.id,
        season=SEASON,
        player_id=player.id,
        category_key="pts",
        values=(("points_per_game", "25.5"),),
        actor="owner",
        reason="minutes role changed after source cutoff",
        created_at=NOW + timedelta(hours=1),
    )
    releases = (
        release_projection_import(session, import_id=manual.id, source=ExternalSource.MANUAL),
        release_projection_import(
            session,
            import_id=monster.id,
            source=ExternalSource.BASKETBALL_MONSTER,
        ),
    )
    _catalog, profile = define_blend_profile(
        session,
        BlendCatalog(),
        league_id=league.id,
        name="default",
        scoring_profile_id=scoring.id,
        sources=releases,
        category_weights=_weights(),
        manual_overrides=(override,),
    )

    row = blend_projections(session, profile).projections[0]
    by_category = {category.category_key: category for category in row.categories}
    assert _category(by_category["pts"], "points_per_game") == Fraction(51, 2)
    assert by_category["pts"].manual_override_id == "owner-pts-001"
    assert by_category["fg_pct"].manual_override_id is None
    assert profile.manual_overrides == (override,)


def test_invalid_weights_and_missing_categories_fail_before_registration(
    session: Session,
) -> None:
    league, scoring, player, manual, _monster = _setup(session)
    incomplete = _projection_import(
        session,
        source=ExternalSource.DARKO,
        players={player.id: {"points_per_game": 15}},
    )
    releases = (
        release_projection_import(session, import_id=manual.id, source=ExternalSource.MANUAL),
        release_projection_import(session, import_id=incomplete.id, source=ExternalSource.DARKO),
    )
    catalog = BlendCatalog()
    weights = _weights(ExternalSource.MANUAL, ExternalSource.DARKO)

    with pytest.raises(MissingProjectionDataError, match="never silently renormalized"):
        define_blend_profile(
            session,
            catalog,
            league_id=league.id,
            name="default",
            scoring_profile_id=scoring.id,
            sources=releases,
            category_weights=weights,
        )
    assert catalog.profiles == ()

    invalid_weights = dict(weights)
    invalid_weights["pts"] = {
        ExternalSource.MANUAL: -1,
        ExternalSource.DARKO: 2,
    }
    with pytest.raises(InvalidBlendProfileError, match="non-negative"):
        define_blend_profile(
            session,
            catalog,
            league_id=league.id,
            name="default",
            scoring_profile_id=scoring.id,
            sources=releases,
            category_weights=invalid_weights,
        )
    assert catalog.profiles == ()


def test_duplicate_unknown_mixed_and_incompatible_inputs_fail_closed(
    session: Session,
) -> None:
    league, scoring, player, manual, monster = _setup(session)
    manual_release = release_projection_import(
        session, import_id=manual.id, source=ExternalSource.MANUAL
    )
    monster_release = release_projection_import(
        session,
        import_id=monster.id,
        source=ExternalSource.BASKETBALL_MONSTER,
    )
    with pytest.raises(InvalidBlendProfileError, match="same import"):
        define_blend_profile(
            session,
            BlendCatalog(),
            league_id=league.id,
            name="default",
            scoring_profile_id=scoring.id,
            sources=(manual_release, manual_release),
            category_weights={
                category: {ExternalSource.MANUAL: 1} for category in ("pts", "fg_pct", "ft_pct")
            },
        )
    with pytest.raises(UnknownProjectionInputError, match="not explicitly selected"):
        release_projection_import(
            session,
            import_id=manual.id,
            source=ExternalSource.BASKETBALL_MONSTER,
        )

    old_season = _projection_import(
        session,
        source=ExternalSource.DARKO,
        season="2025-26",
        players={player.id: _source_values()},
        scoring_type=ScoringType.H2H_EACH_CATEGORY,
    )
    old_release = release_projection_import(
        session, import_id=old_season.id, source=ExternalSource.DARKO
    )
    with pytest.raises(InvalidBlendProfileError, match="does not match league season"):
        define_blend_profile(
            session,
            BlendCatalog(),
            league_id=league.id,
            name="default",
            scoring_profile_id=scoring.id,
            sources=(manual_release, old_release),
            category_weights=_weights(ExternalSource.MANUAL, ExternalSource.DARKO),
        )

    points_source = _projection_import(
        session,
        source=ExternalSource.HASHTAG,
        players={player.id: _source_values()},
        scoring_type=ScoringType.POINTS,
    )
    points_release = release_projection_import(
        session, import_id=points_source.id, source=ExternalSource.HASHTAG
    )
    with pytest.raises(InvalidBlendProfileError, match="not target"):
        define_blend_profile(
            session,
            BlendCatalog(),
            league_id=league.id,
            name="default",
            scoring_profile_id=scoring.id,
            sources=(monster_release, points_release),
            category_weights=_weights(ExternalSource.BASKETBALL_MONSTER, ExternalSource.HASHTAG),
        )


def test_released_value_digest_detects_in_place_projection_change(session: Session) -> None:
    league, scoring, _player_row, manual, monster = _setup(session)
    manual_release = release_projection_import(
        session, import_id=manual.id, source=ExternalSource.MANUAL
    )
    monster_release = release_projection_import(
        session,
        import_id=monster.id,
        source=ExternalSource.BASKETBALL_MONSTER,
    )
    projection = session.scalar(
        select(Projection).where(Projection.projection_import_id == manual.id)
    )
    assert projection is not None
    projection.points_per_game = 99
    session.flush()

    with pytest.raises(StaleProjectionInputError, match="values changed"):
        define_blend_profile(
            session,
            BlendCatalog(),
            league_id=league.id,
            name="default",
            scoring_profile_id=scoring.id,
            sources=(manual_release, monster_release),
            category_weights=_weights(),
        )


def test_activation_supports_a_b_a_and_failed_activation_keeps_current(
    session: Session,
) -> None:
    league, scoring, player, manual, monster = _setup(session)
    releases = (
        release_projection_import(session, import_id=manual.id, source=ExternalSource.MANUAL),
        release_projection_import(
            session,
            import_id=monster.id,
            source=ExternalSource.BASKETBALL_MONSTER,
        ),
    )
    catalog, profile_a = define_blend_profile(
        session,
        BlendCatalog(),
        league_id=league.id,
        name="default",
        scoring_profile_id=scoring.id,
        sources=releases,
        category_weights=_weights(),
    )
    weights_b = _weights()
    weights_b["pts"] = {
        ExternalSource.MANUAL: 3,
        ExternalSource.BASKETBALL_MONSTER: 1,
    }
    catalog, profile_b = define_blend_profile(
        session,
        catalog,
        league_id=league.id,
        name="default",
        scoring_profile_id=scoring.id,
        sources=tuple(reversed(releases)),
        category_weights=weights_b,
    )
    catalog = activate_blend_profile(session, catalog, profile_a)
    assert current_blend_profile(catalog, league_id=league.id) == profile_a
    catalog = activate_blend_profile(session, catalog, profile_b)
    assert current_blend_profile(catalog, league_id=league.id) == profile_b
    catalog = activate_blend_profile(session, catalog, profile_a)
    assert current_blend_profile(catalog, league_id=league.id) == profile_a
    assert (
        blend_active_projections(session, catalog, league_id=league.id).profile_id
        == profile_a.profile_id
    )

    _projection_import(
        session,
        source=ExternalSource.MANUAL,
        players={player.id: _source_values(points=11)},
        imported_at=NOW + timedelta(days=1),
        suffix="new",
    )
    before_failed_activation = catalog
    with pytest.raises(StaleProjectionInputError, match="stale"):
        activate_blend_profile(session, catalog, profile_b)
    assert catalog is before_failed_activation
    assert current_blend_profile(catalog, league_id=league.id) == profile_a


def test_scoring_profile_change_makes_existing_blend_stale(session: Session) -> None:
    league, scoring, _player_row, manual, monster = _setup(session)
    releases = (
        release_projection_import(session, import_id=manual.id, source=ExternalSource.MANUAL),
        release_projection_import(
            session,
            import_id=monster.id,
            source=ExternalSource.BASKETBALL_MONSTER,
        ),
    )
    catalog, profile = define_blend_profile(
        session,
        BlendCatalog(),
        league_id=league.id,
        name="default",
        scoring_profile_id=scoring.id,
        sources=releases,
        category_weights=_weights(),
    )
    scoring.active_league_id = None
    session.flush()

    with pytest.raises(StaleProjectionInputError, match="not active"):
        activate_blend_profile(session, catalog, profile)


def test_real_producer_output_crosses_the_zscore_integrity_boundary(
    session: Session,
) -> None:
    league, scoring = _nine_category_scoring_profile(session)
    first = _player(session, "First Nine Cat Player")
    second = _player(session, "Second Nine Cat Player")
    projection_import = _projection_import(
        session,
        source=ExternalSource.MANUAL,
        players={
            first.id: _nine_category_values(
                points=10,
                fgm=0,
                fga=0,
                ftm=0,
                fta=0,
            ),
            second.id: _nine_category_values(
                points=20,
                fgm=5,
                fga=5,
                ftm=4,
                fta=4,
            ),
        },
    )
    release = release_projection_import(
        session,
        import_id=projection_import.id,
        source=ExternalSource.MANUAL,
    )
    weights = {key: {ExternalSource.MANUAL: 1} for key in NINE_CATEGORY_DEFINITIONS}
    _catalog, profile = define_blend_profile(
        session,
        BlendCatalog(),
        league_id=league.id,
        name="default",
        scoring_profile_id=scoring.id,
        sources=(release,),
        category_weights=weights,
    )
    blended = blend_projections(session, profile)

    result = score_production_zscores(
        league=league,
        blend_profile=profile,
        blend_result=blended,
    )

    assert result.input_kind == "production_blend"
    assert result.blend_profile_content_sha256 == profile.content_sha256
    assert result.blend_result_content_sha256 == blended.content_sha256
    assert result.reference_count == 2


@pytest.mark.parametrize(
    ("made_field", "attempted_field"),
    [
        ("field_goals_made_per_game", "field_goals_attempted_per_game"),
        ("free_throws_made_per_game", "free_throws_attempted_per_game"),
    ],
)
def test_projection_release_refuses_values_below_the_old_tolerance_edge(
    session: Session,
    made_field: str,
    attempted_field: str,
) -> None:
    _league, _scoring = _nine_category_scoring_profile(session)
    player = _player(session, f"Invalid {made_field}")
    values = _nine_category_values(points=10, fgm=1, fga=1, ftm=1, fta=1)
    values[made_field] = 1.0005
    values[attempted_field] = 1
    projection_import = _projection_import(
        session,
        source=ExternalSource.MANUAL,
        players={player.id: values},
    )

    with pytest.raises(InvalidBlendProfileError, match="makes greater than attempts"):
        release_projection_import(
            session,
            import_id=projection_import.id,
            source=ExternalSource.MANUAL,
        )


@pytest.mark.parametrize(
    ("category_key", "made_field", "attempted_field"),
    [
        (
            "fg_pct",
            "field_goals_made_per_game",
            "field_goals_attempted_per_game",
        ),
        (
            "ft_pct",
            "free_throws_made_per_game",
            "free_throws_attempted_per_game",
        ),
    ],
)
def test_manual_override_refuses_values_below_the_old_tolerance_edge(
    session: Session,
    category_key: str,
    made_field: str,
    attempted_field: str,
) -> None:
    league, scoring, player, manual, monster = _setup(session)
    releases = (
        release_projection_import(
            session,
            import_id=manual.id,
            source=ExternalSource.MANUAL,
        ),
        release_projection_import(
            session,
            import_id=monster.id,
            source=ExternalSource.BASKETBALL_MONSTER,
        ),
    )
    override = ManualProjectionOverride(
        override_id=f"invalid-{category_key}",
        league_id=league.id,
        season=SEASON,
        player_id=player.id,
        category_key=category_key,
        values=tuple(
            sorted(
                (
                    (made_field, Fraction(2001, 2000)),
                    (attempted_field, Fraction(1)),
                )
            )
        ),
        actor="owner",
        reason="physical-boundary regression",
        created_at=NOW,
    )

    with pytest.raises(InvalidBlendProfileError, match="makes greater than attempts"):
        define_blend_profile(
            session,
            BlendCatalog(),
            league_id=league.id,
            name="default",
            scoring_profile_id=scoring.id,
            sources=releases,
            category_weights=_weights(),
            manual_overrides=(override,),
        )


def _single_series_profile(
    session: Session, *, series_key: str = "josh"
) -> tuple[ProjectionImport, ReleasedProjectionImport, BlendProfile]:
    league, scoring = _scoring_profile(session)
    player = _player(session, "Series Plumbing Player")
    stored = _projection_import(
        session,
        source=ExternalSource.BASKETBALL_MONSTER,
        players={player.id: _source_values()},
        series_key=series_key,
    )
    release = release_projection_import(
        session, import_id=stored.id, source=ExternalSource.BASKETBALL_MONSTER
    )
    _catalog, profile = define_blend_profile(
        session,
        BlendCatalog(),
        league_id=league.id,
        name="series-contract",
        scoring_profile_id=scoring.id,
        sources=(release,),
        category_weights={
            key: {ExternalSource.BASKETBALL_MONSTER: 1} for key in ("pts", "fg_pct", "ft_pct")
        },
    )
    return stored, release, profile


@pytest.mark.parametrize("tie", [False, True])
def test_currentness_is_within_series_with_existing_time_then_id_order(
    session: Session, tie: bool
) -> None:
    source = ExternalSource.BASKETBALL_MONSTER
    player = _player(session)
    values = {player.id: _source_values()}
    josh = _projection_import(session, source=source, players=values, series_key="josh")
    first = release_projection_import(session, import_id=josh.id, source=source)
    bonus = _projection_import(
        session,
        source=source,
        players=values,
        series_key="bonus",
        imported_at=NOW + timedelta(days=1),
    )
    assert release_projection_import(session, import_id=josh.id, source=source) == first
    bonus_release = release_projection_import(session, import_id=bonus.id, source=source)
    josh_v2 = _projection_import(
        session,
        source=source,
        players=values,
        series_key="josh",
        suffix="new",
        imported_at=NOW if tie else NOW + timedelta(days=2),
    )
    # Higher IDs do not make backdated files current.
    _projection_import(
        session,
        source=source,
        players=values,
        series_key="josh",
        suffix="backdated",
        imported_at=NOW - timedelta(days=1),
    )
    with pytest.raises(StaleProjectionInputError, match=f"current import is {josh_v2.id}"):
        release_projection_import(session, import_id=josh.id, source=source)
    assert (
        release_projection_import(session, import_id=josh_v2.id, source=source).series_key == "josh"
    )
    assert release_projection_import(session, import_id=bonus.id, source=source) == bonus_release
    assert first.content_sha256 == bonus_release.content_sha256
    assert first.profile_definition_sha256 == bonus_release.profile_definition_sha256
    assert first.projection_values_sha256 == bonus_release.projection_values_sha256


def test_invalid_latest_series_refuses_without_older_or_other_series_fallback(
    session: Session,
) -> None:
    source = ExternalSource.BASKETBALL_MONSTER
    player = _player(session)
    values = {player.id: _source_values()}
    josh = _projection_import(session, source=source, players=values, series_key="josh")
    bonus = _projection_import(session, source=source, players=values, series_key="bonus")
    invalid = _projection_import(
        session,
        source=source,
        players=values,
        series_key="josh",
        suffix="invalid",
        imported_at=NOW + timedelta(days=1),
    )
    invalid.profile_verified = False
    session.flush()
    selected_id = current_projection_import_id(
        session, source=source, season=SEASON, series_key="josh"
    )
    assert selected_id == invalid.id
    with pytest.raises(InvalidBlendProfileError, match="verified profile"):
        release_projection_import(session, import_id=selected_id, source=source)
    with pytest.raises(StaleProjectionInputError, match="stale"):
        release_projection_import(session, import_id=josh.id, source=source)
    assert (
        release_projection_import(session, import_id=bonus.id, source=source).series_key == "bonus"
    )


def test_two_current_series_still_cannot_be_blended_as_two_publishers(session: Session) -> None:
    league, scoring = _scoring_profile(session)
    player = _player(session)
    source = ExternalSource.BASKETBALL_MONSTER
    releases = []
    for key in ("josh", "bonus"):
        stored = _projection_import(
            session, source=source, players={player.id: _source_values()}, series_key=key
        )
        releases.append(release_projection_import(session, import_id=stored.id, source=source))
    assert releases[0].import_id != releases[1].import_id
    assert releases[0].series_key != releases[1].series_key
    with pytest.raises(InvalidBlendProfileError, match="more than one import per source"):
        define_blend_profile(
            session,
            BlendCatalog(),
            league_id=league.id,
            name="not-a-two-source-blend",
            scoring_profile_id=scoring.id,
            sources=releases,
            category_weights={key: {source: 1} for key in ("pts", "fg_pct", "ft_pct")},
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("series_key", "", "series_key"),
        ("series_key", "Josh", "series_key"),
        ("series_key", "josh\n", "series_key"),
        ("series_key", None, "series_key"),
        ("release_schema_version", None, "release schema version"),
        ("release_schema_version", "", "release schema version"),
        ("release_schema_version", "projection-import-release-v0", "release schema version"),
    ],
)
def test_release_domain_validation_and_profile_integrity_remain_pure(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    _stored, release, profile = _single_series_profile(session)
    forged = (
        replace(release, series_key=cast(str, value))
        if field == "series_key"
        else replace(release, release_schema_version=cast(str, value))
    )

    def unexpected_io(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("release-domain/profile-integrity validation performed database I/O")

    for method in ("execute", "scalar", "scalars", "get"):
        monkeypatch.setattr(Session, method, unexpected_io)
    validate_blend_profile_integrity(profile)
    assert blend_profile_content_sha256(profile) == profile.content_sha256
    with pytest.raises(InvalidBlendProfileError, match=message):
        validate_blend_profile_integrity(replace(profile, sources=(forged,)))
    # Revalidation also rejects the unsupported domain before loading an ID.
    with pytest.raises(InvalidBlendProfileError, match=message):
        blending._validate_and_load_release(session, forged)


def test_valid_but_forged_series_cannot_release_another_series_import(session: Session) -> None:
    _stored, release, profile = _single_series_profile(session)
    forged = replace(release, series_key="bonus")
    with pytest.raises(StaleProjectionInputError, match="released lineage"):
        define_blend_profile(
            session,
            BlendCatalog(),
            league_id=profile.league_id,
            name=profile.name,
            scoring_profile_id=profile.scoring_profile_id,
            sources=(forged,),
            category_weights={key: {release.source: 1} for key in ("pts", "fg_pct", "ft_pct")},
        )


def test_reclassified_stored_series_invalidates_a_previously_valid_release(
    session: Session,
) -> None:
    stored, _release, profile = _single_series_profile(session)
    stored.series_key = "other"
    stored.series_display_name = "Other operator declaration"
    session.flush()
    with pytest.raises(StaleProjectionInputError, match="released lineage"):
        blend_projections(session, profile)


@pytest.mark.parametrize(
    ("key", "label", "message"),
    [("Josh", "Operator label", "series_key"), ("josh", "\t", "series_display_name")],
)
def test_canonical_release_refuses_malformed_persisted_series(
    session: Session, key: str, label: str, message: str
) -> None:
    stored, release, _profile = _single_series_profile(session)
    stored.series_key = key
    stored.series_display_name = label
    session.flush()
    with pytest.raises(InvalidBlendProfileError, match=message):
        release_projection_import(session, import_id=stored.id, source=release.source)
    if key == release.series_key:
        with pytest.raises(InvalidBlendProfileError, match=message):
            blending._validate_and_load_release(session, release)


def test_release_defaults_append_to_positional_constructor_and_tag_legacy_payloads(
    session: Session,
) -> None:
    _stored, release, _profile = _single_series_profile(session, series_key="legacy")
    constructed = ReleasedProjectionImport(
        release.import_id,
        release.source,
        release.season,
        release.imported_at,
        release.content_sha256,
        release.profile_id,
        release.profile_version,
        release.profile_definition_sha256,
        release.projection_values_sha256,
        release.projection_count,
        release.assumed_scoring_type,
        BlendInputLayer.PROJECTION_IMPORT,
    )
    assert constructed == release
    assert PROJECTION_RELEASE_SCHEMA_VERSION == "projection-import-release-series-v1"
    payload = blending._release_payload(release)
    assert payload["series_key"] == "legacy"
    assert payload["release_schema_version"] == PROJECTION_RELEASE_SCHEMA_VERSION


@pytest.mark.parametrize(
    ("field", "value"),
    [("series_key", "bonus"), ("release_schema_version", "unsupported-hash-domain-control")],
)
def test_hash_payload_binds_series_and_domain_independently_of_import_id(
    session: Session, field: str, value: str
) -> None:
    _stored, release, profile = _single_series_profile(session, series_key="legacy")
    changed = (
        replace(release, series_key=value)
        if field == "series_key"
        else replace(release, release_schema_version=value)
    )
    before, after = blending._release_payload(release), blending._release_payload(changed)
    assert set(before) == set(after)
    assert {key for key in before if before[key] != after[key]} == {field}
    assert release.import_id == changed.import_id
    assert release.content_sha256 == changed.content_sha256
    assert release.profile_definition_sha256 == changed.profile_definition_sha256
    assert release.projection_values_sha256 == changed.projection_values_sha256
    assert (
        blend_profile_content_sha256(replace(profile, sources=(changed,))) != profile.content_sha256
    )


def test_old_content_bound_profile_is_refused_not_rehashed_or_upgraded(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stored, _release, profile = _single_series_profile(session, series_key="legacy")
    successor_payload = blending._release_payload

    def predecessor_payload(release: ReleasedProjectionImport) -> dict[str, object]:
        return {
            key: value
            for key, value in successor_payload(release).items()
            if key not in {"series_key", "release_schema_version"}
        }

    # Construct only a synthetic old-domain content hash. No archived object,
    # scientific artifact, stored recipe or old receipt is rewritten.
    with monkeypatch.context() as patch:
        patch.setattr(blending, "_release_payload", predecessor_payload)
        old_hash = blend_profile_content_sha256(profile)
    assert old_hash != profile.content_sha256
    old = replace(
        profile,
        content_sha256=old_hash,
        profile_id=f"{profile.name}:v{profile.version}:{old_hash[:12]}",
    )
    with pytest.raises(InvalidBlendProfileError, match="content hash"):
        validate_blend_profile_integrity(old)
    with pytest.raises(InvalidBlendProfileError, match="content hash"):
        blend_projections(session, old)
    assert old.content_sha256 == old_hash
    validate_blend_profile_integrity(profile)


def _writer_import(
    session: Session, *, key: str, declaration: ScoringType | None
) -> ProjectionImport:
    """Drive the real admitted writer, never stamp the declaration into an ORM fixture."""
    name = "Synthetic Declaration Player"
    player = session.scalar(select(Player).where(Player.full_name == name))
    if player is None:
        player = _player(session, name)
        session.add(
            PlayerExternalId(
                player_id=player.id,
                source=ExternalSource.NBA,
                current_for_source=ExternalSource.NBA.value,
                external_id="synthetic-declaration-anchor",
                external_name=name,
                normalized_name=player.normalized_name,
                confidence=1.0,
                match_method=MatchMethod.ANCHOR_ID,
                name_evidence=FieldEvidence.AGREE,
            )
        )
        session.flush()
    result = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Synthetic publisher",
        season=SEASON,
        csv_bytes=(
            b"player_name,points_per_game,field_goals_made_per_game,"
            b"field_goals_attempted_per_game,free_throws_made_per_game,"
            b"free_throws_attempted_per_game\nSynthetic Declaration Player,20,8,16,4,5\n"
        ),
        series_key=key,
        assumed_scoring_type=declaration,
    )
    assert result.counts.created + result.counts.updated == 1
    return result.projection_import


@pytest.mark.parametrize("provider_default", [None, ScoringType.H2H_EACH_CATEGORY])
def test_real_named_writer_isolates_declarations_and_keeps_null_fallback_semantics(
    session: Session, provider_default: ScoringType | None
) -> None:
    league, scoring = _scoring_profile(session)
    source = get_or_create_projection_source(
        session,
        source=ExternalSource.MANUAL,
        display_name="Synthetic publisher",
        assumed_scoring_type=provider_default,
    )
    josh = _writer_import(session, key="josh", declaration=None)
    before = release_projection_import(session, import_id=josh.id, source=ExternalSource.MANUAL)
    bonus = _writer_import(session, key="bonus", declaration=ScoringType.POINTS)
    session.expire_all()
    assert source.assumed_scoring_type is provider_default
    assert josh.assumed_scoring_type is None
    assert bonus.assumed_scoring_type is ScoringType.POINTS
    josh_release = release_projection_import(
        session, import_id=josh.id, source=ExternalSource.MANUAL
    )
    bonus_release = release_projection_import(
        session, import_id=bonus.id, source=ExternalSource.MANUAL
    )
    assert josh_release == before
    assert josh_release.assumed_scoring_type is provider_default
    assert bonus_release.assumed_scoring_type is ScoringType.POINTS
    weights = {key: {ExternalSource.MANUAL: 1} for key in ("pts", "fg_pct", "ft_pct")}
    # Null is still accepted by the existing boundary; no new scoring admission rule.
    define_blend_profile(
        session,
        BlendCatalog(),
        league_id=league.id,
        name="josh",
        scoring_profile_id=scoring.id,
        sources=(josh_release,),
        category_weights=weights,
    )
    with pytest.raises(InvalidBlendProfileError, match="not target"):
        define_blend_profile(
            session,
            BlendCatalog(),
            league_id=league.id,
            name="bonus",
            scoring_profile_id=scoring.id,
            sources=(bonus_release,),
            category_weights=weights,
        )


@pytest.mark.parametrize("update_default", ["legacy-new", "legacy-replay", "registration"])
def test_real_writer_preserves_explicit_precedence_and_intentional_provider_updates(
    session: Session, update_default: str
) -> None:
    if update_default == "legacy-replay":
        _writer_import(session, key="legacy", declaration=None)
    null_import = _writer_import(session, key="josh", declaration=None)
    explicit_import = _writer_import(
        session, key="bonus", declaration=ScoringType.H2H_EACH_CATEGORY
    )
    null_release = release_projection_import(
        session, import_id=null_import.id, source=ExternalSource.MANUAL
    )
    explicit_release = release_projection_import(
        session, import_id=explicit_import.id, source=ExternalSource.MANUAL
    )
    assert null_import.assumed_scoring_type is None
    assert null_import.source_row.assumed_scoring_type is None
    assert null_release.assumed_scoring_type is None
    if update_default == "registration":
        get_or_create_projection_source(
            session,
            source=ExternalSource.MANUAL,
            display_name="Synthetic publisher",
            assumed_scoring_type=ScoringType.POINTS,
        )
    else:
        _writer_import(session, key="legacy", declaration=ScoringType.POINTS)
    session.expire_all()
    assert null_import.assumed_scoring_type is None
    stored_source = session.get(ProjectionSource, null_import.source_id)
    assert stored_source is not None
    assert stored_source.assumed_scoring_type is ScoringType.POINTS
    current_null = release_projection_import(
        session, import_id=null_import.id, source=ExternalSource.MANUAL
    )
    assert current_null.assumed_scoring_type is ScoringType.POINTS
    assert (
        release_projection_import(
            session, import_id=explicit_import.id, source=ExternalSource.MANUAL
        )
        == explicit_release
    )
    assert explicit_release.assumed_scoring_type is ScoringType.H2H_EACH_CATEGORY
    with pytest.raises(StaleProjectionInputError, match="released lineage"):
        blending._validate_and_load_release(session, null_release)


def test_real_writer_gp_only_revision_changes_lineage_not_complete_producer_numbers(
    session: Session,
) -> None:
    import_nba_players(
        session, parse_common_all_players(load_fixture(DEFAULT_FIXTURES_DIR, PLAYERS_FIXTURE))
    )
    league, scoring = _nine_category_scoring_profile(session)
    fixtures = Path(__file__).parent / "fixtures" / "projections"
    releases = []
    blends = []
    scores = []
    games = []
    for filename in ("series_josh.csv", "series_josh_gp_only.csv"):
        result = import_projection_csv(
            session,
            source=ExternalSource.BASKETBALL_MONSTER,
            display_name="Synthetic publisher",
            season=SEASON,
            csv_bytes=(fixtures / filename).read_bytes(),
            series_key="josh",
        )
        assert result.counts.created == 55
        release = release_projection_import(
            session,
            import_id=result.projection_import.id,
            source=ExternalSource.BASKETBALL_MONSTER,
        )
        _catalog, profile = define_blend_profile(
            session,
            BlendCatalog(),
            league_id=league.id,
            name="gp-control",
            scoring_profile_id=scoring.id,
            sources=(release,),
            category_weights={
                key: {ExternalSource.BASKETBALL_MONSTER: 1} for key in NINE_CATEGORY_DEFINITIONS
            },
        )
        blend = blend_projections(session, profile)
        scores.append(
            score_production_zscores(league=league, blend_profile=profile, blend_result=blend)
        )
        blends.append(blend)
        releases.append(release)
        games.append(
            tuple(
                session.scalars(
                    select(SourceGamesPlayedAssumption.assumed_games_played)
                    .join(Projection)
                    .where(Projection.projection_import_id == release.import_id)
                    .order_by(Projection.player_id)
                )
            )
        )
    assert len(games[0]) == len(games[1]) == 55
    assert games[0] != games[1]
    assert releases[0].content_sha256 != releases[1].content_sha256
    assert releases[0].profile_definition_sha256 == releases[1].profile_definition_sha256
    assert releases[0].projection_values_sha256 == releases[1].projection_values_sha256
    assert blends[0].projections == blends[1].projections
    assert blends[0].content_sha256 != blends[1].content_sha256
    before, after = asdict(scores[0]), asdict(scores[1])
    assert set(before) == set(after)
    # Enumerate only the four changed lineage identities. Every numeric field,
    # reference member/fingerprint, component, scale, ordinal and replacement
    # value must compare equal, rather than stripping broad result subtrees.
    assert {key for key in before if before[key] != after[key]} == {
        "blend_profile_id",
        "blend_profile_content_sha256",
        "blend_result_content_sha256",
        "content_sha256",
    }
