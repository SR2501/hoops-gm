# Recorded-draft production candidates

Implementation contract, 13 September 2026; local delivery completed
14 September 2026 UTC. This is a read-only, partial browser
increment, not the strategy-aware shortlist or authorization to activate an
unclosed model. Backend owns the served Pydantic/OpenAPI schema; frontend
consumes it. No live-account actions, new data source, persistent blend recipe,
availability fit, dollar value or budget policy is introduced.

## Request and composition

`GET /api/v1/drafts/{draft_id}/production-candidates?source=basketball_monster`

`source` is required. Supported projection namespaces are `basketball_monster`,
`fantasypros`, `hashtag`, `darko` and `manual`, matching
`PROJECTION_IMPORT_SOURCES`. A supported namespace does not mean an admitted
import exists. The browser initially selects BBM and labels the selector as
supported sources, not available data. There is no source-catalog endpoint in
this increment.

Use the recorded draft's actual league, season and structure. Refuse an
unresolved live holding: eligibility cannot be asserted by guessing an identity.
A bid or nomination is not a holding. Compare the persisted league's team count
and roster size with the recorded draft, not its budget; the existing accepted
shared-budget assumption and warning remain owned by the draft-state response.

Compose genuine `release_projection_import`, active scoring-profile release,
request-local `define_blend_profile` / `blend_projections`, and unchanged
`score_production_zscores`. The blend is an explicit identity single-source
weight of one in each category, with no overrides. It is not a persisted recipe
or an independently produced forecast.

Score every complete supplied projection first, then exclude recorded drafted
IDs. Return every remaining candidate in the scorer's original ordinal order.
Do not resize the league, filter for health, infer Fantrax eligibility, drop
incomplete production rows or renormalize a partial category set.

## Response shape

Top-level fields:

| Field | Type / meaning |
|---|---|
| `draft_id`, `league_id` | Positive integer identifiers |
| `season`, `source` | Actual league season and requested projection namespace |
| `source_display_name` | Verbatim local publisher label from the released import's source |
| `source_original_filename` | Nullable original filename on that exact import |
| `draft_status` | Existing `setup`, `in_progress`, `closed` vocabulary |
| `draft_last_sequence` | Recorded revision; not an external feed freshness claim |
| `generated_at` | Actual UTC response-generation timestamp, not a source timestamp |
| `claim` | `projection_relative_production_ranking` |
| `value_scope` | `production_only` |
| `availability_included` | `false` |
| `calibration_status` | `not_established_for_current_selected_source` |
| `source_freshness` | `not_established_beyond_current_import` |
| `limitations` | False strategy, punt, budget/affordability, position-fit and Fantrax-eligibility claims; `partial_browser_increment: true` |
| `lineage`, `reference`, `replacement` | Objects specified below |
| `category_scales` | Nine scorer-produced scales in the active profile's order |
| `health_context`, `candidates` | Separate observation context and ordered rows |

The limitations keys are `strategy_included`, `punt_adjustment_included`,
`budget_or_affordability_included`, `position_fit_included`,
`fantrax_roster_eligibility_included`, and `partial_browser_increment`.
There is no separate `budget_context`.

`lineage` carries:

- `projection_import`: the released `import_id`, `source`, `season`,
  `imported_at`, `content_sha256`, string `profile_id` / `profile_version`,
  `profile_definition_sha256`, `projection_values_sha256`, `projection_count`,
  and nullable `assumed_scoring_type`.
- `scoring_profile`: integer `id` / `version`, `name`, `scoring_type`,
  `settings_snapshot_id`, and `content_sha256`.
- `blend`: `mode: ephemeral_identity_single_source`, `persisted: false`,
  `profile_id`, integer `version`, `content_sha256`, `result_content_sha256`,
  `weight_basis: user_configured`, `manual_override_count: 0`, and nine
  `category_weights` entries carrying `category_key`, `source`, `raw_weight`,
  `normalized_weight`.
- `score`: the actual `model_version`, `input_kind: production_blend`,
  `output_layer: terminal`, `aggregation_policy`, `reference_policy`,
  `replacement_policy`, `scoring_profile_sha256`, `blend_profile_sha256`,
  `blend_result_sha256`, and `content_sha256`.
