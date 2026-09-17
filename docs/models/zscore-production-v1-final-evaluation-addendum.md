# Production z-score v1 final evaluation addendum

**Owner:** quant  
**Model version:** `zscore-production-v1`  
**Experiment:** `zscore-production-carryforward-v1-exp-20260911T201744001625Z`  
**Status:** Model gate passed for limited descriptive projection-relative
production scoring; current-vendor calibration and production activation remain
unapproved  
**Base model card:** [`zscore-production.md`](zscore-production.md)  
**Exact aggregate evidence:**
[`zscore_production_carryforward_v1_final.json`](../../backend/tests/model_evidence/zscore_production_carryforward_v1_final.json)

This is an append-only report adjacent to the immutable, freeze-bound base
card. It does not revise that card, the estimator, the frozen protocol, the
held-out result, or any other experiment record.

The bound aggregate JSON preserves the pre-review candidate status fields with
which it was reviewed. This addendum and the independent closure verdict
supersede only those fields; its numerical evidence and bindings remain
unchanged.

## Supported claim

The final evidence supports using this deterministic production-only transform
as a **projection-relative descriptive z-score and ordinal ranking** when its
source, season, blend, scoring profile, full reference population, model
version, and replacement state are displayed with the score.

It does not establish that the current Basketball Monster forecast, another
vendor forecast, or a current multi-source blend is calibrated. The evaluated
forecast was a retrospective prior-season production carry-forward.

## Immutable experiment identity

| Record | Identity |
|---|---|
| Protocol SHA-256 | `6485d380eb69995f7f0d67356bf6353c1123dc2ba55fd731044ca11993a84135` |
| Freeze | `zscore-final-freeze-20260911T231730153723Z-966f1d50e74d` |
| Accepted-freeze content SHA-256 | `69d30b551295bd9c5fceb9dd9e976472840e18d20f14c6f9f9eb47839614be75` |
| Freeze-confirmation content SHA-256 | `4481fe6670f6dff57a477dd7e798a0af4839305927a5e75c564acceeff017329` |
| Forecast content SHA-256 | `564d8f3570d8b8ce6ba7dd00b0923e847973174a4b0c4e758201a2188fea6eaf` |
| Forecast vector SHA-256 | `0bfaa20748c3055d37178191183d281ecb6488f25e0f0e454cd5ba9f2efe5f4a` |
| Reference-player fingerprint | `2f0ca1f042e2631cf6d36b980130bcf6377a4579102cf93ee946353111fc9451` |
| Outcome package | `20260911T233518298427Z-bcac5d7d349971fa` |
| Outcome-package content SHA-256 | `bcac5d7d349971fa57573b5a1f5c6b75ec6b90f88be1ecd1d112c1bf139adcfe` |
| Outcome release | `zscore-final-outcome-unblind-20260911T234721629192Z-e1855d007cb4` |
| Outcome-release content SHA-256 | `19326c72dc5a1101083523f8f275104df1335bd19b595837192d2a94aa54e2ea` |
| Final-result file SHA-256 | `c3b7830055ff1ce4dbd76d326e5345706ad31e5930d0553259e5d805964e176c` |
| Final-result content SHA-256 | `cf35bc6650165be714c6d6a9a859808415d088832b17461fd0a486ae37a3dcba` |
| Execution-receipt file SHA-256 | `cd4195725e64c9c80132f1d92575af01c890fcef8f5fb072aa434d64ce594a4c` |
| Independent adjudication | `zscore-final-adjudication-20260914T020704993399Z-e3f9ff9de3ce` |
| Adjudication file SHA-256 | `17145a3ae0c745e950489b3e5fcf39f0467b28d9a9227a20c5f958f17dc99da3` |
| Public aggregate evidence content SHA-256 | `b6376c6db5c002e001655aaebbcfd1e507394e67f12ade7eb153a0e2ea7eff76` |

The accepted freeze is a local content-addressed experiment record. It is not
a Git commit and must not be described as one.

## Execution

One worker invocation ran on **12 September 2026**, not during the preceding
night:

