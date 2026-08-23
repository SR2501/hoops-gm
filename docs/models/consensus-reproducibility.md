# How much of a commercial projection set does a naive baseline reproduce?

**Owner:** quant
**Status:** measurement; **not a model card, and not a model**
**Date:** 2026-08-22

This document fits nothing, ships nothing, and produces no player-level number.
It does not claim the Model gate, because there is no model here to gate. It
exists to test one sentence in `docs/models/projection-strategy.md` that an
accepted strategy rests on and that its own author labelled *reasoned, not
driven*:

> *Consensus sits near the ceiling of what public box scores support.*

That lane measured what a naive Marcel reproduces **from public data**. It never
evaluated a commercial projection set. This one does.

**Every result below is an agreement, never an accuracy.** Neither side is
ground truth. There are no outcomes here, no held-out season, and no claim about
who is right.

---

## The answer, first

**On rates, a monkey gets most of the way there, and the commercial set is
nonetheless doing principled work.** Both halves of that are measured, and the
second half is the finding worth keeping.

**On games played, there is almost nothing to reproduce, because the commercial
set barely expresses a per-player opinion.** Its games field takes two values for
85% of the relevant player pool.

The accepted recommendation — consume consensus rates, assert our own
games-played number — **survives, and its games half got stronger.** One change
is warranted: **consume their minutes as well**, which the strategy does not
currently say.

---

## Setup, stated so it can be disproved cheaply

**The measurements below are re-runnable.** `scripts/consensus_rederivation.py`
holds them as four subcommands — `rates`, `divisor`, `concentration`,
`leak-scan` — reading the export by hash and the public side from the recorded
payload store, offline, refusing rather than fetching. It was committed on
2026-08-23, after the *absence* of a committed derivation forced a later lane to
rebuild one from scratch merely to check a citation. It reproduces the
addendum's figures. It does **not** reproduce the originals in this section,
which still have no committed derivation.

**Paid-source discipline.** The commercial export is paid and its rows are
deliberately absent from this repository. No rate, name, or cell value from it
reaches stdout, a log, a committed artefact, or this document. Only counts,
correlations, slopes and mean errors over cohorts of n ≥ 20 appear anywhere.

The leak filter was **proved to fire rather than assumed to**, because a previous
unit's regressed silently and that is in the risk register. The guard's self-test
asserts (a) its banned-token set is non-empty and ≥ 400 entries, (b) it covers
505/505 parsed rows — *the scope includes the thing under test*, (c) it raises on
a real paid name, and (d) it does not raise on innocuous text. A guard that
iterates over an empty set passes every input.

**The export was identified by hash, not by filename.** SHA-256 matched
`FA13AD188E8ACADD410DFEAE7FF296A25078842E22CE17046CF19DFBCA9D3ABD`, the value
pinned in `docs/adapters/basketball-monster-projections.md`. **Driven.**

**Parsed through the existing adapter**, not a reimplementation:
`parse_projection_csv` under `BASKETBALL_MONSTER_PROFILE`. 536 rows → **505
parsed, 31 rejected**. The 31 rejections are exactly the zero/missing-games tail
the adapter doc predicts, for exactly the stated reason. The doc's claim held
under an independent exercise.

**Public side: eleven `PlayerGameLogs` requests** through the existing throttled
client — consuming an adapter, not building one. Seasons 2016-17 … 2025-26,
255,085 player-game rows, cached outside the repository so re-runs cost nothing.

### The window correction, which matters more than it sounds

The prior lane used 2015-16 … **2024-25**. **2025-26 is complete and available —
26,651 rows.** A commercial 2026-27 projection is built with 2025-26 in hand, so a
baseline that stops at 2024-25 is a year stale and *every* disagreement is partly
an artefact of the missing year rather than a difference of opinion. This
experiment uses 2025-26 as its most recent season.

This does not affect the prior lane's results, which are self-contained
season *t* → *t+1* comparisons. It would have invalidated this one.

### Cohort and join

