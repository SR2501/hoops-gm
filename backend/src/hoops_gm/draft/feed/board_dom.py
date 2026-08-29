"""Reading a Fantrax draft board out of the page it was rendered on.

This module exists because both automatic routes to live pick data were
falsified by direct observation on 2026-08-28. ``/fxpa/req`` is issued by
Fantrax's own service worker, which no browser API and no Tampermonkey grant
can observe, and Cache Storage holds only Angular *asset* groups, so there is
nothing to recover from it either. The official ``getDraftPicks`` returned
``{"currentDraftPicks":[]}`` against a finished 216-pick draft. What is left is
the rendered DOM, which ``userscript/src/capture.js`` already snapshots.

So this is not a fallback. On draft day it is the only thing that knows a pick
happened, and the failure the owner named -- *"it loses track of the draft,
shows me picks that already happened or misses one"* -- has no error code
attached to it. A miscount looks exactly like a correct count.

**The refusal is the feature.** Everything below is arranged so that the parse
either returns every pick on the board or raises. It is never allowed to return
some of them. Two properties do that work, and both come from the same
observation: Fantrax renders the *whole* grid, always.

* **The grid is complete before any pick is made.** All 216 cells of a
  12x18 board are in the markup from the moment the room loads, each carrying
  its own ``round-pickInRound`` coordinate, whether or not anyone has drafted
  into it. Verified across 42 board-bearing captures of a real draft: cell
  count was 216 in every one, while picks went 0 -> 7 -> ... -> 216. The board
  is **not virtualised**, so a missing cell is evidence of damage rather than
  of scrolling, and :func:`parse_draft_board` requires the coordinates to cover
  ``rounds x seats`` exactly once each.

* **Two independent encodings of the same fact must agree.** A cell's *column*
  says which seat owns it and the cell's own ``<mark>`` says which pick of
  which round it is. Nothing forces those to agree except Fantrax rendering
  them consistently, so a disagreement means the board is not what we think it
  is. On the finished real board they agreed 216 times out of 216.

The arithmetic here is not self-certified either. Fantrax's chat pane announces
each pick as ``<team> drafted - 16-4 [184]``, printing the round, the pick
within the round *and* the overall number. Across all 49 captures that gives
749 statements of ``overall`` computed by Fantrax, and
``(round - 1) * seats + pick_in_round`` agreed with every one of them.

What none of this can prove is that a *future* Fantrax build looks like this
one. Nothing in the DOM announces its own version, so a rename is undetectable
in advance and the refusal is the only signal available. See
:class:`BoardParseRefused`.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Final

__all__ = [
    "BOARD_BODY_CLASS",
    "BOARD_COLUMN_CLASS",
    "BOARD_HEADER_CLASS",
    "BoardParseRefused",
    "BoardPick",
    "BoardReading",
    "parse_draft_board",
]

#: Class tokens the parse anchors on. Named as constants rather than inlined so
#: that a drift report can quote the exact token that went missing, and so the
#: reversion test has something to rename.
BOARD_HEADER_CLASS: Final = "league-draft-board__header"
BOARD_HEADER_ITEM_CLASS: Final = "league-draft-board__header__item"
BOARD_BODY_CLASS: Final = "league-draft-board__body"
BOARD_COLUMN_CLASS: Final = "league-draft-board__column"
BOARD_ITEM_CLASS: Final = "league-draft-board__item"
BOARD_ITEM_PICKED_CLASS: Final = "league-draft-board__item--picked"
SCORER_NAME_CLASS: Final = "scorer__info__name"
CHAT_NAME_CLASS: Final = "chat-message__name"

#: ``<mark> 12-7</mark>``. The leading space matters: a first pass over these
#: captures searched for ``>12-7<``, found zero, and concluded Angular did not
#: expose board coordinates at all. It does expose them, exactly there, with
#: one space in front. The wrong conclusion cost a day and is recorded here so
#: the next reader does not repeat it.
_COORD = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")

#: ``https://fantraximg.com/si/headshots/NBA/hs00abc_96_3.png`` -> ``00abc``.
#: This is the only place a Fantrax scorer id survives into the rendered page;
#: there is no ``scorerId`` attribute anywhere in the markup. It is therefore
#: read as *optional enrichment* and never as the key: team-defence picks carry
#: a pro-team logo instead of a headshot and have no id at all, which is 16 of
#: the 216 picks in the recorded football draft. Requiring an id would have
#: silently dropped them.
_HEADSHOT = re.compile(r"/headshots/[A-Za-z0-9]+/hs([0-9A-Za-z#]+)_")

#: ``Seat 09 Club drafted - 16-4 [184]`` in the chat pane.
_CHAT_PICK = re.compile(r"drafted\s*-\s*(\d+)\s*-\s*(\d+)\s*\[\s*(\d+)\s*\]")

#: How far ahead of the board the chat pane is allowed to be before the parse
#: refuses.
#:
#: Not zero, and the measurement is why. Across the 28 recorded captures whose
#: chat announced any pick, ``announced == picks`` in **17 of them** — equality
#: is the steady state, not a coincidence, because the same pick that fills a
#: cell also posts a chat line. A strict ``announced > picks`` guard therefore
#: sits exactly on its own boundary for most of a draft, and one render tick in
#: which Angular posts the message before it fills the cell would produce a
#: *false* refusal: the board goes blank mid-draft because the page was caught
#: between two paints. That is the owner's worst outcome, and it would be
#: self-inflicted.
#:
#: One pick of tolerance removes that cliff and costs nothing against the
#: failure this guard exists for, which is not off-by-one. It is a board read
#: as *empty* while the chat says two hundred picks have happened — the case
#: where a build renamed both the picked class and the name element, so every
#: cell classifies as cleanly unfilled and the reading is self-consistent and
#: wrong.
_CHAT_LEAD_TOLERANCE: Final = 1

#: Current and legacy markers appended by ``capture.js`` when a snapshot exceeds
#: ``AUTO_SNAPSHOT_MAX_CHARS``.
#:
#: Current capture emits a complete terminal comment. Historical captures put
#: the same comment after a raw slice, which landed *inside an attribute value*.
#: Keep that recorded shape readable, but do not scan arbitrary visible text:
#: a team/chat label containing the marker words must not relabel board drift as
#: truncation.
_TERMINAL_TRUNCATION_MARKER = re.compile(
    r"(?:\n)?<!-- hoops-gm bridge: truncated at (\d+) chars -->\s*\Z"
)
_LEGACY_TRUNCATION_MARKER = re.compile(r"<!-- hoops-gm bridge: truncated at (\d+) chars -->")

_VOID_TAGS: Final = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class BoardParseRefused(Exception):
    """The board could not be read, with the reason named.

    Raised in preference to returning a short list, which is the whole point of
    this module. ``reason`` is a stable code a screen or a log can branch on;
    ``detail`` carries the specifics -- which token was missing, which cell
    disagreed with its column -- and is meant to be read by a person deciding
    whether Fantrax shipped a new build.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class BoardPick:
    """One filled cell of the board.

    ``seat`` is the 1-based column ordinal and is the only stable identity the
    rendered board offers. ``seat_name`` is a label and deliberately not an
    identity: across the recorded captures four seats changed their displayed
    name mid-session, from Fantrax's ``Mock Drafter 10`` placeholder to the
    real team name, as owners entered the room. Keying anything on the name
    would have made one seat look like two teams. The DOM carries no team id at
    all -- ``draftTeamId`` and ``cellTeamId`` appear in Fantrax's console
    logging and nowhere in its markup -- so there is no third option.
    """

    seat: int
    seat_name: str
    round: int
    pick_in_round: int
    overall: int
    player_name: str
    #: ``None`` for a pick with no headshot, which in the recorded football
    #: draft means a team defence. Absence is normal and is not an error.
    player_external_id: str | None


