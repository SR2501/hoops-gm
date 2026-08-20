import { useEffect, useState } from 'react'

export function useIsStale(
  fetchedAt: Date | null,
  staleAfterMs: number | undefined,
): boolean {
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
