import { apiFetch, type ResponseContract } from './client'
import {
  isProjectionSeriesDescriptor,
  isProjectionSeriesKey,
} from './projectionSeriesEndpoints'
import {
  PROJECTION_RELEASE_SCHEMA_VERSION,
  type ProductionCandidatesOptions,
} from './projectionSeriesTypes'
import { DRAFT_STATUSES } from './draftTypes'
import {
  PRODUCTION_CANDIDATE_SOURCES,
  PRODUCTION_CATEGORY_KEYS,
  PRODUCTION_HEALTH_ARTIFACT_KEY,
  PRODUCTION_RATE_FIELDS,
  PRODUCTION_SCORE_MODEL_VERSION,
  PRODUCTION_SCORING_TYPES,
  PRODUCTION_SEASON_TYPES,
  type ProductionBlendLineage,
  type ProductionBlendWeight,
  type ProductionCandidate,
  type ProductionCandidateHealth,
  type ProductionCandidateSource,
  type ProductionCandidatesLineage,
  type ProductionCandidatesResponse,
  type ProductionCategoryComponent,
  type ProductionCategoryDirection,
  type ProductionCategoryKey,
  type ProductionCategoryKind,
  type ProductionCategoryScale,
  type ProductionHealthContext,
  type ProductionHealthPublication,
  type ProductionProjectionImportLineage,
  type ProductionRateField,
  type ProductionRatesPerGame,
  type ProductionReference,
  type ProductionReplacement,
  type ProductionScoreLineage,
  type ProductionScoringProfileLineage,
  type ProductionScoringType,
  type ProductionSeasonType,
} from './productionCandidatesTypes'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value)
  return actual.length === expected.length && expected.every((key) => Object.hasOwn(value, key))
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

function isNullableNonEmptyString(value: unknown): value is string | null {
  return value === null || isNonEmptyString(value)
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isNonNegativeFiniteNumber(value: unknown): value is number {
  return isFiniteNumber(value) && value >= 0
}

function isTimestamp(value: unknown): value is string {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value))
}

function isDate(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(Date.parse(`${value}T00:00:00Z`))
  )
}

function isSha256(value: unknown): value is string {
  return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)
}

export function isProductionCandidateSource(value: unknown): value is ProductionCandidateSource {
  return (PRODUCTION_CANDIDATE_SOURCES as readonly unknown[]).includes(value)
}

function isCategoryKey(value: unknown): value is ProductionCategoryKey {
  return (PRODUCTION_CATEGORY_KEYS as readonly unknown[]).includes(value)
}

function isRateField(value: unknown): value is ProductionRateField {
  return (PRODUCTION_RATE_FIELDS as readonly unknown[]).includes(value)
}

function isScoringType(value: unknown): value is ProductionScoringType {
  return (PRODUCTION_SCORING_TYPES as readonly unknown[]).includes(value)
}

function isSeasonType(value: unknown): value is ProductionSeasonType {
  return (PRODUCTION_SEASON_TYPES as readonly unknown[]).includes(value)
}

function uniquePositiveIntegers(value: unknown): value is number[] {
  return (
    Array.isArray(value) &&
    value.every(isPositiveInteger) &&
    new Set(value).size === value.length
  )
}

function sameSet(left: readonly number[], right: readonly number[]): boolean {
  if (left.length !== right.length) return false
  const rightSet = new Set(right)
  return left.every((value) => rightSet.has(value))
}

const CATEGORY_SEMANTICS: Record<
  ProductionCategoryKey,
  {
    kind: ProductionCategoryKind
    direction: ProductionCategoryDirection
    fields: readonly ProductionRateField[]
  }
