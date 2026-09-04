import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import auctionStateFixture from '../test/fixtures/draft-auction-state.recorded.json'
import type { DraftEvent, DraftState } from '../api/draftTypes'
import { buildDraftBoardModel } from './draftBoardModel'
import { DraftLog, RECENT_LOG_ENTRY_LIMIT } from './DraftLog'

const auctionState = auctionStateFixture as unknown as DraftState

function largeDraft(sequenceCount = 170) {
  const events: DraftEvent[] = Array.from({ length: sequenceCount }, (_, index) => {
    const sequence = index + 1
    return {
      sequence,
      event_type: sequence === 42 ? 'nomination' : 'pick',
      participant_id: sequence === 88 ? 12 : 1,
      player_id: null,
      player_label: `Synthetic Player ${String(sequence).padStart(3, '0')}`,
      amount: sequence === 42 ? '1.00' : null,
      supersedes_sequence: null,
      occurred_at: null,
      note: null,
      voided_by_sequence: null,
    }
  })
  const state: DraftState = {
    ...auctionState,
    last_sequence: sequenceCount,
    live_event_count: sequenceCount,
    selections_made: sequenceCount,
  }
  return {
    state,
    model: buildDraftBoardModel(state, events),
  }
}

function renderedSequences(): number[] {
  return within(screen.getByTestId('log-list'))
    .getAllByRole('listitem')
    .map((item) => Number(item.getAttribute('data-testid')?.replace('log-entry-', '')))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('DraftLog under a full auction log', () => {
  it('defaults to one chronological recent tail and reports it against the complete cohort', () => {
    const { model } = largeDraft()

    render(<DraftLog model={model} onRecorded={vi.fn()} />)

    expect(RECENT_LOG_ENTRY_LIMIT).toBe(13)
    expect(renderedSequences()).toEqual(
      Array.from(
        { length: RECENT_LOG_ENTRY_LIMIT },
        (_, index) => 170 - RECENT_LOG_ENTRY_LIMIT + index + 1,
      ),
    )
    expect(screen.getByTestId('log-count')).toHaveTextContent(
      'Showing 13 recent entries of 170 total.',
    )
    expect(screen.queryByTestId('log-entry-157')).not.toBeInTheDocument()
  })

  it('searches all 170 entries by sequence, player, event type, and participant label', async () => {
    const user = userEvent.setup()
    const { model } = largeDraft()
    render(<DraftLog model={model} onRecorded={vi.fn()} />)
    const search = screen.getByRole('searchbox', { name: 'Search complete log' })

    await user.type(search, 'sequence 7')
    expect(renderedSequences()).toEqual([7])
    expect(screen.getByTestId('log-count')).toHaveTextContent('1 matching entry from 170 total.')

    await user.clear(search)
    await user.type(search, 'Synthetic Player 042')
    expect(renderedSequences()).toEqual([42])

    await user.clear(search)
    await user.type(search, 'nomination')
    expect(renderedSequences()).toEqual([42])

    await user.clear(search)
    await user.type(search, 'Garbage Time')
    expect(renderedSequences()).toEqual([88])
  })

  it('provides complete-history access without calling unmounted rows visible', async () => {
    const user = userEvent.setup()
    const { model } = largeDraft()
    render(<DraftLog model={model} onRecorded={vi.fn()} />)

    const toggle = screen.getByRole('button', { name: 'Show complete history' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('list', { name: 'Recent draft log entries' })).toBeInTheDocument()

    await user.click(toggle)

    expect(renderedSequences()).toEqual(Array.from({ length: 170 }, (_, index) => index + 1))
    expect(screen.getByTestId('log-count')).toHaveTextContent('Showing all 170 entries.')
    expect(
      screen.getByRole('list', { name: 'Complete draft log history' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show recent entries' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })

  it('distinguishes no search match from an empty log', async () => {
    const user = userEvent.setup()
    const { model, state } = largeDraft()
    const view = render(<DraftLog model={model} onRecorded={vi.fn()} />)

    await user.type(
      screen.getByRole('searchbox', { name: 'Search complete log' }),
      'not in this draft',
    )
    expect(screen.getByTestId('log-no-results')).toHaveTextContent(
      'No log entries match not in this draft. The complete log contains 170 entries.',
    )
    expect(screen.getByTestId('log-count')).toHaveTextContent('0 matching entries from 170 total.')
    expect(screen.queryByTestId('log-list')).not.toBeInTheDocument()
    expect(screen.queryByTestId('log-empty')).not.toBeInTheDocument()

    view.rerender(
      <DraftLog
        model={buildDraftBoardModel({ ...state, last_sequence: 0, live_event_count: 0 }, [])}
        onRecorded={vi.fn()}
      />,
    )
    expect(screen.getByTestId('log-empty')).toHaveTextContent(
      'Nothing has been recorded against this draft yet.',
    )
    expect(screen.queryByTestId('log-no-results')).not.toBeInTheDocument()
  })

  it('retains search and history mode across a poll-style model replacement', async () => {
    const user = userEvent.setup()
    const first = largeDraft()
    const view = render(<DraftLog model={first.model} onRecorded={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Show complete history' }))
    const search = screen.getByRole('searchbox', { name: 'Search complete log' })
    await user.type(search, 'Synthetic Player 007')

    const refreshed = largeDraft(171)
    view.rerender(<DraftLog model={refreshed.model} onRecorded={vi.fn()} />)

    expect(screen.getByRole('searchbox', { name: 'Search complete log' })).toHaveValue(
      'Synthetic Player 007',
    )
    expect(screen.getByRole('button', { name: 'Show recent entries' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(renderedSequences()).toEqual([7])
    expect(screen.getByTestId('log-count')).toHaveTextContent('1 matching entry from 171 total.')

    await user.clear(search)
    expect(renderedSequences()).toHaveLength(171)
    expect(screen.getByTestId('log-count')).toHaveTextContent('Showing all 171 entries.')
  })

  it('keeps the older matched event correction affordance and posts its real sequence', async () => {
    const user = userEvent.setup()
    const { model, state } = largeDraft()
    const onRecorded = vi.fn()
    let requestBody: string | undefined
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      requestBody = typeof init?.body === 'string' ? init.body : undefined
      return Promise.resolve(
        new Response(JSON.stringify(state), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<DraftLog model={model} onRecorded={onRecorded} />)

    await user.type(screen.getByRole('searchbox', { name: 'Search complete log' }), 'sequence 7')
    await user.click(screen.getByTestId('log-tryvoid-7'))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })
    if (requestBody === undefined) throw new Error('void request carried no JSON body')
    expect(JSON.parse(requestBody)).toEqual({
      event_type: 'void',
      supersedes_sequence: 7,
      expected_last_sequence: 170,
    })
    expect(onRecorded).toHaveBeenCalledWith(state)
  })
})
