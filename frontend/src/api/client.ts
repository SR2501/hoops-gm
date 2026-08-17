/**
 * The typed API client.
 *
 * Two things it must do that a bare `fetch` does not:
 *
 * 1. **Never resolve silently on failure.** A dashboard whose job is to let a
 *    recommendation be checked cannot render a blank panel where an error
 *    happened. Every non-2xx becomes an `ApiError`.
 * 2. **Time out.** The backend is local, so a request that has not answered in
 *    a few seconds is a hung backend, not a slow network. Waiting forever
 *    during a pick clock is the worst possible behaviour.
 */

import type { ApiErrorBody } from './types'

/** Same origin by default: the dev server proxies to the backend. */
const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''

const DEFAULT_TIMEOUT_MS = 8000

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string | null

  constructor(status: number, code: string, detail: string, requestId: string | null) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
  }

  /** True when retrying might plausibly help. */
  get isTransient(): boolean {
    return this.status === 0 || this.status >= 500
  }
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === 'object' &&
    value !== null &&
    'error' in value &&
    typeof value.error === 'string'
  )
}

export interface RequestOptions {
  signal?: AbortSignal
  timeoutMs?: number
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { signal, timeoutMs = DEFAULT_TIMEOUT_MS, method = 'GET', body } = options

  const timeoutController = new AbortController()
  const timer = setTimeout(() => {
    timeoutController.abort(new DOMException('Request timed out', 'TimeoutError'))
  }, timeoutMs)

  const signals = signal ? [signal, timeoutController.signal] : [timeoutController.signal]

  let response: Response
  try {
    // Built explicitly rather than with undefined-valued keys, because
    // exactOptionalPropertyTypes treats an explicit undefined as a real value.
    const init: RequestInit = { method, signal: AbortSignal.any(signals) }
    if (body !== undefined) {
      init.headers = { 'Content-Type': 'application/json' }
      init.body = JSON.stringify(body)
    }
    response = await fetch(`${BASE_URL}${path}`, init)
  } catch (cause) {
    // A caller-initiated abort is not an error worth dressing up.
    if (signal?.aborted) throw cause
    const timedOut = cause instanceof DOMException && cause.name === 'TimeoutError'
    throw new ApiError(
      0,
      timedOut ? 'timeout' : 'unreachable',
      timedOut
        ? `The backend did not answer within ${String(timeoutMs)}ms.`
        : 'Could not reach the backend. Is it running on 127.0.0.1:8000?',
      null,
    )
  } finally {
    clearTimeout(timer)
  }

  const requestId = response.headers.get('X-Request-ID')
  const payload: unknown = await response.json().catch(() => null)

  if (!response.ok) {
    if (isErrorBody(payload)) {
      throw new ApiError(response.status, payload.error, payload.detail, payload.request_id)
    }
    throw new ApiError(response.status, 'http_error', response.statusText, requestId)
  }

  return payload as T
}