- receipt observed: `2026-09-12T11:46:48.6823801Z`;
- pre-execution verification:
  `2026-09-12T11:46:48.7331129Z` to
  `2026-09-12T11:46:48.8312077Z`;
- evaluation:
  `2026-09-12T11:46:48.8472379Z` to
  `2026-09-12T11:47:03.5103182Z`;
- exit code: `0`; and
- stderr: empty.

The independent adjudication found the protocol valid and independently
reproduced all frozen metrics, intervals, bins, denominators, anchors,
sensitivities, and accounting. The worker did not rerun the experiment.

## Method and denominators

Final 2023-24 per-game appearance production was carried unchanged into the
2024-25 forecast. Realized final 2024-25 regular-season production was
transformed with the sealed 2023-24 reference means, population standard
deviations (`ddof=0`), and attempt-weighted FG/FT reference percentages.
Outcomes were not normalized on the holdout.

Calibration is unweighted player-level OLS of realized frozen-scale score on
sealed forecast score. Intervals use the frozen deterministic 2,000-resample
player bootstrap. Bins are the sealed forecast-only Type-7 quintiles; they were
not recomputed after unblind.

| Quantity | Count |
|---|---:|
| Frozen forecast keys | 572 |
| Complete observed players | 447 |
| No observed box score | 125 |
| Complete credited outcome rows | 22,567 |
| Credited zero-second rows | 2 |
| Identity-unresolved keys | 0 |
| Incomplete-required-field keys | 0 |
| Incomplete source rows | 0 |
| Unresolved source rows | 0 |

Missing outcomes remained missing. No zero production was fabricated.

## Calibration and secondary metrics

All ten calibrations were evaluable and used 2,000 bootstrap resamples.
Bracketed values are 95% bootstrap intervals. Exact unrounded values are in the
aggregate evidence JSON.

| Metric | Intercept [95%] | Slope [95%] | Realized at forecast +1 / +2 | MAE | RMSE | Spearman |
|---|---|---|---|---:|---:|---:|
| PTS | 0.055237 [0.015753, 0.095483] | 0.877888 [0.839112, 0.918212] | 0.933125 / 1.811013 | 0.345973 | 0.435995 | 0.859890 |
| REB | 0.064459 [0.019939, 0.111024] | 0.856767 [0.803131, 0.911010] | 0.921226 / 1.777993 | 0.362425 | 0.518139 | 0.830239 |
| AST | 0.035235 [-0.002955, 0.076792] | 0.865809 [0.814792, 0.916777] | 0.901044 / 1.766853 | 0.337245 | 0.453337 | 0.834176 |
| STL | 0.229525 [0.164715, 0.292166] | 0.806160 [0.724175, 0.895979] | 1.035685 / 1.841845 | 0.579960 | 0.762430 | 0.745503 |
| BLK | -0.015955 [-0.057474, 0.024825] | 0.834818 [0.755267, 0.904030] | 0.818863 / 1.653680 | 0.371290 | 0.520397 | 0.783636 |
| 3PM | 0.126597 [0.080375, 0.174454] | 0.881117 [0.835049, 0.932252] | 1.007713 / 1.888830 | 0.403606 | 0.548638 | 0.864135 |
| TO | -0.115180 [-0.164492, -0.069206] | 0.905395 [0.851229, 0.960948] | 0.790215 / 1.695611 | 0.406330 | 0.538730 | 0.822736 |
| FG impact | -0.125097 [-0.195831, -0.057895] | 0.774856 [0.682756, 0.850331] | 0.649759 / 1.424615 | 0.568110 | 0.798827 | 0.651528 |
| FT impact | 0.001295 [-0.071132, 0.073714] | 0.791197 [0.662890, 0.908912] | 0.792492 / 1.583688 | 0.551242 | 0.794249 | 0.616501 |
| **Aggregate** | **0.275893 [0.066228, 0.471567]** | **0.814927 [0.754176, 0.876818]** | **1.090820 / 1.905747** | **1.833268** | **2.369671** | **0.837730** |

