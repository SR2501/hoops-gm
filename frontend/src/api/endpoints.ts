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
import type {
  Health,
  Meta,
  Readiness,
  ScheduleGrid,
  ScheduleGridCount,
  ScheduleGridLineage,
  ScheduleGridPeriod,
  ScheduleGridTeam,
} from './types'

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

/* --- Schedule grid (ADR-012) ---------------------------------------------- */

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === 'string')
}

function isScheduleRefreshLineage(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.refresh_id === 'number' &&
    typeof value.version === 'string' &&
    typeof value.refreshed_at === 'string' &&
    typeof value.source_game_count === 'number' &&
    typeof value.resolved_game_count === 'number' &&
    typeof value.persisted_team_row_count === 'number' &&
    isStringArray(value.unresolved_game_ids)
  )
}

function isProjectionRefreshLineage(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.refresh_id === 'number' &&
    typeof value.version === 'string' &&
    typeof value.refreshed_at === 'string'
  )
}

function isRecordLineage(value: unknown): boolean {
  return isRecord(value) && typeof value.id === 'number' && typeof value.version === 'number'
}

function isScheduleGridLineage(value: unknown): value is ScheduleGridLineage {
  return (
    isRecord(value) &&
    isScheduleRefreshLineage(value.schedule) &&
    isProjectionRefreshLineage(value.scoring_period_projection) &&
    isRecordLineage(value.deadline_calendar) &&
    isRecordLineage(value.settings_snapshot)
  )
}

function isScheduleGridTeam(value: unknown): value is ScheduleGridTeam {
  return (
    isRecord(value) &&
    typeof value.team_id === 'number' &&
    typeof value.nba_team_id === 'number' &&
    typeof value.abbreviation === 'string' &&
    typeof value.name === 'string'
  )
}

function isScheduleGridPeriod(value: unknown): value is ScheduleGridPeriod {
  return (
    isRecord(value) &&
    typeof value.period_number === 'number' &&
    typeof value.start_date === 'string' &&
    typeof value.end_date === 'string' &&
    typeof value.is_playoff === 'boolean'
  )
}

/**
 * Counts are non-negative integers.
 *
 * Unlike density, this is a property of the value itself rather than of the
 * collection: a fractional or negative game count means the field is not what
 * this dashboard thinks it is, and rendering `-1` or `2.5` verbatim would put a
 * number on screen that cannot be true. Density is tolerated and reported;
 * a nonsense value is not.
 */
function isScheduleGridCount(value: unknown): value is ScheduleGridCount {
  return (
    isRecord(value) &&
    typeof value.period_number === 'number' &&
    typeof value.team_id === 'number' &&
    typeof value.games === 'number' &&
    Number.isInteger(value.games) &&
    value.games >= 0
  )
}

/**
 * Shape only. Density is deliberately *not* asserted here.
 *
 * The contract says `counts` is dense, and if it ever is not, rejecting the
 * whole response would replace a visible hole with a blank screen and a
 * generic contract error. The grid renders a missing cell as an explicit "no
 * data" marker and says how many it found, which is the difference between
 * finding out and not.
 */
function isScheduleGrid(value: unknown): value is ScheduleGrid {
  return (
    isRecord(value) &&
    typeof value.league_id === 'number' &&
    typeof value.season === 'string' &&
    isScheduleGridLineage(value.lineage) &&
    Array.isArray(value.teams) &&
    value.teams.every(isScheduleGridTeam) &&
    Array.isArray(value.periods) &&
    value.periods.every(isScheduleGridPeriod) &&
    Array.isArray(value.counts) &&
    value.counts.every(isScheduleGridCount)
  )
}

const SCHEDULE_GRID_CONTRACT = {
  isSuccess: isScheduleGrid,
  invalidResponseDetail:
    'The schedule grid response did not match the expected backend contract.',
} satisfies ResponseContract<ScheduleGrid>

export function getScheduleGrid(
  leagueId: number,
  options?: RequestOptions,
): Promise<ScheduleGrid> {
  return apiFetch(
    `/api/v1/leagues/${String(leagueId)}/schedule-grid/current`,
    SCHEDULE_GRID_CONTRACT,
    options,
  )
}
