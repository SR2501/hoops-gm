import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import auctionEvents from '../test/fixtures/draft-auction-events.recorded.json'
import auctionState from '../test/fixtures/draft-auction-state.recorded.json'
import snakeEvents from '../test/fixtures/draft-snake-events.recorded.json'
import snakeState from '../test/fixtures/draft-snake-state.recorded.json'
import type { SourceBoardResponse } from '../api/draftTypes'
import { DraftPage } from './DraftPage'

const noReading: SourceBoardResponse = {
  draft_id: 1,
  as_of: '2026-08-29T18:00:00Z',
  status: 'no_reading',
  refusal_reason: null,
  contact_at: null,
  contact_age_seconds: null,
  board: null,
  board_age_seconds: null,
  regressions: [],
  caveats: [
    'source_seat is a rendered column ordinal, not DraftParticipant.team_slot or identity',
    'seat labels are mutable display evidence and are never matched to participants',
    'an exact-content undo reuses an existing artifact key and cannot appear as a new regression',
    'evidence is from one football snake draft; NBA and auction board support is unestablished',
  ],
}

function availableSource(draftId: number, playerLabel: string): SourceBoardResponse {
  return {
    ...noReading,
    draft_id: draftId,
    status: 'available',
    contact_at: '2026-08-29T18:00:00Z',
    contact_age_seconds: 1,
    board_age_seconds: 1,
    board: {
      artifact_key: `board:${String(draftId)}`,
      recogniser: 'board_dom',
      observed_at: '2026-08-29T18:00:00Z',
      layout: 'snake',
      seat_count: 1,
      round_count: 1,
      picks_made: 1,
      columns: [
        {
          source_seat: 1,
          mutable_label: `Draft ${String(draftId)} label`,
          picks: [
            {
              source_seat: 1,
              round_number: 1,
              pick_in_round: 1,
              overall_pick: 1,
              player_label: playerLabel,
              player_external_id: null,
            },
          ],
        },
      ],
    },
  }
}

function renderBoard() {
  return render(
    <MemoryRouter initialEntries={['/draft/1']}>
      <Routes>
        <Route path="/draft/:draftId" element={<DraftPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the source-board request on the draft page', () => {
  it('shows source loading without holding back the authoritative board', async () => {
    let resolveSource = (_value: Response): void => {
      throw new Error('source request did not start')
    }
    const pendingSource = new Promise<Response>((resolve) => {
      resolveSource = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
        if (url.includes('/source-board')) return pendingSource
        return Promise.resolve(response(url.includes('/events') ? auctionEvents : auctionState))
      }),
    )

    renderBoard()

    expect(await screen.findByTestId('log-list')).toBeInTheDocument()
    expect(screen.getByText('Loading rendered source-board evidence…')).toBeInTheDocument()

    resolveSource(response(noReading))
    expect(await screen.findByTestId('source-board-no-reading')).toBeInTheDocument()
  })

  it('keeps the authoritative board when only source evidence fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
        if (url.includes('/source-board')) {
          return Promise.resolve(
            response(
              {
                error: 'source_board_unavailable',
                detail: 'Rendered board capture is unavailable.',
                request_id: 'req-source-failed',
              },
              503,
            ),
          )
        }
        return Promise.resolve(response(url.includes('/events') ? auctionEvents : auctionState))
      }),
    )

    renderBoard()

    expect(await screen.findByTestId('log-list')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Seats' })).toBeInTheDocument()
    expect(await screen.findByText(/authoritative participant\/event board above is unchanged/i))
      .toBeInTheDocument()
    expect(screen.getByText('Rendered board capture is unavailable.')).toBeInTheDocument()
  })

  it('clears the previous draft source reading through the next draft loading and failure', async () => {
    let failSecondSource = (_value: Response): void => {
      throw new Error('second source request did not start')
    }
    const pendingSecondSource = new Promise<Response>((resolve) => {
      failSecondSource = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
        const forSecondDraft = url.includes('/drafts/2')

        if (url.includes('/source-board')) {
          return forSecondDraft
            ? pendingSecondSource
            : Promise.resolve(response(availableSource(1, 'Draft one source player')))
        }

        if (url.includes('/events')) {
          return Promise.resolve(response(forSecondDraft ? snakeEvents : auctionEvents))
        }
        return Promise.resolve(response(forSecondDraft ? snakeState : auctionState))
      }),
    )

    render(
      <MemoryRouter initialEntries={['/draft/1']}>
        <Link to="/draft/2">Open draft two</Link>
        <Routes>
          <Route path="/draft/:draftId" element={<DraftPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Draft one source player')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('link', { name: 'Open draft two' }))

    expect(await screen.findByText('Loading rendered source-board evidence…')).toBeInTheDocument()
    expect(screen.queryByText('Draft one source player')).not.toBeInTheDocument()

    failSecondSource(
      response(
        {
          error: 'source_board_unavailable',
          detail: 'Draft two source board did not answer.',
          request_id: 'req-source-draft-two',
        },
        503,
      ),
    )

    expect(await screen.findByText('Draft two source board did not answer.')).toBeInTheDocument()
    expect(screen.queryByText('Draft one source player')).not.toBeInTheDocument()
  })
})
