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
 * ADR-013 adds a third thing that is neither: a game the **source** has
 * published without deciding its teams. That is not a hole in our data and not
 * a zero — it is the schedule itself being unfinished. Crucially it is
 * **period-scoped and never cell-scoped**, because a pending game has no teams
 * by definition and so can never be attributed to a row. `readPendingGames`
 * places it on the calendar and nowhere else; there is deliberately no API here
 * for asking whether a *cell* is pending, because the data cannot answer it.
 *
 * Everything here is descriptive arithmetic — sums of integers the backend
 * sent. No thresholds, no "light week", no judgement about whether a count is
 * good. Those belong to `quant` behind the Model gate (ADR-009), and inventing
 * them in a UI would ship an unbacktested model in CSS.
 */

import { WAIT_ABSENCE_REASONS } from '../api/types'
import type {
  ScheduleGrid,
  ScheduleGridPeriod,
  ScheduleGridTeam,
  SchedulePendingGame,
} from '../api/types'

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
  /** Teams the response labelled. */
  teamCount: number
  /** League-wide games in each period. ADR-012 requires the baseline be shown. */
  periodTotals: number[]
  /**
   * Teams that actually reported a count in each period.
   *
   * The denominator for a per-period mean, and it is deliberately not
   * `teamCount`. Dividing a numerator summed over the teams that reported by a
   * denominator counting every team produces a number that is the mean of no
   * set at all — biased low by exactly the missing share, and biased in the
   * direction that makes every team's own count look healthier than it is.
   */
  periodReportingTeams: number[]
  /** Periods where at least one team's count was not sent. */
  periodMissing: boolean[]
  /**
   * Pending games falling in each period, in `periods` order.
   *
   * Parallel to `periodTotals` rather than keyed by period number so the table
   * can index it the same way it indexes everything else.
   */
  periodPending: SchedulePendingGame[][]
  pending: PendingGamesSummary
  integrity: ScheduleGridIntegrity
}

function cellKey(teamId: number, periodNumber: number): string {
  return `${String(teamId)}:${String(periodNumber)}`
}

/* --- Pending games (ADR-013) ---------------------------------------------- */

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

/**
 * What the response said about games the source has not yet assigned teams to.
 *
 * Every field here exists because it supports a sentence a reader can act on,
 * and each names a distinct way the pending set can fail to reach a column.
 * They are kept apart rather than summed into one "problems" count because
 * "the backend sent no pending block at all" and "one pending game is dated
 * outside every scoring period" call for different responses from the person
 * reading them.
 */
export interface PendingGamesSummary {
  /** Size of `pending_game_ids` — the set the completeness invariant counts. */
  declaredCount: number
  /** Pending games successfully placed in one of the periods on screen. */
  placedCount: number
  /**
   * Detail entries whose `game_date` fell in no period the grid displays.
   *
   * Genuinely reachable: a fantasy calendar need not span the whole NBA season,
   * and the NBA Cup knockout dates sit in early-to-mid December where a league
   * that starts late would have no period.
   */
  outsidePeriods: SchedulePendingGame[]
  /**
   * Pending games with no date, where the source has **not committed** to one.
   *
   * `date_absence_reason` of `not_offered`: both time fields absent, nothing
   * published. The only cause whose meaning is certain by construction, and the
   * only one that means *wait*.
   *
   * **Operator action: wait.** A date arrives when the bracket is drawn.
   *
   * `irreconcilable` used to sit here, on the grounds that the producer leaves
   * the import at exit 0 for it. That sentence stayed *literally true* after
   * ADR-013 moved it — `not_offered` really is exit 0 — while the inference it
   * licensed, exit 0 implies wait, was exactly what the ruling overturned. So
   * it is deleted rather than amended: a claim that stops being the reason and
   * keeps the grammar of one is the most survivable form of a stale citation,
   * because it passes review as a true statement.
   */
  awaitingSource: SchedulePendingGame[]
  /**
   * Pending games with no date, where **something needs looking at**.
   *
   * Everything that is not `not_offered`: `unreadable` (a value was published
   * and we could not parse it, or the schema moved), `implausible` (both fields
   * parsed, agreed, and named a date nowhere near the season — the NBA uses a
   * `1900-01-01` epoch as a live placeholder and a placeholder pair reconciles
   * perfectly, so **agreement is not validity**), and `irreconcilable` (both
   * parsed and disagree).
   *
   * **Operator action: investigate.** Kept apart from `awaitingSource` for the
   * one reason ADR-013 names as the error that matters — *"rendering an
   * investigate-class cause as a wait-class one"*. Told to wait, an operator
   * waits through a defect.
   *
   * This is the third time this screen has drawn the same distinction and the
   * first time the contract could support it. `0` versus `·` separates a real
   * count from our gap at cell level; `TBD` separates the source's undecided
   * from our gap at column level; this separates the source's undecided from
   * something worth a look at the reason level. An earlier version collapsed
   * all four causes into one bucket and rendered them as *"none came with it"*,
   * which is false for three of them and false toward comfort.
   */
  dateFaulted: SchedulePendingGame[]
  /**
   * Pending games whose `game_date` is present but not a readable ISO day.
   *
   * A **client-side** guard, and distinct from `dateFaulted`, which is the
   * *producer* telling us it could not derive a date. This one fires when the
   * producer thinks it did.
   *
   * The reason first written here was measured and found false: it claimed
   * `'12/04/2026' <= '2026-12-13'` compares false and would drop a game
   * silently. It compares *true*, and a slash date fails `start_date <=
   * game_date` against every period, so unguarded it lands in `outsidePeriods`
   * and the notice prints it. The drift that is actually plausible is `date` →
   * `datetime` on the Pydantic field: `'2026-12-04T00:00:00Z'` buckets
   * correctly everywhere except a period whose `end_date` is the game's own
   * day, where it falls out of the one column it belongs in and is then
   * described as *"falls outside every scoring period this grid shows"* — a
   * statement about the fantasy calendar made about a data defect. **The guard
   * prevents a mis-attributed explanation, not silence.**
   *
   * **It does not catch every mis-attribution.** `ISO_DAY` accepts any
   * well-formed day, so a degenerate sentinel that survived as a real date
   * would pass it and land in `outsidePeriods` with the calendar sentence. The
   * merged producer closes that door — it classifies year-0001 and 1900 pairs
   * as `implausible` or `irreconcilable` and returns no date at all — so it is
   * unreachable *through this seam* and remains real *in general*: the next
   * producer will not have that classifier, and the client still cannot tell a
   * sentinel from a genuine out-of-calendar date without inventing a rule about
   * what a date means, which is what this screen refuses to do everywhere else.
   * **These buckets partition what the client can tell apart, not what the
   * states are.**
   */
  unreadableDate: SchedulePendingGame[]
}

