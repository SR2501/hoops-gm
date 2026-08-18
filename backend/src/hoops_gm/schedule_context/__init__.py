"""Versioned schedule context derived from schedule and historical observations."""

from hoops_gm.schedule_context.blowout import (
    BlowoutBacktest,
    BlowoutModel,
    GameResult,
    blowout_model_version,
    evaluate_blowout_model,
    fit_blowout_model,
)
from hoops_gm.schedule_context.features import (
    ContextGame,
    OffNightFact,
    OpponentProfile,
    ScheduleContextConfig,
    TeamGameStats,
    build_off_night_facts,
    build_opponent_profile,
)
from hoops_gm.schedule_context.release import (
    RELEASED_BLOWOUT_MODEL_VERSION,
    BlowoutRelease,
    UnreleasedBlowoutModelError,
    load_blowout_release,
)
from hoops_gm.schedule_context.service import (
    ContextCohortClaim,
    ContextWriteCounts,
    InsufficientContextCoverageError,
    StaleContextCohortError,
    compute_schedule_context,
    context_source_version,
    publish_schedule_context_cohorts,
)

__all__ = [
    "RELEASED_BLOWOUT_MODEL_VERSION",
    "BlowoutBacktest",
    "BlowoutModel",
    "BlowoutRelease",
    "ContextCohortClaim",
    "ContextGame",
    "ContextWriteCounts",
    "GameResult",
    "InsufficientContextCoverageError",
    "OffNightFact",
    "OpponentProfile",
    "ScheduleContextConfig",
    "StaleContextCohortError",
    "TeamGameStats",
    "UnreleasedBlowoutModelError",
    "blowout_model_version",
    "build_off_night_facts",
    "build_opponent_profile",
    "compute_schedule_context",
    "context_source_version",
    "evaluate_blowout_model",
    "fit_blowout_model",
    "load_blowout_release",
    "publish_schedule_context_cohorts",
]
