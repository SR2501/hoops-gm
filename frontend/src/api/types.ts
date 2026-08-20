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

/* --- Schedule grid (ADR-012) ---------------------------------------------- */

/**
 * The schedule refresh that produced the counts on screen.
 *
 * `refreshed_at` is kept as the raw ISO string the backend sent rather than a
 * `Date`. The grid displays it verbatim as well as derived, because a
 * self-describing timestamp is exactly the kind of field that can be
 * mislabelled, and a user who can see the original string can check the claim.
 */
export interface ScheduleRefreshLineage {
  refresh_id: number
  version: string
  refreshed_at: string
  source_game_count: number
  resolved_game_count: number
  persisted_team_row_count: number
  unresolved_game_ids: string[]
}

export interface ProjectionRefreshLineage {
  refresh_id: number
  version: string
  refreshed_at: string
}

export interface RecordLineage {
  id: number
  version: number
}

export interface ScheduleGridLineage {
  schedule: ScheduleRefreshLineage
  scoring_period_projection: ProjectionRefreshLineage
  deadline_calendar: RecordLineage
  settings_snapshot: RecordLineage
}

export interface ScheduleGridTeam {
  team_id: number
  nba_team_id: number
  abbreviation: string
  name: string
}

export interface ScheduleGridPeriod {
  period_number: number
  start_date: string
  end_date: string
  is_playoff: boolean
}

export interface ScheduleGridCount {
  period_number: number
  team_id: number
  games: number
}

/**
 * `counts` is dense by contract: one row per (team, period), zeros explicit.
 * The client does not assume it, because a missing cell and a zero cell mean
 * completely different things and the grid has to be able to say which.
 */
export interface ScheduleGrid {
  league_id: number
  season: string
  lineage: ScheduleGridLineage
  teams: ScheduleGridTeam[]
  periods: ScheduleGridPeriod[]
  counts: ScheduleGridCount[]
}
