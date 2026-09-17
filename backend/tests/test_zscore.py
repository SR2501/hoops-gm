from __future__ import annotations

import ast
import hashlib
import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

import pytest

from hoops_gm.db.layers import DataLayer
from hoops_gm.db.models.enums import CategoryKind, ExternalSource, ScoringType
from hoops_gm.db.models.league import League
from hoops_gm.projections.blending import (
    BlendedCategoryValue,
    BlendedProjection,
    BlendProfile,
    BlendResult,
    CategoryBlendWeights,
    ManualProjectionOverride,
    ReleasedProjectionImport,
    ScoringCategoryContract,
    SourceBlendWeight,
    WeightBasis,
    blend_profile_content_sha256,
)
from hoops_gm.valuation.zscore import (
    InvalidZScoreInputError,
    PlayerProductionZScore,
    ProductionZScoreResult,
    ReplacementState,
    ScaleStatus,
    ZScoreCategoryComponent,
    score_production_zscores,
)

_CONTRACTS = (
    ScoringCategoryContract("pts", CategoryKind.COUNTING, 1, ("points_per_game",)),
    ScoringCategoryContract("reb", CategoryKind.COUNTING, 1, ("rebounds_per_game",)),
    ScoringCategoryContract("ast", CategoryKind.COUNTING, 1, ("assists_per_game",)),
    ScoringCategoryContract("stl", CategoryKind.COUNTING, 1, ("steals_per_game",)),
    ScoringCategoryContract("blk", CategoryKind.COUNTING, 1, ("blocks_per_game",)),
    ScoringCategoryContract("fg3m", CategoryKind.COUNTING, 1, ("three_pointers_made_per_game",)),
    ScoringCategoryContract("to", CategoryKind.COUNTING, -1, ("turnovers_per_game",)),
    ScoringCategoryContract(
        "fg_pct",
        CategoryKind.RATIO,
        1,
        ("field_goals_made_per_game", "field_goals_attempted_per_game"),
    ),
    ScoringCategoryContract(
        "ft_pct",
        CategoryKind.RATIO,
        1,
        ("free_throws_made_per_game", "free_throws_attempted_per_game"),
    ),
)


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _category_payload(value: BlendedCategoryValue) -> dict[str, object]:
    return {
        "category_key": value.category_key,
        "values": [
            {"field": field, "value": f"{number.numerator}/{number.denominator}"}
            for field, number in value.values
        ],
        "manual_override_id": value.manual_override_id,
    }


def _projection(player_id: int, values: dict[str, tuple[Fraction, ...]]) -> BlendedProjection:
    categories = tuple(
        BlendedCategoryValue(
            category_key=contract.category_key,
            values=tuple(
                zip(
                    contract.production_fields,
                    values[contract.category_key],
                    strict=True,
                )
            ),
            manual_override_id=None,
        )
        for contract in _CONTRACTS
    )
    return BlendedProjection(
        player_id=player_id,
        categories=categories,
        content_sha256=_sha256(
            {
                "player_id": player_id,
                "categories": [_category_payload(category) for category in categories],
            }
        ),
    )


def _line(
    *,
    pts: Fraction = Fraction(10),
    reb: Fraction = Fraction(5),
    ast: Fraction = Fraction(4),
    stl: Fraction = Fraction(1),
    blk: Fraction = Fraction(1),
    fg3m: Fraction = Fraction(2),
    turnovers: Fraction = Fraction(2),
    fgm: Fraction = Fraction(5),
    fga: Fraction = Fraction(10),
    ftm: Fraction = Fraction(4),
    fta: Fraction = Fraction(5),
) -> dict[str, tuple[Fraction, ...]]:
    return {
        "pts": (pts,),
        "reb": (reb,),
        "ast": (ast,),
        "stl": (stl,),
        "blk": (blk,),
        "fg3m": (fg3m,),
        "to": (turnovers,),
        "fg_pct": (fgm, fga),
        "ft_pct": (ftm, fta),
    }


