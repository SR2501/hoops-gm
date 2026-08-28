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
``test_draft_feed.py``'s
``test_the_envelope_shape_still_matches_the_pinned_client`` re-reads that
source and fails when it stops saying so, which makes this the one claim here
with a drift check behind it. (This paragraph used to name
``test_draft_feed_contracts.py``, which does not exist and never has — an
unenforced rule wearing the clothes of an enforced one, which is the exact
failure mode this package's reviews keep finding.)

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
ids, for **every** record in the list.

**Read the scope of that carefully: an earlier wording overclaimed it, and a
review caught the overclaim rather than a bug.** What the seat anchor
establishes is *structural* — the value read is one of this draft's configured
team ids. It does **not** establish the *semantic* claim that the field means
"the team that drafted this player". A same-league record using ``teamId`` for
some other role passes every check here and is attributed to a seat that is
real, configured, and not necessarily the buyer. So "never the wrong seat" is
true only in the sense of "never an *unconfigured* seat", and is not a
guarantee that the row is about the draft at all.

What this module therefore does **not** exclude is a block that is correctly
read and is not about this draft: a completed *prior* season's draft results for
the same league would pass every check here, and in an auction league a priced
keeper roster is the same tuple as a sale (``salary`` is one of our own amount
aliases and is the defining field of a keeper row), so no structural rule
available here separates them. Nothing in the payload distinguishes those, so
the caller's admission rules (:mod:`hoops_gm.draft.feed.service`) do what they
can, the auction case is surfaced as a note on the response rather than left in
a docstring nobody reads on draft night, and this limit is stated rather than
papered over.
"""

from __future__ import annotations

import re
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

#: The bounds below are all restatements of a column definition, and they exist
#: because a value this reader *accepts* is a value the storage layer is then
#: obliged to hold. Where those two disagree the failure is not a refused row —
#: it is a raised exception during ``session.flush()``, which aborts every
#: observation captured in the same run. ``_store`` catches ``IntegrityError``
#: (a CHECK it can attribute to one row) and nothing else, so a bind-time
#: ``OverflowError`` or ``DataError`` is a whole-ingest failure mid-draft.
#:
#: Keeping the numbers here rather than catching more broadly is deliberate:
#: the coercers are the one place every stored value passes through, and a
#: bound stated as a constant can be checked against the model by reading two
#: lines. A wider ``except`` would convert a knowable refusal into an
#: unattributable one.

#: ``draft_feed_observations.amount`` is ``Numeric(10, 2)``: eight integer
#: digits and two decimal places. ``Decimal.is_finite()`` admits ``1E+30`` and
#: ``0.001`` — both finite, both positive, neither representable. The first
#: reloads from Postgres as a different number; the second passes an
#: ``amount > 0`` check and reloads as ``0.00``, which is a *free* player shown
#: as sold.
MAX_AMOUNT: Final = Decimal("99999999.99")
_CENT: Final = Decimal("0.01")

#: Draft coordinates are plain :class:`~sqlalchemy.Integer` columns, and this
#: bound is **the column's, not Python's**. JSON ``1e100`` — whose
#: ``is_integer()`` is ``True`` — becomes a 101-digit Python ``int`` that raises
#: on bind, so some ceiling is needed; the question is which.
#:
#: An earlier version of this said "SQLite and Postgres both cap a bound integer
#: at signed 64 bits, and that is not readable off the model", and set
#: ``2**63 - 1``. **Both halves were wrong.** SQLAlchemy's ``Integer`` compiles
#: to Postgres ``INTEGER``, which is signed *32* bits, so everything from
#: ``2147483648`` up cleared this guard and overflowed on the engine ADR-001
#: exists to protect. And it *is* readable off the model — by compiling the
#: column's type under the Postgres dialect, which is what
#: ``test_every_bounded_column_this_path_writes_has_a_guard_derived_from_it``
#: now does rather than restating a number.
#:
#: This is the same defect as the text bounds beside it wearing a different
#: type: a value the reader accepts that the storage layer then cannot hold,
#: failing on Postgres and passing in every SQLite test.
MAX_COORDINATE: Final = 2**31 - 1

#: ``player_label`` is ``String(128)``; the external ids are ``String(64)``.
#: This bound is the one that does not fail the same way on both engines:
#: SQLite ignores a ``VARCHAR`` length entirely, so an over-long name stores
#: cleanly in the test suite and raises ``DataError`` on Postgres. Over-long
#: text is read as *absent* rather than truncated, because a truncated name is
#: a wrong name and the identity gates already refuse a record that has none.
MAX_LABEL_CHARS: Final = 128
MAX_EXTERNAL_ID_CHARS: Final = 64

#: ``draft_feed_observations.locator`` is ``String(128)``, and unlike the other
#: bounds here the value is not a field of a record — it is the *path this walk
#: took to reach one*, built from the payload's own key names. Six levels of
#: realistic Fantrax naming (``responses[0].data.draftRoomState...``) reaches
#: this comfortably, so it is not an exotic input.
#:
#: An over-long path is refused rather than truncated, and that is the whole
#: reason this is a separate rule instead of a call to :func:`_as_text`:
#: ``locator`` is a third of the idempotency key ``(transport, artifact_key,
#: locator)``. Two distinct paths truncated to the same 128 characters become
#: the same row, and the second pick of the two is then silently discarded as
#: a duplicate — a *missing pick* on the board rather than a reported refusal.
MAX_LOCATOR_CHARS: Final = 128

#: ``draft_feed_observations.artifact_key`` is ``String(128)`` and is filled on
#: the bridge path from ``bridge_payloads.dedupe_key``, which is ``TEXT`` —
#: **unbounded**. That mismatch spans two tables owned by two different units,
#: so neither model is wrong on its own and reading either one alone would not
#: show it. The userscript chooses the value, so this is the one bound here
#: that a *cooperating* component can breach by accident.
MAX_ARTIFACT_KEY_CHARS: Final = 128

#: A numeric field arriving as a *string* is parsed against these, not handed
#: straight to ``int()`` or ``Decimal()``.
#:
#: **Both of those implement Python's literal grammar, which is wider than any
#: grammar a JSON producer emits**, and the widening is silent rather than
#: erroneous. Measured on this module: ``"1_0"`` read as ``10`` (PEP 515
#: underscore separators), and ``"١٢"`` — Arabic-Indic digits — read as ``12``,
#: because ``int()`` accepts every Unicode ``Nd`` character. ``Decimal`` is
#: looser still and took ``"_10"``, ``"1__0"`` and ``"10_"`` as ``10``; one of
#: those was applied as a completed sale at ``10.00`` with nothing reported.
#:
#: None of those is a misreading of a price or a position. Each is this reader
#: *inventing* a number from a string, and then presenting it with the same
#: confidence as one it read — which is the failure this whole module is shaped
#: to avoid. Refusing them costs nothing a real payload would notice: a JSON
#: number arrives as ``int`` or ``float`` and never touches these.
#:
#: Deliberately narrow. No currency symbol, no thousands separator, no leading
#: ``+``, no exponent. Widening any of them means someone has *seen* Fantrax
#: emit it, which is a different state of knowledge from guessing that it might.
_ASCII_ORDINAL: Final = re.compile(r"\A[0-9]+\Z")
_ASCII_DECIMAL: Final = re.compile(r"\A[0-9]+(?:\.[0-9]+)?\Z")

#: Length ceilings applied *before* conversion, derived from the bounds above.
#: Python 3.11+ raises ``ValueError`` converting an ``int`` from a string past
#: 4300 digits and ``Decimal`` will happily build a megabyte-wide number, so a
#: digit string is refused on width before either is asked to parse it.
_MAX_ORDINAL_DIGITS: Final = len(str(MAX_COORDINATE))
_MAX_AMOUNT_CHARS: Final = len(str(MAX_AMOUNT))

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


def _locator_fits(list_locator: str, count: int) -> bool:
    """Whether every locator this list will produce fits its column.

    Checked once for the list rather than per record, using the widest index
    it will reach, because admission in this module is a property of the whole
    list and a half-stored list is worse than a refused one.
    """
    widest = f"{list_locator}[{max(count - 1, 0)}]"
    return len(widest) <= MAX_LOCATOR_CHARS


class _Unreadable:
    """A field that was **present and could not be read**.

    Distinct from ``None``, which means *absent*, and the distinction is the
    whole of one defect. :func:`_as_text` collapses the two, which is right for
    a caller that only wants a value and wrong for a caller that will otherwise
    go looking for a *different* field.

    A review put a 129-character ``playerName`` beside a ``name`` of
    ``"Seat One"``. ``_as_text`` refused the first, :func:`_player_label` read
    that refusal as "no explicit name here", fell through to the ambiguous
    alias, and the pick was applied with ``player_label='Seat One'`` — the
    seat's own name on the board as the player taken. Nothing was reported: the
    record still had an id, so it was accepted, and the count of unrecognised
    shapes was zero.

    The failure is not that a name was lost. It is that a *substitute* was
    supplied, from a key this module already classifies as ambiguous, and
    presented with the same confidence as a real one.
    """

    __slots__ = ()


#: Singleton for the above; compared with ``is``.
UNREADABLE: Final = _Unreadable()


def _read_text(value: Any, *, limit: int) -> str | _Unreadable | None:
    """Text, :data:`UNREADABLE`, or ``None`` for absent.

    The three-way version of :func:`_as_text`. Use it wherever a refusal must
    not be mistaken for an absence — which is anywhere a fallback follows.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return UNREADABLE
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or len(stripped) > limit:
            return UNREADABLE
        return stripped
    if isinstance(value, int | float):
        rendered = str(value)
        return rendered if len(rendered) <= limit else UNREADABLE
    return UNREADABLE


def _as_text(value: Any, *, limit: int) -> str | None:
    """Text short enough for the column it is bound for, or ``None``.

    ``limit`` is required rather than defaulted because the defect this closes
    is an *unbounded* call site, and a default is exactly the thing that lets
    the next one be added silently. Pass :data:`MAX_LABEL_CHARS` or
    :data:`MAX_EXTERNAL_ID_CHARS`; both are restatements of a column.

    Over-long text reads as **absent**, never truncated. ``"Nikola Jokic"``
    cut to fit is still a name and would be stored as one; the identity gates
    already know what to do with a record that has no name at all, and they
    report it by name.

    **This collapses "absent" and "present but refused" into one answer**, which
    is safe for a caller that stores the result and unsafe for one that falls
    back to another key. Those callers use :func:`_read_text`. See
    :class:`_Unreadable` for what went wrong when they did not.
    """
    read = _read_text(value, limit=limit)
    return read if isinstance(read, str) else None


def _is_integral(value: float | Decimal) -> bool:
    """Whether a non-``int`` number sits exactly on an integer."""
    if isinstance(value, float):
        return value.is_integer()
    return value.is_finite() and value == value.to_integral_value()


def _as_int(value: Any) -> int | None:
    """A draft coordinate: an exact, one-indexed, storable ordinal, or ``None``.

    Every call site is a coordinate — ``overall_pick``, ``round_number``,
    ``pick_in_round`` — so this applies the coordinate's rules rather than a
    general integer coercion's. Check that before widening it: the tightening
    below is wrong for a count and right for a position.

    **Exact, because truncating invents a coordinate instead of failing to read
    one.** ``int(1.9)`` is ``1``. A review drove ``overallPick: 1.9`` through
    the recogniser and got one instant at ``overall_pick == 1`` with **no
    unrecognised shape reported** — a board placing a pick at a position no
    payload claimed, carrying a clean bill of health. Two such rows, ``1.9``
    and ``1.1``, collide on pick 1. A float that *is* integral (``2.0``, which
    is how JSON often delivers a whole number) is still accepted.

    The integrality test covers ``Decimal`` as well as ``float``, because the
    first version of it tested ``float`` alone and ``int(Decimal("1.9"))`` is
    also ``1`` — the same defect surviving inside its own fix. ``Decimal`` is
    not reachable from :mod:`json`, which yields only ``int`` and ``float``;
    the guard is here because the annotation is ``Any`` and the cost of being
    wrong about that reachability is a silently relocated pick.

    **Positive, because the coordinate is one-indexed.** ``0`` and negatives
    parsed here and were refused later by the database CHECK, surfacing as a
    generic ``observations_rejected`` rather than the named
    ``record_missing_draft_coordinate`` that :func:`_has_draft_coordinate`
    promises. Same records refused either way; only one of the two tells the
    owner which payload was unreadable.

    **Bounded, because past :data:`MAX_COORDINATE` the failure stops being a
    refusal.** JSON ``1e100`` has ``is_integer() == True``, so it clears the
    exactness test, becomes a 101-digit ``int``, and raises ``OverflowError``
    when SQLAlchemy binds it — outside the ``IntegrityError`` that ``_store``
    handles, so the *entire* ingest fails instead of one row being counted and
    skipped. A number too large to be a pick is refused where it is read.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float | Decimal):
        if not _is_integral(value):
            return None
        parsed = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        # Grammar before conversion: see ``_ASCII_ORDINAL``. ``int()`` accepts
        # underscore separators and non-ASCII digits, and does so silently.
        if len(stripped) > _MAX_ORDINAL_DIGITS or not _ASCII_ORDINAL.match(stripped):
            return None
        parsed = int(stripped)
    else:
        return None
    return parsed if 1 <= parsed <= MAX_COORDINATE else None


def _as_amount(value: Any) -> Decimal | None:
    """A price the ``Numeric(10, 2)`` column can actually hold, or ``None``.

    Via ``str`` rather than ``Decimal(float)``: a JSON ``41.1`` becomes
    ``41.100000000000001421...`` through the float constructor, and this number
    goes into ``draft_events.amount``, which is ``Numeric(10, 2)``. A clearing
    price is money and money does not round-trip through binary floating point.

    **The non-finite check is load-bearing and the ``try`` does not cover it.**
    ``Decimal("NaN")`` *constructs* — it is a valid Decimal — so it leaves the
    ``try`` intact and then raises ``InvalidOperation`` on the ``> 0``
    comparison below, one line outside the handler. A review put
    ``"winningBid": "NaN"`` in a captured payload and recognition **raised**,
    where the contract is that an unreadable field yields ``None`` and a named
    count. ``Decimal("Infinity")`` is worse and was missed by that review: it
    compares greater than zero perfectly happily, so it was returned as a
    *valid price* and carried to a ``Numeric(10, 2)`` column.

    **Finite is not the same as representable, and that gap was the whole of
    the previous fix's remaining hole.** ``is_finite()`` is true for both
    ``1E+30`` and ``0.001``. Measured against the real model: the first
    reloads as ``1000000000000000019884624838656.00`` and the second passes
    ``amount > 0``, is stored, and **reloads as** ``0.00`` — a player the owner
    watched sell shown at no price, on the source that carries the prices.
    Neither is a bid, and rounding either into range would be this reader
    inventing a number rather than reading one.

    This is a fail-closed reader of arbitrary JSON from an undocumented
    endpoint. ``NaN``, ``Infinity``, ``1E+30`` and sub-cent dust are exactly
    the kind of thing such a source emits, and none of them is a price.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        # Grammar before conversion: see ``_ASCII_DECIMAL``. ``Decimal`` is the
        # looser of the two constructors and took ``"_10"`` as ten.
        stripped = value.strip()
        if len(stripped) > _MAX_AMOUNT_CHARS or not _ASCII_DECIMAL.match(stripped):
            return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite():
        return None
    if not 0 < amount <= MAX_AMOUNT:
        return None
    # Order matters: ``quantize`` raises ``InvalidOperation`` above the column's
    # digit budget, so the magnitude bound has to clear first.
    if amount != amount.quantize(_CENT):
        return None
    return amount


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
) -> tuple[list[tuple[int, dict[str, Any]]], str | None, list[tuple[int, dict[str, Any]]]]:
    """Accept the list, refuse it, or accept it minus the rows it cannot read.

    Returns ``(admitted, refusal, unreadable)``. The third element is the reason
    this returns three things instead of two, and it separates two questions
    that were one until a review drove them apart:

    * **"This is not a pick log."** Every refusal below is evidence about the
      *kind* of list — a standings table, a keeper roster, another league's
      data. One bad record is enough to conclude it, and refusing the whole list
      is the point: the discriminator is what keeps a priced keeper roster off
      the board.
    * **"This is a pick log and I cannot read one row of it."** An unreadable
      ``playerId`` says nothing about the other records. Refusing the list on
      its account discards picks this module read perfectly well.

    Conflating those cost the whole board. **Fantrax republishes the entire
    pick list on every pick**, so a single malformed historical row is present
    in *every* subsequent capture, and "the next capture is seconds away" never
    arrives. Driven: one 5,000-character ``playerId`` in a three-record board
    produced ``observations_written=0`` on both captures, no stored rows at all,
    and a status screen reading ``pending=0 blocked=() skipped=()`` -- which is
    byte-identical to what a draft that has not started yet looks like. **The
    owner has no manual fallback**, so that is the tool going permanently blind
    from one row it could have simply left out.

    **The unreadable rows are now returned with their positions and become
    stored observations carrying a ``skipped_reason``**, rather than being
    reported only as a count. Reporting them was not enough: ``unrecognised``
    reaches the ``POST`` ingest response and ``FeedStatus`` has no such field,
    so a live board polling ``GET`` saw a clean feed while being short a
    player. That is the failure the owner named as disqualifying, and it is
    ``draft-feed-unreadable-id-surfacing`` in ``docs/backlog.md``. The count is
    still published beside the rows, because only the count carries the block's
    *key names*, which is what a five-minute fix needs.

    **Storing them is defensible here and would not be for a refused list**, and
    the difference is what has been established. A list reaches this return
    having had at least one record satisfy every admission rule, so it *is* a
    pick log and the board *is* short exactly these rows. A list whose records
    are all unreadable is refused instead — nothing about it establishes it was
    a pick log at all, and writing observations for records in a list that may
    be a standings block would put unfounded rows on the status screen,
    indistinguishable from real missing picks. That case is reported on the
    ``POST`` response only, and is named in ``docs/handoff.md`` rather than
    quietly claimed closed.

    The admitted records carry their **original index**, not their index among
    the survivors. Renumbering them would change a pick's ``locator`` the day
    the malformed row beside it became readable, and ``locator`` is a third of
    the identity ``(transport, artifact_key, locator)`` this feed dedupes on --
    so the same pick would store a second time as a new observation. The
    unreadable rows carry theirs for the same reason and one more: their
    locator has to name a slot no *admitted* record can also claim, or the two
    would collide on the unique constraint.

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
        return [], "list_length_out_of_range", []

    typed = [record for record in records if isinstance(record, dict)]
    if len(typed) != len(records):  # pragma: no cover - _candidate_lists filters this
        return [], "mixed_record_types", []

    seen_players: set[str] = set()
    admitted: list[tuple[int, dict[str, Any]]] = []
    unreadable: list[tuple[int, dict[str, Any]]] = []
    for position, record in enumerate(typed):
        team = _as_text(_first(record, "team_external_id"), limit=MAX_EXTERNAL_ID_CHARS)
        if team is None or team not in context.team_external_ids:
            return [], "no_seat_anchor", []
        identity = _player_identity(record)
        if isinstance(identity, _Unreadable):
            # Held back rather than admitted, and held back rather than
            # dropped. See this function's docstring: a row whose id this
            # module cannot read is not evidence about the other rows, and it
            # is also not nothing.
            unreadable.append((position, record))
            continue
        if identity is None:
            return [], "record_names_no_player", []
        if identity == team:
            return [], "player_identity_is_the_seat", []
        if not _has_draft_coordinate(record, kind):
            return [], "record_missing_draft_coordinate", []
        if identity in seen_players:
            return [], "duplicate_player_in_list", []
        seen_players.add(identity)
        admitted.append((position, record))
    if not admitted:
        return [], "player_external_id_unreadable", []
    return admitted, None, unreadable


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

    A third review then moved the line again, without touching this function:
    the gate is only as strict as :func:`_as_int`, which truncated ``1.9`` to
    pick 1 and admitted ``0``. "Orderable" has to mean *exactly and validly*
    ordered, or the gate reports a coordinate the payload never claimed. The
    rule now lives in the coercer, where every caller gets it.
    """
    if kind is InstantKind.SALE:
        return _as_amount(_first(record, "amount")) is not None
    if _as_int(_first(record, "overall_pick")) is not None:
        return True
    return (
        _as_int(_first(record, "round_number")) is not None
        and _as_int(_first(record, "pick_in_round")) is not None
    )


