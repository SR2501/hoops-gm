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

#: Bridge capture sources that carry rendered HTML rather than an RPC body.
#:
#: Read off ``userscript/src/capture.js``, where ``capturePageSnapshot`` labels
#: its output ``manual-export`` and the settled-view watcher labels its output
#: ``rendered-view``; the raw paths are ``fetch``, ``xhr`` and ``cache-storage``.
#: The userscript README states the boundary in its own words: a rendered view
#: "is never normalized or presented as the JSON response the userscript could
#: not observe". This constant exists so the backend can *report* that
#: distinction, never to blur it.
SNAPSHOT_CAPTURE_SOURCES: Final[frozenset[str]] = frozenset({"rendered-view", "manual-export"})

#: Bridge capture sources that carry a raw RPC body the recogniser can read.
#:
#: The complement of :data:`SNAPSHOT_CAPTURE_SOURCES` within the labels
#: ``userscript/src/capture.js`` emits, listed positively rather than derived by
#: subtraction so that a *new* capture source added upstream does not silently
#: become evidence the data endpoint is being read. A source we have never heard
#: of should not count as proof of life until someone looks at it.
RPC_CAPTURE_SOURCES: Final[frozenset[str]] = frozenset({"fetch", "xhr", "cache-storage"})

#: Candidate key names, **not** verified names.
#:
#: Mostly the same vocabulary
#: :func:`hoops_gm.ingest.fantrax_official.parsers.parse_draft_picks` already
#: uses, so there is one list of guesses in this repository rather than two that
#: can drift. Order is preference order within each field. The one deliberate
#: divergence is ``player_label``, explained below.
#:
#: ``id`` is excluded from the team aliases on purpose. It is the most likely
#: key name in any JSON on the internet and matching it would let an arbitrary
#: list of objects be accepted the moment one of its ``id`` values collided with
#: a Fantrax team id — which turns the anchor from a check into a coincidence.
#:
#: ``name``, ``shortName`` and ``displayName`` are excluded from
#: ``player_label`` for exactly the same reason, and it took an independent
#: review to see it. A **team** object carries those keys. So a ``draftOrder``
#: or standings block — a list of this league's own teams, which is the single
#: most likely list to appear anywhere in a draft-room batch — satisfied the
#: seat anchor *perfectly* (every record resolves to a seat, because every
#: record **is** a seat) and satisfied "names a player" with the team's own
#: name. It was read as a full board of picks, one per seat, with
#: ``player_label="Team Rocket"``. That is not the safe failure this module
#: claims; it is the half-read board it exists to prevent, and with
#: ``apply=true`` it would have become real ``draft_events``.
#:
#: They survive in :data:`AMBIGUOUS_NAME_ALIASES` as a *label of last resort*,
#: usable only once the record has independently identified a player.
FIELD_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "team_external_id": ("teamId", "fantasyTeamId", "franchiseId", "teamID"),
    "player_external_id": ("playerId", "scorerId", "fantasyPlayerId"),
    "player_label": ("playerName", "scorerName", "playerFullName"),
    "amount": ("amount", "bid", "salary", "price", "winningBid"),
    "overall_pick": ("overallPick", "overall"),
    "round_number": ("round", "roundNumber"),
    "pick_in_round": ("pick", "pickNumber", "pickInRound"),
}

