/**
 * The draft board, driven against payloads recorded from a real backend.
 *
 * ## Why these tests are shaped the way they are
 *
 * The sharpest finding in this repository today: the backend lane put a tripwire
 * in an error handler, drove a genuine violation through it, and ran the whole
 * suite — `1373 passed`, and **zero tests reached the handler**. Every conflict
 * in 1,373 tests came from an optimistic check that never touched the database.
 * A blanket `except` survived a code review, a mutation matrix and a green
 * PostgreSQL run simultaneously, because the suite had *"does not contradict"*
 * where it needed *"reaches"*.
 *
 * So the error-state block below does not assert that nothing bad renders. It
 * drives **every refusal body captured from the live API**, one per case, and
 * asserts the count of states actually reached equals the number of refusals in
 * the fixture. If a fixture entry stopped being exercised, the count moves.
 *
 * The refusals are real, captured against the running service and committed at
 * `src/test/fixtures/draft-refusals.recorded.json` — including the 409, which is
 * the one this screen must treat differently from the rest.
 */

import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import auctionEvents from '../test/fixtures/draft-auction-events.recorded.json'
import auctionState from '../test/fixtures/draft-auction-state.recorded.json'
import refusals from '../test/fixtures/draft-refusals.recorded.json'
import snakeEvents from '../test/fixtures/draft-snake-events.recorded.json'
import snakeState from '../test/fixtures/draft-snake-state.recorded.json'
import { splitRefusalRemedy } from '../components/draftBoardModel'
import { DraftPage, POLL_INTERVAL_MS, STALE_AFTER_MS } from './DraftPage'

interface Refusal {
  status: number
  body: { error: string; detail: string; request_id: string }
}

const REFUSALS = refusals as unknown as Record<string, Refusal>

/** Every refusal actually driven, across every block in this file. */
const reached = new Set<string>()

/**
 * A fetch stub that distinguishes reads from writes.
 *
 * The shared `mockFetch` helper routes on URL substring alone, and this screen
 * GETs and POSTs the same path. Answering a POST with the read payload would
 * make every write appear to succeed.
 */
function stubDraftFetch({
  state,
  events,
  onWrite,
}: {
  state: unknown
  events: unknown
  onWrite?: () => Refusal | { status: number; body: unknown }
}) {
  const writes: unknown[] = []
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const method = init?.method ?? 'GET'

    if (method === 'POST') {
      writes.push(
        typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : null,
      )
      const answer = onWrite?.() ?? { status: 201, body: state }
      return Promise.resolve(
        new Response(JSON.stringify(answer.body), {
          status: answer.status,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    }

    const body = url.includes('/events') ? events : state
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  })

  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, writes }
}

