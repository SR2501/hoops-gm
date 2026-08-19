# Reliability metrics evidence card

**Owner:** quant
**Version:** 1
**Status:** active for descriptive scorecards only. Observed participation is
incomplete under R35; player-specific blowout suppression is rejected; no
composite reliability grade is defined.

## Output boundary

V1 keeps two evidence layers separate:

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

No result table, migration, API, or UI is part of v1.

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
`backend/tests/model_evidence/reliability_metrics_v1.json`. The protocol was
locked in code before the final run:

| Stage | Training | Held out |
|---|---|---|
| Selection | 2023-24 | 2024-25 |
| Final | 2024-25 | 2025-26 |

Eligibility requires at least 20 player games in both adjacent seasons.
Stability reports Spearman correlation and next-season MAE versus a
training-season league-median baseline. The final transition contains 357
eligible players. Minutes CV has Spearman 0.729 and player-specific MAE 0.124,
versus 0.149 for the league-median baseline. Across category SDs, Spearman ranges
from 0.589 to 0.782; every player-specific MAE is lower than its corresponding
league-median baseline MAE. This supports displaying the historical statistics,
not wording them as forecasts.

Held-out p20/p80 coverage is reported overall and in predeclared 1-19, 20-39,
40-59, and 60+ training-sample bands. Continuous shooting-impact coverage is
near the nominal bounds in the final transition (FG 0.221/0.783), while
zero-heavy counting categories are not: for example, BLK p20/p80 covers
0.679/0.881. Ties at zero make a discrete empirical p20 include substantially
more than 20% of later observations. V1 therefore labels these values observed
percentiles and makes no calibrated predictive-interval claim.

### Source-cohort audit

| Season | Parsed games | Player-log game IDs | Included logs | Excluded logs | Fingerprint |
|---|---:|---:|---:|---:|---|
| 2023-24 | 1,230 | 1,230 | 26,401 | 0 | `d7a762232bbeeef9` |
| 2024-25 | 1,225 | 1,230 | 26,188 | 118 | `d390049e25899542` |
| 2025-26 | 1,225 | 1,230 | 26,549 | 102 | `47765bb5fafb9c09` |

The existing `LeagueGameFinder` parser produced no two-sided home/away record
for five game IDs in each of 2024-25 and 2025-26 even though `PlayerGameLogs`
contains those games. The evidence runner does not silently reparse
adapter-owned source rows. It records every excluded ID and log count in the
fingerprint and refuses to run if excluded game IDs exceed 1% of player-log game
IDs. The retained cohorts cover 99.59% of those game IDs. This is a known source
limitation, not evidence that the excluded games are ignorable.

Reproduce the live study with:

```powershell
$env:PYTHONPATH = (Resolve-Path 'backend\src').Path
python -m hoops_gm.availability.reliability_backtest `
  --output backend\tests\model_evidence\reliability_metrics_v1.json
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
| 2024-25 | 351 | 2.646 | 2.947 | -0.006 to 0.577 | 0.278 | 0.689 |
| 2025-26 | 346 | 2.426 | 2.910 | 0.203 to 0.739 | 0.360 | 0.731 |

The candidate lowered average error, but selection uncertainty included zero.
More importantly, in both transitions the highest predicted-delta bin was
positive while its observed mean delta was negative. That calibration sign
reversal vetoes release even though the aggregate final-holdout MAE improved.
No suppression number is emitted at runtime and no final-margin association is
treated as causal.

## Known failure modes and what v1 cannot see

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
