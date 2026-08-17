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

interface AsyncBoundaryProps<T> {
  state: AsyncState<T>
  children: (data: T) => ReactNode
  /** Rendered when the request succeeded but returned nothing meaningful. */
  isEmpty?: (data: T) => boolean
  emptyMessage?: string
  /** Age past which the data is shown as stale. Omit for data that cannot go stale. */
  staleAfterMs?: number
  label?: string
}

export function AsyncBoundary<T>({
  state,
  children,
  isEmpty,
  emptyMessage = 'Nothing to show yet.',
  staleAfterMs,
  label = 'data',
}: AsyncBoundaryProps<T>) {
  const { status, data, error, fetchedAt, reload } = state

  if (status === 'idle' || (status === 'loading' && data === null)) {
    return (
      <div className="state state--loading" role="status" aria-live="polite">
        Loading {label}…
      </div>
    )
  }

  if (status === 'error' && data === null) {
    const detail = error instanceof ApiError ? error.message : (error?.message ?? 'Unknown error')
    const requestId = error instanceof ApiError ? error.requestId : null
    return (
      <div className="state state--error" role="alert">
        <p>Could not load {label}.</p>
        <p className="state__detail">{detail}</p>
        {requestId ? <p className="state__meta">Request {requestId}</p> : null}
        <button type="button" onClick={reload}>
          Retry
        </button>
      </div>
    )
  }

  if (data === null) {
    return <div className="state state--empty">{emptyMessage}</div>
  }

  if (isEmpty?.(data)) {
    return <div className="state state--empty">{emptyMessage}</div>
  }

  const ageMs = fetchedAt ? Date.now() - fetchedAt.getTime() : null
  const isStale = staleAfterMs !== undefined && ageMs !== null && ageMs > staleAfterMs
  // A failed refresh that leaves older data on screen is exactly the case
  // where the screen must say so rather than look current.
  const refreshFailed = status === 'error'

  return (
    <>
      {(isStale || refreshFailed) && (
        <p className="stale-banner" role="status">
          {refreshFailed ? 'Refresh failed — ' : ''}showing data from{' '}
          {fetchedAt?.toLocaleTimeString() ?? 'an earlier load'}.{' '}
          <button type="button" onClick={reload}>
            Refresh
          </button>
        </p>
      )}
      {children(data)}
    </>
  )
}
