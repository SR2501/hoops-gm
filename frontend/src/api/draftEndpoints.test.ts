import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../test/helpers'
import recordedDraft from '../test/fixtures/draft-auction-state.recorded.json'
import recordedFeed from '../test/fixtures/draft-feed-status.recorded.json'
import recordedDraftList from '../test/fixtures/draft-list.recorded.json'
import recordedOpenApi from '../test/fixtures/openapi.recorded.json'
import { ApiError } from './client'
import {
  createDraft,
  getDraft,
  getDraftFeed,
  getDraftSetup,
  getDrafts,
  getSourceBoard,
  isDraftSetupResponse,
  isDraftState,
  isFeedStatusResponse,
  isSourceBoardResponse,
} from './draftEndpoints'
import type {
  CreateDraftRequest,
  DraftSetupResponse,
  FeedStatusResponse,
  SourceBoardResponse,
} from './draftTypes'

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

const setupResponse = {
  leagues: [
    {
      league_id: 3,
      name: 'League setup evidence',
      season: '2026-27',
      format: {
        draft_type: 'auction',
        team_count: 2,
        roster_size: 13,
        total_roster_slots: 26,
        auction_budget: '200.00',
      },
      owner_fantasy_team_id: 31,
      fantasy_teams: [
        { fantasy_team_id: 32, display_name: 'Alpha team' },
        { fantasy_team_id: 31, display_name: 'Owner team' },
      ],
    },
  ],
} satisfies DraftSetupResponse

