import type { ProductionCandidateSource } from './productionCandidatesTypes'

const SOURCE_LABELS: Record<ProductionCandidateSource, string> = {
  basketball_monster: 'Basketball Monster',
  fantasypros: 'FantasyPros',
  hashtag: 'Hashtag Basketball',
  darko: 'DARKO',
  manual: 'Manual import',
}

export function productionSourceLabel(source: ProductionCandidateSource): string {
  return SOURCE_LABELS[source]
}
