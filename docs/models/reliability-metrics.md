# Reliability metrics evidence card

**Owner:** quant
**Version:** 2
**Status:** active for descriptive scorecards only. Observed participation is
incomplete under R35; player-specific blowout suppression is rejected; no
composite reliability grade is defined.

## Output boundary

V2 keeps two evidence layers separate:

1. **Observed participation evidence** reports direct play/non-play observations,
   a calendar-month trend, and direct back-to-back observations. It is not a
   complete availability rate or a `p(play)` model.
2. **Played-game production consistency** reports minutes CV, per-category
   sample standard deviation, and empirical p20/p80. It describes production in
   games where the player appeared; it never inserts a DNP as zero production.

The scorecard has no grade, rank, value, projection, recommendation, or expected
games field. It also has no blowout-suppression field because the candidate
failed the release rule below.

## Inputs and lineage

Runtime computation uses one regular-season window from:

- `team_schedule` and final `nba_games`;
- `player_game_logs`;
- direct `player_participation` observations; and
- the existing pure-calendar `build_schedule_density` result for back-to-backs.

Publishing records three independent current cohorts in `refresh_runs`:

- schedule: `schedule:nba-schedule`;
- source: `source:reliability-observations`; and
- derivation: `model:reliability-derivation`.

The source fingerprint covers the season/type/window, schedule rows, final game
identity and scores, every consumed game-log field, and every participation
field. The derivation version covers category definitions, percentiles, sample
SD, back-to-back method, and ratio-impact formula. Computation locks and rechecks
all three cohorts, recomputes the source fingerprint, and rejects changed,
unknown, or stale claims. Each scorecard carries the exact schedule, source,
derivation, window, and computation time plus the contributing game-log and
participation row IDs.

No result table, migration, API, or UI is part of v2.

## Observed participation method

A game log or `played` participation row is direct evidence of play.
`did_not_play`, `did_not_dress`, `not_with_team`, and `inactive` are direct
evidence of non-play. A game log overrides `unknown`; a game log paired with an
explicit non-play outcome fails loudly.

`observed_play_rate = direct_play / (direct_play + direct_non_play)`

Missing rows and explicit `unknown` rows never enter the denominator. Every rate
reports direct-play, direct-non-play, explicit-unknown, and source-row counts,
with `coverage_status=incomplete_r35` and `opportunity_coverage=null`.
Opportunity coverage cannot be calculated because the merged data lacks both
authoritative historical roster intervals and proof that every game returned a
complete participation payload. Manufacturing a missing-opportunity count would
turn that unknown into a false fact.

Trend is the same direct-evidence calculation grouped by calendar month. No
slope, smoothing, or direction label is fitted. Back-to-back evidence restricts
the same direct observations to the player's historical team/game schedule row;
it never uses the player's current team.

Calibration is not reported for availability or back-to-back rates. The
historical `PlayerGameLogs` evidence contains appearances but not complete
non-appearance labels, so there is no honest held-out target.

## Production consistency method

Minutes volatility is sample SD divided by mean minutes. CV is null with fewer
than two observed minute values or a non-positive mean.

Counting-category distributions cover 3PM, PTS, REB, AST, STL, BLK, and TO.
Each reports observed-game count, mean, sample SD, and deterministic Type-7
empirical p20/p80. These percentiles are historical lower/upper observations,
not predictive intervals.

FG and FT use nightly volume-weighted impact:

`impact = made - cohort_attempt_weighted_rate * attempts`

The baseline rate is aggregate makes divided by aggregate attempts across the
same regular-season source window. Every ratio result retains baseline makes,
attempts, and rate; the scorecard's source version fingerprints the exact logs.
A low-volume perfect shooting night therefore cannot equal a high-volume night
with similar percentage.

## Chronological evaluation

The checked evidence is
`backend/tests/model_evidence/reliability_metrics_v2.json`. Its complete
parameter contract is version `b055dfbf67bb5127`, and the artifact is bound to
runtime descriptive derivation `f4ce099a5e84e0f8`. Tests literal-lock every
protocol value and verify both versions against executable code.

| Stage | Training | Held out |
|---|---|---|
| Selection | 2023-24 | 2024-25 |
| Final | 2024-25 | 2025-26 |

Stability eligibility requires at least 20 player games in both adjacent
seasons. Stability reports Spearman correlation and next-season MAE versus a
training-season league-median baseline. The corrected final transition contains
358 eligible players. Minutes CV has Spearman 0.728 and player-specific MAE 0.124,
versus 0.149 for the league-median baseline. Across category SDs, Spearman ranges
from 0.591 to 0.782; every player-specific MAE is lower than its corresponding
league-median baseline MAE. This supports displaying the historical statistics,
not wording them as forecasts.

