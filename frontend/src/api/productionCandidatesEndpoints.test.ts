import { afterEach, describe, expect, it, vi } from 'vitest'
import recordedResponse from '../test/fixtures/draft-production-candidates.recorded.json'
import { syntheticProductionCandidates } from '../test/productionCandidatesStub'
import { mockFetch, requestUrl } from '../test/helpers'
import { ApiError } from './client'
import {
  PRODUCTION_SCORING_TYPES,
  PRODUCTION_SEASON_TYPES,
} from './productionCandidatesTypes'
import {
  getProductionCandidates,
  isProductionCandidatesResponse,
} from './productionCandidatesEndpoints'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('production-candidates endpoint contract', () => {
  it('requires the selected source in the request and accepts the complete response', async () => {
    const payload = syntheticProductionCandidates()
    const fetchMock = mockFetch({
      '/api/v1/drafts/2/production-candidates?source=basketball_monster': {
        body: payload,
      },
    })

    await expect(
      getProductionCandidates(2, 'basketball_monster'),
    ).resolves.toEqual(payload)
    expect(requestUrl(fetchMock.mock.calls[0]![0])).toBe(
      '/api/v1/drafts/2/production-candidates?source=basketball_monster',
    )
  })

  it('rejects a valid payload for another draft or source instead of relabelling it', async () => {
    const payload = syntheticProductionCandidates({
      draftId: 3,
      source: 'fantasypros',
    })
    mockFetch({
      '/api/v1/drafts/2/production-candidates?source=basketball_monster': {
        body: payload,
        headers: { 'X-Request-ID': 'req-wrong-scope' },
      },
    })

    const error = await getProductionCandidates(2, 'basketball_monster').catch(
      (cause: unknown) => cause,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('invalid_response')
    expect((error as ApiError).requestId).toBe('req-wrong-scope')
  })

  it('accepts category arrays in the profile order rather than imposing another order', () => {
    const payload = syntheticProductionCandidates()

    expect(payload.category_scales.map((scale) => scale.category_key)).toEqual([
      'to',
      'pts',
      'fg_pct',
      'reb',
      'ast',
      'stl',
      'blk',
      'fg3m',
      'ft_pct',
    ])
    expect(isProductionCandidatesResponse(payload)).toBe(true)
  })

  it('requires the stored source label while accepting a missing original filename', () => {
    const nullableFilename = structuredClone(syntheticProductionCandidates())
    nullableFilename.source_original_filename = null
    expect(isProductionCandidatesResponse(nullableFilename)).toBe(true)

    const missingLabel = structuredClone(syntheticProductionCandidates())
    missingLabel.source_display_name = ''
    expect(isProductionCandidatesResponse(missingLabel)).toBe(false)
  })

  it('requires the frozen score descriptors instead of inventing an input layer', () => {
    const payload = structuredClone(syntheticProductionCandidates()) as unknown as {
      lineage: {
        score: Record<string, unknown>
      }
    }
    delete payload.lineage.score.input_kind
    payload.lineage.score.input_layer = 'projections'
    payload.lineage.score.output_layer = 'valuation'

    expect(isProductionCandidatesResponse(payload)).toBe(false)
  })

  it.each([
    'scoring_profile_sha256',
    'blend_profile_sha256',
    'blend_result_sha256',
  ] as const)('rejects a valid but contradictory score %s', (field) => {
    const payload = structuredClone(syntheticProductionCandidates())
    payload.lineage.score[field] = '0'.repeat(64)

    expect(isProductionCandidatesResponse(payload)).toBe(false)
  })

  it('rejects a model version outside the one this surface supports', () => {
    const payload = structuredClone(syntheticProductionCandidates())
    const score = payload.lineage.score as unknown as Record<string, unknown>
    score.model_version = 'zscore-production-v2'

    expect(isProductionCandidatesResponse(payload)).toBe(false)
  })

  it('requires the reliability observation publication artifact key', () => {
    const payload = structuredClone(syntheticProductionCandidates())
    const publication = payload.health_context.status === 'available'
      ? payload.health_context.publication as unknown as Record<string, unknown>
      : null
    if (publication === null) throw new Error('Synthetic health context is unavailable.')
    publication.artifact_key = 'synthetic:test-publication'

    expect(isProductionCandidatesResponse(payload)).toBe(false)
  })

  it('rejects a display label in place of the health season-type wire enum', () => {
    const payload = structuredClone(syntheticProductionCandidates())
    const context = payload.health_context as unknown as Record<string, unknown>
    context.season_type = 'Regular Season'

    expect(isProductionCandidatesResponse(payload)).toBe(false)
  })

  it.each(PRODUCTION_SEASON_TYPES)(
    'accepts the OpenAPI health season type %s',
    (seasonType) => {
      const payload = structuredClone(syntheticProductionCandidates())
      if (payload.health_context.status !== 'available') {
        throw new Error('Synthetic health context is unavailable.')
      }
      payload.health_context.season_type = seasonType

      expect(isProductionCandidatesResponse(payload)).toBe(true)
    },
  )

  it('rejects scoring types outside the OpenAPI enum at both lineage boundaries', () => {
    const importPayload = structuredClone(syntheticProductionCandidates())
    const projectionImport = importPayload.lineage
      .projection_import as unknown as Record<string, unknown>
    projectionImport.assumed_scoring_type = 'nine_category'
    expect(isProductionCandidatesResponse(importPayload)).toBe(false)

    const profilePayload = structuredClone(syntheticProductionCandidates())
    const scoringProfile = profilePayload.lineage
      .scoring_profile as unknown as Record<string, unknown>
    scoringProfile.scoring_type = 'nine_category'
    expect(isProductionCandidatesResponse(profilePayload)).toBe(false)
  })

  it.each(PRODUCTION_SCORING_TYPES)(
    'accepts the OpenAPI scoring type %s at both lineage boundaries',
    (scoringType) => {
      const payload = structuredClone(syntheticProductionCandidates())
      payload.lineage.projection_import.assumed_scoring_type = scoringType
      payload.lineage.scoring_profile.scoring_type = scoringType

      expect(isProductionCandidatesResponse(payload)).toBe(true)
    },
  )

  it.each([
    ['h2h_categories', 'h2h_each_category'],
    ['roto', 'points'],
  ] as const)(
    'rejects incompatible valid scoring declarations %s and %s',
    (assumedScoringType, scoringType) => {
      const payload = structuredClone(syntheticProductionCandidates())
      payload.lineage.projection_import.assumed_scoring_type = assumedScoringType
      payload.lineage.scoring_profile.scoring_type = scoringType

      expect(isProductionCandidatesResponse(payload)).toBe(false)
    },
  )

  it('rejects the genuine V2 payload when only its import declaration is changed', () => {
    expect(isProductionCandidatesResponse(recordedResponse)).toBe(true)
    const payload = structuredClone(recordedResponse)
    payload.lineage.projection_import.assumed_scoring_type = 'h2h_categories'

    expect(isProductionCandidatesResponse(payload)).toBe(false)
  })

  it('keeps the projection import scoring declaration nullable', () => {
    const payload = structuredClone(syntheticProductionCandidates())
    payload.lineage.projection_import.assumed_scoring_type = null

    expect(isProductionCandidatesResponse(payload)).toBe(true)
  })

  it('rejects a component array that no longer matches the scale order', () => {
    const payload = structuredClone(syntheticProductionCandidates())
    payload.candidates[0]!.components.reverse()

    expect(isProductionCandidatesResponse(payload)).toBe(false)
  })

  it('rejects a missing scoring input rather than treating it as zero', () => {
    const payload = structuredClone(syntheticProductionCandidates()) as unknown as {
      candidates: { rates_per_game: Record<string, unknown> }[]
    }
    delete payload.candidates[0]!.rates_per_game.free_throws_attempted_per_game

    expect(isProductionCandidatesResponse(payload)).toBe(false)
  })

  it('rejects an unknown health row inside an available observation window', () => {
    const payload = structuredClone(syntheticProductionCandidates())
    payload.candidates[0]!.health = {
      status: 'unknown',
      credited_appearances: null,
    }

    expect(isProductionCandidatesResponse(payload)).toBe(false)
  })

  it('accepts null health counts only when the observation context is unavailable', () => {
    const payload = structuredClone(syntheticProductionCandidates())
    payload.health_context = {
      status: 'unavailable',
      reason: 'no_attributable_publication',
      season: null,
      season_type: null,
      window_start: null,
      as_of_date: null,
      publication: null,
      row_source_provenance: 'not_recorded',
      counting_rule: 'player_game_log_rows_in_window_including_zero_seconds',
      observation_rows_sha256: null,
      ranking_input: false,
    }
    payload.candidates = payload.candidates.map((candidate) => ({
      ...candidate,
      health: { status: 'unknown', credited_appearances: null },
    }))

    expect(isProductionCandidatesResponse(payload)).toBe(true)
  })

  it('rejects a derived-looking budget context that the contract removed', () => {
    const payload = structuredClone(syntheticProductionCandidates()) as unknown as Record<
      string,
      unknown
    >
    payload.budget_context = { assumed_budget: '200.00' }

    expect(isProductionCandidatesResponse(payload)).toBe(false)
  })

  it('requires the two published shortfalls independently', () => {
    const payload = structuredClone(syntheticProductionCandidates())
    payload.replacement.structural_roster_shortfall =
      payload.replacement.replacement_ordinal_shortfall

    expect(isProductionCandidatesResponse(payload)).toBe(false)
  })
})
