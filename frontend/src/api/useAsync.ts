/**
 * `useAsync` — the only way data enters a component.
 *
 * Four states, always, because the dashboard's job is to make a recommendation
 * checkable and three of the four are the ones that get skipped: loading,
 * error, and *stale*. Stale matters most. A `p(play)` computed from an injury
 * report that is six hours old is not the same number as a fresh one, and a UI
 * that renders them identically is lying by omission.
 *
 * `fetchedAt` is exposed for exactly that reason, and `AsyncBoundary` uses it.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export type AsyncStatus = 'idle' | 'loading' | 'success' | 'error'

/**
 * Whether a failure is worth one immediate retry.
 *
 * A predicate rather than a list of codes, and rather than a boolean, because
 * *which* failures are transient is an endpoint's own knowledge:
 * `projections_inconsistent_cohort` means a concurrent import moved the cohort
 * and a second read will usually succeed, while the other seven projections
 * codes need a human and retrying them just delays the message.
 *
 * **Exactly one retry, enforced here rather than by the caller.** A predicate
 * that returned `true` for a persistent condition would otherwise spin against
 * a backend that is already refusing, which is the failure mode a retry loop
 * is most likely to have and least likely to be tested for.
 */
export type RetryPolicy = (error: Error) => boolean

export interface AsyncState<T> {
  status: AsyncStatus
  /**
   * The last successful payload, **whole**.
   *
   * Retention is whole-payload or nothing, and that is a correctness property
   * rather than an implementation convenience. Every response this dashboard
   * consumes carries its own lineage block describing the rates beside it, and
   * the backend goes to real trouble to guarantee the two agree — the
   * projections route brackets every read between two runs of the canonical
   * release precisely so a 200 can never carry a lineage block that does not
   * describe its own rows.
   *
   * Retaining at any finer granularity would reintroduce that defect on the
   * client, where no server-side bracket can see it: a rate retained from
   * import N sitting in a row beside one refetched from import N+1, under a
   * single lineage block that describes neither. `architect` raised this
   * against ADR-015, where a blend is recomputed per request and the mismatch
   * would be between a blended rate and its own sources.
   *
   * Holding the whole response in one field makes the bad version
   * unrepresentable rather than merely discouraged.
   */
  data: T | null
  error: Error | null
  /** When `data` was received. Null until the first success. */
  fetchedAt: Date | null
  reload: () => void
}

export interface UseAsyncOptions {
  /**
   * Retry once, immediately, when this returns true for the failure.
   *
   * The retained `data` is untouched either way — a failed retry leaves the
   * previous payload on screen with `status: 'error'`, which `AsyncBoundary`
   * renders as its warm path. That is deliberate for a draft board: an empty
   * screen mid-auction is worse than a slightly stale one.
   */
  shouldRetry?: RetryPolicy
  /**
   * Start the request in a microtask so React StrictMode's development-only
   * setup/cleanup replay can cancel the discarded effect before I/O begins.
   *
   * Use this for expensive reads whose server-side work cannot be cancelled
   * when the browser aborts the first request.
   */
  deferInitialRequest?: boolean
}

export function useAsync<T>(
  fetcher: (options: { signal: AbortSignal }) => Promise<T>,
  deps: readonly unknown[] = [],
  options: UseAsyncOptions = {},
): AsyncState<T> {
  const [status, setStatus] = useState<AsyncStatus>('idle')
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null)
  const [nonce, setNonce] = useState(0)

  // Keep the latest fetcher without making it a dependency, so callers can
  // pass an inline arrow function without causing an infinite reload loop.
  const fetcherRef = useRef(fetcher)
  useEffect(() => {
    fetcherRef.current = fetcher
  })
  // Same treatment for the policy, so an inline arrow does not re-run the
  // effect. A policy that changed mid-flight would not affect the attempt
  // already running in any case.
  const shouldRetryRef = useRef(options.shouldRetry)
  useEffect(() => {
    shouldRetryRef.current = options.shouldRetry
  })

  const reload = useCallback(() => {
    setNonce((n) => n + 1)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let active = true

    setStatus('loading')

    // `retriesLeft` is a local rather than a ref or a piece of state: it is
    // scoped to this effect run, so a reload resets it by construction and two
    // overlapping runs cannot share a budget.
    const attempt = (retriesLeft: number): void => {
      fetcherRef
        .current({ signal: controller.signal })
        .then((result) => {
          if (!active) return
          setData(result)
          setError(null)
          setFetchedAt(new Date())
          setStatus('success')
        })
        .catch((cause: unknown) => {
          // Checked before the policy runs, not after. An aborted request is
          // this component unmounting or its deps changing, never a transient
          // backend condition, and retrying one would fire a request whose
          // signal is already aborted.
          if (!active || controller.signal.aborted) return
          const failure = cause instanceof Error ? cause : new Error(String(cause))
          if (retriesLeft > 0 && (shouldRetryRef.current?.(failure) ?? false)) {
            attempt(retriesLeft - 1)
            return
          }
          setError(failure)
          setStatus('error')
        })
    }

    if (options.deferInitialRequest) {
      queueMicrotask(() => {
        if (active && !controller.signal.aborted) attempt(1)
      })
    } else {
      attempt(1)
    }

    return () => {
      active = false
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce, ...deps])

  return { status, data, error, fetchedAt, reload }
}
