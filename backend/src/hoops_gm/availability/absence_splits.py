"""Descriptive teammate production splits across observed absence conditions.

No value from this module is a causal effect or a recommendation. It aggregates
what one player produced in games where a teammate played versus games where
the teammate did not play. A missing participation row is an absence only when
the game falls inside a same-team membership segment bounded by observations on
both sides. Everything outside those bounds remains unknown.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Final, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models.availability import AbsenceSplit, PlayerParticipation
from hoops_gm.db.models.enums import (
    GameStatus,
    ParticipationOutcome,
    RefreshArtifactType,
    SeasonType,
)
from hoops_gm.db.models.lineage import RefreshRun
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog

ABSENCE_SPLIT_EVIDENCE_VERSION: Final = "absence-splits-descriptive-v1"
BOUNDED_MEMBERSHIP_METHOD: Final = "bounded-observed-team-segments-v1"

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
    """The source rows cannot support an honest absence classification."""


@dataclass(frozen=True)
class AbsenceSplitRun:
    """Result of one idempotent descriptive evidence computation."""

    rows: tuple[AbsenceSplit, ...]
    created: int
    reused: int
    skipped_one_sided_pairs: int


@dataclass
class _MembershipObservation:
    player_id: int
    game_id: int
    team_id: int
    game_date: date
    game_log_id: int | None = None
    participation_id: int | None = None

    def reference(self) -> dict[str, object]:
        return {
            "game_id": self.game_id,
            "team_id": self.team_id,
            "game_date": self.game_date.isoformat(),
            "player_game_log_id": self.game_log_id,
            "participation_id": self.participation_id,
        }


@dataclass(frozen=True)
class _MembershipSegment:
    team_id: int
    start: _MembershipObservation
    end: _MembershipObservation


@dataclass(frozen=True)
class _Sample:
    log: PlayerGameLog
    provenance: dict[str, object]


@dataclass
class _PairSamples:
    with_samples: list[_Sample] = field(default_factory=list)
    without_samples: list[_Sample] = field(default_factory=list)
    explicit_absence_games: int = 0
    inferred_absence_games: int = 0
    unknown_game_ids: set[int] = field(default_factory=set)


def compute_absence_splits(
    session: Session,
    *,
    season: str,
    season_type: SeasonType = SeasonType.REGULAR,
    evidence_version: str = ABSENCE_SPLIT_EVIDENCE_VERSION,
    computed_at: datetime | None = None,
) -> AbsenceSplitRun:
    """Compute and persist descriptive pair splits for one season.

    The current season-specific schedule refresh is mandatory. Without it, the
    roster-cross-schedule inference has no versioned calendar provenance and
    fails closed instead of treating missing rows as absences.
    """

    schedule_refresh = _schedule_refresh(session, season)
    if schedule_refresh is None:
        raise AbsenceSplitInputError(
            f"no registered schedule refresh for {season}; missing rows cannot be classified"
        )

    schedule = session.scalars(
        select(TeamScheduleEntry)
        .join(NbaGame, NbaGame.id == TeamScheduleEntry.game_id)
        .where(
            TeamScheduleEntry.season == season,
            TeamScheduleEntry.season_type == season_type,
            NbaGame.status == GameStatus.FINAL,
        )
        .order_by(TeamScheduleEntry.game_date, TeamScheduleEntry.game_id)
    ).all()
    if not schedule:
        raise AbsenceSplitInputError(f"no final scheduled team games found for {season}")

    schedule_by_team: dict[int, list[TeamScheduleEntry]] = defaultdict(list)
    schedule_by_key: dict[tuple[int, int], TeamScheduleEntry] = {}
    game_ids = {entry.game_id for entry in schedule}
    for entry in schedule:
        schedule_by_team[entry.team_id].append(entry)
        schedule_by_key[(entry.team_id, entry.game_id)] = entry

    logs = session.scalars(
        select(PlayerGameLog)
        .where(PlayerGameLog.game_id.in_(game_ids))
        .order_by(PlayerGameLog.game_id, PlayerGameLog.player_id)
    ).all()
    participation = session.scalars(
        select(PlayerParticipation)
        .where(PlayerParticipation.game_id.in_(game_ids))
        .order_by(PlayerParticipation.game_id, PlayerParticipation.player_id)
    ).all()

    logs_by_game_team: dict[tuple[int, int], list[PlayerGameLog]] = defaultdict(list)
    logs_by_player_game: dict[tuple[int, int], PlayerGameLog] = {}
    participation_by_player_game: dict[tuple[int, int], PlayerParticipation] = {}
    observations: dict[tuple[int, int], _MembershipObservation] = {}

    for log in logs:
        entry = _require_schedule_entry(schedule_by_key, log.team_id, log.game_id, "game log")
        logs_by_game_team[(log.game_id, log.team_id)].append(log)
        logs_by_player_game[(log.player_id, log.game_id)] = log
        observation = _observation(observations, log.player_id, entry)
        observation.game_log_id = log.id

    for participation_row in participation:
        entry = _require_schedule_entry(
            schedule_by_key,
            participation_row.team_id,
            participation_row.game_id,
            "participation row",
        )
        key = (participation_row.player_id, participation_row.game_id)
        target_game_log = logs_by_player_game.get(key)
        if target_game_log is not None and participation_row.outcome in _NON_PLAY_OUTCOMES:
            raise AbsenceSplitInputError(
                f"player {participation_row.player_id} has a game log and "
                f"{participation_row.outcome.value} participation for game "
                f"{participation_row.game_id}"
            )
        participation_by_player_game[key] = participation_row
        observation = _observation(observations, participation_row.player_id, entry)
        observation.participation_id = participation_row.id

    observations_by_player: dict[int, list[_MembershipObservation]] = defaultdict(list)
    for observation in observations.values():
        observations_by_player[observation.player_id].append(observation)

    pairs: dict[tuple[int, int, int], _PairSamples] = defaultdict(_PairSamples)
    for absent_player_id, player_observations in observations_by_player.items():
        for segment in _membership_segments(player_observations):
            for entry in schedule_by_team[segment.team_id]:
                if not (segment.start.game_date <= entry.game_date <= segment.end.game_date):
                    continue
                target_key = (absent_player_id, entry.game_id)
                target_log = logs_by_player_game.get(target_key)
                target_participation = participation_by_player_game.get(target_key)
                condition = _condition(target_log, target_participation)
                beneficiaries = logs_by_game_team.get((entry.game_id, segment.team_id), [])
                for beneficiary_log in beneficiaries:
                    if beneficiary_log.player_id == absent_player_id:
                        continue
                    pair = pairs[(beneficiary_log.player_id, absent_player_id, segment.team_id)]
                    if condition == "unknown":
                        pair.unknown_game_ids.add(entry.game_id)
                        continue
                    sample = _Sample(
                        log=beneficiary_log,
                        provenance=_sample_provenance(
                            entry=entry,
                            beneficiary_log=beneficiary_log,
                            target_log=target_log,
                            target_participation=target_participation,
                            segment=segment,
                            condition=condition,
                        ),
                    )
                    if condition == "with":
                        pair.with_samples.append(sample)
                    else:
                        pair.without_samples.append(sample)
                        if condition == "without_explicit":
                            pair.explicit_absence_games += 1
                        else:
                            pair.inferred_absence_games += 1

    when = computed_at if computed_at is not None else datetime.now(UTC)
    if when.tzinfo is None:
        raise ValueError("computed_at must be timezone-aware")

    created = 0
    reused = 0
    skipped = 0
    output_rows: list[AbsenceSplit] = []
    for (beneficiary_id, absent_id, team_id), samples in sorted(pairs.items()):
        if not samples.with_samples or not samples.without_samples:
            skipped += 1
            continue

        production_with = _summarize([sample.log for sample in samples.with_samples])
        production_without = _summarize([sample.log for sample in samples.without_samples])
        deltas = _deltas(production_with, production_without)
        provenance: dict[str, object] = {
            "contract": "descriptive_observational_evidence",
            "membership_method": BOUNDED_MEMBERSHIP_METHOD,
            "with_samples": [sample.provenance for sample in samples.with_samples],
            "without_samples": [sample.provenance for sample in samples.without_samples],
            "excluded_unknown_game_ids": sorted(samples.unknown_game_ids),
        }
        fingerprint = _fingerprint(
            schedule_refresh.version,
            evidence_version,
            production_with,
            production_without,
            provenance,
        )
        existing = session.scalar(
            select(AbsenceSplit).where(
                AbsenceSplit.beneficiary_player_id == beneficiary_id,
                AbsenceSplit.absent_player_id == absent_id,
                AbsenceSplit.team_id == team_id,
                AbsenceSplit.season == season,
                AbsenceSplit.season_type == season_type,
                AbsenceSplit.evidence_version == evidence_version,
                AbsenceSplit.input_fingerprint == fingerprint,
            )
        )
        if existing is not None:
            output_rows.append(existing)
            reused += 1
            continue

        split_row = AbsenceSplit(
            beneficiary_player_id=beneficiary_id,
            absent_player_id=absent_id,
            team_id=team_id,
            season=season,
            season_type=season_type,
            games_with=len(samples.with_samples),
            games_without=len(samples.without_samples),
            explicit_absence_games=samples.explicit_absence_games,
            inferred_absence_games=samples.inferred_absence_games,
            excluded_unknown_games=len(samples.unknown_game_ids),
            production_with=production_with,
            production_without=production_without,
            descriptive_deltas=deltas,
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
                    "aggregate makes/attempts with 95% Wilson interval; attempts within "
                    "games are correlated, so the interval is descriptive only"
                ),
                "causal_effect": False,
                "recommendation": False,
            },
            provenance=provenance,
            membership_method=BOUNDED_MEMBERSHIP_METHOD,
            evidence_version=evidence_version,
            input_fingerprint=fingerprint,
            schedule_version=schedule_refresh.version,
            schedule_refreshed_at=schedule_refresh.refreshed_at,
            computed_at=when,
        )
        session.add(split_row)
        output_rows.append(split_row)
        created += 1

    session.flush()
    return AbsenceSplitRun(
        rows=tuple(output_rows),
        created=created,
        reused=reused,
        skipped_one_sided_pairs=skipped,
    )


def latest_absence_splits(
    session: Session,
    *,
    season: str,
    season_type: SeasonType = SeasonType.REGULAR,
    evidence_version: str = ABSENCE_SPLIT_EVIDENCE_VERSION,
) -> tuple[AbsenceSplit, ...]:
    """Latest row per pair in the current schedule cohort.

    Historical fingerprints remain queryable for audit, but consumers should
    use this selector so a recomputation cannot silently double-count an older
    snapshot or combine evidence from a stale schedule version.
    """

    schedule_refresh = _schedule_refresh(session, season)
    if schedule_refresh is None:
        raise AbsenceSplitInputError(
            f"no registered schedule refresh for {season}; current splits are unknowable"
        )
    rows = session.scalars(
        select(AbsenceSplit)
        .where(
            AbsenceSplit.season == season,
            AbsenceSplit.season_type == season_type,
            AbsenceSplit.evidence_version == evidence_version,
            AbsenceSplit.schedule_version == schedule_refresh.version,
        )
        .order_by(AbsenceSplit.computed_at.desc(), AbsenceSplit.id.desc())
    ).all()
    latest: dict[tuple[int, int, int], AbsenceSplit] = {}
    for row in rows:
        key = (row.beneficiary_player_id, row.absent_player_id, row.team_id)
        latest.setdefault(key, row)
    return tuple(latest[key] for key in sorted(latest))


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


def _observation(
    observations: dict[tuple[int, int], _MembershipObservation],
    player_id: int,
    entry: TeamScheduleEntry,
) -> _MembershipObservation:
    key = (player_id, entry.game_id)
    existing = observations.get(key)
    if existing is not None:
        if existing.team_id != entry.team_id:
            raise AbsenceSplitInputError(
                f"player {player_id} is assigned to two teams in game {entry.game_id}"
            )
        return existing
    observation = _MembershipObservation(
        player_id=player_id,
        game_id=entry.game_id,
        team_id=entry.team_id,
        game_date=entry.game_date,
    )
    observations[key] = observation
    return observation


def _membership_segments(
    observations: list[_MembershipObservation],
) -> tuple[_MembershipSegment, ...]:
    ordered = sorted(observations, key=lambda row: (row.game_date, row.game_id))
    segments: list[_MembershipSegment] = []
    start = ordered[0]
    previous = ordered[0]
    for current in ordered[1:]:
        if current.team_id != previous.team_id:
            segments.append(_MembershipSegment(team_id=previous.team_id, start=start, end=previous))
            start = current
        previous = current
    segments.append(_MembershipSegment(team_id=previous.team_id, start=start, end=previous))
    return tuple(segments)


def _condition(
    target_log: PlayerGameLog | None,
    target_participation: PlayerParticipation | None,
) -> Literal["with", "without_explicit", "without_inferred", "unknown"]:
    if target_log is not None:
        return "with"
    if target_participation is None:
        return "without_inferred"
    if target_participation.outcome == ParticipationOutcome.PLAYED:
        return "with"
    if target_participation.outcome == ParticipationOutcome.UNKNOWN:
        return "unknown"
    return "without_explicit"


def _sample_provenance(
    *,
    entry: TeamScheduleEntry,
    beneficiary_log: PlayerGameLog,
    target_log: PlayerGameLog | None,
    target_participation: PlayerParticipation | None,
    segment: _MembershipSegment,
    condition: str,
) -> dict[str, object]:
    target_evidence: dict[str, object]
    if target_log is not None:
        target_evidence = {
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
    else:
        target_evidence = {
            "kind": "missing_within_bounded_membership",
            "participation_id": None,
            "player_game_log_id": None,
        }
    return {
        "game_id": entry.game_id,
        "team_schedule_id": entry.id,
        "game_date": entry.game_date.isoformat(),
        "beneficiary_game_log_id": beneficiary_log.id,
        "condition": condition,
        "target_evidence": target_evidence,
        "membership_bounds": {
            "start": segment.start.reference(),
            "end": segment.end.reference(),
        },
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
    if attempted == 0:
        rate = None
        interval: list[float] | None = None
        standard_error = None
    else:
        rate = made / attempted
        interval = list(_wilson_interval(made, attempted))
        standard_error = math.sqrt(rate * (1.0 - rate) / attempted)
    return {
        "observed_games": len(samples),
        "made": made,
        "attempted": attempted,
        "aggregate_rate": rate,
        "wilson_95_interval": interval,
        "shot_level_standard_error": standard_error,
    }


def _wilson_interval(made: int, attempted: int) -> tuple[float, float]:
    z = 1.959963984540054
    proportion = made / attempted
    denominator = 1.0 + z**2 / attempted
    center = (proportion + z**2 / (2.0 * attempted)) / denominator
    spread = (
        z
        * math.sqrt(proportion * (1.0 - proportion) / attempted + z**2 / (4.0 * attempted**2))
        / denominator
    )
    return max(0.0, center - spread), min(1.0, center + spread)


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
        with_summary = _object_dict(with_shooting[label])
        without_summary = _object_dict(without_shooting[label])
        with_rate = _optional_float(with_summary["aggregate_rate"])
        without_rate = _optional_float(without_summary["aggregate_rate"])
        shooting[label] = {
            "without_minus_with_aggregate_rate": (
                None if with_rate is None or without_rate is None else without_rate - with_rate
            ),
            "delta_uncertainty": (
                "not estimated: attempts within games are correlated and a "
                "shot-level independent-sample interval would overstate precision"
            ),
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
