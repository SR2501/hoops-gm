# Availability model - preregistration v1

**Status: Proposed.** Written by `quant`; only the project owner may accept it.
**Author:** quant
**Original draft:** 2026-08-31
**Replacement draft:** 2026-09-01, pre-fit and pre-release of any availability
holdout

This is a protocol, not a model card. It fits no estimator, evaluates no
outcome, emits no `p(play)`, and claims no Model gate. A future result belongs
in `docs/models/availability-model.md`.

## 0. Binding order and current terminal state

The following events must occur in order:

1. The owner accepts or declines the exact Git commit containing this protocol.
2. `participation-ledger-population` completes its pending multi-season census
   of direct observations.
3. `participation-opportunity-coverage` completes its separate exhaustive
   player-game classification and provenance report.
4. The custodian freezes the pre-split injury-conversion overlap report in
   section 5.
5. The numeric pre-fit gates in section 3 are evaluated without reading an
   availability outcome value.
6. If and only if every gate passes, the implementation and split manifests are
   frozen, development and selection outcomes are released, and fitting begins.
7. The holdout is released once to an independent evaluator after final
   training is frozen.

Steps 2 and 3 are separate binding fit vetoes. The first owns only direct
`player_participation` observations. The second, and only the second, owns
enumerating every at-risk opportunity and classifying it as
`confirmed_observed`, `confirmed_absent`, or `unknown`.

**Current deterministic verdict: `FIT_VETOED_PREREQUISITES`.** The merged
repository records protocol-eligible direct observations for 2025-26 only.
There are currently zero protocol-eligible direct observations for 2023-24 and
2024-25. No estimator may be fit, no split may be substituted, and no
within-2025-26 fallback exists. A different split requires a separately
reviewed v2 committed before any newly proposed holdout is released.

The owner decision at this stage is therefore only whether to bind this
protocol. Acceptance does not override either data veto.

---

## 1. Questions, modes, and estimands

### Prediction unit

One player x one scheduled NBA regular-season team game for which
`participation-opportunity-coverage` establishes that the player was at risk of
playing.

### In-season mode

At a fixed decision timestamp before tip-off, estimate the calibrated marginal
probability that the player records a direct `played` outcome in that game.
Historical evaluation fixes that timestamp at exactly 60 minutes before the
scheduled tip-off. Production predictions use their actual decision timestamp
and may not claim the historical calibration context if made earlier than the
evaluated 60-minute horizon. Only information available at the applicable
timestamp may enter.

### Preseason / draft-morning mode

At the frozen draft-morning timestamp, estimate the calibrated marginal
probability of play for each scheduled regular-season game. No future injury
report is imputed. Every future game receives the distinct
`draft_morning_no_report` stratum until an in-season prediction is made.
For each historical season, the evaluation cutoff is 09:00
`America/New_York` on the calendar day before that season's first scheduled
regular-season game. The eventual 2026-27 release uses the owner's actual
draft-morning timestamp, recorded in its input lineage.

The two modes are fitted, selected, evaluated, and versioned separately. A
model passing one mode does not activate the other.

### What the probability means

The output is a calibrated **marginal Bernoulli probability in the eligible
population**, with population and calibration context attached. It is not a
joint distribution of a player's season. Summing game-level probabilities
produces expected games over that set of opportunities and nothing more.

No season-games variance, percentile, or interval may be constructed by
treating game-level marginals as independent. A games-played interval requires
a separately preregistered dependence model.

---

## 2. At-risk population, labels, and source boundaries

### Opportunity population

An opportunity exists only where independent roster/opportunity evidence says
the player was eligible for the team game. No G-League-assignment, two-way, or
suspension exclusion is inferred from participation silence or free-text DNP
reason. Such exclusions are allowed only when a separately sourced, dated
record establishes the player's ineligibility for that game.

`participation-opportunity-coverage` must classify every enumerated opportunity:

- `confirmed_observed`: a direct `played` outcome exists;
- `confirmed_absent`: an explicit direct non-play outcome exists; or
- `unknown`: opportunity evidence exists but the direct outcome is missing or
  cannot be reconciled.

The classification owner must publish the source, endpoint or artifact,
capture timestamp, stable player id, stable game id, team id, and the exact
evidence row or absence that supports every classification.

### Fitting labels

The only fitting labels are direct `player_participation` outcomes:

- positive: `played`;
- negative: `did_not_play`, `did_not_dress`, `not_with_team`, `inactive`;
- excluded from fitting: `unknown`, a missing row, unresolved player identity,
  unresolved game identity, or conflicting direct outcomes.

Game logs may audit that a `played` row is complete and may supply
predictor-side workload fields. They **never create, repair, or override a
fitting label**. A game-log appearance without a direct participation outcome
is a coverage discrepancy and remains `unknown` for this protocol.

### Remaining population selection

Even after the coverage gate passes, the estimand remains conditional on:

1. independent evidence that the player was at risk for the game;
2. a directly observed participation outcome;
3. stable player, game, and team identity;
4. survival into whichever history requirement a candidate uses; and
5. the historical NBA reporting and roster regimes represented by the eligible
   seasons.

This is not an all-NBA-player estimand. Rookies, newly signed players, traded
players around uncertain effective dates, and long absences are likely to be
selected differently. The model card must reproduce and disclose those
differences rather than generalize past them.

---

## 3. Pre-fit census, split, and terminal eligibility gates

### Required seasons

The candidate split is fixed:

| Role | Season | Use |
|---|---|---|
| Historical support | 2022-23 | Three-prior-season Marcel support only |
| Development | 2023-24 | Fit candidate structures |
| Selection | 2024-25 | Advance candidates and freeze one structure |
| Holdout | 2025-26 | One final evaluation by the independent evaluator |

There is no two-season or within-season fallback.

### Required direct-ledger census

Before any split is materialized, `participation-ledger-population` must publish
one committed census for each of 2022-23 through 2025-26. Each census names the
store path, schema revision, ingest implementation commit, source artifacts,
source fingerprints, stable-id reconciliation counts, direct outcome counts,
unknown counts, distinct players, distinct game dates, and missing NBA games.

The census is evidence about rows that exist. It must not manufacture an
absence or `unknown` row for a silent player-game.

### Required opportunity report

After the multi-season ledger is complete,
`participation-opportunity-coverage` must publish one committed report over the
same seasons. It must:

1. enumerate every player-game opportunity from independent roster evidence;
2. assign exactly one of the three classes in section 2;
3. report zero duplicate and zero unclassified opportunities;
4. report the class counts and `unknown_share` overall, by season, by mode, by
   report stratum, and by report era; and
5. bind every row to the provenance fields in section 2.

### Numeric proceed predicate

The following boolean is evaluated before a split file or outcome package is
released:

```text
PROCEED =
  all_four_direct_censuses_present
  AND duplicate_opportunities == 0
  AND unclassified_opportunities == 0
  AND unknown_share_overall <= 0.05
  AND max(unknown_share_by_season) <= 0.05
  AND each_fit_partition_direct_rows >= 5000
  AND each_fit_partition_distinct_players >= 100
  AND each_fit_partition_distinct_game_dates >= 100
  AND development_plus_selection_direct_rows_per_official_status >= 100
  AND holdout_direct_rows_per_official_status >= 30
  AND marcel_paired_holdout_players >= 100
  AND injury_conversion_overlap_report_complete
  AND all_required_provenance_fields_non_null
```

`each_fit_partition` means 2023-24, 2024-25, and 2025-26 after applying the
same population and direct-label rules. The five official statuses are `out`,
`doubtful`, `questionable`, `probable`, and `available`.

`marcel_paired_holdout_players` counts only holdout players with zero unknown
opportunities in the holdout and direct opportunity histories in each of the
three immediately prior seasons needed by the Marcel reference.

