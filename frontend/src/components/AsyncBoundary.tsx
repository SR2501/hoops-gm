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

import { useEffect, useState, type ReactNode } from 'react'
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
  const isStale = useIsStale(fetchedAt, staleAfterMs)

  if (status === 'idle' || (status === 'loading' && data === null)) {
    return (
      <div className="state state--loading" role="status" aria-live="polite">
        Loading {label}…
      </div>
    )
  }

  if (status === 'error' && data === null) {
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
  const failureCode = error instanceof ApiError ? error.code : null
  const failureRequestId = error instanceof ApiError ? error.requestId : null
  const dataIsEmpty = isEmpty?.(data) ?? false

  return (
    <>
      {(isStale || refreshFailed) && (
        <p className="stale-banner" role="status">
          <span>
            {refreshFailed ? 'Refresh failed. ' : ''}
            Showing data from {fetchedAt?.toLocaleTimeString() ?? 'an earlier load'}.
            {refreshFailed && error ? (
              <span className="stale-banner__detail">
                {error.message}
                {failureCode ? ` Code ${failureCode}.` : ''}
                {failureRequestId ? ` Request ${failureRequestId}.` : ''}
              </span>
            ) : null}
          </span>
          <button type="button" onClick={reload}>
            Refresh
          </button>
        </p>
      )}
      {dataIsEmpty ? <div className="state state--empty">{emptyMessage}</div> : children(data)}
    </>
  )
}

function useIsStale(fetchedAt: Date | null, staleAfterMs: number | undefined): boolean {
  const [, checkStaleness] = useState(0)

  useEffect(() => {
    if (!fetchedAt || staleAfterMs === undefined) {
      return
    }

    const staleAt = fetchedAt.getTime() + staleAfterMs
    const delayMs = staleAt - Date.now()
    if (delayMs <= 0) {
      return
    }

    const timer = window.setTimeout(() => {
      checkStaleness((version) => version + 1)
    }, delayMs)
    return () => {
      window.clearTimeout(timer)
    }
  }, [fetchedAt, staleAfterMs])

  return (
    fetchedAt !== null &&
    staleAfterMs !== undefined &&
    Date.now() >= fetchedAt.getTime() + staleAfterMs
  )
}