Baselines: Marcel 5/4/3 over 2025-26 / 2024-25 / 2023-24 with shrinkage toward
the league per-36 rate; a naive last-season variant; and raw carry-forward with
no modelling at all.

Join on exact normalised name: **419 of 505 parsed rows matched** a player with
recent NBA history. **Cohort selection is always on our side, never on the
commercial value**, so nothing here selects on the quantity being measured.

---

## Rates: the full range, and the subset it is drawn from

**This range covers scored rate categories only. Minutes and games are excluded
from it and are reported separately below.** The eleven are PTS, REB, AST, STL,
BLK, TOV and FG3M, plus FGM, FGA, FTM and FTA — the nine scored categories with
the two percentage categories expanded into their volume components, because a
percentage category is volume-weighted impact and not a raw percentage. Neither
`minutes` nor `games` is among them, and `games` could not be: it is not a stat
column of `BASKETBALL_MONSTER_PROFILE` at all but a `games_played_alias`, which
`ProjectionSourceRow` carries to a separate table so nothing downstream reaches
it while reading a rate.

**Whenever this range is quoted, quote its subset with it** — the phrase "per
game" below is a *unit* (per-game rather than per-36) and not a scope, and it
has already been misread as one. See the addendum dated 2026-08-23.

Per-game agreement, **all 11 rate categories across all four cohorts: r² 0.726 –
0.947.** The floor is **steals** (0.726, our-MPG ≥ 20); the ceiling is **blocks**
(0.947, our-MPG ≥ 28). Per-36, which strips out the shared minutes channel:
**0.813 – 0.958**.

That is the whole range, not the flattering part of it. The cohort curve is given
in full so the range restriction can be checked rather than trusted:

| cohort (selected on **our** projected MPG) | n | PTS | REB | AST | STL | BLK | TOV | FG3M |
|---|---|---|---|---|---|---|---|---|
| all joined | 419 | 0.857 | 0.857 | 0.883 | 0.778 | 0.878 | 0.848 | 0.856 |
| MPG ≥ 10 | 402 | 0.853 | 0.859 | 0.879 | 0.767 | 0.891 | 0.843 | 0.852 |
| MPG ≥ 20 | 252 | 0.826 | 0.876 | 0.862 | **0.726** | 0.922 | 0.806 | 0.839 |
| MPG ≥ 28 | 105 | 0.808 | 0.898 | 0.874 | 0.789 | **0.947** | 0.804 | 0.889 |

Agreement declines as the cohort tightens, as it must — the spread that inflates
a correlation is being removed. **Steals is the weakest category at every
threshold and blocks the strongest at every threshold.**

### The crudest possible monkey

Not Marcel. **Last season's per-game line, carried forward, with no modelling
whatsoever**: r² **0.658 – 0.942**. It *beats* Marcel on points, threes and
minutes at every cohort — consistent with the prior lane's finding that
multi-year averaging hurts for exactly those quantities.

"Reproducible by a naive baseline" understates the result. Doing nothing at all
is already most of the way there.

---

## But the commercial set is not naive, and this is the finding worth keeping

A correlation cannot distinguish *"they are near the ceiling"* from *"they are
also naive"* — both produce high agreement. **A regression slope can, and it
needs no outcomes and no held-out year.**

Slope of commercial per-36 on last-season per-36, n = 232 (≥ 20 games at ≥ 20 MPG
in 2025-26). Slope 1.0 is pure carry-forward; below 1.0 is shrinkage toward the
mean.

| category | slope | implied shrink | that rate's t→t+1 r², measured independently |
|---|---|---|---|
| STL | 0.824 | **17.6%** | 0.570 — *least stable* |
| TOV | 0.850 | 15.0% | 0.686 |
| AST | 0.912 | 8.8% | 0.826 |
| PTS | 0.929 | 7.1% | 0.747 |
| BLK | 0.957 | 4.3% | 0.781 |
| FG3M | 0.969 | 3.1% | 0.792 |
| REB | 1.001 | **−0.1%** | 0.881 — *most stable* |

