/**
 * The category page as a page: route wiring, two requests, and the paths where
 * one of them fails.
 *
 * `CategoriesPage.recorded.test.tsx` proves the join and the arithmetic against
 * recorded payloads. This proves the composition around them — that the route
 * exists, that the league is taken from the draft rather than a constant, and
 * that a missing projection cohort degrades to a partial screen instead of a
 * blank one. Those are the failures a reader meets first and a fixture cannot
 * show, because a fixture is by definition a request that worked.
 */

import { act, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import type { DraftState, FeedStatusResponse } from '../api/draftTypes'
import { mockFetch, requestUrl } from '../test/helpers'
import recordedDraft from '../test/fixtures/draft-auction-resolved-state.recorded.json'
import recordedFeed from '../test/fixtures/draft-feed-status.recorded.json'
import recordedProjections from '../test/fixtures/projections-current.recorded.json'

/**
 * Ten seconds. Every wait below is a `waitFor` against a stubbed `fetch` that
 * resolves immediately, so this is a ceiling on a hang rather than a budget.
 * Named because `vitest-explicit-timeout` asks for it rather than for the
 * default to be inherited silently.
 */
const TIMEOUT_MS = 10_000

const HEALTH = { status: 'ok', service: 'hoops-gm', version: '0.1.0', environment: 'development' }

const draft = recordedDraft as unknown as DraftState

function feedFor(
  state: DraftState,
  overrides: Partial<FeedStatusResponse> = {},
): FeedStatusResponse {
  return {
    ...(recordedFeed as unknown as FeedStatusResponse),
    draft_id: state.id,
    context_unavailable: null,
    observation_count: 1,
    last_sequence: state.last_sequence,
    skipped_by_participant: state.participants.map((participant) => ({
      participant_id: participant.id,
      team_slot: participant.team_slot,
      total: 0,
      reasons: {},
    })),
    ...overrides,
  }
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function renderAt(route: string) {
  return render(<MemoryRouter initialEntries={[route]}>{<App />}</MemoryRouter>)
}

describe('the league category route', () => {
  it(
    'is reachable at /draft/:id/categories and draws the table',
    async () => {
      mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/feed': { body: feedFor(draft) },
        '/api/v1/drafts/4': { body: draft },
        '/projections/current': { body: recordedProjections },
      })

      renderAt('/draft/4/categories')

      expect(await screen.findByTestId('league-category-table', {}, { timeout: 5000 })).toBeInTheDocument()
      expect(screen.getByTestId('category-join')).toHaveTextContent(
        '48 of 48 selections joined to a projection row',
      )
      expect(screen.getByTestId('owner-standing')).toHaveTextContent('Bench Mob')
    },
    TIMEOUT_MS,
  )

  it(
    "asks for the draft's own league, not the constant the other screens hardcode",
    async () => {
      // The seeded demo puts its drafts in leagues 2 and 3 while the projection
      // and schedule screens are league 1. A hardcoded `LEAGUE_ID = 1` here
      // would join a league-2 draft against a league-1 cohort and rank seats on
      // another league's players, with nothing on screen looking wrong.
      const fetchMock = mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/feed': { body: feedFor(draft) },
        '/api/v1/drafts/4': { body: draft },
        '/projections/current': { body: recordedProjections },
      })

      renderAt('/draft/4/categories')
      await screen.findByTestId('league-category-table', {}, { timeout: 5000 })

      expect(draft.league_id).toBe(2)
      const requested = fetchMock.mock.calls.map(([input]) => requestUrl(input))
      expect(requested).toContain('/api/v1/leagues/2/projections/current')
      expect(requested).not.toContain('/api/v1/leagues/1/projections/current')
    },
    TIMEOUT_MS,
  )

  it(
    'still draws the seats when the projection cohort cannot be read',
    async () => {
      mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/feed': { body: feedFor(draft) },
        '/api/v1/drafts/4': { body: draft },
        '/projections/current': {
          status: 409,
          body: {
            error: 'projections_source_not_imported',
            detail: 'no basketball_monster import for 2026-27',
            request_id: 'req-no-cohort',
          },
        },
      })

      renderAt('/draft/4/categories')

      const banner = await screen.findByTestId('category-no-cohort', {}, { timeout: 5000 })
      expect(banner).toHaveTextContent('No projection cohort could be read for league 2')
      // The seats are recorded facts and are still true, so they are still drawn.
      const table = await screen.findByTestId('league-category-table')
      expect(table.querySelectorAll('td[data-rank]')).toHaveLength(0)
      expect(screen.getByTestId('category-seat-1')).toHaveTextContent('Bench Mob')
    },
    TIMEOUT_MS,
  )

  it(
    'says nothing joined, and why, when every holding is unresolved',
    async () => {
      // The seeded demo's own state: the draft seeder invents player names, the
      // identity crosswalk matches none of them, and every holding carries
      // `player_id: null`. This is what a first-time reader sees.
      const unresolved = {
        ...draft,
        participants: draft.participants.map((seat) => ({
          ...seat,
          holdings: seat.holdings.map((held) => ({ ...held, player_id: null })),
        })),
        unresolved_player_count: 48,
      }

      mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/feed': { body: feedFor(unresolved) },
        '/api/v1/drafts/4': { body: unresolved },
        '/projections/current': { body: recordedProjections },
      })

      renderAt('/draft/4/categories')

      const banner = await screen.findByTestId('category-nothing-joined', {}, { timeout: 5000 })
      expect(banner).toHaveTextContent('None of the 48 recorded selections')
      expect(banner).toHaveTextContent('carry no player id')
      expect(banner).toHaveTextContent('Nothing here is matched by name')
      // The one thing that must not happen: a name-matched join. The cohort
      // carries every one of these labels.
      expect(screen.getByTestId('league-category-table').querySelectorAll('td[data-rank]'))
        .toHaveLength(0)
    },
    TIMEOUT_MS,
  )

  it(
    'does not say "ranked 1-to-0" when nothing can be ranked',
    async () => {
      // Found by opening the page rather than by a test: the lede interpolated
      // `rankedSeatCount` into a range, and the demo's board makes that zero.
      const empty = {
        ...draft,
        participants: draft.participants.map((seat) => ({ ...seat, holdings: [] })),
        selections_made: 0,
      }

      mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/feed': { body: feedFor(empty) },
        '/api/v1/drafts/4': { body: empty },
        '/projections/current': { body: recordedProjections },
      })

      renderAt('/draft/4/categories')

      await screen.findByTestId('category-no-holdings', {}, { timeout: 5000 })
      expect(document.body.textContent).not.toContain('1-to-0')
      expect(document.body.textContent).toContain('No seat could be ranked in any category')
    },
    TIMEOUT_MS,
  )

  it(
    'refuses a draft id that is not one, rather than requesting it',
    async () => {
      const fetchMock = mockFetch({ '/health': { body: HEALTH } })

      renderAt('/draft/not-a-number/categories')

      expect(await screen.findByRole('alert')).toHaveTextContent('is not a draft id')
      await waitFor(() => {
        expect(
          fetchMock.mock.calls.map(([input]) => requestUrl(input)).filter((url) => url.includes('/drafts/')),
        ).toEqual([])
      })
    },
    TIMEOUT_MS,
  )

  it(
    'is linked from the draft board, so it is findable without knowing the url',
    async () => {
      mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/events': { body: { draft_id: 4, events: [], since_sequence: 0, last_sequence: draft.last_sequence } },
        '/api/v1/drafts/4': { body: draft },
      })

      renderAt('/draft/4')

      const link = await screen.findByTestId('draft-categories-link', {}, { timeout: 5000 })
      expect(link).toHaveAttribute('href', '/draft/4/categories')
    },
    TIMEOUT_MS,
  )

  it(
    'maps shuffled permanent skips by participant id and does not use source seat',
    async () => {
      const first = draft.participants[0]
      const second = draft.participants[1]
      if (first === undefined || second === undefined) throw new Error('recorded draft needs two seats')
      const state = {
        ...draft,
        participants: draft.participants.map((participant, index) => ({
          ...participant,
          source_seat: index === 0 ? 12 : index === 11 ? 1 : participant.team_slot,
        })),
      }
      const details = feedFor(state).skipped_by_participant
        .map((entry) =>
          entry.participant_id === second.id
            ? {
                ...entry,
                total: 2,
                reasons: { record_names_no_player: 1, player_external_id_unreadable: 1 },
              }
            : entry,
        )
        .reverse()
      const feed = feedFor(state, {
        skipped: { record_names_no_player: 1, player_external_id_unreadable: 1 },
        skipped_by_participant: details,
      })

      mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/feed': { body: feed },
        '/api/v1/drafts/4': { body: state },
        '/projections/current': { body: recordedProjections },
      })

      renderAt('/draft/4/categories')

      const firstRow = await screen.findByTestId('category-seat-1', {}, { timeout: 5000 })
      const secondRow = screen.getByTestId('category-seat-2')
      expect(within(firstRow).getByTestId(`category-feed-skips-${String(first.id)}`)).toHaveTextContent(
        '0',
      )
      const skipped = within(secondRow).getByTestId(
        `category-feed-skips-${String(second.id)}`,
      )
      expect(skipped).toHaveTextContent('2')
      expect(skipped).toHaveTextContent('roster may be incomplete')
      expect(skipped).toHaveTextContent('record_names_no_player × 1')
      expect(skipped).toHaveTextContent('player_external_id_unreadable × 1')
    },
    TIMEOUT_MS,
  )

  it(
    'warns separately about unattributed skips without adding them to a seat',
    async () => {
      const feed = feedFor(draft, {
        skipped: { no_seat_for_team_external_id: 2 },
        unattributed_skipped: { no_seat_for_team_external_id: 2 },
      })
      mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/feed': { body: feed },
        '/api/v1/drafts/4': { body: draft },
        '/projections/current': { body: recordedProjections },
      })

      renderAt('/draft/4/categories')

      const warning = await screen.findByTestId(
        'category-feed-unattributed',
        {},
        { timeout: 5000 },
      )
      expect(warning).toHaveTextContent('Actual holdings may be missing')
      expect(warning).toHaveTextContent('no_seat_for_team_external_id × 2')
      expect(warning).toHaveTextContent('0 participant-attributed skips')
      for (const participant of draft.participants) {
        expect(
          screen.getByTestId(`category-feed-skips-${String(participant.id)}`),
        ).toHaveTextContent('0')
      }
    },
    TIMEOUT_MS,
  )

  it(
    'renders valid per-seat zeroes while distinguishing a feed with no observations',
    async () => {
      mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/feed': { body: feedFor(draft, { observation_count: 0 }) },
        '/api/v1/drafts/4': { body: draft },
        '/projections/current': { body: recordedProjections },
      })

      renderAt('/draft/4/categories')

      expect(
        await screen.findByTestId('category-feed-empty', {}, { timeout: 5000 }),
      ).toHaveTextContent('contains no observations')
      for (const participant of draft.participants) {
        expect(
          screen.getByTestId(`category-feed-skips-${String(participant.id)}`),
        ).toHaveTextContent('0')
      }
    },
    TIMEOUT_MS,
  )

  it(
    'keeps rankings visible and marks completeness unknown when feed status fails',
    async () => {
      mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/feed': {
          status: 500,
          body: { error: 'feed_failed', detail: 'feed unavailable', request_id: 'req-feed' },
        },
        '/api/v1/drafts/4': { body: draft },
        '/projections/current': { body: recordedProjections },
      })

      renderAt('/draft/4/categories')

      expect(
        await screen.findByTestId('category-feed-unknown', {}, { timeout: 5000 }),
      ).toHaveTextContent('Board completeness is unknown')
      expect(screen.getByTestId('league-category-table').querySelectorAll('td[data-rank]').length)
        .toBeGreaterThan(0)
      expect(screen.getByTestId(`category-feed-skips-${String(draft.participants[0]?.id)}`))
        .toHaveTextContent('unknown')
      expect(screen.queryByTestId('category-no-cohort')).not.toBeInTheDocument()
    },
    TIMEOUT_MS,
  )

  it(
    'keeps rankings visible and marks completeness unknown on a feed contract failure',
    async () => {
      const malformed = structuredClone(feedFor(draft)) as unknown as Record<string, unknown>
      Reflect.deleteProperty(malformed, 'skipped_by_participant')
      mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/feed': { body: malformed },
        '/api/v1/drafts/4': { body: draft },
        '/projections/current': { body: recordedProjections },
      })

      renderAt('/draft/4/categories')

      expect(
        await screen.findByTestId('category-feed-unknown', {}, { timeout: 5000 }),
      ).toHaveTextContent('Board completeness is unknown')
      expect(screen.getByTestId('league-category-table').querySelectorAll('td[data-rank]').length)
        .toBeGreaterThan(0)
    },
    TIMEOUT_MS,
  )

  it(
    'keeps feed diagnostics visible when projections fail independently',
    async () => {
      const first = draft.participants[0]
      if (first === undefined) throw new Error('recorded draft needs one seat')
      const details = feedFor(draft).skipped_by_participant.map((entry) =>
        entry.participant_id === first.id
          ? { ...entry, total: 1, reasons: { record_names_no_player: 1 } }
          : entry,
      )
      mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/feed': {
          body: feedFor(draft, {
            skipped: { record_names_no_player: 1 },
            skipped_by_participant: details,
          }),
        },
        '/api/v1/drafts/4': { body: draft },
        '/projections/current': {
          status: 409,
          body: {
            error: 'projections_source_not_imported',
            detail: 'no cohort',
            request_id: 'req-projection',
          },
        },
      })

      renderAt('/draft/4/categories')

      await screen.findByTestId('category-no-cohort', {}, { timeout: 5000 })
      expect(screen.getByTestId(`category-feed-skips-${String(first.id)}`)).toHaveTextContent(
        '1roster may be incomplete',
      )
      expect(screen.queryByTestId('category-feed-unknown')).not.toBeInTheDocument()
    },
    TIMEOUT_MS,
  )

  it(
    'refuses mismatched participant metadata instead of assigning any count',
    async () => {
      const first = draft.participants[0]
      if (first === undefined) throw new Error('recorded draft needs one seat')
      const details = feedFor(draft).skipped_by_participant.map((entry) =>
        entry.participant_id === first.id ? { ...entry, team_slot: 999 } : entry,
      )
      mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/feed': {
          body: feedFor(draft, { skipped_by_participant: details }),
        },
        '/api/v1/drafts/4': { body: draft },
        '/projections/current': { body: recordedProjections },
      })

      renderAt('/draft/4/categories')

      expect(
        await screen.findByTestId('category-feed-mismatch', {}, { timeout: 5000 }),
      ).toHaveTextContent('No skip count was assigned to any seat')
      expect(screen.getByTestId(`category-feed-skips-${String(first.id)}`)).toHaveTextContent(
        'unknown',
      )
    },
    TIMEOUT_MS,
  )

  it(
    'does not call a context-free feed complete merely because the request answered',
    async () => {
      mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/feed': {
          body: feedFor(draft, { context_unavailable: 'league_not_linked' }),
        },
        '/api/v1/drafts/4': { body: draft },
        '/projections/current': { body: recordedProjections },
      })

      renderAt('/draft/4/categories')

      expect(
        await screen.findByTestId('category-feed-no-context', {}, { timeout: 5000 }),
      ).toHaveTextContent('does not establish that the recorded holdings are complete')
      expect(
        screen.getByTestId(`category-feed-skips-${String(draft.participants[0]?.id)}`),
      ).toHaveTextContent('unknown')
    },
    TIMEOUT_MS,
  )

  it(
    'requests feed status on each poll cycle',
    async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      const fetchMock = mockFetch({
        '/health': { body: HEALTH },
        '/api/v1/drafts/4/feed': { body: feedFor(draft) },
        '/api/v1/drafts/4': { body: draft },
        '/projections/current': { body: recordedProjections },
      })

      renderAt('/draft/4/categories')
      await screen.findByTestId('league-category-table', {}, { timeout: 5000 })
      expect(
        fetchMock.mock.calls
          .map(([input]) => requestUrl(input))
          .filter((url) => url.includes('/api/v1/drafts/4/feed')),
      ).toHaveLength(1)

      await act(async () => {
        await vi.advanceTimersByTimeAsync(6000)
      })
      await waitFor(() => {
        expect(
          fetchMock.mock.calls
            .map(([input]) => requestUrl(input))
            .filter((url) => url.includes('/api/v1/drafts/4/feed')),
        ).toHaveLength(2)
      })
    },
    TIMEOUT_MS,
  )

  it(
    'aborts in-flight feed and projection reads on unmount',
    async () => {
      const pendingSignals: AbortSignal[] = []
      vi.stubGlobal(
        'fetch',
        vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
          const url = requestUrl(input)
          if (url.includes('/health')) {
            return Promise.resolve(new Response(JSON.stringify(HEALTH)))
          }
          if (url.endsWith('/api/v1/drafts/4')) {
            return Promise.resolve(
              new Response(JSON.stringify(draft), {
                headers: { 'Content-Type': 'application/json' },
              }),
            )
          }
          if (url.includes('/feed') || url.includes('/projections/current')) {
            if (init?.signal !== null && init?.signal !== undefined) {
              pendingSignals.push(init.signal)
            }
            return new Promise<Response>(() => undefined)
          }
          return Promise.reject(new Error(`unexpected request ${url}`))
        }),
      )

      const rendered = renderAt('/draft/4/categories')
      await waitFor(() => {
        expect(pendingSignals).toHaveLength(2)
      })
      rendered.unmount()

      expect(pendingSignals.every((signal) => signal.aborted)).toBe(true)
    },
    TIMEOUT_MS,
  )
})
