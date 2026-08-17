import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { App } from '../App'
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

    expect(await screen.findByTestId('backend-status')).toHaveTextContent('Backend unreachable')
    expect(await screen.findByText(/Could not load service metadata/)).toBeInTheDocument()
    // Both the shell status and the failed panel announce themselves.
    expect(await screen.findAllByRole('alert')).toHaveLength(2)
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
        body: { error: 'http_error', detail: 'database check failed', request_id: null },
      },
      '/api/v1/meta': { body: META },
      '/health': { body: HEALTH },
    })

    renderWithRouter(<App />, { route: '/system' })

    expect(await screen.findByText(/Could not load readiness/)).toBeInTheDocument()
  })

  it('renders a not-found page for an unknown route', async () => {
    mockFetch({ '/health': { body: HEALTH } })

    renderWithRouter(<App />, { route: '/no-such-page' })

    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeInTheDocument()
  })
})
