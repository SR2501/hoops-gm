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

import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { SCHEDULE_GRID_ERRORS } from '../api/scheduleGridErrors'
import type { ScheduleGrid, SchedulePendingGame } from '../api/types'
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
        // `lineage.py` requires `persisted_team_row_count == 2 *
        // resolved_game_count` — team_schedule holds exactly two rows per
        // game — so these three move together. 7 games, 14 team rows, and all
        // 14 fall inside the three periods below, so counted equals persisted.
        //
        // An earlier edit set persisted to 14 against 10 resolved "for
        // coherence". That is a body the service cannot produce: it raises
        // inside `schedule_completeness` and becomes a 409. The original
        // 10/20 against 14 counted was not incoherent at all — it is the
        // legitimate case where six team-games fall outside every scoring
        // period. Shape-valid and meaning-invalid, which no test here can see.
        source_game_count: 7,
        resolved_game_count: 7,
        persisted_team_row_count: 14,
        unresolved_game_ids: [],
        // The steady state ADR-013 leaves behind once the NBA Cup bracket is
        // drawn: the block is present and empty, which asserts the season *is*
        // fully scheduled. Distinct from the block being absent, which asserts
        // nothing — `withoutPendingBlock` builds that, and the two must not
        // render the same.
        pending_game_ids: [],
        pending_games: [],
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

/**
 * A grid whose source published `games` without deciding who plays in them.
 *
 * `source_game_count` is moved to keep ADR-013's invariant true, because a
 * payload the backend could never emit is a payload whose behaviour proves
 * nothing about the screen.
 */
function withPendingGames(games: SchedulePendingGame[]): ScheduleGrid {
  const base = scheduleGrid()
  return {
    ...base,
    lineage: {
      ...base.lineage,
      schedule: {
        ...base.lineage.schedule,
        source_game_count: base.lineage.schedule.resolved_game_count + games.length,
        pending_game_ids: games.map((game) => game.nba_game_id),
        pending_games: games,
      },
    },
  }
}

/** A response from a backend that predates the pending contract entirely. */
function withoutPendingBlock(): ScheduleGrid {
  const base = scheduleGrid()
  const { pending_game_ids: _ids, pending_games: _games, ...schedule } = base.lineage.schedule
  return { ...base, lineage: { ...base.lineage, schedule } }
}

