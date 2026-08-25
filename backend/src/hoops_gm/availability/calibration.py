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

**The guard keys on the data, not on which argument the caller used.** An earlier
version keyed only on the `restriction` parameter, and an independent review
defeated it in one line: narrow the rows with this module's own `restrict()`
first, then pass them in as though they were the whole cohort, and the payload
claimed `PREREGISTERED_V2` over an 83-row subgroup. `restrict()` therefore
returns a `RestrictedCohort` that carries what it filtered on, and
`build_calibration_report` inherits that provenance rather than trusting the call
site.

**The residual, stated as a class rather than by naming one convenient example.**
A second review enumerated fifteen routes. `copy.copy`, `copy.deepcopy` and
`pickle` round-trips preserve the marker, because they restore `__dict__` without
calling `__init__`. A whole-extent slice, `* 1`, `+ []` and `.copy()` re-wrap,
because those are defensive-copy idioms; the other forms of those operators
return a plain `list` and so assert nothing. A **fourth** review then defeated
the sentence that used to stand here, which claimed that operations changing
multiplicity return a plain list: `rc += list(rc)`, `rc[0:0] = list(rc)`,
`rc.extend(list(rc))`, and `append`/`insert`/`rc[1] = rc[0]` with a row taken
from the cohort itself, all return a `RestrictedCohort` with the marker intact
and `n` inflated, because `__iadd__` and the mutating methods were never
overridden. (Its headline example, `rc *= 2`, was **wrong** - that one returns a
plain `list`, but only because defining `__mul__` at Python level makes the
in-place operator fall back to it, an accident nothing here relies on. See
`test_the_one_in_place_route_that_does_drop_the_marker_drops_it_by_accident`.)
Every dunder overridden here has an in-place twin that was not. That was a
**false guarantee** rather than a disclosed residual, and the repair is not a
longer list of dunders - see
`_verify_no_duplicate_observations`. What survives is any
route that builds a fresh container by iterating - `list(rc)`, `tuple(rc)`,
`[*rc]`, `itertools` round-trips. A third review **refuted the reason an earlier
version of this paragraph gave for that**: it claimed Python offers no way to
intercept iteration, and it does - `__iter__` is an ordinary dunder, and a
proof-of-concept that yields rows carrying a provenance label in `labels`
refused all five named routes. So the residual is a **design choice, not a
limit of the language**: row-level provenance was not taken because it mutates
row labels, allocates a fresh frozen dataclass per row per iteration, breaks row
identity and equality, and is itself strippable by a caller who wants it - it
moves the residual rather than removing it. What is unarguably true is the
narrower statement: Python cannot stop a caller obtaining a plain `list` of the
rows. The honest claim is therefore not that laundering is impossible, but that
**it takes a step whose only effect is to discard provenance** - and that the
guard is one layer, not the mechanism. The mechanism is that `restriction` is
recorded in the payload and re-verified against the rows.

**And the marker is verified, not believed.** `RestrictedCohort` is a mutable
list, so `rc.extend(...)` changes the contents while the marker stands still. The
same review drove an 83-row `doubtful` cohort extended to 520 rows still
reporting `status=doubtful` - an `out`-dominated rate attributed to `doubtful`,
which is precisely the masking failure the model card warns about, reached
through a list method rather than an exotic bypass. `_verify_restriction_holds`
now re-checks every row against every recorded pair, so a marker that has stopped
being true raises instead of being printed.

**What that verification establishes, and the two things it does not.** It
establishes **soundness**: every row present satisfies every recorded pair. It
cannot establish **completeness** - that every row satisfying the restriction is
present - because a cohort does not carry the population it was drawn from, so
`pop`, `remove` and `del rc[40:]` leave a marker that is still true and no longer
describes the subgroup. And it cannot establish **multiplicity** - that no row is
present twice - because a duplicated row satisfies the pair as happily as the
original. Multiplicity is not left to the container guards, which a fourth
review walked around in one character (`rc * 2` refused, `rc *= 2` allowed): it
is enforced at the point the cohort becomes a number, by
`_verify_no_duplicate_observations`, which refuses a repeated
`observation_id` however the repetition was produced. Completeness remains a
genuine residual and is stated here so that a later lane reads a bounded
guarantee rather than a general one.

## What this module cannot see

It sees a probability and a boolean. It cannot see whether the probability came
from a model that was fit on the rows it is now being scored against, whether the
observations are independent, whether the outcome labels are correct, or whether
a "did not play" is a healthy scratch, a trade, or a G League assignment. A
report from this module is a statement about arithmetic, not about a season.

