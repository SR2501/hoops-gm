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

export class ApiError<TBody = unknown> extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string | null
  readonly body: TBody | null

  constructor(
    status: number,
    code: string,
    detail: string,
    requestId: string | null,
    body: TBody | null = null,
  ) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
    this.body = body
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
    typeof value.error === 'string' &&
    'detail' in value &&
    typeof value.detail === 'string' &&
    'request_id' in value &&
    (typeof value.request_id === 'string' || value.request_id === null)
  )
}

export interface ApiErrorContext {
  status: number
  statusText: string
  requestId: string | null
  path: string
}

export interface ResponseContract<T> {
  isSuccess: (value: unknown) => value is T
  invalidResponseDetail: string
  errorFromResponse?: (value: unknown, context: ApiErrorContext) => ApiError | null
}

export interface RequestOptions {
  signal?: AbortSignal
  timeoutMs?: number
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
}

export async function apiFetch<T>(
  path: string,
  contract: ResponseContract<T>,
  options: RequestOptions = {},
): Promise<T> {
  const { signal, timeoutMs = DEFAULT_TIMEOUT_MS, method = 'GET', body } = options

  const timeoutController = new AbortController()
  const timer = setTimeout(() => {
    timeoutController.abort(new DOMException('Request timed out', 'TimeoutError'))
  }, timeoutMs)

  const signals = signal ? [signal, timeoutController.signal] : [timeoutController.signal]

  try {
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
      if (signal?.aborted) {
        throw signal.reason ?? cause
      }
      if (timeoutController.signal.aborted) {
        throw timeoutError(timeoutMs)
      }
      throw new ApiError(
        0,
        'unreachable',
        'Could not reach the backend. Is it running on 127.0.0.1:8000?',
        null,
      )
    }

    const requestId = response.headers.get('X-Request-ID')
    let payload: unknown
    try {
      payload = await response.json()
    } catch (cause) {
      if (signal?.aborted) {
        throw signal.reason ?? cause
      }
      if (timeoutController.signal.aborted) {
        throw timeoutError(timeoutMs)
      }
      if (response.ok) {
        throw new ApiError(
          response.status,
          'invalid_response',
          `${contract.invalidResponseDetail} The response was not valid JSON.`,
          requestId,
        )
      }
      payload = null
    }

    if (!response.ok) {
      if (isErrorBody(payload)) {
        throw new ApiError<ApiErrorBody>(
          response.status,
          payload.error,
          payload.detail,
          payload.request_id ?? requestId,
          payload,
        )
      }

      const endpointError = contract.errorFromResponse?.(payload, {
        status: response.status,
        statusText: response.statusText,
        requestId,
        path,
      })
      if (endpointError) {
        throw endpointError
      }

      throw new ApiError(
        response.status,
        'http_error',
        response.statusText || `Backend request failed with HTTP ${String(response.status)}.`,
        requestId,
        payload,
      )
    }

    if (!contract.isSuccess(payload)) {
      throw new ApiError(
        response.status,
        'invalid_response',
        contract.invalidResponseDetail,
        requestId,
        payload,
      )
    }

    return payload
  } finally {
    clearTimeout(timer)
  }
}

function timeoutError(timeoutMs: number): ApiError {
  return new ApiError(
    0,
    'timeout',
    `The backend did not answer within ${String(timeoutMs)}ms.`,
    null,
  )
}