- `availability_model_version: null` and `punt_config: null`.

These score descriptors are copied from the frozen result, not inferred from
the pipeline's English description. The score has no `input_layer` field.
The publisher label and filename are display metadata, not independently
verified publisher identity or numeric fingerprint inputs. Read and re-observe
them against the same released import/source identities.

Client validation must also reconcile meaning, not merely valid field syntax.
The score's three input hashes equal the corresponding scoring-profile
`content_sha256`, blend `content_sha256`, and blend `result_content_sha256`.
A non-null import `assumed_scoring_type` equals the active profile's
`scoring_type`; two different valid enum values are still incompatible. The
current client interprets only `zscore-production-v1`, the
`reliability-observations` publication key, and the closed wire enum/literal sets.
Nullable import assumptions and unavailable-publication states remain valid.

`reference` carries `count`, the complete `player_ids`, `players_sha256`,
`scored_before_draft_exclusion: true`,
`draft_exclusion_policy: exclude_resolved_holdings_after_full_reference_scoring`,
`resolved_drafted_player_ids`, `excluded_drafted_player_ids`,
`drafted_player_ids_outside_reference`, and `candidate_count`. Counts and ID sets
must reconcile; names or current bids are not substitute keys.

`replacement` carries `state`, `team_count`, `roster_size`,
`structural_roster_count`, `replacement_ordinal`, `projected_count`,
`structural_roster_covered`, `structural_roster_shortfall`,
`replacement_ordinal_shortfall`, and nullable `replacement_player_id` /
`replacement_total_z`. Map these from the scorer, not another calculation.
A 60-player pool in a 12-by-13 league has structural shortfall 96, required
ordinal 157 and ordinal shortfall 97. Its state is
`unavailable_insufficient_projected_pool`; replacement and every VOR are null.
Even an available structural replacement does not assert free-agent membership.

Each scale carries `category_key`, `kind`, `direction`, `production_fields`
(field-name array), `reference_mean`, `population_sd`, nullable
`reference_percentage`, and `status` (`defined` or `zero_variance`).
The exact key set is `pts`, `reb`, `ast`, `stl`, `blk`, `fg3m`, `to`, `fg_pct`,
`ft_pct`. The scale, weight and component arrays share the published profile
order; clients must not impose another ordering.

Each candidate carries `player_id`, `full_name`, nullable `team_abbreviation`,
`projection_content_sha256`, original `ordinal`, `rates_per_game`, `components`,
`total_z`, nullable `value_above_replacement`, and `health`.
`rates_per_game` contains the eleven required scoring inputs: points, rebounds,
assists, steals, blocks, turnovers, three-pointers made, field goals made and
attempted, free throws made and attempted, each named with `_per_game`.
These are scoring inputs, not a claim to reproduce every source column.
Each component carries `category_key`, the matched scale's `kind` / `direction`,
its field-to-number `production_fields`, `transformed_value`, and `z_score`.
Serialize the already computed values; do not recompute or reverse TO in UI.

## Historical observations

Use a narrow, lock-free read of credited game-log rows inside an attributable
published observation window. Count zero-second credited rows. No percentage,
absence, opportunity denominator, durability score or forecast is inferred.
Publication context is not row-level upstream provenance.

`health_context` always carries `status`, `reason`, `season`, `season_type`,
`window_start`, `as_of_date`, `publication`, `row_source_provenance`,
`counting_rule`, `observation_rows_sha256`, and `ranking_input: false`.

- `available`: `reason` is null; the declared season/window, publication and
  fingerprint are present. `publication` carries integer `refresh_id`,
  `artifact_key`, and actual nullable `source` / `source_version` metadata.
- `unavailable`: `reason` is `no_attributable_publication`; season/window,
  publication and fingerprint are null. Do not choose a historical season
  silently or claim that rows were absent.

`row_source_provenance` is `not_recorded`; `counting_rule` is
`player_game_log_rows_in_window_including_zero_seconds`. Invalid/corrupt
publication evidence is an explicit refusal, not silently unavailable.

Candidate health states are closed: `observed` with positive
`credited_appearances`; `no_observations` with zero in the declared available
window; `unknown` with a null count when context is unavailable. All candidates
remain in the production ranking. Display unrecorded provenance and distinguish
no rows in this window from healthy or no career history.

