"""The draft tracker's read and write contract.

**This is a local write path, and it is not the automation write path.** Every
endpoint here writes to our own database and nothing else. Nothing in this
module, or anything it calls, sends an action to Fantrax, queues one, or holds
a transport that could. The Automation gate (``docs/governance/gates.md``)
covers the path that acts on a live account; recording what a human watched
happen in a draft room is not that. If a change here ever wants to turn a
recorded event into an action against Fantrax, it belongs in the bridge behind
``safety`` sign-off and not in this file.

**Descriptive only.** This module reports what was recorded. It ranks nothing,
values nothing, prices nothing, computes no inflation and produces no
``p(play)``. Those are ``quant``'s behind the Model gate (ADR-002, ADR-008) and
are deliberately absent. The one piece of arithmetic that reaches a response is
``remaining_budget = budget - spent``, which is an identity over recorded
facts, not an estimate. ``max_bid`` — the same subtraction with a
one-dollar-per-open-slot reserve — is a decision number and is deliberately
**not** here; it belongs to ``auction-budget-manager``.

**``remaining_budget`` may be negative, and a negative value is a fact about
this tool rather than about the seat.** The budget in that subtraction is one
scalar for the whole draft, copied from ``League.auction_budget``; the owner's
league sets each seat's bank separately, so the figure is wrong for most seats.
A sale above it is admitted to the board rather than refused — refusing it lost
a pick that really happened — and ``ParticipantOut.over_assumed_budget`` names
the condition so no client has to infer it from a minus sign. Clients must
therefore treat both ``spent`` and ``remaining_budget`` as signed. See
``hoops_gm.draft.state`` for why this is not a refusal, and the
``per-team-auction-budgets`` backlog item for the per-seat column that retires
the assumption.

**No lock is taken on any read** (ADR-014). ``last_sequence`` is a complete
version token, because a log whose only mutation is append means everything at
or below a sequence is immutable. Two responses carrying the same
``last_sequence`` describe the same draft. A polling screen can compare that
one integer instead of diffing the payload, and can pass it back as
``expected_last_sequence`` on the next append to find out whether anything
moved underneath it.

**There is no SSE endpoint, and that is a decision rather than an omission.**
The plan's live surfaces stream; this one does not. A draft tracker with one
recorder on one machine gains nothing from a push channel that a 1-2 second
poll of ``GET /drafts/{id}`` does not already give, and an SSE generator holds
a database session open for the length of the connection, which is the failure
mode most likely to bite during the one hour of the year this must not break.
``GET /drafts/{id}/events?since_sequence=`` makes an incremental poll cheap.
If the screen turns out to need push, adding it later is additive; removing a
stream that is holding sessions open mid-draft is not.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.api.deps import SessionDep
from hoops_gm.api.schemas import ErrorResponse
from hoops_gm.api.security import require_loopback_host
from hoops_gm.db.models.draft import Draft, DraftEvent
from hoops_gm.db.models.enums import DraftEventType, DraftStatus, DraftToolUsage, DraftType
from hoops_gm.db.models.league import League
from hoops_gm.draft import service
from hoops_gm.draft.formats import AuctionDraftFormat
from hoops_gm.draft.state import DraftLogError, DraftStateView

router = APIRouter(prefix="/drafts", tags=["drafts"])

#: Refusals that mean "the log moved underneath you; re-read and retry", as
#: opposed to "what you asked for is wrong". A polling client must treat these
#: as transient and must not clear the board on receiving one.
_RETRYABLE = frozenset({"draft_sequence_conflict"})

#: Refusals that describe a missing thing rather than a rejected one.
_NOT_FOUND = frozenset({"draft_not_found", "draft_league_not_found"})


def _error(status_code: int, code: str, detail: str) -> HTTPException:
    """Raise inside the app's error contract.

    ``X-Bridge-Error`` is **not** a response header. ``app.py``'s handler reads
    it off the exception and returns the code in ``ErrorResponse.error``. The
    name is a legacy of the bridge routes that introduced this transport.
    """

    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"X-Bridge-Error": code},
    )


def _from_log_error(error: DraftLogError) -> HTTPException:
    """Map a derivation refusal onto HTTP without inventing a second vocabulary.

    ``DraftLogError.code`` is published verbatim as the API error code. The
    alternative — a translation table from internal codes to external ones — is
    a second place the two can disagree, and the disagreement would only ever
    show up as a screen displaying a refusal nobody can grep for.
    """

    if error.code in _RETRYABLE:
        return _error(409, error.code, error.detail)
    if error.code in _NOT_FOUND:
        return _error(404, error.code, error.detail)
    return _error(422, error.code, error.detail)


class ParticipantRequest(BaseModel):
    """One seat, at creation."""

    model_config = ConfigDict(extra="forbid")

    team_slot: int = Field(ge=1, description="One-indexed local participant slot.")
    source_seat: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Frozen one-indexed rendered-board column. Either every participant supplies "
            "one or none do; it is distinct from team_slot."
        ),
    )
    display_name: str = Field(min_length=1, max_length=128)
    is_owner: bool = False
    fantasy_team_id: int | None = None


class CreateDraftRequest(BaseModel):
    """Open a draft. The format is taken from the league and frozen here."""

    model_config = ConfigDict(extra="forbid")

    league_id: int
    name: str = Field(min_length=1, max_length=128)
    #: Recorded, never inferred, and required for the same reason ``tool_usage``
    #: is: a mock and the real draft are different evidence (R38).
    is_mock: bool = True
    #: No default. Whether this tool was on the recorder's screen decides
    #: whether the draft is evidence about human behaviour or about this tool's
    #: own advice, and guessing it either way is unrecoverable later.
    tool_usage: DraftToolUsage
    notes: str | None = None
    participants: list[ParticipantRequest]


class _EventBase(BaseModel):
    """Fields every appended event carries.

    ``expected_last_sequence`` is optional, and the trade is worth stating.
    Supplied, it makes the append conditional on the log not having moved, so a
    double-submitted pick is refused with ``draft_sequence_conflict`` instead of
    recorded twice. Omitted, the append always targets the end of the log and
    that protection is forfeited — which is the right default for a person
    typing picks into one screen, and the wrong one for anything automated.

    ``occurred_at`` is the recorder's claim about wall-clock time. It is stored
    and displayed and **never** used to order anything; ``sequence`` is the
    ordering. A self-describing timestamp is exactly the kind of field this
    project has already been burned by (AGENTS.md: ``gameEt`` carries a ``Z``
    and is Eastern), and an ordering a client's clock can permute is not one.

    Unknown fields are **rejected**, not ignored. Pydantic's default would drop
    a ``player_label`` sent on a bid without saying so, and the recorder would
    reasonably believe the player had been captured. For a tool whose entire
    job is recording what happened, silently discarding part of what someone
    recorded is the worst available behaviour; a 422 is recoverable.
    """

    model_config = ConfigDict(extra="forbid")

    occurred_at: datetime | None = None
    note: str | None = None
    expected_last_sequence: int | None = Field(default=None, ge=0)


class PickRequest(_EventBase):
    """An ordered-draft selection."""

    event_type: Literal[DraftEventType.PICK]
    participant_id: int
    player_label: str = Field(min_length=1, max_length=128)
    player_id: int | None = None


class NominationRequest(_EventBase):
    """Put a player on the block. ``amount`` is the nominator's opening bid."""

    event_type: Literal[DraftEventType.NOMINATION]
    participant_id: int
    player_label: str = Field(min_length=1, max_length=128)
    player_id: int | None = None
    amount: Decimal | None = Field(default=None, gt=0)