The aggregate slope interval excludes the ideal reference value 1 and the
intercept interval excludes 0. Forecast-relative magnitudes are materially
compressed and offset in this held-out carry-forward benchmark, even though
ordinal association remains strong.

FG and FT impact have the weakest rank evidence. FT observed bin means contain
a local middle-bin reversal: bin 1 is `-0.093538`, while bin 2 is `-0.150734`.
This is descriptive evidence, not a preregistered veto or a reason to alter the
transform.

## Frozen prediction bins

Each cell is `forecast count / paired count: mean prediction -> mean realized
frozen-scale outcome`. Exact per-bin missing-status counts and unrounded values
are preserved in the evidence JSON.

| Metric | Bin 0 | Bin 1 | Bin 2 | Bin 3 | Bin 4 |
|---|---|---|---|---|---|
| Aggregate | 115/55: -5.098689 -> -3.381889 | 114/77: -2.927610 -> -2.384373 | 114/93: -0.595998 -> -0.428387 | 114/107: 1.869584 -> 1.726902 | 115/115: 7.016945 -> 6.184429 |
| PTS | 115/53: -0.998152 -> -0.705124 | 114/76: -0.655178 -> -0.521455 | 114/93: -0.303711 -> -0.228199 | 114/112: 0.302390 -> 0.232301 | 115/113: 1.682571 -> 1.580460 |
| REB | 115/59: -1.057292 -> -0.674728 | 114/82: -0.628826 -> -0.481804 | 114/86: -0.168794 -> -0.174255 | 113/108: 0.297215 -> 0.273111 | 116/112: 1.595193 -> 1.465468 |
| AST | 115/57: -0.876958 -> -0.667685 | 114/81: -0.609667 -> -0.480418 | 114/101: -0.354517 -> -0.267844 | 114/97: 0.186980 -> 0.140803 | 115/111: 1.711998 -> 1.525354 |
| STL | 115/59: -1.176755 -> -0.609178 | 112/80: -0.665373 -> -0.375332 | 116/98: -0.095741 -> 0.060230 | 114/103: 0.505106 -> 0.637451 | 115/107: 1.497661 -> 1.511097 |
| BLK | 115/68: -0.873923 -> -0.587871 | 114/81: -0.609477 -> -0.527731 | 114/93: -0.256095 -> -0.287113 | 114/98: 0.238250 -> 0.144068 | 115/107: 1.534385 -> 1.252500 |
| 3PM | 115/72: -1.042398 -> -0.869833 | 112/77: -0.713435 -> -0.464967 | 116/80: -0.245342 -> -0.058247 | 114/106: 0.408664 -> 0.449892 | 115/112: 1.634471 -> 1.603830 |
| TO | 115/111: -1.654260 -> -1.679131 | 114/101: -0.314425 -> -0.313421 | 114/95: 0.274853 -> 0.219038 | 108/77: 0.609430 -> 0.430337 | 121/63: 0.980157 -> 0.629219 |
| FG impact | 115/82: -1.060117 -> -0.770941 | 114/83: -0.475578 -> -0.439639 | 112/83: -0.170968 -> -0.366887 | 116/93: 0.247599 -> -0.030276 | 115/106: 1.563840 -> 1.079289 |
| FT impact | 115/92: -1.246284 -> -0.920340 | 114/90: -0.273993 -> -0.093538 | 114/72: -0.007874 -> -0.150734 | 114/89: 0.230473 -> 0.101806 | 115/104: 1.319328 -> 1.053596 |

Aggregate observed means remain monotone across the frozen bins, supporting
descriptive separation among observed players. This does not remove the
selection limitation.

## Survivor selection

Observation is strongly associated with forecast bin. Only 55 of 115 players
in the bottom aggregate bin have a complete observed outcome, compared with
115 of 115 in the top bin. Observation rates rise from 47.83% to 100%.

The evaluation is therefore conditional on at least one complete credited
2024-25 appearance. It cannot estimate production or availability for the 125
missing forecast players, and it does not support population-wide calibration.

## Observed-game support sensitivities

