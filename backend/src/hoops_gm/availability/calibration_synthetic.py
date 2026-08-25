"""Synthetic cohorts with **known** calibration properties.

Every cohort here is fabricated. Nothing in this module reads a database, a
cohort manifest, or a participation outcome, and no play rate below was measured
— the rates are arguments, chosen by the caller to be obviously fictional.

## Why the outcomes are constructed rather than sampled

A Bernoulli draw gives a cohort whose calibration is *approximately* the intended
one, so a test asserting on it has to allow sampling slack — and slack is exactly
where a detector that is subtly wrong hides. Every cell here instead carries an
exact integer play count, so calibration-in-the-large comes out as a closed-form
identity and a test can assert it to floating-point tolerance rather than to a
tolerance chosen to make the test pass.

That matters most for `pooled_band_cohort` and `status_cohort_with_informative_error`,
which exist to reproduce a specific piece of arithmetic about
`docs/models/injury-status-conversion-preregistration.md` §8 rather than to look
roughly right.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from hoops_gm.availability.calibration import CalibrationObservation


@dataclass(frozen=True)
class SyntheticCell:
    """A group of identical-prediction observations with an exact play count."""

    label: str
    observations: int
    plays: int
    predicted: float
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.observations < 1:
            raise ValueError(f"cell {self.label!r} needs at least one observation")
        if not 0 <= self.plays <= self.observations:
            raise ValueError(f"cell {self.label!r} plays {self.plays} outside its population")

    @property
    def observed_rate(self) -> float:
        return self.plays / self.observations


def materialise(cells: Sequence[SyntheticCell]) -> list[CalibrationObservation]:
    """Expand cells into individually-identified observations."""

    rows: list[CalibrationObservation] = []
    for cell in cells:
        for index in range(cell.observations):
            rows.append(
                CalibrationObservation(
                    observation_id=f"{cell.label}#{index:05d}",
                    predicted=cell.predicted,
                    played=index < cell.plays,
                    labels=dict(cell.labels),
                )
            )
    return rows


def exact_plays(observations: int, rate: float) -> int:
    """Return the play count nearest to `observations * rate`.

    Half-up rather than Python's banker's rounding, so the mapping from a
    requested rate to a count is the one a reader expects and does not depend on
    the parity of the product.
    """

    if not 0.0 <= rate <= 1.0:
        raise ValueError(f"rate must lie in [0, 1], got {rate!r}")
    return min(observations, math.floor(observations * rate + 0.5))


def _cells_from_rates(
    counts: Mapping[str, int],
    rates: Mapping[str, float],
    *,
    label_key: str,
) -> list[SyntheticCell]:
    missing = set(counts) - set(rates)
    if missing:
        raise ValueError(f"no fictional rate supplied for {sorted(missing)}")
    return [
        SyntheticCell(
            label=group,
            observations=counts[group],
            plays=exact_plays(counts[group], rates[group]),
            predicted=0.0,  # replaced by every caller below
            labels={label_key: group},
        )
        for group in sorted(counts)
    ]


def perfectly_calibrated_cohort(
    counts: Mapping[str, int],
    rates: Mapping[str, float],
    *,
    label_key: str = "group",
) -> list[CalibrationObservation]:
    """Each group is predicted at exactly its own realised rate.

    Calibration-in-the-large is exactly zero, every bin gap is exactly zero, and
    every emitted probability sits at the centre of its own Wilson interval. This
    is the cohort a detector must **not** fire on.
    """

    return materialise(
        [
            SyntheticCell(
                label=cell.label,
                observations=cell.observations,
                plays=cell.plays,
                predicted=cell.observed_rate,
                labels=cell.labels,
            )
            for cell in _cells_from_rates(counts, rates, label_key=label_key)
        ]
    )


def sharpened_cohort(
    counts: Mapping[str, int],
    rates: Mapping[str, float],
    *,
    factor: float,
    label_key: str = "group",
) -> list[CalibrationObservation]:
    """Predictions pushed away from (`factor` > 1) or toward (< 1) one half.

    `factor` > 1 is the overconfident model this project's rules care most about:
    it can carry a better hit rate while being useless for a start/sit decision.
    `factor` < 1 is the underconfident mirror, which is safer but still wrong and
    must still be detected.
    """

    if factor <= 0:
        raise ValueError("sharpening factor must be positive")
    return materialise(
        [
            SyntheticCell(
                label=cell.label,
                observations=cell.observations,
                plays=cell.plays,
                predicted=min(1.0, max(0.0, 0.5 + factor * (cell.observed_rate - 0.5))),
                labels=cell.labels,
            )
            for cell in _cells_from_rates(counts, rates, label_key=label_key)
        ]
    )


def uniformly_biased_cohort(
    counts: Mapping[str, int],
    rates: Mapping[str, float],
    *,
    bias: float,
    label_key: str = "group",
) -> list[CalibrationObservation]:
    """Every prediction shifted by the same signed amount.

    Calibration-in-the-large is exactly `bias`, which makes it the cleanest test
    of the CITL estimator's sign convention: a positive bias over-predicts play.
    """

    cells = _cells_from_rates(counts, rates, label_key=label_key)
    shifted = [cell.observed_rate + bias for cell in cells]
    if any(value < 0.0 or value > 1.0 for value in shifted):
        raise ValueError(
            "bias pushes a prediction outside [0, 1]; the CITL identity would no "
            "longer hold and the cohort would silently stop testing what it claims"
        )
    return materialise(
        [
            SyntheticCell(
                label=cell.label,
                observations=cell.observations,
                plays=cell.plays,
                predicted=value,
                labels=cell.labels,
            )
            for cell, value in zip(cells, shifted, strict=True)
        ]
    )


def status_cohort_with_informative_error(
    *,
    counts_by_status: Mapping[str, int],
    fictional_rate_by_status: Mapping[str, float],
    informative_statuses: frozenset[str],
    informative_error: float,
) -> list[CalibrationObservation]:
    """Exactly right on the near-deterministic statuses, wrong by delta on the rest.

    This is the cohort shape behind the finding that motivated preregistration
    v3: with the informative statuses a small share of the holdout, a pooled
    calibration-in-the-large error is diluted by that share, so

        pooled CITL = informative_share x delta

    exactly, while the restricted CITL on the informative rows is delta itself.
    The identity is exact by construction and independent of the fictional rates,
    which is the actual content of the claim — it is a statement about
    denominators, not about how often anybody plays.
    """

    unknown = informative_statuses - set(counts_by_status)
    if unknown:
        raise ValueError(f"informative statuses absent from counts: {sorted(unknown)}")
    cells = _cells_from_rates(counts_by_status, fictional_rate_by_status, label_key="status")
    built: list[SyntheticCell] = []
    for cell in cells:
        error = informative_error if cell.label in informative_statuses else 0.0
        predicted = cell.observed_rate + error
        if not 0.0 <= predicted <= 1.0:
            raise ValueError(
                f"status {cell.label!r}: rate {cell.observed_rate:.4f} plus error "
                f"{error:+.4f} leaves [0, 1]. Clipping here would quietly break the "
                "CITL identity this cohort exists to demonstrate, so it refuses instead."
            )
        built.append(
            SyntheticCell(
                label=cell.label,
                observations=cell.observations,
                plays=cell.plays,
                predicted=predicted,
                labels={
                    "status": cell.label,
                    "informative": "yes" if cell.label in informative_statuses else "no",
                },
            )
        )
    return materialise(built)


def pooled_band_cohort(
    *,
    counts_by_status: Mapping[str, int],
    fictional_rate_by_status: Mapping[str, float],
    band_by_status: Mapping[str, str],
    band_probability_offset: float = 0.0,
) -> list[CalibrationObservation]:
    """A band model emitting each band's own pooled rate — right in aggregate.

    Each band's emitted probability is that band's realised play rate over its
    whole population, **displaced by `band_probability_offset`**.

    At offset zero every bin gap is exactly zero under
    one-row-per-distinct-emitted-probability binning. **Those zeros are
    definitional, not measured** — a model that emits each bin's own realised rate
    on the evaluation set has zero gap by construction, and an independent review
    was right to say that reporting them as a result invites reading a
    construction as a measurement. The offset exists so the interesting claim can
    be driven without that crutch: a real fit takes its band rate from the
    development partition, so its held-out band rate is displaced, and the
    question is how far it can drift before a pooled condition notices.

    What survives the offset is the part that is a theorem rather than a
    construction. Distinct-emitted-probability binning partitions rows **by
    predicted value**; statuses sharing a band share a predicted value; so no
    statistic computed on that partition can separate them, at any offset and at
    any rates. Where a band pools a large status with a small one, the small one
    can be arbitrarily miscalibrated and only subgroup restriction sees it.
    """

    missing = set(counts_by_status) - set(band_by_status)
    if missing:
        raise ValueError(f"no band assigned for {sorted(missing)}")
    cells = _cells_from_rates(counts_by_status, fictional_rate_by_status, label_key="status")
    band_observations: dict[str, int] = {}
    band_plays: dict[str, int] = {}
    for cell in cells:
        band = band_by_status[cell.label]
        band_observations[band] = band_observations.get(band, 0) + cell.observations
        band_plays[band] = band_plays.get(band, 0) + cell.plays
    emitted: dict[str, float] = {}
    for band, observations in band_observations.items():
        moved = band_plays[band] / observations + band_probability_offset
        if not 0.0 <= moved <= 1.0:
            raise ValueError(
                f"band {band!r} offset to {moved!r}, outside [0, 1]; "
                "refused rather than clipped, because a clipped band rate would "
                "quietly stop being the quantity the caller asked for"
            )
        emitted[band] = moved
    return materialise(
        [
            SyntheticCell(
                label=cell.label,
                observations=cell.observations,
                plays=cell.plays,
                predicted=emitted[band_by_status[cell.label]],
                labels={"status": cell.label, "band": band_by_status[cell.label]},
            )
            for cell in cells
        ]
    )


def reversed_band_cohort(
    counts: Mapping[str, int],
    predicted_by_group: Mapping[str, float],
    rates: Mapping[str, float],
    *,
    label_key: str = "group",
) -> list[CalibrationObservation]:
    """Predictions rising across groups while realised rates fall, or the converse.

    Feeds the monotonic-reversal detector, v2 §8 condition 7. A reversal is worse
    than imprecision: the ordering itself is wrong, so acting on the model is
    worse than acting on its reverse.
    """

    return materialise(
        [
            SyntheticCell(
                label=cell.label,
                observations=cell.observations,
                plays=cell.plays,
                predicted=predicted_by_group[cell.label],
                labels=cell.labels,
            )
            for cell in _cells_from_rates(counts, rates, label_key=label_key)
        ]
    )