def _player_identity(record: dict[str, Any]) -> str | _Unreadable | None:
    """The record's own claim to be about a player, or why there isn't one.

    Only unambiguous keys count. :data:`AMBIGUOUS_NAME_ALIASES` is deliberately
    not consulted here — that is the whole distinction, and consulting it would
    restore the defect this split exists to remove.

    **This is a caller that falls back to another key**, which is precisely the
    caller :func:`_as_text` documents as unsafe for itself. It used
    :func:`_as_text` anyway, so a record supplying a ``playerId`` this module
    could not read — over the column's 64 characters, or a list, dict or bool —
    fell straight through to the label and stored ``None``, making *supplied
    but refused* indistinguishable from *never supplied*.

    Driven before the fix: two captures naming the same 5,000-character
    ``playerId`` under ``"Nikola Jokic"`` and ``"The Joker"`` both applied, the
    seat held one player twice and ``remaining_budget`` read ``100.00`` where
    ``150.00`` was correct — with nothing blocked, nothing skipped, and
    ``fields_dropped`` naming only the ordinal. The identity guard added the
    round before could not fire, because by the time it looked the evidence it
    needed had been erased here.

    So the unreadable case is returned as itself. The list admission refuses the
    capture and names the field, which loses a scan and is the trade this module
    makes everywhere: a blank board you can diagnose beats a populated one that
    is quietly lying.
    """
    external = _read_text(_first(record, "player_external_id"), limit=MAX_EXTERNAL_ID_CHARS)
    if isinstance(external, str):
        return external
    if _first(record, "player_external_id") is not None:
        return external
    return _as_text(_first(record, "player_label"), limit=MAX_LABEL_CHARS)


