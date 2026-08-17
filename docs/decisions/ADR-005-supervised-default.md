# ADR-005 — Automation is supervised by default; autonomous is opt-in and gated

**Status:** Accepted
**Accepted:** 2026-08-17 by the project owner
**Date:** 2026-08-17

## Context

The owner wants both: supervision while sitting at the draft, and the ability to hand off a round or two — or a lineup set — when preferring not to be present.

The instinct that a userscript driving real DOM events in the owner's own session is indistinguishable from human interaction is broadly correct at the network layer, since the traffic *is* the owner's real session. But detection is the wrong thing to design around. **The real risk is a defect** — auto-drafting a bust, submitting an illegal lineup, or acting on stale injury data at 11:59pm.

## Decision

One pipeline, two modes.

**Supervised (default).** Backend computes a recommendation, the overlay highlights it in Fantrax, the human confirms.

**Autonomous (explicit, per-session opt-in).** The same pipeline, actioned by the userscript, bounded by eight mandatory guardrails: kill switch, dry-run default for new action types, validity precheck, scope caps, confidence floor, availability freshness check, human-paced execution, and a full audit log.

Enforced by structure:

- All write-path code is isolated in one swappable module.
- **`safety` reviews it independently and holds veto. `bridge` may not approve its own guardrails.**
- Enabling autonomous mode, widening its scope caps, and first action on a real draft or live lock are **owner-only decisions**.

## Consequences

Slower to ship than wiring the executor straight to the recommender, and every write-path change carries review overhead — including changes that look trivial, which is where this normally goes wrong.

In exchange, an automation bug is caught in dry-run rather than on draft night, and scope is always bounded and revocable.

## Rejected

**Fully autonomous from the start** — the recommender has not earned that trust and cannot until it is validated against mocks.
**Read-only, no writes** — rejected by the owner, and the guardrails make supervised writes reasonable.

## What would flip this

Sustained evidence across many rehearsals and a full season that the recommender and executor are reliable enough to loosen specific caps. That remains an owner decision.
