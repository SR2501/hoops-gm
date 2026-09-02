"""The only writer for the draft log, and the only reader of it.

Two guarantees, and both are mechanical rather than remembered.

**Every append is validated by the same function that renders the state.**
:func:`hoops_gm.draft.state.derive_state` is invoked over the existing log plus
the candidate event, and the row is written only if that succeeds. There is no
second set of rules for writes. A validator that lives beside the reader
instead of inside it is a validator that drifts from it, and the drift is
invisible until a log that was accepted cannot be read back.

**Concurrent appends are detected, not locked out** (ADR-014). Two writers can
compute the same next sequence; ``uq_draft_events_draft_sequence`` refuses one
of them and this module converts that into ``draft_sequence_conflict``, which
is retryable — re-read the state and append again. No lock is taken anywhere in
this module, so a poll from an open draft board can never stall the person
recording the draft. On draft day that is the only acceptable trade.

**This module writes to our own database and nowhere else.** It sends nothing
to Fantrax, queues no action, and has no transport. The Automation gate covers
the write path *to a live account*; recording what a human watched happen is
not that, and nothing here should ever become that. If a future change wants to
turn a recorded event into an action against Fantrax, it belongs in the bridge
behind ``safety`` sign-off, not here.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.db.models.draft import Draft, DraftEvent, DraftParticipant
from hoops_gm.db.models.enums import DraftEventType, DraftToolUsage, DraftType
from hoops_gm.db.models.league import League
from hoops_gm.draft.formats import (
    AuctionDraftFormat,
    DraftFormat,
    DraftFormatError,
    LinearDraftFormat,
    SnakeDraftFormat,
    draft_format_from_league,
)
from hoops_gm.draft.state import (
    DraftLogError,
    DraftStateView,
    RecordedEvent,
    RecordedParticipant,
    derive_state,
)


@dataclass(frozen=True, slots=True)
class ParticipantSpec:
    """One seat, as supplied at creation."""

    team_slot: int
    display_name: str
    is_owner: bool = False
    fantasy_team_id: int | None = None
    source_seat: int | None = None


@dataclass(frozen=True, slots=True)
class LeagueFormatDrift:
    """What the league row says now, when it no longer matches the snapshot.

    Published rather than resolved. The snapshot is what the draft was recorded
    under and stays authoritative; this exists so a screen can say "these prices
    were paid in a 12-team $200 league, and the league row now reads 10-team
    $100" instead of quietly showing one and labelling it the other. R39 is the
    reason that distinction is worth a field.

    This is the league's *whole current format*, not a sparse per-field diff.
    A sparse diff would need ``None`` to mean "agrees", which is the same value
    ``auction_budget`` legitimately takes for a snake league - the reader could
    not tell "unchanged" from "no budget". The consumer compares against
    ``format`` in the same payload, which it already has.
    """

    draft_type: DraftType | None
    team_count: int | None
    roster_size: int | None
    auction_budget: Decimal | None
    #: Set when the league row no longer forms a valid format at all.
    error: str | None


def format_from_snapshot(draft: Draft) -> DraftFormat:
    """Rebuild the format from the draft's own frozen facts.

    Constructs the same dataclasses ``draft-format-abstraction`` exposes, so
    their own fail-closed validation applies to a stored snapshot exactly as it
    applies to a league row. The league is deliberately not consulted: what a
    recorded draft was run under cannot be allowed to change when the league
    row is edited.
    """
    if draft.draft_type is DraftType.AUCTION:
        if draft.auction_budget is None:  # pragma: no cover - database CHECK forbids it
            raise DraftFormatError("auction_budget is required for auction drafts")
        return AuctionDraftFormat(
            team_count=draft.team_count,
            roster_size=draft.roster_size,
            auction_budget=draft.auction_budget,
        )
    if draft.draft_type is DraftType.SNAKE:
        return SnakeDraftFormat(team_count=draft.team_count, roster_size=draft.roster_size)
    if draft.draft_type is DraftType.LINEAR:
        return LinearDraftFormat(team_count=draft.team_count, roster_size=draft.roster_size)
    raise DraftFormatError(f"unsupported draft_type: {draft.draft_type!r}")


def league_format_drift(draft: Draft, league: League) -> LeagueFormatDrift | None:
    """``None`` when the league still describes this draft's configuration."""
    try:
        current = draft_format_from_league(league)
    except DraftFormatError as error:
        return LeagueFormatDrift(
            draft_type=league.draft_type if isinstance(league.draft_type, DraftType) else None,
            team_count=league.team_count,
            roster_size=league.roster_size,
            auction_budget=league.auction_budget,
            error=str(error),
        )
    if current == format_from_snapshot(draft):
        return None
    return LeagueFormatDrift(
        draft_type=league.draft_type,
        team_count=league.team_count,
        roster_size=league.roster_size,
        auction_budget=league.auction_budget,
        error=None,
    )


