# ADR-017: Auction pricing ships on seed AAV; empirical AAV is an enhancement

- **Status:** Proposed
- **Date:** 2026-08-23
- **Deciders:** owner (accepts), architect (proposes)
- **Supersedes:** nothing. **Amends:** nothing.

## Context

`blind-mocks` is the only **blocked** item in the backlog, and it is blocked
**externally**: the owner found no site offering live auction mocks
(2026-08-17). No engineering effort resolves this.

It is also load-bearing in a way the block notice does not state. Tracing
dependencies on `ade4fa9`:

```
blind-mocks [BLOCKED]
  -> aav-empirical        (R37 track B)
    -> aav-blending
      -> auction-values
        -> auction-inflation, auction-budget-manager
          -> auction-nomination
            -> overlay-auction-panel
```

**The entire auction pricing chain — the screen the owner uses on 18 October —
is downstream of an item with no known venue.** As specified, draft day is
unreachable, and nothing in the milestone table shows this because each edge
looks locally reasonable.

`aav-source` (R37 **track A**, published seed AAV, normalised to this league's
budget pool, team count and roster size per R39) is **done**.

**And the dependency is not merely unfortunate, it is wrong.** `auction-values`
describes its own work as: *"Convert risk-adjusted G-score to dollar values via
value over replacement scaled to the league total budget pool, accounting for
roster size and the minimum-bid reserve."* That derivation takes
`risk-adjusted-valuation` and league configuration. **It does not consume AAV at
all.** AAV is a *seed and cross-check* — a second opinion on a number we compute
ourselves — not an input to the computation.

## Decision

**Drop `aav-blending` from `auction-values`. Keep `aav-source` as a cross-check,
not a precondition.**

This is not a reduced v1. It restores the item to what its own description says
it does: dollars derived from our valuation, with published AAV available beside
it for comparison. `aav-empirical`, `aav-blending` and `aav-calibration` become
**enhancements** that land if and only if a mock corpus materialises.

Implementers: compute dollar values from risk-adjusted G-score. Where AAV is
displayed, show it as a **separate, labelled quantity** alongside ours — never
blended into it, and never silently substituted when ours is unavailable. Do not
stub `aav-empirical`: an absent source must be **absent**, not an empty corpus
that reads as a real one contributing zero.

## Rejected

**Waiting for lobbies to open.** Their opening date is unknown and outside our
control; a hard deadline cannot depend on it.

**Manufacturing simulated clearing prices.** The backlog already forbids this
and is right: R38's control group is only uncontaminated if it is real.

## What would flip this

A mock corpus large enough for `aav-calibration`. Then `aav-empirical` is added
**as an additional source behind the same interface** — not as a precondition.
Note R38: participants price from the same public AAV we seed from, so early
clearing prices echo the seeds rather than testing them. Even unblocked,
empirical AAV starts weak. That is a further reason it must never gate.

## Consequences

Auction values ship derived from our own valuation, with published AAV beside
them as a check. The owner should know that until a mock corpus exists, nothing
in the tool observes what players *actually clear for* in a league like his —
the dollars are a projection of worth, not a forecast of price. That gap is
real, it is unavoidable given the block, and naming it is better than closing it
with data we would have had to invent.
