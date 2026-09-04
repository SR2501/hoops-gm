import { apiFetch, type RequestOptions, type ResponseContract } from './client'
import {
  RELIABILITY_CATEGORIES,
  RELIABILITY_CATEGORY_UNITS,
  type AvailabilityEvidence,
  type CategoryConsistency,
  type DistributionSummary,
  type MonthlyRateEvidence,
  type ObservedRateEvidence,
  type PlayerReliabilityScorecard,
  type ProductionConsistency,
  type RatioBaseline,
  type ReliabilityCohortCounts,
  type ReliabilityCategory,
  type ReliabilityCategoryUnit,
  type ReliabilityLineage,
  type ReliabilityScorecardsResponse,
} from './reliabilityTypes'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function isFiniteNumberOrNull(value: unknown): value is number | null {
  return value === null || (typeof value === 'number' && Number.isFinite(value))
}

function isRateOrNull(value: unknown): value is number | null {
  return value === null || (typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1)
}

function isDate(value: unknown): value is string {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value))
}

function isMonthStart(value: unknown): value is string {
  return isDate(value) && value.endsWith('-01')
}

function isTimestamp(value: unknown): value is string {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value))
}

function isObservedRateEvidence(value: unknown): value is ObservedRateEvidence {
  if (
    !isRecord(value) ||
    !isNonNegativeInteger(value.direct_play) ||
    !isNonNegativeInteger(value.direct_non_play) ||
    !isNonNegativeInteger(value.explicit_unknown) ||
    !isNonNegativeInteger(value.observed_opportunities) ||
    !isRateOrNull(value.observed_play_rate) ||
    !isRateOrNull(value.observed_non_play_rate) ||
    value.coverage_status !== 'incomplete_r35' ||
    !Object.hasOwn(value, 'opportunity_coverage') ||
    value.opportunity_coverage !== null
  ) {
    return false
  }

  const opportunities = value.direct_play + value.direct_non_play
  if (value.observed_opportunities !== opportunities) return false
  if (opportunities === 0) {
    return value.observed_play_rate === null && value.observed_non_play_rate === null
  }
  return (
    value.observed_play_rate !== null &&
    value.observed_non_play_rate !== null &&
    Math.abs(value.observed_play_rate - value.direct_play / opportunities) < 1e-12 &&
    Math.abs(value.observed_non_play_rate - value.direct_non_play / opportunities) < 1e-12
  )
}

function isMonthlyRateEvidence(value: unknown): value is MonthlyRateEvidence {
  return isRecord(value) && isMonthStart(value.month) && isObservedRateEvidence(value.evidence)
}

function isChronologicalMonthlyRateEvidence(value: unknown): value is MonthlyRateEvidence[] {
  if (!Array.isArray(value) || !value.every(isMonthlyRateEvidence)) return false
  // The producer publishes one grouped row per month in ascending order. Refuse
  // drift instead of silently sorting or deduplicating evidence in the browser.
  return value.every(
    (row, index) => index === 0 || value[index - 1]!.month < row.month,
  )
}

function isAvailabilityEvidence(value: unknown): value is AvailabilityEvidence {
  return (
    isRecord(value) &&
    isObservedRateEvidence(value.overall) &&
    isChronologicalMonthlyRateEvidence(value.monthly_trend) &&
    isObservedRateEvidence(value.back_to_back)
  )
}

function isDistributionSummary(value: unknown): value is DistributionSummary {
  return (
    isRecord(value) &&
    isNonNegativeInteger(value.observed_games) &&
    isRateOrNull(value.lower_percentile_probability) &&
    value.lower_percentile_probability !== null &&
    isRateOrNull(value.upper_percentile_probability) &&
    value.upper_percentile_probability !== null &&
    value.lower_percentile_probability < value.upper_percentile_probability &&
    isFiniteNumberOrNull(value.mean) &&
    isFiniteNumberOrNull(value.sample_standard_deviation) &&
    (value.sample_standard_deviation === null || value.sample_standard_deviation >= 0) &&
    isFiniteNumberOrNull(value.lower_percentile) &&
    isFiniteNumberOrNull(value.upper_percentile)
  )
}

function isRatioBaseline(value: unknown): value is RatioBaseline {
  if (
    !isRecord(value) ||
    !isNonNegativeInteger(value.made) ||
    !isNonNegativeInteger(value.attempted) ||
    value.made > value.attempted ||
    !isRateOrNull(value.rate)
  ) {
    return false
  }
  if (value.attempted === 0) return value.made === 0 && value.rate === null
  return value.rate !== null && Math.abs(value.rate - value.made / value.attempted) < 1e-12
}

function isReliabilityCategory(value: unknown): value is ReliabilityCategory {
  return (RELIABILITY_CATEGORIES as readonly unknown[]).includes(value)
}

