"""Pure parsers for ``nba_api`` payloads.

``nba_api`` returns two entirely different envelope shapes and the difference
matters, because the V2 family is being retired underneath us:

* the older ``resultSets`` form — a list of ``{name, headers, rowSet}`` tables
  of positional rows, used by ``CommonAllPlayers``, ``LeagueGameFinder`` and
  ``PlayerGameLogs``;
* the V3 form — ordinary nested JSON objects with camelCase keys.

Positional rows are the dangerous one. ``row[7]`` is meaningless if a column is
inserted upstream, so every access here goes through the payload's own
``headers`` list and a missing header is a :class:`SourceContractError` rather
than an ``IndexError`` three frames away.

**Why the inactive list comes from V3 and never from V2.** Verified on
2026-08-17 by bisecting the 2025-26 season: ``BoxScoreSummaryV2`` returned 8
inactive players for 2025-10-21 and **zero rows for every single date after
it**, through to the end of the season, while ``BoxScoreSummaryV3`` returned
the correct lists for the same games. V2 is the endpoint most public examples
use. Had this adapter used it, the participation ledger would have contained no
inactives at all for the most recent season, with no error and no failing test
— a pillar of this project built on nothing. That is why
``parse_game_participation`` reads V3, and why the contract test asserts a
non-zero inactive count for a known mid-season game rather than merely
asserting the call succeeded.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from hoops_gm.ingest.errors import SourceContractError
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

SOURCE = "nba_stats"

#: The NBA publishes its schedule in Eastern time, and ``gameEt`` is Eastern
#: despite its ``Z`` suffix. A named zone rather than a fixed -5 offset,
#: because the season crosses a daylight saving boundary in March.
NBA_LOCAL_TIMEZONE = ZoneInfo("America/New_York")


# --------------------------------------------------------------------------
# resultSets helpers
# --------------------------------------------------------------------------


class ResultTable:
    """One ``{name, headers, rowSet}`` table, addressed by column name."""

    def __init__(
        self, name: str, headers: list[str], rows: list[list[Any]], *, endpoint: str
    ) -> None:
        self.name = name
        self.headers = headers
        self.rows = rows
        self.endpoint = endpoint
        self._index = {header: position for position, header in enumerate(headers)}

    def __len__(self) -> int:
        return len(self.rows)

    def require(self, *columns: str) -> None:
        """Fail loudly if a column this parser depends on has gone."""
        missing = [c for c in columns if c not in self._index]
        if missing:
            raise SourceContractError(
                f"result set {self.name!r} is missing columns {missing}; it has {self.headers}",
                source=SOURCE,
                endpoint=self.endpoint,
            )

    def get(self, row: list[Any], column: str, default: Any = None) -> Any:
        position = self._index.get(column)
        if position is None or position >= len(row):
            return default
        return row[position]

    def dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.headers, row, strict=False)) for row in self.rows]


def result_tables(payload: Any, *, endpoint: str) -> dict[str, ResultTable]:
    """Decompose a ``resultSets`` payload into named tables."""
    if not isinstance(payload, dict):
        raise SourceContractError(
            f"expected an object, got {type(payload).__name__}", source=SOURCE, endpoint=endpoint
        )
    sets = payload.get("resultSets")
    if sets is None:
        sets = payload.get("resultSet")
    if isinstance(sets, dict):
        sets = [sets]
    if not isinstance(sets, list) or not sets:
        raise SourceContractError(
            f"payload has no result sets; keys were {sorted(payload)}",
            source=SOURCE,
            endpoint=endpoint,
        )

    tables: dict[str, ResultTable] = {}
    for entry in sets:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or endpoint)
        headers = entry.get("headers")
        rows = entry.get("rowSet")
        if not isinstance(headers, list) or not isinstance(rows, list):
            raise SourceContractError(
                f"result set {name!r} has no headers/rowSet pair",
                source=SOURCE,
                endpoint=endpoint,
            )
        tables[name] = ResultTable(name, [str(h) for h in headers], rows, endpoint=endpoint)
    return tables


def require_table(tables: dict[str, ResultTable], name: str, *, endpoint: str) -> ResultTable:
    table = tables.get(name)
    if table is None:
        raise SourceContractError(
            f"expected a result set named {name!r}; got {sorted(tables)}",
            source=SOURCE,
            endpoint=endpoint,
        )
    return table


# --------------------------------------------------------------------------
# scalar coercion
# --------------------------------------------------------------------------

_CLOCK = re.compile(r"^(?P<minutes>\d+):(?P<seconds>\d{1,2})(?:\.\d+)?$")
_ISO_CLOCK = re.compile(r"^PT(?:(?P<minutes>\d+)M)?(?:(?P<seconds>[\d.]+)S)?$")


def parse_minutes_to_seconds(value: Any) -> int | None:
    """Convert every minutes representation this project has seen to seconds.

    Three forms are in play and they are not interchangeable:

    * ``"34:12"`` from the V3 box score and ``MIN_SEC`` in the game logs —
      exact;
    * ``34.2`` from ``PlayerGameLogs.MIN`` — a **rounded decimal**, which is
      why ``MIN_SEC`` is preferred wherever both exist;
    * ``"PT34M12.00S"`` from some live and V3 feeds.

    ``""`` and ``None`` return ``None``, meaning *did not play*, which is a
    different claim from zero seconds and must stay different.
    """
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return round(float(value) * 60)
    text = str(value).strip()
    if not text:
        return None
    match = _CLOCK.match(text)
    if match:
        return int(match["minutes"]) * 60 + int(match["seconds"])
    match = _ISO_CLOCK.match(text)
    if match:
        minutes = int(match["minutes"] or 0)
        seconds = float(match["seconds"] or 0.0)
        return minutes * 60 + round(seconds)
    try:
        return round(float(text) * 60)
    except ValueError:
        return None


def as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def as_date(value: Any, *, endpoint: str) -> date:
    """Parse the several date forms ``stats.nba.com`` mixes across endpoints."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value or "").strip()
    if not text:
        raise SourceContractError("empty game date", source=SOURCE, endpoint=endpoint)
    head = text.split("T", 1)[0]
    try:
        return date.fromisoformat(head)
    except ValueError as exc:
        raise SourceContractError(
            f"unparseable game date {value!r}", source=SOURCE, endpoint=endpoint
        ) from exc


