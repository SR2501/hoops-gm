# DRAFT: production z-score final evaluation freeze

**Experiment:** `zscore-production-carryforward-v1`  
**Status:** DRAFT ONLY — not frozen, not accepted, and not authority to release or
inspect 2024-25 outcomes  
**Owner:** quant  
**Draft date:** 2026-09-11

This draft records the proposed final 2023-24 → 2024-25 evaluation after the
purpose-correct **input-only** forecast release and construction of a private
forecast prefreeze candidate. No held-out outcome or outcome-presence data has
been released or accessed. Exact player predictions and assignments remain in
the private content-addressed artifact; this repository records only safe
aggregate summaries and their identities.

## Claim under evaluation

Given complete canonical prior-season per-game production rows, the
`zscore-production-v1` engine produces directed category and aggregate
magnitudes whose next-season realized values can be interpreted on the same
frozen standardized scale.

This final benchmark would remain a **retrospective carry-forward baseline**. It
would not establish calibration of the current user-configured vendor blend,
because no historical archived as-of vendor projections have been demonstrated.

## Required role separation and release sequence

1. The implementation candidate, tests, development evidence, and this protocol
   receive immutable SHA-256 identities.
2. A data custodian created a purpose-correct immutable **forecast-input**
   package containing only the permitted 2023-24 fields. The existing
   development release was not reused as purpose authority.
3. Independent quant releaser
   `864250a3-a4a7-4ca6-b65b-2613087c39c9` verified and released that exact
   package for input-only forecast construction.
4. The worker created the private prefreeze candidate, including reference
   membership fingerprint, frozen means/SDs/ratio percentages, predictions,
   replacement ordering, prediction-only cuts and bin assignments, and all
   input/implementation hashes. Outcome values remain inaccessible.
5. Before any outcome access, the worker implemented the complete final
   evaluator and synthetic positive/negative package tests. The evaluator
   verifies the accepted freeze, independent confirmation, sealed forecast,
   release/unblind, outcome manifest, key manifest, payload, and frozen code
   identities in that order.
6. An independent reviewer must now verify the corrected candidate identities
   and either accept or revise this draft. This step has **not** occurred.
7. Only after that confirmation may a separate custodian and independent
   releaser verify the sealed forecast and
   release only the matching 2024-25 outcome package.
8. The worker runs the already frozen evaluator without changing population,
   transforms, metrics, bins, thresholds, missingness rules, or code.

Any code or protocol change after forecast sealing creates a new candidate and
requires a new freeze and release. The rejected v1, v2, and v3 artifacts and
snapshots remain preserved and have no release authority.

## Candidate identities to pin before acceptance

The replacement candidate binds every changed estimator, producer-boundary,
forecast, final-evaluation, evidence, model-card, and directly coupled test
file. The exact replacement hashes are inserted only after validation and
real-clock generation; the v2 table below is retained as rejected history and
must not be treated as the replacement candidate:

| Candidate label | Path | SHA-256 |
|---|---|---|
| `valuation_init` | `backend/src/hoops_gm/valuation/__init__.py` | `00e5fe38adf8ca0774a77736c7c7627f56aacae32ce40eaa75b9591afa7e52a1` |
| `runtime` | `backend/src/hoops_gm/valuation/zscore.py` | `a4085ad686122705469fe3ca5cc0782716f325be646a63151d398eac20633d11` |
| `development_evaluator` | `backend/src/hoops_gm/valuation/zscore_backtest.py` | `82c6c99b7408a11e95bb98e2d4eab06b8534fddf76c16eadf264ae5c24641c75` |
| `forecast_builder` | `backend/src/hoops_gm/valuation/zscore_forecast.py` | `2904bfac70d0c1d51f4b9722ff8ac01f4ab6e3740d31c5521913cc0ca5036688` |
| `final_evaluator` | `backend/src/hoops_gm/valuation/zscore_final_evaluation.py` | `88008d12ee2ea3bab2d49193b83e5d0f2d9179bfbb7a19cc769a8c2fc5a60c6d` |
| `projection_blending` | `backend/src/hoops_gm/projections/blending.py` | `a8b22621dee1685289ca8039e8015105a8df66eb2c11740413c59b1c107dd192` |
| `scoring_profiles` | `backend/src/hoops_gm/scoring/profiles.py` | `20e004bf3261e5390b0637a35aa4748cec20f1ade0787bd403362967f25966c3` |
| `runtime_tests` | `backend/tests/test_zscore.py` | `92b4f940f2a53c0ab78153b78238d05e211cfab8c2f72e391093e543619029b1` |
| `development_tests` | `backend/tests/test_zscore_backtest.py` | `2f8d9bf7af60837732df548b5b0a78ad99a0266b9beed0023dd9981965c8d2af` |
| `forecast_tests` | `backend/tests/test_zscore_forecast.py` | `864bedb3e037f26cb1ea4d0ce8f011b829320f2d71032354d1e5ce0001766978` |
| `final_evaluator_tests` | `backend/tests/test_zscore_final_evaluation.py` | `218a737b48f8163a3b436cf21362336ec329a41570c33cf2fd7e4c3df563cd0b` |
| `projection_blending_tests` | `backend/tests/test_projection_blending.py` | `c3e958910df1909398eb4186162e4918410b68de612a75ff72ed1a38ca259a3a` |
| `scoring_profile_tests` | `backend/tests/test_scoring_profiles.py` | `21952200eec5a8ec6338ead9b5b6020616d7a559e7a8f09edd0680e4e77a070d` |
| `development_evidence` | `backend/tests/model_evidence/zscore_production_carryforward_v1_development.json` | `1e1c8ef54e8444b276fe323ab8685e440be8a60afc82e1b1cae80cf9bf0e1158` |
| `zscore_model_card` | `docs/models/zscore-production.md` | `67e4e811e2e33f15f600dc51c0bb835678f617181e835edbd256d4003bcf24a7` |
| `projection_blending_model_card` | `docs/models/projection-blending.md` | `2f7edb2046f5cef473e89d8a552ae0fb3e91a3992718652b5b90cfe224894f43` |

