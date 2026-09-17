"""Released development analysis for the production-only z-score engine.

This module accepts four explicitly named files. It never discovers a package,
opens a source database, fetches a source, or reads a directory. The authorized
development transition is a retrospective rolling-origin carry-forward:
2022-23 observed per-game production is carried unchanged into 2023-24 and
evaluated against retrospectively assembled 2023-24 box scores.

This is not a vendor forecast, an archived as-of forecast, a production baseline
model, or a held-out final evaluation.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

from hoops_gm.db.models.enums import CategoryKind
from hoops_gm.db.models.league import League
from hoops_gm.projections.blending import (
    BlendedCategoryValue,
    BlendedProjection,
    ScoringCategoryContract,
)
from hoops_gm.valuation.zscore import (
    CategoryScale,
    HistoricalProductionBenchmark,
    ScaleStatus,
    score_historical_production_benchmark,
)

EXPERIMENT_ID: Final = "zscore-production-carryforward-v1-exp-20260911T201744001625Z"
PACKAGE_ID: Final = "20260911T201744001625Z-b18c64c12a89226a"
PACKAGE_CONTENT_SHA256: Final = "b18c64c12a89226ab98f8dd84cf3a73b7baa0c247025ec487b988246b0b6f713"
RELEASE_ID: Final = "20260911T203052301107Z-b40e39805c39597f"
RELEASE_CONTENT_SHA256: Final = "b40e39805c39597f28813a5920dfc3e56eb2c77d94ddd337535ccc4cee12ed55"
RELEASE_FILE_SHA256: Final = "c6c5d3632f4ee321619307582c59153526789dd3c597fb320cb3e5ff29a7b633"
MANIFEST_SHA256: Final = "5d2b33f82da0d5150f5455f314ad48fd32ec82f0b57b62a89f2c1baf8a02526b"
FORECAST_SHA256: Final = "36f07a4ea09ae1f49443fbfff431ef6605beb2c4cced5391b8d7828322c58057"
OUTCOME_SHA256: Final = "70716b61cb95802b7552d08cfce87a2c75794cd1fb0e549f139cec7f9a01ba3c"

FORECAST_SEASON: Final = "2022-23"
OUTCOME_SEASON: Final = "2023-24"
TEAM_COUNT: Final = 12
ROSTER_SIZE: Final = 13
BOOTSTRAP_RESAMPLES: Final = 2000
BOOTSTRAP_SEED: Final = 20260911
SUPPORT_SENSITIVITIES: Final = (10, 25, 50)
QUINTILE_PROBABILITIES: Final = (0.2, 0.4, 0.6, 0.8)

CSV_FIELDS: Final = (
    "canonical_player_id",
    "nba_game_id",
    "game_date",
    "season",
    "season_type",
    "seconds_played",
    "field_goals_made",
    "field_goals_attempted",
    "free_throws_made",
    "free_throws_attempted",
    "three_pointers_made",
    "points",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
)

_STAT_FIELDS: Final = (
    "field_goals_made",
    "field_goals_attempted",
    "free_throws_made",
    "free_throws_attempted",
    "three_pointers_made",
    "points",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
)

_CONTRACTS: Final = (
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


class DevelopmentEvidenceError(ValueError):
    """The released development package or its accounting is invalid."""


@dataclass(frozen=True, slots=True)
class SeasonRates:
    player_id: int
    games: int
    seconds_played: int
    field_goals_made_per_game: Fraction
    field_goals_attempted_per_game: Fraction
    free_throws_made_per_game: Fraction
    free_throws_attempted_per_game: Fraction
    three_pointers_made_per_game: Fraction
    points_per_game: Fraction
    rebounds_per_game: Fraction
    assists_per_game: Fraction
    steals_per_game: Fraction
    blocks_per_game: Fraction
    turnovers_per_game: Fraction


@dataclass(frozen=True, slots=True)
class LoadedSeason:
    season: str
    source_rows: int
    zero_second_rows: int
    player_rates: tuple[SeasonRates, ...]


@dataclass(frozen=True, slots=True)
class LinearCalibration:
    status: str
    count: int
    intercept: float | None
    slope: float | None
    intercept_bootstrap_95: tuple[float, float] | None
    slope_bootstrap_95: tuple[float, float] | None
    bootstrap_usable_resamples: int
    anchor_predicted_plus_one: float | None
    anchor_predicted_plus_two: float | None


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _require_file(path: Path, *, expected_sha256: str, label: str) -> None:
    if not path.is_file():
        raise DevelopmentEvidenceError(f"{label} file is absent")
    actual = _file_sha256(path)
    if actual != expected_sha256:
        raise DevelopmentEvidenceError(
            f"{label} SHA-256 mismatch: expected {expected_sha256}, got {actual}"
        )


def _verify_manifest(path: Path) -> dict[str, Any]:
    _require_file(path, expected_sha256=MANIFEST_SHA256, label="manifest")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DevelopmentEvidenceError("manifest must be an object")
    if payload.get("package_id") != PACKAGE_ID:
        raise DevelopmentEvidenceError("manifest package identity mismatch")
    if payload.get("content_sha256") != PACKAGE_CONTENT_SHA256:
        raise DevelopmentEvidenceError("manifest content identity mismatch")
    if payload.get("dataset_class") != "development":
        raise DevelopmentEvidenceError("only the released development package is eligible")
    if payload.get("fields_released") != list(CSV_FIELDS):
        raise DevelopmentEvidenceError("manifest released-field contract mismatch")
    payloads = payload.get("payloads")
    if payloads != [
        {
            "bytes": 1_826_667,
            "filename": "player_game_logs_2022-23.csv",
            "sha256": FORECAST_SHA256,
        },
        {
            "bytes": 1_861_184,
            "filename": "player_game_logs_2023-24.csv",
            "sha256": OUTCOME_SHA256,
        },
    ]:
        raise DevelopmentEvidenceError("manifest payload accounting mismatch")
    return payload


def _verify_release(path: Path) -> dict[str, Any]:
    _require_file(path, expected_sha256=RELEASE_FILE_SHA256, label="release")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DevelopmentEvidenceError("release must be an object")
    if payload.get("release_id") != RELEASE_ID:
        raise DevelopmentEvidenceError("release identity mismatch")
    if payload.get("content_sha256") != RELEASE_CONTENT_SHA256:
        raise DevelopmentEvidenceError("release content identity mismatch")
    if payload.get("experiment_id") != EXPERIMENT_ID:
        raise DevelopmentEvidenceError("release experiment identity mismatch")
    if payload.get("disposition") != "approved_development_only_pending_parent_delivery":
        raise DevelopmentEvidenceError("release does not authorize this development analysis")
    package = payload.get("package")
    if not isinstance(package, dict):
        raise DevelopmentEvidenceError("release package identity is absent")
    if package.get("package_id") != PACKAGE_ID:
        raise DevelopmentEvidenceError("release package ID mismatch")
    if package.get("content_sha256") != PACKAGE_CONTENT_SHA256:
        raise DevelopmentEvidenceError("release package content mismatch")
    if package.get("manifest_sha256") != MANIFEST_SHA256:
        raise DevelopmentEvidenceError("release manifest identity mismatch")
    return payload


def _required_text(raw: str | None, *, field: str, row_number: int) -> str:
    if raw is None or raw == "":
        raise DevelopmentEvidenceError(f"row {row_number} has missing {field}")
    return raw


def _parse_nonnegative_int(raw: str | None, *, field: str, row_number: int) -> int:
    text = _required_text(raw, field=field, row_number=row_number)
    try:
        value = int(text)
    except ValueError as exc:
        raise DevelopmentEvidenceError(f"row {row_number} has non-integer {field}") from exc
    if value < 0:
        raise DevelopmentEvidenceError(f"row {row_number} has negative {field}")
    return value


def _load_season(path: Path, *, season: str, expected_sha256: str) -> LoadedSeason:
    _require_file(path, expected_sha256=expected_sha256, label=f"{season} payload")
    totals: dict[int, dict[str, int]] = {}
    seen_player_games: set[tuple[int, str]] = set()
    source_rows = 0
    zero_second_rows = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CSV_FIELDS:
            raise DevelopmentEvidenceError(
                f"{season} payload header mismatch: got {reader.fieldnames}"
            )
        for row_number, row in enumerate(reader, start=2):
            source_rows += 1
            row_season = _required_text(
                row["season"],
                field="season",
                row_number=row_number,
            )
            if row_season != season:
                raise DevelopmentEvidenceError(
                    f"row {row_number} season {row_season!r} is not {season!r}"
                )
            season_type = _required_text(
                row["season_type"],
                field="season_type",
                row_number=row_number,
            )
            if season_type not in {"regular", "Regular Season"}:
                raise DevelopmentEvidenceError(
                    f"row {row_number} has non-regular season_type {season_type!r}"
                )
            game_date = _required_text(
                row["game_date"],
                field="game_date",
                row_number=row_number,
            )
            try:
                date.fromisoformat(game_date)
            except ValueError as exc:
                raise DevelopmentEvidenceError(
                    f"row {row_number} has invalid ISO game_date {game_date!r}"
                ) from exc
            player_id = _parse_nonnegative_int(
                row["canonical_player_id"],
                field="canonical_player_id",
                row_number=row_number,
            )
            if player_id == 0:
                raise DevelopmentEvidenceError(f"row {row_number} has zero player identity")
            game_id = _required_text(
                row["nba_game_id"],
                field="nba_game_id",
                row_number=row_number,
            )
            identity = (player_id, game_id)
            if identity in seen_player_games:
                raise DevelopmentEvidenceError(f"row {row_number} repeats player-game {identity}")
            seen_player_games.add(identity)
            parsed = {
                field: _parse_nonnegative_int(
                    row[field],
                    field=field,
                    row_number=row_number,
                )
                for field in ("seconds_played", *_STAT_FIELDS)
            }
            if parsed["seconds_played"] == 0:
                zero_second_rows += 1
            if parsed["field_goals_made"] > parsed["field_goals_attempted"]:
                raise DevelopmentEvidenceError(
                    f"row {row_number} has field goals made greater than attempted"
                )
            if parsed["free_throws_made"] > parsed["free_throws_attempted"]:
                raise DevelopmentEvidenceError(
                    f"row {row_number} has free throws made greater than attempted"
                )
            bucket = totals.setdefault(
                player_id,
                {"games": 0, "seconds_played": 0, **dict.fromkeys(_STAT_FIELDS, 0)},
            )
            bucket["games"] += 1
            for field, value in parsed.items():
                bucket[field] += value
    if not totals:
        raise DevelopmentEvidenceError(f"{season} payload has no credited appearances")
    return LoadedSeason(
        season=season,
        source_rows=source_rows,
        zero_second_rows=zero_second_rows,
        player_rates=tuple(
            SeasonRates(
                player_id=player_id,
                games=bucket["games"],
                seconds_played=bucket["seconds_played"],
                field_goals_made_per_game=Fraction(bucket["field_goals_made"], bucket["games"]),
                field_goals_attempted_per_game=Fraction(
                    bucket["field_goals_attempted"], bucket["games"]
                ),
                free_throws_made_per_game=Fraction(bucket["free_throws_made"], bucket["games"]),
                free_throws_attempted_per_game=Fraction(
                    bucket["free_throws_attempted"], bucket["games"]
                ),
                three_pointers_made_per_game=Fraction(
                    bucket["three_pointers_made"], bucket["games"]
                ),
                points_per_game=Fraction(bucket["points"], bucket["games"]),
                rebounds_per_game=Fraction(bucket["rebounds"], bucket["games"]),
                assists_per_game=Fraction(bucket["assists"], bucket["games"]),
                steals_per_game=Fraction(bucket["steals"], bucket["games"]),
                blocks_per_game=Fraction(bucket["blocks"], bucket["games"]),
                turnovers_per_game=Fraction(bucket["turnovers"], bucket["games"]),
            )
            for player_id, bucket in sorted(totals.items())
        ),
    )


def _category_payload(value: BlendedCategoryValue) -> dict[str, object]:
    return {
        "category_key": value.category_key,
        "values": [
            {"field": field, "value": f"{number.numerator}/{number.denominator}"}
            for field, number in value.values
        ],
        "manual_override_id": value.manual_override_id,
    }


def _projection_from_rates(rates: SeasonRates) -> BlendedProjection:
    values: dict[str, tuple[tuple[str, Fraction], ...]] = {
        "pts": (("points_per_game", rates.points_per_game),),
        "reb": (("rebounds_per_game", rates.rebounds_per_game),),
        "ast": (("assists_per_game", rates.assists_per_game),),
        "stl": (("steals_per_game", rates.steals_per_game),),
        "blk": (("blocks_per_game", rates.blocks_per_game),),
        "fg3m": (("three_pointers_made_per_game", rates.three_pointers_made_per_game),),
        "to": (("turnovers_per_game", rates.turnovers_per_game),),
        "fg_pct": (
            ("field_goals_made_per_game", rates.field_goals_made_per_game),
            ("field_goals_attempted_per_game", rates.field_goals_attempted_per_game),
        ),
        "ft_pct": (
            ("free_throws_made_per_game", rates.free_throws_made_per_game),
            ("free_throws_attempted_per_game", rates.free_throws_attempted_per_game),
        ),
    }
    categories = tuple(
        BlendedCategoryValue(
            category_key=contract.category_key,
            values=values[contract.category_key],
            manual_override_id=None,
        )
        for contract in _CONTRACTS
    )
    return BlendedProjection(
        player_id=rates.player_id,
        categories=categories,
        content_sha256=_canonical_sha256(
            {
                "player_id": rates.player_id,
                "categories": [_category_payload(category) for category in categories],
            }
        ),
    )


def _historical_benchmark_inputs(
    forecast_rates: tuple[SeasonRates, ...],
    *,
    forecast_season: str,
    target_season: str,
    forecast_payload_sha256: str,
    method_label: str,
    profile_id_suffix: str,
    profile_name: str,
) -> tuple[League, HistoricalProductionBenchmark]:
    projections = tuple(_projection_from_rates(rates) for rates in forecast_rates)
    benchmark_hash = _canonical_sha256(
        {
            "experiment_id": EXPERIMENT_ID,
            "label": method_label,
            "forecast_season": forecast_season,
            "target_season": target_season,
            "forecast_payload_sha256": forecast_payload_sha256,
            "contracts": [
                {
                    "key": contract.category_key,
                    "kind": contract.kind.value,
                    "direction": contract.direction,
                    "fields": list(contract.production_fields),
                }
                for contract in _CONTRACTS
            ],
        }
    )
    benchmark = HistoricalProductionBenchmark(
        benchmark_id=(f"{EXPERIMENT_ID}:{profile_id_suffix}:{profile_name}:{benchmark_hash[:12]}"),
        input_season=forecast_season,
        target_season=target_season,
        input_content_sha256=forecast_payload_sha256,
        category_contracts=_CONTRACTS,
        projections=projections,
    )
    league = League(
        id=1,
        name="Historical benchmark structure",
        season=target_season,
        team_count=TEAM_COUNT,
        roster_size=ROSTER_SIZE,
    )
    return league, benchmark


def _outcome_component(rates: SeasonRates, scale: CategoryScale) -> float:
    if scale.category_key == "pts":
        transformed = float(rates.points_per_game)
    elif scale.category_key == "reb":
        transformed = float(rates.rebounds_per_game)
    elif scale.category_key == "ast":
        transformed = float(rates.assists_per_game)
    elif scale.category_key == "stl":
        transformed = float(rates.steals_per_game)
    elif scale.category_key == "blk":
        transformed = float(rates.blocks_per_game)
    elif scale.category_key == "fg3m":
        transformed = float(rates.three_pointers_made_per_game)
    elif scale.category_key == "to":
        transformed = float(rates.turnovers_per_game)
    elif scale.category_key == "fg_pct":
        if scale.reference_percentage is None:
            raise DevelopmentEvidenceError("FG scale lacks its frozen reference percentage")
        transformed = float(rates.field_goals_made_per_game) - (
            scale.reference_percentage * float(rates.field_goals_attempted_per_game)
        )
    elif scale.category_key == "ft_pct":
        if scale.reference_percentage is None:
            raise DevelopmentEvidenceError("FT scale lacks its frozen reference percentage")
        transformed = float(rates.free_throws_made_per_game) - (
            scale.reference_percentage * float(rates.free_throws_attempted_per_game)
        )
    else:  # pragma: no cover - contracts are closed above
        raise DevelopmentEvidenceError(f"unsupported category {scale.category_key}")
    if scale.status is ScaleStatus.ZERO_VARIANCE:
        return 0.0
    return scale.direction * (transformed - scale.reference_mean) / scale.population_sd


def _linear_calibration(
    predicted: Sequence[float],
    observed: Sequence[float],
) -> tuple[float, float] | None:
    if len(predicted) < 2 or len(predicted) != len(observed):
        return None
    x_mean = math.fsum(predicted) / len(predicted)
    y_mean = math.fsum(observed) / len(observed)
    denominator = math.fsum((value - x_mean) ** 2 for value in predicted)
    if denominator == 0:
        return None
    slope = (
        math.fsum((x - x_mean) * (y - y_mean) for x, y in zip(predicted, observed, strict=True))
        / denominator
    )
    return y_mean - slope * x_mean, slope


def _type7_quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise DevelopmentEvidenceError("a quantile requires at least one value")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _bootstrap_interval(
    predicted: Sequence[float],
    observed: Sequence[float],
    *,
    metric_key: str,
) -> tuple[tuple[float, float], tuple[float, float], int] | None:
    if _linear_calibration(predicted, observed) is None:
        return None
    seed = int.from_bytes(
        hashlib.sha256(f"{BOOTSTRAP_SEED}:{metric_key}".encode()).digest()[:8],
        "big",
    )
    rng = random.Random(seed)
    intercepts: list[float] = []
    slopes: list[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        indices = [rng.randrange(len(predicted)) for _item in predicted]
        fitted = _linear_calibration(
            [predicted[index] for index in indices],
            [observed[index] for index in indices],
        )
        if fitted is None:
            continue
        intercept, slope = fitted
        intercepts.append(intercept)
        slopes.append(slope)
    if not intercepts:
        return None
    return (
        (_type7_quantile(intercepts, 0.025), _type7_quantile(intercepts, 0.975)),
        (_type7_quantile(slopes, 0.025), _type7_quantile(slopes, 0.975)),
        len(intercepts),
    )


def _calibration(
    predicted: Sequence[float],
    observed: Sequence[float],
    *,
    metric_key: str,
) -> LinearCalibration:
    fitted = _linear_calibration(predicted, observed)
    if fitted is None:
        return LinearCalibration(
            status="not_evaluable_too_few_pairs_or_zero_predictor_variance",
            count=len(predicted),
            intercept=None,
            slope=None,
            intercept_bootstrap_95=None,
            slope_bootstrap_95=None,
            bootstrap_usable_resamples=0,
            anchor_predicted_plus_one=None,
            anchor_predicted_plus_two=None,
        )
    intercept, slope = fitted
    intervals = _bootstrap_interval(predicted, observed, metric_key=metric_key)
    return LinearCalibration(
        status="evaluated",
        count=len(predicted),
        intercept=intercept,
        slope=slope,
        intercept_bootstrap_95=None if intervals is None else intervals[0],
        slope_bootstrap_95=None if intervals is None else intervals[1],
        bootstrap_usable_resamples=0 if intervals is None else intervals[2],
        anchor_predicted_plus_one=intercept + slope,
        anchor_predicted_plus_two=intercept + 2 * slope,
    )


def _average_ranks(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        average = ((start + 1) + end) / 2
        for index, _value in indexed[start:end]:
            ranks[index] = average
        start = end
    return ranks


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = math.fsum(left) / len(left)
    right_mean = math.fsum(right) / len(right)
    left_ss = math.fsum((value - left_mean) ** 2 for value in left)
    right_ss = math.fsum((value - right_mean) ** 2 for value in right)
    if left_ss == 0 or right_ss == 0:
        return None
    covariance = math.fsum(
        (x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True)
    )
    return covariance / math.sqrt(left_ss * right_ss)


def _secondary_metrics(
    predicted: Sequence[float],
    observed: Sequence[float],
) -> dict[str, float | None]:
    if not predicted:
        return {"mae": None, "rmse": None, "spearman": None}
    errors = [actual - forecast for forecast, actual in zip(predicted, observed, strict=True)]
    return {
        "mae": math.fsum(abs(error) for error in errors) / len(errors),
        "rmse": math.sqrt(math.fsum(error * error for error in errors) / len(errors)),
        "spearman": _pearson(_average_ranks(predicted), _average_ranks(observed)),
    }


def _collapsed_quintile_cuts(predictions: Sequence[float]) -> tuple[float, ...]:
    cuts: list[float] = []
    for probability in QUINTILE_PROBABILITIES:
        value = _type7_quantile(predictions, probability)
        if not cuts or value != cuts[-1]:
            cuts.append(value)
    return tuple(cuts)


def _bin_report(
    *,
    forecast_predictions: dict[int, float],
    paired_observations: dict[int, float],
) -> dict[str, object]:
    cuts = _collapsed_quintile_cuts(tuple(forecast_predictions.values()))
    assignments = {
        player_id: bisect.bisect_right(cuts, predicted)
        for player_id, predicted in forecast_predictions.items()
    }
    rows: list[dict[str, object]] = []
    for bin_index in range(len(cuts) + 1):
        forecast_ids = sorted(
            player_id for player_id, assigned in assignments.items() if assigned == bin_index
        )
        paired_ids = [player_id for player_id in forecast_ids if player_id in paired_observations]
        predicted_values = [forecast_predictions[player_id] for player_id in paired_ids]
        observed_values = [paired_observations[player_id] for player_id in paired_ids]
        rows.append(
            {
                "bin_index": bin_index,
                "lower_inclusive": None if bin_index == 0 else cuts[bin_index - 1],
                "upper_exclusive": (None if bin_index == len(cuts) else cuts[bin_index]),
                "assignment_rule": "bisect_right; values equal to a cut enter the upper bin",
                "forecast_count": len(forecast_ids),
                "paired_count": len(paired_ids),
                "missing_outcome_count": len(forecast_ids) - len(paired_ids),
                "mean_predicted": (
                    None
                    if not predicted_values
                    else math.fsum(predicted_values) / len(predicted_values)
                ),
                "mean_observed_frozen_scale": (
                    None
                    if not observed_values
                    else math.fsum(observed_values) / len(observed_values)
                ),
            }
        )
    return {
        "method": "prediction_only_type7_quintiles",
        "probabilities": list(QUINTILE_PROBABILITIES),
        "duplicate_cut_policy": "collapse exact adjacent duplicate cuts deterministically",
        "cuts": list(cuts),
        "assignment_sha256": _canonical_sha256(
            [
                {"player_id": player_id, "bin": assignments[player_id]}
                for player_id in sorted(assignments)
            ]
        ),
        "bins": rows,
    }


def _metric_report(
    *,
    metric_key: str,
    forecast_predictions: dict[int, float],
    paired_observations: dict[int, float],
) -> dict[str, object]:
    paired_ids = sorted(paired_observations)
    predicted = [forecast_predictions[player_id] for player_id in paired_ids]
    observed = [paired_observations[player_id] for player_id in paired_ids]
    return {
        "calibration": asdict(_calibration(predicted, observed, metric_key=metric_key)),
        "secondary": _secondary_metrics(predicted, observed),
        "prediction_bins": _bin_report(
            forecast_predictions=forecast_predictions,
            paired_observations=paired_observations,
        ),
    }


def _canonical_evidence(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def run_development_analysis(
    *,
    manifest_path: Path,
    forecast_csv_path: Path,
    outcome_csv_path: Path,
    release_path: Path,
) -> dict[str, object]:
    manifest = _verify_manifest(manifest_path)
    release = _verify_release(release_path)
    forecast_loaded = _load_season(
        forecast_csv_path,
        season=FORECAST_SEASON,
        expected_sha256=FORECAST_SHA256,
    )
    outcome_loaded = _load_season(
        outcome_csv_path,
        season=OUTCOME_SEASON,
        expected_sha256=OUTCOME_SHA256,
    )
    forecast_rates = forecast_loaded.player_rates
    outcome_rates = outcome_loaded.player_rates
    league, benchmark = _historical_benchmark_inputs(
        forecast_rates,
        forecast_season=FORECAST_SEASON,
        target_season=OUTCOME_SEASON,
        forecast_payload_sha256=FORECAST_SHA256,
        method_label="retrospective_rolling_origin_carryforward_development",
        profile_id_suffix="development-carryforward",
        profile_name="retrospective-carryforward-development",
    )
    scored = score_historical_production_benchmark(
        league=league,
        benchmark=benchmark,
    )
    forecasts = {score.player_id: score for score in scored.scores}
    outcomes = {rates.player_id: rates for rates in outcome_rates}
    paired_ids = sorted(set(forecasts) & set(outcomes))
    missing_ids = sorted(set(forecasts) - set(outcomes))
    outcome_only_ids = sorted(set(outcomes) - set(forecasts))

    predicted_by_metric: dict[str, dict[int, float]] = {
        scale.category_key: {} for scale in scored.category_scales
    }
    predicted_by_metric["aggregate_total"] = {}
    observed_by_metric: dict[str, dict[int, float]] = {
        scale.category_key: {} for scale in scored.category_scales
    }
    observed_by_metric["aggregate_total"] = {}

    for player_id, score in forecasts.items():
        for component in score.category_components:
            predicted_by_metric[component.category_key][player_id] = component.z_score
        predicted_by_metric["aggregate_total"][player_id] = score.total_z
    for player_id in paired_ids:
        rates = outcomes[player_id]
        observed_components = {
            scale.category_key: _outcome_component(rates, scale) for scale in scored.category_scales
        }
        for category_key, value in observed_components.items():
            observed_by_metric[category_key][player_id] = value
        observed_by_metric["aggregate_total"][player_id] = math.fsum(observed_components.values())

    metric_reports = {
        metric_key: _metric_report(
            metric_key=metric_key,
            forecast_predictions=predicted_by_metric[metric_key],
            paired_observations=observed_by_metric[metric_key],
        )
        for metric_key in (
            *[scale.category_key for scale in scored.category_scales],
            "aggregate_total",
        )
    }
    support_reports: dict[str, dict[str, object]] = {}
    for minimum_games in SUPPORT_SENSITIVITIES:
        supported = [
            player_id for player_id in paired_ids if outcomes[player_id].games >= minimum_games
        ]
        supported_predicted = [
            predicted_by_metric["aggregate_total"][player_id] for player_id in supported
        ]
        supported_observed = [
            observed_by_metric["aggregate_total"][player_id] for player_id in supported
        ]
        support_reports[str(minimum_games)] = {
            "minimum_observed_games": minimum_games,
            "paired_players": len(supported),
            "aggregate_total": {
                "calibration": asdict(
                    _calibration(
                        supported_predicted,
                        supported_observed,
                        metric_key=f"aggregate_total_games_{minimum_games}",
                    )
                ),
                "secondary": _secondary_metrics(
                    supported_predicted,
                    supported_observed,
                ),
            },
        }

    evidence: dict[str, object] = {
        "experiment_id": EXPERIMENT_ID,
        "status": "development_only_not_final_model_gate",
        "label": (
            "retrospective rolling-origin carry-forward benchmark using retrospectively "
            "assembled box-score data"
        ),
        "scope_limit": (
            "Evaluates 2022-23 observed per-game rates carried into 2023-24. It is not "
            "an archived as-of or vendor forecast and does not establish calibration of "
            "the current projection blend."
        ),
        "release": {
            "release_id": RELEASE_ID,
            "release_content_sha256": RELEASE_CONTENT_SHA256,
            "release_file_sha256": RELEASE_FILE_SHA256,
            "package_id": PACKAGE_ID,
            "package_content_sha256": PACKAGE_CONTENT_SHA256,
            "manifest_sha256": MANIFEST_SHA256,
            "forecast_payload_sha256": FORECAST_SHA256,
            "outcome_payload_sha256": OUTCOME_SHA256,
            "manifest_purpose": manifest["purpose"],
            "release_disposition": release["disposition"],
            "prior_access_deviation_retained": True,
        },
        "protocol": {
            "forecast_season": FORECAST_SEASON,
            "outcome_season": OUTCOME_SEASON,
            "forecast_method": "prior-season per-game rates carried unchanged",
            "reference_policy": scored.reference_policy,
            "standard_deviation": "population_ddof_0",
            "outcome_scale": (
                "forecast means, SDs, and ratio reference percentages frozen unchanged"
            ),
            "eligibility": "at least one complete credited forecast-season source row",
            "outcome_pairing": "at least one complete credited outcome-season source row",
            "zero_second_policy": "credited zero-second rows count in per-game denominators",
            "minimum_game_filter": None,
            "missing_outcome_policy": (
                "missing, never zero; forecast reference cohort remains unchanged"
            ),
            "bootstrap_unit": "unweighted player",
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_interval": [0.025, 0.975],
            "linear_calibration_reference": {"intercept": 0.0, "slope": 1.0},
            "linear_calibration_thresholds": None,
            "anchor_rule": "fitted intercept+slope*x evaluated at x=1 and x=2",
            "prediction_bin_method": "prediction-only Type-7 quintiles",
            "prediction_bin_probabilities": list(QUINTILE_PROBABILITIES),
            "duplicate_cut_policy": "collapse exact adjacent duplicates",
            "bin_assignment_rule": "bisect_right; equality enters upper bin",
            "support_sensitivities_observed_games": list(SUPPORT_SENSITIVITIES),
            "primary_population": "all paired players with at least one credited game",
            "secondary_metrics": ["mae", "rmse", "spearman"],
            "activation_vetoes": None,
        },
        "denominators": {
            "forecast_source_rows": forecast_loaded.source_rows,
            "outcome_source_rows": outcome_loaded.source_rows,
            "forecast_players": len(forecast_rates),
            "outcome_players": len(outcome_rates),
            "paired_players": len(paired_ids),
            "missing_outcome_players": len(missing_ids),
            "outcome_only_players": len(outcome_only_ids),
            "incomplete_forecast_rows": 0,
            "incomplete_outcome_rows": 0,
            "identity_failure_rows": 0,
            "forecast_zero_second_rows": forecast_loaded.zero_second_rows,
            "outcome_zero_second_rows": outcome_loaded.zero_second_rows,
        },
        "runtime_result": {
            "model_version": scored.model_version,
            "content_sha256": scored.content_sha256,
            "reference_count": scored.reference_count,
            "reference_fingerprint": scored.reference_player_fingerprint,
            "structural_roster_count": scored.structural_roster_count,
            "replacement_state": scored.replacement.state.value,
            "replacement_required_ordinal": scored.replacement.required_ordinal,
            "replacement_player_id_retained_in_runtime_only": (
                scored.replacement.replacement_player_id is not None
            ),
        },
        "frozen_forecast_scales": [
            {
                "category_key": scale.category_key,
                "kind": scale.kind.value,
                "direction": scale.direction,
                "reference_mean": scale.reference_mean,
                "population_sd": scale.population_sd,
                "reference_percentage": scale.reference_percentage,
                "status": scale.status.value,
            }
            for scale in scored.category_scales
        ],
        "metrics": metric_reports,
        "support_sensitivities": support_reports,
        "interpretation": {
            "intercept_zero_and_slope_one_are_references_not_thresholds": True,
            "non_detection_is_not_equivalence": True,
            "poor_results_are_reported_not_tuned_away": True,
            "no_final_2024_25_outcome_access": True,
            "no_2025_26_payload_or_computation": True,
            "model_gate_passed": False,
        },
    }
    evidence["content_sha256"] = _canonical_sha256(evidence)
    return evidence


def run_final_heldout_evaluation(
    *,
    sealed_forecast_path: Path,
    accepted_freeze_path: Path,
    freeze_confirmation_path: Path,
    outcome_release_path: Path,
    outcome_manifest_path: Path,
    forecast_key_manifest_path: Path,
    outcome_csv_path: Path,
    current_candidate_files: dict[str, Path],
) -> dict[str, object]:
    """Dispatch the separately permissioned final entry point.

    The import is intentionally lazy: development analysis cannot accidentally
    touch a final-outcome path merely by importing this module.
    """

    from hoops_gm.valuation.zscore_final_evaluation import (
        run_final_heldout_evaluation as run_frozen_final_evaluation,
    )

    return run_frozen_final_evaluation(
        sealed_forecast_path=sealed_forecast_path,
        accepted_freeze_path=accepted_freeze_path,
        freeze_confirmation_path=freeze_confirmation_path,
        outcome_release_path=outcome_release_path,
        outcome_manifest_path=outcome_manifest_path,
        forecast_key_manifest_path=forecast_key_manifest_path,
        outcome_csv_path=outcome_csv_path,
        current_candidate_files=current_candidate_files,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--forecast-csv", type=Path, required=True)
    parser.add_argument("--outcome-csv", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evidence = run_development_analysis(
        manifest_path=args.manifest,
        forecast_csv_path=args.forecast_csv,
        outcome_csv_path=args.outcome_csv,
        release_path=args.release,
    )
    args.output.write_bytes(_canonical_evidence(evidence))
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "content_sha256": evidence["content_sha256"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
