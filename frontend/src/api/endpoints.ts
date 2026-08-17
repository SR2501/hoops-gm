/**
 * Endpoint functions.
 *
 * One function per backend route, so a route change is a one-line edit here
 * rather than a search through components for a string literal.
 */

import { apiFetch, type RequestOptions } from './client'
import type { Health, Meta, Readiness } from './types'

export function getHealth(options?: RequestOptions): Promise<Health> {
  return apiFetch<Health>('/health', options)
}

export function getReadiness(options?: RequestOptions): Promise<Readiness> {
  return apiFetch<Readiness>('/health/ready', options)
}

export function getMeta(options?: RequestOptions): Promise<Meta> {
  return apiFetch<Meta>('/api/v1/meta', options)
}
