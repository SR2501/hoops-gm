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

export interface AsyncState<T> {
  status: AsyncStatus
  data: T | null
  error: Error | null
  /** When `data` was received. Null until the first success. */
  fetchedAt: Date | null
  reload: () => void
}

export function useAsync<T>(
  fetcher: (options: { signal: AbortSignal }) => Promise<T>,
  deps: readonly unknown[] = [],
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

  const reload = useCallback(() => {
    setNonce((n) => n + 1)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let active = true

    setStatus('loading')
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
        if (!active || controller.signal.aborted) return
        setError(cause instanceof Error ? cause : new Error(String(cause)))
        setStatus('error')
      })

    return () => {
      active = false
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce, ...deps])

  return { status, data, error, fetchedAt, reload }
}
