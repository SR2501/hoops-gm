"""Descriptive durability evidence without manufacturing complete availability.

The participation ledger is observation-only: a missing row is not an absence.
This module therefore reports direct observed play/non-play evidence separately
from played-game production consistency. It does not produce a reliability
grade, a ranking, a value, or a projected games-played number.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.lineage import (
    content_fingerprint,
    current_refresh,
    lock_refresh_scope,
    record_refresh,
    verify_refresh,
)
from hoops_gm.db.models.availability import PlayerParticipation
from hoops_gm.db.models.enums import (
    GameStatus,
    ParticipationOutcome,
    RefreshArtifactType,
    SeasonType,
)
from hoops_gm.db.models.lineage import RefreshRun
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import BOX_SCORE_STAT_KEYS, NbaGame, PlayerGameLog
from hoops_gm.ingest.nba.schedule import build_schedule_density

SCHEDULE_KEY: Final = "nba-schedule"
RELIABILITY_SOURCE_KEY: Final = "reliability-observations"
RELIABILITY_DERIVATION_KEY: Final = "reliability-derivation"
OBSERVED_COVERAGE_STATUS: Final = "incomplete_r35"

RELIABILITY_COUNTING_CATEGORIES: Final = (
    ("fg3m", "three_pointers_made"),
    ("pts", "points"),
    ("reb", "rebounds"),
    ("ast", "assists"),
    ("stl", "steals"),
    ("blk", "blocks"),
    ("to", "turnovers"),
)
RELIABILITY_RATIO_CATEGORIES: Final = (
    ("fg_pct", "field_goals_made", "field_goals_attempted"),
    ("ft_pct", "free_throws_made", "free_throws_attempted"),
)
_NON_PLAY_OUTCOMES: Final = frozenset(
    {
        ParticipationOutcome.DID_NOT_PLAY,
        ParticipationOutcome.DID_NOT_DRESS,
        ParticipationOutcome.NOT_WITH_TEAM,
        ParticipationOutcome.INACTIVE,
    }
)
_SUPPORTED_OUTCOMES: Final = _NON_PLAY_OUTCOMES | {
    ParticipationOutcome.PLAYED,
    ParticipationOutcome.UNKNOWN,
}

CoverageStatus = Literal["incomplete_r35"]
ObservationKind = Literal["played", "non_play", "unknown"]
CategoryUnit = Literal["count", "volume_weighted_impact"]


class ReliabilityInputError(ValueError):
    """Stored observations cannot support a coherent descriptive scorecard."""


class StaleReliabilityCohortError(ValueError):
    """A claimed schedule, source, or derivation cohort is not current."""


@dataclass(frozen=True)
class ReliabilityConfig:
    """Versioned descriptive choices; none is fitted on player outcomes."""

    lower_percentile: float = 0.20
    upper_percentile: float = 0.80

    def __post_init__(self) -> None:
        if not 0 <= self.lower_percentile < self.upper_percentile <= 1:
            raise ValueError("percentiles must satisfy 0 <= lower < upper <= 1")

    @property
    def derivation_version(self) -> str:
        return content_fingerprint(
            [
                "reliability-descriptive-v1",
                "availability:direct-observations-only",
                "trend:calendar-month",
                "b2b:schedule-density-v1",
                "dispersion:sample-standard-deviation",
                "quantile:type-7",
                f"lower:{self.lower_percentile.hex()}",
                f"upper:{self.upper_percentile.hex()}",
                "ratio-impact:made-minus-attempt-weighted-cohort-rate-times-attempts",
                ",".join(
                    f"{category}:{field}" for category, field in RELIABILITY_COUNTING_CATEGORIES
                ),
                ",".join(
                    f"{category}:{made}:{attempted}"
                    for category, made, attempted in RELIABILITY_RATIO_CATEGORIES
                ),
            ]
        )


@dataclass(frozen=True)
class ReliabilityCohortClaim:
    season: str
    season_type: SeasonType
    window_start: date
    as_of_date: date
    schedule_version: str
    source_version: str
    derivation_version: str


@dataclass(frozen=True)
class RateEvidence:
    """Direct observations only; opportunity coverage is unknowable under R35."""

    direct_play: int
    direct_non_play: int
    explicit_unknown: int
    observed_play_rate: float | None
    observed_non_play_rate: float | None
    coverage_status: CoverageStatus
    opportunity_coverage: None
    game_log_ids: tuple[int, ...]
    participation_ids: tuple[int, ...]

    @property
    def observed_opportunities(self) -> int:
        return self.direct_play + self.direct_non_play


@dataclass(frozen=True)
class MonthlyRateEvidence:
    month: date
    evidence: RateEvidence


@dataclass(frozen=True)
class AvailabilityEvidence:
    overall: RateEvidence
    monthly_trend: tuple[MonthlyRateEvidence, ...]
    back_to_back: RateEvidence


@dataclass(frozen=True)
class DistributionSummary:
    observed_games: int
    lower_percentile_probability: float
    upper_percentile_probability: float
    mean: float | None
    sample_standard_deviation: float | None
    lower_percentile: float | None
    upper_percentile: float | None


@dataclass(frozen=True)
class MinutesConsistency:
    distribution_minutes: DistributionSummary
    coefficient_of_variation: float | None


@dataclass(frozen=True)
class RatioBaseline:
    made: int
    attempted: int
    rate: float | None


@dataclass(frozen=True)
class CategoryConsistency:
    category: str
    unit: CategoryUnit
    distribution: DistributionSummary
    ratio_baseline: RatioBaseline | None


@dataclass(frozen=True)
class ProductionConsistency:
    played_games: int
    minutes: MinutesConsistency
    categories: tuple[CategoryConsistency, ...]
    game_log_ids: tuple[int, ...]


@dataclass(frozen=True)
class ReliabilityLineage:
    season: str
    season_type: SeasonType
    window_start: date
    as_of_date: date
    schedule_version: str
    schedule_refreshed_at: datetime
    source_version: str
    derivation_version: str
    computed_at: datetime


@dataclass(frozen=True)
class PlayerReliabilityScorecard:
    player_id: int
    availability: AvailabilityEvidence
    production: ProductionConsistency
    lineage: ReliabilityLineage


@dataclass(frozen=True)
class ReliabilityRun:
    lineage: ReliabilityLineage
    schedule_context_team_games: int
    scheduled_team_games: int
    final_games: int
    player_game_logs: int
    participation_rows: int
    scorecards: tuple[PlayerReliabilityScorecard, ...]


@dataclass(frozen=True)
class _SourceSnapshot:
    season: str
    season_type: SeasonType
    window_start: date
    as_of_date: date
    schedule_entries: tuple[TeamScheduleEntry, ...]
    final_games: tuple[NbaGame, ...]
    logs: tuple[PlayerGameLog, ...]
    participation: tuple[PlayerParticipation, ...]


@dataclass(frozen=True)
class _Observation:
    player_id: int
    game_id: int
    team_id: int
    game_date: date
    is_back_to_back: bool
    kind: ObservationKind
    game_log_id: int | None
    participation_id: int | None


@dataclass(frozen=True)
class _VerifiedRefresh:
    run: RefreshRun
    version: str


def publish_reliability_cohorts(
    session: Session,
    *,
    season: str,
    as_of_date: date,
    window_start: date | None = None,
    season_type: SeasonType = SeasonType.REGULAR,
    config: ReliabilityConfig | None = None,
    refreshed_at: datetime | None = None,
) -> ReliabilityCohortClaim:
    """Publish the exact observations and descriptive derivation a run may use."""

    selected_config = config or ReliabilityConfig()
    _lock_claim_scopes(session, season=season)
    schedule_refresh = _require_current(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=SCHEDULE_KEY,
        season=season,
    )
    snapshot = _source_snapshot(
        session,
        season=season,
        season_type=season_type,
        window_start=window_start,
        as_of_date=as_of_date,
    )
    source_version = _snapshot_version(snapshot)
    when = _aware_utc(refreshed_at or datetime.now(UTC), field="refreshed_at")
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SOURCE,
        artifact_key=RELIABILITY_SOURCE_KEY,
        version=source_version,
        season=season,
        source="nba_games+team_schedule+player_game_logs+player_participation",
        summary={
            "claim": "descriptive direct observations",
            "season_type": season_type.value,
            "window_start": snapshot.window_start.isoformat(),
            "as_of_date": as_of_date.isoformat(),
            "schedule_context_team_games": len(snapshot.schedule_entries),
            "scheduled_team_games": sum(
                entry.game_date >= snapshot.window_start for entry in snapshot.schedule_entries
            ),
            "final_games": len(snapshot.final_games),
            "player_game_logs": len(snapshot.logs),
            "participation_rows": len(snapshot.participation),
            "missing_rows_classified": 0,
            "opportunity_coverage": None,
        },
        refreshed_at=when,
    )
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.MODEL,
        artifact_key=RELIABILITY_DERIVATION_KEY,
        version=selected_config.derivation_version,
        season=season,
        source="quant:reliability-descriptive-derivation",
        summary={
            "claim": "descriptive; not a reliability grade or prediction",
            "lower_percentile": selected_config.lower_percentile,
            "upper_percentile": selected_config.upper_percentile,
            "availability_evidence": "direct observations only; R35 incomplete",
            "blowout_suppression": "not released",
            "composite_grade": "not defined",
        },
        refreshed_at=when,
    )
    return ReliabilityCohortClaim(
        season=season,
        season_type=season_type,
        window_start=snapshot.window_start,
        as_of_date=as_of_date,
        schedule_version=schedule_refresh.version,
        source_version=source_version,
        derivation_version=selected_config.derivation_version,
    )


def compute_reliability_scorecards(
    session: Session,
    *,
    claim: ReliabilityCohortClaim,
    config: ReliabilityConfig | None = None,
    computed_at: datetime | None = None,
) -> ReliabilityRun:
    """Compute one immutable in-memory scorecard cohort from an exact claim."""

    selected_config = config or ReliabilityConfig()
    when = _aware_utc(computed_at or datetime.now(UTC), field="computed_at")
    _lock_claim_scopes(session, season=claim.season)
    schedule_refresh = _require_current(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=SCHEDULE_KEY,
        season=claim.season,
        version=claim.schedule_version,
    )
    _require_current(
        session,
        artifact_type=RefreshArtifactType.SOURCE,
        artifact_key=RELIABILITY_SOURCE_KEY,
        season=claim.season,
        version=claim.source_version,
    )
    _require_current(
        session,
        artifact_type=RefreshArtifactType.MODEL,
        artifact_key=RELIABILITY_DERIVATION_KEY,
        season=claim.season,
        version=claim.derivation_version,
    )
    if selected_config.derivation_version != claim.derivation_version:
        raise StaleReliabilityCohortError(
            "reliability config does not match the published derivation claim"
        )

    snapshot = _source_snapshot(
        session,
        season=claim.season,
        season_type=claim.season_type,
        window_start=claim.window_start,
        as_of_date=claim.as_of_date,
    )
    if snapshot.window_start != claim.window_start:
        raise StaleReliabilityCohortError("resolved reliability window changed after publication")
    if _snapshot_version(snapshot) != claim.source_version:
        raise StaleReliabilityCohortError(
            "reliability observations changed after source publication"
        )

    density = build_schedule_density(
        snapshot.schedule_entries,
        schedule_version=schedule_refresh.version,
        schedule_refreshed_at=schedule_refresh.run.refreshed_at,
    )
    density_by_team_game = {(row.team_id, row.game_id): row.is_back_to_back for row in density}
    observations = _observations(snapshot, density_by_team_game=density_by_team_game)
    observations_by_player: dict[int, list[_Observation]] = defaultdict(list)
    for observation in observations:
        observations_by_player[observation.player_id].append(observation)

    logs_by_player: dict[int, list[PlayerGameLog]] = defaultdict(list)
    for log in snapshot.logs:
        logs_by_player[log.player_id].append(log)
    ratio_baselines = {
        category: _ratio_baseline(snapshot.logs, made_field=made, attempted_field=attempted)
        for category, made, attempted in RELIABILITY_RATIO_CATEGORIES
    }

    lineage = ReliabilityLineage(
        season=claim.season,
        season_type=claim.season_type,
        window_start=claim.window_start,
        as_of_date=claim.as_of_date,
        schedule_version=schedule_refresh.version,
        schedule_refreshed_at=schedule_refresh.run.refreshed_at,
        source_version=claim.source_version,
        derivation_version=claim.derivation_version,
        computed_at=when,
    )
    player_ids = sorted(set(observations_by_player) | set(logs_by_player))
    scorecards = tuple(
        PlayerReliabilityScorecard(
            player_id=player_id,
            availability=_availability_evidence(observations_by_player[player_id]),
            production=_production_consistency(
                logs_by_player[player_id],
                ratio_baselines=ratio_baselines,
                config=selected_config,
            ),
            lineage=lineage,
        )
        for player_id in player_ids
    )
    return ReliabilityRun(
        lineage=lineage,
        schedule_context_team_games=len(snapshot.schedule_entries),
        scheduled_team_games=sum(
            entry.game_date >= snapshot.window_start for entry in snapshot.schedule_entries
        ),
        final_games=len(snapshot.final_games),
        player_game_logs=len(snapshot.logs),
        participation_rows=len(snapshot.participation),
        scorecards=scorecards,
    )


def _source_snapshot(
    session: Session,
    *,
    season: str,
    season_type: SeasonType,
    window_start: date | None,
    as_of_date: date,
) -> _SourceSnapshot:
    season_entries = session.scalars(
        select(TeamScheduleEntry)
        .where(
            TeamScheduleEntry.season == season,
            TeamScheduleEntry.season_type == season_type,
            TeamScheduleEntry.game_date <= as_of_date,
        )
        .order_by(
            TeamScheduleEntry.game_date,
            TeamScheduleEntry.game_id,
            TeamScheduleEntry.team_id,
        )
    ).all()
    if not season_entries:
        raise ReliabilityInputError(
            f"no scheduled team games found for {season} through {as_of_date.isoformat()}"
        )
    resolved_start = window_start or season_entries[0].game_date
    if resolved_start > as_of_date:
        raise ValueError("window_start must not be after as_of_date")
    if not any(entry.game_date >= resolved_start for entry in season_entries):
        raise ReliabilityInputError("reliability window contains no scheduled team games")
    # Density at the first date in a requested sub-window still needs the
    # immediately preceding schedule. Keep all season-to-date calendar rows as
    # density inputs; production and participation remain window-bounded below.
    schedule_entries = tuple(season_entries)

    final_games = tuple(
        session.scalars(
            select(NbaGame)
            .where(
                NbaGame.season == season,
                NbaGame.season_type == season_type,
                NbaGame.status == GameStatus.FINAL,
                NbaGame.game_date.between(resolved_start, as_of_date),
            )
            .order_by(NbaGame.game_date, NbaGame.nba_game_id)
        ).all()
    )
    if not final_games:
        raise ReliabilityInputError("reliability window contains no final games")
    schedule_teams_by_game: dict[int, set[int]] = defaultdict(set)
    for entry in schedule_entries:
        schedule_teams_by_game[entry.game_id].add(entry.team_id)
    for game in final_games:
        expected_teams = {game.home_team_id, game.away_team_id}
        if schedule_teams_by_game.get(game.id, set()) != expected_teams:
            raise ReliabilityInputError(
                f"final game {game.nba_game_id} does not have exact home/away "
                "team_schedule coverage"
            )
    final_game_ids = {game.id for game in final_games}
    logs = tuple(
        session.scalars(
            select(PlayerGameLog)
            .where(PlayerGameLog.game_id.in_(final_game_ids))
            .order_by(PlayerGameLog.game_id, PlayerGameLog.team_id, PlayerGameLog.player_id)
        ).all()
    )
    if not logs:
        raise ReliabilityInputError("reliability window contains no player game logs")
    participation = tuple(
        session.scalars(
            select(PlayerParticipation)
            .where(PlayerParticipation.game_id.in_(final_game_ids))
            .order_by(
                PlayerParticipation.game_id,
                PlayerParticipation.team_id,
                PlayerParticipation.player_id,
            )
        ).all()
    )
    return _SourceSnapshot(
        season=season,
        season_type=season_type,
        window_start=resolved_start,
        as_of_date=as_of_date,
        schedule_entries=schedule_entries,
        final_games=final_games,
        logs=logs,
        participation=participation,
    )


def _snapshot_version(snapshot: _SourceSnapshot) -> str:
    parts = [
        "reliability-observations-v1",
        f"season:{snapshot.season}",
        f"season_type:{snapshot.season_type.value}",
        f"window_start:{snapshot.window_start.isoformat()}",
        f"as_of_date:{snapshot.as_of_date.isoformat()}",
    ]
    parts.extend(
        "schedule:"
        + ":".join(
            (
                str(entry.id),
                str(entry.game_id),
                str(entry.team_id),
                str(entry.opponent_team_id),
                entry.game_date.isoformat(),
                str(entry.is_home),
            )
        )
        for entry in snapshot.schedule_entries
    )
    parts.extend(
        "game:"
        + ":".join(
            (
                str(game.id),
                game.nba_game_id,
                game.game_date.isoformat(),
                str(game.home_team_id),
                str(game.away_team_id),
                str(game.home_score),
                str(game.away_score),
                game.status.value,
            )
        )
        for game in snapshot.final_games
    )
    parts.extend(
        "log:"
        + ":".join(
            (
                str(log.id),
                str(log.player_id),
                str(log.game_id),
                str(log.team_id),
                str(log.started),
                *(str(getattr(log, field)) for field in BOX_SCORE_STAT_KEYS),
            )
        )
        for log in snapshot.logs
    )
    parts.extend(
        "participation:"
        + ":".join(
            (
                str(row.id),
                str(row.player_id),
                str(row.game_id),
                str(row.team_id),
                row.outcome.value,
                row.reason.value,
                row.raw_comment,
                str(row.seconds_played),
                row.source.value,
                str(row.inactive_list_available),
            )
        )
        for row in snapshot.participation
    )
    return content_fingerprint(parts)


def _observations(
    snapshot: _SourceSnapshot,
    *,
    density_by_team_game: dict[tuple[int, int], bool],
) -> tuple[_Observation, ...]:
    schedule_by_team_game = {
        (entry.team_id, entry.game_id): entry for entry in snapshot.schedule_entries
    }
    games_by_id = {game.id: game for game in snapshot.final_games}
    logs_by_player_game = {(log.player_id, log.game_id): log for log in snapshot.logs}
    participation_by_player_game = {
        (row.player_id, row.game_id): row for row in snapshot.participation
    }
    observations: list[_Observation] = []
    keys = sorted(
        set(logs_by_player_game) | set(participation_by_player_game),
        key=lambda key: (games_by_id[key[1]].game_date, key[1], key[0]),
    )
    for player_id, game_id in keys:
        log = logs_by_player_game.get((player_id, game_id))
        participation = participation_by_player_game.get((player_id, game_id))
        if participation is not None and participation.outcome not in _SUPPORTED_OUTCOMES:
            raise ReliabilityInputError(
                f"unsupported participation outcome {participation.outcome.value!r} "
                f"for player {player_id}, game {game_id}"
            )
        team_id = log.team_id if log is not None else _participation_team(participation)
        if participation is not None and log is not None and participation.team_id != log.team_id:
            raise ReliabilityInputError(
                f"player {player_id} is assigned to teams {log.team_id} and "
                f"{participation.team_id} in game {game_id}"
            )
        if (
            log is not None
            and participation is not None
            and participation.outcome in _NON_PLAY_OUTCOMES
        ):
            raise ReliabilityInputError(
                f"player {player_id} has a game log and {participation.outcome.value} "
                f"participation for game {game_id}"
            )
        entry = schedule_by_team_game.get((team_id, game_id))
        if entry is None:
            raise ReliabilityInputError(
                f"player {player_id} observation for team {team_id}, game {game_id} "
                "has no schedule row"
            )
        is_back_to_back = density_by_team_game.get((team_id, game_id))
        if is_back_to_back is None:
            raise ReliabilityInputError(
                f"team {team_id}, game {game_id} has no schedule-density record"
            )
        if log is not None or (
            participation is not None and participation.outcome == ParticipationOutcome.PLAYED
        ):
            kind: ObservationKind = "played"
        elif participation is not None and participation.outcome == ParticipationOutcome.UNKNOWN:
            kind = "unknown"
        elif participation is not None and participation.outcome in _NON_PLAY_OUTCOMES:
            kind = "non_play"
        else:
            raise AssertionError("every observation has one supported direct-evidence outcome")
        observations.append(
            _Observation(
                player_id=player_id,
                game_id=game_id,
                team_id=team_id,
                game_date=entry.game_date,
                is_back_to_back=is_back_to_back,
                kind=kind,
                game_log_id=log.id if log is not None else None,
                participation_id=participation.id if participation is not None else None,
            )
        )
    return tuple(observations)


def _participation_team(row: PlayerParticipation | None) -> int:
    if row is None:
        raise AssertionError("observation keys come from a game log or participation row")
    return row.team_id


def _availability_evidence(observations: Sequence[_Observation]) -> AvailabilityEvidence:
    ordered = sorted(observations, key=lambda row: (row.game_date, row.game_id))
    by_month: dict[date, list[_Observation]] = defaultdict(list)
    for observation in ordered:
        by_month[observation.game_date.replace(day=1)].append(observation)
    return AvailabilityEvidence(
        overall=_rate_evidence(ordered),
        monthly_trend=tuple(
            MonthlyRateEvidence(month=month, evidence=_rate_evidence(rows))
            for month, rows in sorted(by_month.items())
        ),
        back_to_back=_rate_evidence([row for row in ordered if row.is_back_to_back]),
    )


def _rate_evidence(observations: Sequence[_Observation]) -> RateEvidence:
    direct_play = sum(row.kind == "played" for row in observations)
    direct_non_play = sum(row.kind == "non_play" for row in observations)
    explicit_unknown = sum(row.kind == "unknown" for row in observations)
    denominator = direct_play + direct_non_play
    return RateEvidence(
        direct_play=direct_play,
        direct_non_play=direct_non_play,
        explicit_unknown=explicit_unknown,
        observed_play_rate=None if denominator == 0 else direct_play / denominator,
        observed_non_play_rate=None if denominator == 0 else direct_non_play / denominator,
        coverage_status=OBSERVED_COVERAGE_STATUS,
        opportunity_coverage=None,
        game_log_ids=tuple(
            sorted(row.game_log_id for row in observations if row.game_log_id is not None)
        ),
        participation_ids=tuple(
            sorted(row.participation_id for row in observations if row.participation_id is not None)
        ),
    )


def _production_consistency(
    logs: Sequence[PlayerGameLog],
    *,
    ratio_baselines: dict[str, RatioBaseline],
    config: ReliabilityConfig,
) -> ProductionConsistency:
    ordered = sorted(logs, key=lambda row: (row.game_id, row.id))
    minute_values = []
    for log in ordered:
        if log.seconds_played is None:
            continue
        if log.seconds_played < 0:
            raise ReliabilityInputError(f"negative seconds_played in player_game_log {log.id}")
        minute_values.append(log.seconds_played / 60)
    minute_distribution = _distribution(
        minute_values,
        lower_percentile=config.lower_percentile,
        upper_percentile=config.upper_percentile,
    )
    coefficient_of_variation = None
    if (
        minute_distribution.mean is not None
        and minute_distribution.mean > 0
        and minute_distribution.sample_standard_deviation is not None
    ):
        coefficient_of_variation = (
            minute_distribution.sample_standard_deviation / minute_distribution.mean
        )

    categories: list[CategoryConsistency] = []
    for category, field in RELIABILITY_COUNTING_CATEGORIES:
        values = []
        for log in ordered:
            value = getattr(log, field)
            if value is None:
                continue
            if value < 0:
                raise ReliabilityInputError(f"negative {field} in player_game_log {log.id}")
            values.append(float(value))
        categories.append(
            CategoryConsistency(
                category=category,
                unit="count",
                distribution=_distribution(
                    values,
                    lower_percentile=config.lower_percentile,
                    upper_percentile=config.upper_percentile,
                ),
                ratio_baseline=None,
            )
        )
    for category, made_field, attempted_field in RELIABILITY_RATIO_CATEGORIES:
        baseline = ratio_baselines[category]
        impacts: list[float] = []
        if baseline.rate is not None:
            for log in ordered:
                made = getattr(log, made_field)
                attempted = getattr(log, attempted_field)
                if made is None or attempted is None:
                    continue
                _validate_shooting(log.id, made, attempted, made_field, attempted_field)
                impacts.append(volume_weighted_impact(made, attempted, baseline.rate))
        categories.append(
            CategoryConsistency(
                category=category,
                unit="volume_weighted_impact",
                distribution=_distribution(
                    impacts,
                    lower_percentile=config.lower_percentile,
                    upper_percentile=config.upper_percentile,
                ),
                ratio_baseline=baseline,
            )
        )
    return ProductionConsistency(
        played_games=len(ordered),
        minutes=MinutesConsistency(
            distribution_minutes=minute_distribution,
            coefficient_of_variation=coefficient_of_variation,
        ),
        categories=tuple(categories),
        game_log_ids=tuple(log.id for log in ordered),
    )


def _ratio_baseline(
    logs: Iterable[PlayerGameLog],
    *,
    made_field: str,
    attempted_field: str,
) -> RatioBaseline:
    made_total = 0
    attempted_total = 0
    for log in logs:
        made = getattr(log, made_field)
        attempted = getattr(log, attempted_field)
        if made is None or attempted is None:
            continue
        _validate_shooting(log.id, made, attempted, made_field, attempted_field)
        made_total += made
        attempted_total += attempted
    return RatioBaseline(
        made=made_total,
        attempted=attempted_total,
        rate=None if attempted_total == 0 else made_total / attempted_total,
    )


def _validate_shooting(
    log_id: int,
    made: int,
    attempted: int,
    made_field: str,
    attempted_field: str,
) -> None:
    if made < 0 or attempted < 0 or made > attempted:
        raise ReliabilityInputError(
            f"invalid shooting components in player_game_log {log_id}: "
            f"{made_field}={made}, {attempted_field}={attempted}"
        )


def _distribution(
    values: Sequence[float],
    *,
    lower_percentile: float,
    upper_percentile: float,
) -> DistributionSummary:
    if not values:
        return DistributionSummary(
            observed_games=0,
            lower_percentile_probability=lower_percentile,
            upper_percentile_probability=upper_percentile,
            mean=None,
            sample_standard_deviation=None,
            lower_percentile=None,
            upper_percentile=None,
        )
    mean = sum(values) / len(values)
    standard_deviation = sample_standard_deviation(values)
    return DistributionSummary(
        observed_games=len(values),
        lower_percentile_probability=lower_percentile,
        upper_percentile_probability=upper_percentile,
        mean=mean,
        sample_standard_deviation=standard_deviation,
        lower_percentile=type7_quantile(values, lower_percentile),
        upper_percentile=type7_quantile(values, upper_percentile),
    )


def sample_standard_deviation(values: Sequence[float]) -> float | None:
    """Return sample SD for shared runtime and evidence calculations."""

    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def type7_quantile(values: Sequence[float], probability: float) -> float:
    """Return the deterministic Hyndman-Fan Type-7 empirical quantile."""

    if not values:
        raise ValueError("quantile requires at least one value")
    if not 0 <= probability <= 1:
        raise ValueError("quantile probability must be in [0, 1]")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    weight = position - lower_index
    return ordered[lower_index] * (1 - weight) + ordered[upper_index] * weight


def volume_weighted_impact(
    made: int,
    attempted: int,
    baseline_rate: float,
) -> float:
    """Return one game's ratio-category impact without discarding volume."""

    return made - baseline_rate * attempted