> = {
  pts: { kind: 'counting', direction: 1, fields: ['points_per_game'] },
  reb: { kind: 'counting', direction: 1, fields: ['rebounds_per_game'] },
  ast: { kind: 'counting', direction: 1, fields: ['assists_per_game'] },
  stl: { kind: 'counting', direction: 1, fields: ['steals_per_game'] },
  blk: { kind: 'counting', direction: 1, fields: ['blocks_per_game'] },
  fg3m: {
    kind: 'counting',
    direction: 1,
    fields: ['three_pointers_made_per_game'],
  },
  to: { kind: 'counting', direction: -1, fields: ['turnovers_per_game'] },
  fg_pct: {
    kind: 'ratio',
    direction: 1,
    fields: ['field_goals_made_per_game', 'field_goals_attempted_per_game'],
  },
  ft_pct: {
    kind: 'ratio',
    direction: 1,
    fields: ['free_throws_made_per_game', 'free_throws_attempted_per_game'],
  },
}

function exactStringOrder(
  actual: readonly string[],
  expected: readonly string[],
): boolean {
  return (
    actual.length === expected.length &&
    actual.every((value, index) => value === expected[index])
  )
}

function sameStringSet(actual: readonly string[], expected: readonly string[]): boolean {
  return (
    actual.length === expected.length &&
    new Set(actual).size === actual.length &&
    expected.every((value) => actual.includes(value))
  )
}

const PROJECTION_IMPORT_KEYS = [
  'import_id',
  'source',
  'series_key',
  'release_schema_version',
  'season',
  'imported_at',
  'content_sha256',
  'profile_id',
  'profile_version',
  'profile_definition_sha256',
  'projection_values_sha256',
  'projection_count',
  'assumed_scoring_type',
] as const

function isProjectionImportLineage(
  value: unknown,
): value is ProductionProjectionImportLineage {
  return (
    isRecord(value) &&
    hasExactKeys(value, PROJECTION_IMPORT_KEYS) &&
    isPositiveInteger(value.import_id) &&
    isProductionCandidateSource(value.source) &&
    isProjectionSeriesKey(value.series_key) &&
    value.release_schema_version === PROJECTION_RELEASE_SCHEMA_VERSION &&
    isNonEmptyString(value.season) &&
    isTimestamp(value.imported_at) &&
    isSha256(value.content_sha256) &&
    isNonEmptyString(value.profile_id) &&
    isNonEmptyString(value.profile_version) &&
    isSha256(value.profile_definition_sha256) &&
    isSha256(value.projection_values_sha256) &&
    isPositiveInteger(value.projection_count) &&
    (value.assumed_scoring_type === null || isScoringType(value.assumed_scoring_type))
  )
}

const SCORING_PROFILE_KEYS = [
  'id',
  'version',
  'name',
  'scoring_type',
  'settings_snapshot_id',
  'content_sha256',
] as const

function isScoringProfileLineage(
  value: unknown,
): value is ProductionScoringProfileLineage {
  return (
    isRecord(value) &&
    hasExactKeys(value, SCORING_PROFILE_KEYS) &&
    isPositiveInteger(value.id) &&
    isPositiveInteger(value.version) &&
    isNonEmptyString(value.name) &&
    isScoringType(value.scoring_type) &&
    isPositiveInteger(value.settings_snapshot_id) &&
    isSha256(value.content_sha256)
  )
}

const BLEND_WEIGHT_KEYS = [
  'category_key',
  'source',
  'raw_weight',
  'normalized_weight',
] as const

function isBlendWeight(value: unknown): value is ProductionBlendWeight {
  return (
    isRecord(value) &&
    hasExactKeys(value, BLEND_WEIGHT_KEYS) &&
    isCategoryKey(value.category_key) &&
    isProductionCandidateSource(value.source) &&
    value.raw_weight === 1 &&
    value.normalized_weight === 1
  )
}

const BLEND_KEYS = [
  'mode',
  'persisted',
  'profile_id',
  'version',
  'content_sha256',
  'result_content_sha256',
  'weight_basis',
  'manual_override_count',
  'category_weights',
] as const