class BidRequest(_EventBase):
    """A bid on the open lot.

    Carries no player on purpose: the open lot names the player, so a bid
    cannot disagree with the lot it is a bid on.
    """

    event_type: Literal[DraftEventType.BID]
    participant_id: int
    amount: Decimal = Field(gt=0)


class SaleRequest(_EventBase):
    """A lot clearing at an observed price.

    ``player_label`` may be omitted while a lot is open and is required when
    none is — which is the ordinary case in a fast room, where the recorder
    catches "Edwards went to Dave for $41" and never caught the nomination.
    """

    event_type: Literal[DraftEventType.SALE]
    participant_id: int
    amount: Decimal = Field(gt=0)
    player_label: str | None = Field(default=None, max_length=128)
    player_id: int | None = None


class VoidRequest(_EventBase):
    """Supersede an earlier event. Nothing is edited and nothing is deleted."""

    event_type: Literal[DraftEventType.VOID]
    supersedes_sequence: int = Field(ge=1)


class CloseRequest(_EventBase):
    """Declare the draft over. Reopened by voiding this event."""

    event_type: Literal[DraftEventType.CLOSED]


#: A tagged union, so a malformed event is refused by the schema rather than by
#: a hand-written check inside the handler. This is also what makes the OpenAPI
#: document say which fields belong to which event type, which is the whole
#: point of a contract a screen is built against.
EventRequestT = (
    PickRequest | NominationRequest | BidRequest | SaleRequest | VoidRequest | CloseRequest
)
EventRequest = Annotated[EventRequestT, Field(discriminator="event_type")]


