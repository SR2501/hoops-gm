"""``nba_api`` adapter — historical stats, schedule, inactives and DNP reasons.

Use the library, never a hand-rolled HTTP client (risk R27), and use V3
endpoints: ``PlayByPlayV2`` and ``ScoreboardV2`` are deprecated, and
``BoxScoreSummaryV2``'s inactive list is actively wrong for recent seasons.
See :mod:`hoops_gm.ingest.nba.parsers` for the evidence.
"""

from hoops_gm.ingest.nba.client import (
    COMPLETED_GAME_MAX_AGE,
    DEFAULT_MIN_INTERVAL_SECONDS,
    NbaStatsClient,
)
from hoops_gm.ingest.nba.models import (
    DnpReason,
    GameParticipation,
    NbaGameRecord,
    NbaPlayerRecord,
    NbaTeamRecord,
    ParticipationOutcome,
    PlayerBoxScoreRecord,
    PlayerParticipationRecord,
)
from hoops_gm.ingest.nba.parsers import (
    SOURCE,
    combine_game_participation,
    parse_box_score_summary_v3,
    parse_box_score_traditional_v3,
    parse_common_all_players,
    parse_league_game_finder,
    parse_minutes_to_seconds,
    parse_participation_comment,
    parse_player_game_logs,
    parse_teams,
)
from hoops_gm.ingest.nba.schedule import (
    ScheduledGameCount,
    ScheduleGameRecord,
    ScheduleParseResult,
    parse_schedule,
    scheduled_game_counts,
)

__all__ = [
    "COMPLETED_GAME_MAX_AGE",
    "DEFAULT_MIN_INTERVAL_SECONDS",
    "SOURCE",
    "DnpReason",
    "GameParticipation",
    "NbaGameRecord",
    "NbaPlayerRecord",
    "NbaStatsClient",
    "NbaTeamRecord",
    "ParticipationOutcome",
    "PlayerBoxScoreRecord",
    "PlayerParticipationRecord",
    "ScheduleGameRecord",
    "ScheduleParseResult",
    "ScheduledGameCount",
    "combine_game_participation",
    "parse_box_score_summary_v3",
    "parse_box_score_traditional_v3",
    "parse_common_all_players",
    "parse_league_game_finder",
    "parse_minutes_to_seconds",
    "parse_participation_comment",
    "parse_player_game_logs",
    "parse_schedule",
    "parse_teams",
    "scheduled_game_counts",
]
