# ADR-021 — What we walk into 18 October without

**Status:** Proposed
**Date:** 2026-09-05
**Author:** architect

## Context

`draft-day-synthesis` requires our own rankings and dollar values computed
end-to-end from our own projections **and availability**, with no external
ranking in the lineage (ADR-008 clause 5).

ADR-017 already severed one wrong edge on this path: `auction-values` derives
dollars from **risk-adjusted G-score**, not from AAV, so a missing mock corpus
cannot gate draft day. That decision stands and this one depends on it. But it
resolves `auction-values`' input by naming `risk-adjusted-valuation` — and
`risk-adjusted-valuation` is itself now unreachable, for a harder reason.

The owner accepted availability preregistration v1 on 2026-09-01; that
acceptance explicitly left `FIT_VETOED_PREREQUISITES` binding. `PROCEED_COMMON`
requires four direct seasonal censuses — 2023-24 and 2024-25 currently hold
**zero** protocol-eligible observations — and `unknown_share <= 0.05`, which is
not merely failing but **not calculable**: no independent roster-interval
evidence exists. `nba-official-transactions` is live and working, and its own
boundary states it emits no player-game rows. The NBA vocabulary has no
contract-expiration, retirement or assignment event, and a real release
(Wiseman, the Pacers' own 2025-12-26 notice) is absent from the central archive.

Everything downstream — `expected-games`, `zscore-engine`, `gscore-engine`,
`risk-adjusted-valuation`, `auction-values`, `draft-day-synthesis` — is behind
that veto. 29 days remain to the 4 October rehearsal boundary. This is a
source-capability gap, not a staffing one, and unlike `blind-mocks` it is not
resolved by a venue opening.

## Decision

**Draft day ships with no fused availability-adjusted valuation, and says so on
the screen.** The 18 October deliverable set is:

1. The live draft board with picks and budgets — the owner's Q15, which depends
   on none of this.
2. Our own per-game projections and category values, unadjusted for durability.
3. Published seed AAV **beside** them, exactly as ADR-017 already specifies —
   separate, labelled, never blended, never substituted.
4. A descriptive durability panel — observed games played with its unknown share
   published — held at the observation layer as `absence-splits` is, displayed
   beside the value and never fused into it (ADR-018).

Point 2 is the change: values ship from projections alone, because the
risk-adjusted input ADR-017 assumed would exist does not.

## Consequences

ADR-003's G-score default is not exercised on draft day. The reason is evidence
and calendar, not the backtest ADR-003 names as its flip condition, and deferral
must be recorded as such.

ADR-002 is preserved in the only way still open: production and expected games
stay separate, and the games side is **explicitly absent rather than silently
assumed**. The owner will see fragility as observation, not as a modelled number
the tool cannot honestly produce.

**This decision is inert unless ADR-017 is also accepted.** Both are `Proposed`,
both sit on the 18 October path, and neither an agent nor this document can
accept either.

## Rejected

**Fit `p(play)` anyway on 2025-26 alone** — the protocol the owner accepted
exists to refuse exactly this, and a miscalibrated availability number is the
project's defining failure mode.

**Import a vendor games-played column into the availability layer** — ADR-008
clauses 1 and 2. `external-games-as-class-prior` permits it as a class label,
never as an estimate, and a draft-day value is an estimate.

**Blend AAV into valuation to fill the gap** — clause 2, ADR-017, and the R38
laundering this project has already caught three times.

**Say nothing and let the deadline arrive.** The gap is knowable today with 29
days to build around it, and on 3 October it is knowable with none.

## What would flip this

All four direct censuses landed **and** an authoritative source or independently
validated reconstruction contract supplying complete opening membership, dated
starts and ends including contract expiration, and assignment/recall — clearing
`PROCEED_COMMON` before the rehearsal boundary. Nothing currently ingested
supplies it.