class FormatOut(BaseModel):
    """The configuration this draft was recorded under. Frozen at creation."""

    draft_type: DraftType
    team_count: int
    roster_size: int
    total_roster_slots: int
    auction_budget: Decimal | None


class LeagueFormatDriftOut(BaseModel):
    """What the league row says now, when it disagrees with the snapshot.

    ``null`` on the response means the two agree. Published rather than
    resolved: the snapshot stays authoritative, and a screen can say the prices
    were paid under a different configuration instead of relabelling them.
    """

    draft_type: DraftType | None
    team_count: int | None
    roster_size: int | None
    auction_budget: Decimal | None
    error: str | None


class HoldingOut(BaseModel):
    """A player one seat holds, and the log entry that put them there."""

    player_id: int | None
    player_label: str
    player_key: str
    price: Decimal | None
    #: Lineage. Every holding names the single event it came from, so a screen
    #: can answer "where did this come from" with a sequence number.
    event_sequence: int
    overall_pick: int | None


class ParticipantOut(BaseModel):
    id: int
    team_slot: int
    source_seat: int | None
    display_name: str
    is_owner: bool
    fantasy_team_id: int | None
    holdings: list[HoldingOut]
    slots_filled: int
    slots_remaining: int
    spent: Decimal | None
    #: ``budget - spent``. An identity, not a maximum bid — see the module
    #: docstring. **Signed**: negative means this seat's recorded spend has
    #: passed the budget this tool assumed for it.
    remaining_budget: Decimal | None
    #: True when ``remaining_budget`` is negative. Published as its own field so
    #: a client reads the condition rather than re-deriving it from the sign.
    #: ``False`` in an ordered draft, where there is no budget to pass.
    over_assumed_budget: bool


class OpenLotOut(BaseModel):
    nomination_sequence: int
    player_id: int | None
    player_label: str
    player_key: str
    nominated_by_participant_id: int
    high_bid_amount: Decimal | None
    high_bid_participant_id: int | None
    high_bid_sequence: int | None


class NextPickOut(BaseModel):
    overall_pick: int
    round_number: int
    pick_in_round: int
    team_slot: int
    participant_id: int | None


class EventOut(BaseModel):
    """One log entry, as recorded.

    ``voided_by_sequence`` is the only field here the log does not literally
    contain; it is the sequence of the ``void`` that superseded this entry, and
    it is annotated rather than stored so there is still exactly one writable
    fact per event.
    """

    sequence: int
    event_type: DraftEventType
    participant_id: int | None
    player_id: int | None
    player_label: str | None
    amount: Decimal | None
    supersedes_sequence: int | None
    #: The recorder's claim about wall-clock time. Never used for ordering —
    #: ``sequence`` is the ordering. A client that sorts on this is wrong.
    occurred_at: datetime | None
    note: str | None
    voided_by_sequence: int | None


class DraftSummary(BaseModel):
    id: int
    league_id: int
    name: str
    is_mock: bool
    tool_usage: DraftToolUsage
    status: DraftStatus
    format: FormatOut
    last_sequence: int
    selections_made: int
    created_at: datetime
    updated_at: datetime


class DraftListResponse(BaseModel):
    drafts: list[DraftSummary]