export const EMPTY_PENDING: PendingGamesSummary = {
  declaredCount: 0,
  placedCount: 0,
  outsidePeriods: [],
  awaitingSource: [],
  dateFaulted: [],
  unreadableDate: [],
}

/**
 * Bucket pending games into the scoring periods already on screen.
 *
 * Entirely client-side and needs nothing more from the backend: the response
 * carries `periods[].start_date/end_date` and each pending game carries a
 * `game_date`. Comparison is lexicographic on the ISO strings rather than via
 * `Date`, for the reason `formatIsoDay` documents — `new Date('2026-12-07')` is
 * UTC midnight rendered in the local zone, and a period boundary off by a day
 * puts a game in the wrong column, which is a wrong answer rather than a
 * cosmetic one. Bounds are inclusive at both ends because a scoring period
 * owns its last day.
 *
 * The count comes from `pending_game_ids` and the placement from
 * `pending_games`, matching which field each question is stated over: the
 * completeness invariant is written in terms of the ids, and only the records
 * carry a date. The backend guarantees the two name the same games and
 * `isPendingBlock` checks it, so no reconciliation happens here.
 *
 * A date matching more than one period is assigned to the first, so the
 * per-period buckets and the leftovers always sum to the declared total.
 * Overlapping periods would be a calendar defect upstream.
 */
export function readPendingGames(
  schedule: ScheduleGrid['lineage']['schedule'],
  periods: ScheduleGridPeriod[],
): { summary: PendingGamesSummary; periodPending: SchedulePendingGame[][] } {
  const ids = schedule.pending_game_ids
  const games = schedule.pending_games
  const periodPending: SchedulePendingGame[][] = periods.map(() => [])

  const outsidePeriods: SchedulePendingGame[] = []
  const awaitingSource: SchedulePendingGame[] = []
  const dateFaulted: SchedulePendingGame[] = []
  const unreadableDate: SchedulePendingGame[] = []
  let placedCount = 0

  for (const game of games) {
    // Sorted by what it tells an operator to do, before anything about format.
    // The producer has already decided it could derive no date; all this does
    // is keep its reason from being flattened into one message.
    //
    // The *wait* set is the enumerated one, so anything unrecognised falls to
    // investigate. ADR-013 names rendering an investigate-class cause as a
    // wait-class one as the error that matters, and a default has to point
    // somewhere — this one points at the expensive-but-safe answer. The
    // boundary already refuses reasons outside the closed set, so this can only
    // fire on a value the API would not serve; it costs nothing and it means
    // the safe direction survives the boundary being loosened by someone else.
    if (game.game_date === null) {
      if ((WAIT_ABSENCE_REASONS as readonly string[]).includes(game.date_absence_reason)) {
        awaitingSource.push(game)
      } else {
        dateFaulted.push(game)
      }
      continue
    }

    if (!ISO_DAY.test(game.game_date)) {
      unreadableDate.push(game)
      continue
    }

    const dated = game.game_date
    const index = periods.findIndex(
      (period) => period.start_date <= dated && dated <= period.end_date,
    )
    if (index === -1) {
      outsidePeriods.push(game)
      continue
    }
    periodPending[index]?.push(game)
    placedCount += 1
  }

  return {
    summary: {
      declaredCount: ids.length,
      placedCount,
      outsidePeriods,
      awaitingSource,
      dateFaulted,
      unreadableDate,
    },
    periodPending,
  }
}


/**
 * Pending games the response declared but the grid could not put in a column.
 *
 * Equal to `outsidePeriods.length + awaitingSource.length +
 * dateFaulted.length + unreadableDate.length` — **four** terms since the
 * absence-reason contract landed, where this comment has twice named a set of
 * fields that had moved under it. It is a cross-check rather than an
 * independent quantity, which is what the model test uses it for: computed from
 * `declaredCount` (the invariant's own term) minus what was placed, so if that
 * equality ever stops holding the test says so instead of the screen quietly
 * under-reporting.
 */
export function unplacedPendingCount(summary: PendingGamesSummary): number {
  return summary.declaredCount - summary.placedCount
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
  const periodReportingTeams = grid.periods.map(() => 0)
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
      periodReportingTeams[index] = (periodReportingTeams[index] ?? 0) + 1
      return games
    })

    return { team, cells, total, missingCells: rowMissing }
  })

  const { summary, periodPending } = readPendingGames(grid.lineage.schedule, grid.periods)

  return {
    rows,
    periods: grid.periods,
    teamCount: grid.teams.length,
    periodTotals,
    periodReportingTeams,
    periodMissing,
    periodPending,
    pending: summary,
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
