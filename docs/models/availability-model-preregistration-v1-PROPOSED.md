# Availability model — preregistration v1

**Status: Proposed.** Written by `quant`; only the project owner accepts.
**Author:** quant
**Date:** 2026-08-31, pre-fit, pre-unblind

This document is a protocol. It is not a model card, does not claim the Model
gate, and emits no `p(play)`. The model card that eventually reports a result
is `availability-model.md`, which does not exist yet.

**Owner binding required before fit:**

1. Accept or reject this protocol.
2. Decide whether the `participation-ledger-population` evidence (once provided by
   the data-engineer session) is sufficient to define the at-risk population.
   Without that decision, the fit is blocked.

---

## 1. What this model predicts

**Prediction unit:** One player × one scheduled regular-season team game.

**Output:** A probability `p(play)` — the probability that the player appears in
the box score for that game. The output is a probability distribution expressed
as a point estimate with a stated calibration interval, never an unsupported
point certainty.

**At-risk population:** All player-games where the player is on a team's active
roster for the game date, excluding two-way players currently in the G-League
and players on suspension. The denominator is the set of games the player
*could have* played; absence from this set is not evidence of non-play.

**Population identification problem — unresolved.** The at-risk population
requires authoritative historical roster intervals: "player X was on team Y's
roster from date A to date B." The merged data currently lacks both:

- Authoritative roster transaction history (signings, trades, waivers with
  effective dates); and
- Proof that every game returned a complete participation payload (the R35
  gap: a full absence produces no row in any endpoint).

`reliability-metrics.md` already records this: *"Opportunity coverage cannot be
calculated because the merged data lacks both authoritative historical roster
intervals and proof that every game returned a complete participation payload."*

**Evidence required to unblock:** The data-engineer session is re-deriving
this. The fit is blocked until one of:

(a) Authoritative roster intervals are available and validated, making the
    denominator identifiable. The evidence is a coverage report showing that
    for each team-game in the fitting window, the set of rostered players is
    known, and the participation outcome for each is either directly observed
    or explicitly marked as missing coverage.

(b) A principled alternative denominator is defined that does not require roster
    intervals — for example, restricting the at-risk population to players with
    at least one observation in a trailing window, which makes the estimate
    conditional on recent appearance. That conditioning must be stated in the
    model card and makes the model unsuitable for players newly acquired by
    trade, which must be disclosed.

**Until one of (a) or (b) is resolved and accepted by the owner, this protocol
blocks the fit.** Manufacturing a denominator from silence is the error R35
exists to prevent.

---

## 2. Outcome mapping under R35

A `played` participation row or a game-log row is direct evidence of play.
`did_not_play`, `did_not_dress`, `not_with_team`, and `inactive` are direct
evidence of non-play. `unknown` and missing rows are **excluded, not counted
as non-play**. The model is fitted only on directly observed outcomes.

Every fitted observation must trace to a `player_participation` row with a
non-null `outcome` and a valid `game_id` anchored to a resolved `nba_games`
row. Missing participation rows for rostered players are coverage gaps; they
reduce effective sample size but do not create false non-play labels.

The exclusion count and its breakdown by reason are reported in the model card.

---

## 3. Temporal split and holdout integrity

**Split:** Three-season chronological split over 2023-24, 2024-25, and 2025-26
regular seasons.

| Partition | Season | Purpose |
|---|---|---|
| Development | 2023-24 | Feature engineering, candidate exploration |
| Selection | 2024-25 | Model selection, hyperparameter tuning |
| Holdout | 2025-26 | Final evaluation, reported once, never revisited |

The holdout is the 2025-26 season. It is **not** the same partition used for
injury-status-conversion's holdout (the last 41 game-dates of 2025-26). The two
models use different temporal grains — injury conversion splits within a season
by game-date; this model splits across seasons. There is no silent optimization
of this holdout from having seen injury-conversion results, because:

1. The injury-conversion model's emitted probabilities are three constants
   (0.0008725, 0.5405882, 0.8585599) per status band — they carry no
   player-specific or game-specific information from the 2025-26 holdout.