class DraftStateResponse(BaseModel):
    """Everything a draft screen needs, derived from the log on this request."""

    id: int
    league_id: int
    name: str
    is_mock: bool
    tool_usage: DraftToolUsage
    notes: str | None
    status: DraftStatus
    format: FormatOut
    #: ``null`` when the league still describes this configuration.
    league_format_drift: LeagueFormatDriftOut | None
    participants: list[ParticipantOut]
    open_lot: OpenLotOut | None
    next_pick: NextPickOut | None
    selections_made: int
    total_roster_slots: int
    #: The version token. Two responses with the same value describe the same
    #: log, so a poll can compare one integer instead of the whole payload.
    last_sequence: int
    live_event_count: int
    voided_sequences: list[int]
    #: Holdings whose recorded name the crosswalk has not resolved. Reported
    #: rather than hidden — an unresolved name is still a real selection, and a
    #: screen that silently drops it shows a draft that did not happen.
    unresolved_player_count: int


class EventsResponse(BaseModel):
    """A window onto the raw log.

    ``last_sequence`` is the end of the *whole* log, not of this page, so a
    client can tell "you have everything" from "there is more" without a
    separate call.
    """

    draft_id: int
    events: list[EventOut]
    since_sequence: int
    last_sequence: int


def _format_out(state: DraftStateView) -> FormatOut:
    fmt = state.format
    return FormatOut(
        draft_type=fmt.draft_type,
        team_count=fmt.team_count,
        roster_size=fmt.roster_size,
        total_roster_slots=fmt.total_roster_slots,
        auction_budget=fmt.auction_budget if isinstance(fmt, AuctionDraftFormat) else None,
    )


def _state_response(
    draft: Draft, state: DraftStateView, drift: service.LeagueFormatDrift | None
) -> DraftStateResponse:
    next_pick_out: NextPickOut | None = None
    if state.next_pick is not None:
        if state.next_pick_participant_id is None:  # pragma: no cover - state invariant
            raise DraftLogError(
                "draft_source_seat_binding_invalid",
                f"Ordered slot {state.next_pick.team_slot} has no participant.",
            )
        next_pick_team_slot = next(
            seat.participant.team_slot
            for seat in state.participants
            if seat.participant.id == state.next_pick_participant_id
        )
        next_pick_out = NextPickOut(
            overall_pick=state.next_pick.overall_pick,
            round_number=state.next_pick.round_number,
            pick_in_round=state.next_pick.pick_in_round,
            team_slot=next_pick_team_slot,
            participant_id=state.next_pick_participant_id,
        )
    return DraftStateResponse(
        id=draft.id,
        league_id=draft.league_id,
        name=draft.name,
        is_mock=draft.is_mock,
        tool_usage=draft.tool_usage,
        notes=draft.notes,
        status=state.status,
        format=_format_out(state),
        league_format_drift=(
            None
            if drift is None
            else LeagueFormatDriftOut(
                draft_type=drift.draft_type,
                team_count=drift.team_count,
                roster_size=drift.roster_size,
                auction_budget=drift.auction_budget,
                error=drift.error,
            )
        ),
        participants=[
            ParticipantOut(
                id=seat.participant.id,
                team_slot=seat.participant.team_slot,
                source_seat=seat.participant.source_seat,
                display_name=seat.participant.display_name,
                is_owner=seat.participant.is_owner,
                fantasy_team_id=seat.participant.fantasy_team_id,
                holdings=[
                    HoldingOut(
                        player_id=holding.player_id,
                        player_label=holding.player_label,
                        player_key=holding.player_key,
                        price=holding.price,
                        event_sequence=holding.event_sequence,
                        overall_pick=holding.overall_pick,
                    )
                    for holding in seat.holdings
                ],
                slots_filled=seat.slots_filled,
                slots_remaining=seat.slots_remaining,
                spent=seat.spent,
                remaining_budget=seat.remaining_budget,
                over_assumed_budget=seat.over_assumed_budget,
            )
            for seat in state.participants
        ],
        open_lot=(
            None
            if state.open_lot is None
            else OpenLotOut(
                nomination_sequence=state.open_lot.nomination_sequence,
                player_id=state.open_lot.player_id,
                player_label=state.open_lot.player_label,
                player_key=state.open_lot.player_key,
                nominated_by_participant_id=state.open_lot.nominated_by_participant_id,
                high_bid_amount=state.open_lot.high_bid_amount,
                high_bid_participant_id=state.open_lot.high_bid_participant_id,
                high_bid_sequence=state.open_lot.high_bid_sequence,
            )
        ),
        next_pick=next_pick_out,
        selections_made=state.selections_made,
        total_roster_slots=state.total_roster_slots,
        last_sequence=state.last_sequence,
        live_event_count=state.live_event_count,
        voided_sequences=sorted(state.voided_sequences),
        unresolved_player_count=state.unresolved_player_count,
    )


