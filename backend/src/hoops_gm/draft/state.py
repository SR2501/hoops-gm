"""Derive the current state of a draft from its append-only log.

Pure. No database, no HTTP, no clock. Give it a format, the seats and the
events in sequence order and it returns what is true now, or raises
:class:`DraftLogError` naming the first event that cannot be true.

**Why derivation rather than a stored current state.** A draft has exactly one
kind of fact — something happened — and every summary of it (who holds whom,
what a seat has spent, whose turn it is, which lot is open) is a restatement of
those facts. Storing the summary alongside the log creates a second thing that
can be wrong, and this project has already paid for that twice with headers
that disagreed with the file underneath them. There is one fact here and it is
the log.

**Refusals are structural, not advisory.** Every rule below is enforced during
derivation, not only when appending, so a log that violates one cannot be read
back as a valid state through any path. That is what makes an append cheap to
validate: :mod:`hoops_gm.draft.service` appends a candidate event, re-derives,
and refuses if derivation refuses. One rule instead of a validator per event
type that has to be kept in step with the reader.

**Corrections are tail-first, and that is a limit rather than a design.** A
correction is a ``void`` event, so nothing is ever deleted or edited. Voiding
the most recent event always works. Voiding an *older* one replays everything
after it against preconditions that may no longer hold — a bid or a label-less
sale whose open lot has just disappeared, a snake pick whose turn order has
shifted — and derivation refuses rather than producing a state that is not
true. Review found this; it was an unnoticed consequence of "corrections are
voids" and not a trade anybody weighed. It is survivable for the first real
use, an auction recorded as standalone sales, where voiding any old sale
replays cleanly with budgets and holdings correct. Measured on a 27-event
auction, 4 events voided cleanly and only 2 of those were the tail, so "tail
only" overstates the limit: what actually decides it is whether anything after
the target depends on it. It is stated here so the unqualified claim cannot be
read off this module.

**What is not here.** No dollar value, no inflation, no max bid, no
recommendation, no ``p(play)``. The only arithmetic is addition of amounts a
human watched clear, subtraction from a stated budget, and counting slots.
``auction-budget-manager`` owns the $1-per-unfilled-slot reserve and the max
bid it implies; that is a decision number and it is deliberately absent, so the
absence of a ``max_bid`` field here is a boundary rather than an oversight.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from hoops_gm.db.models.enums import DraftEventType, DraftStatus
from hoops_gm.draft.formats import (
    AuctionDraftFormat,
    DraftFormat,
    DraftPick,
    LinearDraftFormat,
    SnakeDraftFormat,
)
from hoops_gm.identity.names import normalize_key

ZERO = Decimal("0.00")

_AUCTION_EVENTS = frozenset({DraftEventType.NOMINATION, DraftEventType.BID, DraftEventType.SALE})


class DraftLogError(ValueError):
    """A log that cannot describe a real draft.

    ``code`` is the stable machine-readable reason, reused verbatim as the
    API's error code so a screen matches on one vocabulary rather than parsing
    prose. ``sequence`` is the event that could not be applied, which is what
    makes a refusal actionable to whoever is recording.
    """

    def __init__(self, code: str, detail: str, *, sequence: int | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.sequence = sequence


@dataclass(frozen=True, slots=True)
class RecordedParticipant:
    """One seat, as read from storage."""

    id: int
    team_slot: int
    display_name: str
    is_owner: bool
    fantasy_team_id: int | None = None


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    """One log entry, as read from storage.

    ``occurred_at`` is carried so a reader can display it. It is never compared
    and never sorted on: ``sequence`` is the only ordering this module knows.
    """

    sequence: int
    event_type: DraftEventType
    participant_id: int | None = None
    player_id: int | None = None
    player_label: str | None = None
    amount: Decimal | None = None
    supersedes_sequence: int | None = None
    occurred_at: datetime | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class RosterHolding:
    """A player a seat holds, and the single event that put them there."""

    player_id: int | None
    player_label: str
    #: The normalised label used for the "already taken" check when the
    #: crosswalk has not resolved a name. Published so a reader can see which
    #: two entries a duplicate refusal considered the same.
    player_key: str
    #: The observed clearing price. ``None`` in an ordered draft, where no
    #: price exists rather than a price of zero.
    price: Decimal | None
    #: Where this came from. Every number attached to a holding traces to one
    #: log entry, which is what lets a screen say where it got it.
    event_sequence: int
    #: One-indexed overall pick in an ordered draft; ``None`` in an auction.
    overall_pick: int | None


@dataclass(frozen=True, slots=True)
class ParticipantState:
    """One seat's derived position."""

    participant: RecordedParticipant
    holdings: tuple[RosterHolding, ...]
    slots_filled: int
    slots_remaining: int
    #: Auction only. The sum of this seat's recorded clearing prices.
    spent: Decimal | None
    #: Auction only. ``budget - spent``, an identity over recorded facts. It is
    #: not a maximum bid: the reserve rule that turns this into one belongs to
    #: ``auction-budget-manager``.
    remaining_budget: Decimal | None


