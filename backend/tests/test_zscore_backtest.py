from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import cast

import pytest

from hoops_gm.db.models.enums import CategoryKind
from hoops_gm.valuation import zscore_backtest as backtest
from hoops_gm.valuation.zscore import CategoryScale, ScaleStatus


def _rates(
    player_id: int,
    *,
    games: int = 1,
    points: Fraction = Fraction(10),
    rebounds: Fraction = Fraction(5),
    assists: Fraction = Fraction(3),
    steals: Fraction = Fraction(1),
    blocks: Fraction = Fraction(1),
    threes: Fraction = Fraction(1),
    turnovers: Fraction = Fraction(2),
    field_goals_made: Fraction = Fraction(4),
    field_goals_attempted: Fraction = Fraction(10),
    free_throws_made: Fraction = Fraction(1),
    free_throws_attempted: Fraction = Fraction(2),
) -> backtest.SeasonRates:
    return backtest.SeasonRates(
        player_id=player_id,
        games=games,
        seconds_played=games * 100,
        field_goals_made_per_game=field_goals_made,
        field_goals_attempted_per_game=field_goals_attempted,
        free_throws_made_per_game=free_throws_made,
        free_throws_attempted_per_game=free_throws_attempted,
        three_pointers_made_per_game=threes,
        points_per_game=points,
        rebounds_per_game=rebounds,
        assists_per_game=assists,
        steals_per_game=steals,
        blocks_per_game=blocks,
        turnovers_per_game=turnovers,
    )


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    lines = [",".join(backtest.CSV_FIELDS)]
    lines.extend(",".join(row[field] for field in backtest.CSV_FIELDS) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _row(
    *,
    player_id: int,
    game_id: str,
    season: str,
    seconds: int,
    points: int,
) -> dict[str, str]:
    return {
        "canonical_player_id": str(player_id),
        "nba_game_id": game_id,
        "game_date": "2023-01-01",
        "season": season,
        "season_type": "Regular Season",
        "seconds_played": str(seconds),
        "field_goals_made": "1" if points else "0",
        "field_goals_attempted": "2" if points else "0",
        "free_throws_made": "0",
        "free_throws_attempted": "0",
        "three_pointers_made": "0",
        "points": str(points),
        "rebounds": "0",
        "assists": "0",
        "steals": "0",
        "blocks": "0",
        "turnovers": "0",
    }


def test_load_season_counts_zero_second_credited_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "season.csv"
    _write_csv(
        path,
        [
            _row(
                player_id=1,
                game_id="a",
                season=backtest.FORECAST_SEASON,
                seconds=0,
                points=0,
            ),
            _row(
                player_id=1,
                game_id="b",
                season=backtest.FORECAST_SEASON,
                seconds=600,
                points=10,
            ),
        ],
    )
    monkeypatch.setattr(backtest, "_require_file", lambda *args, **kwargs: None)

    rates = backtest._load_season(
        path,
        season=backtest.FORECAST_SEASON,
        expected_sha256="ignored",
    )

    assert rates.source_rows == 2
    assert rates.zero_second_rows == 1
    assert rates.player_rates[0].games == 2
    assert rates.player_rates[0].points_per_game == 5


def test_load_season_aggregates_player_rows_across_games(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "season.csv"
    _write_csv(
        path,
        [
            _row(
                player_id=7,
                game_id="old-team",
                season=backtest.FORECAST_SEASON,
                seconds=600,
                points=10,
            ),
            _row(
                player_id=7,
                game_id="new-team",
                season=backtest.FORECAST_SEASON,
                seconds=600,
                points=20,
            ),
        ],
    )
    monkeypatch.setattr(backtest, "_require_file", lambda *args, **kwargs: None)

    rates = backtest._load_season(
        path,
        season=backtest.FORECAST_SEASON,
        expected_sha256="ignored",
    )

    assert len(rates.player_rates) == 1
    assert rates.player_rates[0].games == 2
    assert rates.player_rates[0].points_per_game == 15


def test_load_season_refuses_duplicate_player_game(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "season.csv"
    row = _row(
        player_id=1,
        game_id="same",
        season=backtest.FORECAST_SEASON,
        seconds=1,
        points=1,
    )
    _write_csv(path, [row, row])
    monkeypatch.setattr(backtest, "_require_file", lambda *args, **kwargs: None)

    with pytest.raises(backtest.DevelopmentEvidenceError, match="repeats player-game"):
        backtest._load_season(
            path,
            season=backtest.FORECAST_SEASON,
            expected_sha256="ignored",
        )


def test_outcome_component_uses_frozen_forecast_scale() -> None:
    scale = CategoryScale(
        category_key="pts",
        kind=CategoryKind.COUNTING,
        direction=1,
        production_fields=("points_per_game",),
        reference_mean=10.0,
        population_sd=2.0,
        reference_percentage=None,
        status=ScaleStatus.DEFINED,
    )

    assert backtest._outcome_component(_rates(1, points=Fraction(14)), scale) == 2.0


def test_ratio_outcome_component_uses_frozen_reference_percentage() -> None:
    scale = CategoryScale(
        category_key="ft_pct",
        kind=CategoryKind.RATIO,
        direction=1,
        production_fields=("free_throws_made_per_game", "free_throws_attempted_per_game"),
        reference_mean=0.1,
        population_sd=0.2,
        reference_percentage=0.75,
        status=ScaleStatus.DEFINED,
    )
    rates = _rates(
        1,
        free_throws_made=Fraction(4),
        free_throws_attempted=Fraction(5),
    )

    assert backtest._outcome_component(rates, scale) == pytest.approx(0.75)


def test_bootstrap_is_deterministic() -> None:
    predicted = [-2.0, -1.0, 0.0, 1.0, 2.0]
    observed = [-3.0, -1.0, 1.0, 3.0, 5.0]

    first = backtest._bootstrap_interval(predicted, observed, metric_key="example")
    second = backtest._bootstrap_interval(predicted, observed, metric_key="example")

    assert first == second


def test_duplicate_quintile_cuts_collapse_and_equality_enters_upper_bin() -> None:
    forecasts = {1: 0.0, 2: 0.0, 3: 0.0, 4: 1.0, 5: 1.0}
    observations = dict(forecasts)

    report = backtest._bin_report(
        forecast_predictions=forecasts,
        paired_observations=observations,
    )

    assert report["cuts"] == pytest.approx([0.0, 0.4, 1.0])
    bins = report["bins"]
    assert isinstance(bins, list)
    assert bins[0]["forecast_count"] == 0
    assert bins[1]["forecast_count"] == 3
    assert bins[3]["forecast_count"] == 2


def test_missing_outcomes_do_not_change_forecast_bins() -> None:
    forecasts = {1: -1.0, 2: 0.0, 3: 1.0, 4: 2.0, 5: 3.0}
    report = backtest._bin_report(
        forecast_predictions=forecasts,
        paired_observations={1: -2.0, 5: 6.0},
    )

    bins = report["bins"]
    assert isinstance(bins, list)
    assert sum(bin_row["forecast_count"] for bin_row in bins) == 5
    assert sum(bin_row["paired_count"] for bin_row in bins) == 2
    assert sum(bin_row["missing_outcome_count"] for bin_row in bins) == 3


def test_development_evidence_excludes_player_level_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forecast = tuple(
        _rates(
            player_id,
            points=Fraction(player_id),
            rebounds=Fraction(player_id + 1),
            assists=Fraction(player_id + 2),
            steals=Fraction(player_id + 3),
            blocks=Fraction(player_id + 4),
            threes=Fraction(player_id + 5),
            turnovers=Fraction(player_id + 6),
            field_goals_made=Fraction(player_id + 7),
            field_goals_attempted=Fraction(player_id + 17),
            free_throws_made=Fraction(player_id + 8),
            free_throws_attempted=Fraction(player_id + 18),
        )
        for player_id in range(1, 13)
    )
    outcome = forecast[:-1]
    monkeypatch.setattr(
        backtest,
        "_verify_manifest",
        lambda path: {"purpose": "development-only"},
    )
    monkeypatch.setattr(
        backtest,
        "_verify_release",
        lambda path: {"disposition": "approved_development_only_pending_parent_delivery"},
    )

    def fake_load(
        path: Path,
        *,
        season: str,
        expected_sha256: str,
    ) -> backtest.LoadedSeason:
        del path, expected_sha256
        player_rates = forecast if season == backtest.FORECAST_SEASON else outcome
        return backtest.LoadedSeason(
            season=season,
            source_rows=sum(rates.games for rates in player_rates),
            zero_second_rows=0,
            player_rates=player_rates,
        )

    monkeypatch.setattr(backtest, "_load_season", fake_load)

    evidence = backtest.run_development_analysis(
        manifest_path=Path("manifest"),
        forecast_csv_path=Path("forecast"),
        outcome_csv_path=Path("outcome"),
        release_path=Path("release"),
    )
    serialized = json.dumps(evidence, sort_keys=True)
    denominators = cast(dict[str, int], evidence["denominators"])
    interpretation = cast(dict[str, bool], evidence["interpretation"])

    assert denominators["forecast_players"] == 12
    assert denominators["paired_players"] == 11
    assert "player_ids" not in serialized
    assert '"player_id"' not in serialized
    assert interpretation["model_gate_passed"] is False


def test_main_writes_the_requested_output_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        backtest,
        "run_development_analysis",
        lambda **kwargs: {
            "status": "development_only_not_final_model_gate",
            "content_sha256": "abc",
        },
    )

    result = backtest.main(
        [
            "--manifest",
            "manifest.json",
            "--forecast-csv",
            "forecast.csv",
            "--outcome-csv",
            "outcome.csv",
            "--release",
            "release.json",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert json.loads(output.read_text(encoding="utf-8"))["content_sha256"] == "abc"


@pytest.mark.model_backtest
def test_committed_development_evidence_is_integrity_pinned() -> None:
    path = (
        Path(__file__).parent
        / "model_evidence"
        / ("zscore_production_carryforward_v1_development.json")
    )
    evidence = json.loads(path.read_text(encoding="utf-8"))
    claimed_hash = evidence.pop("content_sha256")

    assert backtest._canonical_sha256(evidence) == claimed_hash
    assert evidence["experiment_id"] == backtest.EXPERIMENT_ID
    assert evidence["status"] == "development_only_not_final_model_gate"
    assert evidence["denominators"] == {
        "forecast_players": 539,
        "forecast_source_rows": 25_894,
        "forecast_zero_second_rows": 2,
        "identity_failure_rows": 0,
        "incomplete_forecast_rows": 0,
        "incomplete_outcome_rows": 0,
        "missing_outcome_players": 89,
        "outcome_only_players": 122,
        "outcome_players": 572,
        "outcome_source_rows": 26_401,
        "outcome_zero_second_rows": 8,
        "paired_players": 450,
    }
    aggregate = evidence["metrics"]["aggregate_total"]["calibration"]
    assert aggregate["count"] == 450
    assert aggregate["bootstrap_usable_resamples"] == backtest.BOOTSTRAP_RESAMPLES
    assert aggregate["slope"] == pytest.approx(0.8791825778554082)
    assert evidence["interpretation"]["model_gate_passed"] is False
