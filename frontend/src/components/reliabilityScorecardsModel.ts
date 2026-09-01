import type {
  PlayerReliabilityScorecard,
  ReliabilityScorecardsResponse,
} from '../api/reliabilityTypes'

export const RELIABILITY_FILTERS = ['all', 'non_play', 'no_b2b', 'missing_name'] as const
export type ReliabilityFilter = (typeof RELIABILITY_FILTERS)[number]

export const RELIABILITY_FILTER_LABELS: Record<ReliabilityFilter, string> = {
  all: 'All players',
  non_play: 'Has direct non-play evidence',
  no_b2b: 'No B2B evidence rows',
  missing_name: 'Name unavailable',
}

export function isReliabilityFilter(value: string): value is ReliabilityFilter {
  return (RELIABILITY_FILTERS as readonly string[]).includes(value)
}

export interface ReliabilityRow {
  card: PlayerReliabilityScorecard
  displayName: string
  searchText: string
}

export function buildReliabilityRows(payload: ReliabilityScorecardsResponse): ReliabilityRow[] {
  return payload.scorecards
    .map((card) => {
      const name = card.player_name?.trim() || null
      const displayName = name ?? `Name unavailable · player ${String(card.player_id)}`
      return {
        card,
        displayName,
        searchText: `${name ?? ''} ${String(card.player_id)}`.toLocaleLowerCase(),
      }
    })
    .sort(
      (left, right) =>
        Number(left.card.player_name === null) - Number(right.card.player_name === null) ||
        left.displayName.localeCompare(right.displayName) ||
        left.card.player_id - right.card.player_id,
    )
}

export function filterReliabilityRows(
  rows: readonly ReliabilityRow[],
  query: string,
  filter: ReliabilityFilter,
): ReliabilityRow[] {
  const needle = query.trim().toLocaleLowerCase()
  return rows.filter((row) => {
    if (needle && !row.searchText.includes(needle)) return false
    if (filter === 'non_play') return row.card.availability.overall.direct_non_play > 0
    if (filter === 'no_b2b') {
      const evidence = row.card.availability.back_to_back
      return evidence.observed_opportunities === 0 && evidence.explicit_unknown === 0
    }
    if (filter === 'missing_name') return !row.card.player_name?.trim()
    return true
  })
}

export function formatRate(rate: number | null): string {
  return rate === null ? 'Unavailable' : `${(rate * 100).toFixed(1)}%`
}

export function formatNumber(value: number | null, digits = 1): string {
  return value === null ? 'Unavailable' : value.toFixed(digits)
}