function isBlendLineage(value: unknown): value is ProductionBlendLineage {
  return (
    isRecord(value) &&
    hasExactKeys(value, BLEND_KEYS) &&
    value.mode === 'ephemeral_identity_single_source' &&
    value.persisted === false &&
    isNonEmptyString(value.profile_id) &&
    isPositiveInteger(value.version) &&
    isSha256(value.content_sha256) &&
    isSha256(value.result_content_sha256) &&
    value.weight_basis === 'user_configured' &&
    value.manual_override_count === 0 &&
    Array.isArray(value.category_weights) &&
    value.category_weights.length === PRODUCTION_CATEGORY_KEYS.length &&
    value.category_weights.every(isBlendWeight)
  )
}

const SCORE_KEYS = [
  'model_version',
  'input_kind',
  'output_layer',
  'aggregation_policy',
  'reference_policy',
  'replacement_policy',
  'scoring_profile_sha256',
  'blend_profile_sha256',
  'blend_result_sha256',
  'content_sha256',
] as const

function isScoreLineage(value: unknown): value is ProductionScoreLineage {
  return (
    isRecord(value) &&
    hasExactKeys(value, SCORE_KEYS) &&
    value.model_version === PRODUCTION_SCORE_MODEL_VERSION &&
    value.input_kind === 'production_blend' &&
    value.output_layer === 'terminal' &&
    isNonEmptyString(value.aggregation_policy) &&
    isNonEmptyString(value.reference_policy) &&
    isNonEmptyString(value.replacement_policy) &&
    isSha256(value.scoring_profile_sha256) &&
    isSha256(value.blend_profile_sha256) &&
    isSha256(value.blend_result_sha256) &&
    isSha256(value.content_sha256)
  )
}

const LINEAGE_KEYS = [
  'projection_import',
  'scoring_profile',
  'blend',
  'score',
  'availability_model_version',
  'punt_config',
] as const

function isLineage(value: unknown): value is ProductionCandidatesLineage {
  return (
    isRecord(value) &&
    hasExactKeys(value, LINEAGE_KEYS) &&
    isProjectionImportLineage(value.projection_import) &&
    isScoringProfileLineage(value.scoring_profile) &&
    isBlendLineage(value.blend) &&
    isScoreLineage(value.score) &&
    value.availability_model_version === null &&
    value.punt_config === null
  )
}

const REFERENCE_KEYS = [
  'count',
  'player_ids',
  'players_sha256',
  'scored_before_draft_exclusion',
  'draft_exclusion_policy',
  'resolved_drafted_player_ids',
  'excluded_drafted_player_ids',
  'drafted_player_ids_outside_reference',
  'candidate_count',
] as const

function isReference(value: unknown): value is ProductionReference {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, REFERENCE_KEYS) ||
    !isPositiveInteger(value.count) ||
    !uniquePositiveIntegers(value.player_ids) ||
    !isSha256(value.players_sha256) ||
    value.scored_before_draft_exclusion !== true ||
    value.draft_exclusion_policy !==
      'exclude_resolved_holdings_after_full_reference_scoring' ||
    !uniquePositiveIntegers(value.resolved_drafted_player_ids) ||
    !uniquePositiveIntegers(value.excluded_drafted_player_ids) ||
    !uniquePositiveIntegers(value.drafted_player_ids_outside_reference) ||
    !isNonNegativeInteger(value.candidate_count)
  ) {
    return false
  }

  const referenceIds = value.player_ids
  const referenceSet = new Set(referenceIds)
  const resolvedIds = value.resolved_drafted_player_ids
  const expectedExcluded = resolvedIds.filter((playerId) => referenceSet.has(playerId))
  const expectedOutside = resolvedIds.filter((playerId) => !referenceSet.has(playerId))

  return (
    value.count === referenceIds.length &&
    sameSet(value.excluded_drafted_player_ids, expectedExcluded) &&
    sameSet(value.drafted_player_ids_outside_reference, expectedOutside) &&
    value.candidate_count === value.count - value.excluded_drafted_player_ids.length
  )
}

