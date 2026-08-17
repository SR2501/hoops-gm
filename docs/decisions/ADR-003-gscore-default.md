# ADR-003 — G-score as the default valuation scheme for H2H

**Status:** Proposed
**Date:** 2026-08-17

## Context

Z-score is the standard method for valuing players in category leagues: normalize each category against the player pool and sum. It is well understood and widely documented.

But z-score values a season-long average, and the target league is head-to-head. In H2H, each week is a separate contest across nine categories. A player who produces the same total via consistent nightly output versus a few explosive games has a different effect on weekly matchup outcomes.

G-score (arXiv 2307.02188) accounts for week-to-week variance using probabilistic distributions rather than static point estimates, and outperforms z-score specifically in H2H formats. In roto the two are equivalent.

## Decision

Both are implemented. **G-score is the default for H2H leagues**; z-score remains available for comparison, for roto, and as a sanity check on the G-score implementation.

G-score's variance framework is also where **availability risk** is absorbed, alongside production variance. An unreliable player contributes variance through both channels, and G-score is the natural place to represent that jointly.

## Consequences

Rankings will differ from the z-score-based tools the market uses — including Basketball Monster and Hashtag. That divergence is intentional and is precisely what the model-vs-market report is for, but it must be explainable rather than merely different.

Requires per-category nightly standard deviations, which the reliability metrics already produce.

## Rejected

**Z-score only** — simpler and market-standard, but leaves H2H value on the table.
**G-score only** — loses a valuable cross-check and the roto path.

## What would flip this

Backtesting showing G-score does not beat z-score on this league's actual scoring settings and roster rules.
