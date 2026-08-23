"""Availability and teammate-absence evidence.

``hoops_gm.availability.coverage`` is deliberately **not** re-exported here. It
is an operator tool with a ``main()``, and importing it into the package
namespace makes ``python -m hoops_gm.availability.coverage`` emit a runpy
double-import ``RuntimeWarning`` on every run. Same reason
``hoops_gm.ingest.__init__`` omits ``backfill``. Import it by full path.
"""

from hoops_gm.availability.absence_splits import (
    ABSENCE_SPLIT_EVIDENCE_VERSION,
    DIRECT_EVIDENCE_METHOD,
    AbsenceSplitInputError,
    AbsenceSplitRun,
    compute_absence_splits,
    latest_absence_splits,
)
from hoops_gm.availability.reliability import (
    OBSERVED_COVERAGE_STATUS,
    RELIABILITY_DERIVATION_KEY,
    RELIABILITY_SOURCE_KEY,
    AvailabilityEvidence,
    CategoryConsistency,
    DistributionSummary,
    MinutesConsistency,
    MonthlyRateEvidence,
    PlayerReliabilityScorecard,
    ProductionConsistency,
    RateEvidence,
    RatioBaseline,
    ReliabilityCohortClaim,
    ReliabilityConfig,
    ReliabilityInputError,
    ReliabilityLineage,
    ReliabilityRun,
    StaleReliabilityCohortError,
    compute_reliability_scorecards,
    publish_reliability_cohorts,
)

__all__ = [
    "ABSENCE_SPLIT_EVIDENCE_VERSION",
    "DIRECT_EVIDENCE_METHOD",
    "OBSERVED_COVERAGE_STATUS",
    "RELIABILITY_DERIVATION_KEY",
    "RELIABILITY_SOURCE_KEY",
    "AbsenceSplitInputError",
    "AbsenceSplitRun",
    "AvailabilityEvidence",
    "CategoryConsistency",
    "DistributionSummary",
    "MinutesConsistency",
    "MonthlyRateEvidence",
    "PlayerReliabilityScorecard",
    "ProductionConsistency",
    "RateEvidence",
    "RatioBaseline",
    "ReliabilityCohortClaim",
    "ReliabilityConfig",
    "ReliabilityInputError",
    "ReliabilityLineage",
    "ReliabilityRun",
    "StaleReliabilityCohortError",
    "compute_absence_splits",
    "compute_reliability_scorecards",
    "latest_absence_splits",
    "publish_reliability_cohorts",
]