If any term is false, the result is `FIT_VETOED_DATA`. No candidate is fit, no
outcome is released, and no threshold is relaxed. The report may recommend
collecting more evidence, but it may not change this predicate. A changed
predicate is v2.

### Split artifact

If `PROCEED` is true, the custodian writes a split manifest containing every
eligible stable `(player_id, game_id)` key, partition, mode, label-availability
flag, report stratum, report era, and provenance digest. The manifest publishes
counts and exclusions by partition, incorporates the already-frozen
injury-conversion overlap-report hash from section 5, and hashes its canonical
sorted contents. The model worker receives development and selection labels
only. The holdout label package remains sealed.

---

## 4. Injury-report mapping and report regimes

At each prediction cutoff, assign exactly one report stratum:

| Stratum | Definition |
|---|---|
| `out`, `doubtful`, `questionable`, `probable`, `available` | Latest canonical official player status strictly before the cutoff |
| `not_on_report` | The team submitted a parseable report for the game and the at-risk player is not listed |
| `not_yet_submitted` | The latest eligible artifact explicitly marks the team `NOT YET SUBMITTED` |
| `unparsed` | An artifact was fetched for the team-game but its relevant block, status, or identity could not be parsed canonically |
| `no_report` | No eligible report artifact exists before an in-season cutoff |
| `draft_morning_no_report` | The target game is still in the future at the registered draft-morning cutoff |

These strata are never collapsed into `available`, `questionable`, or non-play.
Every exclusion and outcome count is reported by stratum.

The report era is also frozen:

- `legacy_hourly`: source date before 2025-12-22;
- `short_lead_fifteen_minute`: source date on or after 2025-12-22;
- `no_report_era`: no eligible report artifact exists.

The published injury-status-conversion constants are context only:

| Status | Published conversion probability |
|---|---:|
| `out`, `doubtful` | 0.0008725 |
| `questionable` | 0.5405882 |
| `probable`, `available` | 0.8585599 |

They are **not** model inputs, predictor values, intercept adjustments, labels,
targets, hyperparameters, or activation thresholds in this protocol because
their 2025-26 source rows overlap the proposed holdout. The pooled,
legacy-only, and short-lead-only values in `injury-status-conversion.md` remain
eligible only for that narrower study and runtime mapping. Report era is a
required evaluation stratum, not a fitted interaction in availability v1.

---

## 5. Known overlap with injury-status conversion

This availability holdout is not cleanly independent of the earlier
injury-status-conversion study. The repository already publishes its aggregate
results and the author has read its model card.

The consumed 2025-26 injury-conversion partitions are:

| Partition | Dates | Direct rows |
|---|---|---:|
| Development | 2025-10-21 through 2026-01-13 | 6,112 |
| Selection | 2026-01-14 through 2026-03-01 | 3,546 |
| Holdout | 2026-03-02 through 2026-04-12 | 3,940 |

The proposed availability holdout spans all three date partitions. The exact
stable-key overlap is not currently published and may not be guessed from
these counts. Before `PROCEED` can be true, the custodian must publish and hash
a separate **pre-split overlap report**, for each injury-conversion partition:

- exact overlapping `(player_id, game_id)` count;
- exact overlap digest over the sorted stable keys;
- availability report-stratum and exclusion counts for those keys; and
- whether each overlapping key was used in injury-conversion fitting,
  selection, or evaluation.

This overlap census uses membership and provenance only; it does not release an
availability outcome to the model worker.

`injury_conversion_overlap_report_complete` is true only when this report
contains all four fields above for all three partitions, its stable-key digests
reproduce, and its hash is frozen before the split manifest is created. The
later split manifest references that frozen hash; it does not create the report
that gates it.

The constants contain aggregate information from 2025-26 and the availability
holdout includes overlapping player-games. Disclosure and the exact overlap
report do not erase that contamination, so this protocol excludes the constants
from every candidate and baseline. The overlap report remains binding evidence
of the prior study's outcome exposure and must accompany any claim that the
availability holdout was not consumed during fitting.

