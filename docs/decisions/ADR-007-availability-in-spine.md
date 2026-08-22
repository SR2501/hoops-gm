# ADR-007 — Availability is a spine concern, modelled before valuation

**Status:** Accepted
**Accepted:** 2026-08-17 by the project owner
**Date:** 2026-08-17

## Context

The natural build order for a fantasy tool is stats → projections → valuation → features, treating games played as an attribute applied near the end.

That order is wrong for this project. Availability is not an attribute of a valuation; it is an **input** to it. Expected games played feeds the fusion step (ADR-002), per-category nightly variance feeds G-score (ADR-003), schedule density conditions `p(play)`, and contingent value depends on absence patterns. Building valuation first and retrofitting availability means rewriting the valuation layer.

There is also a product argument. Missed games are epidemic and getting harder to predict, so availability modelling is the largest single edge available. Treating it as a late-phase feature would make it the first thing cut when draft day approaches.

## Decision

Availability is part of the spine and is sequenced **before** projections and valuation:

1. Foundations
2. Data spine — identity, adapters
3. Schedule intelligence
4. **Availability & reliability engine**
5. Projections & valuation

Feature work — live scorecard, draft, bridge, automation, lineup, trades — comes after.

The availability engine is not a single model but a set: participation ledger, injury status conversion, `p(play)`, reliability metrics, shutdown risk, absence splits, contingent value, and a calibration backtest.

## Consequences

Nothing visually impressive exists for a while. The draft board and live scorecard are the tempting things to build first, and they are worthless sitting on a broken identity table or a naive games-played assumption.

Schedule intelligence is pulled earlier than a feature-led plan would put it, because the availability model consumes density features.

## Rejected

**Valuation first, availability later** — guarantees a rewrite of the layer everything depends on.
**Flat games-played assumption** — the exact modelling error this project exists to beat.

## What would flip this

Evidence that a simple seasonal games-played average predicts as well as a contextual per-game model. The backtest harness will answer this directly, and if it does, the engine should be simplified accordingly.

## Amendments

### 2026-08-22 — the availability model must state an identification strategy before it fits anything

**Status:** Proposed. Written by the quant research lane; only the project owner accepts.

The decision above does not change. Availability stays in the spine, before valuation. What changes is that a **specific, published, named failure mode** now sits in the path of the model as currently specified, and an ADR whose implementation walks into it is incomplete rather than wrong.

**The mechanism.** `arXiv:2603.26935` — *"The Load Management Paradox: Correcting the Healthy-Worker Survivor Effect in NBA Injury Modeling"*, Yue Yu and Guanyu Hu, 2026-03-27, stat.AP; fetched and independently confirmed via the arXiv API, with a control fetch of a nonsense identifier that 404s — reports that **conditioning on game participation induces collider bias driven by unobserved latent fitness**, and that in their simulation this selection mechanism is *"mathematically sufficient to entirely reverse the sign of the true association"* between workload and injury. Not "may bias results". Reverse the sign. They conclude that *"models relying strictly on observational game logs will systematically underestimate the true risk of heavy workloads."*

**We reproduced it in our own data, in the exact quantity this engine consumes.** Prior-season workload against next-season games played, ten seasons of `PlayerGameLogs`: total minutes → next GP **r = +0.521** across all players (+0.328 for the ≥500-minute cohort); MPG → next GP **+0.453** (+0.244). Read naively, heavy minutes protect a player from missing games. Nobody would defend that physiologically. It is survivorship — players healthy enough to log heavy minutes were healthy, and health persists.

**A model fitted on game-log workload features without an identification strategy will learn that workload is protective, and will be confidently, invisibly wrong.** Nothing about it crashes. This is the exact failure class the gates exist for, and the Model gate as currently written would pass it: such a model can be well calibrated *on the selected population* and still carry a reversed causal sign.

**Requirement added to `availability-model`'s Model gate.** Alongside calibration, the model card, and the statement of what the model cannot see, the model must **state its identification strategy before it fits anything** — what population its estimate is conditional on, which of its features are affected by selection on participation, and why its estimate is not the paradox. The paper's own remedy is a marginal structural piecewise exponential model with inverse-probability-of-treatment weighting; naming a different strategy is fine, naming none is not. *A model that cannot say why its estimate is not the paradox is not gate-ready.*

**What this costs us, stated plainly.** The paper indicts our approach; it does not hand us a substitute. Its remedy needs a treatment model over the full at-risk population, and we do not have one — the participation ledger is unpopulated, which is the same blocker that gates the engine itself. **The honest expectation is that before draft day we can detect this bias but not correct it.** That is acceptable, and the requirement is therefore that the limitation ships **named** rather than unnamed: the model card must say that workload-derived features carry a selection-induced sign risk, that the estimate is conditional on having appeared, and that it should not be read causally. An acknowledged limitation is a different object from an undetected one.

**Why this is being written tonight.** Four hours before the paper was found, the injury lane *measured* the era effect on unresolved `doubtful` statuses and got 1.596 per date in the short-lead era against 0.917 in the legacy era — **the opposite direction** from what three of us had jointly predicted from a correct mechanism. Then a published paper turned up warning that a structural bias can reverse a sign in the very model we are about to build. Two independent arrivals at the same warning in one night is the finding: **a mechanism can be real and its sign wrong.** That is now both an empirical result in our data and a published result in the literature, aimed at the same unit.

**A note on the flip condition above, which is now partially engaged and not met.** Measured on players with three prior seasons (n=500): a Marcel-style weighted seasonal average predicts next-season games played at MAE 14.32, against 15.77 for last season alone and 15.90 for the constant league mean. So a *seasonal average* substantially beats the naive alternatives — but the flip condition compares it to a **contextual per-game model**, which has not been built and therefore has not been beaten. ADR-007 stands. The bar is now a number: any contextual model must beat **MAE 14.32 games** on held-out seasons to justify its complexity, and if it does not, the engine should be simplified as this ADR already says.