const EXPECTED_CATEGORY_UNITS: Record<ReliabilityCategory, ReliabilityCategoryUnit> = {
  fg3m: 'count',
  pts: 'count',
  reb: 'count',
  ast: 'count',
  stl: 'count',
  blk: 'count',
  to: 'count',
  fg_pct: 'volume_weighted_impact',
  ft_pct: 'volume_weighted_impact',
}

function expectedCategoryUnit(category: ReliabilityCategory): ReliabilityCategoryUnit {
  return EXPECTED_CATEGORY_UNITS[category]
}

function isCategoryConsistency(value: unknown): value is CategoryConsistency {
  if (
    !isRecord(value) ||
    !isReliabilityCategory(value.category) ||
    !(RELIABILITY_CATEGORY_UNITS as readonly unknown[]).includes(value.unit) ||
    value.unit !== expectedCategoryUnit(value.category) ||
    !isDistributionSummary(value.distribution)
  ) {
    return false
  }
  return value.unit === 'count'
    ? value.ratio_baseline === null
    : isRatioBaseline(value.ratio_baseline)
}

function isProductionConsistency(value: unknown): value is ProductionConsistency {
  if (
    !isRecord(value) ||
    !isNonNegativeInteger(value.played_games) ||
    !isRecord(value.minutes) ||
    !isDistributionSummary(value.minutes.distribution_minutes) ||
    !isFiniteNumberOrNull(value.minutes.coefficient_of_variation) ||
    (value.minutes.coefficient_of_variation !== null && value.minutes.coefficient_of_variation < 0) ||
    !Array.isArray(value.categories) ||
    !value.categories.every(isCategoryConsistency)
  ) {
    return false
  }
  const categories = value.categories
  return (
    categories.length === RELIABILITY_CATEGORIES.length &&
    new Set(categories.map((category) => category.category)).size === categories.length &&
    RELIABILITY_CATEGORIES.every((category) =>
      categories.some((candidate) => candidate.category === category),
    )
  )
}

function isPlayerScorecard(value: unknown): value is PlayerReliabilityScorecard {
  return (
    isRecord(value) &&
    isNonNegativeInteger(value.player_id) &&
    value.player_id > 0 &&
    (typeof value.player_name === 'string' || value.player_name === null) &&
    isAvailabilityEvidence(value.availability) &&
    isProductionConsistency(value.production)
  )
}

function isLineage(value: unknown): value is ReliabilityLineage {
  if (
    !isRecord(value) ||
    typeof value.season !== 'string' ||
    typeof value.season_type !== 'string' ||
    !isDate(value.window_start) ||
    !isDate(value.as_of_date) ||
    typeof value.schedule_source !== 'string' ||
    typeof value.schedule_version !== 'string' ||
    !isTimestamp(value.schedule_refreshed_at) ||
    typeof value.observation_source !== 'string' ||
    typeof value.source_version !== 'string' ||
    typeof value.derivation_source !== 'string' ||
    typeof value.derivation_version !== 'string' ||
    !isTimestamp(value.computed_at)
  ) {
    return false
  }
  return value.window_start <= value.as_of_date
}

function isCounts(value: unknown): value is ReliabilityCohortCounts {
  return (
    isRecord(value) &&
    isNonNegativeInteger(value.scorecards) &&
    isNonNegativeInteger(value.scheduled_team_games) &&
    isNonNegativeInteger(value.schedule_context_team_games) &&
    isNonNegativeInteger(value.final_games) &&
    isNonNegativeInteger(value.player_game_logs) &&
    isNonNegativeInteger(value.participation_rows)
  )
}

export function isReliabilityScorecardsResponse(
  value: unknown,
): value is ReliabilityScorecardsResponse {
  if (
    !isRecord(value) ||
    typeof value.season !== 'string' ||
    typeof value.season_type !== 'string' ||
    !isLineage(value.lineage) ||
    !isCounts(value.counts) ||
    !Array.isArray(value.scorecards) ||
    !value.scorecards.every(isPlayerScorecard)
  ) {
    return false
  }
  const ids = value.scorecards.map((card) => card.player_id)
  return (
    value.season === value.lineage.season &&
    value.season_type === value.lineage.season_type &&
    value.counts.scorecards === ids.length &&
    new Set(ids).size === ids.length
  )
}

const RELIABILITY_CONTRACT = {
  isSuccess: isReliabilityScorecardsResponse,
  invalidResponseDetail:
    'The reliability scorecards response did not match the expected backend contract.',
} satisfies ResponseContract<ReliabilityScorecardsResponse>

export function getReliabilityScorecards(
  options?: RequestOptions,
): Promise<ReliabilityScorecardsResponse> {
  return apiFetch('/api/v1/reliability/scorecards', RELIABILITY_CONTRACT, {
    timeoutMs: 15_000,
    ...options,
  })
}
