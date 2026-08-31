import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import recordedDraftList from '../test/fixtures/draft-list.recorded.json'
import { mockFetch } from '../test/helpers'
import { DashboardPage } from './DashboardPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  )
}

describe('the dashboard launchpad', () => {
  it('keeps the working surfaces reachable while draft data is loading', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))

    renderPage()

    expect(screen.getByRole('status')).toHaveTextContent('Loading the draft launch data')
    expect(screen.getByRole('link', { name: 'Drafts' })).toHaveAttribute('href', '/draft')
    expect(screen.getByRole('link', { name: 'System' })).toHaveAttribute('href', '/system')
  })

  it('uses the recorded response to link the current auction and its category table', async () => {
    mockFetch({
      '/api/v1/drafts': { body: recordedDraftList },
    })

    renderPage()

    // The recording is newest-first and puts an in-progress snake draft before
    // the auction. Both links must come from the selected auction object rather
    // than combining the first response row with a later row's label.
    expect(
      await screen.findByRole('heading', {
        name: '[demo] Auction mock, 12-team $200',
      }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open auction board' })).toHaveAttribute(
      'href',
      '/draft/1',
    )
    expect(screen.getByRole('link', { name: 'Open league category rates' })).toHaveAttribute(
      'href',
      '/draft/1/categories',
    )
    expect(screen.getByTestId('draft-launch')).toHaveTextContent('In-progress auction')

    expect(screen.getByRole('link', { name: 'Drafts' })).toHaveAttribute('href', '/draft')
    expect(screen.getByRole('link', { name: 'Projections' })).toHaveAttribute(
      'href',
      '/projections',
    )
    expect(screen.getByRole('link', { name: 'Reliability' })).toHaveAttribute(
      'href',
      '/reliability',
    )
    expect(screen.getByRole('link', { name: 'Schedule' })).toHaveAttribute('href', '/schedule')
    expect(screen.getByRole('link', { name: 'System' })).toHaveAttribute('href', '/system')
    expect(screen.getAllByText('Evidence only')).toHaveLength(3)
  })

  it('distinguishes an empty database from a missing surface', async () => {
    mockFetch({
      '/api/v1/drafts': { body: { drafts: [] } },
    })

    renderPage()

    expect(
      await screen.findByText(/The draft surfaces exist, but this database has no recorded drafts/),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('draft-launch')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Drafts' })).toHaveAttribute('href', '/draft')
  })

  it('keeps static destinations available when the draft read fails', async () => {
    mockFetch({
      '/api/v1/drafts': {
        status: 403,
        body: {
          error: 'drafts_local_only',
          detail: 'draft reads are local only',
          request_id: 'req-dashboard-drafts',
        },
      },
    })

    renderPage()

    expect(await screen.findByText('Could not load the draft launch data.')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Recorded drafts are served to this machine only',
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Request req-dashboard-drafts')
    expect(screen.getByRole('link', { name: 'Projections' })).toHaveAttribute(
      'href',
      '/projections',
    )
  })
})
