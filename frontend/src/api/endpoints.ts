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
import { DATE_ABSENCE_REASONS, type DateAbsenceReason } from './types'
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

/**
 * The ADR-013 pending block, now required and cross-checked.
 *
 * It was optional while this dashboard was stacked under an unmerged backend
 * lane, on the argument that rejecting the whole response would trade a screen
 * that can describe its own gap for a blank one. That lane has merged, so the
 * argument has expired with it and the tolerance is gone — an absent block is a
 * response that is not the contract.
 *
 * Everything a violation of which would be **silent** is checked here rather
 * than narrated downstream. `pending_game_ids` and `pending_games` must name
 * the same games in the same order with unique ids, which the backend
 * guarantees by deriving the first from the second: without it, ids longer than
 * records produces a pending total larger than the list beneath it, records
 * longer than ids badges a column `TBD` while the lineage states "none", and
 * duplicates reach React as duplicate keys. None of the three is loud.
 *
 * `date_absence_reason` gets the same treatment for the same reason. The set is
 * closed by the producer, and an unrecognised value is a finding rather than a
 * variation precisely because this screen keys *what it tells an operator to
 * do* on it — a new reason arriving unvalidated would be silently sorted into
 * the wrong action class. And the reason is cross-checked against `game_date`
 * in both directions: a reason without an absence, or an absence without a
 * reason, are the two halves of one fact disagreeing on the wire. The producer
 * refuses that pair too, so this cannot arrive from it — but the failure would
 * be silent here (the model reads only `game_date`, so a mismatched reason
 * would simply never be rendered), and a boundary that can be closed should be.
 *
 * The label fields are deliberately **not** in that category. A `null`
 * `game_label` is a gap this screen can describe — `describePendingGame`
 * renders "no label given" — and refusing the response over it would cost every
 * count on the page for a missing piece of prose. Tolerate a gap you can
 * describe, reject a value that cannot be true.
 */
function isNullableString(value: unknown): boolean {
  return typeof value === 'string' || value === null
}

function isSchedulePendingGame(value: unknown): boolean {
  if (
    !isRecord(value) ||
    typeof value.nba_game_id !== 'string' ||
    !isNullableString(value.game_date) ||
    !isNullableString(value.game_label) ||
    !isNullableString(value.game_sub_label) ||
    !isNullableString(value.game_subtype) ||
    typeof value.date_absence_reason !== 'string'
  ) {
    return false
  }
  const reason = value.date_absence_reason as DateAbsenceReason
  if (!(DATE_ABSENCE_REASONS as readonly string[]).includes(reason)) {
    return false
  }
  // The two halves of one fact. A date with a reason, or an absence without
  // one, is a response contradicting itself.
  return (value.game_date === null) === (reason !== '')
}

function isPendingBlock(value: Record<string, unknown>): boolean {
  const ids = value.pending_game_ids
  const games = value.pending_games
  if (!isStringArray(ids) || !Array.isArray(games) || !games.every(isSchedulePendingGame)) {
    return false
  }
  const named = (games as { nba_game_id: string }[]).map((game) => game.nba_game_id)
  return (
    named.length === ids.length &&
    named.every((id, index) => id === ids[index]) &&
    new Set(ids).size === ids.length
  )
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
    isStringArray(value.unresolved_game_ids) &&
    isPendingBlock(value)
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
export function isScheduleGrid(value: unknown): value is ScheduleGrid {
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