2. The availability model consumes these as a conditional feature input (§5),
   not as a label or target. Seeing that `questionable` converts at ~54% on
   the 2025-26 holdout tells us the prior's calibration, not the individual
   outcomes the availability model must predict.

**If the development season (2023-24) lacks sufficient participation data** due
to the population problem in §1, the split degrades to:

| Partition | Season | Purpose |
|---|---|---|
| Development + Selection | 2024-25 | Combined fitting and selection |
| Holdout | 2025-26 | Final evaluation |

This is weaker and must be disclosed. The two-partition fallback may not use any
cross-validation result to select among candidates and then also report that CV
result as the primary evidence — the holdout is the only evaluation.

---

## 4. Candidate ordering and simplest baseline

Candidates are considered in **strict complexity order** and advanced only when
the more complex model demonstrates a **pre-registered improvement** over its
simpler predecessor on the selection partition.

### Candidate 0: Seasonal-games average (the MAE 14.32 baseline)

A Marcel-style weighted average of prior-season games played, converted to a
per-game rate by dividing by team scheduled games. This is the model that any
contextual alternative must beat (ADR-007 amendment, 2026-08-22). It produces a
single season-level expected-games figure, not a per-game `p(play)`.

**Measured:** MAE 14.32 games on held-out seasons for players with three prior
seasons (n=500), versus 15.77 for last-season-only and 15.90 for the constant
league mean.

This candidate is a calibration reference, not a per-game probability model. If
no candidate below beats it when aggregated to season totals, **the engine
should be simplified accordingly** (ADR-007).

### Candidate 1: Status-only prior (the baseline per-game model)

For each game, the player's most recent pre-game injury-report status determines
`p(play)` via the frozen injury-status-conversion estimates. Players with no
report status receive a population base rate from their seasonal-games average.

This is the simplest per-game probability model and the true baseline for
calibration comparison. It uses no history, no schedule, and no player features
beyond report status.

### Candidate 2: Status + direct-history + calendar

Extends Candidate 1 with:

- **Direct participation history:** Observed play rate over the player's last N
  games (where N is a pre-registered window, proposed: 10, 20, 40), excluding
  missing observations. This is a trailing empirical frequency, not a modelled
  trend.
- **Calendar features:** Back-to-back indicator, days of rest since last game,
  games in the trailing 7 days (density), road/home indicator.

These features are purely observational and do not carry the selection-bias
risk described in §6. They describe the game's context, not the player's
workload history.

### Candidate 3: Status + history + calendar + age/tenure

Extends Candidate 2 with:

- **Age** at game date.
- **Career NBA seasons** (tenure).

These are background risk factors that do not depend on game participation. Age
and tenure are known for every player regardless of whether they have appeared.

### Candidate 4 (contingent, may be excluded): Workload features

Extends Candidate 3 with:

- **Season minutes total** (trailing, this season only).
- **Career cumulative minutes.**
- **Recent minutes spike** (deviation from personal trailing average).

**These features are subject to the healthy-worker survivor effect described in
ADR-007's amendment.** See §6 for the identification strategy. **Candidate 4 is
advanced only if §6's diagnostic passes and the owner accepts the stated
limitation.** If the diagnostic fails or the owner declines, Candidate 4 is
excluded and the protocol proceeds with Candidate 3 as the ceiling.

### Advancement criterion

A candidate advances over its predecessor if it achieves:

- A reduction in selection-partition **Brier score** of at least 0.005; **and**
- No degradation in selection-partition **calibration-in-the-large (CITL)**
  beyond ±0.02 absolute.

The threshold 0.005 matches the injury-status-conversion protocol. If no
candidate beyond Candidate 1 advances, Candidate 1 is the selected model.

---

## 5. How the frozen injury-status conversion enters without leakage

The injury-status-conversion model emits three probabilities for three status
bands. These enter as a **conditional prior feature**, not as a fitted
parameter:

1. For each player-game with a pre-game injury report, the report's status maps
   to the frozen conversion probability: `out`/`doubtful` → 0.0008725,
   `questionable` → 0.5405882, `probable`/`available` → 0.8585599.

2. This probability enters the availability model as a **fixed input feature**.
   It is never re-estimated from the availability model's own training data.

