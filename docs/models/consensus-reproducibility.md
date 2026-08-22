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

Per-game agreement, **all 11 categories across all four cohorts: r² 0.726 –
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
| within games bucket 71 | 126 | 1.086 |
| within games bucket 66 | 67 | 1.057 |

**About half the amplification was the confound.** The direction survives; the
magnitude, reported pooled, would have been roughly double the truth.

Control, to show the check discriminates rather than moving everything: PTS/36
slope barely shifts (0.929 pooled → 0.903 / 0.972 within bucket), which is what
must happen, since the divisor cancels for a rate.

**Consequence for the strategy: consume their minutes, not only their rates.** A
deliberate role opinion is exactly the thing our ten-season history cannot
produce, and it is not a rate claim we would be conceding.

---

## Games played: there is almost nothing there

Agreement on games is the weakest of everything measured — **r² 0.284 – 0.504**,
falling as the cohort tightens. The reason is not sophistication we cannot match.

**The commercial games field is a tier, not a per-player estimate.** Across 505
rows it takes **31 distinct values**. Within the rotation cohort it prices most
carefully (its own MPG ≥ 20, n = 249) it takes 18, and **84.7% of them sit on two
values: 71 and 66.**

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

## What this measurement cannot see

- **Whether either side is right.** There are no outcomes here. Every figure is
  an agreement between two opinions, and the experiment is symmetric in a way an
  accuracy measurement would not be.
- **A held-out year.** The export is a single season. The slope analysis is what
  rescues the exercise from that limitation for the rate question; **nothing
  rescues it for the games question**, where we observe only that the two sides
  differ and that one of them is coarse.
- **Whether the games tiering is a modelling choice or an export artefact.**
  One file cannot distinguish these.
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
