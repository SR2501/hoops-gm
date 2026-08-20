"""Projection blending: immutable lineage, layer purity, and per-game math."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from fractions import Fraction

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import CategoryKind, ExternalSource, ScoringType
from hoops_gm.db.models.identity import Player
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
from hoops_gm.projections.blending import (
    BlendCatalog,
    BlendedCategoryValue,
    BlendInputLayer,
    InvalidBlendProfileError,
    LayerPurityError,
    ManualProjectionOverride,
    MissingProjectionDataError,
    StaleProjectionInputError,
    UnknownProjectionInputError,
    WeightBasis,
    activate_blend_profile,
    blend_active_projections,
    blend_projections,
    current_blend_profile,
    define_blend_profile,
    release_projection_import,
)

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
