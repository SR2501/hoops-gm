# Production-only 9-category z-score

**Owner:** quant  
**Version:** `zscore-production-v1`  
**Status:** in development; not active and not through the final Model gate

## What it predicts

The runtime engine does not predict games played. It transforms a complete
cohort of canonical **per-game production-rate projections** into directed
nine-category standardized production components and an equal-weight aggregate.
Its score means production relative to the declared input cohort and frozen
population scale. It is not availability, expected games, risk-adjusted value,
auction dollars, a punt score, or a roster recommendation.

The development study evaluates a separate, deliberately simple forecasting
input: each player's retrospectively assembled 2022-23 per-game box-score rates
are carried unchanged into 2023-24. That result is evidence about a historical
carry-forward benchmark plus this transform. It is not evidence that the current
projection blend is calibrated.

## Inputs

Runtime inputs are existing typed domain values:

- an explicit `League`, including positive integer `team_count` and
  `roster_size`;
- one genuine production `BlendProfile` created under the authoritative
  projection-blending profile-content contract and using canonical
  nine-category scoring contracts; and
- its matching real `BlendResult`, containing complete canonical per-game
  production fields for every supplied player.

The runtime reconstructs the complete blend-profile content hash and exact
profile ID before scoring. It does not accept a synthetic profile merely
because a `BlendResult` repeats its strings. Source lineage, scoring contracts,
weights, overrides, weight basis, version, content hash, and profile ID are all
inside that pure integrity boundary.

Counting inputs are PTS, REB, AST, STL, BLK, 3PM, and TO per game. Ratio inputs
are separately represented FG made/attempted and FT made/attempted per game.
Every numeric input must be finite and non-negative, and makes cannot exceed
attempts exactly. Equality and zero attempts are allowed; no epsilon, clamping,
or rounding is used.

The engine does **not** accept or query availability, `p(play)`, games-played
assumptions, seasonal projected totals, rankings, market data, mock results,
expected games, or a database session. The executable boundary test rejects
imports and signature parameters from those layers.

Each result retains:

- the engine model version;
- league identity and explicit structure;
- blend-profile and blend-result identities and hashes;
- scoring-profile identity and hash;
- exact sorted reference-player identity fingerprint;
- category production fields, direction, reference mean, population SD,
  ratio reference percentage, and zero-variance status;
- replacement state and required ordinal; and
- a deterministic result SHA-256.

The retrospective studies use a distinct
`HistoricalProductionBenchmark` adapter. It shares the same pure production
transforms but is explicitly labelled
`retrospective_historical_benchmark`; it does not fabricate a vendor source,
verified import, archived-as-of release, empty production profile, or
production-blend lineage.

## Method

### Reference population and completeness

Every complete supplied player is in the reference population. The engine
refuses an empty, malformed, incomplete, duplicate, contradictory, or
lineage-invalid cohort. It does not silently drop players or categories and does
not renormalize around missing values.

### Standardized production components

For a counting category:

`z = direction × (per_game_rate - reference_mean) / population_sd`

Population SD uses `ddof=0`. Directions are independently pinned: the eight
positive categories use `+1`; turnovers use `-1`.

For FG% and FT%, the reference percentage is attempts-weighted:

`reference_percentage = sum(makes_per_game) / sum(attempts_per_game)`

Each player's volume impact is:

`impact = makes_per_game - reference_percentage × attempts_per_game`

The impact, not raw percentage, is standardized over the same complete
reference cohort. Zero makes on zero attempts is neutral. A cohort with zero
attempts in a ratio category refuses rather than inventing a denominator.

At the explicit FT reference of 0.78, 90% on one attempt has impact `+0.12`,
while 80% on eight attempts has impact `+0.16`. This example establishes the
required volume behavior at that reference; it is not a universal ordering
independent of the reference percentage.

If a category has zero population variance, every component is exactly zero and
the scale reports `zero_variance`. No epsilon floor is used. The aggregate is
the equal-weight sum of all nine directed components.

