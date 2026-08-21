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
/**
 * A game the source published without team identifiers (ADR-013).
 *
 * There is deliberately no team field, and there cannot be one. The source
 * emits `teamId: 0` with `teamName`, `teamCity`, `teamTricode` and `teamSlug`
 * all null for these games — being undecided is the entire content of the
 * record. Anything on screen attributing a pending game to a named team would
 * be an attribution the source explicitly withheld, so this type gives the UI
 * nothing to make one out of.
 */
export interface SchedulePendingGame {
  nba_game_id: string
  /** ISO day. The only field that can locate a pending game in the grid. */
  game_date: string
  /** e.g. "Emirates NBA Cup". */
  game_label: string
  /** e.g. "Quarterfinal". */
  game_sub_label: string
  /** e.g. `in-season-knockout`. */
  game_subtype: string
}

/**
 * ADR-013 replaces the old `resolved == source` invariant with
 * `source_game_count == resolved_game_count + pending_game_ids.length`.
 *
 * `pending_game_ids` is the term the invariant counts; `pending_games` carries
 * the dates and labels. The backend derives the first from the second and
 * refuses any stored block where they name different games in a different
 * order (`db/lineage.py:_pending_games`), so on a 200 they are the same set and
 * this client does not reconcile them.
 *
 * Both are optional **on the wire only**. This dashboard ships on a branch
 * stacked under the backend lane that emits them, so a response without the
 * block is a state that exists today, and rejecting it outright would trade a
 * screen that can describe its own gap for a blank one and a generic contract
 * error. The absence is never silently read as "nothing is pending" — it is
 * reported as its own state. See `readPendingGames`.
 */
export interface ScheduleRefreshLineage {
  refresh_id: number
  version: string
  refreshed_at: string
  source_game_count: number
  resolved_game_count: number
  persisted_team_row_count: number
  unresolved_game_ids: string[]
  pending_game_ids?: string[]
  pending_games?: SchedulePendingGame[]
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
