from __future__ import annotations

import csv
import hashlib
import shutil
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

import pytest

from hoops_gm.valuation import zscore_backtest as backtest
from hoops_gm.valuation import zscore_final_evaluation as final
from hoops_gm.valuation import zscore_forecast as forecast
from hoops_gm.valuation.zscore_backtest import (
    CSV_FIELDS,
    LoadedSeason,
    SeasonRates,
    _canonical_evidence,
    _canonical_sha256,
)


def _rates(player_id: int) -> SeasonRates:
    return SeasonRates(
        player_id=player_id,
        games=1,
        seconds_played=600,
        field_goals_made_per_game=Fraction(player_id + 2),
        field_goals_attempted_per_game=Fraction(player_id + 12),
        free_throws_made_per_game=Fraction(player_id + 3),
        free_throws_attempted_per_game=Fraction(player_id + 13),
        three_pointers_made_per_game=Fraction(player_id),
        points_per_game=Fraction(player_id + 10),
        rebounds_per_game=Fraction(player_id + 5),
        assists_per_game=Fraction(player_id + 4),
        steals_per_game=Fraction(player_id, 10),
        blocks_per_game=Fraction(player_id, 20),
        turnovers_per_game=Fraction(player_id + 1),
    )


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    value["content_sha256"] = _canonical_sha256(value)
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_bytes(_canonical_evidence(value))


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _outcome_row(
    *,
    player_id: int,
    game_id: str,
    points: int,
    fgm: int = 2,
    fga: int = 4,
    game_date: str = "2025-01-01",
    season: str = final.OUTCOME_SEASON,
) -> dict[str, str]:
    return {
        "canonical_player_id": str(player_id),
        "nba_game_id": game_id,
        "game_date": game_date,
        "season": season,
        "season_type": "Regular Season",
        "seconds_played": "600",
        "field_goals_made": str(fgm),
        "field_goals_attempted": str(fga),
        "free_throws_made": "2",
        "free_throws_attempted": "3",
        "three_pointers_made": "1",
        "points": str(points),
        "rebounds": "5",
        "assists": "4",
        "steals": "1",
        "blocks": "1",
        "turnovers": "2",
    }