const REPLACEMENT_KEYS = [
  'state',
  'team_count',
  'roster_size',
  'structural_roster_count',
  'replacement_ordinal',
  'projected_count',
  'structural_roster_covered',
  'structural_roster_shortfall',
  'replacement_ordinal_shortfall',
  'replacement_player_id',
  'replacement_total_z',
] as const

function isReplacement(value: unknown): value is ProductionReplacement {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, REPLACEMENT_KEYS) ||
    (value.state !== 'available' &&
      value.state !== 'unavailable_insufficient_projected_pool') ||
    !isPositiveInteger(value.team_count) ||
    !isPositiveInteger(value.roster_size) ||
    !isPositiveInteger(value.structural_roster_count) ||
    !isPositiveInteger(value.replacement_ordinal) ||
    !isPositiveInteger(value.projected_count) ||
    typeof value.structural_roster_covered !== 'boolean' ||
    !isNonNegativeInteger(value.structural_roster_shortfall) ||
    !isNonNegativeInteger(value.replacement_ordinal_shortfall) ||
    !(value.replacement_player_id === null || isPositiveInteger(value.replacement_player_id)) ||
    !(value.replacement_total_z === null || isFiniteNumber(value.replacement_total_z))
  ) {
    return false
  }

  const structuralCount = value.team_count * value.roster_size
  const replacementOrdinal = structuralCount + 1
  const structuralShortfall = Math.max(structuralCount - value.projected_count, 0)
  const ordinalShortfall = Math.max(replacementOrdinal - value.projected_count, 0)
  const replacementAvailable = value.projected_count >= replacementOrdinal

  return (
    value.structural_roster_count === structuralCount &&
    value.replacement_ordinal === replacementOrdinal &&
    value.structural_roster_covered === (value.projected_count >= structuralCount) &&
    value.structural_roster_shortfall === structuralShortfall &&
    value.replacement_ordinal_shortfall === ordinalShortfall &&
    (replacementAvailable
      ? value.state === 'available' &&
        value.replacement_player_id !== null &&
        value.replacement_total_z !== null
      : value.state === 'unavailable_insufficient_projected_pool' &&
        value.replacement_player_id === null &&
        value.replacement_total_z === null)
  )
}

const SCALE_KEYS = [
  'category_key',
  'kind',
  'direction',
  'production_fields',
  'reference_mean',
  'population_sd',
  'reference_percentage',
  'status',
] as const

function isCategoryScale(value: unknown): value is ProductionCategoryScale {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, SCALE_KEYS) ||
    !isCategoryKey(value.category_key) ||
    (value.kind !== 'counting' && value.kind !== 'ratio') ||
    (value.direction !== 1 && value.direction !== -1) ||
    !Array.isArray(value.production_fields) ||
    !value.production_fields.every(isRateField) ||
    !isFiniteNumber(value.reference_mean) ||
    !isNonNegativeFiniteNumber(value.population_sd) ||
    !(value.reference_percentage === null ||
      (isFiniteNumber(value.reference_percentage) &&
        value.reference_percentage >= 0 &&
        value.reference_percentage <= 1)) ||
    (value.status !== 'defined' && value.status !== 'zero_variance')
  ) {
    return false
  }

  const expected = CATEGORY_SEMANTICS[value.category_key]
  return (
    value.kind === expected.kind &&
    value.direction === expected.direction &&
    exactStringOrder(value.production_fields, expected.fields) &&
    (value.kind === 'ratio'
      ? value.reference_percentage !== null
      : value.reference_percentage === null) &&
    (value.status === 'defined' ? value.population_sd > 0 : value.population_sd === 0)
  )
}

const RATE_KEYS = [...PRODUCTION_RATE_FIELDS] as const