| Minimum observed games | Players | Intercept [95%] | Slope [95%] | Realized at +1 / +2 | MAE | RMSE | Spearman |
|---:|---:|---|---|---|---:|---:|---:|
| 10 | 423 | 0.346213 [0.134181, 0.552562] | 0.808599 [0.748324, 0.866987] | 1.154812 / 1.963411 | 1.809836 | 2.343072 | 0.842360 |
| 25 | 373 | 0.484135 [0.275997, 0.707814] | 0.808258 [0.749301, 0.866416] | 1.292392 / 2.100650 | 1.775150 | 2.275758 | 0.834484 |
| 50 | 259 | 0.817194 [0.558453, 1.107585] | 0.798654 [0.731200, 0.861436] | 1.615848 / 2.414501 | 1.728934 | 2.230329 | 0.828002 |

Compression persists at all three support thresholds. Minimum-games filtering
does not explain it away.

## Provenance and prior exposure

The represented regular season ends `2025-04-13`; the accepted retrospective
capture timestamp is `2026-09-01T22:44:08.363806+00:00`.

Before the fresh experiment was frozen, the worker saw source metadata and
aggregate season counts that included both 2024-25 and 2025-26. No
player/game-level feature or outcome cells were exposed, but the holdout was
not pristine with respect to aggregate metadata. This is retained as deviation
`20260911T201857956271Z-f2bee81f6dd5b6af`, content SHA-256
`f2bee81f6dd5b6af2e7748e91a9a904ece2db7908ee57ed4fcb6b52b2604440d`.
It would be false to claim that the worker had seen zero information about
calendar 2025 or the 2025-26 season.

Recovery used fresh purpose-correct packages, a fresh experiment freeze,
independent package release, and the single frozen held-out execution described
above. The deviation is disclosed rather than erased or relabelled.

## What this evidence cannot establish

- It does not calibrate the current Basketball Monster forecast, another
  vendor, or a current user-configured blend.
- It does not estimate availability, games played, expected games, injury
  effects, shutdown risk, or production for players with no credited outcome.
- It does not establish auction dollars, inflation, value-over-replacement for
  an undersized pool, risk-adjusted value, punt strategy, draft optimization,
  lineup decisions, trades, recommendations, or account actuation.
- It cannot see trades, coaching or rotation changes, undisclosed injuries,
  personal matters, front-office intent, shutdown intent, rookies, or players
  without a prior-season appearance.
- When the supplied projection population lacks structural ordinal `N+1`,
  replacement and value above replacement remain unavailable. They are not
  zero, capped, or inferred from the smaller pool.

## Gate and delivery status

Independent adjudication, reporting closure and subsequent delivery evidence
establish:

- experiment protocol: **PASS — valid evidence**;
- scientific evidence: **ACCEPTED, LIMITED**;
- descriptive projection-relative score use: **supported with mandatory
  lineage and scope labels**;
- Model gate: **PASS — limited descriptive projection-relative production
  scoring only; current-vendor calibration and production activation remain
  unapproved**;
- Code gate: **PASS for the named local scoring delivery**, following promotion
  of the exact independently reviewed formatting-only successor and its targeted
  formatter, lint, strict type-check and test commands; and
- merge or production activation: **not approved**.

Formatting closure was a separate delivery-only process. Thirteen Python paths
were promoted, ten with different source bytes; the three non-Python bound files
were unchanged. The 14 September 2026 UTC promotion receipt has file SHA-256
`1ec911a078c92820540b72f467316f694893a119f4dfd8b7b3901946c5ffa7d0`.
Its local Code evidence covers those thirteen paths and the six-file,
187-test scoring group, not the concurrently implemented candidate API/UI.
The parent subsequently confirmed all sixteen live delivery hashes against the
reviewed successor map; confirmation file SHA-256 is
`3a151fa905e82cad6e9440207379a08e363649d633a44eb2fc88a259a9732e09`.
Original result, execution receipt and freeze identities remain attached to the
original experiment bytes. No second evaluation occurred or was authorized.