@dataclass(frozen=True, slots=True)
class OpenLot:
    """The auction lot currently on the block."""

    nomination_sequence: int
    player_id: int | None
    player_label: str
    player_key: str
    nominated_by_participant_id: int
    high_bid_amount: Decimal | None
    high_bid_participant_id: int | None
    high_bid_sequence: int | None


@dataclass(frozen=True, slots=True)
class DraftStateView:
    """Everything derivable from one draft's log."""

    format: DraftFormat
    status: DraftStatus
    participants: tuple[ParticipantState, ...]
    open_lot: OpenLot | None
    #: Ordered drafts only: the coordinate of the selection due next.
    next_pick: DraftPick | None
    next_pick_participant_id: int | None
    selections_made: int
    total_roster_slots: int
    #: The version token. Everything at or below this sequence is immutable, so
    #: two responses carrying the same value describe the same log.
    last_sequence: int
    #: Events that survived every ``void``, excluding the voids themselves.
    live_event_count: int
    voided_sequences: frozenset[int]
    #: Holdings whose recorded name the crosswalk has not resolved. Reported
    #: rather than hidden: an unresolved name is still a real selection.
    unresolved_player_count: int


def _player_key(label: str) -> str:
    """A within-one-draft duplicate key for an unresolved name.

    Deliberately narrow. This is *not* a cross-source identity claim — that is
    the crosswalk's, and ADR-008/R23 are about exactly the laundering that
    happens when a name match is promoted into an apparent hard key. Here it
    only answers "did this same draft already record this same string", which
    is a question about one recorder's typing.

    **What it erases, checked by running it rather than by reading
    ``normalize_key``.** Digits and generational suffixes do not survive:
    ``"Player 1"`` and ``"Player 2"`` both key to ``"player"``, and
    ``"Gary Payton II"`` keys to ``"gary payton"``. An ordinary word does
    survive, so ``"Jalen Johnson (ATL)"`` keys to ``"jalen johnson atl"`` and
    is distinguishable from ``"Jalen Johnson"``. That asymmetry is why the
    duplicate refusal tells a recorder to add a *word* rather than a number —
    the obvious fix of typing ``"Jalen Johnson 2"`` does not work and would
    look like a bug.
    """
    return normalize_key(label) or label.strip().casefold()


class _Board:
    """Mutable replay scratch space. Never escapes this module."""

    def __init__(self) -> None:
        # key -> the player ids recorded under it, `None` where unresolved.
        self.taken_by_key: dict[str, list[int | None]] = {}
        self.taken_ids: dict[int, int] = {}
        self.holdings: dict[int, list[RosterHolding]] = {}
        self.spent: dict[int, Decimal] = {}

    def refuse_if_taken(
        self, *, key: str, player_id: int | None, label: str, sequence: int
    ) -> None:
        if player_id is not None and player_id in self.taken_ids:
            raise DraftLogError(
                "draft_player_already_taken",
                f"{label} is already held in this draft "
                f"(recorded at sequence {self.taken_ids[player_id]}).",
                sequence=sequence,
            )
        existing = self.taken_by_key.get(key)
        if existing is None:
            return
        # Two players can genuinely share a normalised name — this repository
        # has already found two "Jalen Johnson" and two "Justin Jackson" inside
        # one Fantrax payload. When the crosswalk has resolved *both* sides to
        # different people, the ids are the better evidence and the name
        # collision is not a duplicate. When either side is unresolved there is
        # nothing to tell them apart, so this refuses rather than guessing, and
        # the recorder distinguishes the label.
        if (
            player_id is not None
            and player_id not in existing
            and all(other is not None for other in existing)
        ):
            return
        raise DraftLogError(
            "draft_player_already_taken",
            f"{label} is already held in this draft. If this is a different "
            f"player with the same name, add a distinguishing word such as a "
            f"team abbreviation — a digit or a suffix will not work, because "
            f"the duplicate key drops both.",
            sequence=sequence,
        )

    def add(self, *, participant_id: int, key: str, holding: RosterHolding) -> None:
        self.taken_by_key.setdefault(key, []).append(holding.player_id)
        if holding.player_id is not None:
            self.taken_ids[holding.player_id] = holding.event_sequence
        self.holdings.setdefault(participant_id, []).append(holding)
        if holding.price is not None:
            self.spent[participant_id] = self.spent.get(participant_id, ZERO) + holding.price

    def selections(self) -> int:
        return sum(len(entries) for entries in self.holdings.values())

    def held_by(self, participant_id: int) -> int:
        return len(self.holdings.get(participant_id, ()))

    def spent_by(self, participant_id: int) -> Decimal:
        return self.spent.get(participant_id, ZERO)


