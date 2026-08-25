"""Tests for the calibration machinery, entirely on synthetic cohorts.

**No test here reads a participation outcome, a cohort database, or a conversion
rate.** Every play rate below is an argument chosen to be obviously fictional;
the arithmetic these tests assert is about *denominators*, and the denominators
used — held-out counts by status — are predictor-side counts already published in
`docs/adapters/nba-injury-report-cohort-admissibility-2025-26.json`.

A calibration checker that has only ever been shown well-calibrated input is not
evidence. Each detector below is driven against a cohort built to break it.
"""

from __future__ import annotations

import copy
import itertools
import math
import pickle
import statistics
from collections.abc import Callable
from fractions import Fraction

import pytest

from hoops_gm.availability.calibration import (
    CALIBRATION_MACHINERY_VERSION,
    DECLARED_CONVENTIONS,
    DEFAULT_PROBABILITY_DECIMALS,
    WILSON_Z_95,
    Band,
    BinningScheme,
    BrierComparison,
    CalibrationBin,
    CalibrationObservation,
    PairedPrediction,
    Provenance,
    RestrictedCohort,
    bands_from_labels,
    build_calibration_report,
    detect_monotonic_reversals,
    paired_bootstrap_brier,
    restrict,
    wilson_interval,
)
from hoops_gm.availability.calibration_synthetic import (
    exact_plays,
    perfectly_calibrated_cohort,
    pooled_band_cohort,
    reversed_band_cohort,
    sharpened_cohort,
    status_cohort_with_informative_error,
    uniformly_biased_cohort,
)

# Held-out direct outcomes by status, from
# `section_2_admissibility.held_out_direct_outcomes_by_status`. Counts only —
# how often any of these players actually played is not in this file and is not
# knowable from it.
HELD_OUT_COUNTS = {
    "out": 2963,
    "available": 467,
    "questionable": 335,
    "probable": 92,
    "doubtful": 83,
}
INFORMATIVE = frozenset({"questionable", "probable", "doubtful"})
# Self-evidently invented. The whole point of the dilution identity is that it
# does not depend on these, which `test_the_dilution_identity_ignores_the_fictional_rates`
# drives directly.
FICTIONAL_RATES = {
    "out": 0.05,
    "available": 0.95,
    "questionable": 0.90,
    "probable": 0.90,
    "doubtful": 0.90,
}


def _delta_dilution(delta: float) -> float:
    """The share the pooled figure dilutes an informative-only error by."""

    informative = sum(HELD_OUT_COUNTS[status] for status in INFORMATIVE)
    return delta * informative / sum(HELD_OUT_COUNTS.values())


# --- Wilson interval, checked against its own definition ---------------------


def test_wilson_interval_matches_the_defining_inequality_solved_numerically() -> None:
    """The closed form is verified against the definition, not against itself.

    The Wilson interval is the set of `p` with `|p_hat - p| <= z*sqrt(p(1-p)/n)`.
    Bisecting that inequality's boundary is an independent derivation, so a
    transcription error in the closed form cannot pass by agreeing with a second
    copy of the same transcription.
    """

    for plays, observations in ((1, 10), (5, 20), (75, 83), (184, 335), (2963, 3940)):
        low, high = wilson_interval(plays, observations)
        p_hat = plays / observations

        def boundary(p: float, p_hat: float = p_hat, n: int = observations) -> float:
            return (p_hat - p) ** 2 - WILSON_Z_95**2 * p * (1.0 - p) / n

        assert boundary(low) == pytest.approx(0.0, abs=1e-12)
        assert boundary(high) == pytest.approx(0.0, abs=1e-12)
        assert _bisect(boundary, 0.0, p_hat) == pytest.approx(low, abs=1e-10)
        assert _bisect(boundary, p_hat, 1.0) == pytest.approx(high, abs=1e-10)


def _bisect(function: Callable[[float], float], low: float, high: float) -> float:
    for _step in range(200):
        middle = (low + high) / 2.0
        if function(low) * function(middle) <= 0:
            high = middle
        else:
            low = middle
    return (low + high) / 2.0


def test_wilson_interval_is_narrower_than_its_continuity_corrected_form() -> None:
    """The declared convention is the stricter arm, and that is checked, not asserted.

    A continuity-corrected interval is wider, and a wider interval makes v2 §8
    condition 5 easier to pass. `WILSON_CONTINUITY_CORRECTION = False` is
    therefore a choice against the author's interest, which is the only kind of
    convention worth declaring blind.
    """

    plays, observations = 184, 335
    low, high = wilson_interval(plays, observations)
    corrected_low, corrected_high = _continuity_corrected_wilson(plays, observations)
    assert corrected_low < low
    assert corrected_high > high


def _continuity_corrected_wilson(plays: int, observations: int) -> tuple[float, float]:
    n = float(observations)
    p_hat = plays / n
    z = WILSON_Z_95
    denominator = 2.0 * (n + z * z)
    root = z * math.sqrt(z * z - 1.0 / n + 4.0 * n * p_hat * (1.0 - p_hat) + (4.0 * p_hat - 2.0))
    low = (2.0 * n * p_hat + z * z - root - 1.0) / denominator
    root_high = z * math.sqrt(
        z * z - 1.0 / n + 4.0 * n * p_hat * (1.0 - p_hat) - (4.0 * p_hat - 2.0)
    )
    high = (2.0 * n * p_hat + z * z + root_high + 1.0) / denominator
    return max(0.0, low), min(1.0, high)


def test_wilson_interval_of_a_zero_play_bin_starts_at_zero() -> None:
    low, high = wilson_interval(0, 40)
    assert low == 0.0
    assert high == pytest.approx(WILSON_Z_95**2 / (40 + WILSON_Z_95**2))


def test_wilson_interval_refuses_an_empty_bin() -> None:
    with pytest.raises(ValueError, match="at least one observation"):
        wilson_interval(0, 0)


def test_wilson_interval_refuses_more_plays_than_observations() -> None:
    with pytest.raises(ValueError, match="outside"):
        wilson_interval(11, 10)


# --- The cohort no detector may fire on --------------------------------------


def test_a_perfectly_calibrated_cohort_fires_no_detector() -> None:
    """False positives are the failure mode that discredits the whole apparatus."""

    rows = perfectly_calibrated_cohort(
        {"low": 400, "mid": 400, "high": 400},
        {"low": 0.2, "mid": 0.5, "high": 0.8},
    )
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.calibration_in_the_large == pytest.approx(0.0, abs=1e-12)
    assert report.expected_calibration_error == pytest.approx(0.0, abs=1e-12)
    assert report.maximum_calibration_error == pytest.approx(0.0, abs=1e-12)
    assert report.bins_outside_wilson_interval == ()
    assert report.bins_below_population_floor == ()
    assert len(report.bins) == 3


# --- Overconfidence and underconfidence --------------------------------------


def test_an_overconfident_model_is_invisible_to_calibration_in_the_large() -> None:
    """The reason a pooled CITL is not sufficient, shown rather than argued.

    A symmetrically overconfident model over-predicts as much as it
    under-predicts, so its calibration-in-the-large is exactly zero while every
    bin it emits is rejected by its own data.
    """

    rows = sharpened_cohort(
        {"low": 400, "mid": 400, "high": 400},
        {"low": 0.2, "mid": 0.5, "high": 0.8},
        factor=1.5,
    )
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.calibration_in_the_large == pytest.approx(0.0, abs=1e-12)
    assert report.expected_calibration_error == pytest.approx(0.1, abs=1e-9)
    assert set(report.bins_outside_wilson_interval) == {"p=0.050000", "p=0.950000"}


