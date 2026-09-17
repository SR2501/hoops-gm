"""Frozen final held-out evaluation for production-only z-scores.

The evaluator first verifies an accepted local freeze, an independent freeze
confirmation, the exact sealed forecast candidate, and an independent outcome
release/unblind. Only then may it open the outcome manifest, forecast-key
manifest, or outcome payload. Forecast scores, scales, and bin assignments are
consumed from the sealed artifact; they are never reconstructed from outcomes.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final, cast

from hoops_gm.db.models.enums import CategoryKind
from hoops_gm.valuation.zscore import CategoryScale, ScaleStatus
from hoops_gm.valuation.zscore_backtest import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CSV_FIELDS,
    EXPERIMENT_ID,
    QUINTILE_PROBABILITIES,
    SUPPORT_SENSITIVITIES,
    DevelopmentEvidenceError,
    _calibration,
    _canonical_evidence,
    _canonical_sha256,
    _collapsed_quintile_cuts,
    _file_sha256,
    _load_season,
    _outcome_component,
    _secondary_metrics,
)

FREEZE_SCHEMA_VERSION: Final = "zscore-final-evaluation-freeze-v2"
CONFIRMATION_SCHEMA_VERSION: Final = "zscore-final-freeze-confirmation-v1"
OUTCOME_MANIFEST_SCHEMA_VERSION: Final = "zscore-final-outcome-manifest-v2"
KEY_MANIFEST_SCHEMA_VERSION: Final = "zscore-final-forecast-key-manifest-v1"
OUTCOME_RELEASE_SCHEMA_VERSION: Final = "zscore-final-outcome-unblind-v2"
RESULT_SCHEMA_VERSION: Final = "zscore-final-evaluation-result-v1"

REQUIRED_CANDIDATE_LABELS: Final = frozenset(
    {
        "valuation_init",
        "runtime",
        "development_evaluator",
        "forecast_builder",
        "final_evaluator",
        "projection_blending",
        "scoring_profiles",
        "runtime_tests",
        "development_tests",
        "forecast_tests",
        "final_evaluator_tests",
        "projection_blending_tests",
        "scoring_profile_tests",
        "development_evidence",
        "zscore_model_card",
        "projection_blending_model_card",
    }
)
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
_FORECAST_BINDING_KEYS: Final = {
    "file_sha256",
    "content_sha256",
    "forecast_vector_sha256",
    "runtime_result_sha256",
    "reference_player_fingerprint",
    "input_package_id",
    "input_release_id",
}
_RELEASE_ARTIFACT_ROLES: Final = {
    "outcome_payload",
    "forecast_key_manifest",
}
_OUTCOME_PAYLOAD_FIELDS: Final = list(CSV_FIELDS)
_FORECAST_KEY_FIELDS: Final = [
    "forecast_player_id",
    "status",
    "complete_payload_rows",
    "incomplete_source_rows",
    "unresolved_source_rows",
    "missing_required_fields",
]
_FIELDS_RELEASED: Final = [
    {
        "payload_role": "outcome_payload",
        "fields": _OUTCOME_PAYLOAD_FIELDS,
    },
    {
        "payload_role": "forecast_key_manifest",
        "fields": _FORECAST_KEY_FIELDS,
    },
]
_FIELDS_WITHHELD: Final = [
    "all 2025-26 season data",
    "participation data",
    "availability data",
    "injury data",
    "roster data",
    "opportunity data",
    "market data",
    "vendor projections",
    "games-played assumptions",
    "foreign or outcome-only players",
    "source fields outside the declared payload schemas",
]
_SOURCE_CUTOFF_MEANING: Final = (
    "Retrospective final official box scores, not pregame or archived as-of "
    "forecasts; later official corrections may be present."
)
_OUTCOME_REGULAR_SEASON_START: Final = date(2024, 10, 22)
_OUTCOME_REGULAR_SEASON_END: Final = date(2025, 4, 13)
_OUTCOME_REGULAR_SEASON_GAME_ID: Final = re.compile(r"00224[0-9]{5}")

_EXPECTED_SCALE_CONTRACTS: Final = {
    "pts": (CategoryKind.COUNTING, 1, ("points_per_game",), False),
    "reb": (CategoryKind.COUNTING, 1, ("rebounds_per_game",), False),
    "ast": (CategoryKind.COUNTING, 1, ("assists_per_game",), False),
    "stl": (CategoryKind.COUNTING, 1, ("steals_per_game",), False),
    "blk": (CategoryKind.COUNTING, 1, ("blocks_per_game",), False),
    "fg3m": (
        CategoryKind.COUNTING,
        1,
        ("three_pointers_made_per_game",),
        False,
    ),
    "to": (CategoryKind.COUNTING, -1, ("turnovers_per_game",), False),
    "fg_pct": (
        CategoryKind.RATIO,
        1,
        ("field_goals_made_per_game", "field_goals_attempted_per_game"),
        True,
    ),
    "ft_pct": (
        CategoryKind.RATIO,
        1,
        ("free_throws_made_per_game", "free_throws_attempted_per_game"),
        True,
    ),
}
FORECAST_ARTIFACT_TYPE: Final = "input_only_final_forecast_prefreeze_candidate"
FORECAST_STATUS: Final = "draft_prefreeze_pending_independent_confirmation"
OUTCOME_SEASON: Final = "2024-25"
FORECAST_SEASON: Final = "2023-24"
KEY_STATUSES: Final = (
    "complete_observation",
    "no_observed_box_score",
    "identity_unresolved",
    "incomplete_required_fields",
)
FINAL_OUTCOME_PURPOSE: Final = (
    "Sealed 2024-25 regular-season appearance-production outcomes and exact "
    "forecast-key accounting for frozen experiment "
    "zscore-production-carryforward-v1-exp-20260911T201744001625Z only."
)

FINAL_EVALUATION_PROTOCOL: Final = {
    "protocol_version": "zscore-production-final-preregistration-v2",
    "experiment_id": EXPERIMENT_ID,
    "research_question_and_eligible_cohort": {
        "question": (
            "Do production-only nine-category z-scores formed by carrying each "
            "eligible player's final 2023-24 per-game rates unchanged preserve "
            "magnitude and spacing in realized 2024-25 per-game production when "
            "both are expressed on the sealed 2023-24 forecast scale?"
        ),
        "forecast_cohort": (
            "all 572 complete forecast players in the sealed input-only forecast; "
            "no minimum-games or future-survivor filter"
        ),
        "outcome_eligibility": (
            "forecast-key-restricted players with at least one complete credited "
            "2024-25 regular-season outcome game"
        ),
        "zero_second_policy": (
            "credited zero-second appearances count as observed games and remain "
            "in per-game denominators"
        ),
        "missingness": (
            "no observed box score, unresolved identity, and incomplete required "
            "fields remain explicitly accounted and are never fabricated as zero"
        ),
    },
    "released_development_and_forecast_inputs": {
        "development_package": {
            "package_id": "20260911T201744001625Z-b18c64c12a89226a",
            "content_sha256": ("b18c64c12a89226ab98f8dd84cf3a73b7baa0c247025ec487b988246b0b6f713"),
            "manifest_file_sha256": (
                "5d2b33f82da0d5150f5455f314ad48fd32ec82f0b57b62a89f2c1baf8a02526b"
            ),
        },
        "development_release": {
            "release_id": "20260911T203052301107Z-b40e39805c39597f",
            "content_sha256": ("b40e39805c39597f28813a5920dfc3e56eb2c77d94ddd337535ccc4cee12ed55"),
            "file_sha256": ("c6c5d3632f4ee321619307582c59153526789dd3c597fb320cb3e5ff29a7b633"),
        },
        "forecast_input_package": {
            "package_id": "20260911T204202792405Z-0fb3dfda4396893f",
            "content_sha256": ("0fb3dfda4396893f38d1a6e49a2f2836efa3098ffe4b325ac6937d8bc787ebe3"),
            "manifest_file_sha256": (
                "2612cfb3005a3aa95a50e810824a0500d38919f0be1b8114b37fcbd03bdaf447"
            ),
        },
        "forecast_input_release": {
            "release_id": "20260911T204417608035Z-8ce7cb77fb4186ef",
            "content_sha256": ("8ce7cb77fb4186efaf54181e71225f7cf537ea957b6f35f493530077c35b14b7"),
            "file_sha256": ("5b5baaecfd158748ff61728b33442a3c5bbeacd6606b1253287005332528648e"),
        },
        "prior_exposure_boundaries": {
            "direct_source_metadata_deviation_id": ("20260911T201857956271Z-f2bee81f6dd5b6af"),
            "direct_source_metadata_deviation_content_sha256": (
                "f2bee81f6dd5b6af2e7748e91a9a904ece2db7908ee57ed4fcb6b52b2604440d"
            ),
            "retained_inventory_sha256": (
                "8a638d65c241930bd7b7487df26a4be9a32b115dd28ec2542c7d1569726d5254"
            ),
            "timestamp_deviation_file_sha256": (
                "32ec650611dd5907e6623864d2c11d2f7a87ba5e43445dc00b4b57fde2c0e0aa"
            ),
            "outcome_presence_or_values_accessed": False,
        },
    },
    "feature_set": {
        "unit": "canonical per-game production rates",
        "counting_categories": ["pts", "reb", "ast", "stl", "blk", "fg3m", "to"],
        "ratio_categories": {
            "fg_pct": ["field_goals_made_per_game", "field_goals_attempted_per_game"],
            "ft_pct": ["free_throws_made_per_game", "free_throws_attempted_per_game"],
        },
        "ratio_transform": (
            "made minus sealed attempt-weighted reference percentage times attempts"
        ),
        "availability_or_games_played_features": False,
        "market_or_vendor_projection_features": False,
    },
    "model_variants": {
        "prespecified_variant": (
            "retrospective rolling-origin 2023-24 to 2024-25 production carry-forward"
        ),
        "estimator_version": "zscore-production-v1",
        "reference_population": "all complete sealed forecast inputs",
        "population_standard_deviation": "ddof=0",
        "category_aggregation": "equal-weight sum of nine directed components",
        "variant_selection": (
            "none; no model, population, feature, transform, threshold, or bin "
            "selection occurs on held-out outcomes"
        ),
    },
    "held_out_outcome_and_split": {
        "forecast_input_season": FORECAST_SEASON,
        "outcome_season": OUTCOME_SEASON,
        "dataset_class": "sealed_outcome",
        "season_type": "Regular Season",
        "regular_season_date_window_inclusive": [
            _OUTCOME_REGULAR_SEASON_START.isoformat(),
            _OUTCOME_REGULAR_SEASON_END.isoformat(),
        ],
        "nba_game_id_rule": "10 digits matching 00224xxxxx",
        "outcome_payload_population": (
            "forecast-key-restricted; foreign and outcome-only players withheld"
        ),
        "outcome_fields": list(CSV_FIELDS),
        "forecast_key_statuses": list(KEY_STATUSES),
    },
    "primary_metric_calibration_and_decision_rule": {
        "primary_metric": (
            "aggregate_total unweighted player-level OLS intercept and slope of "
            "realized frozen-scale score on sealed forecast score"
        ),
        "required_magnitude_evidence": {
            "categories": list(_EXPECTED_SCALE_CONTRACTS),
            "aggregate": "aggregate_total",
            "anchors": ["forecast_plus_one", "forecast_plus_two"],
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_unit": "player",
            "bootstrap_quantiles": [0.025, 0.975],
            "prediction_bins": (
                "per-category and aggregate sealed-forecast Type-7 quintiles "
                "with exact frozen assignments"
            ),
        },
        "ideal_references": {"intercept": 0.0, "slope": 1.0},
        "numerical_pass_fail_tolerances": None,
        "decision_rule": (
            "Every protocol-valid evaluable result, including poor calibration, is "
            "published unchanged for independent Model-gate adjudication. Poor "
            "calibration prevents a broad calibrated-magnitude claim but does not "
            "invalidate the experiment. An unestimable primary aggregate calibration "
            "is valid but insufficient evidence and cannot support Model-gate passage "
            "or activation. Contract, custody, chronology, or payload violations are "
            "invalid evidence and stop before a production result."
        ),
    },
    "secondary_metrics_and_sensitivities": {
        "secondary_metrics": ["mae", "rmse", "spearman"],
        "prediction_bins": {
            "quantile_method": "Type-7",
            "probabilities": list(QUINTILE_PROBABILITIES),
            "duplicate_cuts": "collapse exact adjacent duplicates",
            "assignment": "bisect_right; equality enters upper bin",
            "source": "sealed forecast artifact only",
        },
        "support_sensitivities_observed_games": list(SUPPORT_SENSITIVITIES),
        "category_calibration_required": True,
    },
    "planned_outputs_and_stop_conditions": {
        "planned_outputs": [
            "append-only aggregate final-evaluation result JSON",
            "per-category and aggregate calibration with bootstrap intervals and anchors",
            "sealed prediction-bin summaries",
            "secondary error and rank metrics",
            "10, 25, and 50 observed-game aggregate sensitivities",
            "aggregate-safe model-card result addendum",
        ],
        "public_player_level_output": False,
        "stop_conditions": [
            "worker direct-source or unreleased outcome access",
            "worker, custodian, or independent releaser role collision",
            "package digest, identity, mandatory field, or payload mismatch",
            "outcome release without a prior matching accepted and confirmed freeze",
            "mock outcome entering production evidence",
            "candidate code, protocol, forecast, or chronology mismatch",
            "payload outside the frozen season date or NBA game-ID boundary",
            "source cutoff inconsistent with emitted payload or retrospective capture",
            "withheld-field or declared-schema contradiction",
            "missing, duplicate, foreign, malformed, or contradictory key accounting",
            "malformed production values or no complete observed forecast player",
            "primary aggregate calibration unestimable",
        ],
        "post_unblind_rules": (
            "no estimator, cohort, feature, transform, eligibility, metric, bootstrap, "
            "bin, threshold, missingness, or code changes; final result reporting and "
            "model-card result addendum are append-only"
        ),
        "no_tuning_rule": (
            "no post-result population, threshold, veto, feature, model, or bin changes"
        ),
        "scope_limits": [
            "not calibration evidence for current vendor or blended projections",
            "not availability or expected-games evidence",
            "not dollar, auction, punt, draft, lineup, trade, or recommendation evidence",
        ],
    },
}
FINAL_EVALUATION_PROTOCOL_SHA256: Final = _canonical_sha256(FINAL_EVALUATION_PROTOCOL)


class FinalEvaluationProtocolError(ValueError):
    """A freeze, release, sealed artifact, or final payload failed closed."""


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FinalEvaluationProtocolError(f"{label} file is absent")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FinalEvaluationProtocolError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise FinalEvaluationProtocolError(f"{label} must be a JSON object")
    return value


def _verify_internal_content_hash(value: dict[str, Any], *, label: str) -> str:
    claimed = value.get("content_sha256")
    if not isinstance(claimed, str) or not claimed:
        raise FinalEvaluationProtocolError(f"{label} lacks content_sha256")
    unhashed = dict(value)
    del unhashed["content_sha256"]
    actual = _canonical_sha256(unhashed)
    if actual != claimed:
        raise FinalEvaluationProtocolError(
            f"{label} content hash mismatch: expected {claimed}, got {actual}"
        )
    return claimed


def _timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise FinalEvaluationProtocolError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinalEvaluationProtocolError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.utcoffset() is None:
        raise FinalEvaluationProtocolError(f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def _compact_utc(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise FinalEvaluationProtocolError(f"{label} must be a UTC timestamp")
    try:
        raw = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinalEvaluationProtocolError(f"{label} must be a UTC timestamp") from exc
    if raw.utcoffset() != timedelta(0):
        raise FinalEvaluationProtocolError(f"{label} must use UTC")
    parsed = raw.astimezone(UTC)
    return parsed.strftime("%Y%m%dT%H%M%S%fZ")


def package_identity_material(manifest: Mapping[str, object]) -> bytes:
    """Return the governing package-identity bytes."""

    identity = {
        key: value for key, value in manifest.items() if key not in {"package_id", "content_sha256"}
    }
    payloads = manifest.get("payloads")
    if not isinstance(payloads, list) or not payloads:
        raise FinalEvaluationProtocolError(
            "outcome manifest payloads are absent from package identity"
        )
    digest_lines: list[bytes] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            raise FinalEvaluationProtocolError(
                "outcome manifest payload identity must be an object"
            )
        filename = _required_filename(
            payload.get("filename"),
            label="package payload filename",
        )
        digest = _required_sha256(
            payload.get("sha256"),
            label=f"package payload {filename} sha256",
        )
        digest_lines.append(f"{filename}\t{digest}".encode())
    canonical = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return canonical + b"\n" + b"\n".join(digest_lines)


def package_content_sha256(manifest: Mapping[str, object]) -> str:
    """Reconstruct the normative immutable-package content identity."""

    return hashlib.sha256(package_identity_material(manifest)).hexdigest()


def package_id_for_manifest(manifest: Mapping[str, object]) -> str:
    """Derive compact UTC plus the normative digest prefix."""

    created = _compact_utc(
        manifest.get("created_at"),
        label="outcome manifest created_at",
    )
    return f"{created}-{package_content_sha256(manifest)[:16]}"


def _required_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise FinalEvaluationProtocolError(f"{label} must be a non-empty string")
    return value


def _required_positive_int(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise FinalEvaluationProtocolError(f"{label} must be a positive integer")
    return value


def _strict_keys(value: Mapping[str, object], expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise FinalEvaluationProtocolError(
            f"{label} keys mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _required_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise FinalEvaluationProtocolError(f"{label} must be a lowercase SHA-256")
    return value


def _verify_forecast_binding(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FinalEvaluationProtocolError(f"{label} must be an object")
    _strict_keys(value, _FORECAST_BINDING_KEYS, label=label)
    for key in (
        "file_sha256",
        "content_sha256",
        "forecast_vector_sha256",
        "runtime_result_sha256",
        "reference_player_fingerprint",
    ):
        _required_sha256(value[key], label=f"{label} {key}")
    _required_string(value["input_package_id"], label=f"{label} input_package_id")
    _required_string(value["input_release_id"], label=f"{label} input_release_id")
    return value


def _executing_candidate_paths() -> dict[str, Path]:
    valuation_dir = Path(__file__).resolve().parent
    package_dir = valuation_dir.parent
    return {
        "valuation_init": valuation_dir / "__init__.py",
        "runtime": valuation_dir / "zscore.py",
        "development_evaluator": valuation_dir / "zscore_backtest.py",
        "forecast_builder": valuation_dir / "zscore_forecast.py",
        "final_evaluator": Path(__file__).resolve(),
        "projection_blending": package_dir / "projections" / "blending.py",
        "scoring_profiles": package_dir / "scoring" / "profiles.py",
    }


def _verify_candidate_hash_map(value: object, *, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise FinalEvaluationProtocolError(f"{label} must be an object")
    actual_labels = set(value)
    if actual_labels != REQUIRED_CANDIDATE_LABELS:
        raise FinalEvaluationProtocolError(
            f"{label} labels mismatch; "
            f"missing={sorted(REQUIRED_CANDIDATE_LABELS - actual_labels)}, "
            f"extra={sorted(actual_labels - REQUIRED_CANDIDATE_LABELS)}"
        )
    return {
        key: _required_sha256(value[key], label=f"{label} {key}")
        for key in sorted(REQUIRED_CANDIDATE_LABELS)
    }


def _verify_candidate_files(
    *,
    expected: object,
    current_candidate_files: dict[str, Path],
) -> dict[str, str]:
    expected_hashes = _verify_candidate_hash_map(
        expected,
        label="freeze candidate_files",
    )
    if set(current_candidate_files) != REQUIRED_CANDIDATE_LABELS:
        raise FinalEvaluationProtocolError(
            "current candidate-file labels differ from the complete required set"
        )
    for label, executing_path in _executing_candidate_paths().items():
        supplied_path = current_candidate_files[label]
        if supplied_path.resolve() != executing_path.resolve():
            raise FinalEvaluationProtocolError(
                f"current candidate file {label!r} does not identify the executing implementation"
            )
    actual = {
        label: _file_sha256(path)
        for label, path in sorted(current_candidate_files.items())
        if path.is_file()
    }
    if len(actual) != len(current_candidate_files):
        raise FinalEvaluationProtocolError("one or more frozen candidate files are absent")
    if actual != expected_hashes:
        raise FinalEvaluationProtocolError("current candidate files differ from the freeze")
    return actual


def _verify_freeze(
    path: Path,
    *,
    current_candidate_files: dict[str, Path],
) -> tuple[dict[str, Any], datetime, str]:
    freeze = _read_json(path, label="accepted freeze")
    _strict_keys(
        freeze,
        {
            "schema_version",
            "record_type",
            "experiment_id",
            "freeze_id",
            "created_at",
            "status",
            "worker_id",
            "accepted_by",
            "protocol",
            "protocol_sha256",
            "candidate_files",
            "forecast",
            "authorized_outcome_releasers",
            "content_sha256",
        },
        label="accepted freeze",
    )
    freeze_content = _verify_internal_content_hash(freeze, label="accepted freeze")
    if freeze["schema_version"] != FREEZE_SCHEMA_VERSION:
        raise FinalEvaluationProtocolError("accepted freeze schema mismatch")
    if freeze["record_type"] != "accepted_zscore_final_evaluation_freeze":
        raise FinalEvaluationProtocolError("record is not an accepted final freeze")
    if freeze["experiment_id"] != EXPERIMENT_ID:
        raise FinalEvaluationProtocolError("accepted freeze experiment mismatch")
    if freeze["status"] != "accepted":
        raise FinalEvaluationProtocolError("local freeze has not been accepted")
    if freeze["protocol"] != FINAL_EVALUATION_PROTOCOL:
        raise FinalEvaluationProtocolError("accepted freeze protocol differs from code")
    if freeze["protocol_sha256"] != FINAL_EVALUATION_PROTOCOL_SHA256:
        raise FinalEvaluationProtocolError("accepted freeze protocol hash mismatch")
    accepted_by = freeze["accepted_by"]
    if not isinstance(accepted_by, dict):
        raise FinalEvaluationProtocolError("freeze acceptance must be an object")
    _strict_keys(accepted_by, {"role", "identity"}, label="freeze acceptance")
    if accepted_by["role"] != "owner_supervisor":
        raise FinalEvaluationProtocolError("freeze lacks owner-supervisor acceptance")
    _required_string(accepted_by["identity"], label="freeze accepter identity")
    _required_string(freeze["freeze_id"], label="freeze_id")
    _required_string(freeze["worker_id"], label="worker_id")
    releasers = freeze["authorized_outcome_releasers"]
    if (
        not isinstance(releasers, list)
        or not releasers
        or any(not isinstance(item, str) or not item for item in releasers)
    ):
        raise FinalEvaluationProtocolError(
            "freeze must name authorized independent outcome releasers"
        )
    candidate_hashes = _verify_candidate_files(
        expected=freeze["candidate_files"],
        current_candidate_files=current_candidate_files,
    )
    freeze["candidate_files"] = candidate_hashes
    freeze["forecast"] = _verify_forecast_binding(
        freeze["forecast"],
        label="freeze forecast binding",
    )
    return freeze, _timestamp(freeze["created_at"], label="freeze created_at"), freeze_content


def _verify_confirmation(
    path: Path,
    *,
    freeze: dict[str, Any],
    freeze_path: Path,
    freeze_time: datetime,
    freeze_content_sha256: str,
) -> tuple[dict[str, Any], datetime]:
    confirmation = _read_json(path, label="independent freeze confirmation")
    _strict_keys(
        confirmation,
        {
            "schema_version",
            "record_type",
            "confirmation_id",
            "experiment_id",
            "freeze_id",
            "created_at",
            "reviewer",
            "disposition",
            "accepted_freeze_file_sha256",
            "accepted_freeze_content_sha256",
            "forecast",
            "content_sha256",
        },
        label="independent freeze confirmation",
    )
    _verify_internal_content_hash(
        confirmation,
        label="independent freeze confirmation",
    )
    if confirmation["schema_version"] != CONFIRMATION_SCHEMA_VERSION:
        raise FinalEvaluationProtocolError("freeze confirmation schema mismatch")
    if confirmation["record_type"] != "independent_quant_freeze_confirmation":
        raise FinalEvaluationProtocolError("record is not a freeze confirmation")
    if confirmation["experiment_id"] != EXPERIMENT_ID:
        raise FinalEvaluationProtocolError("freeze confirmation experiment mismatch")
    if confirmation["freeze_id"] != freeze["freeze_id"]:
        raise FinalEvaluationProtocolError("freeze confirmation names another freeze")
    if confirmation["disposition"] != "confirmed_for_final_outcome_release":
        raise FinalEvaluationProtocolError("independent reviewer has not confirmed the freeze")
    reviewer = confirmation["reviewer"]
    if not isinstance(reviewer, dict):
        raise FinalEvaluationProtocolError("freeze reviewer must be an object")
    _strict_keys(reviewer, {"role", "identity"}, label="freeze reviewer")
    if reviewer["role"] != "independent_quant_reviewer":
        raise FinalEvaluationProtocolError("freeze confirmation has the wrong reviewer role")
    reviewer_id = _required_string(
        reviewer["identity"],
        label="independent reviewer identity",
    )
    if reviewer_id == freeze["worker_id"]:
        raise FinalEvaluationProtocolError("worker cannot independently confirm its own freeze")
    if confirmation["accepted_freeze_file_sha256"] != _file_sha256(freeze_path):
        raise FinalEvaluationProtocolError("freeze confirmation file hash mismatch")
    if confirmation["accepted_freeze_content_sha256"] != freeze_content_sha256:
        raise FinalEvaluationProtocolError("freeze confirmation content hash mismatch")
    confirmation_forecast = _verify_forecast_binding(
        confirmation["forecast"],
        label="confirmation forecast binding",
    )
    if confirmation_forecast != freeze["forecast"]:
        raise FinalEvaluationProtocolError("freeze confirmation forecast binding mismatch")
    confirmation_time = _timestamp(
        confirmation["created_at"],
        label="freeze confirmation created_at",
    )
    if confirmation_time <= freeze_time:
        raise FinalEvaluationProtocolError(
            "freeze confirmation must be later than the accepted freeze"
        )
    return confirmation, confirmation_time


def _parse_float(value: object, *, label: str) -> float:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise FinalEvaluationProtocolError(f"{label} must be numeric")
    try:
        parsed = float(value)
    except ValueError as exc:
        raise FinalEvaluationProtocolError(f"{label} must be numeric") from exc
    if not math.isfinite(parsed):
        raise FinalEvaluationProtocolError(f"{label} must be finite")
    return parsed


def _verify_forecast_artifact(
    path: Path,
    *,
    freeze: dict[str, Any],
    freeze_time: datetime,
    confirmation_time: datetime,
) -> tuple[
    dict[str, Any],
    dict[str, dict[int, float]],
    dict[str, CategoryScale],
    dict[str, dict[int, int]],
]:
    forecast_binding = cast(dict[str, Any], freeze["forecast"])
    if _file_sha256(path) != forecast_binding.get("file_sha256"):
        raise FinalEvaluationProtocolError("sealed forecast file hash mismatch")
    artifact = _read_json(path, label="sealed forecast")
    artifact_content = _verify_internal_content_hash(artifact, label="sealed forecast")
    if artifact_content != forecast_binding.get("content_sha256"):
        raise FinalEvaluationProtocolError("sealed forecast content binding mismatch")
    if artifact.get("experiment_id") != EXPERIMENT_ID:
        raise FinalEvaluationProtocolError("sealed forecast experiment mismatch")
    if artifact.get("artifact_type") != FORECAST_ARTIFACT_TYPE:
        raise FinalEvaluationProtocolError("sealed forecast artifact type mismatch")
    if artifact.get("status") != FORECAST_STATUS:
        raise FinalEvaluationProtocolError("sealed forecast status mismatch")
    if artifact.get("forecast_input_season") != FORECAST_SEASON:
        raise FinalEvaluationProtocolError("sealed forecast input season mismatch")
    if artifact.get("target_outcome_season") != OUTCOME_SEASON:
        raise FinalEvaluationProtocolError("sealed forecast target season mismatch")
    if artifact.get("outcome_data_accessed") is not False:
        raise FinalEvaluationProtocolError("sealed forecast claims outcome access")
    if artifact.get("outcome_presence_accessed") is not False:
        raise FinalEvaluationProtocolError("sealed forecast claims outcome-presence access")
    forecast_time = _timestamp(artifact.get("created_at"), label="forecast created_at")
    input_release = artifact.get("input_release")
    if not isinstance(input_release, dict):
        raise FinalEvaluationProtocolError("sealed forecast input release is absent")
    input_release_time = _timestamp(
        input_release.get("release_created_at"),
        label="forecast input release created_at",
    )
    if input_release_time >= forecast_time:
        raise FinalEvaluationProtocolError(
            "forecast input release must be earlier than sealed forecast creation"
        )
    if forecast_time >= freeze_time:
        raise FinalEvaluationProtocolError(
            "sealed forecast creation must be earlier than the accepted freeze"
        )
    if freeze_time >= confirmation_time:
        raise FinalEvaluationProtocolError(
            "accepted freeze must be earlier than independent confirmation"
        )
    forecast_candidates = _verify_candidate_hash_map(
        artifact.get("candidate_files"),
        label="sealed forecast candidate_files",
    )
    if forecast_candidates != freeze["candidate_files"]:
        raise FinalEvaluationProtocolError(
            "sealed forecast candidate files differ from the accepted freeze"
        )
    if artifact.get("forecast_vector_sha256") != forecast_binding.get("forecast_vector_sha256"):
        raise FinalEvaluationProtocolError("sealed forecast vector binding mismatch")
    runtime = artifact.get("runtime")
    if not isinstance(runtime, dict):
        raise FinalEvaluationProtocolError("sealed forecast runtime is absent")
    for artifact_key, freeze_key in (
        ("result_content_sha256", "runtime_result_sha256"),
        ("reference_player_fingerprint", "reference_player_fingerprint"),
    ):
        if runtime.get(artifact_key) != forecast_binding.get(freeze_key):
            raise FinalEvaluationProtocolError(f"sealed forecast {artifact_key} binding mismatch")
    if input_release.get("package_id") != forecast_binding.get("input_package_id"):
        raise FinalEvaluationProtocolError("sealed forecast input package mismatch")
    if input_release.get("release_id") != forecast_binding.get("input_release_id"):
        raise FinalEvaluationProtocolError("sealed forecast input release mismatch")

    vector = artifact.get("forecast_vector")
    if not isinstance(vector, list) or not vector:
        raise FinalEvaluationProtocolError("sealed forecast vector is empty")
    if _canonical_sha256(vector) != artifact["forecast_vector_sha256"]:
        raise FinalEvaluationProtocolError("sealed forecast vector hash mismatch")
    scales_raw = artifact.get("reference_scales")
    if not isinstance(scales_raw, list) or len(scales_raw) != 9:
        raise FinalEvaluationProtocolError("sealed forecast must contain nine scales")
    scales: dict[str, CategoryScale] = {}
    for raw in scales_raw:
        if not isinstance(raw, dict):
            raise FinalEvaluationProtocolError("sealed forecast scale must be an object")
        category_key = _required_string(raw.get("category_key"), label="scale category")
        if category_key in scales:
            raise FinalEvaluationProtocolError("sealed forecast repeats a category scale")
        try:
            kind = CategoryKind(_required_string(raw.get("kind"), label="scale category kind"))
            status = ScaleStatus(_required_string(raw.get("status"), label="scale status"))
        except ValueError as exc:
            raise FinalEvaluationProtocolError("sealed forecast scale enum mismatch") from exc
        direction = raw.get("direction")
        if direction not in {-1, 1}:
            raise FinalEvaluationProtocolError("sealed forecast scale direction is invalid")
        fields = raw.get("production_fields")
        if (
            not isinstance(fields, list)
            or not fields
            or any(not isinstance(field, str) for field in fields)
        ):
            raise FinalEvaluationProtocolError("sealed forecast scale fields are invalid")
        percentage_raw = raw.get("reference_percentage")
        percentage = (
            None
            if percentage_raw is None
            else _parse_float(percentage_raw, label=f"{category_key} reference percentage")
        )
        if percentage is not None and not 0 <= percentage <= 1:
            raise FinalEvaluationProtocolError("ratio reference percentage is outside [0,1]")
        sd = _parse_float(raw.get("population_sd"), label=f"{category_key} SD")
        if sd < 0 or (status is ScaleStatus.DEFINED and sd == 0):
            raise FinalEvaluationProtocolError("sealed forecast scale SD is invalid")
        if status is ScaleStatus.ZERO_VARIANCE and sd != 0:
            raise FinalEvaluationProtocolError("zero-variance scale must have zero SD")
        scales[category_key] = CategoryScale(
            category_key=category_key,
            kind=kind,
            direction=cast(int, direction),
            production_fields=tuple(cast(list[str], fields)),
            reference_mean=_parse_float(
                raw.get("reference_mean"),
                label=f"{category_key} reference mean",
            ),
            population_sd=sd,
            reference_percentage=percentage,
            status=status,
        )
    expected_categories = set(_EXPECTED_SCALE_CONTRACTS)
    if set(scales) != expected_categories:
        raise FinalEvaluationProtocolError(
            "sealed forecast category scales are not canonical 9-cat"
        )
    for category_key, scale in scales.items():
        expected_kind, expected_direction, expected_fields, is_ratio = _EXPECTED_SCALE_CONTRACTS[
            category_key
        ]
        if (
            scale.kind is not expected_kind
            or scale.direction != expected_direction
            or scale.production_fields != expected_fields
        ):
            raise FinalEvaluationProtocolError(
                f"sealed forecast {category_key} scale semantics are not canonical"
            )
        if is_ratio != (scale.reference_percentage is not None):
            raise FinalEvaluationProtocolError(
                f"sealed forecast {category_key} ratio reference is invalid"
            )

    predictions: dict[str, dict[int, float]] = {
        key: {} for key in (*sorted(expected_categories), "aggregate_total")
    }
    ordinals: list[tuple[int, int, float]] = []
    seen_ids: set[int] = set()
    for raw in vector:
        if not isinstance(raw, dict):
            raise FinalEvaluationProtocolError("sealed forecast vector row must be an object")
        player_id = _required_positive_int(raw.get("player_id"), label="forecast player_id")
        ordinal = _required_positive_int(raw.get("ordinal"), label="forecast ordinal")
        if player_id in seen_ids:
            raise FinalEvaluationProtocolError("sealed forecast repeats a player key")
        seen_ids.add(player_id)
        components = raw.get("components")
        if not isinstance(components, list) or len(components) != 9:
            raise FinalEvaluationProtocolError("forecast row must contain nine components")
        seen_components: set[str] = set()
        component_total = 0.0
        for component in components:
            if not isinstance(component, dict):
                raise FinalEvaluationProtocolError("forecast component must be an object")
            category_key = _required_string(
                component.get("category_key"),
                label="forecast component category",
            )
            if category_key in seen_components or category_key not in scales:
                raise FinalEvaluationProtocolError("forecast component category mismatch")
            seen_components.add(category_key)
            transformed = _parse_float(
                component.get("transformed_value"),
                label=f"{category_key} transformed value",
            )
            predicted = _parse_float(
                component.get("z_score"),
                label=f"{category_key} z-score",
            )
            scale = scales[category_key]
            expected = (
                0.0
                if scale.status is ScaleStatus.ZERO_VARIANCE
                else scale.direction * (transformed - scale.reference_mean) / scale.population_sd
            )
            if not math.isclose(predicted, expected, rel_tol=1e-12, abs_tol=1e-12):
                raise FinalEvaluationProtocolError(
                    f"forecast {category_key} z-score disagrees with sealed scale"
                )
            predictions[category_key][player_id] = predicted
            component_total += predicted
        if seen_components != expected_categories:
            raise FinalEvaluationProtocolError("forecast row category set mismatch")
        total = _parse_float(raw.get("total_z"), label="forecast total_z")
        if not math.isclose(total, component_total, rel_tol=1e-12, abs_tol=1e-12):
            raise FinalEvaluationProtocolError("forecast total is not the component sum")
        predictions["aggregate_total"][player_id] = total
        ordinals.append((ordinal, player_id, total))
    if sorted(ordinals) != ordinals:
        raise FinalEvaluationProtocolError("forecast vector is not in ordinal order")
    expected_order = sorted(ordinals, key=lambda item: (-item[2], item[1]))
    if [(ordinal, player_id) for ordinal, player_id, _value in ordinals] != [
        (index, player_id)
        for index, (_old_ordinal, player_id, _value) in enumerate(expected_order, start=1)
    ]:
        raise FinalEvaluationProtocolError("forecast ordinal ordering is invalid")
    reference_ids = sorted(seen_ids)
    if runtime.get("reference_count") != len(reference_ids):
        raise FinalEvaluationProtocolError("forecast reference count mismatch")
    if runtime.get("reference_player_fingerprint") != _canonical_sha256(reference_ids):
        raise FinalEvaluationProtocolError("forecast reference fingerprint mismatch")

    bins_raw = artifact.get("prediction_bins")
    if not isinstance(bins_raw, dict) or set(bins_raw) != set(predictions):
        raise FinalEvaluationProtocolError("sealed prediction-bin metric set mismatch")
    frozen_assignments: dict[str, dict[int, int]] = {}
    for metric_key, metric_predictions in predictions.items():
        raw_bins = bins_raw[metric_key]
        if not isinstance(raw_bins, dict):
            raise FinalEvaluationProtocolError("sealed prediction bins must be objects")
        cuts_raw = raw_bins.get("cuts")
        assignments_raw = raw_bins.get("assignments")
        if not isinstance(cuts_raw, list) or not isinstance(assignments_raw, list):
            raise FinalEvaluationProtocolError("sealed cuts or assignments are absent")
        cuts = tuple(
            _parse_float(value, label=f"{metric_key} prediction cut") for value in cuts_raw
        )
        expected_cuts = _collapsed_quintile_cuts(tuple(metric_predictions.values()))
        if cuts != expected_cuts:
            raise FinalEvaluationProtocolError(
                f"sealed {metric_key} cuts differ from forecast-only Type-7 cuts"
            )
        if _canonical_sha256(assignments_raw) != raw_bins.get("assignment_sha256"):
            raise FinalEvaluationProtocolError(f"sealed {metric_key} assignment hash mismatch")
        assignments: dict[int, int] = {}
        for assignment in assignments_raw:
            if not isinstance(assignment, dict):
                raise FinalEvaluationProtocolError("bin assignment must be an object")
            player_id = _required_positive_int(
                assignment.get("player_id"),
                label="bin assignment player_id",
            )
            bin_index = assignment.get("bin")
            if type(bin_index) is not int or not 0 <= bin_index <= len(cuts):
                raise FinalEvaluationProtocolError("bin assignment index is invalid")
            if player_id in assignments:
                raise FinalEvaluationProtocolError("bin assignments repeat a player")
            expected_bin = bisect.bisect_right(cuts, metric_predictions.get(player_id, math.nan))
            if player_id not in metric_predictions or bin_index != expected_bin:
                raise FinalEvaluationProtocolError("sealed bin assignment is inconsistent")
            assignments[player_id] = bin_index
        if set(assignments) != set(metric_predictions):
            raise FinalEvaluationProtocolError("sealed bin assignments omit forecast keys")
        counts = [0] * (len(cuts) + 1)
        for bin_index in assignments.values():
            counts[bin_index] += 1
        if raw_bins.get("counts") != counts:
            raise FinalEvaluationProtocolError("sealed bin counts mismatch")
        frozen_assignments[metric_key] = assignments
    return artifact, predictions, scales, frozen_assignments


def _verify_outcome_release(
    path: Path,
    *,
    freeze: dict[str, Any],
    confirmation: dict[str, Any],
    confirmation_time: datetime,
) -> tuple[dict[str, Any], datetime]:
    release = _read_json(path, label="outcome release")
    _strict_keys(
        release,
        {
            "schema_version",
            "record_type",
            "release_id",
            "experiment_id",
            "freeze_id",
            "worker_id",
            "created_at",
            "releaser",
            "disposition",
            "package",
            "forecast",
            "content_sha256",
        },
        label="outcome release",
    )
    _verify_internal_content_hash(release, label="outcome release")
    if release["schema_version"] != OUTCOME_RELEASE_SCHEMA_VERSION:
        raise FinalEvaluationProtocolError("outcome release schema mismatch")
    if release["record_type"] != "independent_quant_final_outcome_unblind":
        raise FinalEvaluationProtocolError("record is not a final outcome unblind")
    if release["experiment_id"] != EXPERIMENT_ID:
        raise FinalEvaluationProtocolError("outcome release experiment mismatch")
    if release["freeze_id"] != freeze["freeze_id"]:
        raise FinalEvaluationProtocolError("outcome release freeze mismatch")
    if release["worker_id"] != freeze["worker_id"]:
        raise FinalEvaluationProtocolError("outcome release worker mismatch")
    if release["disposition"] != "approved_final_outcome_unblind":
        raise FinalEvaluationProtocolError("final outcome unblind is not approved")
    releaser = release["releaser"]
    if not isinstance(releaser, dict):
        raise FinalEvaluationProtocolError("outcome releaser must be an object")
    _strict_keys(releaser, {"role", "identity"}, label="outcome releaser")
    if releaser["role"] != "independent_quant_releaser":
        raise FinalEvaluationProtocolError("outcome release has the wrong releaser role")
    releaser_id = _required_string(
        releaser["identity"],
        label="outcome releaser identity",
    )
    if releaser_id == freeze["worker_id"]:
        raise FinalEvaluationProtocolError("worker cannot release its own outcome")
    if releaser_id not in freeze["authorized_outcome_releasers"]:
        raise FinalEvaluationProtocolError("outcome releaser was not authorized by the freeze")
    release_forecast = _verify_forecast_binding(
        release["forecast"],
        label="outcome release forecast binding",
    )
    if release_forecast != confirmation["forecast"]:
        raise FinalEvaluationProtocolError("outcome release forecast binding mismatch")
    package = release["package"]
    if not isinstance(package, dict):
        raise FinalEvaluationProtocolError("outcome release package binding is absent")
    _strict_keys(
        package,
        {
            "package_id",
            "content_sha256",
            "manifest_filename",
            "manifest_bytes",
            "manifest_file_sha256",
        },
        label="outcome release package",
    )
    _required_string(package["package_id"], label="outcome package_id")
    _required_sha256(
        package["content_sha256"],
        label="outcome package content_sha256",
    )
    _required_filename(package["manifest_filename"], label="outcome manifest filename")
    _required_positive_int(package["manifest_bytes"], label="outcome manifest bytes")
    _required_sha256(
        package["manifest_file_sha256"],
        label="outcome manifest file_sha256",
    )
    release_time = _timestamp(release["created_at"], label="outcome release created_at")
    if release_time <= confirmation_time:
        raise FinalEvaluationProtocolError("outcome release must be later than freeze confirmation")
    return release, release_time


def _required_filename(value: object, *, label: str) -> str:
    filename = _required_string(value, label=label)
    if Path(filename).name != filename:
        raise FinalEvaluationProtocolError(f"{label} must be a basename")
    return filename


def _verify_manifest_payloads(
    value: object,
    *,
    label: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise FinalEvaluationProtocolError(f"{label} must be a list")
    if len(value) != len(_RELEASE_ARTIFACT_ROLES):
        raise FinalEvaluationProtocolError(
            f"{label} must contain exactly one outcome payload and one forecast-key manifest"
        )
    by_role: dict[str, dict[str, Any]] = {}
    for raw in value:
        if not isinstance(raw, dict):
            raise FinalEvaluationProtocolError(f"{label} entries must be objects")
        role = raw.get("role")
        if not isinstance(role, str) or role not in _RELEASE_ARTIFACT_ROLES:
            raise FinalEvaluationProtocolError(f"{label} contains an unknown role")
        if role in by_role:
            raise FinalEvaluationProtocolError(f"{label} repeats role {role!r}")
        expected_keys = {
            "role",
            "filename",
            "bytes",
            "rows",
            "sha256",
        }
        if role == "forecast_key_manifest":
            expected_keys.add("content_sha256")
        _strict_keys(raw, expected_keys, label=f"{label} {role}")
        _required_filename(raw["filename"], label=f"{label} {role} filename")
        _required_positive_int(raw["bytes"], label=f"{label} {role} bytes")
        rows = raw["rows"]
        if type(rows) is not int or rows < 0:
            raise FinalEvaluationProtocolError(
                f"{label} {role} rows must be a non-negative integer"
            )
        _required_sha256(
            raw["sha256"],
            label=f"{label} {role} sha256",
        )
        if role == "forecast_key_manifest":
            _required_sha256(
                raw["content_sha256"],
                label=f"{label} {role} content_sha256",
            )
        by_role[role] = raw
    if set(by_role) != _RELEASE_ARTIFACT_ROLES:
        raise FinalEvaluationProtocolError(
            f"{label} must declare exactly {_RELEASE_ARTIFACT_ROLES}"
        )
    if [item["role"] for item in value] != [
        "outcome_payload",
        "forecast_key_manifest",
    ]:
        raise FinalEvaluationProtocolError(
            f"{label} must order outcome CSV before forecast-key JSON"
        )
    return by_role


def _verify_declared_file(
    path: Path,
    declaration: Mapping[str, Any],
    *,
    label: str,
) -> None:
    if not path.is_file():
        raise FinalEvaluationProtocolError(f"{label} file is absent")
    if path.name != declaration["filename"]:
        raise FinalEvaluationProtocolError(f"{label} filename mismatch")
    if path.stat().st_size != declaration["bytes"]:
        raise FinalEvaluationProtocolError(f"{label} byte count mismatch")
    digest = declaration.get("sha256", declaration.get("file_sha256"))
    if _file_sha256(path) != digest:
        raise FinalEvaluationProtocolError(f"{label} file hash mismatch")


def _verify_source_cutoff(manifest: Mapping[str, Any]) -> tuple[date, datetime]:
    cutoff = manifest.get("source_cutoff")
    if not isinstance(cutoff, dict):
        raise FinalEvaluationProtocolError("outcome manifest source_cutoff is absent")
    _strict_keys(
        cutoff,
        {
            "latest_game_date_represented",
            "latest_retrospective_capture_at",
            "meaning",
        },
        label="outcome manifest source_cutoff",
    )
    raw_latest_date = _required_string(
        cutoff["latest_game_date_represented"],
        label="source cutoff latest game date",
    )
    try:
        latest_date = date.fromisoformat(raw_latest_date)
    except ValueError as exc:
        raise FinalEvaluationProtocolError(
            "source cutoff latest game date must be ISO-8601"
        ) from exc
    if not _OUTCOME_REGULAR_SEASON_START <= latest_date <= _OUTCOME_REGULAR_SEASON_END:
        raise FinalEvaluationProtocolError(
            "source cutoff latest game date is outside the frozen regular-season window"
        )
    capture_time = _timestamp(
        cutoff["latest_retrospective_capture_at"],
        label="source cutoff retrospective capture",
    )
    manifest_time = _timestamp(
        manifest["created_at"],
        label="outcome manifest created_at",
    )
    season_end_utc = datetime.combine(
        _OUTCOME_REGULAR_SEASON_END,
        datetime.min.time(),
        tzinfo=UTC,
    )
    if capture_time <= season_end_utc or capture_time > manifest_time:
        raise FinalEvaluationProtocolError(
            "source cutoff retrospective capture must follow the season and not "
            "postdate package creation"
        )
    if cutoff["meaning"] != _SOURCE_CUTOFF_MEANING:
        raise FinalEvaluationProtocolError("source cutoff meaning mismatch")
    return latest_date, capture_time


def _verify_custodian(
    manifest: Mapping[str, Any],
    *,
    freeze: Mapping[str, Any],
    release: Mapping[str, Any],
) -> str:
    custodian = manifest.get("custodian")
    if not isinstance(custodian, dict):
        raise FinalEvaluationProtocolError("outcome manifest custodian is absent")
    _strict_keys(
        custodian,
        {"role", "identity", "attested_at", "attestation"},
        label="outcome manifest custodian",
    )
    if custodian["role"] != "data_engineer_custodian":
        raise FinalEvaluationProtocolError("outcome custodian has the wrong role")
    identity = _required_string(
        custodian["identity"],
        label="outcome custodian identity",
    )
    attested_at = _timestamp(
        custodian["attested_at"],
        label="outcome custodian attested_at",
    )
    manifest_time = _timestamp(
        manifest["created_at"],
        label="outcome manifest created_at",
    )
    if attested_at != manifest_time:
        raise FinalEvaluationProtocolError(
            "outcome custodian attestation time must equal package creation time"
        )
    attestation = custodian["attestation"]
    if not isinstance(attestation, dict):
        raise FinalEvaluationProtocolError("outcome custodian attestation is absent")
    expected_attestation = {
        "confirmed_freeze_and_forecast_keys_verified_before_source_access": True,
        "stable_read_only_transaction": True,
        "access_restricted_to_2024_25_and_frozen_forecast_ids": True,
        "credited_zero_second_appearances_retained": True,
        "missing_outcomes_not_fabricated": True,
        "excluded_data_not_accessed_or_included": True,
        "retrospective_capture_manifest_verified": True,
        "package_is_not_release_or_unblind": True,
    }
    _strict_keys(
        attestation,
        set(expected_attestation),
        label="outcome custodian attestation",
    )
    if attestation != expected_attestation:
        raise FinalEvaluationProtocolError("outcome custodian attestation is incomplete")
    releaser = cast(dict[str, Any], release["releaser"])
    if identity in {freeze["worker_id"], releaser["identity"]}:
        raise FinalEvaluationProtocolError(
            "custodian, worker, and independent releaser must be distinct"
        )
    return identity


def _verify_outcome_row_boundaries(
    path: Path,
    *,
    expected_latest_date: date,
) -> None:
    latest_date: date | None = None
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CSV_FIELDS:
            raise FinalEvaluationProtocolError("outcome payload header mismatch")
        for row_number, row in enumerate(reader, start=2):
            try:
                game_date = date.fromisoformat(row["game_date"])
            except (TypeError, ValueError) as exc:
                raise FinalEvaluationProtocolError(
                    f"outcome row {row_number} has invalid game_date"
                ) from exc
            if not _OUTCOME_REGULAR_SEASON_START <= game_date <= _OUTCOME_REGULAR_SEASON_END:
                raise FinalEvaluationProtocolError(
                    f"outcome row {row_number} is outside the frozen regular-season window"
                )
            game_id = row["nba_game_id"]
            if (
                not isinstance(game_id, str)
                or _OUTCOME_REGULAR_SEASON_GAME_ID.fullmatch(game_id) is None
            ):
                raise FinalEvaluationProtocolError(
                    f"outcome row {row_number} has a non-2024-25 regular-season NBA game ID"
                )
            if row["season"] != OUTCOME_SEASON:
                raise FinalEvaluationProtocolError(f"outcome row {row_number} has the wrong season")
            if row["season_type"] not in {"regular", "Regular Season"}:
                raise FinalEvaluationProtocolError(
                    f"outcome row {row_number} has non-regular season_type"
                )
            latest_date = game_date if latest_date is None else max(latest_date, game_date)
    if latest_date is None:
        raise FinalEvaluationProtocolError("outcome payload has no credited appearances")
    if latest_date != expected_latest_date:
        raise FinalEvaluationProtocolError(
            "source cutoff latest game date disagrees with the emitted outcome payload"
        )


def _verify_outcome_manifest(
    path: Path,
    *,
    release: dict[str, Any],
    freeze: dict[str, Any],
    confirmation_time: datetime,
) -> tuple[dict[str, Any], datetime, dict[str, dict[str, Any]]]:
    package = release["package"]
    _verify_declared_file(
        path,
        {
            "filename": package["manifest_filename"],
            "bytes": package["manifest_bytes"],
            "file_sha256": package["manifest_file_sha256"],
        },
        label="outcome manifest",
    )
    manifest = _read_json(path, label="outcome manifest")
    _strict_keys(
        manifest,
        {
            "schema_version",
            "record_type",
            "experiment_id",
            "freeze_id",
            "package_id",
            "created_at",
            "dataset_class",
            "purpose",
            "season",
            "source_cutoff",
            "fields_released",
            "fields_withheld",
            "custodian",
            "forecast",
            "payloads",
            "content_sha256",
        },
        label="outcome manifest",
    )
    if manifest.get("schema_version") != OUTCOME_MANIFEST_SCHEMA_VERSION:
        raise FinalEvaluationProtocolError("outcome manifest schema mismatch")
    if manifest.get("record_type") != "sealed_zscore_final_outcome_manifest":
        raise FinalEvaluationProtocolError("record is not a final outcome manifest")
    if manifest.get("experiment_id") != EXPERIMENT_ID:
        raise FinalEvaluationProtocolError("outcome manifest experiment mismatch")
    if manifest.get("freeze_id") != freeze["freeze_id"]:
        raise FinalEvaluationProtocolError("outcome manifest freeze mismatch")
    manifest_content = package_content_sha256(manifest)
    if manifest.get("content_sha256") != manifest_content:
        raise FinalEvaluationProtocolError("outcome manifest package content identity mismatch")
    expected_package_id = package_id_for_manifest(manifest)
    if manifest.get("package_id") != expected_package_id:
        raise FinalEvaluationProtocolError(
            "outcome manifest package_id is not derived from creation time and content"
        )
    if manifest["package_id"] != package["package_id"]:
        raise FinalEvaluationProtocolError("outcome package identity mismatch")
    if manifest_content != package["content_sha256"]:
        raise FinalEvaluationProtocolError("outcome package content binding mismatch")
    if manifest.get("dataset_class") != "sealed_outcome":
        raise FinalEvaluationProtocolError("outcome manifest dataset class mismatch")
    if manifest.get("purpose") != FINAL_OUTCOME_PURPOSE:
        raise FinalEvaluationProtocolError("outcome manifest purpose mismatch")
    if manifest.get("season") != OUTCOME_SEASON:
        raise FinalEvaluationProtocolError("outcome manifest season mismatch")
    if manifest.get("fields_released") != _FIELDS_RELEASED:
        raise FinalEvaluationProtocolError("outcome manifest field contract mismatch")
    if manifest.get("fields_withheld") != _FIELDS_WITHHELD:
        raise FinalEvaluationProtocolError("outcome manifest withheld-field contract mismatch")
    manifest_forecast = _verify_forecast_binding(
        manifest["forecast"],
        label="outcome manifest forecast binding",
    )
    if manifest_forecast != release["forecast"]:
        raise FinalEvaluationProtocolError("outcome manifest forecast binding mismatch")
    manifest_artifacts = _verify_manifest_payloads(
        manifest["payloads"],
        label="outcome manifest payloads",
    )
    _verify_source_cutoff(manifest)
    _verify_custodian(manifest, freeze=freeze, release=release)
    manifest_time = _timestamp(manifest.get("created_at"), label="outcome manifest created_at")
    if manifest_time <= confirmation_time:
        raise FinalEvaluationProtocolError(
            "outcome manifest must be later than freeze confirmation"
        )
    return manifest, manifest_time, manifest_artifacts


def _verify_key_manifest(
    path: Path,
    *,
    release: dict[str, Any],
    released_artifacts: dict[str, dict[str, Any]],
    freeze: dict[str, Any],
    forecast_ids: set[int],
    confirmation_time: datetime,
    outcome_manifest_time: datetime,
) -> tuple[dict[int, dict[str, Any]], Counter[str]]:
    key_release = released_artifacts["forecast_key_manifest"]
    _verify_declared_file(path, key_release, label="forecast-key manifest")
    manifest = _read_json(path, label="forecast-key manifest")
    _strict_keys(
        manifest,
        {
            "schema_version",
            "record_type",
            "experiment_id",
            "freeze_id",
            "created_at",
            "season",
            "forecast",
            "forecast_key_count",
            "status_counts",
            "keys",
            "content_sha256",
        },
        label="forecast-key manifest",
    )
    key_content = _verify_internal_content_hash(manifest, label="forecast-key manifest")
    if key_content != key_release.get("content_sha256"):
        raise FinalEvaluationProtocolError("forecast-key manifest content binding mismatch")
    if manifest.get("schema_version") != KEY_MANIFEST_SCHEMA_VERSION:
        raise FinalEvaluationProtocolError("forecast-key manifest schema mismatch")
    if manifest.get("record_type") != "sealed_zscore_forecast_key_manifest":
        raise FinalEvaluationProtocolError("record is not a forecast-key manifest")
    if manifest.get("experiment_id") != EXPERIMENT_ID:
        raise FinalEvaluationProtocolError("forecast-key manifest experiment mismatch")
    if manifest.get("freeze_id") != freeze["freeze_id"]:
        raise FinalEvaluationProtocolError("forecast-key manifest freeze mismatch")
    if manifest.get("season") != OUTCOME_SEASON:
        raise FinalEvaluationProtocolError("forecast-key manifest season mismatch")
    key_forecast = _verify_forecast_binding(
        manifest["forecast"],
        label="forecast-key manifest forecast binding",
    )
    if key_forecast != release["forecast"]:
        raise FinalEvaluationProtocolError("forecast-key manifest forecast binding mismatch")
    key_time = _timestamp(manifest.get("created_at"), label="key manifest created_at")
    if key_time <= confirmation_time:
        raise FinalEvaluationProtocolError(
            "forecast-key manifest must be later than freeze confirmation"
        )
    if key_time > outcome_manifest_time:
        raise FinalEvaluationProtocolError(
            "forecast-key manifest must not postdate its package manifest"
        )
    rows = manifest.get("keys")
    if not isinstance(rows, list):
        raise FinalEvaluationProtocolError("forecast-key manifest keys must be a list")
    by_player: dict[int, dict[str, Any]] = {}
    statuses: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, dict):
            raise FinalEvaluationProtocolError("forecast-key row must be an object")
        _strict_keys(
            row,
            {
                "forecast_player_id",
                "status",
                "complete_payload_rows",
                "incomplete_source_rows",
                "unresolved_source_rows",
                "missing_required_fields",
            },
            label="forecast-key row",
        )
        player_id = _required_positive_int(
            row["forecast_player_id"],
            label="forecast-key player_id",
        )
        if player_id in by_player:
            raise FinalEvaluationProtocolError("forecast-key manifest repeats a key")
        status = row["status"]
        if status not in KEY_STATUSES:
            raise FinalEvaluationProtocolError("forecast-key status is invalid")
        complete = row["complete_payload_rows"]
        incomplete = row["incomplete_source_rows"]
        unresolved = row["unresolved_source_rows"]
        if any(type(value) is not int or value < 0 for value in (complete, incomplete, unresolved)):
            raise FinalEvaluationProtocolError("forecast-key row counts must be non-negative")
        missing_fields = row["missing_required_fields"]
        if (
            not isinstance(missing_fields, list)
            or any(field not in CSV_FIELDS for field in missing_fields)
            or len(missing_fields) != len(set(missing_fields))
        ):
            raise FinalEvaluationProtocolError("forecast-key missing-field list is invalid")
        if (incomplete == 0) != (len(missing_fields) == 0):
            raise FinalEvaluationProtocolError(
                "forecast-key incomplete rows and missing fields are contradictory"
            )
        if status == "complete_observation" and (complete < 1 or unresolved != 0):
            raise FinalEvaluationProtocolError("complete key accounting is contradictory")
        if status == "no_observed_box_score" and (
            complete != 0 or incomplete != 0 or unresolved != 0 or missing_fields
        ):
            raise FinalEvaluationProtocolError("no-box-score accounting is contradictory")
        if status == "identity_unresolved" and (
            complete != 0 or incomplete != 0 or unresolved < 1 or missing_fields
        ):
            raise FinalEvaluationProtocolError("unresolved identity accounting is contradictory")
        if status == "incomplete_required_fields" and (
            complete != 0 or incomplete < 1 or unresolved != 0 or not missing_fields
        ):
            raise FinalEvaluationProtocolError("incomplete-field accounting is contradictory")
        by_player[player_id] = row
        statuses[cast(str, status)] += 1
    if set(by_player) != forecast_ids:
        raise FinalEvaluationProtocolError(
            "forecast-key manifest must account for every and only frozen forecast key"
        )
    declared_counts = manifest.get("status_counts")
    if not isinstance(declared_counts, dict):
        raise FinalEvaluationProtocolError("forecast-key status_counts must be an object")
    _strict_keys(
        declared_counts,
        set(KEY_STATUSES),
        label="forecast-key status_counts",
    )
    if declared_counts != {status: statuses[status] for status in KEY_STATUSES}:
        raise FinalEvaluationProtocolError("forecast-key status counts mismatch")
    if manifest.get("forecast_key_count") != len(forecast_ids):
        raise FinalEvaluationProtocolError("forecast-key count mismatch")
    if key_release["rows"] != len(rows):
        raise FinalEvaluationProtocolError("forecast-key manifest row count mismatch")
    return by_player, statuses


def _frozen_bin_report(
    *,
    predictions: dict[int, float],
    observations: dict[int, float],
    assignments: dict[int, int],
    key_rows: dict[int, dict[str, Any]],
) -> dict[str, object]:
    bin_count = max(assignments.values(), default=-1) + 1
    rows: list[dict[str, object]] = []
    for bin_index in range(bin_count):
        forecast_ids = sorted(
            player_id for player_id, assigned in assignments.items() if assigned == bin_index
        )
        paired = [player_id for player_id in forecast_ids if player_id in observations]
        status_counts = Counter(
            cast(str, key_rows[player_id]["status"]) for player_id in forecast_ids
        )
        rows.append(
            {
                "bin_index": bin_index,
                "forecast_count": len(forecast_ids),
                "paired_count": len(paired),
                "key_status_counts": {status: status_counts[status] for status in KEY_STATUSES},
                "mean_predicted": (
                    None
                    if not paired
                    else math.fsum(predictions[player_id] for player_id in paired) / len(paired)
                ),
                "mean_observed_frozen_scale": (
                    None
                    if not paired
                    else math.fsum(observations[player_id] for player_id in paired) / len(paired)
                ),
            }
        )
    return {"bins": rows}


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
    """Run only after every immutable permission and binding verifies."""

    freeze, freeze_time, freeze_content = _verify_freeze(
        accepted_freeze_path,
        current_candidate_files=current_candidate_files,
    )
    confirmation, confirmation_time = _verify_confirmation(
        freeze_confirmation_path,
        freeze=freeze,
        freeze_path=accepted_freeze_path,
        freeze_time=freeze_time,
        freeze_content_sha256=freeze_content,
    )
    artifact, predictions, scales, assignments = _verify_forecast_artifact(
        sealed_forecast_path,
        freeze=freeze,
        freeze_time=freeze_time,
        confirmation_time=confirmation_time,
    )

    # This release is the permission boundary. Outcome metadata and payloads are
    # not opened before it has independently bound the freeze and forecast.
    release, release_time = _verify_outcome_release(
        outcome_release_path,
        freeze=freeze,
        confirmation=confirmation,
        confirmation_time=confirmation_time,
    )
    manifest, manifest_time, manifest_artifacts = _verify_outcome_manifest(
        outcome_manifest_path,
        release=release,
        freeze=freeze,
        confirmation_time=confirmation_time,
    )
    if release_time <= manifest_time:
        raise FinalEvaluationProtocolError(
            "outcome release must be later than the sealed outcome manifest"
        )
    forecast_ids = set(predictions["aggregate_total"])
    key_rows, key_status_counts = _verify_key_manifest(
        forecast_key_manifest_path,
        release=release,
        released_artifacts=manifest_artifacts,
        freeze=freeze,
        forecast_ids=forecast_ids,
        confirmation_time=confirmation_time,
        outcome_manifest_time=manifest_time,
    )

    verified_outcome_entry = manifest_artifacts["outcome_payload"]
    _verify_declared_file(
        outcome_csv_path,
        verified_outcome_entry,
        label="outcome payload",
    )
    cutoff = cast(dict[str, Any], manifest["source_cutoff"])
    expected_latest_date = date.fromisoformat(cast(str, cutoff["latest_game_date_represented"]))
    _verify_outcome_row_boundaries(
        outcome_csv_path,
        expected_latest_date=expected_latest_date,
    )
    try:
        loaded = _load_season(
            outcome_csv_path,
            season=OUTCOME_SEASON,
            expected_sha256=cast(str, verified_outcome_entry["sha256"]),
        )
    except DevelopmentEvidenceError as exc:
        raise FinalEvaluationProtocolError(str(exc)) from exc
    if loaded.source_rows != verified_outcome_entry.get("rows"):
        raise FinalEvaluationProtocolError("outcome payload row count mismatch")
    outcomes = {rates.player_id: rates for rates in loaded.player_rates}
    if set(outcomes) - forecast_ids:
        raise FinalEvaluationProtocolError("outcome payload contains foreign forecast keys")
    for player_id, key_row in key_rows.items():
        status = key_row["status"]
        observed_rates = outcomes.get(player_id)
        if status == "complete_observation":
            if observed_rates is None or observed_rates.games != key_row["complete_payload_rows"]:
                raise FinalEvaluationProtocolError(
                    "complete forecast-key accounting disagrees with outcome payload"
                )
        elif observed_rates is not None:
            raise FinalEvaluationProtocolError(
                "non-complete forecast key has fabricated outcome rows"
            )
    if loaded.source_rows != sum(
        cast(int, row["complete_payload_rows"]) for row in key_rows.values()
    ):
        raise FinalEvaluationProtocolError(
            "outcome rows do not exactly reconcile to complete forecast keys"
        )
    complete_ids = sorted(
        player_id for player_id, row in key_rows.items() if row["status"] == "complete_observation"
    )
    if not complete_ids:
        raise FinalEvaluationProtocolError("final outcome has no complete observed players")

    observed_by_metric: dict[str, dict[int, float]] = {metric_key: {} for metric_key in predictions}
    for player_id in complete_ids:
        rates = outcomes[player_id]
        observed_components = {
            category_key: _outcome_component(rates, scales[category_key]) for category_key in scales
        }
        for category_key, value in observed_components.items():
            observed_by_metric[category_key][player_id] = value
        observed_by_metric["aggregate_total"][player_id] = math.fsum(observed_components.values())

    aggregate_predicted = [predictions["aggregate_total"][player_id] for player_id in complete_ids]
    aggregate_observed = [
        observed_by_metric["aggregate_total"][player_id] for player_id in complete_ids
    ]
    primary_aggregate_calibration = _calibration(
        aggregate_predicted,
        aggregate_observed,
        metric_key="final:aggregate_total",
    )
    if primary_aggregate_calibration.status != "evaluated":
        raise FinalEvaluationProtocolError(
            f"primary aggregate calibration is unestimable: {primary_aggregate_calibration.status}"
        )

    metrics: dict[str, object] = {}
    for metric_key in predictions:
        predicted = [predictions[metric_key][player_id] for player_id in complete_ids]
        observed_values = [observed_by_metric[metric_key][player_id] for player_id in complete_ids]
        calibration = (
            primary_aggregate_calibration
            if metric_key == "aggregate_total"
            else _calibration(
                predicted,
                observed_values,
                metric_key=f"final:{metric_key}",
            )
        )
        metrics[metric_key] = {
            "calibration": asdict(calibration),
            "secondary": _secondary_metrics(predicted, observed_values),
            "sealed_prediction_bins": _frozen_bin_report(
                predictions=predictions[metric_key],
                observations=observed_by_metric[metric_key],
                assignments=assignments[metric_key],
                key_rows=key_rows,
            ),
        }
    support: dict[str, object] = {}
    for minimum_games in SUPPORT_SENSITIVITIES:
        supported = [
            player_id for player_id in complete_ids if outcomes[player_id].games >= minimum_games
        ]
        predicted = [predictions["aggregate_total"][player_id] for player_id in supported]
        supported_observed = [
            observed_by_metric["aggregate_total"][player_id] for player_id in supported
        ]
        support[str(minimum_games)] = {
            "minimum_observed_games": minimum_games,
            "paired_players": len(supported),
            "calibration": asdict(
                _calibration(
                    predicted,
                    supported_observed,
                    metric_key=f"final:aggregate_total_games_{minimum_games}",
                )
            ),
            "secondary": _secondary_metrics(predicted, supported_observed),
        }

    result: dict[str, object] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "freeze_id": freeze["freeze_id"],
        "status": "final_result_append_only_pending_independent_model_gate_review",
        "protocol_sha256": FINAL_EVALUATION_PROTOCOL_SHA256,
        "sealed_forecast": {
            "file_sha256": freeze["forecast"]["file_sha256"],
            "content_sha256": artifact["content_sha256"],
            "forecast_vector_sha256": artifact["forecast_vector_sha256"],
            "reference_player_fingerprint": cast(
                dict[str, Any],
                artifact["runtime"],
            )["reference_player_fingerprint"],
        },
        "outcome_release": {
            "release_id": release["release_id"],
            "release_content_sha256": release["content_sha256"],
            "package_id": manifest["package_id"],
            "manifest_content_sha256": manifest["content_sha256"],
            "outcome_payload_file_sha256": verified_outcome_entry["sha256"],
        },
        "key_accounting": {
            "forecast_keys": len(forecast_ids),
            "status_counts": {status: key_status_counts[status] for status in KEY_STATUSES},
            "complete_outcome_rows": loaded.source_rows,
            "complete_observed_players": len(complete_ids),
            "incomplete_source_rows": sum(
                cast(int, row["incomplete_source_rows"]) for row in key_rows.values()
            ),
            "unresolved_source_rows": sum(
                cast(int, row["unresolved_source_rows"]) for row in key_rows.values()
            ),
            "zero_second_rows": loaded.zero_second_rows,
        },
        "metrics": metrics,
        "support_sensitivities": support,
        "interpretation": {
            "forecast_reconstructed_from_outcomes": False,
            "outcomes_normalized_on_holdout": False,
            "bins_recomputed_after_unblind": False,
            "missing_outcomes_fabricated_as_zero": False,
            "model_gate_passed": False,
        },
    }
    result["content_sha256"] = _canonical_sha256(result)
    return result


def _candidate_files(values: Sequence[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        label, separator, raw_path = value.partition("=")
        if not separator or not label or not raw_path or label in result:
            raise FinalEvaluationProtocolError(
                "candidate files require unique label=path arguments"
            )
        result[label] = Path(raw_path)
    if not result:
        raise FinalEvaluationProtocolError("candidate-file bindings are required")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sealed-forecast", type=Path, required=True)
    parser.add_argument("--accepted-freeze", type=Path, required=True)
    parser.add_argument("--freeze-confirmation", type=Path, required=True)
    parser.add_argument("--outcome-release", type=Path, required=True)
    parser.add_argument("--outcome-manifest", type=Path, required=True)
    parser.add_argument("--forecast-key-manifest", type=Path, required=True)
    parser.add_argument("--outcome-csv", type=Path, required=True)
    parser.add_argument("--candidate-file", action="append", default=[], required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_final_heldout_evaluation(
        sealed_forecast_path=args.sealed_forecast,
        accepted_freeze_path=args.accepted_freeze,
        freeze_confirmation_path=args.freeze_confirmation,
        outcome_release_path=args.outcome_release,
        outcome_manifest_path=args.outcome_manifest,
        forecast_key_manifest_path=args.forecast_key_manifest,
        outcome_csv_path=args.outcome_csv,
        current_candidate_files=_candidate_files(args.candidate_file),
    )
    args.output.write_bytes(_canonical_evidence(result))
    print(
        json.dumps(
            {
                "status": result["status"],
                "content_sha256": result["content_sha256"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