---

## 6. Estimator family and deterministic implementation

Both modes use one estimator family:
`sklearn.linear_model.LogisticRegression`.

The fixed configuration is:

```text
penalty="l2"
C=1.0
solver="lbfgs"
fit_intercept=True
class_weight=None
max_iter=5000
tol=1e-10
warm_start=False
random_state=250141
```

There is no regularization grid and no alternate estimator. A failure to
converge to the configured tolerance is a fit veto, not permission to change
the solver or tolerance.

Continuous predictors are winsorized to the development partition's 1st and
99th percentiles, then standardized with the development mean and population
standard deviation. A zero-standard-deviation predictor becomes the all-zero
column and is reported. Binary predictors are not standardized. Categorical
levels use the literal closed vocabularies in this protocol and lexicographic
column order. Unknown categories fail before fitting.

In-season report stratum is one closed categorical predictor with the literal
levels in section 4 and `no_report` as its reference level. No numerical
injury-conversion probability enters. Draft-morning Candidate 1 is
intercept-only because every row has the registered
`draft_morning_no_report` stratum.

The exact Python, scikit-learn, NumPy, and BLAS versions, thread count, and
implementation source hash are written into the implementation manifest.
Thread count is fixed to one for fitting and reproduction.

---

## 7. Candidate ladder

Candidates are separate for each mode and advance only in this order.

### Reference baselines - not candidates

1. **Refitted constant:** the Jeffreys-smoothed training play rate,
   `(plays + 0.5) / (direct_rows + 1)`, refitted on development plus selection
   after structure selection.
2. **Marcel seasonal reference:** section 11. It is season-level context, not a
   per-game candidate.

### Candidate 1 - report state only

In-season Candidate 1 uses only the report-stratum indicators in section 4.

Draft-morning Candidate 1 is intercept-only because every future game is
`draft_morning_no_report`. It is intentionally equivalent in information to
the refitted constant baseline; a contextual draft-morning model must advance
beyond it.

### Candidate 2 - Candidate 1 plus one direct-history feature

Add one trailing play-rate feature over the player's last **20 classified
direct opportunities** strictly before the applicable decision cutoff. Unknown
opportunities do not enter its numerator or denominator.

The smoothing rule is fixed:

```text
trailing_play_rate_20 =
  (trailing_plays + 5 * development_mode_base_rate)
  / (trailing_direct_opportunities + 5)
```

The pseudocount is exactly five equivalent opportunities. With no direct
history the feature equals the development mode's base rate. No 10-game,
40-game, exponentially weighted, or adaptively chosen alternative is tested.

### Candidate 3 - Candidate 2 plus calendar context

Add these schedule-derived fields only:

- `second_night_back_to_back`;
- `days_rest`, capped to `[0, 7]`;
- team games including the target in trailing 4, 5, and 6 calendar days; and
- `home_game`.

All are calculated from the published team schedule without using the player's
participation outcome.

### Candidate 4 - Candidate 3 plus workload context

Add:

- season-to-date minutes strictly before the applicable decision cutoff;
- career NBA regular-season minutes strictly before that cutoff; and
- recent minutes spike: minutes in the 7 calendar days before that cutoff minus
  one quarter of minutes in the 28 calendar days before that cutoff.

For draft-morning mode the applicable cutoff is the one frozen timestamp in
section 1 for every future target game. No game, minutes, or participation after
that timestamp may alter a draft-morning predictor.

Game logs may supply these predictor fields but still may not supply labels.
Candidate 4 is contingent on section 9's workload veto.

### Deliberate v1 omissions from the plan

V1 does not fit age, tenure, road-trip length, time zones, body-part recurrence,
injury-history embeddings, playoff position, elimination probability, tanking
posture, contract situation, coaching intent, or learned player-specific B2B
effects. The current repository does not establish complete, time-correct
provenance for all of them, and adding them would break the ordered test of
history before calendar before workload. They require a prospective v2 rather
than opportunistic inclusion.

---

