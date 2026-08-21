# Injury-status conversion: prior work, and what the archive will actually give us

**Owner:** `data-engineer`, with `quant` concerns
**Status:** findings only. **No model is fitted and no conversion rate is emitted here.**
**Probe run:** 2026-08-21, **30 live requests** against `ak-static.cms.nba.com` —
four passes, of which only the last 13 are recorded as observations in the
evidence artifact. See its `request_accounting` block; an earlier version
published `requests_issued: 13` and was read as the whole spend.

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
three the sweep wants. **`PROBABLE` appears in all three**, which is the claim
the plan depended on; `DOUBTFUL` is established by probe for 2023-24 and 2024-25
and by the committed cohort manifest for 2025-26 (see §3). The binding constraint
is not the archive and is not the injury reports; **it is the participation
ledger the cohort must join against**, which is **3.7× the requests and 2.0× the
wall time** for one season.

**Read §4's projections with the caveat in §4.1 attached.** They scale a single
blended per-game `doubtful` rate across seasons, and §5 argues that the two
reporting-cadence eras must never be pooled. Those two things are in tension, the
tension is not resolvable from anything committed, and it bears directly on the
go/no-go this document recommends.

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
effect, and it is a selection-on-the-outcome bias. It is the reason §5 of this
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

**It is false.** Driven, from live bytes. Reports are listed in date order and
the two count columns are aligned to that order:

| Season | Reports probed (date order) | `probable` | `doubtful` |
|---|---:|---|---|
| 2023-24 | 4 — 10-25, 11-15, 01-10, 03-15 | 2, 7, 3, 0 | **0, 2, 3, 1** |
| 2024-25 | 3 — 11-15, 01-15, 03-15 | 8, 13, 10 | 4, 5, 4 |
| 2025-26 | 1 — 11-01 | 5 | **0** — see below |

*(The 2023-24 `doubtful` row was previously printed as `3, 2, 1, 0` — the right
multiset in the wrong order, which claimed the opening-night report carried three
`doubtful` when it carried none. Caught in review, re-derived from the evidence
file, and the reason the column order is now stated explicitly in the header.)*

**`PROBABLE` is present in all three seasons**, which is the claim the plan
depended on and the claim the contract test asserts, from the PDF bytes.

**`DOUBTFUL` is present in 2023-24 and 2024-25, and the single 2025-26 report
this probe captured contains none.** That is a fact about one capture rather than
about the season — `DOUBTFUL` at these rates does not appear on every report —
and the 2025-26 evidence for it is the committed cohort manifest's **21**
observations across four weeks, which is a different artifact under a different
gate. An earlier version of this section claimed both statuses "present
throughout" and said a contract test asserted it across a union of reports; the
test asserted only `PROBABLE`, and a three-season `DOUBTFUL` assertion would have
failed. The tests now assert `DOUBTFUL` for the two seasons that support it and
pin 2025-26's absence explicitly so it cannot be quietly widened back.

### Finding 2 — the archive reaches back further than the parser does

The boundary is **not** where the third-party claim put it, and it is not an
archive-depth boundary at all.

| Season | Report fetches | Parses |
|---|---|---|
| 2023-24 → 2025-26 | yes | **yes** |
| 2022-23 and earlier, back to 2019-20 | **yes** | no |

Reports from 2019-20, 2020-21, 2021-22 and 2022-23 fetch cleanly — HTTP 200,
valid PDF magic, and a response size consistent with a real report. What changed
at the 2023-24 season boundary is the *layout*: pre-2023 reports print words
separated by spaces, later ones do not, and this parser's column-bounds detection
does not survive the difference.

**How far "they are complete reports, not placeholders" actually reaches, which
is less far than this document first claimed.** Only **one** of those five
captures — `2023-01-11`, the committed fixture — has its bytes in the repository,
and a test asserts it is a genuine five-page report with real designations. The
other four were inspected during the probe and are not committed, and the
evidence artifact records only their URL, size, SHA-256 and parse error: **no
page count, no entry count, no text excerpt.** So for `2023-04-05`, `2022-01-12`,
`2021-02-10` and `2020-01-15` the completeness claim is not checkable from this
repository by anyone, which is the same failure this document indicts in the dead
Sloan URL at §2 — *pointing at nothing, while looking like provenance*. What is
checkable for all five is that they fetched, that they are PDFs of a plausible
size, and that this parser refuses them.

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