**The commercial set shrinks each category in near-inverse proportion to how
unstable that category is year over year** — inverse-monotone with one exception,
assists. The stability column is `projection-strategy.md`'s independent
measurement, produced without any sight of this export.

That is what a competent projection system does and what a naive one cannot do by
accident. It is evidence for the ceiling reading that does not depend on
believing anyone's marketing. **Driven.**

**A negative result, recorded because this is the kind that quietly disappears:**
the set does **not** shrink short-history players' rates harder. PTS/36 slope
0.944 for players with three prior seasons against 0.952 for those with two or
fewer (n = 181 / 51). The intuitive direction is absent.

---

## Minutes: a real opinion, after a confound was removed

Pooled, the commercial minutes slope on last season is **1.157** — it
*amplifies* rather than regresses, giving high-minute players more and low-minute
players less. That is the opposite of statistical shrinkage and is the signature
of information no box score contains.

Implied MPG is season minutes ÷ games, so a coarse games divisor leaks directly
into it. Holding the divisor fixed:

| | n | MPG slope |
|---|---|---|
| pooled across buckets | 232 | **1.157** |
| within modal games bucket A | 126 | 1.086 |
| within modal games bucket B | 67 | 1.057 |

**About half the amplification was the confound.** The direction survives; the
magnitude, reported pooled, would have been roughly double the truth.

Control, to show the check discriminates rather than moving everything: PTS/36
slope barely shifts (0.929 pooled → 0.903 / 0.972 within bucket), which is what
must happen, since the divisor cancels for a rate.

**Consequence for the strategy: consume their minutes, not only their rates.** A
deliberate role opinion is exactly the thing our ten-season history cannot
produce, and it is not a rate claim we would be conceding.

**This was accepted by the owner and changes the recommendation** in
`projection-strategy.md`, which previously said *consume rates, assert games* and
now says **consume rates and minutes, assert games**.

### Where that puts the ADR-002 seam

```
season total  =  games played  ×  minutes per game  ×  per-minute rate
                 └── ours ──┘    └──────── theirs ────────┘
```

ADR-002 requires production and availability to be computed separately and fused
explicitly. It does not say where in the decomposition the seam sits, and this
measurement now decides it: **the seam falls at games, not at minutes.**
Minutes-per-game is role — production-side, informed by depth charts and
offseason moves we do not hold, and demonstrably amplified rather than shrunk.
Games-played is availability, and it is where the commercial set expresses almost
no per-player opinion.

**Flagged for `architect`, not decided here.** My read is that this is
implementation of ADR-002 rather than a change to it — the ADR decides *that*
they are separate, this identifies *where*. The argument against my own read,
which `architect` should weigh: placing the seam at minutes-vs-games is precisely
what licenses consuming a third party's minutes, and that is a strategy
commitment rather than a detail. I do not think it needs an amendment; I am not
confident enough to leave it unflagged.

> **Adjudicated 2026-08-23.** An amendment was written — but for neither reason
> given above. Inside ADR-002's own two-factor vocabulary there was never a
> second candidate seam, so nothing was located; and the hazard that does
> warrant an amendment is one this section did not notice. See the addendum
> below and ADR-002's Amendments section.

---

## Games played: there is almost nothing there

Agreement on games is the weakest of everything measured — **r² 0.284 – 0.504**,
falling as the cohort tightens. The reason is not sophistication we cannot match.

**The commercial games field is a tier, not a per-player estimate.** Across 505
rows it takes **31 distinct values**. Within the rotation cohort it prices most
carefully (its own MPG ≥ 20, n = 249) it takes 18, and **84.7% of them sit on
just two values**, which are five games apart and both sit above the observed
three-season league mean.

> **Why the two values are not printed here.** They are the *mode* of a paid
> column, and a mode is the one summary statistic guaranteed to be a verbatim
> cell. My own leak scan passed them because it screened names and rates and
> treated anything distributional as an aggregate — the same defect class as a
> check whose scope excludes the thing under test. The finding is the
> concentration, not the values, and it survives their removal intact.

