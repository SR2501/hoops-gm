"""Pure parsers for the Fantrax official ``/fxea/general/`` payloads.

Every function here takes a decoded payload and returns typed records. No
network, no database, no clock. That is what lets the contract tests run
offline against committed fixtures on every push (ADR-006).

Two behaviours are load-bearing and both were established by hitting the real
endpoints on 2026-08-17 rather than by reading the documentation.

**An error is an HTTP 200.** ``getLeagueInfo`` with no ``leagueId`` returns
status 200 with ``{"error": {"onScreen": false, "code": "WARNING", "message":
"Missing 'leagueId' parameter"}}``. A client that trusts the status code hands
that envelope to a parser as data. :func:`raise_for_error_envelope` is called
before any parsing, on every endpoint.

**The player payload is not all players.** ``getPlayerIds`` mixes thirty team
entities in with 1,788 players (risk R24). They are identified by
``position == "Tm"``, and separately by a ``#`` in the key. Both markers were
checked against the live payload and identify exactly the same thirty rows —
but they are *different claims*, so :func:`parse_player_ids` uses the
positional label and treats the identifier shape as corroboration. Baking the
``#`` convention into anything structural would make one source's incidental
identifier format load-bearing.
"""

from __future__ import annotations

from typing import Any

from hoops_gm.identity.names import NON_PLAYER_POSITIONS, normalize_team_abbreviation
from hoops_gm.ingest.errors import SourceContractError, SourceRejected
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

SOURCE = "fantrax_official"


def raise_for_error_envelope(payload: Any, *, endpoint: str) -> None:
    """Raise if the payload is Fantrax's application-level error envelope.

    Called before parsing on every endpoint, because Fantrax signals refusal
    with an HTTP 200 body rather than a status code.
    """
    if not isinstance(payload, dict):
        return
    error = payload.get("error")
    if not isinstance(error, dict):
        return
    message = error.get("message") or "unspecified error"
    code = error.get("code") or "UNKNOWN"
    raise SourceRejected(
        f"{code}: {message}",
        source=SOURCE,
        endpoint=endpoint,
        detail=error,
    )


def _require(payload: Any, expected: type, *, endpoint: str) -> Any:
    if not isinstance(payload, expected):
        raise SourceContractError(
            f"expected a JSON {expected.__name__}, got {type(payload).__name__}",
            source=SOURCE,
            endpoint=endpoint,
            detail=repr(payload)[:200],
        )
    return payload


def _optional_str(value: Any) -> str | None:
    """Coerce a cross-reference identifier to text, preserving absence.

    ``statsIncId`` and ``rotowireId`` arrive as JSON integers and
    ``sportRadarId`` as a UUID string. They all end up in
    ``player_external_ids.external_id``, which is a string column, so the
    coercion has to happen somewhere; doing it here means the identity layer
    never has to care which source used which JSON type.
    """
    if value is None or value == "":
        return None
    return str(value)


# --------------------------------------------------------------------------
# getPlayerIds
# --------------------------------------------------------------------------


def parse_player_ids(payload: Any) -> FantraxPlayerIds:
    """Split ``getPlayerIds`` into players, team entities and anything else.

    The payload is an object keyed by Fantrax identifier, not an array. Rows
    are classified by ``position``: ``"Tm"`` marks a franchise entity that is
    not a person (R24). Anything that is neither a recognisable player nor a
    team entity goes to ``unclassified`` rather than being dropped, so a third
    row type shows up as a number a test can assert on.
    """
    endpoint = "getPlayerIds"
    raise_for_error_envelope(payload, endpoint=endpoint)
    rows = _require(payload, dict, endpoint=endpoint)

    players: list[FantraxPlayer] = []
    teams: list[FantraxTeamEntity] = []
    unclassified: list[str] = []

    for key, row in rows.items():
        if not isinstance(row, dict):
            unclassified.append(str(key))
            continue

        position = str(row.get("position") or "")
        if position in NON_PLAYER_POSITIONS:
            teams.append(
                FantraxTeamEntity(
                    fantrax_id=str(row.get("fantraxId") or key),
                    team_name=str(row.get("teamName") or ""),
                    team_short_name=str(row.get("teamShortName") or ""),
                )
            )
            continue

        name = row.get("name")
        if not name:
            unclassified.append(str(key))
            continue

        players.append(
            FantraxPlayer(
                fantrax_id=str(row.get("fantraxId") or key),
                name=str(name),
                team=normalize_team_abbreviation(row.get("team")),
                position=position,
                stats_inc_id=_optional_str(row.get("statsIncId")),
                rotowire_id=_optional_str(row.get("rotowireId")),
                sport_radar_id=_optional_str(row.get("sportRadarId")),
            )
        )

    if not players:
        raise SourceContractError(
            f"no player rows in a payload of {len(rows)} entries",
            source=SOURCE,
            endpoint=endpoint,
        )

    return FantraxPlayerIds(players=players, team_entities=teams, unclassified=unclassified)


# --------------------------------------------------------------------------
# getAdp
# --------------------------------------------------------------------------


