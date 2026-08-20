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
        <AsyncBoundary state={state} label="test data">
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
    expect(screen.getByRole('status')).toHaveTextContent('Refreshing.')
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
