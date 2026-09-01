export const RELIABILITY_CATEGORY_UNITS = ['count', 'volume_weighted_impact'] as const
export const RELIABILITY_COUNT_CATEGORIES = [
  'fg3m',
  'pts',
  'reb',
  'ast',
  'stl',
  'blk',
  'to',
] as const
export const RELIABILITY_RATIO_CATEGORIES = ['fg_pct', 'ft_pct'] as const
export const RELIABILITY_CATEGORIES = [
  ...RELIABILITY_COUNT_CATEGORIES,
  ...RELIABILITY_RATIO_CATEGORIES,
] as const

export type ReliabilityCategoryUnit = (typeof RELIABILITY_CATEGORY_UNITS)[number]
export type ReliabilityCategory = (typeof RELIABILITY_CATEGORIES)[number]

export interface ObservedRateEvidence {
  direct_play: number
  direct_non_play: number
  explicit_unknown: number
  observed_opportunities: number
  observed_play_rate: number | null
  observed_non_play_rate: number | null
  coverage_status: 'incomplete_r35'
  opportunity_coverage: null
}

export interface MonthlyRateEvidence {
  month: string
  evidence: ObservedRateEvidence
}

export interface AvailabilityEvidence {
  overall: ObservedRateEvidence
  monthly_trend: MonthlyRateEvidence[]
  back_to_back: ObservedRateEvidence
}

export interface DistributionSummary {
  observed_games: number
  lower_percentile_probability: number
  upper_percentile_probability: number
  mean: number | null
  sample_standard_deviation: number | null
  lower_percentile: number | null
  upper_percentile: number | null
}

export interface MinutesConsistency {
  distribution_minutes: DistributionSummary
  coefficient_of_variation: number | null
}

export interface RatioBaseline {
  made: number
  attempted: number
  rate: number | null
}

export interface CategoryConsistency {
  category: ReliabilityCategory
  unit: ReliabilityCategoryUnit
  distribution: DistributionSummary
  ratio_baseline: RatioBaseline | null
}

export interface ProductionConsistency {
  played_games: number
  minutes: MinutesConsistency
  categories: CategoryConsistency[]
}

export interface PlayerReliabilityScorecard {
  player_id: number
  player_name: string | null
  availability: AvailabilityEvidence
  production: ProductionConsistency
}

export interface ReliabilityLineage {
  season: string
  season_type: string
  window_start: string
  as_of_date: string
  schedule_version: string
  schedule_refreshed_at: string
  source_version: string
  derivation_version: string
  computed_at: string
}

export interface ReliabilityCohortCounts {
  scorecards: number
  scheduled_team_games: number
  schedule_context_team_games: number
  final_games: number
  player_game_logs: number
  participation_rows: number
}

export interface ReliabilityScorecardsResponse {
  season: string
  season_type: string
  lineage: ReliabilityLineage
  counts: ReliabilityCohortCounts
  scorecards: PlayerReliabilityScorecard[]
}
