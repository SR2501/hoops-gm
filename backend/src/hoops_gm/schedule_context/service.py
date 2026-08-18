"""Transactional persistence and cohort enforcement for schedule context."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.lineage import (
    SCHEDULE_CONTEXT_SOURCE_KEY,
    content_fingerprint,
    current_refresh,
    lock_refresh_scope,
    record_refresh,
)
from hoops_gm.db.models.enums import RefreshArtifactType, SeasonType
from hoops_gm.db.models.lineage import RefreshRun
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.schedule_context import OffNightSlate, OpponentContext
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog
from hoops_gm.schedule_context.blowout import BlowoutModel, GameResult
from hoops_gm.schedule_context.features import (
    ContextGame,
    InsufficientContextError,
    OpponentProfile,
    RecentObservationAudit,
    ScheduleContextConfig,
    TeamGameStats,
    build_off_night_facts,
    build_opponent_profile,
)
from hoops_gm.schedule_context.release import (
    RELEASED_BLOWOUT_MODEL_VERSION,
    load_blowout_release,
)

SCHEDULE_KEY = "nba-schedule"
SOURCE_KEY = SCHEDULE_CONTEXT_SOURCE_KEY
BLOWOUT_MODEL_KEY = "schedule-context-blowout"
OFF_NIGHT_MODEL_KEY = "schedule-context-off-night"

_STAT_FIELDS = (
    "seconds_played",
    "field_goals_made",
    "field_goals_attempted",
    "three_pointers_made",
    "free_throws_made",
    "free_throws_attempted",
    "points",
    "offensive_rebounds",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
)


class StaleContextCohortError(ValueError):
    """A claimed schedule/source/model cohort is not current."""


class IncompleteTeamBoxScoreError(ValueError):
    """A game cannot support pace/category context without complete team totals."""


class InsufficientContextCoverageError(ValueError):
    """Too few eligible fixtures produced valid opponent context."""


@dataclass(frozen=True)
class ContextCohortClaim:
    schedule_version: str
    source_version: str
    opponent_model_version: str
    off_night_model_version: str


@dataclass
class ContextWriteCounts:
    opponent_created: int = 0
    opponent_updated: int = 0
    slate_created: int = 0
    slate_updated: int = 0
    opponent_skipped: int = 0
    opponent_eligible: int = 0
    opponent_coverage: float = 0.0


@dataclass(frozen=True)
class ContextCoverageAudit:
    eligible_fixture_rows: int
    produced_fixture_rows: int
    skipped_fixture_rows: int
    coverage_ratio: float
    minimum_coverage_ratio: float
    audited_team_fixture_histories: int
    scored_team_game_observations: int
    complete_team_game_observations: int
    incomplete_team_game_observations: int
    maximum_days_since_latest_scored_game: int | None
    maximum_days_since_latest_complete_game: int | None

    def as_dict(self) -> dict[str, object]:
        return {
            "rule": "produced_regular_season_fixture_rows_over_scheduled_fixture_rows_v1",
            "eligible_fixture_rows": self.eligible_fixture_rows,
            "produced_fixture_rows": self.produced_fixture_rows,
            "skipped_fixture_rows": self.skipped_fixture_rows,
            "coverage_ratio": self.coverage_ratio,
            "minimum_coverage_ratio": self.minimum_coverage_ratio,
            "observation_completeness": {
                "rule": "last_n_scored_regular_season_team_games_complete_v1",
                "audited_team_fixture_histories": self.audited_team_fixture_histories,
                "scored_team_game_observations": self.scored_team_game_observations,
                "complete_team_game_observations": self.complete_team_game_observations,
                "incomplete_team_game_observations": self.incomplete_team_game_observations,
                "maximum_days_since_latest_scored_game": (
                    self.maximum_days_since_latest_scored_game
                ),
                "maximum_days_since_latest_complete_game": (
                    self.maximum_days_since_latest_complete_game
                ),
            },
        }


@dataclass(frozen=True)
class SourceSnapshot:
    games: tuple[NbaGame, ...]
    logs: tuple[PlayerGameLog, ...]


def context_source_version(session: Session) -> str:
    """Fingerprint the exact completed scores and player-log fields in storage."""

    return _snapshot_version(_source_snapshot(session))


def _snapshot_version(snapshot: SourceSnapshot) -> str:
    parts = ["season_type:regular"]
    parts.extend(
        f"game:{game.id}:{game.nba_game_id}:{game.game_date.isoformat()}:"
        f"{game.home_team_id}:{game.away_team_id}:{game.home_score}:{game.away_score}"
        for game in snapshot.games
    )
    parts.extend(
        "log:"
        + ":".join(
            [
                str(log.game_id),
                str(log.team_id),
                str(log.player_id),
                *(str(getattr(log, field)) for field in _STAT_FIELDS),
            ]
        )
        for log in snapshot.logs
    )
    if not parts:
        raise ValueError("schedule context source has no completed observations")
    return content_fingerprint(parts)


def publish_schedule_context_cohorts(
    session: Session,
    *,
    season: str,
    config: ScheduleContextConfig,
    blowout_model_version: str = RELEASED_BLOWOUT_MODEL_VERSION,
    refreshed_at: datetime | None = None,
) -> ContextCohortClaim:
    """Explicitly publish the source and model cohorts a production run may use."""

    release = load_blowout_release(blowout_model_version)
    blowout_model = release.model
    _lock_claim_scopes(session, season=season)
    schedule = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=SCHEDULE_KEY,
        season=season,
    )
    if schedule is None:
        raise StaleContextCohortError(f"no registered schedule cohort for {season}")
    source_version = context_source_version(session)
    when = refreshed_at or datetime.now(UTC)
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SOURCE,
        artifact_key=SOURCE_KEY,
        version=source_version,
        source="nba_games+player_game_logs",
        summary={
            "purpose": "schedule context observations",
            "season_type": SeasonType.REGULAR.value,
            "box_score_completeness": (
                "each_team_player_seconds_equals_240_plus_25_per_overtime_v1"
            ),
            "observation_completeness": ("last_n_scored_regular_season_team_games_complete_v1"),
            "observation_window_games": config.trailing_games,
        },
        refreshed_at=when,
    )
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.MODEL,
        artifact_key=BLOWOUT_MODEL_KEY,
        version=blowout_model.version,
        source="quant:schedule-context-blowout",
        season=season,
        summary={
            "evidence_version": release.evidence_version,
            "training_cutoff": blowout_model.training_cutoff.isoformat(),
            "training_examples": blowout_model.training_examples,
            "training_source_version": blowout_model.source_version,
            "holdout_source_version": release.holdout_source_fingerprint,
            "held_out_examples": release.held_out_examples,
        },
        refreshed_at=when,
    )
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.MODEL,
        artifact_key=OFF_NIGHT_MODEL_KEY,
        version=config.off_night_model_version,
        source="quant:off-night-descriptive-derivation",
        season=season,
        summary={"threshold_percentile": config.off_night_percentile},
        refreshed_at=when,
    )
    return ContextCohortClaim(
        schedule_version=schedule.version,
        source_version=source_version,
        opponent_model_version=blowout_model.version,
        off_night_model_version=config.off_night_model_version,
    )


def compute_schedule_context(
    session: Session,
    *,
    season: str,
    claim: ContextCohortClaim,
    config: ScheduleContextConfig,
    computed_at: datetime | None = None,
) -> ContextWriteCounts:
    """Validate one cohort atomically, then retain versioned context history."""

    when = _utc_datetime(computed_at or datetime.now(UTC), field="computed_at")
    release = load_blowout_release(claim.opponent_model_version)
    blowout_model = release.model
    _lock_claim_scopes(session, season=season)
    schedule_refresh = _require_current(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=SCHEDULE_KEY,
        version=claim.schedule_version,
        season=season,
    )
    _require_current(
        session,
        artifact_type=RefreshArtifactType.SOURCE,
        artifact_key=SOURCE_KEY,
        version=claim.source_version,
        season=None,
    )
    _require_current(
        session,
        artifact_type=RefreshArtifactType.MODEL,
        artifact_key=BLOWOUT_MODEL_KEY,
        version=claim.opponent_model_version,
        season=season,
    )
    _require_current(
        session,
        artifact_type=RefreshArtifactType.MODEL,
        artifact_key=OFF_NIGHT_MODEL_KEY,
        version=claim.off_night_model_version,
        season=season,
    )
    source_snapshot = _source_snapshot(session)
    if _snapshot_version(source_snapshot) != claim.source_version:
        raise StaleContextCohortError("context observations changed after source publication")
    if blowout_model.version != claim.opponent_model_version:
        raise StaleContextCohortError("supplied blowout model does not match its claim")
    if config.off_night_model_version != claim.off_night_model_version:
        raise StaleContextCohortError("off-night derivation does not match its claim")

    schedule_entries = session.scalars(
        select(TeamScheduleEntry)
        .where(
            TeamScheduleEntry.season == season,
            TeamScheduleEntry.season_type == SeasonType.REGULAR,
        )
        .order_by(TeamScheduleEntry.game_date, TeamScheduleEntry.game_id, TeamScheduleEntry.team_id)
    ).all()
    results = [_game_result(game) for game in source_snapshot.games]
    context_games = _context_games(source_snapshot.games, source_snapshot.logs)
    prepared_profiles, coverage = _prepare_opponent_profiles(
        entries=schedule_entries,
        context_games=context_games,
        score_games=results,
        blowout_model=blowout_model,
        config=config,
    )
    counts = ContextWriteCounts()
    counts.opponent_eligible = coverage.eligible_fixture_rows
    counts.opponent_skipped = coverage.skipped_fixture_rows
    counts.opponent_coverage = coverage.coverage_ratio
    _write_slates(
        session,
        entries=schedule_entries,
        season=season,
        claim=claim,
        config=config,
        refreshed_at=schedule_refresh.refreshed_at,
        computed_at=when,
        coverage=coverage,
        counts=counts,
    )
    _write_opponents(
        session,
        prepared_profiles=prepared_profiles,
        season=season,
        claim=claim,
        blowout_model=blowout_model,
        refreshed_at=schedule_refresh.refreshed_at,
        computed_at=when,
        coverage=coverage,
        counts=counts,
    )
    _recheck_claim(session, season=season, claim=claim)
    session.flush()
    return counts


def _lock_claim_scopes(session: Session, *, season: str) -> None:
    """Use the same order as publication so concurrent transactions cannot deadlock."""

    for artifact_type, artifact_key, scope in (
        (RefreshArtifactType.SCHEDULE, SCHEDULE_KEY, season),
        (RefreshArtifactType.SOURCE, SOURCE_KEY, None),
        (RefreshArtifactType.MODEL, BLOWOUT_MODEL_KEY, season),
        (RefreshArtifactType.MODEL, OFF_NIGHT_MODEL_KEY, season),
    ):
        lock_refresh_scope(
            session,
            artifact_type=artifact_type,
            artifact_key=artifact_key,
            season=scope,
        )


def _write_slates(
    session: Session,
    *,
    entries: Sequence[TeamScheduleEntry],
    season: str,
    claim: ContextCohortClaim,
    config: ScheduleContextConfig,
    refreshed_at: datetime,
    computed_at: datetime,
    coverage: ContextCoverageAudit,
    counts: ContextWriteCounts,
) -> None:
    existing = {
        (row.slate_date, row.model_version, row.schedule_version, row.source_version): row
        for row in session.scalars(select(OffNightSlate).where(OffNightSlate.season == season))
    }
    for fact in build_off_night_facts(entries, config=config):
        key = (
            fact.slate_date,
            claim.off_night_model_version,
            claim.schedule_version,
            claim.source_version,
        )
        row = existing.get(key)
        if row is None:
            row = OffNightSlate(
                season=season,
                slate_date=fact.slate_date,
                model_version=claim.off_night_model_version,
                schedule_version=claim.schedule_version,
                source_version=claim.source_version,
                schedule_refreshed_at=refreshed_at,
                computed_at=computed_at,
            )
            session.add(row)
            counts.slate_created += 1
        else:
            counts.slate_updated += 1
        row.scheduled_game_count = fact.scheduled_game_count
        row.scheduled_team_count = fact.scheduled_team_count
        row.is_off_night = fact.is_off_night
        row.light_slate_percentile = fact.light_slate_percentile
        row.threshold_games = fact.threshold_games
        row.threshold_percentile = fact.threshold_percentile
        row.streaming_window_score = None
        row.input_snapshot = {
            **fact.input_snapshot,
            "opponent_context_coverage": coverage.as_dict(),
        }
        row.schedule_refreshed_at = refreshed_at
        row.computed_at = computed_at


def _write_opponents(
    session: Session,
    *,
    prepared_profiles: Sequence[tuple[TeamScheduleEntry, OpponentProfile]],
    season: str,
    claim: ContextCohortClaim,
    blowout_model: BlowoutModel,
    refreshed_at: datetime,
    computed_at: datetime,
    coverage: ContextCoverageAudit,
    counts: ContextWriteCounts,
) -> None:
    existing = {
        (
            row.team_schedule_id,
            row.model_version,
            row.schedule_version,
            row.source_version,
        ): row
        for row in session.scalars(select(OpponentContext).where(OpponentContext.season == season))
    }
    for entry, profile in prepared_profiles:
        key = (
            entry.id,
            claim.opponent_model_version,
            claim.schedule_version,
            claim.source_version,
        )
        row = existing.get(key)
        if row is None:
            row = OpponentContext(
                season=season,
                game_date=entry.game_date,
                team_schedule_id=entry.id,
                team_id=entry.team_id,
                opponent_team_id=entry.opponent_team_id,
                is_home=entry.is_home,
                model_version=claim.opponent_model_version,
                schedule_version=claim.schedule_version,
                source_version=claim.source_version,
                schedule_refreshed_at=refreshed_at,
                computed_at=computed_at,
            )
            session.add(row)
            counts.opponent_created += 1
        else:
            counts.opponent_updated += 1
        row.pace_possessions = profile.pace_possessions
        row.pace_window_games = profile.pace_window_games
        row.category_defence = profile.category_defence
        row.defence_window_games = profile.defence_window_games
        row.blowout_probability = profile.blowout_probability
        row.garbage_time_suppression = None
        row.training_cutoff = blowout_model.training_cutoff
        row.input_snapshot = {
            **profile.input_snapshot,
            "opponent_context_coverage": coverage.as_dict(),
        }
        row.schedule_refreshed_at = refreshed_at
        row.computed_at = computed_at


def _require_current(
    session: Session,
    *,
    artifact_type: RefreshArtifactType,
    artifact_key: str,
    version: str,
    season: str | None,
) -> RefreshRun:
    current = current_refresh(
        session,
        artifact_type,
        artifact_key=artifact_key,
        season=season,
    )
    if current is None:
        raise StaleContextCohortError(
            f"no current {artifact_type.value}:{artifact_key} cohort for season {season}"
        )
    if current.version != version:
        raise StaleContextCohortError(
            f"stale {artifact_type.value}:{artifact_key} cohort "
            f"{version}; current is {current.version}"
        )
    return current


def _recheck_claim(
    session: Session,
    *,
    season: str,
    claim: ContextCohortClaim,
) -> None:
    for artifact_type, artifact_key, version, scope in (
        (
            RefreshArtifactType.SCHEDULE,
            SCHEDULE_KEY,
            claim.schedule_version,
            season,
        ),
        (RefreshArtifactType.SOURCE, SOURCE_KEY, claim.source_version, None),
        (
            RefreshArtifactType.MODEL,
            BLOWOUT_MODEL_KEY,
            claim.opponent_model_version,
            season,
        ),
        (
            RefreshArtifactType.MODEL,
            OFF_NIGHT_MODEL_KEY,
            claim.off_night_model_version,
            season,
        ),
    ):
        _require_current(
            session,
            artifact_type=artifact_type,
            artifact_key=artifact_key,
            version=version,
            season=scope,
        )


def _source_snapshot(session: Session) -> SourceSnapshot:
    rows = session.execute(
        select(NbaGame, PlayerGameLog)
        .outerjoin(PlayerGameLog, PlayerGameLog.game_id == NbaGame.id)
        .where(
            NbaGame.home_score.is_not(None),
            NbaGame.away_score.is_not(None),
            NbaGame.season_type == SeasonType.REGULAR,
        )
        .order_by(
            NbaGame.game_date,
            NbaGame.nba_game_id,
            PlayerGameLog.team_id,
            PlayerGameLog.player_id,
        )
    ).all()
    games_by_id: dict[int, NbaGame] = {}
    logs: list[PlayerGameLog] = []
    for game, log in rows:
        games_by_id[game.id] = game
        if log is not None:
            logs.append(log)
    return SourceSnapshot(
        games=tuple(games_by_id.values()),
        logs=tuple(logs),
    )


def _context_games(
    games: Sequence[NbaGame],
    logs: Sequence[PlayerGameLog],
) -> list[ContextGame]:
    if not games:
        return []
    by_game_team: dict[tuple[int, int], list[PlayerGameLog]] = defaultdict(list)
    for log in logs:
        by_game_team[(log.game_id, log.team_id)].append(log)

    context: list[ContextGame] = []
    for game in games:
        try:
            home = _sum_team_logs(by_game_team[(game.id, game.home_team_id)])
            away = _sum_team_logs(by_game_team[(game.id, game.away_team_id)])
            context_game = ContextGame(_game_result(game), home, away)
        except (IncompleteTeamBoxScoreError, ValueError):
            continue
        context.append(context_game)
    return context


def _sum_team_logs(logs: Iterable[PlayerGameLog]) -> TeamGameStats:
    values = dict.fromkeys(_STAT_FIELDS, 0)
    found = False
    player_seconds: list[int] = []
    for log in logs:
        found = True
        for field in _STAT_FIELDS:
            value = getattr(log, field)
            if value is None:
                raise IncompleteTeamBoxScoreError(f"{field} is missing")
            values[field] += value
        if log.seconds_played is not None and log.seconds_played > 0:
            player_seconds.append(log.seconds_played)
    if not found:
        raise IncompleteTeamBoxScoreError("team has no player logs")
    total_seconds = values["seconds_played"]
    if total_seconds < 14_400 or (total_seconds - 14_400) % 1_500:
        raise IncompleteTeamBoxScoreError("team player-minutes must equal 240 plus 25 per overtime")
    overtime_periods = (total_seconds - 14_400) // 1_500
    game_seconds = 2_880 + overtime_periods * 300
    if len(player_seconds) < 5 or any(seconds > game_seconds for seconds in player_seconds):
        raise IncompleteTeamBoxScoreError(
            "team box score must contain at least five plausible player-minute rows"
        )
    try:
        return TeamGameStats(**values)
    except ValueError as exc:
        raise IncompleteTeamBoxScoreError(str(exc)) from exc


def _prepare_opponent_profiles(
    *,
    entries: Sequence[TeamScheduleEntry],
    context_games: Sequence[ContextGame],
    score_games: Sequence[GameResult],
    blowout_model: BlowoutModel,
    config: ScheduleContextConfig,
) -> tuple[list[tuple[TeamScheduleEntry, OpponentProfile]], ContextCoverageAudit]:
    prepared: list[tuple[TeamScheduleEntry, OpponentProfile]] = []
    observation_audits: dict[tuple[int, date], RecentObservationAudit] = {}
    skipped = 0
    for entry in entries:
        try:
            profile = build_opponent_profile(
                team_id=entry.team_id,
                opponent_team_id=entry.opponent_team_id,
                fixture_date=entry.game_date,
                context_games=context_games,
                score_games=score_games,
                blowout_model=blowout_model,
                config=config,
            )
        except InsufficientContextError:
            skipped += 1
            continue
        prepared.append((entry, profile))
        for audit in profile.observation_audits:
            observation_audits[(audit.team_id, audit.features_as_of)] = audit
    eligible = len(entries)
    coverage_ratio = len(prepared) / eligible if eligible else 0.0
    scored_recencies = [
        (audit.features_as_of - audit.latest_scored_game_date).days
        for audit in observation_audits.values()
        if audit.latest_scored_game_date is not None
    ]
    complete_recencies = [
        (audit.features_as_of - audit.latest_complete_game_date).days
        for audit in observation_audits.values()
        if audit.latest_complete_game_date is not None
    ]
    coverage = ContextCoverageAudit(
        eligible_fixture_rows=eligible,
        produced_fixture_rows=len(prepared),
        skipped_fixture_rows=skipped,
        coverage_ratio=coverage_ratio,
        minimum_coverage_ratio=config.minimum_opponent_coverage,
        audited_team_fixture_histories=len(observation_audits),
        scored_team_game_observations=sum(
            len(audit.scored_game_ids) for audit in observation_audits.values()
        ),
        complete_team_game_observations=sum(
            len(audit.complete_game_ids) for audit in observation_audits.values()
        ),
        incomplete_team_game_observations=sum(
            len(audit.incomplete_game_ids) for audit in observation_audits.values()
        ),
        maximum_days_since_latest_scored_game=max(scored_recencies, default=None),
        maximum_days_since_latest_complete_game=max(complete_recencies, default=None),
    )
    if not prepared or coverage_ratio < config.minimum_opponent_coverage:
        raise InsufficientContextCoverageError(
            "opponent context coverage "
            f"{len(prepared)}/{eligible} ({coverage_ratio:.3f}) is below required "
            f"{config.minimum_opponent_coverage:.3f}"
        )
    return prepared, coverage


def _utc_datetime(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _game_result(game: NbaGame) -> GameResult:
    if game.home_score is None or game.away_score is None:
        raise ValueError("game is not final")
    return GameResult(
        game_id=game.nba_game_id,
        game_date=game.game_date,
        home_team_id=game.home_team_id,
        away_team_id=game.away_team_id,
        home_score=game.home_score,
        away_score=game.away_score,
    )
