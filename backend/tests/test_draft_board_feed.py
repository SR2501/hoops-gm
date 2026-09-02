"""Joining a rendered board reading to the draft feed, under ADR-020.

This is the critical path and it is worth saying why in one place. Both
automatic routes to live pick data are negative: ``/fxpa/req`` is issued by
Fantrax's own service worker and no userscript can observe it (49 of 49
captures), and ``getDraftPicks`` returned ``{"currentDraftPicks":[]}`` against a
finished 216-pick draft. ``board_dom.parse_draft_board`` reading the rendered
page is the only live source of picks that exists, and until this unit it was
wired to nothing.

The four things asserted here are ADR-020's four decisions, and each test names
the reading under which the assertion would hold while the defect was present.
Two of them are worth flagging up front:

* **The keying test must fail on the old behaviour, not merely pass on the
  new.** Byte-keying passes any test that only asserts the new code works, so
  ``test_two_snapshots_of_one_unchanged_board_are_one_reading`` asserts a row
  count and a distinct-key count that byte-keying gets wrong (432 and 2 against
  216 and 1), and asserts the two capture-level dedupe keys appear nowhere.
* **The liveness test needs a board that has already been read.** Content
  keying means a deliberation produces snapshot after snapshot and no new
  observation at all, so the pick clock alone reports ``silent`` through a feed
  that is working perfectly. That is the cry-wolf failure ``contact_at`` exists
  to remove, arriving by a new route.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hoops_gm.db.models.bridge import BridgePayload
from hoops_gm.db.models.draft import Draft
from hoops_gm.db.models.draft_feed import (
    DraftFeedObservation,
    DraftSourceBoardReading,
    DraftSourceBoardState,
)
from hoops_gm.db.models.enums import DraftFeedTransport, DraftToolUsage, DraftType
from hoops_gm.db.models.league import FantasyTeam, League
from hoops_gm.draft import service as draft_service
from hoops_gm.draft.feed import service as feed_service
from hoops_gm.draft.feed.board_dom import (
    BOARD_BODY_CLASS,
    BoardPick,
    BoardReading,
    parse_draft_board,
)
from hoops_gm.draft.feed.observations import SourceTransport
from hoops_gm.draft.feed.recognise import (
    BOARD_RECOGNISER,
    RecognitionContext,
    board_artifact_key,
    recognise_board_snapshot,
)
from hoops_gm.draft.feed.reconcile import SourceFreshness
from hoops_gm.draft.formats import AuctionDraftFormat, LinearDraftFormat, SnakeDraftFormat

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: Adapter gate. Every board reading below is driven against markup recorded off
#: the wire, so a Fantrax rename turns these red rather than turning the board
#: silently short.
pytestmark = pytest.mark.adapter_contract

LEAGUE = "abc123league"
NOW = datetime(2026, 10, 18, 23, 14, tzinfo=UTC)

SEATS = 12
ROUNDS = 18
TOTAL_PICKS = SEATS * ROUNDS  # 216
EARLY_PICKS = 7
SHORT_ROUNDS = 14
SHORT_PICKS = SEATS * SHORT_ROUNDS

_DIV_TOKEN = re.compile(r"<div\b|</div>")


def load(name: str) -> str:
    return (FIXTURES / f"fantrax_draft_board_{name}.html").read_text(encoding="utf-8")


def load_early_with_distinct_names() -> str:
    """Undo fixture anonymisation that collapses all labels under normalize_key."""
    html = load("early")
    labels = (
        "Nikola Jokic",
        "Anthony Edwards",
        "Tyrese Haliburton",
        "Jalen Williams",
        "Cade Cunningham",
        "Paolo Banchero",
        "Scottie Barnes",
    )
    anonymised = (
        "P. Player165",
        "P. Player028",
        "P. Player088",
        "P. Player155",
        "P. Player294",
        "P. Player051",
        "P. Player183",
    )
    for old, new in zip(anonymised, labels, strict=True):
        assert html.count(old) == 1
        html = html.replace(old, new)
    return html


def _div_end(html: str, start: int) -> int:
    depth = 0
    for token in _DIV_TOKEN.finditer(html, start):
        if token.group() == "<div":
            depth += 1
            continue
        depth -= 1
        if depth == 0:
            return token.end()
    raise AssertionError("fixture contains an unclosed div")


def uniformly_short_board(*, rounds: int = SHORT_ROUNDS, empty: bool = False) -> str:
    """Cut every recorded source column to the same number of rendered cells."""
    html = load("predraft" if empty else "complete")
    column_open = '<div class="league-draft-board__column'
    item_open = '<div class="league-draft-board__item '
    column_starts = [match.start() for match in re.finditer(re.escape(column_open), html)]
    assert len(column_starts) == SEATS

    removals: list[tuple[int, int]] = []
    for column_start in column_starts:
        column_end = _div_end(html, column_start)
        item_starts = [
            column_start + match.start()
            for match in re.finditer(re.escape(item_open), html[column_start:column_end])
        ]
        assert len(item_starts) == ROUNDS
        removals.extend((start, _div_end(html, start)) for start in item_starts[rounds:])

    for start, end in sorted(removals, reverse=True):
        html = html[:start] + html[end:]
    # The measured /draft/board route carries no chat pane. Hiding only its
    # parser-owned class keeps this mutation confined to independently recorded
    # source markup rather than manufacturing a second board fixture.
    html = html.replace("chat-message__name", "fixture-chat-message__name")
    reading = parse_draft_board(html, captured_at=NOW)
    assert reading.rounds == rounds
    assert reading.picks_made == (0 if empty else SEATS * rounds)
    return html


def _league(
    session: Session,
    *,
    draft_type: DraftType = DraftType.SNAKE,
    fantrax_league_id: str = LEAGUE,
) -> League:
    league = League(
        fantrax_league_id=fantrax_league_id,
        name="board feed",
        season="2026-27",
        draft_type=draft_type,
        team_count=SEATS,
        roster_size=ROUNDS,
        auction_budget=Decimal("200") if draft_type is DraftType.AUCTION else None,
    )
    session.add(league)
    session.flush()
    return league


def _draft(
    session: Session,
    league: League,
    *,
    source_seats: tuple[int, ...] | None = None,
) -> Draft:
    teams = []
    for index in range(1, SEATS + 1):
        external = f"t{index}"
        team = FantasyTeam(league_id=league.id, fantrax_team_id=external, name=f"Seat {index}")
        session.add(team)
        teams.append(team)
    session.flush()
    draft = draft_service.create_draft(
        session,
        league=league,
        name="board feed",
        tool_usage=DraftToolUsage.INSTRUMENTED,
        participants=[
            draft_service.ParticipantSpec(
                team_slot=index,
                source_seat=None if source_seats is None else source_seats[index - 1],
                display_name=f"Seat {index}",
                is_owner=index == 1,
                fantasy_team_id=team.id,
            )
            for index, team in enumerate(teams, start=1)
        ],
    )
    session.flush()
    return draft


def linear_board(html: str) -> str:
    """Turn the recorded coordinate grid linear without inventing source markup."""

    def replace_coordinate(match: re.Match[str]) -> str:
        round_number = int(match.group("round"))
        pick_in_round = int(match.group("pick"))
        if round_number % 2:
            return match.group(0)
        linear_pick = SEATS + 1 - pick_in_round
        return f"{match.group('prefix')}{round_number}-{linear_pick}{match.group('suffix')}"

    transformed = re.sub(
        r"(?P<prefix><mark[^>]*>\s*)(?P<round>\d+)-(?P<pick>\d+)(?P<suffix>\s*</mark>)",
        replace_coordinate,
        html,
    )
    reading = parse_draft_board(transformed, captured_at=NOW)
    assert reading.layout == "linear"
    return transformed


def _context(
    *,
    draft_type: DraftType = DraftType.SNAKE,
    fantrax_league_id: str = LEAGUE,
) -> RecognitionContext:
    return RecognitionContext(
        fantrax_league_id=fantrax_league_id,
        team_external_ids=frozenset(f"t{index}" for index in range(1, SEATS + 1)),
        draft_type=draft_type,
    )


def _snapshot(
    session: Session,
    *,
    html: str,
    dedupe_key: str,
    created_at: datetime = NOW,
    league_id: str = LEAGUE,
    view: str = "draft",
    source: str = "rendered-view",
) -> BridgePayload:
    """A page-snapshot capture holding real recorded board markup.

    Everything here is what ``capture.js`` actually stores: the *page* URL
    rather than ``/fxpa/req``, the HTML in ``body_raw``, and ``body_json`` unset
    with a parse error beside it, which is what ``JSON.parse`` of a document
    produces.
    """
    row = BridgePayload(
        schema_name="hoops-gm.bridge-payload.v1",
        source=source,
        captured_at=created_at,
        request_method="GET",
        request_url=f"https://www.fantrax.com/fantasy/league/{league_id}/{view}",
        response_status=200,
        response_ok=True,
        response_content_type="text/html",
        body_raw=html,
        body_json=None,
        body_parse_error="Unexpected token < in JSON at position 0",
        dedupe_key=dedupe_key,
        raw_payload="{}",
        created_at=created_at,
    )
    session.add(row)
    session.flush()
    return row


def _reading(
    picks: tuple[BoardPick, ...],
    *,
    seats: tuple[str, ...] = ("A", "B"),
    rounds: int = 2,
    captured_at: datetime = NOW,
    truncated: bool = False,
) -> BoardReading:
    return BoardReading(
        captured_at=captured_at,
        source="rendered-view",
        seats=seats,
        rounds=rounds,
        picks=picks,
        layout="snake",
        truncated=truncated,
    )


def _pick(
    *,
    seat: int = 1,
    seat_name: str = "A",
    round_number: int = 1,
    pick_in_round: int = 1,
    player_name: str = "Nikola Jokic",
    player_external_id: str | None = "00abc",
) -> BoardPick:
    return BoardPick(
        seat=seat,
        seat_name=seat_name,
        round=round_number,
        pick_in_round=pick_in_round,
        overall=(round_number - 1) * 2 + pick_in_round,
        player_name=player_name,
        player_external_id=player_external_id,
    )


def _board_rows(session: Session, draft: Draft) -> list[DraftFeedObservation]:
    return [
        row
        for row in feed_service.load_observations(session, draft)
        if row.recogniser == BOARD_RECOGNISER
    ]


# --------------------------------------------------------------------------
# ADR-020 decision 2: the key is the board, not the bytes
# --------------------------------------------------------------------------


def test_two_snapshots_of_one_unchanged_board_are_one_reading(session: Session) -> None:
    """Excludes: a republishing board multiplying every pick by every snapshot.

    **This is the test that has to fail on the old behaviour.** Two captures of
    the same finished board, differing in HTML and in the userscript's own
    ``dedupe_key``, are one reading of one board. Keyed on bytes -- which is what
    ``InstantProvenance`` said before ADR-020 -- this stores 432 rows under two
    artifact keys and ``SourceFreshness.instant_count`` becomes a count of
    snapshots. Both numbers below are asserted, so byte-keying cannot pass by
    merely working.

    The HTML difference is an Angular churn class on the board body, which is
    the realistic case: the markup moves between two paints of a board nobody
    has touched.
    """
    league = _league(session)
    draft = _draft(session, league)
    original = load("complete")
    repainted = original.replace(
        f'class="{BOARD_BODY_CLASS}"',
        f'class="{BOARD_BODY_CLASS} ng-star-inserted"',
        1,
    ).replace("Seat 01 Club", "Renamed Source Label")
    assert repainted != original, "the churn substitution must actually land"

    _snapshot(session, html=original, dedupe_key="GET:aaa:111", created_at=NOW)
    _snapshot(
        session,
        html=repainted,
        dedupe_key="GET:aaa:222",
        created_at=NOW + timedelta(seconds=30),
    )

    outcome = feed_service.ingest_bridge(session, draft, _context())
    rows = _board_rows(session, draft)

    assert outcome.boards_read == 2
    assert outcome.snapshots_for_this_league == 2
    # 216, not 432.
    assert len(rows) == TOTAL_PICKS
    assert outcome.observations_written == TOTAL_PICKS
    assert outcome.observations_already_present == TOTAL_PICKS
    # One key, not two.
    keys = {row.artifact_key for row in rows}
    assert len(keys) == 1
    assert keys == {board_artifact_key(parse_draft_board(original, captured_at=NOW))}
    # ...and it is not either capture's identity, which is what byte-keying
    # would have stored.
    assert "GET:aaa:111" not in keys
    assert "GET:aaa:222" not in keys
    evidence = feed_service.source_board_evidence(session, draft, now=NOW + timedelta(seconds=30))
    assert evidence.board is not None
    assert evidence.board.columns[0].mutable_label == "Renamed Source Label"
    assert len(feed_service.load_board_readings(session, draft)) == 1

    freshness = next(
        item
        for item in feed_service.feed_status(session, draft, now=NOW).freshness
        if item.transport is SourceTransport.BRIDGE_CAPTURE
    )
    assert freshness.instant_count == TOTAL_PICKS


def test_a_board_that_gained_a_pick_is_a_different_reading(session: Session) -> None:
    """Positive control for the test above: the digest is not simply constant.

    A constant key would satisfy every assertion up there and would collapse the
    whole draft into one reading. Two genuinely different boards -- the recorded
    seven-pick board and the finished one -- must key differently and must both
    be stored.
    """
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load("early"), dedupe_key="GET:aaa:111", created_at=NOW)
    _snapshot(
        session,
        html=load("complete"),
        dedupe_key="GET:aaa:222",
        created_at=NOW + timedelta(minutes=40),
    )

    feed_service.ingest_bridge(session, draft, _context())
    rows = _board_rows(session, draft)

    assert len({row.artifact_key for row in rows}) == 2
    assert len(rows) == EARLY_PICKS + TOTAL_PICKS


def test_the_digest_ignores_what_adr_020_says_it_ignores() -> None:
    """Each exclusion, one at a time, against synthesised readings.

    Asserted on constructed :class:`BoardReading` values rather than through the
    fixtures because the fixtures cannot vary one field at a time -- and a test
    that changes two things and observes one outcome has established nothing
    about which of them mattered.

    ``seat_name`` is the exclusion with a measurement behind it: four seats in
    the recorded session changed their displayed name as owners replaced
    Fantrax's ``Mock Drafter N`` placeholder, while **0** columns ever lost a
    pick and **0** ``overall -> seat`` remappings occurred across 42 captures.
    Digesting the label would have re-keyed the entire board for a repaint.
    """
    base = _reading((_pick(),))

    # Excluded: the snapshot's own timestamp, the truncation flag, seat labels.
    assert board_artifact_key(_reading((_pick(),), captured_at=NOW + timedelta(hours=3))) == (
        board_artifact_key(base)
    )
    assert board_artifact_key(_reading((_pick(),), truncated=True)) == board_artifact_key(base)
    assert board_artifact_key(_reading((_pick(),), seats=("Mock Drafter 4", "B"))) == (
        board_artifact_key(base)
    )
    assert board_artifact_key(_reading((_pick(seat_name="renamed"),))) == board_artifact_key(base)

    # Included: the seat ordinal, the coordinate, the player, the dimensions.
    assert board_artifact_key(_reading((_pick(seat=2),))) != board_artifact_key(base)
    assert board_artifact_key(_reading((_pick(pick_in_round=2),))) != board_artifact_key(base)
    assert board_artifact_key(_reading((_pick(player_external_id="00xyz"),))) != (
        board_artifact_key(base)
    )
    assert board_artifact_key(_reading((_pick(),), rounds=3)) != board_artifact_key(base)
    assert board_artifact_key(_reading((_pick(),), seats=("A", "B", "C"))) != (
        board_artifact_key(base)
    )

    # A cell with no headshot -- a team defence, 16 of the recorded 216 -- keys
    # on its name instead, so two different defences are two different boards.
    nameless = _reading((_pick(player_external_id=None),))
    other = _reading((_pick(player_external_id=None, player_name="Boston Celtics"),))
    assert board_artifact_key(nameless) != board_artifact_key(other)


# --------------------------------------------------------------------------
# ADR-020 decision 1: one transport, told apart by the recogniser
# --------------------------------------------------------------------------


def test_a_board_reading_arrives_on_the_bridge_transport_named_as_board_dom(
    session: Session,
) -> None:
    """Excludes: a rendered board and an RPC capture witnessing each other.

    A ``rendered_view`` transport would have let those two corroborate -- same
    browser, same page, same script. ``DraftFeedTransport``'s docstring forbids
    finer values for exactly that reason, so the distinction lives in
    ``provenance.recogniser`` where it is published and cannot be mistaken for
    independence.

    The reading in which this assertion holds while the defect is present would
    need a stored row whose ``transport`` is something other than the two the
    enum defines, which the column's own type forbids.
    """
    league = _league(session)
    draft = _draft(session, league)
    html = load_early_with_distinct_names()
    _snapshot(session, html=html, dedupe_key="GET:aaa:111")

    feed_service.ingest_bridge(session, draft, _context())
    rows = _board_rows(session, draft)

    assert len(rows) == EARLY_PICKS
    assert {row.transport.value for row in rows} == {SourceTransport.BRIDGE_CAPTURE.value}
    assert {row.recogniser for row in rows} == {BOARD_RECOGNISER}
    assert BOARD_RECOGNISER.startswith("board_dom")
    # Every row points back at the capture that carried the board.
    assert all(row.bridge_payload_id is not None for row in rows)
    # The coordinate is the board's own and now has an explicit column rather
    # than being smuggled through either participant identity or the locator.
    first = min(rows, key=lambda row: row.overall_pick or 0)
    assert first.overall_pick == 1
    assert first.round_number == 1
    assert first.pick_in_round == 1
    assert first.source_seat == 1
    assert first.source_seat_label is not None
    assert first.locator == "board[1].1-1"


def test_a_board_pick_preserves_source_seat_without_participant_attribution(
    session: Session,
) -> None:
    """The board's column is source evidence, not franchise identity.

    The rendered board carries no team id anywhere -- ``draftTeamId`` and
    ``cellTeamId`` are Fantrax console vocabulary and appear nowhere in the
    markup. It therefore never supplies ``team_external_id``, never matches
    ``seat_name``, and never assumes the source column equals our ``team_slot``.
    """
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load_early_with_distinct_names(), dedupe_key="GET:aaa:111")

    feed_service.ingest_bridge(session, draft, _context())
    rows = _board_rows(session, draft)
    assert all(row.team_external_id is None for row in rows)
    assert all(row.participant_id is None for row in rows)
    assert all(row.source_seat is not None for row in rows)
    assert all(row.source_seat_label for row in rows)
    assert {row.skipped_reason for row in rows} == {"source_board_evidence_only"}

    before = feed_service.feed_status(session, draft, now=NOW)
    assert before.pending_count == 0
    applied = feed_service.apply_observations(session, draft, now=NOW)
    assert applied.applied == ()
    assert applied.skipped == ()

    status = feed_service.feed_status(session, draft, now=NOW)
    assert dict(status.skipped) == {"source_board_evidence_only": EARLY_PICKS}
    assert dict(status.unattributed_skipped) == {"source_board_evidence_only": EARLY_PICKS}, (
        "A source column is not a participant attribution without the frozen binding."
    )
    assert all(item.total == 0 for item in status.skipped_by_participant)
    assert status.applied_count == 0
    assert status.last_sequence == 0


def test_a_recorded_board_applies_through_a_deliberately_rotated_source_binding(
    client: TestClient,
    session: Session,
) -> None:
    """The old source-seat-equals-team-slot assumption sends pick one to the wrong team."""
    league = _league(session)
    source_seats = (*range(2, SEATS + 1), 1)
    draft = _draft(session, league, source_seats=source_seats)
    _snapshot(session, html=load_early_with_distinct_names(), dedupe_key="GET:rotated:1")
    session.commit()

    response = client.post(f"/api/v1/drafts/{draft.id}/feed/ingest", json={"apply": True})
    assert response.status_code == 200, response.text
    body = response.json()

    assert len(body["applied"]["events"]) == EARLY_PICKS
    assert body["applied"]["halted"] is None
    assert body["status"]["skipped"] == {}
    assert body["status"]["unattributed_skipped"] == {}
    assert all(item["total"] == 0 for item in body["status"]["skipped_by_participant"])

    participants = {
        participant["source_seat"]: participant
        for participant in client.get(f"/api/v1/drafts/{draft.id}").json()["participants"]
    }
    assert participants[1]["team_slot"] == SEATS
    assert participants[1]["team_slot"] != participants[1]["source_seat"]
    assert participants[1]["holdings"][0]["player_label"] == "Nikola Jokic"

    events = client.get(f"/api/v1/drafts/{draft.id}/events").json()["events"]
    assert [event["participant_id"] for event in events] == [
        participants[source_seat]["id"] for source_seat in range(1, EARLY_PICKS + 1)
    ]

    replay = client.post(f"/api/v1/drafts/{draft.id}/feed/ingest", json={"apply": True})
    assert replay.status_code == 200, replay.text
    assert replay.json()["applied"]["events"] == []
    assert client.get(f"/api/v1/drafts/{draft.id}/events").json()["last_sequence"] == EARLY_PICKS


def test_a_linear_recorded_board_uses_the_same_complete_binding_boundary(
    client: TestClient,
    session: Session,
) -> None:
    league = _league(session, draft_type=DraftType.LINEAR)
    draft = _draft(session, league, source_seats=tuple(range(1, SEATS + 1)))
    _snapshot(
        session,
        html=linear_board(load_early_with_distinct_names()),
        dedupe_key="GET:linear:1",
    )
    session.commit()

    response = client.post(f"/api/v1/drafts/{draft.id}/feed/ingest", json={"apply": True})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["applied"]["events"]) == EARLY_PICKS
    assert body["applied"]["halted"] is None
    assert body["status"]["applied_count"] == EARLY_PICKS
    assert body["status"]["skipped"] == {}


def test_a_changed_historical_board_cell_cannot_be_appended_as_the_next_pick(
    client: TestClient,
    session: Session,
) -> None:
    """A rotated participant recurring on the clock cannot launder an old coordinate."""
    league = League(
        fantrax_league_id=LEAGUE,
        name="three-seat recurrence",
        season="2026-27",
        draft_type=DraftType.SNAKE,
        team_count=3,
        roster_size=2,
        auction_budget=None,
    )
    session.add(league)
    session.flush()
    draft = draft_service.create_draft(
        session,
        league=league,
        name="three-seat recurrence",
        tool_usage=DraftToolUsage.INSTRUMENTED,
        participants=[
            draft_service.ParticipantSpec(
                team_slot=team_slot,
                source_seat=source_seat,
                display_name=f"Team {team_slot}",
            )
            for team_slot, source_seat in [(1, 2), (2, 3), (3, 1)]
        ],
    )
    by_source = {participant.source_seat: participant.id for participant in draft.participants}
    names = ["Nikola Jokic", "Anthony Edwards", "Tyrese Haliburton"]
    session.add_all(
        [
            DraftFeedObservation(
                draft_id=draft.id,
                transport=DraftFeedTransport.BRIDGE_CAPTURE,
                artifact_key="board:original",
                locator=f"board[{source_seat}].1-{source_seat}",
                recogniser=BOARD_RECOGNISER,
                observed_at=NOW,
                kind="selection",
                source_seat=source_seat,
                participant_id=by_source[source_seat],
                player_label=names[source_seat - 1],
                player_external_id=f"original-{source_seat}",
                overall_pick=source_seat,
                round_number=1,
                pick_in_round=source_seat,
            )
            for source_seat in range(1, 4)
        ]
    )
    session.flush()
    first = feed_service.apply_observations(session, draft, now=NOW)
    assert len(first.applied) == 3

    # In a three-team snake, source seat 3 owns both overall picks 3 and 4.
    # Without an exact coordinate gate this changed historical cell passes the
    # participant-only turn check and is appended as overall pick 4.
    session.add(
        DraftFeedObservation(
            draft_id=draft.id,
            transport=DraftFeedTransport.BRIDGE_CAPTURE,
            artifact_key="board:changed",
            locator="board[3].1-3",
            recogniser=BOARD_RECOGNISER,
            observed_at=NOW + timedelta(seconds=30),
            kind="selection",
            source_seat=3,
            participant_id=by_source[3],
            player_label="Shai Gilgeous-Alexander",
            player_external_id="changed-player-id",
            overall_pick=3,
            round_number=1,
            pick_in_round=3,
        )
    )
    session.commit()

    second = client.post(f"/api/v1/drafts/{draft.id}/feed/ingest", json={"apply": True})

    assert second.status_code == 200, second.text
    body = second.json()
    assert body["applied"]["events"] == []
    assert body["applied"]["halted"] == "draft_pick_coordinate_mismatch"
    assert body["last_sequence"] == 3
    assert body["status"]["pending_count"] == 1
    assert any(
        reason.startswith("draft_pick_coordinate_mismatch:") for reason in body["status"]["blocked"]
    )
    assert body["status"]["skipped"] == {}, "The blocked row stays retryable, not burned."
    events = client.get(f"/api/v1/drafts/{draft.id}/events").json()["events"]
    assert "Shai Gilgeous-Alexander" not in [event["player_label"] for event in events]


def test_a_tail_void_between_coordinate_check_and_append_forces_revalidation(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same source seat recurring in a snake cannot hide a log-version race."""
    league = League(
        fantrax_league_id=LEAGUE,
        name="coordinate race",
        season="2026-27",
        draft_type=DraftType.SNAKE,
        team_count=3,
        roster_size=2,
        auction_budget=None,
    )
    session.add(league)
    session.flush()
    draft = draft_service.create_draft(
        session,
        league=league,
        name="coordinate race",
        tool_usage=DraftToolUsage.INSTRUMENTED,
        participants=[
            draft_service.ParticipantSpec(
                team_slot=team_slot,
                source_seat=source_seat,
                display_name=f"Team {team_slot}",
            )
            for team_slot, source_seat in [(1, 2), (2, 3), (3, 1)]
        ],
    )
    by_source = {participant.source_seat: participant.id for participant in draft.participants}
    for source_seat, player in enumerate(
        ["Nikola Jokic", "Anthony Edwards", "Tyrese Haliburton"],
        start=1,
    ):
        draft_service.record_pick(
            session,
            draft,
            participant_id=by_source[source_seat],
            player_label=player,
        )
    session.add(
        DraftFeedObservation(
            draft_id=draft.id,
            transport=DraftFeedTransport.BRIDGE_CAPTURE,
            artifact_key="board:pick-four",
            locator="board[3].2-1",
            recogniser=BOARD_RECOGNISER,
            observed_at=NOW,
            kind="selection",
            source_seat=3,
            participant_id=by_source[3],
            player_label="Shai Gilgeous-Alexander",
            player_external_id="pick-four",
            overall_pick=4,
            round_number=2,
            pick_in_round=1,
        )
    )
    session.flush()

    original_record_pick = draft_service.record_pick
    raced = False

    def record_pick_after_tail_void(
        session_arg: Session,
        draft_arg: Draft,
        *,
        participant_id: int,
        player_label: str,
        player_id: int | None = None,
        occurred_at: datetime | None = None,
        note: str | None = None,
        expected_last_sequence: int | None = None,
    ) -> object:
        nonlocal raced
        if not raced:
            raced = True
            assert expected_last_sequence == 3
            draft_service.record_void(session_arg, draft_arg, supersedes_sequence=3)
        return original_record_pick(
            session_arg,
            draft_arg,
            participant_id=participant_id,
            player_label=player_label,
            player_id=player_id,
            occurred_at=occurred_at,
            note=note,
            expected_last_sequence=expected_last_sequence,
        )

    monkeypatch.setattr(draft_service, "record_pick", record_pick_after_tail_void)

    outcome = feed_service.apply_observations(session, draft, now=NOW)

    assert raced is True, "The test must enter the interval between coordinate check and append."
    assert outcome.applied == ()
    assert outcome.halted == "draft_sequence_conflict"
    assert outcome.last_sequence == 4, "The concurrent void is the new log version."
    assert [event.event_type.value for event in draft_service.load_events(session, draft)] == [
        "pick",
        "pick",
        "pick",
        "void",
    ]
    assert feed_service.feed_status(session, draft, now=NOW).pending_count == 1