## 8. Selection and deterministic tie-breaking

Fit every eligible candidate on development and score it on selection.

A candidate advances over its immediate predecessor only when:

1. predecessor Brier minus candidate Brier is at least `0.0050000000`; and
2. absolute candidate CITL is no more than `0.0100000000` worse than absolute
   predecessor CITL.

Scores are computed in IEEE-754 float64 and compared without rounding. Equality
at either boundary advances only when both conditions pass; any other tie keeps
the simpler candidate. Candidate 4 must first clear section 9.

Stop at the first candidate that fails. Later candidates are not considered.
Refit the selected structure, Candidate 1, and the constant baseline on the
same development-plus-selection rows with unchanged configuration and
preprocessing rules before any holdout prediction. If the selected structure
is Candidate 1, the contextual availability engine cannot activate because
section 12 requires held-out superiority over Candidate 1.

No holdout result participates in selection.

---

## 9. Candidate 4 workload diagnostic and veto

Workload features are observational and population-selected. This protocol
does not claim a causal workload effect.

Before Candidate 4 can be scored for advancement, compute on the selection
partition:

```text
quartile_lift =
  mean(p4 - p3 for top season_to_date_minutes quartile)
  - mean(p4 - p3 for bottom season_to_date_minutes quartile)
```

Quartiles are deterministic equal-count groups after sorting by
`(season_to_date_minutes, game_id, player_id)`; remainder rows are assigned to
the lowest-numbered quartiles.

Candidate 4 is vetoed if **either**:

- `quartile_lift > 0.0200000000`; or
- any standardized workload coefficient is `> 0.1000000000` log-odds.

There is no "unless explained by other features" exception. Crossing either
numeric boundary excludes Candidate 4 regardless of Brier improvement. Report
the coefficients, quartile counts, and `quartile_lift`.

The selection-stage interval for `quartile_lift` uses 2,000
evaluation-only player-cluster bootstrap resamples with seed `250146`.
Recompute the quartiles and lift in every resample. Report the two-sided 95%
percentile interval using the linearly interpolated empirical 0.025 and 0.975
quantiles (`numpy.quantile(..., method="linear")`). The interval is
diagnostic-only: Candidate 4 eligibility uses the two point-estimate thresholds
above, not either interval endpoint. Any non-finite resample, failure to produce
all 2,000 resamples, or failure to reproduce with the seed vetoes Candidate 4.

If Candidate 4 reaches final evaluation, also report
`holdout_quartile_lift`, defined by the same formula on the holdout using the
final development-plus-selection refits of Candidates 3 and 4. Holdout
quartiles use the same deterministic ordering and remainder rule.

Passing this diagnostic does not remove survivor selection. The model card must
still state that workload is observed only among players healthy enough to
accumulate it and must report the remaining selection described in section 2.

---

## 10. Calibration metrics and deterministic bins

For every candidate and baseline, report:

- Brier score;
- CITL, defined as `mean(predicted) - mean(observed)`;
- ECE;
- maximum calibration error;
- clipped log loss, with clip `[1e-6, 1 - 1e-6]`; and
- a reliability table.

ECE uses ten deterministic equal-count bins. Sort rows by
`(predicted_probability, game_id, player_id)`. If `n = 10q + r`, bins `1..r`
receive `q + 1` rows and the remaining bins receive `q` rows. Tied predictions
may therefore span adjacent bins, but the stable-id tie-break makes the result
reproducible. ECE is the count-weighted mean absolute difference between each
bin's predicted mean and observed rate.

Observed rates in finite samples are **not required to be monotonically
non-decreasing**. The reliability table reports every adjacent inversion and
its intervals; a noisy observed inversion is not itself proof that predicted
probabilities are unordered. The old exact-monotonicity activation wording is
withdrawn.

All metrics are reported overall and by mode, report stratum, report era,
pre-/post-All-Star break, and pre-/post-trade-deadline. Strata below 30 direct
holdout rows report counts only.

---

