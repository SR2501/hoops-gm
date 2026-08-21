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

/** A view's own words for a failure, replacing the backend's raw wording. */
export interface ErrorDescription {
  /** What happened, in terms of the data rather than the stack. */
  summary: string
  /** The next thing the reader can actually do. */
  action?: string
}

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
   * Explains a failure in the view's own terms.
   *
   * The backend's own wording is right for a generic surface and wrong where
   * an endpoint fails closed on several distinct conditions calling for
   * different actions.
   *
   * This is a *description* rather than a rendered panel because both failure
   * paths need it: the cold one, where nothing is on screen, and the warm one,
   * where earlier data is still showing and a refresh has just failed. The warm
   * path is the one that matters most on a superseded-cohort error — the reader
   * is looking at numbers now known to be out of date — and handing back a
   * whole panel would have covered only the cold path while appearing to cover
   * both.
   *
   * The backend's raw wording is still shown, so a failure can be quoted and
   * correlated to a server log line exactly. Called only when there is an
   * error, so an implementation never has to handle `null`.
   */
  describeError?: (error: Error) => ErrorDescription
}

export function AsyncBoundary<T>({
  state,
  children,
  isEmpty,
  emptyMessage = 'Nothing to show yet.',
  staleAfterMs,
  label = 'data',
  describeError,
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

  const described = error ? (describeError?.(error) ?? null) : null
  const backendWording = error?.message ?? null
  const code = error instanceof ApiError ? error.code : null
  const requestId = error instanceof ApiError ? error.requestId : null

  if (status === 'error' && data === null) {
    const summary = described?.summary ?? backendWording ?? 'Unknown error'
    return (
      <div className="state state--error" role="alert">
        <p>Could not load {label}.</p>
        <p className="state__detail" data-testid="async-error-summary">
          {summary}
        </p>
        {described?.action ? (
          <p className="state__detail" data-testid="async-error-action">
            {described.action}
          </p>
        ) : null}
        {backendWording && backendWording !== summary ? (
          <p className="state__meta">
            Backend said: <q>{backendWording}</q>
          </p>
        ) : null}
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
  const dataIsEmpty = isEmpty?.(data) ?? false
  const failureWording = described?.summary ?? backendWording
  // The backend's own words, on the warm path too.
  //
  // This previously computed `described?.summary ?? backendWording` and
  // rendered only that — so whenever a view supplied a description, which is
  // every refusal on both data screens, the backend's wording was unreachable
  // once data was already on screen. Every error-copy module in this app tells
  // the reader to read "the backend's wording below" to find out *which* of
  // several conditions fired, and on the warm path there was nothing below.
  //
  // That mattered most exactly where the copy was most decision-bearing: a
  // superseded cohort or a moved import arrives *while* a screen is open, so
  // the warm path is the one those messages were written for. Found in review
  // of the projections screen; the defect is older and belonged to this
  // component, so it is fixed here rather than by weakening the copy that
  // depends on it.
  const showBackendWording =
    backendWording !== null && backendWording !== described?.summary

  return (
    <>
      {(isStale || refreshFailed || refreshPending) && (
        <p className="stale-banner" role="status">
          <span>
            {refreshFailed ? 'Refresh failed. ' : ''}
            {refreshPending ? 'Refreshing. ' : ''}
            Showing data from {fetchedAt?.toLocaleTimeString() ?? 'an earlier load'}.
            {refreshFailed && error ? (
              <span className="stale-banner__detail" data-testid="async-stale-failure">
                {failureWording}
                {described?.action ? ` ${described.action}` : ''}
                {showBackendWording ? (
                  <span className="state__meta" data-testid="async-stale-backend-wording">
                    Backend said: <q>{backendWording}</q>
                  </span>
                ) : null}
                {code ? ` Code ${code}.` : ''}
                {requestId ? ` Request ${requestId}.` : ''}
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
