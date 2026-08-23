# ADR-002 — Separate per-game production from expected games played

**Status:** Accepted
**Accepted:** 2026-08-17 by the project owner
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

## Amendments

### 2026-08-23 — the decomposition is three-factor in practice, and discarding a source's `games` column does not discard its games assumption

**Status:** Proposed. Written by the `quant` lane; only the project owner accepts.

The decision does not change — and, against the reading that prompted this, its
seam did not need locating. Inside this ADR's vocabulary the decomposition is
two-factor, per-game production × expected games, so there is one seam and it
sits at games by construction. What the measurement introduced is a
**three-factor** decomposition, `games × minutes-per-game × per-minute rate`, in
which the question is askable for the first time. This amendment imports that
vocabulary and attaches the hazard it exposes.

**Minutes-per-game is production-side.** A commercial minutes view *amplifies*
rather than shrinks against a naive baseline — slope 1.06–1.09 within a fixed
games bucket, the signature of depth-chart information no box score holds.
ADR-015 clause 4 already admits minutes to the durable recipe as production.

**The hazard, which is the reason to amend.** The Decision requires an imported
games assumption to be captured separately *"so our availability model can
override it rather than compound with it"*. A per-game rate obtained by dividing
a season total by that assumption is not free of it. Measured on the one export
we hold: `minutes ÷ games` is an exact integer for **505 of 505 rows** against a
shuffled-divisor control at 10.9% — their minutes total *is* their games tier
times an integer MPG. The per-game figure is recoverable without residue; the
total is not, and nor is anything rebuilt from it. For the counting categories
the same question is **undetermined**, because publication rounding leaves every
candidate divisor at chance.

**Added to the Decision.** Consume a source's per-game rates and
minutes-per-game; **never its seasonal totals, and never a consumed rate
multiplied by that source's own games figure.** Both re-import the assumption
this ADR discards, while looking like fidelity to the publisher. ADR-015:99 names
one instance of this; it is general.

**Rejected.** *A new ADR* — nothing decided changed and no boundary moved.
*Nothing at all* — defensible on the seam question, but the hazard is stated
nowhere. *Naming the seam without the hazard* — records a non-discovery and omits
the discovery.

**What would flip it.** A source whose rates are shown to be native rather than
divisor-manufactured, or whose games column carries a per-player opinion rather
than a tier. The test is concentration, not variety: in our export's rotation
cohort `games` and minutes-per-game take the **same 18 distinct values** and
differ 6× in effective levels, 2.5 against 14.9.