def test_an_auction_board_is_refused_by_name_rather_than_guessed_at() -> None:
    """Excludes: reasoning from one football snake draft onto an auction.

    Every byte of evidence under ADR-020 is one football, snake draft. An
    auction board may not be a round x seat grid at all. If it were, the draft's
    own snapshotted format would make every cell a ``SALE``, and the storage
    CHECK forbids a sale from carrying the ordinals the cell does carry -- so
    every row would be rejected at flush and the outcome would be a count with
    no cause attached.

    Applicability here is *unestablished*, which is a different state of
    knowledge from untested, and the refusal says which.
    """
    result = recognise_board_snapshot(
        url=f"https://www.fantrax.com/fantasy/league/{LEAGUE}/draft",
        html=load("complete"),
        received_at=NOW,
        captured_at=NOW,
        context=_context(draft_type=DraftType.AUCTION),
        draft_format=AuctionDraftFormat(
            team_count=SEATS,
            roster_size=ROUNDS,
            auction_budget=Decimal("200"),
        ),
    )

    assert result.rejected == "board_reading_unestablished_for_auction"
    assert result.instants == ()


def test_a_board_whose_layout_disagrees_with_the_frozen_format_is_refused() -> None:
    """Excludes: applying snake coordinates to a draft frozen as linear."""
    result = recognise_board_snapshot(
        url=f"https://www.fantrax.com/fantasy/league/{LEAGUE}/draft",
        html=load("complete"),
        received_at=NOW,
        captured_at=NOW,
        context=_context(draft_type=DraftType.LINEAR),
        draft_format=LinearDraftFormat(team_count=SEATS, roster_size=ROUNDS),
    )

    assert result.rejected == "board_layout_mismatch"
    assert result.instants == ()


