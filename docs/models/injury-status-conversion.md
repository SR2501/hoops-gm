# Injury status conversion model card

**Owner:** quant
**Model version:** `injury-status-conversion-v2-scoped-a-v1`
**Calibration machinery:** `calibration-machinery-v1`
**Status:** eligible for runtime activation; all eight frozen conditions passed
**Evidence:** `backend/tests/model_evidence/injury_status_conversion_v1.json`

## Result at a glance

The frozen procedure selected `three_band_jeffreys`. Its 3,940-row chronological
holdout has Brier score **0.0376449**, calibration-in-the-large (CITL)
**+0.0027131**, expected calibration error (ECE) **0.0062994**, and clipped log
loss **0.1163733**. The paired Brier difference against the refitted global
baseline is **-0.1006341**, with a pre-registered 5,000-resample 95% interval of
**[-0.1087733, -0.0923892]**. All three emitted probabilities are inside their
held-out Wilson 95% intervals. All eight frozen activation conditions pass.

This is an availability prior, not a production projection. ADR-002 still
requires per-game production and expected games to remain separate until the
explicit expected-games fusion.

## Blind-break record

The outcome blind was broken once on **2026-08-31**, under frozen v2
`injury-status-conversion-v2-20260821T145900Z` plus the owner's 2026-08-29
**scoped acceptance** of v3 Change A.

- Change A's report-era refits were binding reporting requirements and remain
  diagnostic, not activation conditions.
- Change B was not accepted as an activation gate. Its informative-status table
  is display-only and non-gating under ADR-018. **There is no condition 9.**
- ADR-018 itself remains **Proposed**.
- No split, candidate, estimator, threshold, binning convention, or bootstrap
  setting changed after outcome access. The holdout was evaluated once.
- The frozen procedure was implemented and tested against synthetic cohorts
  before data access. An independent pre-unblind quant review found no
  methodology or arithmetic blocker. Its one evidence-field naming concern was
  corrected before access. The durable review record is
  `backend/tests/model_evidence/injury_status_conversion_review.md`.

## What it predicts

For one scheduled game and one player, the model predicts the probability of a
direct participation outcome of `played`, given the player's **single latest
eligible official report status strictly before tip-off**.

The unit is one canonical player-game, not one report row. Three successive
reports for the same player-game contribute one observation: the latest
pre-tipoff one. Stable NBA game and player identifiers form the evidence
identity. Missing identities, missing participation rows, and non-direct
outcomes do not become non-play; they are excluded and bounded separately.

## Inputs

The fitted predictor is report status only:

`out`, `doubtful`, `questionable`, `probable`, or `available`.

Lead time, report era, and stated-reason category are reporting labels for
pre-registered or display-only sensitivities. They are not fitted features.
Stated reasons are not trusted as medical truth.

The outcome is `played` versus the direct non-play outcomes
`did_not_play`, `did_not_dress`, `not_with_team`, and `inactive`. `unknown`
and missing outcomes are excluded.

## Training window and split

The cohort covers the 2025-26 regular season from `2025-10-21` through
`2026-04-12`. The split is chronological over 164 distinct game dates:

| Partition | Game dates | Date range | Direct rows |
|---|---:|---|---:|
| Development | 82 | `2025-10-21..2026-01-13` | 6,112 |
| Selection | 41 | `2026-01-14..2026-03-01` | 3,546 |
| Holdout | 41 | `2026-03-02..2026-04-12` | 3,940 |

The selected structure was refitted on development plus selection only.

## Method and selection

All candidates use the Jeffreys estimate
`(plays + 0.5) / (observations + 1)`. Candidates were considered in frozen
complexity order and advanced only for selection-Brier improvement of at least
`0.005`.

| Candidate | Selection Brier | Improvement over incumbent | Advanced |
|---|---:|---:|---|
| `global_jeffreys` | 0.1492169 | n/a | yes |
| `three_band_jeffreys` | 0.0371570 | +0.1120599 | yes |
| `five_status_jeffreys` | 0.0373374 | -0.0001804 | no |

