import { describe, expect, it } from 'vitest'
import type { SourceBoardResponse } from '../api/draftTypes'
import { buildSourceBoardEvidenceModel, describeSourceAge } from './sourceBoardModel'

function response(status: SourceBoardResponse['status']): SourceBoardResponse {
  return {
    draft_id: 4,
    as_of: '2026-08-29T18:02:05Z',
    status,
    refusal_reason: status === 'refused' ? 'board_refused:snapshot_truncated' : null,
    contact_at: status === 'no_reading' ? null : '2026-08-29T18:02:00Z',
    contact_age_seconds: status === 'no_reading' ? null : 5.9,
    board_age_seconds: status === 'no_reading' ? null : 125,
    board:
      status === 'no_reading'
        ? null
        : {
            artifact_key: 'board:current',
            recogniser: 'board_dom',
            observed_at: '2026-08-29T18:00:00Z',
            layout: 'snake',
            seat_count: 2,
            round_count: 2,
            picks_made: 2,
            columns: [
              {
                source_seat: 2,
                mutable_label: 'Renamed source label',
                picks: [
                  {
                    source_seat: 2,
                    round_number: 2,
                    pick_in_round: 1,
                    overall_pick: 4,
                    player_label: 'Second',
                    player_external_id: null,
                  },
                ],
              },
              {
                source_seat: 1,
                mutable_label: 'First source label',
                picks: [
                  {
                    source_seat: 1,
                    round_number: 1,
                    pick_in_round: 1,
                    overall_pick: 1,
                    player_label: 'First',
                    player_external_id: 'fantrax-1',
                  },
                ],
              },
            ],
          },
    regressions: [
      {
        source_seat: 2,
        round_number: 2,
        pick_in_round: 1,
        player_label: 'Lost second',
        last_seen_artifact_key: 'board:before',
      },
      {
        source_seat: 1,
        round_number: 2,
        pick_in_round: 2,
        player_label: 'Lost first',
        last_seen_artifact_key: 'board:before',
      },
    ],
    caveats: ['exact-content undo cannot appear as a new regression'],
  }
}

describe('source-board evidence model', () => {
  it('keeps source columns and mutable labels separate from participant coordinates', () => {
    const model = buildSourceBoardEvidenceModel(response('available'))

    expect(model.columns.map((column) => column.sourceSeat)).toEqual([1, 2])
    expect(model.columns.map((column) => column.mutableLabel)).toEqual([
      'First source label',
      'Renamed source label',
    ])
    expect(model.columns[0]).not.toHaveProperty('teamSlot')
    expect(model.columns[0]).not.toHaveProperty('participant')
  })

  it('retains refusal, previous board, and regressions as simultaneous evidence', () => {
    const model = buildSourceBoardEvidenceModel(response('refused'))

    expect(model.response.status).toBe('refused')
    expect(model.response.refusal_reason).toBe('board_refused:snapshot_truncated')
    expect(model.board?.picks_made).toBe(2)
    expect(model.regressions.map((item) => item.player_label)).toEqual([
      'Lost first',
      'Lost second',
    ])
  })

  it('does not turn no-reading into an empty available board', () => {
    const model = buildSourceBoardEvidenceModel(response('no_reading'))

    expect(model.response.status).toBe('no_reading')
    expect(model.board).toBeNull()
    expect(model.columns).toEqual([])
    expect(model.boardAge).toBeNull()
    expect(model.contactAge).toBeNull()
  })
})

describe('source freshness wording', () => {
  it.each([
    [null, null],
    [0.5, 'less than 1 second'],
    [5.9, '5 seconds'],
    [60, '1 minute'],
    [125, '2m 5s'],
    [3600, '1 hour'],
    [3720, '1h 2m'],
  ])('describes %s server seconds as %s', (seconds, expected) => {
    expect(describeSourceAge(seconds)).toBe(expected)
  })
})
