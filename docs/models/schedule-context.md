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
- `pace_possessions` is that raw per-game possession estimate. It is **not**
  normalized per 48 minutes, so overtime games contribute their observed longer
  game length rather than being scaled back to regulation;
- category defence is what the opponent allowed over its trailing 15 games,
  with counting categories normalized per 100 possessions;
- FG and FT retain summed makes and attempts plus the derived rate. Bare
  percentages are never averaged.

Only regular-season games enter v1 because its calibration cohorts contain only
regular-season games. A team-game box score is complete only when summed player
seconds equal 240 minutes plus 25 minutes per overtime, both teams have equal
totals, at least five players recorded positive minutes, and no player exceeds
the inferred game duration. For each fixture and team, every one of the last
`trailing_games` scored regular-season games must have a complete box score.
Missing recent observations fail the run before writes; they cannot be discarded
so that arbitrarily older valid games silently fill the trailing window.

At least five prior complete games are required. A run must produce context for
at least 95% of its regular-season schedule rows and must produce at least one
row; otherwise it raises before writing any slate or opponent output. Successful
runs persist eligible, produced, skipped, threshold, realized fixture coverage,
and aggregate recent-observation completeness/recency in every output's
`input_snapshot`. Opponent rows additionally store the exact last-N scored and
complete game IDs for both teams, their latest observation dates, recency in
days, team-minute totals, completeness rule, and feature cutoff. Rows without
enough strictly as-of history are not filled from a league-average default.
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

The 2024-25 source cohort contains 1,225 games, but refitting produces 1,146
training examples: 79 early games are cold-start drops because both teams do not
yet have the required same-season margin history. All 1,225 holdout games produce
examples because evaluation carries the 2024-25 history across the offseason
into 2025-26. This is also an explicit fit/serve asymmetry: fitting starts the
training season cold, while production scoring may carry prior regular-season
history into a new season. That mirrors the holdout path but makes early-season
display context especially exposed to roster and coaching turnover.

Calibration bins:

| Predicted | Observed | Games |
|---:|---:|---:|
| 0.3281 | 0.3444 | 453 |
| 0.3307 | 0.3267 | 352 |
| 0.3672 | 0.4405 | 420 |

The release rule enforced by the gate is Brier better than the training-rate
baseline and ECE at most 0.04. V1 passes both, but the Brier improvement is only
0.00150 and no significance claim is made. The highest-risk bin still
underpredicts by 7.3 percentage points. The gap is statistically significant
under a binomial normal approximation (`z = 3.12`, two-sided `p ~= 0.002`), not
just visually large, so consumers must show the probability rather than
translate it into a confident garbage-time minutes penalty.

The checked evidence is
`backend/src/hoops_gm/schedule_context/releases/schedule_context_blowout_v1.json`.
That is also the packaged production release artifact: publication accepts only
its allowlisted model version (`4809af29ed135f6f`) and loads the parameters from
that file. The registry parses it and pins a SHA-256 over canonical sorted,
compact JSON, so content changes are rejected while CRLF/LF checkout differences
do not create false mismatches. The loader independently derives the model
version from its source fingerprint and every fitted parameter. Locally fitted,
edited, or self-relabelled variants cannot be registered as production lineage. The
`model_backtest` tests enforce its split, counts, baseline comparison, calibration
limit, pre-holdout model selection, production-loader binding, and source
fingerprints. Reproduce the live source run with:

```powershell
$env:PYTHONPATH = (Resolve-Path 'backend\src').Path
python -m hoops_gm.schedule_context.backtest
```

CI validates the committed evidence contract; it does not call the external NBA
source or independently recreate the 3,680 source games. The command above is
the reproducibility path, and a changed upstream result must produce a new
evidence/model version rather than editing v1 in place.

The final training cohort fingerprint is `ea3f00ea22a4d703` over 1,225 completed
2024-25 games. The untouched evidence cohort fingerprint is
`e992a314295c442a` over 1,225 completed 2025-26 games (2025-10-21 through
2026-04-12). Selection training and validation cohorts are fingerprinted
separately as well. These identities cover game ID, date, teams, and final score,
so an upstream correction changes the evidence and requires a new release rather
than silently preserving the old calibration claim.

## Provenance, history, and rejection rules

Every persisted opponent row binds to:

- `schedule_version`: current `nba-schedule` refresh for that season;
- `source_version`: the exact completed score/box-score observation fingerprint
  used at scoring time, including player seconds and only regular-season games
  for both opponent and slate rows; slate rows retain this source lineage because
  their persisted coverage audit is source-derived;
- `opponent_derivation_version`: the deterministic pace/category-defence
  specification plus `trailing_games`, `minimum_history_games`, and the persisted
  coverage threshold;
- `blowout_model_version`: the separately pinned calibrated blowout release.

Off-night rows retain their own deterministic `model_version`; that version is
not reused for opponent context. The derivation and calibrated-model dimensions
stay separate so changing a descriptive history window does not claim a new
blowout fit, and changing the blowout release does not relabel pace/defence math.

Lineage is keyed by artifact family and season. Publishing explicitly activates
the source, opponent derivation, blowout-model, and off-night derivation cohorts.
Persistence rechecks every claimed cohort inside its transaction, recomputes the
source fingerprint, and holds the same transaction-level lineage locks that
source writers and publishers acquire until the caller commits or rolls back.
Stale, unknown, or mismatched cohorts raise instead of writing.
Natural keys include all applicable versions, so changed source, opponent
derivation, blowout model, or schedule cohorts create history rather than
overwriting prior context. Consumers select the explicitly activated versions;
they must not infer "current" with a maximum version string or reuse an older
row whose derivation configuration differs.

The blowout model version includes its training-source fingerprint separately
from the scoring-time source version. This preserves the distinction between the
data that fit the model and the observations used to score a future fixture.

## Base-rate drift and monitoring limits

The 2024-25 training blowout rate is 34.12%; that is not a permanent league
constant. Pace, parity, officiating, schedule policy, and late-season incentives
can shift the base rate even when the feature distribution appears similar.
V1 has one held-out season and no automated online calibration monitor. The
service records model, training, holdout, and scoring-source cohorts, but it does
not detect a live calibration drift threshold or automatically recalibrate.

V1 is intentionally allowed to serve 2026-27 **display-only** context; there is
no 2025-26-only season guard. That does not make its calibration current.
Before promoting it into any recommendation, minutes adjustment, valuation, or
automation, `quant` must re-run the time-ordered gate on a newly fingerprinted
holdout and inspect both overall base-rate movement and per-bin calibration.
Until enough current-season outcomes exist, consumers must show this as
historical-context probability, not imply that monitoring has proved
current-season calibration.

## What this cannot see

- future injuries, late scratches, unannounced rest, or post-refresh schedule changes;
- trades, coaching changes, lineup and rotation changes;
- market point spreads, travel location during off-days, or front-office intent;
- player-specific garbage-time roles and coach substitution patterns;
- whether a light slate actually creates a usable fantasy roster slot.

These omissions are why pace/category context remains descriptive, blowout
probability stays visible as a probability, and suppression/streaming scores are
not published.
