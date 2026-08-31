from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from hoops_gm.availability.calibration import (
    BinningScheme,
    CalibrationObservation,
    Provenance,
    build_calibration_report,
)

pytestmark = pytest.mark.model_backtest

EVIDENCE = Path(__file__).resolve().parent / "model_evidence" / "injury_status_conversion_v1.json"
IMPLEMENTATION = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "hoops_gm"
    / "availability"
    / "injury_status_conversion.py"
)
ADMISSIBILITY = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "adapters"
    / "nba-injury-report-cohort-admissibility-2025-26.json"
)
MODEL_CARD = Path(__file__).resolve().parents[2] / "docs" / "models" / "injury-status-conversion.md"


def _evidence() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(EVIDENCE.read_text(encoding="utf-8")))


def _lf_sha256(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def test_frozen_evidence_and_implementation_are_integrity_pinned() -> None:
    evidence = _evidence()

    assert _lf_sha256(EVIDENCE) == (
        "f9e4ace0aae41ef52cb3ef851e4630bc094f64ff1d79f3b01ba2b8c3963ded69"
    )
    implementation_digest = _lf_sha256(IMPLEMENTATION)
    assert (
        implementation_digest
        == evidence["inputs"]["committed_inputs"]["implementation"]["sha256_lf_normalized"]
    )
    assert (
        implementation_digest == "f4b16a9909a6e8e0d080da550c1ea3d8cb812132d8a61393df665bf7e643c14c"
    )
    assert evidence["model_version"] == "injury-status-conversion-v2-scoped-a-v1"
    assert evidence["inputs"]["prepared_merged_store"] == {
        "bytes": 50_941_952,
        "sha256": "5fe6110e8c89b91a22a78563111b982eda003c5fe53990143e57e73949554a04",
        "store": "cohort-merged-2025-26.db",
    }


def test_selection_and_refit_remain_bound_to_the_frozen_partitions() -> None:
    evidence = _evidence()
    selection = evidence["selection"]

    assert evidence["split"]["game_dates"] == {
        "development": 82,
        "selection": 41,
        "held_out": 41,
    }
    assert evidence["split"]["held_out"] == ["2026-03-02", "2026-04-12"]
    assert selection["candidate_order"] == [
        "global_jeffreys",
        "three_band_jeffreys",
        "five_status_jeffreys",
    ]
    assert selection["minimum_improvement_to_advance"] == 0.005
    assert selection["selected"] == "three_band_jeffreys"
    assert selection["candidates"]["three_band_jeffreys"]["selection_brier"] == pytest.approx(
        0.037157039566065364
    )
    assert selection["candidates"]["five_status_jeffreys"][
        "improvement_over_incumbent"
    ] == pytest.approx(-0.00018040910042424474)
    assert evidence["final_fit"]["training_partitions"] == ["development", "selection"]


def test_final_probabilities_recompute_from_the_published_jeffreys_counts() -> None:
    groups = _evidence()["final_fit"]["selected_model"]["groups"]

    for group in groups.values():
        expected = (group["plays"] + 0.5) / (group["observations"] + 1)
        assert group["probability"] == pytest.approx(expected)


def test_primary_calibration_recomputes_from_the_published_bins() -> None:
    primary = _evidence()["held_out_primary"]["calibration"]
    rows: list[CalibrationObservation] = []
    for bin_index, published_bin in enumerate(primary["bins"]):
        for row_index in range(published_bin["observations"]):
            rows.append(
                CalibrationObservation(
                    observation_id=f"{bin_index}:{row_index}",
                    predicted=published_bin["predicted_mean"],
                    played=row_index < published_bin["plays"],
                )
            )

    recomputed = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )

    assert recomputed.observations == primary["observations"] == 3_940
    assert recomputed.plays == primary["plays"] == 653
    assert recomputed.brier_score == pytest.approx(primary["brier_score"])
    assert recomputed.calibration_in_the_large == pytest.approx(primary["calibration_in_the_large"])
    assert recomputed.expected_calibration_error == pytest.approx(
        primary["expected_calibration_error"]
    )
    assert recomputed.maximum_calibration_error == pytest.approx(
        primary["maximum_calibration_error"]
    )
    assert recomputed.log_loss == pytest.approx(primary["log_loss"])
    assert recomputed.bins_below_population_floor == ()
    assert recomputed.bins_outside_wilson_interval == ()