def parse_adp(payload: Any) -> list[FantraxAdpEntry]:
    """Parse ``getAdp``.

    Unlike ``getPlayerIds`` this is a JSON array, ordered by ADP ascending. The
    order is not relied on — ``adp`` is carried on each row — but the contract
    test asserts it, because a payload that stops being sorted is a signal
    about the endpoint even when every value is still correct.
    """
    endpoint = "getAdp"
    raise_for_error_envelope(payload, endpoint=endpoint)
    rows = _require(payload, list, endpoint=endpoint)

    entries: list[FantraxAdpEntry] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SourceContractError(
                f"row {index} is a {type(row).__name__}, not an object",
                source=SOURCE,
                endpoint=endpoint,
            )
        identifier = row.get("id")
        adp = row.get("ADP")
        if identifier is None or adp is None:
            raise SourceContractError(
                f"row {index} is missing 'id' or 'ADP': {sorted(row)}",
                source=SOURCE,
                endpoint=endpoint,
            )
        try:
            adp_value = float(adp)
        except (TypeError, ValueError) as exc:
            raise SourceContractError(
                f"row {index} has a non-numeric ADP {adp!r}",
                source=SOURCE,
                endpoint=endpoint,
            ) from exc
        entries.append(
            FantraxAdpEntry(
                fantrax_id=str(identifier),
                name=str(row.get("name") or ""),
                position=str(row.get("pos") or ""),
                adp=adp_value,
            )
        )

    if not entries:
        raise SourceContractError("empty ADP payload", source=SOURCE, endpoint=endpoint)
    return entries


# --------------------------------------------------------------------------
# getLeagueInfo
# --------------------------------------------------------------------------

#: Keys this parser reads. Anything else in the payload is reported on
#: ``unmapped_keys`` rather than ignored: a league setting we quietly drop is a
#: setting the draft engine gets wrong.
_LEAGUE_INFO_KNOWN_KEYS = frozenset(
    {
        "leagueId",
        "leagueName",
        "sport",
        "scoringType",
        "draftType",
        "rosterSize",
        "fantasyTeams",
        "teams",
        "scoringCategories",
        "scoringSystem",
    }
)


def parse_league_info(payload: Any, *, league_id: str | None = None) -> FantraxLeagueInfo:
    """Parse ``getLeagueInfo``.

    **This parser has never been run against a real payload.** ``getLeagueInfo``
    requires a ``leagueId``, and no league credentials existed when it was
    written; the only live response obtained was the missing-parameter error
    envelope, which :func:`raise_for_error_envelope` handles and which *is*
    covered by a contract test.

    So it is written defensively — every field optional, alternative key
    spellings accepted, unrecognised keys surfaced on ``unmapped_keys`` — and
    it must be re-checked against a real league before anything depends on it.
    Recorded in ``docs/handoff.md``.
    """
    endpoint = "getLeagueInfo"
    raise_for_error_envelope(payload, endpoint=endpoint)
    body = _require(payload, dict, endpoint=endpoint)

    raw_teams = body.get("fantasyTeams")
    if not isinstance(raw_teams, list):
        raw_teams = body.get("teams") if isinstance(body.get("teams"), list) else []

    teams = [
        FantraxLeagueTeam(
            team_id=str(t.get("id") or t.get("teamId") or ""),
            name=str(t.get("name") or t.get("teamName") or ""),
            short_name=_optional_str(t.get("shortName")),
            owner_name=_optional_str(t.get("ownerName") or t.get("owner")),
        )
        for t in raw_teams
        if isinstance(t, dict)
    ]

    raw_categories = body.get("scoringCategories")
    categories: list[FantraxScoringCategory] = []
    if isinstance(raw_categories, list):
        for c in raw_categories:
            if isinstance(c, dict):
                key = c.get("id") or c.get("key") or c.get("code") or c.get("name")
                if key is not None:
                    categories.append(
                        FantraxScoringCategory(
                            key=str(key),
                            name=_optional_str(c.get("name")),
                            abbreviation=_optional_str(c.get("shortName") or c.get("abbrev")),
                        )
                    )
            elif isinstance(c, str):
                categories.append(FantraxScoringCategory(key=c))

    roster_size = body.get("rosterSize")
    return FantraxLeagueInfo(
        league_id=str(body.get("leagueId") or league_id or ""),
        league_name=_optional_str(body.get("leagueName")),
        sport=_optional_str(body.get("sport")),
        scoring_type=_optional_str(body.get("scoringType")),
        draft_type=_optional_str(body.get("draftType")),
        roster_size=int(roster_size)
        if isinstance(roster_size, int | str) and str(roster_size).isdigit()
        else None,
        teams=teams,
        scoring_categories=categories,
        unmapped_keys=tuple(sorted(set(body) - _LEAGUE_INFO_KNOWN_KEYS)),
    )


# --------------------------------------------------------------------------
# getDraftPicks
# --------------------------------------------------------------------------


def parse_draft_picks(payload: Any) -> list[FantraxDraftPick]:
    """Parse ``getDraftPicks``.

    **Also never run against a real payload**, for the same reason as
    :func:`parse_league_info`. Both draft formats are first-class in this
    project, so neither the snake shape (round/pick) nor the auction shape
    (a price) is assumed: every field is optional and an auction amount is read
    if present.
    """
    endpoint = "getDraftPicks"
    raise_for_error_envelope(payload, endpoint=endpoint)

    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        found = payload.get("draftPicks") or payload.get("picks")
        rows = found if isinstance(found, list) else []
    else:
        raise SourceContractError(
            f"expected an array or object, got {type(payload).__name__}",
            source=SOURCE,
            endpoint=endpoint,
        )

    picks: list[FantraxDraftPick] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        picks.append(
            FantraxDraftPick(
                team_id=str(row.get("teamId") or row.get("fantasyTeamId") or ""),
                round_number=_as_int(row.get("round") or row.get("roundNumber")),
                pick_number=_as_int(row.get("pick") or row.get("pickNumber")),
                overall_pick=_as_int(row.get("overallPick") or row.get("overall")),
                player_id=_optional_str(row.get("playerId") or row.get("id")),
                player_name=_optional_str(row.get("playerName") or row.get("name")),
                auction_amount=_as_float(row.get("amount") or row.get("bid") or row.get("salary")),
            )
        )
    return picks


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