def _require_draft(session: Session, draft_id: int) -> Draft:
    draft = service.load_draft(session, draft_id)
    if draft is None:
        raise _error(404, "draft_not_found", f"no draft {draft_id}")
    return draft


def _render(session: Session, draft: Draft) -> DraftStateResponse:
    state = service.load_state(session, draft)
    league = session.get(League, draft.league_id)
    drift = None if league is None else service.league_format_drift(draft, league)
    return _state_response(draft, state, drift)


@router.get(
    "",
    response_model=DraftListResponse,
    responses={403: {"model": ErrorResponse}},
    summary="Every recorded draft, newest first",
)
def list_drafts(session: SessionDep, request: Request) -> DraftListResponse:
    require_loopback_host(
        request,
        error_code="drafts_local_only",
        detail="Recorded drafts are only served to the local machine.",
    )
    drafts = session.scalars(select(Draft).order_by(Draft.id.desc())).all()
    summaries: list[DraftSummary] = []
    for draft in drafts:
        state = service.load_state(session, draft)
        summaries.append(
            DraftSummary(
                id=draft.id,
                league_id=draft.league_id,
                name=draft.name,
                is_mock=draft.is_mock,
                tool_usage=draft.tool_usage,
                status=state.status,
                format=_format_out(state),
                last_sequence=state.last_sequence,
                selections_made=state.selections_made,
                created_at=draft.created_at,
                updated_at=draft.updated_at,
            )
        )
    return DraftListResponse(drafts=summaries)


@router.post(
    "",
    response_model=DraftStateResponse,
    status_code=201,
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
    summary="Open a draft and freeze the configuration it is recorded under",
)
def create_draft(
    payload: CreateDraftRequest, session: SessionDep, request: Request
) -> DraftStateResponse:
    require_loopback_host(
        request,
        error_code="drafts_local_only",
        detail="Recording a draft is a local-only operation.",
    )
    league = session.get(League, payload.league_id)
    if league is None:
        raise _error(404, "draft_league_not_found", f"no league {payload.league_id}")
    try:
        draft = service.create_draft(
            session,
            league=league,
            name=payload.name,
            tool_usage=payload.tool_usage,
            is_mock=payload.is_mock,
            notes=payload.notes,
            participants=[
                service.ParticipantSpec(
                    team_slot=seat.team_slot,
                    source_seat=seat.source_seat,
                    display_name=seat.display_name,
                    is_owner=seat.is_owner,
                    fantasy_team_id=seat.fantasy_team_id,
                )
                for seat in payload.participants
            ],
        )
    except DraftLogError as error:
        raise _from_log_error(error) from error
    return _render(session, draft)


@router.get(
    "/{draft_id}",
    response_model=DraftStateResponse,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="One draft's current state, derived from its log on this request",
)
def get_draft(draft_id: int, session: SessionDep, request: Request) -> DraftStateResponse:
    require_loopback_host(
        request,
        error_code="drafts_local_only",
        detail="Recorded drafts are only served to the local machine.",
    )
    return _render(session, _require_draft(session, draft_id))


@router.get(
    "/{draft_id}/events",
    response_model=EventsResponse,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    summary="The raw log, in sequence order, with voids annotated",
)
def get_draft_events(
    draft_id: int,
    session: SessionDep,
    request: Request,
    since_sequence: int = Query(
        default=0,
        ge=0,
        description="Return events strictly after this sequence. 0 returns the whole log.",
    ),
    limit: int = Query(default=500, ge=1, le=2000),
) -> EventsResponse:
    require_loopback_host(
        request,
        error_code="drafts_local_only",
        detail="Recorded drafts are only served to the local machine.",
    )
    draft = _require_draft(session, draft_id)
    rows = service.load_events(session, draft)
    last_sequence = rows[-1].sequence if rows else 0
    voided_by = {
        row.supersedes_sequence: row.sequence
        for row in rows
        if row.event_type is DraftEventType.VOID and row.supersedes_sequence is not None
    }
    window = [row for row in rows if row.sequence > since_sequence][:limit]
    return EventsResponse(
        draft_id=draft.id,
        events=[_event_out(row, voided_by.get(row.sequence)) for row in window],
        since_sequence=since_sequence,
        last_sequence=last_sequence,
    )


