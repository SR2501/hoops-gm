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
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import auctionEvents from '../test/fixtures/draft-auction-events.recorded.json'
import auctionState from '../test/fixtures/draft-auction-state.recorded.json'
import snakeEvents from '../test/fixtures/draft-snake-events.recorded.json'
import snakeState from '../test/fixtures/draft-snake-state.recorded.json'
import type * as DraftBoardModelModule from '../components/draftBoardModel'
import { buildDraftBoardModel } from '../components/draftBoardModel'
import { DraftPage, POLL_INTERVAL_MS } from './DraftPage'

vi.mock('../components/draftBoardModel', async (importOriginal) => {
  const actual = await importOriginal<typeof DraftBoardModelModule>()
  return { ...actual, buildDraftBoardModel: vi.fn(actual.buildDraftBoardModel) }
})

const buildModel = vi.mocked(buildDraftBoardModel)

const NO_SOURCE_READING = {
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
} as const

/**
 * Answers reads from the recorded fixtures, with the events page's
 * `last_sequence` under the test's control.
 */
function stubReads(sequenceFor: (poll: number) => number) {
  let poll = 0
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    if (url.includes('/source-board')) {
      return Promise.resolve(
        new Response(JSON.stringify(NO_SOURCE_READING), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    }
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

/**
 * The two properties the 2026-08-27 restructure could have broken.
 *
 * `DraftPage` used to call `useAsync` before rendering its "not a draft id"
 * refusal, so a malformed id fired `GET /api/v1/drafts/NaN` first. The fix
 * splits the component so the hook only mounts for a valid id — and a split
 * moves `lastBundleRef` into the child, which is precisely the state the poll
 * skip above depends on.
 *
 * The skip itself was already covered, with a control. **The cross-draft keying
 * was not**, and the restructure makes it load-bearing: `DraftBoardLoader`
 * stays mounted across a draft change, so its ref survives, so a bundle from
 * draft 1 is reachable while rendering draft 2 if the id is not compared. That
 * gap is closed here rather than left as a thing the diff happened not to
 * disturb.
 */
describe('the board after the invalid-id restructure', () => {
  it('makes no request at all for an id that is not one', async () => {
    const fetchMock = stubReads(() => 0)

    render(
      <MemoryRouter initialEntries={['/draft/not-a-number']}>
        <Routes>
          <Route path="/draft/:draftId" element={<DraftPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('alert')).toHaveTextContent('is not a draft id')
    // The assertion the restructure exists for. Before it, this was
    // `['/api/v1/drafts/NaN', '/api/v1/drafts/NaN/events']`.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50))
    })
    expect(fetchMock.mock.calls).toEqual([])
  })

  it('does not serve one draft board while showing another draft', async () => {
    // Both logs report the **same** `last_sequence`, which is the only way the
    // keying is discriminating: per-draft counters collide constantly, and
    // draft 2's entry 12 is not draft 1's. Without `previous.draftId ===
    // draftId` the second draft's poll matches on the sequence alone and hands
    // back the first draft's bundle, so the board keeps the old name.
    const sharedSequence = 12
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      const forSnake = url.includes('/drafts/2')
      const state = forSnake ? snakeState : auctionState
      const events = forSnake ? snakeEvents : auctionEvents
      const body = url.includes('/source-board')
        ? { ...NO_SOURCE_READING, draft_id: forSnake ? 2 : 1 }
        : url.includes('/events')
          ? { ...events, last_sequence: sharedSequence }
          : state
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    })
    vi.stubGlobal('fetch', fetchMock)

    // A real navigation, not a re-render with different props. `MemoryRouter`
    // reads `initialEntries` once at mount, so re-rendering it with a new path
    // changes nothing and the first version of this test failed for that reason
    // rather than for the one it was written to detect — which is exactly the
    // "red arriving for the wrong reason" the gate warns about. A plain router
    // driven by a link click rather than `createMemoryRouter`, because the data
    // router constructs a `Request` whose `AbortSignal` jsdom rejects.
    render(
      <MemoryRouter initialEntries={['/draft/1']}>
        <Link to="/draft/2">go to the snake draft</Link>
        <Routes>
          <Route path="/draft/:draftId" element={<DraftPage />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByText(auctionState.name)).toBeInTheDocument()

    await userEvent.click(screen.getByText('go to the snake draft'))

    expect(await screen.findByText(snakeState.name)).toBeInTheDocument()
    expect(screen.queryByText(auctionState.name)).not.toBeInTheDocument()
  })
})
