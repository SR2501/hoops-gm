from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import cast

import pytest

from hoops_gm.valuation import zscore_forecast as forecast
from hoops_gm.valuation.zscore_backtest import (
    LoadedSeason,
    SeasonRates,
    _canonical_sha256,
)


def _rates(player_id: int) -> SeasonRates:
    return SeasonRates(
        player_id=player_id,
        games=1,
        seconds_played=600,
        field_goals_made_per_game=Fraction(player_id + 4),
        field_goals_attempted_per_game=Fraction(player_id + 14),
        free_throws_made_per_game=Fraction(player_id + 5),
        free_throws_attempted_per_game=Fraction(player_id + 15),
        three_pointers_made_per_game=Fraction(player_id),
        points_per_game=Fraction(player_id + 10),
        rebounds_per_game=Fraction(player_id + 3),
        assists_per_game=Fraction(player_id + 2),
        steals_per_game=Fraction(player_id, 10),
        blocks_per_game=Fraction(player_id, 20),
        turnovers_per_game=Fraction(player_id + 1),
    )


def test_frozen_bins_collapse_duplicates_and_retain_exact_assignments() -> None:
    result = forecast._frozen_bins({1: 0.0, 2: 0.0, 3: 0.0, 4: 1.0, 5: 1.0})

    assert result["cuts"] == ["0", "0.39999999999999991", "1"]
    assert result["counts"] == [0, 3, 0, 2]
    assert result["assignments"] == [
        {"player_id": 1, "bin": 1},
        {"player_id": 2, "bin": 1},
        {"player_id": 3, "bin": 1},
        {"player_id": 4, "bin": 3},
        {"player_id": 5, "bin": 3},
    ]


def test_candidate_file_parser_refuses_duplicate_labels() -> None:
    with pytest.raises(forecast.FinalForecastInputError, match="duplicate"):
        forecast._parse_candidate_files(["runtime=a.py", "runtime=b.py"])


def test_build_final_forecast_is_input_only_and_content_addressed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text("candidate\n", encoding="utf-8")
    rates = tuple(_rates(player_id) for player_id in range(1, 13))
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
            "created_at": "2026-09-11T20:00:00Z",
        },
    )
    monkeypatch.setattr(
        forecast,
        "_load_season",
        lambda *args, **kwargs: LoadedSeason(
            season=forecast.INPUT_SEASON,
            source_rows=forecast.INPUT_PAYLOAD_ROWS,
            zero_second_rows=forecast.INPUT_ZERO_SECOND_ROWS,
            player_rates=rates,
        ),
    )

    artifact = forecast.build_final_forecast_artifact(
        manifest_path=Path("manifest"),
        forecast_csv_path=Path("forecast"),
        release_path=Path("release"),
        candidate_files={"runtime": candidate},
        created_at="2026-09-11T20:10:00Z",
    )
    serialized = json.dumps(artifact, sort_keys=True)
    claimed_hash = artifact.pop("content_sha256")
    cohort = cast(dict[str, object], artifact["cohort"])
    runtime = cast(dict[str, object], artifact["runtime"])
    replacement = cast(dict[str, object], runtime["replacement"])
    vector = cast(list[object], artifact["forecast_vector"])

    assert _canonical_sha256(artifact) == claimed_hash
    assert cohort["players"] == 12
    assert artifact["outcome_data_accessed"] is False
    assert artifact["outcome_presence_accessed"] is False
    assert replacement["state"] == ("unavailable_insufficient_projected_pool")
    assert len(vector) == 12
    assert "outcome_rows" not in serialized
    assert "2025-26" not in serialized


def test_main_writes_private_prefreeze_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "prefreeze.json"
    monkeypatch.setattr(
        forecast,
        "build_final_forecast_artifact",
        lambda **kwargs: {
            "status": "draft_prefreeze_pending_independent_confirmation",
            "content_sha256": "artifact",
            "forecast_vector_sha256": "vector",
        },
    )

    result = forecast.main(
        [
            "--manifest",
            "manifest.json",
            "--forecast-csv",
            "forecast.csv",
            "--release",
            "release.json",
            "--candidate-file",
            "runtime=runtime.py",
            "--created-at",
            "2026-09-11T20:10:00Z",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "content_sha256": "artifact",
        "forecast_vector_sha256": "vector",
        "status": "draft_prefreeze_pending_independent_confirmation",
    }
