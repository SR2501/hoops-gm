"""ORM models.

Phase 1 implemented four of the entity groups in the plan's data model:
Identity, Stats, League and Schedule. Phase 2 adds the *observed* part of
Availability — ``player_participation``, the ledger of who took part in what.
The modelled parts of Availability (``p(play)``, reliability, shutdown risk)
plus Contingent value, Projections, Valuation, Draft and Decisions belong to
later phases and their owning agents. Bridge payload capture is implemented
here as a raw transport boundary; it deliberately does not parse Fantrax data.

Import every model here. Alembic autogenerate and ``Base.metadata`` both see
only what has been imported, so a model missing from this list is a table that
silently never gets a migration.
"""

from hoops_gm.db.base import Base
from hoops_gm.db.models.availability import PlayerParticipation
from hoops_gm.db.models.bridge import BridgePayload
from hoops_gm.db.models.enums import (
    CategoryKind,
    CategoryOutcome,
    Conference,
    DnpReason,
    DraftType,
    ExternalSource,
    FieldEvidence,
    GameStatus,
    MatchMethod,
    MatchupStatus,
    ParticipationOutcome,
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
from hoops_gm.db.models.schedule_context import OffNightSlate, OpponentContext
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog, PlayerSeasonStat

__all__ = [
    "Base",
    "BridgePayload",
    "CategoryKind",
    "CategoryOutcome",
    "Conference",
    "DnpReason",
    "DraftType",
    "ExternalSource",
    "FantasyTeam",
    "FieldEvidence",
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
    "OffNightSlate",
    "OpponentContext",
    "ParticipationOutcome",
    "Player",
    "PlayerExternalId",
    "PlayerGameLog",
    "PlayerParticipation",
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
