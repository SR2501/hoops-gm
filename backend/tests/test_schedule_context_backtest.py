from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.model_backtest

EVIDENCE = Path(__file__).resolve().parent / "model_evidence" / "schedule_context_blowout_v1.json"


def test_schedule_context_blowout_has_a_real_time_ordered_holdout() -> None:
    evidence: dict[str, Any] = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    final = evidence["final"]
    backtest = final["backtest"]

    assert evidence["source"] == "nba_api:LeagueGameFinder"
    assert final["training_season"] == "2024-25"
    assert final["held_out_season"] == "2025-26"
    assert date.fromisoformat(backtest["training_cutoff"]) < date.fromisoformat(
        backtest["held_out_start"]
    )
    assert backtest["held_out_examples"] == 1225
    assert sum(row["count"] for row in backtest["calibration_bins"]) == 1225


def test_locked_blowout_model_beats_baseline_and_meets_calibration_limit() -> None:
    evidence: dict[str, Any] = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    backtest = evidence["final"]["backtest"]

    assert backtest["brier_score"] < backtest["baseline_brier_score"]
    assert backtest["expected_calibration_error"] <= 0.04


def test_bin_count_was_selected_before_the_final_holdout() -> None:
    evidence: dict[str, Any] = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    selection = evidence["selection"]
    eligible = [
        row for row in selection["candidates"] if row["brier_score"] <= row["baseline_brier_score"]
    ]
    best = min(
        eligible,
        key=lambda row: (row["expected_calibration_error"], row["brier_score"]),
    )

    assert selection["validation_season"] == "2024-25"
    assert evidence["final"]["held_out_season"] == "2025-26"
    assert selection["selected_bins"] == best["bin_count"] == 3


def test_model_evidence_states_blind_spots() -> None:
    evidence: dict[str, Any] = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    assert len(evidence["blind_spots"]) >= 4