## 11. Marcel comparison on the identical eligible cohort

The previously published `14.32` MAE came from a different study, cohort, and
outcome construction. It is context only and is not an activation threshold.

For this protocol, recompute Marcel on the exact holdout player cohort counted
by `marcel_paired_holdout_players` in section 3:

```text
marcel_rate =
  0.75 * (
    (5 * play_rate_2024_25
     + 4 * play_rate_2023_24
     + 3 * play_rate_2022_23) / 12
  )
  + 0.25 * historical_population_play_rate
marcel_expected =
  sum(marcel_rate over the player's eligible 2025-26 opportunities)
```

Each historical play rate uses the same independently enumerated opportunity
population and direct-label rules as the availability model. The model and
Marcel are compared for the same players, same 2025-26 opportunity keys, and
same actual direct outcomes.

`historical_population_play_rate` is the pooled direct play rate over those
same paired players and their eligible 2022-23 through 2024-25 opportunities.
This reproduces the documented 3/4/5 chronological weighting (5/4/3 from newest
to oldest) and 25% shrinkage toward the cohort mean while recomputing every
input on this protocol's eligible cohort. No 2025-26 outcome enters Marcel.

For each player compute absolute season error for the selected model and
Marcel. Report the paired mean difference
`selected_absolute_error - marcel_absolute_error` with a player-cluster
interval. Activation requires its upper 95% endpoint below zero in each mode.
Also publish player count, opportunity count, exclusions, and the exact cohort
digest. No commercial games projection enters.

---

## 12. Held-out activation and vetoes

The independent evaluator runs the frozen final models on the sealed 2025-26
holdout once. A mode activates only if every condition passes:

1. the selected structure is Candidate 2, 3, or 4;
2. the upper 95% endpoint for paired held-out Brier
   `(selected - Candidate 1)` is below `0`;
3. the upper 95% endpoint for paired held-out Brier
   `(selected - refitted constant)` is below `0`;
4. point `abs(CITL) <= 0.0500000000` and the complete required 95% CITL interval
   lies within `[-0.0500000000, +0.0500000000]`;
5. point `ECE <= 0.0500000000` and every required 95% ECE interval has upper
   endpoint `<= 0.0500000000`;
6. the paired Marcel error interval in section 11 has upper endpoint below `0`;
7. every census, opportunity, split, implementation, overlap, and exclusion
   count and hash reproduces exactly; and
8. section 13 produces every required finite uncertainty interval.

Any failure is `ACTIVATION_VETOED`. Publish the offline evidence and veto, but
add no runtime release, persistence, API, UI, expected-games wiring, or
valuation input.

Candidate 1 remains a comparison baseline. The separate frozen
injury-status-conversion mapping remains independently eligible for its
narrower runtime use; it is not part of Candidate 1 and cannot activate this
broader availability model.

---

## 13. Repeated measures, feasibility budget, and uncertainty

Players repeat across games and game dates share league conditions.

### Pre-unblind feasibility test

Before holdout release, run 25 full-pipeline player-cluster resamples using
development and selection only, seed `250141`. Record wall time, peak resident
memory, convergence failures, and platform. Extrapolate wall time linearly to
1,000 resamples.

The full-refit primary is feasible only if:

- projected wall time is at most 4 hours;
- peak resident memory is at most 16 GiB; and
- all 25 pilot fits converge.

This feasibility verdict and its raw timings are frozen in the implementation
manifest before holdout release.

### Primary and one fallback

If feasible, the primary interval uses 1,000 full-pipeline player-cluster
bootstrap resamples, seed `250142`. Each resample draws from the union of
distinct players appearing in any partition and carries each sampled player's
multiplicity through every partition where that player appears. It refits the
selected structure, Candidate 1, and the constant baseline on the same
resampled development-plus-selection rows, then evaluates only the resampled
holdout rows. When Candidate 4 is selected, Candidate 3 is refit on those same
rows for the holdout workload diagnostic.