Mutation checks were run against these guards, and **independent review found two
of the original four were weak evidence** — one reddened on a neighbouring
condition rather than the property its docstring named, and one reddened all
three parametrisations at once, so it established "an empty counter fails" rather
than per-season discrimination. Both have been replaced, and the reviewers' own
successful attacks were re-run against the corrected tests and now fail. The
`DOUBTFUL` assertion is attributed by a mutation that stops the parser producing
`DOUBTFUL` at all, which reddens exactly the two `DOUBTFUL` tests with their own
assertion message and nothing else.

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
| Game dates in a full season | **164** | measured, `LeagueGameFinder` preflight |
| Holdout share, §4 date rule | 25.0% | (164 − ⌊82⌋ − ⌊41⌋) / 164 |
| **Projected held-out `doubtful`** | **~37 canonical, ~37 direct** | × 98.5% join rate |
| Activation floor, §8 condition 6 | 30 | frozen protocol |

*(An earlier version used ~170 game dates "from schedule shape" while the same
document's preflight had measured **164**. The conclusion is unchanged — 25.0%
against 25.3%, ~37 either way — but the one number the live preflight bought was
contradicted forty lines away from where it was published.)*

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

### 4.1 This projection contradicts §5, and the bias runs the wrong way for the go/no-go

Raised by `quant` in review, and it is the most consequential finding against
this document.

The table above scales **one blended per-game `doubtful` rate** uniformly across
seasons. §5 argues the 2025-12-22 cadence change is a **mandatory stratum**
because the canonical observation moves from a 13:00 ET day-of report to within
15 minutes of tip. **Both cannot stand.** The canonical unit is the *latest
pre-tip-off observation*, so how close to tip it sits determines how many players
are still labelled `doubtful` rather than resolved to `out` or `available`.
Shorter lead time ⇒ more resolution ⇒ **fewer canonical `doubtful`**.

The era weights make the direction concrete:

| Population | Legacy-cadence share | Effect on `doubtful` density |
|---|---:|---|
| Committed cohort, 2025-12-08..2026-01-04 | ~50% of days | the measured 0.1214/game |
| Full 2025-26, 2025-10-21..2026-04-12 | ~36% of days | **lower** than 0.1214 |
| 2024-25 and 2023-24 | **100%** | **higher** than 0.1214 |

So the one-season projection is an **over**estimate — the same direction as the
seasonality argument above but for a larger and better-evidenced reason — while
the two- and three-season figures (~75, ~113) are **under**estimates, because
those seasons are entirely legacy-cadence.

**The practical consequence is adverse exactly where it matters.** The Unit 3
go/no-go is measured on 2025-26, which is the single season where this bias is
largest and pushes the projection *up*. A ~23% margin that this document already
calls "not a margin" is being applied to the season most likely to fall short of
it.

**This cannot be sized from anything committed.** The cohort manifest publishes
whole-cohort `status_counts` only, with no by-date or by-era split, so the
era-conditional `doubtful` rate is not computable today. Unit 2's per-status
by-game-date denominators would make it computable — and Unit 2 is currently
scheduled *after* the sweep decision it would inform. That ordering is worth
revisiting.

**A second unit error in the same figures.** The two- and three-season totals are
in **canonical** observations while the floor of 30 is in **direct outcomes**.
Direct outcomes are a subset, so the comparison is optimistic by the exclusion
rate (~1.5% on the committed cohort, but not guaranteed stable across seasons).
The one-season row applies the 98.5% join rate and is consistent; the multi-season
sentence does not.

### The sweep is a box-score ingest with an injury-report attachment

**Corrected 2026-08-21, after the coordinator promoted this work and asked for
exact figures.** The first version of this table said ~1,230 participation
requests per season and a 23-minute floor. **It counted one request per game;
the ingest makes two** — `BoxScoreTraditionalV3` for who dressed and
`BoxScoreSummaryV3` for the inactive list and the tip-off instant — because only
the per-game endpoints carry DNP comments and inactive lists. The figures below
are re-derived from a read-only `LeagueGameFinder` preflight against the real
2025-26 season, not scaled from the cohort.

| Work | Requests | Throttle | Wall time |
|---|---:|---|---|
| Injury reports, 2025-26 (mixed era) | ~670 | 2.0 s | ~22 min |
| Injury reports, each legacy season | ~340 | 2.0 s | ~11 min |
| **Reports, 3 seasons** | **~1,350** | | **~45 min** |
| Participation, 2025-26 (**measured**: 1,230 games, 164 game dates) | **2,462** | 1.1 s | **45.1 min floor** |
| **Participation, 3 seasons** | **~7,386** | | **~2.3 h floor** |

So participation dominates report fetching by **3.7× in requests and 2.0× in
wall time for one season**, and **~5.5× / ~3×** across three. The earlier
version of this document said 2.7× and 4×; both were wrong, and the conclusion
they supported is stronger than the numbers that were used to argue it.

**A second correction, and this one loosened a constraint rather than tightening
it.** The earlier version said "there is no partial-season shortcut". That is a
property of the *injury-report* backfill's `enforce_expected_game_coverage`, and
it was applied here to participation, which is a different code path with no
such gate: `backfill_season` takes `--start`, `--end` and `--limit-games` and
filters the participation loop through `_participation_games_in_scope` without
consulting any coverage gate at all.