The selected final fit is:

| Emitted band | Statuses | Training n | Plays | `p(play)` |
|---|---|---:|---:|---:|
| unlikely | `out`, `doubtful` | 7,449 | 6 | **0.0008725** |
| uncertain | `questionable` | 849 | 459 | **0.5405882** |
| likely | `probable`, `available` | 1,360 | 1,168 | **0.8585599** |

## Primary held-out calibration

Calibration, not accuracy, is the primary evidence.

| Emitted `p(play)` | Held-out n | Played | Observed rate | Wilson 95% | In interval |
|---:|---:|---:|---:|---:|---|
| 0.0008725 | 3,046 | 1 | 0.0003283 | [0.0000580, 0.0018574] | yes |
| 0.5405882 | 335 | 165 | 0.4925373 | [0.4393900, 0.5458538] | yes |
| 0.8585599 | 559 | 487 | 0.8711986 | [0.8408752, 0.8964549] | yes |

| Metric | Held-out value |
|---|---:|
| Observations / plays | 3,940 / 653 |
| Predicted mean / observed rate | 0.1684491 / 0.1657360 |
| CITL (`mean(predicted) - observed`) | **+0.0027131** |
| ECE | **0.0062994** |
| Maximum calibration error | 0.0480509 |
| Brier | **0.0376449** |
| Global-baseline Brier | 0.1382790 |
| Paired Brier difference | **-0.1006341** |
| Paired 95% interval | **[-0.1087733, -0.0923892]** |
| Log loss / clipped observations | 0.1163733 / 0 |

The interval resamples player-game observations, not player or game clusters.
It therefore does not account for within-player or within-game correlation.

### Per-status display

These rows are required disclosure. They do not create new activation
conditions.

| Status | Predicted | Held-out n | Played | Observed | Wilson 95% | In interval |
|---|---:|---:|---:|---:|---:|---|
| `out` | 0.0008725 | 2,963 | 1 | 0.0003375 | [0.0000596, 0.0019093] | yes |
| `doubtful` | 0.0008725 | 83 | 0 | 0.0000000 | [0.0000000, 0.0442353] | yes |
| `questionable` | 0.5405882 | 335 | 165 | 0.4925373 | [0.4393900, 0.5458538] | yes |
| `probable` | 0.8585599 | 92 | 87 | 0.9456522 | [0.8790147, 0.9765649] | **no** |
| `available` | 0.8585599 | 467 | 400 | 0.8565310 | [0.8218252, 0.8854192] | yes |

The pooled likely band passes, while `probable` alone is under-predicted by
8.71 percentage points and falls outside its interval. That is exactly the
within-band behavior pooled calibration cannot expose. The accepted protocol
makes it visible but does not let it become a ninth activation condition.

## Activation verdict

| Frozen v2 condition | Result |
|---|---|
| 1. Selected model is status-conditioned | pass |
| 2. Paired-Brier interval upper endpoint is below zero | pass (`-0.0923892`) |
| 3. Absolute CITL is at most 0.10 | pass (`0.0027131`) |
| 4. Every emitted bin has at least 20 observations | pass (minimum 335) |
| 5. Every emitted probability is inside its bin's Wilson 95% interval | pass |
| 6. Every status has at least 30 held-out direct outcomes | pass (minimum 83) |
| 7. No unlikely/uncertain/likely monotonic reversal | pass |
| 8. Cohort fingerprint and every exclusion count reproduce | pass |

**Verdict:** eligible for runtime activation. This unit publishes the model and
evidence but adds no database persistence, API, browser display, or write path.

## Required sensitivities

### Exclusion bounds