def as_utc_datetime(value: Any) -> datetime | None:
    """Parse ``gameTimeUTC`` (``2024-12-01T20:30:00Z``) into an aware instant.

    Always aware. ``UTCDateTime`` rejects a naive datetime on purpose, because
    assuming UTC is exactly how a local wall-clock time silently becomes an
    instant several hours away — and this column feeds back-to-back detection.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# --------------------------------------------------------------------------
# static teams
# --------------------------------------------------------------------------


def parse_teams(payload: Any) -> list[NbaTeamRecord]:
    """Parse ``nba_api.stats.static.teams.get_teams()`` output."""
    endpoint = "static.teams"
    if not isinstance(payload, list) or not payload:
        raise SourceContractError(
            f"expected a non-empty list, got {type(payload).__name__}",
            source=SOURCE,
            endpoint=endpoint,
        )
    teams: list[NbaTeamRecord] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        identifier = as_int(entry.get("id"))
        abbreviation = entry.get("abbreviation")
        if identifier is None or not abbreviation:
            raise SourceContractError(
                f"team row lacks an id or abbreviation: {entry!r}",
                source=SOURCE,
                endpoint=endpoint,
            )
        teams.append(
            NbaTeamRecord(
                nba_team_id=identifier,
                abbreviation=str(abbreviation),
                full_name=str(entry.get("full_name") or ""),
                city=entry.get("city") or None,
                nickname=entry.get("nickname") or None,
            )
        )
    return teams


# --------------------------------------------------------------------------
# CommonAllPlayers
# --------------------------------------------------------------------------


def parse_common_all_players(payload: Any) -> list[NbaPlayerRecord]:
    """Parse ``CommonAllPlayers`` — the NBA half of the crosswalk."""
    endpoint = "CommonAllPlayers"
    table = require_table(
        result_tables(payload, endpoint=endpoint), "CommonAllPlayers", endpoint=endpoint
    )
    table.require("PERSON_ID", "DISPLAY_LAST_COMMA_FIRST", "DISPLAY_FIRST_LAST", "ROSTERSTATUS")

    players: list[NbaPlayerRecord] = []
    for row in table.rows:
        person_id = as_int(table.get(row, "PERSON_ID"))
        if person_id is None:
            continue
        team_id = as_int(table.get(row, "TEAM_ID"))
        players.append(
            NbaPlayerRecord(
                nba_player_id=person_id,
                display_last_comma_first=str(table.get(row, "DISPLAY_LAST_COMMA_FIRST") or ""),
                display_first_last=str(table.get(row, "DISPLAY_FIRST_LAST") or ""),
                is_active_roster=bool(as_int(table.get(row, "ROSTERSTATUS"))),
                from_year=_text_or_none(table.get(row, "FROM_YEAR")),
                to_year=_text_or_none(table.get(row, "TO_YEAR")),
                # 0 is the sentinel for "no team", not a team id.
                team_id=team_id or None,
                team_abbreviation=_text_or_none(table.get(row, "TEAM_ABBREVIATION")),
                player_slug=_text_or_none(table.get(row, "PLAYER_SLUG")),
            )
        )
    if not players:
        raise SourceContractError("no player rows", source=SOURCE, endpoint=endpoint)
    return players


def _text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


# --------------------------------------------------------------------------
# LeagueGameFinder
# --------------------------------------------------------------------------

_MATCHUP = re.compile(r"^(?P<team>[A-Z]{2,4})\s+(?P<separator>vs\.|@)\s+(?P<opponent>[A-Z]{2,4})$")


def parse_league_game_finder(
    payload: Any, *, season: str, season_type: str = "regular"
) -> list[NbaGameRecord]:
    """Parse ``LeagueGameFinder`` into one record per game, not per team.

    The endpoint returns two rows per game, one from each team's point of view,
    and the ``MATCHUP`` string is the only thing distinguishing home from away:
    ``"LAL vs. POR"`` is the home row, ``"LAL @ POR"`` the away row. Collapsing
    on ``GAME_ID`` without reading it produces games whose home and away teams
    depend on row order.
    """
    endpoint = "LeagueGameFinder"
    table = require_table(
        result_tables(payload, endpoint=endpoint), "LeagueGameFinderResults", endpoint=endpoint
    )
    table.require("GAME_ID", "TEAM_ID", "GAME_DATE", "MATCHUP")

    games: dict[str, dict[str, Any]] = {}
    for row in table.rows:
        game_id = _text_or_none(table.get(row, "GAME_ID"))
        team_id = as_int(table.get(row, "TEAM_ID"))
        matchup = str(table.get(row, "MATCHUP") or "")
        if game_id is None or team_id is None:
            continue
        match = _MATCHUP.match(matchup.strip())
        if match is None:
            raise SourceContractError(
                f"unrecognised MATCHUP {matchup!r} for game {game_id}",
                source=SOURCE,
                endpoint=endpoint,
            )
        is_home = match["separator"] == "vs."
        entry = games.setdefault(
            game_id,
            {"date": as_date(table.get(row, "GAME_DATE"), endpoint=endpoint)},
        )
        entry["home_id" if is_home else "away_id"] = team_id
        entry["home_pts" if is_home else "away_pts"] = as_int(table.get(row, "PTS"))

    records: list[NbaGameRecord] = []
    for game_id, entry in sorted(games.items()):
        home_id = entry.get("home_id")
        away_id = entry.get("away_id")
        if home_id is None or away_id is None:
            # One-sided rows happen when a filter narrows to a single team.
            # Skipped rather than invented: a game with a guessed opponent is
            # worse than a game we know we are missing.
            continue
        records.append(
            NbaGameRecord(
                nba_game_id=game_id,
                season=season,
                season_type=season_type,
                game_date=entry["date"],
                home_team_id=home_id,
                away_team_id=away_id,
                home_score=entry.get("home_pts"),
                away_score=entry.get("away_pts"),
            )
        )
    return records


# --------------------------------------------------------------------------
# PlayerGameLogs
# --------------------------------------------------------------------------


def parse_player_game_logs(payload: Any) -> list[PlayerBoxScoreRecord]:
    """Parse a whole season of ``PlayerGameLogs`` in one pass.

    One request returns every player-game in a season — 26,306 rows for
    2024-25. That is dramatically cheaper than a box score per game and is why
    the backfill uses it for production, leaving the per-game endpoints to
    supply the participation facts they alone carry.

    ``MIN_SEC`` is preferred over ``MIN``: ``MIN`` is a rounded decimal
    (``48.4``) and ``MIN_SEC`` is exact (``"48:24"``).
    """
    endpoint = "PlayerGameLogs"
    table = require_table(
        result_tables(payload, endpoint=endpoint), "PlayerGameLogs", endpoint=endpoint
    )
    table.require("PLAYER_ID", "GAME_ID", "TEAM_ID", "MIN")

    records: list[PlayerBoxScoreRecord] = []
    for row in table.rows:
        player_id = as_int(table.get(row, "PLAYER_ID"))
        game_id = _text_or_none(table.get(row, "GAME_ID"))
        team_id = as_int(table.get(row, "TEAM_ID"))
        if player_id is None or game_id is None or team_id is None:
            continue
        seconds = parse_minutes_to_seconds(table.get(row, "MIN_SEC"))
        if seconds is None:
            seconds = parse_minutes_to_seconds(table.get(row, "MIN"))
        records.append(
            PlayerBoxScoreRecord(
                nba_player_id=player_id,
                nba_game_id=game_id,
                nba_team_id=team_id,
                player_name=str(table.get(row, "PLAYER_NAME") or ""),
                seconds_played=seconds,
                field_goals_made=as_int(table.get(row, "FGM")),
                field_goals_attempted=as_int(table.get(row, "FGA")),
                three_pointers_made=as_int(table.get(row, "FG3M")),
                three_pointers_attempted=as_int(table.get(row, "FG3A")),
                free_throws_made=as_int(table.get(row, "FTM")),
                free_throws_attempted=as_int(table.get(row, "FTA")),
                points=as_int(table.get(row, "PTS")),
                offensive_rebounds=as_int(table.get(row, "OREB")),
                defensive_rebounds=as_int(table.get(row, "DREB")),
                rebounds=as_int(table.get(row, "REB")),
                assists=as_int(table.get(row, "AST")),
                steals=as_int(table.get(row, "STL")),
                blocks=as_int(table.get(row, "BLK")),
                turnovers=as_int(table.get(row, "TOV")),
                personal_fouls=as_int(table.get(row, "PF")),
                plus_minus=as_int(table.get(row, "PLUS_MINUS")),
            )
        )
    if not records:
        raise SourceContractError("no game log rows", source=SOURCE, endpoint=endpoint)
    return records


# --------------------------------------------------------------------------
# DNP comment normalisation
# --------------------------------------------------------------------------

#: Prefixes seen in the real ``comment`` field, mapped to an outcome.
_COMMENT_PREFIX: dict[str, ParticipationOutcome] = {
    "DNP": ParticipationOutcome.DID_NOT_PLAY,
    "DND": ParticipationOutcome.DID_NOT_DRESS,
    "NWT": ParticipationOutcome.NOT_WITH_TEAM,
}

#: Substring rules over the lower-cased remainder, in priority order. Ordered
#: because real text combines them — "Injury/Illness - Left knee soreness"
#: must not be read as "left".
_REASON_RULES: tuple[tuple[str, DnpReason], ...] = (
    ("coach", DnpReason.COACHES_DECISION),
    ("injury", DnpReason.INJURY_OR_ILLNESS),
    ("illness", DnpReason.INJURY_OR_ILLNESS),
    ("sore", DnpReason.INJURY_OR_ILLNESS),
    ("health and safety", DnpReason.INJURY_OR_ILLNESS),
    ("concussion", DnpReason.INJURY_OR_ILLNESS),
    ("reconditioning", DnpReason.CONDITIONING),
    ("conditioning", DnpReason.CONDITIONING),
    ("rest", DnpReason.REST),
    ("load management", DnpReason.REST),
    ("personal", DnpReason.PERSONAL),
    ("suspend", DnpReason.SUSPENSION),
    ("suspension", DnpReason.SUSPENSION),
    ("g league", DnpReason.G_LEAGUE),
    ("g-league", DnpReason.G_LEAGUE),
    ("two-way", DnpReason.G_LEAGUE),
    ("assignment", DnpReason.G_LEAGUE),
    ("trade", DnpReason.TRADE_PENDING),
    ("not with team", DnpReason.NOT_WITH_TEAM),
)


def parse_participation_comment(
    comment: str | None,
) -> tuple[ParticipationOutcome | None, DnpReason]:
    """Split a box-score ``comment`` into an outcome and a normalised reason.

    Returns ``(None, NONE_GIVEN)`` for an empty comment, which means the player
    appeared — the caller supplies :attr:`ParticipationOutcome.PLAYED`.

    The separator is **not** consistent. Observed in the same season:
    ``"DNP - Coach's Decision"``, ``"DND - Injury/Illness"``,
    ``"NWT - Not With Team"`` and ``"NWT-Return to Competition
    Reconditioning"`` — the last with no spaces around the hyphen. Splitting on
    ``" - "`` drops that one on the floor.

    An unrecognised reason becomes ``OTHER``, never a guess. The raw text is
    retained by the caller, so a better normalisation can be re-derived later;
    a normalisation forced into the nearest category cannot be undone.
    """
    text = (comment or "").strip()
    if not text:
        return None, DnpReason.NONE_GIVEN

    prefix, _, remainder = text.partition("-")
    prefix_key = prefix.strip().upper()
    outcome = _COMMENT_PREFIX.get(prefix_key)
    if outcome is None:
        # No recognised prefix: treat the whole comment as a reason and record
        # a did-not-play, which is the only thing a comment on a zero-minute
        # line can mean.
        outcome = ParticipationOutcome.DID_NOT_PLAY
        remainder = text

    lowered = remainder.strip().lower()
    if not lowered:
        return outcome, DnpReason.NONE_GIVEN
    for needle, reason in _REASON_RULES:
        if needle in lowered:
            return outcome, reason
    return outcome, DnpReason.OTHER


# --------------------------------------------------------------------------
# BoxScoreTraditionalV3 + BoxScoreSummaryV3
# --------------------------------------------------------------------------


def _v3_body(payload: Any, key: str, *, endpoint: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SourceContractError(
            f"expected an object, got {type(payload).__name__}", source=SOURCE, endpoint=endpoint
        )
    body = payload.get(key)
    if not isinstance(body, dict):
        raise SourceContractError(
            f"payload has no {key!r} object; keys were {sorted(payload)}",
            source=SOURCE,
            endpoint=endpoint,
        )
    return body


def parse_box_score_traditional_v3(
    payload: Any,
) -> tuple[list[PlayerBoxScoreRecord], list[PlayerParticipationRecord]]:
    """Parse ``BoxScoreTraditionalV3`` into box scores and participation.

    Only players who **dressed** appear here — those who played, plus those who
    dressed and did not, carrying a ``comment``. Players on the inactive list
    are absent entirely, which is why :func:`parse_box_score_summary_v3` is
    required as well and why the two are combined by
    :func:`combine_game_participation`.
    """
    endpoint = "BoxScoreTraditionalV3"
    body = _v3_body(payload, "boxScoreTraditional", endpoint=endpoint)
    game_id = str(body.get("gameId") or "")
    if not game_id:
        raise SourceContractError("no gameId", source=SOURCE, endpoint=endpoint)

    box_scores: list[PlayerBoxScoreRecord] = []
    participation: list[PlayerParticipationRecord] = []

    for side in ("homeTeam", "awayTeam"):
        team = body.get(side)
        if not isinstance(team, dict):
            raise SourceContractError(f"no {side!r} object", source=SOURCE, endpoint=endpoint)
        team_id = as_int(team.get("teamId"))
        if team_id is None:
            raise SourceContractError(f"{side} has no teamId", source=SOURCE, endpoint=endpoint)
        players = team.get("players")
        if not isinstance(players, list):
            raise SourceContractError(
                f"{side} has no players list", source=SOURCE, endpoint=endpoint
            )
        starters = _slug_set(team.get("starters"))

        for entry in players:
            if not isinstance(entry, dict):
                continue
            person_id = as_int(entry.get("personId"))
            if person_id is None:
                continue
            stats_value = entry.get("statistics")
            stats: dict[str, Any] = stats_value if isinstance(stats_value, dict) else {}
            raw_comment = str(entry.get("comment") or "")
            seconds = parse_minutes_to_seconds(stats.get("minutes"))
            name = f"{entry.get('firstName') or ''} {entry.get('familyName') or ''}".strip()

            outcome, reason = parse_participation_comment(raw_comment)
            if outcome is None:
                outcome = ParticipationOutcome.PLAYED
                box_scores.append(
                    PlayerBoxScoreRecord(
                        nba_player_id=person_id,
                        nba_game_id=game_id,
                        nba_team_id=team_id,
                        player_name=name,
                        seconds_played=seconds,
                        field_goals_made=as_int(stats.get("fieldGoalsMade")),
                        field_goals_attempted=as_int(stats.get("fieldGoalsAttempted")),
                        three_pointers_made=as_int(stats.get("threePointersMade")),
                        three_pointers_attempted=as_int(stats.get("threePointersAttempted")),
                        free_throws_made=as_int(stats.get("freeThrowsMade")),
                        free_throws_attempted=as_int(stats.get("freeThrowsAttempted")),
                        points=as_int(stats.get("points")),
                        offensive_rebounds=as_int(stats.get("reboundsOffensive")),
                        defensive_rebounds=as_int(stats.get("reboundsDefensive")),
                        rebounds=as_int(stats.get("reboundsTotal")),
                        assists=as_int(stats.get("assists")),
                        steals=as_int(stats.get("steals")),
                        blocks=as_int(stats.get("blocks")),
                        turnovers=as_int(stats.get("turnovers")),
                        personal_fouls=as_int(stats.get("foulsPersonal")),
                        plus_minus=as_int(stats.get("plusMinusPoints")),
                        started=(entry.get("playerSlug") in starters) if starters else None,
                    )
                )

            participation.append(
                PlayerParticipationRecord(
                    nba_player_id=person_id,
                    nba_game_id=game_id,
                    nba_team_id=team_id,
                    outcome=outcome,
                    reason=reason,
                    raw_comment=raw_comment,
                    player_name=name or None,
                    seconds_played=seconds,
                )
            )

    return box_scores, participation


def _local_game_date(body: dict[str, Any], tipoff: datetime | None, *, endpoint: str) -> date:
    """The date the game belongs to, which is its **local** date, not its UTC one.

    ``nba_games.game_date`` means the local calendar date, because fantasy days
    are defined in local time. Deriving it from ``gameTimeUTC`` is wrong for
    every game tipping after 7pm Eastern — which is most of them. Game
    ``0022500560`` has ``gameTimeUTC = 2026-01-13T00:30:00Z`` and is a
    **2026-01-12** game; ``LeagueGameFinder`` agrees it is the 12th. An earlier
    version of this function took ``tipoff.date()`` and produced the 13th, so
    the same game arrived with two different dates depending on which endpoint
    wrote it last, and every day-boundary calculation downstream inherited the
    disagreement.

    **``gameEt`` is the local field, and it lies about its timezone.** It is
    Eastern time carrying a ``Z`` suffix: the same payload shows
    ``gameTimeUTC = 2024-12-01T20:30:00Z`` and
    ``gameEt = 2024-12-01T15:30:00Z``, five hours apart and both marked UTC.
    So it must be read for its **date only**, and must never be passed to
    :func:`as_utc_datetime`, which would take the ``Z`` at face value and
    produce an instant five hours wrong.

    Falls back to the tip-off instant **converted to Eastern** only when
    ``gameEt`` is absent — never to its raw UTC date, which is the bug this
    function exists to prevent.
    """
    local = body.get("gameEt")
    if local:
        return as_date(local, endpoint=endpoint)
    if tipoff is not None:
        # Last resort, and still converted rather than truncated: the UTC date
        # of a 7:30pm Eastern tip-off is the following day. `ZoneInfo` rather
        # than a fixed -5 offset, because the NBA season crosses a daylight
        # saving boundary in March.
        return tipoff.astimezone(NBA_LOCAL_TIMEZONE).date()
    raise SourceContractError(
        "no gameEt and no gameTimeUTC, so the game has no date",
        source=SOURCE,
        endpoint=endpoint,
    )


def _slug_set(value: Any) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    return frozenset(
        str(entry.get("playerSlug"))
        for entry in value
        if isinstance(entry, dict) and entry.get("playerSlug")
    )


def parse_box_score_summary_v3(payload: Any) -> tuple[NbaGameRecord | None, GameParticipation]:
    """Parse ``BoxScoreSummaryV3`` for tip-off and the inactive lists.

    The inactive lists are nested under ``homeTeam.inactives`` and
    ``awayTeam.inactives`` rather than being a top-level collection, which is
    easy to miss and is why they were briefly believed not to exist here at
    all.

    ``inactives_available`` is set only when the source actually offered the
    key. An empty list under a present key means "nobody was inactive"; a
    missing key means "this endpoint is not telling us". Those are different
    facts and the availability model must not confuse them.
    """
    endpoint = "BoxScoreSummaryV3"
    body = _v3_body(payload, "boxScoreSummary", endpoint=endpoint)
    game_id = str(body.get("gameId") or "")
    if not game_id:
        raise SourceContractError("no gameId", source=SOURCE, endpoint=endpoint)

    records: list[PlayerParticipationRecord] = []
    #: Set only when **both** teams offered an inactives key. A one-sided
    #: degradation would otherwise be recorded as "the source told us" while
    #: half the game's inactives are missing — structurally the same failure as
    #: the V2 rot this column exists to make impossible.
    sides_offering = 0
    sides_seen = 0
    for side in ("homeTeam", "awayTeam"):
        team = body.get(side)
        if not isinstance(team, dict):
            continue
        sides_seen += 1
        team_id = as_int(team.get("teamId"))
        inactives = team.get("inactives")
        # The type check precedes the flag: a `null` or an object under this
        # key is the source failing to answer, not answering "nobody".
        if not isinstance(inactives, list):
            continue
        sides_offering += 1
        for entry in inactives:
            if not isinstance(entry, dict):
                continue
            person_id = as_int(entry.get("personId"))
            if person_id is None or team_id is None:
                continue
            name = f"{entry.get('firstName') or ''} {entry.get('familyName') or ''}".strip()
            records.append(
                PlayerParticipationRecord(
                    nba_player_id=person_id,
                    nba_game_id=game_id,
                    nba_team_id=team_id,
                    outcome=ParticipationOutcome.INACTIVE,
                    # The inactive list gives no reason at all. Recording
                    # NONE_GIVEN rather than INJURY_OR_ILLNESS matters: most
                    # inactives are injuries, and "most" is exactly the kind of
                    # assumption that turns into a fabricated training label.
                    reason=DnpReason.NONE_GIVEN,
                    raw_comment="",
                    player_name=name or None,
                )
            )

    offered = sides_seen == 2 and sides_offering == 2

    home = body.get("homeTeam")
    away = body.get("awayTeam")
    home_team: dict[str, Any] = home if isinstance(home, dict) else {}
    away_team: dict[str, Any] = away if isinstance(away, dict) else {}
    home_id = as_int(home_team.get("teamId"))
    away_id = as_int(away_team.get("teamId"))
    game: NbaGameRecord | None = None
    if home_id is not None and away_id is not None:
        tipoff = as_utc_datetime(body.get("gameTimeUTC"))
        game = NbaGameRecord(
            nba_game_id=game_id,
            season="",
            season_type="regular",
            game_date=_local_game_date(body, tipoff, endpoint=endpoint),
            home_team_id=home_id,
            away_team_id=away_id,
            home_score=as_int(home_team.get("score")),
            away_score=as_int(away_team.get("score")),
            tipoff_utc=tipoff,
            status=_text_or_none(body.get("gameStatusText")),
        )

    return game, GameParticipation(
        nba_game_id=game_id, records=records, inactives_available=offered
    )


def combine_game_participation(
    traditional: list[PlayerParticipationRecord],
    summary: GameParticipation,
) -> GameParticipation:
    """Merge the dressed-player records with the inactive list.

    The box score wins on conflict: a player who appears in both has a stated
    outcome from the box score, and a stated outcome beats membership of a list
    that gives no reason.
    """
    seen = {r.nba_player_id for r in traditional}
    merged = list(traditional)
    merged.extend(r for r in summary.records if r.nba_player_id not in seen)
    return GameParticipation(
        nba_game_id=summary.nba_game_id,
        records=merged,
        inactives_available=summary.inactives_available,
    )
