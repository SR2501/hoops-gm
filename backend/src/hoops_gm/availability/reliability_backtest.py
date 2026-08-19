"""Reproduce the chronological reliability-metrics evidence study.

The partitions and release rule are constants in this module so the final
2025-26 holdout cannot be used to choose them after the result is known.
Availability and B2B rates are deliberately absent: season-level game logs do
not provide the complete opportunity labels R35 requires.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Protocol

from hoops_gm.availability.reliability import (
    RELIABILITY_COUNTING_CATEGORIES,
    RELIABILITY_RATIO_CATEGORIES,
    ReliabilityConfig,
    sample_standard_deviation,
    type7_quantile,
    volume_weighted_impact,
)
from hoops_gm.db.lineage import content_fingerprint
from hoops_gm.ingest.nba import (
    NbaGameRecord,
    NbaStatsClient,
    PlayerBoxScoreRecord,
    parse_league_game_finder,
    parse_player_game_logs,
)

DEVELOPMENT_SEASON: Final = "2023-24"
SELECTION_SEASON: Final = "2024-25"
FINAL_TRAINING_SEASON: Final = "2024-25"
FINAL_HOLDOUT_SEASON: Final = "2025-26"
SEASONS: Final = (
    DEVELOPMENT_SEASON,
    SELECTION_SEASON,
    FINAL_HOLDOUT_SEASON,
)

MINIMUM_PLAYER_GAMES: Final = 20
MINIMUM_BLOWOUT_GAMES: Final = 5
MINIMUM_NON_BLOWOUT_GAMES: Final = 10
BLOWOUT_MARGIN: Final = 15
LOWER_PERCENTILE: Final = 0.20
UPPER_PERCENTILE: Final = 0.80
CALIBRATION_BIN_COUNT: Final = 4
BOOTSTRAP_RESAMPLES: Final = 2000
BOOTSTRAP_SEED: Final = 250119
MAX_SOURCE_GAME_ID_MISMATCH_FRACTION: Final = 0.01
PERCENTILE_SAMPLE_SIZE_BANDS: Final = (
    ("1-19", 1, 19),
    ("20-39", 20, 39),
    ("40-59", 40, 59),
    ("60+", 60, None),
)


@dataclass(frozen=True)
class HistoricalPlayerGame:
    player_id: int
    game_id: str
    game_date: date
    is_blowout: bool
    seconds_played: int | None
    field_goals_made: int | None
    field_goals_attempted: int | None
    three_pointers_made: int | None
    free_throws_made: int | None
    free_throws_attempted: int | None
    points: int | None
    rebounds: int | None
    assists: int | None
    steals: int | None
    blocks: int | None
    turnovers: int | None


@dataclass(frozen=True)
class SeasonCohort:
    season: str
    games: tuple[NbaGameRecord, ...]
    logs: tuple[HistoricalPlayerGame, ...]
    player_log_game_ids: int
    player_log_only_game_ids: tuple[str, ...]
    parsed_game_only_ids: tuple[str, ...]
    excluded_player_game_logs: int
    fingerprint: str


@dataclass(frozen=True)
class PlayerSeasonSummary:
    player_id: int
    game_count: int
    metric_values: dict[str, float | None]
    category_values: dict[str, tuple[float, ...]]
    lower_quantiles: dict[str, float]
    upper_quantiles: dict[str, float]
    blowout_delta_minutes: float | None
    blowout_games: int
    non_blowout_games: int


class ReliabilityBacktestClient(Protocol):
    def league_game_finder(self, *, season: str) -> object: ...

    def player_game_logs(self, *, season: str) -> object: ...


def run_backtest(client: ReliabilityBacktestClient | None = None) -> dict[str, object]:
    """Run development/selection once, then the locked final holdout."""

    protocol = reliability_backtest_protocol()
    nba = client or NbaStatsClient()
    cohorts = {season: _load_season(nba, season) for season in SEASONS}
    summaries = {season: _season_summaries(cohort) for season, cohort in cohorts.items()}
    selection = _evaluate_pair(
        summaries[DEVELOPMENT_SEASON],
        summaries[SELECTION_SEASON],
        stage="selection",
    )
    final = _evaluate_pair(
        summaries[FINAL_TRAINING_SEASON],
        summaries[FINAL_HOLDOUT_SEASON],
        stage="final_holdout",
    )
    selection_blowout = _object_dict(selection["blowout_suppression"])
    final_blowout = _object_dict(final["blowout_suppression"])
    blowout_released = bool(
        selection_blowout["release_rule_passed"] and final_blowout["release_rule_passed"]
    )
    return {
        "evidence_version": "reliability-metrics-v1",
        "source": "nba_api:LeagueGameFinder+PlayerGameLogs",
        "season_type": "regular",
        "runtime_derivation_version": ReliabilityConfig().derivation_version,
        "protocol": protocol,
        "protocol_version": reliability_backtest_protocol_version(),
        "protocol_provenance": {
            "status": "coordinator_approved_before_successful_outcome_run",
            "immutable_repository_preregistration": False,
            "limitation": (
                "the implementation and evidence first enter git together, so the "
                "repository cannot independently prove prospective registration"
            ),
        },
        "source_cohorts": {season: _cohort_metadata(cohorts[season]) for season in SEASONS},
        "selection": selection,
        "final": final,
        "availability_evaluation": {
            "status": "blocked_incomplete_labels",
            "reason": (
                "PlayerGameLogs contains played games only. The observation ledger "
                "still lacks authoritative historical roster intervals and per-game "
                "ingestion-completeness evidence, so R35 forbids treating silence as absence."
            ),
            "calibration_reported": False,
        },
        "runtime_release": {
            "blowout_suppression": "accepted" if blowout_released else "rejected",
            "blowout_suppression_reason": (
                "selection and final holdout both passed"
                if blowout_released
                else "selection and/or final holdout failed the predeclared rule"
            ),
            "composite_grade": "not_defined",
        },
        "blind_spots": [
            "full absences represented only by missing participation rows",
            "historical roster membership and per-game participation completeness",
            "trades, coaching changes, and role or rotation changes",
            "undisclosed injuries, personal matters, and front-office intent",
            "DNP reasons that relabel rest or load management as minor ailments",
            "final margin is an outcome, not a causal player-level garbage-time treatment",
            "survivorship among players with enough games in adjacent seasons",
            "rookies and players returning from long absences",
        ],
    }


def reliability_backtest_protocol() -> dict[str, object]:
    """Return every declared evidence choice as a fingerprintable contract."""

    return {
        "declared_partitions": {
            "development": DEVELOPMENT_SEASON,
            "selection": SELECTION_SEASON,
            "final_training": FINAL_TRAINING_SEASON,
            "final_holdout": FINAL_HOLDOUT_SEASON,
        },
        "minimum_player_games": MINIMUM_PLAYER_GAMES,
        "stability_metrics": [
            "spearman",
            "player_specific_mae",
            "training_league_median_baseline_mae",
        ],
        "minimum_blowout_games": MINIMUM_BLOWOUT_GAMES,
        "minimum_non_blowout_games": MINIMUM_NON_BLOWOUT_GAMES,
        "blowout_margin": BLOWOUT_MARGIN,
        "blowout_effect": (
            "mean player minutes in margin>=15 games minus mean player minutes in all other games"
        ),
        "lower_percentile": LOWER_PERCENTILE,
        "upper_percentile": UPPER_PERCENTILE,
        "percentile_player_eligibility": (
            "all players in both adjacent seasons with non-empty training and "
            "holdout values for the category; no minimum-game threshold"
        ),
        "percentile_coverage_rule": (
            "fraction of holdout values <= the player's training Type-7 quantile"
        ),
        "calibration_bin_count": CALIBRATION_BIN_COUNT,
        "calibration_bin_method": "equal-count bins sorted by predicted delta",
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_unit": "player-level paired MAE improvement",
        "bootstrap_interval_quantiles": [0.025, 0.975],
        "maximum_source_game_id_mismatch_fraction": (MAX_SOURCE_GAME_ID_MISMATCH_FRACTION),
        "source_game_id_coverage_rule": (
            "fail if either player-log-only ids / player-log ids or "
            "parsed-game-only ids / parsed-game ids exceeds the ceiling"
        ),
        "percentile_sample_size_bands": [
            {
                "label": label,
                "minimum": minimum,
                "maximum": maximum,
            }
            for label, minimum, maximum in PERCENTILE_SAMPLE_SIZE_BANDS
        ],
        "blowout_release_rule": (
            "both chronological transitions must pass: candidate MAE < "
            "zero-effect MAE; player-block bootstrap 95% improvement interval "
            "lower bound > 0; calibration slope > 0; no calibration-bin sign "
            "reversal; sign stability > 0.5"
        ),
    }


def reliability_backtest_protocol_version() -> str:
    """Fingerprint the complete declared protocol independently of evidence."""

    protocol = reliability_backtest_protocol()
    rendered = json.dumps(protocol, sort_keys=True, separators=(",", ":"))
    return content_fingerprint(["reliability-backtest-protocol-v1", rendered])


def _load_season(client: ReliabilityBacktestClient, season: str) -> SeasonCohort:
    games = tuple(
        game
        for game in parse_league_game_finder(
            client.league_game_finder(season=season),
            season=season,
        )
        if game.home_score is not None and game.away_score is not None
    )
    if not games:
        raise RuntimeError(f"{season} contains no completed regular-season games")
    games_by_id = {game.nba_game_id: game for game in games}
    if len(games_by_id) != len(games):
        raise RuntimeError(f"{season} contains duplicate completed game ids")

    parsed_logs = parse_player_game_logs(client.player_game_logs(season=season))
    player_log_game_ids = {row.nba_game_id for row in parsed_logs}
    parsed_game_ids = set(games_by_id)
    player_log_only_game_ids, parsed_game_only_ids = _validated_source_game_id_mismatches(
        season=season,
        parsed_game_ids=parsed_game_ids,
        player_log_game_ids=player_log_game_ids,
    )
    excluded_log_count = sum(row.nba_game_id in player_log_only_game_ids for row in parsed_logs)
    included_logs = [row for row in parsed_logs if row.nba_game_id in games_by_id]
    logs = tuple(
        _historical_log(row, games_by_id[row.nba_game_id])
        for row in sorted(
            included_logs,
            key=lambda item: (
                games_by_id[item.nba_game_id].game_date,
                item.nba_game_id,
                item.nba_player_id,
            ),
        )
    )
    return SeasonCohort(
        season=season,
        games=tuple(sorted(games, key=lambda row: (row.game_date, row.nba_game_id))),
        logs=logs,
        player_log_game_ids=len(player_log_game_ids),
        player_log_only_game_ids=player_log_only_game_ids,
        parsed_game_only_ids=parsed_game_only_ids,
        excluded_player_game_logs=excluded_log_count,
        fingerprint=_cohort_fingerprint(
            season,
            games,
            logs,
            player_log_game_ids=len(player_log_game_ids),
            player_log_only_game_ids=player_log_only_game_ids,
            parsed_game_only_ids=parsed_game_only_ids,
            excluded_player_game_logs=excluded_log_count,
        ),
    )


def _validated_source_game_id_mismatches(
    *,
    season: str,
    parsed_game_ids: set[str],
    player_log_game_ids: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not parsed_game_ids or not player_log_game_ids:
        raise RuntimeError(f"{season} source game-id sets must both be non-empty")
    player_log_only_game_ids = tuple(sorted(player_log_game_ids - parsed_game_ids))
    parsed_game_only_ids = tuple(sorted(parsed_game_ids - player_log_game_ids))
    player_log_only_fraction = len(player_log_only_game_ids) / len(player_log_game_ids)
    parsed_game_only_fraction = len(parsed_game_only_ids) / len(parsed_game_ids)
    if (
        player_log_only_fraction > MAX_SOURCE_GAME_ID_MISMATCH_FRACTION
        or parsed_game_only_fraction > MAX_SOURCE_GAME_ID_MISMATCH_FRACTION
    ):
        raise RuntimeError(
            f"{season} source game-id mismatch exceeds the "
            f"{MAX_SOURCE_GAME_ID_MISMATCH_FRACTION:.2%} ceiling: "
            f"{len(player_log_only_game_ids)} of {len(player_log_game_ids)} "
            "PlayerGameLogs game ids lack a parsed LeagueGameFinder game and "
            f"{len(parsed_game_only_ids)} of {len(parsed_game_ids)} parsed games "
            "lack all player logs"
        )
    return player_log_only_game_ids, parsed_game_only_ids


def _historical_log(
    row: PlayerBoxScoreRecord,
    game: NbaGameRecord,
) -> HistoricalPlayerGame:
    if game.home_score is None or game.away_score is None:
        raise AssertionError("season cohort keeps completed games only")
    return HistoricalPlayerGame(
        player_id=row.nba_player_id,
        game_id=row.nba_game_id,
        game_date=game.game_date,
        is_blowout=abs(game.home_score - game.away_score) >= BLOWOUT_MARGIN,
        seconds_played=row.seconds_played,
        field_goals_made=row.field_goals_made,
        field_goals_attempted=row.field_goals_attempted,
        three_pointers_made=row.three_pointers_made,
        free_throws_made=row.free_throws_made,
        free_throws_attempted=row.free_throws_attempted,
        points=row.points,
        rebounds=row.rebounds,
        assists=row.assists,
        steals=row.steals,
        blocks=row.blocks,
        turnovers=row.turnovers,
    )


def _cohort_fingerprint(
    season: str,
    games: Sequence[NbaGameRecord],
    logs: Sequence[HistoricalPlayerGame],
    *,
    player_log_game_ids: int,
    player_log_only_game_ids: Sequence[str],
    parsed_game_only_ids: Sequence[str],
    excluded_player_game_logs: int,
) -> str:
    parts = [
        f"reliability-backtest-v1:{season}",
        f"player_log_game_ids:{player_log_game_ids}",
        f"player_log_only_game_ids:{','.join(player_log_only_game_ids)}",
        f"parsed_game_only_ids:{','.join(parsed_game_only_ids)}",
        f"excluded_player_game_logs:{excluded_player_game_logs}",
    ]
    parts.extend(
        "game:"
        + ":".join(
            (
                game.nba_game_id,
                game.game_date.isoformat(),
                str(game.home_team_id),
                str(game.away_team_id),
                str(game.home_score),
                str(game.away_score),
            )
        )
        for game in sorted(games, key=lambda row: (row.game_date, row.nba_game_id))
    )
    parts.extend(
        "log:"
        + ":".join(
            (
                str(row.player_id),
                row.game_id,
                row.game_date.isoformat(),
                str(row.seconds_played),
                str(row.field_goals_made),
                str(row.field_goals_attempted),
                str(row.three_pointers_made),
                str(row.free_throws_made),
                str(row.free_throws_attempted),
                str(row.points),
                str(row.rebounds),
                str(row.assists),
                str(row.steals),
                str(row.blocks),
                str(row.turnovers),
            )
        )
        for row in logs
    )
    return content_fingerprint(parts)


def _cohort_metadata(cohort: SeasonCohort) -> dict[str, object]:
    player_ids = {row.player_id for row in cohort.logs}
    paired_game_ids = len(cohort.games) - len(cohort.parsed_game_only_ids)
    return {
        "fingerprint": cohort.fingerprint,
        "parsed_completed_games": len(cohort.games),
        "source_game_ids_with_player_logs": cohort.player_log_game_ids,
        "parsed_game_coverage_of_player_logs": (paired_game_ids / cohort.player_log_game_ids),
        "player_log_coverage_of_parsed_games": paired_game_ids / len(cohort.games),
        "player_game_logs": len(cohort.logs),
        "players": len(player_ids),
        "player_log_only_game_ids": list(cohort.player_log_only_game_ids),
        "parsed_game_only_ids": list(cohort.parsed_game_only_ids),
        "excluded_player_game_logs": cohort.excluded_player_game_logs,
        "player_log_only_reason": (
            "PlayerGameLogs game ids without a two-sided home/away result from "
            "the existing LeagueGameFinder parser"
            if cohort.player_log_only_game_ids
            else None
        ),
        "parsed_game_only_reason": (
            "parsed LeagueGameFinder games without any PlayerGameLogs rows"
            if cohort.parsed_game_only_ids
            else None
        ),
        "first_game_date": cohort.games[0].game_date.isoformat(),
        "last_game_date": cohort.games[-1].game_date.isoformat(),
        "first_game_id": cohort.games[0].nba_game_id,
        "last_game_id": cohort.games[-1].nba_game_id,
    }


def _season_summaries(cohort: SeasonCohort) -> dict[int, PlayerSeasonSummary]:
    ratio_rates = _ratio_rates(cohort.logs)
    by_player: dict[int, list[HistoricalPlayerGame]] = defaultdict(list)
    for log in cohort.logs:
        by_player[log.player_id].append(log)
    return {
        player_id: _player_summary(logs, ratio_rates=ratio_rates)
        for player_id, logs in by_player.items()
    }


def _ratio_rates(logs: Sequence[HistoricalPlayerGame]) -> dict[str, float | None]:
    rates: dict[str, float | None] = {}
    for category, made_field, attempted_field in RELIABILITY_RATIO_CATEGORIES:
        made_total = 0
        attempted_total = 0
        for log in logs:
            made = getattr(log, made_field)
            attempted = getattr(log, attempted_field)
            if made is None or attempted is None:
                continue
            _validate_shooting(log, made, attempted, made_field, attempted_field)
            made_total += made
            attempted_total += attempted
        rates[category] = None if attempted_total == 0 else made_total / attempted_total
    return rates


def _player_summary(
    logs: Sequence[HistoricalPlayerGame],
    *,
    ratio_rates: dict[str, float | None],
) -> PlayerSeasonSummary:
    ordered = sorted(logs, key=lambda row: (row.game_date, row.game_id))
    category_values: dict[str, tuple[float, ...]] = {}
    for category, field in RELIABILITY_COUNTING_CATEGORIES:
        values: list[float] = []
        for row in ordered:
            value = getattr(row, field)
            if value is None:
                continue
            if value < 0:
                raise RuntimeError(
                    f"negative {field} for player {row.player_id}, game {row.game_id}"
                )
            values.append(float(value))
        category_values[category] = tuple(values)
    for category, made_field, attempted_field in RELIABILITY_RATIO_CATEGORIES:
        rate = ratio_rates[category]
        impacts: list[float] = []
        if rate is not None:
            for row in ordered:
                made = getattr(row, made_field)
                attempted = getattr(row, attempted_field)
                if made is None or attempted is None:
                    continue
                _validate_shooting(row, made, attempted, made_field, attempted_field)
                impacts.append(volume_weighted_impact(made, attempted, rate))
        category_values[category] = tuple(impacts)

    minute_values_list: list[float] = []
    for row in ordered:
        if row.seconds_played is None:
            continue
        if row.seconds_played < 0:
            raise RuntimeError(
                f"negative seconds_played for player {row.player_id}, game {row.game_id}"
            )
        minute_values_list.append(row.seconds_played / 60)
    minute_values = tuple(minute_values_list)
    minute_mean = _mean(minute_values)
    minute_sd = sample_standard_deviation(minute_values)
    metric_values: dict[str, float | None] = {
        "minutes_cv": (
            None
            if minute_mean is None or minute_mean <= 0 or minute_sd is None
            else minute_sd / minute_mean
        )
    }
    metric_values.update(
        {
            f"{category}_sd": sample_standard_deviation(values)
            for category, values in category_values.items()
        }
    )
    lower_quantiles = {
        category: type7_quantile(values, LOWER_PERCENTILE)
        for category, values in category_values.items()
        if values
    }
    upper_quantiles = {
        category: type7_quantile(values, UPPER_PERCENTILE)
        for category, values in category_values.items()
        if values
    }

    blowout_minutes = [
        row.seconds_played / 60
        for row in ordered
        if row.is_blowout and row.seconds_played is not None and row.seconds_played >= 0
    ]
    non_blowout_minutes = [
        row.seconds_played / 60
        for row in ordered
        if not row.is_blowout and row.seconds_played is not None and row.seconds_played >= 0
    ]
    blowout_delta = None
    if (
        len(blowout_minutes) >= MINIMUM_BLOWOUT_GAMES
        and len(non_blowout_minutes) >= MINIMUM_NON_BLOWOUT_GAMES
    ):
        blowout_mean = _mean(blowout_minutes)
        non_blowout_mean = _mean(non_blowout_minutes)
        if blowout_mean is None or non_blowout_mean is None:
            raise AssertionError("non-empty minute groups have means")
        blowout_delta = blowout_mean - non_blowout_mean
    return PlayerSeasonSummary(
        player_id=ordered[0].player_id,
        game_count=len(minute_values),
        metric_values=metric_values,
        category_values=category_values,
        lower_quantiles=lower_quantiles,
        upper_quantiles=upper_quantiles,
        blowout_delta_minutes=blowout_delta,
        blowout_games=len(blowout_minutes),
        non_blowout_games=len(non_blowout_minutes),
    )


def _evaluate_pair(
    training: dict[int, PlayerSeasonSummary],
    holdout: dict[int, PlayerSeasonSummary],
    *,
    stage: str,
) -> dict[str, object]:
    eligible_players = sorted(
        player_id
        for player_id in set(training) & set(holdout)
        if training[player_id].game_count >= MINIMUM_PLAYER_GAMES
        and holdout[player_id].game_count >= MINIMUM_PLAYER_GAMES
    )
    percentile_players = sorted(set(training) & set(holdout))
    metric_names = sorted(
        {metric for player_id in eligible_players for metric in training[player_id].metric_values}
    )
    stability = {
        metric: _stability_metric(
            [
                (
                    training[player_id].metric_values.get(metric),
                    holdout[player_id].metric_values.get(metric),
                )
                for player_id in eligible_players
            ]
        )
        for metric in metric_names
    }
    categories = [category for category, _field in RELIABILITY_COUNTING_CATEGORIES] + [
        category for category, _made, _attempted in RELIABILITY_RATIO_CATEGORIES
    ]
    percentile_coverage = {
        category: _percentile_coverage(
            training,
            holdout,
            eligible_players=percentile_players,
            category=category,
        )
        for category in categories
    }
    return {
        "stage": stage,
        "eligible_players": len(eligible_players),
        "minimum_games_each_season": MINIMUM_PLAYER_GAMES,
        "percentile_players_considered": len(percentile_players),
        "stability": stability,
        "percentile_coverage": percentile_coverage,
        "blowout_suppression": _evaluate_blowout(training, holdout),
    }


def _stability_metric(
    raw_pairs: Sequence[tuple[float | None, float | None]],
) -> dict[str, object]:
    pairs = [(left, right) for left, right in raw_pairs if left is not None and right is not None]
    if not pairs:
        return {
            "players": 0,
            "spearman": None,
            "player_specific_mae": None,
            "league_median_baseline": None,
            "league_median_baseline_mae": None,
        }
    training_values = [left for left, _right in pairs]
    holdout_values = [right for _left, right in pairs]
    baseline = type7_quantile(training_values, 0.5)
    return {
        "players": len(pairs),
        "spearman": _spearman(training_values, holdout_values),
        "player_specific_mae": _mean([abs(left - right) for left, right in pairs]),
        "league_median_baseline": baseline,
        "league_median_baseline_mae": _mean([abs(baseline - right) for right in holdout_values]),
    }


def _percentile_coverage(
    training: dict[int, PlayerSeasonSummary],
    holdout: dict[int, PlayerSeasonSummary],
    *,
    eligible_players: Sequence[int],
    category: str,
) -> dict[str, object]:
    overall: list[tuple[float, float, tuple[float, ...]]] = []
    by_band: dict[str, list[tuple[float, float, tuple[float, ...]]]] = {
        label: [] for label, _minimum, _maximum in PERCENTILE_SAMPLE_SIZE_BANDS
    }
    for player_id in eligible_players:
        lower = training[player_id].lower_quantiles.get(category)
        upper = training[player_id].upper_quantiles.get(category)
        training_values = training[player_id].category_values.get(category, ())
        values = holdout[player_id].category_values.get(category, ())
        if lower is None or upper is None or not values:
            continue
        record = (lower, upper, values)
        overall.append(record)
        band = _sample_size_band(len(training_values))
        by_band[band].append(record)
    result = _coverage_summary(overall)
    result.update(
        {
            "sample_size_bands": [
                {
                    "label": label,
                    **_coverage_summary(by_band[label]),
                }
                for label, _minimum, _maximum in PERCENTILE_SAMPLE_SIZE_BANDS
            ]
        }
    )
    return result


def _sample_size_band(sample_size: int) -> str:
    for label, minimum, maximum in PERCENTILE_SAMPLE_SIZE_BANDS:
        if sample_size >= minimum and (maximum is None or sample_size <= maximum):
            return label
    raise ValueError(f"no pre-registered percentile sample-size band for {sample_size}")


def _coverage_summary(
    records: Sequence[tuple[float, float, tuple[float, ...]]],
) -> dict[str, object]:
    observations = sum(len(values) for _lower, _upper, values in records)
    below_lower = sum(value <= lower for lower, _upper, values in records for value in values)
    below_upper = sum(value <= upper for _lower, upper, values in records for value in values)
    return {
        "players": len(records),
        "holdout_observations": observations,
        "lower_target": LOWER_PERCENTILE,
        "lower_observed": None if observations == 0 else below_lower / observations,
        "upper_target": UPPER_PERCENTILE,
        "upper_observed": None if observations == 0 else below_upper / observations,
    }


def _evaluate_blowout(
    training: dict[int, PlayerSeasonSummary],
    holdout: dict[int, PlayerSeasonSummary],
) -> dict[str, object]:
    pairs: list[tuple[int, float, float]] = []
    for player_id in sorted(set(training) & set(holdout)):
        prediction = training[player_id].blowout_delta_minutes
        observed = holdout[player_id].blowout_delta_minutes
        if prediction is not None and observed is not None:
            pairs.append((player_id, prediction, observed))
    if len(pairs) < CALIBRATION_BIN_COUNT:
        return {
            "eligible_players": len(pairs),
            "candidate_mae": None,
            "zero_effect_mae": None,
            "mean_mae_improvement": None,
            "mae_improvement_bootstrap_95": None,
            "sign_stability": None,
            "calibration_slope": None,
            "calibration_intercept": None,
            "calibration_bins": [],
            "calibration_sign_reversal": None,
            "release_rule_passed": False,
            "release_reason": "insufficient players for pre-registered calibration bins",
        }
    predictions = [prediction for _player, prediction, _observed in pairs]
    outcomes = [actual for _player, _prediction, actual in pairs]
    candidate_errors = [
        abs(prediction - actual) for prediction, actual in zip(predictions, outcomes, strict=True)
    ]
    zero_errors = [abs(actual) for actual in outcomes]
    improvements = [
        zero_error - candidate_error
        for zero_error, candidate_error in zip(zero_errors, candidate_errors, strict=True)
    ]
    interval = _bootstrap_mean_interval(improvements)
    candidate_mae = _required_mean(candidate_errors)
    zero_mae = _required_mean(zero_errors)
    mean_improvement = _required_mean(improvements)
    sign_stability = sum(
        prediction * actual > 0 for prediction, actual in zip(predictions, outcomes, strict=True)
    ) / len(predictions)
    slope, intercept = _linear_calibration(predictions, outcomes)
    calibration_bins = _calibration_bins(predictions, outcomes)
    calibration_sign_reversal = any(
        _required_float(row["predicted_mean_delta_minutes"])
        * _required_float(row["observed_mean_delta_minutes"])
        < 0
        for row in calibration_bins
    )
    passed = (
        candidate_mae < zero_mae
        and interval[0] > 0
        and slope is not None
        and slope > 0
        and not calibration_sign_reversal
        and sign_stability > 0.5
    )
    return {
        "eligible_players": len(pairs),
        "candidate_mae": candidate_mae,
        "zero_effect_mae": zero_mae,
        "mean_mae_improvement": mean_improvement,
        "mae_improvement_bootstrap_95": list(interval),
        "sign_stability": sign_stability,
        "calibration_slope": slope,
        "calibration_intercept": intercept,
        "calibration_bins": calibration_bins,
        "calibration_sign_reversal": calibration_sign_reversal,
        "release_rule_passed": passed,
        "release_reason": (
            "all pre-registered held-out rules passed"
            if passed
            else "one or more pre-registered held-out rules failed"
        ),
    }


def _calibration_bins(
    predicted: Sequence[float],
    observed: Sequence[float],
) -> list[dict[str, object]]:
    pairs = sorted(zip(predicted, observed, strict=True), key=lambda pair: pair[0])
    bins: list[dict[str, object]] = []
    for index in range(CALIBRATION_BIN_COUNT):
        start = len(pairs) * index // CALIBRATION_BIN_COUNT
        end = len(pairs) * (index + 1) // CALIBRATION_BIN_COUNT
        group = pairs[start:end]
        if not group:
            continue
        bins.append(
            {
                "predicted_mean_delta_minutes": _required_mean(
                    [prediction for prediction, _actual in group]
                ),
                "observed_mean_delta_minutes": _required_mean(
                    [actual for _prediction, actual in group]
                ),
                "players": len(group),
            }
        )
    return bins


def _linear_calibration(
    predicted: Sequence[float],
    observed: Sequence[float],
) -> tuple[float | None, float | None]:
    predicted_mean = _required_mean(predicted)
    observed_mean = _required_mean(observed)
    denominator = sum((value - predicted_mean) ** 2 for value in predicted)
    if denominator == 0:
        return None, None
    slope = (
        sum(
            (prediction - predicted_mean) * (actual - observed_mean)
            for prediction, actual in zip(predicted, observed, strict=True)
        )
        / denominator
    )
    return slope, observed_mean - slope * predicted_mean


def _bootstrap_mean_interval(values: Sequence[float]) -> tuple[float, float]:
    if not values:
        raise ValueError("bootstrap requires at least one player")
    generator = random.Random(BOOTSTRAP_SEED)
    estimates = [
        _required_mean([values[generator.randrange(len(values))] for _ in values])
        for _sample in range(BOOTSTRAP_RESAMPLES)
    ]
    return (
        type7_quantile(estimates, 0.025),
        type7_quantile(estimates, 0.975),
    )


def _spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right):
        raise ValueError("Spearman inputs must have equal lengths")
    if len(left) < 2:
        return None
    left_ranks = _ranks(left)
    right_ranks = _ranks(right)
    left_mean = _required_mean(left_ranks)
    right_mean = _required_mean(right_ranks)
    numerator = sum(
        (left_rank - left_mean) * (right_rank - right_mean)
        for left_rank, right_rank in zip(left_ranks, right_ranks, strict=True)
    )
    left_sum = sum((rank - left_mean) ** 2 for rank in left_ranks)
    right_sum = sum((rank - right_mean) ** 2 for rank in right_ranks)
    if left_sum == 0 or right_sum == 0:
        return None
    return numerator / math.sqrt(left_sum * right_sum)


def _ranks(values: Sequence[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average_rank = (index + 1 + end) / 2
        for position in range(index, end):
            ranks[ordered[position][0]] = average_rank
        index = end
    return ranks


def _validate_shooting(
    row: HistoricalPlayerGame,
    made: int,
    attempted: int,
    made_field: str,
    attempted_field: str,
) -> None:
    if made < 0 or attempted < 0 or made > attempted:
        raise RuntimeError(
            f"invalid shooting components for player {row.player_id}, game {row.game_id}: "
            f"{made_field}={made}, {attempted_field}={attempted}"
        )


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def _required_mean(values: Sequence[float]) -> float:
    mean = _mean(values)
    if mean is None:
        raise ValueError("mean requires at least one value")
    return mean


def _object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    return value


def _required_float(value: object) -> float:
    if not isinstance(value, int | float):
        raise TypeError("expected a JSON number")
    return float(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    evidence = run_backtest()
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