@dataclass(frozen=True, slots=True)
class BoardReading:
    """Every pick on one snapshot of the board, and when that snapshot was taken.

    ``captured_at`` is carried because a parse is only ever as current as the
    snapshot behind it, and the snapshot fires on ``MutationObserver`` and
    ``setTimeout`` -- both throttled by the browser in a hidden tab. A reading
    that arrives without its own timestamp invites a consumer to treat stale as
    live, which is the failure mode this whole unit exists to avoid.

    ``truncated`` records that ``capture.js`` cut the snapshot at its character
    cap. It can be true on a perfectly good reading, because the cap usually
    lands past the board and eats only the chat pane; when it lands *inside*
    the board the parse refuses instead.
    """

    captured_at: datetime
    source: str
    seats: tuple[str, ...]
    rounds: int
    picks: tuple[BoardPick, ...]
    #: ``"snake"``, ``"linear"`` or ``"other"`` -- derived from the rendered
    #: coordinates rather than assumed. The recorded draft is a snake, but the
    #: owner's league format is a separate question and this module does not
    #: presume an answer to it.
    layout: str
    truncated: bool

    @property
    def seat_count(self) -> int:
        return len(self.seats)

    @property
    def board_cells(self) -> int:
        return len(self.seats) * self.rounds

    @property
    def picks_made(self) -> int:
        return len(self.picks)

    @property
    def is_complete(self) -> bool:
        """Whether every cell on the board is filled."""
        return self.picks_made == self.board_cells


