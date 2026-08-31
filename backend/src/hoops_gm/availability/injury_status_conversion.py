"""Run the frozen injury-status conversion fit exactly once.

The estimator, split, candidate order, advancement threshold, calibration
conventions, activation conditions, and v3 Change A sensitivity are repository
constants. The command reads one pre-authorized merged store in read-only mode;
it never opens the deliberately disjoint component stores and never writes a
runtime activation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.availability.calibration import (
    CALIBRATION_MACHINERY_VERSION,
    DEFAULT_BOOTSTRAP_RESAMPLES,
    DEFAULT_BOOTSTRAP_SEED,
    BinningScheme,
    CalibrationObservation,
    PairedPrediction,
    Provenance,
    bands_from_labels,
    build_calibration_report,
    detect_monotonic_reversals,
    paired_bootstrap_brier,
    wilson_interval,
)
from hoops_gm.db.models import NbaGame, PlayerExternalId, PlayerParticipation
from hoops_gm.db.models.enums import ExternalSource, ParticipationOutcome, SeasonType
from hoops_gm.ingest.injury_report.backfill import (
    CanonicalPregameObservation,
    select_canonical_pregame_observations,
)
from hoops_gm.ingest.injury_report.cohort_admissibility import (
    ADMISSIBILITY_FLOOR,
    COHORT_STATUSES,
    DIRECT_OUTCOMES,
    ERA_LEGACY,
    ERA_SHORT_LEAD,
    chronological_split,
    lead_time_band,
    read_only_engine,
    report_era,
)
from hoops_gm.ingest.injury_report.cohort_evidence import content_sha256

MODEL_VERSION: Final = "injury-status-conversion-v2-scoped-a-v1"
EVIDENCE_SCHEMA_VERSION: Final = 1
FREEZE_ID: Final = "injury-status-conversion-v2-20260821T145900Z"
GOVERNING_PROTOCOL: Final = "v3 with scoped acceptance: frozen v2 plus Change A"
SELECTION_BRIER_IMPROVEMENT: Final = 0.005
MINIMUM_DEVELOPMENT_STATUS_OBSERVATIONS: Final = 20

GLOBAL: Final = "global_jeffreys"
THREE_BAND: Final = "three_band_jeffreys"
FIVE_STATUS: Final = "five_status_jeffreys"
CANDIDATE_ORDER: Final = (GLOBAL, THREE_BAND, FIVE_STATUS)

UNLIKELY: Final = "unlikely"
UNCERTAIN: Final = "uncertain"
LIKELY: Final = "likely"
BAND_ORDER: Final = (UNLIKELY, UNCERTAIN, LIKELY)
THREE_BAND_BY_STATUS: Final[Mapping[str, str]] = {
    "out": UNLIKELY,
    "doubtful": UNLIKELY,
    "questionable": UNCERTAIN,
    "probable": LIKELY,
    "available": LIKELY,
}
INFORMATIVE_STATUSES: Final = frozenset({"doubtful", "questionable", "probable"})

# Display-only proxy, frozen before outcome access. Stated reasons are not a
# feature and are not trusted as medical facts.
HEALTH_REASON_HEADS: Final = frozenset(
    {"Injury/Illness", "Concussion Protocol", "Return to Competition Reconditioning"}
)

EXCLUSION_UNRESOLVED: Final = "unresolved_player_identity"
EXCLUSION_NO_ANCHOR: Final = "resolved_observations_without_nba_anchor"
EXCLUSION_NO_ROW: Final = "resolved_observations_without_participation_row"
EXCLUSION_NON_DIRECT: Final = "with_non_direct_participation_outcome"
EXCLUSION_CLASSES: Final = (
    EXCLUSION_NO_ANCHOR,
    EXCLUSION_NO_ROW,
    EXCLUSION_UNRESOLVED,
    EXCLUSION_NON_DIRECT,
)


@dataclass(frozen=True)
class ConversionRow:
    observation_id: str
    game_date: date
    status: str
    lead_time_minutes: int
    report_era: str
    reason_head: str
    played: bool


@dataclass(frozen=True)
class ExcludedRow:
    game_date: date
    status: str
    exclusion_class: str


@dataclass(frozen=True)
class LoadedCohort:
    rows: tuple[ConversionRow, ...]
    excluded: tuple[ExcludedRow, ...]
    cohort_dates: tuple[date, ...]
    canonical_counts: Mapping[str, int]
    direct_counts: Mapping[str, int]
    exclusion_counts: Mapping[str, Mapping[str, int]]
    canonical_fingerprint: str
    direct_membership_fingerprint: str


@dataclass(frozen=True)
class FittedModel:
    candidate: str
    group_probabilities: Mapping[str, float]
    group_observations: Mapping[str, int]
    group_plays: Mapping[str, int]

    def predict(self, status: str) -> float:
        return self.group_probabilities[_group_for_status(self.candidate, status)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "estimator": "(plays + 0.5) / (observations + 1)",
            "groups": {
                group: {
                    "observations": self.group_observations[group],
                    "plays": self.group_plays[group],
                    "probability": probability,
                }
                for group, probability in sorted(self.group_probabilities.items())
            },
            "status_probabilities": {status: self.predict(status) for status in COHORT_STATUSES},
        }


def _group_for_status(candidate: str, status: str) -> str:
    if status not in COHORT_STATUSES:
        raise ValueError(f"unknown injury-report status {status!r}")
    if candidate == GLOBAL:
        return "all_statuses"
    if candidate == THREE_BAND:
        return THREE_BAND_BY_STATUS[status]
    if candidate == FIVE_STATUS:
        return status
    raise ValueError(f"unknown candidate {candidate!r}")


def _groups(candidate: str) -> tuple[str, ...]:
    if candidate == GLOBAL:
        return ("all_statuses",)
    if candidate == THREE_BAND:
        return BAND_ORDER
    if candidate == FIVE_STATUS:
        return COHORT_STATUSES
    raise ValueError(f"unknown candidate {candidate!r}")


def _status_counts(rows: Sequence[ConversionRow]) -> dict[str, int]:
    counts = Counter(row.status for row in rows)
    return {status: counts[status] for status in COHORT_STATUSES}


def candidate_is_eligible(candidate: str, development: Sequence[ConversionRow]) -> bool:
    if candidate != FIVE_STATUS:
        return True
    counts = _status_counts(development)
    return all(
        counts[status] >= MINIMUM_DEVELOPMENT_STATUS_OBSERVATIONS for status in COHORT_STATUSES
    )


def fit_candidate(candidate: str, rows: Sequence[ConversionRow]) -> FittedModel:
    observations: Counter[str] = Counter()
    plays: Counter[str] = Counter()
    for row in rows:
        group = _group_for_status(candidate, row.status)
        observations[group] += 1
        plays[group] += int(row.played)
    probabilities = {
        group: (plays[group] + 0.5) / (observations[group] + 1) for group in _groups(candidate)
    }
    return FittedModel(
        candidate=candidate,
        group_probabilities=probabilities,
        group_observations={group: observations[group] for group in _groups(candidate)},
        group_plays={group: plays[group] for group in _groups(candidate)},
    )


def brier_score(model: FittedModel, rows: Sequence[ConversionRow]) -> float:
    if not rows:
        raise ValueError("Brier score requires at least one row")
    return sum((model.predict(row.status) - float(row.played)) ** 2 for row in rows) / len(rows)


def select_candidate(
    development: Sequence[ConversionRow],
    selection: Sequence[ConversionRow],
) -> tuple[str, dict[str, Any]]:
    incumbent = GLOBAL
    results: dict[str, Any] = {}
    for candidate in CANDIDATE_ORDER:
        eligible = candidate_is_eligible(candidate, development)
        if not eligible:
            results[candidate] = {
                "eligible": False,
                "development_counts_by_status": _status_counts(development),
                "selection_brier": None,
                "improvement_over_incumbent": None,
                "advanced": False,
            }
            continue
        fitted = fit_candidate(candidate, development)
        score = brier_score(fitted, selection)
        if candidate == GLOBAL:
            improvement = None
            advanced = True
        else:
            incumbent_result = results[incumbent]
            if not isinstance(incumbent_result, dict):
                raise AssertionError("candidate result must be a mapping")
            incumbent_score = incumbent_result["selection_brier"]
            if not isinstance(incumbent_score, float):
                raise AssertionError("eligible incumbent must have a Brier score")
            improvement = incumbent_score - score
            advanced = improvement >= SELECTION_BRIER_IMPROVEMENT
        results[candidate] = {
            "eligible": True,
            "development_counts_by_status": _status_counts(development),
            "fit": fitted.to_dict(),
            "selection_brier": score,
            "improvement_over_incumbent": improvement,
            "advanced": advanced,
        }
        if advanced:
            incumbent = candidate
    return incumbent, results


def _reason_head(reason_raw: str) -> str:
    return reason_raw.split(" - ", 1)[0].strip() or "(blank)"


def _canonical_identity_record(
    observation: CanonicalPregameObservation,
    *,
    nba_game_id: str,
    anchor: str | None,
) -> str:
    identity = f"nba:{anchor}" if anchor is not None else f"raw:{observation.player_name_raw}"
    return "|".join(
        (
            nba_game_id,
            identity,
            observation.team_raw,
            observation.report_timestamp.isoformat(),
            observation.status.value,
            str(observation.lead_time_minutes),
        )
    )


def load_cohort(
    session: Session,
    *,
    season: str,
    season_type: SeasonType,
    start: date,
    end: date,
) -> LoadedCohort:
    games = list(
        session.scalars(
            select(NbaGame).where(
                NbaGame.season == season,
                NbaGame.season_type == season_type,
                NbaGame.game_date >= start,
                NbaGame.game_date <= end,
            )
        )
    )
    game_by_pk = {game.id: game for game in games}
    game_tipoffs = {game.id: game.tipoff_utc for game in games if game.tipoff_utc is not None}
    anchors = {
        row.player_id: row.external_id
        for row in session.scalars(
            select(PlayerExternalId).where(PlayerExternalId.source == ExternalSource.NBA)
        )
    }
    participation = {
        (row.game_id, row.player_id): row.outcome
        for row in session.scalars(select(PlayerParticipation))
    }
    observations = select_canonical_pregame_observations(
        session,
        game_ids=list(game_tipoffs),
        game_tipoffs=game_tipoffs,
    )

    rows: list[ConversionRow] = []
    excluded: list[ExcludedRow] = []
    canonical_records: list[str] = []
    membership_records: list[str] = []
    canonical_counts: Counter[str] = Counter()
    direct_counts: Counter[str] = Counter()
    exclusion_counts: defaultdict[str, Counter[str]] = defaultdict(Counter)
    cohort_dates: set[date] = set()

    for observation in observations:
        game = game_by_pk[observation.game_id]
        status = observation.status.value
        anchor = anchors.get(observation.player_id) if observation.player_id is not None else None
        canonical_counts[status] += 1
        cohort_dates.add(game.game_date)
        canonical_records.append(
            _canonical_identity_record(
                observation,
                nba_game_id=game.nba_game_id,
                anchor=anchor,
            )
        )

        exclusion: str | None = None
        outcome: ParticipationOutcome | None = None
        if observation.player_id is None:
            exclusion = EXCLUSION_UNRESOLVED
        elif anchor is None:
            exclusion = EXCLUSION_NO_ANCHOR
        else:
            outcome = participation.get((observation.game_id, observation.player_id))
            if outcome is None:
                exclusion = EXCLUSION_NO_ROW
            elif outcome.value not in DIRECT_OUTCOMES:
                exclusion = EXCLUSION_NON_DIRECT
        if exclusion is not None:
            excluded.append(
                ExcludedRow(
                    game_date=game.game_date,
                    status=status,
                    exclusion_class=exclusion,
                )
            )
            exclusion_counts[exclusion][status] += 1
            continue
        if anchor is None or outcome is None:
            raise AssertionError("eligible direct row must have an anchor and outcome")

        observation_id = f"{game.nba_game_id}|nba:{anchor}"
        membership_records.append(f"{observation_id}|{status}")
        direct_counts[status] += 1
        rows.append(
            ConversionRow(
                observation_id=observation_id,
                game_date=game.game_date,
                status=status,
                lead_time_minutes=observation.lead_time_minutes,
                report_era=report_era(observation.report_timestamp),
                reason_head=_reason_head(observation.reason_raw),
                played=outcome is ParticipationOutcome.PLAYED,
            )
        )

    return LoadedCohort(
        rows=tuple(sorted(rows, key=lambda row: (row.game_date, row.observation_id))),
        excluded=tuple(
            sorted(
                excluded,
                key=lambda row: (row.game_date, row.status, row.exclusion_class),
            )
        ),
        cohort_dates=tuple(sorted(cohort_dates)),
        canonical_counts={status: canonical_counts[status] for status in COHORT_STATUSES},
        direct_counts={status: direct_counts[status] for status in COHORT_STATUSES},
        exclusion_counts={
            exclusion: {
                status: exclusion_counts[exclusion][status]
                for status in COHORT_STATUSES
                if exclusion_counts[exclusion][status]
            }
            for exclusion in EXCLUSION_CLASSES
        },
        canonical_fingerprint=content_sha256(sorted(canonical_records)),
        direct_membership_fingerprint=content_sha256(sorted(membership_records)),
    )


def _calibration_rows(
    rows: Sequence[ConversionRow],
    model: FittedModel,
) -> list[CalibrationObservation]:
    return [
        CalibrationObservation(
            observation_id=row.observation_id,
            predicted=model.predict(row.status),
            played=row.played,
            labels={
                "status": row.status,
                "band": THREE_BAND_BY_STATUS[row.status],
                "lead_time_band": lead_time_band(row.lead_time_minutes),
                "report_era": row.report_era,
                "informative": "yes" if row.status in INFORMATIVE_STATUSES else "no",
                "health_reason_proxy": ("yes" if row.reason_head in HEALTH_REASON_HEADS else "no"),
            },
        )
        for row in rows
    ]


def _status_table(
    rows: Sequence[ConversionRow],
    model: FittedModel,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for status in COHORT_STATUSES:
        members = [row for row in rows if row.status == status]
        count = len(members)
        plays = sum(row.played for row in members)
        low, high = wilson_interval(plays, count)
        result[status] = {
            "predicted_probability": model.predict(status),
            "observations": count,
            "plays": plays,
            "observed_rate": plays / count,
            "wilson_low": low,
            "wilson_high": high,
            "display_only_non_gating": True,
        }
    return result


def _lead_time_sensitivity(
    calibration_rows: Sequence[CalibrationObservation],
) -> dict[str, object]:
    reports: dict[str, object] = {}
    for label in ("<=60", "61-180", "181-540", ">540"):
        count = sum(row.labels.get("lead_time_band") == label for row in calibration_rows)
        reports[label] = {
            "observations": count,
            "minimum_to_report_metrics": 10,
            "counts_only": count < 10,
            "calibration": (
                None
                if count < 10
                else build_calibration_report(
                    calibration_rows,
                    provenance=Provenance.PREREGISTERED_V2_SENSITIVITY,
                    binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
                    restriction={"lead_time_band": label},
                ).to_dict()
            ),
            "gating": False,
        }
    return reports


def _display_only_subgroups(
    calibration_rows: Sequence[CalibrationObservation],
) -> dict[str, object]:
    return {
        "informative_statuses": {
            "definition": sorted(INFORMATIVE_STATUSES),
            "calibration": build_calibration_report(
                calibration_rows,
                provenance=Provenance.DISPLAY_ONLY_ADR_018,
                binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
                restriction={"informative": "yes"},
            ).to_dict(),
            "gating": False,
            "standing": "display-only under ADR-018; Change B rejected as a gate",
            "condition_9_exists": False,
        },
        "health_reason_proxy": {
            "definition": sorted(HEALTH_REASON_HEADS),
            "calibration": build_calibration_report(
                calibration_rows,
                provenance=Provenance.POST_HOC_DIAGNOSTIC,
                binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
                restriction={"health_reason_proxy": "yes"},
            ).to_dict(),
            "gating": False,
            "standing": (
                "display-only post-hoc proxy required by the pre-unblind model-card "
                "skeleton; stated reason is not a feature or a trusted medical fact"
            ),
        },
    }


def _era_sensitivity(
    development: Sequence[ConversionRow],
    held_out: Sequence[ConversionRow],
    *,
    selected_candidate: str,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for era in (ERA_LEGACY, ERA_SHORT_LEAD):
        training = [row for row in development if row.report_era == era]
        training_counts = _status_counts(training)
        counts_only = [
            status
            for status in COHORT_STATUSES
            if training_counts[status] < MINIMUM_DEVELOPMENT_STATUS_OBSERVATIONS
        ]
        model = fit_candidate(selected_candidate, training)
        scored_holdout = [row for row in held_out if row.status not in counts_only]
        calibration = (
            None
            if not scored_holdout
            else build_calibration_report(
                _calibration_rows(scored_holdout, model),
                provenance=Provenance.PREREGISTERED_V3_SCOPED_CHANGE_A,
                binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
            ).to_dict()
        )
        result[era] = {
            "training_partition": "development only",
            "training_counts_by_status": training_counts,
            "statuses_reported_as_counts_only": counts_only,
            "fit": model.to_dict(),
            "same_held_out_date_partition": True,
            "held_out_observations_total": len(held_out),
            "held_out_observations_scored": len(scored_holdout),
            "calibration": calibration,
            "gating": False,
        }
    return {
        "standing": "v3 Change A, scoped acceptance 2026-08-29",
        "interpretation": (
            "training-era sensitivity, not held-out legacy calibration; the holdout "
            "is 100% short-lead"
        ),
        "pooled_result_remains_primary": True,
        "enters_v2_section_8": False,
        "refits": result,
    }


def _exclusion_sensitivity(
    held_out: Sequence[ConversionRow],
    excluded: Sequence[ExcludedRow],
) -> dict[str, object]:
    classes = {
        "unresolved_identity": {EXCLUSION_UNRESOLVED, EXCLUSION_NO_ANCHOR},
        "missing_participation_row": {EXCLUSION_NO_ROW},
        "explicit_unknown_outcome": {EXCLUSION_NON_DIRECT},
    }
    output: dict[str, object] = {}
    for label, included_classes in classes.items():
        by_status: dict[str, object] = {}
        for status in COHORT_STATUSES:
            direct = [row for row in held_out if row.status == status]
            uncertain = sum(
                row.status == status and row.exclusion_class in included_classes for row in excluded
            )
            plays = sum(row.played for row in direct)
            denominator = len(direct) + uncertain
            by_status[status] = {
                "direct_observations": len(direct),
                "direct_plays": plays,
                "uncertain_observations": uncertain,
                "play_rate_if_all_uncertain_do_not_play": plays / denominator,
                "play_rate_if_all_uncertain_play": (plays + uncertain) / denominator,
            }
        output[label] = {
            "by_status": by_status,
            "enters_fit_or_primary_evaluation": False,
        }
    return output


def _cohort_reproduction(
    cohort: LoadedCohort,
    admissibility: Mapping[str, Any],
) -> dict[str, object]:
    fingerprints = admissibility["fingerprints"]
    expected_exclusions = admissibility["exclusion_classes_by_status"]
    section = admissibility["section_2_admissibility"]
    checks = {
        "canonical_fingerprint": {
            "expected": fingerprints["sha256_sorted_canonical_identity_records"],
            "observed": cohort.canonical_fingerprint,
            "matches": (
                cohort.canonical_fingerprint
                == fingerprints["sha256_sorted_canonical_identity_records"]
            ),
        },
        "direct_membership_fingerprint": {
            "expected": fingerprints["sha256_sorted_direct_outcome_membership"],
            "observed": cohort.direct_membership_fingerprint,
            "matches": (
                cohort.direct_membership_fingerprint
                == fingerprints["sha256_sorted_direct_outcome_membership"]
            ),
        },
        "canonical_counts": {
            "expected": section["canonical_observations_by_status"],
            "observed": dict(cohort.canonical_counts),
            "matches": dict(cohort.canonical_counts) == section["canonical_observations_by_status"],
        },
        "direct_counts": {
            "expected": section["direct_outcomes_by_status"],
            "observed": dict(cohort.direct_counts),
            "matches": dict(cohort.direct_counts) == section["direct_outcomes_by_status"],
        },
        "exclusion_counts": {
            "expected": expected_exclusions,
            "observed": dict(cohort.exclusion_counts),
            "matches": dict(cohort.exclusion_counts) == expected_exclusions,
        },
    }
    return {
        "checks": checks,
        "all_match": all(bool(check["matches"]) for check in checks.values()),
    }


def evaluate_frozen_protocol(
    cohort: LoadedCohort,
    *,
    admissibility: Mapping[str, Any],
    input_identity: Mapping[str, object],
) -> dict[str, Any]:
    development_dates, selection_dates, held_out_dates = chronological_split(cohort.cohort_dates)
    development_set = set(development_dates)
    selection_set = set(selection_dates)
    held_out_set = set(held_out_dates)
    development = [row for row in cohort.rows if row.game_date in development_set]
    selection = [row for row in cohort.rows if row.game_date in selection_set]
    held_out = [row for row in cohort.rows if row.game_date in held_out_set]
    held_out_excluded = [row for row in cohort.excluded if row.game_date in held_out_set]

    expected_section = admissibility["section_2_admissibility"]
    expected_split = expected_section["split_game_dates"]
    observed_split = {
        "development": len(development_dates),
        "selection": len(selection_dates),
        "held_out": len(held_out_dates),
    }
    if observed_split != expected_split:
        raise RuntimeError(
            f"frozen split does not reproduce: expected {expected_split}, observed {observed_split}"
        )
    if (
        held_out_dates[0].isoformat() != expected_section["held_out_start"]
        or held_out_dates[-1].isoformat() != expected_section["held_out_end"]
    ):
        raise RuntimeError("frozen held-out date boundaries do not reproduce")

    selected, selection_trace = select_candidate(development, selection)
    final_training = [*development, *selection]
    final_model = fit_candidate(selected, final_training)
    global_baseline = fit_candidate(GLOBAL, final_training)
    calibration_rows = _calibration_rows(held_out, final_model)
    primary = build_calibration_report(
        calibration_rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    comparison = paired_bootstrap_brier(
        [
            PairedPrediction(
                observation_id=row.observation_id,
                candidate_predicted=final_model.predict(row.status),
                baseline_predicted=global_baseline.predict(row.status),
                played=row.played,
            )
            for row in held_out
        ],
        resamples=DEFAULT_BOOTSTRAP_RESAMPLES,
        seed=DEFAULT_BOOTSTRAP_SEED,
    )
    monotonic_bands = bands_from_labels(
        calibration_rows,
        label_key="band",
        order=BAND_ORDER,
    )
    reversals = detect_monotonic_reversals(monotonic_bands)
    status_counts = _status_counts(held_out)
    reproduction = _cohort_reproduction(cohort, admissibility)

    conditions: list[dict[str, Any]] = [
        {
            "number": 1,
            "name": "selected_model_is_status_conditioned",
            "passed": selected != GLOBAL,
        },
        {
            "number": 2,
            "name": "paired_brier_interval_upper_below_zero",
            "passed": comparison.interval_high < 0.0,
            "observed": comparison.interval_high,
        },
        {
            "number": 3,
            "name": "absolute_calibration_in_the_large_at_most_0_10",
            "passed": abs(primary.calibration_in_the_large) <= 0.10,
            "observed": abs(primary.calibration_in_the_large),
        },
        {
            "number": 4,
            "name": "every_emitted_bin_has_at_least_20",
            "passed": not primary.bins_below_population_floor,
            "failures": list(primary.bins_below_population_floor),
        },
        {
            "number": 5,
            "name": "every_emitted_probability_inside_wilson_95",
            "passed": not primary.bins_outside_wilson_interval,
            "failures": list(primary.bins_outside_wilson_interval),
        },
        {
            "number": 6,
            "name": "every_status_has_at_least_30_held_out_direct_outcomes",
            "passed": all(
                status_counts[status] >= ADMISSIBILITY_FLOOR for status in COHORT_STATUSES
            ),
            "observed": status_counts,
        },
        {
            "number": 7,
            "name": "no_monotonic_reversal_across_three_declared_bands",
            "passed": not reversals,
            "failures": [list(pair) for pair in reversals],
        },
        {
            "number": 8,
            "name": "cohort_fingerprint_and_exclusions_reproduce",
            "passed": bool(reproduction["all_match"]),
        },
    ]
    activated = all(bool(condition["passed"]) for condition in conditions)

    return {
        "kind": "injury-status-conversion-model-evidence",
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "calibration_machinery_version": CALIBRATION_MACHINERY_VERSION,
        "governing_protocol": {
            "freeze_id": FREEZE_ID,
            "standing": GOVERNING_PROTOCOL,
            "v3_change_a": "accepted and binding diagnostic",
            "v3_change_b": "rejected as an activation gate; display-only",
            "condition_9_exists": False,
        },
        "inputs": dict(input_identity),
        "split": {
            "denominator": "ordered distinct cohort game dates",
            "game_dates": observed_split,
            "development": [development_dates[0].isoformat(), development_dates[-1].isoformat()],
            "selection": [selection_dates[0].isoformat(), selection_dates[-1].isoformat()],
            "held_out": [held_out_dates[0].isoformat(), held_out_dates[-1].isoformat()],
            "direct_rows": {
                "development": len(development),
                "selection": len(selection),
                "held_out": len(held_out),
            },
        },
        "selection": {
            "primary_metric": "selection-partition Brier score",
            "candidate_order": list(CANDIDATE_ORDER),
            "minimum_improvement_to_advance": SELECTION_BRIER_IMPROVEMENT,
            "selected": selected,
            "candidates": selection_trace,
        },
        "final_fit": {
            "training_partitions": ["development", "selection"],
            "selected_model": final_model.to_dict(),
            "global_baseline": global_baseline.to_dict(),
        },
        "held_out_primary": {
            "standing": "primary Model-gate evidence",
            "calibration": primary.to_dict(),
            "paired_brier_against_global": comparison.to_dict(),
            "per_status": _status_table(held_out, final_model),
            "monotonic_bands": [
                {
                    "label": band.label,
                    "predicted_mean": band.predicted_mean,
                    "observed_rate": band.observed_rate,
                    "observations": band.observations,
                }
                for band in monotonic_bands
            ],
            "monotonic_reversals": [list(pair) for pair in reversals],
        },
        "sensitivities": {
            "v2_exclusion_bounds": _exclusion_sensitivity(held_out, held_out_excluded),
            "v2_lead_time_bands": _lead_time_sensitivity(calibration_rows),
            "v3_change_a_report_era": _era_sensitivity(
                development,
                held_out,
                selected_candidate=selected,
            ),
        },
        "display_only_subgroups": _display_only_subgroups(calibration_rows),
        "cohort_reproduction": reproduction,
        "activation": {
            "default": "veto",
            "conditions": conditions,
            "conditions_present": 8,
            "condition_9_exists": False,
            "eligible_for_runtime_activation": activated,
            "runtime_wiring_changed_by_this_unit": False,
        },
        "blind_break": {
            "held_out_evaluations": 1,
            "tuning_after_held_out_access": False,
            "deviations_from_frozen_estimator_split_or_thresholds": [],
        },
        "cannot_see": [
            "whether a team's public injury designation is medically truthful",
            "warm-up setbacks, illness, or coaching decisions after the last report",
            "trades, buyouts, waivers, G League recalls, and roster eligibility events",
            "coaching changes, minutes restrictions, shutdown policy, or front-office intent",
            "undisclosed injuries or absences missing from the report",
            "the 2026-27 season that this 2025-26 prior will be used for",
            "within-player or within-game correlation in the player-game bootstrap interval",
        ],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _text_sha256(path: Path) -> str:
    canonical = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(canonical).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError(f"{path.name} must contain one JSON object")
    return loaded


def verify_authorized_inputs(
    *,
    store: Path,
    merge_receipt_path: Path,
    cohort_manifest_path: Path,
    admissibility_path: Path,
    preregistration_v2_path: Path,
    preregistration_v3_path: Path,
    implementation_path: Path,
) -> tuple[dict[str, Any], dict[str, object]]:
    receipt = _load_json(merge_receipt_path)
    manifest = _load_json(cohort_manifest_path)
    admissibility = _load_json(admissibility_path)
    store_digest = _sha256(store)
    if receipt.get("kind") != "injury_report_store_merge_receipt":
        raise RuntimeError("adjacent receipt has the wrong kind")
    merged = receipt.get("merged_store")
    if not isinstance(merged, dict):
        raise RuntimeError("adjacent receipt has no merged_store object")
    if merged.get("store") != store.name or merged.get("sha256") != store_digest:
        raise RuntimeError("prepared store does not match its adjacent merge receipt")
    embedded = manifest.get("store_assembly")
    if not isinstance(embedded, dict) or embedded.get("receipt") != receipt:
        raise RuntimeError("adjacent merge receipt does not match the committed cohort manifest")
    section = admissibility.get("section_2_admissibility")
    if not isinstance(section, dict):
        raise RuntimeError("admissibility artifact has no section_2_admissibility object")
    if section.get("freeze_id") != FREEZE_ID:
        raise RuntimeError("admissibility artifact does not name the frozen v2 protocol")
    if section.get("admissible") is not True or section.get("statuses_below_floor") != []:
        raise RuntimeError("cohort is not pre-unblind admissible")
    v3_text = preregistration_v3_path.read_text(encoding="utf-8")
    required_v3_markers = (
        "**Status: Scoped acceptance.**",
        "**Accept Change A only; retain the prior Change B ruling.**",
        "There is no condition 9.",
    )
    if any(marker not in v3_text for marker in required_v3_markers):
        raise RuntimeError("committed v3 protocol does not carry the scoped owner acceptance")
    manifest_fingerprint = manifest.get("canonical_observations", {}).get(
        "sha256_sorted_stable_records"
    )
    admissibility_fingerprint = admissibility.get("fingerprints", {}).get(
        "sha256_sorted_canonical_identity_records"
    )
    if manifest_fingerprint != admissibility_fingerprint:
        raise RuntimeError("committed cohort and admissibility canonical fingerprints disagree")

    identity = {
        "prepared_merged_store": {
            "store": store.name,
            "bytes": store.stat().st_size,
            "sha256": store_digest,
        },
        "adjacent_merge_receipt": {
            "file": merge_receipt_path.name,
            "bytes": merge_receipt_path.stat().st_size,
            "sha256": _sha256(merge_receipt_path),
            "matches_committed_manifest_receipt": True,
        },
        "committed_inputs": {
            "cohort_manifest": {
                "file": "docs/adapters/" + cohort_manifest_path.name,
                "sha256_lf_normalized": _text_sha256(cohort_manifest_path),
            },
            "admissibility": {
                "file": "docs/adapters/" + admissibility_path.name,
                "sha256_lf_normalized": _text_sha256(admissibility_path),
            },
            "preregistration_v2": {
                "file": "docs/models/" + preregistration_v2_path.name,
                "sha256_lf_normalized": _text_sha256(preregistration_v2_path),
            },
            "preregistration_v3_scoped": {
                "file": "docs/models/" + preregistration_v3_path.name,
                "sha256_lf_normalized": _text_sha256(preregistration_v3_path),
            },
            "implementation": {
                "file": "backend/src/hoops_gm/availability/" + implementation_path.name,
                "sha256_lf_normalized": _text_sha256(implementation_path),
            },
        },
        "reproducible_command": (
            "python -m hoops_gm.availability.injury_status_conversion "
            '--store "$env:HOOPS_GM_DATA\\cohort-merged-2025-26.db" '
            "--merge-receipt "
            '"$env:HOOPS_GM_DATA\\cohort-merged-2025-26.db.merge-receipt.json"'
        ),
    }
    return admissibility, identity


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def main(argv: Sequence[str] | None = None) -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--merge-receipt", type=Path, required=True)
    parser.add_argument(
        "--cohort-manifest",
        type=Path,
        default=root / "docs" / "adapters" / "nba-injury-report-cohort-2025-10-21--2026-04-12.json",
    )
    parser.add_argument(
        "--admissibility",
        type=Path,
        default=root / "docs" / "adapters" / "nba-injury-report-cohort-admissibility-2025-26.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "backend" / "tests" / "model_evidence" / "injury_status_conversion_v1.json",
    )
    args = parser.parse_args(argv)
    implementation = Path(__file__).resolve()
    preregistration_v2 = root / "docs" / "models" / "injury-status-conversion-preregistration.md"
    preregistration_v3 = (
        root / "docs" / "models" / "injury-status-conversion-preregistration-v3-PROPOSED.md"
    )
    admissibility, identity = verify_authorized_inputs(
        store=args.store,
        merge_receipt_path=args.merge_receipt,
        cohort_manifest_path=args.cohort_manifest,
        admissibility_path=args.admissibility,
        preregistration_v2_path=preregistration_v2,
        preregistration_v3_path=preregistration_v3,
        implementation_path=implementation,
    )
    scope = admissibility["scope"]
    before = _sha256(args.store)
    engine = read_only_engine(args.store)
    try:
        with Session(engine) as session:
            cohort = load_cohort(
                session,
                season=str(scope["season"]),
                season_type=SeasonType(str(scope["season_type"])),
                start=date.fromisoformat(str(scope["start_game_date"])),
                end=date.fromisoformat(str(scope["end_game_date"])),
            )
            evidence = evaluate_frozen_protocol(
                cohort,
                admissibility=admissibility,
                input_identity=identity,
            )
    finally:
        engine.dispose()
    after = _sha256(args.store)
    if before != after:
        raise RuntimeError("prepared store bytes changed during read-only evaluation")
    rendered = json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
