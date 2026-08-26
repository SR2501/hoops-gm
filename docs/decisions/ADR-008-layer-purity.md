# ADR-008 — Aggregates are terminal outputs, never inputs

**Status:** Accepted
**Accepted:** 2026-08-18 by the project owner
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
4. **Every stored quantity records its layer**, and a test rejects any flow from a higher layer to a lower one — the same project-wide "make invalid states inexpressible" pattern used at other load-bearing boundaries.
5. **The draft-day rankings are ours alone** — computed end-to-end from our own projections and availability, with no external ranking anywhere in the lineage.

## Consequences

Some tempting shortcuts become unavailable. Blending FantasyPros consensus rankings directly into our valuation would be quick and is now forbidden; only their underlying per-game projections may be imported, with their games-played assumption stripped and replaced by ours.

In exchange, every number stays decomposable. "Why is he ranked here?" always resolves to production × availability, both traceable to their own sources, and the model-vs-market report stays honest because the two sides never touched.

## Rejected

**Blending rankings for a quick baseline** — the fidelity loss is unrecoverable and invisible.
**Trusting sources to be pure** — most published projections silently bundle a games-played assumption; the importer already strips it.

## What would flip this

A source publishing genuinely decomposed outputs — per-game production and its availability assumption as separate fields. Those may be imported into their respective layers. The rule is about the *aggregate*, not the publisher.


## Amendments

### 2026-08-25 - a rank cannot express clause 3 (`Proposed`)

**Status: Proposed.** Written by `architect` on the `backend` lane's argument.
The decision is unchanged; what changed is the discovery that clause 3 is **not
expressible** by the construction everyone reaches for first.

Clause 3 says no ranking, AAV or composite value may be an input to any earlier
layer. The obvious implementation is a rank: order the layers, refuse any flow
from a higher number to a lower one. It is cheap, idiomatic, and wrong.

> **No total order can express "A must not reach B" while also placing A before
> B.**

Driven on `f3e2c53`: a rank permits `valuation -> market`, `availability ->
market` and `projections -> market`, because `MARKET` must sit late enough to
consume valuation and therefore sits later than all three. Each of those edges is
R38 - our own fused value returning as somebody else's evidence, which is the
circularity this ADR exists to prevent.

**Implementers: use an explicit permitted-edge set, not a rank.** `LAYER_RANK`
survives only as a descriptive label. `FLOW_MATRIX_SIZE` is asserted so an eighth
layer forces every new edge through review rather than defaulting.

**The default is what protects; the assertion only notices.** `flow_permitted` is
a pure allowlist with no fallback, so an enum member cannot add a permission and
every undecided edge is refused. The residual is **over**-refusal - loud,
immediate, at import - rather than a wrong number.

### Rejected: an explicit `REFUSED_FLOWS` set with a reason per edge

It converts silencing keystrokes into authored lines a reviewer can see, which is
real. It buys no safety the allowlist default does not already give, and
twenty-five reasons that mostly read "backwards" is documentation nobody rereads.
Recorded so it is refusable again rather than rediscovered.

### What this ratifies, at its real size

`main` was **not** violating clause 3 when this landed: 39 mapped tables, 62
declared foreign keys, **zero flowing backwards**, only 5 cross-layer and all
five identity.

But "assigns nothing" would be the wrong summary. **Three of thirty-nine tables
already recorded a layer** - `absence_splits` at `observations`,
`auction_value_sources` and `published_auction_values` at `market` - each by an
ad-hoc CHECK on a string column. **The repository had independently reached for
this idea three times without a shared vocabulary.** This amendment ratifies a
concept that had already emerged, which is also why `MARKET` is in the enum.

### What this cannot see

Pinned as assertions in `test_layer_purity.py` rather than left in prose.

- **`FLOW_SCAN_LIMIT`** - the set is closed under *declared foreign keys*, not
  under Python. A value copied between layers in application code leaves no key
  and is invisible. **10** `_id`-suffixed columns have no declared FK.
- **`GRAIN_LIMIT`** - assignment is per-table. `draft_events.amount` is a live
  R38 case, a market quantity on a non-market table, and this cannot see it.
  Column granularity is what comes next.

### What would flip this

A layer vocabulary where every pair's permission follows from position - if one
is ever found, the edge set becomes redundant. Nobody has proposed one, and
clause 3's shape is the reason to doubt it exists.