No held-out row had an explicit `unknown` outcome. Five held-out `out` rows
lacked a participation row. Fourteen held-out rows had unresolved identity or
no NBA anchor (`out` 11, `available` 2, `doubtful` 1). Treating each class as
all-play or all-non-play does not enter fitting or the primary verdict. The
largest informative-status movement is `doubtful`: 0/83 direct becomes a
play-rate range of **[0, 1/84 = 0.0119048]** under the unresolved-identity
bound.

### Lead-time bands

| Minutes before tip | Held-out n | Brier | CITL | ECE | Display finding |
|---|---:|---:|---:|---:|---|
| `<=60` | 1,673 | 0.0261913 | +0.0014038 | 0.0054237 | uncertain bin n=14, below 20 and outside Wilson |
| `61-180` | 1,613 | 0.0453837 | -0.0003384 | 0.0041631 | none |
| `181-540` | 654 | 0.0478576 | +0.0135884 | 0.0138086 | none |
| `>540` | 0 | n/a | n/a | n/a | counts only, as frozen |

All lead-time results are non-gating sensitivities.

### Change A: report-era refits

The selected three-band structure was refitted separately on legacy-only and
short-lead-only **development** rows, then both were evaluated on the same
100% short-lead holdout. No status fell below the 20-row era-training floor.

| Development era | Train n | unlikely | uncertain | likely | Holdout Brier | CITL | ECE | Bins outside Wilson |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `legacy_hourly` | 4,166 | 0.0007783 | 0.5032895 | 0.8512974 | 0.0374919 | -0.0015614 | 0.0040857 | none |
| `short_lead_fifteen_minute` | 1,946 | 0.0003298 | 0.5805085 | 0.8365079 | 0.0382545 | +0.0025591 | 0.0124028 | uncertain, likely |

This is training-era sensitivity, not held-out legacy calibration. It cannot
separate era from lead time because the holdout contains no legacy rows. The
short-lead-only development refit is materially less calibrated in its
uncertain and likely bands, but Change A is diagnostic and the pooled frozen
fit remains primary.

## Display-only restricted calibration

Change B's informative statuses (`doubtful`, `questionable`, `probable`) contain
510 holdout rows. Their display-only report has Brier **0.1763352**, CITL
**+0.0159941**, ECE **0.0474156**, and the likely/probable bin outside Wilson.
It is stamped `display_only_adr_018`, is non-gating, and creates no condition 9.

The pre-unblind card also required a health-reason display. Because "health
reason" had no single accepted definition, the evidence freezes an explicit
proxy before access: `Injury/Illness`, `Concussion Protocol`, and
`Return to Competition Reconditioning`. Its 2,941 rows have Brier **0.0328566**,
CITL **-0.0116736**, and ECE **0.0123214**; the likely bin is outside Wilson.
This is a post-hoc, non-gating descriptive slice. Stated reason is neither a
feature nor ground truth.

## Mandatory shutdown-window limitation

The following is copied verbatim from
`docs/adapters/nba-injury-report-cohort-admissibility-2025-26.json`:

> THE HOLDOUT IS THE END-OF-SEASON SHUTDOWN WINDOW, AND IT IS NOT THE REGIME THE TOOL IS USED IN. §4's chronological rule puts the held-out range at late February to mid-April: eliminated teams shutting players down, seeding races, pre-playoff load management. The tool is used from draft day onward, weighted October-March, and §7 permits ONE evaluation. v1's holdout was late December — mid-season and unremarkable — so widening did not merely make the holdout bigger, it silently changed its character. 'Widen the cohort' is satisfied without being met, and no count distinguishes the two outcomes. Declared pre-unblind as a limitation by owner ruling; the split boundaries are deliberately NOT moved, because choosing different proportions BECAUSE these ones are inconvenient is the trap §4 already names. THIS MUST REACH THE MODEL CARD VERBATIM.

## What this model cannot see

- Whether a team's public designation or stated reason is medically truthful.
- Warm-up setbacks, illness, or coaching decisions after the last eligible
  report.
