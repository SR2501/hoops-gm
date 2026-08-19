"""League deadline calendars: the versioned join of settings lineage and schedule lineage."""

from hoops_gm.calendar.deadline_calendar import (
    SCHEMA_VERSION,
    DeadlineCalendarDerivation,
    DeadlineCalendarLineageError,
    DeadlineCalendarStaleActivationError,
    activate_deadline_calendar,
    current_deadline_calendar,
    derive_deadline_calendar,
    scoring_period_windows,
)
from hoops_gm.calendar.scoring_periods import (
    PROJECTION_SCHEMA_VERSION,
    ProjectedScoringPeriod,
    ScoringPeriodProjectionError,
    ScoringPeriodProjectionLineage,
    ScoringPeriodProjectionResult,
    ScoringPeriodReplacementConflictError,
    StaleScoringPeriodProjectionError,
    project_scoring_periods,
    require_current_scoring_period_projection,
    scoring_period_artifact_key,
)

__all__ = [
    "PROJECTION_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "DeadlineCalendarDerivation",
    "DeadlineCalendarLineageError",
    "DeadlineCalendarStaleActivationError",
    "ProjectedScoringPeriod",
    "ScoringPeriodProjectionError",
    "ScoringPeriodProjectionLineage",
    "ScoringPeriodProjectionResult",
    "ScoringPeriodReplacementConflictError",
    "StaleScoringPeriodProjectionError",
    "activate_deadline_calendar",
    "current_deadline_calendar",
    "derive_deadline_calendar",
    "project_scoring_periods",
    "require_current_scoring_period_projection",
    "scoring_period_artifact_key",
    "scoring_period_windows",
]
