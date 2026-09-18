"""Construct the input-only 2024-25 z-score forecast prefreeze artifact.

The only row-bearing input is the independently released, purpose-correct
2023-24 appearance-production CSV. This module has no outcome input, source
database access, directory discovery, availability input, or 2024-25 presence
information.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from hoops_gm.valuation.zscore import score_historical_production_benchmark
from hoops_gm.valuation.zscore_backtest import (
    CSV_FIELDS,
    EXPERIMENT_ID,
    OUTCOME_SHA256,
    _canonical_evidence,
    _canonical_sha256,
    _collapsed_quintile_cuts,
    _file_sha256,
    _historical_benchmark_inputs,
    _load_season,
    _require_file,
)

INPUT_PACKAGE_ID: Final = "20260911T204202792405Z-0fb3dfda4396893f"
INPUT_PACKAGE_CONTENT_SHA256: Final = (
    "0fb3dfda4396893f38d1a6e49a2f2836efa3098ffe4b325ac6937d8bc787ebe3"
)
INPUT_MANIFEST_SHA256: Final = "2612cfb3005a3aa95a50e810824a0500d38919f0be1b8114b37fcbd03bdaf447"
INPUT_RELEASE_ID: Final = "20260911T204417608035Z-8ce7cb77fb4186ef"
INPUT_RELEASE_CONTENT_SHA256: Final = (
    "8ce7cb77fb4186efaf54181e71225f7cf537ea957b6f35f493530077c35b14b7"
)
INPUT_RELEASE_FILE_SHA256: Final = (
    "5b5baaecfd158748ff61728b33442a3c5bbeacd6606b1253287005332528648e"
)
INPUT_SEASON: Final = "2023-24"
TARGET_SEASON: Final = "2024-25"
INPUT_PAYLOAD_BYTES: Final = 1_861_184
INPUT_PAYLOAD_ROWS: Final = 26_401
INPUT_ZERO_SECOND_ROWS: Final = 8
WORKER_ID: Final = "cbd0b663-f1be-41a8-bebb-d4519b1326cf"
RELEASER_ID: Final = "864250a3-a4a7-4ca6-b65b-2613087c39c9"
PURPOSE_RULING_ID: Final = "20260911T203909966400Z-8f295a4f6a4efcea"
PURPOSE_RULING_CONTENT_SHA256: Final = (
    "8f295a4f6a4efcea6fc61e209b8a95146c44a7e27e79da8600ff9303de9b4917"
)
PRIOR_ACCESS_DEVIATION_ID: Final = "20260911T201857956271Z-f2bee81f6dd5b6af"
PRIOR_ACCESS_DEVIATION_CONTENT_SHA256: Final = (
    "f2bee81f6dd5b6af2e7748e91a9a904ece2db7908ee57ed4fcb6b52b2604440d"
)
PRIOR_ACCESS_DEVIATION_FILE_SHA256: Final = (
    "99ca8e02b1add9deac32f2fae567031f207d57d3f7666383cb312d348a9cb604"
)
PRIOR_ACCESS_INVENTORY_SHA256: Final = (
    "8a638d65c241930bd7b7487df26a4be9a32b115dd28ec2542c7d1569726d5254"
)
EXPECTED_PURPOSE: Final = (
    "Final-forecast input for experiment "
    "zscore-production-carryforward-v1-exp-20260911T201744001625Z: 2023-24 "
    "production is INPUT ONLY for the final 2024-25 carry-forward forecast vector, "
    "reference means, population SDs, ratio reference percentages, replacement state, "
    "prediction-only bin edges, and exact assignments before the matching freeze."
)


class FinalForecastInputError(ValueError):
    """The input-only release or prefreeze construction is invalid."""


def _verify_input_manifest(path: Path) -> dict[str, Any]:
    _require_file(
        path,
        expected_sha256=INPUT_MANIFEST_SHA256,
        label="final-forecast input manifest",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FinalForecastInputError("input manifest must be an object")
    if payload.get("package_id") != INPUT_PACKAGE_ID:
        raise FinalForecastInputError("input manifest package identity mismatch")
    if payload.get("content_sha256") != INPUT_PACKAGE_CONTENT_SHA256:
        raise FinalForecastInputError("input manifest content identity mismatch")
    if payload.get("dataset_class") != "development":
        raise FinalForecastInputError("input manifest dataset class mismatch")
    if payload.get("purpose") != EXPECTED_PURPOSE:
        raise FinalForecastInputError("input manifest purpose mismatch")
    if payload.get("fields_released") != list(CSV_FIELDS):
        raise FinalForecastInputError("input manifest released-field contract mismatch")
    if payload.get("payloads") != [
        {
            "filename": "player_game_logs_2023-24.csv",
            "bytes": INPUT_PAYLOAD_BYTES,
            "sha256": OUTCOME_SHA256,
        }
    ]:
        raise FinalForecastInputError("input manifest payload accounting mismatch")
    lineage = payload.get("lineage")
    if not isinstance(lineage, dict) or lineage.get("experiment_id") != EXPERIMENT_ID:
        raise FinalForecastInputError("input manifest experiment lineage mismatch")
    return payload


def _verify_input_release(path: Path) -> dict[str, Any]:
    _require_file(
        path,
        expected_sha256=INPUT_RELEASE_FILE_SHA256,
        label="final-forecast input release",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FinalForecastInputError("input release must be an object")
    if payload.get("release_id") != INPUT_RELEASE_ID:
        raise FinalForecastInputError("input release identity mismatch")
    if payload.get("content_sha256") != INPUT_RELEASE_CONTENT_SHA256:
        raise FinalForecastInputError("input release content identity mismatch")
    if payload.get("experiment_id") != EXPERIMENT_ID:
        raise FinalForecastInputError("input release experiment identity mismatch")
    if payload.get("worker_id") != WORKER_ID:
        raise FinalForecastInputError("input release worker identity mismatch")
    if payload.get("releaser_id") != RELEASER_ID:
        raise FinalForecastInputError("input release releaser identity mismatch")
    if payload.get("record_type") != "independent_quant_final_forecast_input_release":
        raise FinalForecastInputError("release is not a final-forecast input release")
    if payload.get("disposition") != "approved_input_only_pending_parent_delivery":
        raise FinalForecastInputError("release does not authorize input-only construction")
    package = payload.get("package")
    if not isinstance(package, dict):
        raise FinalForecastInputError("input release package identity is absent")
    if package.get("package_id") != INPUT_PACKAGE_ID:
        raise FinalForecastInputError("input release package ID mismatch")
    if package.get("content_sha256") != INPUT_PACKAGE_CONTENT_SHA256:
        raise FinalForecastInputError("input release package content mismatch")
    if package.get("manifest_sha256") != INPUT_MANIFEST_SHA256:
        raise FinalForecastInputError("input release manifest identity mismatch")
    released = payload.get("released_artifacts")
    if released != [
        {
            "filename": "manifest.json",
            "bytes": 3_636,
            "sha256": INPUT_MANIFEST_SHA256,
        },
        {
            "filename": "player_game_logs_2023-24.csv",
            "bytes": INPUT_PAYLOAD_BYTES,
            "rows": INPUT_PAYLOAD_ROWS,
            "sha256": OUTCOME_SHA256,
        },
    ]:
        raise FinalForecastInputError("input release artifact accounting mismatch")
    return payload


def _float_text(value: float) -> str:
    if not math.isfinite(value):
        raise FinalForecastInputError("forecast artifact contains a non-finite value")
    return format(value, ".17g")


def _parse_candidate_files(values: Sequence[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        label, separator, raw_path = value.partition("=")
        if not separator or not label or not raw_path:
            raise FinalForecastInputError(
                "candidate files must use the form --candidate-file label=path"
            )
        if label in parsed:
            raise FinalForecastInputError(f"duplicate candidate-file label {label!r}")
        parsed[label] = Path(raw_path)
    if not parsed:
        raise FinalForecastInputError("at least one candidate file must be bound")
    return parsed


def _candidate_hashes(candidate_files: dict[str, Path]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for label, path in sorted(candidate_files.items()):
        if not path.is_file():
            raise FinalForecastInputError(f"candidate file {label!r} is absent")
        hashes[label] = _file_sha256(path)
    return hashes


def _utc_timestamp(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinalForecastInputError(f"{label} is not an ISO-8601 timestamp") from exc
    if parsed.utcoffset() is None:
        raise FinalForecastInputError(f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def _frozen_bins(predictions: dict[int, float]) -> dict[str, object]:
    cuts = _collapsed_quintile_cuts(tuple(predictions.values()))
    assignments = [
        {
            "player_id": player_id,
            "bin": bisect.bisect_right(cuts, predictions[player_id]),
        }
        for player_id in sorted(predictions)
    ]
    counts = [0] * (len(cuts) + 1)
    for assignment in assignments:
        counts[int(assignment["bin"])] += 1
    return {
        "method": "prediction_only_type7_quintiles",
        "probabilities": [0.2, 0.4, 0.6, 0.8],
        "duplicate_cut_policy": "collapse exact adjacent duplicate cuts deterministically",
        "assignment_rule": "bisect_right; values equal to a cut enter the upper bin",
        "cuts": [_float_text(value) for value in cuts],
        "counts": counts,
        "assignments": assignments,
        "assignment_sha256": _canonical_sha256(assignments),
    }


def build_final_forecast_artifact(
    *,
    manifest_path: Path,
    forecast_csv_path: Path,
    release_path: Path,
    candidate_files: dict[str, Path],
    created_at: str,
) -> dict[str, object]:
    manifest = _verify_input_manifest(manifest_path)
    release = _verify_input_release(release_path)
    release_created_at = _utc_timestamp(
        str(release.get("created_at")),
        label="input release created_at",
    )
    forecast_created_at = _utc_timestamp(created_at, label="forecast created_at")
    if forecast_created_at <= release_created_at:
        raise FinalForecastInputError(
            "forecast created_at must be later than the independent input release"
        )
    loaded = _load_season(
        forecast_csv_path,
        season=INPUT_SEASON,
        expected_sha256=OUTCOME_SHA256,
    )
    if loaded.source_rows != INPUT_PAYLOAD_ROWS:
        raise FinalForecastInputError(
            f"input row count mismatch: expected {INPUT_PAYLOAD_ROWS}, got {loaded.source_rows}"
        )
    if loaded.zero_second_rows != INPUT_ZERO_SECOND_ROWS:
        raise FinalForecastInputError(
            "input zero-second-row count does not match the independent release"
        )
    league, benchmark = _historical_benchmark_inputs(
        loaded.player_rates,
        forecast_season=INPUT_SEASON,
        target_season=TARGET_SEASON,
        forecast_payload_sha256=OUTCOME_SHA256,
        method_label="retrospective_rolling_origin_carryforward_final_forecast",
        profile_id_suffix="final-forecast-carryforward",
        profile_name="retrospective-carryforward-final-forecast",
    )
    scored = score_historical_production_benchmark(
        league=league,
        benchmark=benchmark,
    )
    vector = [
        {
            "player_id": score.player_id,
            "ordinal": score.ordinal,
            "components": [
                {
                    "category_key": component.category_key,
                    "production_fields": [
                        {
                            "field": field,
                            "value": f"{value.numerator}/{value.denominator}",
                        }
                        for field, value in component.production_fields
                    ],
                    "transformed_value": _float_text(component.transformed_value),
                    "z_score": _float_text(component.z_score),
                }
                for component in score.category_components
            ],
            "total_z": _float_text(score.total_z),
            "value_above_replacement": (
                None
                if score.value_above_replacement is None
                else _float_text(score.value_above_replacement)
            ),
        }
        for score in scored.scores
    ]
    predictions: dict[str, dict[int, float]] = {
        scale.category_key: {} for scale in scored.category_scales
    }
    predictions["aggregate_total"] = {}
    for score in scored.scores:
        for component in score.category_components:
            predictions[component.category_key][score.player_id] = component.z_score
        predictions["aggregate_total"][score.player_id] = score.total_z
    bins = {
        metric_key: _frozen_bins(metric_predictions)
        for metric_key, metric_predictions in predictions.items()
    }
    artifact: dict[str, object] = {
        "experiment_id": EXPERIMENT_ID,
        "artifact_type": "input_only_final_forecast_prefreeze_candidate",
        "status": "draft_prefreeze_pending_independent_confirmation",
        "created_at": forecast_created_at.isoformat().replace("+00:00", "Z"),
        "forecast_input_season": INPUT_SEASON,
        "target_outcome_season": TARGET_SEASON,
        "outcome_data_accessed": False,
        "outcome_presence_accessed": False,
        "availability_included": False,
        "input_release": {
            "package_id": INPUT_PACKAGE_ID,
            "package_content_sha256": INPUT_PACKAGE_CONTENT_SHA256,
            "manifest_sha256": INPUT_MANIFEST_SHA256,
            "release_id": INPUT_RELEASE_ID,
            "release_content_sha256": INPUT_RELEASE_CONTENT_SHA256,
            "release_file_sha256": INPUT_RELEASE_FILE_SHA256,
            "payload_sha256": OUTCOME_SHA256,
            "purpose": manifest["purpose"],
            "disposition": release["disposition"],
            "release_created_at": release["created_at"],
            "purpose_ruling_id": PURPOSE_RULING_ID,
            "purpose_ruling_content_sha256": PURPOSE_RULING_CONTENT_SHA256,
            "prior_access_deviation": {
                "record_id": PRIOR_ACCESS_DEVIATION_ID,
                "content_sha256": PRIOR_ACCESS_DEVIATION_CONTENT_SHA256,
                "file_sha256": PRIOR_ACCESS_DEVIATION_FILE_SHA256,
                "retained_inventory_sha256": PRIOR_ACCESS_INVENTORY_SHA256,
                "classification": (
                    "protocol-invalid direct-source metadata discovery; no player/game-level "
                    "feature or outcome cells exposed"
                ),
            },
        },
        "candidate_files": _candidate_hashes(candidate_files),
        "cohort": {
            "source_rows": loaded.source_rows,
            "players": len(loaded.player_rates),
            "zero_second_rows": loaded.zero_second_rows,
            "eligibility": "at least one complete credited 2023-24 appearance row",
            "minimum_game_filter": None,
            "future_survivor_filter": None,
        },
        "runtime": {
            "model_version": scored.model_version,
            "result_content_sha256": scored.content_sha256,
            "reference_policy": scored.reference_policy,
            "reference_count": scored.reference_count,
            "reference_player_fingerprint": scored.reference_player_fingerprint,
            "team_count": scored.team_count,
            "roster_size": scored.roster_size,
            "structural_roster_count": scored.structural_roster_count,
            "replacement": {
                "state": scored.replacement.state.value,
                "required_ordinal": scored.replacement.required_ordinal,
                "projected_count": scored.replacement.projected_count,
                "replacement_player_id": scored.replacement.replacement_player_id,
                "replacement_total_z": (
                    None
                    if scored.replacement.replacement_total_z is None
                    else _float_text(scored.replacement.replacement_total_z)
                ),
            },
        },
        "reference_scales": [
            {
                "category_key": scale.category_key,
                "kind": scale.kind.value,
                "direction": scale.direction,
                "production_fields": list(scale.production_fields),
                "reference_mean": _float_text(scale.reference_mean),
                "population_sd": _float_text(scale.population_sd),
                "reference_percentage": (
                    None
                    if scale.reference_percentage is None
                    else _float_text(scale.reference_percentage)
                ),
                "status": scale.status.value,
            }
            for scale in scored.category_scales
        ],
        "forecast_vector": vector,
        "forecast_vector_sha256": _canonical_sha256(vector),
        "prediction_bins": bins,
    }
    artifact["content_sha256"] = _canonical_sha256(artifact)
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--forecast-csv", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--candidate-file", action="append", default=[], required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    artifact = build_final_forecast_artifact(
        manifest_path=args.manifest,
        forecast_csv_path=args.forecast_csv,
        release_path=args.release,
        candidate_files=_parse_candidate_files(args.candidate_file),
        created_at=args.created_at,
    )
    args.output.write_bytes(_canonical_evidence(artifact))
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "content_sha256": artifact["content_sha256"],
                "forecast_vector_sha256": artifact["forecast_vector_sha256"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