def _player_label(record: dict[str, Any]) -> str | None:
    """The best display name for a record already known to be about a player.

    Falls back to an ambiguous key only when :func:`_player_identity` has
    already succeeded, which is guaranteed by :func:`_accept_list` running
    first. A record identified solely by ``playerId`` can therefore still show
    a name on the board, without an ambiguous name ever being what let the list
    in.

    **The fallback is conditional on the explicit key being absent, not on it
    being unusable.** A ``playerName`` that is present and refused means this
    record *does* carry an explicit claim about the player and this module
    could not read it; substituting ``name`` there does not recover the claim,
    it replaces it with a different one. In the case that surfaced this, the
    different one was the seat's own name. So a refused explicit label yields
    ``None`` — the pick is still recorded against the right seat and the right
    player id, with no name, which is a visible gap rather than a wrong name.

    The same rule applies to the ambiguous aliases among themselves: the first
    one *present* decides, whether or not it is readable. Otherwise a refused
    ``name`` would fall through to ``shortName`` and reintroduce the substitution
    one key along.
    """
    explicit = _read_text(_first(record, "player_label"), limit=MAX_LABEL_CHARS)
    if explicit is not None:
        return explicit if isinstance(explicit, str) else None
    for alias in AMBIGUOUS_NAME_ALIASES:
        if record.get(alias) is None:
            continue
        text = _read_text(record[alias], limit=MAX_LABEL_CHARS)
        return text if isinstance(text, str) else None
    return None


