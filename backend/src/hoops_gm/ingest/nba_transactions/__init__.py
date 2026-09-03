"""Official NBA and G League transaction archive adapters."""

from hoops_gm.ingest.nba_transactions.client import (
    DEFAULT_MAX_AGE,
    DEFAULT_MIN_INTERVAL_SECONDS,
    G_LEAGUE_TRANSACTIONS_URL,
    NBA_PLAYER_MOVEMENT_URL,
    NbaOfficialTransactionsClient,
)
from hoops_gm.ingest.nba_transactions.models import (
    GLeagueTransactionRecord,
    NbaPlayerMovementRecord,
)
from hoops_gm.ingest.nba_transactions.parsers import (
    G_LEAGUE_TRANSACTION_FIELDS,
    G_LEAGUE_TRANSACTIONS_ENDPOINT,
    G_LEAGUE_TYPE_DESCRIPTIONS,
    NBA_PLAYER_MOVEMENT_COLUMNS,
    NBA_PLAYER_MOVEMENT_ENDPOINT,
    NBA_PLAYER_MOVEMENT_FIELDS,
    NBA_PLAYER_MOVEMENT_TYPES,
    SOURCE,
    parse_g_league_transactions,
    parse_nba_player_movements,
)

__all__ = [
    "DEFAULT_MAX_AGE",
    "DEFAULT_MIN_INTERVAL_SECONDS",
    "G_LEAGUE_TRANSACTIONS_ENDPOINT",
    "G_LEAGUE_TRANSACTIONS_URL",
    "G_LEAGUE_TRANSACTION_FIELDS",
    "G_LEAGUE_TYPE_DESCRIPTIONS",
    "NBA_PLAYER_MOVEMENT_COLUMNS",
    "NBA_PLAYER_MOVEMENT_ENDPOINT",
    "NBA_PLAYER_MOVEMENT_FIELDS",
    "NBA_PLAYER_MOVEMENT_TYPES",
    "NBA_PLAYER_MOVEMENT_URL",
    "SOURCE",
    "GLeagueTransactionRecord",
    "NbaOfficialTransactionsClient",
    "NbaPlayerMovementRecord",
    "parse_g_league_transactions",
    "parse_nba_player_movements",
]
