"""Calibrated blowout likelihood from strictly pre-game score history."""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from hoops_gm.db.lineage import content_fingerprint


@dataclass(frozen=True)
class GameResult:
    game_id: str
    game_date: date
    home_team_id: int
    away_team_id: int
    home_score: int
    away_score: int


@dataclass(frozen=True)
class BlowoutExample:
    game_id: str
    game_date: date
    projected_margin_gap: float
    was_blowout: bool


@dataclass(frozen=True)
class CalibrationBin:
    predicted_probability: float
    observed_rate: float
    count: int


@dataclass(frozen=True)
class BlowoutModel:
    """Empirical probability by pre-game team-strength gap."""

    training_cutoff: date
    window_games: int
    minimum_history_games: int
    blowout_margin: int
    bin_edges: tuple[float, ...]
    probabilities: tuple[float, ...]
    training_examples: int
    training_blowout_rate: float
    source_version: str
    version: str

    def predict(self, projected_margin_gap: float) -> float:
        return self.probabilities[bisect_right(self.bin_edges, projected_margin_gap)]


@dataclass(frozen=True)
class BlowoutBacktest:
    training_cutoff: date
    held_out_start: date
    held_out_end: date
    training_examples: int
    held_out_examples: int
    brier_score: float
    baseline_brier_score: float
    expected_calibration_error: float
    calibration_bins: tuple[CalibrationBin, ...]


def blowout_model_version(
    *,
    source_version: str,
    training_cutoff: date,
    window_games: int,
    minimum_history_games: int,
    blowout_margin: int,
    bin_edges: Sequence[float],
    probabilities: Sequence[float],
) -> str:
    """Derive the immutable version from every fitted parameter and its source."""

    return content_fingerprint(
        [
            "schedule-context-blowout-empirical-v1",
            source_version,
            training_cutoff.isoformat(),
            str(window_games),
            str(minimum_history_games),
            str(blowout_margin),
            ",".join(f"{edge:.8f}" for edge in bin_edges),
            ",".join(f"{probability:.8f}" for probability in probabilities),
        ]
    )


def pregame_examples(
    games: Sequence[GameResult],
    *,
    window_games: int,
    minimum_history_games: int,
    blowout_margin: int,
) -> list[BlowoutExample]:
    """Build features before updating either team's history for that game."""

    if window_games < 1:
        raise ValueError("window_games must be positive")
    if minimum_history_games < 1 or minimum_history_games > window_games:
        raise ValueError("minimum_history_games must be in [1, window_games]")
    if blowout_margin < 1:
        raise ValueError("blowout_margin must be positive")

    margins: dict[int, deque[int]] = defaultdict(lambda: deque(maxlen=window_games))
    examples: list[BlowoutExample] = []
    for game in sorted(games, key=lambda row: (row.game_date, row.game_id)):
        home_history = margins[game.home_team_id]
        away_history = margins[game.away_team_id]
        if (
            len(home_history) >= minimum_history_games
            and len(away_history) >= minimum_history_games
        ):
            home_strength = sum(home_history) / len(home_history)
            away_strength = sum(away_history) / len(away_history)
            examples.append(
                BlowoutExample(
                    game_id=game.game_id,
                    game_date=game.game_date,
                    projected_margin_gap=abs(home_strength - away_strength),
                    was_blowout=abs(game.home_score - game.away_score) >= blowout_margin,
                )
            )

        margin = game.home_score - game.away_score
        home_history.append(margin)
        away_history.append(-margin)
    return examples