def _voided_sequences(events: Sequence[RecordedEvent]) -> frozenset[int]:
    """Resolve every ``void`` against the events it can legally supersede."""
    by_sequence = {event.sequence: event for event in events}
    voided: set[int] = set()
    for event in events:
        if event.event_type is not DraftEventType.VOID:
            continue
        target_sequence = event.supersedes_sequence
        if target_sequence is None:  # pragma: no cover - database CHECK forbids it
            raise DraftLogError(
                "draft_void_without_target",
                "A void must name the sequence it supersedes.",
                sequence=event.sequence,
            )
        target = by_sequence.get(target_sequence)
        if target is None or target_sequence >= event.sequence:
            raise DraftLogError(
                "draft_void_target_missing",
                f"Sequence {target_sequence} is not an earlier event of this draft.",
                sequence=event.sequence,
            )
        if target.event_type is DraftEventType.VOID:
            raise DraftLogError(
                "draft_cannot_void_a_void",
                "A void cannot be undone. Record the event again instead.",
                sequence=event.sequence,
            )
        if target_sequence in voided:
            raise DraftLogError(
                "draft_void_target_already_voided",
                f"Sequence {target_sequence} has already been voided.",
                sequence=event.sequence,
            )
        voided.add(target_sequence)
    return frozenset(voided)


def _require_participant(
    participants: Mapping[int, RecordedParticipant],
    participant_id: int | None,
    sequence: int,
) -> RecordedParticipant:
    if participant_id is None or participant_id not in participants:
        raise DraftLogError(
            "draft_unknown_participant",
            f"Participant {participant_id!r} is not a seat in this draft.",
            sequence=sequence,
        )
    return participants[participant_id]


def _require_label(event: RecordedEvent) -> str:
    label = (event.player_label or "").strip()
    if not label:
        raise DraftLogError(
            "draft_player_label_required",
            "This event must name the player as the recorder saw the name.",
            sequence=event.sequence,
        )
    return label


def _refuse_if_board_full(board: _Board, total_slots: int, sequence: int) -> None:
    if board.selections() >= total_slots:
        raise DraftLogError(
            "draft_board_full",
            f"All {total_slots} roster slots in this draft are already filled.",
            sequence=sequence,
        )


def _refuse_if_roster_full(
    board: _Board, participant: RecordedParticipant, roster_size: int, sequence: int
) -> None:
    if board.held_by(participant.id) >= roster_size:
        raise DraftLogError(
            "draft_roster_full",
            f"{participant.display_name} already holds {roster_size} players.",
            sequence=sequence,
        )