Development evidence internal content SHA-256 is
`66e5064e8d263c6eb09840c0e29e55fe78efa96192074b5bc206fa125da58c2b`.
This draft receives a separate SHA-256 after these identities are inserted,
avoiding a circular artifact/draft hash.

Rejected replacement v3 candidate identities:

| Candidate label | SHA-256 |
|---|---|
| `valuation_init` | `00e5fe38adf8ca0774a77736c7c7627f56aacae32ce40eaa75b9591afa7e52a1` |
| `runtime` | `a4085ad686122705469fe3ca5cc0782716f325be646a63151d398eac20633d11` |
| `development_evaluator` | `82c6c99b7408a11e95bb98e2d4eab06b8534fddf76c16eadf264ae5c24641c75` |
| `forecast_builder` | `2904bfac70d0c1d51f4b9722ff8ac01f4ab6e3740d31c5521913cc0ca5036688` |
| `final_evaluator` | `e055903281973b9862429e4661f92d4acdafc820f9e1588f1176cf3f122c72bf` |
| `projection_blending` | `a8b22621dee1685289ca8039e8015105a8df66eb2c11740413c59b1c107dd192` |
| `scoring_profiles` | `20e004bf3261e5390b0637a35aa4748cec20f1ade0787bd403362967f25966c3` |
| `runtime_tests` | `92b4f940f2a53c0ab78153b78238d05e211cfab8c2f72e391093e543619029b1` |
| `development_tests` | `2f8d9bf7af60837732df548b5b0a78ad99a0266b9beed0023dd9981965c8d2af` |
| `forecast_tests` | `864bedb3e037f26cb1ea4d0ce8f011b829320f2d71032354d1e5ce0001766978` |
| `final_evaluator_tests` | `6eac61570efc4e1ba7421e5c0b1a0d3b9b96a6bfad2d042e72ae73aa8a6f265d` |
| `projection_blending_tests` | `c3e958910df1909398eb4186162e4918410b68de612a75ff72ed1a38ca259a3a` |
| `scoring_profile_tests` | `21952200eec5a8ec6338ead9b5b6020616d7a559e7a8f09edd0680e4e77a070d` |
| `development_evidence` | `1e1c8ef54e8444b276fe323ab8685e440be8a60afc82e1b1cae80cf9bf0e1158` |
| `zscore_model_card` | `3a8ca77d5937b04ce6477bc78ec41fc1a41bd8f571505b064154e2aff4703f3e` |
| `projection_blending_model_card` | `2f7edb2046f5cef473e89d8a552ae0fb3e91a3992718652b5b90cfe224894f43` |

Rejected replacement v4 candidate identities:

| Candidate label | SHA-256 |
|---|---|
| `valuation_init` | `00e5fe38adf8ca0774a77736c7c7627f56aacae32ce40eaa75b9591afa7e52a1` |
| `runtime` | `a4085ad686122705469fe3ca5cc0782716f325be646a63151d398eac20633d11` |
| `development_evaluator` | `82c6c99b7408a11e95bb98e2d4eab06b8534fddf76c16eadf264ae5c24641c75` |
| `forecast_builder` | `2904bfac70d0c1d51f4b9722ff8ac01f4ab6e3740d31c5521913cc0ca5036688` |
| `final_evaluator` | `636432c7074f06413c615a8f4e508cba4845e0e60f4a7b5b565a797883bcac03` |
| `projection_blending` | `a8b22621dee1685289ca8039e8015105a8df66eb2c11740413c59b1c107dd192` |
| `scoring_profiles` | `20e004bf3261e5390b0637a35aa4748cec20f1ade0787bd403362967f25966c3` |
| `runtime_tests` | `92b4f940f2a53c0ab78153b78238d05e211cfab8c2f72e391093e543619029b1` |
| `development_tests` | `2f8d9bf7af60837732df548b5b0a78ad99a0266b9beed0023dd9981965c8d2af` |
| `forecast_tests` | `864bedb3e037f26cb1ea4d0ce8f011b829320f2d71032354d1e5ce0001766978` |
| `final_evaluator_tests` | `598473fdba3b6a4f5ba4afdeeeea62b643077af5a6eb69a8b43c2b8e66e6ae75` |
| `projection_blending_tests` | `c3e958910df1909398eb4186162e4918410b68de612a75ff72ed1a38ca259a3a` |
| `scoring_profile_tests` | `21952200eec5a8ec6338ead9b5b6020616d7a559e7a8f09edd0680e4e77a070d` |
| `development_evidence` | `1e1c8ef54e8444b276fe323ab8685e440be8a60afc82e1b1cae80cf9bf0e1158` |
| `zscore_model_card` | `9443ef883b142138fcadd65f3eee7ee57e6ac2fd3df8269cf2b37868b7150b1f` |
| `projection_blending_model_card` | `2f7edb2046f5cef473e89d8a552ae0fb3e91a3992718652b5b90cfe224894f43` |

Replacement v5 candidate identities:

| Candidate label | SHA-256 |
|---|---|
| `valuation_init` | `00e5fe38adf8ca0774a77736c7c7627f56aacae32ce40eaa75b9591afa7e52a1` |
| `runtime` | `a4085ad686122705469fe3ca5cc0782716f325be646a63151d398eac20633d11` |
| `development_evaluator` | `82c6c99b7408a11e95bb98e2d4eab06b8534fddf76c16eadf264ae5c24641c75` |
| `forecast_builder` | `2904bfac70d0c1d51f4b9722ff8ac01f4ab6e3740d31c5521913cc0ca5036688` |
| `final_evaluator` | `6a478ebad9ffaa5404b105c00869f13652f0f62d5bafa176b7fe395fa1bca16f` |
| `projection_blending` | `a8b22621dee1685289ca8039e8015105a8df66eb2c11740413c59b1c107dd192` |
| `scoring_profiles` | `20e004bf3261e5390b0637a35aa4748cec20f1ade0787bd403362967f25966c3` |
| `runtime_tests` | `92b4f940f2a53c0ab78153b78238d05e211cfab8c2f72e391093e543619029b1` |
| `development_tests` | `2f8d9bf7af60837732df548b5b0a78ad99a0266b9beed0023dd9981965c8d2af` |
| `forecast_tests` | `864bedb3e037f26cb1ea4d0ce8f011b829320f2d71032354d1e5ce0001766978` |
| `final_evaluator_tests` | `b8c8bf8a2fe2a445ac78e5f64ba76c835b678248e16d0956b7dc87e330cfa06e` |
| `projection_blending_tests` | `c3e958910df1909398eb4186162e4918410b68de612a75ff72ed1a38ca259a3a` |
| `scoring_profile_tests` | `21952200eec5a8ec6338ead9b5b6020616d7a559e7a8f09edd0680e4e77a070d` |
| `development_evidence` | `1e1c8ef54e8444b276fe323ab8685e440be8a60afc82e1b1cae80cf9bf0e1158` |
| `zscore_model_card` | `cb5ba8ab6b618a036815f4d821f3b429eab1a89df9625092c3622956418d9a51` |
| `projection_blending_model_card` | `2f7edb2046f5cef473e89d8a552ae0fb3e91a3992718652b5b90cfe224894f43` |

Replacement final-evaluation protocol SHA-256:
`6485d380eb69995f7f0d67356bf6353c1123dc2ba55fd731044ca11993a84135`.

## Final forecast input

- season: 2023-24 regular season;
- one row per credited canonical player-game appearance;
- exact fields: canonical player ID, canonical NBA game ID, game date, season,
  season type, seconds, FGM, FGA, FTM, FTA, 3PM, PTS, REB, AST, STL, BLK, TO;
- all credited rows count, including zero-second/all-zero rows;
- aggregate all team stints by canonical player;
- no minimum-games, roster, opportunity, or future-survivor filter;
- eligibility requires at least one complete credited row;
- duplicate player-game identities, nulls, invalid numeric values,
  makes greater than attempts, wrong season/type, or schema drift refuse the
  whole run.

Purpose-correct input package:

- package ID: `20260911T204202792405Z-0fb3dfda4396893f`;
- package content SHA-256:
  `0fb3dfda4396893f38d1a6e49a2f2836efa3098ffe4b325ac6937d8bc787ebe3`;
- manifest SHA-256:
  `2612cfb3005a3aa95a50e810824a0500d38919f0be1b8114b37fcbd03bdaf447`;
- payload SHA-256:
  `70716b61cb95802b7552d08cfce87a2c75794cd1fb0e549f139cec7f9a01ba3c`;
- source rows: 26,401;
- canonical forecast players: 572;
- credited zero-second/all-zero rows retained: 8; and
- latest represented game date: 2024-04-14, with retrospective capture at
  2026-09-01T22:44:03.660171+00:00.

Independent input-only release:

- release ID: `20260911T204417608035Z-8ce7cb77fb4186ef`;
- content SHA-256:
  `8ce7cb77fb4186efaf54181e71225f7cf537ea957b6f35f493530077c35b14b7`;
- file SHA-256:
  `5b5baaecfd158748ff61728b33442a3c5bbeacd6606b1253287005332528648e`;
- disposition: `approved_input_only_pending_parent_delivery`; and
- worker: `cbd0b663-f1be-41a8-bebb-d4519b1326cf`.

The prior metadata-discovery deviation remains bound as record
`20260911T201857956271Z-f2bee81f6dd5b6af`, content
`f2bee81f6dd5b6af2e7748e91a9a904ece2db7908ee57ed4fcb6b52b2604440d`,
file `99ca8e02b1add9deac32f2fae567031f207d57d3f7666383cb312d348a9cb604`,
and retained inventory
`8a638d65c241930bd7b7487df26a4be9a32b115dd28ec2542c7d1569726d5254`.
It is not relabelled as compliant self-release.

## Forecast construction

Carry each eligible player's final 2023-24 per-game rates unchanged into
2024-25. Use the complete forecast cohort as the reference population.

- population SD: `ddof=0`;
- FG/FT: attempt-weighted reference percentage and
  `makes - reference_percentage × attempts`;
- category directions: eight positive, turnovers negative;
- zero variance: component zero with explicit status;
- aggregate: unweighted sum of nine components;
- ordering: aggregate descending, canonical player ID ascending;
- structural roster count: explicit `12 × 13 = 156` for this target benchmark,
  not inferred from the package size and not a generic engine constant;
- replacement: ordinal 157 if present, otherwise unavailable with nullable
  value above replacement.

The prior private prefreeze candidate at
`zscore-production-final-forecast-prefreeze-candidate.json` was rejected and
is retained byte-for-byte in the independent rejected-candidate snapshot. It
is not a valid freeze input and will not be overwritten.

The rejected v2 private prefreeze candidate is:

- path:
  `C:\Users\steverones\.copilot\session-state\baeb9984-a1e5-4aac-8c95-af634150b9dd\files\zscore-production-final-forecast-prefreeze-candidate-v2-20260911T213000Z.json`;
- nominal caller-supplied stamp: `2026-09-11T21:30:00Z`, not a literal
  wall-clock creation time;
- bytes: 2,194,034;
- file SHA-256:
  `6620d52a8a689f309cec9510a472e59f024ff9699ef6cf744cc1e826ce424ae2`;
- internal content SHA-256:
  `daa0d248f8283492f4b159509e0033626d6ef7c13ed2e198ea9942d125d68f53`;
- exact forecast-vector SHA-256:
  `0bfaa20748c3055d37178191183d281ecb6488f25e0f0e454cd5ba9f2efe5f4a`;
