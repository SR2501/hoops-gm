import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../test/helpers'
import { ApiError } from './client'
import { getSourceBoard, isSourceBoardResponse } from './draftEndpoints'
import type { SourceBoardResponse } from './draftTypes'

const available: SourceBoardResponse = {
  draft_id: 7,
  as_of: '2026-08-29T18:00:30Z',
  status: 'available',
  refusal_reason: null,
  contact_at: '2026-08-29T18:00:29Z',
  contact_age_seconds: 1,
  board_age_seconds: 30,
  board: {
    artifact_key: 'board:abc',
    recogniser: 'board_dom',
    observed_at: '2026-08-29T18:00:00Z',
    layout: 'snake',
    seat_count: 2,
    round_count: 2,
    picks_made: 2,
    columns: [
      {
        source_seat: 1,
        mutable_label: 'Displayed name',
        picks: [
          {
            source_seat: 1,
            round_number: 1,
            pick_in_round: 1,
            overall_pick: 1,
            player_label: 'Player One',
            player_external_id: 'fantrax-1',
          },
        ],
      },
      {
        source_seat: 2,
        mutable_label: null,
        picks: [
          {
            source_seat: 2,
            round_number: 1,
            pick_in_round: 2,
            overall_pick: 2,
            player_label: null,
            player_external_id: null,
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
      player_label: 'Player Lost',
      last_seen_artifact_key: 'board:before',
    },
  ],
  caveats: [
    'source_seat is a rendered column ordinal, not DraftParticipant.team_slot or identity',
    'seat labels are mutable display evidence and are never matched to participants',
    'an exact-content undo reuses an existing artifact key and cannot appear as a new regression',
    'evidence is from one football snake draft; NBA and auction board support is unestablished',
  ],
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('source-board endpoint contract', () => {
  it('requests the dedicated read endpoint and accepts the complete available shape', async () => {
    const fetchMock = mockFetch({
      '/api/v1/drafts/7/source-board': { body: available },
    })

    await expect(getSourceBoard(7)).resolves.toEqual(available)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/drafts/7/source-board')
  })

  it.each([
    {
      ...available,
      status: 'no_reading',
      contact_at: null,
      contact_age_seconds: null,
      board: null,
      board_age_seconds: null,
      regressions: [],
    },
    {
      ...available,
      status: 'refused',
      refusal_reason: 'board_refused:snapshot_truncated',
      board: null,
      board_age_seconds: null,
    },
  ] satisfies SourceBoardResponse[])('accepts the explicit $status state', (body) => {
    expect(isSourceBoardResponse(body)).toBe(true)
  })

  it('rejects a malformed nested pick instead of treating it as an empty board', async () => {
    const malformed = structuredClone(available)
    Reflect.deleteProperty(malformed.board?.columns[0]?.picks[0] ?? {}, 'source_seat')
    mockFetch({
      '/api/v1/drafts/7/source-board': {
        body: malformed,
        headers: { 'X-Request-ID': 'req-source-contract' },
      },
    })

    const error = await getSourceBoard(7).catch((cause: unknown) => cause)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('invalid_response')
    expect((error as ApiError).requestId).toBe('req-source-contract')
    expect((error as ApiError).message).toContain('source-board response')
  })

  it('rejects a status outside the backend vocabulary', () => {
    expect(isSourceBoardResponse({ ...available, status: 'empty' })).toBe(false)
  })
})
