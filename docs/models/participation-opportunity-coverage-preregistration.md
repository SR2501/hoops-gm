# Participation opportunity coverage - frozen preregistration v1

**Owner:** quant
**Freeze id:** `participation-opportunity-coverage-v1-20260906T052618Z`
**Frozen at:** 2026-09-06T05:26:18Z
**Status:** frozen before an opportunity-coverage result exists. No model is
fitted, no outcome package is released, and no `p(play)` value is emitted.

This document satisfies criterion 1 of
`participation-opportunity-coverage` only. It freezes the player-game cohort,
the maximum acceptable `unknown` share, and the coverage proceed predicate
before the coverage report is built. It does not satisfy criteria 2 or 3, does
not mark that backlog item done, and does not claim the Model gate.

The accepted availability protocol remains controlling:
`docs/models/availability-model-preregistration-v1-PROPOSED.md`. This document
makes its opportunity-coverage terms independently testable; it does not relax
or replace any of that protocol's other fit vetoes.

---

## 1. Prospectivity and inspection disclosure

At freeze time the repository states that no complete player-game opportunity
denominator exists, `unknown_share` is not calculable, and no public opportunity
envelope or sealed keyed package has been emitted. I did **not** query a
database, run coverage code, count silent player-games, derive a roster
denominator, inspect a coverage report, or compute, estimate, look up, or infer
an actual `unknown` share.

I inspected only:

- the repository documents named in the task, including the accepted
  availability protocol, ADR-002, ADR-007 and its 2026-08-22 amendment;
- the committed direct-observation census structure for 2023-24 through
  2025-26, whose scope explicitly says `opportunity_coverage=null`;
- the committed reliability evidence's regular-season first and last game
  dates for 2023-24 through 2025-26;
- row counts and known source limitations already published in
  `docs/backlog.md`; and
- official schedule-date search results for the 2022-23 calendar boundary. The
  search returned stale or incomplete claims for later seasons, so those claims
  were not used; the later boundaries below come from committed repository
  evidence.

I deliberately did not open the off-repository SQLite stores or raw captures
named by those artifacts. The threshold below is therefore not selected for
achievability. It is inherited from the owner-accepted availability protocol
and justified here from the decision it protects.

---

## 2. Exact window and role of each season

The opportunity report covers four complete NBA regular seasons. Game dates are
inclusive and refer to the actual date of the final regular-season game under
the project's corrected NBA game-date contract.

| Season | Inclusive regular-season dates | Role |
|---|---|---|
| 2022-23 | 2022-10-18 through 2023-04-09 | Historical support only; supplies prior opportunity history and the Marcel reference. It is not a fitting target partition. |
| 2023-24 | 2023-10-24 through 2024-04-14 | Development; candidate structures are fitted here. |
| 2024-25 | 2024-10-22 through 2025-04-13 | Selection; candidates are advanced here, then the selected structure is refit on 2023-24 plus 2024-25. |
| 2025-26 | 2025-10-21 through 2026-04-12 | Holdout; evaluated once by the independent evaluator. |

2022-23 is the Marcel reference season because the holdout comparison requires
each 2025-26 player to have the three immediately prior seasons of opportunity
history: 2022-23, 2023-24, and 2024-25. Moving that support window later would
consume the holdout; moving it earlier would not supply the required adjacent
three-season history.

Preseason, All-Star, Play-In, playoff, Summer League, G League, and cancelled
games are excluded. There is no two-season, within-season, shortened-window, or
rotation-only fallback under v1.

### Exact player-game inclusion rule

The population is **all at-risk player-games**, not a rotation-relevant subset.
No minutes, starts, box-score appearance, prior participation, fantasy roster
status, injury status, or stated DNP reason is an inclusion criterion.

The coverage implementation must first produce a versioned canonical roster
interval manifest from independent roster/opportunity evidence. Each interval
must contain a stable NBA player id, stable NBA team id, inclusive effective
start instant, exclusive effective end instant (or a season-end sentinel),
source, endpoint or artifact, source event id, and capture timestamp. The
independently validated reconstruction contract must cover opening membership,
every effective start and end including contract expiration, assignment and
recall, suspension, and same-day boundaries for all four seasons.

