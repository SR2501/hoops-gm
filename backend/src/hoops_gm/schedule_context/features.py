"""Descriptive slate, pace, and category-defence derivations."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from hoops_gm.db.lineage import content_fingerprint
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.schedule_context.blowout import BlowoutModel, GameResult

_OPPONENT_DERIVATION_SPEC = (
    "opponent-context-derivation-v1",
    "fixture-scope:regular-season-team-schedule-v1",
    "history:strictly-before-fixture-last-n-scored-complete-games-v1",
    "pace:mean-of-team-and-opponent-trailing-estimated-possessions-v1",
    "possessions:fga-minus-oreb-plus-tov-plus-0.44-fta-v1",
    "category-defence:opponent-allowed-counting-per-100-and-volume-ratios-v1",
    "blowout-input:absolute-trailing-mean-margin-gap-v1",
    "coverage:produced-fixture-rows-over-scheduled-fixture-rows-v1",
)


@dataclass(frozen=True)
class ScheduleContextConfig:
    trailing_games: int = 15
    minimum_history_games: int = 5
    off_night_percentile: float = 0.25
    minimum_opponent_coverage: float = 0.95

    def __post_init__(self) -> None:
        if self.trailing_games < 1:
            raise ValueError("trailing_games must be positive")
        if self.minimum_history_games < 1 or self.minimum_history_games > self.trailing_games:
            raise ValueError("minimum_history_games must be in [1, trailing_games]")
        if not 0 < self.off_night_percentile < 1:
            raise ValueError("off_night_percentile must be between zero and one")
        if not 0.95 <= self.minimum_opponent_coverage <= 1:
            raise ValueError("minimum_opponent_coverage must be in [0.95, 1]")

    @property
    def off_night_model_version(self) -> str:
        return content_fingerprint(
            [
                "off-night-empirical-midrank-v1",
                f"{self.off_night_percentile:.8f}",
                f"trailing-games:{self.trailing_games}",
                f"minimum-history-games:{self.minimum_history_games}",
                f"minimum-opponent-coverage:{self.minimum_opponent_coverage:.8f}",
            ]
        )

    @property
    def opponent_derivation_version(self) -> str:
        """Fingerprint the complete pace, defence, and coverage derivation."""

        return content_fingerprint(
            [
                *_OPPONENT_DERIVATION_SPEC,
                f"trailing-games:{self.trailing_games}",
                f"minimum-history-games:{self.minimum_history_games}",
                f"minimum-opponent-coverage:{self.minimum_opponent_coverage:.8f}",
            ]
        )


class InsufficientContextError(ValueError):
    """The stored observations cannot support an as-of context row."""


class IncompleteRecentContextError(ValueError):
    """A recent scored game is missing a complete team box score."""


@dataclass(frozen=True)
class RecentObservationAudit:
    team_id: int
    features_as_of: date
    window_games: int
    scored_game_ids: tuple[str, ...]
    complete_game_ids: tuple[str, ...]
    incomplete_game_ids: tuple[str, ...]
    latest_scored_game_date: date | None
    latest_complete_game_date: date | None

    def as_dict(self) -> dict[str, object]:
        return {
            "rule": "last_n_scored_regular_season_team_games_complete_v1",
            "team_id": self.team_id,
            "features_as_of": self.features_as_of.isoformat(),
            "window_games": self.window_games,
            "scored_game_ids": list(self.scored_game_ids),
            "complete_game_ids": list(self.complete_game_ids),
            "incomplete_game_ids": list(self.incomplete_game_ids),
            "latest_scored_game_date": (
                self.latest_scored_game_date.isoformat() if self.latest_scored_game_date else None
            ),
            "latest_complete_game_date": (
                self.latest_complete_game_date.isoformat()
                if self.latest_complete_game_date
                else None
            ),
            "days_since_latest_scored_game": (
                (self.features_as_of - self.latest_scored_game_date).days
                if self.latest_scored_game_date
                else None
            ),
            "days_since_latest_complete_game": (
                (self.features_as_of - self.latest_complete_game_date).days
                if self.latest_complete_game_date
                else None
            ),
        }


@dataclass(frozen=True)
class TeamGameStats:
    field_goals_made: int
    field_goals_attempted: int
    three_pointers_made: int
    free_throws_made: int
    free_throws_attempted: int
    points: int
    offensive_rebounds: int
    rebounds: int
    assists: int
    steals: int
    blocks: int
    turnovers: int
    seconds_played: int = 14_400

    def __post_init__(self) -> None:
        if self.seconds_played < 14_400 or (self.seconds_played - 14_400) % 1_500:
            raise ValueError("team player-minutes must equal 240 plus 25 per overtime")

    @property
    def possessions(self) -> float:
        return (
            self.field_goals_attempted
            - self.offensive_rebounds
            + self.turnovers
            + 0.44 * self.free_throws_attempted
        )


@dataclass(frozen=True)
class ContextGame:
    result: GameResult
    home_stats: TeamGameStats
    away_stats: TeamGameStats

    def __post_init__(self) -> None:
        if self.home_stats.seconds_played != self.away_stats.seconds_played:
            raise ValueError("opponents must have equal complete team player-minutes")

    def stats_for(self, team_id: int) -> TeamGameStats:
        if team_id == self.result.home_team_id:
            return self.home_stats
        if team_id == self.result.away_team_id:
            return self.away_stats
        raise ValueError(f"team {team_id} did not play game {self.result.game_id}")

    def opponent_stats_for(self, team_id: int) -> TeamGameStats:
        if team_id == self.result.home_team_id:
            return self.away_stats
        if team_id == self.result.away_team_id:
            return self.home_stats
        raise ValueError(f"team {team_id} did not play game {self.result.game_id}")

    @property
    def pace(self) -> float:
        return (self.home_stats.possessions + self.away_stats.possessions) / 2


@dataclass(frozen=True)
class OffNightFact:
    slate_date: date
    scheduled_game_count: int
    scheduled_team_count: int
    is_off_night: bool
    light_slate_percentile: float
    threshold_games: int
    threshold_percentile: float
    input_snapshot: dict[str, object]


@dataclass(frozen=True)
class OpponentProfile:
    pace_possessions: float
    pace_window_games: int
    category_defence: dict[str, object]
    defence_window_games: int
    blowout_probability: float
    input_snapshot: dict[str, object]
    observation_audits: tuple[RecentObservationAudit, RecentObservationAudit]


def build_off_night_facts(
    entries: Sequence[TeamScheduleEntry],
    *,
    config: ScheduleContextConfig,
) -> list[OffNightFact]:
    """Describe each actual slate date without introducing fantasy periods."""

    game_ids_by_date: dict[date, set[int]] = defaultdict(set)
    for entry in entries:
        game_ids_by_date[entry.game_date].add(entry.game_id)
    if not game_ids_by_date:
        return []

    counts = sorted(len(game_ids) for game_ids in game_ids_by_date.values())
    threshold_games = _lower_quantile(counts, config.off_night_percentile)
    facts: list[OffNightFact] = []
    for slate_date, game_ids in sorted(game_ids_by_date.items()):
        count = len(game_ids)
        percentile = _empirical_midrank(counts, count)
        facts.append(
            OffNightFact(
                slate_date=slate_date,
                scheduled_game_count=count,
                scheduled_team_count=count * 2,
                is_off_night=count <= threshold_games,
                light_slate_percentile=percentile,
                threshold_games=threshold_games,
                threshold_percentile=config.off_night_percentile,
                input_snapshot={
                    "derivation": "season_slate_game_count_empirical_midrank_v1",
                    "game_ids": sorted(game_ids),
                    "season_slate_game_counts": counts,
                },
            )
        )
    return facts


def build_opponent_profile(
    *,
    team_id: int,
    opponent_team_id: int,
    fixture_date: date,
    context_games: Sequence[ContextGame],
    score_games: Sequence[GameResult],
    blowout_model: BlowoutModel,
    config: ScheduleContextConfig,
) -> OpponentProfile:
    """Build strictly as-of context; no game on/after the fixture may contribute."""

    if blowout_model.training_cutoff >= fixture_date:
        raise ValueError("blowout model training cutoff must precede the fixture")
    team_observation_audit = _recent_observation_audit(
        team_id=team_id,
        before=fixture_date,
        context_games=context_games,
        score_games=score_games,
        limit=config.trailing_games,
    )
    opponent_observation_audit = _recent_observation_audit(
        team_id=opponent_team_id,
        before=fixture_date,
        context_games=context_games,
        score_games=score_games,
        limit=config.trailing_games,
    )
    team_history = _team_history(team_id, fixture_date, context_games, config.trailing_games)
    opponent_history = _team_history(
        opponent_team_id, fixture_date, context_games, config.trailing_games
    )
    if len(team_history) < config.minimum_history_games:
        raise InsufficientContextError(
            f"team {team_id} has insufficient pre-fixture context history"
        )
    if len(opponent_history) < config.minimum_history_games:
        raise InsufficientContextError(
            f"opponent {opponent_team_id} has insufficient pre-fixture history"
        )

    pace = (
        sum(game.pace for game in team_history) / len(team_history)
        + sum(game.pace for game in opponent_history) / len(opponent_history)
    ) / 2
    defence = _category_defence(opponent_team_id, opponent_history)
    margin_histories = _score_margin_histories(
        score_games,
        before=fixture_date,
        window_games=blowout_model.window_games,
    )
    team_margins = margin_histories.get(team_id, ())
    opponent_margins = margin_histories.get(opponent_team_id, ())
    if (
        len(team_margins) < blowout_model.minimum_history_games
        or len(opponent_margins) < blowout_model.minimum_history_games
    ):
        raise InsufficientContextError(
            "insufficient pre-fixture score history for blowout probability"
        )
    projected_gap = abs(
        sum(team_margins) / len(team_margins) - sum(opponent_margins) / len(opponent_margins)
    )
    return OpponentProfile(
        pace_possessions=pace,
        pace_window_games=min(len(team_history), len(opponent_history)),
        category_defence=defence,
        defence_window_games=len(opponent_history),
        blowout_probability=blowout_model.predict(projected_gap),
        input_snapshot={
            "features_as_of": fixture_date.isoformat(),
            "pace_formula": "mean(team trailing game pace, opponent trailing game pace)",
            "possession_formula": "FGA - OREB + TOV + 0.44 * FTA",
            "pace_units": "raw estimated possessions per game; not normalized per 48 minutes",
            "box_score_completeness": (
                "each_team_player_seconds_equals_240_plus_25_per_overtime_v1"
            ),
            "observation_completeness": {
                "team": team_observation_audit.as_dict(),
                "opponent": opponent_observation_audit.as_dict(),
            },
            "team_pace_game_ids": [game.result.game_id for game in team_history],
            "opponent_defence_game_ids": [game.result.game_id for game in opponent_history],
            "team_pace_game_seconds": [
                game.stats_for(team_id).seconds_played for game in team_history
            ],
            "opponent_defence_game_seconds": [
                game.stats_for(opponent_team_id).seconds_played for game in opponent_history
            ],
            "offseason_carryover": (
                (fixture_date - max(game.result.game_date for game in opponent_history)).days > 60
            ),
            "projected_margin_gap": projected_gap,
            "blowout_bin_edges": list(blowout_model.bin_edges),
        },
        observation_audits=(team_observation_audit, opponent_observation_audit),
    )


def _recent_observation_audit(
    *,
    team_id: int,
    before: date,
    context_games: Sequence[ContextGame],
    score_games: Sequence[GameResult],
    limit: int,
) -> RecentObservationAudit:
    scored_history = sorted(
        (
            game
            for game in score_games
            if game.game_date < before and team_id in (game.home_team_id, game.away_team_id)
        ),
        key=lambda game: (game.game_date, game.game_id),
    )[-limit:]
    complete_games = {
        game.result.game_id: game
        for game in context_games
        if team_id in (game.result.home_team_id, game.result.away_team_id)
    }
    complete_history = [
        complete_games[game.game_id] for game in scored_history if game.game_id in complete_games
    ]
    incomplete_game_ids = tuple(
        game.game_id for game in scored_history if game.game_id not in complete_games
    )
    audit = RecentObservationAudit(
        team_id=team_id,
        features_as_of=before,
        window_games=limit,
        scored_game_ids=tuple(game.game_id for game in scored_history),
        complete_game_ids=tuple(game.result.game_id for game in complete_history),
        incomplete_game_ids=incomplete_game_ids,
        latest_scored_game_date=(scored_history[-1].game_date if scored_history else None),
        latest_complete_game_date=(
            complete_history[-1].result.game_date if complete_history else None
        ),
    )
    if incomplete_game_ids:
        raise IncompleteRecentContextError(
            f"team {team_id} has {len(incomplete_game_ids)}/{len(scored_history)} incomplete "
            f"box scores in its last {limit} scored games before {before}: "
            f"{', '.join(incomplete_game_ids)}"
        )
    return audit


def _team_history(
    team_id: int,
    before: date,
    games: Sequence[ContextGame],
    limit: int,
) -> list[ContextGame]:
    eligible = [
        game
        for game in games
        if game.result.game_date < before
        and team_id in (game.result.home_team_id, game.result.away_team_id)
    ]
    return sorted(eligible, key=lambda game: (game.result.game_date, game.result.game_id))[-limit:]


def _category_defence(team_id: int, games: Sequence[ContextGame]) -> dict[str, object]:
    allowed = [game.opponent_stats_for(team_id) for game in games]
    possessions = sum(row.possessions for row in allowed)
    if possessions <= 0:
        raise ValueError("opponent history has no positive possession estimate")
    per_100_fields = {
        "three_pointers_made": sum(row.three_pointers_made for row in allowed),
        "points": sum(row.points for row in allowed),
        "rebounds": sum(row.rebounds for row in allowed),
        "assists": sum(row.assists for row in allowed),
        "steals": sum(row.steals for row in allowed),
        "blocks": sum(row.blocks for row in allowed),
        "turnovers": sum(row.turnovers for row in allowed),
    }
    field_goals_made = sum(row.field_goals_made for row in allowed)
    field_goals_attempted = sum(row.field_goals_attempted for row in allowed)
    free_throws_made = sum(row.free_throws_made for row in allowed)
    free_throws_attempted = sum(row.free_throws_attempted for row in allowed)
    return {
        "counting_per_100_possessions": {
            key: value * 100 / possessions for key, value in per_100_fields.items()
        },
        "ratios": {
            "field_goals": {
                "made": field_goals_made,
                "attempted": field_goals_attempted,
                "rate": (
                    field_goals_made / field_goals_attempted if field_goals_attempted else None
                ),
            },
            "free_throws": {
                "made": free_throws_made,
                "attempted": free_throws_attempted,
                "rate": (
                    free_throws_made / free_throws_attempted if free_throws_attempted else None
                ),
            },
        },
        "normalization_possessions": possessions,
    }


def _score_margin_histories(
    games: Sequence[GameResult],
    *,
    before: date,
    window_games: int,
) -> dict[int, tuple[int, ...]]:
    margins: dict[int, list[int]] = defaultdict(list)
    for game in sorted(games, key=lambda row: (row.game_date, row.game_id)):
        if game.game_date >= before:
            continue
        margin = game.home_score - game.away_score
        margins[game.home_team_id].append(margin)
        margins[game.away_team_id].append(-margin)
    return {team_id: tuple(values[-window_games:]) for team_id, values in margins.items()}


def _empirical_midrank(ordered_values: Sequence[int], value: int) -> float:
    lower = sum(item < value for item in ordered_values)
    equal = sum(item == value for item in ordered_values)
    return (lower + equal / 2) / len(ordered_values)


def _lower_quantile(ordered_values: Sequence[int], probability: float) -> int:
    index = max(0, min(len(ordered_values) - 1, int(probability * len(ordered_values)) - 1))
    return ordered_values[index]