**Cross-check, because a field that claims to be a projection should be checked
against something independent rather than believed.** The adapter's semantic
screenshot reconciliation established that dividing season totals by `games`
reproduces the source's own displayed per-game figures, 13/13. So `games` is
demonstrably the divisor the source itself uses — it is their games assumption,
not an unrelated column. **Driven.**

What that cross-check cannot settle: whether the tiering is a modelling choice or
an artefact of this particular export view. One file cannot tell us.
**Reasoned, and flagged.**

### Level

For the rotation cohort (our MPG ≥ 20, n = 252):

| quantity | games |
|---|---|
| commercial mean | **65.0** |
| those same players' observed 3-season mean, from public logs | 61.4 |
| our unshrunk 3-year mean | 61.1 |
| our 25%-shrunk Marcel figure | 59.8 |

**63.9%** of the cohort carries a commercial games figure above its own unshrunk
history. The direction was measured, not predicted.

**And the magnitude was checked against my own tuning**, because a shrinkage
constant is exactly the kind of parameter that manufactures a gap like this: the
gap is **+5.1 games against the shrunk baseline and +3.9 against the unshrunk
one.** Roughly three quarters survives removing the parameter, but the figure I
would have reported was inflated by about 30% by a choice of mine.

This makes `projection-strategy.md`'s *"consensus systematically over-projects
games for stars"* row **measured and directionally confirmed** — a modest tilt,
not a landslide.

---

## The ordering, replicated by an unrelated experiment

| channel | r² range across all four cohorts |
|---|---|
| per-36 **rates** | 0.813 – 0.958 |
| **minutes** | 0.395 – 0.747 |
| **games** | 0.284 – 0.504 |

**Rates ≫ minutes ≫ games**, at every threshold. This is the same ordering
`projection-strategy.md` found, reached by a different route: that lane measured
year-over-year self-stability in public data, this one measures agreement with a
commercial set. Two unrelated measurements, one ordering. The strategy rests on
that ordering rather than on any point estimate, and it now has two independent
supports.

---

## Where the disagreement lives

Mean absolute difference normalised by the commercial value's standard deviation
across the whole MPG ≥ 20 cohort, so cells compare across categories and rows.

| subgroup | n | PTS | REB | AST | STL | BLK | TOV | FG3M | **MPG** |
|---|---|---|---|---|---|---|---|---|---|
| 3 prior seasons | 193 | 0.303 | 0.238 | 0.257 | 0.376 | 0.184 | 0.320 | 0.292 | 0.386 |
| 2 prior seasons | 29 | 0.351 | 0.339 | 0.326 | 0.421 | 0.266 | 0.357 | 0.381 | 0.552 |
| **1 prior season** | 30 | 0.504 | 0.434 | 0.378 | **0.670** | 0.307 | 0.470 | 0.355 | **0.896** |
| **missed most of 2025-26 (GP ≤ 25)** | 24 | 0.465 | 0.427 | 0.380 | 0.640 | 0.329 | 0.508 | 0.403 | 0.737 |
| played 2025-26 (GP > 25) | 228 | 0.319 | 0.256 | 0.269 | 0.393 | 0.195 | 0.325 | 0.300 | 0.437 |
| **debut in last 2 seasons** | 53 | 0.461 | 0.407 | 0.351 | 0.552 | 0.298 | 0.433 | 0.381 | 0.788 |
| established (debut ≤ 2021-22) | 158 | 0.293 | 0.238 | 0.267 | 0.389 | 0.184 | 0.320 | 0.294 | 0.370 |

**The disagreement is concentrated, not diffuse.** Short-history,
recently-debuted and returning-from-absence players disagree **1.5 – 2.4×** more
than established ones, and the gap is **widest on minutes** — 0.896 against
0.386, a 2.4× spread, against only ~1.6× on the rates.

This is directly actionable and it is the useful output of the exercise: **the
caveat the screen must show is about role and availability for these cohorts, not
about rates.** A blanket uncertainty band would be wrong in both directions.

### The harder version of the same finding