def test_a_board_whose_seat_count_disagrees_with_the_frozen_draft_is_refused() -> None:
    """Excludes: silently rotating or truncating a board with a different width."""
    result = recognise_board_snapshot(
        url=f"https://www.fantrax.com/fantasy/league/{LEAGUE}/draft",
        html=load("complete"),
        received_at=NOW,
        captured_at=NOW,
        context=_context(),
        draft_format=SnakeDraftFormat(team_count=SEATS + 1, roster_size=ROUNDS),
    )

    assert result.rejected == "board_seat_count_mismatch"
    assert result.instants == ()


def test_a_board_exceeding_the_frozen_round_count_is_refused() -> None:
    """The format remains a hard upper bound while history owns the lower bound."""
    result = recognise_board_snapshot(
        url=f"https://www.fantrax.com/fantasy/league/{LEAGUE}/draft",
        html=load("complete"),
        received_at=NOW,
        captured_at=NOW,
        context=_context(),
        draft_format=SnakeDraftFormat(team_count=SEATS, roster_size=ROUNDS - 1),
    )

    assert result.rejected == "board_round_count_mismatch"
    assert result.instants == ()


def test_first_partial_dimensions_can_establish_and_grow_with_the_rendered_board(
    session: Session,
) -> None:
    """A first snapshot cannot know the final grid; the frozen format is the cap."""
    league = _league(session)
    draft = _draft(session, league)
    short = uniformly_short_board()
    _snapshot(session, html=short, dedupe_key="GET:dimensions:14", created_at=NOW)

    first = feed_service.ingest_bridge(session, draft, _context())
    first_evidence = feed_service.source_board_evidence(session, draft, now=NOW)

    assert first.board_refusals == {}
    assert first_evidence.status == "available"
    assert first_evidence.board is not None
    assert first_evidence.board.round_count == SHORT_ROUNDS
    assert first_evidence.board.picks_made == SHORT_PICKS

    _snapshot(
        session,
        html=load("complete"),
        dedupe_key="GET:dimensions:18",
        created_at=NOW + timedelta(seconds=30),
    )
    grown = feed_service.ingest_bridge(session, draft, _context())
    grown_evidence = feed_service.source_board_evidence(
        session, draft, now=NOW + timedelta(seconds=30)
    )

    assert grown.board_refusals == {}
    assert [
        reading.round_count for reading in feed_service.load_board_readings(session, draft)
    ] == [
        SHORT_ROUNDS,
        ROUNDS,
    ]
    assert grown_evidence.status == "available"
    assert grown_evidence.board is not None
    assert grown_evidence.board.round_count == ROUNDS
    assert grown_evidence.board.picks_made == TOTAL_PICKS