def _inputs(
    projections: tuple[BlendedProjection, ...],
    *,
    team_count: int = 1,
    roster_size: int = 1,
) -> tuple[League, BlendProfile, BlendResult]:
    release = ReleasedProjectionImport(
        import_id=1,
        source=ExternalSource.MANUAL,
        season="2026-27",
        imported_at=datetime(2026, 9, 1, tzinfo=UTC),
        content_sha256="c" * 64,
        profile_id="manual-test",
        profile_version="1",
        profile_definition_sha256="d" * 64,
        projection_values_sha256="e" * 64,
        projection_count=max(1, len(projections)),
        assumed_scoring_type=ScoringType.H2H_EACH_CATEGORY,
    )
    weights = tuple(
        CategoryBlendWeights(
            category_key=contract.category_key,
            weights=(
                SourceBlendWeight(
                    source=ExternalSource.MANUAL,
                    raw_weight=Fraction(1),
                    normalized_weight=Fraction(1),
                ),
            ),
        )
        for contract in _CONTRACTS
    )
    unhashed_profile = BlendProfile(
        profile_id="pending",
        name="test-production",
        version=1,
        league_id=1,
        season="2026-27",
        scoring_profile_id=7,
        scoring_profile_sha256="b" * 64,
        scoring_type=ScoringType.H2H_EACH_CATEGORY,
        sources=(release,),
        category_contracts=_CONTRACTS,
        category_weights=weights,
        manual_overrides=(),
        weight_basis=WeightBasis.USER_CONFIGURED,
        content_sha256="pending",
    )
    profile_hash = blend_profile_content_sha256(unhashed_profile)
    profile = replace(
        unhashed_profile,
        profile_id=f"test-production:v1:{profile_hash[:12]}",
        content_sha256=profile_hash,
    )
    result = BlendResult(
        profile_id=profile.profile_id,
        profile_content_sha256=profile_hash,
        projections=projections,
        content_sha256=_sha256(
            {
                "profile_id": profile.profile_id,
                "profile_content_sha256": profile_hash,
                "projections": [
                    {"player_id": projection.player_id, "sha256": projection.content_sha256}
                    for projection in projections
                ],
            }
        ),
    )
    league = League(
        id=1,
        name="Test League",
        season="2026-27",
        team_count=team_count,
        roster_size=roster_size,
    )
    return league, profile, result


def _score_by_id(
    result: ProductionZScoreResult,
    player_id: int,
) -> PlayerProductionZScore:
    return next(score for score in result.scores if score.player_id == player_id)


def _component(
    score: PlayerProductionZScore,
    category_key: str,
) -> ZScoreCategoryComponent:
    return next(
        component
        for component in score.category_components
        if component.category_key == category_key
    )


@pytest.mark.parametrize(
    ("category_key", "high_line", "low_line"),
    [
        ("pts", _line(pts=Fraction(20)), _line(pts=Fraction(10))),
        ("reb", _line(reb=Fraction(10)), _line(reb=Fraction(5))),
        ("ast", _line(ast=Fraction(8)), _line(ast=Fraction(4))),
        ("stl", _line(stl=Fraction(2)), _line(stl=Fraction(1))),
        ("blk", _line(blk=Fraction(2)), _line(blk=Fraction(1))),
        ("fg3m", _line(fg3m=Fraction(4)), _line(fg3m=Fraction(2))),
        ("to", _line(turnovers=Fraction(4)), _line(turnovers=Fraction(2))),
        (
            "fg_pct",
            _line(fgm=Fraction(6), fga=Fraction(10)),
            _line(fgm=Fraction(4), fga=Fraction(10)),
        ),
        (
            "ft_pct",
            _line(ftm=Fraction(9), fta=Fraction(10)),
            _line(ftm=Fraction(7), fta=Fraction(10)),
        ),
    ],
)
def test_each_category_sign_is_pinned_independently(
    category_key: str,
    high_line: dict[str, tuple[Fraction, ...]],
    low_line: dict[str, tuple[Fraction, ...]],
) -> None:
    league, profile, blend = _inputs(
        (_projection(1, high_line), _projection(2, low_line)),
        team_count=1,
        roster_size=1,
    )

    result = score_production_zscores(
        league=league,
        blend_profile=profile,
        blend_result=blend,
    )

    high = _component(_score_by_id(result, 1), category_key)
    low = _component(_score_by_id(result, 2), category_key)
    if category_key == "to":
        assert high.z_score < low.z_score
    else:
        assert high.z_score > low.z_score


def test_ft_volume_impact_uses_the_explicit_point_seven_eight_reference() -> None:
    players = (
        _projection(1, _line(ftm=Fraction(9, 10), fta=Fraction(1))),
        _projection(2, _line(ftm=Fraction(32, 5), fta=Fraction(8))),
        _projection(3, _line(ftm=Fraction(707, 10), fta=Fraction(91))),
    )
    league, profile, blend = _inputs(players, team_count=1, roster_size=3)

    result = score_production_zscores(
        league=league,
        blend_profile=profile,
        blend_result=blend,
    )

    scale = next(scale for scale in result.category_scales if scale.category_key == "ft_pct")
    one_attempt = _component(_score_by_id(result, 1), "ft_pct")
    eight_attempts = _component(_score_by_id(result, 2), "ft_pct")
    assert scale.reference_percentage == pytest.approx(0.78)
    assert one_attempt.transformed_value == pytest.approx(0.12)
    assert eight_attempts.transformed_value == pytest.approx(0.16)
    assert eight_attempts.z_score > one_attempt.z_score


