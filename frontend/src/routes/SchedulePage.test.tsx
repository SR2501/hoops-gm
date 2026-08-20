/**
 * The schedule grid, exercised through the real client and the real route.
 *
 * These go through `mockFetch`, which stubs `fetch` rather than the API client,
 * so the error-envelope parsing that turns a body's `error` field into a code
 * is under test here too. That matters more than usual on this endpoint: the
 * code arrives in the **body**, not in an `X-Bridge-Error` header, and a client
 * that read the header would see `null` on every refusal and fall through to a
 * generic message — silently, and only in the cases that matter most.
 */

import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import type { ScheduleGrid } from '../api/types'
import { mockFetch, renderWithRouter } from '../test/helpers'

const HEALTH = { status: 'ok', service: 'hoops-gm', version: '0.1.0', environment: 'development' }

const GRID_PATH = '/schedule-grid/current'

function scheduleGrid(overrides: Partial<ScheduleGrid> = {}): ScheduleGrid {
  return {
    league_id: 1,
    season: '2026-27',
    lineage: {
      schedule: {
        refresh_id: 1,
        version: '9bcac1c60490b41a',
        refreshed_at: '2026-08-20T12:00:00Z',
        source_game_count: 10,
        resolved_game_count: 10,
        persisted_team_row_count: 20,
        unresolved_game_ids: [],
      },
      scoring_period_projection: {
        refresh_id: 2,
        version: '22a8bac85a909ccd',
        refreshed_at: '2026-08-20T12:00:00Z',
      },
      deadline_calendar: { id: 1, version: 1 },
      settings_snapshot: { id: 1, version: 1 },
    },
    teams: [
      { team_id: 1, nba_team_id: 1610612737, abbreviation: 'ATL', name: 'Atlanta Hawks' },
      { team_id: 2, nba_team_id: 1610612738, abbreviation: 'BOS', name: 'Boston Celtics' },
      { team_id: 3, nba_team_id: 1610612739, abbreviation: 'CLE', name: 'Cleveland Cavaliers' },
    ],
    periods: [
      { period_number: 1, start_date: '2026-10-19', end_date: '2026-10-25', is_playoff: false },
      { period_number: 2, start_date: '2026-10-26', end_date: '2026-11-01', is_playoff: false },
      { period_number: 3, start_date: '2027-03-08', end_date: '2027-03-14', is_playoff: true },
    ],
    counts: [
      { period_number: 1, team_id: 1, games: 0 },
      { period_number: 1, team_id: 2, games: 4 },
      { period_number: 1, team_id: 3, games: 2 },
      { period_number: 2, team_id: 1, games: 0 },
      { period_number: 2, team_id: 2, games: 0 },
      { period_number: 2, team_id: 3, games: 0 },
      { period_number: 3, team_id: 1, games: 5 },
      { period_number: 3, team_id: 2, games: 3 },
      { period_number: 3, team_id: 3, games: 0 },
    ],
    ...overrides,
  }
}