def create_draft(
    session: Session,
    *,
    league: League,
    name: str,
    tool_usage: DraftToolUsage,
    participants: Sequence[ParticipantSpec],
    is_mock: bool = True,
    notes: str | None = None,
) -> Draft:
    """Open a draft whose configuration is frozen at this moment.

    The four format facts are taken from the format
    ``draft_format_from_league`` accepted, not copied field by field off the
    league row, so the snapshot is by construction a configuration that
    abstraction considers valid.
    """
    label = name.strip()
    if not label:
        raise DraftLogError("draft_name_required", "A draft needs a name.")
    try:
        fmt = draft_format_from_league(league)
    except DraftFormatError as error:
        raise DraftLogError(
            "draft_format_invalid",
            f"League {league.id} does not describe a draft that can be recorded: {error}",
        ) from error

    slots = sorted(spec.team_slot for spec in participants)
    if slots != list(range(1, fmt.team_count + 1)):
        raise DraftLogError(
            "draft_participants_incomplete",
            f"A {fmt.team_count}-team draft needs exactly one seat per team slot "
            f"1..{fmt.team_count}; got {slots}.",
        )
    source_seats = [spec.source_seat for spec in participants]
    if any(source_seat is not None for source_seat in source_seats):
        expected_source_seats = list(range(1, fmt.team_count + 1))
        present_source_seats = sorted(
            source_seat for source_seat in source_seats if source_seat is not None
        )
        if (
            len(present_source_seats) != len(source_seats)
            or present_source_seats != expected_source_seats
        ):
            raise DraftLogError(
                "draft_source_seat_binding_invalid",
                f"A source-seat binding must map every participant one-to-one onto "
                f"1..{fmt.team_count}; got {source_seats}.",
            )
    owners = [spec for spec in participants if spec.is_owner]
    if len(owners) > 1:
        raise DraftLogError(
            "draft_multiple_owner_seats",
            "At most one seat in a draft can be the owner's.",
        )
    for spec in participants:
        if not spec.display_name.strip():
            raise DraftLogError(
                "draft_participant_name_required",
                f"Team slot {spec.team_slot} needs a display name.",
            )

    draft = Draft(
        league_id=league.id,
        name=label,
        is_mock=is_mock,
        tool_usage=tool_usage,
        draft_type=fmt.draft_type,
        team_count=fmt.team_count,
        roster_size=fmt.roster_size,
        auction_budget=(fmt.auction_budget if isinstance(fmt, AuctionDraftFormat) else None),
        notes=notes,
    )
    session.add(draft)
    session.flush()

    for spec in sorted(participants, key=lambda entry: entry.team_slot):
        session.add(
            DraftParticipant(
                draft_id=draft.id,
                team_slot=spec.team_slot,
                source_seat=spec.source_seat,
                display_name=spec.display_name.strip(),
                owner_draft_id=draft.id if spec.is_owner else None,
                fantasy_team_id=spec.fantasy_team_id,
            )
        )
    session.flush()
    session.refresh(draft)
    return draft


def load_draft(session: Session, draft_id: int) -> Draft | None:
    return session.get(Draft, draft_id)


