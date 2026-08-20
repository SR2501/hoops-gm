/**
 * Turning the wire response into something a table can render, with the holes
 * left visible.
 *
 * The one rule this module exists to enforce: **a cell is either a count or it
 * is absent, and those are different values.** `games: 0` means the team has
 * no game scheduled in that period — a real, decision-bearing fact. A missing
 * `counts` row means the backend did not tell us, which is not a fact about
 * the schedule at all. Collapsing them into one blank cell is the single most
 * common way a schedule tool lies to the person reading it, so `null` is
 * reserved for absence and rendered as its own marker.
 *
 * Everything here is descriptive arithmetic — sums of integers the backend
 * sent. No thresholds, no "light week", no judgement about whether a count is
 * good. Those belong to `quant` behind the Model gate (ADR-009), and inventing
 * them in a UI would ship an unbacktested model in CSS.
 */

import type { ScheduleGrid, ScheduleGridPeriod, ScheduleGridTeam } from '../api/types'

export interface ScheduleGridRow {
  team: ScheduleGridTeam
  /** One entry per period, in `periods` order. `null` means no row was sent. */
  cells: (number | null)[]
  /** Games across the periods we were actually told about. */
  total: number
  missingCells: number
}

export interface ScheduleGridIntegrity {
  /** (team, period) pairs the dense contract promised and did not deliver. */
  missingCells: number
  /** `counts` rows naming a team or period absent from the headers. */
  unmatchedRows: number
  /** More than one `counts` row for the same (team, period). */
  duplicateRows: number
  /** True when the response was exactly as dense as the contract states. */
  isDense: boolean
}

export interface ScheduleGridModel {
  rows: ScheduleGridRow[]
  periods: ScheduleGridPeriod[]
  /** Teams the response labelled — the denominator for a per-team mean. */
  teamCount: number
  /** League-wide games in each period. ADR-012 requires the baseline be shown. */
  periodTotals: number[]
  /** Periods where at least one team's count was not sent. */
  periodMissing: boolean[]
  integrity: ScheduleGridIntegrity
}

function cellKey(teamId: number, periodNumber: number): string {
  return `${String(teamId)}:${String(periodNumber)}`
}

export function buildScheduleGridModel(grid: ScheduleGrid): ScheduleGridModel {
  const byCell = new Map<string, number>()
  let duplicateRows = 0
  let unmatchedRows = 0

  const knownTeams = new Set(grid.teams.map((team) => team.team_id))
  const knownPeriods = new Set(grid.periods.map((period) => period.period_number))

  for (const count of grid.counts) {
    if (!knownTeams.has(count.team_id) || !knownPeriods.has(count.period_number)) {
      unmatchedRows += 1
      continue
    }
    const key = cellKey(count.team_id, count.period_number)
    if (byCell.has(key)) {
      duplicateRows += 1
      continue
    }
    byCell.set(key, count.games)
  }

  const periodTotals = grid.periods.map(() => 0)
  const periodMissing = grid.periods.map(() => false)
  let missingCells = 0

  const rows = grid.teams.map((team) => {
    let total = 0
    let rowMissing = 0

    const cells = grid.periods.map((period, index) => {
      const games = byCell.get(cellKey(team.team_id, period.period_number))
      if (games === undefined) {
        rowMissing += 1
        missingCells += 1
        periodMissing[index] = true
        return null
      }
      total += games
      periodTotals[index] = (periodTotals[index] ?? 0) + games
      return games
    })

    return { team, cells, total, missingCells: rowMissing }
  })

  return {
    rows,
    periods: grid.periods,
    teamCount: grid.teams.length,
    periodTotals,
    periodMissing,
    integrity: {
      missingCells,
      unmatchedRows,
      duplicateRows,
      isDense: missingCells === 0 && unmatchedRows === 0 && duplicateRows === 0,
    },
  }
}

const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

/**
 * `2026-10-19` → `Oct 19`, by string surgery rather than `new Date`.
 *
 * `new Date('2026-10-19')` is parsed as UTC midnight and then displayed in the
 * local zone, so west of Greenwich it renders as the 18th. A period boundary
 * that is off by a day is a wrong answer, not a cosmetic one, and the date has
 * no time component to reason about in the first place.
 */
export function formatIsoDay(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate)
  if (!match) {
    return isoDate
  }
  const month = MONTHS[Number(match[2]) - 1]
  if (month === undefined) {
    return isoDate
  }
  return `${month} ${String(Number(match[3]))}`
}

export function formatPeriodRange(period: ScheduleGridPeriod): string {
  return `${formatIsoDay(period.start_date)} – ${formatIsoDay(period.end_date)}`
}

export const DAY_MS = 86_400_000

export interface RefreshAge {
  /** Whole days between the refresh and now, or null if unparseable. */
  days: number | null
  /** Rendered age, or an explicit statement that the timestamp is unreadable. */
  label: string
}

/**
 * How old the schedule cohort itself is — a different question from how long
 * ago the browser fetched it.
 *
 * ADR-012 requires re-ingest at least weekly, so seven days is the documented
 * cadence rather than a threshold invented here.
 */
export function describeRefreshAge(refreshedAt: string, now: Date): RefreshAge {
  const parsed = new Date(refreshedAt)
  const time = parsed.getTime()
  if (Number.isNaN(time)) {
    return { days: null, label: 'age unknown — the timestamp could not be read' }
  }

  const elapsed = now.getTime() - time
  const days = Math.floor(elapsed / DAY_MS)
  if (elapsed < 0) {
    return { days, label: 'timestamped in the future' }
  }
  if (days < 1) {
    return { days, label: 'refreshed today' }
  }
  return { days, label: days === 1 ? 'refreshed 1 day ago' : `refreshed ${String(days)} days ago` }
}

export const REFRESH_CADENCE_DAYS = 7