## This module's own gate does not pre-discharge the model's

**Read this before citing "the calibration machinery passed its gate" for
anything.** This module was written under the **Code gate**. That is the
architect's ruling, and the reasoning is worth carrying rather than just the
verdict: you cannot hold data out from a formula, so the honest discharge for a
deterministic estimator is verification against analytically known values and
deliberate corruption — which is what the tests and `scripts/mutate_calibration.py`
do. There is no estimate here to back-test.

An independent reviewer argued for Code + Model, reading `gates.md`'s *"anything
producing a number a decision rests on — `p(play)`, reliability metrics, …"* as a
leading-clause test with the em-dash list as examples, and taking "reliability
metrics" to name this apparatus. **That last step is a word collision**: the
entry means the player-consistency model in `docs/models/reliability-metrics.md`,
not a *reliability diagram*, which is a calibration plot. Two senses of one word
inside the file that decides which gate applies. The argument was put, considered
and ruled on; it is recorded here because a reader will otherwise re-derive it.

**The half that binds forward:** when this machinery is later used to produce v2
§7's held-out calibration table, **that report is Model-gated**, and this module
is load-bearing inside it. Nothing verified here discharges any part of that
gate. A green suite in this module says its arithmetic is right; it says nothing
whatever about whether a model scored by it is any good.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from itertools import pairwise
from typing import Final, SupportsIndex, overload

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
    "bin_gap_sign": "predicted mean - observed rate, per bin; positive over-predicts play",
    "expected_calibration_error": "observation-weighted mean absolute bin gap",
    "bootstrap_quantile": "Hyndman-Fan type 7, on the resampled difference distribution",
    "bootstrap_unit": (
        "one observation id, resampled with replacement; duplicate ids are refused"
    ),
    "duplicate_observations": "refused; the same forecast may not be counted twice",
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
        """Signed calibration gap. Positive over-predicts play.

        The sign is emitted in `to_dict()`, so it is load-bearing for any reader
        of the per-bin table - but every internal consumer takes `abs()`, which
        is exactly the symmetry that let a reversed-sign mutant survive a whole
        suite. A declared convention is only pinned if some test observes it
        through a path that does not symmetrise it.
        """

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


class RestrictedCohort(list[CalibrationObservation]):
    """Observations that have already been narrowed to a labelled subgroup.

    It exists so the provenance guard can key on **what the data is** rather than
    on which parameter the caller happened to use. Pre-filtering with `restrict()`
    and then presenting the result as a whole cohort was a one-line defeat of the
    parameter-keyed guard, and it is the ordinary way a caller would reach for a
    restriction primitive, not an exotic bypass.

    **The marker is an assertion, so it is verified rather than believed.** This
    is a mutable `list`, and `rc.extend(...)` is an ordinary method call that
    leaves the marker untouched while changing what the marker describes. A
    second review drove exactly that: 83 `doubtful` rows extended with 437 `out`
    rows still recorded `status=doubtful`, which is the pooling failure this
    module's own model card warns about, reached through a list method. So
    `build_calibration_report` re-checks every row against every recorded pair
    before it will record it - see `_verify_restriction_holds`.

    Container operations re-wrap **only when they provably preserve the row
    multiset** - a whole-extent slice, `* 1`, `+ []`, `.copy()`. A third review
    showed why the wider rule was wrong: `rc * 2` and `rc[:10]` re-wrapped too,
    so the marker stayed true of every row present while the payload's `n` was
    doubled or truncated. That is not academic here. v2 §8 condition 5 is a
    Wilson half-width, which goes as `1/sqrt(n)`: duplicating an 83-row
    `doubtful` cohort takes its worst case from 0.1052 to 0.0752 and converts
    "a 0.10 guarantee cannot be issued" into "protected", with every recorded
    pair still true.

    **These guards are one layer and are not the multiplicity guarantee.** A
    fourth review walked around them by moving a single character: `rc + other`
    is refused, `rc += other` is not, because `__iadd__` has no override - and
    neither have `extend`, `append`, `insert`, slice-assignment, or any other
    route that builds a cohort without going through these methods. The
    sentence that used to end this docstring, promising that
    multiplicity-changing operations return a plain `list`, was therefore a
    false guarantee. Duplication is now refused where the cohort becomes a
    number, by `_verify_no_duplicate_observations`; these methods remain because
    failing early at the operation is friendlier than failing late at the
    report, not because they are sufficient.
    """

    def __init__(
        self,
        rows: Iterable[CalibrationObservation],
        restriction: tuple[tuple[str, str], ...],
    ) -> None:
        super().__init__(rows)
        self.restriction = restriction

    @overload
    def __getitem__(self, index: SupportsIndex) -> CalibrationObservation: ...

    @overload
    def __getitem__(self, index: slice) -> list[CalibrationObservation]: ...

    def __getitem__(
        self, index: SupportsIndex | slice
    ) -> CalibrationObservation | list[CalibrationObservation]:
        if isinstance(index, slice):
            rows: list[CalibrationObservation] = super().__getitem__(index)
            if index.indices(len(self)) == (0, len(self), 1):
                return RestrictedCohort(rows, self.restriction)
            return rows
        return super().__getitem__(index)

    def __add__(  # type: ignore[override]
        self, other: list[CalibrationObservation]
    ) -> list[CalibrationObservation]:
        combined: list[CalibrationObservation] = super().__add__(other)
        if not other:
            return RestrictedCohort(combined, self.restriction)
        return combined

    def __mul__(self, count: SupportsIndex) -> list[CalibrationObservation]:
        repeated: list[CalibrationObservation] = super().__mul__(count)
        if count.__index__() == 1:
            return RestrictedCohort(repeated, self.restriction)
        return repeated

    def __rmul__(self, count: SupportsIndex) -> list[CalibrationObservation]:
        repeated: list[CalibrationObservation] = super().__rmul__(count)
        if count.__index__() == 1:
            return RestrictedCohort(repeated, self.restriction)
        return repeated

    def copy(self) -> RestrictedCohort:
        return RestrictedCohort(self, self.restriction)