describe('draft setup endpoint contract', () => {
  it('requests the setup endpoint and accepts the complete persisted evidence shape', async () => {
    const fetchMock = mockFetch({
      '/api/v1/drafts/setup': { body: setupResponse },
    })

    await expect(getDraftSetup()).resolves.toEqual(setupResponse)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/drafts/setup')
  })

  it('matches the exact recorded OpenAPI field sets', () => {
    const schemas = recordedOpenApi.components.schemas

    expect(Object.keys(schemas.DraftSetupResponse.properties)).toEqual(['leagues'])
    expect(Object.keys(schemas.DraftSetupLeagueOut.properties)).toEqual([
      'league_id',
      'name',
      'season',
      'format',
      'owner_fantasy_team_id',
      'fantasy_teams',
    ])
    expect(Object.keys(schemas.DraftSetupTeamOut.properties)).toEqual([
      'fantasy_team_id',
      'display_name',
    ])
  })

  it('rejects added seat evidence instead of silently ignoring it', async () => {
    const malformed = structuredClone(setupResponse) as unknown as {
      leagues: { fantasy_teams: Record<string, unknown>[] }[]
    }
    const firstTeam = malformed.leagues[0]?.fantasy_teams[0]
    if (firstTeam === undefined) throw new Error('fixture needs a fantasy team')
    firstTeam.source_seat = 1

    expect(isDraftSetupResponse(malformed)).toBe(false)
    mockFetch({
      '/api/v1/drafts/setup': {
        body: malformed,
        headers: { 'X-Request-ID': 'req-setup-contract' },
      },
    })

    const error = await getDraftSetup().catch((cause: unknown) => cause)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('invalid_response')
    expect((error as ApiError).requestId).toBe('req-setup-contract')
  })

  it('rejects extra public fields at every setup boundary', () => {
    expect(isDraftSetupResponse({ ...setupResponse, source: 'fantrax' })).toBe(false)

    const leagueExtra = structuredClone(setupResponse) as unknown as {
      leagues: Record<string, unknown>[]
    }
    leagueExtra.leagues[0]!.source = 'fantrax'
    expect(isDraftSetupResponse(leagueExtra)).toBe(false)

    const formatExtra = structuredClone(setupResponse) as unknown as {
      leagues: { format: Record<string, unknown> }[]
    }
    formatExtra.leagues[0]!.format.owner_budget = '200.00'
    expect(isDraftSetupResponse(formatExtra)).toBe(false)
  })

  it('rejects non-record values at every setup boundary', () => {
    expect(isDraftSetupResponse(null)).toBe(false)
    expect(isDraftSetupResponse({ leagues: [null] })).toBe(false)

    const nullFormat = structuredClone(setupResponse) as unknown as {
      leagues: { format: null }[]
    }
    nullFormat.leagues[0]!.format = null
    expect(isDraftSetupResponse(nullFormat)).toBe(false)

    const nullTeam = structuredClone(setupResponse) as unknown as {
      leagues: { fantasy_teams: (DraftSetupResponse['leagues'][number]['fantasy_teams'][number] | null)[] }[]
    }
    nullTeam.leagues[0]!.fantasy_teams[0] = null
    expect(isDraftSetupResponse(nullTeam)).toBe(false)

    const nullTeamArray = structuredClone(setupResponse) as unknown as {
      leagues: { fantasy_teams: null }[]
    }
    nullTeamArray.leagues[0]!.fantasy_teams = null
    expect(isDraftSetupResponse(nullTeamArray)).toBe(false)
  })

  it('rejects malformed identifiers, labels, and format values', () => {
    const badLeagueId = structuredClone(setupResponse)
    badLeagueId.leagues[0]!.league_id = 0
    expect(isDraftSetupResponse(badLeagueId)).toBe(false)

    const fractionalLeagueId = structuredClone(setupResponse)
    fractionalLeagueId.leagues[0]!.league_id = 1.5
    expect(isDraftSetupResponse(fractionalLeagueId)).toBe(false)

    const blankLeagueName = structuredClone(setupResponse)
    blankLeagueName.leagues[0]!.name = ' '
    expect(isDraftSetupResponse(blankLeagueName)).toBe(false)

    const nullLeagueName = structuredClone(setupResponse) as unknown as {
      leagues: { name: null }[]
    }
    nullLeagueName.leagues[0]!.name = null
    expect(isDraftSetupResponse(nullLeagueName)).toBe(false)

    const blankSeason = structuredClone(setupResponse)
    blankSeason.leagues[0]!.season = ' '
    expect(isDraftSetupResponse(blankSeason)).toBe(false)

    const nullSeason = structuredClone(setupResponse) as unknown as {
      leagues: { season: null }[]
    }
    nullSeason.leagues[0]!.season = null
    expect(isDraftSetupResponse(nullSeason)).toBe(false)

    const badTeamId = structuredClone(setupResponse)
    badTeamId.leagues[0]!.fantasy_teams[0]!.fantasy_team_id = 0
    expect(isDraftSetupResponse(badTeamId)).toBe(false)

    const blankTeamName = structuredClone(setupResponse)
    blankTeamName.leagues[0]!.fantasy_teams[0]!.display_name = ' '
    expect(isDraftSetupResponse(blankTeamName)).toBe(false)

    const nullTeamName = structuredClone(setupResponse) as unknown as {
      leagues: { fantasy_teams: { display_name: null }[] }[]
    }
    nullTeamName.leagues[0]!.fantasy_teams[0]!.display_name = null
    expect(isDraftSetupResponse(nullTeamName)).toBe(false)

    const badDraftType = structuredClone(setupResponse) as unknown as {
      leagues: { format: { auction_budget: string | null; draft_type: string } }[]
    }
    badDraftType.leagues[0]!.format.draft_type = 'serpentine'
    badDraftType.leagues[0]!.format.auction_budget = null
    expect(isDraftSetupResponse(badDraftType)).toBe(false)

    const invalidBudget = structuredClone(setupResponse)
    invalidBudget.leagues[0]!.format.auction_budget = 'USD 200'
    expect(isDraftSetupResponse(invalidBudget)).toBe(false)

    const zeroBudget = structuredClone(setupResponse)
    zeroBudget.leagues[0]!.format.auction_budget = '0.00'
    expect(isDraftSetupResponse(zeroBudget)).toBe(false)
  })

  it('rejects contradictory format, team-count, and owner evidence', () => {
    const wrongTotal = structuredClone(setupResponse)
    wrongTotal.leagues[0]!.format.total_roster_slots = 25
    expect(isDraftSetupResponse(wrongTotal)).toBe(false)

    const orderedWithBudget = structuredClone(setupResponse) as unknown as DraftSetupResponse
    orderedWithBudget.leagues[0]!.format.draft_type = 'snake'
    expect(isDraftSetupResponse(orderedWithBudget)).toBe(false)

    const zeroTeamCount = structuredClone(setupResponse) as unknown as DraftSetupResponse
    zeroTeamCount.leagues[0]!.format.team_count = 0
    zeroTeamCount.leagues[0]!.format.total_roster_slots = 0
    zeroTeamCount.leagues[0]!.owner_fantasy_team_id = null
    zeroTeamCount.leagues[0]!.fantasy_teams = []
    expect(isDraftSetupResponse(zeroTeamCount)).toBe(false)

    const zeroRosterSize = structuredClone(setupResponse) as unknown as DraftSetupResponse
    zeroRosterSize.leagues[0]!.format.roster_size = 0
    zeroRosterSize.leagues[0]!.format.total_roster_slots = 0
    expect(isDraftSetupResponse(zeroRosterSize)).toBe(false)

    const missingTeam = structuredClone(setupResponse)
    missingTeam.leagues[0]!.fantasy_teams.shift()
    expect(isDraftSetupResponse(missingTeam)).toBe(false)

    const duplicateTeam = structuredClone(setupResponse)
    duplicateTeam.leagues[0]!.fantasy_teams[0]!.fantasy_team_id =
      duplicateTeam.leagues[0]!.fantasy_teams[1]!.fantasy_team_id
    expect(isDraftSetupResponse(duplicateTeam)).toBe(false)

    const missingOwner = structuredClone(setupResponse)
    missingOwner.leagues[0]!.owner_fantasy_team_id = 999
    expect(isDraftSetupResponse(missingOwner)).toBe(false)

    const duplicateLeague = structuredClone(setupResponse)
    duplicateLeague.leagues.push(structuredClone(duplicateLeague.leagues[0]!))
    expect(isDraftSetupResponse(duplicateLeague)).toBe(false)

    expect(isDraftSetupResponse({ leagues: null })).toBe(false)
  })

  it('posts the complete explicit creation request through the typed client', async () => {
    const body: CreateDraftRequest = {
      league_id: 3,
      name: 'Opening mock',
      is_mock: true,
      tool_usage: 'partial',
      source_board_profile: null,
      notes: 'Recorded without source-seat evidence.',
      participants: [
        {
          team_slot: 1,
          source_seat: null,
          display_name: 'Owner team',
          is_owner: true,
          fantasy_team_id: 31,
        },
        {
          team_slot: 2,
          source_seat: null,
          display_name: 'Alpha team',
          is_owner: false,
          fantasy_team_id: 32,
        },
      ],
    }
    const fetchMock = mockFetch({
      '/api/v1/drafts': { body: recordedDraft },
    })

    await expect(createDraft(body)).resolves.toEqual(recordedDraft)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/drafts')
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify(body),
    })
  })
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

  it.each(['retryable', 'skipped', 'unattributed_skipped'] as const)(
    'rejects an array masquerading as the %s count map',
    (field) => {
      const malformed = structuredClone(feed) as unknown as Record<string, unknown>
      malformed[field] = []
      expect(isFeedStatusResponse(malformed)).toBe(false)
    },
  )

  it('rejects an array masquerading as participant reason counts', () => {
    const malformed = structuredClone(feed) as unknown as Record<string, unknown>
    const rows = malformed.skipped_by_participant as Record<string, unknown>[]
    const first = rows[0]
    if (first === undefined) throw new Error('recorded feed needs one participant')
    first.reasons = []
    expect(isFeedStatusResponse(malformed)).toBe(false)
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
