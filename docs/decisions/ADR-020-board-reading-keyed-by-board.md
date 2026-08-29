# ADR-020: A rendered board reading is keyed by the board, not by the bytes

- **Status:** Accepted
- **Accepted:** 2026-08-28 by the project owner, for numbered Decisions 1-4.
  Amendments below retain their own status.
- **Date:** 2026-08-28
- **Deciders:** owner (accepted Decisions 1-4), architect (proposes amendments)
- **Supersedes:** nothing. **Amends:** nothing. Bounds the
  `InstantProvenance` contract in one place and says so there as well as here.

## Context

Both automatic pick paths are now negative. `/fxpa/req` is service-worker
originated and no userscript can observe it — 49 of 49 captures, none containing
`fxpa`. `getDraftPicks` is reachable, unauthenticated, and returned
`{"currentDraftPicks":[]}` for a completed 216-pick draft.
`board_dom.parse_draft_board` reads the rendered board instead, correctly on 42
of 49 real captures. It is deliberately **not wired to the feed**, because three
contract questions were open. This settles them.

## Decision

**1. The transport stays `BRIDGE_CAPTURE`; no `rendered_view` value is added.** A
board reading arrives through the userscript into `bridge_payloads` — the same
pipe. `DraftFeedTransport`'s own docstring forbids finer values, so that two
readings off one pipe cannot look like two pipes. The distinction belongs in
`InstantProvenance.recogniser`, as `board_dom`.

**2. `artifact_key` digests the parsed board, not the HTML.** Sorted
`(round, pick_in_round, seat, player_external_id or player_name)` with `seats`
and `rounds`. Not `captured_at`, not `truncated`, not a parser version.

This diverges from `observations.py:44` — "identifies the **bytes**" — and the
divergence must be recorded there too. **The strong reason is false and is worth
naming so nobody reaches for it later:** the independence guard would *not* be
fooled, because `_independence` refuses on `same_transport_on_both_sides` and two
bridge readings never corroborate each other however they are keyed. The real
cost is volume. `dedupeKey` is `METHOD:fnv1a(url):fnv1a(raw)`, the raw is the
HTML, and the HTML moves between two snapshots of an unchanged board. Keyed on
bytes, a 156-slot board snapshotted through a three-hour auction stores every
pick once per snapshot, and `instant_count` becomes a count of snapshots rather
than of picks.

**3. Liveness comes from `contact_at`, which already exists.** Content-deduping
means a four-minute deliberation produces no new observation.
`freshness_of(contact_at=...)` takes the newest bridge payload's arrival. Its
documented asymmetry stands: contact does **not** rescue a transport that has
read zero picks.

**4. A newer board that has lost a pick never clears it.** Store the reading,
publish `board_regression`, retract nothing automatically.

## Rejected

**A `rendered_view` transport.** It would let the DOM board and a future
`/fxpa/req` capture witness each other. Same browser, same page, same script.

**Refusing a regressed board.** That discards evidence of the exact failure the
owner named in Q12 — *"it loses track of the draft"*.

## What would flip this

A capture route to an RPC body being found: `rendered_view` and `fxpa` might then
be two genuine pipes inside the bridge, and (1) is revisited. Or a regression
observed and *proven* an undo rather than a repaint, which would make automatic
retraction worth costing.

## Consequences

`draft-board-feed-integration` has a contract and can be scoped.

Three things still look identical at the DOM: a repaint, an undo, and a capture
cut inside the board. **The third is excluded by measurement — 794 cut offsets,
0 parsed clean and short — but by a different mechanism than this paragraph
originally claimed, and there is a live hole beside it. See the amendment.**
`bridge-snapshot-budget` is load-bearing rather than hygiene.

**Every byte of evidence under this ADR is football, snake format.** Nothing here
has been driven against an auction board or an NBA one.

## Amendments

### 2026-08-28 — the truncation guard I named was dead, and the safety is in the layout rather than the check

**Status:** Proposed. Written by `architect`, the author of the body above; only
the project owner accepts.

**The decision does not change.** What changes is the standing of two claims
under it, both of which the handoff entry listed as "could not verify".

**The board is column-major in document order, and this is now checkable in CI.**
Coordinate marks in `backend/tests/fixtures/fantrax_draft_board_complete.html`
run `1-1, 2-12, 3-1, 4-12 … 17-1, 18-12` — all eighteen of seat 1's picks,
snaking within the one column — and only then `1-2, 2-11, …`. The same holds in
**all 42 board-bearing captures**. The DOM is
`__body > __column ×12 > __item ×18`.

**A truncated capture never parses short. Measured, not reasoned:** a real
216-pick capture cut at **794 offsets** plus all 12 exact column boundaries gave
**769 refused, 25 parsed-full (cut landed past the board), 0 parsed clean and
short.**

**The mechanism named in the first draft of this amendment was wrong, and the
correction matters more than the conclusion.** It said the cut shortens the last
column and trips `coordinate_grid_incomplete` or `ragged_columns`. Across 771
in-board cuts the actual distribution is **`seat_column_mismatch` 705,
`ragged_columns` 61, `coordinate_grid_incomplete` 0 — it never fires at all.**