3. The conversion probabilities are constants derived from a separate fitting
   procedure on a separate (partially overlapping) cohort. They are not updated,
   blended, or shrunk toward the availability model's observations.

**Leakage analysis:** The injury-conversion model was fitted on 2025-26
development+selection (first 123 game-dates). Its estimates are aggregate rates
that carry no individual player-game outcome information. The availability
model's 2025-26 holdout partition will contain individual player-games that
contributed to those aggregates, but the conversion probability is the same
constant for every `questionable` game regardless of outcome — it cannot
overfit to individual holdout rows.

The residual concern is that the conversion model's calibration was measured
on the same 2025-26 season that serves as the availability holdout. This means
we know the conversion prior is well-calibrated for 2025-26 specifically.
**This is disclosed but not disqualifying** — the prior's calibration is a
property of the reporting environment, not a player-specific or game-specific
information leak.

---

## 6. Identification strategy and the healthy-worker survivor effect

### The problem

ADR-007's amendment documents `arXiv:2603.26935` and our own reproduction:
total minutes → next GP has r = +0.521, showing that conditioning on game
participation induces collider bias. A model fitted on game-log workload
features without an identification strategy will learn that workload is
protective, and will be confidently, invisibly wrong.

### The strategy

**This model does not claim causal estimates and does not attempt to recover
the causal effect of workload on availability.** The identification strategy is
**explicit conditioning with stated limitations**, not causal inference:

1. **Candidates 1–3 do not use workload features.** Status, participation
   history, calendar, age, and tenure are not collider-affected by the
   selection mechanism. A player's age does not change because he played.
   Calendar features (B2B, rest days) are properties of the schedule, not of
   participation.

2. **Participation history (Candidate 2+) is a trailing empirical rate, not a
   workload measure.** It describes *whether* the player appeared, not *how much*
   he played when he did. It is affected by selection in a different way: a
   player must have appeared to have a non-zero history. This is disclosed as a
   conditioning limitation: the model's estimate for a player with zero recent
   observations is driven entirely by the status prior and population base rate.

3. **Candidate 4's workload features are explicitly flagged.** If Candidate 4
   is considered, the model card must report:
   - The sign of the workload coefficient (if positive after controlling for
     other features, the survivor effect is likely dominant);
   - A diagnostic comparison: Candidate 3's predictions versus Candidate 4's
     on the selection partition, stratified by workload quartile. If Candidate
     4 shows higher `p(play)` for higher-workload players in a way that is not
     explained by other features, the survivor effect is likely leaking in;
   - **The model card must state:** "Workload-derived features carry a
     selection-induced sign risk. The estimate is conditional on having appeared.
     It should not be read causally."

4. **The population estimate is conditional on the denominator in §1.** Under
   option (b), it is explicitly conditional on recent appearance. The model does
   not estimate availability for players who have never been observed.

### What this strategy cannot do

It cannot separate "heavy minutes are protective" (survivor effect) from
"durable players earn heavy minutes" (true positive association) from "heavy
minutes cause injury" (true negative association). The honest position is that
on observational game-log data, with no treatment model and no IPW, these are
confounded and will remain so. The model's estimate is *predictive* — "given
what we observe, what do we expect?" — not *causal*.

**The paper's remedy (marginal structural model with IPTW) requires a treatment
model over the full at-risk population, which we do not have** (same
denominator problem as §1). The honest expectation before draft day is that we
can detect this bias but not correct it.

---

## 7. Schedule-density and direct-history features — allowed list

Features are partitioned into three classes based on their relationship to
participation selection:

### Class A: Not selection-affected (allowed in all candidates)

- Game-date calendar features: day of week, month, back-to-back indicator,
  games in trailing 7/14 days, days of rest, home/away
- Player demographics: age, career seasons
- Injury-report status (frozen conversion probability)

### Class B: Selection-conditioned (allowed with disclosure)

- Trailing observed play rate (last 10/20/40 games) — conditioned on having
  at least one observation in the window. Players with zero observations
  receive the population base rate. This conditioning is disclosed.

### Class C: Survivor-affected (Candidate 4 only, with §6 diagnostics)

