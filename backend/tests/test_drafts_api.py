"""The HTTP contract a draft screen is entitled to rely on.

These tests exist because the screen is being built by a different lane against
this contract and nothing else. Every claim the route docstrings make to that
reader is asserted here: the shape of the payload, the status code each refusal
produces, that paging is by sequence and never by time, that a refused append
leaves no row, and that the surface offers no way to edit or delete a recorded
event.

The last one is asserted by *inspecting the routing table*, not by observing a
405. A 405 is what FastAPI returns for a path that exists with other methods,
so it is equally consistent with "no such route" and "the route was removed
from the app but is still registered somewhere" - the routing table says which.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hoops_gm.db.models.draft import Draft
from hoops_gm.db.models.enums import DraftType
from hoops_gm.db.models.league import League
from hoops_gm.draft import service as draft_service

_MUTATING = {"PUT", "PATCH", "DELETE"}


def _league(
    session: Session,
    *,
    draft_type: DraftType = DraftType.AUCTION,
    team_count: int = 4,
    roster_size: int = 2,
    budget: Decimal | None = Decimal("200.00"),
    name: str = "api mock",
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
    session.commit()
    session.refresh(league)
    return league


def _create(client: TestClient, league: League, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "league_id": league.id,
        "name": "recorded mock",
        "is_mock": True,
        "tool_usage": "blind",
        "participants": [
            {"team_slot": slot, "display_name": f"Team {slot}", "is_owner": slot == 1}
            for slot in range(1, (league.team_count or 0) + 1)
        ],
    }
    body.update(overrides)
    response = client.post("/api/v1/drafts", json=body)
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()
    return payload


def _seats(state: dict[str, Any]) -> dict[int, int]:
    return {seat["team_slot"]: seat["id"] for seat in state["participants"]}


def test_creating_a_draft_returns_the_whole_derived_state(
    client: TestClient, session: Session
) -> None:
    """A create is a read too, so the screen never needs a second round trip."""
    state = _create(client, _league(session))

    assert state["status"] == "setup"
    assert state["last_sequence"] == 0
    assert state["selections_made"] == 0
    assert state["format"] == {
        "draft_type": "auction",
        "team_count": 4,
        "roster_size": 2,
        "total_roster_slots": 8,
        "auction_budget": "200.00",
    }
    assert [seat["team_slot"] for seat in state["participants"]] == [1, 2, 3, 4]
    assert [seat["source_seat"] for seat in state["participants"]] == [None, None, None, None]
    assert [seat["is_owner"] for seat in state["participants"]] == [True, False, False, False]
    assert state["open_lot"] is None
    assert state["next_pick"] is None, "An auction has no turn order to publish."
    assert state["league_format_drift"] is None


def test_an_auction_lot_cycle_over_http(client: TestClient, session: Session) -> None:
    """The path the owner's mock actually walks: nominate, bid, sell."""
    state = _create(client, _league(session))
    draft_id = state["id"]
    seats = _seats(state)

    nominated = client.post(
        f"/api/v1/drafts/{draft_id}/events",
        json={
            "event_type": "nomination",
            "participant_id": seats[1],
            "player_label": "Ansel Whitcombe",
            "amount": "1.00",
        },
    )
    assert nominated.status_code == 201, nominated.text
    lot = nominated.json()["open_lot"]
    assert lot["player_label"] == "Ansel Whitcombe"
    assert lot["high_bid_amount"] == "1.00"
    assert lot["high_bid_participant_id"] == seats[1]

    bid = client.post(
        f"/api/v1/drafts/{draft_id}/events",
        json={"event_type": "bid", "participant_id": seats[3], "amount": "18.00"},
    )
    assert bid.status_code == 201, bid.text
    assert bid.json()["open_lot"]["high_bid_participant_id"] == seats[3]

    sold = client.post(
        f"/api/v1/drafts/{draft_id}/events",
        json={"event_type": "sale", "participant_id": seats[3], "amount": "21.00"},
    )
    assert sold.status_code == 201, sold.text
    final = sold.json()

    assert final["open_lot"] is None
    assert final["selections_made"] == 1
    assert final["status"] == "in_progress"
    buyer = next(seat for seat in final["participants"] if seat["id"] == seats[3])
    assert buyer["spent"] == "21.00"
    assert buyer["remaining_budget"] == "179.00"
    assert buyer["slots_filled"] == 1
    assert [holding["player_label"] for holding in buyer["holdings"]] == ["Ansel Whitcombe"]
    assert buyer["holdings"][0]["price"] == "21.00"
    assert buyer["holdings"][0]["event_sequence"] == 3


