"""Turning a captured artifact into claims about the draft, or into silence.

Two recognisers. Both **fail closed**: when the shape is not what they can
read, they emit nothing and say so, rather than emitting a partially-read
record. On a draft night an empty board with "0 of 41 recognised" on it is
recoverable in five minutes; a board holding three wrong picks is not.

## What is actually known about the bridge envelope, and what is not

**Known, and checkable.** ``/fxpa/req`` is a JSON-RPC batch. The request is
``{"msgs": [{"method": ..., "data": {...}}]}`` with ``?leagueId=`` on the query
string; the response is ``{"responses": [{"data": {...}}, ...]}``, positionally
aligned with the request. That is not inferred from a captured payload — it is
read off ``fantraxapi`` 1.0.1's ``api.py``, which is a pinned dependency of this
project and a working client against the live endpoint.
``test_draft_feed_contracts.py`` re-reads that source and fails when it stops
saying so, which makes this the one claim here with a drift check behind it.

**The consequence, which shapes everything below.** The method name lives in the
*request* body. The userscript never reads a request body — deliberately, and
that is not going to change (``userscript/src/capture.js``: outgoing request
bodies and all headers are never read or forwarded). So a captured response
**does not say which RPC produced it**, and the batch means one capture can hold
several unrelated answers. Discrimination has to happen on the response's own
content.

**Not known.** Which method a Fantrax draft room calls, and what its response
looks like. ``fantraxapi`` implements no draft method. No draft-room payload has
ever been captured — ``backend/tests/fixtures/`` holds none, and
``docs/adapters/fantrax-official.md`` records ``getDraftPicks`` as never having
returned a successful real response either. So there is no shape to match
against and writing one from imagination is what ADR-006 rejects.

## How this is discriminated without guessing a shape

The recogniser does not look for a known key path. It looks for **a list of
records that every one of this league's own seats can be found in**, using
identifiers we already hold: ``fantasy_teams.fantrax_team_id`` for the seats of
*this* draft, and the ``leagueId`` on the capture's own URL.

That inverts where a wrong guess lands. Key-name aliases (:data:`FIELD_ALIASES`)
are still candidates rather than verified names — but they are used only to
*read* a record that has already been accepted, and acceptance requires every
record in the list to resolve to a team id this draft knows about. A block whose
key names do not match yields zero accepted records and is reported as an
unrecognised shape. It cannot yield a record with a missing buyer, because a
record with no resolvable buyer disqualifies the entire list it is in.

The falsifiable form: *the defect excluded is "a wrong alias produces a record
attributed to the wrong seat, or to no seat".* A reading where a block is
accepted and that defect is present needs a payload in which a wrong alias
nonetheless reads out a string that is exactly one of this league's Fantrax team
ids, for **every** record in the list. What it does **not** exclude is a block
that is correctly read and is not about this draft at all — a completed *prior*
season's draft results for the same league would pass every check here. Nothing
in the payload distinguishes those, so the caller's admission rules
(:mod:`hoops_gm.draft.feed.service`) do the rest, and this limit is stated
rather than papered over.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from urllib.parse import parse_qs, urlparse

from hoops_gm.db.models.enums import DraftType
from hoops_gm.draft.feed.observations import (
    InstantKind,
    InstantProvenance,
    ObservedInstant,
    RecognitionResult,
    SourceTransport,
    UnrecognisedShape,
)
from hoops_gm.ingest.fantrax_official.models import FantraxDraftPick

#: The exact pathname the userscript captures, repeated here rather than
#: imported from JavaScript. Kept exact — a prefix match would let the capture
#: surface widen silently if Fantrax adds ``/fxpa/reqSomethingElse``.
FXPA_REQ_PATHNAME: Final = "/fxpa/req"

#: Candidate key names, **not** verified names.
#:
#: Deliberately the same vocabulary
#: :func:`hoops_gm.ingest.fantrax_official.parsers.parse_draft_picks` already
#: uses, so there is one list of guesses in this repository rather than two that
#: can drift. Order is preference order within each field.
#:
#: ``id`` is excluded from the team aliases on purpose. It is the most likely
#: key name in any JSON on the internet and matching it would let an arbitrary
#: list of objects be accepted the moment one of its ``id`` values collided with
#: a Fantrax team id — which turns the anchor from a check into a coincidence.
FIELD_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "team_external_id": ("teamId", "fantasyTeamId", "franchiseId", "teamID"),
    "player_external_id": ("playerId", "scorerId", "fantasyPlayerId"),
    "player_label": ("playerName", "name", "shortName", "displayName"),
    "amount": ("amount", "bid", "salary", "price", "winningBid"),
    "overall_pick": ("overallPick", "overall"),
    "round_number": ("round", "roundNumber"),
    "pick_in_round": ("pick", "pickNumber", "pickInRound"),
}

#: How deep into a response block the walk will go looking for record lists.
#: Bounded because this runs on every capture during a live draft and an
#: unbounded walk over a Fantrax league payload is not a thing to discover at
#: 7:14pm. Six levels reaches ``responses[].data.a.b.c.d.list``.
MAX_WALK_DEPTH: Final = 6

#: Lists longer than this are not considered draft record lists. A draft is
#: bounded by ``team_count * roster_size``; a player universe is not. The bound
#: is generous (a 30-team 20-round dynasty draft is 600) so it refuses only
#: things that are obviously a different kind of collection.
MAX_RECORD_LIST: Final = 1000

_BRIDGE_RECOGNISER: Final = "fxpa_req.seat_anchored.v1"
_OFFICIAL_RECOGNISER: Final = "fxea.getDraftPicks.v1"


@dataclass(frozen=True, slots=True)
class RecognitionContext:
    """The independently-held facts a candidate block is checked against.

    Every field here comes from our own database, populated before the draft by
    a person or by the league ingest. None of it is read out of the payload
    being recognised — that is the whole point, and it is why an empty
    ``team_external_ids`` is a refusal rather than a permissive default.
    """

    #: ``leagues.fantrax_league_id`` for the league this draft was opened under.
    fantrax_league_id: str
    #: ``fantasy_teams.fantrax_team_id`` for the seats of *this* draft.
    team_external_ids: frozenset[str]
    draft_type: DraftType

    def anchor_failure(self) -> str | None:
        """Why this context cannot anchor a recognition, or ``None``."""
        if not self.fantrax_league_id:
            return "league_not_linked"
        if not self.team_external_ids:
            return "seats_not_linked"
        if self.draft_type is DraftType.UNKNOWN:
            # Mirrors ``draft_format_from_league``: an unknown format cannot say
            # whether a record is a selection or a sale, and picking one would
            # be a coin toss written into ``draft_events.event_type``.
            return "draft_type_unknown"
        return None


def _keys_of(block: Any) -> tuple[str, ...]:
    if isinstance(block, dict):
        return tuple(sorted(str(key) for key in block))
    if isinstance(block, list):
        return ("<list>",)
    return (f"<{type(block).__name__}>",)


def _first(record: dict[str, Any], field: str) -> Any:
    for alias in FIELD_ALIASES[field]:
        if alias in record:
            value = record[alias]
            if value is not None:
                return value
    return None


def _as_text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, int | float):
        return str(value)
    return None


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_amount(value: Any) -> Decimal | None:
    """A price, as an exact decimal.

    Via ``str`` rather than ``Decimal(float)``: a JSON ``41.1`` becomes
    ``41.100000000000001421...`` through the float constructor, and this number
    goes into ``draft_events.amount``, which is ``Numeric(10, 2)``. A clearing
    price is money and money does not round-trip through binary floating point.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _candidate_lists(block: Any, locator: str, depth: int = 0) -> list[tuple[str, list[Any]]]:
    """Every list-of-objects reachable within :data:`MAX_WALK_DEPTH`.

    Returns the *containers*, not the records: acceptance is a property of the
    whole list, because "every record resolves to a seat" is what makes the
    anchor an anchor and it cannot be evaluated one record at a time.
    """
    if depth > MAX_WALK_DEPTH:
        return []
    found: list[tuple[str, list[Any]]] = []
    if isinstance(block, list):
        if block and all(isinstance(item, dict) for item in block):
            found.append((locator, block))
        # Still descend: a list of lists, or a list of objects that each hold
        # the real collection, are both ordinary JSON shapes.
        for index, item in enumerate(block[:MAX_RECORD_LIST]):
            found.extend(_candidate_lists(item, f"{locator}[{index}]", depth + 1))
    elif isinstance(block, dict):
        for key, value in block.items():
            found.extend(_candidate_lists(value, f"{locator}.{key}", depth + 1))
    return found


