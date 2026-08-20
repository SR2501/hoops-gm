/**
 * Endpoint functions.
 *
 * One function per backend route, so a route change is a one-line edit here
 * rather than a search through components for a string literal.
 */

import {
  ApiError,
  apiFetch,
  type ApiErrorContext,
  type RequestOptions,
  type ResponseContract,
} from './client'
import type { Health, Meta, Readiness } from './types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isHealth(value: unknown): value is Health {
  return (
    isRecord(value) &&
    value.status === 'ok' &&
    typeof value.service === 'string' &&
    typeof value.version === 'string' &&
    typeof value.environment === 'string'
  )
}

function isReadiness(value: unknown): value is Readiness {
  return (
    isRecord(value) &&
    (value.status === 'ok' || value.status === 'degraded') &&
    (value.database === 'ok' || value.database === 'unavailable') &&
    (typeof value.detail === 'string' || value.detail === null)
  )
}

function isMeta(value: unknown): value is Meta {
  return (
    isRecord(value) &&
    typeof value.service === 'string' &&
    typeof value.version === 'string' &&
    typeof value.environment === 'string' &&
    typeof value.season === 'string' &&
    Array.isArray(value.entity_groups) &&
    value.entity_groups.every((group) => typeof group === 'string')
  )
}

function readinessError(value: unknown, context: ApiErrorContext): ApiError<Readiness> | null {
  if (!isReadiness(value) || value.status !== 'degraded') {
    return null
  }

  return new ApiError(
    context.status,
    value.status,
    value.detail ?? 'The backend is running but is not ready to serve database requests.',
    context.requestId,
    value,
  )
}

const HEALTH_CONTRACT = {
  isSuccess: isHealth,
  invalidResponseDetail: 'The health response did not match the expected backend contract.',
} satisfies ResponseContract<Health>

const READINESS_CONTRACT = {
  isSuccess: isReadiness,
  invalidResponseDetail: 'The readiness response did not match the expected backend contract.',
  errorFromResponse: readinessError,
} satisfies ResponseContract<Readiness>

const META_CONTRACT = {
  isSuccess: isMeta,
  invalidResponseDetail: 'The service metadata response did not match the expected backend contract.',
} satisfies ResponseContract<Meta>

export function getHealth(options?: RequestOptions): Promise<Health> {
  return apiFetch('/health', HEALTH_CONTRACT, options)
}

export function getReadiness(options?: RequestOptions): Promise<Readiness> {
  return apiFetch('/health/ready', READINESS_CONTRACT, options)
}

export function getMeta(options?: RequestOptions): Promise<Meta> {
  return apiFetch('/api/v1/meta', META_CONTRACT, options)
}