def _lock_claim_scopes(session: Session, *, season: str) -> None:
    for artifact_type, artifact_key in (
        (RefreshArtifactType.SCHEDULE, SCHEDULE_KEY),
        (RefreshArtifactType.SOURCE, RELIABILITY_SOURCE_KEY),
        (RefreshArtifactType.MODEL, RELIABILITY_DERIVATION_KEY),
    ):
        lock_refresh_scope(
            session,
            artifact_type=artifact_type,
            artifact_key=artifact_key,
            season=season,
        )


def _require_current(
    session: Session,
    *,
    artifact_type: RefreshArtifactType,
    artifact_key: str,
    season: str,
    version: str | None = None,
) -> _VerifiedRefresh:
    current = current_refresh(
        session,
        artifact_type,
        artifact_key=artifact_key,
        season=season,
    )
    if current is None:
        raise StaleReliabilityCohortError(
            f"no current {artifact_type.value}:{artifact_key} cohort for season {season}"
        )
    try:
        verification = verify_refresh(session, current)
    except ValueError as exc:
        raise StaleReliabilityCohortError(
            f"cannot verify current {artifact_type.value}:{artifact_key} cohort for season {season}"
        ) from exc
    if not verification.is_current or verification.current_version is None:
        raise StaleReliabilityCohortError(
            f"registered {artifact_type.value}:{artifact_key} cohort "
            f"{verification.registered_version} is no longer current for season {season}"
        )
    if version is not None and verification.current_version != version:
        raise StaleReliabilityCohortError(
            f"stale {artifact_type.value}:{artifact_key} cohort {version}; "
            f"current is {verification.current_version}"
        )
    return _VerifiedRefresh(current, verification.current_version)


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)