And the injury-report gate itself is narrower than that phrasing suggests. It is
scoped to the **requested range** — `expected` is filtered by `--start`/`--end`
before comparison — and carries an explicit `allow_missing_games` escape hatch
that a deliberately partial run must name. So the real constraint is *whatever
window you request must be complete within itself*, not *you must ingest whole
seasons*.

**Consequence: participation is chunkable by date range**, with a
`session.commit()` after every game, so a month-sized slice is a legitimate unit
of work rather than a compromise.

### Resume behaviour, and whether a resumed run equals an uninterrupted one

Recorded because the participation ingest was promoted to the critical path and
will run for the better part of an hour on a home machine. All of this is read
from the code, not inferred from the docstrings.

**Resume mechanism.** There is no checkpoint file. Resuming is re-running the
same command. Three properties make that safe:

- `session.commit()` fires after **every game**, so committed work is durable at
  per-game granularity.
- `import_participation` upserts on `(game_id, player_id)` against the rows
  already present, so replaying a game is a no-op rather than a duplicate.
- `COMPLETED_GAME_MAX_AGE` is **3,650 days**, so a completed game's two
  responses are served from the raw store essentially forever.

**Replay is fast, and for a non-obvious reason.** `NbaStatsClient.fetch` checks
the cache *before* `_invoke`, and `limiter.acquire()` lives inside `_invoke`. So
a cache hit pays no throttle at all. A resumed run replays every already-fetched
game at disk speed and only slows to 1.1 s/request when it reaches new work.
Interruption therefore costs re-parsing and re-upserting, not re-fetching.

**Is a resumed run provably equivalent to an uninterrupted one? No.** Three
divergences, in descending order of how much they should worry an operator:

1. **The cache windows are asymmetric.** Per-game endpoints are pinned for 3,650
   days, but `LeagueGameFinder` and `PlayerGameLogs` use `SEASON_MAX_AGE`, which
   is **12 hours**. A run resumed more than 12 hours later re-fetches both, and
   the game list and season logs it then works from are whatever the source says
   at that moment. For a **completed** season — 2025-26 ended 2026-04-12 — the
   schedule is static and the refetch should be identical, but that is an
   empirical claim about a finished season rather than a guarantee the code
   makes. For an in-progress season the two runs would genuinely differ.
2. **A cached bad response is replayed identically.** If a fetch succeeded and
   the *parse* failed, the response is already in the raw store, so resuming
   reproduces the same failure deterministically. That is good for
   reproducibility and bad for recovery: a failure that looks transient is not
   retried by resuming, and only clearing the raw-store entry will re-fetch it.
3. **The failure list does not survive across invocations.** Per-game failures
   are collected into `result.failures` and reported at the end of *that* run.
   An operator who is interrupted twice sees three separate failure lists and no
   union; nothing persists them. For a 45-minute job that is a real gap — the
   run is resumable but its *error record* is not.

None of these is a defect in the participation ingest as scoped. They are the
things worth knowing before starting it, and (3) in particular argues for
capturing stdout to a file rather than trusting the terminal.

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
4. **A reversible alternative loses most of it, and is not free.** Ingest every
   listed player and carry a per-observation role covariate, so the choice of
   whether to condition on it is made at analysis time rather than destroyed at
   ingest time. That is strictly better than filtering — a filter cannot be
   undone, a covariate can be ignored — but `quant` is right that it does not
   escape the problem it was offered against: **a role covariate measured
   contemporaneously is as downstream of availability as a minutes filter is**,
   so conditioning on it reintroduces the same selection, and a covariate
   measured *from the same games* leaks the outcome. If it is used at all it must
   be defined on a prior window (e.g. role as of the preceding season, or a
   rolling window strictly before the game date), and that definition is the
   `quant` deliverable, not this one.

   **And it is not "pre-declared".** An earlier version of this section called it
   a pre-declared sensitivity; the frozen protocol pre-declares no role
   stratification of any kind. Its declared sensitivities are unresolved
   identity, missing participation row, explicit unknown outcome, and the
   lead-time bands. Adding one after the fact is a v3 conversation with `quant`,
   not something this document can assert.

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

**But stratifying by era does not identify what this section implies it does,
and `quant` is right about that.** Era and lead-time band are near-collinear by
construction: legacy candidates top out at a 13:00 ET day-of report, while the
15-minute era adds offsets reaching 15 minutes before tip, so "which era" and
"how long before tip" are close to the same variable. Reporting per-era rates
therefore does **not** separate *the label means something different since the
cadence change* from *a label read 15 minutes before tip is more informative than
one read nine hours before*. It renames the confounding rather than resolving it.

