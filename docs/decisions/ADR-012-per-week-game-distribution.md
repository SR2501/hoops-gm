# ADR-012 — Per-week game distribution is a draft/trade-facing view, not folded into valuation

**Status:** Accepted
**Accepted:** 2026-08-17 by the project owner
**Date:** 2026-08-17

## Context

The owner flagged that the schedule grid — games scheduled per fantasy week, per team/player, already an output of `schedule-ingest` (Phase 3) — matters for draft, trade, and weekly management independent of strength of schedule (ADR-011). Some players' teams are front-loaded early in the season, others back-loaded; a player may have only two games in one H2H period and five in another. For top players, that volume difference can swing an entire matchup. Drafting or trading for players whose game distribution complements the roster's existing weekly totals, and acting on known light/heavy weeks, is a material fantasy input distinct from "is the opponent good."

This is a third, separate schedule concern from the two already sequenced. `schedule-density` (Phase 3) is calendar arithmetic per game. `opponent_context`/`strength-of-schedule` (Phase 4/5, ADR-009/011) is about opponent quality. This is about **game *count* distributed across weeks** — already computable the moment `schedule-ingest` lands, since it needs no opponent-quality judgment and no player valuation at all, just team schedule counts per `scoring_periods` week.

Currently nothing consumes it early enough to matter. `schedule-ui` exists but is gated behind the full `availability-model` (Phase 4) and is presented as availability-adjusted, not as a raw draft-prep view. `draft-recommender` and the auction items (`auction-values`, `auction-nomination`) have no dependency on schedule data at all today — a genuine gap, since the marginal edge the owner describes is exactly a draft-day and trade-lab decision.

## Decision

The per-team, per-week scheduled game count from `schedule-ingest` is exposed as its own lightweight, standalone view — not bundled into `schedule-ui`'s later availability-adjusted grid, and not deferred behind it. Name it `schedule-grid-early` (or fold into an existing early-phase item if a specialist finds a natural home — `architect` doesn't own the implementation, only the sequencing gap).

It surfaces in two places already in the plan, both of which need a new dependency on `schedule-ingest`:
- `draft-recommender` — as a schedule-volume signal alongside valuation: expose each candidate's weekly game-count profile, flag two-game/five-game weeks, and use schedule fit when comparing otherwise viable roster constructions. It must not be hidden inside a long-run player valuation.
- `trade-evaluator` — already depends on `schedule-ingest`; extend its "schedule impact" to explicitly include per-week game-count shape, not just fantasy-playoff-week strength.

This is raw count data, not a model — no Model gate, just the Adapter gate `schedule-ingest` already satisfies.

## Consequences

`schedule-ui`'s scope stays what it was (availability-adjusted grid, later phase). A second, earlier, simpler surface avoids waiting for the availability model to give draft prep something the data already supports on day one of Phase 3.

## Rejected

**Waiting for `schedule-ui`** — ties a zero-judgment fact to a Phase 7 UI item and to the availability model, when the underlying data is ready in Phase 3 and the decision it informs (draft, trade) happens well before Phase 7 ships.

## What would flip this

If held-out H2H analysis shows weekly game-count timing has negligible fantasy value even for elite players, reduce it to an informational display rather than an active recommendation signal. It must not be removed merely because it is not a projection input; its weekly management value is a separate question.

## Amendments

### 2026-08-17 — Sparse league-wide weeks and trade targeting

The schedule grid must identify sparse periods caused by league-wide calendar events, especially the In-Season Tournament and All-Star break. These weeks can have fewer games across the league, so a player's raw scheduled-game count must be shown both against that team's normal distribution and against the league-wide period baseline. Trade evaluation must use this information to identify schedule-driven targets and avoid treating a high-value week as an ordinary period. A trade can be attractive because it improves a specific sparse or high-volume H2H period even when rest-of-season totals barely change.
