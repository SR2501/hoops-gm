# Projection strategy — should we build our own, and what would it have to be?

**Owner:** quant
**Status:** research finding and recommendation; **not a model card, and not a model**
**Date:** 2026-08-22

This document is not a model card and does not claim the Model gate. It fits no
parameters, produces no player-level number, and nothing here is an input to any
production path. It exists to answer one question the owner asked — *what should
our strategy be for producing original projections from scratch?* — and to record
the measurements that answer it, so the next person can disprove them cheaply.

The `baseline-model` backlog item is the subject. **The recommendation is not to
build it before draft day.**

---

## The recommendation, first

**Ship consensus per-game rates fused with our own availability number.** Do not
build an in-house per-game *production* model before Sunday 18 October 2026.

1. **Consume consensus rates as-is.** We cannot beat them, we would add nothing
   measurable, and a rate disagreement is not defensible in a draft room.
2. **Assert our own games-played number.** This is the only factor where an
   independent claim is both possible and explicable.
3. **Build the naive Marcel/SPS baseline only as a measuring stick** — never as a
   production source — to quantify how much of any projection set is reproducible
   from public box scores by a monkey.
4. **Spend the remaining weeks unblocking `participation-ledger-population`,**
   which is where the unpredictable variance actually lives and is currently the
   binding constraint on the entire spine.

---

## Why: the decomposition, measured

Season production decomposes as

```
season total  =  games played  ×  minutes per game  ×  per-minute rate
```

The three factors are not equally predictable, and the ordering decides the
strategy. Measured on `PlayerGameLogs` for 2015-16 … 2024-25 — **254,512
player-game rows, ten throttled requests**, one per season, because that endpoint
returns a whole league-season at a time. 2019-20 and 2020-21 are excluded from
every headline as disrupted (bubble and 72-game seasons); including them moves
nothing material and both figures are reported below.

### Year-over-year stability, season *t* → *t+1*

Qualified cohort, ≥500 total minutes in **both** seasons. Both columns are shown
so the exclusion can be checked rather than trusted: n = 1,719 pairs excluding
the disrupted seasons, n = 2,578 including them.

| factor | r² (excl. disrupted) | r² (incl. disrupted) |
|---|---|---|
| **games played** | **0.052** | 0.061 |
| minutes per game | 0.597 | 0.578 |
| STL / 36 | 0.570 | 0.555 |
| FT% | 0.509 | 0.494 |
| FG% | 0.659 | 0.664 |
| TOV / 36 | 0.686 | 0.684 |
| PTS / 36 | 0.747 | 0.744 |
| BLK / 36 | 0.781 | 0.787 |
| FG3M / 36 | 0.792 | 0.783 |
| AST / 36 | 0.826 | 0.819 |
| REB / 36 | 0.881 | 0.882 |

The exclusion changes nothing material and is not doing any work in the argument.

### The obvious objection, tested

Conditioning on ≥500 minutes in both seasons removes exactly the injury-shortened
seasons that GP variance lives in, so the headline GP figure is range-restricted.
It is, and this is the honest range rather than the flattering number:

| minutes filter (both seasons) | n | r²(GP) | r²(MPG) |
|---|---|---|---|
| none | 2,520 | 0.281 | 0.613 |
| ≥100 | 2,234 | 0.153 | 0.609 |
| ≥250 | 2,009 | 0.077 | 0.614 |
| ≥500 | 1,719 | 0.052 | 0.597 |
| ≥1000 | 1,239 | 0.046 | 0.574 |
| ≥1500 | 799 | 0.077 | 0.515 |

**GP r² is 0.046–0.281 depending on cohort. MPG r² is 0.52–0.61 across the same
range.** The minutes figure is far more stable; the games figure is the
conditioned one. Two honest complications, reported rather than trimmed: the GP
curve is **not monotonic** — it ticks back up to 0.077 at the tightest filter,
where n has fallen to 799 and the cohort is dominated by iron-man starters whose
games total genuinely does persist — and MPG's own r² does sag at that same
threshold. Neither disturbs the conclusion, because the *ordering* — games least
predictable, minutes next, rates most — holds at every threshold, and it is the
ordering that decides the strategy rather than any point estimate. A one-sided
filter (qualified in season *t* only, which removes the "survived into *t+1*"
selection) gives r²(GP) = 0.091 at ≥500 min, n = 1,985.

### The number that settles it

For players with three prior consecutive seasons (n = 500), predicting
next-season games played:

| predictor | MAE |
|---|---|
| the constant league mean | 15.90 games |
| **last season's games played** | **15.77 games** |
| unweighted 3-season mean | 14.86 games |
| Marcel-style 3/4/5 weights, 25% shrink to mean | **14.32 games** |

Mean GP is 58.5, sd 19.6. **A full season of games-played history is worth 0.13
games of accuracy over knowing nothing at all.** Everything available buys ~1.6
games out of 15.9.

### Where the unpredictable variance actually sits

Residual (unpredictable-from-last-season) variance share of a log season total,
by category and cohort:

| filter | PTS | REB | AST | STL | BLK | FG3M |
|---|---|---|---|---|---|---|
| none | GP+MPG **91%** | 92% | 86% | 85% | 75% | 71% |
| ≥250 min | 85% | 85% | 69% | 70% | 47% | 43% |
| ≥500 min | 79% | 79% | 61% | 64% | 37% | 34% |
| ≥1000 min | 69% | 67% | 47% | 51% | 25% | 21% |

**This is category-dependent and that matters for punt builds.** For the volume
categories that decide most head-to-head weeks, availability and role are 69–92%
of what nobody can predict. For specialist categories — blocks, threes — the
*rate* dominates among established players. A punt-FG%/stream-blocks build is
betting on a different factor than a points-and-boards build, and the tool should
not pretend one number describes both.

### The ceiling on sophistication

Predicting season-total points for the same cohort:

| method | r² |
|---|---|
| naive "last season's total" | **0.611** |
| Marcel rate × Marcel MPG × last-season GP | 0.582 |
| Marcel rate × Marcel MPG × league-mean GP | 0.576 |

**The careful decomposition is worse than the naive carry-forward**, because
games-played error swamps every refinement downstream of it. This single line is
the argument against `baseline-model` in its current form.

### Marcel versus naive, per category

Weighted 3/4/5 prior seasons with regression to the population mean, against
last-season-only, on per-36 rates (n = 500):

| category | naive r² | Marcel r² | winner |
|---|---|---|---|
| PTS/36 | 0.753 | 0.709 | naive |
| REB/36 | 0.879 | 0.893 | Marcel |
| AST/36 | 0.798 | 0.810 | Marcel |
| STL/36 | 0.442 | 0.496 | Marcel |
| BLK/36 | 0.769 | 0.811 | Marcel |
| TOV/36 | 0.659 | 0.655 | naive |
| FG3M/36 | 0.757 | 0.760 | ~tie |
| **MPG** | **0.675** | 0.602 | **naive** |

**Averaging helps for some categories and hurts for others, and the split is
measured even though the explanation for it is not.** The pattern — rebounds,
blocks and steals rewarding multi-year averaging while scoring rate and minutes
reward recency — is consistent with the former being attributes of a body and the
latter being decisions a coach makes, but **that reading is an interpretation, not
a measurement**; nothing here tests it. What is measured, and all the strategy
needs, is that **any recipe applying one weighting scheme to all categories is
leaving accuracy on the table in both directions.**

---

## Why an in-house rate model cannot pay for itself

**1. The information is exhausted, not merely hard.** A naive Marcel reaches
r² **0.50–0.89** across the seven per-36 categories — 0.71–0.89 for the volume
categories that drive most rosters (PTS, REB, AST, BLK, FG3M), with steals the
outlier at 0.50 and turnovers at 0.66. Whatever remains is largely irreducible
from public box scores. We would be competing for a residual that the best
public system in the world also cannot reach.

**2. A rate disagreement is not defensible in a draft room.** The acceptance test
for any disagreement is one row, under a bid clock:

> *"We have him at 6.1 assists per 36, they have 5.8."*

Nobody can act on that, nobody should, and the owner would be right to ignore it.
Against:

> *"We have him at 62 games, consensus assumes 72 — that is −14% on every
> counting stat he produces, driven by [three named drivers]."*

That is checkable, arguable, and actionable in the seconds available. **The
decomposition and the draft-room test point at the same factor**, which is the
strongest signal in this whole exercise.

**3. It would fail the circularity test.** See below.

---

## The circularity test, and why this recommendation passes it

A projection that agrees with consensus *for the same reason consensus agrees
with itself* has told us nothing. If our model were trained toward, blended with,
or regularised against the consensus we intend to disagree with, every agreement
would be an artefact and every divergence would measure regularisation strength
rather than a belief about players.

**The recommended approach passes structurally, not by good intentions:**

- **We make no rate claim**, so there is no rate agreement that could be fake. We
  are not measured against consensus on rates because we do not contest them.