function isRatesPerGame(value: unknown): value is ProductionRatesPerGame {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, RATE_KEYS) ||
    !PRODUCTION_RATE_FIELDS.every((field) => isNonNegativeFiniteNumber(value[field]))
  ) {
    return false
  }

  const rates = value as unknown as ProductionRatesPerGame
  return (
    rates.field_goals_made_per_game <= rates.field_goals_attempted_per_game &&
    rates.free_throws_made_per_game <= rates.free_throws_attempted_per_game
  )
}

const COMPONENT_KEYS = [
  'category_key',
  'kind',
  'direction',
  'production_fields',
  'transformed_value',
  'z_score',
] as const

function isCategoryComponent(value: unknown): value is ProductionCategoryComponent {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, COMPONENT_KEYS) ||
    !isCategoryKey(value.category_key) ||
    (value.kind !== 'counting' && value.kind !== 'ratio') ||
    (value.direction !== 1 && value.direction !== -1) ||
    !isRecord(value.production_fields) ||
    !isFiniteNumber(value.transformed_value) ||
    !isFiniteNumber(value.z_score)
  ) {
    return false
  }

  const expected = CATEGORY_SEMANTICS[value.category_key]
  const productionFields = value.production_fields
  const fields = Object.keys(productionFields)
  return (
    value.kind === expected.kind &&
    value.direction === expected.direction &&
    sameStringSet(fields, expected.fields) &&
    fields.every((field) => isNonNegativeFiniteNumber(productionFields[field]))
  )
}

const HEALTH_KEYS = ['status', 'credited_appearances'] as const

function isCandidateHealth(value: unknown): value is ProductionCandidateHealth {
  if (!isRecord(value) || !hasExactKeys(value, HEALTH_KEYS)) return false
  if (value.status === 'observed') return isPositiveInteger(value.credited_appearances)
  if (value.status === 'no_observations') return value.credited_appearances === 0
  return value.status === 'unknown' && value.credited_appearances === null
}

const CANDIDATE_KEYS = [
  'player_id',
  'full_name',
  'team_abbreviation',
  'projection_content_sha256',
  'ordinal',
  'rates_per_game',
  'components',
  'total_z',
  'value_above_replacement',
  'health',
] as const

function isCandidate(value: unknown): value is ProductionCandidate {
  return (
    isRecord(value) &&
    hasExactKeys(value, CANDIDATE_KEYS) &&
    isPositiveInteger(value.player_id) &&
    isNonEmptyString(value.full_name) &&
    isNullableNonEmptyString(value.team_abbreviation) &&
    isSha256(value.projection_content_sha256) &&
    isPositiveInteger(value.ordinal) &&
    isRatesPerGame(value.rates_per_game) &&
    Array.isArray(value.components) &&
    value.components.length === PRODUCTION_CATEGORY_KEYS.length &&
    value.components.every(isCategoryComponent) &&
    isFiniteNumber(value.total_z) &&
    (value.value_above_replacement === null ||
      isFiniteNumber(value.value_above_replacement)) &&
    isCandidateHealth(value.health)
  )
}

const PUBLICATION_KEYS = [
  'refresh_id',
  'artifact_key',
  'source',
  'source_version',
] as const

function isHealthPublication(value: unknown): value is ProductionHealthPublication {
  return (
    isRecord(value) &&
    hasExactKeys(value, PUBLICATION_KEYS) &&
    isPositiveInteger(value.refresh_id) &&
    value.artifact_key === PRODUCTION_HEALTH_ARTIFACT_KEY &&
    isNullableNonEmptyString(value.source) &&
    isNullableNonEmptyString(value.source_version)
  )
}

const HEALTH_CONTEXT_KEYS = [
  'status',
  'reason',
  'season',
  'season_type',
  'window_start',
  'as_of_date',
  'publication',
  'row_source_provenance',
  'counting_rule',
  'observation_rows_sha256',
  'ranking_input',
] as const

