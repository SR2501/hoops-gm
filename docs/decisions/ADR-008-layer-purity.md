# ADR-008 — Aggregates are terminal outputs, never inputs

**Status:** Proposed
**Date:** 2026-08-17
**Originated by:** the project owner

## Context

ADR-002 separates per-game production from expected games played inside our own pipeline. It does not say what happens when an *external* product already contains both.

Published rankings, average auction values, and "expert consensus" tiers are **synthesized aggregates**. A ranking already contains production, an availability assumption, a scoring-format assumption, and often positional scarcity. AAV adds market psychology and budget structure on top. Blending any of these into our projection or availability layers imports all of those hidden components at once.

The owner's analogy: holding mutual funds and then buying company stock through an ESPP, only to discover the fund was already heavily weighted in your employer. The exposure was there the whole time; the aggregate concealed it. Two positions that looked independent were not.

The failure is loss of fidelity, and it is silent. Availability gets counted twice — once by our model, once inside the imported ranking — and afterwards no query can separate "he is good" from "he is durable," because the distinction was destroyed at import.

This is the third instance of one pattern on this project. Using a name-matched ID dataset as a crosswalk bridge would launder a name match into an apparent hard key (R23). Bidding with our own values in mocks would launder our own output back in as market evidence (R38). This laundering derived information into apparent independent evidence.

## Decision

Layers are ordered, and information flows one way only.

```
observations → projections → availability → valuation → rankings/values
   (facts)      (production)   (p(play))     (fused)      (TERMINAL)
```

1. **Aggregate only within a layer.** Projections blend with projections — per-game rates, never seasonal totals with games baked in. Availability blends with availability. Never across.
2. **Terminal products never re-enter.** No ranking, AAV or composite value may be an input to any earlier layer, at any weight, including zero-with-intent-to-raise-it.
3. **External aggregates may be compared against, never blended in.** This is exactly the model-vs-market report: divergence is the signal, and it only means something if the two sides are independent.
4. **Every stored quantity records its layer**, and a test rejects any flow from a higher layer to a lower one — the same "make it inexpressible" pattern as ADR-007's tenant isolation analogue.
5. **The draft-day rankings are ours alone** — computed end-to-end from our own projections and availability, with no external ranking anywhere in the lineage.

## Consequences

Some tempting shortcuts become unavailable. Blending FantasyPros consensus rankings directly into our valuation would be quick and is now forbidden; only their underlying per-game projections may be imported, with their games-played assumption stripped and replaced by ours.

In exchange, every number stays decomposable. "Why is he ranked here?" always resolves to production × availability, both traceable to their own sources, and the model-vs-market report stays honest because the two sides never touched.

## Rejected

**Blending rankings for a quick baseline** — the fidelity loss is unrecoverable and invisible.
**Trusting sources to be pure** — most published projections silently bundle a games-played assumption; the importer already strips it.

## What would flip this

A source publishing genuinely decomposed outputs — per-game production and its availability assumption as separate fields. Those may be imported into their respective layers. The rule is about the *aggregate*, not the publisher.
