import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { ApiError } from '../api/client'
import { AppLayout, BackendStatus } from '../components/AppLayout'
import { mockFetch, renderWithRouter } from '../test/helpers'

const HEALTH = { status: 'ok', service: 'hoops-gm', version: '0.1.0', environment: 'development' }
const READY = { status: 'ok', database: 'ok', detail: null }

afterEach(() => {
  vi.useRealTimers()
})

describe('the dashboard shell', () => {
  it('renders backend state from a real API call', async () => {
    mockFetch({
      '/health/ready': { body: READY },
      '/api/v1/drafts': { body: { drafts: [] } },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />)

    await waitFor(() => {
      expect(screen.getByTestId('backend-status')).toHaveTextContent('Backend 0.1.0')
    })
    expect(await screen.findByRole('heading', { name: 'Start here' })).toBeInTheDocument()
    expect(
      await screen.findByText(/The draft surfaces exist, but this database has no recorded drafts/),
    ).toBeInTheDocument()
  })

  it('says so when the backend is unreachable instead of rendering blank', async () => {
    mockFetch({})

    renderWithRouter(<App />)

    await waitFor(() => {
      expect(screen.getByTestId('backend-status')).toHaveTextContent('Backend unreachable')
    })
    expect(await screen.findByText(/Could not load the draft launch data/)).toBeInTheDocument()
    // Both the shell status and the failed panel announce themselves.
    expect(await screen.findAllByRole('alert')).toHaveLength(2)
  })

  it('does not misclassify a malformed health response as unreachable', async () => {
    mockFetch({
      '/api/v1/drafts': { body: { drafts: [] } },
      '/health': {
        body: { status: 'ok' },
        headers: { 'X-Request-ID': 'req-bad-health' },
      },
    })

    renderWithRouter(<App />)

    await waitFor(() => {
      expect(screen.getByTestId('backend-status')).toHaveTextContent('Backend error')
    })
    expect(screen.getByTestId('backend-status')).toHaveTextContent('did not match')
    expect(screen.getByTestId('backend-status')).toHaveTextContent('Code invalid_response')
    expect(screen.getByTestId('backend-status')).toHaveTextContent('Request req-bad-health')
  })

  it('treats a proxy-generated 5xx with no backend request id as unreachable', async () => {
    mockFetch({
      '/api/v1/drafts': { body: { drafts: [] } },
      '/health': { status: 502, body: null },
    })

    renderWithRouter(<App />)

    await waitFor(() => {
      expect(screen.getByTestId('backend-status')).toHaveTextContent('Backend unreachable')
    })
    expect(
      screen.getByRole('button', { name: 'Check backend again' }),
    ).toBeInTheDocument()
  })

  it('marks an old shell health result stale and offers a deterministic recheck', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-19T12:00:00Z'))
    const reload = vi.fn()

    render(
      <BackendStatus
        status="success"
        version="0.1.0"
        environment="development"
        error={null}
        fetchedAt={new Date()}
        reload={reload}
      />,
    )

    expect(screen.queryByText('Health status is stale.')).not.toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(60_000)
    })

    expect(screen.getByText('Health status is stale.')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Check backend again' }),
    ).toBeInTheDocument()
  })

  it('offers a retry that actually retries', async () => {
    const fetchMock = mockFetch({})
    renderWithRouter(<App />)

    const retry = await screen.findByRole('button', { name: 'Retry' })
    const before = fetchMock.mock.calls.length

    await userEvent.click(retry)

    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(before)
    })
  })

  it('navigates to the system page and shows database readiness', async () => {
    mockFetch({
      '/health/ready': { body: READY },
      '/api/v1/drafts': { body: { drafts: [] } },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />)
    await userEvent.click(
      within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('link', {
        name: 'System',
      }),
    )

    expect(await screen.findByRole('heading', { name: 'System' })).toBeInTheDocument()
    expect(await screen.findByTestId('readiness-database')).toHaveTextContent('ok')
  })

  it('navigates to the projections page from the shell', async () => {
    // The route table and the nav item are shared files this lane edited, and
    // `ProjectionsPage.test.tsx` renders the page directly — so without this,
    // a page that works would still be unreachable and nothing would say so.
    mockFetch({
      '/api/v1/drafts': { body: { drafts: [] } },
      '/api/v1/leagues/1/projections/current': {
        status: 409,
        body: {
          error: 'projections_source_not_imported',
          detail: 'no basketball_monster projection import exists',
          request_id: 'req-1',
        },
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />)
    await userEvent.click(
      within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('link', {
        name: 'Projections',
      }),
    )

    expect(await screen.findByRole('heading', { name: 'Projections' })).toBeInTheDocument()
    // Reached the endpoint and rendered its refusal in the screen's own words,
    // rather than merely mounting a heading.
    expect(await screen.findByTestId('async-error-summary')).toHaveTextContent(
      /No Basketball Monster projections have been imported/i,
    )
  })

  it('navigates to the reliability page from the shell', async () => {
    mockFetch({
      '/api/v1/drafts': { body: { drafts: [] } },
      '/api/v1/reliability/scorecards': {
        status: 409,
        body: {
          error: 'reliability_not_published',
          detail: 'no current reliability cohort exists',
          request_id: 'req-1',
        },
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />)
    await userEvent.click(
      within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('link', {
        name: 'Reliability',
      }),
    )
    expect(await screen.findByRole('heading', { name: 'Reliability' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Reliability' })).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Reliability evidence has not been published for this store',
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Code reliability_not_published')
  })

  it('surfaces a degraded database rather than hiding it', async () => {
    mockFetch({
      '/health/ready': {
        status: 503,
        body: {
          status: 'degraded',
          database: 'unavailable',
          detail: 'database check failed: OperationalError',
        },
        headers: { 'X-Request-ID': 'req-ready-route' },
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/system' })

    expect(await screen.findByText(/Could not load readiness/)).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('database check failed: OperationalError')
    expect(screen.getByRole('alert')).toHaveTextContent('Code degraded')
    expect(screen.getByRole('alert')).toHaveTextContent('Request req-ready-route')
  })

  it('renders a malformed 2xx draft list as an explicit contract error', async () => {
    mockFetch({
      '/health/ready': { body: READY },
      '/api/v1/drafts': {
        body: { drafts: 'not-an-array' },
        headers: { 'X-Request-ID': 'req-bad-drafts-route' },
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />)

    expect(await screen.findByText(/Could not load the draft launch data/)).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('did not match the expected backend contract')
    expect(screen.getByRole('alert')).toHaveTextContent('Code invalid_response')
    expect(screen.getByRole('alert')).toHaveTextContent('Request req-bad-drafts-route')
  })

  it('navigates to the draft board from the shell', async () => {
    // Same reason as the projections case above: `DraftPage.recorded.test.tsx`
    // renders the page directly, so without this the board could work
    // perfectly and still be unreachable from the nav, with nothing saying so.
    mockFetch({
      '/api/v1/drafts/1/events': {
        body: { draft_id: 1, events: [], since_sequence: 0, last_sequence: 0 },
      },
      '/api/v1/drafts/1': {
        body: {
          id: 1,
          league_id: 1,
          name: '[demo] Auction',
          is_mock: true,
          tool_usage: 'assisted',
          source_board_profile: null,
          notes: null,
          status: 'in_progress',
          format: {
            draft_type: 'auction',
            team_count: 12,
            roster_size: 13,
            total_roster_slots: 156,
            auction_budget: '200.00',
          },
          league_format_drift: null,
          participants: [],
          open_lot: null,
          next_pick: null,
          selections_made: 0,
          total_roster_slots: 156,
          last_sequence: 0,
          live_event_count: 0,
          voided_sequences: [],
          unresolved_player_count: 0,
        },
      },
      '/api/v1/drafts': {
        body: {
          drafts: [
            {
              id: 1,
              league_id: 1,
              name: '[demo] Auction',
              is_mock: true,
              tool_usage: 'assisted',
              source_board_profile: null,
              status: 'in_progress',
              format: {
                draft_type: 'auction',
                team_count: 12,
                roster_size: 13,
                total_roster_slots: 156,
                auction_budget: '200.00',
              },
              last_sequence: 0,
              selections_made: 0,
              created_at: '2026-08-21T19:00:00Z',
              updated_at: '2026-08-21T19:30:00Z',
            },
          ],
        },
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />)
    await userEvent.click(await screen.findByRole('link', { name: 'Draft' }))

    // Reached the list and then the board itself, rather than merely mounting
    // a heading: the second click only resolves if the list rendered a real
    // draft from a real response.
    await userEvent.click(await screen.findByRole('link', { name: '[demo] Auction' }))
    expect(await screen.findByRole('heading', { name: '[demo] Auction' })).toBeInTheDocument()
    expect(await screen.findByTestId('log-empty')).toBeInTheDocument()
  })

  it('renders a not-found page for an unknown route', async () => {
    mockFetch({ '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/no-such-page' })

    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeInTheDocument()
  })

  it('keeps shell navigation available and resets the boundary on route change', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    mockFetch({ '/health': { body: HEALTH } })

    function BrokenRoute(): never {
      throw new ApiError(500, 'render_failed', 'Route render failed.', 'req-route-render')
    }

    renderWithRouter(
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<BrokenRoute />} />
          <Route path="system" element={<p>Recovered through navigation</p>} />
        </Route>
      </Routes>,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent('Route render failed.')
    await userEvent.click(screen.getByRole('link', { name: 'System' }))

    expect(await screen.findByText('Recovered through navigation')).toBeInTheDocument()
    expect(screen.queryByText('Route render failed.')).not.toBeInTheDocument()
  })
})