def test_a_uniformly_shortened_12_by_18_board_refuses_as_12_by_14(
    client: TestClient,
    session: Session,
) -> None:
    """Measured failure: 168 filled cells are not a complete 216-pick draft."""
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load("complete"), dedupe_key="GET:dimensions:18", created_at=NOW)
    feed_service.ingest_bridge(session, draft, _context())
    _snapshot(
        session,
        html=uniformly_short_board(),
        dedupe_key="GET:dimensions:14",
        created_at=NOW + timedelta(seconds=30),
    )

    outcome = feed_service.ingest_bridge(session, draft, _context())
    session.commit()

    assert outcome.board_refusals[feed_service.BOARD_DIMENSIONS_REGRESSED] == 1
    assert len(_board_rows(session, draft)) == TOTAL_PICKS
    assert [
        reading.round_count for reading in feed_service.load_board_readings(session, draft)
    ] == [ROUNDS]

    response = client.get(f"/api/v1/drafts/{draft.id}/source-board")
    assert response.status_code == 200, response.text
    source = response.json()
    assert source["status"] == "refused"
    assert source["refusal_reason"] == feed_service.BOARD_DIMENSIONS_REGRESSED
    assert source["contact_at"] == (NOW + timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    assert source["board"]["round_count"] == ROUNDS
    assert source["board"]["picks_made"] == TOTAL_PICKS
    assert client.get(f"/api/v1/drafts/{draft.id}/events").json()["events"] == []
    state = client.get(f"/api/v1/drafts/{draft.id}").json()
    assert all(participant["holdings"] == [] for participant in state["participants"])

    freshness = next(
        item
        for item in client.get(f"/api/v1/drafts/{draft.id}/feed").json()["freshness"]
        if item["transport"] == SourceTransport.BRIDGE_CAPTURE.value
    )
    assert freshness["contact_is_known"] is True
    assert freshness["silent"] is False


def test_repeated_smaller_content_refuses_after_larger_dimensions_were_seen(
    session: Session,
) -> None:
    """A prior artifact key cannot bypass the floor after the board grows."""
    league = _league(session)
    draft = _draft(session, league)
    short = uniformly_short_board()
    _snapshot(session, html=short, dedupe_key="GET:dimensions:14a", created_at=NOW)
    feed_service.ingest_bridge(session, draft, _context())
    _snapshot(
        session,
        html=load("complete"),
        dedupe_key="GET:dimensions:18",
        created_at=NOW + timedelta(seconds=30),
    )
    feed_service.ingest_bridge(session, draft, _context())
    _snapshot(
        session,
        html=short,
        dedupe_key="GET:dimensions:14b",
        created_at=NOW + timedelta(seconds=60),
    )

    outcome = feed_service.ingest_bridge(session, draft, _context())
    evidence = feed_service.source_board_evidence(session, draft, now=NOW + timedelta(seconds=60))

    assert outcome.board_refusals[feed_service.BOARD_DIMENSIONS_REGRESSED] == 1
    assert evidence.status == "refused"
    assert evidence.refusal_reason == feed_service.BOARD_DIMENSIONS_REGRESSED
    assert evidence.board is not None
    assert evidence.board.round_count == ROUNDS
    assert [
        reading.round_count for reading in feed_service.load_board_readings(session, draft)
    ] == [
        SHORT_ROUNDS,
        ROUNDS,
    ]


def test_a_refusal_before_the_first_success_establishes_no_dimension_floor(
    session: Session,
) -> None:
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load("truncated"), dedupe_key="GET:dimensions:refused")
    feed_service.ingest_bridge(session, draft, _context())
    _snapshot(
        session,
        html=uniformly_short_board(),
        dedupe_key="GET:dimensions:first-success",
        created_at=NOW + timedelta(seconds=30),
    )

    outcome = feed_service.ingest_bridge(session, draft, _context())
    evidence = feed_service.source_board_evidence(session, draft, now=NOW + timedelta(seconds=30))

    assert outcome.board_refusals["board_refused:snapshot_truncated"] == 1
    assert evidence.status == "available"
    assert evidence.board is not None
    assert evidence.board.round_count == SHORT_ROUNDS