def test_an_underconfident_model_is_detected_by_the_binned_table() -> None:
    rows = sharpened_cohort(
        {"low": 400, "mid": 400, "high": 400},
        {"low": 0.2, "mid": 0.5, "high": 0.8},
        factor=0.5,
    )
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.calibration_in_the_large == pytest.approx(0.0, abs=1e-12)
    assert report.expected_calibration_error == pytest.approx(0.1, abs=1e-9)
    assert set(report.bins_outside_wilson_interval) == {"p=0.350000", "p=0.650000"}


def test_a_uniform_bias_reproduces_itself_as_calibration_in_the_large() -> None:
    """Pins the sign convention: positive bias over-predicts play."""

    rows = uniformly_biased_cohort(
        {"low": 400, "high": 400},
        {"low": 0.3, "high": 0.6},
        bias=0.08,
    )
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.calibration_in_the_large == pytest.approx(0.08, abs=1e-12)
    assert report.predicted_mean > report.observed_rate


def test_a_negative_bias_under_predicts_play() -> None:
    rows = uniformly_biased_cohort(
        {"low": 400, "high": 400},
        {"low": 0.3, "high": 0.6},
        bias=-0.08,
    )
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.calibration_in_the_large == pytest.approx(-0.08, abs=1e-12)


def test_a_bias_that_would_leave_the_unit_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="outside"):
        uniformly_biased_cohort({"high": 100}, {"high": 0.95}, bias=0.2)


# --- The finding that motivated preregistration v3 ---------------------------


def test_the_published_holdout_is_one_eighth_informative() -> None:
    """51/394 of the held-out partition carries an informative status.

    Recomputed here from the published counts rather than copied from v3, so the
    share this suite reasons about cannot silently disagree with the artefact.
    """

    total = sum(HELD_OUT_COUNTS.values())
    informative = sum(HELD_OUT_COUNTS[status] for status in INFORMATIVE)
    assert total == 3940
    assert informative == 510
    assert informative / total == pytest.approx(51 / 394)
    assert informative / total == pytest.approx(0.1294416, abs=1e-7)


def test_pooled_calibration_dilutes_an_informative_error_by_that_share() -> None:
    """`pooled CITL = informative_share x delta`, exactly.

    This is the arithmetic behind v3 §4: a model exactly right on the 87% of
    near-deterministic rows and wrong by delta on every informative row moves the
    pooled figure by only delta times one eighth.
    """

    delta = -0.77
    rows = status_cohort_with_informative_error(
        counts_by_status=HELD_OUT_COUNTS,
        fictional_rate_by_status=FICTIONAL_RATES,
        informative_statuses=INFORMATIVE,
        informative_error=delta,
    )
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.calibration_in_the_large == pytest.approx(delta * 510 / 3940, abs=1e-12)
    assert report.calibration_in_the_large == pytest.approx(_delta_dilution(delta), abs=1e-12)


def test_v2_condition_three_survives_a_seventy_seven_point_error_and_fails_at_seventy_eight() -> (
    None
):
    """The threshold is `delta > 197/255 = 0.7725490...`, driven both sides.

    v2 §8 condition 3 caps |CITL| at 0.10. Against this holdout's composition
    that needs the model to be wrong by 77 percentage points on *every*
    informative row, which is what "close to unfailable" means.
    """

    threshold = 0.10 * 3940 / 510
    assert threshold == pytest.approx(197 / 255)
    assert threshold == pytest.approx(0.7725490196, abs=1e-9)

    for delta, expected_pass in ((-0.77, True), (-0.78, False), (-1.0, False)):
        rows = status_cohort_with_informative_error(
            counts_by_status=HELD_OUT_COUNTS,
            fictional_rate_by_status={**FICTIONAL_RATES, **dict.fromkeys(INFORMATIVE, 1.0)},
            informative_statuses=INFORMATIVE,
            informative_error=delta,
        )
        report = build_calibration_report(
            rows,
            provenance=Provenance.PREREGISTERED_V2,
            binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        )
        assert (abs(report.calibration_in_the_large) <= 0.10) is expected_pass


def test_restricting_to_the_informative_statuses_reports_the_undiluted_error() -> None:
    """v3 §4's condition 9, computed. Restricted CITL is delta itself."""

    delta = -0.77
    rows = status_cohort_with_informative_error(
        counts_by_status=HELD_OUT_COUNTS,
        fictional_rate_by_status=FICTIONAL_RATES,
        informative_statuses=INFORMATIVE,
        informative_error=delta,
    )
    restricted = build_calibration_report(
        rows,
        provenance=Provenance.PROPOSED_V3_NOT_BOUND,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        restriction={"informative": "yes"},
    )
    assert restricted.observations == 510
    assert restricted.calibration_in_the_large == pytest.approx(delta, abs=1e-12)
    assert abs(restricted.calibration_in_the_large) > 0.10


def test_the_dilution_identity_ignores_the_fictional_rates() -> None:
    """The claim is about denominators, so varying the invented rates changes nothing.

    This is what makes the whole exercise legal pre-unblind: no real conversion
    rate is needed to establish it, and none is used.
    """

    delta = -0.5
    results = []
    for informative_rate, out_rate, available_rate in (
        (0.55, 0.05, 0.95),
        (0.70, 0.40, 0.60),
        (0.99, 0.99, 0.01),
    ):
        rows = status_cohort_with_informative_error(
            counts_by_status=HELD_OUT_COUNTS,
            fictional_rate_by_status={
                "out": out_rate,
                "available": available_rate,
                **dict.fromkeys(INFORMATIVE, informative_rate),
            },
            informative_statuses=INFORMATIVE,
            informative_error=delta,
        )
        report = build_calibration_report(
            rows,
            provenance=Provenance.PREREGISTERED_V2,
            binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        )
        results.append(report.calibration_in_the_large)
    assert results == pytest.approx([delta * 510 / 3940] * 3, abs=1e-12)


# --- Masking: the case the pooled table cannot see at all --------------------


def _masked_band_cohort(*, offset: float = 0.0) -> list[CalibrationObservation]:
    return pooled_band_cohort(
        band_probability_offset=offset,
        counts_by_status=HELD_OUT_COUNTS,
        fictional_rate_by_status={
            "out": 0.02,
            "doubtful": 0.90,
            "questionable": 0.55,
            "probable": 0.85,
            "available": 0.95,
        },
        band_by_status={
            "out": "unlikely",
            "doubtful": "unlikely",
            "questionable": "uncertain",
            "probable": "likely",
            "available": "likely",
        },
    )


def test_a_band_model_emitting_each_realised_band_rate_clears_the_pooled_conditions() -> None:
    """A three-band model can pass v2 §8's pooled checks while one status is 86 points out.

    Every emitted probability is its own band's realised rate, so each bin gap is
    exactly zero: condition 3 passes at 0.0, condition 4 passes, condition 5
    passes, condition 7 finds no reversal. The `doubtful` rows inside the
    `unlikely` band are predicted at the band rate, which `out` dominates
    2,963 to 83.

    Read the scope in the name. This is the **zero-displacement** case, and its
    exact zeros are definitional - see
    `test_the_pooled_zeros_are_definitional_and_this_test_says_so`. A real fit
    takes its band rate from a different partition, and
    `test_a_band_probability_displaced_by_one_point_starts_failing_condition_five`
    shows condition 5 firing about 0.7pp away. An earlier name for this test said
    "clears every computable pooled condition", which read as a claim about band
    models generally rather than about this one.

    Synthetic. It shows the condition set is *satisfiable* by such a model, not
    that the real fit will be one.
    """

    rows = _masked_band_cohort()
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert abs(report.calibration_in_the_large) == pytest.approx(0.0, abs=1e-12)
    assert report.expected_calibration_error == pytest.approx(0.0, abs=1e-12)
    assert report.bins_below_population_floor == ()
    assert report.bins_outside_wilson_interval == ()
    bands = bands_from_labels(rows, label_key="band", order=("unlikely", "uncertain", "likely"))
    assert detect_monotonic_reversals(bands) == ()


