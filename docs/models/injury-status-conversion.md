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
entirely by `out`, and `doubtful` is predicted at whatever `out` does. A pooled
calibration table cannot see this: if each band emits its own realised rate, every
bin gap is *exactly* zero and calibration-in-the-large, ECE, per-bin Wilson
coverage and monotonic ordering all pass, while the `doubtful` cell can be wrong
by an arbitrary amount. This is demonstrated on synthetic data with an ~86
percentage-point hidden error in
`test_a_band_model_right_in_aggregate_clears_every_computable_pooled_condition`
and `test_subgroup_restriction_exposes_the_status_the_pooled_table_masked`.

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
status gets its own bin: the Wilson half-width on `questionable` at n=335 is
≈0.054, tighter than 0.10. The dilution argument is therefore not the whole
story, and the sharper hole is the pooled-band masking described under Method —
which condition 5 does **not** catch, because the pooled band is a single bin.

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

`G League` `doubtful` is the sharp case: **41 of 221 season-wide `doubtful`
observations — 18.6%** — are a Two-Way player who might be recalled. That is real
uncertainty, but it is a **roster mechanic**, and there is no reason for its
conversion rate to resemble injury-`doubtful`. On health reasons alone
`doubtful`'s held-out floor is ~74 rather than 83, against v2 §8 condition 6's
≥30 — 2.5× headroom, not 2.8×.

The recommendation inherited from v3 §6 is to **cut none of them**, because
excluding rows would change the membership fingerprint that §8 condition 8
requires to reproduce. They are disclosed instead, and the health-restricted
table above is how they are held to account.

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

## Change log

| Version | Date | Change | Effect on results |
|---|---|---|---|
| 0 | 2026-08-23 | Skeleton created **before** any fit, under an unbroken blind. Reporting structure, subgroup requirements, disclosure of the non-health share, and the δ = 197/255 dilution arithmetic fixed in advance. Machinery: `hoops_gm.availability.calibration`, developed and verified entirely on synthetic cohorts. | None — no result exists. |

**The next entry in this table must state the date the blind was broken and under
which pre-registration version.** A results row that does not is not admissible.