def test_zero_attempt_player_is_neutral_but_all_zero_reference_attempts_refuse() -> None:
    neutral = _projection(1, _line(ftm=Fraction(0), fta=Fraction(0)))
    volume = _projection(2, _line(ftm=Fraction(4), fta=Fraction(5)))
    league, profile, blend = _inputs((neutral, volume))

    result = score_production_zscores(
        league=league,
        blend_profile=profile,
        blend_result=blend,
    )

    assert _component(_score_by_id(result, 1), "ft_pct").transformed_value == 0

    all_zero = (
        _projection(1, _line(ftm=Fraction(0), fta=Fraction(0))),
        _projection(2, _line(ftm=Fraction(0), fta=Fraction(0))),
    )
    league, profile, blend = _inputs(all_zero)
    with pytest.raises(InvalidZScoreInputError, match="zero attempts"):
        score_production_zscores(
            league=league,
            blend_profile=profile,
            blend_result=blend,
        )


def test_zero_variance_emits_explicit_zero_components() -> None:
    league, profile, blend = _inputs(
        (_projection(1, _line()), _projection(2, _line())),
        team_count=1,
        roster_size=2,
    )

    result = score_production_zscores(
        league=league,
        blend_profile=profile,
        blend_result=blend,
    )

    assert all(scale.status is ScaleStatus.ZERO_VARIANCE for scale in result.category_scales)
    assert all(
        component.z_score == 0 for score in result.scores for component in score.category_components
    )


@pytest.mark.parametrize("player_count", [12, 60])
def test_valid_cohorts_at_or_below_structural_n_keep_scores_without_replacement(
    player_count: int,
) -> None:
    projections = tuple(
        _projection(player_id, _line(pts=Fraction(player_id)))
        for player_id in range(1, player_count + 1)
    )
    league, profile, blend = _inputs(projections, team_count=12, roster_size=13)

    result = score_production_zscores(
        league=league,
        blend_profile=profile,
        blend_result=blend,
    )

    assert len(result.scores) == player_count
    assert result.structural_roster_count == 156
    assert result.replacement.state is ReplacementState.UNAVAILABLE_INSUFFICIENT_PROJECTED_POOL
    assert result.replacement.required_ordinal == 157
    assert result.replacement.replacement_player_id is None
    assert result.replacement.replacement_total_z is None
    assert all(score.value_above_replacement is None for score in result.scores)


def test_replacement_is_explicit_ordinal_n_plus_one() -> None:
    projections = tuple(
        _projection(player_id, _line(pts=Fraction(player_id))) for player_id in range(1, 5)
    )
    league, profile, blend = _inputs(projections, team_count=1, roster_size=2)

    result = score_production_zscores(
        league=league,
        blend_profile=profile,
        blend_result=blend,
    )

    assert result.replacement.state is ReplacementState.AVAILABLE
    assert result.replacement.required_ordinal == 3
    assert result.replacement.replacement_player_id == result.scores[2].player_id
    assert result.replacement.replacement_total_z == result.scores[2].total_z
    assert all(score.value_above_replacement is not None for score in result.scores)


def test_ties_order_by_canonical_player_id_without_changing_equal_scores() -> None:
    league, profile, blend = _inputs(
        (_projection(9, _line()), _projection(3, _line())),
        team_count=1,
        roster_size=2,
    )

    result = score_production_zscores(
        league=league,
        blend_profile=profile,
        blend_result=blend,
    )

    assert [score.player_id for score in result.scores] == [3, 9]
    assert result.scores[0].total_z == result.scores[1].total_z == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("team_count", None),
        ("team_count", True),
        ("team_count", 0),
        ("roster_size", None),
        ("roster_size", False),
        ("roster_size", -1),
    ],
)
def test_structure_is_explicit_positive_and_never_inferred(field: str, value: object) -> None:
    league, profile, blend = _inputs((_projection(1, _line()),))
    setattr(league, field, value)
    with pytest.raises(InvalidZScoreInputError, match=field):
        score_production_zscores(
            league=league,
            blend_profile=profile,
            blend_result=blend,
        )


