"""Synthetic tests for the frozen injury-status conversion fit path.

No test in this module opens a cohort store or reads a real participation
outcome. The fictional rates are chosen to make selection decisions obvious.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from hoops_gm.availability.injury_status_conversion import (
    CANDIDATE_ORDER,
    FIVE_STATUS,
    GLOBAL,
    MODEL_VERSION,
    SELECTION_BRIER_IMPROVEMENT,
    THREE_BAND,
    ConversionRow,
    ExcludedRow,
    LoadedCohort,
    candidate_is_eligible,
    evaluate_frozen_protocol,
    fit_candidate,
    select_candidate,
)
from hoops_gm.ingest.injury_report.cohort_admissibility import (
    COHORT_STATUSES,
    ERA_LEGACY,
    ERA_SHORT_LEAD,
)


def _rows(
    *,
    start: date,
    dates: int,
    plays_by_status: dict[str, int],
    rows_per_status: int = 40,
    era: str = ERA_SHORT_LEAD,
) -> list[ConversionRow]:
    rows: list[ConversionRow] = []
    for status in COHORT_STATUSES:
        plays = plays_by_status[status]
        for index in range(rows_per_status):
            game_date = start + timedelta(days=index % dates)
            rows.append(
                ConversionRow(
                    observation_id=f"{start}:{status}:{index}",
                    game_date=game_date,
                    status=status,
                    lead_time_minutes=45 + index % 600,
                    report_era=era,
                    reason_head="Injury/Illness",
                    played=index < plays,
                )
            )
    return rows


def test_five_status_requires_twenty_development_rows_for_every_status() -> None:
    development = _rows(
        start=date(2025, 10, 1),
        dates=10,
        rows_per_status=20,
        plays_by_status=dict.fromkeys(COHORT_STATUSES, 10),
    )
    assert candidate_is_eligible(FIVE_STATUS, development)
    thinned = [row for row in development if not (row.status == "doubtful" and row.played)]
    assert sum(row.status == "doubtful" for row in thinned) == 10
    assert not candidate_is_eligible(FIVE_STATUS, thinned)


def test_selection_advances_in_fixed_complexity_order_on_the_frozen_threshold() -> None:
    development = _rows(
        start=date(2025, 10, 1),
        dates=10,
        plays_by_status={
            "out": 0,
            "doubtful": 0,
            "questionable": 20,
            "probable": 40,
            "available": 40,
        },
    )
    selection = _rows(
        start=date(2025, 11, 1),
        dates=10,
        plays_by_status={
            "out": 0,
            "doubtful": 0,
            "questionable": 20,
            "probable": 40,
            "available": 40,
        },
    )
    selected, trace = select_candidate(development, selection)
    assert list(trace) == list(CANDIDATE_ORDER)
    assert selected == THREE_BAND
    assert trace[THREE_BAND]["advanced"] is True
    assert trace[FIVE_STATUS]["advanced"] is False
    assert trace[FIVE_STATUS]["improvement_over_incumbent"] < SELECTION_BRIER_IMPROVEMENT


def test_advancement_threshold_is_inclusive_and_ties_keep_the_incumbent() -> None:
    assert SELECTION_BRIER_IMPROVEMENT == 0.005
    development = _rows(
        start=date(2025, 10, 1),
        dates=10,
        plays_by_status=dict.fromkeys(COHORT_STATUSES, 20),
    )
    selection = _rows(
        start=date(2025, 11, 1),
        dates=10,
        plays_by_status=dict.fromkeys(COHORT_STATUSES, 20),
    )
    selected, trace = select_candidate(development, selection)
    assert selected == GLOBAL
    assert trace[THREE_BAND]["improvement_over_incumbent"] == pytest.approx(0.0)
    assert trace[THREE_BAND]["advanced"] is False
    assert trace[FIVE_STATUS]["advanced"] is False


def test_jeffreys_estimate_is_applied_per_declared_group() -> None:
    rows = _rows(
        start=date(2025, 10, 1),
        dates=10,
        rows_per_status=20,
        plays_by_status={
            "out": 0,
            "doubtful": 5,
            "questionable": 10,
            "probable": 15,
            "available": 20,
        },
    )
    model = fit_candidate(FIVE_STATUS, rows)
    assert model.predict("out") == pytest.approx(0.5 / 21)
    assert model.predict("doubtful") == pytest.approx(5.5 / 21)
    assert model.predict("available") == pytest.approx(20.5 / 21)


def _synthetic_evaluation_cohort() -> tuple[LoadedCohort, dict[str, object]]:
    start = date(2025, 1, 1)
    dates = tuple(start + timedelta(days=index) for index in range(40))
    rows: list[ConversionRow] = []
    rates = {
        "out": 0.05,
        "doubtful": 0.20,
        "questionable": 0.50,
        "probable": 0.80,
        "available": 0.95,
    }
    for day_index, day in enumerate(dates):
        era = ERA_LEGACY if day_index < 10 else ERA_SHORT_LEAD
        for status in COHORT_STATUSES:
            for player in range(4):
                threshold = int(rates[status] * 20)
                rows.append(
                    ConversionRow(
                        observation_id=f"{day}:{status}:{player}",
                        game_date=day,
                        status=status,
                        lead_time_minutes=(45, 120, 360, 600)[player],
                        report_era=era,
                        reason_head="Injury/Illness",
                        played=(day_index * 4 + player) % 20 < threshold,
                    )
                )
    canonical_counts = {
        status: sum(row.status == status for row in rows) for status in COHORT_STATUSES
    }
    exclusions: dict[str, dict[str, int]] = {
        "resolved_observations_without_nba_anchor": {},
        "resolved_observations_without_participation_row": {},
        "unresolved_player_identity": {},
        "with_non_direct_participation_outcome": {},
    }
    cohort = LoadedCohort(
        rows=tuple(rows),
        excluded=(),
        cohort_dates=dates,
        canonical_counts=canonical_counts,
        direct_counts=canonical_counts,
        exclusion_counts=exclusions,
        canonical_fingerprint="canonical",
        direct_membership_fingerprint="direct",
    )
    held_out_counts = dict.fromkeys(COHORT_STATUSES, 40)
    admissibility: dict[str, Any] = {
        "fingerprints": {
            "sha256_sorted_canonical_identity_records": "canonical",
            "sha256_sorted_direct_outcome_membership": "direct",
        },
        "exclusion_classes_by_status": exclusions,
        "section_2_admissibility": {
            "canonical_observations_by_status": canonical_counts,
            "direct_outcomes_by_status": canonical_counts,
            "held_out_direct_outcomes_by_status": held_out_counts,
            "held_out_start": dates[30].isoformat(),
            "held_out_end": dates[-1].isoformat(),
            "split_game_dates": {
                "development": 20,
                "selection": 10,
                "held_out": 10,
            },
        },
    }
    return cohort, admissibility


def test_evidence_has_exactly_eight_conditions_and_change_b_never_gates() -> None:
    cohort, admissibility = _synthetic_evaluation_cohort()
    evidence = evaluate_frozen_protocol(
        cohort,
        admissibility=admissibility,
        input_identity={"synthetic": True},
    )
    activation = evidence["activation"]
    assert activation["conditions_present"] == 8
    assert [condition["number"] for condition in activation["conditions"]] == list(range(1, 9))
    assert activation["condition_9_exists"] is False
    informative = evidence["display_only_subgroups"]["informative_statuses"]
    assert informative["gating"] is False
    assert informative["condition_9_exists"] is False


def test_change_a_refits_both_development_eras_against_the_same_holdout() -> None:
    cohort, admissibility = _synthetic_evaluation_cohort()
    evidence = evaluate_frozen_protocol(
        cohort,
        admissibility=admissibility,
        input_identity={"synthetic": True},
    )
    sensitivity = evidence["sensitivities"]["v3_change_a_report_era"]
    assert sensitivity["pooled_result_remains_primary"] is True
    assert sensitivity["enters_v2_section_8"] is False
    assert "training-era sensitivity" in sensitivity["interpretation"]
    refits = sensitivity["refits"]
    assert set(refits) == {ERA_LEGACY, ERA_SHORT_LEAD}
    for refit in refits.values():
        assert refit["training_partition"] == "development only"
        assert refit["same_held_out_date_partition"] is True
        assert refit["held_out_observations_total"] == 200
        assert refit["gating"] is False


def test_evidence_versions_the_model_machinery_and_inputs() -> None:
    cohort, admissibility = _synthetic_evaluation_cohort()
    evidence = evaluate_frozen_protocol(
        cohort,
        admissibility=admissibility,
        input_identity={"fixture": "synthetic-v1"},
    )
    assert evidence["model_version"] == MODEL_VERSION
    assert evidence["calibration_machinery_version"] == "calibration-machinery-v1"
    assert evidence["inputs"] == {"fixture": "synthetic-v1"}
    assert evidence["blind_break"]["held_out_evaluations"] == 1
    assert evidence["blind_break"]["tuning_after_held_out_access"] is False


def test_excluded_rows_are_not_needed_to_make_the_primary_fit_run() -> None:
    cohort, admissibility = _synthetic_evaluation_cohort()
    one_exclusion = ExcludedRow(
        game_date=cohort.cohort_dates[-1],
        status="out",
        exclusion_class="resolved_observations_without_participation_row",
    )
    changed_exclusions = {
        **cohort.exclusion_counts,
        "resolved_observations_without_participation_row": {"out": 1},
    }
    changed = LoadedCohort(
        rows=cohort.rows,
        excluded=(one_exclusion,),
        cohort_dates=cohort.cohort_dates,
        canonical_counts=cohort.canonical_counts,
        direct_counts=cohort.direct_counts,
        exclusion_counts=changed_exclusions,
        canonical_fingerprint=cohort.canonical_fingerprint,
        direct_membership_fingerprint=cohort.direct_membership_fingerprint,
    )
    admissibility["exclusion_classes_by_status"] = changed_exclusions
    evidence = evaluate_frozen_protocol(
        changed,
        admissibility=admissibility,
        input_identity={"synthetic": True},
    )
    sensitivity = evidence["sensitivities"]["v2_exclusion_bounds"]["missing_participation_row"][
        "by_status"
    ]["out"]
    assert sensitivity["uncertain_observations"] == 1
    assert evidence["cohort_reproduction"]["all_match"] is True
