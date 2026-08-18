"""Reproduce the live, time-ordered schedule-context blowout backtest."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, cast

from hoops_gm.db.lineage import content_fingerprint
from hoops_gm.ingest.nba import NbaStatsClient, parse_league_game_finder
from hoops_gm.schedule_context.blowout import (
    BlowoutBacktest,
    GameResult,
    evaluate_blowout_model,
    fit_blowout_model,
)

SEASONS = ("2023-24", "2024-25", "2025-26")
VALIDATION_BINS = (3, 4, 5, 6)


@dataclass(frozen=True)
class ValidationCandidate:
    bin_count: int
    brier_score: float
    baseline_brier_score: float
    expected_calibration_error: float


def run_backtest() -> dict[str, object]:
    """Select bin count on 2024-25, then evaluate once on held-out 2025-26."""

    client = NbaStatsClient()
    by_season = {
        season: _game_results(
            parse_league_game_finder(client.league_game_finder(season=season), season=season)
        )
        for season in SEASONS
    }

    validation_candidates: list[ValidationCandidate] = []
    validation_games = by_season["2023-24"] + by_season["2024-25"]
    validation_source = _source_version(by_season["2023-24"])
    for bin_count in VALIDATION_BINS:
        model = fit_blowout_model(
            validation_games,
            training_cutoff=date(2024, 6, 30),
            source_version=validation_source,
            requested_bins=bin_count,
        )
        report = evaluate_blowout_model(
            model,
            validation_games,
            held_out_start=date(2024, 10, 22),
            held_out_end=date(2025, 4, 13),
        )
        validation_candidates.append(
            ValidationCandidate(
                bin_count=bin_count,
                brier_score=report.brier_score,
                baseline_brier_score=report.baseline_brier_score,
                expected_calibration_error=report.expected_calibration_error,
            )
        )
    eligible = [row for row in validation_candidates if row.brier_score <= row.baseline_brier_score]
    if not eligible:
        raise RuntimeError("no validation candidate beats the constant-rate baseline")
    selected = min(
        eligible,
        key=lambda row: (row.expected_calibration_error, row.brier_score),
    )
    selected_bins = selected.bin_count

    final_games = by_season["2024-25"] + by_season["2025-26"]
    training_source = _source_version(by_season["2024-25"])
    final_model = fit_blowout_model(
        final_games,
        training_cutoff=date(2025, 6, 30),
        source_version=training_source,
        requested_bins=selected_bins,
    )
    held_out = evaluate_blowout_model(
        final_model,
        final_games,
        held_out_start=date(2025, 10, 21),
        held_out_end=date(2026, 4, 12),
    )
    return {
        "evidence_version": "schedule-context-blowout-v1",
        "source": "nba_api:LeagueGameFinder",
        "selection": {
            "training_season": "2023-24",
            "validation_season": "2024-25",
            "candidates": [asdict(candidate) for candidate in validation_candidates],
            "selected_bins": selected_bins,
        },
        "final": {
            "training_season": "2024-25",
            "held_out_season": "2025-26",
            "model": _jsonable(asdict(final_model)),
            "backtest": _backtest_dict(held_out),
        },
        "blind_spots": [
            "future injuries and late scratches",
            "lineup and rotation changes",
            "trades and coaching changes",
            "market spreads and front-office intent",
        ],
    }


def _game_results(records: list[Any]) -> list[GameResult]:
    return [
        GameResult(
            game_id=game.nba_game_id,
            game_date=game.game_date,
            home_team_id=game.home_team_id,
            away_team_id=game.away_team_id,
            home_score=game.home_score,
            away_score=game.away_score,
        )
        for game in records
        if game.home_score is not None and game.away_score is not None
    ]


def _source_version(games: list[GameResult]) -> str:
    return content_fingerprint(
        f"{game.game_id}:{game.game_date.isoformat()}:{game.home_team_id}:"
        f"{game.away_team_id}:{game.home_score}:{game.away_score}"
        for game in sorted(games, key=lambda row: (row.game_date, row.game_id))
    )


def _backtest_dict(report: BlowoutBacktest) -> dict[str, object]:
    return cast(dict[str, object], _jsonable(asdict(report)))


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value


def main() -> None:
    print(json.dumps(run_backtest(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