The **only fallback** is a 5,000-resample evaluation-only player-cluster
bootstrap of the already frozen selected, Candidate 1, constant, and when
needed Candidate 3 models, seed `250143`. It is used only when the pre-unblind
feasibility rule rejects the full refit. It omits fitting uncertainty, and the
model card must say so.

### Required secondary dependence checks

Regardless of primary or fallback, also compute:

1. a 5,000-resample evaluation-only game-date block bootstrap, seed `250144`;
2. a 2,000-resample two-way player x game-date pigeonhole bootstrap, seed
   `250145`.

Both secondary checks use the same frozen final-model and comparator
predictions as the fallback. They resample holdout evaluation rows only and do
not refit.

Use two-sided percentile 95% intervals for paired Brier differences, CITL, ECE,
Candidate 4 `holdout_quartile_lift`, paired Marcel error, and seasonal-games
MAE. Every endpoint is the linearly interpolated empirical 0.025 or 0.975
quantile (`numpy.quantile(..., method="linear")`). Activation uses the least
favorable bound across the player, date-block, and two-way intervals. The
selection-only `quartile_lift` interval remains the separate Candidate 4
eligibility diagnostic in section 9.

Every registered resample must produce every applicable finite statistic. Any
fit failure, empty required evaluation population, non-finite statistic,
missing resample, or failure to reproduce with the registered seed vetoes the
mode. Failed resamples are never dropped, retried with a new seed, or replaced.
Naive row-level intervals are never substituted.

---

## 14. Cohort, exclusion, and report reproduction

The evaluator must reproduce, before reporting a score:

- direct and opportunity census hashes;
- split-manifest hash and exact stable keys;
- implementation source and dependency-lock hashes;
- every included row count by season, partition, mode, report stratum, and era;
- every exclusion count by reason and the corresponding stable-key digest;
- the injury-conversion overlap counts and digests in section 5;
- preprocessing parameters and feature-column order; and
- Candidate 4 diagnostic inputs when applicable.

Any mismatch vetoes evaluation. It is not rounded away or reconciled manually.

---

## 15. Output shape and calibration context

The following JSON is **illustrative only**. It is not an API, persistence, or
schema commitment:

```json
{
  "player_id": 12345,
  "game_id": 67890,
  "mode": "in_season",
  "marginal_p_play": 0.72,
  "model_version": "availability-v1-<release-hash>",
  "population_version": "<opportunity-report-hash>",
  "report_stratum": "not_on_report",
  "report_era": "short_lead_fifteen_minute",
  "features": {
    "trailing_play_rate_20": 0.85,
    "second_night_back_to_back": false,
    "days_rest": 2
  },
  "calibration_context": {
    "eligible_population": "direct-outcome holdout",
    "equal_count_bin": 7,
    "bin_observed_rate": 0.74,
    "bin_n": 342,
    "model_citl": 0.003,
    "model_ece": 0.021
  }
}
```

Every stored probability must retain the exact population, split, model,
inputs, cutoff, report stratum, and calibration release that produced it.
ADR-018 governs display: calibration context is adjacent, toggleable, and
non-blocking. Model activation remains governed by this protocol; the display
badge does not override an activation veto.

---

## 16. Freeze identity, implementation lineage, and release identity

The accepted protocol is identified by:

- the exact Git commit containing this file; and
- the later owner-acceptance commit naming that protocol commit.

A chat statement, PR approval without an exact commit, or mutable branch name
does not bind the protocol.

Before development labels are released, the implementation manifest must bind:

- protocol commit and owner-acceptance commit;
- direct-census and opportunity-report SHA-256 values;
- canonical split-manifest SHA-256;
- feature/configuration manifest SHA-256;
- implementation source-tree SHA-256;
- dependency-lock SHA-256;
- development and selection package identities; and
- all RNG seeds in this protocol.

Before holdout release, add the final-training artifact SHA-256 and independent
evaluator identity. The runtime release hash covers the accepted protocol,
implementation manifest, final fitted parameters, calibration evidence, and
all input identities. A change to any component creates a new release; it never
inherits the old calibration claim.

