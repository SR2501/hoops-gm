"""Calibration and reliability-diagram machinery for binary probability forecasts.

This module fits nothing, reads no cohort, and holds no outcome. It scores
`(predicted probability, did the player play?)` pairs that a caller supplies.
It exists so that the apparatus the injury-status conversion model will be
**graded by** is written before anyone can see the score.

## Why it is written blind, and what that buys

Every estimator below carries convention choices that change a verdict:

* Wilson with or without a continuity correction,
* how "one row per distinct emitted probability" survives floating point,
* what log loss does with a prediction of exactly zero,
* which sign calibration-in-the-large carries,
* which empirical-quantile rule a bootstrap interval uses.

Each is a researcher degree of freedom. Fixed *before* the unblind they are
conventions; fixed *after* it they are choices someone made knowing which way
they would push the result. So they are fixed here, and each is stated in
`DECLARED_CONVENTIONS` and copied into every emitted report.

The choices were made without knowledge of any conversion rate. Where a choice
had an obvious "makes the gate easier / makes the gate harder" axis, the
stricter arm was taken and is flagged as such — see `WILSON_CONTINUITY_CORRECTION`.

## Provenance is mandatory, and that is the point

`docs/models/injury-status-conversion-preregistration.md` (v2) is the bound
protocol. Its §7 declares a pooled binned calibration table and nothing
restricted to a subgroup. A restricted table is proposed by
`injury-status-conversion-preregistration-v3-PROPOSED.md` §4 as condition 9, and
v3 is `Proposed` — not bound.

So a report cannot be built without saying which of those it is. A *restricted*
report may never claim `PREREGISTERED_V2`, because v2 pre-registers no such
analysis; that is true whatever the owner decides about v3, so the guard does not
depend on a fact that can change underneath it.

## What this module cannot see

It sees a probability and a boolean. It cannot see whether the probability came
from a model that was fit on the rows it is now being scored against, whether the
observations are independent, whether the outcome labels are correct, or whether
a "did not play" is a healthy scratch, a trade, or a G League assignment. A
report from this module is a statement about arithmetic, not about a season.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from itertools import pairwise
from typing import Final

from hoops_gm.availability.reliability import type7_quantile

#: Bumped whenever an emitted figure could change. Copied into every report so a
#: stored number traces to the arithmetic that produced it.
CALIBRATION_MACHINERY_VERSION: Final = "calibration-machinery-v1"

#: Two-sided 95% standard normal critical value.
WILSON_Z_95: Final = 1.959963984540054

#: **Declared blind.** No continuity correction. The corrected interval is
#: strictly wider, and a wider interval makes v2 §8 condition 5 ("every emitted
#: probability lies inside its bin's Wilson 95% interval") *easier* to pass. The
#: narrower, stricter arm is taken so the choice cannot be read as self-serving.
WILSON_CONTINUITY_CORRECTION: Final = False

#: **Declared blind.** v2 §7 asks for "one row per distinct emitted probability".
#: Grouping raw floats means two arithmetically identical rates that differ in the
#: last ulp become two bins, each with half the population — which could fail
#: condition 4 (">=20 observations per bin") for a purely numerical reason. That
#: would be a *wrong veto*, so predictions are rounded to this many decimals
#: before grouping. Twelve cannot merge two rates a real cell would distinguish.
DEFAULT_PROBABILITY_DECIMALS: Final = 12

#: **Declared blind.** Log loss is unbounded at a confident miss. Predictions are
#: clipped into `[LOG_LOSS_CLIP, 1 - LOG_LOSS_CLIP]`, and the number of rows the
#: clip actually touched is reported, so a finite log loss can never hide the fact
#: that it is finite only because of this constant.
LOG_LOSS_CLIP: Final = 1e-15

#: v2 §8 condition 4.
DEFAULT_POPULATION_FLOOR: Final = 20

#: v2 §7's paired player-game bootstrap.
DEFAULT_BOOTSTRAP_RESAMPLES: Final = 5000
DEFAULT_BOOTSTRAP_SEED: Final = 250119

DECLARED_CONVENTIONS: Final[Mapping[str, str]] = {
    "wilson_interval": "score interval, no continuity correction (the narrower, stricter arm)",
    "wilson_z_95": repr(WILSON_Z_95),
    "probability_decimals": (
        f"predictions rounded to {DEFAULT_PROBABILITY_DECIMALS} decimals before grouping"
    ),
    "log_loss_clip": f"predictions clipped into [{LOG_LOSS_CLIP}, 1 - {LOG_LOSS_CLIP}]",
    "calibration_in_the_large_sign": "mean(predicted) - observed rate; positive over-predicts play",
    "expected_calibration_error": "observation-weighted mean absolute bin gap",
    "bootstrap_quantile": "Hyndman-Fan type 7, on the resampled difference distribution",
    "bootstrap_unit": "one observation id, resampled with replacement",
}


class Provenance(Enum):
    """Which protocol, if any, pre-registered the figure being emitted.

    Required on every report. A number whose standing is not recorded beside it
    becomes a number whose standing is argued about later, under time pressure,
    by people who want it to have a particular standing.
    """

    #: Declared by v2 §7, which is bound. Pooled analyses only.
    PREREGISTERED_V2 = "preregistered_v2"
    #: Declared by v3 §4 condition 9, which is `Proposed` and not in force. Such
    #: a figure is computable and reportable, but it does not gate anything
    #: unless and until the owner binds v3.
    PROPOSED_V3_NOT_BOUND = "proposed_v3_not_bound"
    #: Chosen after the fact by whoever ran it. Correct, and less persuasive,
    #: because a reader cannot tell it from an analysis picked to suit a result.
    POST_HOC_DIAGNOSTIC = "post_hoc_diagnostic"


class BinningScheme(Enum):
    """How a reliability diagram's rows are formed.

    Deliberately has **no default** anywhere in this module. A default is a
    choice made silently, and this is exactly the kind of choice that must appear
    in the report rather than in someone's memory of what the function does.
    """

    #: v2 §7's scheme: one row per distinct emitted probability. Correct for a
    #: small-cell model such as the status-conditioned Jeffreys candidates.
    DISTINCT_EMITTED_PROBABILITY = "distinct_emitted_probability"
    #: Equal-width bins across [0, 1]. Not named by v2; for a continuous-output
    #: model such as the eventual per-game `p(play)`.
    EQUAL_WIDTH = "equal_width"


@dataclass(frozen=True)
class CalibrationObservation:
    """One scored forecast.

    `observation_id` is the resampling unit for the paired bootstrap — a
    player-game, for the injury-status model. `labels` carries whatever a caller
    may later want to restrict on: status, report era, lead-time band, whether
    the stated reason is a health event.
    """

    observation_id: str
    predicted: float
    played: bool
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not math.isfinite(self.predicted):
            raise ValueError(f"predicted probability must be finite, got {self.predicted!r}")
        if not 0.0 <= self.predicted <= 1.0:
            raise ValueError(f"predicted probability must lie in [0, 1], got {self.predicted!r}")


@dataclass(frozen=True)
class CalibrationBin:
    """One row of a binned calibration table / reliability diagram."""

    label: str
    predicted_mean: float
    observed_rate: float
    observations: int
    plays: int
    wilson_low: float
    wilson_high: float

    @property
    def emitted_probability_within_interval(self) -> bool:
        """v2 §8 condition 5, for this row."""

        return self.wilson_low <= self.predicted_mean <= self.wilson_high

    @property
    def gap(self) -> float:
        """Signed calibration gap. Positive over-predicts play."""

        return self.predicted_mean - self.observed_rate

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "predicted_mean": self.predicted_mean,
            "observed_rate": self.observed_rate,
            "observations": self.observations,
            "plays": self.plays,
            "wilson_low": self.wilson_low,
            "wilson_high": self.wilson_high,
            "gap": self.gap,
            "emitted_probability_within_interval": self.emitted_probability_within_interval,
        }


@dataclass(frozen=True)
class CalibrationReport:
    """A pooled or subgroup-restricted calibration result.

    `restriction` is `None` for a pooled report, otherwise the label filter that
    produced it, recorded so a restricted figure can never be read as a pooled
    one.
    """

    provenance: Provenance
    binning: BinningScheme
    restriction: tuple[tuple[str, str], ...] | None
    observations: int
    plays: int
    predicted_mean: float
    observed_rate: float
    brier_score: float
    log_loss: float
    log_loss_clipped_observations: int
    expected_calibration_error: float
    maximum_calibration_error: float
    bins: tuple[CalibrationBin, ...]
    population_floor: int
    machinery_version: str = CALIBRATION_MACHINERY_VERSION

    def __post_init__(self) -> None:
        # v2 §7 declares a pooled table and no restricted one. A restricted
        # figure claiming v2 pre-registration would be asserting a guarantee that
        # document does not carry. True regardless of what happens to v3.
        if self.restriction is not None and self.provenance is Provenance.PREREGISTERED_V2:
            raise ValueError(
                "a subgroup-restricted report may not claim PREREGISTERED_V2 provenance: "
                "v2 §7 pre-registers a pooled calibration table only. Restricted calibration "
                "is proposed by v3 §4 condition 9, which is not bound; label such a report "
                "PROPOSED_V3_NOT_BOUND or POST_HOC_DIAGNOSTIC."
            )

    @property
    def calibration_in_the_large(self) -> float:
        """Signed CITL error. Positive over-predicts play. v2 §8 condition 3."""

        return self.predicted_mean - self.observed_rate

    @property
    def bins_below_population_floor(self) -> tuple[str, ...]:
        """v2 §8 condition 4: bins too thin to support an emitted probability."""

        return tuple(
            row.label for row in self.bins if row.observations < self.population_floor
        )

    @property
    def bins_outside_wilson_interval(self) -> tuple[str, ...]:
        """v2 §8 condition 5: bins whose emitted probability its own data rejects."""

        return tuple(row.label for row in self.bins if not row.emitted_probability_within_interval)

    def to_dict(self) -> dict[str, object]:
        return {
            "machinery_version": self.machinery_version,
            "provenance": self.provenance.value,
            "binning": self.binning.value,
            "restriction": (
                None if self.restriction is None else [list(pair) for pair in self.restriction]
            ),
            "declared_conventions": dict(DECLARED_CONVENTIONS),
            "observations": self.observations,
            "plays": self.plays,
            "predicted_mean": self.predicted_mean,
            "observed_rate": self.observed_rate,
            "calibration_in_the_large": self.calibration_in_the_large,
            "brier_score": self.brier_score,
            "log_loss": self.log_loss,
            "log_loss_clipped_observations": self.log_loss_clipped_observations,
            "expected_calibration_error": self.expected_calibration_error,
            "maximum_calibration_error": self.maximum_calibration_error,
            "population_floor": self.population_floor,
            "bins_below_population_floor": list(self.bins_below_population_floor),
            "bins_outside_wilson_interval": list(self.bins_outside_wilson_interval),
            "bins": [row.to_dict() for row in self.bins],
        }


def wilson_interval(
    plays: int,
    observations: int,
    *,
    z: float = WILSON_Z_95,
) -> tuple[float, float]:
    """Return the Wilson score interval for `plays` successes in `observations`.

    No continuity correction — see `WILSON_CONTINUITY_CORRECTION`.

    The interval is the set of `p` satisfying `|p_hat - p| <= z * sqrt(p(1-p)/n)`,
    which is a quadratic in `p`; the closed form below is its two roots. The test
    suite checks this against that defining inequality solved numerically, so the
    implementation is verified against the definition rather than against itself.
    """

    if observations <= 0:
        raise ValueError("Wilson interval requires at least one observation")
    if not 0 <= plays <= observations:
        raise ValueError(f"plays {plays} outside [0, {observations}]")
    n = float(observations)
    p_hat = plays / n
    z_sq_over_n = z * z / n
    denominator = 1.0 + z_sq_over_n
    centre = (p_hat + z_sq_over_n / 2.0) / denominator
    spread = (
        z
        / denominator
        * math.sqrt(p_hat * (1.0 - p_hat) / n + z * z / (4.0 * n * n))
    )
    return max(0.0, centre - spread), min(1.0, centre + spread)


def restrict(
    observations: Iterable[CalibrationObservation],
    **labels: str,
) -> list[CalibrationObservation]:
    """Return the observations whose labels match every supplied key.

    Subgroup restriction is a first-class operation here rather than something a
    caller open-codes at each site, because the finding that motivated v3 is
    exactly that a pooled figure can be excellent while the subgroup the model is
    actually asked about is worthless. A capability that is awkward to reach for
    is a capability that does not get used under time pressure.
    """

    wanted = tuple(sorted(labels.items()))
    return [
        row
        for row in observations
        if all(row.labels.get(key) == value for key, value in wanted)
    ]


def build_calibration_report(
    observations: Sequence[CalibrationObservation],
    *,
    provenance: Provenance,
    binning: BinningScheme,
    restriction: Mapping[str, str] | None = None,
    population_floor: int = DEFAULT_POPULATION_FLOOR,
    probability_decimals: int = DEFAULT_PROBABILITY_DECIMALS,
    equal_width_bins: int | None = None,
) -> CalibrationReport:
    """Score a set of forecasts, optionally restricted to a labelled subgroup.

    `provenance` and `binning` are required and have no defaults. Both are
    choices that change what a number means, and a silent default is how such a
    choice stops being visible.
    """

    if restriction is not None:
        rows = restrict(observations, **dict(restriction))
        recorded_restriction: tuple[tuple[str, str], ...] | None = tuple(
            sorted(restriction.items())
        )
    else:
        rows = list(observations)
        recorded_restriction = None
    if not rows:
        raise ValueError("calibration requires at least one observation after restriction")

    total = len(rows)
    plays = sum(1 for row in rows if row.played)
    predicted_mean = sum(row.predicted for row in rows) / total
    observed_rate = plays / total
    brier = sum((row.predicted - float(row.played)) ** 2 for row in rows) / total
    log_loss, clipped = _log_loss(rows)

    if binning is BinningScheme.DISTINCT_EMITTED_PROBABILITY:
        bins = _distinct_probability_bins(rows, probability_decimals)
    else:
        if equal_width_bins is None or equal_width_bins < 1:
            raise ValueError("EQUAL_WIDTH binning requires equal_width_bins >= 1")
        bins = _equal_width_bins(rows, equal_width_bins)

    gaps = [(abs(row.gap), row.observations) for row in bins]
    ece = sum(gap * count for gap, count in gaps) / total
    mce = max(gap for gap, _count in gaps)

    return CalibrationReport(
        provenance=provenance,
        binning=binning,
        restriction=recorded_restriction,
        observations=total,
        plays=plays,
        predicted_mean=predicted_mean,
        observed_rate=observed_rate,
        brier_score=brier,
        log_loss=log_loss,
        log_loss_clipped_observations=clipped,
        expected_calibration_error=ece,
        maximum_calibration_error=mce,
        bins=bins,
        population_floor=population_floor,
    )


def _log_loss(rows: Sequence[CalibrationObservation]) -> tuple[float, int]:
    total = 0.0
    clipped = 0
    for row in rows:
        value = row.predicted
        if value < LOG_LOSS_CLIP or value > 1.0 - LOG_LOSS_CLIP:
            clipped += 1
            value = min(max(value, LOG_LOSS_CLIP), 1.0 - LOG_LOSS_CLIP)
        total += -math.log(value) if row.played else -math.log(1.0 - value)
    return total / len(rows), clipped


def _distinct_probability_bins(
    rows: Sequence[CalibrationObservation],
    decimals: int,
) -> tuple[CalibrationBin, ...]:
    grouped: dict[float, list[CalibrationObservation]] = {}
    for row in rows:
        grouped.setdefault(round(row.predicted, decimals), []).append(row)
    return tuple(
        _summarise_bin(f"p={key:.{min(decimals, 6)}f}", members)
        for key, members in sorted(grouped.items())
    )


def _equal_width_bins(
    rows: Sequence[CalibrationObservation],
    bin_count: int,
) -> tuple[CalibrationBin, ...]:
    grouped: dict[int, list[CalibrationObservation]] = {}
    for row in rows:
        index = min(int(row.predicted * bin_count), bin_count - 1)
        grouped.setdefault(index, []).append(row)
    return tuple(
        _summarise_bin(
            f"[{index / bin_count:.3f},{(index + 1) / bin_count:.3f}"
            f"{']' if index == bin_count - 1 else ')'}",
            members,
        )
        for index, members in sorted(grouped.items())
    )


def _summarise_bin(label: str, members: Sequence[CalibrationObservation]) -> CalibrationBin:
    count = len(members)
    plays = sum(1 for row in members if row.played)
    low, high = wilson_interval(plays, count)
    return CalibrationBin(
        label=label,
        predicted_mean=sum(row.predicted for row in members) / count,
        observed_rate=plays / count,
        observations=count,
        plays=plays,
        wilson_low=low,
        wilson_high=high,
    )


@dataclass(frozen=True)
class Band:
    """One rung of an ordered set of groups, for the monotonicity check."""

    label: str
    predicted_mean: float
    observed_rate: float
    observations: int


def bands_from_labels(
    observations: Sequence[CalibrationObservation],
    *,
    label_key: str,
    order: Sequence[str],
) -> tuple[Band, ...]:
    """Summarise observations into bands in a caller-declared order.

    The order is supplied rather than inferred, because v2 §8 condition 7 is
    about a *prior* ordering — unlikely, uncertain, likely — and inferring the
    order from the data would make a reversal impossible to detect by
    construction.
    """

    bands: list[Band] = []
    for label in order:
        members = [row for row in observations if row.labels.get(label_key) == label]
        if not members:
            continue
        count = len(members)
        plays = sum(1 for row in members if row.played)
        bands.append(
            Band(
                label=label,
                predicted_mean=sum(row.predicted for row in members) / count,
                observed_rate=plays / count,
                observations=count,
            )
        )
    return tuple(bands)


def detect_monotonic_reversals(bands: Sequence[Band]) -> tuple[tuple[str, str], ...]:
    """Return consecutive band pairs where predicted and observed move oppositely.

    v2 §8 condition 7. A reversal is a pair where the model says "more likely to
    play" and the data says "less likely", or the converse — the failure that
    makes a per-status table actively misleading rather than merely imprecise.
    """

    reversals: list[tuple[str, str]] = []
    for earlier, later in pairwise(bands):
        predicted_step = later.predicted_mean - earlier.predicted_mean
        observed_step = later.observed_rate - earlier.observed_rate
        if predicted_step * observed_step < 0:
            reversals.append((earlier.label, later.label))
    return tuple(reversals)


@dataclass(frozen=True)
class PairedPrediction:
    """One observation scored by both a candidate model and a baseline."""

    observation_id: str
    candidate_predicted: float
    baseline_predicted: float
    played: bool


@dataclass(frozen=True)
class BrierComparison:
    """Paired-bootstrap comparison of two models' Brier scores.

    The difference is `candidate - baseline`, so **negative is better**, and
    v2 §8 condition 2 asks for the interval's upper endpoint to lie below zero.
    """

    candidate_brier: float
    baseline_brier: float
    mean_difference: float
    interval_low: float
    interval_high: float
    resamples: int
    seed: int

    @property
    def candidate_beats_baseline(self) -> bool:
        return self.interval_high < 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_brier": self.candidate_brier,
            "baseline_brier": self.baseline_brier,
            "mean_difference": self.mean_difference,
            "interval_low": self.interval_low,
            "interval_high": self.interval_high,
            "resamples": self.resamples,
            "seed": self.seed,
            "candidate_beats_baseline": self.candidate_beats_baseline,
            "interval_caveat": (
                "resampled by observation id; not valid against within-player or "
                "within-game correlation"
            ),
        }


def paired_bootstrap_brier(
    pairs: Sequence[PairedPrediction],
    *,
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> BrierComparison:
    """Bootstrap the Brier difference, resampling observation ids with replacement.

    The interval is **not** valid against within-player or within-game
    correlation. That limitation is v2 §7's own wording and is reported beside
    the number rather than fixed by asserting independence.
    """

    if not pairs:
        raise ValueError("paired bootstrap requires at least one observation")
    if resamples < 1:
        raise ValueError("paired bootstrap requires at least one resample")

    differences = [
        (pair.candidate_predicted - float(pair.played)) ** 2
        - (pair.baseline_predicted - float(pair.played)) ** 2
        for pair in pairs
    ]
    candidate_brier = sum(
        (pair.candidate_predicted - float(pair.played)) ** 2 for pair in pairs
    ) / len(pairs)
    baseline_brier = sum(
        (pair.baseline_predicted - float(pair.played)) ** 2 for pair in pairs
    ) / len(pairs)

    generator = random.Random(seed)
    size = len(differences)
    estimates = [
        sum(differences[generator.randrange(size)] for _ in range(size)) / size
        for _resample in range(resamples)
    ]
    return BrierComparison(
        candidate_brier=candidate_brier,
        baseline_brier=baseline_brier,
        mean_difference=sum(differences) / size,
        interval_low=type7_quantile(estimates, 0.025),
        interval_high=type7_quantile(estimates, 0.975),
        resamples=resamples,
        seed=seed,
    )