- Trades, buyouts, waivers, G League recalls, and changing roster eligibility.
- Coaching changes, minutes restrictions, shutdown policy, tanking, or
  front-office intent.
- Undisclosed injuries or absences absent from the report.
- The 2026-27 season for which this 2025-26 estimate is only a prior.
- Era performance outside a short-lead holdout.
- Within-player and within-game correlation in the reported bootstrap interval.
- Production conditional on playing; that remains a separate ADR-002 quantity.

## Known failure modes and use constraints

- `out` and `doubtful` share one estimate; `probable` and `available` share
  another. A pooled band can pass while one member is miscalibrated. The held-out
  `probable` row demonstrates this, so the per-status display must travel with
  the model.
- `questionable` is not a universal coin flip. The frozen estimate is 0.5406,
  the shutdown-window holdout observed 0.4925, and the two era-only development
  refits span 0.5033 to 0.5805.
- The model is a 2025-26 prior. It should be recalibrated with 2026-27 evidence
  under a new preregistration rather than silently tuned against this consumed
  holdout.
- No lead-time interaction was fitted. The lead-time tables are sensitivities,
  not alternate predictions.
- Calibration is necessary, not sufficient. This model has no estimate of
  playing time, production, role, or fantasy value conditional on playing.

## Reproducibility and input identity

The committed evidence is deterministic JSON. Its SHA-256 is
`f9e4ace0aae41ef52cb3ef851e4630bc094f64ff1d79f3b01ba2b8c3963ded69`
over 50,097 LF bytes.

| Input | Identity |
|---|---|
| Prepared merged store | `cohort-merged-2025-26.db`, 50,941,952 bytes, SHA-256 `5fe6110e8c89b91a22a78563111b982eda003c5fe53990143e57e73949554a04` |
| Adjacent receipt | 2,159 bytes, SHA-256 `87befcf2e73d9fec803328f9a5d7281c098274d4c03a7bbf217bb44ad7be154d` |
| Receipt participation source | SHA-256 `09ab985caa3ab5ffb3ae5546afb15a37b2e4d1f94e6dc762fb338faf2c63b181` |
| Receipt report-sweep source | SHA-256 `9f1b8107fbfb16d8681c23e737b6fd402309eb80e2c51bcf906530e9e1edcaf9` |
| Canonical identity fingerprint | `8e1986229b3644daa1f7bffa3ce2362e8cfb438da4b1085c0803aebe53f8176e` |
| Direct membership fingerprint | `bb67c0d20f1e8b91dd6148b3ce767478a89a88101a5301f2b4a2326c5ee1d12f` |
| Frozen implementation, LF-normalized | SHA-256 `f4b16a9909a6e8e0d080da550c1ea3d8cb812132d8a61393df665bf7e643c14c` |

The receipt matches the receipt embedded in the committed cohort manifest.
Every cohort fingerprint, status count, and exclusion count reproduced before
the activation verdict was emitted.

From `backend/`, with the authorized external data directory assigned to
`HOOPS_GM_DATA`, the frozen command is:

```powershell
$env:PYTHONPATH = "src"
python -m hoops_gm.availability.injury_status_conversion `
  --store "$env:HOOPS_GM_DATA\cohort-merged-2025-26.db" `
  --merge-receipt "$env:HOOPS_GM_DATA\cohort-merged-2025-26.db.merge-receipt.json"
```

The command is recorded for provenance, not permission to spend the holdout a
second time. The frozen evidence, not a rerun, is the Model-gate artifact.

## Change log

| Version | Date | Change |
|---|---|---|
| 0 | 2026-08-23 | Pre-unblind card skeleton and reporting contract. |
| 1 | 2026-08-31 | Blind broken once under frozen v2 plus scoped Change A; selected three-band fit, held-out calibration, all sensitivities, and eight-condition activation verdict published. |