function isAvailableHealthContext(value: Record<string, unknown>): boolean {
  return (
    value.status === 'available' &&
    value.reason === null &&
    isNonEmptyString(value.season) &&
    isSeasonType(value.season_type) &&
    isDate(value.window_start) &&
    isDate(value.as_of_date) &&
    value.window_start <= value.as_of_date &&
    isHealthPublication(value.publication) &&
    isSha256(value.observation_rows_sha256)
  )
}

function isUnavailableHealthContext(value: Record<string, unknown>): boolean {
  return (
    value.status === 'unavailable' &&
    value.reason === 'no_attributable_publication' &&
    value.season === null &&
    value.season_type === null &&
    value.window_start === null &&
    value.as_of_date === null &&
    value.publication === null &&
    value.observation_rows_sha256 === null
  )
}

function isHealthContext(value: unknown): value is ProductionHealthContext {
  return (
    isRecord(value) &&
    hasExactKeys(value, HEALTH_CONTEXT_KEYS) &&
    value.row_source_provenance === 'not_recorded' &&
    value.counting_rule === 'player_game_log_rows_in_window_including_zero_seconds' &&
    value.ranking_input === false &&
    (isAvailableHealthContext(value) || isUnavailableHealthContext(value))
  )
}

const LIMITATION_KEYS = [
  'strategy_included',
  'punt_adjustment_included',
  'budget_or_affordability_included',
  'position_fit_included',
  'fantrax_roster_eligibility_included',
  'partial_browser_increment',
] as const

function hasExpectedLimitations(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, LIMITATION_KEYS) &&
    value.strategy_included === false &&
    value.punt_adjustment_included === false &&
    value.budget_or_affordability_included === false &&
    value.position_fit_included === false &&
    value.fantrax_roster_eligibility_included === false &&
    value.partial_browser_increment === true
  )
}

const RESPONSE_KEYS = [
  'draft_id',
  'league_id',
  'season',
  'source',
  'source_display_name',
  'series',
  'source_original_filename',
  'draft_status',
  'draft_last_sequence',
  'generated_at',
  'claim',
  'value_scope',
  'availability_included',
  'calibration_status',
  'source_freshness',
  'limitations',
  'lineage',
  'reference',
  'replacement',
  'category_scales',
  'health_context',
  'candidates',
] as const