def test_subgroup_restriction_exposes_the_status_the_pooled_table_masked() -> None:
    rows = _masked_band_cohort()
    restricted = build_calibration_report(
        rows,
        provenance=Provenance.POST_HOC_DIAGNOSTIC,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        restriction={"status": "doubtful"},
    )
    assert restricted.observations == 83
    assert restricted.observed_rate == pytest.approx(75 / 83)
    assert restricted.calibration_in_the_large < -0.8
    assert restricted.bins_outside_wilson_interval == tuple(
        row.label for row in restricted.bins
    )


# --- Provenance guard --------------------------------------------------------


def test_a_restricted_report_may_not_claim_v2_preregistration() -> None:
    """v2 §7 pre-registers a pooled table only, so a restricted one is not it.

    True whatever the owner decides about v3, which is why the guard keys on the
    presence of a restriction rather than on a mutable "is v3 bound yet" flag.
    """

    rows = perfectly_calibrated_cohort({"a": 100, "b": 100}, {"a": 0.3, "b": 0.7})
    with pytest.raises(ValueError, match="may not claim PREREGISTERED_V2"):
        build_calibration_report(
            rows,
            provenance=Provenance.PREREGISTERED_V2,
            binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
            restriction={"group": "a"},
        )


def test_a_restricted_report_may_be_labelled_proposed_or_post_hoc() -> None:
    rows = perfectly_calibrated_cohort({"a": 100, "b": 100}, {"a": 0.3, "b": 0.7})
    for provenance in (Provenance.PROPOSED_V3_NOT_BOUND, Provenance.POST_HOC_DIAGNOSTIC):
        report = build_calibration_report(
            rows,
            provenance=provenance,
            binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
            restriction={"group": "a"},
        )
        assert report.restriction == (("group", "a"),)
        assert report.observations == 100


def test_a_pooled_report_may_claim_v2_preregistration() -> None:
    rows = perfectly_calibrated_cohort({"a": 100, "b": 100}, {"a": 0.3, "b": 0.7})
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.restriction is None


# --- Restriction semantics ---------------------------------------------------


def test_restriction_requires_every_label_to_match() -> None:
    """`all`, not `any`: a restriction that widens under a second key is not one."""

    rows = [
        CalibrationObservation("a", 0.5, True, {"status": "doubtful", "era": "legacy"}),
        CalibrationObservation("b", 0.5, False, {"status": "doubtful", "era": "short_lead"}),
        CalibrationObservation("c", 0.5, True, {"status": "out", "era": "legacy"}),
    ]
    both = restrict(rows, status="doubtful", era="legacy")
    assert [row.observation_id for row in both] == ["a"]


def test_restriction_to_an_absent_subgroup_is_refused_rather_than_returning_nothing() -> None:
    rows = perfectly_calibrated_cohort({"a": 40}, {"a": 0.5})
    with pytest.raises(ValueError, match="at least one observation after restriction"):
        build_calibration_report(
            rows,
            provenance=Provenance.POST_HOC_DIAGNOSTIC,
            binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
            restriction={"group": "nonexistent"},
        )


# --- Population floor and Wilson containment ---------------------------------


def test_thin_bins_are_named_against_the_population_floor() -> None:
    """v2 §8 condition 4: a bin under 20 observations cannot support its own rate."""

    rows = perfectly_calibrated_cohort(
        {"thin": 8, "fat": 400},
        {"thin": 0.25, "fat": 0.75},
    )
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.EQUAL_WIDTH,
        equal_width_bins=10,
    )
    assert [row.observations for row in report.bins] == [8, 400]
    assert report.bins_below_population_floor == ("[0.200,0.300)",)


def test_a_bin_whose_emitted_probability_its_own_data_rejects_is_named() -> None:
    """v2 §8 condition 5, driven."""

    rows = uniformly_biased_cohort({"a": 500}, {"a": 0.5}, bias=0.2)
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.bins_outside_wilson_interval == ("p=0.700000",)


# --- Monotonic reversal ------------------------------------------------------


def test_a_monotonic_reversal_across_declared_bands_is_detected() -> None:
    """v2 §8 condition 7. v1's held-out `probable` and `available` reversed."""

    rows = reversed_band_cohort(
        {"unlikely": 200, "uncertain": 200, "likely": 200},
        {"unlikely": 0.20, "uncertain": 0.50, "likely": 0.80},
        {"unlikely": 0.20, "uncertain": 0.80, "likely": 0.50},
    )
    bands = bands_from_labels(
        rows, label_key="group", order=("unlikely", "uncertain", "likely")
    )
    assert detect_monotonic_reversals(bands) == (("uncertain", "likely"),)


def test_no_reversal_is_reported_when_predictions_and_outcomes_move_together() -> None:
    rows = perfectly_calibrated_cohort(
        {"unlikely": 200, "uncertain": 200, "likely": 200},
        {"unlikely": 0.2, "uncertain": 0.5, "likely": 0.8},
    )
    bands = bands_from_labels(
        rows, label_key="group", order=("unlikely", "uncertain", "likely")
    )
    assert detect_monotonic_reversals(bands) == ()


def test_bands_are_summarised_in_the_declared_order_not_alphabetically() -> None:
    """The prior ordering is supplied, because inferring it hides the reversal.

    The declared order below is deliberately not alphabetical: under it the three
    bands step consistently, while in alphabetical order the same three bands
    contain a reversal. If the order were inferred rather than declared, this
    cohort would report a reversal that its own prior ordering does not contain.
    """

    rows = reversed_band_cohort(
        {"beta": 200, "alpha": 200, "gamma": 200},
        {"beta": 0.5, "alpha": 0.2, "gamma": 0.8},
        {"beta": 0.9, "alpha": 0.2, "gamma": 0.5},
    )
    declared = bands_from_labels(rows, label_key="group", order=("beta", "alpha", "gamma"))
    assert [band.label for band in declared] == ["beta", "alpha", "gamma"]
    assert detect_monotonic_reversals(declared) == ()

    alphabetical = bands_from_labels(
        rows, label_key="group", order=("alpha", "beta", "gamma")
    )
    assert detect_monotonic_reversals(alphabetical) == (("beta", "gamma"),)


def test_a_band_with_no_members_is_omitted_rather_than_invented() -> None:
    rows = perfectly_calibrated_cohort({"present": 40}, {"present": 0.5})
    bands = bands_from_labels(rows, label_key="group", order=("present", "absent"))
    assert [band.label for band in bands] == ["present"]


def test_reversal_detection_needs_at_least_two_bands() -> None:
    assert detect_monotonic_reversals([Band("only", 0.5, 0.5, 10)]) == ()


# --- Expected calibration error ----------------------------------------------


def test_expected_calibration_error_is_weighted_by_population_not_by_bin() -> None:
    """The same volume-weighting mistake as a raw-percentage fantasy category.

    A bin holding 20 observations must not count as much as one holding 2,000.
    An unweighted mean over bins here would report 0.25; the weighted figure is
    0.0099..., and the difference is the whole reason the naive version is wrong.
    """

    rows = [
        *uniformly_biased_cohort({"tiny": 20}, {"tiny": 0.5}, bias=0.5),
        *perfectly_calibrated_cohort({"huge": 2000}, {"huge": 0.5}),
    ]
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    unweighted = sum(abs(row.gap) for row in report.bins) / len(report.bins)
    assert unweighted == pytest.approx(0.25, abs=1e-12)
    assert report.expected_calibration_error == pytest.approx(0.5 * 20 / 2020, abs=1e-12)
    assert report.maximum_calibration_error == pytest.approx(0.5, abs=1e-12)


