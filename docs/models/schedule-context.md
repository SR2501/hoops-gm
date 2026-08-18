# Schedule-context model card

**Status:** Design and versioned output schema only. No trained model is approved for use.

## Purpose

`opponent_context` describes the expected game environment for a team's scheduled
fixture: pace, category defensive profile, blowout probability, and prospective
garbage-time suppression. `off_night_slates` describes whether a date is light
enough to affect streaming or lineup opportunity.

These are modelling outputs, not schedule facts. `team_schedule` remains the
source calendar and `schedule_density` remains pure calendar arithmetic.
Per ADR-002, context must not silently change per-game production or expected
games; it is an explicitly versioned conditioning input. Per ADR-007, it may
condition `p(play)` only through the availability-model seam.

## Provenance and refresh contract

Every row carries:

- `model_version`: the feature and model specification;
- `schedule_version`: the immutable identifier of the schedule snapshot used;
- `schedule_refreshed_at`: when that schedule snapshot was refreshed;
- `computed_at`: when the output was produced;
- `input_snapshot`: the auditable model-input summary.

The natural key includes `schedule_version`, so a changed schedule creates a
new output rather than overwriting a row derived from an earlier snapshot.
Schedule context must be recomputed at least weekly and whenever the schedule
version changes. Consumers must select one matching schedule/model version
cohort and reject stale or mismatched context rather than combining it with
newer projections, strength of schedule, or schedule inputs.

## Planned formulation

- Pace and category defence use a trailing 15-game window with recency weighting
  and shrinkage; percentage categories retain makes and attempts in the input
  snapshot rather than becoming bare percentages.
- Blowout probability targets a final margin of at least 15 points. Garbage-time
  suppression is an explicit output feature, not a hidden production adjustment.
- Off-night classification is per date, based on scheduled game count and the
  date's historical slate percentile. The persisted thresholds make the rule
  auditable.

## Required Model gate

Before any decision-facing use, run a held-out, time-ordered backtest that
reports calibration, not only accuracy:

- reliability plots, Brier score, and expected calibration error for blowout
  probability;
- calibration of garbage-time suppression against realized player minutes;
- baseline comparisons against season-average opponent features and a
  game-count-only off-night rule;
- error slices by season phase, home/away, team, and short schedule windows.

The model cannot see future injuries, late scratches, lineup changes, unannounced
rest, or post-refresh schedule changes. Its outputs must therefore never be
treated as a replacement for availability observations or live injury status.
