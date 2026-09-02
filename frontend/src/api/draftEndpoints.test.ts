import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../test/helpers'
import recordedDraft from '../test/fixtures/draft-auction-state.recorded.json'
import recordedFeed from '../test/fixtures/draft-feed-status.recorded.json'
import recordedDraftList from '../test/fixtures/draft-list.recorded.json'
import { ApiError } from './client'
import {
  getDraft,
  getDraftFeed,
  getDrafts,
  getSourceBoard,
  isDraftState,
  isFeedStatusResponse,
  isSourceBoardResponse,
} from './draftEndpoints'
import type { FeedStatusResponse, SourceBoardResponse } from './draftTypes'

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

describe('draft additive contract', () => {
  it('accepts the current recorded draft state', () => {
    expect(isDraftState(recordedDraft)).toBe(true)
  })

  it.each([
    ['missing source_seat', (body: Record<string, unknown>) => {
      const participants = body.participants as Record<string, unknown>[]
      Reflect.deleteProperty(participants[0] ?? {}, 'source_seat')
    }],
    ['wrong source_seat', (body: Record<string, unknown>) => {
      const participants = body.participants as Record<string, unknown>[]
      if (participants[0] !== undefined) participants[0].source_seat = '1'
    }],
    ['missing source_board_profile', (body: Record<string, unknown>) => {
      Reflect.deleteProperty(body, 'source_board_profile')
    }],
    ['unknown source_board_profile', (body: Record<string, unknown>) => {
      body.source_board_profile = 'fantrax_any_board'
    }],
  ])('rejects a draft with %s', async (_label, mutate) => {
    const malformed = structuredClone(recordedDraft) as unknown as Record<string, unknown>
    mutate(malformed)
    expect(isDraftState(malformed)).toBe(false)

    mockFetch({
      '/api/v1/drafts/1': {
        body: malformed,
        headers: { 'X-Request-ID': 'req-draft-contract' },
      },
    })
    const error = await getDraft(1).catch((cause: unknown) => cause)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('invalid_response')
  })

  it('rejects a draft-list summary without the source-board profile', async () => {
    const malformed = structuredClone(recordedDraftList) as unknown as {
      drafts: Record<string, unknown>[]
    }
    Reflect.deleteProperty(malformed.drafts[0] ?? {}, 'source_board_profile')
    mockFetch({ '/api/v1/drafts': { body: malformed } })

    const error = await getDrafts().catch((cause: unknown) => cause)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('invalid_response')
  })
})

describe('draft feed endpoint contract', () => {
  const feed = recordedFeed as unknown as FeedStatusResponse

  it('requests the feed endpoint and accepts the complete recorded shape', async () => {
    const fetchMock = mockFetch({
      '/api/v1/drafts/1/feed': { body: recordedFeed },
    })

    await expect(getDraftFeed(1)).resolves.toEqual(recordedFeed)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/drafts/1/feed')
    expect(isFeedStatusResponse(recordedFeed)).toBe(true)
  })

  it.each([
    ['skipped_by_participant', (body: Record<string, unknown>) => {
      Reflect.deleteProperty(body, 'skipped_by_participant')
    }],
    ['unattributed_skipped', (body: Record<string, unknown>) => {
      Reflect.deleteProperty(body, 'unattributed_skipped')
    }],
    ['retryable', (body: Record<string, unknown>) => {
      Reflect.deleteProperty(body, 'retryable')
    }],
    ['board_regressions', (body: Record<string, unknown>) => {
      Reflect.deleteProperty(body, 'board_regressions')
    }],
  ])('rejects an absent %s field', (_field, mutate) => {
    const malformed = structuredClone(feed) as unknown as Record<string, unknown>
    mutate(malformed)
    expect(isFeedStatusResponse(malformed)).toBe(false)
  })

  it('rejects wrong skip-detail types and totals', () => {
    const wrongReasons = structuredClone(feed)
    const first = wrongReasons.skipped_by_participant[0]
    if (first === undefined) throw new Error('recorded feed needs one participant')
    first.reasons = { unreadable: -1 }
    first.total = -1
    expect(isFeedStatusResponse(wrongReasons)).toBe(false)

    const wrongTotal = structuredClone(feed)
    const row = wrongTotal.skipped_by_participant[0]
    if (row === undefined) throw new Error('recorded feed needs one participant')
    row.total = 1
    expect(isFeedStatusResponse(wrongTotal)).toBe(false)

    const wrongUnattributed = structuredClone(feed)
    wrongUnattributed.unattributed_skipped = { unknown: 1.5 }
    expect(isFeedStatusResponse(wrongUnattributed)).toBe(false)
  })

  it('rejects a skip partition that does not reproduce the aggregate', () => {
    const malformed = structuredClone(feed)
    malformed.skipped = { reason_not_in_partition: 1 }
    expect(isFeedStatusResponse(malformed)).toBe(false)
  })

  it('rejects extra participant detail keys rather than depending on permissive parsing', () => {
    const malformed = structuredClone(feed) as unknown as Record<string, unknown>
    const rows = malformed.skipped_by_participant as Record<string, unknown>[]
    const first = rows[0]
    if (first === undefined) throw new Error('recorded feed needs one participant')
    first.mutable_label = 'not identity'
    expect(isFeedStatusResponse(malformed)).toBe(false)
  })

  it('surfaces malformed feed payloads as invalid responses', async () => {
    const malformed = structuredClone(feed) as unknown as Record<string, unknown>
    Reflect.deleteProperty(malformed, 'unattributed_skipped')
    mockFetch({
      '/api/v1/drafts/1/feed': {
        body: malformed,
        headers: { 'X-Request-ID': 'req-feed-contract' },
      },
    })

    const error = await getDraftFeed(1).catch((cause: unknown) => cause)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('invalid_response')
    expect((error as ApiError).requestId).toBe('req-feed-contract')
    expect((error as ApiError).message).toContain('draft feed response')
  })
})