# --- Binning -----------------------------------------------------------------


def test_distinct_probability_binning_survives_floating_point_drift() -> None:
    """Two arithmetically equal rates that differ by an ulp are one bin, not two.

    Splitting them would halve each bin's population and could fail v2 §8
    condition 4 for a purely numerical reason — a wrong veto, which is as bad as
    a wrong pass.
    """

    assert 0.1 + 0.2 != 0.3
    rows = [
        CalibrationObservation(f"drift#{index}", 0.1 + 0.2, index % 2 == 0)
        for index in range(30)
    ] + [CalibrationObservation(f"exact#{index}", 0.3, index % 2 == 0) for index in range(30)]
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert len(report.bins) == 1
    assert report.bins[0].observations == 60


def test_equal_width_binning_requires_an_explicit_bin_count() -> None:
    rows = perfectly_calibrated_cohort({"a": 40}, {"a": 0.5})
    with pytest.raises(ValueError, match="equal_width_bins"):
        build_calibration_report(
            rows,
            provenance=Provenance.PREREGISTERED_V2,
            binning=BinningScheme.EQUAL_WIDTH,
        )


def test_equal_width_binning_closes_the_final_bin_on_one() -> None:
    rows = [CalibrationObservation(f"certain#{index}", 1.0, True) for index in range(25)]
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.EQUAL_WIDTH,
        equal_width_bins=10,
    )
    assert [row.label for row in report.bins] == ["[0.900,1.000]"]


# --- Log loss ----------------------------------------------------------------


def test_log_loss_reports_how_many_rows_the_clip_touched() -> None:
    """A finite log loss must never hide that it is finite only by convention."""

    rows = [
        CalibrationObservation("confident-miss", 0.0, True),
        *[CalibrationObservation(f"ordinary#{i}", 0.5, i % 2 == 0) for i in range(9)],
    ]
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.log_loss_clipped_observations == 1
    assert math.isfinite(report.log_loss)
    assert report.log_loss > 3.0


def test_log_loss_reports_no_clipping_when_no_prediction_is_extreme() -> None:
    rows = perfectly_calibrated_cohort({"a": 40}, {"a": 0.5})
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.log_loss_clipped_observations == 0
    assert report.log_loss == pytest.approx(math.log(2.0), abs=1e-12)


# --- Paired bootstrap --------------------------------------------------------


def _paired(rows: list[CalibrationObservation], baseline: float) -> list[PairedPrediction]:
    return [
        PairedPrediction(
            observation_id=row.observation_id,
            candidate_predicted=row.predicted,
            baseline_predicted=baseline,
            played=row.played,
        )
        for row in rows
    ]


def test_paired_bootstrap_interval_clears_zero_for_a_genuinely_better_candidate() -> None:
    rows = perfectly_calibrated_cohort(
        {"low": 300, "high": 300},
        {"low": 0.1, "high": 0.9},
    )
    comparison = paired_bootstrap_brier(_paired(rows, 0.5), resamples=400, seed=250119)
    assert comparison.candidate_brier < comparison.baseline_brier
    assert comparison.interval_high < 0.0
    assert comparison.candidate_beats_baseline is True


def test_paired_bootstrap_does_not_clear_zero_for_an_identical_candidate() -> None:
    rows = perfectly_calibrated_cohort({"only": 300}, {"only": 0.5})
    comparison = paired_bootstrap_brier(_paired(rows, 0.5), resamples=400, seed=250119)
    assert comparison.mean_difference == pytest.approx(0.0, abs=1e-12)
    assert comparison.interval_high == pytest.approx(0.0, abs=1e-12)
    assert comparison.candidate_beats_baseline is False


def test_paired_bootstrap_is_deterministic_for_a_fixed_seed() -> None:
    rows = perfectly_calibrated_cohort({"low": 120, "high": 120}, {"low": 0.2, "high": 0.8})
    pairs = _paired(rows, 0.5)
    first = paired_bootstrap_brier(pairs, resamples=200, seed=250119)
    second = paired_bootstrap_brier(pairs, resamples=200, seed=250119)
    different = paired_bootstrap_brier(pairs, resamples=200, seed=999)
    assert first.interval_low == second.interval_low
    assert first.interval_high == second.interval_high
    assert (first.interval_low, first.interval_high) != (
        different.interval_low,
        different.interval_high,
    )


def test_paired_bootstrap_refuses_an_empty_cohort() -> None:
    with pytest.raises(ValueError, match="at least one observation"):
        paired_bootstrap_brier([], resamples=10, seed=1)


def test_paired_bootstrap_records_the_correlation_caveat_beside_the_number() -> None:
    rows = perfectly_calibrated_cohort({"only": 60}, {"only": 0.5})
    payload = paired_bootstrap_brier(_paired(rows, 0.5), resamples=50, seed=1).to_dict()
    assert "within-player" in str(payload["interval_caveat"])


# --- Emitted payload ---------------------------------------------------------


def test_every_report_carries_its_provenance_version_and_conventions() -> None:
    """"Version the output" — the Model gate bullet that does bite here."""

    rows = perfectly_calibrated_cohort({"a": 40}, {"a": 0.5})
    payload = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    ).to_dict()
    assert payload["machinery_version"] == CALIBRATION_MACHINERY_VERSION
    assert payload["provenance"] == "preregistered_v2"
    assert payload["binning"] == "distinct_emitted_probability"
    assert payload["restriction"] is None
    conventions = payload["declared_conventions"]
    assert isinstance(conventions, dict)
    assert "no continuity correction" in conventions["wilson_interval"]
    assert str(DEFAULT_PROBABILITY_DECIMALS) in conventions["probability_decimals"]


def test_a_restricted_payload_records_what_it_was_restricted_to() -> None:
    rows = perfectly_calibrated_cohort({"a": 40, "b": 40}, {"a": 0.3, "b": 0.7})
    payload = build_calibration_report(
        rows,
        provenance=Provenance.POST_HOC_DIAGNOSTIC,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        restriction={"group": "b"},
    ).to_dict()
    assert payload["restriction"] == [["group", "b"]]
    assert payload["provenance"] == "post_hoc_diagnostic"


# --- Input validation and generator determinism ------------------------------


def test_a_prediction_outside_zero_one_is_refused() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        CalibrationObservation("bad", 1.5, True)


def test_a_non_finite_prediction_is_refused() -> None:
    with pytest.raises(ValueError, match="finite"):
        CalibrationObservation("bad", float("nan"), True)


def test_exact_plays_rounds_half_up_rather_than_to_even() -> None:
    """`round()` would send 0.5 to 0 and 1.5 to 2, which no reader expects."""

    assert exact_plays(1, 0.5) == 1
    assert exact_plays(3, 0.5) == 2
    assert exact_plays(2963, 0.02) == 59
    assert exact_plays(83, 0.90) == 75


def test_synthetic_cohorts_are_reproducible_byte_for_byte() -> None:
    first = status_cohort_with_informative_error(
        counts_by_status=HELD_OUT_COUNTS,
        fictional_rate_by_status=FICTIONAL_RATES,
        informative_statuses=INFORMATIVE,
        informative_error=-0.5,
    )
    second = status_cohort_with_informative_error(
        counts_by_status=HELD_OUT_COUNTS,
        fictional_rate_by_status=FICTIONAL_RATES,
        informative_statuses=INFORMATIVE,
        informative_error=-0.5,
    )
    assert first == second
    assert len(first) == 3940


def test_an_error_pushing_a_prediction_out_of_range_is_refused_not_clipped() -> None:
    with pytest.raises(ValueError, match="leaves"):
        status_cohort_with_informative_error(
            counts_by_status=HELD_OUT_COUNTS,
            fictional_rate_by_status=FICTIONAL_RATES,
            informative_statuses=INFORMATIVE,
            informative_error=0.5,
        )


