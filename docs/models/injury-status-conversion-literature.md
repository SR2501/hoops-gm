# Injury-status conversion: prior work, and what the archive will actually give us

**Owner:** `data-engineer`, with `quant` concerns
**Status:** findings only. **No model is fitted and no conversion rate is emitted here.**
**Probe run:** 2026-08-21, 30 live requests against `ak-static.cms.nba.com`

This is not a model card and it does not claim the Model gate. It answers the
question that has to be settled before a multi-season sweep is worth starting:
**has anyone already measured this, and will the archive give us enough to
measure it ourselves?** The protocol the eventual fit must follow is
[`injury-status-conversion-preregistration.md`](injury-status-conversion-preregistration.md),
which is frozen and is not modified by anything here.

---

## 1. The finding, in one paragraph

**Nobody has published this properly.** There is no peer-reviewed measurement of
NBA injury-report label → play conversion, and the widely repeated rates
(`DOUBTFUL` ~25%, `QUESTIONABLE` ~50%, `PROBABLE` 75–90%) have no traceable
primary source. So our own fit is worth running. **The archive will support it**:
reports are reachable back to at least the 2019-20 season, and the three seasons
this project's parser can read — 2023-24, 2024-25, 2025-26 — are exactly the
three the sweep wants. Every status, including the scarce `PROBABLE` and
`DOUBTFUL`, appears in all three. The binding constraint is not the archive and
is not the injury reports; **it is the participation ledger the cohort must join
against**, which is roughly 2.7× the requests and 4× the wall time.

---

## 2. Prior work

### How these citations were checked

Every entry below was **retrieved**, not recalled. A citation is a claim about an
artefact outside this repository, so no gate in this project looks at it: a
plausible-but-wrong arXiv identifier is well-formed, correctly formatted, names a
real venue, and simply is not a thing — the same failure shape as `gameEt`
carrying a `Z` suffix while not being UTC. Form validates; referent does not.

So each was resolved through a machine-readable registry (Crossref for DOIs, the
arXiv API, the PyPI JSON API) or fetched directly, on **2026-08-21**, and the
**title the registry returned** is recorded beside the title claimed.

| # | Claimed | Resolved via | Title returned | Match |
|---|---|---|---|---|
| 1 | arXiv 2603.26935, *The Load Management Paradox: Correcting the Healthy-Worker Survivor Effect in NBA Injury Modeling* (2026) | arXiv API, `id_list=2603.26935` | *The Load Management Paradox: Correcting the Healthy-Worker Survivor Effect in NBA Injury Modeling*, published 2026-03-27, `v1` | exact |
| 2 | *Sports Analytics for Evaluating Injury Impact on NBA Performance*, Information, 2025 | Crossref, `10.3390/info16080699` | *Sports Analytics for Evaluating Injury Impact on NBA Performance*, Information 16(8) 699, issued 2025-08-17 | exact |
| 3 | *Injury Patterns and Impact on Performance in the NBA League Using Sports Analytics*, Computation, 2024 | Crossref, `10.3390/computation12020036` | *Injury Patterns and Impact on Performance in the NBA League Using Sports Analytics*, Computation 12(2) 36, issued 2024-02-16 | exact |
| 4 | `mxufc29/nbainjuries` | PyPI JSON API + GitHub README | `nbainjuries` 1.1.1, *"Library for accessing and extracting NBA player injury data from official team injury reports."* | exact |
| 5 | `nba-injury-report` (PyPI) | PyPI JSON API | `nba-injury-report` 0.1.0, *"Fetch and parse official NBA injury reports"* | exact |
| 6 | MIT Sloan research-paper archive | direct fetch | see correction below | **corrected** |

