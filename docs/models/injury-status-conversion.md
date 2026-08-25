# Injury status conversion model card

**Owner:** quant
**Version:** 0 (skeleton — no model has been fitted)
**Status:** in development

> **Every results field in this card reads `NOT YET COMPUTED — blind in force`.**
> That is not an oversight and it is not a placeholder awaiting tidy-up. No
> conversion rate for any status has been computed by anyone, the selection
> partition's outcomes have not been read, and the held-out partition has not
> been touched. This card exists **before** the fit so that the fit cannot
> afterwards define its own success criteria. If you are reading a version of
> this file where the results are filled in but this paragraph is unchanged,
> something has gone wrong: the change log must record the unblind.

## Why this card exists before its model

The Model gate requires a card. Written after a fit, a card records whatever the
fit happened to produce and whatever metrics happened to flatter it. Written
before, it is a constraint. The pre-registration
([v2](injury-status-conversion-preregistration.md), frozen 2026-08-21) already
constrains the protocol; this card constrains the *reporting*, and the machinery
that will produce the numbers
(`hoops_gm.availability.calibration`) was likewise written and tested against
synthetic data whose calibration properties are known, by an author who could not
see a single outcome. See `DECLARED_CONVENTIONS` in that module: every estimator
convention that could change a verdict is pinned there, and every report copies
it, so a later reader can check the conventions were not chosen to suit the
answer.

## What it predicts

For one row of an official NBA injury report — one player, one scheduled game,
one report timestamp — the probability that the player records a **direct
participation outcome of "played"** in that game.

The unit is the *report observation*, not the player and not the game. A player
listed `questionable` on three successive reports before one game contributes
three observations. Lead time is a first-class covariate for exactly that reason
(§7 of the pre-registration defines the bands prospectively).

This is an **availability** quantity in the ADR-002 sense. It says nothing about
how well the player performs if he plays, and it must never be multiplied into a
per-game production line anywhere except the declared expected-games fusion.

## Inputs

All predictor-side, all resolved strictly before tip-off.

| Input | Source | Notes |
|---|---|---|
| Report status | `nba_injury_report` cohort | `out`, `doubtful`, `questionable`, `probable`, `available` |
| Stated reason category | same | `Injury/Illness`, `G League`, `Rest`, `Not With Team`, suspensions, `Personal Reasons`, `Trade Pending`, `Coach's Decision`, `Concussion Protocol`, `Return to Competition Reconditioning` |
| Stated reason subcategory | same | e.g. `G League` splits `Two-Way` / `On Assignment` |
| Lead time to tip-off | derived, cross-store | minutes; banded `<=60`, `61-180`, `181-540`, `>540` |
| Report era | derived | `legacy_hourly` / `short_lead_fifteen_minute`, boundary per the admissibility artefact |

Nothing here is derived from another *model*, so no model error compounds into
this one. Lead time is derived from a **cross-store** tip-off join, which is a
plumbing dependency rather than a modelling one: it is checked by
`cross_store_tipoff_agreement` in the admissibility artefact, and that check
exists because `gameEt` in the NBA box-score payload carries a `Z` suffix and is
not UTC.

**Outcome (not an input):** the direct participation outcome, sealed. Counts of
it by status, era, lead-time band and date are published; **no rate is**.

## Method

Not yet chosen. The pre-registration fixes the choice procedure so that it
cannot be made after seeing which choice wins:

- **Candidates** (§5), all Jeffreys `(plays + 0.5) / (observations + 1)`:
  `global_jeffreys`, `three_band_jeffreys` (`out`+`doubtful` /
  `questionable` / `probable`+`available`), `five_status_jeffreys`.
- **Selection** (§6): Brier on the selection partition; advance to a more complex
  eligible candidate only on a **≥0.005** improvement; ties keep the simpler one.
- **Final fit** (§6): refit the selected structure on development + selection,
  with no change to groups, priors, thresholds or metrics.
- **Evaluation** (§7): the held-out partition, run **once**.

**A structural note on the candidate set, recorded now because it is
predictor-side and will be unarguable later.** `three_band_jeffreys` pools `out`
with `doubtful`. In the held-out partition those are **2,963** and **83**
observations respectively — a 35.7-to-1 ratio — so the band rate is set almost
entirely by `out`, and `doubtful` is predicted at whatever `out` does.