- runtime-result SHA-256:
  `ac4851e1334c34fc98a7331c3142e23f4c7cce5f3e6ad26b015c9580d5b39a88`;
- reference-player fingerprint:
  `2f0ca1f042e2631cf6d36b980130bcf6377a4579102cf93ee946353111fc9451`;
- reference count: 572;
- replacement state: available at required ordinal 157; and
- replacement aggregate threshold: `2.1390899410208184`.

This v2 candidate is not eligible for confirmation. Its nominal timestamp
defect is recorded by
`scoring-prefreeze-timestamp-deviation-20260911.md`, SHA-256
`32ec650611dd5907e6623864d2c11d2f7a87ba5e43445dc00b4b57fde2c0e0aa`.

The replacement candidate was required to use an actual UTC sample taken
immediately before generation and to have a separate receipt recording the
sample, command, working directory, complete candidate mapping, package/release
identities, process observations, and output identities.

The independently rejected v3 candidate was:

- path:
  `C:\Users\steverones\.copilot\session-state\baeb9984-a1e5-4aac-8c95-af634150b9dd\files\zscore-production-final-forecast-prefreeze-candidate-v3-20260911T2156424318657Z.json`;
- actual UTC sample passed unchanged as `--created-at`:
  `2026-09-11T21:56:42.4318657Z`;
- process-start observation: `2026-09-11T21:56:42.4304574Z`;
- process-completion observation: `2026-09-11T21:56:44.1069004Z`;
- bytes: 2,194,041;
- file SHA-256:
  `7a078006f1cc6b7f2a12aca1e81588c92dd03cdd051a723a267a5194dd108108`;
- internal content SHA-256:
  `3ebf682c2cc4490a1b3eb3845483ea608d5237a21764d0fc82132cd46fa934c4`;
- exact forecast-vector SHA-256:
  `0bfaa20748c3055d37178191183d281ecb6488f25e0f0e454cd5ba9f2efe5f4a`;
- runtime-result SHA-256:
  `ac4851e1334c34fc98a7331c3142e23f4c7cce5f3e6ad26b015c9580d5b39a88`;
- reference-player fingerprint:
  `2f0ca1f042e2631cf6d36b980130bcf6377a4579102cf93ee946353111fc9451`;
- reference count: 572;
- replacement state: available at required ordinal 157; and
- replacement aggregate threshold: `2.1390899410208184`.

Generation receipt:

- path:
  `C:\Users\steverones\.copilot\session-state\baeb9984-a1e5-4aac-8c95-af634150b9dd\files\zscore-production-final-forecast-generation-receipt-v3-20260911T2156424318657Z.json`;
- file SHA-256:
  `8b4d5a5fb695d550500b7f985a0098992e5e97c2d987a0f80b8bab6a24176a49`.

Canonical byte comparisons against v2 confirm equality of the complete
forecast vector, reference scales, prediction cuts, and exact bin assignments.
The changed artifact identity is attributable to the real timestamp and
corrected candidate/protocol lineage, not numerical regeneration differences.

The independently rejected governing-contract v4 candidate was:

- path:
  `C:\Users\steverones\.copilot\session-state\baeb9984-a1e5-4aac-8c95-af634150b9dd\files\zscore-production-final-forecast-prefreeze-candidate-v4-20260911T2232025866191Z.json`;
- actual UTC sample passed unchanged as `--created-at`:
  `2026-09-11T22:32:02.5866191Z`;
- process-start observation: `2026-09-11T22:32:02.5847666Z`;
- process-completion observation: `2026-09-11T22:32:04.3769594Z`;
- bytes: 2,194,041;
- file SHA-256:
  `84cd5660262cd7c90367f8a3d6a6e738995b0a03964ab83eb0d9ec73d356082d`;
- internal content SHA-256:
  `a04768103155fe6177cc4c71d0fb8a7c979444744ecba9e4e9d4cbc57a5efc7f`;
- exact forecast-vector SHA-256:
  `0bfaa20748c3055d37178191183d281ecb6488f25e0f0e454cd5ba9f2efe5f4a`;
- runtime-result SHA-256:
  `ac4851e1334c34fc98a7331c3142e23f4c7cce5f3e6ad26b015c9580d5b39a88`;
- reference-player fingerprint:
  `2f0ca1f042e2631cf6d36b980130bcf6377a4579102cf93ee946353111fc9451`;
- reference count: 572;
- replacement state: available at required ordinal 157; and
- replacement aggregate threshold: `2.1390899410208184`.

V4 generation receipt:

- path:
  `C:\Users\steverones\.copilot\session-state\baeb9984-a1e5-4aac-8c95-af634150b9dd\files\zscore-production-final-forecast-generation-receipt-v4-20260911T2232025866191Z.json`;
- bytes: 10,188; and
- file SHA-256:
  `77ba9a24d8d11649da97eb95dc5365b57a44cc7382d495e9aea7a59bf758f58c`.

Canonical comparisons against v3 confirm exact equality of the complete
forecast vector, frozen reference scales, prediction cuts, exact bin
assignments, runtime result, reference fingerprint, replacement state, and
replacement threshold. Only the real creation timestamp and corrected
candidate/protocol/model-card lineage changed.

The executable-gap replacement v5 candidate is:

- path:
  `C:\Users\steverones\.copilot\session-state\baeb9984-a1e5-4aac-8c95-af634150b9dd\files\zscore-production-final-forecast-prefreeze-candidate-v5-20260911T2300491066175Z.json`;
- actual UTC sample passed unchanged as `--created-at`:
  `2026-09-11T23:00:49.1066175Z`;
- process-start observation: `2026-09-11T23:00:49.1048834Z`;
- process-completion observation: `2026-09-11T23:00:50.8720198Z`;
- bytes: 2,194,041;
- file SHA-256:
  `d78a971d0fe6b30148e891ebc862a64981e24a4ba81f80c9dbea20ac49051fbf`;
