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
  /**
   * Whether the response carried the ADR-013 block at all.
   *
   * `false` is **not** "nothing is pending". It is "this response cannot say",
   * and the UI must render it as a third thing rather than as a clean bill of
   * health. A backend predating ADR-013 refused unfinished seasons outright,
   * so its silence did once imply completeness — but that is an inference about
   * a backend version the client cannot see, and encoding it here would put a
   * guess where a fact belongs.
   */
  present: boolean
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
   * Detail entries the source published **without a usable date**.
   *
   * `game_date: null`. What that does *not* mean is worth stating first,
   * because an earlier version of this comment got it wrong and the screen
   * repeated the error to a reader. It does not mean "the source has not
   * decided when". `_pending_game_date` in the producer wraps **both** the
   * `gameDateTimeUTC` and `gameDateTimeEst` parses in one
   * `except SourceContractError: return None`, so `null` covers three
   * situations and only the third is the source declining to commit:
   *
   * 1. `gameDateTimeUTC` could not be read — *we* failed to read a date the
   *    source did give.
   * 2. `gameDateTimeEst` could not be read — likewise.
   * 3. The two are irreconcilable — the source's own fields disagree.
   *
   * The producer's own summary is honest about this: *"or `None` if it is not
   * trustworthy"*. The slippage to "the source has not told us when" happens in
   * its next paragraph and I inherited and amplified it. **The direction of the
   * error is what makes it matter**: told the source has not decided, a reader
   * waits; told we could not read it, a reader investigates. Attributing a
   * parse failure to the source errs toward false comfort, which is the
   * `0`-versus-`·` collapse this file exists to refuse, pointed the other way.
   *
   * So nothing here attributes a cause. The rendered clause says *no usable
   * date came with it*, which is true under all three. If the producer ever
   * narrows its `except` so `null` means only case 3, this can say more.
   *
   * Kept apart from `unreadableDate` because the two prescribe different
   * actions and print different things — `unreadableDate` prints the offending
   * value, which is evidence, where there is no value to print here. Note the
   * split is narrower than "three-way" suggests: the old bucket could never
   * hold a `null`, because the validator rejected nulls, so this is a rename
   * plus one new state for one new contract value.
   *
   * **The obligation not to drop these is real, and it is not in ADR-013.** An
   * earlier version of this comment quoted *"a consumer must then treat the
   * game as belonging to no known period rather than dropping it"* as ADR text.
   * It is not: it is the `PendingScheduleGameLineage` docstring in
   * `backend/src/hoops_gm/api/routes/schedule_grid.py` on the unmerged
   * `sr2501-real-schedule-import`. ADR-013's actual consumer clause is
   * *"Consumers displaying schedule counts must show the pending set, not
   * merely omit it"*, which supports the same conclusion from an address that
   * exists. Citing an unmerged branch as an accepted decision is the
   * coding-against-something-in-no-branch pattern moved into the citation
   * layer, and it is worse there, because a reader who checks and finds nothing
   * may conclude the constraint was invented.
   *
   * That clause cuts two ways and only one is about columns. A game with no
   * date belongs to no week, so it cannot be attributed to one — but the
   * **season** figure must still count it. Different denominators, and a
   * per-week view being honestly incomplete does not license the season view to
   * be wrong.
   *
   * **It is a drift signal, not the present state.** Against the live source
   * all six pending games currently carry reconcilable dates and the live smoke
   * asserts exactly that, so this bucket should be empty on every real response
   * today. Nothing here should be shaped around it being common — over-building
   * for a state that will not arrive is as wrong as rejecting it, and equally
   * available.
   */
  undatedBySource: SchedulePendingGame[]
  /**
   * Detail entries whose `game_date` is present but not a readable ISO day.
   *
   * A **defect**, not a fact — and the reason first written here was measured
   * and found false. It claimed `'12/04/2026' <= '2026-12-13'` compares false
   * and would drop a game out of its column without a word. It compares *true*;
   * and a slash-formatted date fails `start_date <= game_date` against every
   * period, so unguarded it lands in `outsidePeriods` and the notice prints it.
   * Neither half of that justification survived being run.
   *
   * The guard is still right, for the failure that is actually plausible. The
   * drift to expect is `date` → `datetime` on the Pydantic field, giving
   * `2026-12-04T00:00:00Z`. Measured, that buckets *correctly* everywhere
   * except a period whose `end_date` is the game's own day, where
   * `'2026-12-04T00:00:00Z' <= '2026-12-04'` is false — so the game silently
   * falls out of the one column it belongs in and is then reported as *"falls
   * outside every scoring period this grid shows"*, which is a statement about
   * the fantasy calendar made about a data defect.
   *
   * So the value of this guard is that it prevents a **mis-attributed
   * explanation**, not that it prevents silence. That is why the id/record
   * states went and this one stayed: those are forbidden by an invariant the
   * client now checks at the boundary (`isPendingBlock`), and a boundary that
   * can be closed should be closed rather than narrated. The wire date format
   * is not ours to close.
   *
   * **And this bucket does not catch every mis-attribution, which the split's
   * framing can obscure.** `ISO_DAY` accepts any well-formed day, so a
   * degenerate *sentinel* — `0001-01-01`, which the producer's own docstring
   * names as what the source emits for an undecided tip-off, or `1900-01-01` —
   * passes it, matches no period, and lands in `outsidePeriods`, where it is
   * described as falling outside the fantasy calendar. That is the exact
   * mis-attribution named above, arriving through the one door this guard does
   * not cover.
   *
   * It is deliberately not coded around. The client cannot distinguish a
   * sentinel from a genuine out-of-calendar date without inventing a rule —
   * "before 1901", "more than a season before the first period" — and inventing
   * rules about what a date means is what this screen refuses to do everywhere
   * else. Two things limit the damage: the `outsidePeriods` clause prints the
   * date, so `on 0001-01-01` discloses itself to anyone reading it, and the
   * producer nulls the sentinel today. The second is a one-commit-old behaviour
   * on another branch, so this is a real dependency rather than a theoretical
   * one. **These three buckets partition what the client can tell apart, not
   * what the states are.**
   */
  unreadableDate: SchedulePendingGame[]
}