**One citation handed to me was wrong, and this is why the condition exists.**
The search summary that surfaced Sloan gave
`https://www.sloansportsconference.com/research-papers`. **It returns HTTP 404.**
The working pages are
[`/research-paper-competition`](https://www.sloansportsconference.com/research-paper-competition)
(*"Research Paper Competition | MIT Sloan Sports Analytics Conference"*) and
[`/past-conferences`](https://www.sloansportsconference.com/past-conferences)
(*"Past Conferences | MIT Sloan Sports Analytics Conference"*), both HTTP 200.
Had I copied the summary through, this document would have carried a dead link
to the single most important venue it claims to have searched — and the claim
"we searched Sloan" would have been unfalsifiable in the worst way: pointing at
nothing, while looking like provenance.

*(One source resolves but could not be title-verified:
`espn.com/nba/story/_/id/47361909/...` returns HTTP 202 with no extractable
title, which is bot mitigation rather than absence. It is cited below only for a
policy date that is independently corroborated inside this repository, and never
as sole authority.)*

### What the literature contains

**Injury *hazard* modelling is a real and active field.** Entries 2 and 3 pair
injury events with player-game performance across many seasons, and study
recovery and post-injury production. Neither examines what a report *designation*
is worth.

**Entry 1 is the genuinely useful one, and not for its subject.** It shows that
NBA injury models systematically produce *inverted* effects — heavy recent
workload appearing protective — because the risk set is progressively enriched
for players healthy enough to keep playing. That is the healthy-worker survivor
effect, and it is a selection-on-the-outcome bias. It is the reason §4 of this
document rejects a minutes floor.

It is also worth reading its calibration section beside our own Model gate. It
reports predictions clustered near zero against observed event rates of 2–3%
across deciles, and says plainly that its models are informative about *relative*
hazard rather than absolute probability. That is independent support, from a
source with no stake in this project, for the gate's insistence that calibration
is the primary metric and accuracy alone can mislead.

### What the literature does not contain, stated so it can be disproved cheaply

> **No study — peer-reviewed or otherwise — publishes an NBA injury-report
> label → play conversion rate with a stated sample size, season, and split.**

Searched: MIT Sloan proceedings and paper archive; arXiv; the Journal of
Quantitative Analysis in Sports and Journal of Sports Analytics; and the serious
betting- and fantasy-analytics writing where the numbers actually circulate.
Every trail for the familiar rates ends at a handicapping or fantasy page
restating them with no N, no season and no method.

**Disprove this by producing one citation with a sample size and a season.** I
could not.

### The folklore rates, and what may be done with them

`DOUBTFUL` ~25%, `QUESTIONABLE` ~50%, `PROBABLE` 75–90%.

**No resolvable primary source.** These are recorded here as a *comparison
target* and nothing else. Under **ADR-008** aggregates are terminal: an external
number may be compared against and may never be blended in, at any weight. So
these three figures must never enter a cohort manifest, a fitting input, or any
artifact a join can reach. They belong in the eventual model card's comparison
section, labelled unsourced, and nowhere else.

There is a second reason for suspicion beyond their missing provenance. **Our own
invalidated v1 study contradicts their ordering** — held-out `PROBABLE` came out
above `AVAILABLE`, reversed — on real data. That is a defect, a real effect, or
noise from a tiny sample, and nobody knows which. Treat the published rates as a
hypothesis to falsify.

### Existing tooling, and why it does not save us a sweep

Entries 4 and 5 parse the same PDFs from the same CDN. They fetch what we fetch,
so adopting one would trade our recorded fixtures and contract tests for a third
party's, add a Java runtime dependency (`tabula-py`), and save no requests. Our
adapter already exists and already passes the Adapter gate. The one thing their
documentation gave us was a **claim** about archive depth — "available since the
2021-2022 NBA season" — which §3 tested rather than adopted.

---

## 3. The probe: what the archive actually holds

30 live requests, 2026-08-21. Evidence, including the SHA-256 of every response,
is committed at
[`nba-injury-report-archive-reach-probe.json`](../adapters/nba-injury-report-archive-reach-probe.json).
Contract test: `backend/tests/test_injury_report_archive_reach.py`.

### Finding 1 — the vocabulary claim in the secondary sources is false

Multiple secondary sources state the NBA vocabulary is Out / Doubtful /
Questionable / Available **with no `PROBABLE` at all**, unchanged from 2022-23
through 2025-26.

This mattered enormously. If it were true, backfilling three seasons would clear
the activation floor for `doubtful` and leave the model unactivatable on
`probable` instead — a multi-hour sweep spent to remain blocked on a different
status than the one we set out to fix.

**It is false.** Driven, from live bytes:

| Season | Reports probed | `probable` | `doubtful` |
|---|---:|---|---|
| 2023-24 | 4 | 2, 7, 3, 0 | 3, 2, 1, 0 |
| 2024-25 | 3 | 13, 8, 10 | 5, 4, 4 |
| 2025-26 | 1 | 5 | — (cohort manifest records 21 across four weeks) |

Both scarce statuses are present throughout. `DOUBTFUL` does not appear on every
single report, which is expected at these rates and is why the contract test
asserts across the union of a season's probed reports rather than from one
capture.

### Finding 2 — the archive reaches back further than the parser does

The boundary is **not** where the third-party claim put it, and it is not an
archive-depth boundary at all.

| Season | Report fetches | Parses |
|---|---|---|
| 2023-24 → 2025-26 | yes | **yes** |
| 2022-23 and earlier, back to 2019-20 | **yes** | no |

Reports from 2019-20, 2020-21, 2021-22 and 2022-23 fetch cleanly — HTTP 200,
valid PDF magic, five pages of genuine injury data with real players, real
matchups and real designations. **They are complete reports, not placeholders.**
What changed at the 2023-24 season boundary is the *layout*: pre-2023 reports
print words separated by spaces, later ones do not, and this parser's
column-bounds detection does not survive the difference.

The boundary is bracketed between **2023-04-05** (refused) and **2023-10-25**
(parsed), i.e. it falls in the 2023 offseason.

**This finding is only visible because the probe looked inside the files.** Every
transport-level signal said success. Had the probe stopped at "the fetch worked"
it would have reported four more usable seasons; had it stopped at "the parse
failed" it would have reported the archive as reaching back only to 2023-24. Both
would have been wrong, in opposite directions. *Validation of form cannot catch
errors of meaning* — the house rule earned its place here.

### Finding 3 — the dangerous case is the one that must fail

A pre-2023 report is the worst shape a bad input can take: it fetches cleanly, so
nothing in transport notices, and only the parser stands between that layout and
a cohort full of plausible nonsense. The refusal is therefore load-bearing
behaviour, not a limitation, and it is pinned by a committed fixture
(`nba_injury_report_2023-01-11_0530pm_unsupported_layout.pdf`) with a test
asserting that the fixture **is a complete report** — because a parser refusing a
stub would prove nothing.

Four mutation checks were run against these guards, each reproducing the failure
its docstring names, with green asserted before mutating and the mutation
asserted to have applied. All four were caught; no skips.

### Consequence for scope

**Three seasons is available and three seasons is the plan.** A fourth would
require parser work for the pre-2023 layout — a real, bounded piece of work, but
not one this unit takes on, and not one the arithmetic in §4 needs.

---

## 4. What the numbers say about how wide to go

Re-derived at this commit from
[`nba-injury-report-cohort-2025-12-08--2026-01-04.json`](../adapters/nba-injury-report-cohort-2025-12-08--2026-01-04.json),
not from prose. Committed cohort: **173 games, 26 game dates**, `doubtful` 21,
`probable` 59.

| Quantity | Value | Derivation |
|---|---:|---|
| `doubtful` per game | 0.1214 | 21 / 173 |
| Full regular season | 1,230 games | 30 × 82 / 2 |
| Scaling factor | 7.11× | 1,230 / 173 |
| Projected whole-season `doubtful` | ~149 | 21 × 7.11 |
| Game dates in a full season | ~170 | schedule shape |
| Holdout share, §4 date rule | 25.3% | (170 − ⌊85⌋ − ⌊42⌋) / 170 |
| **Projected held-out `doubtful`** | **~38 canonical, ~37 direct** | × 98.5% join rate |
| Activation floor, §8 condition 6 | 30 | frozen protocol |

**One season clears the floor by ~23%, which is not a margin.** Three reasons:

- The freeze already warns its own multiplier is probably an underestimate.
- Our four-week sample is **December**. October carries few designations and
  April converts marginal cases to `out` via shutdowns, so December is plausibly
  *peak* `doubtful` density and the full-season figure is more likely below 149
  than above it.
- The estimate assumes a stable status mix across a season, which is the
  assumption the trend analysis exists to test.

Two seasons → ~75 held-out `doubtful`. Three → ~113. **Two is the first safe
stop; three earns the trend analysis.** The owner's three-season goal is
supported by arithmetic, not only by ambition.

**None of this substitutes for the measured count.** The gate is the per-status
direct-outcome count in the declared holdout. These figures are a planning aid
for a spend decision and are not a preregistered threshold.

### The sweep is a box-score ingest with an injury-report attachment

| Work | Requests | Throttle | Wall time |
|---|---:|---|---|
| Injury reports, 2025-26 (mixed era) | ~670 | 2.0 s | ~22 min |
| Injury reports, each legacy season | ~340 | 2.0 s | ~11 min |
| **Reports, 3 seasons** | **~1,350** | | **~45 min** |
| Participation / box scores, per season | ~1,230 | 1.1 s | 23 min floor, 45–90 min real |
| **Participation, 3 seasons** | **~3,690** | | **2–4.5 h** |

This is unremarkable traffic and politeness is not in tension with it. But the
shape is the opposite of what the framing suggests: **participation dominates
report fetching by ~2.7× in requests and ~4× in wall time**, and
`enforce_expected_game_coverage` is fail-closed on every expected game being
ingested, so **there is no partial-season shortcut**. A season is ingested whole
or not at all.

---

## 5. Scope, and the argument for it

### No minutes or games-played floor

The intuition — that whole 15-man rosters are unnecessary — is a *cost*
intuition, and the cost is not in rows. The report lists only designated players,
about 11 per game; three seasons is roughly 40,000 rows. Against that, a floor is
actively harmful:

1. **It filters on a variable downstream of the outcome.** Minutes and games
   played are partly *consequences* of availability. Conditioning on them is the
   selection structure arXiv 2603.26935 exists to correct, so we would be
   introducing at ingest time the exact bias a 2026 paper was written to remove.
2. **It buys nothing where the constraint binds.** Its target is deep-bench `OUT`
   padding, but `out` sits at 1,508 and clears every floor by two orders of
   magnitude. Trimming the one cell that is not scarce does not move `doubtful`
   at 21.
3. **It risks removing exactly what we are short of.** Rotation players are where
   availability uncertainty lives, and the scarce designations concentrate there
   rather than among stars — a star is `out` or he plays. The effect of a floor
   on the binding cell is unknown until the data exists, so the cut cannot be
   justified before the sweep it is meant to shrink.
4. **A reversible alternative loses nothing.** Ingest every listed player, carry
   a per-observation role/minutes covariate, and let `quant` report per-status
   rates stratified by role band as a pre-declared sensitivity. That converts an
   irreversible ingest-time decision into a reversible analysis-time one.

### Regular season only

Postseason availability behaviour is categorically different — short series,
elimination games, a playoff `QUESTIONABLE` is not a January `QUESTIONABLE` — the
population is 16 teams, and this league is regular-season H2H. Cutting on the
dimension the *decision* lives on is principled; cutting on a dimension
correlated with the outcome is not.

### The era boundary is a mandatory stratum, not an optional one

The 2025-12-22 cadence change is a regime discontinuity that a pooled fit would
launder into the label. Before it, the candidate strategy reaches at best an
evening-before or 13:00 ET report; after it, four tip-off-anchored candidates
reach within 15 minutes of tip. **Legacy-era canonical observations therefore
carry systematically longer lead times**, and the frozen protocol's own lead-time
bands (≤60 / 61–180 / 181–540 / >540 minutes) are exactly the axis this moves
along. A rate fitted across both eras conflates what the label means with how
close to tip-off it was read.

So per-season and per-era rates must be reported **before** any pooled rate, and
a pooled rate must not be published if the strata disagree. This makes the trend
analysis mandatory rather than a bonus.

---

## 6. Sequence

Units are numbered contiguously here. **This is a renumbering** from the plan the
coordinator approved, where the probe's removal from a standalone slot left a gap
and two dangling references to a "Unit 2" that no longer existed. The
coordinator's binding go/no-go condition attached to "Unit 4, the first season
sweep"; that is **Unit 3** below, unchanged in substance.

| Unit | Work | Network | Gate |
|---|---|---|---|
| **1** | This document + the archive-reach probe | 30 requests, done | Adapter + Code |
| **2** | Manifest disclosure contract test: outcome-keyed field allow-list, `joined_direct_outcomes`, per-status direct-outcome counts by game date, exclusion classes by status | none | Code |
| **3** | 2025-26 full regular season: participation, then reports, then manifest | ~1,900 | Adapter |
| **4** | 2024-25 | ~1,570 | Adapter |
| **5** | 2023-24 | ~1,570 | Adapter |
| **6** | Per-season and per-era trend report, handed to `quant` | none | Code |

**Unit 2 must land before any widened manifest is generated** — it is the
disclosure surface the frozen protocol's admissibility gate reads.

**The Unit 3 go/no-go is binding and must be measured.** If season one's
held-out `doubtful` comes in under 30, stop and report; do not proceed to season
two on the multiplier's authority. Given §4, that call is live.

**This lane stops at the observation layer.** The fit, the calibration table and
the model card are `quant`'s work under the frozen protocol. Nothing in this lane
emits a conversion rate.

---

## 7. What this cannot see, and what remains unverified

Separated by whether the belief was **driven** — established by running something
— or **reasoned**.

### Driven

- **Archive reach back to 2019-20.** Fetched; five real reports inspected.
- **The parser boundary at the 2023-24 season start.** Bracketed by a refused
  2023-04-05 and a parsed 2023-10-25.
- **`PROBABLE` and `DOUBTFUL` present in 2023-24 and 2024-25.** Counted from
  seven parsed reports.
- **The pre-2023 files are complete reports, not placeholders.** Text extracted
  and read.
- **The Sloan URL in the search summary is dead.** HTTP 404; working paths
  substituted.
- **All five other citations resolve with exact-matching titles.** Crossref,
  arXiv and PyPI APIs, 2026-08-21.
- **The four guards catch what their docstrings claim.** Mutation harness, green
  before, mutation applied, red, reverted, green.

### Reasoned, not driven — treat accordingly

- **The full-season `doubtful` projection (~149).** Scaled from one December
  window. The seasonality argument for it being an *over*estimate is reasoning,
  not measurement, and it is the number the Unit 3 go/no-go exists to replace.
- **Participation wall-time estimates.** Derived from the client's 1.1 s interval
  and game counts. No season ingest has been run; retries, 429s and parse
  failures are not modelled.
- **That the PDF table layout is stable *within* each of the three seasons.** Four
  reports were probed for 2023-24 and three for 2024-25, spread across each
  season — not exhaustive. A mid-season layout change inside a supported season
  would not have been caught.
- **That no relevant Sloan paper exists.** This is absence of evidence from four
  searches. Sloan proceedings are not uniformly indexed and I did not enumerate
  them year by year. The claim I am confident in is narrower: no such paper
  surfaced through any search route tried.
- **That the era-boundary lead-time argument holds quantitatively.** The
  mechanism is established from the documented candidate strategies; the size of
  the resulting lead-time shift is not measured and will not be until Unit 3.
- **That 40,000 rows is "nothing" for three seasons.** Extrapolated from the
  committed cohort's ~11 designated players per game; not measured at season
  scale.

### Could not verify at all

- **CI on this head.** Not pushed when written.
- **Whether the pre-2023 layout is recoverable.** The parser refuses it; no
  attempt was made to read it, so the cost of a fourth season is unknown rather
  than high.
- **The ESPN policy article's contents.** HTTP 202 with no extractable title.
  Cited only for a date corroborated independently inside this repository.
- **Whether the ~99.18% v1 overlap bound or any other v1-derived figure is
  correct.** Those live on a local-only branch, per the frozen protocol's own
  disclosure. Nothing in this document depends on them.

---

No model was fitted. No conversion rate was emitted. No cohort was regenerated.
No number a decision rests on was published. No owner-only decision was taken.