- **Our availability model cannot see consensus's games assumption.**
  `docs/models/projection-blending.md` records that games-played assumptions are
  not inputs and that `source_games_played_assumptions` is a table the blending
  service *never queries*;
  `docs/adapters/basketball-monster-projections.md` records that Basketball
  Monster's `games` is persisted only as the source assumption, with every season
  total divided by it. **The one quantity we disagree about is the one quantity
  our model never observes their answer for.**
- **ADR-002's seam is therefore the anti-circularity mechanism**, not merely a
  modelling preference. That is a stronger justification than ADR-002 itself
  gives.

**What it does share, stated so it can be disproved:** the NBA game logs. Any
consensus games-played assumption is presumably derived from the same history.
Shared input, different method — weaker than full independence, and it must be
claimed as such. The methodological edge on that shared input is real but
specific, and it is described under *Identification* below.

### How much independence is there in "consensus" anyway?

Less than the number of sources suggests, though not for the reason one would
first assume.

Public projection systems share a **lineage**, and it is admitted in the primary
sources. DARKO's acknowledgments thank *"TangoTiger for inspiration in the design
of DARKO, and assistance with the underlying math"*; Basketball-Reference's Simple
Projection System states *"I took Tom's general idea, tweaked it to apply to
basketball and, presto, the SPS."*

**But shared inspiration is not shared arithmetic**, and the strong version of
this claim does not survive contact with the sources. DARKO's actual method —
per-stat exponential decay with β tuned by a differential-evolution optimiser, a
modified Kalman filter, the two blended by a gradient-boosted tree, plus
per-stat aging curves and opponent, seasonality, free-agency and interaction
effects — is substantially more elaborate than Marcel. It is not a Marcel variant.

The honest mechanism is different and still supports the conclusion: **public
systems agree largely because they consume the same public box scores and all sit
near the ceiling of what those inputs support.** The measured ceiling is above:
a monkey gets r² 0.71–0.89 on the volume categories (0.50 on steals, the
weakest). The spread between sophisticated systems is
small *because the information is exhausted*, not because anyone is copying.

Two consequences:

- **Agreement between sources is weak evidence of correctness.** Independent
  inputs would be needed for agreement to confirm anything, and there are none.
- **Blending N sources buys much less error reduction than N independent
  opinions would.** This is a live implication for the shipped
  `projection-blending` contract and has been added to that card's blind spots.

---

## Identification: the trap sitting in `availability-model`'s path

Our edge is games played. The following is the reason that edge is not free, and
it is the most important finding in this document.

**arXiv:2603.26935** — *"The Load Management Paradox: Correcting the
Healthy-Worker Survivor Effect in NBA Injury Modeling"*, Yue Yu and Guanyu Hu,
submitted 2026-03-27, stat.AP — reports that *"naive survival models applied to
NBA game-log data consistently yield a paradox: players who recently logged heavy
minutes appear less likely to sustain an injury"*, and demonstrates this is *"an
artifact of the healthy-worker survivor effect, wherein conditioning on game
participation induces severe collider bias driven by unobserved latent fitness."*
Their simulation shows the selection mechanism is *"mathematically sufficient to
entirely reverse the sign of the true association."*

**We reproduced the paradox in our own data, in the exact quantity
`availability-model` is specified to consume.** Prior-season workload against
next-season games played:

| cohort | prior total minutes → next GP | prior MPG → next GP |
|---|---|---|
| all players in both seasons (n=2,520) | **r = +0.521** | **r = +0.453** |
| ≥500 min in season *t* (n=1,985) | r = +0.328 | r = +0.244 |

Read naively this says heavy minutes *protect* a player from missing games, which
is not a physiological claim anyone would defend. It is survivorship: players who
were healthy enough to log heavy minutes were healthy, and health persists.
**A model fitted on these features without an identification strategy will learn
that workload is protective and will be confidently, invisibly wrong** — the exact
failure class this project's governance exists for, since nothing about it crashes.

This does not flip ADR-007; availability remains the edge and remains in the
spine. It changes what a gate-ready availability model must show. The amendment is
drafted in ADR-007.

### Is durability a real trait at all?

Yes, and smaller than intuition suggests. Grouping players by their mean games
played over three prior seasons and measuring what actually happened next:

| prior 3-season mean GP | n | next-season GP mean | median | sd |
|---|---|---|---|---|
| high (≥72) | 145 | **65.0** | 72.0 | 17.7 |
| mid (60–71) | 200 | 59.6 | 64.0 | 18.5 |
| low (<60) | 155 | **51.0** | 57.0 | 20.4 |

