from __future__ import annotations

import json
import math
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest

import hoops_gm.availability.reliability_backtest as backtest
from hoops_gm.availability.reliability import (
    ReliabilityConfig,
    sample_standard_deviation,
    type7_quantile,
    volume_weighted_impact,
)

pytestmark = pytest.mark.model_backtest

EVIDENCE = Path(__file__).resolve().parent / "model_evidence" / "reliability_metrics_v2.json"
HISTORICAL_EVIDENCE = EVIDENCE.with_name("reliability_metrics_v1.json")
_SEASON_DATES = {
    "2023-24": "2023-10-24",
    "2024-25": "2024-10-22",
    "2025-26": "2025-10-21",
}
_SEASON_IDS = {
    "2023-24": "22023",
    "2024-25": "22024",
    "2025-26": "22025",
}
_GAME_IDS = {
    "2023-24": "0022300001",
    "2024-25": "0022400001",
    "2025-26": "0022500001",
}


class _SyntheticEvidenceClient:
    def league_game_finder(self, *, season: str) -> object:
        game_id = _GAME_IDS[season]
        return {
            "parameters": {
                "Season": season,
                "SeasonType": "Regular Season",
            },
            "resultSets": [
                {
                    "name": "LeagueGameFinderResults",
                    "headers": [
                        "GAME_ID",
                        "SEASON_ID",
                        "TEAM_ID",
                        "TEAM_ABBREVIATION",
                        "GAME_DATE",
                        "MATCHUP",
                        "PTS",
                    ],
                    "rowSet": [
                        [
                            game_id,
                            _SEASON_IDS[season],
                            1,
                            "HOM",
                            _SEASON_DATES[season],
                            "HOM vs. AWY",
                            110,
                        ],
                        [
                            game_id,
                            _SEASON_IDS[season],
                            2,
                            "AWY",
                            _SEASON_DATES[season],
                            "AWY @ HOM",
                            100,
                        ],
                    ],
                }
            ],
        }

    def player_game_logs(self, *, season: str) -> object:
        return {
            "resultSets": [
                {
                    "name": "PlayerGameLogs",
                    "headers": [
                        "PLAYER_ID",
                        "GAME_ID",
                        "TEAM_ID",
                        "MIN",
                        "MIN_SEC",
                        "FGM",
                        "FGA",
                        "FG3M",
                        "FTM",
                        "FTA",
                        "PTS",
                        "REB",
                        "AST",
                        "STL",
                        "BLK",
                        "TOV",
                        "PLAYER_NAME",
                    ],
                    "rowSet": [
                        [
                            10,
                            _GAME_IDS[season],
                            1,
                            30,
                            "30:00",
                            5,
                            10,
                            2,
                            4,
                            5,
                            16,
                            5,
                            4,
                            1,
                            1,
                            2,
                            "Synthetic Player",
                        ]
                    ],
                }
            ]
        }


def _evidence() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(EVIDENCE.read_text(encoding="utf-8")))


def test_retired_v1_evidence_remains_integrity_pinned() -> None:
    payload = json.loads(HISTORICAL_EVIDENCE.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    assert sha256(canonical).hexdigest() == (
        "254eac10d358f87a4e21aab4f88d9204eba829cc7c461b246a73aa5861707911"
    )


def _expected_protocol() -> dict[str, object]:
    return {
        "declared_partitions": {
            "development": "2023-24",
            "selection": "2024-25",
            "final_training": "2024-25",
            "final_holdout": "2025-26",
        },
        "minimum_player_games": 20,
        "stability_metrics": [
            "spearman",
            "player_specific_mae",
            "training_league_median_baseline_mae",
        ],
        "minimum_blowout_games": 5,
        "minimum_non_blowout_games": 10,
        "blowout_margin": 15,
        "blowout_effect": (
            "mean player minutes in margin>=15 games minus mean player minutes in all other games"
        ),
        "lower_percentile": 0.2,
        "upper_percentile": 0.8,
        "percentile_player_eligibility": (
            "all players in both adjacent seasons with non-empty training and "
            "holdout values for the category; no minimum-game threshold"
        ),
        "percentile_coverage_rule": (
            "fraction of holdout values <= the player's training Type-7 quantile"
        ),
        "calibration_bin_count": 4,
        "calibration_bin_method": "equal-count bins sorted by predicted delta",
        "bootstrap_resamples": 2000,
        "bootstrap_seed": 250119,
        "bootstrap_unit": "player-level paired MAE improvement",
        "bootstrap_interval_quantiles": [0.025, 0.975],
        "maximum_source_game_id_mismatch_fraction": 0.01,
        "source_game_id_coverage_rule": (
            "fail if either player-log-only ids / player-log ids or "
            "parsed-game-only ids / parsed-game ids exceeds the ceiling"
        ),
        "percentile_sample_size_bands": [
            {"label": "1-19", "minimum": 1, "maximum": 19},
            {"label": "20-39", "minimum": 20, "maximum": 39},
            {"label": "40-59", "minimum": 40, "maximum": 59},
            {"label": "60+", "minimum": 60, "maximum": None},
        ],
        "blowout_release_rule": (
            "both chronological transitions must pass: candidate MAE < "
            "zero-effect MAE; player-block bootstrap 95% improvement interval "
            "lower bound > 0; calibration slope > 0; no calibration-bin sign "
            "reversal; sign stability > 0.5"
        ),
    }


def test_reliability_evidence_is_bound_to_literal_protocol_and_runtime() -> None:
    evidence = _evidence()

    assert backtest.reliability_backtest_protocol() == _expected_protocol()
    assert evidence["protocol"] == _expected_protocol()
    assert (
        evidence["protocol_version"]
        == backtest.reliability_backtest_protocol_version()
        == "b055dfbf67bb5127"
    )
    assert (
        evidence["runtime_derivation_version"]
        == ReliabilityConfig().derivation_version
        == "f4ce099a5e84e0f8"
    )
    assert evidence["protocol_provenance"]["immutable_repository_preregistration"] is False


def test_backtest_runner_executes_end_to_end_against_parsed_source_contracts() -> None:
    evidence = backtest.run_backtest(_SyntheticEvidenceClient())

    assert evidence["protocol"] == _expected_protocol()
    assert evidence["runtime_derivation_version"] == ReliabilityConfig().derivation_version
    cohorts = cast(dict[str, dict[str, Any]], evidence["source_cohorts"])
    for cohort in cohorts.values():
        assert cohort["parsed_completed_games"] == 1
        assert cohort["source_game_ids_with_player_logs"] == 1
        assert cohort["parsed_game_coverage_of_player_logs"] == 1
        assert cohort["player_log_coverage_of_parsed_games"] == 1
    final = cast(dict[str, Any], evidence["final"])
    assert final["eligible_players"] == 0
    assert final["percentile_players_considered"] == 1
    percentile_coverage = cast(dict[str, dict[str, Any]], final["percentile_coverage"])
    for result in percentile_coverage.values():
        sparse = next(band for band in result["sample_size_bands"] if band["label"] == "1-19")
        assert sparse["players"] == 1
        assert sparse["holdout_observations"] == 1
    assert evidence["runtime_release"] == {
        "blowout_suppression": "rejected",
        "blowout_suppression_reason": (
            "selection and/or final holdout failed the predeclared rule"
        ),
        "composite_grade": "not_defined",
    }


def test_reliability_evidence_uses_chronological_partitions() -> None:
    evidence = _evidence()

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
        "2023-24": "4ecfda8e09653886",
        "2024-25": "34a836176d535b4b",
        "2025-26": "b7301976c833738f",
    }


