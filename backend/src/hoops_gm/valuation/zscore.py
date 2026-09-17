"""Deterministic, production-only nine-category z-scores.

This module starts at the released projection-blend boundary. It accepts the
existing :class:`~hoops_gm.projections.blending.BlendProfile` and
:class:`~hoops_gm.projections.blending.BlendResult` domain values plus explicit
league structure. It has no database session and no path to availability,
games-played assumptions, seasonal totals, market evidence, or draft outcomes.

All supplied complete players form the reference population. Counting rates are
standardized directly. FG% and FT% are converted to made-shot impact relative
to the reference population's attempt-weighted percentage, then those impacts
are standardized. Population standard deviation (``ddof=0``) is used because
the declared reference cohort is the complete population being valued.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from typing import Final

from hoops_gm.db.layers import DataLayer
from hoops_gm.db.models.enums import CategoryKind, ScoringType
from hoops_gm.db.models.league import League
from hoops_gm.projections.blending import (
    BlendedCategoryValue,
    BlendedProjection,
    BlendProfile,
    BlendResult,
    ProjectionBlendError,
    ScoringCategoryContract,
    validate_blend_profile_integrity,
    validate_production_shooting_values,
)
from hoops_gm.scoring.profiles import NINE_CATEGORY_DEFINITIONS

MODEL_VERSION: Final = "zscore-production-v1"
REFERENCE_POLICY: Final = "all_complete_supplied_players_v1"
REPLACEMENT_POLICY: Final = "explicit_structure_ordinal_n_plus_one_v1"
AGGREGATION_POLICY: Final = "equal_weight_sum_of_nine_directed_components_v1"

_COUNTING_FIELDS: Final[dict[str, str]] = {
    "pts": "points_per_game",
    "reb": "rebounds_per_game",
    "ast": "assists_per_game",
    "stl": "steals_per_game",
    "blk": "blocks_per_game",
    "fg3m": "three_pointers_made_per_game",
    "to": "turnovers_per_game",
}


class InvalidZScoreInputError(ValueError):
    """The supplied production cohort cannot be scored without invention."""


class ScaleStatus(StrEnum):
    DEFINED = "defined"
    ZERO_VARIANCE = "zero_variance"


class ReplacementState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE_INSUFFICIENT_PROJECTED_POOL = "unavailable_insufficient_projected_pool"


@dataclass(frozen=True, slots=True)
class CategoryScale:
    """The complete transform that gives one category component its meaning."""

    category_key: str
    kind: CategoryKind
    direction: int
    production_fields: tuple[str, ...]
    reference_mean: float
    population_sd: float
    reference_percentage: float | None
    status: ScaleStatus


@dataclass(frozen=True, slots=True)
class ZScoreCategoryComponent:
    """One player's transformed production value and directed z-score."""

    category_key: str
    production_fields: tuple[tuple[str, Fraction], ...]
    transformed_value: float
    z_score: float


@dataclass(frozen=True, slots=True)
class PlayerProductionZScore:
    """Production-only score; ordinal is structural ordering, not roster status."""

    player_id: int
    ordinal: int
    category_components: tuple[ZScoreCategoryComponent, ...]
    total_z: float
    value_above_replacement: float | None


@dataclass(frozen=True, slots=True)
class ReplacementSummary:
    """Whether the explicit projected pool contains ordinal ``N + 1``."""

    policy: str
    state: ReplacementState
    required_ordinal: int
    projected_count: int
    structural_roster_count: int
    structural_roster_covered: bool
    structural_roster_shortfall: int
    replacement_ordinal_shortfall: int
    replacement_player_id: int | None
    replacement_total_z: float | None


@dataclass(frozen=True, slots=True)
class ProductionZScoreResult:
    """A deterministic, fully attributed production-only scoring result."""

    model_version: str
    value_scope: str
    output_layer: DataLayer
    availability_included: bool
    aggregation_policy: str
    input_kind: str
    league_id: int
    season: str
    team_count: int
    roster_size: int
    structural_roster_count: int
    scoring_profile_id: int | None
    scoring_profile_sha256: str | None
    scoring_type: ScoringType
    blend_profile_id: str | None
    blend_profile_content_sha256: str | None
    blend_result_content_sha256: str | None
    benchmark_id: str | None
    benchmark_input_season: str | None
    benchmark_input_content_sha256: str | None
    reference_policy: str
    reference_count: int
    reference_player_ids: tuple[int, ...]
    reference_player_fingerprint: str
    category_scales: tuple[CategoryScale, ...]
    replacement: ReplacementSummary
    scores: tuple[PlayerProductionZScore, ...]
    content_sha256: str