**66 commercial rows have no NBA game log in ten seasons at all** — rookies and
international signings — of which roughly 8 are at rotation minutes. For those the
caveat is not "less confident". It is **"we have no number"**. Any baseline built
from public game logs is structurally blind to them, and a screen that silently
omits a player a draft room is actively discussing is worse than one that says it
cannot see him.

---

---

## What this measurement cost the anti-circularity argument

`projection-strategy.md` argues that our availability model cannot be circular
with a commercial one, and the argument is structural rather than aspirational:
`source_games_played_assumptions` is a table the blending service *never
queries*, so the one quantity we contest is the one whose answer our model never
sees.

**This measurement read that column.** Offline, for evaluation, and no code
changed — but the guarantee did.

Before: *no one on our side can fit to their games number, because nothing on our
side can read it.* After: *no one on our side should fit to their games number.*
Nothing in the repository weakened, no gate moved, and the protection went from
**structural to behavioural** because a human now knows the shape of that
distribution.

Two consequences, and the second is a staffing constraint rather than a note:

- **Read it to score ourselves, never to fit ourselves.** Including informally,
  by an author who simply remembers the number while tuning a prior.
- **Whoever builds the availability model should not be whoever read that
  column.** That is me. I can state the aggregate honestly and still not be the
  right person to choose a shrinkage target afterwards, because I cannot
  demonstrate that I have forgotten it and no reviewer can check.

This is offered as a real cost of having run the experiment, not a
disclaimer. The experiment was still worth running — but the cost should be
paid deliberately rather than discovered later.

### Scope of that staffing rule, ruled 2026-08-23 by `architect`

The rule above was read more widely than it is written, so its scope is now
stated here rather than inferred from it.

**The predicate is not *did you look*. It is *did you acquire a quantity a prior
could be tuned toward*.**

- **Values exclude:** a mode, a mean, a player-level figure, an extremum of the
  contested column.
- **Facts do not:** a concentration, a correlation, a count. There is no number
  in "2.5 effective levels" for an estimate to be pulled toward.

**The exclusion expires on publication.** Once a quantity is in `main`, every
lane holds it, and excluding one lane for knowing what the repository tells
everyone is theatre — *legible* theatre, which is how a guardrail loses the
authority it needs for the cases that matter.

That limb is not hypothetical here. **This document already publishes a mean of
the contested column** — the rotation-cohort games figure in the Level table
above, and the gap against our baseline stated both shrunk and unshrunk. That is
a value by the test above, it has been in `main` since 2026-08-22, and it is
therefore held by every lane rather than by its author. An exclusion keyed on it
would exclude everyone or no one.

**Two readings are withdrawn**, both `architect`'s: that the rule binds everyone
who has measured any input the availability model consumes — applied across
lanes without citing the sentence it came from — and an accompanying "three lanes
are now excluded" count, asserted without the three ever being enumerated. **No
artefact in this repository records who has read which column**, so the true
number was unavailable to the person asserting it and remains unavailable now.

Why the wide reading was wrong in direction and not merely in size: it made the
cheapest route to staying eligible for the most important model in the project
**measuring less**. A rule whose incentive is to look away is worse than no rule,
because it is obeyed.

**A narrower recusal, kept voluntarily and not required by the above.** The
author of this document should not be the one who chooses the availability
model's shrinkage *target*, having read this column's distribution twice and
being unable to demonstrate what has been forgotten. That is a caution about one
parameter, not a disqualification from the model, and it is recorded as the
author's own rather than as the rule's consequence — a self-recusal presented as
a requirement is how a rule silently widens again.

What survives unchanged is the class, which is the durable half and is not about
staffing at all: **a guarantee enforced by what code can see, destroyed by what a
person has seen, and no diff shows it.** The gate that would catch a forbidden
query cannot catch a memory. That asymmetry is why the rule exists, and it is
why a narrow rule that is actually enforced beats a wide one re-derived from
recollection at each invocation — which is how the wide reading arose.

---

## Addendum, 2026-08-23 — a citation was challenged, and the challenge was wrong in an instructive direction