function pendingGame(overrides: Partial<SchedulePendingGame> = {}): SchedulePendingGame {
  return {
    nba_game_id: '0022601201',
    game_date: '2026-10-21',
    game_label: 'Emirates NBA Cup',
    game_sub_label: 'Quarterfinal',
    game_subtype: 'in-season-knockout',
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
    // 3 teams, plus the league sum row and the per-team mean row.
    expect(within(grid).getAllByRole('row')).toHaveLength(6)
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

  it('renders every non-zero count identically, so magnitude carries no styling', async () => {
    // Requirement: descriptive counts only. The moment a cell's appearance
    // varies with how big the number is, the grid is asserting a judgement
    // about schedule volume that belongs to `quant` behind the Model gate.
    mockFetch({ [GRID_PATH]: { body: scheduleGrid() }, '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    const four = await screen.findByTestId('cell-2-1')
    const two = screen.getByTestId('cell-3-1')
    const five = screen.getByTestId('cell-1-3')
    const zero = screen.getByTestId('cell-1-1')

    expect(four.className).toBe(two.className)
    expect(four.getAttribute('data-state')).toBe(two.getAttribute('data-state'))
    // A zero is styled like any other count; only its `data-state` names it,
    // and the playoff column adds a category marker, not a magnitude one.
    expect(zero.className).toBe(four.className)
    expect(five.className).toContain('grid__cell--playoff')
    expect(zero.getAttribute('data-state')).toBe('zero')
    expect(four.getAttribute('data-state')).toBe('count')
  })

  it('marks a total that is missing periods, on screen and not only for a screen reader', async () => {
    const holed = scheduleGrid({
      counts: scheduleGrid().counts.filter(
        (count) => !(count.team_id === 3 && count.period_number === 2),
      ),
    })
    mockFetch({ [GRID_PATH]: { body: holed }, '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    const partial = await screen.findByTestId('team-total-3')
    expect(partial).toHaveAttribute('data-state', 'partial')
    expect(partial.className).toContain('grid__total--partial')
    // The marker is real text in the cell, not screen-reader-only.
    expect(partial).toHaveTextContent('+?')

    // A complete total in the same column is not marked.
    const complete = screen.getByTestId('team-total-1')
    expect(complete).toHaveAttribute('data-state', 'complete')
    expect(complete).not.toHaveTextContent('+?')

    // The league cell for the affected period is marked too — otherwise a
    // period where nobody reported would read as a period where nobody played.
    expect(screen.getByTestId('league-total-2')).toHaveAttribute('data-state', 'partial')
  })

  it('gives the league baseline as both a sum and a per-team mean', async () => {
    mockFetch({ [GRID_PATH]: { body: scheduleGrid() }, '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    expect(await screen.findByTestId('league-total-1')).toHaveTextContent('6')
    expect(screen.getByTestId('league-mean-1')).toHaveTextContent('2.0')
    expect(screen.getByTestId('league-mean-3')).toHaveTextContent('2.7')
    expect(screen.getByTestId('league-mean-1')).toHaveAttribute('data-state', 'complete')
    // The season column is the mean of the Total column: 14 games over 3 teams.
    expect(screen.getByTestId('league-mean-season')).toHaveTextContent('4.7')
  })

  it('does not let a missing team quietly drag the per-team mean down', async () => {
    // The numerator sums only the teams that reported. Dividing it by every
    // team would understate the mean by exactly the missing share — and
    // understate it in the direction that makes each team's own count read as
    // relatively healthier than it is.
    //
    // Period 1 here is ATL 4, BOS 4, CLE dropped, so the honest mean over the
    // two teams that reported is 4.0; a full-denominator quotient would be
    // 8/3 = 2.7. CLE's period-3 count is raised to 6 so that the season
    // column's numerator differs too: the season sum is 22 across every
    // reported cell, while the mean of the Total column is over complete rows
    // only — ATL 9 and BOS 7 — giving 16/2 = 8.0 rather than 22/3 = 7.3.
    const base = scheduleGrid()
    const holed = scheduleGrid({
      counts: base.counts
        .filter((count) => !(count.team_id === 3 && count.period_number === 1))
        .map((count) => {
          if (count.period_number === 1 && count.team_id === 1) return { ...count, games: 4 }
          if (count.period_number === 3 && count.team_id === 3) return { ...count, games: 6 }
          return count
        }),
    })
    mockFetch({ [GRID_PATH]: { body: holed }, '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    const mean = await screen.findByTestId('league-mean-1')
    expect(mean).toHaveTextContent('4.0')
    expect(mean).toHaveAttribute('data-state', 'partial')
    // Marked on screen, next to the sum that is also marked — not a bare
    // number sitting beside a flagged sibling, which would read as checked.
    expect(mean).toHaveTextContent('+?')
    expect(screen.getByTestId('league-total-1')).toHaveAttribute('data-state', 'partial')
    expect(mean).toHaveAccessibleName(/over the 2 of 3 that reported/)

    // The season cell is the mean of the Total column, so it drops incomplete
    // rows entirely rather than dividing the season sum by every team. This is
    // the only input on which that differs from the simpler expression.
    const seasonMean = screen.getByTestId('league-mean-season')
    expect(screen.getByTestId('league-total-season')).toHaveTextContent('22')
    expect(screen.getByTestId('league-total-season')).toHaveAttribute('data-state', 'partial')
    expect(seasonMean).toHaveTextContent('8.0')
    expect(seasonMean).toHaveAttribute('data-state', 'partial')
    expect(seasonMean).toHaveAccessibleName(/over the 2 of 3 with a complete row/)
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
      '7 from source · 7 resolved · 0 pending · 14 team rows persisted · 14 counted in this grid',
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

  it('explains a refusal that arrives on top of data already on screen', async () => {
    // The case that matters most and was previously uncovered: the grid loads,
    // the schedule is re-ingested underneath, and the refresh comes back 409.
    // The reader is looking at counts now known to be superseded, so the
    // written summary and its next step must reach this path too — not just
    // the cold-load panel. This drives the real user route: wait for the grid
    // to go stale, then press the Refresh the stale banner offers.
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-20T12:00:00Z'))

    let gridCall = 0
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
        Promise.resolve(
          new Response(JSON.stringify(body), {
            status,
            headers: { 'Content-Type': 'application/json', ...headers },
          }),
        )

      if (url.includes('/health')) return json(HEALTH)

      gridCall += 1
      if (gridCall === 1) return json(scheduleGrid())
      return json(
        {
          error: 'schedule_grid_not_current',
          detail: 'registered version no longer matches the persisted schedule content',
          request_id: 'req-warm-failure',
        },
        409,
        { 'X-Request-ID': 'req-warm-failure' },
      )
    })
    vi.stubGlobal('fetch', fetchMock)

    renderWithRouter(<App />, { route: '/schedule' })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByTestId('schedule-grid')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5 * 60_000)
    })
    const refresh = screen.getByRole('button', { name: 'Refresh' })

    fireEvent.click(refresh)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })

    const failure = screen.getByTestId('async-stale-failure')
    expect(failure).toHaveTextContent(/would describe current reality/)
    expect(failure).toHaveTextContent(/the remedy differs/)
    expect(failure).toHaveTextContent('Code schedule_grid_not_current.')
    expect(failure).toHaveTextContent('Request req-warm-failure.')
    // The stale data is still on screen and labelled, not hidden.
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

    const panel = await screen.findByRole('alert')
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
 * ADR-013: the schedule itself can be unfinished, and that is a third thing
 * alongside a real zero and an absent count.
 *
 * The rule these all defend is that a pending game has **no teams** — the
 * source publishes it with `teamId: 0` and every naming field null — so nothing
 * on this screen may attribute one to a team. The temptation is real and the
 * brief for this work originally asked for exactly that; these tests exist so
 * the next person who reaches for a per-cell badge has to delete an assertion
 * that says why not.
 */
describe('a season the source has not finished scheduling', () => {
  it('says a pending week may rise, without claiming to know whose count does', async () => {
    mockFetch({
      [GRID_PATH]: { body: withPendingGames([pendingGame()]) },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const notice = await screen.findByTestId('grid-pending')
    expect(notice).toHaveTextContent('This season is not fully scheduled')
    expect(notice).toHaveTextContent('Scoring period 1 (1) is marked TBD')
    expect(notice).toHaveTextContent('may rise')
    expect(notice).toHaveTextContent('not a confirmed bye')
    // The statement is about the column, so it must say it cannot name teams.
    expect(notice).toHaveTextContent('cannot say which teams are affected')

    // And no team is named anywhere in it. ATL/BOS/CLE are the three teams in
    // this payload; a per-cell attribution would have to mention one.
    expect(notice.textContent).not.toMatch(/\b(ATL|BOS|CLE|Hawks|Celtics|Cavaliers)\b/)
  })

  it('marks the column that holds the pending game and leaves the others alone', async () => {
    mockFetch({
      [GRID_PATH]: { body: withPendingGames([pendingGame({ game_date: '2026-10-28' })]) },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    // Period 2 is 2026-10-26..2026-11-01.
    const marked = await screen.findByTestId('period-header-2')
    expect(marked).toHaveAttribute('data-pending', 'true')
    expect(marked).toHaveTextContent('TBD')
    expect(screen.getByTestId('period-header-1')).toHaveAttribute('data-pending', 'false')
    expect(screen.getByTestId('period-header-1')).not.toHaveTextContent('TBD')
    expect(screen.getByTestId('period-header-3')).toHaveAttribute('data-pending', 'false')
  })

  it('leaves a zero under a TBD header reading as the real zero it is', async () => {
    mockFetch({
      [GRID_PATH]: { body: withPendingGames([pendingGame({ game_date: '2026-10-28' })]) },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    // Every team has 0 games in period 2 in this payload.
    const inPendingColumn = await screen.findByTestId('cell-1-2')
    const elsewhere = screen.getByTestId('cell-1-1')

    expect(inPendingColumn).toHaveAttribute('data-state', 'zero')
    expect(elsewhere).toHaveAttribute('data-state', 'zero')
    expect(inPendingColumn.textContent).toBe(elsewhere.textContent)
    expect(inPendingColumn.getAttribute('aria-label')).toBe('ATL, period 2: 0 games')
    expect(inPendingColumn).not.toHaveAttribute('title')
  })

  it('does not reuse the missing-data marker for a schedule that is merely unfinished', async () => {
    // `+?` means "this sum is short because a count did not arrive". A pending
    // period makes a sum provisional for an unrelated reason, and one glyph
    // cannot carry both without making the reader guess which is meant.
    mockFetch({
      [GRID_PATH]: { body: withPendingGames([pendingGame({ game_date: '2026-10-28' })]) },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const leagueTotal = await screen.findByTestId('league-total-2')
    expect(leagueTotal).toHaveAttribute('data-pending', 'true')
    expect(leagueTotal).toHaveAttribute('data-state', 'complete')
    expect(leagueTotal.textContent).not.toContain('+?')
    expect(leagueTotal.getAttribute('title')).toContain('may rise')

    // No integrity banner: nothing is missing, so the error-styled one that
    // means "this grid is not complete" must stay off screen.
    expect(screen.queryByTestId('grid-integrity')).toBeNull()
  })

  it('tells a response that says "none pending" apart from one that cannot say', async () => {
    // The distinction the whole feature turns on. An empty block asserts the
    // season is fully scheduled; a missing block asserts nothing at all, and
    // rendering them the same would let the second pass for the first.
    mockFetch({ [GRID_PATH]: { body: scheduleGrid() }, '/health': { body: HEALTH } })
    renderWithRouter(<App />, { route: '/schedule' })

    await screen.findByTestId('schedule-grid')
    expect(screen.queryByTestId('grid-pending')).toBeNull()
    expect(screen.queryByTestId('grid-pending-unknown')).toBeNull()
    expect(screen.getByTestId('schedule-pending-games')).toHaveTextContent(
      'none — every game the source published has teams assigned',
    )
  })

  it('says a response predating the contract cannot vouch for completeness', async () => {
    mockFetch({ [GRID_PATH]: { body: withoutPendingBlock() }, '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    const unknown = await screen.findByTestId('grid-pending-unknown')
    expect(unknown).toHaveTextContent('Whether this season is fully scheduled is unknown')
    expect(unknown).toHaveTextContent('carried no pending-games block')
    // Not silently "no pending games": no column may be marked, and the lineage
    // must not print a reassuring zero.
    expect(screen.queryByTestId('grid-pending')).toBeNull()
    expect(screen.getByTestId('period-header-1')).toHaveAttribute('data-pending', 'false')
    expect(screen.getByTestId('schedule-game-counts')).toHaveTextContent('pending not reported')
    expect(screen.getByTestId('schedule-pending-games')).toHaveTextContent('not reported')

    // The grid still draws. Refusing the whole response would replace a screen
    // that states its own gap with a blank one and a generic contract error.
    expect(screen.getByTestId('schedule-grid')).toBeInTheDocument()
  })

  it('lists the labels that are the only evidence pending still means "undecided"', async () => {
    // ADR-013 flips back to refusing if the pending set stops being explicable
    // as an undetermined bracket. A bare count would satisfy the arithmetic and
    // show nothing a person could check that against.
    //
    // These are the values the *live* payload carries, not the ones in the
    // committed fixture. That fixture was trimmed before these fields mattered
    // and nulls them, so the recorded contract test can only ever exercise the
    // degenerate case — the labelled case, which is the one a reader actually
    // checks the flip condition against, exists only here and in a browser.
    mockFetch({
      [GRID_PATH]: {
        body: withPendingGames([
          pendingGame({ game_sub_label: 'Quarterfinal', game_subtype: 'in-season-knockout' }),
        ]),
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const listed = await screen.findByTestId('schedule-pending-games')
    expect(listed).toHaveTextContent('0022601201')
    expect(listed).toHaveTextContent('2026-10-21')
    expect(listed).toHaveTextContent('Emirates NBA Cup — Quarterfinal — in-season-knockout')
  })

  it('renders a pending game with no labels without printing empty separators', async () => {
    // The recorded response carries `game_sub_label` and `game_subtype` as
    // empty strings, so this is a shape the service really emits rather than a
    // defensive guess — even though it is an artifact of a trimmed fixture and
    // not what production sends.
    mockFetch({
      [GRID_PATH]: {
        body: withPendingGames([pendingGame({ game_sub_label: '', game_subtype: '' })]),
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const listed = await screen.findByTestId('schedule-pending-games')
    expect(listed).toHaveTextContent('Emirates NBA Cup')
    expect(listed.textContent).not.toContain('Emirates NBA Cup — ')
  })

  it('says a pending game has no date yet, in different words from a date it cannot read', async () => {
    // The contract change: `game_date` is now `date | None`, because applying
    // resolved-game time reconciliation to a pending fixture returned no season
    // at all. `null` is the source saying it has not decided when — the same
    // kind of statement as the TBD marker, one field along — and it must not be
    // reported in the words reserved for a wire defect. Nor may it be dropped:
    // ADR-013 says a consumer treats it as belonging to no known period,
    // because the game is still published.
    mockFetch({
      [GRID_PATH]: {
        body: withPendingGames([
          pendingGame({ nba_game_id: 'no-date', game_date: null }),
          pendingGame({ nba_game_id: 'unreadable', game_date: '10/21/2026' }),
        ]),
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const notice = await screen.findByTestId('grid-pending')
    expect(notice).toHaveTextContent(
      '1 of them has no date yet — the source published it without saying when',
    )
    expect(notice).toHaveTextContent('1 carried a date this screen could not read')
    // Each names its own game, so the two cannot be read as one clause.
    expect(notice).toHaveTextContent('no-date')
    expect(notice).toHaveTextContent('unreadable (10/21/2026)')
    // Neither reaches a column, and the grid still draws.
    expect(screen.getByTestId('period-header-1')).toHaveAttribute('data-pending', 'false')
    expect(screen.getByTestId('schedule-grid')).toBeInTheDocument()
  })

  it('lists an undated pending game rather than leaving the count unexplained', async () => {
    // It cannot be bucketed, so the period-scoped notice cannot name a column
    // for it. If the lineage list dropped it too, the pending count would
    // exceed the marked columns with nothing on screen accounting for the
    // difference — the invariant visibly failing, which is the state this
    // panel already refuses to leave undescribed.
    mockFetch({
      [GRID_PATH]: {
        body: withPendingGames([pendingGame({ nba_game_id: 'no-date', game_date: null })]),
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const listed = await screen.findByTestId('schedule-pending-games')
    expect(listed).toHaveTextContent('no-date')
    expect(listed).toHaveTextContent('date not yet set')
    // Not rendered as a hole, and not as the string "null".
    expect(listed.textContent).not.toMatch(/null|undefined/)
    expect(screen.getByTestId('schedule-game-counts')).toHaveTextContent('1 pending')
  })

  it('accepts a null game_date but still refuses one that is simply absent', async () => {
    // The distinction the contract turns on. `game_date` is always *present*
    // and may be `null`, so this is a value check, not a key check: `null` is
    // the source saying it has not decided when, while a missing key is a
    // response that is not the contract. Widening the first must not widen the
    // second, or the present-but-malformed rule this validator is built on
    // stops meaning anything.
    const base = scheduleGrid()
    const withRecord = (record: Record<string, unknown>) => ({
      ...base,
      lineage: {
        ...base.lineage,
        schedule: {
          ...base.lineage.schedule,
          pending_game_ids: ['0022601201'],
          pending_games: [record],
        },
      },
    })
    const fields = {
      nba_game_id: '0022601201',
      game_label: 'Emirates NBA Cup',
      game_sub_label: 'Quarterfinal',
      game_subtype: 'in-season-knockout',
    }

    mockFetch({
      [GRID_PATH]: { body: withRecord({ ...fields, game_date: null }) },
      '/health': { body: HEALTH },
    })
    const first = renderWithRouter(<App />, { route: '/schedule' })
    expect(await screen.findByTestId('schedule-grid')).toBeInTheDocument()
    first.unmount()
    vi.restoreAllMocks()

    mockFetch({ [GRID_PATH]: { body: withRecord(fields) }, '/health': { body: HEALTH } })
    renderWithRouter(<App />, { route: '/schedule' })
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'did not match the schedule grid contract',
    )
    expect(screen.queryByTestId('schedule-grid')).toBeNull()
  })

  it('keeps the season-level pending count complete when a game cannot be placed', async () => {
    // Two different denominators, and only one of them is allowed to be short.
    // A game with no date belongs to no week, so it cannot be attributed to a
    // column — but it still exists, and "N games not yet decided this season"
    // must stay complete even when the per-week attribution cannot. Dropping
    // what cannot be placed is the same shape as attributing a pending game to
    // a named team, one level up: a number that quietly sheds what it cannot
    // locate is worse than one that says it cannot locate it.
    mockFetch({
      [GRID_PATH]: {
        body: withPendingGames([
          pendingGame({ nba_game_id: 'placed', game_date: '2026-10-21' }),
          pendingGame({ nba_game_id: 'no-date', game_date: null }),
          pendingGame({ nba_game_id: 'outside', game_date: '2026-09-30' }),
        ]),
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const notice = await screen.findByTestId('grid-pending')
    // The season figure counts all three, not the one that reached a column.
    expect(notice).toHaveTextContent('The source has published 3 games without deciding')
    expect(screen.getByTestId('schedule-game-counts')).toHaveTextContent('3 pending')
    // The per-week view is honestly short, and says why for each.
    expect(notice).toHaveTextContent('Scoring period 1 (1) is marked TBD')
    expect(notice).toHaveTextContent('has no date yet')
    expect(notice).toHaveTextContent('falls outside every scoring period this grid shows')
    // And all three are listed, so the reader can reconcile 3 against 1 column.
    const listed = screen.getByTestId('schedule-pending-games')
    for (const id of ['placed', 'no-date', 'outside']) {
      expect(listed).toHaveTextContent(id)
    }
  })

  it('says a pending game fell outside the calendar rather than losing it', async () => {
    mockFetch({
      [GRID_PATH]: { body: withPendingGames([pendingGame({ game_date: '2026-09-30' })]) },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const notice = await screen.findByTestId('grid-pending')
    expect(notice).toHaveTextContent('falls outside every scoring period this grid shows')
    expect(notice).toHaveTextContent('0022601201 on 2026-09-30')
    expect(notice.textContent).not.toContain('marked TBD')
    expect(screen.getByTestId('period-header-1')).toHaveAttribute('data-pending', 'false')
  })

  it('does not let the season aggregates claim a total that cannot rise', async () => {
    // A pending game dated outside every scoring period has a fixed date no
    // column can ever hold, so it cannot enter a period count and cannot enter
    // the season total either. The notice above says exactly that. An earlier
    // version passed the *declared* pending count to the season mean, which
    // then announced that this column may rise — the screen contradicting
    // itself on one render, with the sibling season total silently disagreeing.
    mockFetch({
      [GRID_PATH]: { body: withPendingGames([pendingGame({ game_date: '2026-09-30' })]) },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const mean = await screen.findByTestId('league-mean-season')
    const total = screen.getByTestId('league-total-season')

    // The two season aggregates must agree with each other.
    expect(mean).toHaveAttribute('data-pending', 'false')
    expect(total).toHaveAttribute('data-pending', 'false')
    expect(mean.getAttribute('title')).toBeNull()
    // And neither may borrow the period sentence for a column that is not one.
    expect(mean.getAttribute('aria-label')).not.toContain('This period')
    expect(mean.getAttribute('aria-label')).toContain('Season mean games per team')
  })

  it('keeps the season aggregates quiet even when a column really is pending', async () => {
    // The season claim is stated once, in the notice, where it can be
    // qualified. Not paraphrased into a tooltip on one of two adjacent
    // aggregates.
    mockFetch({
      [GRID_PATH]: { body: withPendingGames([pendingGame({ game_date: '2026-10-28' })]) },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    // The period column that holds it does carry the statement.
    const periodMean = await screen.findByTestId('league-mean-2')
    expect(periodMean).toHaveAttribute('data-pending', 'true')
    expect(periodMean.getAttribute('aria-label')).toContain('This period contains 1 game')

    // The season column does not.
    const seasonMean = screen.getByTestId('league-mean-season')
    expect(seasonMean).toHaveAttribute('data-pending', 'false')
    expect(seasonMean.getAttribute('aria-label')).not.toContain('This period')
    expect(screen.getByTestId('league-total-season')).toHaveAttribute('data-pending', 'false')
  })

  it('says a date it could not read is a date it could not read', async () => {
    mockFetch({
      [GRID_PATH]: { body: withPendingGames([pendingGame({ game_date: '10/21/2026' })]) },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const notice = await screen.findByTestId('grid-pending')
    expect(notice).toHaveTextContent('carried a date this screen could not read')
    expect(notice).toHaveTextContent('0022601201 (10/21/2026)')
    // The failure mode this guards: `'10/21/2026' <= '2026-10-25'` is a valid
    // string comparison that would have placed the game in period 1.
    expect(screen.getByTestId('period-header-1')).toHaveAttribute('data-pending', 'false')
  })

  it('refuses a pending block whose ids and records disagree, in either direction', async () => {
    // The boundary check that lets three states be deleted instead of narrated.
    // Records longer than ids is the dangerous direction: unguarded it badged a
    // column TBD while the lineage said "none — every game the source published
    // has teams assigned", which is the only place on this screen the copy ever
    // asserts completeness. Nothing about that is loud.
    const base = scheduleGrid()
    const record = pendingGame()
    const withBlock = (ids: string[], games: SchedulePendingGame[]) => ({
      ...base,
      lineage: {
        ...base.lineage,
        schedule: { ...base.lineage.schedule, pending_game_ids: ids, pending_games: games },
      },
    })

    for (const body of [
      withBlock([], [record]),
      withBlock(['0022601201', '0022601202'], [record]),
      withBlock(['a-different-id'], [record]),
      // Duplicates pass a positional equality check but reach `lineage__list`
      // as duplicate React keys, which React documents as unsupported rather
      // than cosmetic. Same class as the states above, so closed the same way.
      withBlock(
        ['0022601201', '0022601201'],
        [record, { ...record, game_sub_label: 'Semifinal' }],
      ),
    ]) {
      mockFetch({ [GRID_PATH]: { body }, '/health': { body: HEALTH } })
      const { unmount } = renderWithRouter(<App />, { route: '/schedule' })

      const panel = await screen.findByRole('alert')
      expect(panel).toHaveTextContent('did not match the schedule grid contract')
      expect(screen.queryByTestId('schedule-grid')).toBeNull()
      expect(screen.queryByTestId('grid-pending')).toBeNull()
      unmount()
      vi.restoreAllMocks()
    }
  })

  it('accepts a pending game whose prose labels are null rather than losing the page', async () => {
    // A missing label is a gap this screen can describe. Refusing the response
    // over it would cost every count on the grid for a piece of prose, which is
    // the wrong side of "tolerate a gap you can describe, reject a value that
    // cannot be true".
    mockFetch({
      [GRID_PATH]: {
        body: withPendingGames([
          pendingGame({ game_label: null, game_sub_label: null, game_subtype: null }),
        ]),
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    expect(await screen.findByTestId('schedule-grid')).toBeInTheDocument()
    expect(screen.getByTestId('schedule-pending-games')).toHaveTextContent('no label given')
    expect(screen.getByTestId('grid-pending')).toHaveTextContent('not fully scheduled')
  })

  it('says no count is final, in both directions, whether or not anything is pending', async () => {
    // ADR-013 names two sources of forward incompleteness and the contract
    // carries one. Make-up games for teams eliminated early are not published
    // at all, so no column can be marked for them — and without this the
    // marking implies its own converse, that an unmarked column is settled.
    // It must survive the pending set emptying, which is exactly when the
    // notice stops rendering and the screen would otherwise fall silent.
    //
    // Both directions, because "floor" is true of a season total and false of
    // a cell: a re-ingest moving a fixture to the next week takes the first
    // week's count down. Erring toward false comfort at the granularity a
    // manager plans a week on is the wrong way to be wrong.
    mockFetch({ [GRID_PATH]: { body: scheduleGrid() }, '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    const grid = await screen.findByTestId('schedule-grid')
    expect(screen.queryByTestId('grid-pending')).toBeNull()

    // In the caption, so it sits where the eye already is when reading a
    // number, and so it cannot outlive the numbers it qualifies.
    expect(within(grid).getByText(/No count here is final/i)).toBeVisible()
    expect(grid).toHaveTextContent('Make-up games')
    expect(grid).toHaveTextContent('can fall as well as rise')
    expect(grid).toHaveTextContent('in columns carrying no mark as much as in marked ones')
    // Make-up games land on dates, so they raise the weekly columns they fall
    // in, not only the season total. Correcting "floor" to "not final" first
    // reassigned this consequence to the Total column alone — right about the
    // direction, wrong about the granularity, in the same sentence. ADR-013
    // states it per period: anything consuming games-per-period must treat
    // counts before December as provisional.
    expect(grid).toHaveTextContent('and the weekly counts they land in')
    // The claim it must not make.
    expect(grid.textContent).not.toMatch(/is a floor/i)
  })

  it('does not claim anything about counts when there are no counts on screen', async () => {
    // The caveat lived in the page header and rendered above "Could not load
    // the schedule grid", asserting that every count below was a floor with no
    // counts below. In the caption it exists only when the table does.
    mockFetch({
      [GRID_PATH]: refusal(503, 'schedule_grid_incomplete', 'no cohort'),
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    await screen.findByRole('alert')
    expect(screen.queryByTestId('schedule-grid')).toBeNull()
    expect(screen.queryByText(/No count here is final/i)).toBeNull()
    expect(screen.queryByText(/Make-up games/i)).toBeNull()
  })

  it('does not put the pending sentence in both the name and the description', async () => {
    // The visually-hidden span is the accessible name; `title` becomes the
    // description. Carrying the sentence in both had the column announced twice
    // at triple length on every focus change.
    mockFetch({
      [GRID_PATH]: { body: withPendingGames([pendingGame({ game_date: '2026-10-28' })]) },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const header = await screen.findByTestId('period-header-2')
    expect(header.getAttribute('title')).toBe('Period 2: Oct 26 – Nov 1')
    expect(header).toHaveTextContent('This period contains 1 game')
  })
  it('refuses a pending block that is present but not the contract', async () => {
    // Absent is tolerated because the screen can describe it. Malformed is not:
    // a half-read pending set would under-report the incompleteness it exists
    // to declare, which is worse than drawing nothing.
    const base = scheduleGrid()
    mockFetch({
      [GRID_PATH]: {
        body: {
          ...base,
          lineage: {
            ...base.lineage,
            schedule: {
              ...base.lineage.schedule,
              pending_game_ids: ['0022601201'],
              pending_games: [{ nba_game_id: '0022601201' }],
            },
          },
        },
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const panel = await screen.findByRole('alert')
    expect(panel).toHaveTextContent('did not match the schedule grid contract')
    expect(panel).toHaveTextContent('invalid_response')
    expect(screen.queryByTestId('schedule-grid')).toBeNull()
  })

  it('shows all three states at once and keeps them apart', async () => {
    // A real zero, an absent count, and a period the source has not finished
    // scheduling — on one screen, which is the case the reader actually meets.
    const withPending = withPendingGames([pendingGame({ game_date: '2026-10-28' })])
    mockFetch({
      [GRID_PATH]: {
        body: {
          ...withPending,
          counts: withPending.counts.filter(
            (count) => !(count.team_id === 1 && count.period_number === 3),
          ),
        },
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    await screen.findByTestId('schedule-grid')

    const realZero = screen.getByTestId('cell-1-1')
    const absent = screen.getByTestId('cell-1-3')
    const inPendingColumn = screen.getByTestId('cell-1-2')

    expect(realZero.dataset.state).toBe('zero')
    expect(absent.dataset.state).toBe('no-data')
    expect(inPendingColumn.dataset.state).toBe('zero')

    // Absence is the only one of the three that changes what a *cell* claims.
    expect(realZero).toHaveTextContent('0')
    expect(absent).toHaveTextContent('·')
    expect(inPendingColumn).toHaveTextContent('0')

    // The pending signal lives on the column, and each state has its own
    // banner, marker and wording.
    expect(screen.getByTestId('period-header-2')).toHaveTextContent('TBD')
    expect(screen.getByTestId('period-header-3')).not.toHaveTextContent('TBD')
    expect(screen.getByTestId('grid-integrity')).toHaveTextContent('This grid is not complete')
    expect(screen.getByTestId('grid-pending')).toHaveTextContent(
      'This season is not fully scheduled',
    )
    expect(screen.getByTestId('team-total-1')).toHaveTextContent('+?')
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
      expect: /would describe current reality/,
    },
    {
      code: 'schedule_grid_incomplete_evidence',
      status: 409,
      detail: 'carries no schedule_completeness block',
      expect: /could not verify the evidence behind the counts/,
    },
    {
      code: 'schedule_grid_incomplete',
      status: 409,
      detail: 'grid has no rows',
      expect: /does not hold together/,
    },
  ]

  for (const testCase of cases) {
    it(`explains ${testCase.code} specifically`, async () => {
      mockFetch({
        [GRID_PATH]: refusal(testCase.status, testCase.code, testCase.detail),
        '/health': { body: HEALTH },
      })

      renderWithRouter(<App />, { route: '/schedule' })

      const panel = await screen.findByRole('alert')
      expect(within(panel).getByTestId('async-error-summary')).toHaveTextContent(
        testCase.expect,
      )
      // The action is present and is not a restatement of the summary.
      const action = within(panel).getByTestId('async-error-action')
      expect(action.textContent?.length ?? 0).toBeGreaterThan(20)
      // The code and the backend's own words both survive, so the failure can
      // be correlated to a server log line.
      expect(panel).toHaveTextContent(testCase.code)
      expect(panel).toHaveTextContent(testCase.detail)
      expect(panel).toHaveTextContent('req-schedule-1')
    })
  }

  it('covers every backend condition that shares the incomplete-evidence code', async () => {
    // The backend raises this one code from nine places, on four different
    // objects: the refresh's completeness evidence, the cohort it describes,
    // the league's team rows, and the league's scoring calendar. Two were
    // driven end to end against the real service; this pins that the copy is
    // true of the families rather than of the one condition it was written
    // against, which is how it went wrong the first time.
    mockFetch({
      [GRID_PATH]: refusal(
        409,
        'schedule_grid_incomplete_evidence',
        "schedule refresh 1 describes a 'playoffs' cohort, but this grid counts regular-season games only",
      ),
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const panel = await screen.findByRole('alert')
    const summary = within(panel).getByTestId('async-error-summary')
    const action = within(panel).getByTestId('async-error-action')

    // All three common families named, and named as examples rather than as a
    // closed set — the code has nine raisers and any enumeration the copy makes
    // is a claim about the response it cannot keep.
    expect(summary).toHaveTextContent(/common cases are/)
    expect(summary).toHaveTextContent(/cannot account for what it imported/)
    expect(summary).toHaveTextContent(/different cohort from the one this grid counts/)
    expect(summary).toHaveTextContent(/not line up with this league's teams or scoring calendar/)
    // The backend's wording is the statement of what failed, not a selector
    // between two options.
    expect(summary).toHaveTextContent(/names the check that failed/)

    // The action must not assert a single remedy. Three of the nine conditions
    // are about the league's calendar or team rows, and re-importing the
    // schedule does not create a missing scoring period — an earlier version
    // told the operator to do exactly that.
    expect(action).toHaveTextContent(/the remedy is not the same for each/)
    expect(action).toHaveTextContent(/re-importing the schedule will not create one/i)

    expect(panel).toHaveTextContent("describes a 'playoffs' cohort")
  })

  it('covers both conditions that raise the incomplete code', async () => {
    // Merged main added a second raiser: a team holding schedule rows inside
    // the verified cohort but absent from the grid, because it is marked
    // inactive. Driven end to end against the merged route. The old copy said
    // the grid "produced no game counts at all", which is false there — there
    // are counts, they are just short a team whose rows exist.
    mockFetch({
      [GRID_PATH]: refusal(
        409,
        'schedule_grid_incomplete',
        'teams [2] have 2026-27 schedule rows inside the verified cohort but are absent from the grid; refusing to serve counts that contradict their own lineage block',
      ),
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const panel = await screen.findByRole('alert')
    const summary = within(panel).getByTestId('async-error-summary')
    // Both codes now phrase their case list open, and both are pinned by a test
    // asserting the hedge rather than only the contents.
    expect(summary).toHaveTextContent(/common cases are no counts at all/)
    expect(summary).toHaveTextContent(/team left out of the grid that has schedule rows/)
    // Phrased open, like its sibling, so a third raiser does not silently
    // falsify it.
    expect(summary).toHaveTextContent(/names what failed/)
    // The remedy for "no counts at all" must not name the all-zero-calendar
    // condition, which raises `incomplete_evidence` instead.
    const action = within(panel).getByTestId('async-error-action')
    expect(action).toHaveTextContent(/no scoring periods, or no active teams/)
    expect(action).toHaveTextContent(/marked inactive/)
    expect(panel).toHaveTextContent('teams [2] have 2026-27 schedule rows')
  })

  it('gives every documented code its own summary and its own action', () => {
    // Asserted over the module, not over the table of regexes above — a test
    // that compares its own literals to each other passes no matter what the
    // product code says.
    const codes = Object.keys(SCHEDULE_GRID_ERRORS)
    expect(new Set(codes)).toEqual(new Set(cases.map((testCase) => testCase.code)))

    const summaries = Object.values(SCHEDULE_GRID_ERRORS).map((copy) => copy.summary)
    const actions = Object.values(SCHEDULE_GRID_ERRORS).map((copy) => copy.action)
    expect(new Set(summaries).size).toBe(codes.length)
    expect(new Set(actions).size).toBe(codes.length)
  })

  it('does not tell a not-current caller that nothing can show the schedule is right', () => {
    // `not_current` means verification worked and returned a clear verdict.
    // `incomplete_evidence` means it could not. Swapping those two messages
    // would send the operator down the wrong path.
    const notCurrent = SCHEDULE_GRID_ERRORS.schedule_grid_not_current
    const noEvidence = SCHEDULE_GRID_ERRORS.schedule_grid_incomplete_evidence
    expect(notCurrent?.summary).toMatch(/would describe current reality/)
    expect(notCurrent?.summary).toMatch(/no schedule refresh registered for this season/)
    expect(notCurrent?.summary).toMatch(/cannot be resolved/)
    expect(notCurrent?.action).toMatch(/the remedy differs/)
    expect(notCurrent?.action).toMatch(/re-importing the schedule will not touch it/)
    expect(noEvidence?.summary).toMatch(/nothing on record establishes the counts/)
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

    const panel = await screen.findByRole('alert')
    expect(panel).toHaveTextContent(/would describe current reality/)
  })

  it('stays specific about an unreachable backend rather than blaming the data', async () => {
    mockFetch({ '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/schedule' })

    const panel = await screen.findByRole('alert')
    expect(panel).toHaveTextContent(/did not answer, so no schedule data was received/)
    expect(panel).toHaveTextContent('unreachable')
  })

  it('does not invent an explanation for a code it has never seen', async () => {
    mockFetch({
      [GRID_PATH]: refusal(409, 'schedule_grid_something_new', 'a condition added later'),
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/schedule' })

    const panel = await screen.findByRole('alert')
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