def test_a_shorter_empty_board_refuses_and_preserves_the_complete_board(
    session: Session,
) -> None:
    """Zero picks do not exempt a successful parse from dimension history."""
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load("complete"), dedupe_key="GET:dimensions:18", created_at=NOW)
    feed_service.ingest_bridge(session, draft, _context())
    _snapshot(
        session,
        html=uniformly_short_board(empty=True),
        dedupe_key="GET:dimensions:empty14",
        created_at=NOW + timedelta(seconds=30),
    )

    outcome = feed_service.ingest_bridge(session, draft, _context())
    evidence = feed_service.source_board_evidence(session, draft, now=NOW + timedelta(seconds=30))

    assert outcome.board_refusals[feed_service.BOARD_DIMENSIONS_REGRESSED] == 1
    assert evidence.status == "refused"
    assert evidence.board is not None
    assert evidence.board.round_count == ROUNDS
    assert evidence.board.picks_made == TOTAL_PICKS
    assert [
        reading.round_count for reading in feed_service.load_board_readings(session, draft)
    ] == [ROUNDS]


def test_an_other_layout_is_refused_before_any_pick_is_stored() -> None:
    """Excludes: treating a self-consistent but unsupported order as snake.

    Swap the round-one pick coordinates of columns one and two. The coordinate
    cover remains complete, so the parser is entitled to return a board, but
    its layout is ``other`` and the feed is not entitled to choose a buyer.
    """
    html = load("complete")
    first = '<mark class="ng-star-inserted"> 1-1</mark>'
    second = '<mark class="ng-star-inserted"> 1-2</mark>'
    assert html.count(first) == 1
    assert html.count(second) == 1
    swapped = (
        html.replace(first, "__FIRST__", 1)
        .replace(second, first, 1)
        .replace("__FIRST__", second, 1)
    )
    assert parse_draft_board(swapped, captured_at=NOW).layout == "other"

    result = recognise_board_snapshot(
        url=f"https://www.fantrax.com/fantasy/league/{LEAGUE}/draft",
        html=swapped,
        received_at=NOW,
        captured_at=NOW,
        context=_context(),
        draft_format=SnakeDraftFormat(team_count=SEATS, roster_size=ROUNDS),
    )

    assert result.rejected == "board_layout_unrecognised"
    assert result.instants == ()


def test_a_board_does_not_depend_on_a_participant_at_the_same_ordinal(
    session: Session,
) -> None:
    """Excludes: source-seat evidence acquiring identity from table position."""
    league = _league(session)
    draft = _draft(session, league)
    missing = next(
        participant for participant in draft.participants if participant.team_slot == SEATS
    )
    session.delete(missing)
    session.flush()
    _snapshot(session, html=load("complete"), dedupe_key="GET:aaa:111")

    outcome = feed_service.ingest_bridge(session, draft, _context())

    assert outcome.boards_read == 1
    assert outcome.board_refusals == {}
    assert len(_board_rows(session, draft)) == TOTAL_PICKS
    assert all(row.participant_id is None for row in _board_rows(session, draft))


def test_html_that_is_not_a_board_is_refused_by_name_and_never_scraped(
    session: Session,
) -> None:
    """The boundary the userscript README states, kept after ADR-020 widened it.

    A rendered view "is never normalized or presented as the JSON response the
    userscript could not observe". ADR-020 authorises reading a *board* out of a
    snapshot and nothing else, so a snapshot of some other page contributes no
    instants and says why by name. ``board_refusals`` is a separate channel from
    ``rejected`` on purpose: a snapshot of the league home refusing with
    ``no_board_element`` is the correct answer, and reporting it as a rejected
    draft payload would teach the owner to ignore the tally that matters.
    """
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load("absent"), dedupe_key="GET:aaa:111")
    _snapshot(session, html=load("truncated"), dedupe_key="GET:aaa:222")

    outcome = feed_service.ingest_bridge(session, draft, _context())

    assert outcome.boards_read == 0
    assert outcome.observations_written == 0
    assert outcome.instants_recognised == 0
    assert outcome.rejected == {}
    assert outcome.board_refusals == {
        "board_refused:no_board_element": 1,
        "board_refused:snapshot_truncated": 1,
    }


# --------------------------------------------------------------------------
# ADR-020 decision 3: liveness comes from contact, which content-deduping needs
# --------------------------------------------------------------------------


def test_a_board_only_feed_is_not_silent_through_a_deliberation(session: Session) -> None:
    """Excludes: the freshness indicator crying wolf on a board that is working.

    Content keying means a four-minute deliberation produces snapshot after
    snapshot and **no new observation at all**, so the pick clock alone reports
    ``silent`` on a feed reading the board perfectly. By the fourth round the
    owner has learned to dismiss the one indicator that has to be believed.

    The reading in which ``silent=False`` would be wrong -- a dead bridge
    reported live -- needs a ``bridge_payloads`` row appearing with a recent
    ``created_at`` while the userscript is not running, and nothing but
    ``POST /bridge/payloads`` writes that table.

    The negative half is asserted first and is the important one: before any
    board has been read, a page snapshot still proves nothing, which is the
    service-worker case.
    """
    league = _league(session)
    draft = _draft(session, league)

    def bridge_freshness() -> SourceFreshness:
        status = feed_service.feed_status(session, draft, now=NOW)
        return next(
            item for item in status.freshness if item.transport is SourceTransport.BRIDGE_CAPTURE
        )

    # A snapshot of this league's pages, and nothing read from it yet.
    _snapshot(
        session,
        html=load("absent"),
        dedupe_key="GET:aaa:000",
        created_at=NOW - timedelta(minutes=10),
    )
    blind = bridge_freshness()
    assert blind.contact_is_known is False, (
        "before a board has ever been read, a page snapshot is the service-worker "
        "case and proves nothing"
    )
    assert blind.silent is True

    # A board is read six minutes ago...
    _snapshot(
        session,
        html=load("early"),
        dedupe_key="GET:aaa:111",
        created_at=NOW - timedelta(minutes=6),
    )
    feed_service.ingest_bridge(session, draft, _context())
    quiet = bridge_freshness()
    assert quiet.instant_count == EARLY_PICKS
    # Contact is now *known* -- the board path is a working source here, so this
    # league's page snapshots became evidence -- and it is six minutes old, so
    # it rescues nothing. Both halves matter: contact suppresses silence by
    # being recent, never by merely existing.
    assert quiet.contact_is_known is True
    assert quiet.contact_age_seconds == 360.0
    assert quiet.silent is True, "six-minute-old contact is silence and must say so"

    # ...and the board has not changed since, so the newest snapshot writes no
    # observation at all. Only contact can tell the pipe is alive.
    _snapshot(
        session,
        html=load("early"),
        dedupe_key="GET:aaa:222",
        created_at=NOW - timedelta(seconds=20),
    )
    feed_service.ingest_bridge(session, draft, _context())
    assert len(_board_rows(session, draft)) == EARLY_PICKS

    live = bridge_freshness()
    assert live.contact_is_known is True
    assert live.contact_age_seconds == 20.0
    assert live.silent is False
    # The pick clock is untouched: "no new pick for six minutes" is still
    # readable. The fix adds a fact rather than overwriting one.
    assert live.age_seconds == 360.0


# --------------------------------------------------------------------------
# ADR-020 decision 4: a board that lost a pick retracts nothing
# --------------------------------------------------------------------------


