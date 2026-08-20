/**
 * `AsyncBoundary` — the component convention for anything that loads data.
 *
 * Every data-bearing view renders through this. It handles loading, error,
 * empty and stale in one place so that no individual view can quietly skip
 * one of them, and so that "this number is old" looks the same everywhere.
 *
 * The staleness threshold is a prop rather than a constant because the honest
 * answer differs by data: a league roster from an hour ago is fine, an injury
 * report from an hour ago is not.
 */

import type { ReactNode } from 'react'
import { ApiError } from '../api/client'
import type { AsyncState } from '../api/useAsync'
import { useIsStale } from '../api/useStale'

interface AsyncBoundaryProps<T> {
  state: AsyncState<T>
  children: (data: T) => ReactNode
  /** Rendered when the request succeeded but returned nothing meaningful. */
  isEmpty?: (data: T) => boolean
  emptyMessage?: string
  /** Age past which the data is shown as stale. Omit for data that cannot go stale. */
  staleAfterMs?: number
  label?: string
  /**
   * Replaces the default error panel.
   *
   * The default panel shows the backend's own wording, which is right for a
   * generic surface but wrong where an endpoint fails closed on several
   * distinct conditions that call for different actions. A view that can say
   * something more useful passes this; everything else keeps the default, so
   * there is still exactly one error convention rather than two.
   */
  renderError?: (error: Error | null, reload: () => void) => ReactNode
}

export function AsyncBoundary<T>({
  state,
  children,
  isEmpty,
  emptyMessage = 'Nothing to show yet.',
  staleAfterMs,
  label = 'data',
  renderError,
}: AsyncBoundaryProps<T>) {
  const { status, data, error, fetchedAt, reload } = state
  const isStale = useIsStale(fetchedAt, staleAfterMs)

  if (status === 'idle' || (status === 'loading' && data === null)) {
    return (
      <div className="state state--loading" role="status" aria-live="polite">
        Loading {label}…
      </div>
    )
  }

  if (status === 'error' && data === null) {
    if (renderError) {
      return <>{renderError(error, reload)}</>
    }
    const detail = error instanceof ApiError ? error.message : (error?.message ?? 'Unknown error')
    const code = error instanceof ApiError ? error.code : null
    const requestId = error instanceof ApiError ? error.requestId : null
    return (
      <div className="state state--error" role="alert">
        <p>Could not load {label}.</p>
        <p className="state__detail">{detail}</p>
        {code || requestId ? (
          <p className="state__meta">
            {code ? (
              <>
                Code <code>{code}</code>
              </>
            ) : null}
            {code && requestId ? ' · ' : null}
            {requestId ? <>Request {requestId}</> : null}
          </p>
        ) : null}
        <button type="button" onClick={reload}>
          Retry
        </button>
      </div>
    )
  }

  if (data === null) {
    return <div className="state state--empty">{emptyMessage}</div>
  }

  // A failed refresh that leaves older data on screen is exactly the case
  // where the screen must say so rather than look current.
  const refreshFailed = status === 'error'
  const refreshPending = status === 'loading'
  const failureCode = error instanceof ApiError ? error.code : null
  const failureRequestId = error instanceof ApiError ? error.requestId : null
  const dataIsEmpty = isEmpty?.(data) ?? false

  return (
    <>
      {(isStale || refreshFailed || refreshPending) && (
        <p className="stale-banner" role="status">
          <span>
            {refreshFailed ? 'Refresh failed. ' : ''}
            {refreshPending ? 'Refreshing. ' : ''}
            Showing data from {fetchedAt?.toLocaleTimeString() ?? 'an earlier load'}.
            {refreshFailed && error ? (
              <span className="stale-banner__detail">
                {error.message}
                {failureCode ? ` Code ${failureCode}.` : ''}
                {failureRequestId ? ` Request ${failureRequestId}.` : ''}
              </span>
            ) : null}
          </span>
          <button
            type="button"
            onClick={refreshPending ? undefined : reload}
            aria-disabled={refreshPending}
          >
            {refreshPending ? 'Refreshing…' : 'Refresh'}
          </button>
        </p>
      )}
      {dataIsEmpty ? <div className="state state--empty">{emptyMessage}</div> : children(data)}
    </>
  )
}
