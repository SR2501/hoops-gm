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

from datetime import datetime
from typing import Any, Final

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
from hoops_gm.ingest.league_settings import (
    parse_official_league_settings,
    parse_scoring_category_configs,
    parse_scoring_type_raw,
)

SOURCE = "fantrax_official"
_MAX_DRAFT_COORDINATE_DIGITS: Final = 10


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
        "draftSettings",
        "endDate",
        "leagueHistoryId",
        "matchups",
        "playerInfo",
        "playoffs",
        "poolSettings",
        "rosterInfo",
        "rosterPeriods",
        "scoringPeriods",
        "seasonYear",
        "startDate",
        "teamInfo",
    }
)


def parse_league_info(
    payload: Any,
    *,
    league_id: str | None = None,
    capture_ref: str | None = None,
    source_payload_sha256: str | None = None,
    source_observed_at: datetime | None = None,
) -> FantraxLeagueInfo:
    """Parse ``getLeagueInfo``.

    The current shape is pinned to a sanitized successful response captured from
    the target league on 2026-08-18. The source returned that private league's
    data for a request containing only its non-secret ``leagueId``.
    """
    endpoint = "getLeagueInfo"
    raise_for_error_envelope(payload, endpoint=endpoint)
    body = _require(payload, dict, endpoint=endpoint)
    resolved_league_id = str(body.get("leagueId") or league_id or "")
    if not resolved_league_id:
        raise SourceContractError(
            "successful payload did not identify a league",
            source=SOURCE,
            endpoint=endpoint,
        )
    if capture_ref is None:
        suffix = source_payload_sha256 or "digest-unavailable"
        capture_ref = f"{SOURCE}:{endpoint}:sha256:{suffix}"

    raw_teams = body.get("fantasyTeams")
    if isinstance(raw_teams, list):
        team_items = [(None, item) for item in raw_teams]
    elif isinstance(body.get("teams"), list):
        team_items = [(None, item) for item in body["teams"]]
    elif isinstance(body.get("teamInfo"), dict):
        team_items = list(body["teamInfo"].items())
    else:
        team_items = []

    teams = [
        FantraxLeagueTeam(
            team_id=str(t.get("id") or t.get("teamId") or key or ""),
            name=str(t.get("name") or t.get("teamName") or ""),
            short_name=_optional_str(t.get("shortName")),
            owner_name=_optional_str(t.get("ownerName") or t.get("owner")),
        )
        for key, t in team_items
        if isinstance(t, dict)
    ]

    raw_categories = parse_scoring_category_configs(body)
    categories: list[FantraxScoringCategory] = (
        [
            FantraxScoringCategory(
                code=item.code,
                name=item.display_name,
                abbreviation=item.abbreviation,
                weight=item.weight,
            )
            for item in raw_categories
        ]
        if raw_categories is not None
        else []
    )

    roster_info = body.get("rosterInfo")
    roster_size = body.get("rosterSize")
    if roster_size is None and isinstance(roster_info, dict):
        roster_size = roster_info.get("maxTotalPlayers")
    scoring_type = parse_scoring_type_raw(body)
    return FantraxLeagueInfo(
        league_id=resolved_league_id,
        league_name=_optional_str(body.get("leagueName")),
        sport=_optional_str(body.get("sport")),
        scoring_type=_optional_str(scoring_type),
        draft_type=_optional_str(body.get("draftType")),
        roster_size=int(roster_size)
        if isinstance(roster_size, int | str) and str(roster_size).isdigit()
        else None,
        source_payload_sha256=source_payload_sha256,
        source_observed_at=source_observed_at,
        teams=teams,
        scoring_categories=categories,
        settings=parse_official_league_settings(
            body,
            source_league_id=resolved_league_id,
            capture_ref=capture_ref,
        ),
        unmapped_keys=tuple(sorted(set(body) - _LEAGUE_INFO_KNOWN_KEYS)),
    )


# --------------------------------------------------------------------------
# getDraftPicks
# --------------------------------------------------------------------------


