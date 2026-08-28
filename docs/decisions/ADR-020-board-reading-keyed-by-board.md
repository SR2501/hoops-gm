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