def test_a_board_that_lost_a_pick_is_stored_and_published_and_retracts_nothing(
    session: Session,
) -> None:
    """Excludes: a repaint silently deleting picks the board already showed.

    SPA navigation, a partial re-render and a throttled tab are all ways a later
    snapshot can hold fewer picks than an earlier one, and "the board went
    backwards" is the owner's own description of the failure this feed exists
    for -- *"it loses track of the draft"*. Refusing the regressed board would
    discard the evidence; clearing the missing picks would let a repaint delete
    a real selection. So it is stored, published, and acted on by nobody.

    Driven with the recorded fixtures in reverse arrival order: the finished
    216-pick board, then the seven-pick one arriving later.
    """
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load("complete"), dedupe_key="GET:aaa:111", created_at=NOW)
    _snapshot(
        session,
        html=load("early"),
        dedupe_key="GET:aaa:222",
        created_at=NOW + timedelta(seconds=30),
    )

    feed_service.ingest_bridge(session, draft, _context())
    rows = _board_rows(session, draft)

    # Nothing was retracted: both readings are still there, in full.
    assert len(rows) == TOTAL_PICKS + EARLY_PICKS

    status = feed_service.feed_status(session, draft, now=NOW)
    regressions = status.board_regressions
    assert len(regressions) == TOTAL_PICKS - EARLY_PICKS
    lost = {(item.round_number, item.pick_in_round) for item in regressions}
    assert (1, 1) not in lost, "a slot the newest board still holds is not a regression"
    assert (18, 12) in lost
    assert all(item.player_label for item in regressions)
    assert all(item.source_seat >= 1 for item in regressions)
    assert {item.last_seen_artifact_key for item in regressions} == {
        board_artifact_key(parse_draft_board(load("complete"), captured_at=NOW))
    }


def test_a_board_that_only_grows_reports_no_regression(session: Session) -> None:
    """Positive control: the regression check is discrimination, not a constant.

    A check that fires on the ordinary case is one the owner learns to ignore
    before the moment it is true, and a check that never fires is worth nothing.
    The ordinary case is a board gaining picks, and it must be silent.
    """
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load("predraft"), dedupe_key="GET:aaa:000", created_at=NOW)
    _snapshot(
        session,
        html=load("early"),
        dedupe_key="GET:aaa:111",
        created_at=NOW + timedelta(minutes=5),
    )
    _snapshot(
        session,
        html=load("complete"),
        dedupe_key="GET:aaa:222",
        created_at=NOW + timedelta(minutes=40),
    )

    feed_service.ingest_bridge(session, draft, _context())
    status = feed_service.feed_status(session, draft, now=NOW)

    assert status.board_regressions == ()
    assert len(_board_rows(session, draft)) == EARLY_PICKS + TOTAL_PICKS


def test_a_complete_board_followed_by_an_empty_board_is_a_regression(
    client: TestClient, session: Session
) -> None:
    """A successful zero-pick reading is a reading, not an absence of pick rows."""
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load("complete"), dedupe_key="GET:aaa:111", created_at=NOW)
    _snapshot(
        session,
        html=load("predraft"),
        dedupe_key="GET:aaa:222",
        created_at=NOW + timedelta(seconds=30),
    )

    feed_service.ingest_bridge(session, draft, _context())
    session.commit()

    assert len(_board_rows(session, draft)) == TOTAL_PICKS, "prior evidence is retained"
    assert client.get(f"/api/v1/drafts/{draft.id}/events").json()["events"] == []
    draft_body = client.get(f"/api/v1/drafts/{draft.id}").json()
    assert all(participant["holdings"] == [] for participant in draft_body["participants"])

    source_response = client.get(f"/api/v1/drafts/{draft.id}/source-board")
    assert source_response.status_code == 200, source_response.text
    source = source_response.json()
    assert source["status"] == "available"
    assert source["refusal_reason"] is None
    assert source["board"]["round_count"] == ROUNDS
    assert source["board"]["picks_made"] == 0
    assert all(column["picks"] == [] for column in source["board"]["columns"])
    assert len(source["regressions"]) == TOTAL_PICKS
    assert "participant_id" not in str(source)
    assert "budget" not in str(source)
    assert any("exact-content undo" in caveat for caveat in source["caveats"])

    feed_response = client.get(f"/api/v1/drafts/{draft.id}/feed")
    assert feed_response.status_code == 200, feed_response.text
    assert len(feed_response.json()["board_regressions"]) == TOTAL_PICKS


def test_an_initial_empty_board_is_available_and_dedupes_while_contact_advances(
    client: TestClient, session: Session
) -> None:
    """Empty content has reading identity even though it creates no pick rows."""
    league = _league(session)
    draft = _draft(session, league)
    first_at = NOW - timedelta(minutes=6)
    latest_at = NOW - timedelta(seconds=20)
    _snapshot(session, html=load("predraft"), dedupe_key="GET:aaa:111", created_at=first_at)
    feed_service.ingest_bridge(session, draft, _context())
    _snapshot(session, html=load("predraft"), dedupe_key="GET:aaa:222", created_at=latest_at)
    feed_service.ingest_bridge(session, draft, _context())
    session.commit()

    readings = (
        session.query(DraftSourceBoardReading)
        .filter(DraftSourceBoardReading.draft_id == draft.id)
        .all()
    )
    assert len(readings) == 1
    assert readings[0].picks_made == 0
    assert readings[0].observed_at == first_at
    state = session.get(DraftSourceBoardState, draft.id)
    assert state is not None
    assert state.contact_at == latest_at

    response = client.get(f"/api/v1/drafts/{draft.id}/source-board")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "available"
    assert body["refusal_reason"] is None
    assert body["board"]["picks_made"] == 0
    assert body["contact_at"] == latest_at.isoformat().replace("+00:00", "Z")
    assert body["regressions"] == []

    freshness = next(
        item
        for item in client.get(f"/api/v1/drafts/{draft.id}/feed").json()["freshness"]
        if item["transport"] == SourceTransport.BRIDGE_CAPTURE.value
    )
    assert freshness["instant_count"] == 0
    assert freshness["contact_is_known"] is True
    assert freshness["contact_age_seconds"] < 60
    assert freshness["silent"] is True, "contact does not invent a pick reading"


def test_an_empty_board_can_advance_to_picks_without_a_regression(session: Session) -> None:
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load("predraft"), dedupe_key="GET:aaa:111", created_at=NOW)
    _snapshot(
        session,
        html=load("early"),
        dedupe_key="GET:aaa:222",
        created_at=NOW + timedelta(seconds=30),
    )

    feed_service.ingest_bridge(session, draft, _context())

    readings = (
        session.query(DraftSourceBoardReading)
        .filter(DraftSourceBoardReading.draft_id == draft.id)
        .all()
    )
    assert [reading.picks_made for reading in readings] == [0, EARLY_PICKS]
    assert feed_service.feed_status(session, draft, now=NOW).board_regressions == ()
    evidence = feed_service.source_board_evidence(session, draft, now=NOW)
    assert evidence.board is not None
    assert evidence.board.picks_made == EARLY_PICKS


def test_an_older_overlapping_request_cannot_replace_newer_board_state(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two request sessions may finish out of arrival order without moving back."""
    league = _league(session)
    draft = _draft(session, league)
    old_payload = _snapshot(
        session,
        html=load("predraft"),
        dedupe_key="GET:concurrent:old",
        created_at=NOW,
    )
    draft_id = draft.id
    session.commit()

    old_at_lock = Event()
    release_old = Event()
    real_lock = feed_service._lock_board_scope

    def delay_old_request(lock_session: Session, locked_draft: Draft) -> None:
        if not old_at_lock.is_set():
            old_at_lock.set()
            assert release_old.wait(timeout=10), "newer request never released the older request"
        real_lock(lock_session, locked_draft)

    monkeypatch.setattr(feed_service, "_lock_board_scope", delay_old_request)

    def ingest_old() -> object:
        response = client.post(f"/api/v1/drafts/{draft_id}/feed/ingest", json={"apply": False})
        assert response.status_code == 200, response.text
        return response.json()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="older-board-ingest") as executor:
        older = executor.submit(ingest_old)
        assert old_at_lock.wait(timeout=10), "older request did not reach the board lock"

        newer_at = NOW + timedelta(seconds=30)
        with cast("FastAPI", client.app).state.database.session() as writer:
            new_payload = _snapshot(
                writer,
                html=load("early"),
                dedupe_key="GET:concurrent:new",
                created_at=newer_at,
            )

        newer = client.post(
            f"/api/v1/drafts/{draft_id}/feed/ingest",
            json={"apply": False},
        )
        assert newer.status_code == 200, newer.text
        release_old.set()
        older.result(timeout=10)

    with cast("FastAPI", client.app).state.database.session() as check:
        state = check.get(DraftSourceBoardState, draft_id)
        assert state is not None
        assert state.latest_bridge_payload_id == new_payload.id
        assert state.latest_bridge_payload_id > old_payload.id
        assert state.contact_at == newer_at
        assert state.picks_made == EARLY_PICKS
        assert check.scalar(select(func.count()).select_from(DraftSourceBoardState)) == 1
        assert check.scalar(select(func.count()).select_from(DraftSourceBoardReading)) == 2

    source = client.get(f"/api/v1/drafts/{draft_id}/source-board").json()
    assert source["status"] == "available"
    assert source["board"]["picks_made"] == EARLY_PICKS
    assert client.get(f"/api/v1/drafts/{draft_id}/events").json()["events"] == []
    draft_body = client.get(f"/api/v1/drafts/{draft_id}").json()
    assert all(participant["holdings"] == [] for participant in draft_body["participants"])
    assert "participant_id" not in str(source)
    assert "budget" not in str(source)


def test_delayed_short_reading_cannot_follow_concurrent_dimension_growth(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-draft lock makes the dimension floor atomic with reading writes."""
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(
        session,
        html=uniformly_short_board(),
        dedupe_key="GET:concurrent:14",
        created_at=NOW,
    )
    draft_id = draft.id
    session.commit()

    old_at_lock = Event()
    release_old = Event()
    real_lock = feed_service._lock_board_scope

    def delay_old_request(lock_session: Session, locked_draft: Draft) -> None:
        if not old_at_lock.is_set():
            old_at_lock.set()
            assert release_old.wait(timeout=10), "newer request never released the older request"
        real_lock(lock_session, locked_draft)

    monkeypatch.setattr(feed_service, "_lock_board_scope", delay_old_request)

    def ingest_old() -> object:
        response = client.post(f"/api/v1/drafts/{draft_id}/feed/ingest", json={"apply": False})
        assert response.status_code == 200, response.text
        return response.json()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="short-board-ingest") as executor:
        older = executor.submit(ingest_old)
        assert old_at_lock.wait(timeout=10), "older request did not reach the board lock"

        with cast("FastAPI", client.app).state.database.session() as writer:
            _snapshot(
                writer,
                html=load("complete"),
                dedupe_key="GET:concurrent:18",
                created_at=NOW + timedelta(seconds=30),
            )

        newer = client.post(
            f"/api/v1/drafts/{draft_id}/feed/ingest",
            json={"apply": False},
        )
        assert newer.status_code == 200, newer.text
        release_old.set()
        old_result = cast("dict[str, object]", older.result(timeout=10))

    old_bridge = next(
        source
        for source in cast("list[dict[str, object]]", old_result["sources"])
        if source["transport"] == SourceTransport.BRIDGE_CAPTURE.value
    )
    assert old_bridge["board_refusals"] == {}
    with cast("FastAPI", client.app).state.database.session() as check:
        stored_draft = check.get(Draft, draft_id)
        assert stored_draft is not None
        readings = feed_service.load_board_readings(check, stored_draft)
        assert [reading.round_count for reading in readings] == [SHORT_ROUNDS, ROUNDS]
        state = check.get(DraftSourceBoardState, draft_id)
        assert state is not None
        assert state.refusal_reason is None
        assert state.round_count == ROUNDS
        assert state.contact_at == NOW + timedelta(seconds=30)

    source = client.get(f"/api/v1/drafts/{draft_id}/source-board").json()
    assert source["status"] == "available"
    assert source["board"]["round_count"] == ROUNDS
    assert source["board"]["picks_made"] == TOTAL_PICKS
    assert client.get(f"/api/v1/drafts/{draft_id}/events").json()["events"] == []