The part of this that is a **theorem** rather than a demonstration:
distinct-emitted-probability binning partitions rows **by predicted value**;
statuses sharing a band share a predicted value; therefore no statistic computed
on that partition — conditions 3, 4, 5 and 7 all read off it — can separate them,
at any rates. `test_pooling_puts_the_two_statuses_in_one_bin_whatever_the_invented_rates`
drives it across three unrelated rate assignments so it cannot be an artefact of
the numbers chosen.

**Two boundaries on that claim, added after an independent review and stated
because the first write-up of this finding did not state them.**

1. **The exact zeros are definitional, not measured.** A model emitting each
   bin's own realised rate *on the evaluation set* has zero gap by construction.
   Quoting "CITL exactly 0.0, ECE exactly 0.0" as a result invites reading a
   construction as a measurement. `test_the_pooled_zeros_are_definitional_and_this_test_says_so`
   records that in the suite.
2. **Condition 5 does defend the band, though not the status inside it.** A real
   fit takes its band rate from the development partition, so its held-out band
   rate is displaced. The `unlikely` band's 3,046 observations make its Wilson
   half-width ≈0.0073, so the emitted band probability must land within about
   0.7 percentage points or condition 5 fires. The honest statement is therefore
   *a three-band model whose emitted band probability lands within ~0.7pp of the
   held-out band rate clears every pooled condition while `doubtful` is ~86
   points wrong* — narrower than "a band model right in aggregate clears
   everything", and driven at displacements of 0, 0.005 and 0.02 in
   `test_a_band_probability_displaced_by_one_point_starts_failing_condition_five`,
   where the `doubtful` error stays past 80 points at every one.

Demonstrated on synthetic data throughout; see also
`test_subgroup_restriction_exposes_the_status_the_pooled_table_masked`.

That is a statement about what the **condition set** can detect, not a prediction
about what the fit will do. It is also the reason this card requires the
subgroup-restricted table below regardless of how the owner rules on v3.

## Training window

2025-26 regular season, `2025-10-21` to `2026-04-12`, chronologically split by
§4 into development (82 game dates), selection (41) and held-out (41,
`2026-03-02` to `2026-04-12`). No recency weighting.

**Two known defects in that window, both published and neither fixable by
weighting.**

1. **The holdout is the end-of-season shutdown window and is not the regime the
   tool is used in.** Eliminated teams, seeding races, pre-playoff load
   management. The tool is used from draft day onward, weighted October–March.
   The admissibility artefact states this in
   `limitations_that_the_count_cannot_see`, and it is a limitation of the
   *cohort*, not of any model fitted on it.
2. **Era and lead time are structurally confounded.** `legacy_hourly` rows appear
   in the development partition only — **4,166** of them — while selection and
   held-out are **100% `short_lead_fifteen_minute`** (3,546 and 3,940). A model
   fitted partly on legacy rows is evaluated entirely on short-lead ones, and any
   era effect is inseparable from a lead-time effect by construction. This is the
   gap v3 §3 proposes to address.

## Evaluation

Held-out only, run once, per §7. **Calibration is the primary metric**; accuracy
is not reported as a headline.

Produced by `hoops_gm.availability.calibration.build_calibration_report`, which
stamps `CALIBRATION_MACHINERY_VERSION`, the binning scheme, the provenance and
the full `DECLARED_CONVENTIONS` map into every payload.

| Reported quantity | Value |
|---|---|
| Binned calibration table (one row per distinct emitted probability) | NOT YET COMPUTED — blind in force |
| Calibration-in-the-large (`mean(predicted) − observed rate`) | NOT YET COMPUTED — blind in force |
| Expected calibration error (observation-weighted) | NOT YET COMPUTED — blind in force |
| Brier score | NOT YET COMPUTED — blind in force |
| Log loss, with clipped-observation count | NOT YET COMPUTED — blind in force |
| Per-bin Wilson 95% intervals | NOT YET COMPUTED — blind in force |
| Monotonic ordering across the declared status order | NOT YET COMPUTED — blind in force |
| Lead-time band sensitivity | NOT YET COMPUTED — blind in force |
| **Subgroup-restricted table: informative statuses only** | NOT YET COMPUTED — blind in force |
| **Subgroup-restricted table: health reasons only** | NOT YET COMPUTED — blind in force |
| **Subgroup-restricted table: era split** | NOT COMPUTABLE on this cohort — held-out is 100% short-lead |

### Why the subgroup rows are mandatory in this card

Whether the **activation gate** may turn on a restricted table is the owner's
call on v3 and is not decided here. Whether this **card** reports one is decided
here, and it does, because a pooled-only report is not an honest description of
what was measured.

