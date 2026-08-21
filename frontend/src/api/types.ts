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
/**
 * Why a pending game carries no date (ADR-013's nullable-date contract).
 *
 * A closed set on purpose: the producer validates it and an unrecognised value
 * is a finding rather than a variation, precisely because a consumer keys
 * behaviour on it. `''` means a date *was* published and reconciled.
 *
 * **The split that matters is what it tells an operator to do**, and it is not
 * the split a reader would guess from the names:
 *
 * - `not_offered` — both time fields absent. The source has not committed.
 * - `irreconcilable` — both parsed and disagree; the source contradicts itself.
 * - `unreadable` — a value was published and *we* could not read it, or the
 *   schema moved. **Our failure.**
 * - `implausible` — both parsed, agreed, and named a date nowhere near the
 *   season. Agreement is not validity: the NBA uses a `1900-01-01` epoch as a
 *   live placeholder, and a placeholder pair reconciles perfectly. **Our
 *   failure to reject a placeholder earlier.**
 *
 * The producer classes the last two as faults and exits non-zero on them
 * (`schedule_import.py:_FAULT_ABSENCE_REASONS`), while the first two leave it
 * at exit 0. So the first two mean *wait* and the last two mean *investigate*,
 * and ADR-013 states the error that matters as rendering an investigate-class
 * cause as a wait-class one.
 */
export const DATE_ABSENCE_REASONS = [
  '',
  'not_offered',
  'unreadable',
  'irreconcilable',
  'implausible',
] as const

export type DateAbsenceReason = (typeof DATE_ABSENCE_REASONS)[number]

/** Absence causes that mean *investigate*, mirroring the producer's own set. */
export const FAULT_ABSENCE_REASONS: readonly DateAbsenceReason[] = ['unreadable', 'implausible']

export interface SchedulePendingGame {
  nba_game_id: string
  /**
   * ISO day, or `null` when no trustworthy date could be derived.
   *
   * `null` does **not** mean the source withheld a date, and an earlier version
   * of this screen said it did. Three of the four absence causes involve a
   * value that *was* published — unreadable, irreconcilable and implausible all
   * describe something arriving and being rejected. Only `not_offered` means
   * nothing came. Which is why the cause is carried beside it rather than
   * inferred from the `null`.
   */
  game_date: string | null
  /** e.g. "Emirates NBA Cup". */
  game_label: string | null
  /** e.g. "Quarterfinal". */
  game_sub_label: string | null
  /** e.g. "in-season-knockout". */
  game_subtype: string | null
  /** Empty string when `game_date` is present. See `DATE_ABSENCE_REASONS`. */
  date_absence_reason: string
}

/**
 * ADR-013 replaces the old `resolved == source` invariant with
 * `source_game_count == resolved_game_count + pending_game_ids.length`.
 *
 * `pending_game_ids` is the term the invariant counts; `pending_games` carries
 * the dates, labels and absence reasons. The backend derives the first from the
 * second and refuses any stored block where they name different games in a
 * different order, so on a 200 they are the same set.
 *
 * **Both are required.** They were optional on the wire while this dashboard
 * was stacked under an unmerged backend lane, and the absence was rendered as
 * its own statement. That lane has merged, so the tolerance and the notice that
 * described it are gone: a response without the block is now a response that is
 * not the contract, and the boundary refuses it rather than the screen
 * narrating it.
 */
export interface ScheduleRefreshLineage {
  refresh_id: number
  version: string
  refreshed_at: string
  source_game_count: number
  resolved_game_count: number
  persisted_team_row_count: number
  unresolved_game_ids: string[]
  pending_game_ids: string[]
  pending_games: SchedulePendingGame[]
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