def _apply_pick(
    event: RecordedEvent,
    *,
    fmt: SnakeDraftFormat | LinearDraftFormat,
    participants: Mapping[int, RecordedParticipant],
    board: _Board,
) -> None:
    participant = _require_participant(participants, event.participant_id, event.sequence)
    label = _require_label(event)
    _refuse_if_board_full(board, fmt.total_roster_slots, event.sequence)
    expected = fmt.pick_at(board.selections() + 1)
    if participant.team_slot != expected.team_slot:
        raise DraftLogError(
            "draft_pick_out_of_turn",
            f"Overall pick {expected.overall_pick} belongs to team slot "
            f"{expected.team_slot}; {participant.display_name} holds slot "
            f"{participant.team_slot}.",
            sequence=event.sequence,
        )
    _refuse_if_roster_full(board, participant, fmt.roster_size, event.sequence)
    key = _player_key(label)
    board.refuse_if_taken(key=key, player_id=event.player_id, label=label, sequence=event.sequence)
    board.add(
        participant_id=participant.id,
        key=key,
        holding=RosterHolding(
            player_id=event.player_id,
            player_label=label,
            player_key=key,
            price=None,
            event_sequence=event.sequence,
            overall_pick=expected.overall_pick,
        ),
    )


def _apply_nomination(
    event: RecordedEvent,
    *,
    fmt: AuctionDraftFormat,
    participants: Mapping[int, RecordedParticipant],
    board: _Board,
    open_lot: OpenLot | None,
    previous_live_sequence: int | None = None,
) -> OpenLot:
    if open_lot is not None:
        # The advice has to name an action that will actually be accepted, and
        # it has to be true of the log as it stands. ``event.sequence - 1`` is
        # not that: during a void replay the preceding sequence may itself be
        # the event being voided, so the arithmetic advises voiding the very
        # thing the caller is already voiding, and claims a voided event still
        # depends on the lot. Count from the last event that actually survives.
        tail = previous_live_sequence
        if tail is None or open_lot.nomination_sequence >= tail:
            remedy = f"or void the nomination at sequence {open_lot.nomination_sequence}"
        else:
            remedy = (
                f"or void back from sequence {tail} to "
                f"{open_lot.nomination_sequence}, most recent first -- voiding the "
                f"nomination while the events between them still depend on the "
                f"open lot will be refused"
            )
        raise DraftLogError(
            "draft_lot_already_open",
            f"{open_lot.player_label} is still on the block. Record the sale, {remedy}.",
            sequence=event.sequence,
        )
    participant = _require_participant(participants, event.participant_id, event.sequence)
    label = _require_label(event)
    _refuse_if_board_full(board, fmt.total_roster_slots, event.sequence)
    key = _player_key(label)
    board.refuse_if_taken(key=key, player_id=event.player_id, label=label, sequence=event.sequence)
    if event.amount is not None:
        _refuse_if_over_budget(
            amount=event.amount,
            participant=participant,
            fmt=fmt,
            board=board,
            sequence=event.sequence,
        )
    return OpenLot(
        nomination_sequence=event.sequence,
        player_id=event.player_id,
        player_label=label,
        player_key=key,
        nominated_by_participant_id=participant.id,
        # A nomination amount is the nominator's opening bid, which is how
        # every auction site this project has observed treats it. Absent when
        # the recorder only caught who was nominated.
        high_bid_amount=event.amount,
        high_bid_participant_id=participant.id if event.amount is not None else None,
        high_bid_sequence=event.sequence if event.amount is not None else None,
    )


def _refuse_if_over_budget(
    *,
    amount: Decimal,
    participant: RecordedParticipant,
    fmt: AuctionDraftFormat,
    board: _Board,
    sequence: int,
) -> None:
    remaining = fmt.auction_budget - board.spent_by(participant.id)
    if amount > remaining:
        raise DraftLogError(
            "draft_budget_exceeded",
            f"{participant.display_name} has {remaining} left and this is {amount}.",
            sequence=sequence,
        )


