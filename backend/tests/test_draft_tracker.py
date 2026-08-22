"""The draft log derives one state, and refuses everything that would be a lie.

Every test here drives the real service functions against a real session, not
:func:`derive_state` in isolation, because the claim worth testing is that a
log the writer accepted is a log the reader can read back. A pure-derivation
test would pass with the writer disconnected entirely.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from hoops_gm.db.models.draft import Draft, DraftEvent
from hoops_gm.db.models.enums import DraftEventType, DraftStatus, DraftToolUsage, DraftType
from hoops_gm.db.models.league import League
from hoops_gm.draft import service
from hoops_gm.draft.formats import AuctionDraftFormat
from hoops_gm.draft.state import DraftLogError


def _league(
    session: Session,
    *,
    draft_type: DraftType = DraftType.AUCTION,
    team_count: int = 4,
    roster_size: int = 3,
    budget: Decimal | None = Decimal("200.00"),
    name: str = "mock",
) -> League:
    league = League(
        fantrax_league_id=None,
        name=name,
        season="2026-27",
        draft_type=draft_type,
        team_count=team_count,
        roster_size=roster_size,
        auction_budget=budget,
    )
    session.add(league)
    session.flush()
    return league


def _draft(session: Session, league: League, *, seats: int | None = None) -> Draft:
    count = seats if seats is not None else (league.team_count or 0)
    return service.create_draft(
        session,
        league=league,
        name="a mock",
        tool_usage=DraftToolUsage.BLIND,
        participants=[
            service.ParticipantSpec(
                team_slot=index, display_name=f"Team {index}", is_owner=index == 1
            )
            for index in range(1, count + 1)
        ],
    )


_NAMES = (
    "Ansel Whitcombe",
    "Dov Kestrel",
    "Ilario Bexley",
    "Marek Sandoval",
    "Teodor Fane",
    "Oskar Vellamo",
    "Cassian Ferro",
    "Rune Halvorsen",
)


def _seat_ids(draft: Draft) -> dict[int, int]:
    return {seat.team_slot: seat.id for seat in draft.participants}


def test_an_auction_mock_records_end_to_end(session: Session) -> None:
    """The whole point of the unit: a lot cycle survives a round trip."""
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)

    service.record_nomination(
        session, draft, participant_id=seats[1], player_label="Ansel Whitcombe"
    )
    service.record_bid(session, draft, participant_id=seats[2], amount=Decimal("14.00"))
    state = service.record_sale(session, draft, participant_id=seats[3], amount=Decimal("22.00"))

    assert state.open_lot is None
    assert state.selections_made == 1
    assert state.last_sequence == 3
    held = {seat.participant.team_slot: seat for seat in state.participants}
    assert held[3].holdings[0].player_label == "Ansel Whitcombe"
    assert held[3].holdings[0].price == Decimal("22.00")
    # Lineage: the holding names the one event it came from.
    assert held[3].holdings[0].event_sequence == 3
    assert held[3].spent == Decimal("22.00")
    assert held[3].remaining_budget == Decimal("178.00")
    # A seat that bought nothing has spent nothing, not None.
    assert held[1].spent == Decimal("0.00")


def test_a_sale_may_stand_alone_without_a_nomination(session: Session) -> None:
    """The fast path a live room actually produces.

    The recorder catches "Edwards went to Dave for $41" and never caught the
    nomination. Refusing that loses the only fact worth having about the lot.
    """
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)

    state = service.record_sale(
        session,
        draft,
        participant_id=seats[2],
        amount=Decimal("41.00"),
        player_label="Ilario Bexley",
    )

    assert state.selections_made == 1
    assert state.open_lot is None


def test_a_standalone_sale_still_needs_a_name(session: Session) -> None:
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)

    with pytest.raises(DraftLogError) as caught:
        service.record_sale(session, draft, participant_id=seats[2], amount=Decimal("41.00"))

    assert caught.value.code == "draft_player_label_required"


def test_a_bid_needs_a_lot_on_the_block(session: Session) -> None:
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)

    with pytest.raises(DraftLogError) as caught:
        service.record_bid(session, draft, participant_id=seats[1], amount=Decimal("5.00"))

    assert caught.value.code == "draft_no_open_lot"


def test_a_bid_must_beat_the_standing_one(session: Session) -> None:
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    service.record_nomination(
        session,
        draft,
        participant_id=seats[1],
        player_label="Dov Kestrel",
        opening_bid=Decimal("10.00"),
    )

    with pytest.raises(DraftLogError) as caught:
        service.record_bid(session, draft, participant_id=seats[2], amount=Decimal("10.00"))

    assert caught.value.code == "draft_bid_not_increasing"


def test_a_sale_below_a_recorded_bid_is_refused(session: Session) -> None:
    """Bids are sampled, so a price *above* the highest recorded bid is ordinary.

    A price below one is not: it says somebody bid more and did not win.
    """
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    service.record_nomination(session, draft, participant_id=seats[1], player_label="Teodor Fane")
    service.record_bid(session, draft, participant_id=seats[2], amount=Decimal("30.00"))

    # Above the recorded bid: accepted, because the recorder missed bids.
    service.record_sale(session, draft, participant_id=seats[2], amount=Decimal("34.00"))

    service.record_nomination(session, draft, participant_id=seats[1], player_label="Oskar Vellamo")
    service.record_bid(session, draft, participant_id=seats[2], amount=Decimal("30.00"))
    with pytest.raises(DraftLogError) as caught:
        service.record_sale(session, draft, participant_id=seats[3], amount=Decimal("29.00"))

    assert caught.value.code == "draft_sale_below_recorded_bid"


def test_a_seat_cannot_spend_past_its_budget(session: Session) -> None:
    draft = _draft(session, _league(session, budget=Decimal("50.00")))
    seats = _seat_ids(draft)
    service.record_sale(
        session,
        draft,
        participant_id=seats[1],
        amount=Decimal("40.00"),
        player_label="Ansel Whitcombe",
    )

    with pytest.raises(DraftLogError) as caught:
        service.record_sale(
            session,
            draft,
            participant_id=seats[1],
            amount=Decimal("11.00"),
            player_label="Dov Kestrel",
        )

    assert caught.value.code == "draft_budget_exceeded"


def test_the_same_player_cannot_be_taken_twice(session: Session) -> None:
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    service.record_sale(
        session,
        draft,
        participant_id=seats[1],
        amount=Decimal("10.00"),
        player_label="Ansel Whitcombe",
    )

    with pytest.raises(DraftLogError) as caught:
        service.record_sale(
            session,
            draft,
            participant_id=seats[2],
            amount=Decimal("12.00"),
            player_label="  ansel   whitcombe ",
        )

    assert caught.value.code == "draft_player_already_taken"


def test_two_resolved_players_may_share_a_name(session: Session) -> None:
    """This repository has already found two "Jalen Johnson" in one payload.

    When the crosswalk has resolved both sides to different people the ids are
    the better evidence, so the name collision is not a duplicate.
    """
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    service.record_sale(
        session,
        draft,
        participant_id=seats[1],
        amount=Decimal("10.00"),
        player_label="Jalen Johnson",
        player_id=None,
    )

    # Unresolved on one side: refused, because nothing tells them apart.
    with pytest.raises(DraftLogError):
        service.record_sale(
            session,
            draft,
            participant_id=seats[2],
            amount=Decimal("9.00"),
            player_label="Jalen Johnson",
        )


def test_an_ordered_draft_enforces_its_own_order(session: Session) -> None:
    league = _league(session, draft_type=DraftType.SNAKE, budget=None)
    draft = _draft(session, league)
    seats = _seat_ids(draft)

    state = service.load_state(session, draft)
    assert state.next_pick is not None
    assert state.next_pick.overall_pick == 1
    assert state.next_pick_participant_id == seats[1]

    with pytest.raises(DraftLogError) as caught:
        service.record_pick(session, draft, participant_id=seats[2], player_label="Dov Kestrel")
    assert caught.value.code == "draft_pick_out_of_turn"

    service.record_pick(session, draft, participant_id=seats[1], player_label="Dov Kestrel")
    state = service.load_state(session, draft)
    assert state.next_pick is not None
    assert state.next_pick.team_slot == 2


def test_a_snake_draft_turns_around_at_the_end_of_a_round(session: Session) -> None:
    """The order comes from the format abstraction, not from a second copy of it."""
    league = _league(session, draft_type=DraftType.SNAKE, team_count=3, roster_size=2, budget=None)
    draft = _draft(session, league)
    seats = _seat_ids(draft)
    order = []
    for index in range(6):
        state = service.load_state(session, draft)
        assert state.next_pick is not None
        order.append(state.next_pick.team_slot)
        service.record_pick(
            session,
            draft,
            participant_id=seats[state.next_pick.team_slot],
            player_label=_NAMES[index],
        )

    assert order == [1, 2, 3, 3, 2, 1]
    assert service.load_state(session, draft).next_pick is None


def test_a_roster_cannot_hold_more_than_the_format_allows(session: Session) -> None:
    league = _league(session, team_count=2, roster_size=1)
    draft = _draft(session, league)
    seats = _seat_ids(draft)
    service.record_sale(
        session, draft, participant_id=seats[1], amount=Decimal("1.00"), player_label="A One"
    )

    with pytest.raises(DraftLogError) as caught:
        service.record_sale(
            session, draft, participant_id=seats[1], amount=Decimal("1.00"), player_label="B Two"
        )

    assert caught.value.code == "draft_roster_full"


def test_a_void_removes_a_selection_without_removing_the_record(session: Session) -> None:
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    mistake = service.record_sale(
        session,
        draft,
        participant_id=seats[1],
        amount=Decimal("18.00"),
        player_label="Cassian Ferro",
    )
    assert mistake.selections_made == 1

    state = service.record_void(session, draft, supersedes_sequence=mistake.last_sequence)

    assert state.selections_made == 0
    assert state.voided_sequences == frozenset({1})
    # The mistaken event is still in the log. Nothing was deleted.
    rows = service.load_events(session, draft)
    assert [row.sequence for row in rows] == [1, 2]
    assert rows[0].player_label == "Cassian Ferro"
    # And the player is available again, which is the point of the correction.
    service.record_sale(
        session,
        draft,
        participant_id=seats[2],
        amount=Decimal("18.00"),
        player_label="Cassian Ferro",
    )


def test_a_void_cannot_target_a_void_or_a_missing_event(session: Session) -> None:
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    service.record_sale(
        session, draft, participant_id=seats[1], amount=Decimal("5.00"), player_label="A One"
    )
    service.record_void(session, draft, supersedes_sequence=1)

    with pytest.raises(DraftLogError) as first:
        service.record_void(session, draft, supersedes_sequence=2)
    assert first.value.code == "draft_cannot_void_a_void"

    with pytest.raises(DraftLogError) as second:
        service.record_void(session, draft, supersedes_sequence=1)
    assert second.value.code == "draft_void_target_already_voided"

    with pytest.raises(DraftLogError) as third:
        service.record_void(session, draft, supersedes_sequence=99)
    assert third.value.code == "draft_void_target_missing"


def test_closing_refuses_later_events_until_it_is_voided(session: Session) -> None:
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    state = service.record_close(session, draft)
    assert state.status is DraftStatus.CLOSED

    with pytest.raises(DraftLogError) as caught:
        service.record_sale(
            session, draft, participant_id=seats[1], amount=Decimal("5.00"), player_label="A One"
        )
    assert caught.value.code == "draft_closed"

    reopened = service.record_void(session, draft, supersedes_sequence=1)
    assert reopened.status is DraftStatus.SETUP
    service.record_sale(
        session, draft, participant_id=seats[1], amount=Decimal("5.00"), player_label="A One"
    )


def test_a_full_board_is_not_the_same_as_a_closed_draft(session: Session) -> None:
    """Mock auctions routinely end with slots unfilled, so fullness is a fact.

    ``DraftStatus`` has no COMPLETE-by-fullness value on purpose: closing is
    something the recorder says, and fullness is published separately.
    """
    league = _league(session, team_count=2, roster_size=1)
    draft = _draft(session, league)
    seats = _seat_ids(draft)
    for slot in (1, 2):
        service.record_sale(
            session,
            draft,
            participant_id=seats[slot],
            amount=Decimal("1.00"),
            player_label=_NAMES[slot],
        )

    state = service.load_state(session, draft)
    assert state.selections_made == state.total_roster_slots == 2
    assert state.status is DraftStatus.IN_PROGRESS

    with pytest.raises(DraftLogError) as caught:
        service.record_sale(
            session, draft, participant_id=seats[1], amount=Decimal("1.00"), player_label="Extra"
        )
    assert caught.value.code in {"draft_roster_full", "draft_board_full"}


def test_occurred_at_going_backwards_does_not_reorder_anything(session: Session) -> None:
    """``sequence`` is the ordering; a recorder's clock is only a claim.

    ``gameEt`` in the NBA box score carries a ``Z`` and is Eastern time. A
    self-describing timestamp is exactly the field this project has been burned
    by, so nothing here sorts on one.
    """
    league = _league(session, draft_type=DraftType.SNAKE, team_count=2, roster_size=1, budget=None)
    draft = _draft(session, league)
    seats = _seat_ids(draft)

    service.record_pick(
        session,
        draft,
        participant_id=seats[1],
        player_label="Later Claim",
        occurred_at=datetime(2026, 10, 18, 23, 0, tzinfo=UTC),
    )
    service.record_pick(
        session,
        draft,
        participant_id=seats[2],
        player_label="Earlier Claim",
        occurred_at=datetime(2026, 10, 18, 9, 0, tzinfo=UTC),
    )

    rows = service.load_events(session, draft)
    assert [row.player_label for row in rows] == ["Later Claim", "Earlier Claim"]
    state = service.load_state(session, draft)
    held = {seat.participant.team_slot: seat.holdings[0] for seat in state.participants}
    # Seat 1 picked first because it holds overall pick 1, not because its
    # claimed timestamp is later or earlier.
    assert held[1].overall_pick == 1
    assert held[2].overall_pick == 2


def test_an_append_is_refused_when_the_log_moved_underneath_it(session: Session) -> None:
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    service.record_sale(
        session, draft, participant_id=seats[1], amount=Decimal("5.00"), player_label="A One"
    )

    with pytest.raises(DraftLogError) as caught:
        service.record_sale(
            session,
            draft,
            participant_id=seats[2],
            amount=Decimal("5.00"),
            player_label="B Two",
            expected_last_sequence=0,
        )

    assert caught.value.code == "draft_sequence_conflict"
    assert service.load_state(session, draft).last_sequence == 1


def test_a_refused_append_writes_nothing(session: Session) -> None:
    """Validation happens before the insert, so a refusal leaves no row.

    Worth its own test: the alternative implementation — insert, re-derive,
    roll back — leaves the sequence counter advanced on some dialects, and a
    log with a hole in it is a log whose ``last_sequence`` stops being a count.
    """
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)

    with pytest.raises(DraftLogError):
        service.record_bid(session, draft, participant_id=seats[1], amount=Decimal("5.00"))

    assert service.load_events(session, draft) == []
    service.record_sale(
        session, draft, participant_id=seats[1], amount=Decimal("5.00"), player_label="A One"
    )
    assert [row.sequence for row in service.load_events(session, draft)] == [1]


def test_a_draft_needs_exactly_one_seat_per_team_slot(session: Session) -> None:
    league = _league(session, team_count=4)

    with pytest.raises(DraftLogError) as caught:
        _draft(session, league, seats=3)

    assert caught.value.code == "draft_participants_incomplete"


def test_at_most_one_seat_is_the_owners(session: Session) -> None:
    league = _league(session, team_count=2)

    with pytest.raises(DraftLogError) as caught:
        service.create_draft(
            session,
            league=league,
            name="two owners",
            tool_usage=DraftToolUsage.BLIND,
            participants=[
                service.ParticipantSpec(team_slot=1, display_name="A", is_owner=True),
                service.ParticipantSpec(team_slot=2, display_name="B", is_owner=True),
            ],
        )

    assert caught.value.code == "draft_multiple_owner_seats"


def test_a_league_that_cannot_describe_a_draft_is_refused(session: Session) -> None:
    league = _league(session, draft_type=DraftType.UNKNOWN, budget=None)

    with pytest.raises(DraftLogError) as caught:
        _draft(session, league)

    assert caught.value.code == "draft_format_invalid"


def test_the_format_snapshot_survives_a_later_league_edit(session: Session) -> None:
    """R39: auction prices do not transfer between configurations.

    Deriving the format from the league on read would let an edit rewrite what
    configuration an old mock was recorded under, which makes its prices
    uninterpretable while still displaying them.
    """
    league = _league(session, team_count=4, roster_size=3, budget=Decimal("200.00"))
    draft = _draft(session, league)
    seats = _seat_ids(draft)
    service.record_sale(
        session, draft, participant_id=seats[1], amount=Decimal("60.00"), player_label="A One"
    )

    league.team_count = 10
    league.auction_budget = Decimal("100.00")
    session.flush()

    state = service.load_state(session, draft)
    assert isinstance(state.format, AuctionDraftFormat)
    assert state.format.team_count == 4
    assert state.format.auction_budget == Decimal("200.00")

    drift = service.league_format_drift(draft, league)
    assert drift is not None
    assert drift.team_count == 10
    assert drift.auction_budget == Decimal("100.00")
    assert drift.error is None


def test_drift_is_none_when_the_league_still_agrees(session: Session) -> None:
    """Assert the presence of agreement, not merely the absence of a complaint."""
    league = _league(session)
    draft = _draft(session, league)

    assert service.league_format_drift(draft, league) is None


def test_the_log_never_stores_a_number_a_decision_rests_on(session: Session) -> None:
    """Scope, asserted rather than remembered.

    A recommendation, a valuation, an auction price estimate or a ``p(play)``
    on the table that records what happened would be a decision number wearing
    an observation's clothes. Those are ``quant``'s behind the Model gate.
    """
    columns = set(inspect(DraftEvent).columns.keys())
    forbidden = {
        "projected_value",
        "recommended_bid",
        "expected_price",
        "inflation_factor",
        "p_play",
        "z_score",
        "g_score",
    }

    assert columns & forbidden == set()
    # And the presence that makes the absence meaningful: the observed price is
    # here, under a name that says it was observed.
    assert "amount" in columns
    assert "player_label" in columns


def test_current_state_is_not_stored_anywhere(session: Session) -> None:
    """The log is the only fact, checked by construction rather than by intent.

    A summary column beside the log would be a second thing that can be wrong,
    and nothing in a response would say which of the two to believe.
    """
    draft_columns = set(inspect(Draft).columns.keys())
    derived = {
        "status",
        "current_pick",
        "selections_made",
        "last_sequence",
        "open_lot_player_id",
        "remaining_budget",
    }

    assert draft_columns & derived == set()


@pytest.mark.sqlite_only
def test_a_raw_update_is_possible_which_is_why_the_claim_is_narrow(session: Session) -> None:
    """Append-only is enforced by the service, not by the database.

    Stated as an executable fact rather than left as an unexamined guarantee.
    A portable trigger would need dialect-specific SQL, which
    ``test_portability.py`` forbids, so the honest claim is "nothing in this
    codebase updates an event", and this test is what stops that claim quietly
    becoming "nothing can".
    """
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    service.record_sale(
        session, draft, participant_id=seats[1], amount=Decimal("5.00"), player_label="A One"
    )
    session.flush()

    session.execute(text("UPDATE draft_events SET player_label = 'Rewritten' WHERE sequence = 1"))
    session.expire_all()

    assert service.load_events(session, draft)[0].player_label == "Rewritten"


def test_every_event_type_round_trips_through_the_log(session: Session) -> None:
    """Assert the presence of all six, so a type nobody records cannot hide.

    Two drafts, because a ``pick`` is not applicable to an auction and a
    ``nomination`` is not applicable to an ordered draft — that split is itself
    the thing being asserted.
    """
    auction = _draft(session, _league(session))
    seats = _seat_ids(auction)
    service.record_nomination(
        session,
        auction,
        participant_id=seats[1],
        player_label="Ansel Whitcombe",
        opening_bid=Decimal("1.00"),
    )
    service.record_bid(session, auction, participant_id=seats[2], amount=Decimal("4.00"))
    service.record_sale(session, auction, participant_id=seats[2], amount=Decimal("6.00"))
    service.record_void(session, auction, supersedes_sequence=3)
    service.record_close(session, auction)

    snake = _draft(
        session,
        _league(
            session,
            draft_type=DraftType.SNAKE,
            team_count=2,
            roster_size=1,
            budget=None,
            name="ordered mock",
        ),
    )
    service.record_pick(
        session, snake, participant_id=_seat_ids(snake)[1], player_label="Dov Kestrel"
    )

    recorded = {row.event_type for row in service.load_events(session, auction)}
    recorded |= {row.event_type for row in service.load_events(session, snake)}
    assert recorded == set(DraftEventType)


def test_a_pick_and_a_nomination_belong_to_different_formats(session: Session) -> None:
    """Format is honoured rather than special-cased, per ``draft-format-abstraction``."""
    auction = _draft(session, _league(session))
    with pytest.raises(DraftLogError) as in_auction:
        service.record_pick(
            session, auction, participant_id=_seat_ids(auction)[1], player_label="Ansel Whitcombe"
        )
    assert in_auction.value.code == "draft_event_not_applicable"

    snake = _draft(
        session,
        _league(
            session, draft_type=DraftType.SNAKE, team_count=2, roster_size=1, budget=None, name="s"
        ),
    )
    with pytest.raises(DraftLogError) as in_snake:
        service.record_nomination(
            session, snake, participant_id=_seat_ids(snake)[1], player_label="Ansel Whitcombe"
        )
    assert in_snake.value.code == "draft_event_not_applicable"


def test_the_duplicate_key_drops_digits_and_suffixes(session: Session) -> None:
    """Driven, not assumed, because the obvious workaround does not work.

    A recorder facing a duplicate refusal will try typing ``"Jalen Johnson 2"``.
    That keys identically to ``"Jalen Johnson"`` and is refused again, which
    looks like a bug unless the refusal says so. A distinguishing *word* does
    survive, so that is what the message asks for.
    """
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    service.record_sale(
        session,
        draft,
        participant_id=seats[1],
        amount=Decimal("5.00"),
        player_label="Jalen Johnson",
    )

    with pytest.raises(DraftLogError) as digit:
        service.record_sale(
            session,
            draft,
            participant_id=seats[2],
            amount=Decimal("5.00"),
            player_label="Jalen Johnson 2",
        )
    assert digit.value.code == "draft_player_already_taken"
    assert "digit" in digit.value.detail

    with pytest.raises(DraftLogError):
        service.record_sale(
            session,
            draft,
            participant_id=seats[2],
            amount=Decimal("5.00"),
            player_label="Jalen Johnson Jr.",
        )

    # A word does distinguish, which is the escape hatch the message names.
    state = service.record_sale(
        session,
        draft,
        participant_id=seats[2],
        amount=Decimal("5.00"),
        player_label="Jalen Johnson (ATL)",
    )
    assert state.selections_made == 2


def test_a_permanent_row_rejection_is_not_published_as_a_retryable_conflict(
    session: Session,
) -> None:
    """The classification bug review found, driven on whichever dialect is running.

    ``derive_state`` validates the log's semantics; it does not validate the
    row's storage constraints. A ``player_id`` naming no player is a permanent
    input error. Published as ``draft_sequence_conflict`` it becomes a 409 that
    a conforming client retries forever, while telling the person recording a
    live auction that someone beat them to the sequence.
    """
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)

    # Presence first: an ordinary sale is accepted, so a refusal below is the
    # constraint refusing and not the fixture being broken.
    accepted = service.record_sale(
        session, draft, participant_id=seats[1], amount=Decimal("5.00"), player_label="Dov Kestrel"
    )
    assert accepted.last_sequence == 1

    with pytest.raises(DraftLogError) as caught:
        service.record_sale(
            session,
            draft,
            participant_id=seats[2],
            amount=Decimal("6.00"),
            player_label="Ilario Bexley",
            player_id=987654321,
        )

    assert caught.value.code == "draft_row_rejected"
    assert caught.value.code not in {"draft_sequence_conflict"}
    assert "the same way" in caught.value.detail

    # The session survives the failed append on both dialects: Postgres aborts
    # the transaction where SQLite does not, and the rollback is what makes the
    # log readable afterwards rather than the dialect being forgiving.
    state = service.load_state(session, draft)
    assert state.last_sequence == 1


def test_the_retryable_conflict_is_still_reported_as_retryable(session: Session) -> None:
    """The other half. Discriminating must not silence the real race.

    Without this, a fix that classified *everything* permanent would pass the
    test above and quietly break the concurrency contract ADR-014 rests on.
    """
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    service.record_sale(
        session, draft, participant_id=seats[1], amount=Decimal("5.00"), player_label="Dov Kestrel"
    )

    with pytest.raises(DraftLogError) as caught:
        service.record_sale(
            session,
            draft,
            participant_id=seats[2],
            amount=Decimal("6.00"),
            player_label="Ilario Bexley",
            expected_last_sequence=99,
        )
    assert caught.value.code == "draft_sequence_conflict"


def test_the_lot_already_open_refusal_names_an_action_that_is_accepted(
    session: Session,
) -> None:
    """A refusal must advise something the surface will then accept.

    Same class as the duplicate-key message: advice naming an action that is
    itself refused is worse than no advice, because it costs the recorder a
    round trip mid-auction to discover it does not work.
    """
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    service.record_nomination(session, draft, participant_id=seats[1], player_label="Dov Kestrel")
    service.record_bid(session, draft, participant_id=seats[2], amount=Decimal("4.00"))

    with pytest.raises(DraftLogError) as caught:
        service.record_nomination(
            session, draft, participant_id=seats[3], player_label="Ilario Bexley"
        )
    assert caught.value.code == "draft_lot_already_open"
    # The nomination is no longer the tail, so the advice must not say to void
    # it outright -- doing so is refused, which is the whole finding.
    assert "void back from sequence 2" in caught.value.detail

    # Drive the advice: voiding the tail first, then the nomination, works.
    service.record_void(session, draft, supersedes_sequence=2)
    service.record_void(session, draft, supersedes_sequence=1)
    reopened = service.record_nomination(
        session, draft, participant_id=seats[3], player_label="Ilario Bexley"
    )
    assert reopened.open_lot is not None
    assert reopened.open_lot.player_label == "Ilario Bexley"


def test_voiding_the_tail_is_advised_directly_when_it_is_the_tail(session: Session) -> None:
    """The other branch of the same message, so neither arm goes unexercised."""
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    service.record_nomination(session, draft, participant_id=seats[1], player_label="Dov Kestrel")

    with pytest.raises(DraftLogError) as caught:
        service.record_nomination(
            session, draft, participant_id=seats[2], player_label="Ilario Bexley"
        )
    assert "void the nomination at sequence 1" in caught.value.detail


def test_a_void_refused_by_replay_says_it_was_the_replay(session: Session) -> None:
    """Corrections are tail-first; the refusal must not read as a bug.

    Voiding an old event replays the ones after it. When one of those no longer
    holds, the refusal is about *that* event, and without this it surfaces as a
    message describing a sequence the recorder never posted.
    """
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    service.record_nomination(session, draft, participant_id=seats[1], player_label="Dov Kestrel")
    service.record_bid(session, draft, participant_id=seats[2], amount=Decimal("4.00"))

    with pytest.raises(DraftLogError) as caught:
        service.record_void(session, draft, supersedes_sequence=1)

    assert "Voiding sequence 1 was refused because sequence 2" in caught.value.detail
    assert "Void back from the most recent event instead." in caught.value.detail
    assert caught.value.sequence == 2


def test_voiding_the_most_recent_event_is_always_accepted(session: Session) -> None:
    """The tail-first limit is a limit, not a prohibition -- assert the presence."""
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    service.record_nomination(session, draft, participant_id=seats[1], player_label="Dov Kestrel")
    state = service.record_bid(session, draft, participant_id=seats[2], amount=Decimal("4.00"))
    assert state.last_sequence == 2

    after = service.record_void(session, draft, supersedes_sequence=2)
    assert after.open_lot is not None
    assert after.open_lot.player_label == "Dov Kestrel"


def test_a_refused_append_does_not_discard_the_callers_uncommitted_work(
    session: Session,
) -> None:
    """The savepoint, driven.

    A plain ``session.rollback()`` in the failure path undoes everything the
    caller has not committed -- including the draft and its seats when a script
    opens a draft and records into it in one transaction. That is a data-loss
    bug that only shows up when the refused append shares a transaction with
    the thing being recorded, which is exactly what ``seed_draft`` and any mock
    recorded in one go will do.
    """
    league = _league(session)
    draft = _draft(session, league)
    seats = _seat_ids(draft)
    draft_id = draft.id

    with pytest.raises(DraftLogError) as caught:
        service.record_sale(
            session,
            draft,
            participant_id=seats[1],
            amount=Decimal("6.00"),
            player_label="Ilario Bexley",
            player_id=987654321,
        )
    assert caught.value.code == "draft_row_rejected"

    # Assert the presence of what should have survived, not the absence of an
    # error: the draft, all four seats, and the ability to record afterwards.
    survived = session.get(Draft, draft_id)
    assert survived is not None
    assert len(survived.participants) == 4

    state = service.record_sale(
        session, draft, participant_id=seats[1], amount=Decimal("6.00"), player_label="Dov Kestrel"
    )
    assert state.last_sequence == 1
    assert len(service.load_events(session, draft)) == 1


def test_a_legal_derivation_that_the_row_check_refuses_is_also_permanent(
    session: Session,
) -> None:
    """The second reachable input review named, and the sharper of the two.

    A sale carrying ``player_id`` with no ``player_label`` is legal to derive
    while a lot is open -- ``_apply_sale`` takes the label from the lot -- but
    the stored row trips ``player_id_requires_label``. Derivation accepting
    something storage refuses is precisely the seam a blanket ``except`` hides.
    """
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    opened = service.record_nomination(
        session, draft, participant_id=seats[1], player_label="Dov Kestrel"
    )
    assert opened.open_lot is not None

    with pytest.raises(DraftLogError) as caught:
        service.record_sale(
            session, draft, participant_id=seats[2], amount=Decimal("9.00"), player_id=4242
        )

    assert caught.value.code == "draft_row_rejected"
    # The lot is untouched: the refusal cost the log nothing.
    still = service.load_state(session, draft)
    assert still.open_lot is not None
    assert still.open_lot.player_label == "Dov Kestrel"
    assert still.last_sequence == 1


def test_a_real_unique_violation_is_reported_as_the_retryable_conflict(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one storage failure that IS transient, driven through the handler.

    Every other test that produces ``draft_sequence_conflict`` reaches the
    optimistic check in Python and never touches the database. A tripwire in
    the ``IntegrityError`` handler confirmed that no test in the suite reached
    it at all, which is how a blanket ``except`` survived review -- and why the
    Postgres branch of :func:`_violated_constraint` was unexercised while
    looking covered.

    Forcing ``_append`` to misread the log reproduces exactly what a losing
    writer in a real race does: computes a sequence that has since been taken,
    and hands the constraint a duplicate.
    """
    draft = _draft(session, _league(session))
    seats = _seat_ids(draft)
    service.record_sale(
        session, draft, participant_id=seats[1], amount=Decimal("5.00"), player_label="Dov Kestrel"
    )
    service.record_sale(
        session,
        draft,
        participant_id=seats[2],
        amount=Decimal("7.00"),
        player_label="Marek Sandoval",
    )
    stale = service.load_events(session, draft)[:1]
    assert len(stale) == 1, "presence: the stale view must contain the first event"

    monkeypatch.setattr(service, "load_events", lambda _session, _draft: stale)

    with pytest.raises(DraftLogError) as caught:
        service.record_sale(
            session,
            draft,
            participant_id=seats[3],
            amount=Decimal("9.00"),
            player_label="Teodor Fane",
        )

    assert caught.value.code == "draft_sequence_conflict"
    assert "append again" in caught.value.detail

    monkeypatch.undo()
    # The log is intact and still appendable: the savepoint discarded the
    # refused row and nothing else, on whichever dialect this ran on.
    assert len(service.load_events(session, draft)) == 2
    recovered = service.record_sale(
        session, draft, participant_id=seats[3], amount=Decimal("9.00"), player_label="Teodor Fane"
    )
    assert recovered.last_sequence == 3
