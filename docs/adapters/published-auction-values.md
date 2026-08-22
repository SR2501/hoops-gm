# Published auction values (seed AAV)

## What this adapter is for

Seed auction values are **market evidence, not a valuation input** (ADR-008,
`plan.md` line 305). The job is not to source a better AAV. It is to source the
market's AAV well enough that a disagreement with it is defensible, player by
player, at speed, with the clock running.

That inverts the usual priority. Coverage and freshness matter less than being
able to answer *"the market says $28 and we say $34 — on what basis?"* with the
source, its date, its scoring basis, its budget basis, and what it was derived
from. Provenance is the product here, not the hygiene around it.

## Boundary

Every source is **manually downloaded**, following the shape of
[basketball-monster-projections.md](basketball-monster-projections.md). The
adapter never logs in, calls a network endpoint, discovers a local file, or
reads a default path. `import_auction_value_csv` receives explicit bytes. The
CLI reads exactly the path it is given.

This sidesteps every terms-of-service clause found on the four publishers
surveyed: we crawl nothing and redistribute nothing. The ToS exposure this
project worries about is the **write path to Fantrax**, which this adapter does
not touch at all.

## Why `header_contract_verified` is `False` everywhere, honestly

The projection adapter pins exact headers and refuses an unverified profile
outright. Copying that here would refuse every source, and it would be a
misplaced check rather than a strict one.

**No NBA auction-value publisher offers a machine-readable export.** Every one
renders an HTML table that an operator copies out. The header spelling in the
CSV therefore describes *our clipboard*, not the source's contract — pinning it
would pin the transcription step and call the result a verified upstream. So
header matching is alias-based and case-insensitive, `header_contract_verified`
is `False` for all four profiles, and the import gate sits where the real risk
is instead: **basis and derivation**, both mandatory and non-defaultable.

This is a deliberate departure from the projections precedent. It is recorded in
`profiles.py`'s module docstring as well, so the next reader meets it wherever
they arrive.

## Market publisher ids do not enter the identity layer

**Decision, not an omission.** Yahoo and FantraxHQ are not added to `ExternalSource`,
and no `PlayerExternalId` row is written for them. Players are resolved by the
existing name resolver against the NBA crosswalk and stored as `player_id`; a
publisher's own id, where one appears in an export, is kept only in
`published_text`-adjacent import metadata.

The reason is a layering one. `PlayerExternalId` is the **identity** layer — it
answers "who is this person, across sources that independently identify people."
`ExternalSource` is that layer's enum. A market publisher does not identify players
in any sense we depend on; it publishes a price against a name. Adding Yahoo and
FantraxHQ to `ExternalSource` would put non-projection publishers into an
identity-layer enum, **the same shape as putting seeded AAV into `projection_sources`
would have been** — the mistake this unit's boundary ruling avoided, one layer down.

The player crosswalk is `data-engineer`'s scope, so this is the lane's decision to
make; it is written here so the next lane wanting Yahoo ids finds an argument rather
than an absence. **If that lane has a real identity need** — a Yahoo id that resolves
players our name resolver cannot — that is a genuine reason to revisit, and it should
be argued on identity grounds, not on "we already import Yahoo data."

**What the decision costs, stated precisely.** A row whose name the resolver cannot
match is **not written to `published_auction_values`**; it is counted in
`AuctionValueImport.unmatched_count`, and its verbatim name and refusal reason are
written to a `<stem>-unresolved.csv` report the CLI emits at import time under
`--report-dir` (gitignored `data/` by default, and written only when there is at
least one unresolved row). So the *name* survives the import as a file, and the
*database* keeps only a count. That is a deliberate line — this unit stores market
evidence about identified players, and a price attached to a name we cannot resolve
is not yet evidence about a player — but it does mean **the durable record of a
dropped priced player is a number, and the report is gitignored.** Anyone widening
this should treat that as the first thing to change, and should not discover it by
finding a total that does not add up.

## The row grain, and why

`(source, player, as-of date, value kind)`. One row answers "what did source X
say about player Y as of date Z", which is the question a draft-room argument
actually asks. An aggregate cannot be defended per-player, and per-player is
where the whole edge lives.

Each row keeps the **verbatim published text** beside the parsed number
(`published_text`), so a parse can be argued with rather than trusted.

### `value_kind` is per row, not per source

Yahoo publishes a *projected* value and an *observed* average cost **in the same
table**. Deriving the kind from the source name would be wrong by construction,
and anything pulling that table into one "value" column has silently mixed model
output with market observation — the two things this unit exists to keep apart.
`AuctionValueKind` is therefore a column on the value row, and a profile mapping
one header to two kinds is refused.

## Basis is mandatory, conversion is deferred

