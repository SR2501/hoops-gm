import type { DraftStatus } from './draftTypes'

/**
 * Projection namespaces the endpoint accepts.
 *
 * This is a supported-input vocabulary, not a catalogue of imports currently
 * present in the database. Selecting one can therefore return a typed
 * `production_candidates_source_not_imported` refusal.
 */
export const PRODUCTION_CANDIDATE_SOURCES = [
  'basketball_monster',
  'fantasypros',
  'hashtag',
  'darko',
  'manual',
] as const

export type ProductionCandidateSource = (typeof PRODUCTION_CANDIDATE_SOURCES)[number]

/**
 * The canonical category keys. Their order here is only a closed vocabulary:
 * the response's category_scales array is the presentation order.
 */
export const PRODUCTION_CATEGORY_KEYS = [
  'pts',
  'reb',
  'ast',
  'stl',
  'blk',
  'fg3m',
  'to',
  'fg_pct',
  'ft_pct',
] as const

export type ProductionCategoryKey = (typeof PRODUCTION_CATEGORY_KEYS)[number]

export const PRODUCTION_RATE_FIELDS = [
  'points_per_game',
  'rebounds_per_game',
  'assists_per_game',
  'steals_per_game',
  'blocks_per_game',
  'turnovers_per_game',
  'three_pointers_made_per_game',
  'field_goals_made_per_game',
  'field_goals_attempted_per_game',
  'free_throws_made_per_game',
  'free_throws_attempted_per_game',
] as const

export type ProductionRateField = (typeof PRODUCTION_RATE_FIELDS)[number]

export type ProductionCategoryKind = 'counting' | 'ratio'
export type ProductionCategoryDirection = 1 | -1
export type ProductionScaleStatus = 'defined' | 'zero_variance'

export const PRODUCTION_SCORING_TYPES = [
  'h2h_categories',
  'h2h_points',
  'h2h_each_category',
  'roto',
  'points',
] as const

export type ProductionScoringType = (typeof PRODUCTION_SCORING_TYPES)[number]

export const PRODUCTION_SEASON_TYPES = [
  'preseason',
  'regular',
  'play_in',
  'playoffs',
] as const

export type ProductionSeasonType = (typeof PRODUCTION_SEASON_TYPES)[number]

export const PRODUCTION_SCORE_MODEL_VERSION = 'zscore-production-v1' as const
export const PRODUCTION_HEALTH_ARTIFACT_KEY = 'reliability-observations' as const

export interface ProductionCandidateLimitations {
  strategy_included: false
  punt_adjustment_included: false
  budget_or_affordability_included: false
  position_fit_included: false
  fantrax_roster_eligibility_included: false
  partial_browser_increment: true
}

export interface ProductionProjectionImportLineage {
  import_id: number
  source: ProductionCandidateSource
  season: string
  imported_at: string
  content_sha256: string
  profile_id: string
  profile_version: string
  profile_definition_sha256: string
  projection_values_sha256: string
  projection_count: number
  assumed_scoring_type: ProductionScoringType | null
}

export interface ProductionScoringProfileLineage {
  id: number
  version: number
  name: string
  scoring_type: ProductionScoringType
  settings_snapshot_id: number
  content_sha256: string
}

export interface ProductionBlendWeight {
  category_key: ProductionCategoryKey
  source: ProductionCandidateSource
  raw_weight: number
  normalized_weight: number
}

export interface ProductionBlendLineage {
  mode: 'ephemeral_identity_single_source'
  persisted: false
  profile_id: string
  version: number
  content_sha256: string
  result_content_sha256: string
  weight_basis: 'user_configured'
  manual_override_count: 0
  category_weights: ProductionBlendWeight[]
}

export interface ProductionScoreLineage {
  model_version: typeof PRODUCTION_SCORE_MODEL_VERSION
  input_kind: 'production_blend'
  output_layer: 'terminal'
  aggregation_policy: string
  reference_policy: string
  replacement_policy: string
  scoring_profile_sha256: string
  blend_profile_sha256: string
  blend_result_sha256: string
  content_sha256: string
}

export interface ProductionCandidatesLineage {
  projection_import: ProductionProjectionImportLineage
  scoring_profile: ProductionScoringProfileLineage
  blend: ProductionBlendLineage
  score: ProductionScoreLineage
  availability_model_version: null
  punt_config: null
}

