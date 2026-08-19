from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest

pytestmark = pytest.mark.model_backtest

EVIDENCE = Path(__file__).resolve().parent / "model_evidence" / "reliability_metrics_v1.json"


def _evidence() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(EVIDENCE.read_text(encoding="utf-8")))


def test_reliability_evidence_uses_locked_chronological_partitions() -> None:
    evidence = _evidence()
    protocol = evidence["protocol"]

    assert protocol["pre_registered_partitions"] == {
        "development": "2023-24",
        "selection": "2024-25",
        "final_training": "2024-25",
        "final_holdout": "2025-26",
    }
    assert evidence["selection"]["stage"] == "selection"
    assert evidence["final"]["stage"] == "final_holdout"
    cohorts = evidence["source_cohorts"]
    assert date.fromisoformat(cohorts["2023-24"]["last_game_date"]) < date.fromisoformat(
        cohorts["2024-25"]["first_game_date"]
    )
    assert date.fromisoformat(cohorts["2024-25"]["last_game_date"]) < date.fromisoformat(
        cohorts["2025-26"]["first_game_date"]
    )
    assert {season: row["fingerprint"] for season, row in cohorts.items()} == {
        "2023-24": "d7a762232bbeeef9",
        "2024-25": "d390049e25899542",
        "2025-26": "47765bb5fafb9c09",
    }


def test_source_exclusions_are_bounded_and_auditable() -> None:
    evidence = _evidence()
    maximum_excluded = evidence["protocol"]["maximum_excluded_game_fraction"]
    cohorts = evidence["source_cohorts"]

    assert cohorts["2023-24"]["parsed_game_coverage"] == 1.0
    assert cohorts["2024-25"]["excluded_game_ids"] == [
        "0022400147",
        "0022400621",
        "0022400633",
        "0022401229",
        "0022401230",
    ]
    assert cohorts["2025-26"]["excluded_game_ids"] == [
        "0022500147",
        "0022500578",
        "0022500602",
        "0022501229",
        "0022501230",
    ]
    for cohort in cohorts.values():
        assert cohort["source_game_ids_with_player_logs"] == 1230
        assert cohort["parsed_game_coverage"] >= 1 - maximum_excluded
        assert bool(cohort["excluded_game_ids"]) == bool(cohort["exclusion_reason"])


def test_descriptive_metrics_report_stability_and_percentile_coverage() -> None:
    evidence = _evidence()
    final = evidence["final"]

    assert evidence["runtime_release"]["descriptive_scorecard"] == "accepted"
    assert final["eligible_players"] == 357
    assert set(final["stability"]) == {
        "ast_sd",
        "blk_sd",
        "fg3m_sd",
        "fg_pct_sd",
        "ft_pct_sd",
        "minutes_cv",
        "pts_sd",
        "reb_sd",
        "stl_sd",
        "to_sd",
    }
    for result in final["stability"].values():
        assert result["players"] > 0
        assert result["spearman"] is not None
        assert result["player_specific_mae"] is not None
        assert result["league_median_baseline_mae"] is not None

    for result in final["percentile_coverage"].values():
        assert result["lower_target"] == 0.2
        assert result["upper_target"] == 0.8
        assert (
            sum(band["holdout_observations"] for band in result["sample_size_bands"])
            == result["holdout_observations"]
        )
        assert sum(band["players"] for band in result["sample_size_bands"]) == result["players"]


def test_calibration_sign_reversal_rejects_blowout_suppression() -> None:
    evidence = _evidence()
    selection = evidence["selection"]["blowout_suppression"]
    final = evidence["final"]["blowout_suppression"]

    assert selection["candidate_mae"] < selection["zero_effect_mae"]
    assert selection["mae_improvement_bootstrap_95"][0] <= 0
    assert selection["calibration_sign_reversal"] is True
    assert selection["release_rule_passed"] is False

    assert final["candidate_mae"] < final["zero_effect_mae"]
    assert final["mae_improvement_bootstrap_95"][0] > 0
    assert final["calibration_slope"] > 0
    assert final["sign_stability"] > 0.5
    assert final["calibration_sign_reversal"] is True
    assert final["release_rule_passed"] is False
    assert evidence["runtime_release"]["blowout_suppression"] == "rejected"


def test_incomplete_availability_labels_are_not_misreported_as_calibration() -> None:
    evidence = _evidence()
    availability = evidence["availability_evaluation"]

    assert availability["status"] == "blocked_incomplete_labels"
    assert availability["calibration_reported"] is False
    assert "R35" in availability["reason"]
    assert evidence["runtime_release"]["composite_grade"] == "not_defined"
    assert len(evidence["blind_spots"]) >= 8
