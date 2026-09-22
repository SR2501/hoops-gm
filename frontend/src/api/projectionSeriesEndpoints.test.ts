import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './client'
import { getCurrentProjections, isCurrentProjections } from './endpoints'
import {
  getProductionCandidates,
  isProductionCandidatesResponse,
} from './productionCandidatesEndpoints'
import {
  getDraftProjectionSeries,
  getProjectionSeries,
  isDraftProjectionSeriesCatalog,
  isProjectionSeriesCatalog,
  isProjectionSeriesDescriptor,
  isProjectionSeriesKey,
} from './projectionSeriesEndpoints'
import {
  PROJECTION_RELEASE_SCHEMA_VERSION,
  projectionSeriesScopeKey,
} from './projectionSeriesTypes'
import { mockFetch, requestUrl } from '../test/helpers'
import {
  candidateRecordings,
  projectionRecordings,
  recordedDraftCatalog,
  recordedLeagueCatalog,
  recordedSingleCatalog,
} from '../test/projectionSeriesRecordings'
import oldProjections from '../test/fixtures/projections-current.recorded.json'
import { syntheticSeriesCatalog, syntheticSeriesDescriptor } from '../test/projectionSeriesStub'

afterEach(() => { vi.unstubAllGlobals() })

describe('recorded series inventory contract', () => {
  it('uses the league and draft routes with explicit publishers, never an inferred league for drafts', async () => {
    const fetchMock = mockFetch({
      '/api/v1/leagues/1/projections/series?source=basketball_monster': { body: recordedLeagueCatalog },
      '/api/v1/drafts/1/projection-series?source=basketball_monster': { body: recordedDraftCatalog },
    })
    await expect(getProjectionSeries(1)).resolves.toEqual(recordedLeagueCatalog)
    await expect(getDraftProjectionSeries(1, 'basketball_monster')).resolves.toEqual(recordedDraftCatalog)
    expect(recordedDraftCatalog.league_id).toBe(2)
    expect(fetchMock.mock.calls.map(([input]) => requestUrl(input))).toEqual([
      '/api/v1/leagues/1/projections/series?source=basketball_monster',
      '/api/v1/drafts/1/projection-series?source=basketball_monster',
    ])
  })

  it('accepts zero inventory and the genuine sole legacy inventory without advertising supported imports', () => {
    expect(isProjectionSeriesCatalog(syntheticSeriesCatalog({ keys: [] }))).toBe(true)
    expect(isDraftProjectionSeriesCatalog(recordedSingleCatalog)).toBe(true)
    expect(recordedSingleCatalog.series.map((entry) => entry.key)).toEqual(['legacy'])
    expect(recordedSingleCatalog.selection_required).toBe(false)
    expect(recordedDraftCatalog.series.map((entry) => entry.key)).toEqual(['bonus', 'josh', 'legacy'])
  })

  it.each(['draft', 'league', 'source'] as const)('rejects a well-formed wrong %s catalog HTTP200', async (field) => {
    const body = structuredClone(recordedDraftCatalog)
    if (field === 'draft') body.draft_id = 4
    if (field === 'source') body.source = 'fantasypros'
    const leagueBody = { ...recordedLeagueCatalog, league_id: 4 }
    mockFetch({
      '/projection-series': { body, headers: { 'X-Request-ID': 'catalog-scope' } },
      '/projections/series': { body: leagueBody, headers: { 'X-Request-ID': 'catalog-scope' } },
    })
    const request = field === 'league' ? getProjectionSeries(1) : getDraftProjectionSeries(1, 'basketball_monster')
    await expect(request).rejects.toMatchObject({
      status: 200, code: 'invalid_response', requestId: 'catalog-scope',
    })
  })

  it('does not accept a league catalog as a draft catalog or discard extra catalog fields', () => {
    expect(isDraftProjectionSeriesCatalog(recordedLeagueCatalog)).toBe(false)
    expect(isProjectionSeriesCatalog(recordedDraftCatalog)).toBe(false)
    expect(isProjectionSeriesCatalog({ ...recordedLeagueCatalog, active_series: 'josh' })).toBe(false)
  })

  it.each(['duplicate', 'unsorted', 'ambiguity', 'legacy', 'hash', 'profile', 'time', 'id'] as const)(
    'rejects contradictory or incomplete %s inventory evidence',
    (fault) => {
      const body = structuredClone(recordedLeagueCatalog)
      const entry = body.series[0]!
      if (fault === 'duplicate') body.series.push(structuredClone(entry))
      if (fault === 'unsorted') body.series.reverse()
      if (fault === 'ambiguity') body.selection_required = false
      if (fault === 'legacy') body.series.find((series) => series.key === 'legacy')!.display_name = 'Josh'
      if (fault === 'hash') entry.latest_import.content_sha256 = 'not-a-hash'
      if (fault === 'profile') entry.latest_import.profile_id = ''
      if (fault === 'time') entry.latest_import.imported_at = 'yesterday'
      if (fault === 'id') entry.latest_import.import_id = 0
      expect(isProjectionSeriesCatalog(body)).toBe(false)
    },
  )

  it.each(['', ' ', 'Josh', 'josh\n', 'josh\r\n', '-josh', 'josh.bonus', 'é', 'a'.repeat(65)])(
    'requires a FULL canonical ASCII series key: %j',
    (key) => {
      expect(isProjectionSeriesKey(key)).toBe(false)
      expect(isProjectionSeriesDescriptor(syntheticSeriesDescriptor(key))).toBe(false)
    },
  )

  it.each(['josh', 'bonus', 'a'.repeat(64), 'josh_v2-2026'])('accepts canonical named key %s', (key) => {
    expect(isProjectionSeriesDescriptor(syntheticSeriesDescriptor(key))).toBe(true)
  })

  it('checks legacy and named provenance and bounded nonblank labels, not filenames', () => {
    expect(isProjectionSeriesDescriptor(syntheticSeriesDescriptor())).toBe(true)
    expect(isProjectionSeriesDescriptor({ ...syntheticSeriesDescriptor(), provenance: 'operator_declared' })).toBe(false)
    expect(isProjectionSeriesDescriptor({ ...syntheticSeriesDescriptor('josh'), provenance: 'legacy_unspecified' })).toBe(false)
    for (const display_name of ['', '   ', 'a'.repeat(129)]) {
      expect(isProjectionSeriesDescriptor({ ...syntheticSeriesDescriptor('josh'), display_name })).toBe(false)
    }
    expect(isProjectionSeriesDescriptor({ ...syntheticSeriesDescriptor('josh'), latest_import: {} })).toBe(false)
  })
})