@dataclass(frozen=True, slots=True)
class _ValidatedPlayer:
    player_id: int
    by_category: dict[str, tuple[tuple[str, Fraction], ...]]


@dataclass(frozen=True, slots=True)
class HistoricalProductionBenchmark:
    """Explicit non-vendor adapter input for a retrospective carry-forward."""

    benchmark_id: str
    input_season: str
    target_season: str
    input_content_sha256: str
    category_contracts: tuple[ScoringCategoryContract, ...]
    projections: tuple[BlendedProjection, ...]


def _positive_non_boolean_int(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise InvalidZScoreInputError(f"{label} must be a positive non-boolean integer")
    return value


def _expected_fields(contract: ScoringCategoryContract) -> tuple[str, ...]:
    definition = NINE_CATEGORY_DEFINITIONS.get(contract.category_key)
    if definition is None:
        raise InvalidZScoreInputError(
            f"unsupported scoring category {contract.category_key!r}; exactly canonical 9-cat "
            "is required"
        )
    if contract.kind is not definition.kind or contract.direction != definition.direction:
        raise InvalidZScoreInputError(
            f"category {contract.category_key!r} semantics disagree with canonical 9-cat"
        )
    if contract.kind is CategoryKind.COUNTING:
        expected = _COUNTING_FIELDS.get(contract.category_key)
        if expected is None:
            raise InvalidZScoreInputError(
                f"counting category {contract.category_key!r} has no production mapping"
            )
        return (expected,)
    if definition.numerator_stat is None or definition.denominator_stat is None:
        raise InvalidZScoreInputError(
            f"ratio category {contract.category_key!r} lacks canonical volume semantics"
        )
    return (
        f"{definition.numerator_stat}_per_game",
        f"{definition.denominator_stat}_per_game",
    )


def _validate_contracts(
    contracts: tuple[ScoringCategoryContract, ...],
) -> tuple[tuple[ScoringCategoryContract, tuple[str, ...]], ...]:
    expected_keys = set(NINE_CATEGORY_DEFINITIONS)
    actual_keys = [contract.category_key for contract in contracts]
    if len(actual_keys) != len(set(actual_keys)):
        raise InvalidZScoreInputError("scoring profile repeats a category")
    if set(actual_keys) != expected_keys:
        raise InvalidZScoreInputError(
            "scoring profile must contain exactly canonical 9-cat; "
            f"missing={sorted(expected_keys - set(actual_keys))}, "
            f"extra={sorted(set(actual_keys) - expected_keys)}"
        )
    validated: list[tuple[ScoringCategoryContract, tuple[str, ...]]] = []
    for contract in contracts:
        fields = _expected_fields(contract)
        if contract.production_fields != fields:
            raise InvalidZScoreInputError(
                f"category {contract.category_key!r} must use fields {fields}, "
                f"got {contract.production_fields}"
            )
        validated.append((contract, fields))
    return tuple(validated)


def _category_payload(value: BlendedCategoryValue) -> dict[str, object]:
    return {
        "category_key": value.category_key,
        "values": [
            {"field": field, "value": f"{field_value.numerator}/{field_value.denominator}"}
            for field, field_value in value.values
        ],
        "manual_override_id": value.manual_override_id,
    }


def _validate_projection_hash(projection: BlendedProjection) -> None:
    expected = _sha256(
        {
            "player_id": projection.player_id,
            "categories": [_category_payload(value) for value in projection.categories],
        }
    )
    if projection.content_sha256 != expected:
        raise InvalidZScoreInputError(
            f"player {projection.player_id} projection content hash does not match its values"
        )


def _validate_result_hash(result: BlendResult) -> None:
    expected = _sha256(
        {
            "profile_id": result.profile_id,
            "profile_content_sha256": result.profile_content_sha256,
            "projections": [
                {"player_id": projection.player_id, "sha256": projection.content_sha256}
                for projection in result.projections
            ],
        }
    )
    if result.content_sha256 != expected:
        raise InvalidZScoreInputError("blend result content hash does not match its projections")


def _validated_players(
    projections: tuple[BlendedProjection, ...],
    contracts: tuple[tuple[ScoringCategoryContract, tuple[str, ...]], ...],
) -> tuple[_ValidatedPlayer, ...]:
    if not projections:
        raise InvalidZScoreInputError("the supplied production cohort is empty")
    expected_categories = {contract.category_key for contract, _fields in contracts}
    seen_players: set[int] = set()
    validated: list[_ValidatedPlayer] = []
    for projection in projections:
        player_id = _positive_non_boolean_int(projection.player_id, label="player_id")
        if player_id in seen_players:
            raise InvalidZScoreInputError(f"player {player_id} appears more than once")
        seen_players.add(player_id)
        _validate_projection_hash(projection)
        values_by_key: dict[str, BlendedCategoryValue] = {}
        for value in projection.categories:
            if value.category_key in values_by_key:
                raise InvalidZScoreInputError(
                    f"player {player_id} repeats category {value.category_key!r}"
                )
            values_by_key[value.category_key] = value
        if set(values_by_key) != expected_categories:
            raise InvalidZScoreInputError(
                f"player {player_id} must provide all nine categories; "
                f"missing={sorted(expected_categories - set(values_by_key))}, "
                f"extra={sorted(set(values_by_key) - expected_categories)}"
            )
        player_values: dict[str, tuple[tuple[str, Fraction], ...]] = {}
        for contract, fields in contracts:
            supplied = values_by_key[contract.category_key]
            field_names = tuple(field for field, _value in supplied.values)
            if field_names != fields:
                raise InvalidZScoreInputError(
                    f"player {player_id} category {contract.category_key!r} must provide "
                    f"{fields}, got {field_names}"
                )
            normalized: list[tuple[str, Fraction]] = []
            for field, raw in supplied.values:
                if not isinstance(raw, Fraction):
                    raise InvalidZScoreInputError(
                        f"player {player_id} field {field!r} is not a normalized Fraction"
                    )
                if raw < 0:
                    raise InvalidZScoreInputError(
                        f"player {player_id} field {field!r} must be non-negative"
                    )
                normalized.append((field, raw))
            if contract.kind is CategoryKind.RATIO:
                try:
                    validate_production_shooting_values(
                        tuple(normalized),
                        label=f"player {player_id} category {contract.category_key}",
                    )
                except ProjectionBlendError as exc:
                    raise InvalidZScoreInputError(str(exc)) from exc
            player_values[contract.category_key] = tuple(normalized)
        validated.append(_ValidatedPlayer(player_id=player_id, by_category=player_values))
    return tuple(sorted(validated, key=lambda player: player.player_id))


def _population_scale(values: list[float]) -> tuple[float, float, ScaleStatus]:
    try:
        mean = math.fsum(values) / len(values)
        variance = math.fsum((value - mean) ** 2 for value in values) / len(values)
    except OverflowError as exc:
        raise InvalidZScoreInputError(
            "reference population values exceed the finite scoring range"
        ) from exc
    if not math.isfinite(mean) or not math.isfinite(variance):
        raise InvalidZScoreInputError("reference population values exceed the finite scoring range")
    sd = math.sqrt(variance)
    if sd == 0:
        return mean, 0.0, ScaleStatus.ZERO_VARIANCE
    return mean, sd, ScaleStatus.DEFINED


def _finite_float(value: Fraction, *, player_id: int, field: str) -> float:
    try:
        converted = float(value)
    except OverflowError as exc:
        raise InvalidZScoreInputError(
            f"player {player_id} field {field!r} exceeds the finite scoring range"
        ) from exc
    if not math.isfinite(converted):
        raise InvalidZScoreInputError(f"player {player_id} field {field!r} must be finite")
    return converted


def _category_scales_and_values(
    players: tuple[_ValidatedPlayer, ...],
    contracts: tuple[tuple[ScoringCategoryContract, tuple[str, ...]], ...],
) -> tuple[tuple[CategoryScale, ...], dict[int, dict[str, float]]]:
    scales: list[CategoryScale] = []
    transformed: dict[int, dict[str, float]] = {player.player_id: {} for player in players}
    for contract, fields in contracts:
        reference_percentage: float | None = None
        values: list[float] = []
        if contract.kind is CategoryKind.RATIO:
            total_made = sum(
                (player.by_category[contract.category_key][0][1] for player in players),
                start=Fraction(),
            )
            total_attempted = sum(
                (player.by_category[contract.category_key][1][1] for player in players),
                start=Fraction(),
            )
            if total_attempted == 0:
                raise InvalidZScoreInputError(
                    f"category {contract.category_key!r} has zero attempts across the "
                    "entire reference population"
                )
            reference_percentage = float(total_made / total_attempted)
            for player in players:
                made = player.by_category[contract.category_key][0][1]
                attempted = player.by_category[contract.category_key][1][1]
                impact = _finite_float(
                    made - (total_made / total_attempted) * attempted,
                    player_id=player.player_id,
                    field=f"{contract.category_key}_volume_impact",
                )
                transformed[player.player_id][contract.category_key] = impact
                values.append(impact)
        else:
            for player in players:
                value = _finite_float(
                    player.by_category[contract.category_key][0][1],
                    player_id=player.player_id,
                    field=fields[0],
                )
                transformed[player.player_id][contract.category_key] = value
                values.append(value)
        mean, sd, status = _population_scale(values)
        scales.append(
            CategoryScale(
                category_key=contract.category_key,
                kind=contract.kind,
                direction=contract.direction,
                production_fields=fields,
                reference_mean=mean,
                population_sd=sd,
                reference_percentage=reference_percentage,
                status=status,
            )
        )
    return tuple(scales), transformed


def _component(
    *,
    player: _ValidatedPlayer,
    scale: CategoryScale,
    transformed_value: float,
) -> ZScoreCategoryComponent:
    if scale.status is ScaleStatus.ZERO_VARIANCE:
        z_score = 0.0
    else:
        z_score = scale.direction * (transformed_value - scale.reference_mean) / scale.population_sd
        if not math.isfinite(z_score):
            raise InvalidZScoreInputError(
                f"player {player.player_id} category {scale.category_key!r} "
                "produced a non-finite z-score"
            )
    return ZScoreCategoryComponent(
        category_key=scale.category_key,
        production_fields=player.by_category[scale.category_key],
        transformed_value=transformed_value,
        z_score=z_score,
    )


def _score_payload(score: PlayerProductionZScore) -> dict[str, object]:
    return {
        "player_id": score.player_id,
        "ordinal": score.ordinal,
        "components": [
            {
                "category_key": component.category_key,
                "fields": [
                    {
                        "field": field,
                        "value": f"{value.numerator}/{value.denominator}",
                    }
                    for field, value in component.production_fields
                ],
                "transformed_value": _canonical_float(component.transformed_value),
                "z_score": _canonical_float(component.z_score),
            }
            for component in score.category_components
        ],
        "total_z": _canonical_float(score.total_z),
        "value_above_replacement": (
            None
            if score.value_above_replacement is None
            else _canonical_float(score.value_above_replacement)
        ),
    }


@dataclass(frozen=True, slots=True)
class _InputContext:
    input_kind: str
    scoring_profile_id: int | None
    scoring_profile_sha256: str | None
    scoring_type: ScoringType
    blend_profile_id: str | None
    blend_profile_content_sha256: str | None
    blend_result_content_sha256: str | None
    benchmark_id: str | None
    benchmark_input_season: str | None
    benchmark_input_content_sha256: str | None


def _score_complete_cohort(
    *,
    league: League,
    contracts: tuple[tuple[ScoringCategoryContract, tuple[str, ...]], ...],
    players: tuple[_ValidatedPlayer, ...],
    context: _InputContext,
) -> ProductionZScoreResult:
    league_id = _positive_non_boolean_int(league.id, label="league.id")
    team_count = _positive_non_boolean_int(league.team_count, label="league.team_count")
    roster_size = _positive_non_boolean_int(league.roster_size, label="league.roster_size")
    structural_count = team_count * roster_size
    scales, transformed = _category_scales_and_values(players, contracts)
    unsorted_scores: list[tuple[int, tuple[ZScoreCategoryComponent, ...], float]] = []
    for player in players:
        components = tuple(
            _component(
                player=player,
                scale=scale,
                transformed_value=transformed[player.player_id][scale.category_key],
            )
            for scale in scales
        )
        try:
            total_z = math.fsum(component.z_score for component in components)
        except OverflowError as exc:  # pragma: no cover - guarded component values
            raise InvalidZScoreInputError(
                f"player {player.player_id} aggregate exceeds the finite scoring range"
            ) from exc
        if not math.isfinite(total_z):
            raise InvalidZScoreInputError(f"player {player.player_id} aggregate is non-finite")
        unsorted_scores.append((player.player_id, components, total_z))
    ordered = sorted(unsorted_scores, key=lambda item: (-item[2], item[0]))
    replacement_player_id: int | None = None
    replacement_total_z: float | None = None
    if len(ordered) > structural_count:
        replacement_player_id = ordered[structural_count][0]
        replacement_total_z = ordered[structural_count][2]
        replacement_state = ReplacementState.AVAILABLE
    else:
        replacement_state = ReplacementState.UNAVAILABLE_INSUFFICIENT_PROJECTED_POOL

    scores = tuple(
        PlayerProductionZScore(
            player_id=player_id,
            ordinal=ordinal,
            category_components=components,
            total_z=total_z,
            value_above_replacement=(
                None if replacement_total_z is None else total_z - replacement_total_z
            ),
        )
        for ordinal, (player_id, components, total_z) in enumerate(ordered, start=1)
    )
    replacement = ReplacementSummary(
        policy=REPLACEMENT_POLICY,
        state=replacement_state,
        required_ordinal=structural_count + 1,
        projected_count=len(players),
        structural_roster_count=structural_count,
        structural_roster_covered=len(players) >= structural_count,
        structural_roster_shortfall=max(structural_count - len(players), 0),
        replacement_ordinal_shortfall=max(structural_count + 1 - len(players), 0),
        replacement_player_id=replacement_player_id,
        replacement_total_z=replacement_total_z,
    )
    reference_ids = tuple(player.player_id for player in players)
    reference_fingerprint = _sha256(list(reference_ids))
    input_payload = {
        "input_kind": context.input_kind,
        "scoring_profile_id": context.scoring_profile_id,
        "scoring_profile_sha256": context.scoring_profile_sha256,
        "scoring_type": context.scoring_type.value,
        "blend_profile_id": context.blend_profile_id,
        "blend_profile_content_sha256": context.blend_profile_content_sha256,
        "blend_result_content_sha256": context.blend_result_content_sha256,
        "benchmark_id": context.benchmark_id,
        "benchmark_input_season": context.benchmark_input_season,
        "benchmark_input_content_sha256": context.benchmark_input_content_sha256,
    }
    base_payload: dict[str, object] = {
        "model_version": MODEL_VERSION,
        "value_scope": "production_only",
        "output_layer": DataLayer.TERMINAL.value,
        "availability_included": False,
        "aggregation_policy": AGGREGATION_POLICY,
        "input": input_payload,
        "league": {
            "league_id": league_id,
            "season": league.season,
            "team_count": team_count,
            "roster_size": roster_size,
            "structural_roster_count": structural_count,
        },
        "reference": {
            "policy": REFERENCE_POLICY,
            "count": len(reference_ids),
            "player_ids": list(reference_ids),
            "fingerprint": reference_fingerprint,
        },
        "category_scales": [
            {
                "category_key": scale.category_key,
                "kind": scale.kind.value,
                "direction": scale.direction,
                "production_fields": list(scale.production_fields),
                "reference_mean": _canonical_float(scale.reference_mean),
                "population_sd": _canonical_float(scale.population_sd),
                "reference_percentage": (
                    None
                    if scale.reference_percentage is None
                    else _canonical_float(scale.reference_percentage)
                ),
                "status": scale.status.value,
            }
            for scale in scales
        ],
        "replacement": {
            "policy": replacement.policy,
            "state": replacement.state.value,
            "required_ordinal": replacement.required_ordinal,
            "projected_count": replacement.projected_count,
            "structural_roster_count": replacement.structural_roster_count,
            "structural_roster_covered": replacement.structural_roster_covered,
            "structural_roster_shortfall": replacement.structural_roster_shortfall,
            "replacement_ordinal_shortfall": replacement.replacement_ordinal_shortfall,
            "replacement_player_id": replacement.replacement_player_id,
            "replacement_total_z": (
                None
                if replacement.replacement_total_z is None
                else _canonical_float(replacement.replacement_total_z)
            ),
        },
        "scores": [_score_payload(score) for score in scores],
    }
    return ProductionZScoreResult(
        model_version=MODEL_VERSION,
        value_scope="production_only",
        output_layer=DataLayer.TERMINAL,
        availability_included=False,
        aggregation_policy=AGGREGATION_POLICY,
        input_kind=context.input_kind,
        league_id=league_id,
        season=league.season,
        team_count=team_count,
        roster_size=roster_size,
        structural_roster_count=structural_count,
        scoring_profile_id=context.scoring_profile_id,
        scoring_profile_sha256=context.scoring_profile_sha256,
        scoring_type=context.scoring_type,
        blend_profile_id=context.blend_profile_id,
        blend_profile_content_sha256=context.blend_profile_content_sha256,
        blend_result_content_sha256=context.blend_result_content_sha256,
        benchmark_id=context.benchmark_id,
        benchmark_input_season=context.benchmark_input_season,
        benchmark_input_content_sha256=context.benchmark_input_content_sha256,
        reference_policy=REFERENCE_POLICY,
        reference_count=len(reference_ids),
        reference_player_ids=reference_ids,
        reference_player_fingerprint=reference_fingerprint,
        category_scales=scales,
        replacement=replacement,
        scores=scores,
        content_sha256=_sha256(base_payload),
    )


def score_production_zscores(
    *,
    league: League,
    blend_profile: BlendProfile,
    blend_result: BlendResult,
) -> ProductionZScoreResult:
    """Score every complete supplied player without reading any other source."""

    league_id = _positive_non_boolean_int(league.id, label="league.id")
    _positive_non_boolean_int(league.team_count, label="league.team_count")
    _positive_non_boolean_int(league.roster_size, label="league.roster_size")
    try:
        validate_blend_profile_integrity(blend_profile)
    except ProjectionBlendError as exc:
        raise InvalidZScoreInputError(str(exc)) from exc
    if blend_profile.league_id != league_id or blend_profile.season != league.season:
        raise InvalidZScoreInputError("blend profile belongs to another league or season")
    if blend_profile.scoring_type is not ScoringType.H2H_EACH_CATEGORY:
        raise InvalidZScoreInputError("zscore-production-v1 requires H2H each-category scoring")
    if blend_result.profile_id != blend_profile.profile_id:
        raise InvalidZScoreInputError("blend result names a different blend profile")
    if blend_result.profile_content_sha256 != blend_profile.content_sha256:
        raise InvalidZScoreInputError("blend result carries a stale blend-profile hash")
    _validate_result_hash(blend_result)

    contracts = _validate_contracts(blend_profile.category_contracts)
    players = _validated_players(blend_result.projections, contracts)
    return _score_complete_cohort(
        league=league,
        contracts=contracts,
        players=players,
        context=_InputContext(
            input_kind="production_blend",
            scoring_profile_id=blend_profile.scoring_profile_id,
            scoring_profile_sha256=blend_profile.scoring_profile_sha256,
            scoring_type=blend_profile.scoring_type,
            blend_profile_id=blend_profile.profile_id,
            blend_profile_content_sha256=blend_profile.content_sha256,
            blend_result_content_sha256=blend_result.content_sha256,
            benchmark_id=None,
            benchmark_input_season=None,
            benchmark_input_content_sha256=None,
        ),
    )


def score_historical_production_benchmark(
    *,
    league: League,
    benchmark: HistoricalProductionBenchmark,
) -> ProductionZScoreResult:
    """Score an explicitly labelled retrospective benchmark without fake releases."""

    if not benchmark.benchmark_id.strip():
        raise InvalidZScoreInputError("historical benchmark requires a non-empty identity")
    if not benchmark.input_season or not benchmark.target_season:
        raise InvalidZScoreInputError("historical benchmark seasons must be non-empty")
    if benchmark.target_season != league.season:
        raise InvalidZScoreInputError("historical benchmark target season differs from league")
    if not benchmark.input_content_sha256.strip():
        raise InvalidZScoreInputError("historical benchmark input identity is absent")
    contracts = _validate_contracts(benchmark.category_contracts)
    players = _validated_players(benchmark.projections, contracts)
    return _score_complete_cohort(
        league=league,
        contracts=contracts,
        players=players,
        context=_InputContext(
            input_kind="retrospective_historical_benchmark",
            scoring_profile_id=None,
            scoring_profile_sha256=_sha256(
                [
                    {
                        "category_key": contract.category_key,
                        "kind": contract.kind.value,
                        "direction": contract.direction,
                        "production_fields": list(contract.production_fields),
                    }
                    for contract, _fields in contracts
                ]
            ),
            scoring_type=ScoringType.H2H_EACH_CATEGORY,
            blend_profile_id=None,
            blend_profile_content_sha256=None,
            blend_result_content_sha256=None,
            benchmark_id=benchmark.benchmark_id,
            benchmark_input_season=benchmark.input_season,
            benchmark_input_content_sha256=benchmark.input_content_sha256,
        ),
    )


def _canonical_float(value: float) -> str:
    if not math.isfinite(value):
        raise InvalidZScoreInputError("z-score output became non-finite")
    return format(value, ".17g")


def _sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