def _apply_bid(
    event: RecordedEvent,
    *,
    fmt: AuctionDraftFormat,
    participants: Mapping[int, RecordedParticipant],
    board: _Board,
    open_lot: OpenLot | None,
) -> OpenLot:
    if open_lot is None:
        raise DraftLogError(
            "draft_no_open_lot",
            "A bid needs a lot on the block. Record the nomination first.",
            sequence=event.sequence,
        )
    participant = _require_participant(participants, event.participant_id, event.sequence)
    amount = event.amount
    if amount is None:  # pragma: no cover - database CHECK forbids it
        raise DraftLogError(
            "draft_amount_required", "A bid must carry an amount.", sequence=event.sequence
        )
    if open_lot.high_bid_amount is not None and amount <= open_lot.high_bid_amount:
        raise DraftLogError(
            "draft_bid_not_increasing",
            f"The bid on {open_lot.player_label} already stands at {open_lot.high_bid_amount}.",
            sequence=event.sequence,
        )
    _refuse_if_roster_full(board, participant, fmt.roster_size, event.sequence)
    _refuse_if_over_budget(
        amount=amount, participant=participant, fmt=fmt, board=board, sequence=event.sequence
    )
    return OpenLot(
        nomination_sequence=open_lot.nomination_sequence,
        player_id=open_lot.player_id,
        player_label=open_lot.player_label,
        player_key=open_lot.player_key,
        nominated_by_participant_id=open_lot.nominated_by_participant_id,
        high_bid_amount=amount,
        high_bid_participant_id=participant.id,
        high_bid_sequence=event.sequence,
    )


def _apply_sale(
    event: RecordedEvent,
    *,
    fmt: AuctionDraftFormat,
    participants: Mapping[int, RecordedParticipant],
    board: _Board,
    open_lot: OpenLot | None,
) -> None:
    participant = _require_participant(participants, event.participant_id, event.sequence)
    amount = event.amount
    if amount is None:  # pragma: no cover - database CHECK forbids it
        raise DraftLogError(
            "draft_amount_required", "A sale must carry a price.", sequence=event.sequence
        )
    if open_lot is None:
        # The fast path a live mock actually produces: the recorder caught
        # "Edwards went to Dave for $41" and never caught the nomination.
        # Refusing that would lose the only fact worth having.
        label = _require_label(event)
        player_id = event.player_id
        key = _player_key(label)
    else:
        label = open_lot.player_label
        player_id = open_lot.player_id
        key = open_lot.player_key
        claimed = (event.player_label or "").strip()
        if claimed and _player_key(claimed) != key:
            raise DraftLogError(
                "draft_lot_player_mismatch",
                f"{open_lot.player_label} is on the block, not {claimed}.",
                sequence=event.sequence,
            )
        if (
            event.player_id is not None
            and open_lot.player_id is not None
            and event.player_id != open_lot.player_id
        ):
            raise DraftLogError(
                "draft_lot_player_mismatch",
                "This sale resolves to a different player than the open lot.",
                sequence=event.sequence,
            )
        player_id = player_id if player_id is not None else event.player_id
        if open_lot.high_bid_amount is not None and amount < open_lot.high_bid_amount:
            # Bids may be sampled — a recorder cannot type every one — so a
            # price above the highest *recorded* bid is ordinary. A price below
            # one is not: it says somebody bid more and did not win.
            raise DraftLogError(
                "draft_sale_below_recorded_bid",
                f"A bid of {open_lot.high_bid_amount} is recorded on "
                f"{open_lot.player_label}; this sale is {amount}.",
                sequence=event.sequence,
            )
    _refuse_if_board_full(board, fmt.total_roster_slots, event.sequence)
    _refuse_if_roster_full(board, participant, fmt.roster_size, event.sequence)
    board.refuse_if_taken(key=key, player_id=player_id, label=label, sequence=event.sequence)
    _refuse_if_over_budget(
        amount=amount, participant=participant, fmt=fmt, board=board, sequence=event.sequence
    )
    board.add(
        participant_id=participant.id,
        key=key,
        holding=RosterHolding(
            player_id=player_id,
            player_label=label,
            player_key=key,
            price=amount,
            event_sequence=event.sequence,
            overall_pick=None,
        ),
    )


def _validate_seats(
    fmt: DraftFormat, participants: Sequence[RecordedParticipant]
) -> dict[int, RecordedParticipant]:
    slots = sorted(participant.team_slot for participant in participants)
    if slots != list(range(1, fmt.team_count + 1)):
        raise DraftLogError(
            "draft_participants_incomplete",
            f"A {fmt.team_count}-team draft needs exactly one seat per team slot "
            f"1..{fmt.team_count}; got {slots}.",
        )
    return {participant.id: participant for participant in participants}


