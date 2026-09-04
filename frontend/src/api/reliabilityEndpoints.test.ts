import { afterEach, describe, expect, it } from 'vitest'
import { ApiError } from './client'
import {
  getReliabilityScorecards,
  isReliabilityScorecardsResponse,
} from './reliabilityEndpoints'
import recorded from '../test/fixtures/reliability-scorecards.recorded.json'
import { mockFetch, requestUrl } from '../test/helpers'

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null) throw new Error('Expected object.')
  return value as Record<string, unknown>
}

function firstScorecard(body: unknown): Record<string, unknown> {
  const scorecards = record(body).scorecards
  if (!Array.isArray(scorecards) || scorecards.length === 0) {
    throw new Error('Expected at least one scorecard.')
  }
  return record(scorecards[0])
}

function overallEvidence(body: unknown): Record<string, unknown> {
  return record(record(firstScorecard(body).availability).overall)
}

function monthlyEvidence(body: unknown): unknown[] {
  const months = record(firstScorecard(body).availability).monthly_trend
  if (!Array.isArray(months)) throw new Error('Expected monthly evidence.')
  return months
}

function lineage(body: unknown): Record<string, unknown> {
  return record(record(body).lineage)
}

function firstRatioCategory(body: unknown): Record<string, unknown> {
  const categories = record(firstScorecard(body).production).categories
  if (!Array.isArray(categories)) throw new Error('Expected categories.')
  const ratio = categories.find((category) => record(category).unit === 'volume_weighted_impact')
  if (!ratio) throw new Error('Expected a ratio category.')
  return record(ratio)
}

function categories(body: unknown): unknown[] {
  const value = record(firstScorecard(body).production).categories
  if (!Array.isArray(value)) throw new Error('Expected categories.')
  return value
}

function firstCountCategory(body: unknown): Record<string, unknown> {
  const count = categories(body).find((category) => record(category).unit === 'count')
  if (!count) throw new Error('Expected a count category.')
  return record(count)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('reliability endpoint contract', () => {
  it('accepts the response recorded through the production route', () => {
    expect(isReliabilityScorecardsResponse(recorded)).toBe(true)
  })

  it('requests the one read-only reliability endpoint', async () => {
    const fetchMock = mockFetch({ '/api/v1/reliability/scorecards': { body: recorded } })

    await getReliabilityScorecards()

    expect(fetchMock).toHaveBeenCalledOnce()
    expect(requestUrl(fetchMock.mock.calls[0]![0])).toContain('/api/v1/reliability/scorecards')
  })

  it.each<[string, (body: unknown) => void]>([
    ['unknown opportunity coverage', (body) => {
      overallEvidence(body).opportunity_coverage = 0.5
    }],
    ['contradictory direct denominator', (body) => {
      overallEvidence(body).observed_opportunities = 999
    }],
    ['duplicate calendar month represented by a different date', (body) => {
      const months = monthlyEvidence(body)
      const duplicate = record(structuredClone(months[0]))
      duplicate.month = '2026-01-15'
      months.push(duplicate)
    }],
    ['out-of-order monthly evidence', (body) => {
      const months = monthlyEvidence(body)
      const earlier = record(structuredClone(months[0]))
      earlier.month = '2025-12-01'
      months.push(earlier)
    }],
    ['raw percentage unit', (body) => {
      firstRatioCategory(body).unit = 'percentage'
    }],
    ['percentage impact without its baseline', (body) => {
      firstRatioCategory(body).ratio_baseline = null
    }],
    ['percentage category labelled as a count', (body) => {
      firstRatioCategory(body).unit = 'count'
      firstRatioCategory(body).ratio_baseline = null
    }],
    ['counting category labelled as percentage impact', (body) => {
      firstCountCategory(body).unit = 'volume_weighted_impact'
      firstCountCategory(body).ratio_baseline = firstRatioCategory(body).ratio_baseline
    }],
    ['unknown category', (body) => {
      firstCountCategory(body).category = 'mystery'
    }],
    ['missing category', (body) => {
      categories(body).pop()
    }],
    ['missing schedule source', (body) => {
      delete lineage(body).schedule_source
    }],
    ['missing observation source', (body) => {
      delete lineage(body).observation_source
    }],
    ['missing derivation source', (body) => {
      delete lineage(body).derivation_source
    }],
  ])('rejects %s', async (_name, mutate) => {
    const body: unknown = structuredClone(recorded)
    mutate(body)
    mockFetch({ '/api/v1/reliability/scorecards': { body } })

    const error = await getReliabilityScorecards().catch((cause: unknown) => cause)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ code: 'invalid_response' })
  })
})