Percentile coverage uses every player observed in both adjacent seasons rather
than the 20-game stability threshold: 464 players in the final transition.
Results are reported overall and in declared 1-19, 20-39, 40-59, and 60+
training-sample bands. The sparse band is therefore measured, not an empty
placeholder: its final FG-impact p20/p80 coverage is 0.294/0.684 across 55
players. Overall FG-impact coverage is 0.226/0.777. Zero-heavy counting
categories depart even further from nominal coverage because ties at zero make
an empirical p20 include substantially more than 20% of later observations.
V2 therefore labels every value an observed percentile, exposes its sample
count, and makes no calibrated predictive-interval claim.

The coordinator approved the partitions, thresholds, and calibration veto
before the successful outcome run. However, the implementation and evidence
first enter git together. The artifact records
`immutable_repository_preregistration=false`; this repository cannot
independently prove prospective registration. V2 is chronological held-out
evidence under a predeclared plan, not an immutably preregistered experiment.
Any future release must commit its protocol separately before evaluating its
final holdout.

### Source-cohort audit

| Season | Parsed games | Player-log game IDs | Included logs | Excluded logs | Fingerprint |
|---|---:|---:|---:|---:|---|
| 2023-24 | 1,230 | 1,230 | 26,401 | 0 | `4ecfda8e09653886` |
| 2024-25 | 1,230 | 1,230 | 26,306 | 0 | `34a836176d535b4b` |
| 2025-26 | 1,230 | 1,230 | 26,651 | 0 | `b7301976c833738f` |

The v1 evidence excluded five game IDs in each of 2024-25 and 2025-26 because
the adapter assumed each team row carried a reciprocal `MATCHUP` string. The
official source instead repeats one canonical matchup on both rows for those
games. Adapter reconciliation now identifies each row by its team abbreviation,
and bidirectional game-ID coverage is 100% in all three seasons. The mismatch
ceiling remains a drift guard, not permission to release another reduced cohort;
its 1% tolerance did not catch this 0.41% game-ID loss, so the evidence contract
also asserts literal 100% bidirectional coverage in the committed Model-gate
tests. Affected examples include neutral-site Paris and NBA Cup games, so the
restored rows are not assumed to be a random sample and nominal home/away must
not be interpreted as home-court advantage. Retired v1 evidence remains in the
repository as historical evidence and is integrity-pinned; it is not a runtime
release.

Reproduce the live study with:

```powershell
$env:PYTHONPATH = (Resolve-Path 'backend\src').Path
python -m hoops_gm.availability.reliability_backtest `
  --output backend\tests\model_evidence\reliability_metrics_v2.json
```

CI validates the committed evidence contract and fingerprints; it does not call
`stats.nba.com`.

## Rejected blowout-suppression candidate

A blowout is final margin at least 15 points. For players with at least five
blowout and ten non-blowout appearances in each adjacent season:

`delta_minutes = mean(blowout minutes) - mean(non-blowout minutes)`

The prior-season delta was compared with the next-season delta and with a
zero-effect baseline. The predeclared rule required both chronological
transitions to have lower MAE than zero, a player-block bootstrap 95% interval
strictly above zero for paired MAE improvement, positive calibration slope, no
calibration-bin sign reversal, and sign stability above 0.5.

| Held-out season | Players | Candidate MAE | Zero MAE | Improvement 95% CI | Slope | Sign stability |
|---|---:|---:|---:|---:|---:|---:|
| 2024-25 | 351 | 2.659 | 2.946 | -0.014 to 0.567 | 0.270 | 0.684 |
| 2025-26 | 346 | 2.409 | 2.903 | 0.212 to 0.749 | 0.360 | 0.728 |

The candidate lowered average error, but selection uncertainty included zero.
More importantly, in both transitions the highest predicted-delta bin was
positive while its observed mean delta was negative. That calibration sign
reversal vetoes release even though the aggregate final-holdout MAE improved.
No suppression number is emitted at runtime and no final-margin association is
treated as causal.

## Known failure modes and what v2 cannot see

- missing roster intervals and incomplete participation imports;
- trades, coaching changes, role changes, and rotation changes;
- undisclosed injuries, personal matters, and front-office intent;
- DNP-reason laundering, including rest labelled as a minor ailment;
- rookies, long-absence returners, and survivorship from adjacent-season
  eligibility;
- uncertainty in sparse player samples beyond the exposed counts;
- whether final margin caused a minutes change rather than merely co-occurred
  with role, score, or lineup context;
- future schedule corrections or upstream parser drift; and
- 2026-27 behavior, which has no completed outcome cohort yet.

Observed participation undercoverage is expected to be worst for long absences,
the exact cases a durability tool most needs. Consumers must not reinterpret
the observed rate as complete availability, combine it with production
dispersion into a grade, or feed either descriptive object directly into value.

## Change log

| Version | Date | Change | Evaluation effect |
|---|---|---|---|
| 1 | 2026-08-19 | Initial observed-only participation and played-game consistency scorecard. | Descriptive output accepted; blowout suppression rejected; composite undefined. |
| 2 | 2026-08-20 | Regenerated from complete 1,230-game source cohorts after adapter reconciliation restored 118 and 102 player logs. | Descriptive output remains accepted; blowout suppression remains rejected on calibration sign reversal; composite remains undefined. |
