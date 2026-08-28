# ADR-020: A rendered board reading is keyed by the board, not by the bytes

- **Status:** Proposed
- **Date:** 2026-08-28
- **Deciders:** owner (accepts), architect (proposes)
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
cut inside the board. The third is *mostly* excluded — `ragged_columns` and
`coordinate_grid_incomplete` refuse an incomplete cover — but that is established
only against captures whose cut landed **past** the board, which is all 22
truncated ones on record. A cut landing inside a longer board has never been
observed, so `bridge-snapshot-budget` is load-bearing rather than hygiene.

**Every byte of evidence under this ADR is football, snake format.** Nothing here
has been driven against an auction board or an NBA one.

## Amendments

### 2026-08-28 — the truncation and seat-stability claims are now measured, not reasoned

**Status:** Proposed. Written by `architect`, the author of the body above; only
the project owner accepts.

**The decision does not change.** What changes is the standing of two claims
under it, both of which the handoff entry listed as "could not verify".

**The board is column-major in document order, and this is now checkable in CI.**
Coordinate marks in `backend/tests/fixtures/fantrax_draft_board_complete.html`
run `1-1, 2-12, 3-1, 4-12 … 17-1, 18-12` — all eighteen of seat 1's picks,
snaking within the one column — and only then `1-2, 2-11, …`. The same holds in
**all 42 board-bearing captures**. The Consequences paragraph above therefore
stands: a byte cut either removes whole trailing columns, leaving `seen` short of
an `expected` built from the **header**-derived `seat_count` and tripping
`coordinate_grid_incomplete`, or lands mid-column and trips `ragged_columns`.
Both refuse. Had the layout been row-major, a cut would have removed trailing
rounds uniformly, `rounds` is derived from the rendered cell count
(`board_dom.py:475-484`), and a truncated capture would have parsed **clean and
short** — the precise defect the unit exists to prevent.

**Seat index is stable.** Column *i* begins with coordinate `1-i` in **all 42**
captures, spanning 0 to 216 picks. Decision 2 digests `seat` and excludes
`seat_name`, and that is the property that holds: the four renames
`board_dom.py:171` records are of displayed *names*, and the digest never reads
one.

**What this still does not establish.** One draft, one league, football, snake.
It says nothing about an auction board, which may not carry coordinates at all,
and nothing about whether column order survives a mid-draft re-render in a
different league.

**Because the fixture is committed, this is a test rather than a claim** — no
private capture is needed to re-derive either figure. Pinning column-major order
against that fixture is now an acceptance criterion on
`draft-board-feed-integration`, so the property is re-derived rather than
believed.
