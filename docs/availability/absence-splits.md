# Absence splits

**Owner:** quant  
**Evidence version:** `absence-splits-descriptive-v1`  
**Status:** descriptive observation-layer evidence

## Claim boundary

An absence split says what one player produced in observed games with and
without a specific teammate. It does **not** estimate a causal effect, predict a
future role, or recommend adding, drafting, starting, or trading a player.

This explicit boundary keeps the output outside the Model gate. The later
`contingent-value` model may consume these facts, but its decision-bearing
numbers require held-out temporal validation, a model card, versioned output,
and documented blind spots before they can drive a recommendation.

## Inputs

- Final games from `team_schedule`/`nba_games`, stamped with the current
  season-specific schedule refresh version and time.
- `player_game_logs` for beneficiary production and direct evidence that a
  teammate played.
- `player_participation` for observed non-play outcomes and source provenance.

Schedule-density facts are not inputs. This computation describes historical
production conditions; it does not condition or adjust them for rest, travel,
or density.

## R35: when a missing row may mean absent

A missing game log or participation row is not itself an absence. The
computation first orders every observed row for a player and creates same-team
membership segments. A missing row is classified as an inferred absence only
when:

1. the game is a final scheduled game for that team;
2. the game lies between observed membership endpoints for the same team; and
3. the beneficiary has a game log for that team and game.

The bounds are conservative. Games before the first observation, after the last
observation, and gaps across a team change remain unknown. A player who leaves
and later returns to the same team creates separate segments. An explicit
`unknown` participation outcome is excluded rather than coerced to absence. If
a game log proves the player appeared, it wins over an uninformative `unknown`
participation row; a non-play outcome beside a game log is contradictory input
and fails the run loudly.

## Stored evidence

Each `absence_splits` row identifies the player pair, team, season, schedule
cohort, evidence algorithm, input fingerprint, and computation time. It stores:

- with/without sample sizes;
- explicit versus bounded-inferred absence counts;
- excluded unknown-game count;
- every beneficiary game-log ID, participation-row ID, team-schedule ID, and
  membership boundary used by the classification;
- production summaries and descriptive without-minus-with deltas;
- sample standard deviation and standard error where at least two games make
  variance estimable.

Rows are append-only by input fingerprint. `latest_absence_splits` selects one
row per player pair from the current schedule cohort so consumers do not
double-count historical recomputations.

## Percentage categories

Field-goal and free-throw evidence stores aggregate makes and attempts and
computes the rate from those totals. It never averages game percentages. A
1-for-1 game and a 9-for-10 game therefore summarize as 10-for-11, not 95%.
The Wilson interval is reported as descriptive uncertainty only. No
independent-shot delta interval is claimed because attempts within a game are
correlated.

## What this evidence cannot see

- The exact transaction time within a gap between observations.
- Practice, coaching, matchup, lineup, and role decisions that changed both the
  absence and the beneficiary's production.
- Whether a stated DNP reason is truthful.
- Unobserved roster membership before the first or after the last same-team
  observation.
- Whether an historical correlation will persist after trades, coaching
  changes, injuries, development, or roster turnover.
- A causal counterfactual: the same game cannot be observed both with and
  without the teammate.

Sparse splits remain sparse facts. They are retained with their sample sizes
and non-estimable variance fields, never promoted into recommendations here.