**A 14-game gap between the most and least durable groups, against a typical
within-group sd of 18.8.** The trait is real at the group level and swamped by
noise at the individual level. That reconciles the low r² with the correct
intuition that durability exists, and it dictates the output form: **`p(play)`
must be a distribution, not a point estimate**, and its calibration matters more
than its accuracy — which is what `quant.md` and ADR-007 already require.

Note also that even the most durable group averaged **65 games, not 78**.
Regression toward the ~58.5 league mean is strong, and a player who played 75+
for three straight seasons should still be projected well below that.

---

## Directional claims: measured, or labelled unmeasured

Standing rule: *nobody may predict the direction of a pooled estimate's bias
without measuring it.* A correctly identified mechanism does not determine the
sign of its aggregate. Every directional claim this document relies on:

| claim | status |
|---|---|
| Rates are more predictable than minutes, which are more predictable than games | **measured** — four cohort thresholds, ordering stable at all |
| Range restriction depresses the GP correlation | **measured** — r² 0.281 → 0.046 across the filter curve, though **non-monotonically**: it returns to 0.077 at ≥1500 min, n=799 |
| Multi-year averaging beats last-season-only for games played | **measured** — MAE 14.32 vs 15.77 |
| Multi-year averaging *hurts* for minutes and scoring rate | **measured** — MPG r² 0.602 vs 0.675; PTS/36 0.710 vs 0.753. The intuitive direction is wrong |
| Prior workload predicts *more* future availability, not less | **measured** — r = +0.52; the counterintuitive sign, and it is survivorship |
| Durable players stay more durable | **measured** — +14.0 games between extreme groups |
| A naive baseline reproduces most of what public box scores support | **measured for the baseline, UNMEASURED for consensus.** We measured what Marcel achieves; we have not measured what any consensus source achieves, because that requires an eligible held-out experiment we have not run |
| Consensus is well calibrated on rates and poorly calibrated on games | **UNMEASURED.** Plausible, load-bearing if true, and not checked. This is the single most valuable unrun experiment in this document |
| Consensus systematically over-projects games for stars | **UNMEASURED.** Our data shows strong regression toward ~58.5 games, but we have not compared that to any published assumption |
| Age curves regress older players down | **UNMEASURED and not cheaply measurable.** `PlayerIndex` carries no birth date or age — verified, one request, its 27 columns include `DRAFT_YEAR`, `FROM_YEAR` and `TO_YEAR` but no age. A career-stage proxy from our ten-season window is left-censored for anyone who debuted before 2015-16. Deliberately not proxied badly |
| Rookies are over-projected by consensus | **UNMEASURED.** Noting only that DARKO initialises every rookie identically, adjusted only for age, because it holds no NCAA, summer-league or preseason data |
| High-variance players should be discounted | **UNMEASURED.** This is G-score's premise (ADR-003) and is not evidence from this analysis |

---

## If it is built later: what the Model gate would require

Should `baseline-model` proceed after draft day, these are its conditions and
none of them is satisfied by the analysis in this document.

**Measured against.** The naive Marcel/SPS baseline, on held-out seasons, per
category. Not against consensus — beating consensus is not the goal and cannot be
the acceptance criterion, since the purpose of an in-house number is to *locate*
divergence, not to win.

**Calibration, not accuracy.** For any probabilistic output, a reliability diagram
or binned calibration table. For point projections, residual distributions by
cohort — rookies, returnees from long absences, mid-season role changes — because
a model that is accurate on average and badly wrong on a knowable subgroup is
worse than one that says so.

**Sequestration.** `docs/governance/projection-experiment-protocol.md` applies in
full: the model worker receives only independently released immutable packages,
the freeze predates the unblind, and mock outcomes are permanently ineligible.

**A model card in `docs/models/`** meeting the normative minimum in
`docs/models/README.md`, including the mandatory statement of what the model
cannot see.

**Traceability.** Every stored number records the model version and the inputs
that produced it. A fused output is a composite of two lineages — consensus rates
and our availability — and without versioning nobody can later determine which
half moved.

**Driver features persisted.** "Why this number?" must always have an answer, and
that answer is the product. See the draft-room test above.

### The falsifying test for percentage categories

Percentage categories are volume-weighted impact, never raw percentage. A 90% free
throw shooter on one attempt is worthless. The named test, taken from
Basketball-Reference's SPS:

> **Project shots *missed* rather than shots attempted, then derive attempts as
> makes + misses.**

