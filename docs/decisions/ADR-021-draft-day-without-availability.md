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

## Amendments

### 2026-09-06 - all four censuses have landed, and point 4 names a number that cannot be computed

**Status:** Proposed. Written by `architect`, the author of the body above.

**The decision does not change.** Two claims under it do.

**The Context is out of date, and in the project's favour.** It states that
`PROCEED_COMMON` requires four direct seasonal censuses and that "2023-24 and
2024-25 currently hold **zero** protocol-eligible observations". All four have
since landed. `docs/adapters/participation-ledger-2022-23-coverage.json` carries a
`protocol_support` block naming `required_direct_census_seasons` as 2022-23,
2023-24, 2024-25 and 2025-26, assigning them the roles
`historical_marcel_support_only`, `development`, `selection` and `held_out`, and
reporting **170,856 direct rows** in
`participation-ledger-direct-2022-26.db` at revision `0016`. Game coverage is
1230/1230 for the first three seasons and 1227/1230 for 2025-26, the three
unobserved games all falling on 2025-11-19.

**So `PROCEED_COMMON` has exactly one unmet conjunct, not two.** The remaining
one is `unknown_share <= 0.05`, which is not failing but uncomputable, for the
reason the body already gives. That is now tracked as `roster-interval-source`,
which states the five properties a source must supply and blesses a negative
result as closing it. This narrows what the owner is deciding: not whether to
rescue a two-part gap, but whether to acquire one input.

**Point 4 is buildable, and the body does not say why.** The veto is on the
*denominator* - which games a player could have played. Point 4's numerator -
games observed played - is directly observed and needs no roster intervals at
all. That asymmetry is the whole reason a durability panel survives a veto that
stops valuation. Measured from the store above for 2025-26: 582 players hold at
least one played game, median 51 and mean 45.7, with 175 players at 65 or more
and 265 at 55 or more. A twelve-team league drafting thirteen slots needs about
156 names, so the panel is populated across the entire draftable pool rather than
only its top.

**Point 4 cannot be built exactly as written.** It requires "observed games played
with its **unknown share** published", but the unknown share the accepted protocol
defines is the quantity this same ADR says is not calculable. As drafted, point 4
asks the screen to publish a number the Context says does not exist. Two readings
build different screens, so the ambiguity is load-bearing rather than cosmetic.

**Resolution: publish the denominator, not an unknown share.** The panel names on
screen the population it divided by - games the player's team played while that
player held any participation row that season - which is descriptive, checkable,
and needs no roster intervals. It must be labelled so it cannot be read as the
protocol's `unknown_share`, which remains uncomputed. Reusing that name for a
weaker quantity is precisely the `gameEt` failure this project keeps paying for:
a well-formed value that lies about what it is.

**What the number cannot see, and this must appear beside it.** Games played
conflates durability with rotation status and roster tenure. An injured starter, a
healthy scratch, a late signing and a two-way player on assignment are
indistinguishable in it. That conflation is exactly what the denominator would
resolve, and exactly why this panel stays descriptive, is never sorted as though
it were value, and is never fused into a price (ADR-018, ADR-002).

**The uncomputable conjunct is now measured rather than argued, and you can check
it in ninety seconds.** When this ADR and the amendment above were written, the
claim that `unknown_share` is uncomputable rested on reasoning about what the
admitted sources emit. PR #172 has since merged the machine-readable finding, so
the claim is now falsifiable against a committed file rather than against prose.
In `docs/models/participation-opportunity-coverage-v1-evidence-gap.json`:

- `evaluation_status` is `not_evaluable`, and `proceed_opportunity_coverage` is
  `null` - **not `false`**. The distinction is the whole decision: a `false`
  would mean we measured coverage and it was too low, which a better ingest could
  fix. A `null` means the quantity has no denominator to be a share of.
