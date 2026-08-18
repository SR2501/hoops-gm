"""Versioned schedule context derived from schedule and historical observations."""

from hoops_gm.schedule_context.blowout import (
    BlowoutBacktest,
    BlowoutModel,
    GameResult,
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
from hoops_gm.schedule_context.service import (
    ContextCohortClaim,
    ContextWriteCounts,
    StaleContextCohortError,
    compute_schedule_context,
    context_source_version,
    publish_schedule_context_cohorts,
)

__all__ = [
    "BlowoutBacktest",
    "BlowoutModel",
    "ContextCohortClaim",
    "ContextGame",
    "ContextWriteCounts",
    "GameResult",
    "OffNightFact",
    "OpponentProfile",
    "ScheduleContextConfig",
    "StaleContextCohortError",
    "TeamGameStats",
    "build_off_night_facts",
    "build_opponent_profile",
    "compute_schedule_context",
    "context_source_version",
    "evaluate_blowout_model",
    "fit_blowout_model",
    "publish_schedule_context_cohorts",
]
