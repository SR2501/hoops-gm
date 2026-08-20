import { describe, expect, it, vi } from 'vitest'
import { ApiError, apiFetch, type ResponseContract } from './client'

interface StatusBody {
  status: string
}

const STATUS_CONTRACT = {
  isSuccess: (value: unknown): value is StatusBody =>
    typeof value === 'object' &&
    value !== null &&
    'status' in value &&
    typeof value.status === 'string',
  invalidResponseDetail: 'The response did not contain a status.',
} satisfies ResponseContract<StatusBody>

function jsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

describe('apiFetch', () => {
  it('returns the parsed body on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonResponse({ status: 'ok', version: '0.1.0' }))),
    )

    await expect(apiFetch('/health', STATUS_CONTRACT)).resolves.toEqual({
      status: 'ok',
      version: '0.1.0',
    })
  })

  it('turns the error envelope into an ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          jsonResponse(
            { error: 'http_error', detail: 'Not Found', request_id: 'req-1' },
            { status: 404 },
          ),
        ),
      ),
    )

    const error = await apiFetch('/api/v1/nope', STATUS_CONTRACT).catch(
      (cause: unknown) => cause,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(404)
    expect((error as ApiError).code).toBe('http_error')
    expect((error as ApiError).requestId).toBe('req-1')
    expect((error as ApiError).isTransient).toBe(false)
  })

  it('falls back to the response header when an error body request id is null', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          jsonResponse(
            { error: 'internal_error', detail: 'Backend failed', request_id: null },
            { status: 500, headers: { 'X-Request-ID': 'req-header-fallback' } },
          ),
        ),
      ),
    )

    const error = await apiFetch('/health', STATUS_CONTRACT).catch((cause: unknown) => cause)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).requestId).toBe('req-header-fallback')
  })

  it('never resolves silently on a non-2xx without an envelope', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('<html>gateway</html>', { status: 502 }))),
    )

    const error = await apiFetch('/health', STATUS_CONTRACT).catch((cause: unknown) => cause)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).isTransient).toBe(true)
  })

  it('reports an unreachable backend rather than hanging', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
    )

    const error = await apiFetch('/health', STATUS_CONTRACT).catch((cause: unknown) => cause)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(0)
    expect((error as ApiError).code).toBe('unreachable')
    expect((error as ApiError).isTransient).toBe(true)
  })

  it('gives up rather than waiting forever', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => {
              reject(init.signal?.reason as Error)
            })
          }),
      ),
    )

    const error = await apiFetch('/health', STATUS_CONTRACT, { timeoutMs: 5 }).catch(
      (cause: unknown) => cause,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('timeout')
  })

  it('keeps the timeout active while reading a stalled response body', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
        Promise.resolve(stalledJsonResponse(init?.signal, 'req-stalled-body')),
      ),
    )

    const error = await apiFetch('/health', STATUS_CONTRACT, { timeoutMs: 5 }).catch(
      (cause: unknown) => cause,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('timeout')
    expect((error as ApiError).requestId).toBe('req-stalled-body')
  })

  it('propagates a caller-initiated abort untouched', async () => {
    const controller = new AbortController()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => {
              reject(init.signal?.reason as Error)
            })
          }),
      ),
    )

    const pending = apiFetch('/health', STATUS_CONTRACT, { signal: controller.signal }).catch(
      (cause: unknown) => cause,
    )
    controller.abort()

    await expect(pending).resolves.not.toBeInstanceOf(ApiError)
  })

  it('propagates a caller abort that happens while reading the response body', async () => {
    const controller = new AbortController()
    const reason = new DOMException('Caller stopped the request', 'AbortError')
    vi.stubGlobal(
      'fetch',
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
        Promise.resolve(stalledJsonResponse(init?.signal)),
      ),
    )

    const pending = apiFetch('/health', STATUS_CONTRACT, {
      signal: controller.signal,
    }).catch((cause: unknown) => cause)
    await Promise.resolve()
    controller.abort(reason)

    await expect(pending).resolves.toBe(reason)
  })

  it('rejects invalid JSON on a successful response with request context', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response('<html>not json</html>', {
            status: 200,
            headers: { 'X-Request-ID': 'req-invalid-json' },
          }),
        ),
      ),
    )

    const error = await apiFetch('/health', STATUS_CONTRACT).catch((cause: unknown) => cause)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('invalid_response')
    expect((error as ApiError).requestId).toBe('req-invalid-json')
    expect((error as ApiError).message).toContain('not valid JSON')
  })
})

function stalledJsonResponse(signal?: AbortSignal | null, requestId?: string): Response {
  const body = new ReadableStream({
    start(controller) {
      signal?.addEventListener(
        'abort',
        () => {
          controller.error(signal.reason)
        },
        { once: true },
      )
    },
  })
  return new Response(body, {
    status: 200,
    headers: {
      'Content-Type': 'application/json',
      ...(requestId ? { 'X-Request-ID': requestId } : {}),
    },
  })
}