def _instant_from(
    record: dict[str, Any],
    *,
    kind: InstantKind,
    provenance: InstantProvenance,
    skipped_reason: str | None = None,
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

    **``skipped_reason`` changes what the record is allowed to claim, and that
    is the whole difference between the two callers.** A skipped record stores
    **no player label and no player id**. The id is the field that failed; the
    label is withheld deliberately, on two grounds.

    :func:`_player_label` is documented as the name for "a record already known
    to be about a player", and its fallback to
    :data:`AMBIGUOUS_NAME_ALIASES` is safe *because* :func:`_player_identity`
    has already succeeded. On a skipped record it has not — it returned
    :data:`UNREADABLE` — so the precondition that fallback rests on is absent,
    and taking the ambiguous key anyway is how a seat's own name once reached
    the board as the player taken.

    And withholding even an *explicit*, readable ``playerName`` is what makes
    "a refused record never joins identity matching" true by construction: a
    row naming nobody has no
    :func:`~hoops_gm.draft.feed.observations.matching_key`, so no rule has to
    remember to exclude it. The cost is real and is the intended direction —
    the status screen says the board is short a record at seat ``t1`` rather
    than naming the player. A name attached to a record whose identity this
    module refused is a claim it is not entitled to make, and this package's
    position everywhere else is that visibly absent beats confidently wrong.

    That is why such a row names no player at all, which is what the
    ``feed_names_a_player`` CHECK forbade until migration ``0021`` admitted it
    for rows that carry a reason.
    """
    amount = _as_amount(_first(record, "amount"))
    overall_pick = _as_int(_first(record, "overall_pick"))
    round_number = _as_int(_first(record, "round_number"))
    pick_in_round = _as_int(_first(record, "pick_in_round"))

    if kind is InstantKind.SELECTION:
        amount = None
    else:
        overall_pick = round_number = pick_in_round = None

    if skipped_reason is not None:
        return ObservedInstant(
            kind=kind,
            provenance=provenance,
            team_external_id=_as_text(
                _first(record, "team_external_id"), limit=MAX_EXTERNAL_ID_CHARS
            ),
            overall_pick=overall_pick,
            round_number=round_number,
            pick_in_round=pick_in_round,
            amount=amount,
            skipped_reason=skipped_reason,
        )

    return ObservedInstant(
        kind=kind,
        provenance=provenance,
        team_external_id=_as_text(_first(record, "team_external_id"), limit=MAX_EXTERNAL_ID_CHARS),
        player_label=_player_label(record),
        player_external_id=_as_text(
            _first(record, "player_external_id"), limit=MAX_EXTERNAL_ID_CHARS
        ),
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

    if len(dedupe_key) > MAX_ARTIFACT_KEY_CHARS:
        return RecognitionResult(
            rejected="artifact_key_too_long_to_record",
            unrecognised=(
                UnrecognisedShape(
                    keys=(),
                    occurrences=1,
                    example_locator="$",
                    reason="artifact_key_too_long_to_record",
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
        shape_refusals: list[tuple[str, tuple[str, ...], str]] = []
        capacity_refusals: list[tuple[str, tuple[str, ...], str]] = []
        for list_locator, records in _candidate_lists(block, locator):
            if not _locator_fits(list_locator, len(records)):
                capacity_refusals.append(
                    (
                        list_locator,
                        _keys_of(records[0] if records else None),
                        "locator_too_long_to_record",
                    )
                )
                continue
            typed, refusal, unreadable = _accept_list(records, context, kind)
            if refusal is not None:
                shape_refusals.append(
                    (list_locator, _keys_of(records[0] if records else None), refusal)
                )
                continue
            accepted_here = True
            if unreadable:
                # Reported here rather than through ``shape_refusals`` because
                # this list *was* accepted, and the suppression below would
                # therefore swallow it entirely. A dropped record is a missing
                # pick; the count is the number of rows this board is short.
                #
                # The count alone was not enough, and that is
                # ``draft-feed-unreadable-id-surfacing``: it reaches the ``POST``
                # ingest response and ``FeedStatus`` has no such field, so a
                # board polling ``GET`` read clean while missing a player. The
                # rows below are the surfacing; this stays because only it
                # carries the block's key names.
                unrecognised.append(
                    UnrecognisedShape(
                        keys=_keys_of(unreadable[0][1]),
                        occurrences=len(unreadable),
                        example_locator=list_locator,
                        reason="player_external_id_unreadable",
                    )
                )
            for position, record in typed:
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
            for position, record in unreadable:
                # After the admitted records, so the picks a capture *did*
                # yield keep the lower observation ids. Nothing depends on
                # that -- a refused row is never pending, never reconciled and
                # never a tie-break for anything -- and it is done this way so
                # a person reading the table sees the board before the
                # refusals rather than a refusal at row one.
                #
                # Stored at the same locator scheme the admitted records use,
                # so a republished capture dedupes against it instead of
                # writing a second copy, and so it can never collide with an
                # admitted record's slot.
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
                        skipped_reason="player_external_id_unreadable",
                    )
                )
        # A capacity refusal is reported whatever else happened in this entry.
        #
        # The suppression below is right for a *shape* refusal and wrong for
        # this one, and the difference is which side the fault is on. Walking a
        # draft-room block finds many lists that are simply not the pick log —
        # a standings table, a budget block — and each returns ``no_seat_anchor``
        # or ``record_names_no_player``. Reporting those once something was
        # accepted would bury the screen in noise about lists nobody wanted.
        #
        # ``locator_too_long_to_record`` says the opposite: this list may well
        # be the pick log, and *this module* cannot write down where it found
        # it. A review showed one shallow accepted list silencing exactly that
        # about a deep one — recognition returned ``unrecognised []`` and
        # ``rejected None`` while the deeper list's records went nowhere. A
        # missing pick reported as nothing, which is the failure mode this
        # refusal exists to prevent, defeated by the channel it reports on.
        for list_locator, keys, refusal in capacity_refusals:
            unrecognised.append(
                UnrecognisedShape(
                    keys=keys,
                    occurrences=1,
                    example_locator=list_locator,
                    reason=refusal,
                )
            )
        if not accepted_here and not capacity_refusals:
            if shape_refusals:
                list_locator, keys, refusal = shape_refusals[0]
                unrecognised.append(
                    UnrecognisedShape(
                        keys=keys,
                        occurrences=len(shape_refusals),
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

    **One of those guesses has since been settled, and it was wrong.** The live
    read on 2026-08-28 returned ``{"currentDraftPicks":[]}``; the parser had
    been looking for ``draftPicks`` or ``picks``. The *container* key is now
    verified. Every **per-record** field name this reader consumes —
    ``teamId``, ``playerId``, ``round``, ``overallPick``, an auction ``amount``
    — remains a guess, because no populated row has ever been observed on this
    path. Do not read "verified live" in the adapter doc as covering them.

    **That argument is about key names and does not extend to values.**
    Inheriting the parser also inherits how it *converts* what it finds, and
    that half is not free: see the falsified-justification note at the end of
    this docstring. The two are separable in principle — this reader could take
    the raw records and keep one set of key-name guesses — and doing so is the
    only construction that closes the class. It is an architecture change across
    two units, so it is escalated rather than made here.

    The seat anchor is applied here too, for the same reason and with the same
    fail-closed direction: a pick naming a team id this draft does not have a
    seat for is dropped and counted, not attributed.

    **This recogniser is deliberately weaker than
    :func:`recognise_bridge_payload`, and reasoning written about that one does
    not transfer.** It applies the seat anchor and a player-name check and
    nothing else — no :func:`_accept_list`, so no
    :func:`_has_draft_coordinate`, no ``duplicate_player_in_list``, no
    ``player_identity_is_the_seat``. The consequence is that the *bridge*
    recogniser refuses a payload whose coordinates are missing while this one
    accepts it and reports the loss instead. A round of review found three
    docstrings in this package that argued from "the coordinate rule refuses
    that" without noticing the argument held on one path only; if you are about
    to write a fourth, name the path.

    **What this docstring used to say, and why it was wrong.** It justified the
    weakness with "it can afford to be, because the shape is already typed by
    ``parse_draft_picks`` rather than guessed from an arbitrary JSON block".
    Round 8 falsified that by execution. Being typed by that parser is not a
    safety property, because the parser *normalises before this reader sees
    anything*: it converts with a bare ``int()``/``float()``/``str()`` and
    selects aliases with a truthy ``or`` chain. Measured, on the real chain::

        {"overallPick": 1.9}              -> overall_pick=1     (bridge refuses)
        {"overallPick": "1_0"}            -> overall_pick=10    (bridge refuses)
        {"overallPick": 0, "overall": 3}  -> overall_pick=3     (bridge refuses)
        {"amount": 0, "bid": 10}          -> amount=10.0        (bridge refuses)

    Every one of those is *already* a plain, in-range, exactly-typed value by
    the time the coercers above run, so they pass — and they pass **because**
    the damage was done upstream, not in spite of it. The round-7 fix that
    routed every field through the coercers is therefore real but bounded: it
    closes the asymmetry at the typed-dataclass layer, and **not** across the
    raw source. The coercers cannot recover information that no longer exists.

    That defect lives in
    :mod:`hoops_gm.ingest.fantrax_official.parsers`, which this unit does not
    own, and it is filed rather than patched here. **Do not add a "the parser
    validates that" clause to this docstring.** It does not.
    """
    anchor_failure = context.anchor_failure()
    if anchor_failure is not None:
        return RecognitionResult(rejected=anchor_failure)

    kind = _kind_for(context.draft_type)
    instants: list[ObservedInstant] = []
    unanchored = 0
    unnamed = 0
    coerced = 0
    unreadable = 0
    unreadable_fields: set[str] = set()
    dropped_names: set[str] = set()
    for index, pick in enumerate(picks):
        # Every field below goes through the same coercers as the bridge path.
        #
        # **This is the round-4 asymmetry one layer down.** That round closed a
        # difference in how the two recognisers *admitted a list*; this one was
        # a difference in how they *read a field*, and it survived because the
        # reviews kept re-reading admission. ``parse_draft_picks`` returns a
        # typed dataclass, and being typed was mistaken for being bounded: its
        # ``int | None`` is a Python ``int``, and a Python ``int`` is arbitrary
        # precision. Measured here, ``overallPick: 1e100`` arrived as a
        # 101-digit ``int``, was recognised without comment, and raised
        # ``OverflowError`` binding to SQLite — outside the ``IntegrityError``
        # ``_store`` handles, so the whole ingest, not the row. A 129-character
        # ``playerName`` and a 65-character ``playerId`` likewise stored on
        # SQLite and would have raised ``DataError`` on Postgres.
        team_external_id = _as_text(pick.team_id, limit=MAX_EXTERNAL_ID_CHARS)
        if team_external_id is None or team_external_id not in context.team_external_ids:
            unanchored += 1
            continue
        player_external_id = _as_text(pick.player_id, limit=MAX_EXTERNAL_ID_CHARS)
        player_label = _as_text(pick.player_name, limit=MAX_LABEL_CHARS)
        amount = _as_amount(pick.auction_amount)
        overall_pick = _as_int(pick.overall_pick)
        round_number = _as_int(pick.round_number)
        pick_in_round = _as_int(pick.pick_number)
        # A field the source supplied and this reader refused is a loss, and an
        # unreported loss on this path is indistinguishable from the source
        # never having sent it. Counted by name so the status screen can say
        # which one.
        lost = tuple(
            field
            for field, supplied, read in (
                ("player_external_id", pick.player_id, player_external_id),
                ("player_label", pick.player_name, player_label),
                ("amount", pick.auction_amount, amount),
                ("overall_pick", pick.overall_pick, overall_pick),
                ("round_number", pick.round_number, round_number),
                ("pick_in_round", pick.pick_number, pick_in_round),
            )
            if supplied is not None and read is None
        )
        if lost:
            unreadable += 1
            unreadable_fields.update(lost)
        skipped_reason: str | None = None
        if not (player_external_id or player_label):
            unnamed += 1
            # **Recorded rather than dropped**, and this is the mirror of the
            # bridge path's ``player_external_id_unreadable`` surfacing. Round
            # eight of this unit found three arguments that held on one path
            # only, so the same defect is closed on both: dropping here left a
            # record the source published for one of *our* seats visible on the
            # ``POST`` response and nowhere on ``GET``, which is a pick that
            # happened reported as nothing.
            #
            # The two reasons are kept apart because they call for different
            # reactions. A refused identity means the source named someone and
            # this reader could not read it -- the board is short a pick. A
            # record naming nobody at all may simply be an unmade future pick,
            # which is not a loss, and calling it one would teach the owner to
            # dismiss the count.
            skipped_reason = (
                "player_external_id_unreadable"
                if pick.player_id is not None or pick.player_name is not None
                else "record_names_no_player"
            )
        # ``parse_draft_picks`` fills the ordinals *and* the amount from the
        # same row unconditionally, so an auction league's own results are the
        # expected shape that violates the storage CHECK. Conform to the kind
        # the draft's snapshotted format dictates, and count the loss.
        #
        # A skipped record is conformed but **not counted**: ``coerced_to_kind``
        # is read against ``instants_recognised``, which excludes skipped rows,
        # and ``every_instant_coerced`` compares the two. Counting one side and
        # not the other is how a rate becomes nonsense.
        if kind is InstantKind.SELECTION:
            if amount is not None and skipped_reason is None:
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
                if skipped_reason is None:
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
                    locator=f"getDraftPicks[{index}]",
                ),
                team_external_id=team_external_id,
                player_label=player_label,
                player_external_id=player_external_id,
                overall_pick=overall_pick,
                round_number=round_number,
                pick_in_round=pick_in_round,
                amount=amount,
                skipped_reason=skipped_reason,
            )
        )

    unrecognised: list[UnrecognisedShape] = []
    if unanchored:
        unrecognised.append(
            UnrecognisedShape(
                keys=("teamId",),
                occurrences=unanchored,
                example_locator="getDraftPicks[].teamId",
                reason="no_seat_anchor",
            )
        )
    if unnamed:
        unrecognised.append(
            UnrecognisedShape(
                keys=("playerId", "playerName"),
                occurrences=unnamed,
                example_locator="getDraftPicks[]",
                reason="record_names_no_player",
            )
        )
    if unreadable:
        # Not ``rejected``: these picks were still recorded, minus a field. The
        # count exists so "the board shows no price for that sale" has an
        # answer other than "the source did not send one".
        unrecognised.append(
            UnrecognisedShape(
                keys=tuple(sorted(unreadable_fields)),
                occurrences=unreadable,
                example_locator="getDraftPicks[]",
                reason="field_too_large_to_record",
            )
        )
    return RecognitionResult(
        instants=tuple(instants),
        unrecognised=tuple(unrecognised),
        coerced_to_kind=coerced,
        fields_dropped=tuple(sorted(dropped_names)),
        notes=(
            "getDraftPicks was verified reachable on 2026-08-28 and returned "
            "an empty list for a completed 216-pick draft; what a populated row "
            "would mean is still unresolved. See the module docs.",
        ),
    )