describe('numerical current-within-series scope', () => {
  for (const key of ['legacy', 'josh', 'bonus'] as const) {
    it(`accepts the genuine ${key} release on both numerical routes and sends explicit selection`, async () => {
      const fetchMock = mockFetch({
        [`/leagues/1/projections/current?source=basketball_monster&series_key=${key}`]: { body: projectionRecordings[key] },
        [`/drafts/1/production-candidates?source=basketball_monster&series_key=${key}`]: { body: candidateRecordings[key] },
      })
      await expect(getCurrentProjections(1, { seriesKey: key, expectedSeason: '2026-27' }))
        .resolves.toEqual(projectionRecordings[key])
      await expect(getProductionCandidates(1, 'basketball_monster', {
        seriesKey: key, expectedSeason: '2026-27', expectedLeagueId: 2,
      })).resolves.toEqual(candidateRecordings[key])
      for (const [input] of fetchMock.mock.calls) {
        const url = new URL(requestUrl(input), 'http://127.0.0.1')
        expect(url.searchParams.get('series_key')).toBe(key)
        expect([...url.searchParams.keys()]).toEqual(['source', 'series_key'])
      }
    })
  }

  it('preserves old optional-options call shapes and explicit omission for sole-series callers', async () => {
    const fetchMock = mockFetch({
      '/projections/current': { body: projectionRecordings.legacy },
      '/production-candidates': { body: candidateRecordings.legacy },
    })
    await getCurrentProjections(1)
    await getProductionCandidates(1, 'basketball_monster')
    expect(fetchMock.mock.calls.every(([input]) => !requestUrl(input).includes('series_key'))).toBe(true)
  })

  it('rejects genuine Bonus HTTP200s for Josh requests even though both shapes and scopes are otherwise valid', async () => {
    mockFetch({
      '/projections/current': { body: projectionRecordings.bonus },
      '/production-candidates': { body: candidateRecordings.bonus },
    })
    expect(isCurrentProjections(projectionRecordings.bonus)).toBe(true)
    expect(isProductionCandidatesResponse(candidateRecordings.bonus)).toBe(true)
    await expect(getCurrentProjections(1, { seriesKey: 'josh' })).rejects.toMatchObject({ code: 'invalid_response' })
    await expect(getProductionCandidates(1, 'basketball_monster', { seriesKey: 'josh' })).rejects.toMatchObject({ code: 'invalid_response' })
  })

  it.each(['league', 'source', 'season'] as const)('rejects a well-formed wrong %s projection release', async (field) => {
    const body = structuredClone(projectionRecordings.josh)
    if (field === 'league') body.league_id = 3
    if (field === 'source') body.source = body.lineage.projection_import.source = 'fantasypros'
    if (field === 'season') body.season = body.lineage.projection_import.season = '2025-26'
    expect(isCurrentProjections(body)).toBe(true)
    mockFetch({ '/projections/current': { body, headers: { 'X-Request-ID': 'wrong-projection-scope' } } })
    await expect(getCurrentProjections(1, { seriesKey: 'josh', expectedSeason: '2026-27' })).rejects.toMatchObject({
      code: 'invalid_response', requestId: 'wrong-projection-scope',
    })
  })

  it.each(['draft', 'league', 'source', 'season'] as const)('rejects a well-formed wrong %s candidate release', async (field) => {
    const body = structuredClone(candidateRecordings.josh)
    if (field === 'draft') body.draft_id = 3
    if (field === 'league') body.league_id = 3
    if (field === 'source') {
      body.source = body.lineage.projection_import.source = 'fantasypros'
      body.lineage.blend.category_weights.forEach((weight) => { weight.source = 'fantasypros' })
    }
    if (field === 'season') body.season = body.lineage.projection_import.season = '2025-26'
    expect(isProductionCandidatesResponse(body)).toBe(true)
    mockFetch({ '/production-candidates': { body, headers: { 'X-Request-ID': 'wrong-candidate-scope' } } })
    await expect(getProductionCandidates(1, 'basketball_monster', {
      seriesKey: 'josh', expectedSeason: '2026-27', expectedLeagueId: 2,
    })).rejects.toMatchObject({ code: 'invalid_response', requestId: 'wrong-candidate-scope' })
  })

  it.each(['series_key', 'release_schema_version', 'source', 'season'] as const)(
    'refuses a contradictory import %s HTTP200 on both routes',
    async (field) => {
      const projections = structuredClone(projectionRecordings.josh)
      const candidates = structuredClone(candidateRecordings.josh)
      for (const payload of [projections, candidates]) {
        const imported = payload.lineage.projection_import as unknown as Record<string, unknown>
        imported[field] = {
          series_key: 'bonus', release_schema_version: 'projection-import-release-v1',
          source: 'fantasypros', season: '2025-26',
        }[field]
      }
      mockFetch({ '/projections/current': { body: projections }, '/production-candidates': { body: candidates } })
      await expect(getCurrentProjections(1, { seriesKey: 'josh' })).rejects.toBeInstanceOf(ApiError)
      await expect(getProductionCandidates(1, 'basketball_monster', { seriesKey: 'josh' })).rejects.toMatchObject({
        status: 200, code: 'invalid_response',
      })
      expect(isCurrentProjections(projections)).toBe(false)
      expect(isProductionCandidatesResponse(candidates)).toBe(false)
    },
  )

  it('rejects the old projection recording without adding successor fields', async () => {
    mockFetch({ '/projections/current': { body: oldProjections } })
    await expect(getCurrentProjections(1)).rejects.toMatchObject({ code: 'invalid_response' })
    expect(oldProjections).not.toHaveProperty('series')
    expect(oldProjections.lineage.projection_import).not.toHaveProperty('release_schema_version')
  })

  it.each(['', ' ', 'Josh', 'josh\n'])('never drops an invalid explicit key %j into the omission fallback', async (seriesKey) => {
    // A server incorrectly ignoring the key still cannot satisfy the client.
    const fetchMock = mockFetch({
      '/projections/current': { body: projectionRecordings.legacy },
      '/production-candidates': { body: candidateRecordings.legacy },
    })
    await expect(getCurrentProjections(1, { seriesKey })).rejects.toMatchObject({ code: 'invalid_response' })
    await expect(getProductionCandidates(1, 'basketball_monster', { seriesKey })).rejects.toMatchObject({ code: 'invalid_response' })
    for (const [input] of fetchMock.mock.calls) {
      const query = new URL(requestUrl(input), 'http://127.0.0.1').searchParams
      expect(query.has('series_key')).toBe(true)
      expect(query.get('series_key')).toBe(seriesKey)
    }
  })

  it('namespaces cold boundaries by release, resource, league, season, publisher and series (not import id)', () => {
    const selection = { leagueId: 2, season: '2026-27', seriesKey: 'josh' }
    const keys = [
      projectionSeriesScopeKey('draft', 1, 'basketball_monster', selection),
      projectionSeriesScopeKey('league', 1, 'basketball_monster', selection),
      projectionSeriesScopeKey('draft', 2, 'basketball_monster', selection),
      projectionSeriesScopeKey('draft', 1, 'fantasypros', selection),
      projectionSeriesScopeKey('draft', 1, 'basketball_monster', { ...selection, leagueId: 3 }),
      projectionSeriesScopeKey('draft', 1, 'basketball_monster', { ...selection, season: '2025-26' }),
      projectionSeriesScopeKey('draft', 1, 'basketball_monster', { ...selection, seriesKey: 'bonus' }),
    ]
    expect(new Set(keys).size).toBe(keys.length)
    expect(keys.every((key) => key.includes(PROJECTION_RELEASE_SCHEMA_VERSION))).toBe(true)
  })
})