def test_the_screen_can_trace_a_holding_back_to_its_event(
    client: TestClient, session: Session
) -> None:
    """Lineage, not just totals - the screen must be able to say where a number came from."""
    state = _create(client, _league(session))
    draft_id = state["id"]
    seats = _seats(state)
    client.post(
        f"/api/v1/drafts/{draft_id}/events",
        json={
            "event_type": "sale",
            "participant_id": seats[2],
            "amount": "31.00",
            "player_label": "Dov Kestrel",
        },
    )

    current = client.get(f"/api/v1/drafts/{draft_id}").json()
    holder = next(seat for seat in current["participants"] if seat["id"] == seats[2])
    sequence = holder["holdings"][0]["event_sequence"]

    log = client.get(f"/api/v1/drafts/{draft_id}/events").json()
    source = next(row for row in log["events"] if row["sequence"] == sequence)
    assert source["event_type"] == "sale"
    assert source["amount"] == holder["holdings"][0]["price"]
    assert source["participant_id"] == seats[2]
    assert holder["spent"] == source["amount"]


def test_events_page_by_sequence_and_report_the_whole_log_end(
    client: TestClient, session: Session
) -> None:
    """``last_sequence`` is the end of the log, never the end of the page.

    A poller that treated the page end as the log end would stop early and
    silently show a stale board for the rest of the draft.
    """
    state = _create(client, _league(session, team_count=4, roster_size=4))
    draft_id = state["id"]
    seats = _seats(state)
    for index in range(4):
        client.post(
            f"/api/v1/drafts/{draft_id}/events",
            json={
                "event_type": "sale",
                "participant_id": seats[(index % 4) + 1],
                "amount": "3.00",
                "player_label": f"Ansel Whitcombe {'x' * (index + 1)}",
            },
        )

    page = client.get(f"/api/v1/drafts/{draft_id}/events", params={"limit": 2}).json()
    assert [row["sequence"] for row in page["events"]] == [1, 2]
    assert page["since_sequence"] == 0
    assert page["last_sequence"] == 4

    rest = client.get(
        f"/api/v1/drafts/{draft_id}/events", params={"since_sequence": 2, "limit": 2}
    ).json()
    assert [row["sequence"] for row in rest["events"]] == [3, 4]
    assert rest["last_sequence"] == 4

    beyond = client.get(f"/api/v1/drafts/{draft_id}/events", params={"since_sequence": 4}).json()
    assert beyond["events"] == []
    assert beyond["last_sequence"] == 4


def test_a_voided_event_stays_in_the_log_and_says_what_voided_it(
    client: TestClient, session: Session
) -> None:
    """A correction is an event. The screen can show that a price was withdrawn."""
    state = _create(client, _league(session))
    draft_id = state["id"]
    seats = _seats(state)
    client.post(
        f"/api/v1/drafts/{draft_id}/events",
        json={
            "event_type": "sale",
            "participant_id": seats[2],
            "amount": "40.00",
            "player_label": "Ilario Bexley",
        },
    )
    voided = client.post(
        f"/api/v1/drafts/{draft_id}/events",
        json={"event_type": "void", "supersedes_sequence": 1, "note": "misheard the price"},
    )
    assert voided.status_code == 201, voided.text
    after = voided.json()
    assert after["selections_made"] == 0
    assert after["voided_sequences"] == [1]
    assert after["last_sequence"] == 2, "The void is itself recorded, so the log grew."

    log = client.get(f"/api/v1/drafts/{draft_id}/events").json()
    assert [row["sequence"] for row in log["events"]] == [1, 2]
    assert log["events"][0]["voided_by_sequence"] == 2
    assert log["events"][1]["voided_by_sequence"] is None
    assert log["events"][1]["note"] == "misheard the price"


