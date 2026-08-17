import { describe, expect, it, vi } from 'vitest'
import { ApiError, apiFetch } from './client'

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

    await expect(apiFetch<{ status: string }>('/health')).resolves.toEqual({
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

    const error = await apiFetch('/api/v1/nope').catch((cause: unknown) => cause)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(404)
    expect((error as ApiError).code).toBe('http_error')
    expect((error as ApiError).requestId).toBe('req-1')
    expect((error as ApiError).isTransient).toBe(false)
  })

  it('never resolves silently on a non-2xx without an envelope', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('<html>gateway</html>', { status: 502 }))),
    )

    const error = await apiFetch('/health').catch((cause: unknown) => cause)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).isTransient).toBe(true)
  })

  it('reports an unreachable backend rather than hanging', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
    )

    const error = await apiFetch('/health').catch((cause: unknown) => cause)

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

    const error = await apiFetch('/health', { timeoutMs: 5 }).catch((cause: unknown) => cause)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('timeout')
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

    const pending = apiFetch('/health', { signal: controller.signal }).catch(
      (cause: unknown) => cause,
    )
    controller.abort()

    await expect(pending).resolves.not.toBeInstanceOf(ApiError)
  })
})