function refusal(status: number, error: string, detail: string) {
  return {
    status,
    body: { error, detail, request_id: 'req-schedule-1' },
    headers: { 'X-Request-ID': 'req-schedule-1' },
  }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('the schedule grid', () => {
  it('renders every team and period from the endpoint response', async () => {
    mockFetch({ [GRID_PATH]: { body: scheduleGrid() }, '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    const grid = await screen.findByTestId('schedule-grid')
    // 3 teams plus the league baseline row.
    expect(within(grid).getAllByRole('row')).toHaveLength(5)
    expect(within(grid).getByText('ATL')).toBeInTheDocument()
    expect(within(grid).getByText('Cleveland Cavaliers')).toBeInTheDocument()
    expect(screen.getByTestId('cell-2-1')).toHaveTextContent('4')
    expect(screen.getByTestId('cell-1-3')).toHaveTextContent('5')
  })

  it('renders a zero as an explicit zero, not as a blank', async () => {
    mockFetch({ [GRID_PATH]: { body: scheduleGrid() }, '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    const zero = await screen.findByTestId('cell-1-1')
    expect(zero).toHaveTextContent('0')
    expect(zero).toHaveAttribute('data-state', 'zero')
    expect(zero).toHaveAccessibleName('ATL, period 1: 0 games')
  })

  it('distinguishes a missing count from a zero instead of blanking both', async () => {
    const holed = scheduleGrid({
      counts: scheduleGrid().counts.filter(
        (count) => !(count.team_id === 3 && count.period_number === 2),
      ),
    })
    mockFetch({ [GRID_PATH]: { body: holed }, '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    const missing = await screen.findByTestId('cell-3-2')
    expect(missing).toHaveAttribute('data-state', 'no-data')
    expect(missing).toHaveAccessibleName('CLE, period 2: no data')
    expect(missing).not.toHaveTextContent('0')

    // A zero elsewhere is still unmistakably a zero.
    expect(screen.getByTestId('cell-1-2')).toHaveAttribute('data-state', 'zero')

    // And the hole is announced rather than left for the reader to notice.
    const integrity = screen.getByTestId('grid-integrity')
    expect(integrity).toHaveTextContent('This grid is not complete.')
    expect(integrity).toHaveTextContent('1 of 9 cells had no count')
  })

  it('renders a sparse period as sparse rather than as an error', async () => {
    mockFetch({ [GRID_PATH]: { body: scheduleGrid() }, '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    // Period 2 is zero for every team; it must still draw, with a zero baseline.
    expect(await screen.findByTestId('league-total-2')).toHaveTextContent('0')
    expect(screen.getByTestId('league-total-1')).toHaveTextContent('6')
    expect(screen.getByTestId('league-total-3')).toHaveTextContent('8')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByTestId('grid-integrity')).not.toBeInTheDocument()
  })

  it('marks fantasy playoff periods, which are not interchangeable with regular ones', async () => {
    mockFetch({ [GRID_PATH]: { body: scheduleGrid() }, '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    const playoff = await screen.findByTestId('period-header-3')
    expect(playoff).toHaveTextContent('PO')
    expect(playoff).toHaveTextContent('fantasy playoff period')
    expect(screen.getByTestId('period-header-1')).not.toHaveTextContent('PO')
  })

  it('shows the schedule cohort that produced the numbers without needing devtools', async () => {
    mockFetch({ [GRID_PATH]: { body: scheduleGrid() }, '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    const lineage = await screen.findByTestId('schedule-lineage')
    expect(lineage).toHaveTextContent('9bcac1c60490b41a')
    expect(within(lineage).getByTestId('schedule-game-counts')).toHaveTextContent(
      '10 from source · 10 resolved · 20 team rows persisted',
    )
    // The raw timestamp is shown verbatim, so a mislabelled one stays checkable.
    expect(within(lineage).getByTestId('schedule-refreshed-at')).toHaveTextContent(
      '2026-08-20T12:00:00Z',
    )
    expect(lineage).toHaveTextContent('22a8bac85a909ccd')
  })

  it('says when the schedule cohort itself is older than the weekly re-ingest cadence', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-31T12:00:00Z'))
    mockFetch({ [GRID_PATH]: { body: scheduleGrid() }, '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    const age = screen.getByTestId('schedule-age')
    expect(age).toHaveTextContent('refreshed 11 days ago')
    expect(age).toHaveTextContent('older than the weekly re-ingest ADR-012 requires')
  })

  it('marks an old fetch stale rather than letting it look current', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-20T12:00:00Z'))
    mockFetch({ [GRID_PATH]: { body: scheduleGrid() }, '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByTestId('schedule-grid')).toBeInTheDocument()
    expect(screen.queryByText(/Showing data from/)).not.toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5 * 60_000)
    })

    expect(screen.getByText(/Showing data from/)).toBeInTheDocument()
    // The grid is still on screen — stale is labelled, not hidden.
    expect(screen.getByTestId('schedule-grid')).toBeInTheDocument()
  })

  it('says there is nothing to draw rather than drawing an empty table', async () => {
    mockFetch({
      [GRID_PATH]: { body: scheduleGrid({ teams: [], counts: [] }) },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    expect(await screen.findByText(/no teams or no scoring periods/)).toBeInTheDocument()
    expect(screen.queryByTestId('schedule-grid')).not.toBeInTheDocument()
  })

  it('rejects a 2xx body that does not match the contract instead of drawing from it', async () => {
    mockFetch({
      [GRID_PATH]: {
        body: { ...scheduleGrid(), counts: [{ period_number: 1, team_id: 1, games: 'four' }] },
        headers: { 'X-Request-ID': 'req-bad-grid' },
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const panel = await screen.findByTestId('schedule-grid-error')
    expect(panel).toHaveTextContent('did not match the schedule grid contract')
    expect(panel).toHaveTextContent('Code')
    expect(panel).toHaveTextContent('invalid_response')
    expect(panel).toHaveTextContent('req-bad-grid')
    expect(screen.queryByTestId('schedule-grid')).not.toBeInTheDocument()
  })

  it('offers a retry that actually retries', async () => {
    const fetchMock = mockFetch({
      [GRID_PATH]: refusal(409, 'schedule_grid_incomplete', 'no rows'),
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const retry = await screen.findByRole('button', { name: 'Retry' })
    const before = fetchMock.mock.calls.length
    await userEvent.click(retry)

    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(before)
    })
  })
})

/**
 * Each refusal is a different situation calling for a different action, and
 * collapsing them into "something went wrong" would throw away the backend's
 * fail-closed work. One case per documented code, asserting they differ.
 */
describe('schedule grid refusals', () => {
  const cases: { code: string; status: number; detail: string; expect: RegExp }[] = [
    {
      code: 'schedule_grid_local_only',
      status: 403,
      detail: 'caller is not loopback',
      expect: /served to this machine only/,
    },
    {
      code: 'schedule_grid_league_not_found',
      status: 404,
      detail: 'no league 1',
      expect: /no such league/,
    },
    {
      code: 'schedule_grid_not_current',
      status: 409,
      detail: 'registered version no longer matches',
      expect: /changed after it was last verified/,
    },
    {
      code: 'schedule_grid_incomplete_evidence',
      status: 409,
      detail: 'carries no schedule_completeness block',
      expect: /completeness could not be verified/,
    },
    {
      code: 'schedule_grid_incomplete',
      status: 409,
      detail: 'grid has no rows',
      expect: /no game counts at all/,
    },
  ]

  for (const testCase of cases) {
    it(`explains ${testCase.code} specifically`, async () => {
      mockFetch({
        [GRID_PATH]: refusal(testCase.status, testCase.code, testCase.detail),
        '/health': { body: HEALTH },
      })

      renderWithRouter(<App />, { route: '/schedule' })

      const panel = await screen.findByTestId('schedule-grid-error')
      expect(within(panel).getByTestId('schedule-grid-error-summary')).toHaveTextContent(
        testCase.expect,
      )
      // The action is present and is not a restatement of the summary.
      const action = within(panel).getByTestId('schedule-grid-error-action')
      expect(action.textContent?.length ?? 0).toBeGreaterThan(20)
      // The code and the backend's own words both survive, so the failure can
      // be correlated to a server log line.
      expect(panel).toHaveTextContent(testCase.code)
      expect(panel).toHaveTextContent(testCase.detail)
      expect(panel).toHaveTextContent('req-schedule-1')
    })
  }

  it('gives every code a distinct summary', () => {
    const summaries = new Set<string>()
    for (const testCase of cases) {
      summaries.add(testCase.expect.source)
    }
    expect(summaries.size).toBe(cases.length)
  })

  it('does not read the code from a header the browser never receives', async () => {
    // `X-Bridge-Error` is an internal backend transport and is absent from
    // every refusal on the wire. A client reading it would see null and fall
    // through to a generic message, which is the failure this asserts against.
    mockFetch({
      [GRID_PATH]: {
        status: 409,
        body: {
          error: 'schedule_grid_not_current',
          detail: 'stale',
          request_id: 'req-no-header',
        },
        headers: { 'X-Request-ID': 'req-no-header' },
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const panel = await screen.findByTestId('schedule-grid-error')
    expect(panel).toHaveTextContent(/changed after it was last verified/)
  })

  it('stays specific about an unreachable backend rather than blaming the data', async () => {
    mockFetch({ '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    const panel = await screen.findByTestId('schedule-grid-error')
    expect(panel).toHaveTextContent(/did not answer, so no schedule data was received/)
    expect(panel).toHaveTextContent('unreachable')
  })

  it('does not invent an explanation for a code it has never seen', async () => {
    mockFetch({
      [GRID_PATH]: refusal(409, 'schedule_grid_something_new', 'a condition added later'),
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const panel = await screen.findByTestId('schedule-grid-error')
    expect(panel).toHaveTextContent(/did not give a reason this dashboard recognises/)
    expect(panel).toHaveTextContent('schedule_grid_something_new')
    expect(panel).toHaveTextContent('a condition added later')
  })
})

describe('navigation', () => {
  it('reaches the schedule from the sidebar', async () => {
    mockFetch({
      [GRID_PATH]: { body: scheduleGrid() },
      '/api/v1/meta': {
        body: {
          service: 'hoops-gm',
          version: '0.1.0',
          environment: 'development',
          season: '2026-27',
          entity_groups: ['schedule'],
        },
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />)
    await userEvent.click(await screen.findByRole('link', { name: 'Schedule' }))

    expect(await screen.findByRole('heading', { name: 'Schedule' })).toBeInTheDocument()
    expect(await screen.findByTestId('schedule-grid')).toBeInTheDocument()
  })
})