def restrict(
    observations: Iterable[CalibrationObservation],
    **labels: str,
) -> RestrictedCohort:
    """Return the observations whose labels match every supplied key.

    Subgroup restriction is a first-class operation here rather than something a
    caller open-codes at each site, because the finding that motivated v3 is
    exactly that a pooled figure can be excellent while the subgroup the model is
    actually asked about is worthless. A capability that is awkward to reach for
    is a capability that does not get used under time pressure.

    A row **missing** a restricted key is excluded, not kept. That is the whole
    difference between a restriction and a no-op, and it is the reason
    `row.labels.get(key)` is compared to `value` rather than tested for
    truthiness.

    **Nesting accumulates, and the outer call wins a key conflict.**
    `restrict(restrict(rows, status="doubtful"), era="legacy")` records both
    pairs, not just the outer one. An earlier version recorded only
    `era=legacy`, so a 60-row payload claimed to be the legacy cohort while 200
    legacy rows had been silently dropped - an under-report of the same kind the
    pooled-versus-restricted distinction exists to prevent, one level down. When
    the same key appears twice, `labels` overrides `inherited`, so
    `restrict(restrict(rows, status="doubtful"), status="out")` is empty rather
    than 83 `doubtful` rows relabelled `out`. That precedence is load-bearing
    and unobservable from the payload - both orders produce a self-consistent
    marker that `_verify_restriction_holds` accepts - so it is pinned by test.
    """

    inherited = dict(_inherited_restriction(observations))
    wanted = tuple(sorted((inherited | labels).items()))
    return RestrictedCohort(
        (
            row
            for row in observations
            if all(row.labels.get(key) == value for key, value in wanted)
        ),
        wanted,
    )


def _inherited_restriction(
    observations: Iterable[CalibrationObservation],
) -> tuple[tuple[str, str], ...]:
    """What `observations` was already filtered on, if anything."""

    if isinstance(observations, RestrictedCohort):
        return observations.restriction
    return ()


def _verify_no_duplicate_observations(
    rows: Sequence[CalibrationObservation],
) -> None:
    """Refuse a cohort that counts the same forecast twice.

    Verification of the restriction marker establishes soundness only: a
    duplicated row satisfies every recorded pair as happily as the original, so
    multiplicity has to be checked separately or not at all. A fourth review
    showed why "not at all" is untenable. `rc += list(rc)`,
    `rc[0:0] = list(rc)`, `rc.extend(list(rc))` and a directly constructed
    subclass all produce a
    cohort whose marker is true of every row present and whose `n` is wrong -
    and `n` is not decoration. v2 §8 condition 5 is a Wilson half-width going as
    `1/sqrt(n)`: duplicating the 83-row `doubtful` cohort moves its worst case
    from 0.1052 to 0.0752 and **manufactures** the 0.10 guarantee this model
    card says cannot be issued blind. Condition 6's population floor reads the
    same inflated count.

    The reviewer's own suggestion was to enumerate the in-place twin of every
    dunder already overridden - `__iadd__` for `__add__`, `__imul__` for
    `__mul__`, `__setitem__` for `__getitem__`. That is a good rule and a closed
    list, but it is the weaker fix: it guards the routes someone thought of, and
    `list` is not the only way to build a cohort. It also would not have covered
    `append` or `insert`, which have no non-mutating twin to have prompted them,
    and which duplicate a row just as effectively. Checking the invariant
    **where the claim becomes a number** covers every route at once, including
    direct construction and the adversarial `__index__` that the container
    guards cannot see. It is the same principle as verifying the marker rather
    than believing it.
    """

    counts = Counter(row.observation_id for row in rows)
    repeated = sorted(identifier for identifier, count in counts.items() if count > 1)
    if repeated:
        raise ValueError(
            f"{len(repeated)} observation id(s) appear more than once, starting with "
            f"{repeated[0]!r}; duplication inflates n and narrows every interval"
        )