def _recorded_participants(session: Session, draft: Draft) -> list[RecordedParticipant]:
    rows = session.scalars(
        select(DraftParticipant)
        .where(DraftParticipant.draft_id == draft.id)
        .order_by(DraftParticipant.team_slot)
    ).all()
    return [
        RecordedParticipant(
            id=row.id,
            team_slot=row.team_slot,
            source_seat=row.source_seat,
            display_name=row.display_name,
            is_owner=row.is_owner,
            fantasy_team_id=row.fantasy_team_id,
        )
        for row in rows
    ]


def load_events(session: Session, draft: Draft) -> list[DraftEvent]:
    """The whole log, in sequence order. No lock — see the module docstring."""
    return list(
        session.scalars(
            select(DraftEvent).where(DraftEvent.draft_id == draft.id).order_by(DraftEvent.sequence)
        ).all()
    )


def _last_sequence(session: Session, draft: Draft) -> int:
    """The highest sequence in the log, or 0 when it is empty.

    Read separately from ``load_events`` because ``record_void`` needs to know
    which sequences already existed *before* its own append, in order to tell a
    replay refusal apart from one about the void itself.
    """
    highest = session.scalar(
        select(func.max(DraftEvent.sequence)).where(DraftEvent.draft_id == draft.id)
    )
    return int(highest) if highest is not None else 0


def _as_recorded(rows: Sequence[DraftEvent]) -> list[RecordedEvent]:
    return [
        RecordedEvent(
            sequence=row.sequence,
            event_type=row.event_type,
            participant_id=row.participant_id,
            player_id=row.player_id,
            player_label=row.player_label,
            amount=row.amount,
            supersedes_sequence=row.supersedes_sequence,
            occurred_at=row.occurred_at,
            note=row.note,
        )
        for row in rows
    ]


def load_state(session: Session, draft: Draft) -> DraftStateView:
    """Derive the current state. Takes no lock and writes nothing."""
    return derive_state(
        fmt=format_from_snapshot(draft),
        participants=_recorded_participants(session, draft),
        events=_as_recorded(load_events(session, draft)),
    )


#: The one storage failure that is genuinely transient. A second writer took
#: the sequence between the read in :func:`_append` and its flush; re-reading
#: and appending again will succeed. Every *other* constraint on
#: ``draft_events`` describes a row that will be rejected identically no matter
#: how many times it is sent, so publishing it as retryable would invite a
#: conforming client to loop forever -- and would tell the person recording a
#: live auction that someone else beat them to the sequence when nothing of the
#: kind happened, which is the wrong diagnosis at the worst possible moment.
_RETRYABLE_CONSTRAINT = "uq_draft_events_draft_sequence"


def _violated_constraint(error: IntegrityError) -> str | None:
    """Name the constraint an ``IntegrityError`` came from, across dialects.

    ``derive_state`` validates the log's *semantics*; it does not validate the
    row's *storage* constraints. Those are two unrelated failure domains and
    only one of them is worth retrying, so this handler has to tell them apart
    rather than letting a single ``except`` speak for both.

    psycopg reports the name directly. SQLite only produces message text, and
    only for some constraint kinds: ``CHECK`` names the constraint, ``UNIQUE``
    names the columns instead, and ``FOREIGN KEY`` names nothing at all.
    Returns ``None`` when the dialect will not say, which the caller treats as
    permanent -- the safe direction, because an unrecognised failure reported
    as permanent is visible and re-postable, whereas one reported as transient
    is an invisible retry loop.
    """
    diagnostic = getattr(getattr(error, "orig", None), "diag", None)
    named = getattr(diagnostic, "constraint_name", None)
    if isinstance(named, str) and named:
        return named

    message = str(getattr(error, "orig", error))
    check = re.search(r"CHECK constraint failed: (\w+)", message)
    if check is not None:
        return check.group(1)
    if "UNIQUE constraint failed:" in message:
        columns = message.split("UNIQUE constraint failed:", 1)[1]
        touched = {part.strip() for part in columns.split(",")}
        if touched == {"draft_events.draft_id", "draft_events.sequence"}:
            return _RETRYABLE_CONSTRAINT
    return None