The exact source registry and reconstruction implementation cannot be named
today because the repository records that no currently admitted source can
produce complete intervals. Inventing one here would turn a source gap into a
paper guarantee. Instead, cohort identity is frozen in a mandatory
pre-classification stage:

1. commit the source registry, reconstruction contract, canonical interval
   manifest, and canonical regular-season schedule manifest;
2. record each artifact's raw Git-blob SHA-256 and the commit containing it;
3. independently reproduce the interval manifest from the frozen sources and
   contract and reproduce the schedule manifest from its frozen source; and
4. only after that commit is immutable may any direct participation row be
   joined or any coverage class or `unknown` count be computed.

The coverage report must bind those four hashes, prove that their freeze commit
is an ancestor of the classification commit, and publish a SHA-256 over the
sorted distinct `(player_id, game_id)` cohort keys produced by the join. Two
implementations apply the join below to the same hashed interval and schedule
manifests and must reproduce that cohort-key digest. A changed source,
precedence rule, conflict rule, event-to-interval rule, schedule row, or
manifest creates a different cohort and cannot inherit this report.

For each season, the cohort is exactly the relational join:

```text
COHORT =
  DISTINCT (
    roster_interval.player_id,
    regular_season_game.game_id
  )
WHERE
  regular_season_game.season == roster_interval.season
  AND regular_season_game.status == "final"
  AND regular_season_game.game_date BETWEEN season_start AND season_end
  AND roster_interval.team_id IN (
    regular_season_game.home_team_id,
    regular_season_game.away_team_id
  )
  AND roster_interval.effective_start_utc
      <= regular_season_game.tipoff_utc
  AND regular_season_game.tipoff_utc
      < roster_interval.effective_end_utc
```

Same-team overlapping intervals are unioned before the join. Overlapping
different-team intervals for the same player at one tip-off, an unresolved
same-day ordering, a missing opening interval, or a missing effective end is a
failure of roster-interval completeness; it is not resolved from participation
silence and is not dropped.

Each distinct `(player_id, game_id)` is then assigned exactly one class:

- `confirmed_observed`: one direct `played` participation outcome exists;
- `confirmed_absent`: one direct `did_not_play`, `did_not_dress`,
  `not_with_team`, or `inactive` outcome exists; or
- `unknown`: the opportunity is established but its direct participation
  outcome is missing, explicitly `unknown`, identity-unresolved, or conflicting.

Game logs may audit source-game identity and may later supply predictor-side
workload. They never create, repair, or override a coverage class. Free-text
DNP reasons never establish roster membership or a class.

This inclusion rule deliberately keeps long absences and fringe players. A
minutes or appearance threshold would select on surviving into games, exclude
the player-specific silences most likely to matter, and recreate the
healthy-worker/collider problem named by ADR-007's 2026-08-22 amendment.

---

## 3. Maximum acceptable unknown share

The maximum acceptable `unknown` share is **0.05 inclusive (5%)**.

It is measured over the **whole all-at-risk cohort** defined in section 2:

```text
unknown_share =
  unknown_opportunities / total_enumerated_at_risk_opportunities
```

The ceiling applies twice:

1. `unknown_share_overall <= 0.05` over all four seasons combined; and
2. `unknown_share_by_season[season] <= 0.05` for every one of 2022-23,
   2023-24, 2024-25, and 2025-26.

A zero denominator fails. Shares are computed from integer counts before
display rounding. The equivalent authoritative comparison is
`unknown_opportunities * 100 <= total_opportunities * 5`.

### Why 5% protects the decision

The model will turn these labels into calibrated game-level probabilities that
later affect expected games and draft-day dollars. Five percent unresolved
mass can move an unadjusted cohort play rate by as much as five percentage
points under the two extreme assignments. That is already large enough to
change expected-games differences between otherwise comparable players and is
therefore a ceiling, not a target.