def derive_state(
    *,
    fmt: DraftFormat,
    participants: Sequence[RecordedParticipant],
    events: Iterable[RecordedEvent],
) -> DraftStateView:
    """Replay ``events`` in sequence order and return what is true now.

    Raises :class:`DraftLogError` on the first event that cannot be applied.
    Callers appending a new event get their validation from this function
    rather than from a parallel set of rules, which is the only way the writer
    and the reader cannot drift apart.
    """
    ordered = sorted(events, key=lambda event: event.sequence)
    seen: set[int] = set()
    for event in ordered:
        if event.sequence in seen:  # pragma: no cover - unique constraint forbids it
            raise DraftLogError(
                "draft_duplicate_sequence",
                f"Sequence {event.sequence} appears twice.",
                sequence=event.sequence,
            )
        seen.add(event.sequence)

    by_id = _validate_seats(fmt, participants)
    voided = _voided_sequences(ordered)
    board = _Board()
    open_lot: OpenLot | None = None
    closed_at: int | None = None
    live_event_count = 0
    previous_live_sequence: int | None = None

    for event in ordered:
        if event.event_type is DraftEventType.VOID or event.sequence in voided:
            continue
        live_event_count += 1
        if closed_at is not None:
            raise DraftLogError(
                "draft_closed",
                f"This draft was closed at sequence {closed_at}. Void that event to reopen it.",
                sequence=event.sequence,
            )
        if event.event_type is DraftEventType.CLOSED:
            closed_at = event.sequence
        elif event.event_type is DraftEventType.PICK:
            if isinstance(fmt, AuctionDraftFormat):
                raise DraftLogError(
                    "draft_event_not_applicable",
                    "An auction records nominations, bids and sales, not picks.",
                    sequence=event.sequence,
                )
            _apply_pick(event, fmt=fmt, participants=by_id, board=board)
        elif event.event_type in _AUCTION_EVENTS:
            if not isinstance(fmt, AuctionDraftFormat):
                raise DraftLogError(
                    "draft_event_not_applicable",
                    f"An ordered draft records picks, not {event.event_type.value} events.",
                    sequence=event.sequence,
                )
            if event.event_type is DraftEventType.NOMINATION:
                open_lot = _apply_nomination(
                    event,
                    fmt=fmt,
                    participants=by_id,
                    board=board,
                    open_lot=open_lot,
                    previous_live_sequence=previous_live_sequence,
                )
            elif event.event_type is DraftEventType.BID:
                open_lot = _apply_bid(
                    event, fmt=fmt, participants=by_id, board=board, open_lot=open_lot
                )
            else:
                _apply_sale(event, fmt=fmt, participants=by_id, board=board, open_lot=open_lot)
                open_lot = None
        previous_live_sequence = event.sequence

    budget = fmt.auction_budget if isinstance(fmt, AuctionDraftFormat) else None
    is_auction = budget is not None
    participant_states = tuple(
        ParticipantState(
            participant=participant,
            holdings=tuple(board.holdings.get(participant.id, ())),
            slots_filled=board.held_by(participant.id),
            slots_remaining=fmt.roster_size - board.held_by(participant.id),
            spent=board.spent_by(participant.id) if is_auction else None,
            remaining_budget=(
                budget - board.spent_by(participant.id) if budget is not None else None
            ),
        )
        for participant in sorted(participants, key=lambda seat: seat.team_slot)
    )

    selections = board.selections()
    next_pick: DraftPick | None = None
    next_pick_participant_id: int | None = None
    if (
        not isinstance(fmt, AuctionDraftFormat)
        and closed_at is None
        and selections < fmt.total_roster_slots
    ):
        next_pick = fmt.pick_at(selections + 1)
        next_pick_participant_id = next(
            (seat.id for seat in participants if seat.team_slot == next_pick.team_slot),
            None,
        )

    if closed_at is not None:
        status = DraftStatus.CLOSED
    elif live_event_count:
        status = DraftStatus.IN_PROGRESS
    else:
        status = DraftStatus.SETUP

    return DraftStateView(
        format=fmt,
        status=status,
        participants=participant_states,
        open_lot=open_lot,
        next_pick=next_pick,
        next_pick_participant_id=next_pick_participant_id,
        selections_made=selections,
        total_roster_slots=fmt.total_roster_slots,
        last_sequence=ordered[-1].sequence if ordered else 0,
        live_event_count=live_event_count,
        voided_sequences=voided,
        unresolved_player_count=sum(
            1
            for state in participant_states
            for holding in state.holdings
            if holding.player_id is None
        ),
    )
