/**
 * Fabricated inventory for focused legacy page tests, not a recording.
 * Named-series integration tests use the genuine HTTP files without this helper.
 */
import type { ProductionCandidateSource } from '../api/productionCandidatesTypes'
import type {
  DraftProjectionSeriesCatalog,
  ProjectionSeriesCatalog,
  ProjectionSeriesDescriptor,
} from '../api/projectionSeriesTypes'
import { requestUrl } from './helpers'

export function syntheticSeriesDescriptor(key = 'legacy'): ProjectionSeriesDescriptor {
  return key === 'legacy'
    ? { key, display_name: 'Unspecified legacy series', provenance: 'legacy_unspecified' }
    : { key, display_name: `${key} synthetic series`, provenance: 'operator_declared' }
}

export function syntheticSeriesCatalog({
  leagueId = 1,
  source = 'basketball_monster',
  keys = ['legacy'],
  season = '2026-27',
}: {
  leagueId?: number
  source?: ProductionCandidateSource
  keys?: string[]
  season?: string
} = {}): ProjectionSeriesCatalog {
  return {
    league_id: leagueId,
    season,
    source,
    source_display_name: `Synthetic ${source} inventory`,
    selection_required: keys.length > 1,
    series: [...keys].sort().map((key, index) => ({
      ...syntheticSeriesDescriptor(key),
      latest_import: {
        import_id: index + 1,
        imported_at: '2026-09-18T12:00:00Z',
        content_sha256: 'a'.repeat(64),
        profile_id: 'synthetic-profile',
        profile_version: '1',
        profile_definition_sha256: 'b'.repeat(64),
        original_filename: `synthetic-${key}.csv`,
      },
    })),
  }
}

export function syntheticDraftSeriesCatalog(
  draftId = 2,
  source: ProductionCandidateSource = 'basketball_monster',
): DraftProjectionSeriesCatalog {
  return { ...syntheticSeriesCatalog({ leagueId: 2, source }), draft_id: draftId }
}

/**
 * Add catalog I/O to tests whose assertions count *numerical* attempts. The
 * underlying fetch spy still sees every numerical request, through the real
 * client/useAsync. Dedicated chooser tests count both kinds explicitly.
 */
export function withSingleSeriesCatalog(
  numericalFetch: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
) {
  return (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(requestUrl(input), 'http://127.0.0.1')
    const league = /^\/api\/v1\/leagues\/(\d+)\/projections\/series$/.exec(url.pathname)
    const draft = /^\/api\/v1\/drafts\/(\d+)\/projection-series$/.exec(url.pathname)
    if (league !== null || draft !== null) {
      const source = url.searchParams.get('source') as ProductionCandidateSource
      const body = draft !== null
        ? syntheticDraftSeriesCatalog(Number(draft[1]), source)
        : syntheticSeriesCatalog({ leagueId: Number(league![1]), source })
      return Promise.resolve(new Response(JSON.stringify(body), {
        headers: { 'Content-Type': 'application/json' },
      }))
    }
    return numericalFetch(input, init)
  }
}
