/**
 * What the board does when a poll brings back a draft that has not moved.
 *
 * `last_sequence` is published as a complete version token — append is the log's
 * only mutation, so two responses carrying the same value describe the same
 * draft. `draftTypes.ts` says exactly that at the field, and the reason it was
 * put there was so "a poll compares one integer instead of diffing the payload".
 * Nothing was comparing it. Every two seconds the screen built a fresh bundle,
 * handed it to React as a new object, and re-rendered the whole board.
 *
 * The two halves only work together, which is why they are tested together. The
 * comparison alone changes nothing, because `useAsync` sets `fetchedAt` and
 * `status` on every poll and those reach the parent regardless of what `data`
 * does; the memo alone changes nothing, because a fresh bundle never compares
 * equal. Removing either one puts the re-render back.
 *
 * The count is taken from the model builder rather than from the DOM, because
 * the DOM is the wrong instrument here: React reconciles a re-render to the same
 * markup and mutates nothing, so a MutationObserver reports the same zero either
 * way. Measured in a real browser, the work was invisible in the DOM and real in
 * the render path.
 */

import { act, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import auctionEvents from '../test/fixtures/draft-auction-events.recorded.json'
import auctionState from '../test/fixtures/draft-auction-state.recorded.json'
import type * as DraftBoardModelModule from '../components/draftBoardModel'
import { buildDraftBoardModel } from '../components/draftBoardModel'
import { DraftPage, POLL_INTERVAL_MS } from './DraftPage'

vi.mock('../components/draftBoardModel', async (importOriginal) => {
  const actual = await importOriginal<typeof DraftBoardModelModule>()
  return { ...actual, buildDraftBoardModel: vi.fn(actual.buildDraftBoardModel) }
})

const buildModel = vi.mocked(buildDraftBoardModel)

/**
 * Answers reads from the recorded fixtures, with the events page's
 * `last_sequence` under the test's control.
 */
function stubReads(sequenceFor: (poll: number) => number) {
  let poll = 0
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    if (!url.includes('/events')) {
      return Promise.resolve(
        new Response(JSON.stringify(auctionState), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    }
    poll += 1
    const body = { ...auctionEvents, last_sequence: sequenceFor(poll) }
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
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

describe('the board when a poll brings back a draft that has not moved', () => {
  beforeEach(() => {
    buildModel.mockClear()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('re-reads, and does not rebuild the board', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const recorded = (auctionEvents as { last_sequence: number }).last_sequence
    const fetchMock = stubReads(() => recorded)

    renderBoard()
    await screen.findByTestId('log-list')
    const buildsAfterFirstPaint = buildModel.mock.calls.length
    const readsAfterFirstPaint = fetchMock.mock.calls.length

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3 + 100)
    })

    // The polls really happened. Without this the assertion below is satisfied
    // by a board that simply stopped reading, which is the failure that would
    // matter most and the one a bare "did not rebuild" cannot tell apart.
    expect(fetchMock.mock.calls.length).toBeGreaterThan(readsAfterFirstPaint)
    expect(buildModel.mock.calls.length).toBe(buildsAfterFirstPaint)

    // And the board is still on screen, rather than skipped into nothing.
    expect(screen.getByTestId('log-list')).toBeInTheDocument()
  })

  it('does rebuild when the log has moved, which is what makes the skip a skip', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const recorded = (auctionEvents as { last_sequence: number }).last_sequence
    // Every poll reports a longer log. This is the control for the test above:
    // a counter that never moves would satisfy it by being broken.
    const fetchMock = stubReads((poll) => recorded + poll)

    renderBoard()
    await screen.findByTestId('log-list')
    const buildsAfterFirstPaint = buildModel.mock.calls.length

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3 + 100)
    })

    expect(fetchMock.mock.calls.length).toBeGreaterThan(0)
    expect(buildModel.mock.calls.length).toBeGreaterThan(buildsAfterFirstPaint)
  })
})
