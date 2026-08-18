# ADR-011 — Strength of schedule is a Phase 5+ valuation concern, not schedule intelligence

**Status:** Accepted
**Accepted:** 2026-08-17 by the project owner
**Date:** 2026-08-17

## Context

The owner flagged that strength of schedule (SOS) — how favourable a team's or player's remaining schedule is *relative to value*, not just density — is missing from the plan entirely. It surfaced while ADR-009 was splitting Phase 3/4 schedule work, and the two are easy to conflate: both consume `team_schedule` and both are "about the schedule."

They are not the same thing. `schedule-density` (Phase 3, data-engineer, ADR-009) is calendar arithmetic — B2Bs, rest days — with no opponent-quality judgment at all. `schedule-context`/`opponent_context` (Phase 4, quant, ADR-009) is opponent *defensive* quality, conditioning `p(play)` and per-category production variance for the availability model — it answers "does this matchup suppress minutes or stats," not "is this schedule good or bad to own."

Strength of schedule proper — is a stretch of games worth more or less than average, in fantasy-value terms — requires a value to weight the schedule by. That value doesn't exist until projections (`baseline-model`, `projection-blending`) and valuation (`gscore-engine`) exist in Phase 5. There is no way to build it earlier without inventing a placeholder value and later discovering it doesn't match the real one — the exact aggregate-contamination failure ADR-008 already names.

## Decision

Add `strength-of-schedule` to Phase 5 (Projections & valuation), owned by `quant`, depending on `schedule-ingest` (Phase 3), `opponent_context` (Phase 4), and `gscore-engine`/`baseline-model` (Phase 5) — it is one of the last spine items, not an early one, because it needs a settled valuation to weight against.

It computes, per team and per fantasy week: opponent quality faced (using the already-built `opponent_context` per-category defensive profiles) weighted by games scheduled, expressed relative to league-average schedule difficulty. It surfaces at three places already in the plan: `draft-recommender` (ROS value), `games-cap-tracker` and `playoff-schedule` (which playoff weeks are schedule-favourable), and `auction-values` (draft-day-only, so it necessarily uses *projected* rather than *known* opponent quality).

There are several defensible SOS formulations (opponent record, opponent per-category defensive rank, pace-adjusted, recency-weighted). Do not pick one now — that choice is itself a Model-gate-worthy decision requiring a backtest of which formulation actually predicts realized value, deferred to `quant` when the item is built.

## Consequences

`playoff-schedule` (Phase 3, currently game-count only) gets a second pass in Phase 5 once SOS exists, rather than being "finished" twice under different names. Note this explicitly in the backlog item so it isn't read as scope creep on the Phase 3 item.

## Rejected

**Building a placeholder SOS metric earlier from opponent record alone** — a preseason projection-free proxy would get silently baked into draft prep and never revisited, repeating the "guessed shape, believed, wrong" pattern (R30, R33, R36) this project keeps finding.

## What would flip this

If `quant` determines a projection-free SOS proxy (e.g., prior-season opponent defensive rank) is good enough to ship for the Phase 3/4 window and won't need to be thrown away once real projections land, it can move earlier — but that is itself a claim requiring evidence, not an assumption to build on.