# --- Findings from the independent review at 5032bf1 -------------------------
#
# Four mutations written by a reviewer who was not the author survived the suite
# above. Every one is pinned here, and two of them were closed in the module
# rather than only in a test, because a survivor that is merely tested can be
# reintroduced by the next person who reads the test as optional.


def test_the_pooled_zeros_are_definitional_and_this_test_says_so() -> None:
    """The masked band's exact zeros are a restatement of the construction.

    An independent review was right that reporting `CITL == 0.0` and `ECE == 0.0`
    as though they were measurements invites a reader to treat a construction as
    a result. At offset zero every emitted probability **is** its bin's realised
    rate, so a zero gap is arithmetic, not evidence. This test exists to make
    that explicit in the suite rather than only in a docstring, and the honest
    version of the finding is driven by the two tests after it.
    """

    rows = _masked_band_cohort()
    report = build_calibration_report(
        rows,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    for row in report.bins:
        assert row.predicted_mean == pytest.approx(row.observed_rate, abs=1e-12)
        assert row.gap == pytest.approx(0.0, abs=1e-12)


def test_a_band_probability_displaced_by_one_point_starts_failing_condition_five() -> None:
    """The non-circular form: a real fit's band rate comes from another partition.

    A model fitted on development emits a band probability that is *not* the
    held-out band rate, so the interesting question is how far it may drift
    before a pooled condition notices. The `unlikely` band's 3,046 observations
    make condition 5 tight at band level, which is a real defence and one the
    first write-up of this finding did not mention.

    What does **not** move with the offset is the `doubtful` error: it stays
    around 86 points at every displacement, because condition 5 is protecting the
    band, not the status inside it.
    """

    tolerated = build_calibration_report(
        _masked_band_cohort(offset=0.005),
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert tolerated.bins_outside_wilson_interval == ()

    caught = build_calibration_report(
        _masked_band_cohort(offset=0.02),
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    unlikely = next(row for row in caught.bins if row.observations == 3046)
    assert unlikely.label in caught.bins_outside_wilson_interval

    for offset in (0.0, 0.005, 0.02):
        restricted = build_calibration_report(
            _masked_band_cohort(offset=offset),
            provenance=Provenance.POST_HOC_DIAGNOSTIC,
            binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
            restriction={"status": "doubtful"},
        )
        assert restricted.calibration_in_the_large < -0.8


def test_pooling_puts_the_two_statuses_in_one_bin_whatever_the_invented_rates() -> None:
    """The part of the masking finding that is a theorem, not a construction.

    Distinct-emitted-probability binning partitions rows by *predicted value*.
    Statuses sharing a band share a predicted value. So no statistic computed on
    that partition can separate them - at any offset, at any rates. Driven across
    three unrelated rate assignments so the claim cannot be an artefact of the
    numbers chosen, which is the guarantee the dilution identity already had and
    this finding did not.
    """

    for doubtful_rate in (0.10, 0.50, 0.90):
        rows = pooled_band_cohort(
            counts_by_status=HELD_OUT_COUNTS,
            fictional_rate_by_status={
                "out": 0.02,
                "doubtful": doubtful_rate,
                "questionable": 0.55,
                "probable": 0.85,
                "available": 0.95,
            },
            band_by_status={
                "out": "unlikely",
                "doubtful": "unlikely",
                "questionable": "uncertain",
                "probable": "likely",
                "available": "likely",
            },
        )
        report = build_calibration_report(
            rows,
            provenance=Provenance.PREREGISTERED_V2,
            binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        )
        assert len(report.bins) == 3
        assert report.bins_outside_wilson_interval == ()
        unlikely = next(row for row in report.bins if row.observations == 3046)
        assert unlikely.observations == HELD_OUT_COUNTS["out"] + HELD_OUT_COUNTS["doubtful"]


def test_restriction_excludes_a_row_that_lacks_the_restricted_key() -> None:
    """Reviewer mutation N02: treating a missing key as a match, and surviving.

    A restriction that keeps unlabelled rows is not a restriction. The mutation
    turned `restrict()` into a near-no-op and every test above stayed green,
    which means nothing was checking the one property that makes the operation
    worth having.
    """

    labelled = perfectly_calibrated_cohort({"a": 30}, {"a": 0.5})
    unlabelled = [
        CalibrationObservation(
            observation_id=f"bare-{index}",
            predicted=0.5,
            played=index % 2 == 0,
            labels={},
        )
        for index in range(30)
    ]
    kept = restrict([*labelled, *unlabelled], group="a")
    assert len(kept) == 30
    assert all(row.labels.get("group") == "a" for row in kept)
    assert not any(row.observation_id.startswith("bare-") for row in kept)


def test_wilson_z_is_the_standard_normal_upper_975th_percentile() -> None:
    """Reviewer mutation N01: swap the 95% constant for the 90% one, and survive.

    Everything else derived the interval from `WILSON_Z_95`, so the constant was
    self-referential: it could be any number and the suite would agree with
    itself. Pinned against an independent source rather than against a literal I
    typed twice.
    """

    assert pytest.approx(statistics.NormalDist().inv_cdf(0.975), abs=1e-12) == WILSON_Z_95


def test_an_inverted_bootstrap_interval_is_refused_rather_than_reported() -> None:
    """Reviewer mutation N05: swap the 2.5% and 97.5% quantiles, and survive.

    v2 §8 condition 2 reads the **upper** endpoint, so an inverted pair converts
    a straddling interval into a pass - a loosening, in the direction that
    flatters the candidate. Closed in `BrierComparison.__post_init__` rather than
    only here, because an invariant of the object belongs on the object.
    """

    with pytest.raises(ValueError, match="inverted"):
        BrierComparison(
            candidate_brier=0.2,
            baseline_brier=0.2,
            mean_difference=0.0,
            interval_low=0.05,
            interval_high=-0.05,
            resamples=10,
            seed=1,
        )


def test_a_straddling_interval_does_not_claim_the_candidate_wins() -> None:
    comparison = BrierComparison(
        candidate_brier=0.2,
        baseline_brier=0.2,
        mean_difference=-0.001,
        interval_low=-0.05,
        interval_high=0.05,
        resamples=10,
        seed=1,
    )
    assert comparison.interval_low < 0.0
    assert comparison.candidate_beats_baseline is False


def test_pre_filtered_rows_cannot_be_presented_as_a_pooled_v2_report() -> None:
    """The review's highest-severity finding, closed.

    The guard used to key on the `restriction` **parameter**, so narrowing the
    rows first with this module's own `restrict()` produced an 83-row
    `doubtful`-only table stamped `preregistered_v2` and `restriction: None` -
    indistinguishable from a legitimate pooled report. Not an exotic bypass: it
    is the obvious way to use the primitive this module deliberately promotes.
    """

    rows = _masked_band_cohort()
    only_doubtful = restrict(rows, status="doubtful")
    with pytest.raises(ValueError, match="PREREGISTERED_V2"):
        build_calibration_report(
            only_doubtful,
            provenance=Provenance.PREREGISTERED_V2,
            binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        )


def test_a_pre_filtered_report_records_what_it_was_filtered_on() -> None:
    rows = _masked_band_cohort()
    report = build_calibration_report(
        restrict(rows, status="doubtful"),
        provenance=Provenance.POST_HOC_DIAGNOSTIC,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.restriction == (("status", "doubtful"),)
    assert report.observations == 83


def test_a_pre_filter_and_a_parameter_restriction_are_both_recorded() -> None:
    """Pre-filter on the LATER key so insertion order and sorted order differ.

    A reviewer's mutation dropped the `sorted()` from the recorded restriction
    and all 61 tests stayed green, because this test used to pre-filter on
    `band` and pass `status` as the parameter - insertion order was already
    sorted order, so the assertion could not tell the two apart. Filtering on
    `status` first makes insertion order `(status, band)` and sorted order
    `(band, status)`, so the assertion now fails if the sort is removed.
    """

    rows = _masked_band_cohort()
    report = build_calibration_report(
        restrict(rows, status="doubtful"),
        provenance=Provenance.POST_HOC_DIAGNOSTIC,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        restriction={"band": "unlikely"},
    )
    assert report.restriction == (("band", "unlikely"), ("status", "doubtful"))
    assert report.observations == 83


def test_an_unlabelled_restrict_call_is_not_treated_as_a_restriction() -> None:
    """`restrict(rows)` narrows nothing, so it must not block a pooled claim."""

    rows = perfectly_calibrated_cohort({"a": 40}, {"a": 0.5})
    report = build_calibration_report(
        restrict(rows),
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.restriction is None
    assert report.observations == 40


def test_the_wilson_half_width_at_the_informative_counts_is_bounded_without_a_rate() -> None:
    """What condition 5 can promise per status, stated in a blind-safe form.

    The model card claims per-bin Wilson coverage gives real protection where a
    status gets its own bin. The reviewer computed ~0.053 at `questionable`'s
    *realised* rate - but that rate is an outcome nobody here may know, so the
    claim has to be made at the worst case, `p_hat = 0.5`, which maximises the
    half-width and depends on nothing but the count.
    """

    worst_case = {
        status: (lambda bounds: (bounds[1] - bounds[0]) / 2.0)(
            wilson_interval(HELD_OUT_COUNTS[status] // 2, HELD_OUT_COUNTS[status])
        )
        for status in ("questionable", "probable", "doubtful", "available")
    }
    assert worst_case["questionable"] == pytest.approx(0.0533, abs=5e-4)
    assert worst_case["questionable"] < 0.10
    assert worst_case["available"] == pytest.approx(0.0452, abs=5e-4)
    assert worst_case["available"] < 0.10
    # Mind the quantifier. For the two smaller statuses the supremum exceeds
    # 0.10, which establishes that no guarantee can be ISSUED without knowing
    # the rate - not that protection is absent. See the test below for the
    # narrow band of rates where it actually fails.
    assert worst_case["probable"] > 0.10
    assert worst_case["doubtful"] > 0.10


def test_where_condition_five_actually_stops_protecting_probable_and_doubtful() -> None:
    """The existential arm of the previous test, made specific.

    Saying `probable` and `doubtful` are "not protected by a 0.10 threshold" is
    a quantifier error: their worst case exceeds 0.10, so a guarantee cannot be
    issued blind, but the region where protection genuinely fails is narrow and
    is derivable from the counts alone. A reviewer caught the unqualified form
    in the model card's change log; this pins the corrected version.

    Blind-safe: it enumerates every arithmetically possible play count and
    reports which ones would breach. It reads no outcome and asserts nothing
    about which count is real.
    """

    def breaching_rates(observations: int) -> list[float]:
        breaching = []
        for plays in range(observations + 1):
            low, high = wilson_interval(plays, observations)
            if (high - low) / 2.0 >= 0.10:
                breaching.append(plays / observations)
        return breaching

    probable = breaching_rates(HELD_OUT_COUNTS["probable"])
    doubtful = breaching_rates(HELD_OUT_COUNTS["doubtful"])

    # `probable` fails only in a ~4-point window centred on a coin flip - for a
    # status whose label means "likely to play".
    assert len(probable) == 5
    assert min(probable) == pytest.approx(0.478, abs=5e-4)
    assert max(probable) == pytest.approx(0.522, abs=5e-4)

    # `doubtful` is wider, and likewise centred where a status meaning
    # "unlikely to play" is least expected to sit.
    assert min(doubtful) == pytest.approx(0.349, abs=5e-4)
    assert max(doubtful) == pytest.approx(0.651, abs=5e-4)

    # And the statuses with a sub-0.10 supremum have no breaching rate at all.
    assert breaching_rates(HELD_OUT_COUNTS["questionable"]) == []
    assert breaching_rates(HELD_OUT_COUNTS["available"]) == []


def test_the_g_league_share_of_doubtful_implies_a_health_only_floor_near_sixty_eight() -> None:
    """v3 section 6's own share does not reach v3 section 6's own headroom figure.

    v3 states that 41 of 221 season-wide `doubtful` observations are G League
    recall cases (18.6%), and separately that on health reasons alone the
    held-out `doubtful` floor is "~74", giving "2.5x" headroom over v2 section 8
    condition 6's minimum of 30. Applying the first number to the held-out count
    gives ~68 and 2.25x - 2.27x if the count is rounded to a whole player
    first - not 74 and 2.5x. The card leads with 2.25x; both are asserted below.

    Both are predictor-side counts, so this is checkable under the blind. The
    conclusion is unchanged either way - condition 6 clears comfortably - which
    is why the model card reports this to the architect rather than treating it
    as an objection. It is here so the discrepancy cannot be quietly re-copied.

    The 41/221 itself is NOT independently derivable from anything committed on
    `main`: the cohort manifest publishes status counts and stated-reason
    categories as separate marginals with no cross. It is quoted from v3.
    """

    g_league_doubtful_share = Fraction(41, 221)
    assert float(g_league_doubtful_share) == pytest.approx(0.186, abs=5e-4)

    held_out_doubtful = HELD_OUT_COUNTS["doubtful"]
    assert held_out_doubtful == 83

    health_only = held_out_doubtful * (1 - g_league_doubtful_share)
    assert health_only == Fraction(14940, 221)
    assert float(health_only) == pytest.approx(67.6, abs=0.05)
    assert round(float(health_only)) == 68

    condition_six_floor = 30
    headroom = float(health_only) / condition_six_floor
    assert headroom == pytest.approx(2.2534, abs=5e-4)
    # Rounding the count to a whole player first moves it barely.
    assert round(float(health_only)) / condition_six_floor == pytest.approx(2.2667, abs=5e-4)

    # v3's stated pair is not reproducible from v3's stated share.
    assert round(float(health_only)) != 74
    assert headroom < 2.5

def test_the_module_says_its_own_gate_does_not_pre_discharge_the_model_gate() -> None:
    """The one sentence in the docstring that a later lane is most likely to need.

    The architect ruled this unit Code-gated and pinned the caveat that carries
    the weight: when this machinery is later used to produce v2 section 7's
    held-out table, *that* report is Model-gated and this module is load-bearing
    inside it. Nothing verified here discharges any part of it.

    That is a claim about governance, so nothing in the arithmetic protects it -
    it survives only as prose, and prose is deletable. This test is the only
    thing standing between that paragraph and someone citing "the calibration
    machinery passed its gate" as though it settled the model's.
    """

    import hoops_gm.availability.calibration as module

    docstring = module.__doc__
    assert docstring is not None
    assert "does not pre-discharge" in docstring
    assert "Model-gated" in docstring
    assert "Nothing verified here discharges any part of that" in docstring
    # And the reason the reviewer's reading was available at all, so it is not
    # silently re-derived by the next lane to read gates.md.
    assert "word collision" in docstring
    assert "reliability-metrics.md" in docstring

# ---------------------------------------------------------------------------
# Findings from the second independent review, at 471c061
# ---------------------------------------------------------------------------


def test_nested_restriction_accumulates_rather_than_replacing() -> None:
    """P2-2: the inner filter used to vanish, and the payload under-reported.

    `restrict(restrict(rows, status="doubtful"), band="unlikely")` narrows twice
    but used to record only the outer pair. The reviewer drove the analogous
    case: a 60-row payload labelled as the whole `era=legacy` cohort when 200
    legacy rows had been dropped. Under-reporting is not obviously dangerous
    until you notice it is the same shape as the pooled-versus-restricted
    confusion this module exists to prevent, one level down.
    """

    rows = _masked_band_cohort()
    nested = restrict(restrict(rows, status="doubtful"), band="unlikely")

    assert nested.restriction == (("band", "unlikely"), ("status", "doubtful"))

    report = build_calibration_report(
        nested,
        provenance=Provenance.POST_HOC_DIAGNOSTIC,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.restriction == (("band", "unlikely"), ("status", "doubtful"))
    assert report.observations == 83

    # The outer key alone selects far more than the nested pair does, which is
    # exactly what the old payload concealed.
    assert len(restrict(rows, band="unlikely")) == 3046


def test_a_cohort_mutated_after_restriction_is_refused_rather_than_mislabelled() -> None:
    """P2-3: `extend` moved the rows and left the marker behind.

    The reviewer took an 83-row `doubtful` cohort, extended it with `out` rows,
    and got a 520-row report still recording `status=doubtful` - an
    `out`-dominated rate attributed to `doubtful`, through an ordinary list
    method. That is this project's headline failure mode arriving by the back
    door, so the marker is now re-verified against the rows instead of trusted.
    """

    rows = _masked_band_cohort()
    cohort = restrict(rows, status="doubtful")
    assert len(cohort) == 83
    cohort.extend(restrict(rows, status="out"))
    assert len(cohort) > 83

    with pytest.raises(ValueError, match="claims restriction"):
        build_calibration_report(
            cohort,
            provenance=Provenance.POST_HOC_DIAGNOSTIC,
            binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        )


def test_a_forged_marker_is_refused() -> None:
    """The same verification, reached by constructing the claim directly."""

    rows = _masked_band_cohort()
    forged = RestrictedCohort(rows, (("status", "doubtful"),))

    with pytest.raises(ValueError, match="claims restriction"):
        build_calibration_report(
            forged,
            provenance=Provenance.POST_HOC_DIAGNOSTIC,
            binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        )


@pytest.mark.parametrize(
    ("name", "transform"),
    [
        ("copy", lambda rc: copy.copy(rc)),
        ("deepcopy", lambda rc: copy.deepcopy(rc)),
        ("pickle", lambda rc: pickle.loads(pickle.dumps(rc))),
        ("slice", lambda rc: rc[:]),
        ("method_copy", lambda rc: rc.copy()),
        ("concat", lambda rc: rc + []),  # noqa: RUF005 - concatenation is the construct under test
        ("repeat", lambda rc: rc * 1),
    ],
)
def test_copying_a_restricted_cohort_keeps_it_restricted(
    name: str,
    transform: Callable[[RestrictedCohort], RestrictedCohort],
) -> None:
    """Defensive copying must not disarm the guard.

    Slicing and concatenation are how anyone copies a sequence; they are not
    laundering. A reviewer's enumeration found `rc[:]`, `rc + []` and `rc * 1`
    silently returning plain lists, which stripped the marker through an idiom
    nobody would think twice about. `copy`, `deepcopy` and `pickle` already
    held, because they restore `__dict__` without calling `__init__`.
    """

    rows = _masked_band_cohort()
    copied = transform(restrict(rows, status="doubtful"))

    assert isinstance(copied, RestrictedCohort), name
    assert copied.restriction == (("status", "doubtful"),), name
    with pytest.raises(ValueError, match="restricted"):
        build_calibration_report(
            copied,
            provenance=Provenance.PREREGISTERED_V2,
            binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        )


@pytest.mark.parametrize(
    ("name", "transform"),
    [
        ("list", lambda rc: list(rc)),
        ("tuple", lambda rc: list(tuple(rc))),  # noqa: C414 - the tuple round-trip is the point
        ("star", lambda rc: [*rc]),
        ("chain", lambda rc: list(itertools.chain(rc))),
    ],
)
def test_the_iteration_routes_that_strip_the_marker_are_named_not_denied(
    name: str,
    transform: Callable[[RestrictedCohort], list[CalibrationObservation]],
) -> None:
    """The residual, pinned as a fact so the docstring cannot drift from it.

    Any route that builds a fresh container by iterating discards the marker and
    the guard cannot fire. A third review refuted the *reason* an earlier version
    of this docstring gave - it said Python cannot intercept iteration, and it
    can: `__iter__` is an ordinary dunder, and a proof-of-concept that yields
    rows carrying provenance in `labels` refused all four of these routes. So
    the hole is a design choice, not a limit of the language, and the choice is
    argued in the module docstring rather than hidden behind a false
    impossibility claim.

    This test asserts the hole is still exactly where the docstring says it is.
    If a future change closes one of these, this test fails and the docstring
    gets corrected - which is the point. A claim of closure that nothing checks
    is how the first version of this guard came to be believed.
    """

    rows = _masked_band_cohort()
    stripped = transform(restrict(rows, status="doubtful"))

    assert not isinstance(stripped, RestrictedCohort), name
    report = build_calibration_report(
        stripped,
        provenance=Provenance.PREREGISTERED_V2,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.restriction is None, name
    assert report.observations == 83, name

def test_verification_refuses_a_claim_the_rows_are_merely_silent_about() -> None:
    """M23, which I wrote and which then survived my own suite.

    `_verify_restriction_holds` compares `row.labels.get(key)` to the value, so
    an unlabelled row fails the claim. Defaulting the lookup to the claimed
    value instead - the same missing-key trap the reviewer found one layer down
    in `restrict()` - would let a cohort that says nothing about `status` assert
    `status=doubtful` and be believed.

    Nothing exercised that path, so the mutation lived. It is the second time
    this exact shape has bitten in this module: a key that is absent is not a
    key that matches, and a suite whose fixtures are all fully labelled cannot
    tell the difference.
    """

    silent = RestrictedCohort(
        [
            CalibrationObservation(
                observation_id=f"silent-{index}",
                predicted=0.5,
                played=index % 2 == 0,
                labels={"era": "legacy"},
            )
            for index in range(30)
        ],
        (("status", "doubtful"),),
    )

    with pytest.raises(ValueError, match="claims restriction"):
        build_calibration_report(
            silent,
            provenance=Provenance.POST_HOC_DIAGNOSTIC,
            binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        )

# ---------------------------------------------------------------------------
# Findings from the third independent review, at 57e370d
# ---------------------------------------------------------------------------


def test_verification_checks_every_recorded_pair_not_merely_the_first() -> None:
    """3-A: a survivor, and the clearest case yet of a fix enlarging its own blind spot.

    Mutating the verification loop to `list(restriction.items())[:1]` survived
    all 78 tests. Every test that reached verification used a single-key
    restriction, so the loop body was never entered twice with a failing second
    pair - and the P2-2 fix, which made `restrict()` accumulate, had just made
    two-key markers the normal case rather than an exotic one.

    Sorted order puts `band` before `status`, so this cohort satisfies the first
    pair completely and the second not at all: exactly the shape a first-pair-only
    check cannot see. Under the mutant, 3,046 rows that `out` dominates 2,963 to
    83 are recorded as `status=doubtful` - the P2-3 lie, reached again through
    the door the P2-3 fix left open.
    """

    rows = _masked_band_cohort()
    band = restrict(rows, band="unlikely")
    assert len(band) == 3046
    assert all(row.labels["band"] == "unlikely" for row in band)

    forged = RestrictedCohort(band, (("band", "unlikely"), ("status", "doubtful")))
    with pytest.raises(ValueError, match="claims restriction status='doubtful'"):
        build_calibration_report(
            forged,
            provenance=Provenance.POST_HOC_DIAGNOSTIC,
            binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        )


def test_restrict_lets_the_outer_call_win_a_key_conflict() -> None:
    """3-D: a survivor. Reversing the merge returns rows under the wrong label.

    `restrict(restrict(rows, status="doubtful"), status="out")` must be empty:
    no row is both. Under `labels | inherited` it returns 83 `doubtful` rows
    marked `status=out`, and nothing downstream can tell, because the marker is
    self-consistent - every row present satisfies the recorded pair, so
    `_verify_restriction_holds` passes. Soundness is not identity.
    """

    rows = _masked_band_cohort()
    conflicting = restrict(restrict(rows, status="doubtful"), status="out")

    assert conflicting.restriction == (("status", "out"),)
    assert len(conflicting) == 0

    same_key_same_value = restrict(restrict(rows, status="doubtful"), status="doubtful")
    assert len(same_key_same_value) == 83


@pytest.mark.parametrize(
    ("name", "transform", "expected"),
    [
        ("double", lambda rc: rc * 2, 166),
        ("triple", lambda rc: rc * 3, 249),
        ("rdouble", lambda rc: 2 * rc, 166),
        ("head", lambda rc: rc[:10], 10),
        ("stride", lambda rc: rc[::2], 42),
        ("reverse", lambda rc: rc[::-1], 83),
        ("concat_self", lambda rc: rc + rc, 166),
    ],
)
def test_operations_that_change_multiplicity_or_extent_drop_the_marker(
    name: str,
    transform: Callable[[RestrictedCohort], list[CalibrationObservation]],
    expected: int,
) -> None:
    """3-B and 3-C: the P2-1 fix over-applied, and its contents were never asserted.

    Re-wrapping made the marker survive duplication and truncation. Every row
    still satisfied every recorded pair, so verification passed - the marker was
    true and the payload was false about the cohort. `rc * 3` recorded 249 rows
    as the 83-row `doubtful` subgroup.

    The count is asserted here as well as the type, because a separate survivor
    (`super().__mul__(1)` in place of `count`) showed that a container override
    can lose rows silently while every type and marker assertion still passes.
    """

    rows = _masked_band_cohort()
    result = transform(restrict(rows, status="doubtful"))

    assert len(result) == expected, name
    assert not isinstance(result, RestrictedCohort), name


@pytest.mark.parametrize(
    ("name", "transform", "expected"),
    [
        ("whole_slice", lambda rc: rc[:], 83),
        ("explicit_whole_slice", lambda rc: rc[0:83:1], 83),
        ("repeat_once", lambda rc: rc * 1, 83),
        ("concat_empty", lambda rc: rc + [], 83),  # noqa: RUF005 - concatenation is the construct under test
        ("method_copy", lambda rc: rc.copy(), 83),
    ],
)
def test_the_defensive_copy_idioms_still_preserve_the_marker_and_the_rows(
    name: str,
    transform: Callable[[RestrictedCohort], list[CalibrationObservation]],
    expected: int,
) -> None:
    """The other half of 3-B: narrowing the rule must not re-open the P2-1 hole.

    A whole-extent slice, `* 1`, `+ []` and `.copy()` provably preserve the row
    multiset, so they keep the marker. Anything that does not is above.
    """

    rows = _masked_band_cohort()
    result = transform(restrict(rows, status="doubtful"))

    assert len(result) == expected, name
    assert isinstance(result, RestrictedCohort), name
    assert result.restriction == (("status", "doubtful"),), name


def test_why_multiplicity_matters_condition_five_is_a_function_of_n() -> None:
    """3-B's motivation, as arithmetic rather than as principle.

    v2 §8 condition 5 is a Wilson half-width and goes as 1/sqrt(n), so
    duplicating a cohort tightens it. At the held-out `doubtful` count of 83 the
    worst case is outside 0.10 and a 0.10 guarantee cannot be issued; at 166 it
    is inside, and the same marker would still read `status=doubtful` with every
    recorded pair true. That is why the multiplicity rule exists, and it is
    computed from counts alone at the worst-case rate - no outcome is read.
    """

    def half_width(observations: int) -> float:
        low, high = wilson_interval(observations // 2, observations)
        return (high - low) / 2.0

    assert half_width(83) > 0.10
    assert half_width(166) < 0.10
    assert half_width(83) == pytest.approx(0.105154, abs=5e-6)
    assert half_width(166) == pytest.approx(0.075196, abs=5e-6)


def test_the_per_bin_gap_sign_is_observed_through_a_path_that_does_not_take_abs() -> None:
    """3-E: the second instance of the M12 symmetry class, and the general rule.

    `Band.gap` declares "positive over-predicts play", and reversing it survived
    the whole suite: every internal consumer takes `abs()` (ECE, MCE), and the
    only two tests that touched it wrapped it in `abs()` or asserted it equal to
    zero. So the sign was never observed at a nonzero value.

    The generalisation, which is worth more than this fix: a declared convention
    is pinned only if some test observes it through a path that does not
    symmetrise it. `abs`, a square, and a product of two sign-flipping factors
    all destroy exactly the information the convention asserts.

    `to_dict()` emits the signed gap, so this is load-bearing for any reader of
    the per-bin table, not merely internal bookkeeping.
    """

    over = CalibrationBin(
        label="over",
        predicted_mean=0.80,
        observed_rate=0.50,
        observations=100,
        plays=50,
        wilson_low=0.404,
        wilson_high=0.596,
    )
    under = CalibrationBin(
        label="under",
        predicted_mean=0.20,
        observed_rate=0.50,
        observations=100,
        plays=50,
        wilson_low=0.404,
        wilson_high=0.596,
    )

    assert over.gap == pytest.approx(0.30)
    assert under.gap == pytest.approx(-0.30)
    assert over.to_dict()["gap"] == pytest.approx(0.30)
    assert under.to_dict()["gap"] == pytest.approx(-0.30)
    assert "positive over-predicts play" in DECLARED_CONVENTIONS["bin_gap_sign"]


def test_a_tampered_cohort_is_repaired_rather_than_refused_when_a_restriction_is_passed() -> None:
    """The reviewer's informational asymmetry, pinned so it cannot drift silently.

    The same tampered object is refused on one call shape and silently repaired
    on the other: with a `restriction` parameter, `restrict()` re-filters the
    offending rows away before verification sees them. It fails safe - the
    payload that results is true of the rows it reports - but half the call
    surface never surfaces the tampering, which is worth knowing if you are
    relying on the error to tell you something went wrong.
    """

    rows = _masked_band_cohort()
    tampered = RestrictedCohort(rows, (("status", "doubtful"),))

    with pytest.raises(ValueError, match="claims restriction"):
        build_calibration_report(
            tampered,
            provenance=Provenance.POST_HOC_DIAGNOSTIC,
            binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        )

    repaired = build_calibration_report(
        tampered,
        provenance=Provenance.POST_HOC_DIAGNOSTIC,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
        restriction={"band": "unlikely"},
    )
    assert repaired.observations == 83
    assert repaired.restriction == (("band", "unlikely"), ("status", "doubtful"))


def test_removal_leaves_a_marker_that_is_true_and_no_longer_complete() -> None:
    """The completeness residual, driven rather than asserted in prose.

    Verification establishes soundness - every row present satisfies every
    recorded pair. It cannot establish completeness, because a cohort does not
    carry the population it was drawn from. `pop` leaves a marker that is still
    true of all 82 remaining rows and no longer describes the subgroup, and no
    check in this module can tell. Stated in the docstring, pinned here.
    """

    rows = _masked_band_cohort()
    cohort = restrict(rows, status="doubtful")
    cohort.pop()
    cohort.pop()

    report = build_calibration_report(
        cohort,
        provenance=Provenance.POST_HOC_DIAGNOSTIC,
        binning=BinningScheme.DISTINCT_EMITTED_PROBABILITY,
    )
    assert report.observations == 81
    assert report.restriction == (("status", "doubtful"),)