def test_a_stale_writer_is_refused_with_a_conflict(client: TestClient, session: Session) -> None:
    """409 and not 422, because the caller should re-read and retry rather than fix a field."""
    state = _create(client, _league(session))
    draft_id = state["id"]
    seats = _seats(state)
    body = {
        "event_type": "sale",
        "participant_id": seats[1],
        "amount": "5.00",
        "player_label": "Marek Sandoval",
        "expected_last_sequence": 0,
    }
    assert client.post(f"/api/v1/drafts/{draft_id}/events", json=body).status_code == 201

    replayed = client.post(f"/api/v1/drafts/{draft_id}/events", json=body)
    assert replayed.status_code == 409
    assert replayed.json()["error"] == "draft_sequence_conflict"

    log = client.get(f"/api/v1/drafts/{draft_id}/events").json()
    assert log["last_sequence"] == 1, "The refused append must not have left a row."


@pytest.mark.parametrize(
    ("body", "expected_error"),
    [
        (
            {"event_type": "bid", "participant_id": None, "amount": "5.00"},
            "draft_no_open_lot",
        ),
        (
            {"event_type": "void", "supersedes_sequence": 99},
            "draft_void_target_missing",
        ),
    ],
)
def test_a_refusal_is_a_422_carrying_its_code(
    client: TestClient, session: Session, body: dict[str, Any], expected_error: str
) -> None:
    """The code is the contract. A screen keys its message off it, not off prose."""
    state = _create(client, _league(session))
    draft_id = state["id"]
    seats = _seats(state)
    sent = dict(body)
    if "participant_id" in sent:
        sent["participant_id"] = seats[1]

    response = client.post(f"/api/v1/drafts/{draft_id}/events", json=sent)
    assert response.status_code == 422, response.text
    assert response.json()["error"] == expected_error

    log = client.get(f"/api/v1/drafts/{draft_id}/events").json()
    assert log["last_sequence"] == 0, "A refused append leaves no row and no sequence hole."


def test_a_sale_above_the_assumed_budget_is_accepted_and_flagged(
    client: TestClient, session: Session
) -> None:
    """**This test replaces a removed assertion, and the removal is the point.**

    ``test_a_refusal_is_a_422_carrying_its_code`` used to parametrise a third
    case: a ``500.00`` sale for "Teodor Fane" against a ``200.00`` draft,
    asserting ``422 draft_budget_exceeded``. That assertion is gone. It was
    pinning a defect rather than a contract.

    **Why the old behaviour was wrong, stated so it can be disagreed with
    cheaply.** ``Draft.auction_budget`` is one scalar for the whole draft — grep
    ``DraftParticipant`` in ``db/models`` and there is no budget column — and
    ``formats.py`` copies it from the single nullable ``League.auction_budget``.
    The owner's league sets each seat's bank from last season's final totals, so
    that scalar is wrong for most seats by construction. The refusal fired in
    ``_apply_sale`` three lines above ``board.add``, so the pick never reached
    the board: a sale the recorder watched clear vanished, which is exactly the
    owner's stated walk-away condition ("it loses track of the draft ... misses
    one"). The refusal was also filed into ``skipped_reason`` by the capture
    ingest path, and nothing clears that column, so a retry deduped against the
    burned row instead of re-running.

    A recorded sale above the assumed budget means our assumption is wrong, not
    that the sale did not happen. The contract asserted here is the replacement:
    **201, the pick is on the board, and the wrongness is named on the seat.**
    """
    state = _create(client, _league(session))
    draft_id = state["id"]
    seats = _seats(state)

    response = client.post(
        f"/api/v1/drafts/{draft_id}/events",
        json={
            "event_type": "sale",
            "participant_id": seats[1],
            "amount": "500.00",
            "player_label": "Teodor Fane",
        },
    )
    assert response.status_code == 201, response.text

    body = client.get(f"/api/v1/drafts/{draft_id}").json()
    seat = {each["team_slot"]: each for each in body["participants"]}[1]

    # The assertion the old behaviour could not satisfy. Everything below is
    # worthless without this one: the pick that happened is on the board.
    assert [held["player_label"] for held in seat["holdings"]] == ["Teodor Fane"]
    assert body["selections_made"] == 1

    # Signed, and published as a string like every other money field.
    assert seat["spent"] == "500.00"
    assert seat["remaining_budget"] == "-300.00"
    assert seat["over_assumed_budget"] is True

    # No other seat is flagged, so the flag is about this seat rather than about
    # the draft.
    assert [each["over_assumed_budget"] for each in body["participants"]].count(True) == 1


