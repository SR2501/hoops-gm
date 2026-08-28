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

import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { mockFetch, requestUrl } from '../test/helpers'
import recordedDraft from '../test/fixtures/draft-auction-resolved-state.recorded.json'
import recordedProjections from '../test/fixtures/projections-current.recorded.json'

/**
 * Ten seconds. Every wait below is a `waitFor` against a stubbed `fetch` that
 * resolves immediately, so this is a ceiling on a hang rather than a budget.
 * Named because `vitest-explicit-timeout` asks for it rather than for the
 * default to be inherited silently.
 */
const TIMEOUT_MS = 10_000

const HEALTH = { status: 'ok', service: 'hoops-gm', version: '0.1.0', environment: 'development' }

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
        '/api/v1/drafts/4': { body: recordedDraft },
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
        '/api/v1/drafts/4': { body: recordedDraft },
        '/projections/current': { body: recordedProjections },
      })

      renderAt('/draft/4/categories')
      await screen.findByTestId('league-category-table', {}, { timeout: 5000 })

      expect(recordedDraft.league_id).toBe(2)
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
        '/api/v1/drafts/4': { body: recordedDraft },
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
        ...recordedDraft,
        participants: recordedDraft.participants.map((seat) => ({
          ...seat,
          holdings: seat.holdings.map((held) => ({ ...held, player_id: null })),
        })),
        unresolved_player_count: 48,
      }

      mockFetch({
        '/health': { body: HEALTH },
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
        ...recordedDraft,
        participants: recordedDraft.participants.map((seat) => ({ ...seat, holdings: [] })),
        selections_made: 0,
      }

      mockFetch({
        '/health': { body: HEALTH },
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
        '/api/v1/drafts/4/events': { body: { draft_id: 4, events: [], since_sequence: 0, last_sequence: recordedDraft.last_sequence } },
        '/api/v1/drafts/4': { body: recordedDraft },
      })

      renderAt('/draft/4')

      const link = await screen.findByTestId('draft-categories-link', {}, { timeout: 5000 })
      expect(link).toHaveAttribute('href', '/draft/4/categories')
    },
    TIMEOUT_MS,
  )
})