A $200 budget and a $260 budget produce different dollars for the same player,
and both look like money. Five basis fields are recorded, each paired with a
`*_basis_stated` flag and evidence:

| Field | What it settles |
|---|---|
| `basis_budget_dollars` | Which pool the dollars came out of |
| `basis_team_count` | How many ways that pool was split |
| `basis_roster_slots` | How many players each team had to buy |
| `basis_scoring_type` | Points vs. categories |
| `basis_category_count` | **8-cat and 9-cat are both `h2h_categories`** and are not comparable |

`basis_category_count` exists because `ScoringType` cannot express category
*count*. This is live, not hypothetical: FantraxHQ publishes 8-cat and the
owner's league is 9-cat.

Each field records whether it was **stated by the source** or **inferred by us**.
An inferred basis and a stated basis are different claims and only one is
evidence. **Converting between bases is a Model-gate act** — proportional
scaling and surplus-above-reserve scaling produce materially different dollars —
and belongs to `auction-values`/`quant`, not here. This adapter's half of R39 is
disclosure; the conversion half is not its to make.

## Circularity is a refusal, not a warning

Published AAV is largely produced by, and echoed between, a small number of
sources, several derived from projections **this repository already imports**.
A blend of four sources that are three copies of one is worse than one source
honestly labelled, because it looks like agreement.

`hoops_gm.market.independence` refuses to treat a source as **independent
evidence** unless its projection lineage is *established* and *disjoint* from
our own imported projection sources. It is not a refusal to import, and not a
refusal to display: a source can be present, labelled, and inadmissible as a
benchmark at the same time, and that is the honest state.

Note the shape of that rule, because the first version got it wrong. It refused
when lineage *intersected*, which means a source with **no recorded lineage**
was cleared — the overlap test examined an empty set, found no intersection,
and reported independence about a source nothing was known of. Two routes
demonstrated it: `manual` was reported admissible and the CLI exited 0, and
deleting a refused source's lineage rows flipped a live circularity refusal to
admissible, so the refusal depended on the very rows that recorded the problem.
There are therefore **three** lineage verdicts, not two:

| Lineage state | Verdict | Finding |
|---|---|---|
| Overlaps ours | refused | `circular_lineage` |
| Not recorded at all | refused | `lineage_unestablished` |
| Established and disjoint | admissible | `derivation_unestablished` as a caveat if the *method* is unknown |

A source believed to observe real auctions rather than derive from projections
still records an input row — with no projection source — so "established as
deriving from nothing of ours" stays distinguishable from "nobody looked". That
distinction is the whole point of this page, and the guard now enforces it
rather than assuming it.

The refusal message says so explicitly, including the line **"THIS IS THE GUARD
WORKING, NOT A DATA ERROR"** — a refusal whose reason is unclear is the one that
gets loosened.

Note it fires on **imports**, not registrations: `imported_projection_sources()`
asks which sources have at least one projection import, because a source we have
registered but never imported cannot have contaminated anything.

### The finding this guard exists for

**Basketball Monster's auction values are a deterministic z-score transform of
the Basketball Monster projections we already import.** Seeding from BBM would
have benchmarked us against our own primary projection input with a dollar sign
on it — every match fake agreement, every divergence measuring the gap between
two valuation formulas rather than a difference of opinion about a player. And
it was the most tempting source, because we have paid for it and verified its
export.

BBM is registered in the source registry anyway, precisely **so the guard has
something real to refuse** rather than a branch that is green because nothing
ever enters it. The refusal is proved end-to-end against a real BBM projection
import through the ordinary CSV path.

Be precise about how far that goes, though. There is **no `basketball_monster`
auction-value profile**, so no auction-value file can be imported under this
source and no `auction_value_imports` row for it can exist in a real database.
The refusal is reachable at the **source** level — which is where independence
is assessed, so the mechanism is genuinely exercised — but not through the
import path. Hashtag is the case that would arise from an ordinary import, and
even that is not reachable today: `import_projection_csv` refuses an unverified
projection profile and only Basketball Monster is verified, so Hashtag
projections cannot be imported at all. That path refuses Hashtag one step
earlier. See the `hashtag-projection-profile-verification` backlog item, which
blocks `aav-blending` for exactly this reason.

### Shared method is a separate failure from copying

Hashtag, BBM, RotoWire and FantraxHQ all run the same z-score →
value-above-replacement → budget-distribution arithmetic over **independently
generated** projections. Their correlation is therefore strong evidence that they
do the same maths and weak evidence that they agree about players.

That is a different failure from one source copying another, and it would be
invisible if we recorded only "derived from projections". `derivation_method`
and the `auction_value_source_inputs` rows are kept as **two separate fields**
for this reason, even where it looks redundant.