@dataclass(slots=True)
class _El:
    tag: str
    classes: frozenset[str]
    style: str
    children: list[_El]
    text_parts: list[str]

    def text(self) -> str:
        return "".join(self.text_parts).strip()

    def deep_text(self) -> str:
        out = list(self.text_parts)
        for child in self.children:
            out.append(child.deep_text())
        return "".join(out).strip()

    def find_all(self, css_class: str) -> list[_El]:
        found: list[_El] = []
        for child in self.children:
            if css_class in child.classes:
                found.append(child)
            found.extend(child.find_all(css_class))
        return found

    def find_first(self, css_class: str) -> _El | None:
        for child in self.children:
            if css_class in child.classes:
                return child
            deeper = child.find_first(css_class)
            if deeper is not None:
                return deeper
        return None

    def first_tag(self, tag: str) -> _El | None:
        for child in self.children:
            if child.tag == tag:
                return child
            deeper = child.first_tag(tag)
            if deeper is not None:
                return deeper
        return None


class _DomBuilder(HTMLParser):
    """A forgiving element tree.

    Deliberately tolerant of unclosed tags, because a truncated snapshot ends
    mid-element by construction and a strict parser would refuse the whole
    document for a reason that has nothing to do with the board. Structural
    damage is caught downstream by the completeness checks, which can say what
    is actually wrong.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _El("#document", frozenset(), "", [], [])
        self._stack: list[_El] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrib = {k: (v or "") for k, v in attrs}
        element = _El(
            tag=tag,
            classes=frozenset(attrib.get("class", "").split()),
            style=attrib.get("style", ""),
            children=[],
            text_parts=[],
        )
        self._stack[-1].children.append(element)
        if tag not in _VOID_TAGS:
            self._stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].text_parts.append(data)


def _seat_name(header_item: _El) -> str | None:
    """The team label in one board header cell.

    Reads the ``<span>`` inside the ``<h4>`` rather than the heading's text,
    because the heading also contains a ``<mat-icon>`` whose ligature text is
    the literal word ``flip_camera_android``. Taking the heading wholesale
    would name a seat after a Material icon.
    """
    heading = header_item.first_tag("h4")
    if heading is None:
        return None
    span = heading.first_tag("span")
    if span is None:
        return None
    name = span.deep_text()
    return name or None


def _player_of(cell: _El) -> tuple[str | None, str | None]:
    """``(player_name, player_external_id)`` for one cell, either possibly ``None``."""
    holder = cell.find_first(SCORER_NAME_CLASS)
    name = holder.deep_text() if holder is not None else ""
    external_id: str | None = None
    for element in [cell, *cell.find_all("scorer__image")]:
        match = _HEADSHOT.search(element.style)
        if match is not None:
            external_id = match.group(1)
            break
    return (name or None), external_id


def _layout_of(picks_grid: dict[tuple[int, int], int], seats: int, rounds: int) -> str:
    """Name the rendered pick order without requiring any particular one."""
    snake = all(
        picks_grid[(seat, rnd)] == (seat if rnd % 2 else seats + 1 - seat)
        for seat in range(1, seats + 1)
        for rnd in range(1, rounds + 1)
    )
    if snake:
        return "snake"
    linear = all(
        picks_grid[(seat, rnd)] == seat
        for seat in range(1, seats + 1)
        for rnd in range(1, rounds + 1)
    )
    return "linear" if linear else "other"


def _max_chat_overall(root: _El) -> int:
    """The highest overall pick number the chat pane claims has happened.

    Used only as a lower bound on the board, never as a source of picks: the
    pane holds a capped, scrollable window and is absent entirely on the
    ``/draft/board`` route. It cannot say how many picks there are and it can
    say that there are at least this many, which is exactly the direction that
    catches a board silently reading as empty.
    """
    highest = 0
    for label in root.find_all(CHAT_NAME_CLASS):
        match = _CHAT_PICK.search(label.deep_text())
        if match is not None:
            highest = max(highest, int(match.group(3)))
    return highest


def _snapshot_was_truncated(html: str) -> bool:
    if _TERMINAL_TRUNCATION_MARKER.search(html) is not None:
        return True
    legacy = _LEGACY_TRUNCATION_MARKER.search(html)
    if legacy is None:
        return False
    marker_at = legacy.start()
    return html.rfind("<", 0, marker_at) > html.rfind(">", 0, marker_at)


def parse_draft_board(
    html: str,
    *,
    captured_at: datetime,
    source: str = "rendered-view",
) -> BoardReading:
    """Read every pick on a captured draft board, or refuse and say why.

    ``captured_at`` must be timezone-aware. The userscript's own ``capturedAt``
    is produced by ``new Date(...).toISOString()``, which is genuinely UTC --
    checked against the code that emits it rather than against the ``Z`` on the
    string, because AGENTS.md records a field in this project that wears a
    ``Z`` and is Eastern.

    **What this docstring used to say about the stored column was wrong.** It
    claimed ``bridge_payloads.captured_at`` "has had the offset stripped and is
    a UTC instant wearing no marker at all", and made refusing a naive value the
    caller's problem on that basis. The column is
    :class:`~hoops_gm.db.base.UTCDateTime`, whose ``process_result_value``
    re-attaches UTC on the way out precisely because SQLite drops the offset, so
    a row read back through the ORM is **aware**. The refusal below is still
    right and its justification is now the general one: a naive datetime reaching
    a parser is a value whose zone somebody has already guessed, and this is not
    the place to guess it again. A caller reading the column with raw SQL, or
    any future caller holding a naive instant, still meets a named refusal
    instead of a silent five-hour shift.

    :raises BoardParseRefused: for anything that would otherwise yield a
        partial reading.
    """
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise BoardParseRefused(
            "naive_captured_at",
            "captured_at must be timezone-aware; a naive instant is one whose "
            "zone somebody has already guessed, and this parser is not the "
            "place to guess it a second time",
        )

    builder = _DomBuilder()
    builder.feed(html)
    builder.close()
    root = builder.root
    truncated = _snapshot_was_truncated(html)

    def refuse(reason: str, detail: str) -> BoardParseRefused:
        # A truncated snapshot that fails a structural check almost certainly
        # failed it *because* it was cut, and "the board was cut off" is a far
        # more actionable thing to read than "the grid is incomplete". The
        # underlying code is kept in the detail rather than discarded, so no
        # information is lost by relabelling.
        if truncated:
            return BoardParseRefused(
                "snapshot_truncated",
                f"snapshot was cut at capture.js's character cap; underlying "
                f"failure was {reason}: {detail}",
            )
        return BoardParseRefused(reason, detail)

    header = root.find_first(BOARD_HEADER_CLASS)
    body = root.find_first(BOARD_BODY_CLASS)
    if header is None or body is None:
        missing_anchors = [
            token
            for token, found in ((BOARD_HEADER_CLASS, header), (BOARD_BODY_CLASS, body))
            if found is None
        ]
        # Two anchors rather than one: a page that is not the draft room at all
        # is missing both, whereas a renamed build is likely to lose one. The
        # message says which, because those need different responses.
        raise refuse(
            "no_board_element",
            f"no element carrying {' and '.join(missing_anchors)}; either this snapshot "
            f"is not of the draft room, or Fantrax renamed the board markup",
        )

    seat_items = header.find_all(BOARD_HEADER_ITEM_CLASS)
    columns = body.find_all(BOARD_COLUMN_CLASS)
    if not seat_items:
        raise refuse("no_seats", f"board header holds no .{BOARD_HEADER_ITEM_CLASS} cells")
    if not columns:
        raise refuse("no_columns", f"board body holds no .{BOARD_COLUMN_CLASS} cells")
    if len(seat_items) != len(columns):
        raise refuse(
            "seat_column_mismatch",
            f"{len(seat_items)} header seats against {len(columns)} board columns; "
            f"the two must describe the same teams and no longer do",
        )

    seats: list[str] = []
    for index, item in enumerate(seat_items, start=1):
        name = _seat_name(item)
        if name is None:
            raise refuse("unreadable_seat_name", f"header cell {index} carries no readable name")
        seats.append(name)
    seat_count = len(seats)

    distinct = {len(column.find_all(BOARD_ITEM_CLASS)) for column in columns}
    if distinct == {0}:
        raise refuse("no_cells", f"every column is empty of .{BOARD_ITEM_CLASS}")
    if len(distinct) != 1:
        raise refuse(
            "ragged_columns",
            f"columns hold different numbers of cells ({sorted(distinct)}); a complete "
            f"board is rectangular, so this is a partial render or a cut snapshot",
        )
    rounds = distinct.pop()

    coordinates: dict[tuple[int, int], tuple[int, int]] = {}
    picks: list[BoardPick] = []
    picked_cells = 0
    for seat, column in enumerate(columns, start=1):
        for row, cell in enumerate(column.find_all(BOARD_ITEM_CLASS), start=1):
            mark = cell.first_tag("mark")
            match = _COORD.match(mark.deep_text()) if mark is not None else None
            if match is None:
                raise refuse(
                    "cell_without_coordinate",
                    f"seat {seat} row {row} has no parseable <mark>round-pick</mark>; "
                    f"every cell carries one even before it is filled, so this cell "
                    f"cannot be placed on the board",
                )
            rnd, pick_in_round = int(match.group(1)), int(match.group(2))
            coordinates[(seat, row)] = (rnd, pick_in_round)

            is_picked = BOARD_ITEM_PICKED_CLASS in cell.classes
            player_name, external_id = _player_of(cell)
            # The two facts a cell states about itself -- "I am filled" and
            # "here is who is in me" -- are carried by different markup, so
            # either can drift without the other. Requiring them to agree is
            # what turns a rename into a refusal instead of a short list: drop
            # the picked class and every filled cell reports a player it says
            # it does not have.
            if is_picked and player_name is None:
                raise refuse(
                    "picked_cell_without_player",
                    f"seat {seat} round {rnd} is marked picked but no player name was "
                    f"found under .{SCORER_NAME_CLASS}; returning the other picks would "
                    f"be a short list with no error attached",
                )
            if player_name is not None and not is_picked:
                raise refuse(
                    "unpicked_cell_with_player",
                    f"seat {seat} round {rnd} names a player but carries no "
                    f".{BOARD_ITEM_PICKED_CLASS}; the class that marks a filled cell "
                    f"has most likely been renamed",
                )
            if not is_picked:
                continue
            picked_cells += 1
            assert player_name is not None
            picks.append(
                BoardPick(
                    seat=seat,
                    seat_name=seats[seat - 1],
                    round=rnd,
                    pick_in_round=pick_in_round,
                    overall=(rnd - 1) * seat_count + pick_in_round,
                    player_name=player_name,
                    player_external_id=external_id,
                )
            )

    expected = {(rnd, pick) for rnd in range(1, rounds + 1) for pick in range(1, seat_count + 1)}
    seen = Counter(coordinates.values())
    duplicated = sorted(coord for coord, count in seen.items() if count > 1)
    if duplicated:
        raise refuse(
            "duplicate_coordinates",
            f"{len(duplicated)} board coordinate(s) appear more than once, e.g. "
            f"{duplicated[:3]}; each pick slot must be rendered exactly once",
        )
    if set(seen) != expected:
        missing = sorted(expected - set(seen))
        unexpected = sorted(set(seen) - expected)
        raise refuse(
            "coordinate_grid_incomplete",
            f"a {seat_count}-seat, {rounds}-round board must render each "
            f"(round, pick) exactly once; {len(missing)} missing "
            f"(e.g. {missing[:3]}) and {len(unexpected)} unexpected "
            f"(e.g. {unexpected[:3]})",
        )

    by_seat_round = {
        (seat, coordinates[(seat, row)][0]): coordinates[(seat, row)][1]
        for seat in range(1, seat_count + 1)
        for row in range(1, rounds + 1)
    }
    if len(by_seat_round) != seat_count * rounds:
        raise refuse(
            "seat_round_collision",
            "a seat holds two cells for the same round; the column no longer "
            "corresponds one-to-one with a team's picks",
        )

    if len(picks) != picked_cells:
        raise refuse(
            "pick_count_mismatch",
            f"{picked_cells} filled cells produced {len(picks)} picks",
        )
    overalls = Counter(pick.overall for pick in picks)
    repeated = sorted(value for value, count in overalls.items() if count > 1)
    if repeated:
        raise refuse(
            "duplicate_overall_pick",
            f"overall pick number(s) {repeated[:5]} claimed by more than one seat",
        )

    announced = _max_chat_overall(root)
    if announced > len(picks) + _CHAT_LEAD_TOLERANCE:
        raise refuse(
            "chat_reports_more_picks",
            f"the chat pane announces overall pick {announced} but the board yielded "
            f"only {len(picks)}; the board markup is being read as emptier than it is",
        )

    return BoardReading(
        captured_at=captured_at,
        source=source,
        seats=tuple(seats),
        rounds=rounds,
        picks=tuple(sorted(picks, key=lambda pick: pick.overall)),
        layout=_layout_of(by_seat_round, seat_count, rounds),
        truncated=truncated,
    )