---

## 17. Explainability

Every prediction must support:

1. the mode and decision cutoff;
2. the report stratum and report era;
3. the exact 20-opportunity history rows and smoothing base;
4. calendar and workload predictor values;
5. standardized logistic coefficients and signed log-odds contributions; and
6. the population and calibration bin in which the prediction was evaluated.

This is association evidence, not a causal explanation.

---

## 18. Backtest sequencing and durable harness

`availability-model` and `availability-backtest` may be released in one atomic
PR so no runtime model exists without held-out evidence. Atomic release does
not erase the backlog boundary.

The implementation must retain a distinct, rerunnable
`availability-backtest` harness with:

- its own command entry point;
- synthetic contract tests that do not use the sealed holdout;
- explicit inputs for the frozen manifests and release;
- deterministic seeds and machine-readable output; and
- a refusal to run a second final evaluation for the same freeze id.

The fit PR may mark both backlog items done only if the harness, evidence,
model card, and eligible runtime release land together. If activation is
vetoed, `availability-backtest` may be complete while `availability-model`
remains pending or is explicitly recorded as rejected; the backlog must not
call a vetoed runtime model done.

---

## 19. Draft-day ceiling and downstream boundary

The owner-confirmed rule in `docs/what-draft-day-looks-like.md` remains:
availability adjusts comparisons among comparable players and must not overturn
a large talent gap. That is a downstream expected-games and valuation policy,
not a reason to alter this model's probability.

ADR-002 remains absolute. This model predicts play only. It consumes no
production projection, rank, AAV, dollar value, recommendation, or commercial
games assumption. `expected-games` is the only later seam that may combine
availability and per-game production.

---

## 20. Transfer and shutdown limitations

Report held-out calibration separately before and after the All-Star break and
trade deadline. Do not fit a playoff-probability or tanking interaction in v1.
The 2025-26 holdout includes the shutdown regime and is not interchangeable
with draft-morning 2026-27 use.

Neither mode can see future trades, coaching changes, undisclosed injuries,
personal matters, warm-up setbacks, future roster eligibility, front-office
intent, a new collective-bargaining regime, or 2026-27 reporting drift.
Preseason mode cannot see future injury reports by construction. In-season mode
cannot turn `not_yet_submitted`, `unparsed`, or `no_report` into medical
evidence.

---

## 21. What this replacement changed

This replacement:

- removes the invented within-2025-26 fallback;
- makes both prerequisite backlog items binding fit vetoes and preserves their
  ownership split;
- makes game logs audit/features only, never fitting labels;
- binds one estimator family and exact configuration;
- separates draft-morning and in-season modes;
- orders one history window before calendar and workload candidates;
- registers the trailing-rate pseudocount;
- replaces MAE 14.32 as a threshold with a paired, same-cohort Marcel study;
- requires held-out Brier superiority over Candidate 1 and a refitted constant;
- defines deterministic equal-count ECE bins and corrects monotonic wording;
- gives Candidate 4 numeric diagnostics with no self-neutralizing exception;
- pre-registers a compute budget, one fallback, two dependence checks, fixed
  calibration thresholds, and an uncertainty veto;
- maps every no-status report state and declares report-era handling;
- discloses the exact known injury-conversion partitions and requires stable-key
  overlap counts before fitting, while excluding their contaminated conversion
  constants from availability candidates and baselines;
- states that outputs are marginal probabilities, not joint season
  distributions;
- binds protocol acceptance, implementation, split, and release hashes;
- preserves a distinct rerunnable backtest harness; and
- records the deliberate v1 omissions from the broader plan.

## 22. Owner decision

The owner must choose **accept** or **decline** for the exact protocol commit.
If accepted, the current result remains `FIT_VETOED_PREREQUISITES` until both
pending data tasks and every numeric pre-fit gate pass. If declined, no fit
occurs and a replacement protocol must be proposed without reading a new
holdout.