@pytest.mark.parametrize("draft_type", [DraftType.AUCTION, DraftType.SNAKE])
def test_over_assumed_budget_never_disagrees_with_remaining_budget(
    client: TestClient, session: Session, draft_type: DraftType
) -> None:
    """``over_assumed_budget`` is a total function of ``remaining_budget``.

    This is the executable half of the argument for typing the field ``bool``
    rather than ``bool | None``. A nullable flag would be a *second* nullable
    encoding of "does this draft have a budget at all", which
    ``remaining_budget`` already answers — two fields that can represent
    disagreeing answers (``remaining_budget: "138.00"`` beside
    ``over_assumed_budget: null``) where one field can not.

    So the claim is not "``False`` reads better than ``None``", which is
    taste. It is the identity below, which either holds for every seat of both
    draft types or does not.

    **The write is asserted and the flagged count is pinned per draft type.**
    Without both, this degenerates into the failure mode this repository keeps
    finding: a POST that silently did nothing leaves four untouched seats, the
    identity holds trivially on four ``False``s, and the test reports green
    while never once exercising the ``True`` branch it exists for. That is not
    hypothetical here — the first draft of this test sent ``amount: None`` on
    the snake ``pick``, which the request model refuses as ``extra_forbidden``,
    and the assertion below is what turned a silent green into a red.
    """
    budget = Decimal("200.00") if draft_type is DraftType.AUCTION else None
    is_auction = draft_type is DraftType.AUCTION
    league = _league(
        session, draft_type=draft_type, budget=budget, name=f"identity {draft_type.value}"
    )
    state = _create(client, league)
    draft_id = state["id"]
    seats = _seats(state)

    # ``amount`` is omitted rather than passed as ``None`` on the pick: the
    # discriminated request model forbids the key outright on that branch.
    body_out: dict[str, Any] = {
        "event_type": "sale" if is_auction else "pick",
        "participant_id": seats[1],
        "player_label": "Teodor Fane",
    }
    if is_auction:
        body_out["amount"] = "500.00"

    written = client.post(f"/api/v1/drafts/{draft_id}/events", json=body_out)
    assert written.status_code == 201, written.text

    body = client.get(f"/api/v1/drafts/{draft_id}").json()
    assert body["selections_made"] == 1, "the pick this test reasons about was never recorded"

    checked = 0
    for seat in body["participants"]:
        remaining = seat["remaining_budget"]
        expected = remaining is not None and Decimal(remaining) < 0
        assert seat["over_assumed_budget"] == expected, seat
        checked += 1
    assert checked == 4, "A vacuous pass over zero seats would prove nothing."

    # The discriminating half: the auction case must actually reach ``True``,
    # and the snake case must reach it nowhere.
    flagged = sum(1 for seat in body["participants"] if seat["over_assumed_budget"])
    assert flagged == (1 if is_auction else 0)


