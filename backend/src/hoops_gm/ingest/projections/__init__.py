"""Generic projection CSV importer — ``csv-importer``, Phase 5.

No projection source in this project's plan has an API (plan.md): FantasyPros
is a free CSV, Hashtag Basketball is Patreon-gated, Basketball Monster is a
paid CSV export, DARKO is historical CSV only. A CSV drop is the entire
integration surface, so this package is the reusable boundary everything else
in Projections builds on — column-mapping profiles, validation, identity
resolution and versioned, idempotent writes — kept deliberately separate from
blending, the baseline model and ``expected-games`` fusion, which are later
backlog items and consume this table rather than extend it.

See ``hoops_gm.db.models.projections`` for the schema and ADR-002 for why
per-game production and a source's embedded games-played assumption are two
tables, never one.
"""

from hoops_gm.ingest.projections.importer import (
    ProjectionEncodingError,
    ProjectionImportOutcome,
    ProjectionVerificationError,
    build_player_targets,
    get_or_create_projection_source,
    import_projection_csv,
    resolve_projection_identities,
)
from hoops_gm.ingest.projections.models import (
    ProjectionParseResult,
    ProjectionSourceRow,
    RowIssue,
)
from hoops_gm.ingest.projections.parser import ProjectionProfileError, parse_projection_csv
from hoops_gm.ingest.projections.profiles import (
    BASKETBALL_MONSTER_2026_27_HEADERS,
    BASKETBALL_MONSTER_PROFILE,
    CANONICAL_STAT_FIELDS,
    FANTASYPROS_PROFILE,
    HASHTAG_2026_27_HEADERS,
    HASHTAG_PROFILE,
    MANUAL_PROFILE,
    PROFILES_BY_SOURCE,
    ColumnProfile,
    CompositeShootingColumn,
    DerivedStatColumn,
    StatColumn,
    ValueShape,
)
from hoops_gm.ingest.projections.verification import (
    IMPORT_BLOCKING_CHECKS,
    BakedInAvailabilityReport,
    VerificationFinding,
    VerificationOutcome,
    VerificationReport,
    verify_no_baked_in_availability,
    verify_projection_batch,
    verify_scoring_identity,
    verify_value_shape,
)

__all__ = [
    "BASKETBALL_MONSTER_2026_27_HEADERS",
    "BASKETBALL_MONSTER_PROFILE",
    "CANONICAL_STAT_FIELDS",
    "FANTASYPROS_PROFILE",
    "HASHTAG_2026_27_HEADERS",
    "HASHTAG_PROFILE",
    "IMPORT_BLOCKING_CHECKS",
    "MANUAL_PROFILE",
    "PROFILES_BY_SOURCE",
    "BakedInAvailabilityReport",
    "ColumnProfile",
    "CompositeShootingColumn",
    "DerivedStatColumn",
    "ProjectionEncodingError",
    "ProjectionImportOutcome",
    "ProjectionParseResult",
    "ProjectionProfileError",
    "ProjectionSourceRow",
    "ProjectionVerificationError",
    "RowIssue",
    "StatColumn",
    "ValueShape",
    "VerificationFinding",
    "VerificationOutcome",
    "VerificationReport",
    "build_player_targets",
    "get_or_create_projection_source",
    "import_projection_csv",
    "parse_projection_csv",
    "resolve_projection_identities",
    "verify_no_baked_in_availability",
    "verify_projection_batch",
    "verify_scoring_identity",
    "verify_value_shape",
]
