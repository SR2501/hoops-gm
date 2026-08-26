"""Post-parse verification of what a projection source actually delivered.

The parser answers "did these columns map?". This module answers the harder
question: **are the numbers behind those columns the quantity the profile says
they are?** Those are different failures. A file can map perfectly, parse
without a single issue, and still be season totals labelled per-game, or
per-*played*-game rates about to be discounted a second time for availability.

Everything here follows one rule, and every public function's docstring states
both halves of it: **name the defect the check excludes, then name a reading in
which the check passes and the defect is present.** A check whose false-pass
reading cannot be constructed is not a strong check — it is an unfalsifiable
one, and it is worth less than the sentence admitting so.

Two deliberate non-goals:

* **No check here verifies a forecast.** ``GP`` is a claim about a season that
  has not happened. It cannot be verified, only used. What *is* checkable is
  whether ``GP`` has already been folded into the per-game rates, which is a
  claim about arithmetic rather than about the future.
* **No check here verifies the vendor's scoring format.** Per-category
  per-game rates do not depend on it: a rebound is a rebound in 8-cat and
  9-cat, and the category set changes which rates get *valued*, not what any
  rate *is*. The one column whose meaning does depend on format is the
  vendor's composite total, and ADR-008 refuses that column outright rather
  than trying to verify a self-description. Refusing the column is a check
  that can fail; verifying the declaration is not.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from hoops_gm.identity.names import normalize_name
from hoops_gm.ingest.projections.models import ProjectionSourceRow

__all__ = [
    "COUNTING_STAT_PER_GAME_CEILING",
    "IMPORT_BLOCKING_CHECKS",
    "PTS_IDENTITY_TOLERANCE",
    "BakedInAvailabilityReport",
    "VerificationFinding",
    "VerificationOutcome",
    "VerificationReport",
    "verify_no_baked_in_availability",
    "verify_projection_batch",
    "verify_scoring_identity",
    "verify_value_shape",
]

#: No player has ever averaged 60 points per game. The highest single-season
#: mark in NBA history is 50.4 (Chamberlain, 1961-62), and the highest in the
#: modern era is 37.1. A projection is a central estimate, not a record
#: attempt, so the observed live ceiling is far below this: 32.7 across 429
#: rows. 60 is chosen to sit above anything a sane projection can produce and
#: far below the smallest plausible season total (a 10-game, 5-ppg fringe
#: player totals 50, but that is exactly why the check is on the *maximum*
#: across the batch rather than on any single row).
COUNTING_STAT_PER_GAME_CEILING = 60.0

#: ``2*FGM + 3PM + FTM`` should reproduce ``PTS`` exactly in real basketball.
#: Published figures are rounded to one decimal, so the residual has a
#: worst-case magnitude of ``2*0.05 + 0.05 + 0.05 + 0.05`` = 0.25. Measured
#: worst case across 429 live per-game rows: 0.20.
PTS_IDENTITY_TOLERANCE = 0.25

#: Below this many projected games a per-game rate is too noisy for the
#: baked-in-availability comparison to say anything, and including such rows
#: drags the cohort statistic around for reasons unrelated to the defect.
MIN_GAMES_FOR_BAKED_IN_CHECK = 20

#: How many players must clear the floor before the cohort statistic is
#: reported at all. Below this the median is not a cohort measurement.
MIN_COHORT_FOR_BAKED_IN_CHECK = 25

#: Which checks are allowed to *refuse* an import, as opposed to being recorded
#: on the outcome for a caller to read.
#:
#: Only ``value_shape`` is here, and the distinction is not "which check is more
#: important" — it is which check has a legitimate false positive.
#:
#: ``value_shape`` excludes the defect this whole module exists for: a batch on
#: the wrong basis, which inflates every counting category by a factor of the
#: games played and has no symptom whatsoever. No legitimate per-game projection
#: trips a 60-point ceiling, so a refusal here is never wrong about a real file.
#:
#: ``scoring_identity`` is a cross-check between columns a source may compute
#: *independently*. Vendors routinely blend a points projection from one model
#: and shooting volumes from another, then round each to one decimal; the two
#: need not reconcile to 0.25, and a source publishing to zero decimals would
#: fail it outright. Blocking on it would refuse legitimate files on draft week,
#: which is a loud failure in the wrong direction. It is still run, still
#: reported, and still visible on ``ProjectionImportOutcome.verification`` — the
#: caller decides.
IMPORT_BLOCKING_CHECKS = frozenset({"value_shape"})


class VerificationOutcome(StrEnum):
    """Whether a check ran, and what it concluded."""

    PASSED = "passed"
    FAILED = "failed"
    #: The check could not run — the inputs it needs were absent. This is
    #: distinct from passing, and is kept distinct precisely so that an empty
    #: input cannot be read as a clean bill of health.
    NOT_RUN = "not_run"


@dataclass(frozen=True)
class VerificationFinding:
    """One check, its outcome, and the reading in which it lies."""

    check: str
    outcome: VerificationOutcome
    detail: str
    #: The reading in which this check passes while the defect it targets is
    #: present. Carried in the data, not only in the docstring, so it travels
    #: with the result into a handoff entry or an operator's console.
    false_pass_reading: str
    observed: float | None = None
    threshold: float | None = None

    @property
    def failed(self) -> bool:
        return self.outcome is VerificationOutcome.FAILED


@dataclass
class VerificationReport:
    """The findings for one parsed batch."""

    profile_id: str
    rows_examined: int
    findings: list[VerificationFinding] = field(default_factory=list)

    @property
    def failures(self) -> list[VerificationFinding]:
        return [finding for finding in self.findings if finding.failed]

    @property
    def passed(self) -> bool:
        """True only if no check failed.

        Note what this deliberately does *not* require: that every check ran.
        A ``NOT_RUN`` finding is visible in ``findings`` and must be read
        there. Collapsing "clean" and "could not look" into one boolean is the
        shape of defect this module exists to catch, so the boolean is
        documented rather than made to carry a meaning it cannot.
        """
        return not self.failures


def _finite(values: Iterable[float | None]) -> list[float]:
    return [value for value in values if value is not None]


def verify_value_shape(rows: Sequence[ProjectionSourceRow]) -> VerificationFinding:
    """Detect season totals wearing per-game labels.

    This is the defect that actually happened to the Basketball Monster
    adapter: the page said "Per Game Stats" and served season totals. Hashtag
    Basketball can reproduce it on demand — its ``DDRANK`` control switches
    between per-game and season totals **while rendering identical header
    text**, so nothing in the file distinguishes the two. That is the
    ``gameEt`` shape: a self-describing artefact whose self-description is
    detached from its contents.

    The discriminator has to be a *counting* stat. An earlier draft of this
    check used minutes per game, on the reasoning that no one plays more than
    48. Measured against both modes: ``MPG <= 48`` passes on 100% of per-game
    rows **and 100% of season-total rows**, because Hashtag leaves minutes
    per-game in both modes. It separates nothing. ``PTS <= 60`` passes on 100%
    of per-game rows and 0% of season-total rows.

    Defect excluded: an entire batch of season totals imported as per-game
    rates, which inflates every counting category by roughly seventy times.

    Reading in which this passes and the defect is present: a *deep* cohort —
    a paste of only low-minute players — whose season totals all land under
    60 points. A player projected for 0.8 points across 40 games totals 32,
    and a batch made entirely of such players is indistinguishable to this
    check from a per-game batch. The check is strong on the star rows that
    dominate valuation and weak exactly where the shape error would matter
    least, which is the trade it is making, not an accident.
    """
    false_pass = (
        "a batch containing only low-volume players, whose season totals all fall "
        "below the per-game ceiling"
    )
    points = _finite(row.points_per_game for row in rows)
    if not points:
        return VerificationFinding(
            check="value_shape",
            outcome=VerificationOutcome.NOT_RUN,
            detail="no rows carried a points figure; shape was not examined",
            false_pass_reading=false_pass,
        )
    observed = max(points)
    if observed > COUNTING_STAT_PER_GAME_CEILING:
        return VerificationFinding(
            check="value_shape",
            outcome=VerificationOutcome.FAILED,
            detail=(
                f"maximum points figure {observed:.1f} exceeds the per-game ceiling "
                f"{COUNTING_STAT_PER_GAME_CEILING:.0f}; these are season totals, not "
                "per-game rates, whatever the file's header says"
            ),
            false_pass_reading=false_pass,
            observed=observed,
            threshold=COUNTING_STAT_PER_GAME_CEILING,
        )
    return VerificationFinding(
        check="value_shape",
        outcome=VerificationOutcome.PASSED,
        detail=(
            f"maximum points figure {observed:.1f} is consistent with per-game rates "
            f"across {len(points)} rows"
        ),
        false_pass_reading=false_pass,
        observed=observed,
        threshold=COUNTING_STAT_PER_GAME_CEILING,
    )


def verify_scoring_identity(rows: Sequence[ProjectionSourceRow]) -> VerificationFinding:
    """Check ``2*FGM + 3PM + FTM == PTS`` within display rounding.

    This ties the decomposed shooting volume back to a column parsed from a
    different cell entirely. It is the closest thing available to an
    independent witness inside a single file: the composite ``FG%`` cell and
    the standalone ``PTS`` column would have to be corrupted *consistently* to
    survive it.

    **This check cannot be the shape check, and the reason is worth keeping
    where the next reader will find it: the identity is scale-invariant.**
    Multiply every column in the file by 72 and ``2*FGM + 3PM + FTM == PTS``
    still holds exactly. So it passes cleanly while the season-totals defect
    is fully present. It happens to also flag season totals in the live data,
    but only because the absolute residual grows with magnitude — an accident
    of rounding, not a property to rely on. ``verify_value_shape`` carries
    that job; this one must not be promoted into it.

    Defect excluded: shooting volume that does not belong to the row it is
    sitting on — a column shifted by one during a paste, or an FG cell
    carrying FT volume.

    Reading in which this passes and the defect is present: any error applied
    uniformly to every scoring column at once, including the scale error
    above. Also two players swapped wholesale, since each row remains
    internally consistent — the identity constrains arithmetic within a row
    and knows nothing about whose row it is.
    """
    false_pass = (
        "any transformation applied uniformly across all scoring columns, notably a "
        "per-game/season-total scale error, since the identity is scale-invariant; "
        "also two rows swapped wholesale, each remaining internally consistent"
    )
    residuals: list[tuple[str, float]] = []
    for row in rows:
        fgm = row.field_goals_made_per_game
        tpm = row.three_pointers_made_per_game
        ftm = row.free_throws_made_per_game
        pts = row.points_per_game
        if fgm is None or tpm is None or ftm is None or pts is None:
            continue
        residuals.append((row.player_name, abs(2 * fgm + tpm + ftm - pts)))

    if not residuals:
        return VerificationFinding(
            check="scoring_identity",
            outcome=VerificationOutcome.NOT_RUN,
            detail=(
                "no row carried all of FGM, 3PM, FTM and PTS; the identity was not "
                "evaluated on any row"
            ),
            false_pass_reading=false_pass,
        )

    worst_name, worst = max(residuals, key=lambda pair: pair[1])
    if worst > PTS_IDENTITY_TOLERANCE:
        return VerificationFinding(
            check="scoring_identity",
            outcome=VerificationOutcome.FAILED,
            detail=(
                f"2*FGM + 3PM + FTM does not reproduce PTS for {worst_name!r}: off by "
                f"{worst:.2f} against a display-rounding tolerance of "
                f"{PTS_IDENTITY_TOLERANCE:.2f} ({len(residuals)} rows checked)"
            ),
            false_pass_reading=false_pass,
            observed=worst,
            threshold=PTS_IDENTITY_TOLERANCE,
        )
    return VerificationFinding(
        check="scoring_identity",
        outcome=VerificationOutcome.PASSED,
        detail=(
            f"2*FGM + 3PM + FTM reproduces PTS across {len(residuals)} rows; worst "
            f"residual {worst:.2f} ({worst_name!r})"
        ),
        false_pass_reading=false_pass,
        observed=worst,
        threshold=PTS_IDENTITY_TOLERANCE,
    )


@dataclass(frozen=True)
class BakedInAvailabilityReport:
    """Cohort evidence about whether ``GP`` is already inside the rates."""

    finding: VerificationFinding
    cohort_size: int
    median_ratio: float | None


def verify_no_baked_in_availability(
    rows: Sequence[ProjectionSourceRow],
    observed_minutes_per_played_game: dict[str, float],
    *,
    minimum_games: int = MIN_GAMES_FOR_BAKED_IN_CHECK,
    minimum_cohort: int = MIN_COHORT_FOR_BAKED_IN_CHECK,
) -> BakedInAvailabilityReport:
    """Test whether the vendor already discounted its rates for availability.

    This is the check the owner's decision actually rests on. On draft night
    he is comparing sixty games of player X against seventy of player Y, and
    that comparison is only coherent if the per-game rates describe a *healthy*
    game. ADR-002 requires production and availability to be computed
    separately and fused explicitly. If the vendor has already folded expected
    missed games into its per-game figures and ``quant`` then applies
    ``p(play)`` on top, the discount lands twice — and it lands hardest on
    exactly the fragile stars whose pricing this whole tool exists to get
    right.

    The test: for each player, compare the source's projected minutes per game
    against his own prior-season minutes per *played* game, taken from
    ``player_game_logs``. Those two quantities are independent in provenance —
    one is the vendor's forecast, the other is observed history the vendor did
    not supply us. A source publishing per-scheduled-game rates will sit
    systematically *below* observed per-played-game minutes; across this
    cohort the two bases are 12-33% apart, so the effect is large enough to
    see in a median.

    **This is a cohort statistic and must never become a per-row gate.** Any
    individual player can legitimately be projected for far fewer minutes than
    he played last season — a role change, an ageing curve, a new signing
    ahead of him on the depth chart. Failing his row would be wrong. Only the
    *systematic* direction across many players carries information.

    Direction is stated in advance, deliberately: baked-in availability makes
    the ratio fall below 1. A cohort median *above* 1 is not this defect and
    is not reported as one.

    Defect excluded: importing per-scheduled-game rates as per-healthy-game
    rates, producing a silent double-discount once ``p(play)`` is applied.

    Reading in which this passes and the defect is present: a season in which
    the cohort's real minutes genuinely shrink by about as much as the baking
    would have shrunk them — a league-wide load-management shift, or a cohort
    selected toward players losing minutes. The check cannot separate "the
    vendor discounted these rates" from "these players are really playing
    less", because both produce the same ratio. It is evidence about a
    direction, not a proof, and it is reported as a measurement with a
    threshold rather than as a verdict.
    """
    false_pass = (
        "a cohort whose minutes genuinely declined year over year by roughly the "
        "amount an availability discount would have applied; the ratio cannot "
        "distinguish a vendor discount from a real drop in role"
    )
    ratios: list[float] = []
    for row in rows:
        projected = row.minutes_per_game
        games = row.assumed_games_played
        if projected is None or not projected:
            continue
        if games is None or games < minimum_games:
            continue
        observed = observed_minutes_per_played_game.get(normalized_key(row))
        if observed is None or observed <= 0:
            continue
        ratios.append(projected / observed)

    if len(ratios) < minimum_cohort:
        return BakedInAvailabilityReport(
            finding=VerificationFinding(
                check="baked_in_availability",
                outcome=VerificationOutcome.NOT_RUN,
                detail=(
                    f"only {len(ratios)} players cleared the {minimum_games}-game floor and "
                    f"matched prior-season logs; {minimum_cohort} are required before a "
                    "cohort median means anything. This is not a pass."
                ),
                false_pass_reading=false_pass,
            ),
            cohort_size=len(ratios),
            median_ratio=None,
        )

    median_ratio = statistics.median(ratios)
    # 0.93 sits below the tightest end of the 12-33% separation between the two
    # bases, so a genuinely per-healthy-game source clears it comfortably while
    # a per-scheduled-game source does not.
    threshold = 0.93
    if median_ratio < threshold:
        return BakedInAvailabilityReport(
            finding=VerificationFinding(
                check="baked_in_availability",
                outcome=VerificationOutcome.FAILED,
                detail=(
                    f"across {len(ratios)} players the source's projected minutes are a "
                    f"median {median_ratio:.3f} of prior-season minutes per *played* game, "
                    f"below {threshold:.2f}. That is the signature of rates already "
                    "discounted for expected missed games. Applying p(play) on top would "
                    "double-count availability (ADR-002)."
                ),
                false_pass_reading=false_pass,
                observed=median_ratio,
                threshold=threshold,
            ),
            cohort_size=len(ratios),
            median_ratio=median_ratio,
        )
    return BakedInAvailabilityReport(
        finding=VerificationFinding(
            check="baked_in_availability",
            outcome=VerificationOutcome.PASSED,
            detail=(
                f"across {len(ratios)} players the source's projected minutes are a median "
                f"{median_ratio:.3f} of prior-season minutes per played game, consistent "
                "with per-healthy-game rates that have not been pre-discounted"
            ),
            false_pass_reading=false_pass,
            observed=median_ratio,
            threshold=threshold,
        ),
        cohort_size=len(ratios),
        median_ratio=median_ratio,
    )


def normalized_key(row: ProjectionSourceRow) -> str:
    """The key a caller should use when supplying observed prior-season minutes.

    Returns the ``key`` string rather than the ``NormalizedName`` object, so
    that callers building the observation dict and this module reading it
    agree. They did not agree in the first draft, and the symptom was an empty
    cohort — which the ``NOT_RUN`` outcome reported honestly rather than
    passing.
    """
    return normalize_name(row.player_name).key


def verify_projection_batch(
    profile_id: str,
    rows: Sequence[ProjectionSourceRow],
    *,
    observed_minutes_per_played_game: dict[str, float] | None = None,
) -> VerificationReport:
    """Run every applicable check over one parsed batch.

    The availability check runs only when prior-season observations are
    supplied. When they are not, it records ``NOT_RUN`` rather than being
    omitted — an absent check and a passing check must not look the same in
    the report.
    """
    report = VerificationReport(profile_id=profile_id, rows_examined=len(rows))
    report.findings.append(verify_value_shape(rows))
    report.findings.append(verify_scoring_identity(rows))
    if observed_minutes_per_played_game is None:
        report.findings.append(
            VerificationFinding(
                check="baked_in_availability",
                outcome=VerificationOutcome.NOT_RUN,
                detail=(
                    "no prior-season minutes were supplied, so whether this source has "
                    "already discounted its rates for availability is unknown, not clean"
                ),
                false_pass_reading="not applicable; the check did not run",
            )
        )
    else:
        report.findings.append(
            verify_no_baked_in_availability(rows, observed_minutes_per_played_game).finding
        )
    return report