#: Names that could belong to a player *or* to a team, and so cannot identify
#: one. Read only for display, and only on a record that some key in
#: ``player_external_id`` or ``player_label`` has already established is about a
#: player. Never sufficient on their own to accept a list.
AMBIGUOUS_NAME_ALIASES: Final[tuple[str, ...]] = ("name", "shortName", "displayName")

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
    records: list[Any], context: RecognitionContext, kind: InstantKind
) -> tuple[list[dict[str, Any]], str | None]:
    """Accept the whole list or none of it, and say why when none.

    The refusals are separate strings rather than one because they mean
    different things to whoever reads the status screen: a length refusal says
    "this is a different kind of collection", an anchor refusal says "the alias
    is wrong or this is another league's data", and an identification refusal
    says "this is about teams but not about players".

    **The seat anchor alone is not a check, and the reason is not obvious.** The
    list that satisfies "every record resolves to a seat of this draft" most
    perfectly is a list of this draft's seats — a ``draftOrder`` block, a
    standings block, a budget table. Those are not exotic; in a draft-room
    batch they are the *likeliest* lists present. So acceptance additionally
    requires each record to identify a **player**, by a key that a team object
    does not carry: an id under :data:`FIELD_ALIASES`\\ ``["player_external_id"]``
    or a name under a player-specific key. A team's own ``name`` no longer
    counts, which is what previously let a list of teams through.

    **"Seat plus player" is still only a shape, and several lists in a draft
    room have that shape.** An independent review demonstrated four against this
    module: a keeper roster, an auction bid history, a waiver claim list, and an
    on-the-clock block. Each was read as the pick log. The consequences are not
    cosmetic — keepers are not picks and would have become real ``draft_events``
    via :func:`apply_observations`, and a bid history would have credited the
    *first* bid on a player as the clearing price. So three further rules, each
    keyed on a property the pick log genuinely has and those lists genuinely
    lack, rather than on a guessed key path:

    * ``record_missing_draft_coordinate`` — every record must carry the
      coordinate its ``kind`` is defined by: an ordinal for a snake selection,
      an amount for an auction sale. A roster row records *that* a player is on
      a team; a pick record records *where in the draft* he was taken, and
      without that this module cannot order the board anyway.

      **This rule is strong on the snake path and weak on the auction path, and
      the difference is not cosmetic.** Under ``SELECTION`` it does exclude a
      keeper roster, because a roster row carries no ordinal. Under ``SALE`` it
      very largely does not: the amount aliases include ``salary`` and ``bid``
      (:data:`FIELD_ALIASES`), and ``salary`` is the *defining field of a keeper
      roster row* while ``bid`` is the defining field of a FAAB waiver claim.
      An independent review drove a priced auction keeper roster end to end and
      it became two real ``draft_events``. **A priced keeper roster and an
      auction sale log are the same tuple**, so there is no structural
      discriminator between them for this module to key on, and this rule does
      not supply one. Said plainly here because an earlier version of this
      docstring claimed it did — and a stated protection that does not exist is
      worse than a known gap, since it is what stops the next reader looking.
    * ``duplicate_player_in_list`` — a pick log never contains the same player
      twice; a bid history contains little else. Cheap, and structural.
    * ``player_identity_is_the_seat`` — a record whose player id equals its own
      team id is a team wearing a player-shaped key, which is the residual case
      the review could still get through. A player is not a team.

    **The cost of these rules is real and is the intended direction.** If a real
    Fantrax pick log turns out not to carry an ordinal, this refuses it and the
    board stays blank — with the refused list's key names published on the
    status endpoint, which makes it a five-minute fix rather than a dead
    evening. That trade is the same one the whole module makes: on draft night a
    blank board you can diagnose beats a populated board that is quietly lying.
    No fixture exists to say which way it will go. See ``docs/handoff.md``.
    """
    if not records or len(records) > MAX_RECORD_LIST:
        return [], "list_length_out_of_range"

    typed = [record for record in records if isinstance(record, dict)]
    if len(typed) != len(records):  # pragma: no cover - _candidate_lists filters this
        return [], "mixed_record_types"

    seen_players: set[str] = set()
    for record in typed:
        team = _as_text(_first(record, "team_external_id"))
        if team is None or team not in context.team_external_ids:
            return [], "no_seat_anchor"
        identity = _player_identity(record)
        if identity is None:
            return [], "record_names_no_player"
        if identity == team:
            return [], "player_identity_is_the_seat"
        if not _has_draft_coordinate(record, kind):
            return [], "record_missing_draft_coordinate"
        if identity in seen_players:
            return [], "duplicate_player_in_list"
        seen_players.add(identity)
    return typed, None


def _has_draft_coordinate(record: dict[str, Any], kind: InstantKind) -> bool:
    """Whether the record positions itself in the draft, per its kind.

    A snake selection is defined by *where* it happened, an auction sale by
    *what it cost*. A record carrying neither may well be about a player on a
    team — a roster, a keeper, a watchlist — but it is not a record of a pick,
    and this module has no way to order it if it were.

    **The test is orderability, not presence, and not parseability either.**
    Two successive reviews moved this line. It first tested presence, and
    ``{"round": "N/A"}`` passed it while :func:`_instant_from` discarded the
    value — a record admitted *because* of a field that was then thrown away.
    Tightening it to parseability fixed that case and left a nearer one:
    ``{"round": 1, "pick": "N/A"}`` parses, so it passed, but
    :func:`~hoops_gm.draft.feed.service._apply_order` needs ``overall_pick``,
    or ``round_number`` **and** ``pick_in_round``, so the row still landed in
    the arrival-order fallback bucket the sort exists to avoid. A review drove
    two such records in the wrong order and the board halted on
    ``draft_pick_out_of_turn`` — zero picks applied, deterministically, with
    the blame attached to turn order rather than to the payload that caused it.

    So this gate requires exactly what the sort requires. A snake board that
    numbers its rounds but not the picks within them is now **refused**, and
    that is deliberate: both readings apply zero picks, and a named
    ``record_missing_draft_coordinate`` count says which payload was unreadable
    while an out-of-turn halt does not.
    """
    if kind is InstantKind.SALE:
        return _as_amount(_first(record, "amount")) is not None
    if _as_int(_first(record, "overall_pick")) is not None:
        return True
    return (
        _as_int(_first(record, "round_number")) is not None
        and _as_int(_first(record, "pick_in_round")) is not None
    )