### Ordering and replacement

Players order by aggregate descending and canonical player ID ascending. The ID
only breaks ordinal ties; tied numerical scores remain equal.

Structural roster count is `N = team_count × roster_size`, never inferred from
the size of the supplied projection cohort. If the pool contains more than
`N` players, replacement is ordinal `N+1` and value above replacement is the
aggregate difference from that player. If the pool contains `N` or fewer
players, production scores remain valid while replacement identity, replacement
score, and value above replacement are null with state
`unavailable_insufficient_projected_pool`.

## Training window

The engine fits no learned parameters. Its reference means, percentages, and
population SDs are computed from the supplied forecast cohort for that run.

The authorized development forecasting benchmark uses:

- forecast input: final retrospectively assembled 2022-23 regular-season
  appearance rows;
- held-out development outcome: final retrospectively assembled 2023-24
  regular-season appearance rows; and
- no minimum-games or future-survivor filter.

This is rolling-origin by season, but not an archived as-of forecast. Official
corrections and retrospective capture through 2026-09-02 may be present.

The final evaluator is a separate pre-unblind entry point. It consumes an
independently confirmed accepted freeze, the exact sealed forecast vector,
scales and bins, an independently released outcome package, and a complete
forecast-key accounting manifest. It cannot rerun the forecast or reconstruct
scales from held-out outcomes. The sealed forecast, accepted freeze, and actual
current candidate files must contain the same complete required label-to-hash
map. Executable labels are resolved against the modules actually running, so a
caller cannot substitute an unrelated archived file while calling it current
code.

The outcome handoff is one direct `sealed_outcome` package manifest, not a
worker-defined wrapper. Its package identity follows the governing experiment
protocol: canonical sorted compact UTF-8 JSON excluding only `package_id` and
`content_sha256`, one line feed, then ordered `filename<TAB>sha256` payload
lines with no trailing line feed. `package_id` is the compact UTC creation
timestamp plus the first 16 hexadecimal characters of that digest. The
manifest declares exactly the outcome CSV followed by the forecast-key JSON,
the fields released by both payloads, explicitly withheld source classes, the
source cutoff, and the data-engineer custodian's creation attestation. The
release/unblind record only approves that immutable package identity and
manifest file; it cannot redeclare or widen the payload.

The accepted freeze binds the executable preregistration itself, including the
question and eligible cohort, released development and forecast-input package
identities, feature and model variants, frozen 2024-25 regular-season split,
primary aggregate calibration and required category evidence, secondary
metrics, planned outputs, and all stop/no-tuning rules. Ideal intercept 0 and
slope 1 are references, not tolerances. A valid poor result is published
unchanged. An unestimable primary aggregate calibration is insufficient
evidence and stops before a production result.

The predeclared outcome consistency boundary is 2024-10-22 through 2025-04-13
inclusive with ten-digit NBA regular-season game IDs matching `00224xxxxx`.
This allows calendar-2025 games in the 2024-25 season. It detects a
self-labelled foreign-season payload but does not prove source completeness or
the absence of later official corrections; those remain custodian provenance
claims checked against the manifest's actual source cutoff.

Final outcome payloads are forecast-key-restricted. They can measure observed
outcomes and missingness states for the sealed forecast cohort, but cannot
measure source-population players outside those 572 forecast keys. In
particular, the final result does not report an outcome-only-player count.
For every forecast key, zero incomplete source rows is equivalent to an empty
missing-required-field list. A player may still have both complete credited
games and coherently accounted incomplete source rows; the at-least-one-
complete-game eligibility rule does not become an all-games-complete filter.

## Evaluation

Evidence:
`backend/tests/model_evidence/zscore_production_carryforward_v1_development.json`

Experiment:
`zscore-production-carryforward-v1-exp-20260911T201744001625Z`