function renderBoard(draftId = '1') {
  return render(
    <MemoryRouter initialEntries={[`/draft/${draftId}`]}>
      <Routes>
        <Route path="/draft/:draftId" element={<DraftPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.stubEnv('TZ', 'UTC')
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the draft board, from recorded payloads', () => {
  it('draws every seat and every log entry the payloads contain', async () => {
    stubDraftFetch({ state: auctionState, events: auctionEvents })
    renderBoard()

    // Assert what was drawn, counted. "No seat is missing" would be satisfied
    // by a board with no seats at all.
    const seats = await screen.findByRole('heading', { name: 'Seats' })
    expect(seats).toBeInTheDocument()
    await waitFor(() => {
      expect(within(screen.getByTestId('log-list')).getAllByRole('listitem')).toHaveLength(18)
    })
    for (const participant of auctionState.participants) {
      expect(screen.getByTestId(`seat-${String(participant.id)}`)).toBeInTheDocument()
    }
    expect(auctionState.participants).toHaveLength(12)
  })

  it('keeps the recorder and the log inside one sticky container, so recording survives a long board', async () => {
    // Driven in a browser on a full 156-slot board: with the log as a sibling of
    // `.draft__panels` the page ran to 11,037px and the Record button was off
    // screen for 11 of the 15.3 screens — the one panel that has to be reachable
    // under an auction clock, unreachable for most of the page. The fix is
    // structural, so this guards the structure rather than the pixel measurement,
    // which jsdom cannot reproduce.
    stubDraftFetch({ state: auctionState, events: auctionEvents })
    const { container } = renderBoard()

    await screen.findByTestId('log-list')

    const panels = container.querySelector('.draft__panels')
    const recorder = container.querySelector('.recorder')
    const log = container.querySelector('.log')

    // Narrowed by throwing rather than by `!`, so a missing element fails here
    // with a name rather than turning the containment checks below into a
    // comparison of two nulls that an empty page would satisfy.
    if (panels === null) throw new Error('no .draft__panels rendered')
    if (recorder === null) throw new Error('no .recorder rendered')
    if (log === null) throw new Error('no .log rendered')

    expect(panels.contains(recorder)).toBe(true)
    expect(panels.contains(log)).toBe(true)
  })

  it('shows the live bid and the remaining budget as two claims, on the one seat that has both', async () => {
    stubDraftFetch({ state: auctionState, events: auctionEvents })
    renderBoard()

    const remaining = await screen.findByTestId('seat-remaining-9')
    const live = screen.getByTestId('seat-live-bid-9')

    // Different figures, said in different words. If they were ever rendered as
    // one number this would be the test that noticed.
    expect(remaining).toHaveTextContent('$200.00')
    expect(live).toHaveTextContent('$150.00')
    expect(live).toHaveTextContent('live on Rune Halvorsen')
    expect(live).toHaveTextContent('not subtracted above')
    expect(screen.getByTestId('seat-9')).toHaveTextContent('left, of sales recorded')

    // Exactly one caveat on the whole board. Counting is the assertion: a query
    // for "no caveat where it does not belong" passes on a board with none.
    const caveats = screen
      .getAllByTestId(/^seat-live-bid-/)
      .map((node) => node.getAttribute('data-testid'))
    expect(caveats).toEqual(['seat-live-bid-9'])
  })

  it('renders money byte-identically to what the backend sent', async () => {
    stubDraftFetch({ state: auctionState, events: auctionEvents })
    renderBoard()

    await screen.findByTestId('seat-remaining-9')
    let checked = 0
    for (const participant of auctionState.participants) {
      const node = screen.getByTestId(`seat-remaining-${String(participant.id)}`)
      // `$200.00`, not `$200`. A float round-trip would pass a numeric
      // comparison and fail this one, which is the point.
      expect(node.textContent).toBe(`$${participant.remaining_budget}`)
      checked += 1
    }
    expect(checked).toBe(12)
  })

  it('offers exactly one guaranteed correction and labels the rest as refusable', async () => {
    stubDraftFetch({ state: auctionState, events: auctionEvents })
    renderBoard()

    await screen.findByTestId('log-list')

    const undo = screen.getAllByRole('button', { name: 'Undo' })
    const tryVoid = screen.getAllByRole('button', { name: 'Try to void' })

    expect(undo).toHaveLength(1)
    expect(screen.getByTestId('log-undo-18')).toBe(undo[0])
    // 18 entries, minus the guaranteed one, minus the voided sale and the void
    // itself, which cannot be corrected at all.
    expect(tryVoid).toHaveLength(15)
    // And the two labels are genuinely different text, not the same affordance
    // twice: the whole design rests on a reader telling them apart at a glance.
    expect(undo[0]?.textContent).not.toBe(tryVoid[0]?.textContent)
  })

  it('stops promising a guaranteed undo once the last entry is itself a correction', async () => {
    // The state a recorder is in the instant after using Undo — the commonest
    // correction under a clock. Found by looking at the demo board in a browser,
    // where the lede promised an Undo that the screen below it did not offer.
    //
    // These are the recorded auction's own entries, cut where that correction
    // landed, so the log is a real log in its real order. Only the log is under
    // assertion here; the budgets belong to the full 18 entries.
    const throughTheCorrection = {
      ...auctionEvents,
      events: auctionEvents.events.filter((event) => event.sequence <= 14),
      last_sequence: 14,
    }
    expect(throughTheCorrection.events).toHaveLength(14)
    expect(throughTheCorrection.events.at(-1)?.event_type).toBe('void')

    stubDraftFetch({ state: auctionState, events: throughTheCorrection })
    renderBoard()

    await screen.findByTestId('log-list')

    // Assert the log drew before asserting anything is missing from it. "No Undo
    // button" is satisfied perfectly by a log that rendered nothing at all.
    expect(screen.getAllByRole('button', { name: 'Try to void' }).length).toBeGreaterThan(0)
    expect(screen.queryAllByRole('button', { name: 'Undo' })).toHaveLength(0)

    // So the standing copy must carry the exception while that is true.
    expect(screen.getByTestId('log-lede')).toHaveTextContent('unless it is itself a correction')
  })

  it('says why the superseded entry and the correction itself cannot be undone', async () => {
    stubDraftFetch({ state: auctionState, events: auctionEvents })
    renderBoard()

    expect(await screen.findByTestId('log-reason-13')).toHaveTextContent(
      'Already corrected by entry 14.',
    )
    expect(screen.getByTestId('log-reason-14')).toHaveTextContent('cannot itself be undone')
    expect(screen.getByTestId('log-voided-13')).toHaveTextContent('withdrawn by #14')
    expect(screen.queryByTestId('log-undo-13')).not.toBeInTheDocument()
    expect(screen.queryByTestId('log-tryvoid-14')).not.toBeInTheDocument()
  })

  it('reduces an ordered draft to a single field, because the seat is already fixed', async () => {
    stubDraftFetch({ state: snakeState, events: snakeEvents })
    renderBoard('2')

    expect(await screen.findByTestId('recorder-next-pick')).toHaveTextContent('On the clock')
    expect(screen.getByTestId('recorder-player')).toBeInTheDocument()
    // No seat picker and no price: offering a seat choice with exactly one
    // correct answer is a keystroke that can only go wrong.
    expect(screen.queryByTestId('recorder-seat')).not.toBeInTheDocument()
    expect(screen.queryByTestId('recorder-amount')).not.toBeInTheDocument()
  })

  it('drops the player field when a lot is open, rather than validating it', async () => {
    stubDraftFetch({ state: auctionState, events: auctionEvents })
    renderBoard()

    expect(await screen.findByTestId('recorder-open-lot')).toHaveTextContent('Rune Halvorsen')
    // Sale is the default mode, and with a lot open the sale is seat + price.
    expect(screen.queryByTestId('recorder-player')).not.toBeInTheDocument()
    expect(screen.getByTestId('recorder-seat')).toBeInTheDocument()
    expect(screen.getByTestId('recorder-amount')).toBeInTheDocument()
  })
})

describe('recording', () => {
  it('sends the sale the recorder typed, carrying the sequence it was looking at', async () => {
    const { writes } = stubDraftFetch({ state: auctionState, events: auctionEvents })
    renderBoard()

    await screen.findByTestId('recorder-seat')
    await userEvent.selectOptions(screen.getByTestId('recorder-seat'), '9')
    await userEvent.type(screen.getByTestId('recorder-amount'), '151')
    await userEvent.click(screen.getByTestId('recorder-submit'))

    await waitFor(() => {
      expect(writes).toHaveLength(1)
    })
    expect(writes[0]).toEqual({
      event_type: 'sale',
      participant_id: 9,
      amount: '151',
      expected_last_sequence: 18,
    })
  })

  it('posts a void naming the entry, not an edit', async () => {
    const { writes } = stubDraftFetch({ state: auctionState, events: auctionEvents })
    renderBoard()

    await userEvent.click(await screen.findByTestId('log-undo-18'))

    await waitFor(() => {
      expect(writes).toHaveLength(1)
    })
    expect(writes[0]).toEqual({
      event_type: 'void',
      supersedes_sequence: 18,
      expected_last_sequence: 18,
    })
  })
})

describe('every recorded refusal, reached', () => {
  // Registered into the file-scoped `reached` set and checked in `afterAll`,
  // not in a trailing `it`. A trailing `it` runs when *this block* ends, so a
  // refusal driven by a later block counted as undriven -- which is how the
  // check reported a shortfall that was not real. `afterAll` at file scope
  // cannot be outrun by a describe added below it.

  it('leads a refused non-tail void with the backend’s own wording, not this build’s copy for the code', async () => {
    const refusal = REFUSALS['void-non-tail']!
    stubDraftFetch({
      state: auctionState,
      events: auctionEvents,
      onWrite: () => refusal,
    })
    renderBoard()

    await userEvent.click(await screen.findByTestId('log-tryvoid-5'))

    const headline = await screen.findByTestId('log-failure-5')
    // Verbatim, including the sequence number, which is the only actionable
    // part and the first casualty of any paraphrase.
    expect(headline).toHaveTextContent(refusal.body.detail)
    expect(headline).toHaveTextContent('sequence 6')
    // The instruction is asserted as a *property of the recorded detail* rather
    // than as a literal. The literal here used to be "Void back from the most
    // recent event instead"; the base moved to `ce4c603` and the backend now
    // says "To void sequence 5, void back from sequence 15 to sequence 6
    // first." Pinning the sentence again would just reschedule this failure.
    //
    // What must hold is that the refusal tells the recorder which sequence to
    // deal with first, and that the screen shows that sentence rather than a
    // paraphrase of it.
    expect(refusal.body.detail).toMatch(/to void sequence \d+/i)
    const instruction = /to void sequence \d+[^.]*\./i.exec(refusal.body.detail)
    if (instruction === null) throw new Error('the fixture carries no instruction to assert on')
    expect(headline).toHaveTextContent(instruction[0])

    // And specifically NOT this build's copy for `draft_player_label_required`,
    // which describes a field the void form does not have. Driving this in a
    // browser is how the misreading was found: the code on a refused non-tail
    // void is the *later* entry's precondition, not this action's.
    expect(headline).not.toHaveTextContent(/as the recorder saw the name written/i)
    // And nothing beneath it re-adds an instruction about that field either.
    // The same misreading appeared one line down as "Type the player name and
    // submit again" before this was pinned.
    const alert = headline.closest('[role="alert"]')
    expect(alert).not.toBeNull()
    expect(alert?.textContent ?? '').not.toMatch(/Type the player name/i)
    expect(screen.queryByTestId('log-failure-backend-5')).not.toBeInTheDocument()
    reached.add('void-non-tail')
  })

  it('shows a refused void of a void', async () => {
    const refusal = REFUSALS['void-a-void']!
    stubDraftFetch({ state: auctionState, events: auctionEvents, onWrite: () => refusal })
    renderBoard()

    await userEvent.click(await screen.findByTestId('log-tryvoid-5'))
    expect(await screen.findByTestId('log-failure-5')).toHaveTextContent(refusal.body.detail)
    reached.add('void-a-void')
  })

  it('keeps this build’s explanation as the headline when the code really is about the void posted', async () => {
    // A sequence conflict is the one refusal of a void that is genuinely about
    // the void itself rather than a later entry, so the human explanation leads
    // and the server's sentence supports it. Without this the rule above would
    // be a blanket rather than a distinction.
    const refusal = REFUSALS['sequence-conflict']!
    stubDraftFetch({ state: auctionState, events: auctionEvents, onWrite: () => refusal })
    renderBoard()

    await userEvent.click(await screen.findByTestId('log-undo-18'))

    expect(await screen.findByTestId('log-failure-18')).toHaveTextContent(
      /Another append reached this draft after this screen last read it/i,
    )
    expect(screen.getByTestId('log-failure-backend-18')).toHaveTextContent(refusal.body.detail)
  })

  it('tells the recorder a conflicting write was not recorded, and keeps what they typed', async () => {
    const refusal = REFUSALS['sequence-conflict']!
    expect(refusal.status).toBe(409)
    stubDraftFetch({ state: auctionState, events: auctionEvents, onWrite: () => refusal })
    renderBoard()

    await screen.findByTestId('recorder-seat')
    await userEvent.selectOptions(screen.getByTestId('recorder-seat'), '9')
    await userEvent.type(screen.getByTestId('recorder-amount'), '151')
    await userEvent.click(screen.getByTestId('recorder-submit'))

    expect(await screen.findByTestId('recorder-error-summary')).toHaveTextContent(
      /Another append reached this draft after this screen last read it/i,
    )
    // The form still holds what was typed. On a conflict the entry was correct
    // and merely stale, and retyping it under a clock is the cost this avoids.
    expect(screen.getByTestId('recorder-amount')).toHaveValue('151')
    expect(screen.getByTestId('recorder-error-code')).toHaveTextContent('draft_sequence_conflict')
    reached.add('sequence-conflict')
  })

  it('shows a refused bid in the backend’s own terms', async () => {
    const refusal = REFUSALS['bid-not-increasing']!
    stubDraftFetch({ state: auctionState, events: auctionEvents, onWrite: () => refusal })
    renderBoard()

    await userEvent.click(await screen.findByTestId('recorder-mode-bid'))
    await userEvent.selectOptions(screen.getByTestId('recorder-seat'), '9')
    await userEvent.type(screen.getByTestId('recorder-amount'), '150')
    await userEvent.click(screen.getByTestId('recorder-submit'))

    expect(await screen.findByTestId('recorder-error-backend')).toHaveTextContent(
      refusal.body.detail,
    )
    reached.add('bid-not-increasing')
  })

  it('shows a refused over-budget sale', async () => {
    const refusal = REFUSALS['budget-exceeded']!
    stubDraftFetch({ state: auctionState, events: auctionEvents, onWrite: () => refusal })
    renderBoard()

    await screen.findByTestId('recorder-seat')
    await userEvent.selectOptions(screen.getByTestId('recorder-seat'), '9')
    await userEvent.type(screen.getByTestId('recorder-amount'), '999')
    await userEvent.click(screen.getByTestId('recorder-submit'))

    expect(await screen.findByTestId('recorder-error-backend')).toHaveTextContent(
      refusal.body.detail,
    )
    reached.add('budget-exceeded')
  })

  it('shows a refused unknown seat', async () => {
    const refusal = REFUSALS['unknown-participant']!
    stubDraftFetch({ state: auctionState, events: auctionEvents, onWrite: () => refusal })
    renderBoard()

    await screen.findByTestId('recorder-seat')
    await userEvent.selectOptions(screen.getByTestId('recorder-seat'), '9')
    await userEvent.type(screen.getByTestId('recorder-amount'), '5')
    await userEvent.click(screen.getByTestId('recorder-submit'))

    expect(await screen.findByTestId('recorder-error-backend')).toHaveTextContent(
      refusal.body.detail,
    )
    reached.add('unknown-participant')
  })

  it('drove every refusal the fixture holds', () => {
    // A count is asserted, but the *set* comparison is what carries it: the
    // number alone would be satisfied by driving one refusal seven times.
    // Checked in `afterAll` below so a block added after this one still counts.
    expect(Object.keys(REFUSALS).length).toBeGreaterThan(0)
  })
})

afterAll(() => {
  // Reports the states observed against the fixtures available, at the point
  // where every block has run. A fixture that stopped being driven -- or one
  // added without a case -- fails here rather than shrinking the suite quietly.
  expect([...reached].sort()).toEqual(Object.keys(REFUSALS).sort())
})

describe('an error code this build has never seen', () => {
  it('shows the server’s own message rather than swallowing it', async () => {
    // `draft_row_rejected` arrived at backend head `5ec3d0f` on a reworded
    // existing case with the OpenAPI document byte-identical, so a generator
    // could not have shown it. A code allow-list here cannot be kept complete
    // and would fail silently; the fallback promotes the server's `detail` to
    // the headline instead.
    stubDraftFetch({
      state: auctionState,
      events: auctionEvents,
      onWrite: () => ({
        status: 422,
        body: {
          error: 'draft_row_rejected',
          detail: 'Sale names player 4242, which is not a player row.',
          request_id: 'req-unknown-code',
        },
      }),
    })
    renderBoard()

    await screen.findByTestId('recorder-seat')
    await userEvent.selectOptions(screen.getByTestId('recorder-seat'), '9')
    await userEvent.type(screen.getByTestId('recorder-amount'), '5')
    await userEvent.click(screen.getByTestId('recorder-submit'))

    const summary = await screen.findByTestId('recorder-error-summary')
    expect(summary).toHaveTextContent('Sale names player 4242, which is not a player row.')
    expect(screen.getByTestId('recorder-error-code')).toHaveTextContent('draft_row_rejected')
  })
})

describe('the no-decision-numbers rule', () => {
  it('renders none of the terms the API deliberately does not publish', async () => {
    stubDraftFetch({ state: auctionState, events: auctionEvents })
    const { container } = renderBoard()
    await screen.findByTestId('log-list')

    // Word-boundary matched against the rendered text. Substring matching would
    // fire on "invaluable" and on the page's own sentence saying these do not
    // exist here — which is why the lede is excluded below by matching only the
    // panels.
    const panels = container.querySelector('.draft__panels')
    const log = container.querySelector('.log')
    expect(panels).not.toBeNull()
    expect(log).not.toBeNull()
    const rendered = `${panels?.textContent ?? ''} ${log?.textContent ?? ''}`
    expect(rendered.length).toBeGreaterThan(200)

    const forbidden = [
      'projected',
      'projection',
      'valuation',
      'z-score',
      'g-score',
      'inflation',
      'tier',
      'rank',
      'p(play)',
      'availability',
      'expected value',
      'suggested',
      'recommend',
      'target price',
      'par value',
      'surplus',
      'upside',
      'sleeper',
      'bust',
    ]
    const found = forbidden.filter((term) =>
      new RegExp(`\\b${term.replace(/[().]/g, '\\$&')}`, 'i').test(rendered),
    )
    expect(found).toEqual([])
  })
})

/**
 * The board when reads stop coming back — and what I found trying to test it.
 *
 * `frontend.md` lists "loading, empty, error and stale-data states handled" as a
 * done criterion. This screen appeared to pass it: blocking `fetch` in a real
 * browser for twelve seconds produced a banner reading "Showing data from
 * 12:19:28 AM", so the state renders. Before this block, no test in this file
 * entered it — the string `stale` appeared once, in a comment about a sequence
 * conflict.
 *
 * So I wrote the tests below, and then did the thing that matters: **deleted
 * `staleAfterMs` from DraftPage to watch them fail.** All 23 still passed.
 *
 * The reason is worth more than the test. `AsyncBoundary` renders the banner on
 * `isStale || refreshFailed || refreshPending`. This screen polls every two
 * seconds, so data can only age if a read fails (`refreshFailed`) or is in
 * flight (`refreshPending`) — both of which raise the banner on their own.
 * `isStale` never decides anything here, and **`staleAfterMs` on this screen is
 * unreachable configuration**. The browser observation that "the stale state
 * works" was true about the banner and wrong about the mechanism.
 *
 * It is left wired deliberately, as a backstop for the day polling learns to
 * pause (a hidden tab, a paused board), which would age `fetchedAt` with no
 * request outstanding. It is documented here rather than deleted because a
 * future reader deserves to know it is currently inert, and rather than claimed
 * as covered because it is not.
 *
 * What these tests do cover is the state a recorder actually hits mid-auction:
 * the backend stops answering, the board must say so, and must not blank the
 * prices that did arrive. Proven to fire — with reads that succeed instead of
 * failing, the banner is absent and both fail on the missing banner.
 */
describe('the board when reads stop coming back', () => {
  it('says the board is stale, and keeps showing the last good board', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      let call = 0
      vi.stubGlobal(
        'fetch',
        vi.fn((input: RequestInfo | URL) => {
          const url =
            typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
          call += 1
          // The first pass of reads succeeds, everything after it fails outright
          // -- the shape a recorder hits when the backend goes away mid-auction.
          if (call > 2) return Promise.reject(new TypeError('Failed to fetch'))
          return Promise.resolve(
            new Response(JSON.stringify(url.includes('/events') ? auctionEvents : auctionState), {
              status: 200,
              headers: { 'Content-Type': 'application/json' },
            }),
          )
        }),
      )

      renderBoard()
      await screen.findByTestId('log-list')

      await act(async () => {
        await vi.advanceTimersByTimeAsync(STALE_AFTER_MS + POLL_INTERVAL_MS * 2)
      })

      // Reaches the state: the banner is present and names a time.
      const banner = await screen.findByText(/showing data from/i)
      expect(banner).toBeInTheDocument()

      // And the board underneath is still the last good one, not blanked. A
      // recorder mid-auction needs the prices that did arrive.
      expect(within(screen.getByTestId('log-list')).getAllByRole('listitem')).toHaveLength(18)
      expect(screen.getByTestId('recorder-submit')).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('reaches the failure detail, with the backend transport wording', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      let call = 0
      vi.stubGlobal(
        'fetch',
        vi.fn((input: RequestInfo | URL) => {
          const url =
            typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
          call += 1
          if (call > 2) return Promise.reject(new TypeError('Failed to fetch'))
          return Promise.resolve(
            new Response(JSON.stringify(url.includes('/events') ? auctionEvents : auctionState), {
              status: 200,
              headers: { 'Content-Type': 'application/json' },
            }),
          )
        }),
      )

      renderBoard()
      await screen.findByTestId('log-list')

      await act(async () => {
        await vi.advanceTimersByTimeAsync(STALE_AFTER_MS + POLL_INTERVAL_MS * 2)
      })

      const refresh = await screen.findByRole('button', { name: /refresh/i })
      await act(async () => {
        refresh.click()
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
      })

      await waitFor(() => {
        expect(screen.getByTestId('async-stale-failure')).toBeInTheDocument()
      })
      // The recorder must be told nothing was written, not merely that a read
      // failed -- a poll failing and an append failing look identical otherwise.
      expect(screen.getByTestId('async-stale-failure').textContent).toMatch(/nothing was recorded/i)
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps the stale threshold clear of the poll interval, for when it is live', () => {
    // Inert today (see the block comment), so this pins intent rather than
    // behaviour: if polling ever pauses and `isStale` starts deciding, a window
    // shorter than the poll would mark a healthy board stale between two good
    // reads. Two intervals of headroom.
    expect(STALE_AFTER_MS).toBeGreaterThan(POLL_INTERVAL_MS * 2)
  })
})

describe('a refusal that carries two competing instructions', () => {
  const refusal = REFUSALS['void-replay-two-instructions']!

  it('splits off the remedy that works without changing a character', () => {
    const { lead, remedy } = splitRefusalRemedy(refusal.body.detail)
    // The property the whole approach rests on: this is emphasis, not editing.
    expect(lead + (remedy ?? '')).toBe(refusal.body.detail)
    if (remedy === null) throw new Error('the recorded refusal carries no remedy to weight')
    expect(remedy).toMatch(/^To void sequence \d+,/)
    // The advice about the hypothetical replayed log stays on screen, in the
    // lead. Dropping it would be paraphrasing the backend.
    expect(lead).toContain('Record the sale, or void the nomination at sequence 5.')
  })

  it('leaves a single-instruction refusal untouched', () => {
    const single = REFUSALS['void-a-void']!.body.detail
    const { lead, remedy } = splitRefusalRemedy(single)
    expect(remedy).toBeNull()
    expect(lead).toBe(single)
  })

  it('renders the whole sentence, with the working remedy weighted', async () => {
    stubDraftFetch({ state: auctionState, events: auctionEvents, onWrite: () => refusal })
    renderBoard()

    await userEvent.click(await screen.findByTestId('log-tryvoid-6'))

    const headline = await screen.findByTestId('log-failure-6')
    // Verbatim and whole, still.
    expect(headline).toHaveTextContent(refusal.body.detail)

    // And the emphasised part is the outer remedy, not the inner advice.
    const remedy = screen.getByTestId('log-remedy-6')
    expect(remedy.textContent).toMatch(/^To void sequence 6,/)
    expect(remedy.textContent).not.toContain('Record the sale')
    expect(remedy.tagName).toBe('STRONG')
    reached.add('void-replay-two-instructions')
  })
})