The arithmetic, re-derived independently from
`section_2_admissibility.held_out_direct_outcomes_by_status`
(`out` 2,963, `available` 467, `questionable` 335, `probable` 92, `doubtful` 83;
total **3,940**):

- Informative rows (`questionable` + `probable` + `doubtful`) = **510**.
- Informative share = 510/3,940 = **51/394 = 0.129441…**, one row in eight.
- A model exactly right on the other 87.06% and wrong by δ on *every* informative
  row shows a pooled calibration-in-the-large error of only `0.129441·δ`.
- Breaching a 0.10 pooled threshold therefore needs **δ > 197/255 =
  0.7725490…** — an error of 77.3 percentage points on every informative row.

Computed exactly with `fractions.Fraction`; v3's "0.773" is that to three
significant figures. Driven in
`test_v2_condition_three_survives_a_seventy_seven_point_error_and_fails_at_seventy_eight`.

**One correction to how that finding is usually stated.** v3 §4 argues from
calibration-in-the-large alone. Under distinct-emitted-probability binning, §8
condition 5 (per-bin Wilson coverage) *does* supply per-status protection where a
status gets its own bin. How much protection is bounded without seeing any
outcome, because the Wilson half-width is widest at `p̂ = 0.5`: evaluating each
held-out status count at `plays = n // 2` gives `questionable` (n=335)
**0.053238**, `available` (n=467) **0.045163**, `probable` (n=92) **0.100102**
and `doubtful` (n=83) **0.105154**.

So only `questionable` and `available` are protected below the 0.10 threshold at
any realised rate. For `probable` and `doubtful` the supremum exceeds 0.10, which
establishes that **a guarantee cannot be issued without knowing the rate** — not,
as an earlier draft of this card's change log said, that protection is absent.
That distinction is a quantifier, and the corrected form is strictly more useful
because the failing region is also derivable from counts alone: condition 5's
half-width reaches 0.10 only for `probable` at `p̂ ∈ [0.478, 0.522]` (5 of its 93
possible counts) and for `doubtful` at `p̂ ∈ [0.349, 0.651]`. Both windows are
centred on a coin flip, which is where a status meaning *likely to play* or
*unlikely to play* is least expected to sit.

An earlier draft also cited ≈0.054 for `questionable`, which came from a
*synthetic* realised rate — a number this lane must not use for a real status.
These bounds and ranges are blind-safe and are driven in
`test_the_wilson_half_width_at_the_informative_counts_is_bounded_without_a_rate`
and `test_where_condition_five_actually_stops_protecting_probable_and_doubtful`.

The dilution argument is therefore not the whole story, and the sharper hole is
the pooled-band masking described under Method — which condition 5 does **not**
catch, because the pooled band is a single bin.

## What this model cannot see

Mandatory section. Be specific.

**It cannot see the thing it is nominally about.** An injury report status is a
team's public statement, filed to a league requirement, by an organisation with
competitive reasons to be vague. It is not a medical fact. The model predicts the
conversion of *the statement*, and inherits every incentive behind it.

- **Whether the stated reason is true.** "Rest" is routinely laundered as a minor
  ailment, and the reverse also appears in this very cohort: 7 of the 97 `Rest`
  rows carry subcategories naming a specific knee and the phrase "Injury
  Management". Do not trust stated DNP reasons; lean on observed patterns.
- **Anything decided after the last report and before tip-off** — a warm-up that
  goes badly, a pre-game illness, a coach's late change of mind.
- **Trades, buyouts, waivers and G League recalls** as *events*. It sees a
  `Trade Pending` label (37 rows) but not the trade.
- **Coaching changes, minutes-restriction policy, front-office intent**, whether
  a team is tanking, and whether a player is being showcased or shut down.
- **Undisclosed injuries**, which by construction never appear.
- **Anything about the 2026-27 season**, which is what the tool is actually for.
  This is a 2025-26 model used as a prior for a season it has no observation of.

### It also cannot see that a quarter of its cohort is not an injury event

Of 13,789 canonical observations, **3,822 = 27.72%** carry a stated reason that
is not a health event: `G League` 3,385 (`Two-Way` 2,828, `On Assignment` 557),
`Not With Team` 247, `Personal Reasons` 82, suspensions 56 (55 league, 1 team),
`Trade Pending` 37, `Coach's Decision` 15.

