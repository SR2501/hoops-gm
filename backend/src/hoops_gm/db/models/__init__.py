"""ORM models.

Phase 1 implemented four of the entity groups in the plan's data model:
Identity, Stats, League and Schedule. Phase 2 adds the *observed* part of
Availability — ``player_participation``, the ledger of who took part in what.
Phase 3/4 add schedule context (``opponent_context``, ``off_night_slates``).
Phase 5 adds the ``csv-importer`` slice of Projections — ``projection_sources``,
``projection_profile_versions``, ``projection_imports``, ``projections`` (per-game rates) and
``source_games_played_assumptions``. Phase 8 adds the *market* layer —
``auction_value_sources``, ``auction_value_source_inputs``,
``auction_value_imports`` and ``published_auction_values`` — which stores what
other people published, at ``data_layer = 'market'``, and derives nothing.
Blending, the baseline model and
``expected-games`` fusion are not implemented here; they consume this table
and belong to their own backlog items. Phase 8 adds the *recorded* half of
Draft — ``drafts``, ``draft_participants`` and the append-only ``draft_events``
log, which hold what a person observed happening in a draft. The modelled parts
of Availability (``p(play)``, reliability, shutdown risk) plus Contingent value,
Valuation and the decision-bearing half of Draft (recommendations, dollar
values, inflation) belong to later phases and their owning agents. Bridge
payload capture is implemented here as a raw transport boundary; it
deliberately does not parse Fantrax data.

Import every model here. Alembic autogenerate and ``Base.metadata`` both see
only what has been imported, so a model missing from this list is a table that
silently never gets a migration.

Importing this module also **validates ADR-008 layer purity** — see the call to
``validate_layers`` at the foot of the file. That placement is deliberate: this
is the one point at which ``Base.metadata`` is complete, so it is the earliest
moment a backwards flow can be refused, and refusing it here makes an unlayered
table or a market-into-projections foreign key an ``ImportError`` rather than a
test somebody might not have run.
"""

from hoops_gm.db.base import Base
from hoops_gm.db.layers import DataLayer, LayerViolation, validate_layers
from hoops_gm.db.models.availability import (
    AbsenceSplit,
    AbsenceSplitComputationRun,
    PlayerParticipation,
)
from hoops_gm.db.models.bridge import BridgePayload
from hoops_gm.db.models.deadline_calendar import LeagueDeadlineCalendar
from hoops_gm.db.models.draft import Draft, DraftEvent, DraftParticipant
from hoops_gm.db.models.enums import (
    AuctionValueDerivation,
    AuctionValueInputKind,
    AuctionValueKind,
    BasisEvidence,
    CategoryKind,
    CategoryOutcome,
    Conference,
    DnpReason,
    DraftEventType,
    DraftStatus,
    DraftToolUsage,
    DraftType,
    ExternalSource,
    FieldEvidence,
    GameStatus,
    InjuryReportStatus,
    MatchMethod,
    MatchupStatus,
    ParticipationOutcome,
    PlayerStatus,
    RefreshArtifactType,
    RosterStatus,
    ScoringType,
    SeasonType,
    StatScope,
    TransactionType,
)
from hoops_gm.db.models.identity import NbaTeam, Player, PlayerExternalId
from hoops_gm.db.models.injury_report import InjuryReportEntry
from hoops_gm.db.models.layers import DataLayerFlow, DataLayerRegistry
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
from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot
from hoops_gm.db.models.lineage import RefreshRun
from hoops_gm.db.models.market import (
    AuctionValueImport,
    AuctionValueSource,
    AuctionValueSourceInput,
    PublishedAuctionValue,
)
from hoops_gm.db.models.projections import (
    Projection,
    ProjectionImport,
    ProjectionProfileVersion,
    ProjectionSource,
    SourceGamesPlayedAssumption,
)
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.schedule_context import OffNightSlate, OpponentContext
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog, PlayerSeasonStat

__all__ = [
    "AbsenceSplit",
    "AbsenceSplitComputationRun",
    "AuctionValueDerivation",
    "AuctionValueImport",
    "AuctionValueInputKind",
    "AuctionValueKind",
    "AuctionValueSource",
    "AuctionValueSourceInput",
    "Base",
    "BasisEvidence",
    "BridgePayload",
    "CategoryKind",
    "CategoryOutcome",
    "Conference",
    "DataLayer",
    "DataLayerFlow",
    "DataLayerRegistry",
    "DnpReason",
    "Draft",
    "DraftEvent",
    "DraftEventType",
    "DraftParticipant",
    "DraftStatus",
    "DraftToolUsage",
    "DraftType",
    "ExternalSource",
    "FantasyTeam",
    "FieldEvidence",
    "GameStatus",
    "InjuryReportEntry",
    "InjuryReportStatus",
    "LayerViolation",
    "League",
    "LeagueDeadlineCalendar",
    "LeagueScoringCategory",
    "LeagueScoringProfile",
    "LeagueSettingsSnapshot",
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
    "Projection",
    "ProjectionImport",
    "ProjectionProfileVersion",
    "ProjectionSource",
    "PublishedAuctionValue",
    "RefreshArtifactType",
    "RefreshRun",
    "RosterEntry",
    "RosterSlot",
    "RosterStatus",
    "ScoringPeriod",
    "ScoringType",
    "SeasonType",
    "SourceGamesPlayedAssumption",
    "StatScope",
    "TeamScheduleEntry",
    "Transaction",
    "TransactionType",
]

# ADR-008, enforced at the one moment ``Base.metadata`` is complete. A table
# with no layer, or a foreign key from a later layer into an earlier one, is an
# ImportError here rather than a finding in a test run somebody skipped —
# "inexpressible rather than merely documented" is the whole instruction.
validate_layers(Base.metadata)
