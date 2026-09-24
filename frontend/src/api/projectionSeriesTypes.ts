import type { RequestOptions } from './client'
import type { ProductionCandidateSource } from './productionCandidatesTypes'

/** A release-domain successor, not a parser version or a model/calibration claim. */
export const PROJECTION_RELEASE_SCHEMA_VERSION = 'projection-import-release-series-v1'
export const DEFAULT_PROJECTION_SOURCE: ProductionCandidateSource = 'basketball_monster'
export const PROJECTION_SERIES_PROVENANCES = ['operator_declared', 'legacy_unspecified'] as const

export interface ProjectionSeriesDescriptor {
  key: string
  display_name: string
  provenance: (typeof PROJECTION_SERIES_PROVENANCES)[number]
}

export interface LatestSeriesImport {
  import_id: number
  imported_at: string
  content_sha256: string
  profile_id: string
  profile_version: string
  profile_definition_sha256: string
  original_filename: string | null
}

export interface ProjectionSeriesEntry extends ProjectionSeriesDescriptor {
  latest_import: LatestSeriesImport
}

/** Recorded candidates only. Presence in this inventory is not release approval. */
export interface ProjectionSeriesCatalog {
  league_id: number
  season: string
  source: ProductionCandidateSource
  source_display_name: string | null
  selection_required: boolean
  series: ProjectionSeriesEntry[]
}

export interface DraftProjectionSeriesCatalog extends ProjectionSeriesCatalog {
  draft_id: number
}

export interface ProjectionSelectionOptions extends RequestOptions {
  seriesKey?: string
  /** Check the response against catalog context; never sent as a query/pinning option. */
  expectedSeason?: string
}

export interface CurrentProjectionsOptions extends ProjectionSelectionOptions {
  source?: ProductionCandidateSource
}

export interface ProductionCandidatesOptions extends ProjectionSelectionOptions {
  /** From the draft-scoped catalog, not an assumed league id. */
  expectedLeagueId?: number
}

export interface ProjectionSelection {
  leagueId: number
  season: string
  seriesKey: string
}

/**
 * React cold-boundary identity, not an active pointer or a persisted cache.
 * No exact import id: a refresh follows the current import within this series.
 */
export function projectionSeriesScopeKey(
  resource: 'league' | 'draft',
  resourceId: number,
  source: ProductionCandidateSource,
  selection?: ProjectionSelection,
): string {
  return JSON.stringify([
    PROJECTION_RELEASE_SCHEMA_VERSION,
    resource,
    resourceId,
    selection?.leagueId ?? null,
    selection?.season ?? null,
    source,
    selection?.seriesKey ?? null,
  ])
}