def _write_outcomes(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _finalize_package_manifest(value: dict[str, Any]) -> dict[str, Any]:
    value["content_sha256"] = final.package_content_sha256(value)
    value["package_id"] = final.package_id_for_manifest(value)
    return value


def _synthetic_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    variant: str = "valid",
) -> dict[str, Any]:
    candidate = tmp_path / "candidate.txt"
    candidate.write_text("frozen candidate\n", encoding="utf-8")
    candidate_files = dict.fromkeys(final.REQUIRED_CANDIDATE_LABELS, candidate)
    candidate_files.update(final._executing_candidate_paths())
    if variant == "missing_candidate_label":
        candidate_files.pop("runtime_tests")
    if variant == "extra_candidate_label":
        candidate_files["unexpected_candidate"] = candidate
    if variant == "substituted_executing_file":
        archived_evaluator = tmp_path / "archived-final-evaluator.py"
        shutil.copyfile(Path(final.__file__), archived_evaluator)
        candidate_files["final_evaluator"] = archived_evaluator
    synthetic_rates = tuple(_rates(player_id) for player_id in range(1, 6))
    if variant == "zero_aggregate_predictor_variance":
        synthetic_rates = (*synthetic_rates[:4], replace(_rates(1), player_id=5))
    input_release_created_at = "2026-09-11T20:00:00Z"
    forecast_created_at = (
        "2026-09-11T20:25:00Z" if variant == "forecast_after_freeze" else "2026-09-11T20:10:00Z"
    )
    freeze_created_at = (
        "2026-09-11T20:35:00Z" if variant == "freeze_after_confirmation" else "2026-09-11T20:20:00Z"
    )
    confirmation_created_at = "2026-09-11T20:30:00Z"
    key_created_at = {
        "key_before_confirmation": "2026-09-11T20:25:00Z",
        "key_after_manifest": "2026-09-11T20:55:00Z",
    }.get(variant, "2026-09-11T20:40:00Z")
    manifest_created_at = "2026-09-11T20:50:00Z"
    release_created_at = (
        "2026-09-11T20:50:00Z"
        if variant == "release_not_after_manifest"
        else "2026-09-11T21:00:00Z"
    )
    monkeypatch.setattr(
        forecast,
        "_verify_input_manifest",
        lambda path: {"purpose": forecast.EXPECTED_PURPOSE},
    )
    monkeypatch.setattr(
        forecast,
        "_verify_input_release",
        lambda path: {
            "disposition": "approved_input_only_pending_parent_delivery",
            "created_at": input_release_created_at,
        },
    )
    monkeypatch.setattr(
        forecast,
        "_load_season",
        lambda *args, **kwargs: LoadedSeason(
            season=forecast.INPUT_SEASON,
            source_rows=forecast.INPUT_PAYLOAD_ROWS,
            zero_second_rows=forecast.INPUT_ZERO_SECOND_ROWS,
            player_rates=synthetic_rates,
        ),
    )
    artifact = forecast.build_final_forecast_artifact(
        manifest_path=Path("manifest"),
        forecast_csv_path=Path("forecast"),
        release_path=Path("release"),
        candidate_files=candidate_files,
        created_at=forecast_created_at,
    )
    if variant == "input_release_after_forecast":
        input_release = cast(dict[str, Any], artifact["input_release"])
        input_release["release_created_at"] = "2026-09-11T20:15:00Z"
    if variant == "sealed_scale_semantics_tamper":
        scales = cast(list[dict[str, Any]], artifact["reference_scales"])
        scales[0]["direction"] = -1
    if variant == "sealed_vector_semantics_tamper":
        vector = cast(list[dict[str, Any]], artifact["forecast_vector"])
        vector[0]["total_z"] = float(vector[0]["total_z"]) + 0.5
        artifact["forecast_vector_sha256"] = _canonical_sha256(vector)
    if variant == "sealed_bin_semantics_tamper":
        bins = cast(dict[str, dict[str, Any]], artifact["prediction_bins"])
        aggregate_bins = bins["aggregate_total"]
        assignments = cast(list[dict[str, Any]], aggregate_bins["assignments"])
        cuts = cast(list[float], aggregate_bins["cuts"])
        assignments[0]["bin"] = (cast(int, assignments[0]["bin"]) + 1) % (len(cuts) + 1)
        aggregate_bins["assignment_sha256"] = _canonical_sha256(assignments)
    if variant in {
        "input_release_after_forecast",
        "sealed_scale_semantics_tamper",
        "sealed_vector_semantics_tamper",
        "sealed_bin_semantics_tamper",
    }:
        artifact.pop("content_sha256")
        artifact["content_sha256"] = _canonical_sha256(artifact)
    runtime = cast(dict[str, Any], artifact["runtime"])
    forecast_path = tmp_path / "sealed-forecast.json"
    _write_json(forecast_path, artifact)
    forecast_binding = {
        "file_sha256": _file_sha(forecast_path),
        "content_sha256": artifact["content_sha256"],
        "forecast_vector_sha256": artifact["forecast_vector_sha256"],
        "runtime_result_sha256": runtime["result_content_sha256"],
        "reference_player_fingerprint": runtime["reference_player_fingerprint"],
        "input_package_id": forecast.INPUT_PACKAGE_ID,
        "input_release_id": forecast.INPUT_RELEASE_ID,
    }
    freeze_candidate_files = artifact["candidate_files"]
    current_candidate_files = candidate_files
    if variant == "forecast_freeze_candidate_mismatch":
        alternate = tmp_path / "alternate-runtime-tests.py"
        alternate.write_text("independently frozen alternate\n", encoding="utf-8")
        current_candidate_files = dict(candidate_files)
        current_candidate_files["runtime_tests"] = alternate
        freeze_candidate_files = {
            label: _file_sha(path) for label, path in sorted(current_candidate_files.items())
        }
    frozen_protocol: dict[str, Any] = deepcopy(final.FINAL_EVALUATION_PROTOCOL)
    if variant == "incomplete_preregistration":
        frozen_protocol.pop("planned_outputs_and_stop_conditions")
    if variant == "invented_numeric_veto":
        frozen_protocol["primary_metric_calibration_and_decision_rule"][
            "numerical_pass_fail_tolerances"
        ] = {"slope": [0.8, 1.2]}
    freeze = _seal(
        {
            "schema_version": final.FREEZE_SCHEMA_VERSION,
            "record_type": "accepted_zscore_final_evaluation_freeze",
            "experiment_id": backtest.EXPERIMENT_ID,
            "freeze_id": "freeze-synthetic-001",
            "created_at": freeze_created_at,
            "status": "accepted",
            "worker_id": "worker-1",
            "accepted_by": {
                "role": "owner_supervisor",
                "identity": "owner-1",
            },
            "protocol": frozen_protocol,
            "protocol_sha256": _canonical_sha256(frozen_protocol),
            "candidate_files": freeze_candidate_files,
            "forecast": forecast_binding,
            "authorized_outcome_releasers": ["independent-2"],
        }
    )
    if variant == "wrong_freeze_experiment":
        freeze["experiment_id"] = "wrong-experiment"
        freeze = _seal({key: value for key, value in freeze.items() if key != "content_sha256"})
    freeze_path = tmp_path / "accepted-freeze.json"
    _write_json(freeze_path, freeze)

    confirmation = _seal(
        {
            "schema_version": final.CONFIRMATION_SCHEMA_VERSION,
            "record_type": "independent_quant_freeze_confirmation",
            "confirmation_id": "confirmation-synthetic-001",
            "experiment_id": backtest.EXPERIMENT_ID,
            "freeze_id": freeze["freeze_id"],
            "created_at": confirmation_created_at,
            "reviewer": {
                "role": "independent_quant_reviewer",
                "identity": "independent-1",
            },
            "disposition": "confirmed_for_final_outcome_release",
            "accepted_freeze_file_sha256": _file_sha(freeze_path),
            "accepted_freeze_content_sha256": freeze["content_sha256"],
            "forecast": forecast_binding,
        }
    )
    if variant == "wrong_confirmation_freeze":
        confirmation["freeze_id"] = "another-freeze"
        confirmation = _seal(
            {key: value for key, value in confirmation.items() if key != "content_sha256"}
        )
    confirmation_path = tmp_path / "freeze-confirmation.json"
    _write_json(confirmation_path, confirmation)

    outcome_rows = [
        _outcome_row(player_id=1, game_id="0022400001", points=13),
        _outcome_row(player_id=1, game_id="0022400002", points=15),
        _outcome_row(player_id=5, game_id="0022400003", points=22),
    ]
    if variant == "foreign_outcome_key":
        outcome_rows.append(_outcome_row(player_id=999, game_id="0022400004", points=10))
    if variant == "invalid_outcome_value":
        outcome_rows[0] = _outcome_row(
            player_id=1,
            game_id="0022400001",
            points=13,
            fgm=5,
            fga=4,
        )
    if variant == "wrong_regular_season_date":
        outcome_rows[0] = _outcome_row(
            player_id=1,
            game_id="0022400001",
            points=13,
            game_date="2025-04-14",
        )
    if variant == "wrong_regular_season_game_id":
        outcome_rows[0] = _outcome_row(
            player_id=1,
            game_id="0022500001",
            points=13,
        )
    if variant == "wrong_row_season":
        outcome_rows[0] = _outcome_row(
            player_id=1,
            game_id="0022400001",
            points=13,
            season="2023-24",
        )
    if variant == "no_complete_keys":
        outcome_rows = []
    if variant == "one_complete_player":
        outcome_rows = outcome_rows[:2]
    outcome_path = tmp_path / "player_game_logs_2024-25.csv"
    _write_outcomes(outcome_path, outcome_rows)

    key_rows: list[dict[str, object]] = [
        {
            "forecast_player_id": 1,
            "status": "complete_observation",
            "complete_payload_rows": 2,
            "incomplete_source_rows": 0,
            "unresolved_source_rows": 0,
            "missing_required_fields": [],
        },
        {
            "forecast_player_id": 2,
            "status": "no_observed_box_score",
            "complete_payload_rows": 0,
            "incomplete_source_rows": 0,
            "unresolved_source_rows": 0,
            "missing_required_fields": [],
        },
        {
            "forecast_player_id": 3,
            "status": "identity_unresolved",
            "complete_payload_rows": 0,
            "incomplete_source_rows": 0,
            "unresolved_source_rows": 1,
            "missing_required_fields": [],
        },
        {
            "forecast_player_id": 4,
            "status": "incomplete_required_fields",
            "complete_payload_rows": 0,
            "incomplete_source_rows": 1,
            "unresolved_source_rows": 0,
            "missing_required_fields": ["points"],
        },
        {
            "forecast_player_id": 5,
            "status": "complete_observation",
            "complete_payload_rows": 1,
            "incomplete_source_rows": 0,
            "unresolved_source_rows": 0,
            "missing_required_fields": [],
        },
    ]
    if variant == "missing_forecast_key":
        key_rows.pop()
    if variant == "duplicate_forecast_key":
        key_rows.append(dict(key_rows[0]))
    if variant == "no_complete_keys":
        key_rows = [
            {
                "forecast_player_id": player_id,
                "status": "no_observed_box_score",
                "complete_payload_rows": 0,
                "incomplete_source_rows": 0,
                "unresolved_source_rows": 0,
                "missing_required_fields": [],
            }
            for player_id in range(1, 6)
        ]
    if variant == "one_complete_player":
        key_rows[4] = {
            "forecast_player_id": 5,
            "status": "no_observed_box_score",
            "complete_payload_rows": 0,
            "incomplete_source_rows": 0,
            "unresolved_source_rows": 0,
            "missing_required_fields": [],
        }
    if variant == "coherent_complete_with_incomplete":
        key_rows[0]["incomplete_source_rows"] = 1
        key_rows[0]["missing_required_fields"] = ["points"]
    if variant == "complete_incomplete_without_missing_fields":
        key_rows[0]["incomplete_source_rows"] = 1
    if variant == "complete_missing_fields_without_incomplete":
        key_rows[0]["missing_required_fields"] = ["points"]
    status_counts = Counter(str(row["status"]) for row in key_rows)
    key_manifest_body: dict[str, Any] = {
        "schema_version": final.KEY_MANIFEST_SCHEMA_VERSION,
        "record_type": "sealed_zscore_forecast_key_manifest",
        "experiment_id": backtest.EXPERIMENT_ID,
        "freeze_id": freeze["freeze_id"],
        "created_at": key_created_at,
        "season": final.OUTCOME_SEASON,
        "forecast": forecast_binding,
        "forecast_key_count": len(key_rows),
        "status_counts": {status: status_counts[status] for status in final.KEY_STATUSES},
        "keys": key_rows,
    }
    if variant == "unknown_key_manifest_field":
        key_manifest_body["unexpected"] = "closed-schema violation"
    key_manifest = _seal(key_manifest_body)
    key_path = tmp_path / "forecast-key-manifest.json"
    _write_json(key_path, key_manifest)
    key_entry = {
        "role": "forecast_key_manifest",
        "filename": key_path.name,
        "bytes": key_path.stat().st_size,
        "rows": len(key_rows),
        "sha256": _file_sha(key_path),
        "content_sha256": key_manifest["content_sha256"],
    }
    outcome_entry = {
        "role": "outcome_payload",
        "filename": outcome_path.name,
        "bytes": outcome_path.stat().st_size,
        "rows": len(outcome_rows),
        "sha256": _file_sha(outcome_path),
    }
    if variant == "false_outcome_bytes":
        outcome_entry["bytes"] = cast(int, outcome_entry["bytes"]) + 1
    if variant == "false_key_rows":
        key_entry["rows"] = cast(int, key_entry["rows"]) + 1
    if variant == "mismatching_outcome_filename":
        outcome_entry["filename"] = "other-outcomes.csv"
    if variant == "mismatching_key_content_identity":
        key_entry["content_sha256"] = "0" * 64
    manifest_payloads: list[dict[str, Any]] = [dict(outcome_entry), dict(key_entry)]
    if variant in {"extra_manifest_payload", "extra_release_and_manifest_artifact"}:
        manifest_payloads.append(
            {
                "role": "unexpected_payload",
                "filename": "player_game_logs_2025-26.csv",
                "bytes": 1,
                "rows": 1,
                "sha256": "0" * 64,
            }
        )
    if variant == "duplicate_manifest_role":
        manifest_payloads = [dict(outcome_entry), dict(outcome_entry)]
    if variant == "unknown_manifest_artifact_field":
        manifest_payloads[0]["unexpected"] = "closed-schema violation"
    custodian_identity = {
        "custodian_worker_collision": "worker-1",
        "custodian_releaser_collision": "independent-2",
    }.get(variant, "custodian-1")
    custodian = {
        "role": "data_engineer_custodian",
        "identity": custodian_identity,
        "attested_at": manifest_created_at,
        "attestation": {
            "confirmed_freeze_and_forecast_keys_verified_before_source_access": True,
            "stable_read_only_transaction": True,
            "access_restricted_to_2024_25_and_frozen_forecast_ids": True,
            "credited_zero_second_appearances_retained": True,
            "missing_outcomes_not_fabricated": True,
            "excluded_data_not_accessed_or_included": True,
            "retrospective_capture_manifest_verified": True,
            "package_is_not_release_or_unblind": True,
        },
    }
    source_cutoff = {
        "latest_game_date_represented": (
            "2025-01-02" if variant == "false_source_cutoff" else "2025-01-01"
        ),
        "latest_retrospective_capture_at": (
            "2026-09-12T00:00:00Z"
            if variant == "capture_postdates_package"
            else "2026-09-01T00:00:00Z"
        ),
        "meaning": final._SOURCE_CUTOFF_MEANING,
    }
    if variant == "wrong_source_cutoff_meaning":
        source_cutoff["meaning"] = "Archived as-of forecasts."
    fields_withheld = list(final._FIELDS_WITHHELD)
    if variant == "withheld_schema_contradiction":
        fields_withheld.remove("all 2025-26 season data")
    fields_released = [dict(item) for item in final._FIELDS_RELEASED]
    if variant == "released_schema_contradiction":
        fields_released[0] = {
            "payload_role": "outcome_payload",
            "fields": list(CSV_FIELDS[:-1]),
        }
    manifest_body: dict[str, Any] = {
        "schema_version": final.OUTCOME_MANIFEST_SCHEMA_VERSION,
        "record_type": "sealed_zscore_final_outcome_manifest",
        "experiment_id": backtest.EXPERIMENT_ID,
        "freeze_id": freeze["freeze_id"],
        "created_at": manifest_created_at,
        "dataset_class": "sealed_outcome",
        "purpose": (
            "wrong purpose" if variant == "wrong_outcome_purpose" else final.FINAL_OUTCOME_PURPOSE
        ),
        "season": ("2025-26" if variant == "wrong_outcome_season" else final.OUTCOME_SEASON),
        "source_cutoff": source_cutoff,
        "fields_released": fields_released,
        "fields_withheld": fields_withheld,
        "custodian": custodian,
        "forecast": forecast_binding,
        "payloads": manifest_payloads,
    }
    if variant == "wrong_dataset_class":
        manifest_body["dataset_class"] = "final_holdout_outcome"
    if variant == "missing_source_cutoff":
        manifest_body.pop("source_cutoff")
    if variant == "missing_fields_withheld":
        manifest_body.pop("fields_withheld")
    if variant == "missing_custodian":
        manifest_body.pop("custodian")
    if variant == "incomplete_custodian_attestation":
        cast(dict[str, Any], custodian["attestation"]).pop("stable_read_only_transaction")
    if variant == "wrong_custodian_role":
        custodian["role"] = "quant_worker"
    if variant == "wrong_custodian_attestation_time":
        custodian["attested_at"] = "2026-09-11T20:49:59Z"
    if variant == "unknown_outcome_manifest_field":
        manifest_body["unexpected"] = "closed-schema violation"
    manifest = _finalize_package_manifest(manifest_body)
    if variant == "arbitrary_package_id":
        manifest["package_id"] = "arbitrary-package-id"
    if variant == "non_utc_package_time":
        manifest["created_at"] = "2026-09-11T16:50:00-04:00"
        cast(dict[str, Any], manifest["custodian"])["attested_at"] = manifest["created_at"]
        manifest["content_sha256"] = final.package_content_sha256(manifest)
        manifest["package_id"] = (
            "20260911T205000000000Z-" + cast(str, manifest["content_sha256"])[:16]
        )
    if variant == "wrong_package_content":
        manifest["content_sha256"] = "0" * 64
    if variant == "wrong_package_hash_convention":
        generic = {key: value for key, value in manifest.items() if key != "content_sha256"}
        manifest["content_sha256"] = _canonical_sha256(generic)
        manifest["package_id"] = (
            "20260911T205000000000Z-" + cast(str, manifest["content_sha256"])[:16]
        )
    manifest_path = tmp_path / "outcome-manifest.json"
    _write_json(manifest_path, manifest)
    package_binding: dict[str, Any] = {
        "package_id": manifest["package_id"],
        "content_sha256": manifest["content_sha256"],
        "manifest_filename": manifest_path.name,
        "manifest_bytes": manifest_path.stat().st_size,
        "manifest_file_sha256": _file_sha(manifest_path),
    }
    if variant == "unknown_release_package_field":
        package_binding["unexpected"] = "closed-schema violation"
    if variant == "false_manifest_bytes":
        package_binding["manifest_bytes"] = cast(int, package_binding["manifest_bytes"]) + 1
    if variant == "mismatching_manifest_filename":
        package_binding["manifest_filename"] = "other-manifest.json"
    release_body: dict[str, Any] = {
        "schema_version": final.OUTCOME_RELEASE_SCHEMA_VERSION,
        "record_type": "independent_quant_final_outcome_unblind",
        "release_id": "outcome-release-synthetic-001",
        "experiment_id": (
            "wrong-experiment" if variant == "wrong_release_experiment" else backtest.EXPERIMENT_ID
        ),
        "freeze_id": freeze["freeze_id"],
        "worker_id": "wrong-worker" if variant == "wrong_worker" else "worker-1",
        "created_at": (
            "2026-09-11T20:45:00Z" if variant == "wrong_timestamp_order" else release_created_at
        ),
        "releaser": {
            "role": (
                "model_worker" if variant == "wrong_releaser_role" else "independent_quant_releaser"
            ),
            "identity": ("worker-1" if variant == "worker_self_release" else "independent-2"),
        },
        "disposition": "approved_final_outcome_unblind",
        "package": package_binding,
        "forecast": forecast_binding,
    }
    if variant in {
        "extra_release_artifact",
        "extra_release_and_manifest_artifact",
        "duplicate_release_role",
    }:
        release_body["released_artifacts"] = [
            dict(outcome_entry),
            dict(key_entry),
        ]
    if variant == "unknown_release_artifact_field":
        release_body["unexpected_artifact_declaration"] = {"role": "outcome_payload"}
    release = _seal(release_body)
    release_path = tmp_path / "outcome-release.json"
    _write_json(release_path, release)

    if variant == "tampered_key_manifest":
        key_path.write_text(key_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    if variant == "tampered_forecast":
        forecast_path.write_text(
            forecast_path.read_text(encoding="utf-8") + " ",
            encoding="utf-8",
        )
    if variant == "changed_candidate":
        candidate.write_text("changed after freeze\n", encoding="utf-8")

    return {
        "sealed_forecast_path": forecast_path,
        "accepted_freeze_path": freeze_path,
        "freeze_confirmation_path": confirmation_path,
        "outcome_release_path": release_path,
        "outcome_manifest_path": manifest_path,
        "forecast_key_manifest_path": key_path,
        "outcome_csv_path": outcome_path,
        "current_candidate_files": current_candidate_files,
    }


def test_complete_synthetic_final_evaluation_uses_sealed_forecast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _synthetic_package(tmp_path, monkeypatch)

    result = backtest.run_final_heldout_evaluation(**package)
    metrics = cast(dict[str, Any], result["metrics"])

    assert result["key_accounting"] == {
        "forecast_keys": 5,
        "status_counts": {
            "complete_observation": 2,
            "no_observed_box_score": 1,
            "identity_unresolved": 1,
            "incomplete_required_fields": 1,
        },
        "complete_outcome_rows": 3,
        "complete_observed_players": 2,
        "incomplete_source_rows": 1,
        "unresolved_source_rows": 1,
        "zero_second_rows": 0,
    }
    assert metrics["aggregate_total"]["calibration"]["count"] == 2
    assert result["interpretation"] == {
        "forecast_reconstructed_from_outcomes": False,
        "outcomes_normalized_on_holdout": False,
        "bins_recomputed_after_unblind": False,
        "missing_outcomes_fabricated_as_zero": False,
        "model_gate_passed": False,
    }


def test_complete_observation_allows_coherent_incomplete_source_accounting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _synthetic_package(
        tmp_path,
        monkeypatch,
        variant="coherent_complete_with_incomplete",
    )

    result = backtest.run_final_heldout_evaluation(**package)
    metrics = cast(dict[str, Any], result["metrics"])

    assert cast(dict[str, Any], result["key_accounting"])["complete_observed_players"] == 2
    assert cast(dict[str, Any], result["key_accounting"])["incomplete_source_rows"] == 2
    assert metrics["aggregate_total"]["calibration"]["status"] == "evaluated"


def _final_main_args(package: dict[str, Any], output_path: Path) -> list[str]:
    args = [
        "--sealed-forecast",
        str(package["sealed_forecast_path"]),
        "--accepted-freeze",
        str(package["accepted_freeze_path"]),
        "--freeze-confirmation",
        str(package["freeze_confirmation_path"]),
        "--outcome-release",
        str(package["outcome_release_path"]),
        "--outcome-manifest",
        str(package["outcome_manifest_path"]),
        "--forecast-key-manifest",
        str(package["forecast_key_manifest_path"]),
        "--outcome-csv",
        str(package["outcome_csv_path"]),
    ]
    current_candidate_files = cast(
        dict[str, Path],
        package["current_candidate_files"],
    )
    for label, path in current_candidate_files.items():
        args.extend(("--candidate-file", f"{label}={path}"))
    args.extend(("--output", str(output_path)))
    return args


@pytest.mark.parametrize(
    "variant",
    ["one_complete_player", "zero_aggregate_predictor_variance"],
)
def test_primary_calibration_insufficiency_stops_without_final_result_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    package = _synthetic_package(tmp_path, monkeypatch, variant=variant)
    output_path = tmp_path / "must-not-exist-final-result.json"

    with pytest.raises(
        final.FinalEvaluationProtocolError,
        match=(
            "primary aggregate calibration is unestimable: "
            "not_evaluable_too_few_pairs_or_zero_predictor_variance"
        ),
    ):
        final.main(_final_main_args(package, output_path))

    assert not output_path.exists()


def test_governing_package_identity_known_answer() -> None:
    manifest = {
        "created_at": "2026-09-11T22:30:45.123456Z",
        "dataset_class": "sealed_outcome",
        "payloads": [
            {"filename": "a.csv", "sha256": "0" * 64},
            {"filename": "b.json", "sha256": "f" * 64},
        ],
        "purpose": "known-answer",
    }

    assert final.package_content_sha256(manifest) == (
        "04192807db086eedf5e71580e64d3412cf7b58a9d439a618b9626f3ec3ab266b"
    )
    assert final.package_id_for_manifest(manifest) == ("20260911T223045123456Z-04192807db086eed")


def test_executable_protocol_contains_complete_governing_preregistration() -> None:
    assert set(final.FINAL_EVALUATION_PROTOCOL) == {
        "protocol_version",
        "experiment_id",
        "research_question_and_eligible_cohort",
        "released_development_and_forecast_inputs",
        "feature_set",
        "model_variants",
        "held_out_outcome_and_split",
        "primary_metric_calibration_and_decision_rule",
        "secondary_metrics_and_sensitivities",
        "planned_outputs_and_stop_conditions",
    }
    primary = cast(
        dict[str, Any],
        final.FINAL_EVALUATION_PROTOCOL["primary_metric_calibration_and_decision_rule"],
    )
    assert primary["ideal_references"] == {"intercept": 0.0, "slope": 1.0}
    assert primary["numerical_pass_fail_tolerances"] is None
    released = cast(
        dict[str, Any],
        final.FINAL_EVALUATION_PROTOCOL["released_development_and_forecast_inputs"],
    )
    development_package = cast(dict[str, Any], released["development_package"])
    assert development_package["package_id"] == ("20260911T201744001625Z-b18c64c12a89226a")


@pytest.mark.parametrize(
    "variant",
    [
        "wrong_freeze_experiment",
        "wrong_confirmation_freeze",
        "wrong_release_experiment",
        "wrong_worker",
        "wrong_outcome_purpose",
        "wrong_outcome_season",
        "wrong_releaser_role",
        "wrong_timestamp_order",
        "tampered_key_manifest",
        "tampered_forecast",
        "sealed_scale_semantics_tamper",
        "sealed_vector_semantics_tamper",
        "sealed_bin_semantics_tamper",
        "changed_candidate",
        "missing_forecast_key",
        "duplicate_forecast_key",
        "foreign_outcome_key",
        "invalid_outcome_value",
        "no_complete_keys",
    ],
)
def test_final_evaluation_stops_on_invalid_release_or_accounting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    package = _synthetic_package(tmp_path, monkeypatch, variant=variant)

    with pytest.raises(final.FinalEvaluationProtocolError):
        backtest.run_final_heldout_evaluation(**package)


@pytest.mark.parametrize(
    ("variant", "message"),
    [
        (
            "forecast_freeze_candidate_mismatch",
            "sealed forecast candidate files differ from the accepted freeze",
        ),
        (
            "substituted_executing_file",
            "does not identify the executing implementation",
        ),
        ("missing_candidate_label", "candidate_files labels mismatch"),
        ("extra_candidate_label", "candidate_files labels mismatch"),
        (
            "input_release_after_forecast",
            "forecast input release must be earlier than sealed forecast creation",
        ),
        (
            "forecast_after_freeze",
            "sealed forecast creation must be earlier than the accepted freeze",
        ),
        (
            "freeze_after_confirmation",
            "freeze confirmation must be later than the accepted freeze",
        ),
        (
            "key_before_confirmation",
            "forecast-key manifest must be later than freeze confirmation",
        ),
        (
            "key_after_manifest",
            "forecast-key manifest must not postdate its package manifest",
        ),
        (
            "release_not_after_manifest",
            "outcome release must be later than the sealed outcome manifest",
        ),
        (
            "extra_release_artifact",
            "outcome release keys mismatch",
        ),
        (
            "extra_release_and_manifest_artifact",
            "outcome release keys mismatch",
        ),
        ("duplicate_release_role", "outcome release keys mismatch"),
        (
            "extra_manifest_payload",
            "must contain exactly one outcome payload and one forecast-key manifest",
        ),
        ("duplicate_manifest_role", "repeats role 'outcome_payload'"),
        (
            "unknown_release_package_field",
            "outcome release package keys mismatch",
        ),
        (
            "unknown_release_artifact_field",
            "outcome release keys mismatch",
        ),
        (
            "unknown_manifest_artifact_field",
            "outcome manifest payloads outcome_payload keys mismatch",
        ),
        (
            "unknown_outcome_manifest_field",
            "outcome manifest keys mismatch",
        ),
        (
            "unknown_key_manifest_field",
            "forecast-key manifest keys mismatch",
        ),
        ("false_manifest_bytes", "outcome manifest byte count mismatch"),
        ("false_outcome_bytes", "outcome payload byte count mismatch"),
        ("false_key_rows", "forecast-key manifest row count mismatch"),
        ("mismatching_manifest_filename", "outcome manifest filename mismatch"),
        ("mismatching_outcome_filename", "outcome payload filename mismatch"),
        (
            "mismatching_key_content_identity",
            "forecast-key manifest content binding mismatch",
        ),
        ("wrong_dataset_class", "outcome manifest dataset class mismatch"),
        ("missing_source_cutoff", "outcome manifest keys mismatch"),
        ("missing_fields_withheld", "outcome manifest keys mismatch"),
        ("missing_custodian", "outcome manifest keys mismatch"),
        (
            "incomplete_custodian_attestation",
            "outcome custodian attestation keys mismatch",
        ),
        ("wrong_custodian_role", "outcome custodian has the wrong role"),
        (
            "wrong_custodian_attestation_time",
            "outcome custodian attestation time must equal package creation time",
        ),
        (
            "custodian_worker_collision",
            "custodian, worker, and independent releaser must be distinct",
        ),
        (
            "custodian_releaser_collision",
            "custodian, worker, and independent releaser must be distinct",
        ),
        ("worker_self_release", "worker cannot release its own outcome"),
        (
            "arbitrary_package_id",
            "package_id is not derived from creation time and content",
        ),
        (
            "wrong_package_content",
            "outcome manifest package content identity mismatch",
        ),
        (
            "wrong_package_hash_convention",
            "outcome manifest package content identity mismatch",
        ),
        ("non_utc_package_time", "outcome manifest created_at must use UTC"),
        (
            "false_source_cutoff",
            "source cutoff latest game date disagrees with the emitted outcome payload",
        ),
        (
            "capture_postdates_package",
            "source cutoff retrospective capture must follow the season",
        ),
        (
            "wrong_source_cutoff_meaning",
            "source cutoff meaning mismatch",
        ),
        (
            "wrong_regular_season_date",
            "outside the frozen regular-season window",
        ),
        (
            "wrong_regular_season_game_id",
            "non-2024-25 regular-season NBA game ID",
        ),
        ("wrong_row_season", "outcome row 2 has the wrong season"),
        (
            "withheld_schema_contradiction",
            "outcome manifest withheld-field contract mismatch",
        ),
        (
            "released_schema_contradiction",
            "outcome manifest field contract mismatch",
        ),
        (
            "complete_incomplete_without_missing_fields",
            "forecast-key incomplete rows and missing fields are contradictory",
        ),
        (
            "complete_missing_fields_without_incomplete",
            "forecast-key incomplete rows and missing fields are contradictory",
        ),
        (
            "incomplete_preregistration",
            "accepted freeze protocol differs from code",
        ),
        ("invented_numeric_veto", "accepted freeze protocol differs from code"),
    ],
)
def test_final_evaluation_rejects_resealed_semantic_protocol_violations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
    message: str,
) -> None:
    package = _synthetic_package(tmp_path, monkeypatch, variant=variant)

    with pytest.raises(final.FinalEvaluationProtocolError, match=message):
        backtest.run_final_heldout_evaluation(**package)
