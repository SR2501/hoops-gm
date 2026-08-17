/**
 * Types mirroring the backend's response models.
 *
 * Hand-written on purpose for now. Generating them from `/openapi.json` is the
 * obvious next step and the reason the backend serves the document, but a
 * codegen step nobody has needed yet is a build dependency without a payoff.
 * When the surface grows past a handful of endpoints, generate these and
 * delete the file.
 *
 * Keep in step with `backend/src/hoops_gm/api/schemas.py`.
 */

export interface Health {
  status: 'ok'
  service: string
  version: string
  environment: string
}

export interface Readiness {
  status: 'ok' | 'degraded'
  database: 'ok' | 'unavailable'
  detail: string | null
}

export interface Meta {
  service: string
  version: string
  environment: string
  season: string
  entity_groups: string[]
}

/** The backend's stable error envelope. */
export interface ApiErrorBody {
  error: string
  detail: string
  request_id: string | null
}