That is not an argument for pooling — pooling is strictly worse, because it hides
the discontinuity instead of displaying it. It is a limit on what a per-era table
may be said to show, and it belongs beside the number when one is eventually
published. Separating the two would need lead-time variation *within* an era,
which the 15-minute era's four offsets do provide and the legacy era's two
candidates largely do not. Whether that is enough is a `quant` question and is
not settled here.

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
| **1b** | **2025-26 participation ingest — promoted to the critical path** | ~2,462, ~45 min floor | Adapter |
| **2** | Manifest disclosure contract test: outcome-keyed field allow-list, `joined_direct_outcomes`, per-status direct-outcome counts by game date, exclusion classes by status | none | Code |
| **3** | 2025-26 injury reports + regenerated manifest | ~670 | Adapter |
| **4** | 2024-25 (participation + reports) | ~2,800 | Adapter |
| **5** | 2023-24 (participation + reports) | ~2,800 | Adapter |
| **6** | Per-season and per-era trend report, handed to `quant` | none | Code |

**Unit 1b is not part of the conversion study, and that is the point.** The
coordinator traced the dependency graph after approving this plan and found that
`availability-model` is blocked by two independent routes — its
`injury-status-conversion` dependency *and* its own need for direct non-play
labels from `player_participation` — so closing only the first would not unblock
it. Everything downstream of `availability-model` (`expected-games`,
`zscore-engine`, `gscore-engine`, `risk-adjusted-valuation`, `auction-values`
and the auction capabilities beyond) waits on those labels regardless of what
this conversion study concludes. The participation ingest is therefore the
spine, and this lane was merely the first thing that would have caused it to
happen.

It is sequenced first, it is **not** low-priority, and it is the one item here
whose cost is wall-clock rather than effort — 45 minutes of throttled fetching
cannot be compressed on the day we discover we need it. The literature review
and the conversion study keep their original low priority.

**The `PROBABLE` question governed the conversion study, not the participation
ingest.** Those were coupled only by living in one plan. A probe result that
killed the three-season sweep would not have touched Unit 1b.

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
- **`PROBABLE` present in all three sweep seasons; `DOUBTFUL` in 2023-24 and
  2024-25.** Counted from seven parsed reports, and asserted in the contract test
  from the PDF bytes rather than from a recorded count. The single 2025-26 probe
  report carries no `DOUBTFUL`; that season's evidence for it is the committed
  cohort manifest's 21 observations.
- **The 2023-01-11 file is a complete report, not a placeholder.** Text
  extracted, read, and pinned by a committed fixture and test. **The other four
  pre-2023 captures are *not* committed**, and the evidence artifact records only
  their URL, size, SHA-256 and parse error — so "complete report" for
  `2023-04-05`, `2022-01-12`, `2021-02-10` and `2020-01-15` is **reasoned from
  what I saw during the probe and is not checkable by any other reader.** Listed
  here rather than under Driven, after review pointed out it was the same
  pointing-at-nothing failure this document indicts elsewhere.
- **The Sloan URL in the search summary is dead.** HTTP 404; working paths
  substituted.
- **All five other citations resolve with exact-matching titles.** Crossref,
  arXiv and PyPI APIs, 2026-08-21.
- **The four guards catch what their docstrings claim.** *Withdrawn.* Two of the
  four original mutations were shown by review to establish something other than
  what they claimed. The corrected statement is above: the guards were rebuilt,
  the reviewers' successful attacks re-run and now caught, and the `DOUBTFUL`
  assertion attributed by a mutation aimed at the property its docstring names.
- **The 2025-26 participation ingest size.** Read-only `LeagueGameFinder`
  preflight: 1,230 games, 164 game dates, 2025-10-21 to 2026-04-12, so 2,462
  requests and a 45.1-minute throttle floor.
- **Resume mechanics and the three divergences above.** Read from
  `backfill_season`, `NbaStatsClient.fetch`, `import_participation` and the
  cache-window constants, not from their docstrings.

### Reasoned, not driven — treat accordingly

- **The full-season `doubtful` projection (~149).** Scaled from one December
  window. The seasonality argument for it being an *over*estimate is reasoning,
  not measurement, and it is the number the Unit 3 go/no-go exists to replace.
- **Participation wall-time estimates.** The **request count** is now driven
  (2,462 for 2025-26) and the 45.1-minute figure is an exact throttle floor. What
  remains reasoned is everything above that floor: no season ingest has been run,
  so retries, 429s, parse failures and disk time are unmodelled, and the floor
  should not be read as an estimate of the real duration.
- **That a resumed run reproduces an uninterrupted one on a completed season.**
  The *mechanism* is driven — the 12-hour `SEASON_MAX_AGE` against the 3,650-day
  per-game window is read from the constants. That a refetch of a finished
  season's `LeagueGameFinder` returns an identical slate is **reasoned**, from
  the season being over, and I have not tested it.
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