- internal content SHA-256:
  `564d8f3570d8b8ce6ba7dd00b0923e847973174a4b0c4e758201a2188fea6eaf`;
- exact forecast-vector SHA-256:
  `0bfaa20748c3055d37178191183d281ecb6488f25e0f0e454cd5ba9f2efe5f4a`;
- runtime-result SHA-256:
  `ac4851e1334c34fc98a7331c3142e23f4c7cce5f3e6ad26b015c9580d5b39a88`;
- reference-player fingerprint:
  `2f0ca1f042e2631cf6d36b980130bcf6377a4579102cf93ee946353111fc9451`;
- reference count: 572;
- replacement state: available at required ordinal 157; and
- replacement aggregate threshold: `2.1390899410208184`.

V5 generation receipt:

- path:
  `C:\Users\steverones\.copilot\session-state\baeb9984-a1e5-4aac-8c95-af634150b9dd\files\zscore-production-final-forecast-generation-receipt-v5-20260911T2300491066175Z.json`;
- bytes: 10,188; and
- file SHA-256:
  `3910ba2c28df3c5a5e6ea34037285fd63980aa6bf9c922c0956b71340dcf6820`.

Canonical comparisons against v4 confirm exact equality of the complete
forecast vector, frozen reference scales, prediction cuts, exact bin
assignments, runtime result, reference fingerprint, replacement state, and
replacement threshold. The executable protocol hash is also unchanged because
the corrections enforce its already-frozen semantics rather than changing
policy. Only the real creation timestamp and corrected evaluator, test, and
model-card lineage changed.

The rejected candidate was:

- path:
  `C:\Users\steverones\.copilot\session-state\baeb9984-a1e5-4aac-8c95-af634150b9dd\files\zscore-production-final-forecast-prefreeze-candidate.json`;
- bytes: 2,193,251;
- file SHA-256:
  `852b3ee18361fca8f8dd8456b12462b3e8ed6190c9b79abd7dbfc57f5ad78a2f`;
- internal content SHA-256:
  `b453eca7d672e00ff63360931cfd32d178df80eec62f5237d75098d785a78caf`;
- exact forecast-vector SHA-256:
  `0bfaa20748c3055d37178191183d281ecb6488f25e0f0e454cd5ba9f2efe5f4a`;
- runtime-result SHA-256:
  `ae977bbf305c51a3547e007c534698ee6850fdef2a293f1bf1d42392f42f01ee`;
- reference-player fingerprint:
  `2f0ca1f042e2631cf6d36b980130bcf6377a4579102cf93ee946353111fc9451`;
- replacement state: available at required ordinal 157; and
- replacement aggregate threshold: `2.1390899410208184`.

The rejected artifact's exact replacement player identity and all player-level
rows remain private and are not reused as release authority.

Frozen 2023-24 reference scales:

| Category | Mean/impact mean | Population SD | Reference percentage |
|---|---:|---:|---:|
| PTS | 8.422110637780147 | 6.784297163824275 | — |
| REB | 3.374554310567026 | 2.424901696738034 | — |
| AST | 2.001325386821212 | 1.874017897815133 | — |
| STL | 0.590327603475621 | 0.392835884304264 | — |
| BLK | 0.400272153103270 | 0.410541240245825 | — |
| 3PM | 0.941158694089765 | 0.877346852024681 | — |
| TO | 0.981546349851321 | 0.794649381381301 | — |
| FG impact | ~0 | 0.488438016080723 | 0.466711047389612 |
| FT impact | ~0 | 0.206355213850151 | 0.776814797526196 |

## Prediction-only calibration bins

For every category and the aggregate:

- compute Type-7 quantiles at 0.2, 0.4, 0.6, and 0.8 using **all forecast
  predictions before outcome pairing**;
- collapse exact adjacent duplicate cuts deterministically;
- assign with `bisect_right`, so a prediction exactly equal to a cut enters the
  upper bin;
- preserve empty bins with count zero and null summaries; and
- seal a hash over canonical player ID → bin assignment.

The cuts, counts, and exact assignment hashes are now frozen in the private
candidate:

| Metric | Type-7 cuts | Bin counts | Assignment SHA-256 |
|---|---|---|---|
| PTS | -0.820080, -0.506473, -0.070036, 0.774041 | 115/114/114/114/115 | `cfe6c0276b4e2866337fe9c773ce60508925939899dd482e52758dcc978ef027` |
| REB | -0.810313, -0.438350, 0.042858, 0.676379 | 115/114/114/113/116 | `d5db8a4b5968b1def625b49e8cfbd44f6abd506f7ab91e389f3c6b27cf0d1b38` |
| AST | -0.753758, -0.491968, -0.187210, 0.707321 | 115/114/114/114/115 | `8214a6baf8865c138232d9e698263cae8a0a3d556af5b9261038a76dc972ad75` |
| STL | -0.910341, -0.345646, 0.168588, 0.810832 | 115/112/116/114/115 | `608c8d40e70e1c64e6d72ca6f4aba2cdd0ceb978749231084229b498daea48b1` |
| BLK | -0.724976, -0.441411, -0.056621, 0.542048 | 115/114/114/114/115 | `6e1f9d4b8d3a3f59d7923a4f91a03fe339b1dfff5836b06c072b918b2a086146` |
| 3PM | -0.936962, -0.502833, 0.061439, 0.808720 | 115/112/116/114/115 | `cd8ecb7c26f41e7e22036f6410770fc0b5288aadf61f52d265d5a025262475d6` |
| TO | -0.692225, 0.034672, 0.478854, 0.815722 | 115/114/114/108/121 | `ae3627dee2a31a2196db59363e034926d8df68bfed4e4b1e2f9c25b263bf8072` |
| FG impact | -0.667049, -0.318380, ~0, 0.560223 | 115/114/112/116/115 | `064b6271f6c5e695dc6683311083db8fd773f0110d3133209ef9dc3dffcd4108` |
| FT impact | -0.484865, -0.093786, 0.087195, 0.403982 | 115/114/114/114/115 | `0f5c1a460e7ccdf79c0633c10dd6e5d2ead3808db6f590f61c1bf65807ddbe27` |
| Aggregate | -4.088353, -1.803898, 0.438770, 3.593673 | 115/114/114/114/115 | `b95be84a9a63362cd77a26c0c9ad2cae0a076d8cd09162266d497d919574ce26` |