More importantly, `unknown` is not plausibly random. The repository's named
failure mode is player-specific silence around long absences and roster
transitions. Those are exactly the cases a durability model must learn rather
than discard. Above 5%, a model can look calibrated on directly observed rows
while being calibrated only on the easier, healthier selected population. A
higher ceiling would let missingness plausibly dominate the draft decision the
model is supposed to improve.

The per-season ceiling prevents one weak season from hiding inside a combined
pass. The whole-cohort population prevents a rotation filter from laundering
the failure by excluding players whose missingness or low participation made
them look non-rotation-relevant. Passing this gate still does not establish
player-, stratum-, or era-level calibration; the accepted availability protocol
has separate sample floors and held-out calibration vetoes for those claims.

---

## 4. Machine-evaluable coverage proceed predicate

The report must carry this freeze id and the exact counts used below. The
following predicate is canonical; prose elsewhere does not override it.

```text
REQUIRED_SEASONS = {"2022-23", "2023-24", "2024-25", "2025-26"}
REQUIRED_WINDOWS = {
  "2022-23": ["2022-10-18", "2023-04-09"],
  "2023-24": ["2023-10-24", "2024-04-14"],
  "2024-25": ["2024-10-22", "2025-04-13"],
  "2025-26": ["2025-10-21", "2026-04-12"]
}
MAX_UNKNOWN_SHARE = 0.05

PROCEED_OPPORTUNITY_COVERAGE =
  report.preregistration_id
    == "participation-opportunity-coverage-v1-20260906T052618Z"
  AND report.population == "all_at_risk_player_games"
  AND set(report.seasons.keys()) == REQUIRED_SEASONS
  AND for_every(season IN REQUIRED_SEASONS,
        [report.seasons[season].start_date,
         report.seasons[season].end_date] == REQUIRED_WINDOWS[season])
  AND report.cohort_rule
      == "roster_interval_start_inclusive_end_exclusive_at_tipoff_v1"
  AND report.roster_source_registry_sha256_is_verified == true
  AND report.roster_reconstruction_contract_sha256_is_verified == true
  AND report.roster_interval_manifest_sha256_is_verified == true
  AND report.schedule_manifest_sha256_is_verified == true
  AND report.roster_reconstruction_contract_independently_validated == true
  AND report.roster_interval_manifest_independently_reproduced == true
  AND report.schedule_manifest_independently_reproduced == true
  AND report.input_manifest_commit_is_ancestor_of_classification_commit
      == true
  AND report.classification_started_after_input_manifest_freeze == true
  AND report.cohort_key_sha256_is_reproduced == true
  AND report.roster_interval_coverage_complete == true
  AND report.schedule_coverage_complete == true
  AND report.all_four_direct_censuses_present == true
  AND report.duplicate_opportunities == 0
  AND report.unclassified_opportunities == 0
  AND report.missing_required_provenance_fields == 0
  AND all_counts_are_nonnegative_integers(
        report.total_opportunities,
        report.direct_label_available,
        report.confirmed_observed,
        report.confirmed_absent,
        report.unknown_opportunities,
        report.duplicate_opportunities,
        report.unclassified_opportunities,
        report.missing_required_provenance_fields,
        every report.seasons[*].total_opportunities,
        every report.seasons[*].direct_label_available,
        every report.seasons[*].confirmed_observed,
        every report.seasons[*].confirmed_absent,
        every report.seasons[*].unknown_opportunities)
  AND report.total_opportunities > 0
  AND report.total_opportunities
      == report.direct_label_available + report.unknown_opportunities
  AND report.direct_label_available
      == report.confirmed_observed + report.confirmed_absent
  AND report.total_opportunities
      == sum(report.seasons[season].total_opportunities
             for season IN REQUIRED_SEASONS)
  AND report.direct_label_available
      == sum(report.seasons[season].direct_label_available
             for season IN REQUIRED_SEASONS)
  AND report.confirmed_observed
      == sum(report.seasons[season].confirmed_observed
             for season IN REQUIRED_SEASONS)
  AND report.confirmed_absent
      == sum(report.seasons[season].confirmed_absent
             for season IN REQUIRED_SEASONS)
  AND report.unknown_opportunities
      == sum(report.seasons[season].unknown_opportunities
             for season IN REQUIRED_SEASONS)
  AND report.unknown_share_overall
      == report.unknown_opportunities / report.total_opportunities
  AND report.unknown_opportunities * 100
      <= report.total_opportunities * 5
  AND for_every(season IN REQUIRED_SEASONS,
        report.seasons[season].total_opportunities > 0
        AND report.seasons[season].total_opportunities
            == report.seasons[season].direct_label_available
               + report.seasons[season].unknown_opportunities
        AND report.seasons[season].direct_label_available
            == report.seasons[season].confirmed_observed
               + report.seasons[season].confirmed_absent
        AND report.seasons[season].unknown_share
            == report.seasons[season].unknown_opportunities
               / report.seasons[season].total_opportunities
        AND report.seasons[season].unknown_opportunities * 100
            <= report.seasons[season].total_opportunities * 5)
```