def _player_identity(record: dict[str, Any]) -> str | None:
    """The record's own claim to be about a player, or ``None``.

    Only unambiguous keys count. :data:`AMBIGUOUS_NAME_ALIASES` is deliberately
    not consulted here — that is the whole distinction, and consulting it would
    restore the defect this split exists to remove.
    """
    return _as_text(_first(record, "player_external_id")) or _as_text(
        _first(record, "player_label")
    )


def _player_label(record: dict[str, Any]) -> str | None:
    """The best display name for a record already known to be about a player.

    Falls back to an ambiguous key only when :func:`_player_identity` has
    already succeeded, which is guaranteed by :func:`_accept_list` running
    first. A record identified solely by ``playerId`` can therefore still show
    a name on the board, without an ambiguous name ever being what let the list
    in.
    """
    label = _as_text(_first(record, "player_label"))
    if label is not None:
        return label
    for alias in AMBIGUOUS_NAME_ALIASES:
        value = record.get(alias)
        if value is not None:
            text = _as_text(value)
            if text is not None:
                return text
    return None


def _instant_from(
    record: dict[str, Any],
    *,
    kind: InstantKind,
    provenance: InstantProvenance,
) -> ObservedInstant:
    """Read one record into the shape its ``kind`` permits.

    The forbidden fields are dropped rather than carried, because the storage
    layer enforces the split as a CHECK constraint and a violated CHECK is not a
    bad row — it aborts the flush, and with it every observation from the same
    run. A snake-league pick carrying ``salary`` (one of our own aliases) or an
    auction sale carrying a round and pick number (which
    ``parse_draft_picks`` populates unconditionally, so the official source
    produces it as a matter of course) would otherwise have made the first real
    ingest of the season return 500 and store nothing at all.

    ``kind`` comes from the draft's own snapshotted format, not from the
    payload, so it is the authoritative side of the disagreement. Dropping is
    still a loss and :class:`RecognitionResult` counts it.
    """
    amount = _as_amount(_first(record, "amount"))
    overall_pick = _as_int(_first(record, "overall_pick"))
    round_number = _as_int(_first(record, "round_number"))
    pick_in_round = _as_int(_first(record, "pick_in_round"))

    if kind is InstantKind.SELECTION:
        amount = None
    else:
        overall_pick = round_number = pick_in_round = None

    return ObservedInstant(
        kind=kind,
        provenance=provenance,
        team_external_id=_as_text(_first(record, "team_external_id")),
        player_label=_player_label(record),
        player_external_id=_as_text(_first(record, "player_external_id")),
        overall_pick=overall_pick,
        round_number=round_number,
        pick_in_round=pick_in_round,
        amount=amount,
    )


_ORDINAL_FIELDS = ("overall_pick", "round_number", "pick_in_round")


def _fields_dropped_for_kind(record: dict[str, Any], kind: InstantKind) -> tuple[str, ...]:
    """The fields this record carried that its ``kind`` forbids, **by name**.

    Named rather than counted because the direction of the loss carries all the
    diagnostic value and the count carries none. A dropped ordinal on an
    auction is the expected shape; a dropped *amount* on a draft recorded as a
    snake means the source published a price for a format that has none. Those
    two produce an identical count and want opposite reactions, which is why
    :attr:`~hoops_gm.draft.feed.service.SourceOutcome.every_instant_coerced`
    cannot be read on its own.
    """
    if kind is InstantKind.SELECTION:
        return ("amount",) if _as_amount(_first(record, "amount")) is not None else ()
    return tuple(name for name in _ORDINAL_FIELDS if _as_int(_first(record, name)) is not None)


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


