import { describe, expect, it } from 'vitest'
import { mockFetch } from '../test/helpers'
import { ApiError } from './client'
import { getMeta, getReadiness } from './endpoints'
import type { Readiness } from './types'

describe('endpoint response contracts', () => {
  it('retains the typed readiness 503 body and request context', async () => {
    const body: Readiness = {
      status: 'degraded',
      database: 'unavailable',
      detail: 'database check failed: OperationalError',
    }
    mockFetch({
      '/health/ready': {
        status: 503,
        body,
        headers: { 'X-Request-ID': 'req-ready-503' },
      },
    })

    const error = await getReadiness().catch((cause: unknown) => cause)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError<Readiness>).status).toBe(503)
    expect((error as ApiError<Readiness>).code).toBe('degraded')
    expect((error as ApiError<Readiness>).message).toBe(body.detail)
    expect((error as ApiError<Readiness>).requestId).toBe('req-ready-503')
    expect((error as ApiError<Readiness>).body).toEqual(body)
  })

  it('rejects a malformed 2xx instead of treating it as empty or successful', async () => {
    mockFetch({
      '/api/v1/meta': {
        body: {
          service: 'hoops-gm',
          version: '0.1.0',
          environment: 'development',
          season: '2026-27',
          entity_groups: 'identity',
        },
        headers: { 'X-Request-ID': 'req-malformed-meta' },
      },
    })

    const error = await getMeta().catch((cause: unknown) => cause)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('invalid_response')
    expect((error as ApiError).requestId).toBe('req-malformed-meta')
    expect((error as ApiError).message).toContain('metadata response')
  })
})