The corrected candidate is expected to preserve these prediction-only values
because the production math and released 2023-24 input are unchanged. They
must nevertheless be reverified against the newly named artifact. Once
independently confirmed, they may not be recomputed or adjusted after any
outcome or outcome-presence release.

## Executable release and accounting contracts

The frozen evaluator accepts only these exact schema versions:

- accepted freeze: `zscore-final-evaluation-freeze-v2`;
- independent confirmation: `zscore-final-freeze-confirmation-v1`;
- outcome manifest: `zscore-final-outcome-manifest-v2`;
- forecast-key manifest: `zscore-final-forecast-key-manifest-v1`;
- release/unblind: `zscore-final-outcome-unblind-v2`; and
- append-only result: `zscore-final-evaluation-result-v1`.

The accepted freeze binds the complete executable preregistration, not just a
protocol label. The hash-bound object contains:

1. the research question, complete 572-player forecast cohort, outcome
   eligibility, zero-second policy, and missingness handling;
2. the released development and final-input package/release identities plus
   prior-exposure and timestamp-deviation boundaries;
3. the exact production-only feature set and explicit exclusions;
4. the single prespecified historical carry-forward model variant;
5. the sealed 2024-25 split, date/game-ID boundary, fields, and key statuses;
6. the primary aggregate magnitude-calibration metric, required per-category
   and aggregate bootstrap/anchor/bin evidence, ideal references, and
   no-numerical-tolerance decision rule;
7. secondary errors, rank and support sensitivities, planned outputs, all stop
   conditions, append-only reporting boundary, no-tuning rule, and scope
   limitations.

The freeze also binds the full fresh experiment ID, worker, all current
candidate-file hashes, exact sealed forecast file/content/vector/runtime/
reference identities, and authorized independent releasers. The confirmation
must be later than the forecast and freeze, reproduce those identities, and
have an independent quant reviewer role. A mutable DRAFT is never release
permission.

The candidate-file map is closed: it must contain every required label and no
others. The same complete map must appear in the sealed forecast and accepted
freeze and must match the actual files supplied to the evaluator. Executable
labels must resolve to the implementation modules actually executing, rather
than arbitrary caller-designated archives.

The outcome release/unblind must be later than the independent confirmation
and bind the same experiment, worker, freeze, forecast, direct package identity,
manifest file, and authorized independent releaser. The manifest's package
identity transitively binds its exact purpose, season, outcome payload, and key
manifest. The evaluator does not open outcome metadata or payload rows until
the release record verifies.

The complete timezone-aware custody order is:

`input release < sealed forecast creation < accepted freeze < independent
confirmation < forecast-key manifest <= outcome manifest < release/unblind`.

The outcome handoff is one direct governing `sealed_outcome` package manifest.
It is not nested in a worker-defined wrapper. Its `content_sha256` is SHA-256
over:

```text
canonical sorted compact UTF-8 manifest excluding only package_id and
content_sha256
+ LF
+ ordered filename<TAB>sha256 payload lines joined by LF
```

There is no line feed after the final payload digest. `package_id` is the
compact UTC `created_at` value plus `-` plus the first 16 digest characters.
The normative known-answer fixture uses
`2026-09-11T22:30:45.123456Z`, `a.csv` with 64 zeroes, and `b.json` with
64 `f` characters; its content digest is
`04192807db086eedf5e71580e64d3412cf7b58a9d439a618b9626f3ec3ab266b`
and package ID is
`20260911T223045123456Z-04192807db086eed`.

The direct package manifest declares exactly two payloads in order:
`outcome_payload` CSV and `forecast_key_manifest` JSON. The schemas are closed,
roles are unique, and no extra payload is legal. Filenames, byte lengths, row
counts, file SHA-256 values, and the key manifest's internal content SHA-256
must match actual files. The independent release/unblind record references
only this immutable package identity and manifest file; it cannot redeclare
payloads.

Accepted-freeze shape:

```json
{
  "schema_version": "zscore-final-evaluation-freeze-v2",
  "record_type": "accepted_zscore_final_evaluation_freeze",
  "experiment_id": "<exact experiment>",
  "freeze_id": "<unique freeze>",
  "created_at": "<actual timezone-aware UTC observation>",
  "status": "accepted",
  "worker_id": "<worker>",
  "accepted_by": {"role": "owner_supervisor", "identity": "<owner>"},
  "protocol": {
    "protocol_version": "zscore-production-final-preregistration-v2",
    "experiment_id": "<exact experiment>",
    "research_question_and_eligible_cohort": "<complete frozen object>",
    "released_development_and_forecast_inputs": "<complete frozen object>",
    "feature_set": "<complete frozen object>",
    "model_variants": "<complete frozen object>",
    "held_out_outcome_and_split": "<complete frozen object>",
    "primary_metric_calibration_and_decision_rule": "<complete frozen object>",
    "secondary_metrics_and_sensitivities": "<complete frozen object>",
    "planned_outputs_and_stop_conditions": "<complete frozen object>"
  },
  "protocol_sha256": "<sha256>",
  "candidate_files": {"<every required label>": "<sha256>"},
  "forecast": {
    "file_sha256": "<sha256>",
    "content_sha256": "<sha256>",
    "forecast_vector_sha256": "<sha256>",
    "runtime_result_sha256": "<sha256>",
    "reference_player_fingerprint": "<sha256>",
    "input_package_id": "<package>",
    "input_release_id": "<release>"
  },
  "authorized_outcome_releasers": ["<independent releaser>"],
  "content_sha256": "<internal canonical content sha256>"
}
```