def _event_out(row: DraftEvent, voided_by_sequence: int | None) -> EventOut:
    return EventOut(
        sequence=row.sequence,
        event_type=row.event_type,
        participant_id=row.participant_id,
        player_id=row.player_id,
        player_label=row.player_label,
        amount=row.amount,
        supersedes_sequence=row.supersedes_sequence,
        occurred_at=row.occurred_at,
        note=row.note,
        voided_by_sequence=voided_by_sequence,
    )


@router.post(
    "/{draft_id}/events",
    response_model=DraftStateResponse,
    status_code=201,
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
    summary="Append one event to a draft's log",
)
def append_draft_event(
    draft_id: int,
    payload: EventRequest,
    session: SessionDep,
    request: Request,
) -> DraftStateResponse:
    """Record one thing that happened, and answer with the whole new state.

    The full state comes back rather than the created event because the
    alternative gives a screen a torn view: it would hold an event it knows
    landed and a board that predates it, and would have to either re-poll
    immediately or guess at the difference. Guessing at the difference means
    reimplementing derivation in the browser, which is the one thing this
    contract exists to make unnecessary.

    A local write to our own database. Nothing is sent to Fantrax — see the
    module docstring.
    """

    require_loopback_host(
        request,
        error_code="drafts_local_only",
        detail="Recording a draft event is a local-only operation.",
    )
    draft = _require_draft(session, draft_id)
    try:
        _dispatch(session, draft, payload)
    except DraftLogError as error:
        raise _from_log_error(error) from error
    return _render(session, draft)


def _dispatch(session: Session, draft: Draft, payload: EventRequestT) -> DraftStateView:
    """Route one request body to the recorder that matches its shape.

    One branch per event type, and each branch names the fields its recorder
    takes rather than splatting a shared dict — so a field that exists on one
    event type and not another cannot silently be forwarded to a recorder that
    has no parameter for it. ``CloseRequest`` is the final branch by
    elimination, which the union makes total.
    """

    if isinstance(payload, PickRequest):
        return service.record_pick(
            session,
            draft,
            participant_id=payload.participant_id,
            player_label=payload.player_label,
            player_id=payload.player_id,
            occurred_at=payload.occurred_at,
            note=payload.note,
            expected_last_sequence=payload.expected_last_sequence,
        )
    if isinstance(payload, NominationRequest):
        return service.record_nomination(
            session,
            draft,
            participant_id=payload.participant_id,
            player_label=payload.player_label,
            player_id=payload.player_id,
            opening_bid=payload.amount,
            occurred_at=payload.occurred_at,
            note=payload.note,
            expected_last_sequence=payload.expected_last_sequence,
        )
    if isinstance(payload, BidRequest):
        return service.record_bid(
            session,
            draft,
            participant_id=payload.participant_id,
            amount=payload.amount,
            occurred_at=payload.occurred_at,
            note=payload.note,
            expected_last_sequence=payload.expected_last_sequence,
        )
    if isinstance(payload, SaleRequest):
        return service.record_sale(
            session,
            draft,
            participant_id=payload.participant_id,
            amount=payload.amount,
            player_label=payload.player_label,
            player_id=payload.player_id,
            occurred_at=payload.occurred_at,
            note=payload.note,
            expected_last_sequence=payload.expected_last_sequence,
        )
    if isinstance(payload, VoidRequest):
        return service.record_void(
            session,
            draft,
            supersedes_sequence=payload.supersedes_sequence,
            occurred_at=payload.occurred_at,
            note=payload.note,
            expected_last_sequence=payload.expected_last_sequence,
        )
    return service.record_close(
        session,
        draft,
        occurred_at=payload.occurred_at,
        note=payload.note,
        expected_last_sequence=payload.expected_last_sequence,
    )
