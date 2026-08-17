"""Cross-source player identity — the highest-risk foundation in the project.

Risk R7. Fantrax identifiers, NBA identifiers and projection-CSV name strings
all disagree, and — verified live on 2026-08-17 — **no two of them share a
key**. Every match is inferred. A silent mismatch corrupts every downstream
number and looks like a modelling bug for weeks, so this package ships with its
own test suite, per-field evidence for every decision, and a report for the
tail no automated rule should be trusted with.
"""

from hoops_gm.identity.evidence import (
    FieldEvidence,
    MatchEvidence,
    compare_optional,
    compare_positions,
    compare_suffix,
    score_evidence,
)
from hoops_gm.identity.names import (
    NON_PLAYER_POSITIONS,
    NormalizedName,
    normalize_key,
    normalize_name,
    normalize_positions,
    normalize_team_abbreviation,
    strip_accents,
)
from hoops_gm.identity.report import partition, render_summary, to_csv
from hoops_gm.identity.resolver import (
    AMBIGUITY_MARGIN,
    AUTO_ACCEPT_CONFIDENCE,
    REVIEW_FLOOR_CONFIDENCE,
    Candidate,
    IdentityResolver,
    Resolution,
    ResolutionReport,
    ResolvableRecord,
)

__all__ = [
    "AMBIGUITY_MARGIN",
    "AUTO_ACCEPT_CONFIDENCE",
    "NON_PLAYER_POSITIONS",
    "REVIEW_FLOOR_CONFIDENCE",
    "Candidate",
    "FieldEvidence",
    "IdentityResolver",
    "MatchEvidence",
    "NormalizedName",
    "Resolution",
    "ResolutionReport",
    "ResolvableRecord",
    "compare_optional",
    "compare_positions",
    "compare_suffix",
    "normalize_key",
    "normalize_name",
    "normalize_positions",
    "normalize_team_abbreviation",
    "partition",
    "render_summary",
    "score_evidence",
    "strip_accents",
    "to_csv",
]