def fit_blowout_model(
    games: Sequence[GameResult],
    *,
    training_cutoff: date,
    source_version: str,
    window_games: int = 15,
    minimum_history_games: int = 5,
    blowout_margin: int = 15,
    requested_bins: int = 3,
) -> BlowoutModel:
    """Fit equal-frequency empirical bins with beta(1, 1) smoothing."""

    if requested_bins < 2:
        raise ValueError("requested_bins must be at least two")
    examples = [
        row
        for row in pregame_examples(
            games,
            window_games=window_games,
            minimum_history_games=minimum_history_games,
            blowout_margin=blowout_margin,
        )
        if row.game_date <= training_cutoff
    ]
    if len(examples) < requested_bins * 4:
        raise ValueError("not enough pre-cutoff games to fit calibrated blowout bins")

    edges = _quantile_edges([row.projected_margin_gap for row in examples], requested_bins)
    successes = [0] * (len(edges) + 1)
    counts = [0] * (len(edges) + 1)
    for example in examples:
        index = bisect_right(edges, example.projected_margin_gap)
        counts[index] += 1
        successes[index] += int(example.was_blowout)
    probabilities = tuple(
        (successes[index] + 1) / (counts[index] + 2) for index in range(len(counts))
    )
    overall_rate = sum(successes) / sum(counts)
    version = blowout_model_version(
        source_version=source_version,
        training_cutoff=training_cutoff,
        window_games=window_games,
        minimum_history_games=minimum_history_games,
        blowout_margin=blowout_margin,
        bin_edges=edges,
        probabilities=probabilities,
    )
    return BlowoutModel(
        training_cutoff=training_cutoff,
        window_games=window_games,
        minimum_history_games=minimum_history_games,
        blowout_margin=blowout_margin,
        bin_edges=edges,
        probabilities=probabilities,
        training_examples=len(examples),
        training_blowout_rate=overall_rate,
        source_version=source_version,
        version=version,
    )


def evaluate_blowout_model(
    model: BlowoutModel,
    games: Sequence[GameResult],
    *,
    held_out_start: date,
    held_out_end: date,
) -> BlowoutBacktest:
    """Evaluate only games after the training cutoff in the requested date range."""

    if held_out_start <= model.training_cutoff:
        raise ValueError("held_out_start must be after the training cutoff")
    if held_out_end < held_out_start:
        raise ValueError("held_out_end must not precede held_out_start")
    examples = [
        row
        for row in pregame_examples(
            games,
            window_games=model.window_games,
            minimum_history_games=model.minimum_history_games,
            blowout_margin=model.blowout_margin,
        )
        if held_out_start <= row.game_date <= held_out_end
    ]
    if not examples:
        raise ValueError("held-out window contains no eligible games")

    predicted = [model.predict(row.projected_margin_gap) for row in examples]
    observed = [int(row.was_blowout) for row in examples]
    brier = sum(
        (probability - outcome) ** 2
        for probability, outcome in zip(predicted, observed, strict=True)
    ) / len(examples)
    baseline = sum((model.training_blowout_rate - outcome) ** 2 for outcome in observed) / len(
        examples
    )

    by_probability: dict[float, list[int]] = defaultdict(list)
    for probability, outcome in zip(predicted, observed, strict=True):
        by_probability[probability].append(outcome)
    calibration = tuple(
        CalibrationBin(
            predicted_probability=probability,
            observed_rate=sum(outcomes) / len(outcomes),
            count=len(outcomes),
        )
        for probability, outcomes in sorted(by_probability.items())
    )
    ece = sum(
        abs(row.predicted_probability - row.observed_rate) * row.count / len(examples)
        for row in calibration
    )
    return BlowoutBacktest(
        training_cutoff=model.training_cutoff,
        held_out_start=held_out_start,
        held_out_end=held_out_end,
        training_examples=model.training_examples,
        held_out_examples=len(examples),
        brier_score=brier,
        baseline_brier_score=baseline,
        expected_calibration_error=ece,
        calibration_bins=calibration,
    )


def _quantile_edges(values: Sequence[float], requested_bins: int) -> tuple[float, ...]:
    ordered = sorted(values)
    candidates = [
        ordered[min(len(ordered) - 1, (len(ordered) * index) // requested_bins)]
        for index in range(1, requested_bins)
    ]
    return tuple(sorted(set(candidates)))