def league_id_in_page_url(url: str) -> str | None:
    """The league id in a Fantrax *page* URL, as opposed to an RPC URL.

    Page snapshots (``rendered-view``, ``manual-export``) are stored under the
    URL of the page the owner was looking at — ``/fantasy/league/<id>/...`` —
    not under ``/fxpa/req``. :func:`league_id_in` therefore returns ``None`` for
    every one of them, which is correct for its own purpose and is exactly why
    a snapshot of this league's draft room is otherwise indistinguishable from
    a capture belonging to somebody else's league.

    This exists only to attribute a snapshot to a league so the count can be
    *reported*. Nothing reads a snapshot's contents. Rendered HTML is not the
    RPC body and this module does not pretend otherwise.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    parts = [segment for segment in parsed.path.split("/") if segment]
    # ``/fantasy/league/<id>/<view>`` — the id is the segment after "league".
    for index, segment in enumerate(parts[:-1]):
        if segment == "league":
            candidate = parts[index + 1].strip()
            if candidate:
                return candidate
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

    # A Fantrax error arrives with HTTP 200 and a ``pageError`` block rather
    # than a status code — ``fantraxapi``'s own ``_request`` checks for it
    # after the status check, which is where the evidence for this comes from.
    # Naming it is worth the branch: the common cause is an expired cookie, and
    # "you are logged out" and "Fantrax changed its envelope" are otherwise the
    # same string on the screen at the moment the owner has the least time to
    # work out which one he is looking at.
    #
    # Checked **before** the envelope shape, not inside the not-a-list branch
    # where it started. ``fantraxapi`` checks ``"pageError" in response_json``
    # unconditionally, so a reply carrying an error *and* a well-formed
    # ``responses`` list is a shape the pinned client treats as an error and we
    # were treating as ordinary data — reading whatever the list happened to
    # hold and reporting nothing wrong. Being logged out is the one rejection
    # the owner can act on in thirty seconds, and it is the one this ordering
    # was hiding.
    page_error = body_json.get("pageError") if isinstance(body_json, dict) else None
    if isinstance(page_error, dict):
        code = page_error.get("code")
        reason = f"page_error:{code}" if isinstance(code, str) and code else "page_error"
        return RecognitionResult(
            rejected=reason,
            unrecognised=(
                UnrecognisedShape(
                    keys=_keys_of(page_error),
                    occurrences=1,
                    example_locator="$.pageError",
                    reason=reason,
                ),
            ),
        )

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
    coerced = 0
    dropped_names: set[str] = set()

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
            typed, refusal = _accept_list(records, context, kind)
            if refusal is not None:
                refusals.append((list_locator, _keys_of(records[0] if records else None), refusal))
                continue
            accepted_here = True
            for position, record in enumerate(typed):
                dropped = _fields_dropped_for_kind(record, kind)
                if dropped:
                    coerced += 1
                    dropped_names.update(dropped)
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
        coerced_to_kind=coerced,
        fields_dropped=tuple(sorted(dropped_names)),
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

    **This recogniser is deliberately weaker than
    :func:`recognise_bridge_payload`, and reasoning written about that one does
    not transfer.** It applies the seat anchor and a player-name check and
    nothing else — no :func:`_accept_list`, so no
    :func:`_has_draft_coordinate`, no ``duplicate_player_in_list``, no
    ``player_identity_is_the_seat``. It can afford to be, because the shape is
    already typed by ``parse_draft_picks`` rather than guessed from an
    arbitrary JSON block. The consequence is that the *bridge* recogniser
    refuses a payload whose coordinates are missing while this one accepts it
    and reports the loss instead. A round of review found three docstrings in
    this package that argued from "the coordinate rule refuses that" without
    noticing the argument held on one path only; if you are about to write a
    fourth, name the path.
    """
    anchor_failure = context.anchor_failure()
    if anchor_failure is not None:
        return RecognitionResult(rejected=anchor_failure)

    kind = _kind_for(context.draft_type)
    instants: list[ObservedInstant] = []
    unanchored = 0
    unnamed = 0
    coerced = 0
    dropped_names: set[str] = set()
    for index, pick in enumerate(picks):
        if pick.team_id not in context.team_external_ids:
            unanchored += 1
            continue
        if not (pick.player_id or pick.player_name):
            unnamed += 1
            continue
        amount = _as_amount(pick.auction_amount)
        overall_pick = pick.overall_pick
        round_number = pick.round_number
        pick_in_round = pick.pick_number
        # ``parse_draft_picks`` fills the ordinals *and* the amount from the
        # same row unconditionally, so an auction league's own results are the
        # expected shape that violates the storage CHECK. Conform to the kind
        # the draft's snapshotted format dictates, and count the loss.
        if kind is InstantKind.SELECTION:
            if amount is not None:
                coerced += 1
                dropped_names.add("amount")
            amount = None
        else:
            ordinals = tuple(
                name
                for name, value in (
                    ("overall_pick", overall_pick),
                    ("round_number", round_number),
                    ("pick_in_round", pick_in_round),
                )
                if value is not None
            )
            if ordinals:
                coerced += 1
                dropped_names.update(ordinals)
                overall_pick = round_number = pick_in_round = None
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
                overall_pick=overall_pick,
                round_number=round_number,
                pick_in_round=pick_in_round,
                amount=amount,
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
        coerced_to_kind=coerced,
        fields_dropped=tuple(sorted(dropped_names)),
        notes=("getDraftPicks has never returned a verified real payload; see the module docs.",),
    )