**Status: still a measurement, still not a model.** Nothing here is fitted.
Re-deriving an existing figure to check what it covers is not a new model; the
one genuinely new quantity below is a concentration statistic of a source
column, which is a census of one file rather than a sample, and it is published
in exactly the form the `games` finding above was already published in. No
Model gate is claimed, and there is nothing here for a held-out year to hold
out.

### The challenge

The governance lane observed that `docs/backlog.md` and
`docs/models/projection-blending.md` carry the flat `0.726–0.947` while this
document records games agreement at `0.284–0.504`, and suspected a **rates-only**
figure was being quoted as though it covered **games** — the exact conflation
ADR-002 exists to prevent, in the documents arguing for the blending approach.

### It is not that, and the range is arithmetically incapable of being that

Settled from the measurement rather than the prose. The crudest baseline above —
last season's per-game line carried forward, with no modelling at all — needs a
single season, so it re-derives from cache with **no request and no refit**.
Independently rebuilt against the cached 2025-26 `PlayerGameLogs` (26,651 rows),
joined on exact normalised name, 400 of 505 rows matched, cohorts n = 400 / 361 /
244 / 110 selected on **our** observed MPG:

| channel | re-derived r² across all four cohorts | as published above |
|---|---|---|
| the 11 rate categories | **0.626 – 0.937** | 0.658 – 0.942 |
| minutes | 0.345 – 0.775 | 0.395 – 0.747 |
| games | **0.280 – 0.448** | 0.284 – 0.504 |

The re-derivation is close but not identical, and the gap is expected: this join
uses one season of history where the original used ten, so it matches 400 rather
than 419 rows and its cohorts are differently populated.

**The decisive fact needs none of that precision. Games agreement never reaches
0.5 in any cohort by either route, so it cannot sit inside a range whose floor is
0.726.** Had `games` been in the pool, the published floor would have been
roughly 0.28. Had `minutes` been in it, roughly 0.35–0.40. The range is
rates-only, and the structural check agrees: `games` is not a stat column of the
profile at all.

### The defect is real, and it is the mirror image of the one suspected

The citations do not over-claim. They **under-report**, and at the site that
matters most. `docs/backlog.md`'s amendment quoted the rates figure, then the
minutes finding, then concluded *"the ADR-002 seam therefore falls at games, not
minutes"* — **with no games figure in it anywhere.** The strongest channel was
quoted and the load-bearing one omitted, in the file a reader consults first. The
seam is at games because games agreement is 0.284–0.504 against a two-value
column, not because minutes amplify; a reader was left to infer the conclusion
from the wrong half of the evidence.

Compounding it, "per game" in those citations is a *unit* and sits one clause
from a games-played argument, where it reads as a *scope*. It has now
demonstrably misled one careful reader. Every citation site has been given its
subset and, where it makes the seam claim, its games counterpart.

### Two arithmetic facts about the export that the correlations could not show

Asked because ADR-002 line 21 captures the games assumption separately *"so our
availability model can override it rather than **compound** with it"* — and a
per-game rate obtained by dividing a season total by that same assumption is a
candidate for compounding.

**The vendor's minutes quantity is an integer MPG multiplied by the games tier,
exactly.** `minutes ÷ games` is an exact integer for **505 of 505 rows**, against
a shuffled-divisor control at 10.9%. It is therefore recoverable without loss and
carries no tier residue — consuming their minutes-per-game inherits nothing from
the column we reject.

**For the counting categories, no divisor recovers a rounder native quantity, and
this is undetermined rather than resolved.** Season totals sit on a one-decimal
grid for 100% of rows; `total ÷ games` lands on that grid for 1.8–11.1%,
`36 × total ÷ minutes` for 2.4–9.9%, and `total ÷ minutes` for 0.8–8.9% — against
a shuffled-divisor control of 3.2–10.5%. Every candidate is **at chance**. So
publication rounding has destroyed whatever grid the native quantity had, and
this file cannot say whether their counting rates are native or manufactured by
dividing by a two-value tier. **Reasoned, and the honest answer is that we do not
know.** The consequence is recorded in ADR-002's amendment rather than waved
past: multiplying a consumed rate by *their* games — or consuming a season total
— re-imports the tier, and looks like a feature while doing it.

