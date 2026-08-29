"""Adapter gate: reading the Fantrax draft board out of recorded page snapshots.

The unit under test is the only thing that will know a pick happened on draft
night. Both automatic alternatives were falsified by direct observation on
2026-08-28 -- ``/fxpa/req`` is service-worker private and unobservable from a
userscript, and the official ``getDraftPicks`` returns an empty list against a
*finished* 216-pick draft -- so what remains is the rendered DOM.

That changes what is worth asserting. "It parsed" is the weak version, because
the defect the owner actually named has no error code: *"it loses track of the
draft, shows me picks that already happened or misses one."* A parser that
returns 214 picks of 216 raises nothing, logs nothing, and looks exactly like a
parser that returns 216.

So the tests below are arranged around two questions rather than one:

1. **Does it read the board correctly?** Checked against ground truth the owner
   watched happen -- 216 picks, 18 rounds, 12 teams -- and against Fantrax's
   *own* arithmetic, which the chat pane prints independently of the board.
2. **Does it refuse rather than shorten?** Every mutation test below breaks one
   piece of markup and asserts a refusal. Each one first asserts that the
   mutation actually landed, because a substitution that silently matched
   nothing leaves the fixture intact and turns the whole test into a second
   run of the happy path wearing a different name.

What none of this can establish is that a future Fantrax build looks like this
one. Nothing in the DOM announces its own version. That is why the refusals are
the load-bearing half.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from hoops_gm.draft.feed.board_dom import (
    BoardParseRefused,
    BoardReading,
    parse_draft_board,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: Adapter gate. Every test in this file asserts that the parser still matches
#: markup recorded off the wire, which is what that gate selects for. They also
#: run unmarked in the default suite, so a drift shows up on every push rather
#: than only in the gate job.
pytestmark = pytest.mark.adapter_contract

#: The recorded draft ran on this date; the value is the userscript's own
#: ``capturedAt`` for the final snapshot, which ``capture.js`` produces with
#: ``new Date(...).toISOString()`` and is therefore genuinely UTC.
CAPTURED_AT = datetime(2026, 8, 28, 18, 30, 57, tzinfo=UTC)

#: Ground truth for the recorded league, watched by the owner.
SEATS = 12
ROUNDS = 18
TOTAL_PICKS = SEATS * ROUNDS  # 216

_CHAT_ANNOUNCEMENT = re.compile(r"drafted\s*-\s*(\d+)\s*-\s*(\d+)\s*\[\s*(\d+)\s*\]")


def load(name: str) -> str:
    return (FIXTURES / f"fantrax_draft_board_{name}.html").read_text(encoding="utf-8")


def parse(name: str) -> BoardReading:
    return parse_draft_board(load(name), captured_at=CAPTURED_AT)


# --------------------------------------------------------------------------
# 1. Does it read the board correctly?
# --------------------------------------------------------------------------


def test_finished_board_yields_exactly_the_picks_the_owner_watched() -> None:
    """216, not "about 216".

    The count is the assertion because the count is the failure. A parser that
    drops two cells produces a plausible board, and nothing downstream can tell
    that it did.
    """
    reading = parse("complete")

    assert reading.picks_made == TOTAL_PICKS
    assert reading.seat_count == SEATS
    assert reading.rounds == ROUNDS
    assert reading.board_cells == TOTAL_PICKS
    assert reading.is_complete
    # Every overall number from 1 to 216 exactly once: stronger than the count,
    # which a duplicate plus an omission would satisfy.
    assert sorted(pick.overall for pick in reading.picks) == list(range(1, TOTAL_PICKS + 1))


def test_a_named_pick_sits_where_the_board_says_it_does() -> None:
    """A specific cell, not just a total.

    The three coordinates checked are the ones that separate a real read from
    an index-based guess: the first pick, the last pick of round one, and the
    round-two wrap, where a snake sends the pick back to the seat that just
    had it.
    """
    picks = {(pick.seat, pick.round): pick for pick in parse("complete").picks}

    opener = picks[(1, 1)]
    assert (opener.pick_in_round, opener.overall) == (1, 1)
    assert opener.seat_name == "Seat 01 Club"
    assert opener.player_name == "P. Player165"
    assert opener.player_external_id == "zz131"

    # Seat 12 closes round one at overall 12 ...
    assert (picks[(12, 1)].pick_in_round, picks[(12, 1)].overall) == (12, 12)
    # ... and opens round two, which in a snake is pick 12 *of that round*,
    # overall 24. Seat 1 picks last in round two, at overall 24's predecessor
    # chain -- the two seats swap ends, and an off-by-one here is exactly the
    # bug that shows the owner a pick that already happened.
    assert (picks[(12, 2)].pick_in_round, picks[(12, 2)].overall) == (1, 13)
    assert (picks[(1, 2)].pick_in_round, picks[(1, 2)].overall) == (12, 24)


def test_overall_numbering_agrees_with_fantrax_own_arithmetic() -> None:
    """Corroboration from outside the parser, not from inside it.

    The board encodes ``round-pickInRound`` and nothing else, so ``overall`` is
    computed here. Computing it and then asserting our own formula would prove
    only that the code does what the code does. Fantrax's chat pane, however,
    announces each pick as ``drafted - 16-4 [184]`` -- the same fact, arrived at
    by their arithmetic, rendered in a different subtree.

    Across the full recording that comparison ran 749 times with no
    disagreement. This test re-runs whatever subset survives in the fixture.
    """
    html = load("complete")
    reading = parse("complete")
    by_coordinate = {(pick.round, pick.pick_in_round): pick.overall for pick in reading.picks}

    announced = {
        (int(match.group(1)), int(match.group(2))): int(match.group(3))
        for match in _CHAT_ANNOUNCEMENT.finditer(html)
    }
    assert announced, "fixture lost its chat announcements; this test would be vacuous"

    for coordinate, fantrax_overall in announced.items():
        assert by_coordinate[coordinate] == fantrax_overall


def test_snake_layout_is_derived_from_the_markup_not_assumed() -> None:
    """The recorded league is a snake; the owner's may not be.

    ``layout`` is read off the rendered coordinates rather than configured, so
    an auction or a linear draft is described rather than mangled.
    """
    assert parse("complete").layout == "snake"


def test_team_defence_picks_survive_having_no_player_id() -> None:
    """Absence of an id is normal and must not remove a pick.

    Fantrax renders a pro-team logo instead of a headshot for a defence, and
    the scorer id lives *only* in the headshot URL -- there is no id attribute
    anywhere in the markup. Sixteen of the 216 recorded picks therefore have no
    id, and a parser that required one would have quietly returned 200.

    NBA has no defences, so this exact shape cannot occur in the real draft.
    The property under test is not "defences work"; it is that an optional
    field being absent never costs a row.
    """
    picks = parse("complete").picks

    without_id = [pick for pick in picks if pick.player_external_id is None]
    assert len(without_id) == 16
    assert len(picks) == TOTAL_PICKS
    assert all(pick.player_name for pick in picks)


def test_a_later_snapshot_holds_more_picks_than_an_earlier_one() -> None:
    """Growth, and the grid that does not grow with it.

    ``board_cells`` is identical in all three readings while ``picks_made``
    climbs. That is the property the whole refusal design rests on: Fantrax
    renders every cell from the moment the room loads, so a *missing* cell is
    damage rather than a pick that has not happened yet.
    """
    predraft = parse("predraft")
    early = parse("early")
    complete = parse("complete")

    assert predraft.picks_made == 0
    assert early.picks_made == 7
    assert complete.picks_made == TOTAL_PICKS
    assert predraft.picks_made < early.picks_made < complete.picks_made
    assert predraft.board_cells == early.board_cells == complete.board_cells == TOTAL_PICKS

    # The early board is seven consecutive round-one picks, seats 1 to 7.
    assert [(pick.seat, pick.overall) for pick in early.picks] == [(n, n) for n in range(1, 8)]


def test_an_empty_board_is_not_the_same_fact_as_no_board() -> None:
    """Zero picks is a reading; no board is a refusal.

    Both look like "no picks" to a caller that only counts rows, and they need
    opposite responses: one means the draft has not started, the other means
    the snapshot is of the wrong page or the markup moved.
    """
    assert parse("predraft").picks_made == 0

    with pytest.raises(BoardParseRefused) as refusal:
        parse("absent")
    assert refusal.value.reason == "no_board_element"


# --------------------------------------------------------------------------
# 2. Staleness: a reading is only as current as its snapshot
# --------------------------------------------------------------------------


def test_the_reading_carries_the_snapshot_timestamp() -> None:
    """Snapshots fire on ``MutationObserver`` and ``setTimeout``, both of which
    the browser throttles in a hidden tab. A reading that arrived without its
    own timestamp would let a consumer show a ten-minute-old board as live.
    """
    reading = parse("complete")
    assert reading.captured_at == CAPTURED_AT
    assert reading.captured_at.tzinfo is not None
    assert reading.source == "rendered-view"


def test_a_naive_timestamp_is_refused_rather_than_assumed_utc() -> None:
    """The stored ``bridge_payloads.captured_at`` column has had its offset
    stripped, so it is a UTC instant wearing no marker. Guessing here is how a
    board ends up an hour stale with nothing to show for it; the caller has to
    make that decision where the justification lives.
    """
    with pytest.raises(BoardParseRefused) as refusal:
        parse_draft_board(load("complete"), captured_at=datetime(2026, 8, 28, 18, 30, 57))
    assert refusal.value.reason == "naive_captured_at"

    # A non-UTC aware value is fine: the point is the offset being present.
    shifted = parse_draft_board(
        load("complete"),
        captured_at=CAPTURED_AT.astimezone(timezone(timedelta(hours=-4))),
    )
    assert shifted.picks_made == TOTAL_PICKS


def test_a_snapshot_cut_mid_board_refuses_instead_of_reporting_what_survived() -> None:
    """``capture.js`` caps a snapshot at 250,000 characters and appends a
    marker. On the recorded 216-pick board the cut landed 42,000 characters
    *past* the grid, so nothing was lost -- but the margin was 42 KB on a
    208 KB board, and a longer league would lose the tail.

    A parser that reported the cells that survived would return a short list
    with no error, which is the exact failure this module exists to prevent.
    """
    with pytest.raises(BoardParseRefused) as refusal:
        parse("truncated")

    assert refusal.value.reason == "snapshot_truncated"
    # The structural reason is kept rather than discarded, so a reader can tell
    # a cut snapshot from a renamed build.
    assert "seat_column_mismatch" in refusal.value.detail


def test_truncation_is_detected_even_though_the_marker_is_not_a_comment() -> None:
    """Recorded here because the obvious implementation is wrong.

    ``capture.js`` builds the marker as ``html.slice(0, limit)`` followed by
    ``<!-- ... -->``, and the cut lands wherever it lands. In the recorded
    captures it lands *inside an attribute value*, so an HTML parser folds the
    marker into that attribute and never emits a comment node. Detecting
    truncation via ``handle_comment`` would have reported every truncated
    capture on record as untruncated.
    """
    html = load("truncated")
    assert "hoops-gm bridge: truncated at" in html

    # The marker is preceded by an unterminated tag, which is what defeats a
    # comment-based check.
    marker_at = html.index("<!-- hoops-gm bridge: truncated at")
    assert html.rindex("<", 0, marker_at) > html.rindex(">", 0, marker_at)


def test_current_terminal_truncation_marker_is_detected() -> None:
    html = f"{load('complete')}\n<!-- hoops-gm bridge: truncated at 250000 chars -->"

    reading = parse_draft_board(html, captured_at=CAPTURED_AT)

    assert reading.truncated
    assert reading.picks_made == TOTAL_PICKS


def test_visible_marker_words_cannot_spoof_snapshot_truncation() -> None:
    html = load("complete")
    spoofed = html.replace(
        "</body>",
        "<div>hoops-gm bridge: truncated at 250000 chars</div></body>",
    ).replace("league-draft-board__body", "league-draft-board__grid")
    assert spoofed != html
    assert "hoops-gm bridge: truncated at 250000 chars" in spoofed

    with pytest.raises(BoardParseRefused) as refusal:
        parse_draft_board(spoofed, captured_at=CAPTURED_AT)

    assert refusal.value.reason == "no_board_element"


# --------------------------------------------------------------------------
# 3. Does it refuse rather than shorten? (markup drift)
# --------------------------------------------------------------------------

#: Each entry breaks one thing the parse depends on and names the refusal it
#: must produce. The class renames simulate the actual hazard: Fantrax ships a
#: new Angular build and a selector stops matching.
DRIFT_CASES: list[tuple[str, str, str, str]] = [
    (
        "the class marking a filled cell is renamed",
        "league-draft-board__item--picked",
        "league-draft-board__item--chosen",
        "unpicked_cell_with_player",
    ),
    (
        "the element holding the player name is renamed",
        "scorer__info__name",
        "scorer__info__label",
        "picked_cell_without_player",
    ),
    (
        "the board body is renamed",
        "league-draft-board__body",
        "league-draft-board__grid",
        "no_board_element",
    ),
    (
        "the per-team column is renamed",
        "league-draft-board__column",
        "league-draft-board__lane",
        "no_columns",
    ),
    (
        "the header cell naming each team is renamed",
        "league-draft-board__header__item",
        "league-draft-board__header__team",
        "no_seats",
    ),
]


@pytest.mark.parametrize(
    ("description", "original", "replacement", "expected_reason"),
    DRIFT_CASES,
    ids=[case[0] for case in DRIFT_CASES],
)
def test_renamed_markup_refuses_and_never_returns_a_short_list(
    description: str, original: str, replacement: str, expected_reason: str
) -> None:
    """Injection is not the interesting half; reversion is.

    Each case asserts three things in order, and the first two are what stop
    the test being decorative: the fixture parses to 216 before the mutation,
    the mutation demonstrably changed the markup, and only then that the parse
    refuses. Without the middle assertion a substitution that matched nothing
    would leave the happy path intact and pass.
    """
    html = load("complete")
    assert parse_draft_board(html, captured_at=CAPTURED_AT).picks_made == TOTAL_PICKS

    mutated = html.replace(original, replacement)
    assert mutated != html, f"mutation {description!r} matched nothing; the test would be vacuous"

    with pytest.raises(BoardParseRefused) as refusal:
        parse_draft_board(mutated, captured_at=CAPTURED_AT)
    assert refusal.value.reason == expected_reason
    # The message has to name the token, because the only way anyone learns
    # Fantrax shipped a new build is by reading this string.
    assert original in refusal.value.detail or replacement in refusal.value.detail


def test_a_deleted_cell_refuses_rather_than_reporting_a_rectangle_with_a_hole() -> None:
    """One cell removed from one column.

    This is the shape a partial re-render takes, and it is the one a naive
    parser handles worst: it returns 215 picks and a coherent-looking board.
    """
    html = load("complete")
    opening = '<div class="league-draft-board__item league-draft-board__item--picked'
    start = html.index(opening)
    end = html.index(opening, start + 1)
    mutated = html[:start] + html[end:]
    assert mutated != html
    assert mutated.count(opening) == html.count(opening) - 1

    with pytest.raises(BoardParseRefused) as refusal:
        parse_draft_board(mutated, captured_at=CAPTURED_AT)
    assert refusal.value.reason == "ragged_columns"


def test_a_cell_that_lost_its_coordinate_refuses() -> None:
    """The coordinate is what places a pick on the board. A cell without one
    cannot be attributed to a round, and dropping it silently would move every
    later assumption about that column.
    """
    html = load("complete")
    mutated = html.replace("<mark", "<span", 1).replace("</mark>", "</span>", 1)
    assert mutated != html

    with pytest.raises(BoardParseRefused) as refusal:
        parse_draft_board(mutated, captured_at=CAPTURED_AT)
    assert refusal.value.reason == "cell_without_coordinate"


def test_a_board_read_as_empty_is_caught_by_the_chat_pane() -> None:
    """The one case the cell-level checks cannot see.

    If a build renamed *both* the picked class and the name element, every cell
    would classify as cleanly empty and the board would report zero picks on a
    finished draft -- self-consistent, and wrong. Fantrax's chat pane announces
    picks from a different subtree, so it can contradict that.

    The guard is deliberately one-directional. The chat is capped and is absent
    entirely on the ``/draft/board`` route, so it can say the board holds *at
    least* N picks and never how many. Five recorded snapshots have picks and
    no chat pane at all, which is why it is a floor and not an equality.
    """
    html = load("complete")
    mutated = html.replace("league-draft-board__item--picked", "x-picked").replace(
        "scorer__info__name", "x-name"
    )
    assert "league-draft-board__item--picked" not in mutated
    assert "scorer__info__name" not in mutated
    assert _CHAT_ANNOUNCEMENT.search(mutated), "fixture lost its chat pane"

    with pytest.raises(BoardParseRefused) as refusal:
        parse_draft_board(mutated, captured_at=CAPTURED_AT)
    assert refusal.value.reason == "chat_reports_more_picks"


def test_the_chat_guard_tolerates_one_pick_of_lead_and_no_more() -> None:
    """The tolerance is deliberate, and the measurement is the argument.

    In 17 of the 28 recorded captures whose chat announced anything, the chat's
    highest overall equalled the board's pick count *exactly*. Equality is the
    steady state, because the pick that fills a cell also posts the message. A
    guard written as ``announced > picks`` would therefore have sat on its own
    boundary for most of the draft, and a single render tick with the message
    painted before the cell would blank the board mid-draft for no reason.

    Pinned here so that tightening it back to zero is a decision somebody has
    to make on purpose rather than a tidy-up.
    """
    html = load("complete")

    # One ahead: tolerated, board still reads in full.
    one_ahead = html.replace("drafted - 18-12 [216]", "drafted - 1-1 [217]")
    if one_ahead == html:  # the fixture's chat window may not hold the last pick
        announced = max(int(m.group(3)) for m in _CHAT_ANNOUNCEMENT.finditer(html))
        one_ahead = html.replace(f"[{announced}]", f"[{TOTAL_PICKS + 1}]", 1)
    assert one_ahead != html
    assert parse_draft_board(one_ahead, captured_at=CAPTURED_AT).picks_made == TOTAL_PICKS

    # Two ahead: refused.
    two_ahead = one_ahead.replace(f"[{TOTAL_PICKS + 1}]", f"[{TOTAL_PICKS + 2}]", 1)
    assert two_ahead != one_ahead
    with pytest.raises(BoardParseRefused) as refusal:
        parse_draft_board(two_ahead, captured_at=CAPTURED_AT)
    assert refusal.value.reason == "chat_reports_more_picks"


def test_the_seat_header_and_the_columns_must_describe_the_same_teams() -> None:
    """Twelve columns and eleven headers is not a board we can attribute picks
    on, even though every pick would still parse.
    """
    html = load("complete")
    opening = '<div class="league-draft-board__header__item'
    start = html.index(opening)
    end = html.index("</h4></div>", start) + len("</h4></div>")
    mutated = html[:start] + html[end:]
    assert mutated.count(opening) == html.count(opening) - 1

    with pytest.raises(BoardParseRefused) as refusal:
        parse_draft_board(mutated, captured_at=CAPTURED_AT)
    assert refusal.value.reason == "seat_column_mismatch"


def test_a_seat_is_never_named_after_a_material_icon() -> None:
    """The header's ``<h4>`` contains both the team name and a ``<mat-icon>``
    whose ligature text is the literal string ``flip_camera_android``. Reading
    the heading wholesale would name seats after an icon, and every seat label
    on the screen would be wrong in a way no count could detect.
    """
    reading = parse("complete")
    assert all("flip_camera_android" not in name for name in reading.seats)
    assert reading.seats[0] == "Seat 01 Club"
    assert len(reading.seats) == SEATS


def test_seat_identity_is_the_column_not_the_displayed_name() -> None:
    """Four seats changed their displayed name during the recorded session, as
    owners entered the room and Fantrax's ``Mock Drafter N`` placeholder was
    replaced by the real team name. The pre-draft fixture still carries one.

    Anything keyed on the name would have seen one seat as two teams. The DOM
    carries no team id at all, so the column ordinal is the only identity
    available -- which is why ``seat`` is an integer and ``seat_name`` is a
    label that travels with it.
    """
    predraft = parse("predraft")
    complete = parse("complete")

    assert any(name.startswith("Mock Drafter") for name in predraft.seats)
    assert predraft.seats != complete.seats
    # Same board, same seats, despite the labels moving.
    assert predraft.seat_count == complete.seat_count == SEATS
    assert [pick.seat for pick in complete.picks[:SEATS]] == list(range(1, SEATS + 1))
