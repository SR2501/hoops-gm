"""ORM models.

Phase 1 implements four of the entity groups in the plan's data model:
Identity, Stats, League and Schedule. The Availability, Contingent value,
Projections, Valuation, Draft, Decisions and Bridge groups belong to later
phases and their owning agents, and are deliberately absent.

Import every model here. Alembic autogenerate and ``Base.metadata`` both see
only what has been imported, so a model missing from this list is a table that
silently never gets a migration.
"""

from hoops_gm.db.base import Base
from hoops_gm.db.models.enums import (
    CategoryKind,
    CategoryOutcome,
    Conference,
    DraftType,
    ExternalSource,
    GameStatus,
    MatchMethod,
    MatchupStatus,
    PlayerStatus,
    RosterStatus,
    ScoringType,
    SeasonType,
    StatScope,
    TransactionType,
)
from hoops_gm.db.models.identity import NbaTeam, Player, PlayerExternalId
from hoops_gm.db.models.league import (
    FantasyTeam,
    League,
    LeagueScoringCategory,
    LeagueScoringProfile,
    Matchup,
    MatchupCategoryResult,
    RosterEntry,
    RosterSlot,
    ScoringPeriod,
    Transaction,
)
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog, PlayerSeasonStat

__all__ = [
    "Base",
    "CategoryKind",
    "CategoryOutcome",
    "Conference",
    "DraftType",
    "ExternalSource",
    "FantasyTeam",
    "GameStatus",
    "League",
    "LeagueScoringCategory",
    "LeagueScoringProfile",
    "MatchMethod",
    "Matchup",
    "MatchupCategoryResult",
    "MatchupStatus",
    "NbaGame",
    "NbaTeam",
    "Player",
    "PlayerExternalId",
    "PlayerGameLog",
    "PlayerSeasonStat",
    "PlayerStatus",
    "RosterEntry",
    "RosterSlot",
    "RosterStatus",
    "ScoringPeriod",
    "ScoringType",
    "SeasonType",
    "StatScope",
    "TeamScheduleEntry",
    "Transaction",
    "TransactionType",
]
