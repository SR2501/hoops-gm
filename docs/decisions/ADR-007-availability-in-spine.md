# ADR-007 — Availability is a spine concern, modelled before valuation

**Status:** Proposed
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
