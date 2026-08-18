# Absence splits

**Owner:** quant
**Evidence version:** `absence-splits-descriptive-v2`
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

## R35 remains unresolved for missing rows

A missing game log or participation row is never classified as an absence.
`without` requires an explicit observed non-play outcome in
`player_participation`.

Same-team observations bracketing a gap are not roster history: a player can
leave, remain unsigned, and later return without an observed intervening-team
row. Even an authoritative roster interval would not prove absence by itself,
because the current import is upsert-only and carries no versioned statement
that a game's participation payload was complete. A partial payload can include
the beneficiary while omitting the teammate.

Missing-row inference must remain disabled until both inputs exist:

1. authoritative, versioned historical NBA roster-membership intervals; and
2. versioned per-game ingestion-completeness evidence proving the relevant
   participation sources were complete.

An explicit `unknown` participation outcome remains provenance, not absence or
schedule-coverage evidence. If a game log proves the player appeared, it wins
over an uninformative `unknown` row; a non-play outcome beside a game log is
contradictory input and fails the run loudly.

## Stored evidence

Each successful computation writes an `absence_split_runs` row, including a run
that produces zero pair results. The run identifies season, schedule cohort,
evidence algorithm, complete-input fingerprint, computation time, result count,
and one-sided pair count. `absence_splits` rows attach to exactly one run and
store:

- with/without sample sizes;
- a database-enforced statement that every `without` sample has direct observed
  absence evidence;
- every beneficiary game-log ID, participation-row ID, and team-schedule ID
  used by the classification;
- production summaries and descriptive without-minus-with deltas;
- sample standard deviation and standard error where at least two games make
  variance estimable.

Every successful computation appends a new activation, even when its complete
input fingerprint matches an older run. `latest_absence_splits` reads
exclusively from the newest successful activation in the current schedule
cohort. This preserves A-to-B-to-A ordering, and an empty recomputation removes
obsolete pairs from the current view while preserving every older run for
audit. The entire cohort is validated before its activation is inserted, so a
caught input error cannot become current if the caller commits.

## Percentage categories

Field-goal and free-throw evidence stores aggregate makes and attempts and
computes the rate from those totals. It never averages game percentages. A
1-for-1 game and a 9-for-10 game therefore summarize as 10-for-11, not 95%.
No percentage-category interval is reported. Wilson or binomial intervals over
attempts assume independent trials and overstate precision because shots cluster
within games. A future interval must resample or otherwise model games as the
independent unit.

## What this evidence cannot see

- Full absences represented only by missing source rows (R35).
- Historical roster membership and exact transaction times within observation
  gaps.
- Whether a per-game participation payload was complete.
- Practice, coaching, matchup, lineup, and role decisions that changed both the
  absence and the beneficiary's production.
- Whether a stated DNP reason is truthful.
- Whether an historical correlation will persist after trades, coaching
  changes, injuries, development, or roster turnover.
- A causal counterfactual: the same game cannot be observed both with and
  without the teammate.

Sparse splits remain sparse facts. They are retained with their sample sizes
and non-estimable variance fields, never promoted into recommendations here.
