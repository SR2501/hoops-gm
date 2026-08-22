import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { AsyncState } from '../api/useAsync'
import { useAsync } from '../api/useAsync'
import { AsyncBoundary } from './AsyncBoundary'

const unhandledRejection = vi.fn()

afterEach(() => {
  vi.useRealTimers()
  process.off('unhandledRejection', unhandledRejection)
})

function successState<T>(data: T, fetchedAt: Date, reload = vi.fn()): AsyncState<T> {
  return {
    status: 'success',
    data,
    error: null,
    fetchedAt,
    reload,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('AsyncBoundary', () => {
  it('becomes stale exactly at the deadline with one scheduled check', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-19T12:00:00Z'))
    const fetchedAt = new Date()

    render(
      <AsyncBoundary
        state={successState({ value: 'current' }, fetchedAt)}
        staleAfterMs={60_000}
      >
        {(data) => <p>{data.value}</p>}
      </AsyncBoundary>,
    )

    expect(screen.queryByText(/Showing data from/)).not.toBeInTheDocument()
    expect(vi.getTimerCount()).toBe(1)

    act(() => {
      vi.advanceTimersByTime(59_999)
    })
    expect(screen.queryByText(/Showing data from/)).not.toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(screen.getByText(/Showing data from/)).toBeInTheDocument()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('keeps the last good data and exposes refresh failure without an unhandled rejection', async () => {
    const first = deferred<{ value: string }>()
    const second = deferred<{ value: string }>()
    let request = 0
    const fetcher = () => {
      request += 1
      return request === 1 ? first.promise : second.promise
    }
    unhandledRejection.mockClear()
    process.on('unhandledRejection', unhandledRejection)

    function Harness() {
      const state = useAsync(fetcher, [])
      return (
        <AsyncBoundary state={state} label="test data" slowRefreshAfterMs={0}>
          {(data) => (
            <>
              <p>{data.value}</p>
              <button type="button" onClick={state.reload}>
                Reload data
              </button>
            </>
          )}
        </AsyncBoundary>
      )
    }

    render(<Harness />)
    await act(async () => {
      first.resolve({ value: 'last good value' })
      await first.promise
    })

    await userEvent.click(screen.getByRole('button', { name: 'Reload data' }))
    await waitFor(() => {
      expect(request).toBe(2)
    })
    expect(screen.getByText('last good value')).toBeInTheDocument()
    // `slowRefreshAfterMs={0}` on the harness: this test is about what a failed
    // refresh says, not about how long it waits before saying anything.
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('Refreshing.')
    })
    expect(screen.getByRole('button', { name: 'Refreshing…' })).toHaveAttribute(
      'aria-disabled',
      'true',
    )

    await act(async () => {
      second.reject(
        new ApiError(503, 'refresh_unavailable', 'Database refresh failed.', 'req-refresh'),
      )
      await second.promise.catch(() => undefined)
    })

    expect(screen.getByText('last good value')).toBeInTheDocument()
    expect(screen.getByText(/Refresh failed/)).toHaveTextContent('Database refresh failed.')
    expect(screen.getByText(/Refresh failed/)).toHaveTextContent('Code refresh_unavailable.')
    expect(screen.getByText(/Refresh failed/)).toHaveTextContent('Request req-refresh.')
    await new Promise((resolve) => window.setTimeout(resolve, 0))
    expect(unhandledRejection).not.toHaveBeenCalled()
  })

  it('does not let an empty last-good result hide a refresh failure', () => {
    const state: AsyncState<readonly string[]> = {
      status: 'error',
      data: [],
      error: new ApiError(503, 'refresh_unavailable', 'Refresh failed.', 'req-empty-refresh'),
      fetchedAt: new Date(),
      reload: vi.fn(),
    }

    const { rerender } = render(
      <AsyncBoundary state={state} isEmpty={(data) => data.length === 0}>
        {(data) => <p>{data.join(', ')}</p>}
      </AsyncBoundary>,
    )

    expect(screen.getByText('Nothing to show yet.')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Code refresh_unavailable.')
    expect(screen.getByRole('status')).toHaveTextContent('Request req-empty-refresh.')

    rerender(
      <AsyncBoundary
        state={{ ...state, status: 'loading' }}
        isEmpty={(data) => data.length === 0}
      >
        {(data) => <p>{data.join(', ')}</p>}
      </AsyncBoundary>,
    )

    expect(screen.getByText('Nothing to show yet.')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Refreshing.')
  })

  it('uses a view description on both failure paths, not just the cold one', () => {
    const error = new ApiError(409, 'some_code', 'Backend wording.', 'req-custom')
    const describeError = () => ({
      summary: 'A more specific explanation.',
      action: 'And the next thing to do.',
    })

    // Cold: nothing on screen.
    const cold: AsyncState<string> = {
      status: 'error',
      data: null,
      error,
      fetchedAt: null,
      reload: vi.fn(),
    }
    const { rerender } = render(
      <AsyncBoundary state={cold} label="the thing">
        {(data) => <p>{data}</p>}
      </AsyncBoundary>,
    )
    // Without a description, the backend's own wording is still what shows.
    expect(screen.getByTestId('async-error-summary')).toHaveTextContent('Backend wording.')
    expect(screen.queryByTestId('async-error-action')).not.toBeInTheDocument()

    rerender(
      <AsyncBoundary state={cold} label="the thing" describeError={describeError}>
        {(data) => <p>{data}</p>}
      </AsyncBoundary>,
    )
    expect(screen.getByTestId('async-error-summary')).toHaveTextContent(
      'A more specific explanation.',
    )
    expect(screen.getByTestId('async-error-action')).toHaveTextContent('And the next thing to do.')
    // The backend's words survive alongside, so a report can quote them.
    expect(screen.getByText(/Backend said/)).toHaveTextContent('Backend wording.')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()

    // Warm: a refresh failed with earlier data still on screen. This is the
    // path a rendered-panel prop would have silently missed.
    const warm: AsyncState<string> = { ...cold, data: 'earlier value' }
    rerender(
      <AsyncBoundary state={warm} label="the thing" describeError={describeError}>
        {(data) => <p>{data}</p>}
      </AsyncBoundary>,
    )
    const failure = screen.getByTestId('async-stale-failure')
    expect(failure).toHaveTextContent('A more specific explanation.')
    expect(failure).toHaveTextContent('And the next thing to do.')
    expect(failure).toHaveTextContent('Code some_code.')
    expect(screen.getByText('earlier value')).toBeInTheDocument()
  })
})

/**
 * What a background refresh is allowed to say, and when.
 *
 * The defect these were written against: the banner rose on
 * `isStale || refreshFailed || refreshPending`, and `refreshPending` is true
 * during *every* poll. The draft board polls every two seconds, so it flashed a
 * staleness warning about data one second old, twice a minute, for about 40ms
 * each time — **a warning that was false on 100% of its occurrences**. Found by
 * the owner watching the merged screen for ten seconds; 248 tests, a review and
 * a rendered inspection all missed it, because every one of them looks at a
 * single render and this defect only exists across time.
 *
 * Each test below pairs its silence with the sound that follows it. An assertion
 * that the banner is absent is worth nothing on its own — an empty screen
 * satisfies it — so no test here ends on a `not.toBeInTheDocument()`.
 */
describe('AsyncBoundary, on what a refresh announces', () => {
  const board = { value: 'board' }

  function renderBoundary(state: AsyncState<{ value: string }>, staleAfterMs?: number) {
    return render(
      // Spread rather than passed as `undefined`: `exactOptionalPropertyTypes`
      // treats an explicit undefined as a different thing from an absent prop.
      <AsyncBoundary state={state} {...(staleAfterMs === undefined ? {} : { staleAfterMs })}>
        {(data) => <p>{data.value}</p>}
      </AsyncBoundary>,
    )
  }

  it('stays quiet through a quick background refresh, and speaks up for a slow one', () => {
    vi.useFakeTimers()
    const fetchedAt = new Date()
    const settled = successState(board, fetchedAt)
    const { rerender } = renderBoundary(settled)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    rerender(
      <AsyncBoundary state={{ ...settled, status: 'loading' }}>
        {(data) => <p>{data.value}</p>}
      </AsyncBoundary>,
    )

    // The poll the draft board runs every two seconds. It finishes in tens of
    // milliseconds and the reader is told nothing, because nothing is wrong.
    act(() => {
      vi.advanceTimersByTime(999)
    })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    // The silence above only means something because this arrives. A refresh
    // still running after a second may really be showing something old.
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(screen.getByRole('status')).toHaveTextContent('Refreshing.')
  })

  it('announces a refresh the reader asked for without making them wait', () => {
    vi.useFakeTimers()
    const reload = vi.fn()
    // Old enough that the banner — and so its Refresh button — is already up.
    const fetchedAt = new Date(Date.now() - 120_000)
    const settled = successState(board, fetchedAt, reload)
    const { rerender } = renderBoundary(settled, 60_000)

    // The control, in the same test: an unasked-for refresh at this instant
    // says nothing, so the assertion after the click is about the click.
    rerender(
      <AsyncBoundary state={{ ...settled, status: 'loading' }} staleAfterMs={60_000}>
        {(data) => <p>{data.value}</p>}
      </AsyncBoundary>,
    )
    expect(screen.queryByRole('button', { name: 'Refreshing…' })).not.toBeInTheDocument()

    rerender(
      <AsyncBoundary state={settled} staleAfterMs={60_000}>
        {(data) => <p>{data.value}</p>}
      </AsyncBoundary>,
    )
    act(() => {
      screen.getByRole('button', { name: 'Refresh' }).click()
    })
    expect(reload).toHaveBeenCalledTimes(1)

    rerender(
      <AsyncBoundary state={{ ...settled, status: 'loading' }} staleAfterMs={60_000}>
        {(data) => <p>{data.value}</p>}
      </AsyncBoundary>,
    )
    // Not one millisecond advanced.
    expect(screen.getByRole('button', { name: 'Refreshing…' })).toBeInTheDocument()
  })

  it('does not blink the banner out between retries after a failure', () => {
    vi.useFakeTimers()
    const failed: AsyncState<{ value: string }> = {
      status: 'error',
      data: board,
      error: new ApiError(503, 'refresh_unavailable', 'Backend went away.', 'req-retry'),
      fetchedAt: new Date(),
      reload: vi.fn(),
    }
    const { rerender } = renderBoundary(failed)
    expect(screen.getByRole('status')).toHaveTextContent('Refresh failed.')

    rerender(
      <AsyncBoundary state={{ ...failed, status: 'loading' }}>
        {(data) => <p>{data.value}</p>}
      </AsyncBoundary>,
    )

    // Without advancing the clock. Delaying the announcement of a routine poll
    // is right; letting that delay take down a banner that is already up, in the
    // one state it exists for, would have put the flicker back where it does the
    // most harm.
    expect(screen.getByRole('status')).toHaveTextContent('Refreshing.')
  })
})
