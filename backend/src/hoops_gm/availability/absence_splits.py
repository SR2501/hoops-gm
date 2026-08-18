"""Descriptive teammate splits from directly observed participation evidence.

No value from this module is a causal effect or a recommendation. A ``without``
sample requires an explicit non-play row in ``player_participation``. Missing
rows are never classified: the repository does not yet have either
authoritative historical roster intervals or a per-game ingestion-completeness
artifact, and R35 requires both before silence can become absence evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models.availability import (
    AbsenceSplit,
    AbsenceSplitComputationRun,
    PlayerParticipation,
)
from hoops_gm.db.models.enums import (
    GameStatus,
    ParticipationOutcome,
    RefreshArtifactType,
    SeasonType,
)
from hoops_gm.db.models.lineage import RefreshRun
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import BOX_SCORE_STAT_KEYS, NbaGame, PlayerGameLog

ABSENCE_SPLIT_EVIDENCE_VERSION: Final = "absence-splits-descriptive-v2"
DIRECT_EVIDENCE_METHOD: Final = "observed-participation-only-v1"

_COUNTING_STATS: Final = (
    "seconds_played",
    "three_pointers_made",
    "points",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
)
_RATIO_STATS: Final = {
    "field_goals": ("field_goals_made", "field_goals_attempted"),
    "free_throws": ("free_throws_made", "free_throws_attempted"),
}
_NON_PLAY_OUTCOMES: Final = {
    ParticipationOutcome.DID_NOT_PLAY,
    ParticipationOutcome.DID_NOT_DRESS,
    ParticipationOutcome.NOT_WITH_TEAM,
    ParticipationOutcome.INACTIVE,
}


class AbsenceSplitInputError(ValueError):
    """The source rows cannot support an honest direct-evidence split."""


@dataclass(frozen=True)
class AbsenceSplitRun:
    """Result of one complete successful descriptive computation."""

    computation_run: AbsenceSplitComputationRun
    rows: tuple[AbsenceSplit, ...]
    created: int
    skipped_one_sided_pairs: int


@dataclass(frozen=True)
class _Sample:
    log: PlayerGameLog
    provenance: dict[str, object]


@dataclass
class _PairSamples:
    with_samples: list[_Sample] = field(default_factory=list)
    without_samples: list[_Sample] = field(default_factory=list)
    observed_absence_games: int = 0
    explicit_unknown_game_ids: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class _SplitDraft:
    beneficiary_player_id: int
    absent_player_id: int
    team_id: int
    games_with: int
    games_without: int
    observed_absence_games: int
    production_with: dict[str, object]
    production_without: dict[str, object]
    descriptive_deltas: dict[str, object]
    uncertainty: dict[str, object]
    provenance: dict[str, object]


def compute_absence_splits(
    session: Session,
    *,
    season: str,
    season_type: SeasonType = SeasonType.REGULAR,
    evidence_version: str = ABSENCE_SPLIT_EVIDENCE_VERSION,
    computed_at: datetime | None = None,
) -> AbsenceSplitRun:
    """Compute and persist one complete direct-evidence cohort.

    A run row is persisted even when every candidate pair is one-sided and no
    split rows are produced. That empty run supersedes earlier cohorts, so a
    pair removed by corrected input cannot survive through a stale row.
    """

    schedule_refresh = _schedule_refresh(session, season)
    if schedule_refresh is None:
        raise AbsenceSplitInputError(
            f"no registered schedule refresh for {season}; source cohort is unknowable"
        )

    schedule = session.scalars(
        select(TeamScheduleEntry)
        .join(NbaGame, NbaGame.id == TeamScheduleEntry.game_id)
        .where(
            TeamScheduleEntry.season == season,
            TeamScheduleEntry.season_type == season_type,
            NbaGame.status == GameStatus.FINAL,
        )
        .order_by(
            TeamScheduleEntry.game_date,
            TeamScheduleEntry.game_id,
            TeamScheduleEntry.team_id,
        )
    ).all()
    if not schedule:
        raise AbsenceSplitInputError(f"no final scheduled team games found for {season}")

    schedule_by_key = {(entry.team_id, entry.game_id): entry for entry in schedule}
    game_ids = {entry.game_id for entry in schedule}
    logs = session.scalars(
        select(PlayerGameLog)
        .where(PlayerGameLog.game_id.in_(game_ids))
        .order_by(PlayerGameLog.game_id, PlayerGameLog.team_id, PlayerGameLog.player_id)
    ).all()
    participation = session.scalars(
        select(PlayerParticipation)
        .where(PlayerParticipation.game_id.in_(game_ids))
        .order_by(
            PlayerParticipation.game_id,
            PlayerParticipation.team_id,
            PlayerParticipation.player_id,
        )
    ).all()

    logs_by_game_team: dict[tuple[int, int], list[PlayerGameLog]] = defaultdict(list)
    logs_by_player_game: dict[tuple[int, int], PlayerGameLog] = {}
    participation_by_player_game: dict[tuple[int, int], PlayerParticipation] = {}
    for log in logs:
        _require_schedule_entry(schedule_by_key, log.team_id, log.game_id, "game log")
        logs_by_game_team[(log.game_id, log.team_id)].append(log)
        logs_by_player_game[(log.player_id, log.game_id)] = log

    for row in participation:
        _require_schedule_entry(schedule_by_key, row.team_id, row.game_id, "participation row")
        key = (row.player_id, row.game_id)
        target_log = logs_by_player_game.get(key)
        if target_log is not None and target_log.team_id != row.team_id:
            raise AbsenceSplitInputError(
                f"player {row.player_id} is assigned to teams {target_log.team_id} "
                f"and {row.team_id} in game {row.game_id}"
            )
        if target_log is not None and row.outcome in _NON_PLAY_OUTCOMES:
            raise AbsenceSplitInputError(
                f"player {row.player_id} has a game log and {row.outcome.value} "
                f"participation for game {row.game_id}"
            )
        participation_by_player_game[key] = row

    when = computed_at if computed_at is not None else datetime.now(UTC)
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("computed_at must be timezone-aware")
    fingerprint = _fingerprint(
        schedule_refresh.version,
        evidence_version,
        [_schedule_input(entry) for entry in schedule],
        [_log_input(log) for log in logs],
        [_participation_input(row) for row in participation],
    )

    pairs: dict[tuple[int, int, int], _PairSamples] = defaultdict(_PairSamples)
    target_keys = sorted(
        set(logs_by_player_game) | set(participation_by_player_game),
        key=lambda key: (key[1], key[0]),
    )
    for absent_player_id, game_id in target_keys:
        target_log = logs_by_player_game.get((absent_player_id, game_id))
        target_participation = participation_by_player_game.get((absent_player_id, game_id))
        team_id = _target_team_id(target_log, target_participation)
        condition = _condition(target_log, target_participation)
        entry = _require_schedule_entry(schedule_by_key, team_id, game_id, "target evidence")
        for beneficiary_log in logs_by_game_team.get((game_id, team_id), []):
            if beneficiary_log.player_id == absent_player_id:
                continue
            pair = pairs[(beneficiary_log.player_id, absent_player_id, team_id)]
            if condition == "unknown":
                pair.explicit_unknown_game_ids.add(game_id)
                continue
            sample = _Sample(
                log=beneficiary_log,
                provenance=_sample_provenance(
                    entry=entry,
                    beneficiary_log=beneficiary_log,
                    target_log=target_log,
                    target_participation=target_participation,
                    condition=condition,
                ),
            )
            if condition == "with":
                pair.with_samples.append(sample)
            else:
                pair.without_samples.append(sample)
                pair.observed_absence_games += 1

    skipped = sum(
        not samples.with_samples or not samples.without_samples for samples in pairs.values()
    )

    # Validate and materialize the whole cohort before persisting its activation.
    # A caller may catch AbsenceSplitInputError and commit the surrounding
    # transaction; no failed computation may then become the latest run.
    drafts: list[_SplitDraft] = []
    for (beneficiary_id, absent_id, team_id), samples in sorted(pairs.items()):
        if not samples.with_samples or not samples.without_samples:
            continue
        production_with = _summarize([sample.log for sample in samples.with_samples])
        production_without = _summarize([sample.log for sample in samples.without_samples])
        drafts.append(
            _SplitDraft(
                beneficiary_player_id=beneficiary_id,
                absent_player_id=absent_id,
                team_id=team_id,
                games_with=len(samples.with_samples),
                games_without=len(samples.without_samples),
                observed_absence_games=samples.observed_absence_games,
                production_with=production_with,
                production_without=production_without,
                descriptive_deltas=_deltas(production_with, production_without),
                uncertainty={
                    "sample_sizes": {
                        "with": len(samples.with_samples),
                        "without": len(samples.without_samples),
                    },
                    "variance_estimable": {
                        "with": len(samples.with_samples) >= 2,
                        "without": len(samples.without_samples) >= 2,
                    },
                    "counting": (
                        "sample standard deviation and standard error across beneficiary games"
                    ),
                    "shooting": (
                        "aggregate makes/attempts only; no interval is estimated because "
                        "attempts cluster within games"
                    ),
                    "causal_effect": False,
                    "recommendation": False,
                },
                provenance={
                    "contract": "descriptive_observational_evidence",
                    "absence_evidence_method": DIRECT_EVIDENCE_METHOD,
                    "with_samples": [sample.provenance for sample in samples.with_samples],
                    "without_samples": [sample.provenance for sample in samples.without_samples],
                    "explicit_unknown_game_ids": sorted(samples.explicit_unknown_game_ids),
                    "missing_rows_classified": 0,
                },
            )
        )

    run = AbsenceSplitComputationRun(
        season=season,
        season_type=season_type,
        evidence_version=evidence_version,
        input_fingerprint=fingerprint,
        schedule_version=schedule_refresh.version,
        schedule_refreshed_at=schedule_refresh.refreshed_at,
        computed_at=when,
        result_count=len(drafts),
        skipped_one_sided_pairs=skipped,
    )
    session.add(run)
    session.flush()

    output_rows: list[AbsenceSplit] = []
    for draft in drafts:
        split = AbsenceSplit(
            run_id=run.id,
            beneficiary_player_id=draft.beneficiary_player_id,
            absent_player_id=draft.absent_player_id,
            team_id=draft.team_id,
            games_with=draft.games_with,
            games_without=draft.games_without,
            observed_absence_games=draft.observed_absence_games,
            production_with=draft.production_with,
            production_without=draft.production_without,
            descriptive_deltas=draft.descriptive_deltas,
            uncertainty=draft.uncertainty,
            provenance=draft.provenance,
        )
        session.add(split)
        output_rows.append(split)

    session.flush()
    return AbsenceSplitRun(
        computation_run=run,
        rows=tuple(output_rows),
        created=len(output_rows),
        skipped_one_sided_pairs=skipped,
    )


def latest_absence_splits(
    session: Session,
    *,
    season: str,
    season_type: SeasonType = SeasonType.REGULAR,
    evidence_version: str = ABSENCE_SPLIT_EVIDENCE_VERSION,
) -> tuple[AbsenceSplit, ...]:
    """Rows from exactly the latest successful current-schedule run."""

    schedule_refresh = _schedule_refresh(session, season)
    if schedule_refresh is None:
        raise AbsenceSplitInputError(
            f"no registered schedule refresh for {season}; current splits are unknowable"
        )
    run = session.scalar(
        select(AbsenceSplitComputationRun)
        .where(
            AbsenceSplitComputationRun.season == season,
            AbsenceSplitComputationRun.season_type == season_type,
            AbsenceSplitComputationRun.evidence_version == evidence_version,
            AbsenceSplitComputationRun.schedule_version == schedule_refresh.version,
        )
        .order_by(AbsenceSplitComputationRun.id.desc())
        .limit(1)
    )
    return () if run is None else _rows_for_run(session, run.id)


def _rows_for_run(session: Session, run_id: int) -> tuple[AbsenceSplit, ...]:
    return tuple(
        session.scalars(
            select(AbsenceSplit)
            .where(AbsenceSplit.run_id == run_id)
            .order_by(
                AbsenceSplit.beneficiary_player_id,
                AbsenceSplit.absent_player_id,
                AbsenceSplit.team_id,
            )
        ).all()
    )


def _schedule_refresh(session: Session, season: str) -> RefreshRun | None:
    return session.scalar(
        select(RefreshRun)
        .where(
            RefreshRun.artifact_type == RefreshArtifactType.SCHEDULE,
            RefreshRun.season == season,
        )
        .order_by(RefreshRun.refreshed_at.desc(), RefreshRun.id.desc())
        .limit(1)
    )


def _require_schedule_entry(
    schedule_by_key: dict[tuple[int, int], TeamScheduleEntry],
    team_id: int,
    game_id: int,
    source_kind: str,
) -> TeamScheduleEntry:
    entry = schedule_by_key.get((team_id, game_id))
    if entry is None:
        raise AbsenceSplitInputError(
            f"{source_kind} for team {team_id}, game {game_id} has no matching final schedule row"
        )
    return entry


def _target_team_id(
    target_log: PlayerGameLog | None,
    target_participation: PlayerParticipation | None,
) -> int:
    if target_log is not None:
        return target_log.team_id
    if target_participation is not None:
        return target_participation.team_id
    raise AssertionError("target keys come only from direct source rows")


def _condition(
    target_log: PlayerGameLog | None,
    target_participation: PlayerParticipation | None,
) -> Literal["with", "without_observed", "unknown"]:
    if target_log is not None:
        return "with"
    if target_participation is None:
        raise AssertionError("missing rows are never target evidence")
    if target_participation.outcome == ParticipationOutcome.PLAYED:
        return "with"
    if target_participation.outcome == ParticipationOutcome.UNKNOWN:
        return "unknown"
    return "without_observed"


def _sample_provenance(
    *,
    entry: TeamScheduleEntry,
    beneficiary_log: PlayerGameLog,
    target_log: PlayerGameLog | None,
    target_participation: PlayerParticipation | None,
    condition: str,
) -> dict[str, object]:
    if target_log is not None:
        target_evidence: dict[str, object] = {
            "kind": "player_game_log",
            "player_game_log_id": target_log.id,
            "participation_id": (
                target_participation.id if target_participation is not None else None
            ),
            "participation_outcome": (
                target_participation.outcome.value if target_participation is not None else None
            ),
        }
    elif target_participation is not None:
        target_evidence = {
            "kind": "participation",
            "participation_id": target_participation.id,
            "outcome": target_participation.outcome.value,
            "source": target_participation.source.value,
            "inactive_list_available": target_participation.inactive_list_available,
        }
    else:  # pragma: no cover - guarded by _condition
        raise AssertionError("missing rows cannot produce a sample")
    return {
        "game_id": entry.game_id,
        "team_schedule_id": entry.id,
        "game_date": entry.game_date.isoformat(),
        "beneficiary_game_log_id": beneficiary_log.id,
        "condition": condition,
        "target_evidence": target_evidence,
    }


def _schedule_input(entry: TeamScheduleEntry) -> dict[str, object]:
    return {
        "id": entry.id,
        "game_id": entry.game_id,
        "team_id": entry.team_id,
        "opponent_team_id": entry.opponent_team_id,
        "game_date": entry.game_date.isoformat(),
        "is_home": entry.is_home,
    }


def _log_input(log: PlayerGameLog) -> dict[str, object]:
    return {
        "id": log.id,
        "player_id": log.player_id,
        "game_id": log.game_id,
        "team_id": log.team_id,
        "started": log.started,
        "stats": {key: getattr(log, key) for key in BOX_SCORE_STAT_KEYS},
    }


def _participation_input(row: PlayerParticipation) -> dict[str, object]:
    return {
        "id": row.id,
        "player_id": row.player_id,
        "game_id": row.game_id,
        "team_id": row.team_id,
        "outcome": row.outcome.value,
        "reason": row.reason.value,
        "raw_comment": row.raw_comment,
        "seconds_played": row.seconds_played,
        "source": row.source.value,
        "inactive_list_available": row.inactive_list_available,
    }


def _summarize(logs: list[PlayerGameLog]) -> dict[str, object]:
    counting: dict[str, object] = {}
    for stat in _COUNTING_STATS:
        values = [float(value) for log in logs if (value := getattr(log, stat)) is not None]
        counting[stat] = _count_summary(values)

    shooting: dict[str, object] = {}
    for label, (made_stat, attempted_stat) in _RATIO_STATS.items():
        samples: list[tuple[int, int]] = []
        for log in logs:
            made = getattr(log, made_stat)
            attempted = getattr(log, attempted_stat)
            if made is None or attempted is None:
                continue
            if made < 0 or attempted < 0 or made > attempted:
                raise AbsenceSplitInputError(
                    f"invalid shooting components in player_game_log {log.id}: "
                    f"{made_stat}={made}, {attempted_stat}={attempted}"
                )
            samples.append((made, attempted))
        shooting[label] = _ratio_summary(samples)
    return {"games": len(logs), "counting": counting, "shooting": shooting}


def _count_summary(values: list[float]) -> dict[str, object]:
    count = len(values)
    if count == 0:
        return {
            "observed_games": 0,
            "total": None,
            "per_game": None,
            "sample_standard_deviation": None,
            "standard_error": None,
        }
    total = sum(values)
    mean = total / count
    if count < 2:
        standard_deviation = None
        standard_error = None
    else:
        standard_deviation = math.sqrt(sum((value - mean) ** 2 for value in values) / (count - 1))
        standard_error = standard_deviation / math.sqrt(count)
    return {
        "observed_games": count,
        "total": total,
        "per_game": mean,
        "sample_standard_deviation": standard_deviation,
        "standard_error": standard_error,
    }


def _ratio_summary(samples: list[tuple[int, int]]) -> dict[str, object]:
    made = sum(value[0] for value in samples)
    attempted = sum(value[1] for value in samples)
    return {
        "observed_games": len(samples),
        "made": made,
        "attempted": attempted,
        "aggregate_rate": None if attempted == 0 else made / attempted,
        "interval": None,
        "interval_reason": "not estimated: attempts cluster within games",
    }


def _deltas(with_stats: dict[str, object], without_stats: dict[str, object]) -> dict[str, object]:
    with_counting = _object_dict(with_stats["counting"])
    without_counting = _object_dict(without_stats["counting"])
    counting: dict[str, object] = {}
    for stat in _COUNTING_STATS:
        with_summary = _object_dict(with_counting[stat])
        without_summary = _object_dict(without_counting[stat])
        with_mean = _optional_float(with_summary["per_game"])
        without_mean = _optional_float(without_summary["per_game"])
        with_se = _optional_float(with_summary["standard_error"])
        without_se = _optional_float(without_summary["standard_error"])
        counting[stat] = {
            "without_minus_with_per_game": (
                None if with_mean is None or without_mean is None else without_mean - with_mean
            ),
            "delta_standard_error": (
                None
                if with_se is None or without_se is None
                else math.sqrt(with_se**2 + without_se**2)
            ),
        }

    with_shooting = _object_dict(with_stats["shooting"])
    without_shooting = _object_dict(without_stats["shooting"])
    shooting: dict[str, object] = {}
    for label in _RATIO_STATS:
        with_rate = _optional_float(_object_dict(with_shooting[label])["aggregate_rate"])
        without_rate = _optional_float(_object_dict(without_shooting[label])["aggregate_rate"])
        shooting[label] = {
            "without_minus_with_aggregate_rate": (
                None if with_rate is None or without_rate is None else without_rate - with_rate
            ),
            "delta_interval": None,
            "interval_reason": "not estimated: attempts cluster within games",
        }
    return {"counting": counting, "shooting": shooting}


def _object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"expected a dict, got {type(value).__name__}")
    return value


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise TypeError(f"expected a number, got {type(value).__name__}")
    return float(value)


def _fingerprint(*parts: object) -> str:
    rendered = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()