This is structurally superior to projecting makes and attempts independently
because it **cannot produce makes > attempts** — the invariant is enforced by the
parameterisation rather than checked afterwards. The test that must exist: feed a
projection set where a naive implementation would average raw percentages, and
assert the output preserves made/attempted volume separately. The existing
blending contract already does this; anything new must too.

---

## What this analysis cannot see

- **Whether consensus is actually good.** Everything here measures what is
  *reproducible from public box scores*, not what any commercial source achieves.
  No consensus projection set was evaluated. This is the largest gap.
- **Anything about 2026-27 specifically.** Rookies, players returning from a lost
  season, new roles after an offseason move, rule changes, and the current injury
  landscape are all invisible to a ten-season historical decomposition.
- **Non-appearance reasons.** `PlayerGameLogs` contains appearances almost
  exclusively — only 50 of 254,512 rows carry zero minutes. Games played here
  means *games with a log row*; the denominator — games the player's team
  scheduled while he was rostered and available — is not knowable from this
  source. This is precisely why `participation-ledger-population` is the binding
  constraint, and why `AVAILABLE_FLAG` cannot substitute: its non-1 values have a
  median 23.4 minutes and **0 of 2,736 such rows are zero-minute**, so it is not
  an appearance flag and does not mark absences.
- **Trades, coaching changes, undisclosed injuries, front-office intent, minutes
  restrictions, personal matters.** None appear in a box score.
- **Whether a 14-game durability spread is worth what it costs to model.** That is
  an outcome question, answerable only by a backtest against actual league
  results, which does not exist.
- **Two-way contracts, G-League assignments and mid-season signings**, which
  depress games played for reasons unrelated to availability and are not separated
  out here.

---

## Sources

All fetched 2026-08-22 UTC. Retrieval was driven; where a title differs from what
was expected it is recorded as returned rather than reconciled.

| Source | URL | Returned title | Note |
|---|---|---|---|
| DARKO | `https://www.darko.app/about` | "What Is DARKO?" | Redirected from `darko.app/about`. Daily in-season system; season-long projections listed under *Further Improvements*, i.e. not currently produced |
| BRef SPS | `https://www.basketball-reference.com/about/projections.html` | "Simple Projection System" | The published basketball Marcel: 6/3/1 weights, +1000 min regression, per-36, age break at 28 |
| Marcel | `https://tangotiger.net/archives/stud0346.shtml` | "The 2004 Marcels" | 5/4/3 weights, 1200 PA regression, age break at 29 — **and a separate formula for playing time**, independent support for ADR-002 from 2004 |
| Marcel (index) | `https://tangotiger.net/marcel/` | no `<title>` rendered; page text begins "The Marcel the Monkey Forecasting System…" | Recorded as returned |
| Load management | `https://arxiv.org/abs/2603.26935` | "[2603.26935] The Load Management Paradox…" | Abs page returned title only; **verified independently via the arXiv API** (authors, date, abstract) and a control fetch of nonsense ID `2603.99999`, which 404s — so the fetcher does not confabulate |
| Stabilization | `https://kmedved.com/2020/08/06/nba-stabilization-rates-and-the-padding-approach/` | "Stabilization Rates" | Minutes most stable — but this is *in-season* stability, a different quantity from the cross-season predictability measured here |
| RAPM | `https://www.sloansportsconference.com/research-papers/improved-nba-adjusted-using-regularization-and-out-of-sample-testing` | "Improved NBA Adjusted +/- Using Regularization and Out-of-Sample Testing" | Impact metric, not a box-score projection |
| BPM | `https://www.basketball-reference.com/about/bpm2.html` | "Box Plus/Minus, Version 2.0 (BPM)" | Reports no year-over-year r² per stat |

**Could not resolve.** EPM's methodology — `dunksandthrees.com/epm` and `/about`
both returned only a navigation skeleton (client-rendered); *no resolvable
primary source*. The widely-repeated CountTheBasket per-minute reliability figures
(pts ~0.61, ast ~0.59, stl ~0.31, blk ~0.27) have *no resolvable primary source;
searched the Wayback archive of countthebasket.com and
basketball-reference.com/about/reliability.html, both 404* — they are cited here
only as an example of a number that should not be inherited. **No published
year-over-year correlation for NBA games played was found at all**, so the figures
in this document may be the only ones available to us; treat them as ours to
defend rather than as corroborated.

## Change log

| Version | Date | Change |
|---|---|---|
| 1 | 2026-08-22 | Initial strategy. Recommends not building `baseline-model` pre-draft; ship consensus rates × in-house availability. |
