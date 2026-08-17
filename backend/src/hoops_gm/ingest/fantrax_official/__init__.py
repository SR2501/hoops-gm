"""Fantrax official ``/fxea/general/`` adapter.

Free, unauthenticated for the two endpoints that matter most, and the source of
the player-id map, ADP, league settings and draft picks.

Its most important property is a negative one: **it exposes no NBA.com player
identifier**. ``statsIncId``, ``rotowireId`` and ``sportRadarId`` are all it
offers, and NBA.com publishes none of them. That is risk R23, and it is why the
crosswalk in :mod:`hoops_gm.identity` cannot anchor on a shared key.
"""

from hoops_gm.ingest.fantrax_official.client import (
    BASE_URL,
    DEFAULT_MAX_AGE,
    DEFAULT_MIN_INTERVAL_SECONDS,
    FantraxOfficialClient,
)
from hoops_gm.ingest.fantrax_official.models import (
    FantraxAdpEntry,
    FantraxDraftPick,
    FantraxLeagueInfo,
    FantraxLeagueTeam,
    FantraxPlayer,
    FantraxPlayerIds,
    FantraxScoringCategory,
    FantraxTeamEntity,
)
from hoops_gm.ingest.fantrax_official.parsers import (
    SOURCE,
    parse_adp,
    parse_draft_picks,
    parse_league_info,
    parse_player_ids,
    raise_for_error_envelope,
)

__all__ = [
    "BASE_URL",
    "DEFAULT_MAX_AGE",
    "DEFAULT_MIN_INTERVAL_SECONDS",
    "SOURCE",
    "FantraxAdpEntry",
    "FantraxDraftPick",
    "FantraxLeagueInfo",
    "FantraxLeagueTeam",
    "FantraxOfficialClient",
    "FantraxPlayer",
    "FantraxPlayerIds",
    "FantraxScoringCategory",
    "FantraxTeamEntity",
    "parse_adp",
    "parse_draft_picks",
    "parse_league_info",
    "parse_player_ids",
    "raise_for_error_envelope",
]