def test_all_and_only_the_eight_frozen_activation_conditions_pass() -> None:
    evidence = _evidence()
    activation = evidence["activation"]
    conditions = activation["conditions"]

    assert activation["default"] == "veto"
    assert activation["conditions_present"] == 8
    assert [condition["number"] for condition in conditions] == list(range(1, 9))
    assert all(condition["passed"] for condition in conditions)
    assert activation["eligible_for_runtime_activation"] is True
    assert activation["condition_9_exists"] is False
    assert evidence["cohort_reproduction"]["all_match"] is True


def test_primary_evidence_reports_calibration_and_the_paired_baseline() -> None:
    primary = _evidence()["held_out_primary"]
    calibration = primary["calibration"]
    comparison = primary["paired_brier_against_global"]

    assert calibration["brier_score"] == pytest.approx(0.037644920084708336)
    assert calibration["calibration_in_the_large"] == pytest.approx(0.002713100761360887)
    assert calibration["expected_calibration_error"] == pytest.approx(0.00629940823160707)
    assert comparison == {
        "baseline_brier": pytest.approx(0.13827903556658858),
        "candidate_beats_baseline": True,
        "candidate_brier": pytest.approx(0.037644920084708336),
        "interval_caveat": (
            "resampled by observation id; not valid against within-player "
            "or within-game correlation"
        ),
        "interval_high": pytest.approx(-0.09238916108929127),
        "interval_low": pytest.approx(-0.10877328091715036),
        "mean_difference": pytest.approx(-0.10063411548188023),
        "resamples": 5_000,
        "seed": 250_119,
    }


def test_scoped_change_a_is_present_and_non_gating() -> None:
    sensitivity = _evidence()["sensitivities"]["v3_change_a_report_era"]

    assert sensitivity["pooled_result_remains_primary"] is True
    assert sensitivity["enters_v2_section_8"] is False
    assert sensitivity["standing"] == "v3 Change A, scoped acceptance 2026-08-29"
    assert set(sensitivity["refits"]) == {
        "legacy_hourly",
        "short_lead_fifteen_minute",
    }
    assert (
        sensitivity["refits"]["legacy_hourly"]["calibration"]["bins_outside_wilson_interval"] == []
    )
    assert sensitivity["refits"]["short_lead_fifteen_minute"]["calibration"][
        "bins_outside_wilson_interval"
    ] == ["p=0.580508", "p=0.836508"]
    for refit in sensitivity["refits"].values():
        assert refit["training_partition"] == "development only"
        assert refit["same_held_out_date_partition"] is True
        assert refit["held_out_observations_total"] == 3_940
        assert refit["statuses_reported_as_counts_only"] == []
        assert refit["gating"] is False


def test_change_b_and_every_subgroup_remain_display_only() -> None:
    evidence = _evidence()
    informative = evidence["display_only_subgroups"]["informative_statuses"]
    health = evidence["display_only_subgroups"]["health_reason_proxy"]

    assert evidence["governing_protocol"]["condition_9_exists"] is False
    assert evidence["governing_protocol"]["v3_change_b"] == (
        "rejected as an activation gate; display-only"
    )
    assert informative["calibration"]["observations"] == 510
    assert informative["calibration"]["bins_outside_wilson_interval"] == ["p=0.858560"]
    assert informative["gating"] is False
    assert informative["condition_9_exists"] is False
    assert health["calibration"]["observations"] == 2_941
    assert health["gating"] is False
    assert all(
        row["display_only_non_gating"]
        for row in evidence["held_out_primary"]["per_status"].values()
    )


def test_evidence_records_the_blind_break_and_explicit_blind_spots() -> None:
    evidence = _evidence()

    assert evidence["blind_break"] == {
        "deviations_from_frozen_estimator_split_or_thresholds": [],
        "held_out_evaluations": 1,
        "tuning_after_held_out_access": False,
    }
    assert len(evidence["cannot_see"]) >= 7


def test_shutdown_window_limitation_reaches_the_model_card_verbatim() -> None:
    admissibility: dict[str, Any] = json.loads(ADMISSIBILITY.read_text(encoding="utf-8"))
    limitation = admissibility["section_2_admissibility"]["limitations_that_the_count_cannot_see"][
        0
    ]
    quoted = [
        line.removeprefix("> ")
        for line in MODEL_CARD.read_text(encoding="utf-8").splitlines()
        if line.startswith("> THE HOLDOUT IS THE END-OF-SEASON")
    ]

    assert quoted == [limitation]