Independently released development package:
`20260911T201744001625Z-b18c64c12a89226a`
(`b18c64c12a89226ab98f8dd84cf3a73b7baa0c247025ec487b988246b0b6f713`).
The evidence retains the protocol-invalid prior metadata-discovery deviation;
it is not relabelled as compliant self-release.

All 25,894 credited 2022-23 rows, including two zero-second/all-zero rows,
produce 539 forecast players. All 26,401 credited 2023-24 rows, including eight
zero-second/all-zero rows, produce 572 outcome players. There are 450 paired
players, 89 forecast players with missing outcomes, and 122 outcome-only
players. Missing outcomes remain missing rather than becoming zero and never
alter the forecast reference cohort or scales.

Realized 2023-24 rates are transformed using the **frozen 2022-23 forecast
means, SDs, and ratio reference percentages**. The outcome is never normalized
against 2023-24. Calibration is unweighted player-level OLS of realized frozen-
scale score on forecast score, with a deterministic 2,000-resample player-block
bootstrap. Intercept 0 and slope 1 are interpretive references, not activation
thresholds.

| Component | Pairs | Intercept | Slope | Slope bootstrap 95% | Realized at forecast +1 | Realized at forecast +2 | MAE | RMSE | Spearman |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| PTS | 450 | -0.076 | 0.910 | 0.874..0.945 | 0.834 | 1.744 | 0.349 | 0.459 | 0.828 |
| REB | 450 | -0.050 | 0.910 | 0.847..0.964 | 0.860 | 1.771 | 0.381 | 0.518 | 0.821 |
| AST | 450 | 0.016 | 0.845 | 0.768..0.911 | 0.861 | 1.706 | 0.360 | 0.540 | 0.799 |
| STL | 450 | 0.026 | 0.676 | 0.543..0.807 | 0.701 | 1.377 | 0.523 | 0.781 | 0.730 |
| BLK | 450 | 0.050 | 0.814 | 0.720..0.914 | 0.864 | 1.678 | 0.417 | 0.593 | 0.761 |
| 3PM | 450 | -0.016 | 0.897 | 0.851..0.947 | 0.881 | 1.779 | 0.386 | 0.529 | 0.852 |
| TO | 450 | 0.111 | 0.802 | 0.723..0.867 | 0.913 | 1.716 | 0.417 | 0.583 | 0.767 |
| FG impact | 450 | -0.015 | 0.722 | 0.656..0.792 | 0.707 | 1.429 | 0.519 | 0.669 | 0.692 |
| FT impact | 450 | 0.019 | 0.703 | 0.630..0.779 | 0.721 | 1.424 | 0.406 | 0.574 | 0.681 |
| Aggregate | 450 | 0.031 | 0.879 | 0.820..0.931 | 0.910 | 1.789 | 1.856 | 2.450 | 0.791 |

The aggregate slope below one indicates that carried-forward magnitudes are too
widely spaced on the frozen forecast scale. A forecast aggregate of +2 maps to
about +1.79 realized units, not two fully preserved units. The ratio-impact and
steals slopes show still stronger shrinkage. The engine therefore must not
describe an uncalibrated +2 as a guaranteed twice-+1 future edge.

Prediction-only Type-7 aggregate quintiles were fixed from all 539 forecasts
before pairing outcomes. Exact duplicate cuts collapse; equality enters the
upper bin. The five forecast bins contain 108, 108, 107, 108, and 108 players.
Their paired counts are 66, 80, 92, 106, and 106; their mean predicted versus
mean realized frozen-scale aggregates are respectively:

- `-4.636` versus `-3.235`;
- `-2.712` versus `-2.671`;
- `-0.709` versus `-1.006`;
- `1.767` versus `1.619`; and
- `6.644` versus `5.933`.

Observed-game sensitivities retain 417 players at 10+, 366 at 25+, and 273 at
50+. Aggregate calibration slopes are 0.876, 0.863, and 0.824 respectively, so
the shrinkage is not explained away by only the sparsest outcomes.

