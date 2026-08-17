/**
 * Test helpers.
 *
 * `mockFetch` stubs the global so tests exercise the real client — its error
 * envelope parsing, its timeout, its abort handling — rather than a mock of
 * the client, which would test nothing.
 */

import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

export function renderWithRouter(ui: ReactElement, { route = '/' } = {}) {
  return render(<MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>)
}

export interface MockResponse {
  status?: number
  body: unknown
  headers?: Record<string, string>
}

/** Stub `fetch`, routing by URL substring. Unmatched requests fail loudly. */
export function mockFetch(routes: Record<string, MockResponse | (() => never)>) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url =
      typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const match = Object.entries(routes).find(([path]) => url.includes(path))

    if (!match) {
      return Promise.reject(new TypeError(`Unmocked request: ${url}`))
    }

    const [, handler] = match
    if (typeof handler === 'function') {
      handler()
    }

    const { status = 200, body, headers = {} } = handler as MockResponse
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json', ...headers },
      }),
    )
  })

  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