export function isProductionCandidatesResponse(
  value: unknown,
): value is ProductionCandidatesResponse {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, RESPONSE_KEYS) ||
    !isPositiveInteger(value.draft_id) ||
    !isPositiveInteger(value.league_id) ||
    !isNonEmptyString(value.season) ||
    !isProductionCandidateSource(value.source) ||
    !isNonEmptyString(value.source_display_name) ||
    !isProjectionSeriesDescriptor(value.series) ||
    !isNullableNonEmptyString(value.source_original_filename) ||
    !(DRAFT_STATUSES as readonly unknown[]).includes(value.draft_status) ||
    !isNonNegativeInteger(value.draft_last_sequence) ||
    !isTimestamp(value.generated_at) ||
    value.claim !== 'projection_relative_production_ranking' ||
    value.value_scope !== 'production_only' ||
    value.availability_included !== false ||
    value.calibration_status !== 'not_established_for_current_selected_source' ||
    value.source_freshness !== 'not_established_beyond_current_import' ||
    !hasExpectedLimitations(value.limitations) ||
    !isLineage(value.lineage) ||
    !isReference(value.reference) ||
    !isReplacement(value.replacement) ||
    !Array.isArray(value.category_scales) ||
    value.category_scales.length !== PRODUCTION_CATEGORY_KEYS.length ||
    !value.category_scales.every(isCategoryScale) ||
    !isHealthContext(value.health_context) ||
    !Array.isArray(value.candidates) ||
    !value.candidates.every(isCandidate)
  ) {
    return false
  }

  const response = value as unknown as ProductionCandidatesResponse
  const projectionImport = response.lineage.projection_import
  const scoringProfile = response.lineage.scoring_profile
  const scales = response.category_scales
  const scaleKeys = scales.map((scale) => scale.category_key)
  const candidates = response.candidates
  const candidateIds = candidates.map((candidate) => candidate.player_id)
  const candidateOrdinals = candidates.map((candidate) => candidate.ordinal)
  const excluded = new Set(response.reference.excluded_drafted_player_ids)
  const expectedCandidateIds = response.reference.player_ids.filter(
    (playerId) => !excluded.has(playerId),
  )
  const weights = response.lineage.blend.category_weights
  const healthMatchesContext =
    response.health_context.status === 'available'
      ? candidates.every((candidate) => candidate.health.status !== 'unknown')
      : candidates.every((candidate) => candidate.health.status === 'unknown')
  const replacementMatchesCandidates =
    response.replacement.state === 'available'
      ? candidates.every((candidate) => candidate.value_above_replacement !== null)
      : candidates.every((candidate) => candidate.value_above_replacement === null)

  return (
    new Set(scaleKeys).size === PRODUCTION_CATEGORY_KEYS.length &&
    PRODUCTION_CATEGORY_KEYS.every((key) => scaleKeys.includes(key)) &&
    projectionImport.source === response.source &&
    projectionImport.series_key === response.series.key &&
    projectionImport.season === response.season &&
    projectionImport.projection_count === response.reference.count &&
    (projectionImport.assumed_scoring_type === null ||
      projectionImport.assumed_scoring_type === scoringProfile.scoring_type) &&
    response.lineage.score.scoring_profile_sha256 ===
      scoringProfile.content_sha256 &&
    response.lineage.score.blend_profile_sha256 ===
      response.lineage.blend.content_sha256 &&
    response.lineage.score.blend_result_sha256 ===
      response.lineage.blend.result_content_sha256 &&
    response.replacement.projected_count === response.reference.count &&
    response.reference.candidate_count === candidates.length &&
    new Set(candidateIds).size === candidateIds.length &&
    sameSet(candidateIds, expectedCandidateIds) &&
    new Set(candidateOrdinals).size === candidateOrdinals.length &&
    candidateOrdinals.every(
      (ordinal, index) =>
        ordinal <= response.reference.count &&
        (index === 0 || candidateOrdinals[index - 1]! < ordinal),
    ) &&
    exactStringOrder(
      weights.map((weight) => weight.category_key),
      scaleKeys,
    ) &&
    weights.every((weight) => weight.source === value.source) &&
    candidates.every((candidate) =>
      candidate.components.every((component, index) => {
        const scale = scales[index]
        return (
          scale !== undefined &&
          component.category_key === scale.category_key &&
          component.kind === scale.kind &&
          component.direction === scale.direction &&
          sameStringSet(Object.keys(component.production_fields), scale.production_fields)
        )
      }),
    ) &&
    healthMatchesContext &&
    replacementMatchesCandidates
  )
}

export function getProductionCandidates(
  draftId: number,
  source: ProductionCandidateSource,
  options: ProductionCandidatesOptions = {},
): Promise<ProductionCandidatesResponse> {
  const contract = {
    isSuccess: (value: unknown): value is ProductionCandidatesResponse =>
      isProductionCandidatesResponse(value) &&
      value.draft_id === draftId &&
      value.source === source &&
      (options.expectedLeagueId === undefined || value.league_id === options.expectedLeagueId) &&
      (options.expectedSeason === undefined || value.season === options.expectedSeason) &&
      (options.seriesKey === undefined || value.series.key === options.seriesKey),
    invalidResponseDetail:
      'The production-candidates response did not match the requested draft/league/source/season/series release contract.',
  } satisfies ResponseContract<ProductionCandidatesResponse>

  const query = new URLSearchParams({ source })
  if (options.seriesKey !== undefined) query.set('series_key', options.seriesKey)
  return apiFetch(
    `/api/v1/drafts/${String(draftId)}/production-candidates?${query.toString()}`,
    contract,
    {
      timeoutMs: 15_000,
      ...options,
    },
  )
}
