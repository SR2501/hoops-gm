import { describe, expect, it } from 'vitest'
import { isReliabilityScorecardsResponse } from '../api/reliabilityEndpoints'
import type { ReliabilityScorecardsResponse } from '../api/reliabilityTypes'
import recorded from '../test/fixtures/reliability-scorecards.recorded.json'
import {
  buildReliabilityRows,
  filterReliabilityRows,
  formatNumber,
  formatRate,
} from './reliabilityScorecardsModel'

function payload(): ReliabilityScorecardsResponse {
  if (!isReliabilityScorecardsResponse(recorded)) throw new Error('Invalid recorded fixture.')
  return structuredClone(recorded)
}

describe('reliability scorecard model', () => {
  it('sorts named players before a truthfully labelled missing name', () => {
    const body = payload()
    const missing = structuredClone(body.scorecards[0]!)
    missing.player_id = 99
    missing.player_name = null
    body.scorecards.push(missing)
    body.counts.scorecards += 1

    const rows = buildReliabilityRows(body)

    expect(rows.at(-1)?.displayName).toBe('Name unavailable · player 99')
  })

  it('filters direct non-play evidence independently from no B2B evidence', () => {
    const body = payload()
    body.scorecards[0]!.availability.back_to_back = {
      direct_play: 0,
      direct_non_play: 0,
      explicit_unknown: 0,
      observed_opportunities: 0,
      observed_play_rate: null,
      observed_non_play_rate: null,
      coverage_status: 'incomplete_r35',
      opportunity_coverage: null,
    }
    body.scorecards[1]!.availability.back_to_back = {
      direct_play: 0,
      direct_non_play: 0,
      explicit_unknown: 1,
      observed_opportunities: 0,
      observed_play_rate: null,
      observed_non_play_rate: null,
      coverage_status: 'incomplete_r35',
      opportunity_coverage: null,
    }
    const rows = buildReliabilityRows(body)

    expect(filterReliabilityRows(rows, '', 'non_play').map((row) => row.displayName))
      .toEqual(['Glass Cannon'])
    expect(filterReliabilityRows(rows, '', 'no_b2b').map((row) => row.displayName))
      .toEqual(['Iron Man'])
  })

  it('searches case-insensitively by name or canonical player id', () => {
    const rows = buildReliabilityRows(payload())

    expect(filterReliabilityRows(rows, 'gLaSs', 'all')).toHaveLength(1)
    expect(filterReliabilityRows(rows, '2', 'all')[0]?.displayName).toBe('Glass Cannon')
  })

  it('never turns an unavailable rate or metric into zero', () => {
    expect(formatRate(null)).toBe('Unavailable')
    expect(formatNumber(null)).toBe('Unavailable')
    expect(formatRate(0)).toBe('0.0%')
  })
})