## Consistency and refusal

No read lock may block a writer. Bracket with the genuine production releases
and re-observe draft revision, scoring/league structure and the narrow health
snapshot. Reuse one definition of the health read/fingerprint. Enumerate join
keys and covered fields in the implementation; explicitly identify canonical
player display metadata outside the numeric fingerprint.

Promise a coherent older response or a typed retryable conflict, not freshness
or detection of every write. A moved-and-reverted state or ORM snapshot can evade
detection; it must not produce mixed numeric inputs and lineage.

All refusals use `{error, detail, request_id}`:

| HTTP | Code |
|---|---|
| 403 | `production_candidates_local_only` |
| 404 | `production_candidates_draft_not_found` |
| 400 | `production_candidates_source_unsupported` |
| 409 | `production_candidates_source_not_imported` |
| 409 | `production_candidates_draft_state_refused` |
| 409 | `production_candidates_draft_identity_incomplete` |
| 409 | `production_candidates_league_structure_mismatch` |
| 409 | `production_candidates_scoring_profile_unavailable` |
| 409 | `production_candidates_incomplete_production` |
| 409 | `production_candidates_input_evidence_refused` |
| 409 | `production_candidates_inconsistent_snapshot` |
| 422 | `validation_error` |

Retry only `production_candidates_inconsistent_snapshot`, exactly once. Keep a
whole last-good response for the same draft/source, visibly stale on failure.
A changed draft/source is a cold scope; late old responses cannot replace it.

## Browser and delivery boundary

Route: `/draft/:draftId/production-candidates`, linked from DraftPage without
fetching candidates in that page. Use the supplied draft ID in the header; no
unprovided draft-name field is assumed. Keep source/import identity and time,
profile/reference/model identity and the replacement state adjacent to scores.
Say that import time is not vendor as-of/freshness validation and that historical
carry-forward evidence does not calibrate the selected vendor.

Validate the raw route ID as canonical positive decimal text and then as a safe
integer before mounting the loader. Hexadecimal/exponential/decimal aliases,
signs, whitespace, leading zeroes, zero and unsafe integers are client refusals,
not coerced requests for another draft.

The served synthetic fixture must retain 60 scored / seven excluded /
53 candidates, five with observations and 48 without. A frontend fixture
labelled recorded must be exported from the real seeded HTTP response. Backend
also updates the repository's recorded OpenAPI artifact with its existing
generator. All Code gates and independent reporting/formatting closure still
apply; no merge or production activation is implied.

The normal composed seed must create its first synthetic import with the
scoring declaration matching its recorded auction profile. Do not repair that
fixture by appending a blank CSV record to force another import identity.
Preserve standalone seed behavior, safety guards and repeat semantics.
Display the actual publisher label and original filename prominently: the
fixture says "synthetic demo cohort"; its identifier-derived rates must not look
like the owner's actual BBM forecasts. Regeneration uses new named outputs and
refuses existing targets rather than deleting an earlier recording.

## Local delivery evidence

The genuine V2 response in
`frontend/src/test/fixtures/draft-production-candidates.recorded.json` comes from
normal fresh `seed_demo` alone and the actual HTTP route: draft 1 belongs to
league 2 and uses projection import 1. Its SHA-256 is
`678a56b101c8742d03e3f79f4d048e3449a9eb8bdd742a4a1505f15d6cbf08ec`.
It is synthetic evidence, not an owner-supplied vendor forecast.

Desktop and narrow-viewport browser observations covered server/row order,
nine-component evidence, provenance, replacement/VOR states, source-switch
isolation and retained data after browser-only failures. A subsequent HTTP200
body with one contradicted score input hash was rejected without replacing
last-good data. The reported malformed URL cases rendered client refusals with
no candidate resource requests during the bounded observation.

Independent integration review found and guided the lineage and route-ID fixes.
Its last remaining null-or-equal scoring-declaration predicate was applied
literally and checked with targeted regressions; that final two-file change is
parent-confirmed, not represented as another independent full review. The
broader strategy/budget/roster-aware shortlist, current-source calibration,
availability fitting, Git delivery and real-account activation remain outside
this local increment.
