from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from hoops_gm.schedule_context import RELEASED_BLOWOUT_MODEL_VERSION, load_blowout_release
from hoops_gm.schedule_context import release as release_registry

pytestmark = pytest.mark.model_backtest

EVIDENCE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "hoops_gm"
    / "schedule_context"
    / "releases"
    / "schedule_context_blowout_v1.json"
)


def test_schedule_context_blowout_has_a_real_time_ordered_holdout() -> None:
    evidence: dict[str, Any] = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    final = evidence["final"]
    backtest = final["backtest"]

    assert evidence["source"] == "nba_api:LeagueGameFinder"
    assert evidence["season_type"] == "regular"
    assert final["training_season"] == "2024-25"
    assert final["held_out_season"] == "2025-26"
    assert date.fromisoformat(backtest["training_cutoff"]) < date.fromisoformat(
        backtest["held_out_start"]
    )
    assert backtest["held_out_examples"] == 1225
    assert sum(row["count"] for row in backtest["calibration_bins"]) == 1225
    assert final["source_cohorts"]["training"] == {
        "completed_games": 1225,
        "fingerprint": "ea3f00ea22a4d703",
        "first_game_date": "2024-10-22",
        "first_game_id": "0022400061",
        "last_game_date": "2025-04-13",
        "last_game_id": "0022401200",
    }
    assert final["source_cohorts"]["held_out"] == {
        "completed_games": 1225,
        "fingerprint": "e992a314295c442a",
        "first_game_date": "2025-10-21",
        "first_game_id": "0022500001",
        "last_game_date": "2026-04-12",
        "last_game_id": "0022501200",
    }


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


def test_production_release_loader_is_bound_to_the_gate_evidence() -> None:
    evidence: dict[str, Any] = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    release = load_blowout_release()

    assert release.evidence_version == evidence["evidence_version"]
    assert release.model.version == evidence["final"]["model"]["version"]
    assert (
        release.training_source_fingerprint
        == (evidence["final"]["source_cohorts"]["training"]["fingerprint"])
    )
    assert (
        release.holdout_source_fingerprint
        == (evidence["final"]["source_cohorts"]["held_out"]["fingerprint"])
    )


def test_production_release_loader_rejects_an_unpinned_artifact_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filename, _digest = release_registry._RELEASE_FILES[RELEASED_BLOWOUT_MODEL_VERSION]
    monkeypatch.setitem(
        release_registry._RELEASE_FILES,
        RELEASED_BLOWOUT_MODEL_VERSION,
        (filename, "0" * 64),
    )

    with pytest.raises(RuntimeError, match="does not match its pinned digest"):
        load_blowout_release()