def _verify_restriction_holds(
    rows: Sequence[CalibrationObservation],
    restriction: Mapping[str, str],
) -> None:
    """Refuse to record a restriction that the rows do not actually satisfy.

    A `RestrictedCohort`'s marker is an assertion made when it was built, and a
    `list` stays mutable afterwards. Checking is cheap and the alternative is a
    payload that misdescribes its own contents, which is worse than an error
    because nothing downstream can detect it.

    **Every pair, not the first.** `restrict()` accumulates, so a two-key marker
    is the normal case and not an edge one; a version of this loop that checked
    only the first pair survived a whole suite, because every test that reached
    here used a single-key restriction. Fixing one defect enlarged the surface
    the next one hides in, which is why the multi-pair path is now driven at
    n=2 rather than n=1.
    """

    for key, value in restriction.items():
        offenders = sum(1 for row in rows if row.labels.get(key) != value)
        if offenders:
            raise ValueError(
                f"cohort claims restriction {key}={value!r} but "
                f"{offenders} of {len(rows)} rows do not satisfy it"
            )


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

    inherited = _inherited_restriction(observations)
    rows: list[CalibrationObservation]
    if restriction is not None:
        rows = restrict(observations, **dict(restriction))
        # Precedence on a key conflict is unobservable by construction: the two
        # values cannot both match a row, so `rows` goes empty and the call
        # raises below before `merged` is ever recorded. An independent reviewer
        # confirmed reversing this `|` is an equivalent mutant, not a gap.
        merged = dict(inherited) | dict(restriction)
    else:
        rows = list(observations)
        merged = dict(inherited)
    _verify_restriction_holds(rows, merged)
    _verify_no_duplicate_observations(rows)
    recorded_restriction: tuple[tuple[str, str], ...] | None = (
        tuple(sorted(merged.items())) if merged else None
    )
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

    def __post_init__(self) -> None:
        # An independent review swapped the 2.5% and 97.5% quantiles and the
        # suite stayed green, while `candidate_beats_baseline` flipped to True on
        # a candidate that does not beat its baseline - a loosening of v2 §8
        # condition 2 that no test saw. Endpoint order is an invariant of the
        # object, so it is enforced here rather than left to a caller to notice.
        if self.interval_low > self.interval_high:
            raise ValueError(
                "bootstrap interval endpoints are inverted: "
                f"low {self.interval_low!r} exceeds high {self.interval_high!r}. "
                "v2 §8 condition 2 reads the UPPER endpoint, so an inverted pair "
                "silently converts a straddling interval into a pass."
            )

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

    **The declared unit is enforced, not assumed.** `DECLARED_CONVENTIONS`
    records the resampling unit as one observation id, and a fourth review
    found the loop resampling *row positions* while `observation_id` was never
    read - true only for as long as ids happen to be unique, and silently
    producing an interval that is too narrow the moment they are not. Too
    narrow is the direction that makes v2 §8 condition 2 easier to pass, so the
    error flattered the candidate. A declared convention the code does not
    implement is worse than an undeclared one, because a later reader has a
    written assurance to rely on. Duplicate ids are therefore refused here, and
    with ids unique the positional draw *is* the id draw.
    """

    if not pairs:
        raise ValueError("paired bootstrap requires at least one observation")
    if resamples < 1:
        raise ValueError("paired bootstrap requires at least one resample")
    repeated_ids = sorted(
        identifier
        for identifier, count in Counter(pair.observation_id for pair in pairs).items()
        if count > 1
    )
    if repeated_ids:
        raise ValueError(
            f"{len(repeated_ids)} observation id(s) appear more than once, starting "
            f"with {repeated_ids[0]!r}; the declared resampling unit is one "
            "observation id, and repeated ids would narrow the interval"
        )

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