## Sources

| Source | Role | Derivation | Established? |
|---|---|---|---|
| Hashtag Basketball | **Primary** | z-score → VAR → budget distribution over own projections | Method published; inputs own projections |
| Yahoo | Observed series | Actual average cost across Yahoo auctions | Method stated; **window and league-size mix unestablished** |
| FantraxHQ | Cross-check | Same family of arithmetic; own projections | Method inferred; **budget unestablished** |
| Basketball Monster | Registered, **inadmissible** | Deterministic transform of BBM projections we import | Established — and that is the problem |
| Manual | Operator entry | Whatever the operator declares | Per import |

**Hashtag is primary for one deciding reason: it is configurable.** We can
generate at our own 9-cat basis rather than converting to it, which *removes*
the normalisation problem for that source instead of solving it.

Yahoo is second because it is the one **observed** series available — a record
of what people actually paid rather than what a model says they should. Its
window and league-size mix are recorded as `unestablished`, not left blank.

### FantraxHQ: the inherited `$200` inference, falsified

The FantraxHQ page states values are *"optimized for 8-category leagues with 156
rostered players"* and **prints no budget**. The obvious inference is 12 teams ×
$200. It does not survive the published pool:

- 194 rows, of which exactly **156** are non-zero — consistent with 12 × 13.
- The non-zero values sum to **$2,655**.
- A 12 × $200 pool is **$2,400**. The published pool is **10.6% above it**.
- Rounding noise over 156 whole-dollar values is ≈ √156 × 0.289 ≈ **3.6**. The
  gap is roughly **70σ**.

So the budget is recorded as `UNESTABLISHED`, not as "inferred $200". The team
and slot counts survive as inferences and are flagged as inferred. The
arithmetic is re-derived from the transcribed counts in the test suite rather
than restated as a sentence, so the verdict is checkable rather than quoted.

## Fixtures and the contract test

Fixtures live in `backend/tests/fixtures/auction_values/`. Each has a
`.metadata.json` recording three things separately: **what is verified**, **what
is synthetic**, and **what could not be established**. An unexamined blank and an
investigated "unknown" are different claims and must not be stored the same way.

The suite asserts the presence it expects before iterating: `REQUIRED_FIXTURES`
is checked non-empty and each file checked present and non-empty before any test
reads one, so a check that iterates cannot pass by iterating over nothing.

**The fixture-deletion check was driven, not assumed.** Deleting each of the four
fixtures in turn takes the suite red; so does emptying one, and so does
truncating one to its header. A test can be accurate and non-independent, and
the only way to know which is to remove the thing it claims to depend on.

## Drift and failure behaviour

There is no remote request to throttle or retry — the input is bytes handed in.

Rejected without a write: an unknown or duplicate value column, a value column
mapped to two kinds, a missing player name, an unparseable dollar figure, a
negative value, a figure above `$1000` (a mis-mapped-column guard, **not** a
budget claim), a basis field asserted as stated with no evidence, and any basis
field left unestablished when the import is being used as a benchmark.

Unresolved players are **counted and not imported** — fail-closed. The importer
writes nothing to the identity crosswalk, because `PlayerExternalId.source` is
an `ExternalSource` and Yahoo and FantraxHQ are not in that vocabulary; inventing
entries there would corrupt a table this adapter does not own.

Exit codes: `0` success, `2` usage, `3` parse/contract, `4` database, and **`5`
imported but not usable as an independent benchmark** — a distinct code because
"we stored it" and "you may measure yourself against it" are different outcomes
and collapsing them is the defect this whole unit is designed against.

## Live smoke

There is one, and it is opt-in in the same way the Basketball Monster
projection smoke is. No publisher can be polled — there is nothing
machine-readable to poll, and crawling one is the ToS exposure this boundary
avoids — but the *shape of the table the operator copies out* can drift, and
that drift is invisible to a contract test pinned to a months-old fixture.

```powershell
$env:HOOPS_GM_AAV_CSV = '<freshly-downloaded-export>'
$env:HOOPS_GM_AAV_PROFILE = 'hashtag-auction-values'
pytest -m live_smoke -k PublishedAuctionValue
```

Absent either variable it skips. **It was driven rather than assumed** - but be
exact about against what. **No real published export has ever been run through
it, because nobody here has one.** It passes on a *realistically shaped synthetic*
export, and goes red on a renamed value column, on a
header-only file, and on a negative dollar figure — at three *different*
assertions, so each one does distinct work rather than one catch-all absorbing
every case. Driving the negative case also showed the parser rejects it fatally
first, so a further non-negative assertion could never have been reached; it is
deliberately absent rather than present and unenterable.