export interface ProductionReference {
  count: number
  player_ids: number[]
  players_sha256: string
  scored_before_draft_exclusion: true
  draft_exclusion_policy: 'exclude_resolved_holdings_after_full_reference_scoring'
  resolved_drafted_player_ids: number[]
  excluded_drafted_player_ids: number[]
  drafted_player_ids_outside_reference: number[]
  candidate_count: number
}

export type ProductionReplacementState =
  | 'available'
  | 'unavailable_insufficient_projected_pool'

export interface ProductionReplacement {
  state: ProductionReplacementState
  team_count: number
  roster_size: number
  structural_roster_count: number
  replacement_ordinal: number
  projected_count: number
  structural_roster_covered: boolean
  structural_roster_shortfall: number
  replacement_ordinal_shortfall: number
  replacement_player_id: number | null
  replacement_total_z: number | null
}

export interface ProductionCategoryScale {
  category_key: ProductionCategoryKey
  kind: ProductionCategoryKind
  direction: ProductionCategoryDirection
  production_fields: ProductionRateField[]
  reference_mean: number
  population_sd: number
  reference_percentage: number | null
  status: ProductionScaleStatus
}

export interface ProductionRatesPerGame {
  points_per_game: number
  rebounds_per_game: number
  assists_per_game: number
  steals_per_game: number
  blocks_per_game: number
  turnovers_per_game: number
  three_pointers_made_per_game: number
  field_goals_made_per_game: number
  field_goals_attempted_per_game: number
  free_throws_made_per_game: number
  free_throws_attempted_per_game: number
}

export interface ProductionCategoryComponent {
  category_key: ProductionCategoryKey
  kind: ProductionCategoryKind
  direction: ProductionCategoryDirection
  production_fields: Record<string, number>
  transformed_value: number
  z_score: number
}

export interface ObservedCandidateHealth {
  status: 'observed'
  credited_appearances: number
}

export interface NoObservationsCandidateHealth {
  status: 'no_observations'
  credited_appearances: 0
}

export interface UnknownCandidateHealth {
  status: 'unknown'
  credited_appearances: null
}

export type ProductionCandidateHealth =
  | ObservedCandidateHealth
  | NoObservationsCandidateHealth
  | UnknownCandidateHealth

export interface ProductionCandidate {
  player_id: number
  full_name: string
  team_abbreviation: string | null
  projection_content_sha256: string
  ordinal: number
  rates_per_game: ProductionRatesPerGame
  components: ProductionCategoryComponent[]
  total_z: number
  value_above_replacement: number | null
  health: ProductionCandidateHealth
}

export interface ProductionHealthPublication {
  refresh_id: number
  artifact_key: typeof PRODUCTION_HEALTH_ARTIFACT_KEY
  source: string | null
  source_version: string | null
}

interface ProductionHealthContextBase {
  row_source_provenance: 'not_recorded'
  counting_rule: 'player_game_log_rows_in_window_including_zero_seconds'
  ranking_input: false
}

export interface AvailableProductionHealthContext extends ProductionHealthContextBase {
  status: 'available'
  reason: null
  season: string
  season_type: ProductionSeasonType
  window_start: string
  as_of_date: string
  publication: ProductionHealthPublication
  observation_rows_sha256: string
}

export interface UnavailableProductionHealthContext extends ProductionHealthContextBase {
  status: 'unavailable'
  reason: 'no_attributable_publication'
  season: null
  season_type: null
  window_start: null
  as_of_date: null
  publication: null
  observation_rows_sha256: null
}

export type ProductionHealthContext =
  | AvailableProductionHealthContext
  | UnavailableProductionHealthContext

export interface ProductionCandidatesResponse {
  draft_id: number
  league_id: number
  season: string
  source: ProductionCandidateSource
  source_display_name: string
  source_original_filename: string | null
  draft_status: DraftStatus
  draft_last_sequence: number
  generated_at: string
  claim: 'projection_relative_production_ranking'
  value_scope: 'production_only'
  availability_included: false
  calibration_status: 'not_established_for_current_selected_source'
  source_freshness: 'not_established_beyond_current_import'
  limitations: ProductionCandidateLimitations
  lineage: ProductionCandidatesLineage
  reference: ProductionReference
  replacement: ProductionReplacement
  category_scales: ProductionCategoryScale[]
  health_context: ProductionHealthContext
  candidates: ProductionCandidate[]
}