- `source_feasibility.real_source_registry_can_be_supplied_from_admitted_sources`
  and `...reconstruction_contract_can_be_supplied_from_admitted_sources` are both
  `false`. Those are the two inputs the amendment above refers to as "one input";
  they are two fields but a single acquisition.
- `new_source_acquisition_attempted` is `false`, with the scope field stating
  plainly that acquiring one is separate Adapter-gate work that **may require an
  owner-only paid-data decision**. No agent has attempted it, and none may.

**What this evidence does not establish.** It shows the denominator cannot be
built from sources we have *admitted*, which is not the same as showing no free
authoritative source exists - the lane that produced it said so explicitly, and
that gap is real. It also does not price or evaluate any paid source, because
that assessment is owner-only and was correctly not started. So this artifact
closes the question *"can we proceed on what we have?"* with a firm no, and
leaves *"is there something we could get?"* open. Accepting this ADR does not
answer the second question or foreclose it.

**What I did not do.** I counted played rows per player. I did not compute an
at-risk denominator, an unknown count, or any unknown share, and nothing here is
an input to the frozen preregistration at
`docs/models/participation-opportunity-coverage-preregistration.md`.

### 2026-09-06 - the Context vetoes a thing the Decision requires, and the veto is the mistake

**Status:** Proposed. Written by `architect`, the author of the body above.

**The decision does not change. One claim under it is false and it is load-bearing.**

**The contradiction, stated so it can be checked in a minute.** The Context above
says everything downstream - naming `zscore-engine` among them - "is behind that
veto". Decision point 2 requires on 18 October "our own per-game projections and
**category values, unadjusted for durability**". Category values unadjusted for
durability *are* `zscore-engine`'s output; the backlog item describes it as
"Z-score valuation for FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO". So as written
this ADR requires on draft day a thing it elsewhere declares vetoed. Two readings
build different products, which is why this is worth an amendment rather than a
correction in passing.

**The Context is the half that is wrong.** `zscore-engine` was behind the veto
only through a single backlog dependency edge on `expected-games`. ADR-002's
Decision defines `expected-games` as the seam where production and availability
are combined - "the only place the two are combined" - so that edge made the
production half wait on the fusion. Its other two edges, `projection-blending` and
`scoring-profiles`, are both `done`. The edge is removed as of 2026-09-06 with the
argument recorded in the backlog item, and `zscore-engine` is dependency-ready.

**Why this matters more than a tidy-up.** It changes what point 2 costs. Written,
point 2 reads as a concession - ship less because the model is blocked. It is
better than that: an unadjusted per-game z-score is not a substitute for the
intended architecture, it is **the production half of it**, computed exactly as
ADR-002 intends and fusing at `expected-games` without rework when the veto
clears. The draft-day fallback and the real design are the same artifact stopped
one layer short, so nothing built for 18 October is thrown away.

**It also supplies a selection rule the headline deliverable lacks.**
`draft-day-shortlist` must return 3-5 candidates and the owner's stated reason for
wanting it is to avoid "overweighting one category by sorting in a hurry" - so
single-category sorting is excluded by the requirement itself, while its Gate
boundary forbids inventing a fused score under the Code gate. A production-only
z-score under a full Model gate is the one ordering that satisfies both.

**What this does not do.** It does not weaken the availability veto, touch
`PROCEED_COMMON`, or make `expected-games`, `risk-adjusted-valuation` or
`auction-values` reachable; those remain behind it and the amendment above still
governs. It does not relax the Model gate on the z-score, which needs calibration
reporting, a model card and a blind-spot statement before any number it produces
reaches a screen. And it does not make the z-score safe to display as value: it is
production-only, it says nothing about who suits up, and sorting it as though it
were availability-adjusted is the failure ADR-002 exists to prevent.

**What I did not verify.** That no *other* dependency edge in the backlog carries
the same defect. I found this one by walking the chain behind a single deadline
item; the same inversion could sit on any edge pointing at a fusion or aggregation
step, and I checked the spine rather than the graph. Filed as
`fusion-seam-edge-audit`.