def _append(
    session: Session,
    draft: Draft,
    *,
    event_type: DraftEventType,
    participant_id: int | None = None,
    player_id: int | None = None,
    player_label: str | None = None,
    amount: Decimal | None = None,
    supersedes_sequence: int | None = None,
    occurred_at: datetime | None = None,
    note: str | None = None,
    expected_last_sequence: int | None = None,
) -> DraftStateView:
    existing = _as_recorded(load_events(session, draft))
    last_sequence = existing[-1].sequence if existing else 0
    if expected_last_sequence is not None and expected_last_sequence != last_sequence:
        raise DraftLogError(
            "draft_sequence_conflict",
            f"The log is at sequence {last_sequence}, not {expected_last_sequence}. "
            f"Re-read the draft and append again.",
        )

    label = player_label.strip() if player_label is not None else None
    candidate = RecordedEvent(
        sequence=last_sequence + 1,
        event_type=event_type,
        participant_id=participant_id,
        player_id=player_id,
        player_label=label or None,
        amount=amount,
        supersedes_sequence=supersedes_sequence,
        occurred_at=occurred_at,
        note=note,
    )
    # Validate by deriving. Raises before anything is written.
    state = derive_state(
        fmt=format_from_snapshot(draft),
        participants=_recorded_participants(session, draft),
        events=[*existing, candidate],
    )

    row = DraftEvent(
        draft_id=draft.id,
        sequence=candidate.sequence,
        event_type=candidate.event_type,
        participant_id=candidate.participant_id,
        player_id=candidate.player_id,
        player_label=candidate.player_label,
        amount=candidate.amount,
        supersedes_sequence=candidate.supersedes_sequence,
        occurred_at=candidate.occurred_at,
        note=candidate.note,
    )
    try:
        # A SAVEPOINT, not a plain flush. Postgres aborts the whole transaction
        # on a failed statement where SQLite carries on, so *something* has to
        # undo the bad INSERT before the caller can keep using this session --
        # but ``session.rollback()`` undoes the caller's uncommitted work too,
        # and a script that opens a draft and records into it in one
        # transaction would lose the draft itself. Rolling back to a savepoint
        # discards exactly the refused row and nothing else, on both dialects.
        with session.begin_nested():
            session.add(row)
    except IntegrityError as error:
        constraint = _violated_constraint(error)
        if row in session:
            session.expunge(row)
        if constraint == _RETRYABLE_CONSTRAINT:
            # Another writer took this sequence between the read above and here.
            # Detected rather than prevented: a lock would have blocked the person
            # recording the draft, which ADR-014 rules out for exactly this case.
            raise DraftLogError(
                "draft_sequence_conflict",
                "Another append reached this draft first. Re-read the draft and append again.",
            ) from error
        named = f" ({constraint})" if constraint else ""
        raise DraftLogError(
            "draft_row_rejected",
            f"The database refused this event{named}. Retrying it unchanged will fail "
            f"the same way. Check that any player_id names a player that exists and "
            f"that the event carries the fields its type requires.",
        ) from error
    return state


def record_pick(
    session: Session,
    draft: Draft,
    *,
    participant_id: int,
    player_label: str,
    player_id: int | None = None,
    occurred_at: datetime | None = None,
    note: str | None = None,
    expected_last_sequence: int | None = None,
) -> DraftStateView:
    """Record an ordered-draft selection."""
    return _append(
        session,
        draft,
        event_type=DraftEventType.PICK,
        participant_id=participant_id,
        player_id=player_id,
        player_label=player_label,
        occurred_at=occurred_at,
        note=note,
        expected_last_sequence=expected_last_sequence,
    )


def record_nomination(
    session: Session,
    draft: Draft,
    *,
    participant_id: int,
    player_label: str,
    player_id: int | None = None,
    opening_bid: Decimal | None = None,
    occurred_at: datetime | None = None,
    note: str | None = None,
    expected_last_sequence: int | None = None,
) -> DraftStateView:
    """Open an auction lot. ``opening_bid`` is the nominator's own first bid."""
    return _append(
        session,
        draft,
        event_type=DraftEventType.NOMINATION,
        participant_id=participant_id,
        player_id=player_id,
        player_label=player_label,
        amount=opening_bid,
        occurred_at=occurred_at,
        note=note,
        expected_last_sequence=expected_last_sequence,
    )