export const EMPTY_PENDING: PendingGamesSummary = {
  present: false,
  declaredCount: 0,
  placedCount: 0,
  outsidePeriods: [],
  undatedBySource: [],
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
 * carry a date. The backend guarantees the two name the same games, so no
 * reconciliation happens here.
 *
 * A date matching more than one period is assigned to the first, so the
 * per-period buckets and the leftovers always sum to the games that had a
 * readable date. Overlapping periods would be a calendar defect upstream.
 */
export function readPendingGames(
  schedule: ScheduleGrid['lineage']['schedule'],
  periods: ScheduleGridPeriod[],
): { summary: PendingGamesSummary; periodPending: SchedulePendingGame[][] } {
  const ids = schedule.pending_game_ids
  const games = schedule.pending_games
  const periodPending: SchedulePendingGame[][] = periods.map(() => [])

  if (ids === undefined || games === undefined) {
    return { summary: { ...EMPTY_PENDING, present: false }, periodPending }
  }

  const outsidePeriods: SchedulePendingGame[] = []
  const undatedBySource: SchedulePendingGame[] = []
  const unreadableDate: SchedulePendingGame[] = []
  let placedCount = 0

  for (const game of games) {
    // Checked before the format guard, because the two mean opposite things.
    // `null` is the source stating it has not decided when; anything else that
    // fails `ISO_DAY` is something having gone wrong on the way here. Folding
    // the first into the second would report a published fact as a fault.
    if (game.game_date === null) {
      undatedBySource.push(game)
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
      present: true,
      declaredCount: ids.length,
      placedCount,
      outsidePeriods,
      undatedBySource,
      unreadableDate,
    },
    periodPending,
  }
}

/**
 * Pending games the response declared but the grid could not put in a column.
 *
 * Equal to `outsidePeriods.length + undatedBySource.length +
 * unreadableDate.length` — **three** terms since the nullable-date contract
 * landed, where this comment previously named two and one of them by a field
 * name that no longer exists. It is a cross-check rather than an independent
 * quantity, which is what the model test uses it for: computed from
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