### The test that condemned `games` had never been run on `minutes`

This is the part I did not expect and it is the finding worth keeping. The case
against the `games` column was its coarseness, evidenced as *31 distinct values,
84.7% of the rotation cohort on two*. The recommendation to **consume** their
minutes rested only on the slope evidence. **The same coarseness test was never
applied to the column being adopted.**

Applied now, identically to both, and note first that it **replicates the
published figure exactly** — games in the rotation cohort (their MPG ≥ 20,
n = 249): 18 distinct values, 84.7% on two. Independent replication, different
author, same file.

| column | cohort | n | distinct | top 2 share | **effective levels** |
|---|---|---|---|---|---|
| `games` | whole file | 505 | 31 | 60.0% | **4.5** |
| minutes-per-game | whole file | 505 | 34 | 10.5% | **29.2** |
| `games` | their MPG ≥ 20 | 249 | 18 | **84.7%** | **2.5** |
| minutes-per-game | their MPG ≥ 20 | 249 | 18 | 20.5% | **14.9** |

Effective levels is 1 / Σp², the count of distinct values a uniform column would
need to be this concentrated; a column on two values scores 2.

**Distinct-value count alone would have said the two columns are identical** —
18 against 18 in the rotation cohort. It is concentration, not variety, that
separates them, and it separates them by **6×**. The seam location survives the
test that was owed to it, and it now rests on a measurement rather than on the
absence of one.

A qualification that belongs next to the result rather than below it: their MPG
is **integer-valued for 505 of 505 rows**, so it is coarser than a
one-decimal-looking column would be. Fourteen effective levels is a real
per-player opinion; it is not a fine one.



- **Whether either side is right.** There are no outcomes here. Every figure is
  an agreement between two opinions, and the experiment is symmetric in a way an
  accuracy measurement would not be.
- **A held-out year.** The export is a single season. The slope analysis is what
  rescues the exercise from that limitation for the rate question; **nothing
  rescues it for the games question**, where we observe only that the two sides
  differ and that one of them is coarse.
- **Whether the games tiering is a modelling choice or an export artefact.**
  One file cannot distinguish these.
- **Whether the vendor's counting-stat rates are native or manufactured by
  dividing by that tier.** Publication rounding to one decimal destroys the
  arithmetic signature that would answer it; every candidate divisor tests at
  chance. Added 2026-08-23.
- **Sources other than this one.** "Consensus" is one commercial set here. The
  conclusions are about it, not about every published projection.
- **19 further joinable rows.** A first-initial-plus-surname key would recover up
  to 19 more matches, 13 at rotation minutes. They were **not** folded in: that
  key can match falsely, and verifying candidates would have required reading paid
  names. The headline n = 419 is therefore a slight undercount.
- **Anything about 2026-27 specifically** — rookies, offseason moves, current
  injuries, rule changes. A historical baseline cannot see them, which is
  precisely why the disagreement concentrates where it does.

---

## What follows

1. **Do not build an in-house rate model before draft day.** Unchanged, and now
   supported by the strong reason rather than only the weak one.
2. **Consume consensus minutes as well as rates.** New. Their minutes carry a
   deliberate role opinion our history cannot produce.
3. **Keep the games-played edge, and expect it to be uncontested.** A two-tier
   assumption is not a competitor.
4. **The screen's uncertainty caveat is cohort-specific**, keyed on prior-season
   history and last-season availability, and it must include a "no baseline
   exists for this player" state.
5. **The load-bearing sentence should be weakened where it is quoted.**
   *"Consensus sits near the ceiling"* now has real evidence behind it, but the
   claim this experiment actually establishes is narrower and sufficient:
   *consensus rates are largely reproducible from public box scores, and their
   departures from a naive carry-forward are calibrated to category stability.*
