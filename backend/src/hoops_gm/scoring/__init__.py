"""Scoring: deriving and activating a league's scoring profile from its rules.

See ``profiles.py`` for the module docstring covering scope, ADR-002/ADR-008
boundaries, and the fail-closed/versioning discipline.
"""

from __future__ import annotations

from hoops_gm.scoring.profiles import (
    NINE_CATEGORY_DEFINITIONS,
    CategoryDefinition,
    NonUnitCategoryWeightError,
    SourceCategory,
    UnsupportedCategoryError,
    UnsupportedScoringFormatError,
    activate_scoring_profile_version,
    build_scoring_profile,
    current_scoring_profile,
    map_source_categories,
)

__all__ = [
    "NINE_CATEGORY_DEFINITIONS",
    "CategoryDefinition",
    "NonUnitCategoryWeightError",
    "SourceCategory",
    "UnsupportedCategoryError",
    "UnsupportedScoringFormatError",
    "activate_scoring_profile_version",
    "build_scoring_profile",
    "current_scoring_profile",
    "map_source_categories",
]