No pass/fail numerical tolerance was selected after seeing these results. This
valid but imperfect development result is reported rather than tuned away. It
supports the algebra and demonstrates that magnitude/spacing can be measured;
it does not establish current-blend calibration, final holdout performance, or
production activation.

The regenerated evidence uses the explicit retrospective benchmark adapter.
Its empirical values are unchanged because the mathematical transform is
unchanged. Evidence file SHA-256 is
`1e1c8ef54e8444b276fe323ab8685e440be8a60afc82e1b1cae80cf9bf0e1158`;
internal content SHA-256 is
`66e5064e8d263c6eb09840c0e29e55fe78efa96192074b5bc206fa125da58c2b`.

The executable final protocol is specified in
`zscore-production-final-evaluation-DRAFT.md`. No real 2024-25 outcome
presence or values have been released or accessed, and the final Model gate
remains pending.

## What this model cannot see

- trades, coaching changes, rotation changes, or role changes;
- rookies and players without an eligible prior-season production row;
- undisclosed injuries, rest plans, personal matters, or front-office intent;
- future availability or games played;
- schedule density, teammates, contingent opportunity, or replacement role;
- projection-source copying, correlated errors, or source staleness;
- whether a player will remain in the NBA outcome population;
- category scarcity under a specific opponent, roster, punt build, or waiver
  pool; or
- whether the supplied reference cohort represents the economically relevant
  fantasy-player pool.

## Known failure modes

- Reference-population composition changes every mean, SD, component, aggregate,
  and replacement value. Scores from differently declared populations are not
  directly interchangeable.
- A complete but very broad input pool can give different scales from a
  fantasy-relevant draft pool. Version 1 exposes that choice rather than hiding
  it.
- Small prior-season samples are intentionally retained in this development
  benchmark and can create unstable carry-forward inputs.
- Ratio categories are sensitive to both shooting efficiency and attempt
  volume; callers that supply rounded or percentage-only data are ineligible.
- Zero-variance categories are neutral by contract, which is honest but can
  reduce the aggregate below nine informative dimensions.
- Replacement is undefined when the supplied pool has no ordinal `N+1`;
  consumers must preserve null rather than substitute a capped or invented
  value.
- The development sample is conditional on an observed next-season appearance.
  It cannot measure availability loss and must not reinterpret missing outcomes
  as zero production.

## Change log

| Version | Date | Change | Evaluation effect |
|---|---|---|---|
| 1 | 2026-09-11 | Added the typed production-only nine-category transform, complete-cohort and lineage refusal, volume impacts, explicit zero variance, structural replacement state, and released development carry-forward study. | Development aggregate slope 0.879 (95% bootstrap 0.820..0.931), 450 pairs. Final 2024-25 holdout remains sealed; Model gate and activation are not claimed. |
| 1 prefreeze correction | 2026-09-11 | Replaced synthetic historical blend lineage with an explicit benchmark adapter, required authoritative production-profile reconstruction, enforced exact made≤attempted, and added the sealed final-evaluation entry point. | Development values are unchanged; final outcome evaluation remains prohibited until an independent freeze confirmation and matching release/unblind. |
| 1 governing prefreeze correction | 2026-09-11 | Replaced the non-governing outcome wrapper with the direct `sealed_outcome` package identity, added custodian/source-cutoff/season-boundary verification, and moved the complete preregistration into the hash-bound executable protocol. | Numerical runtime and development evidence are unchanged. No outcome package has been released or accessed, and no Model-gate or activation claim is made. |
| 1 accounting/evidence-sufficiency correction | 2026-09-11 | Required incomplete-row counts and missing-field declarations to agree in both directions, while preserving coherent mixed complete/incomplete players, and made unestimable primary aggregate calibration terminal before result emission. | Poor but estimable calibration still publishes unchanged. Runtime scoring and all forecast mathematics remain unchanged. |