def test_missing_category_and_invalid_volume_refuse_the_whole_run() -> None:
    projection = _projection(1, _line())
    missing = replace(
        projection,
        categories=projection.categories[:-1],
    )
    missing = replace(
        missing,
        content_sha256=_sha256(
            {
                "player_id": missing.player_id,
                "categories": [_category_payload(category) for category in missing.categories],
            }
        ),
    )
    league, profile, blend = _inputs((missing,))
    with pytest.raises(InvalidZScoreInputError, match="all nine"):
        score_production_zscores(
            league=league,
            blend_profile=profile,
            blend_result=blend,
        )

    invalid = _projection(1, _line(fgm=Fraction(11), fga=Fraction(10)))
    league, profile, blend = _inputs((invalid,))
    with pytest.raises(InvalidZScoreInputError, match="makes greater"):
        score_production_zscores(
            league=league,
            blend_profile=profile,
            blend_result=blend,
        )


def test_value_outside_finite_float_range_refuses_the_whole_run() -> None:
    projections = (
        _projection(1, _line(pts=Fraction(10**1000))),
        _projection(2, _line(pts=Fraction(1))),
    )
    league, profile, blend = _inputs(projections)

    with pytest.raises(InvalidZScoreInputError, match="finite scoring range"):
        score_production_zscores(
            league=league,
            blend_profile=profile,
            blend_result=blend,
        )


def test_lineage_hash_tampering_is_refused() -> None:
    league, profile, blend = _inputs((_projection(1, _line()),))
    with pytest.raises(InvalidZScoreInputError, match="content hash"):
        score_production_zscores(
            league=league,
            blend_profile=profile,
            blend_result=replace(blend, content_sha256="0" * 64),
        )


def test_runtime_reconstructs_all_blend_profile_integrity_fields() -> None:
    league, profile, blend = _inputs((_projection(1, _line()),))
    changed_source = replace(profile.sources[0], content_sha256="f" * 64)
    changed_contract = replace(profile.category_contracts[0], direction=-1)
    changed_weight = replace(
        profile.category_weights[0].weights[0],
        raw_weight=Fraction(2),
    )
    changed_category_weights = replace(
        profile.category_weights[0],
        weights=(changed_weight,),
    )
    override = ManualProjectionOverride(
        override_id="owner-pts",
        league_id=profile.league_id,
        season=profile.season,
        player_id=1,
        category_key="pts",
        values=(("points_per_game", Fraction(11)),),
        actor="owner",
        reason="test integrity binding",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    tampered_profiles = (
        replace(profile, sources=(changed_source,)),
        replace(
            profile,
            category_contracts=(changed_contract, *profile.category_contracts[1:]),
        ),
        replace(
            profile,
            category_weights=(
                changed_category_weights,
                *profile.category_weights[1:],
            ),
        ),
        replace(profile, manual_overrides=(override,)),
        replace(profile, weight_basis=WeightBasis.LEARNED_ACCURACY),
        replace(profile, scoring_profile_sha256="0" * 64),
        replace(profile, scoring_type=ScoringType.POINTS),
        replace(profile, version=2),
        replace(profile, profile_id="tampered"),
    )

    for tampered in tampered_profiles:
        with pytest.raises(InvalidZScoreInputError):
            score_production_zscores(
                league=league,
                blend_profile=tampered,
                blend_result=blend,
            )


def test_result_is_explicitly_production_only_and_content_addressed() -> None:
    league, profile, blend = _inputs(
        (_projection(1, _line(pts=Fraction(10))), _projection(2, _line(pts=Fraction(20)))),
    )

    first = score_production_zscores(
        league=league,
        blend_profile=profile,
        blend_result=blend,
    )
    second = score_production_zscores(
        league=league,
        blend_profile=profile,
        blend_result=blend,
    )

    assert first == second
    assert first.value_scope == "production_only"
    assert first.availability_included is False
    assert first.output_layer is DataLayer.TERMINAL
    assert len(first.content_sha256) == 64
    assert first.reference_count == 2
    assert first.reference_player_ids == (1, 2)


def test_runtime_dependency_surface_has_no_query_or_forbidden_layer_path() -> None:
    import hoops_gm.valuation.zscore as module

    signature = inspect.signature(module.score_production_zscores)
    assert tuple(signature.parameters) == ("league", "blend_profile", "blend_result")

    path = Path(module.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    forbidden_prefixes = (
        "sqlalchemy",
        "hoops_gm.availability",
        "hoops_gm.db.models.availability",
        "hoops_gm.db.models.market",
        "hoops_gm.db.models.projections",
    )
    assert not {
        name
        for name in imported
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden_prefixes)
    }
    source = path.read_text(encoding="utf-8")
    assert "SourceGamesPlayedAssumption" not in source
    assert "assumed_games_played" not in source
    assert "expected_games" not in source