`G League` `doubtful` is the sharp case. **v3 §6 reports 41 of 221 season-wide
`doubtful` observations — 18.6% — as Two-Way players who might be recalled.** That
figure is quoted from v3 and is **not** independently derivable from any artefact
committed on `main`: the cohort manifest publishes `status_counts` and
`stated_reason_categories` as separate marginals with no status-by-reason cross,
so this lane cannot check it. A `data-engineer` lane is committing that cross;
until it lands, treat 18.6% as v3's number, not as a verified one. Recall
uncertainty is real, but it is a **roster mechanic**, and there is no reason for
its conversion rate to resemble injury-`doubtful`.

**An arithmetic discrepancy in v3 §6, reported rather than copied.** §6 states
that on health reasons alone `doubtful`'s held-out floor is ~74, giving 2.5x
headroom over v2 §8 condition 6's ≥30. Applying §6's own 18.6% to the held-out
`doubtful` count gives 83 x (1 − 41/221) = 14,940/221 = **67.6, so ~68**, and
67.6/30 = **2.25x** (2.27x if the count is rounded to a whole player first). I
cannot reconstruct a route from the published figures to 74
or to 2.5x; an independent reviewer brute-forced `c x (1 - a/b)` over the 23
published counts and found no expression starting from the held-out 83 that
reaches 74. The nearest structural explanation is that 74 was derived from the
**development** partition's `doubtful` count of 75 rather than the held-out 83.
The
conclusion — condition 6 still clears comfortably on health rows alone — is
unaffected either way, which is why this is a note to the architect before the
owner binds v3 rather than an objection to v3. Driven in
`test_the_g_league_share_of_doubtful_implies_a_health_only_floor_near_sixty_eight`.

The recommendation inherited from v3 §6 is to **cut none of them**, because
excluding rows would change the membership fingerprint that §8 condition 8
requires to reproduce. They are disclosed instead, and the health-restricted
table above is how they are held to account.

