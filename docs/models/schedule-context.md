# Schedule-context model card

**Status:** Implemented. Descriptive context is available. Blowout probability
v1 met the release calibration rule for display as context, but its improvement
over baseline is small and it is not approved to adjust minutes, valuation, or
automated decisions. Garbage-time suppression remains disabled.

## Purpose and output classes

Schedule context deliberately contains two different kinds of output:

1. **Descriptive derived facts:** off-night slate counts/percentiles, trailing
   pace, and opponent category allowances. These summarize observed schedule or
   box-score inputs and make no claim that a recommendation will improve.
2. **Decision-bearing model output:** blowout probability, defined as the chance
   that the final margin is at least 15 points. This passed the Model gate below.

`streaming_window_score` and `garbage_time_suppression` remain `NULL`. A
descriptive light-slate label or blowout probability is not evidence for the
size of a player-minutes effect, and the repository has no held-out calibration
supporting either number yet.

No schedule-density fact is computed here. Back-to-backs, rest days, rolling
calendar density, and road-trip structure remain in the data-engineer-owned
schedule-density contract. No playoff date or scoring-period count is assumed.

## Inputs and methods

### Off-night slates

For every date actually present in one season's `team_schedule`, count distinct
NBA games and compute its empirical midrank within that season's slate-count
distribution. `is_off_night` is the declared lower-quartile policy
(`off_night_percentile = 0.25`), not a calibrated claim about streaming value.
The derivation version records that threshold and formula. Consumers may display
the label; turning it into a recommendation requires separate outcome evidence.

### Pace and category defence

For each team fixture, use only games before the fixture date:

- expected pace is the mean of the team's and opponent's trailing 15-game pace;
- possessions are estimated as `FGA - OREB + TOV + 0.44 * FTA`;
- category defence is what the opponent allowed over its trailing 15 games,
  with counting categories normalized per 100 possessions;
- FG and FT retain summed makes and attempts plus the derived rate. Bare
  percentages are never averaged.

At least five prior complete games are required. Rows without enough strictly
as-of history are reported as skipped, not filled from a league-average default.
Every row stores the exact game IDs and feature cutoff in `input_snapshot`.
At the start of a season, the trailing window carries over the prior season
rather than manufacturing a league-average fallback; `input_snapshot` marks
`offseason_carryover = true` when the latest defensive-history game is more than
60 days before the fixture. Trades and rotation changes make those opening-week
profiles materially less trustworthy.

### Blowout probability v1

The feature is the absolute gap between the two teams' trailing 15-game average
point margins, computed before the game result enters either history. Three
equal-frequency feature bins were selected on a validation season. Each bin's
probability is its empirical blowout rate with beta(1, 1) smoothing.

This is intentionally simple. The feature's discrimination is weak. It has
slightly lower held-out squared probability error than the constant-rate
baseline, but its aggregate ECE (3.23%) is slightly worse than the constant
baseline's absolute held-out rate gap (3.11%). A more complex model is not
justified until independent inputs add measurable held-out value.

## Model selection and held-out evidence

The bin count was selected using 2023–24 for training and 2024–25 for
validation. The selected three-bin formulation was then refit on 2024–25 and
evaluated once on untouched 2025–26 regular-season games.

| Metric | Held-out result |
|---|---:|
| Training examples | 1,146 |
| Held-out examples | 1,225 |
| Brier score | 0.23314 |
| Constant-rate baseline Brier | 0.23464 |
| Expected calibration error | 0.03229 |

Calibration bins:

| Predicted | Observed | Games |
|---:|---:|---:|
| 0.3281 | 0.3444 | 453 |
| 0.3307 | 0.3267 | 352 |
| 0.3672 | 0.4405 | 420 |

The release rule enforced by the gate is Brier better than the training-rate
baseline and ECE at most 0.04. V1 passes both, but the Brier improvement is only
0.00150 and no significance claim is made. The highest-risk bin still
underpredicts by 7.3 percentage points, so consumers must show the probability
rather than translate it into a confident garbage-time minutes penalty.

The checked evidence is
`backend/tests/model_evidence/schedule_context_blowout_v1.json`; the
`model_backtest` tests enforce its split, counts, baseline comparison, calibration
limit, and pre-holdout model selection. Reproduce the live source run with:

```powershell
$env:PYTHONPATH = (Resolve-Path 'backend\src').Path
python -m hoops_gm.schedule_context.backtest
```

CI validates the committed evidence contract; it does not call the external NBA
source or independently recreate the 3,676 source games. The command above is
the reproducibility path, and a changed upstream result must produce a new
evidence/model version rather than editing v1 in place.

## Provenance, history, and rejection rules

Every persisted row binds to:

- `schedule_version`: current `nba-schedule` refresh for that season;
- `source_version`: the exact completed score/box-score observation fingerprint
  used at scoring time (the schedule fingerprint for slate-only rows);
- `model_version`: blowout training/specification version, or the deterministic
  off-night derivation version.

Lineage is keyed by artifact family and season. Publishing registers the source,
blowout-model, and off-night derivation cohorts. Persistence rechecks all three
inside its transaction, recomputes the source fingerprint, and holds row locks
on the same lineage scopes that publishers lock until the caller commits or
rolls back. Stale, unknown, or mismatched cohorts raise instead of writing.
Natural keys include all applicable versions, so a changed
source/model/schedule creates history rather than overwriting prior context.

The model version includes its training-source fingerprint separately from the
scoring-time source version. This preserves the distinction between the data
that fit the model and the observations used to score a future fixture.

## What this cannot see

- future injuries, late scratches, unannounced rest, or post-refresh schedule changes;
- trades, coaching changes, lineup and rotation changes;
- market point spreads, travel location during off-days, or front-office intent;
- player-specific garbage-time roles and coach substitution patterns;
- whether a light slate actually creates a usable fantasy roster slot.

These omissions are why pace/category context remains descriptive, blowout
probability stays visible as a probability, and suppression/streaming scores are
not published.
