import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../App'
import { ApiError } from '../api/client'
import { AppLayout } from '../components/AppLayout'
import { mockFetch, renderWithRouter } from '../test/helpers'

const HEALTH = { status: 'ok', service: 'hoops-gm', version: '0.1.0', environment: 'development' }
const META = {
  service: 'hoops-gm',
  version: '0.1.0',
  environment: 'development',
  season: '2026-27',
  entity_groups: ['identity', 'stats', 'league', 'schedule'],
}
const READY = { status: 'ok', database: 'ok', detail: null }

describe('the dashboard shell', () => {
  it('renders backend state from a real API call', async () => {
    mockFetch({
      '/health/ready': { body: READY },
      '/api/v1/meta': { body: META },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />)

    expect(await screen.findByTestId('backend-status')).toHaveTextContent('Backend 0.1.0')
    expect(await screen.findByText('2026-27')).toBeInTheDocument()
    expect(await screen.findByText('identity, stats, league, schedule')).toBeInTheDocument()
  })

  it('says so when the backend is unreachable instead of rendering blank', async () => {
    mockFetch({})

    renderWithRouter(<App />)

    await waitFor(() => {
      expect(screen.getByTestId('backend-status')).toHaveTextContent('Backend unreachable')
    })
    expect(await screen.findByText(/Could not load service metadata/)).toBeInTheDocument()
    // Both the shell status and the failed panel announce themselves.
    expect(await screen.findAllByRole('alert')).toHaveLength(2)
  })

  it('does not misclassify a malformed health response as unreachable', async () => {
    mockFetch({
      '/api/v1/meta': { body: META },
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
      '/api/v1/meta': { body: META },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />)
    await userEvent.click(await screen.findByRole('link', { name: 'System' }))

    expect(await screen.findByRole('heading', { name: 'System' })).toBeInTheDocument()
    expect(await screen.findByTestId('readiness-database')).toHaveTextContent('ok')
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
      '/api/v1/meta': { body: META },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/system' })

    expect(await screen.findByText(/Could not load readiness/)).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('database check failed: OperationalError')
    expect(screen.getByRole('alert')).toHaveTextContent('Code degraded')
    expect(screen.getByRole('alert')).toHaveTextContent('Request req-ready-route')
  })

  it('renders malformed 2xx metadata as an explicit contract error', async () => {
    mockFetch({
      '/health/ready': { body: READY },
      '/api/v1/meta': {
        body: { ...META, entity_groups: 'identity' },
        headers: { 'X-Request-ID': 'req-bad-meta-route' },
      },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />)

    expect(await screen.findByText(/Could not load service metadata/)).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('did not match the expected backend contract')
    expect(screen.getByRole('alert')).toHaveTextContent('Code invalid_response')
    expect(screen.getByRole('alert')).toHaveTextContent('Request req-bad-meta-route')
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