**And the health/non-health split is itself a stated-reason artefact, so treat
every figure derived from it as approximate in *both* directions.** `AGENTS.md`
says rest is routinely laundered as a minor ailment; this cohort shows the same
corruption running the other way, with 7 of the 97 `Rest` rows naming a specific
knee and "Injury Management". A reason string is a team's choice of words, so a
health-restricted count is not a count of injuries — it is a count of rows a team
chose to describe as injuries. Everything above that rests on the split (the ~68
health-only held-out `doubtful`, and v3 §6's informative-row figures) inherits
that looseness, and should be read as an estimate rather than a measurement.

## Known failure modes

Anticipated, not yet observed — nothing has been fitted.

- **`doubtful` under any pooling.** n=83 held out, 18.6% of it a roster mechanic,
  and pooled with `out` under one of the three candidates at 35.7-to-1.
- **`probable`** at n=92: the smallest informative cell, and the one whose Wilson
  interval will be widest.
- **The `<=60` band for informative statuses.** Across all direct outcomes in
  the cohort the `<=60` band holds `doubtful` 1, `probable` 10, `questionable`
  42, against `out` 3,183 and `available` 812. Any lead-time claim about
  informative statuses near tip-off rests on almost nothing.
- **Era transfer.** Fitted partly on `legacy_hourly`, evaluated on none of it.
- **Regime transfer.** Fitted across the season, evaluated on the shutdown
  window, deployed in October–March of a different season.
- **A well-calibrated model that is useless.** Predicting the base rate for
  everyone is perfectly calibrated in the large and has no discrimination at all.
  Calibration is necessary, not sufficient; this is why §6 selects on Brier and
  §7 reports the calibration table rather than a single number.

## Gate status of the machinery this card depends on

The calibration machinery (`hoops_gm.availability.calibration`, plus the
synthetic generators and 30 driven mutations) is filed under the **Code gate**.
That is the architect's ruling; the reasoning matters more than the verdict.

**Why Code and not Model.** You cannot hold data out from a formula. The Model
gate's central requirement is a backtest against held-out data, and there is no
estimate here to back-test — the module is a deterministic scorer, not an
estimator. The honest discharge for such a thing is verification against
analytically known values plus deliberate corruption, which is what the tests and
`scripts/mutate_calibration.py` do: 30 mutations, each driven red.

**The argument on the other side, recorded because a reader will otherwise
re-derive it.** An independent non-`quant` reviewer argued Code + Model, reading
`gates.md`'s *"anything producing a number a decision rests on — `p(play)`,
reliability metrics, projections, blending"* as a leading-clause test with the
em-dash list as examples, and noting that CITL, ECE, the Wilson endpoints and the
bootstrapped Brier interval are the numbers v2 §8's conditions 2-5 and 7 are read
from. I accepted that correction before learning the fact that undercuts its
strongest step: **"reliability metrics" in `gates.md` is a word collision.** It
names the player-consistency model in `docs/models/reliability-metrics.md`, not a
*reliability diagram*, which is a calibration plot. Two senses of one word inside
the document that decides which gate applies. The architect has filed the
ambiguity as a defect in `gates.md` in its own right.

**The half of this that binds forward, and the reason the section exists.** When
this machinery is later used to produce v2 §7's held-out calibration table,
**that report is Model-gated**, and this module is load-bearing inside it.
**Nothing verified here pre-discharges any part of that gate.** A green suite in
this module says its arithmetic is right; it says nothing about whether a model
scored by it is any good. That sentence is also in the module docstring and is
pinned by
`test_the_module_says_its_own_gate_does_not_pre_discharge_the_model_gate`,
because it survives only as prose and prose is deletable.

## Change log

| Version | Date | Change | Effect on results |
|---|---|---|---|
| 0 | 2026-08-23 | Skeleton created **before** any fit, under an unbroken blind. Reporting structure, subgroup requirements, disclosure of the non-health share, and the δ = 197/255 dilution arithmetic fixed in advance. Machinery: `hoops_gm.availability.calibration`, developed and verified entirely on synthetic cohorts. | None — no result exists. |
| 0.1 | 2026-08-23 | Revised after independent non-`quant` review, blind still unbroken. Four reviewer mutations that had survived are now caught (18 total). Corrections: the pooled-masking claim narrowed to its rate-independent theorem plus the ~0.7pp condition-5 boundary, with the exact zeros marked definitional; per-status Wilson half-widths restated at the blind-safe `p_hat = 0.5` worst case, which shows a 0.10 guarantee **can** be issued for `questionable` and `available` at any rate but **cannot** be issued for `probable` or `doubtful` without knowing theirs; v3 §6's 18.6% attributed rather than asserted; v3 §6's ~74 / 2.5x recomputed as ~68 / 2.25x and flagged to the architect; gate relabelled Code + **Model**, then **reverted to Code** by the architect's ruling once the `gates.md` "reliability metrics" word collision came to light, with the forward-binding caveat pinned by test instead. | None — no result exists. |
| 0.2 | 2026-08-23 | Revised after the **second** independent review, blind still unbroken. Two payload defects fixed: nested `restrict()` dropped the inherited pairs and under-reported what had been excluded; a `RestrictedCohort` mutated after construction over-claimed, recording an `out`-dominated rate as `doubtful`. Restriction markers are now **verified against the rows** rather than believed. Container copies (slice, `+`, `*`, `.copy()`) re-wrap; the iteration-based strip routes are documented as a residual **class** and pinned by test rather than denied. The 0.1 row's own quantifier error corrected — the Wilson result shows a 0.10 guarantee cannot be *issued* blind for `probable`/`doubtful`, not that protection is absent, and the failing rate windows are now stated. Mutations: 23, all caught, one of which survived its first run and exposed a genuinely untested path. | None — no result exists. |
| 0.3 | 2026-08-23 | Revised after the **third** independent review, blind still unbroken. Four reviewer mutations survived a suite that had just caught 23, and all four share a shape: **each earlier fix landed on the case that was driven and left the generalisation of that case untested.** Verification checked only the first recorded pair - which the previous fix had just made the abnormal case by teaching `restrict()` to accumulate; `restrict()`'s key-conflict precedence was unpinned, so asking for `out` after `doubtful` could return `doubtful` rows relabelled `out` with a self-consistent marker; `__mul__` could drop its count silently, because the container tests asserted type and marker but never contents; and the per-bin gap's declared sign was unpinned because every consumer takes `abs()` - the second instance of a symmetry class this repository is now collecting. The re-wrap rule was also **too wide** and is narrowed: only a whole-extent slice, `* 1`, `+ []` and `.copy()` keep the marker, because duplication and truncation left it true of every row while the payload's `n` was wrong - and condition 5 is a Wilson half-width going as 1/sqrt(n), so duplicating the 83-row `doubtful` cohort moves its worst case from 0.1052 to 0.0752 and manufactures a guarantee. The module now states plainly what verification does and does not establish: **soundness, not completeness and not multiplicity.** The docstring's claim that Python cannot intercept iteration was refuted by proof-of-concept and is restated as the design choice it actually is. Mutations: 30, all caught. | None — no result exists. |

**The next entry in this table must state the date the blind was broken and under
which pre-registration version.** A results row that does not is not admissible.