def _accept_list(
    records: list[Any], context: RecognitionContext
) -> tuple[list[dict[str, Any]], str | None]:
    """Accept the whole list or none of it, and say why when none.

    The three refusals are separate strings rather than one because they mean
    different things to whoever reads the status screen: a length refusal says
    "this is a different kind of collection", an anchor refusal says "the alias
    is wrong or this is another league's data", and a naming refusal says "this
    is about teams but not about players".
    """
    if not records or len(records) > MAX_RECORD_LIST:
        return [], "list_length_out_of_range"

    typed = [record for record in records if isinstance(record, dict)]
    if len(typed) != len(records):  # pragma: no cover - _candidate_lists filters this
        return [], "mixed_record_types"

    for record in typed:
        team = _as_text(_first(record, "team_external_id"))
        if team is None or team not in context.team_external_ids:
            return [], "no_seat_anchor"
        named = _as_text(_first(record, "player_external_id")) or _as_text(
            _first(record, "player_label")
        )
        if named is None:
            return [], "record_names_no_player"
    return typed, None


def _instant_from(
    record: dict[str, Any],
    *,
    kind: InstantKind,
    provenance: InstantProvenance,
) -> ObservedInstant:
    return ObservedInstant(
        kind=kind,
        provenance=provenance,
        team_external_id=_as_text(_first(record, "team_external_id")),
        player_label=_as_text(_first(record, "player_label")),
        player_external_id=_as_text(_first(record, "player_external_id")),
        overall_pick=_as_int(_first(record, "overall_pick")),
        round_number=_as_int(_first(record, "round_number")),
        pick_in_round=_as_int(_first(record, "pick_in_round")),
        amount=_as_amount(_first(record, "amount")),
    )


