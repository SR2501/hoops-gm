# ADR-002 — Separate per-game production from expected games played

**Status:** Proposed
**Date:** 2026-08-17

## Context

Missed games are epidemic in the modern NBA — load management, rest on back-to-backs, DNP-CDs, late-season shutdowns. A 70-game player and a 55-game player with identical per-game lines are very different assets.

Most published projections bundle a games-played assumption into a single seasonal total, and most homebrew tools inherit that. The result is systematic overvaluation of fragile stars and undervaluation of durable mid-rounders, with no way to inspect which factor drives a given number.

## Decision

Production and availability are modelled independently and fused only at an explicit seam.

- **Per-game production** comes from projection blending and the baseline model, expressed as rates.
- **Expected games played** comes from the availability model, as the sum of per-game `p(play)` over a window.
- **`expected-games`** is the only place the two are combined.

Imported projections must have their embedded games-played assumption captured separately from their per-game rates, so our availability model can override it rather than compound with it.

## Consequences

The tool can answer "is this player good, or merely present?" and price those separately. Total value and per-game value become distinct, inspectable views, which is what makes the fragile-star tradeoff explicit at the draft.

It costs an extra modelling layer and requires importers to decompose sources that publish only totals.

## Rejected

**Single blended seasonal projection** — simpler, but makes durability invisible and unattributable.
**Applying a flat durability discount after valuation** — cannot express that availability varies by opponent, schedule density and date.

## What would flip this

Nothing foreseeable. This is the central modelling commitment of the project.