Outcome-manifest shape:

```json
{
  "schema_version": "zscore-final-outcome-manifest-v2",
  "record_type": "sealed_zscore_final_outcome_manifest",
  "experiment_id": "<exact experiment>",
  "freeze_id": "<accepted freeze>",
  "package_id": "<outcome package>",
  "content_sha256": "<governing package content sha256>",
  "created_at": "<actual UTC package-creation observation>",
  "dataset_class": "sealed_outcome",
  "purpose": "Sealed 2024-25 regular-season appearance-production outcomes and exact forecast-key accounting for frozen experiment zscore-production-carryforward-v1-exp-20260911T201744001625Z only.",
  "season": "2024-25",
  "source_cutoff": {
    "latest_game_date_represented": "<maximum emitted game_date>",
    "latest_retrospective_capture_at": "<accepted retrospective capture timestamp>",
    "meaning": "Retrospective final official box scores, not pregame or archived as-of forecasts; later official corrections may be present."
  },
  "fields_released": [
    {
      "payload_role": "outcome_payload",
      "fields": ["<exact 17 CSV fields in order>"]
    },
    {
      "payload_role": "forecast_key_manifest",
      "fields": [
        "forecast_player_id",
        "status",
        "complete_payload_rows",
        "incomplete_source_rows",
        "unresolved_source_rows",
        "missing_required_fields"
      ]
    }
  ],
  "fields_withheld": [
    "all 2025-26 season data",
    "participation data",
    "availability data",
    "injury data",
    "roster data",
    "opportunity data",
    "market data",
    "vendor projections",
    "games-played assumptions",
    "foreign or outcome-only players",
    "source fields outside the declared payload schemas"
  ],
  "custodian": {
    "role": "data_engineer_custodian",
    "identity": "<non-worker, non-releaser custodian>",
    "attested_at": "<same actual UTC package-creation observation>",
    "attestation": {
      "confirmed_freeze_and_forecast_keys_verified_before_source_access": true,
      "stable_read_only_transaction": true,
      "access_restricted_to_2024_25_and_frozen_forecast_ids": true,
      "credited_zero_second_appearances_retained": true,
      "missing_outcomes_not_fabricated": true,
      "excluded_data_not_accessed_or_included": true,
      "retrospective_capture_manifest_verified": true,
      "package_is_not_release_or_unblind": true
    }
  },
  "forecast": "<exact frozen forecast binding>",
  "payloads": [
    {
      "role": "outcome_payload",
      "filename": "player_game_logs_2024-25.csv",
      "bytes": 123,
      "rows": 1,
      "sha256": "<sha256>"
    },
    {
      "role": "forecast_key_manifest",
      "filename": "forecast-key-manifest.json",
      "bytes": 123,
      "rows": 572,
      "sha256": "<sha256>",
      "content_sha256": "<internal canonical content sha256>"
    }
  ]
}
```

The exact predeclared regular-season consistency boundary is 2024-10-22
through 2025-04-13 inclusive, season type `Regular Season`, and ten-digit NBA
game IDs matching `00224xxxxx`. Calendar-2025 games inside 2024-25 are valid.
Every emitted row must satisfy that boundary, and the maximum emitted
`game_date` must equal `source_cutoff.latest_game_date_represented`. The capture
timestamp must follow the season and not postdate package creation. This rule
detects foreign-season rows but does not prove source completeness or the
absence of later official corrections.

The outcome CSV contract is exactly:

```text
canonical_player_id,nba_game_id,game_date,season,season_type,seconds_played,
field_goals_made,field_goals_attempted,free_throws_made,
free_throws_attempted,three_pointers_made,points,rebounds,assists,steals,
blocks,turnovers
```

Each frozen forecast key appears exactly once in the forecast-key manifest.
No foreign key is allowed. Example:

```json
{
  "forecast_player_id": 123,
  "status": "complete_observation",
  "complete_payload_rows": 82,
  "incomplete_source_rows": 0,
  "unresolved_source_rows": 0,
  "missing_required_fields": []
}
```

The key-manifest enclosing record is:

```json
{
  "schema_version": "zscore-final-forecast-key-manifest-v1",
  "record_type": "sealed_zscore_forecast_key_manifest",
  "experiment_id": "<exact experiment>",
  "freeze_id": "<accepted freeze>",
  "created_at": "<actual timezone-aware UTC observation>",
  "season": "2024-25",
  "forecast": "<exact frozen forecast binding>",
  "forecast_key_count": 572,
  "status_counts": {
    "complete_observation": 0,
    "no_observed_box_score": 0,
    "identity_unresolved": 0,
    "incomplete_required_fields": 0
  },
  "keys": ["<exactly 572 key-accounting rows>"],
  "content_sha256": "<internal canonical content sha256>"
}
```

Release/unblind shape:

```json
{
  "schema_version": "zscore-final-outcome-unblind-v2",
  "record_type": "independent_quant_final_outcome_unblind",
  "release_id": "<unique release>",
  "experiment_id": "<exact experiment>",
  "freeze_id": "<accepted freeze>",
  "worker_id": "<worker>",
  "created_at": "<actual timezone-aware UTC observation>",
  "releaser": {
    "role": "independent_quant_releaser",
    "identity": "<authorized non-worker>"
  },
  "disposition": "approved_final_outcome_unblind",
  "package": {
    "package_id": "<outcome package>",
    "content_sha256": "<governing package content sha256>",
    "manifest_filename": "outcome-manifest.json",
    "manifest_bytes": 123,
    "manifest_file_sha256": "<sha256>"
  },
  "forecast": "<exact frozen forecast binding>",
  "content_sha256": "<internal canonical content sha256>"
}
```

Allowed statuses and exact behavior:

- `complete_observation`: at least one complete payload row, zero unresolved
  rows, and payload games equal `complete_payload_rows`; coherent incomplete
  source rows remain allowed, but zero incomplete rows is equivalent to an
  empty `missing_required_fields` list;
- `no_observed_box_score`: all three row counts are zero and the outcome
  remains missing, never zero;
- `identity_unresolved`: no complete rows, at least one unresolved row, and no
  fabricated payload;
- `incomplete_required_fields`: no complete rows, at least one incomplete row,
  a non-empty required-field list, and no fabricated payload.

Duplicate, absent, or foreign keys; status/count contradictions; malformed or
non-finite values; negative values; made greater than attempted; wrong season
or schema; payload/key count mismatch; and no complete observed forecast player
all stop evaluation. Eligibility remains the previously approved at-least-one
complete credited game rule. There is no future-survivor or seconds-played
filter. If primary aggregate calibration is unestimable after otherwise valid
accounting, the evidence is insufficient and evaluation stops before emitting
a production result.

Synthetic tests exercise a complete positive path through
`zscore_backtest.run_final_heldout_evaluation` and refuse wrong experiment,
freeze, worker, role, purpose, season, order, hashes, candidate bytes, missing/
duplicate/foreign keys, invalid physical values, no evaluable observations,
independently resealed but semantically altered scales, vectors, or bins,
wrong governing package identity conventions, omitted manifest requirements,
custodian/releaser/worker collisions, false cutoffs, foreign dates/game IDs,
released/withheld schema contradictions, and incomplete or numerically altered
preregistration.

## Immutable pre-unblind and append-only result boundary

Before unblind, the accepted freeze, confirmation, candidate files, protocol,
sealed forecast, prediction scales, bins, assignments, and exact file/content
identities are immutable. Any change creates a new candidate and requires a new
independent confirmation and release.

After a valid unblind, no estimator implementation, eligibility rule,
transform, metric, bootstrap, bin, or missingness rule may change. The only
permitted mutation is append-only publication of the evaluator's already
defined result document and a model-card result addendum. Attaching results
does not require or permit modifying estimator code.

## Held-out outcome and pairing

- season: 2024-25 regular season;
- same exact schema and validation as the forecast input;
- all credited appearance rows count regardless of seconds;
- outcome eligibility requires at least one complete credited row;
- pair by canonical player ID;
- a missing outcome remains missing, never zero;
- the outcome payload is restricted to the sealed 572 forecast keys, so
  source-population outcome-only players are **not measured**;
- missing outcomes do not change forecast reference membership, means, SDs,
  ratio percentages, ordering, replacement, cuts, or assignments.

Report all 572 forecast keys by status, complete outcome rows, paired players,
incomplete-source rows, unresolved-source rows, and credited zero-second rows.
Do not report zero outcome-only players as though the unrestricted source
population had been observed. Invalid released input refuses rather than being
silently omitted.

## Frozen outcome transform

Apply the sealed 2023-24 reference means, population SDs, and ratio reference
percentages to realized 2024-25 per-game rates. Do not compute or use 2024-25
means, SDs, reference percentages, ranks, or replacement state to normalize the
outcomes.

When a forecast category has zero variance, its forecast and realized
components remain zero under the declared version-1 semantics and that
category's calibration is not evaluable.

## Metrics

Primary calibration, independently for all nine categories and aggregate:

- unweighted player-level OLS:
  `realized_frozen_scale = intercept + slope × forecast`;
- status not evaluable with fewer than two pairs or zero predictor variance;
- intercept and slope;
- deterministic player-block bootstrap 95% intervals;
- 2,000 resamples;
- base seed `20260911`, with metric-specific seed derived as the first eight
  bytes of SHA-256 over `"{base_seed}:{metric_key}"`;
- Type-7 bootstrap quantiles at 0.025 and 0.975;
- bootstrap draws with zero predictor variance are skipped and the number of
  usable draws must be reported;
- fitted realized anchors at forecast `+1` and `+2`; and
- prediction-only bin counts, missing counts, mean prediction, and mean
  realized frozen-scale outcome.

Secondary metrics:

- MAE;
- RMSE; and
- Spearman correlation using deterministic average ranks for ties.

Primary cohort: every paired player with at least one credited outcome game.
Support sensitivities repeat aggregate calibration and secondary metrics for at
least 10, 25, and 50 credited outcome games. These are sensitivities, not
eligibility filters.

## Interpretation and decision rule

Intercept 0 and slope 1 are reference values. No post-result numeric tolerance,
positive-slope veto, bin-sign veto, or `[0.8, 1.2]`/`±0.25` rule is authorized.
A valid poor result must be published rather than tuned away.

The result may establish the empirical magnitude and spacing of this historical
carry-forward benchmark on one later season. It cannot establish:

- calibration of current vendor or blended projections;
- availability or expected-games performance;
- causal effects;
- auction dollars, risk-adjusted values, punt values, or recommendations; or
- generalization to rookies or players without a prior-season appearance.

Final Model-gate disposition and any runtime activation require independent
review of the complete result and a claim no broader than the released evidence.
This draft itself passes no gate.

## Blind spots fixed before outcome access

Trades, coaching and rotation changes, undisclosed injuries, rest and shutdown
intent, personal matters, front-office intent, rookie performance, departures
from the league, and reference-pool composition changes are unseen. The
appearance-only outcome cannot separate production decline from availability
loss, because missing games and absent players are not zero production.

## Stop conditions

Stop without outcome access if:

- the purpose-correct forecast release is missing or mismatched;
- candidate code/test/protocol hashes differ from the accepted freeze;
- the sealed forecast artifact is absent or cannot be reproduced;
- the outcome release does not bind the same experiment and forecast hash;
- any 2025-26 row-level payload is included;
- availability, games-played assumptions, market, mock, or vendor-total fields
  are included; or
- applying the protocol would expose another experiment's reserved holdout.