def test_delayed_prelock_scan_cannot_persist_a_board_displaced_by_newer_captures(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Candidate selection is refreshed after waiting for the board lock."""
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(
        session,
        html=load("complete"),
        dedupe_key="GET:concurrent:stale18",
        created_at=NOW,
    )
    draft_id = draft.id
    session.commit()

    old_at_lock = Event()
    release_old = Event()
    real_lock = feed_service._lock_board_scope

    def delay_old_request(lock_session: Session, locked_draft: Draft) -> None:
        if not old_at_lock.is_set():
            old_at_lock.set()
            assert release_old.wait(timeout=10), "newer request never released the older request"
        real_lock(lock_session, locked_draft)

    monkeypatch.setattr(feed_service, "_lock_board_scope", delay_old_request)

    def ingest_old() -> object:
        response = client.post(f"/api/v1/drafts/{draft_id}/feed/ingest", json={"apply": False})
        assert response.status_code == 200, response.text
        return response.json()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="stale-board-scan") as executor:
        older = executor.submit(ingest_old)
        assert old_at_lock.wait(timeout=10), "older request did not reach the board lock"

        with cast("FastAPI", client.app).state.database.session() as writer:
            for index in range(feed_service.BOARD_SCAN_LIMIT):
                _snapshot(
                    writer,
                    html=uniformly_short_board(),
                    dedupe_key=f"GET:concurrent:new14:{index}",
                    created_at=NOW + timedelta(seconds=index + 1),
                )

        newer = client.post(
            f"/api/v1/drafts/{draft_id}/feed/ingest",
            json={"apply": False},
        )
        assert newer.status_code == 200, newer.text
        release_old.set()
        older.result(timeout=10)

    with cast("FastAPI", client.app).state.database.session() as check:
        stored_draft = check.get(Draft, draft_id)
        assert stored_draft is not None
        readings = feed_service.load_board_readings(check, stored_draft)
        assert [reading.round_count for reading in readings] == [SHORT_ROUNDS]
        state = check.get(DraftSourceBoardState, draft_id)
        assert state is not None
        assert state.refusal_reason is None
        assert state.round_count == SHORT_ROUNDS
        assert state.contact_at == NOW + timedelta(seconds=feed_service.BOARD_SCAN_LIMIT)

    source = client.get(f"/api/v1/drafts/{draft_id}/source-board").json()
    assert source["status"] == "available"
    assert source["board"]["round_count"] == SHORT_ROUNDS
    assert source["board"]["picks_made"] == SHORT_PICKS
    assert client.get(f"/api/v1/drafts/{draft_id}/events").json()["events"] == []


def test_two_concurrent_first_ingests_share_one_state_and_reading(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lock exists before the singleton, so its first insertion is serialized."""
    league = _league(session)
    draft = _draft(session, league)
    payload = _snapshot(
        session,
        html=load("early"),
        dedupe_key="GET:concurrent:first",
        created_at=NOW,
    )
    draft_id = draft.id
    session.commit()

    both_loaded = Barrier(2)
    real_lock = feed_service._lock_board_scope

    def align_first_ingests(lock_session: Session, locked_draft: Draft) -> None:
        both_loaded.wait(timeout=10)
        real_lock(lock_session, locked_draft)

    monkeypatch.setattr(feed_service, "_lock_board_scope", align_first_ingests)

    def ingest() -> int:
        response = client.post(f"/api/v1/drafts/{draft_id}/feed/ingest", json={"apply": False})
        assert response.status_code == 200, response.text
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(lambda _: ingest(), range(2))) == [200, 200]

    with cast("FastAPI", client.app).state.database.session() as check:
        state = check.get(DraftSourceBoardState, draft_id)
        assert state is not None
        assert state.latest_bridge_payload_id == payload.id
        assert check.scalar(select(func.count()).select_from(DraftSourceBoardState)) == 1
        assert check.scalar(select(func.count()).select_from(DraftSourceBoardReading)) == 1
        assert (
            check.scalar(
                select(func.count())
                .select_from(DraftFeedObservation)
                .where(DraftFeedObservation.draft_id == draft_id)
            )
            == EARLY_PICKS
        )

    assert client.get(f"/api/v1/drafts/{draft_id}/events").json()["events"] == []
    draft_body = client.get(f"/api/v1/drafts/{draft_id}").json()
    assert all(participant["holdings"] == [] for participant in draft_body["participants"])


def test_source_board_readings_are_isolated_by_draft(session: Session) -> None:
    first_league_id = "first-draft-league"
    second_league_id = "second-draft-league"
    first = _draft(
        session,
        _league(session, fantrax_league_id=first_league_id),
    )
    second = _draft(
        session,
        _league(session, fantrax_league_id=second_league_id),
    )
    _snapshot(
        session,
        html=load("complete"),
        dedupe_key="GET:first:111",
        league_id=first_league_id,
        created_at=NOW,
    )
    _snapshot(
        session,
        html=load("predraft"),
        dedupe_key="GET:first:222",
        league_id=first_league_id,
        created_at=NOW + timedelta(seconds=30),
    )
    _snapshot(
        session,
        html=load("predraft"),
        dedupe_key="GET:second:111",
        league_id=second_league_id,
        created_at=NOW,
    )
    feed_service.ingest_bridge(
        session,
        first,
        _context(fantrax_league_id=first_league_id),
    )
    feed_service.ingest_bridge(
        session,
        second,
        _context(fantrax_league_id=second_league_id),
    )

    assert len(feed_service.feed_status(session, first, now=NOW).board_regressions) == TOTAL_PICKS
    assert feed_service.feed_status(session, second, now=NOW).board_regressions == ()
    counts: dict[int, int] = {}
    for draft_id, count in session.execute(
        select(
            DraftSourceBoardReading.draft_id,
            func.count(DraftSourceBoardReading.id),
        ).group_by(DraftSourceBoardReading.draft_id)
    ).all():
        counts[draft_id] = count
    assert counts == {first.id: 2, second.id: 1}


# --------------------------------------------------------------------------
# the scan bound, and what it is allowed to cost
# --------------------------------------------------------------------------