- Season total minutes, career total minutes, recent minutes deviation.
  These features mechanically encode the survivor effect: players who play
  more have, by definition, been healthy enough to play.

No feature outside this list may be added without a protocol amendment (v2).

---

## 8. Explicit treatment of ADR-007's healthy-worker/collider warning

This section exists because ADR-007's amendment requires the model to "state
its identification strategy before it fits anything."

**Statement:** This model's predictions are conditional on:

1. The player being in the at-risk population (§1's denominator);
2. The player having a recent participation observation (for Class B features);
3. The frozen injury-conversion prior being calibrated for the current reporting
   environment.

The model does not claim that its features cause availability or that its
coefficients have a causal interpretation. The workload-is-protective paradox
(r = +0.521 for total minutes → next GP) is acknowledged as present in our data
and is addressed by feature-class separation rather than by a causal model.

**A model that uses only Class A and B features is not the paradox**, because it
does not condition on a collider between latent fitness and participation.
Calendar features are assigned by the schedule, not by health. Trailing play
rate is a direct observation of the outcome variable's own history, which
creates serial correlation but not collider bias. Age and tenure are
pre-treatment covariates.

**Candidate 4 introduces the collider.** Season minutes is a post-treatment
variable that is simultaneously caused by latent fitness and causes future
availability. The diagnostic in §6.3 is the check; the limitation in §6.3's
bullet is the disclosure.

---

## 9. Model-gate metrics and activation/veto conditions

Calibration is the primary evidence. Accuracy (AUC, accuracy) is secondary.

### Primary metrics (reported for every candidate)

| Metric | Purpose |
|---|---|
| Brier score | Proper scoring rule; decomposes into calibration + resolution |
| CITL | Calibration-in-the-large: mean(predicted) − observed rate |
| ECE | Expected calibration error across decile bins |
| Maximum calibration error | Worst single-bin deviation |
| Reliability diagram | Visual calibration across probability deciles |

### Activation conditions (must all pass for the selected model to activate)

1. **Calibration-in-the-large:** |CITL| ≤ 0.05 on the held-out season.
2. **Expected calibration error:** ECE ≤ 0.05 on the held-out season.
3. **No probability-decile reversal:** Within each decile, the observed rate
   must be monotonically non-decreasing across probability bins.
4. **Seasonal-games MAE:** When aggregated to per-player season totals
   (sum of `p(play)` over scheduled games), MAE must be < 14.32 games
   (the Marcel baseline from ADR-007). If it does not beat this, the engine
   should be simplified (ADR-007's flip condition is engaged).
5. **Minimum held-out observations:** At least 1,000 directly observed
   player-games in the holdout partition.
6. **Coverage disclosure:** The fraction of holdout player-games excluded
   due to missing observations must be reported. If exclusions exceed 20%
   of the at-risk population, the model card must flag the result as
   "limited-coverage" and the owner must decide whether to activate.

### Veto conditions (any one blocks activation)

- The MAE 14.32 comparison (condition 4) fails.
- The identification diagnostic for Candidate 4 (§6.3) shows the survivor
  effect is dominant and no simpler candidate is selected.
- The owner declines to accept the population definition (§1).

---

## 10. Uncertainty and repeated-measures structure

Player-games are not independent. The same player contributes dozens of
observations, and games on the same date share league-wide conditions.

### Bootstrap specification

The primary confidence interval uses a **cluster bootstrap resampling players**
(not player-games). Each resample draws N players with replacement (where N is
the number of distinct players in the partition), takes all of each drawn
player's games, refits the model, and re-evaluates on the held-out season.

**Number of resamples:** 1,000 (pre-registered).

**Reported intervals:** 95% percentile intervals for Brier score, CITL, ECE,
and seasonal-games MAE.

If the cluster bootstrap is computationally infeasible (fitting the model 1,000
times), the fallback is a **player-clustered standard error** using the
delta method or sandwich estimator, with the limitation disclosed.

### If the model cannot account for repeated measures

If neither a cluster bootstrap nor a clustered standard error is feasible, the
model card must:

1. Report the naive (unclustered) interval with an explicit warning that it
   understates uncertainty;
2. Report the effective sample size (number of distinct players, not
   player-games);
3. Widen the activation conditions: |CITL| ≤ 0.03 and ECE ≤ 0.03 (tighter
   thresholds to compensate for understated uncertainty).

---

## 11. Probability-distribution output

The model emits a **point probability with a calibration context**, not a bare
number:

```
{
  "player_id": 12345,
  "game_id": 67890,
  "p_play": 0.72,
  "model_version": "availability-v1-<hash>",
  "injury_status_prior": 0.8585599,
  "features": {
    "trailing_play_rate_20": 0.85,
    "b2b": false,
    "days_rest": 2,
    "age": 28
  },
  "calibration": {
    "decile_bin": 7,
    "bin_observed_rate": 0.74,
    "bin_n": 342,
    "citl": 0.003,
    "model_ece": 0.021
  }
}
```

Every stored `p(play)` records its model version, input features (for "why this
number?"), and the calibration context of the bin it falls in. The calibration
display follows ADR-018: rendered adjacent, blocking nothing, toggleable.

---

## 12. Model version and input lineage

Every emitted `p(play)` records:

- **Model version hash:** SHA-256 of the serialized model parameters.
- **Input versions:** Injury-conversion freeze id, participation-ledger
  coverage fingerprint, schedule version.
- **Feature vector:** The exact features used for this prediction, enabling
  "why this number?" at any point.

A stored prediction whose input versions no longer match current data is
marked stale and must be recomputed.

---

## 13. Driver evidence for explainability

The model card and every stored prediction must support answering "why is
this player projected for 61 games?" by reporting:

1. The player's base rate (seasonal average or population mean).
2. The contribution of each feature class: status prior, recent history,
   calendar, demographics, (workload if Candidate 4).
3. For tree-based models: feature importances or SHAP values.
4. For linear models: coefficients with standard errors.

The driver evidence is what makes "the tool said 61 games" into "the tool said
61 games because he sat 3 of his last 5 B2Bs, has a recent play rate of 0.78,
and was listed questionable."

---

## 14. Owner-confirmed ceiling

From `docs/what-draft-day-looks-like.md`, owner-confirmed 2026-08-29:

> *"At the end of the day, fifty games of an elite player is worth more than
> seventy or eighty games of a role player."*

**Availability adjusts a comparison between comparable players. It does not
overturn a talent gap.** Any recommendation that downgrades an elite player
below a durable role player has almost certainly over-weighted availability.

This is a constraint on the downstream expected-games fusion and valuation,
not on the availability model itself. The model estimates `p(play)` honestly;
the ceiling operates at the point where `p(play)` enters dollar values.

---

## 15. Shutdown-window and 2026-27 transfer limitations

### Shutdown window

The 2025-26 holdout includes games after the trade deadline and into the
shutdown window where eliminated teams rest veterans. The model must report
calibration separately for:

- Pre-All-Star-break games;
- Post-trade-deadline games;
- Games where the team's playoff probability was below 10% (if available).

These are reporting stratifications, not fitted interactions. They exist to
detect whether the model's calibration degrades in the window where shutdown
behaviour dominates.

### 2026-27 transfer limitations

**This model is fitted on 2023-24 through 2025-26 data and applied to 2026-27
predictions.** The fundamental limitation is that the 2026-27 league
environment (rule changes, load-management policies, new CBA provisions) is
not in the training data.

Specific limitations:

- **Roster turnover:** A player traded to a new team has no participation
  history on that team. The model falls back to status + base rate.
- **Rookie availability:** First-year players have no prior-season history.
  They receive the population base rate, which is disclosed as a weak prior.
- **Regime shifts:** If the NBA materially changes its load-management or
  rest-day policies, the model's calibration may degrade. The in-season
  calibration monitoring (§9's metrics computed on early-season games) is the
  detection mechanism.

---

## 16. What the model cannot see

Stated plainly, because the Model gate requires it:

- **Undisclosed injuries.** A player who is hurt but not on the report.
- **Front-office intent.** Whether a team plans to tank, rest a player for
  the playoffs, or manage minutes down the stretch.
- **Coaching decisions.** Rotation changes, matchup-based DNPs, and
  "coach's decision" rest that appears as a minor ailment on the report.
- **Trades and roster moves.** Until a trade happens, the model cannot
  price in the possibility. After a trade, the player's history with the
  new team starts from zero.
- **Personal matters.** Family emergencies, bereavement, mental health.
- **Post-report setbacks.** A player listed `available` at 5pm who
  re-aggravates in warmups.
- **Production conditional on playing.** This model predicts *whether*
  a player plays, not *how well*. ADR-002's separation is absolute.
- **Public-report truthfulness.** "Rest" is routinely laundered as a
  minor ailment. The injury-conversion prior inherits this limitation.
- **The causal effect of workload on injury.** Per §6 and ADR-007.

---

## 17. Comparison to the MAE 14.32 baseline

The seasonal-games MAE comparison required by ADR-007 and §9 condition 4:

1. For each player in the holdout season with at least one observation:
   `expected_games = sum(p(play))` over that player's scheduled team games.
2. `actual_games = count(played outcomes)` for that player in the holdout.
3. `MAE = mean(|expected_games - actual_games|)` across all eligible players.

The Marcel baseline uses `(3 × GP_{t-1} + 2 × GP_{t-2} + GP_{t-3}) / 6`
scaled to the current season's 82-game schedule.

**No commercial games-played assumption is used anywhere in this comparison.**
The Marcel weights are fixed (3/2/1), the GP figures come from our own
historical game-log counts, and the 82-game scale factor is the published
league schedule length. The model remains structurally independent of any
commercial source's games projection.

---

## 18. Resolving the availability-backtest sequencing problem

The backlog has `availability-backtest` depending on `availability-model`, and
the Model gate requires held-out calibration before merging. This creates a
sequencing paradox: the model cannot merge without a backtest, and the backtest
depends on the model.

### Resolution: Atomic completion unit

`availability-model` and `availability-backtest` are **one atomic PR**. The
model is fitted, the backtest is run, the model card is written, and the
evidence is committed in a single unit. There is no state where the model
exists without its backtest.

### Precise backlog treatment

No backlog change is made in this PR. When the fit PR is prepared:

- `availability-model` moves to `done` with the evidence and model card.
- `availability-backtest` moves to `done` in the same commit, because the
  backtest is embedded in the model's evaluation procedure.
- `expected-games` remains `pending` with its existing dependencies.

This is the same pattern as `injury-status-conversion`, which committed its
model card, evidence, and evaluation in one unit.

---

## 19. What this protocol recommends

**Favor Candidate 2 (status + history + calendar) as the likely v1.**

Reasoning:

1. Candidate 1 (status-only) is a strong baseline but cannot express "this
   player has been sitting out of B2Bs all season" or "this player just returned
   from a 10-game absence and has played 3 of his last 4."

2. Candidate 2 adds the most informative features without touching the
   survivor-effect minefield. Back-to-back sit patterns, rest days, and recent
   play rate are the three most actionable availability predictors a fantasy
   manager uses intuitively.

3. Candidates 3 and 4 add progressively more complexity with diminishing and
   potentially misleading returns. Age effects are real but small within a
   single season. Workload effects are real but confounded.

**If Candidate 2 does not beat Candidate 1 on the selection partition, ship
Candidate 1.** A well-calibrated status-only prior with a population base rate
is already more useful than a flat seasonal average, because it updates on
game day as injury reports arrive.

**If Candidate 1 does not beat the MAE 14.32 baseline when aggregated to season
totals, recommend simplifying the engine to a seasonal-average model per
ADR-007.** Document why and propose the simpler architecture.

---

## 20. What this protocol does not do

- **No fitting.** No parameter is estimated.
- **No unblinding.** No held-out outcome is inspected.
- **No runtime code.** No `p(play)` is emitted, stored, or served.
- **No consumer wiring.** `expected-games`, valuation, UI, and the overlay
  do not learn about this model.
- **No commercial games-assumption dependency.** The MAE 14.32 baseline
  and the Marcel weights use only historical game-log counts and the
  published 82-game schedule.

The population-identification blocker in §1 is the binding constraint. Until
the data-engineer session resolves it and the owner accepts the resolution,
this document is the complete deliverable for `availability-model`.