`direct_label_available` is
`confirmed_observed + confirmed_absent`. Required provenance for each
opportunity is the stable player, game, and team identity; roster-interval
source, endpoint or artifact, source event id, and capture timestamp; direct
participation source, endpoint or artifact, capture timestamp, and stable
source-row id or canonical row digest when present; and the searched-source
provenance that establishes its absence when the class is `unknown`.

This is a necessary coverage conjunct of the accepted protocol's
`PROCEED_COMMON`, not a sufficient fit authorization. The first model may
proceed only when this predicate **and every other accepted `PROCEED_COMMON`
and mode-specific condition** are true.

---

## 5. Precommitted failure branch

If `PROCEED_OPPORTUNITY_COVERAGE` is false:

1. publish the coverage result and the failing conjuncts;
2. keep `participation-opportunity-coverage` pending and
   `availability-model` at `FIT_VETOED_DATA` or
   `FIT_VETOED_PREREQUISITES`, as applicable;
3. release no split labels, fit no candidate, emit no `p(play)`, and do not
   lower 0.05 after seeing the result;
4. first evaluate every predicate conjunct **except** the four genuine
   evidence-sufficiency checks named in step 5. If any such conjunct is false,
   treat the report as invalid, repair that artifact or its generator, and
   rerun it against the unchanged frozen inputs;
5. only after every other conjunct is true, treat any of these as a genuine
   evidence failure: `all_four_direct_censuses_present == false`,
   `roster_interval_coverage_complete == false`,
   `schedule_coverage_complete == false`, or a correctly recomputed overall or
   per-season `unknown` share above 0.05. Widen the evidence source or complete
   an independently validated reconstruction contract satisfying the
   roster-interval fields above; and
6. if that cannot be done with an allowed source, accept the resulting delay.

Narrowing the window is not an automatic remedy. The owner-accepted
availability v1 protocol has no shortened-window fallback. Any narrower cohort
requires a separately reviewed replacement protocol committed before that new
cohort's coverage outcome is examined; it cannot be presented as a pass under
this freeze.

---

## 6. Identification boundary

This gate protects label coverage, not causal identification. Even after it
passes, the fitted estimand is conditional on independent roster evidence,
directly observed labels, stable identities, survival into candidate history
requirements, and the represented reporting regimes. Workload features remain
selected by prior health and participation. The model card must name that
selection-induced sign risk, treat workload associations as non-causal, report
calibration on the held-out population, and state that the model cannot see
future trades, coaching changes, undisclosed injuries, personal matters,
warm-up setbacks, front-office intent, or future reporting drift.

Production is outside this artifact. Per-game production remains independent
of availability and can be fused with expected games only at `expected-games`
under ADR-002.

---

## 7. Binding and change control

This v1 freezes when its exact Git commit is created, before any
opportunity-coverage result is examined. After that commit, changing a date,
population rule, classification rule, threshold, or predicate requires v2.
The v1 artifact and any result against it remain intact. A post-result change
must be labelled post-result and may not be represented as preregistered.