def test_source_game_id_coverage_is_complete_and_auditable() -> None:
    evidence = _evidence()
    cohorts = evidence["source_cohorts"]

    for cohort in cohorts.values():
        assert cohort["parsed_completed_games"] == 1230
        assert cohort["source_game_ids_with_player_logs"] == 1230
        for field in (
            "parsed_game_coverage_of_player_logs",
            "player_log_coverage_of_parsed_games",
        ):
            assert cohort[field] == 1.0
        assert cohort["player_log_only_game_ids"] == []
        assert cohort["player_log_only_reason"] is None
        assert cohort["parsed_game_only_ids"] == []
        assert cohort["parsed_game_only_reason"] is None
        assert cohort["excluded_player_game_logs"] == 0


def test_source_game_id_guard_rejects_truncation_in_either_direction() -> None:
    full = {f"game-{index}" for index in range(100)}
    truncated = {f"game-{index}" for index in range(98)}

    with pytest.raises(RuntimeError, match="parsed games lack all player logs"):
        backtest._validated_source_game_id_mismatches(
            season="test",
            parsed_game_ids=full,
            player_log_game_ids=truncated,
        )
    with pytest.raises(RuntimeError, match="PlayerGameLogs game ids lack"):
        backtest._validated_source_game_id_mismatches(
            season="test",
            parsed_game_ids=truncated,
            player_log_game_ids=full,
        )

    player_log_only, parsed_game_only = backtest._validated_source_game_id_mismatches(
        season="test",
        parsed_game_ids=full,
        player_log_game_ids=full - {"game-99"},
    )
    assert player_log_only == ()
    assert parsed_game_only == ("game-99",)


def test_descriptive_metrics_report_stability_and_percentile_coverage() -> None:
    evidence = _evidence()
    final = evidence["final"]

    assert final["eligible_players"] == 358
    assert final["percentile_players_considered"] == 464
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
        sparse = next(band for band in result["sample_size_bands"] if band["label"] == "1-19")
        assert sparse["players"] > 0
        assert sparse["holdout_observations"] > 0


def test_statistical_helpers_have_known_answers() -> None:
    assert sample_standard_deviation([10, 20, 30, 40, 50]) == pytest.approx(math.sqrt(250))
    assert type7_quantile([10, 20, 30, 40, 50], 0.2) == 18
    assert type7_quantile([10, 20, 30, 40, 50], 0.8) == 42
    assert volume_weighted_impact(9, 10, 0.5) == 4
    assert backtest._spearman([1, 2, 2, 4], [4, 1, 1, 0]) == -1
    assert backtest._linear_calibration([1, 2, 3, 4], [2, 4, 6, 8]) == (
        2,
        0,
    )
    assert backtest._calibration_bins([1, 2, 3, 4], [2, 4, 6, 8]) == [
        {
            "predicted_mean_delta_minutes": 1,
            "observed_mean_delta_minutes": 2,
            "players": 1,
        },
        {
            "predicted_mean_delta_minutes": 2,
            "observed_mean_delta_minutes": 4,
            "players": 1,
        },
        {
            "predicted_mean_delta_minutes": 3,
            "observed_mean_delta_minutes": 6,
            "players": 1,
        },
        {
            "predicted_mean_delta_minutes": 4,
            "observed_mean_delta_minutes": 8,
            "players": 1,
        },
    ]
    assert backtest._bootstrap_mean_interval([0, 1]) == (0, 1)
    assert backtest._coverage_summary([(1, 3, (0, 1, 2, 4))]) == {
        "players": 1,
        "holdout_observations": 4,
        "lower_target": 0.2,
        "lower_observed": 0.5,
        "upper_target": 0.8,
        "upper_observed": 0.75,
    }


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