def test_an_unknown_draft_is_a_404_not_a_500(client: TestClient) -> None:
    for path in ("/api/v1/drafts/9999", "/api/v1/drafts/9999/events"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.json()["error"] == "draft_not_found"


def test_an_unknown_league_is_refused_before_any_row_is_written(
    client: TestClient, session: Session
) -> None:
    response = client.post(
        "/api/v1/drafts",
        json={
            "league_id": 9999,
            "name": "orphan",
            "tool_usage": "blind",
            "participants": [{"team_slot": 1, "display_name": "Team 1", "is_owner": True}],
        },
    )
    assert response.status_code == 404
    assert response.json()["error"] == "draft_league_not_found"
    assert client.get("/api/v1/drafts").json()["drafts"] == []


def test_a_bid_carrying_a_player_is_rejected_by_shape(client: TestClient, session: Session) -> None:
    """The lot names the player, so a bid that names one is a category error.

    Caught by ``extra="forbid"`` on the request model rather than by the log,
    which is why this is a 422 carrying FastAPI's own validation body and no
    ``error`` code of ours. Without that setting pydantic drops the field
    silently and the recorder is told the bid was accepted *and* that the
    player was captured, only one of which is true.
    """
    state = _create(client, _league(session))
    seats = _seats(state)
    response = client.post(
        f"/api/v1/drafts/{state['id']}/events",
        json={
            "event_type": "bid",
            "participant_id": seats[1],
            "amount": "5.00",
            "player_label": "Oskar Vellamo",
        },
    )
    assert response.status_code == 422
    assert "player_label" in response.text


def test_an_unknown_event_type_is_refused_by_the_discriminator(
    client: TestClient, session: Session
) -> None:
    state = _create(client, _league(session))
    response = client.post(
        f"/api/v1/drafts/{state['id']}/events",
        json={"event_type": "trade", "participant_id": 1},
    )
    assert response.status_code == 422


def test_the_list_reports_enough_to_choose_a_draft(client: TestClient, session: Session) -> None:
    first = _create(client, _league(session, name="first"), name="first mock")
    second = _create(client, _league(session, name="second"), name="second mock")

    listed = client.get("/api/v1/drafts").json()["drafts"]
    assert [row["id"] for row in listed] == [second["id"], first["id"]], "Newest first."
    assert [row["name"] for row in listed] == ["second mock", "first mock"]
    assert all(row["tool_usage"] == "blind" for row in listed)
    assert all(row["format"]["draft_type"] == "auction" for row in listed)
    assert all(row["last_sequence"] == 0 for row in listed)


def test_a_snake_draft_publishes_whose_turn_it_is(client: TestClient, session: Session) -> None:
    league = _league(
        session,
        draft_type=DraftType.SNAKE,
        team_count=3,
        roster_size=2,
        budget=None,
        name="snake api",
    )
    state = _create(client, league, name="ordered mock")
    draft_id = state["id"]
    seats = _seats(state)

    assert state["next_pick"] == {
        "overall_pick": 1,
        "round_number": 1,
        "pick_in_round": 1,
        "team_slot": 1,
        "participant_id": seats[1],
    }
    assert [seat["source_seat"] for seat in state["participants"]] == [None, None, None]
    assert state["format"]["auction_budget"] is None
    assert all(seat["remaining_budget"] is None for seat in state["participants"])

    names = ["Ansel Whitcombe", "Dov Kestrel", "Ilario Bexley"]
    for index, label in enumerate(names):
        current = client.get(f"/api/v1/drafts/{draft_id}").json()
        turn = current["next_pick"]
        assert turn["overall_pick"] == index + 1
        response = client.post(
            f"/api/v1/drafts/{draft_id}/events",
            json={
                "event_type": "pick",
                "participant_id": turn["participant_id"],
                "player_label": label,
            },
        )
        assert response.status_code == 201, response.text

    turned = client.get(f"/api/v1/drafts/{draft_id}").json()["next_pick"]
    assert turned == {
        "overall_pick": 4,
        "round_number": 2,
        "pick_in_round": 1,
        "team_slot": 3,
        "participant_id": seats[3],
    }, "Round two runs backwards, so slot 3 picks again."


def test_a_pick_out_of_turn_is_refused(client: TestClient, session: Session) -> None:
    league = _league(
        session,
        draft_type=DraftType.SNAKE,
        team_count=3,
        roster_size=2,
        budget=None,
        name="snake turn",
    )
    state = _create(client, league, name="ordered mock")
    seats = _seats(state)
    response = client.post(
        f"/api/v1/drafts/{state['id']}/events",
        json={"event_type": "pick", "participant_id": seats[2], "player_label": "Ansel Whitcombe"},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "draft_pick_out_of_turn"


def test_a_rotated_source_binding_resolves_the_turn_without_redefining_team_slot(
    client: TestClient, session: Session
) -> None:
    """The source column orders the pick; the public team slot names the participant."""
    league = _league(
        session,
        draft_type=DraftType.SNAKE,
        team_count=3,
        roster_size=2,
        budget=None,
        name="rotated source order",
    )
    state = _create(
        client,
        league,
        participants=[
            {"team_slot": 1, "source_seat": 2, "display_name": "Team 1", "is_owner": True},
            {"team_slot": 2, "source_seat": 3, "display_name": "Team 2"},
            {"team_slot": 3, "source_seat": 1, "display_name": "Team 3"},
        ],
    )
    by_slot = {seat["team_slot"]: seat for seat in state["participants"]}

    assert [by_slot[slot]["source_seat"] for slot in (1, 2, 3)] == [2, 3, 1]
    assert state["next_pick"]["team_slot"] == 3
    assert state["next_pick"]["participant_id"] == by_slot[3]["id"]

    draft = session.get(Draft, state["id"])
    assert draft is not None
    internal = draft_service.load_state(session, draft)
    assert internal.next_pick is not None
    assert internal.next_pick.team_slot == 1, "The frozen ordered coordinate remains source seat 1."

    recorded = client.post(
        f"/api/v1/drafts/{state['id']}/events",
        json={
            "event_type": "pick",
            "participant_id": by_slot[3]["id"],
            "player_label": "Nikola Jokic",
        },
    )
    assert recorded.status_code == 201, recorded.text
    assert recorded.json()["participants"][2]["holdings"][0]["player_label"] == "Nikola Jokic"


@pytest.mark.parametrize(
    "source_seats",
    [
        [1, 2, None],
        [1, 1, 3],
        [1, 2, 4],
    ],
    ids=["partial", "duplicate", "out_of_range"],
)
def test_draft_creation_rejects_any_source_binding_that_is_not_a_bijection(
    client: TestClient,
    session: Session,
    source_seats: list[int | None],
) -> None:
    league = _league(
        session,
        draft_type=DraftType.SNAKE,
        team_count=3,
        roster_size=2,
        budget=None,
        name="invalid source order",
    )
    response = client.post(
        "/api/v1/drafts",
        json={
            "league_id": league.id,
            "name": "invalid binding",
            "tool_usage": "blind",
            "participants": [
                {
                    "team_slot": team_slot,
                    "source_seat": source_seat,
                    "display_name": f"Team {team_slot}",
                }
                for team_slot, source_seat in enumerate(source_seats, start=1)
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"] == "draft_source_seat_binding_invalid"
    assert client.get("/api/v1/drafts").json()["drafts"] == []


def test_draft_creation_rejects_a_nonpositive_source_seat_at_the_schema_boundary(
    client: TestClient, session: Session
) -> None:
    league = _league(
        session,
        draft_type=DraftType.SNAKE,
        team_count=2,
        roster_size=2,
        budget=None,
        name="invalid source ordinal",
    )
    response = client.post(
        "/api/v1/drafts",
        json={
            "league_id": league.id,
            "name": "invalid source ordinal",
            "tool_usage": "blind",
            "participants": [
                {"team_slot": 1, "source_seat": 0, "display_name": "Team 1"},
                {"team_slot": 2, "source_seat": 2, "display_name": "Team 2"},
            ],
        },
    )

    assert response.status_code == 422
    assert "source_seat" in response.text


def test_the_snapshot_survives_the_league_changing_underneath(
    client: TestClient, session: Session
) -> None:
    """A recorded draft is a historical fact, so it is never re-read from the league.

    The drift is published rather than hidden, so a screen can say that the
    league has since been edited without the recorded board moving.
    """
    league = _league(session)
    state = _create(client, league)
    draft_id = state["id"]

    league.auction_budget = Decimal("300.00")
    league.team_count = 12
    session.commit()

    after = client.get(f"/api/v1/drafts/{draft_id}").json()
    assert after["format"]["auction_budget"] == "200.00"
    assert after["format"]["team_count"] == 4
    assert after["league_format_drift"] == {
        "draft_type": "auction",
        "team_count": 12,
        "roster_size": 2,
        "auction_budget": "300.00",
        "error": None,
    }, "The whole current league format, not a sparse diff - see LeagueFormatDrift."


def test_closing_a_draft_refuses_further_events(client: TestClient, session: Session) -> None:
    state = _create(client, _league(session))
    draft_id = state["id"]
    seats = _seats(state)

    closed = client.post(f"/api/v1/drafts/{draft_id}/events", json={"event_type": "closed"})
    assert closed.status_code == 201, closed.text
    assert closed.json()["status"] == "closed"

    refused = client.post(
        f"/api/v1/drafts/{draft_id}/events",
        json={
            "event_type": "sale",
            "participant_id": seats[1],
            "amount": "4.00",
            "player_label": "Rune Halvorsen",
        },
    )
    assert refused.status_code == 422
    assert refused.json()["error"] == "draft_closed"

    reopened = client.post(
        f"/api/v1/drafts/{draft_id}/events",
        json={"event_type": "void", "supersedes_sequence": 1},
    )
    assert reopened.status_code == 201, reopened.text
    assert reopened.json()["status"] == "setup"


def test_the_draft_surface_offers_no_way_to_edit_or_delete(client: TestClient) -> None:
    """Append-only is a property of the surface, asserted against the published contract.

    Read from the OpenAPI document rather than from a 405, because a 405 cannot
    tell "this method is not offered" apart from "this path is not ours at
    all". The document is also the artefact the frontend lane will generate a
    client from, so it is the contract that actually binds.

    ``app.routes`` was the obvious place to look and is wrong: this FastAPI
    keeps an included router as a single lazy ``_IncludedRouter`` entry, so a
    scan of it finds no draft routes at all and every "no mutating method"
    assertion below would pass vacuously. That is exactly the shape of check
    this project keeps getting bitten by, which is why the presence assertion
    comes first.

    The feed paths are pinned here rather than mounted under a prefix of their
    own. A separate prefix would have left this exact-set assertion untouched
    and passing while adding unscanned draft routes, which is evading the check
    rather than satisfying it. ``GET /feed`` reports freshness and
    reconciliation, ``GET /source-board`` reports rendered source evidence,
    and ``POST /feed/ingest`` appends only independently attributed RPC claims
    through ``draft_service``. None offers edit or delete, so the property this
    test defends still holds over the wider surface.
    """
    document = cast("FastAPI", client.app).openapi()
    draft_routes = {
        (path, method.upper())
        for path, operations in document["paths"].items()
        if path.startswith("/api/v1/drafts")
        for method in operations
    }
    assert draft_routes, "Assert presence first - an empty set would satisfy every check below."

    assert {path for path, _ in draft_routes} == {
        "/api/v1/drafts",
        "/api/v1/drafts/{draft_id}",
        "/api/v1/drafts/{draft_id}/events",
        "/api/v1/drafts/{draft_id}/feed",
        "/api/v1/drafts/{draft_id}/feed/ingest",
        "/api/v1/drafts/{draft_id}/source-board",
    }

    mutating = {(path, method) for path, method in draft_routes if method in _MUTATING}
    assert mutating == set(), f"The draft log must be append-only, found {sorted(mutating)}."

    assert draft_routes == {
        ("/api/v1/drafts", "GET"),
        ("/api/v1/drafts", "POST"),
        ("/api/v1/drafts/{draft_id}", "GET"),
        ("/api/v1/drafts/{draft_id}/events", "GET"),
        ("/api/v1/drafts/{draft_id}/events", "POST"),
        ("/api/v1/drafts/{draft_id}/feed", "GET"),
        ("/api/v1/drafts/{draft_id}/feed/ingest", "POST"),
        ("/api/v1/drafts/{draft_id}/source-board", "GET"),
    }


def test_recording_how_the_draft_was_run_is_not_optional(
    client: TestClient, session: Session
) -> None:
    """``tool_usage`` has no default, and that is deliberate (R38).

    Whether this tool was on the recorder's screen decides whether the draft is
    evidence about how humans draft or evidence about this tool's own advice.
    A default would silently answer that question for every mock recorded
    before anyone noticed the field existed, and it is not recoverable later.
    """
    league = _league(session)
    body: dict[str, Any] = {
        "league_id": league.id,
        "name": "unlabelled mock",
        "participants": [
            {"team_slot": slot, "display_name": f"Team {slot}", "is_owner": slot == 1}
            for slot in range(1, 5)
        ],
    }
    response = client.post("/api/v1/drafts", json=body)
    assert response.status_code == 422
    assert "tool_usage" in response.text

    body["tool_usage"] = "instrumented"
    accepted = client.post("/api/v1/drafts", json=body)
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["tool_usage"] == "instrumented"


def test_the_surface_publishes_no_decision_numbers(client: TestClient, session: Session) -> None:
    """Scope guard. Valuation, prices and p(play) are quant's and are blocked upstream.

    Read from the **schema**, not from one populated payload. The first version
    of this test walked a live auction response and did not catch a ``max_bid``
    added to ``NextPickOut``, because an auction publishes ``next_pick: null``
    and that model never appeared in the body at all. A guard that only sees
    the fields some fixture happened to populate is a guard over the fixture.

    The mutation harness found that, not review.
    """
    state = _create(client, _league(session))
    seats = _seats(state)
    populated = client.post(
        f"/api/v1/drafts/{state['id']}/events",
        json={
            "event_type": "sale",
            "participant_id": seats[1],
            "amount": "12.00",
            "player_label": "Cassian Ferro",
        },
    ).json()

    forbidden = {
        "projected_value",
        "expected_price",
        "par",
        "inflation",
        "inflation_factor",
        "recommendation",
        "recommended_player_id",
        "p_play",
        "expected_games",
        "z_score",
        "g_score",
        "max_bid",
        "value_over_replacement",
    }

    document = cast("FastAPI", client.app).openapi()
    schemas = document["components"]["schemas"]
    seen: set[str] = set()
    fields: set[str] = set()

    def collect(node: object) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.rsplit("/", 1)[-1]
                if name not in seen:
                    seen.add(name)
                    collect(schemas[name])
                return
            fields.update(node.get("properties", {}))
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    for path, operations in document["paths"].items():
        if path.startswith("/api/v1/drafts"):
            collect(operations)

    assert "NextPickOut" in seen, (
        "Assert presence first. A ref walk that reached nothing would report no "
        "forbidden fields and read as success - which is how the earlier "
        "payload-only version of this test passed while missing a real field."
    )
    assert {"spent", "remaining_budget", "overall_pick", "player_label"} <= fields
    assert forbidden & fields == set(), (
        f"Decision numbers belong to quant, found {sorted(forbidden & fields)}."
    )

    def walk(node: object) -> None:
        if isinstance(node, dict):
            overlap = forbidden & set(node)
            assert overlap == set(), f"Decision numbers belong to quant, found {sorted(overlap)}."
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(populated)
    assert populated["participants"][0]["spent"] == "12.00", (
        "Assert the presence of the descriptive number too, so the guard above "
        "is not passing merely because the payload is empty."
    )