def _kind_for(draft_type: DraftType) -> InstantKind:
    return InstantKind.SALE if draft_type is DraftType.AUCTION else InstantKind.SELECTION


def league_id_in(url: str) -> str | None:
    """The ``leagueId`` query parameter of a captured ``/fxpa/req`` URL.

    ``fantraxapi`` puts it there on every call (``api.py``: ``params={"leagueId":
    league_id}``), which is what makes a capture attributable to a league at all
    given that the response body carries no method name. Returns ``None`` when
    the URL is not the RPC endpoint or carries no such parameter.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.path != FXPA_REQ_PATHNAME:
        return None
    values = parse_qs(parsed.query).get("leagueId") or []
    for value in values:
        text = value.strip()
        if text:
            return text
    return None


def recognise_bridge_payload(
    *,
    url: str,
    body_json: Any,
    dedupe_key: str,
    received_at: datetime,
    captured_at: datetime | None,
    context: RecognitionContext,
) -> RecognitionResult:
    """Read one stored bridge capture, or explain why it was not read.

    ``received_at`` is our own row timestamp and ``captured_at`` is the
    userscript's claim; both are carried onto every instant and only the first
    is ever used for an age. See :class:`InstantProvenance`.
    """
    anchor_failure = context.anchor_failure()
    if anchor_failure is not None:
        return RecognitionResult(rejected=anchor_failure)

    league_id = league_id_in(url)
    if league_id is None:
        return RecognitionResult(rejected="not_fxpa_req")
    if league_id != context.fantrax_league_id:
        return RecognitionResult(rejected="wrong_league")

    if not isinstance(body_json, dict) or not isinstance(body_json.get("responses"), list):
        return RecognitionResult(
            rejected="envelope_unrecognised",
            unrecognised=(
                UnrecognisedShape(
                    keys=_keys_of(body_json),
                    occurrences=1,
                    example_locator="$",
                    reason="envelope_unrecognised",
                ),
            ),
        )

    instants: list[ObservedInstant] = []
    unrecognised: list[UnrecognisedShape] = []
    kind = _kind_for(context.draft_type)

    for index, entry in enumerate(body_json["responses"]):
        locator = f"responses[{index}]"
        if isinstance(entry, dict) and "data" in entry:
            block = entry["data"]
            locator = f"{locator}.data"
        else:
            # Positionally aligned with the request's ``msgs``, so an entry
            # without ``data`` is a shape change worth reporting rather than
            # skipping quietly.
            block = entry
        accepted_here = False
        refusals: list[tuple[str, tuple[str, ...], str]] = []
        for list_locator, records in _candidate_lists(block, locator):
            typed, refusal = _accept_list(records, context)
            if refusal is not None:
                refusals.append((list_locator, _keys_of(records[0] if records else None), refusal))
                continue
            accepted_here = True
            for position, record in enumerate(typed):
                instants.append(
                    _instant_from(
                        record,
                        kind=kind,
                        provenance=InstantProvenance(
                            transport=SourceTransport.BRIDGE_CAPTURE,
                            artifact_key=dedupe_key,
                            recogniser=_BRIDGE_RECOGNISER,
                            received_at=received_at,
                            source_claimed_at=captured_at,
                            locator=f"{list_locator}[{position}]",
                        ),
                    )
                )
        if not accepted_here:
            if refusals:
                list_locator, keys, refusal = refusals[0]
                unrecognised.append(
                    UnrecognisedShape(
                        keys=keys,
                        occurrences=len(refusals),
                        example_locator=list_locator,
                        reason=refusal,
                    )
                )
            else:
                unrecognised.append(
                    UnrecognisedShape(
                        keys=_keys_of(block),
                        occurrences=1,
                        example_locator=locator,
                        reason="no_record_list",
                    )
                )

    return RecognitionResult(
        instants=tuple(instants),
        unrecognised=tuple(unrecognised),
        notes=(
            "The RPC method name is in the request body, which the userscript "
            "never captures, so this recogniser discriminates on content.",
        ),
    )


def recognise_official_draft_picks(
    picks: list[FantraxDraftPick],
    *,
    artifact_key: str,
    received_at: datetime,
    context: RecognitionContext,
) -> RecognitionResult:
    """Read a parsed ``getDraftPicks`` response.

    Parsing is
    :func:`hoops_gm.ingest.fantrax_official.parsers.parse_draft_picks`'s, not
    repeated here — that parser's key-name guesses are already recorded as
    unverified in ``docs/adapters/fantrax-official.md``, and duplicating them
    would give this repository two guesses that can drift apart instead of one.

    The seat anchor is applied here too, for the same reason and with the same
    fail-closed direction: a pick naming a team id this draft does not have a
    seat for is dropped and counted, not attributed.
    """
    anchor_failure = context.anchor_failure()
    if anchor_failure is not None:
        return RecognitionResult(rejected=anchor_failure)

    kind = _kind_for(context.draft_type)
    instants: list[ObservedInstant] = []
    unanchored = 0
    unnamed = 0
    for index, pick in enumerate(picks):
        if pick.team_id not in context.team_external_ids:
            unanchored += 1
            continue
        if not (pick.player_id or pick.player_name):
            unnamed += 1
            continue
        instants.append(
            ObservedInstant(
                kind=kind,
                provenance=InstantProvenance(
                    transport=SourceTransport.OFFICIAL_HTTP,
                    artifact_key=artifact_key,
                    recogniser=_OFFICIAL_RECOGNISER,
                    received_at=received_at,
                    # getDraftPicks publishes no per-pick timestamp. Absent
                    # rather than backfilled from ``received_at``, which would
                    # invent a claim the source never made.
                    source_claimed_at=None,
                    locator=f"draftPicks[{index}]",
                ),
                team_external_id=pick.team_id,
                player_label=pick.player_name,
                player_external_id=pick.player_id,
                overall_pick=pick.overall_pick,
                round_number=pick.round_number,
                pick_in_round=pick.pick_number,
                amount=_as_amount(pick.auction_amount),
            )
        )

    unrecognised: list[UnrecognisedShape] = []
    if unanchored:
        unrecognised.append(
            UnrecognisedShape(
                keys=("teamId",),
                occurrences=unanchored,
                example_locator="draftPicks[].teamId",
                reason="no_seat_anchor",
            )
        )
    if unnamed:
        unrecognised.append(
            UnrecognisedShape(
                keys=("playerId", "playerName"),
                occurrences=unnamed,
                example_locator="draftPicks[]",
                reason="record_names_no_player",
            )
        )
    return RecognitionResult(
        instants=tuple(instants),
        unrecognised=tuple(unrecognised),
        notes=("getDraftPicks has never returned a verified real payload; see the module docs.",),
    )