def record_bid(
    session: Session,
    draft: Draft,
    *,
    participant_id: int,
    amount: Decimal,
    occurred_at: datetime | None = None,
    note: str | None = None,
    expected_last_sequence: int | None = None,
) -> DraftStateView:
    """Record a bid on the open lot. The lot names the player, so this does not."""
    return _append(
        session,
        draft,
        event_type=DraftEventType.BID,
        participant_id=participant_id,
        amount=amount,
        occurred_at=occurred_at,
        note=note,
        expected_last_sequence=expected_last_sequence,
    )


def record_sale(
    session: Session,
    draft: Draft,
    *,
    participant_id: int,
    amount: Decimal,
    player_label: str | None = None,
    player_id: int | None = None,
    occurred_at: datetime | None = None,
    note: str | None = None,
    expected_last_sequence: int | None = None,
) -> DraftStateView:
    """Close an auction lot at an observed price.

    ``player_label`` may be omitted when a lot is open, and is required when
    one is not — which is the case whenever the recorder caught the sale but
    not the nomination, and is the common case in a fast mock.
    """
    return _append(
        session,
        draft,
        event_type=DraftEventType.SALE,
        participant_id=participant_id,
        player_id=player_id,
        player_label=player_label,
        amount=amount,
        occurred_at=occurred_at,
        note=note,
        expected_last_sequence=expected_last_sequence,
    )


def record_void(
    session: Session,
    draft: Draft,
    *,
    supersedes_sequence: int,
    occurred_at: datetime | None = None,
    note: str | None = None,
    expected_last_sequence: int | None = None,
) -> DraftStateView:
    """Supersede an earlier event. Nothing is deleted and nothing is edited.

    **Corrections are tail-first.** Voiding the most recent event always works.
    Voiding an *older* one replays every event after it under preconditions
    that may no longer hold -- a bid whose lot is gone, a label-less sale whose
    lot is gone, a snake pick whose turn order has shifted -- and the log
    refuses rather than deriving something untrue. When that happens the
    refusal is about the *replayed* event, not the void that was posted, so it
    is re-raised here saying so.

    Only a refusal blaming an event that **already existed and sits after the
    target** is a replay refusal. The void's own hygiene rules -- voiding a
    void, voiding the same target twice, naming a target that is not there,
    naming itself -- blame the sequence the new void would occupy, which is not
    a pre-existing later event and must pass through untouched.
    """
    tail = _last_sequence(session, draft)
    try:
        return _append(
            session,
            draft,
            event_type=DraftEventType.VOID,
            supersedes_sequence=supersedes_sequence,
            occurred_at=occurred_at,
            note=note,
            expected_last_sequence=expected_last_sequence,
        )
    except DraftLogError as error:
        blamed = error.sequence
        is_replay_refusal = (
            blamed is not None
            and error.code != "draft_row_rejected"
            and supersedes_sequence < blamed <= tail
        )
        if not is_replay_refusal:
            raise
        remedy = (
            f"void sequence {blamed} first"
            if blamed == tail
            else f"void back from sequence {tail} to sequence {blamed} first"
        )
        # The inner refusal's own advice is about the *hypothetical replayed*
        # log, not the one that exists, so following it costs a wasted round
        # trip. Quote it as a reason rather than leaving it standing as a
        # second instruction, and let the only imperative be the outer one.
        raise DraftLogError(
            error.code,
            f"Voiding sequence {supersedes_sequence} was refused because sequence "
            f"{blamed}, which comes after it, no longer holds once it is gone: "
            f'"{error.detail}" To void sequence {supersedes_sequence}, {remedy}.',
            sequence=blamed,
        ) from error


def record_close(
    session: Session,
    draft: Draft,
    *,
    occurred_at: datetime | None = None,
    note: str | None = None,
    expected_last_sequence: int | None = None,
) -> DraftStateView:
    """Declare the draft over. Reopen by voiding this event."""
    return _append(
        session,
        draft,
        event_type=DraftEventType.CLOSED,
        occurred_at=occurred_at,
        note=note,
        expected_last_sequence=expected_last_sequence,
    )