It is not merely unused; it is **unreachable by truncation**, and for a reason of
source order rather than logic. `expected` is built from `seat_count`, which
comes from the header, so by the time the cover check at `board_dom.py:554` runs,
`seat_column_mismatch` at `:462` has already refused any input whose column count
disagrees with the header — and dropping whole trailing columns is exactly that
input. `ragged_columns` catches only the residue: cuts landing inside the *last*
column, where 12 columns are still present.

So the guarantee is **"the header precedes the body in document order"**, which
is a *different property from column-major* and must be pinned separately: a
redesign could preserve either and break the other. I had named one secondary
guard and one dead one, and got the right answer for the wrong reason — which
would have survived indefinitely, because the conclusion was correct.

**Seat index is stable.** Column *i* begins with coordinate `1-i` in **all 42**
captures, spanning 0 to 216 picks. Checked by content rather than header text:
**0** columns ever lost a pick they previously held, and **0** `overall → seat`
remappings. The **4** name changes are `Mock Drafter N` → real name at fixed
indices (seats 4, 12, 6, 10). Decision 2 digests `seat` and excludes `seat_name`,
and that is precisely the property that holds.

### The safety comes from the layout, not from the check

**A uniformly-short board parses clean, short, and `is_complete=True`.** Built and
driven: 12 columns uniformly cut to 14 cells parses as a *finished* 12×14 draft
reporting 168 of 216 picks. No structural check sees it — `rounds` is derived
from the cell count at `board_dom.py:475-484`, and a uniformly-short board is
perfectly rectangular with a complete coordinate cover.

The only thing that catches it is the chat cross-check, **and the chat pane does
not exist on the `/draft/board` route.** Five recorded snapshots (0043–0047,
157–205 picks) carry picks and no chat pane, and **the owner navigated to that
route mid-draft.**

Today the layout and the check give the same answer. A Fantrax redesign, a
virtualised board or a partial Angular re-render separates them, and on
`/draft/board` nothing would notice.

**This is not a parser defect and must not be fixed there.** A parser sees one
snapshot and cannot know that 14 rounds is wrong. **Board dimensions are a
property of the draft, not of the snapshot**: once an 18-round board has been
seen for a draft, a 14-round reading must refuse. That is a fifth decision for
`draft-board-feed-integration`, and it is the one with a live failure behind it
rather than a hypothetical.

Related: `is_complete` means "every rendered cell is filled", not "the draft is
over". On a uniformly-short board it returns `True` for a partial draft.

**What this still does not establish.** One draft, one league, football, snake.
It says nothing about an auction board, which may not carry coordinates — or be a
grid — at all, and nothing about a team being removed mid-draft or a re-sortable
board. Stability here is 42 snapshots of one uninterrupted session.

**Because the fixture is committed, the two structural claims are tests rather
than claims** — no private capture is needed to re-derive either. Pinning
column-major order against that fixture is an acceptance criterion on
`draft-board-feed-integration`.

### 2026-08-28 — source columns require an explicit participant binding

**Status:** Proposed. Written by `architect`; only the project owner accepts.

Rendered board markup contains no team id. Never join a board pick to
`DraftParticipant` by a displayed seat or team name: four such names changed
during the recorded session while their columns stayed fixed.

`DraftParticipant.team_slot` is the internal ordered-draft coordinate contract,
but nothing establishes that the owner populated those slots in Fantrax column
order. The board DOM independently proves snake or linear source coordinates;
it does not prove participant identity. A rotated setup would otherwise
silently attribute every pick to the wrong participant.

Until setup records an explicit, one-to-one source-column-to-participant
binding, or an equivalent independently established anchor, board observations
may be stored and published by source coordinate but must not enter
participant-attributed draft events. The service layer must also require the
board layout to match the frozen ordered draft type, `seat_count` to equal
`draft.team_count`, and each `(round, pick_in_round, seat)` to agree with the
frozen `DraftFormat`. Missing, incomplete, or contradictory binding or
coordinates refuse attribution. Auction and `layout="other"` remain
unestablished and refused.

This also narrows three explanatory claims in the accepted body. Decision 2's
board dimensions mean `seat_count` and `rounds`, not mutable
`BoardReading.seats`. Independence reports a shared artifact before a shared
transport; two bridge readings remain non-independent either way.
`board_dom` artifact identity names parsed board content, not necessarily raw
bytes; the backend lane owns reconciling the implementation docstrings.

Board dimensions per draft remain the separate
`board-dimensions-per-draft` follow-on. This amendment does not absorb that
work.

Content deduplication has one exact blind spot: an undo whose rendered content
equals an already-stored board reuses its artifact identity, so it cannot be
observed as a new regression.

**Rejected:** direct `seat == team_slot`, joining by displayed names, or
treating a column as a Fantrax franchise identifier. **What would flip this:**
rendered markup gaining a stable team identifier whose independent captures
establish that it survives renames and draft types.