#: Keys that may carry the list of picks, in the order they are tried.
#:
#: ``currentDraftPicks`` is the **only one ever observed**: league
#: ``b2gyornvms4606iv`` returned ``{"currentDraftPicks":[]}`` under HTTP 200 on
#: 2026-08-28 (fixture ``fantrax_getdraftpicks_completed_snake_empty.json``).
#: ``draftPicks`` and ``picks`` were this parser's original guesses. They are
#: kept rather than deleted because one real payload names one key and does not
#: disprove the others — but they are now demoted below a name we have actually
#: seen.
_DRAFT_PICK_LIST_KEYS: Final = ("currentDraftPicks", "draftPicks", "picks")


def parse_draft_picks(payload: Any) -> list[FantraxDraftPick]:
    """Parse ``getDraftPicks``.

    Both draft formats are first-class in this project, so neither the snake
    shape (round/pick) nor the auction shape (a price) is assumed: every field
    is optional and an auction amount is read if present.

    **The list key is selected by presence, not by truthiness.** The original
    ``payload.get("draftPicks") or payload.get("picks")`` would step straight
    past an empty-but-present list to a later key — silently converting *"this
    source says there are no picks"* into *"look somewhere else"*. That is the
    same defect class already recorded against the value aliases at
    :func:`hoops_gm.draft.feed.recognise.recognise_official_draft_picks`, where
    ``{"overallPick": 0, "overall": 3}`` yields ``3``. It matters here because
    the one real payload we have **is** an empty list under the first key.

    **An unrecognised object still returns no picks rather than raising.** The
    feed is built to treat this source's silence as silence, not as failure, and
    inventing a new error mode on a case never observed would trade a survivable
    outcome for an unsurvivable one. Drift in the key name is caught by the live
    smoke, which asserts the observed key against the real endpoint — not here,
    because a committed fixture cannot notice that the source was renamed.
    """
    endpoint = "getDraftPicks"
    raise_for_error_envelope(payload, endpoint=endpoint)

    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = []
        for key in _DRAFT_PICK_LIST_KEYS:
            if key in payload:
                candidate = payload[key]
                rows = candidate if isinstance(candidate, list) else []
                break
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
                round_number=_draft_coordinate(
                    row,
                    ("round", "roundNumber"),
                    field_name="round_number",
                    endpoint=endpoint,
                ),
                pick_number=_draft_coordinate(
                    row,
                    ("pick", "pickNumber"),
                    field_name="pick_number",
                    endpoint=endpoint,
                ),
                overall_pick=_draft_coordinate(
                    row,
                    ("overallPick", "overall"),
                    field_name="overall_pick",
                    endpoint=endpoint,
                ),
                player_id=_optional_str(row.get("playerId") or row.get("id")),
                player_name=_optional_str(row.get("playerName") or row.get("name")),
                auction_amount=_as_float(row.get("amount") or row.get("bid") or row.get("salary")),
            )
        )
    return picks


def _draft_coordinate(
    row: dict[str, Any],
    keys: tuple[str, ...],
    *,
    field_name: str,
    endpoint: str,
) -> int | None:
    """An absent coordinate, or an exact integer the source actually supplied."""
    value: Any = None
    supplied_key: str | None = None
    for key in keys:
        if key in row:
            value = row[key]
            supplied_key = key
            break
    if supplied_key is None or value is None:
        return None
    if isinstance(value, bool):
        parsed = None
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        candidate = value
        digits = candidate[1:] if candidate.startswith(("+", "-")) else candidate
        is_ascii_integer = (
            bool(digits)
            and len(digits) <= _MAX_DRAFT_COORDINATE_DIGITS
            and all("0" <= character <= "9" for character in digits)
        )
        parsed = int(candidate) if is_ascii_integer else None
    else:
        parsed = None
    if parsed is None:
        raise SourceContractError(
            f"{field_name} must be an exact integer when supplied",
            source=SOURCE,
            endpoint=endpoint,
            detail={"key": supplied_key, "value": repr(value)[:100]},
        )
    return parsed


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