def test_the_board_scan_bound_is_reported_rather_than_inferred(session: Session) -> None:
    """Excludes: a bounded scan that reads as a complete one.

    Reading a board is an HTML parse of the whole page -- 49 ms on the recorded
    225 KB board -- so parsing all 400 captures of the RPC scan window is twenty
    seconds of CPU on a request made mid-draft. The bound is reported because
    "we read the newest eight" and "there were only eight" are the same number
    and different facts. It is not called harmless: ADR-020 decision 4 exists
    because a newer reading can lose a pick, so an older reading outside the
    first ingest's window can hold evidence the parsed window does not.
    """
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load("early"), dedupe_key="GET:aaa:111", created_at=NOW)
    _snapshot(
        session,
        html=load("complete"),
        dedupe_key="GET:aaa:222",
        created_at=NOW + timedelta(minutes=40),
    )

    outcome = feed_service.ingest_bridge(session, draft, _context(), board_scan_limit=1)

    assert outcome.board_scan_truncated is True
    assert outcome.boards_read == 1
    assert len(_board_rows(session, draft)) == TOTAL_PICKS
    assert any("may hold evidence" in note for note in outcome.notes)


def test_a_board_and_an_rpc_capture_are_both_read_in_one_run(session: Session) -> None:
    """Excludes: the board branch swallowing the RPC path, or the reverse.

    Two readers on one transport is the shape ADR-020 chose, and the way that
    goes wrong quietly is one of them consuming the other's rows. Both are
    driven in a single ingest, and the counters that describe them are asserted
    apart: ``artifacts_examined`` stays the RPC number and ``boards_read`` is
    the board one.
    """
    league = _league(session)
    draft = _draft(session, league)
    session.add(
        BridgePayload(
            schema_name="hoops-gm.bridge-payload.v1",
            source="xhr",
            captured_at=NOW,
            request_method="POST",
            request_url=f"https://www.fantrax.com/fxpa/req?leagueId={LEAGUE}",
            response_status=200,
            response_ok=True,
            response_content_type="application/json",
            body_raw="{}",
            body_json={
                "responses": [
                    {
                        "data": {
                            "draftPicks": [
                                {"teamId": "t1", "playerName": "Nikola Jokic", "overallPick": 1}
                            ]
                        }
                    }
                ]
            },
            dedupe_key="POST:rpc:1",
            raw_payload="{}",
            created_at=NOW,
        )
    )
    session.flush()
    _snapshot(
        session,
        html=load("early"),
        dedupe_key="GET:aaa:111",
        created_at=NOW + timedelta(seconds=5),
    )

    outcome = feed_service.ingest_bridge(session, draft, _context())
    rows = feed_service.load_observations(session, draft)

    assert outcome.artifacts_examined == 1
    assert outcome.boards_read == 1
    assert len(rows) == EARLY_PICKS + 1
    assert len({row.recogniser for row in rows}) == 2
    # One pipe, whatever read it. Two transports here would be the false
    # corroboration ADR-020 decision 1 refuses.
    assert {row.transport.value for row in rows} == {SourceTransport.BRIDGE_CAPTURE.value}
    assert all(row.participant_id is None for row in rows if row.recogniser == BOARD_RECOGNISER)


def test_a_board_for_another_league_is_never_read_as_this_drafts(session: Session) -> None:
    """Excludes: a snapshot of somebody else's draft becoming this draft's board.

    The mirror of the counter above, and just as expensive: a mock in another
    league is exactly the traffic a bridge sees most of. The page URL is the
    only attribution a snapshot has, so this asserts it is actually consulted.
    """
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(
        session,
        html=load("complete"),
        dedupe_key="GET:aaa:111",
        league_id="a-different-league",
    )

    outcome = feed_service.ingest_bridge(session, draft, _context())

    assert outcome.snapshots_for_this_league == 0
    assert outcome.boards_read == 0
    assert feed_service.load_observations(session, draft) == []


def test_the_board_feed_reaches_the_status_endpoint(session: Session) -> None:
    """The whole join, end to end, in the numbers a screen actually reads.

    ``observation_count``, freshness and the skip reason all move together, so a
    screen that shows the board being read and a screen that shows why it cannot
    be applied are the same screen.
    """
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load("complete"), dedupe_key="GET:aaa:111", created_at=NOW)

    outcome = feed_service.ingest(session, draft)
    bridge = next(
        source for source in outcome.sources if source.transport is SourceTransport.BRIDGE_CAPTURE
    )
    assert bridge.boards_read == 1
    assert bridge.instants_recognised == TOTAL_PICKS

    status = feed_service.feed_status(session, draft, now=NOW)
    assert status.observation_count == TOTAL_PICKS
    assert status.pending_count == 0
    assert dict(status.skipped) == {"source_board_evidence_only": TOTAL_PICKS}
    assert status.board_regressions == ()
    freshness = next(
        item for item in status.freshness if item.transport is SourceTransport.BRIDGE_CAPTURE
    )
    assert freshness.instant_count == TOTAL_PICKS
    assert freshness.silent is False
    # No price is ever invented for a board pick: the board renders none.
    assert all(row.amount is None for row in _board_rows(session, draft))
    assert Decimal("0") not in {row.amount for row in _board_rows(session, draft)}


def test_source_board_api_is_explicit_before_any_reading(
    client: TestClient, session: Session
) -> None:
    league = _league(session)
    draft = _draft(session, league)
    session.commit()

    response = client.get(f"/api/v1/drafts/{draft.id}/source-board")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "no_reading"
    assert body["board"] is None
    assert body["refusal_reason"] is None
    assert body["contact_at"] is None


def test_source_board_api_publishes_picks_without_events_or_participants(
    client: TestClient, session: Session
) -> None:
    league = _league(session)
    draft = _draft(session, league)
    for participant in draft.participants:
        participant.fantasy_team_id = None
    _snapshot(session, html=load_early_with_distinct_names(), dedupe_key="GET:aaa:111")
    outcome = feed_service.ingest(session, draft)
    assert outcome.context_unavailable is None
    session.commit()

    response = client.get(f"/api/v1/drafts/{draft.id}/source-board")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "available"
    assert body["refusal_reason"] is None
    assert body["board"]["picks_made"] == EARLY_PICKS
    assert body["board"]["artifact_key"].startswith("board:")
    assert body["board"]["recogniser"] == BOARD_RECOGNISER
    assert body["board"]["observed_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert len(body["board"]["columns"]) == SEATS
    picks = [pick for column in body["board"]["columns"] for pick in column["picks"]]
    assert len(picks) == EARLY_PICKS
    assert set(picks[0]) == {
        "source_seat",
        "round_number",
        "pick_in_round",
        "overall_pick",
        "player_label",
        "player_external_id",
    }
    assert {pick["source_seat"] for pick in picks} <= set(range(1, SEATS + 1))
    assert "participant_id" not in str(body)
    assert "budget" not in str(body)
    assert any("exact-content undo" in caveat for caveat in body["caveats"])
    assert client.get(f"/api/v1/drafts/{draft.id}/events").json()["events"] == []
    state = client.get(f"/api/v1/drafts/{draft.id}").json()
    assert all(participant["holdings"] == [] for participant in state["participants"])


def test_source_board_api_publishes_a_refusal_instead_of_an_empty_success(
    client: TestClient, session: Session
) -> None:
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load("early"), dedupe_key="GET:aaa:111", created_at=NOW)
    _snapshot(
        session,
        html=load("truncated"),
        dedupe_key="GET:aaa:222",
        created_at=NOW + timedelta(seconds=30),
    )
    feed_service.ingest_bridge(session, draft, _context())
    session.commit()

    response = client.get(f"/api/v1/drafts/{draft.id}/source-board")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "refused"
    assert body["refusal_reason"] == "board_refused:snapshot_truncated"
    assert body["board"]["picks_made"] == EARLY_PICKS
    assert body["contact_at"] is not None


def test_source_board_api_publishes_initial_refusal_without_an_empty_board(
    client: TestClient, session: Session
) -> None:
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load("truncated"), dedupe_key="GET:aaa:111")
    feed_service.ingest_bridge(session, draft, _context())
    session.commit()

    response = client.get(f"/api/v1/drafts/{draft.id}/source-board")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "refused"
    assert body["refusal_reason"] == "board_refused:snapshot_truncated"
    assert body["board"] is None


def test_source_board_api_publishes_regression_without_retracting_or_attributing(
    client: TestClient, session: Session
) -> None:
    league = _league(session)
    draft = _draft(session, league)
    _snapshot(session, html=load("complete"), dedupe_key="GET:aaa:111", created_at=NOW)
    _snapshot(
        session,
        html=load("early"),
        dedupe_key="GET:aaa:222",
        created_at=NOW + timedelta(seconds=30),
    )
    feed_service.ingest_bridge(session, draft, _context())
    session.commit()

    response = client.get(f"/api/v1/drafts/{draft.id}/source-board")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "available"
    assert body["board"]["picks_made"] == EARLY_PICKS
    assert len(body["regressions"]) == TOTAL_PICKS - EARLY_PICKS
    assert all(item["last_seen_artifact_key"].startswith("board:") for item in body["regressions"])
    assert client.get(f"/api/v1/drafts/{draft.id}/events").json()["events"] == []
    state = client.get(f"/api/v1/drafts/{draft.id}").json()
    assert all(participant["holdings"] == [] for participant in state["participants"])
