import { describe, expect, it } from 'vitest'
import type { ScheduleGrid, SchedulePendingGame } from '../api/types'
import {
  buildScheduleGridModel,
  describeRefreshAge,
  formatIsoDay,
  formatPeriodRange,
  unplacedPendingCount,
} from './scheduleGridModel'

function grid(overrides: Partial<ScheduleGrid> = {}): ScheduleGrid {
  return {
    league_id: 1,
    season: '2026-27',
    lineage: {
      schedule: {
        refresh_id: 1,
        version: 'abc',
        refreshed_at: '2026-08-20T12:00:00Z',
        source_game_count: 2,
        resolved_game_count: 2,
        persisted_team_row_count: 4,
        unresolved_game_ids: [],
      },
      scoring_period_projection: {
        refresh_id: 2,
        version: 'def',
        refreshed_at: '2026-08-20T12:00:00Z',
      },
      deadline_calendar: { id: 1, version: 1 },
      settings_snapshot: { id: 1, version: 1 },
    },
    teams: [
      { team_id: 1, nba_team_id: 1610612737, abbreviation: 'ATL', name: 'Atlanta Hawks' },
      { team_id: 2, nba_team_id: 1610612738, abbreviation: 'BOS', name: 'Boston Celtics' },
    ],
    periods: [
      { period_number: 1, start_date: '2026-10-19', end_date: '2026-10-25', is_playoff: false },
      { period_number: 2, start_date: '2026-10-26', end_date: '2026-11-01', is_playoff: true },
    ],
    counts: [
      { period_number: 1, team_id: 1, games: 0 },
      { period_number: 1, team_id: 2, games: 4 },
      { period_number: 2, team_id: 1, games: 2 },
      { period_number: 2, team_id: 2, games: 0 },
    ],
    ...overrides,
  }
}

describe('buildScheduleGridModel', () => {
  it('lays a dense response out in header order rather than wire order', () => {
    const shuffled = grid({
      counts: [
        { period_number: 2, team_id: 2, games: 0 },
        { period_number: 1, team_id: 2, games: 4 },
        { period_number: 2, team_id: 1, games: 2 },
        { period_number: 1, team_id: 1, games: 0 },
      ],
    })

    const model = buildScheduleGridModel(shuffled)

    expect(model.rows.map((row) => row.cells)).toEqual([
      [0, 2],
      [4, 0],
    ])
    expect(model.integrity.isDense).toBe(true)
  })

  it('keeps a zero as a zero rather than turning it into absence', () => {
    const model = buildScheduleGridModel(grid())

    expect(model.rows[0]?.cells[0]).toBe(0)
    expect(model.rows[0]?.cells[0]).not.toBeNull()
    expect(model.integrity.missingCells).toBe(0)
  })

  it('marks a cell the backend never sent as absent, not as zero', () => {
    const sparse = grid({
      counts: [
        { period_number: 1, team_id: 1, games: 0 },
        { period_number: 1, team_id: 2, games: 4 },
        { period_number: 2, team_id: 2, games: 0 },
      ],
    })

    const model = buildScheduleGridModel(sparse)

    expect(model.rows[0]?.cells).toEqual([0, null])
    expect(model.rows[0]?.missingCells).toBe(1)
    expect(model.integrity.missingCells).toBe(1)
    expect(model.integrity.isDense).toBe(false)
    expect(model.periodMissing).toEqual([false, true])
    // The denominator for the per-period mean counts only the cells the
    // numerator summed. Both the unmatched-row and duplicate-row paths skip
    // the increment, so this needs its own guard rather than riding on totals.
    expect(model.periodReportingTeams).toEqual([2, 1])
    expect(model.teamCount).toBe(2)
  })

  it('does not count an unmatched or duplicate row toward the mean denominator', () => {
    const messy = grid({
      counts: [
        ...grid().counts,
        { period_number: 1, team_id: 1, games: 9 },
        { period_number: 1, team_id: 99, games: 9 },
      ],
    })

    const model = buildScheduleGridModel(messy)

    expect(model.integrity.duplicateRows).toBe(1)
    expect(model.integrity.unmatchedRows).toBe(1)
    // Two real teams reported each period; neither stray row inflates it.
    expect(model.periodReportingTeams).toEqual([2, 2])
  })

  it('totals only what it was told, so a missing cell cannot inflate a row', () => {
    const sparse = grid({
      counts: [
        { period_number: 1, team_id: 1, games: 3 },
        { period_number: 1, team_id: 2, games: 4 },
        { period_number: 2, team_id: 2, games: 1 },
      ],
    })

    const model = buildScheduleGridModel(sparse)

    expect(model.rows[0]?.total).toBe(3)
    expect(model.periodTotals).toEqual([7, 1])
  })

  it('reports counts naming a team or period it has no header for', () => {
    const stray = grid({
      counts: [
        ...grid().counts,
        { period_number: 99, team_id: 1, games: 5 },
        { period_number: 1, team_id: 99, games: 5 },
      ],
    })

    const model = buildScheduleGridModel(stray)

    expect(model.integrity.unmatchedRows).toBe(2)
    expect(model.integrity.isDense).toBe(false)
    expect(model.periodTotals).toEqual([4, 2])
  })

  it('reports duplicate counts and keeps the first', () => {
    const duplicated = grid({
      counts: [...grid().counts, { period_number: 1, team_id: 1, games: 9 }],
    })

    const model = buildScheduleGridModel(duplicated)

    expect(model.integrity.duplicateRows).toBe(1)
    expect(model.rows[0]?.cells[0]).toBe(0)
  })

  it('gives the league-wide baseline each period, so a sparse period reads as sparse', () => {
    const model = buildScheduleGridModel(grid())

    expect(model.periodTotals).toEqual([4, 2])
  })
})

describe('readPendingGames', () => {
  function pending(
    overrides: Partial<SchedulePendingGame> = {},
    id = '0022601201',
  ): SchedulePendingGame {
    return {
      nba_game_id: id,
      game_date: '2026-10-21',
      game_label: 'Emirates NBA Cup',
      game_sub_label: 'Quarterfinal',
      game_subtype: 'in-season-knockout',
      ...overrides,
    }
  }

  function withPending(games: SchedulePendingGame[], ids?: string[]): ScheduleGrid {
    const base = grid()
    return {
      ...base,
      lineage: {
        ...base.lineage,
        schedule: {
          ...base.lineage.schedule,
          source_game_count: base.lineage.schedule.resolved_game_count + games.length,
          pending_game_ids: ids ?? games.map((game) => game.nba_game_id),
          pending_games: games,
        },
      },
    }
  }

  it('puts a pending game in the period whose range contains its date', () => {
    const model = buildScheduleGridModel(withPending([pending({ game_date: '2026-10-28' })]))

    expect(model.periodPending[0]).toEqual([])
    expect(model.periodPending[1]?.map((game) => game.nba_game_id)).toEqual(['0022601201'])
    expect(model.pending.placedCount).toBe(1)
    expect(model.pending.declaredCount).toBe(1)
  })

  it('treats both period bounds as inside, because a period owns its last day', () => {
    // Period 1 is 2026-10-19..2026-10-25. The exclusive-end mistake would drop
    // the 25th into no column at all and quietly understate that week.
    const model = buildScheduleGridModel(
      withPending([
        pending({ game_date: '2026-10-19' }, 'a'),
        pending({ game_date: '2026-10-25' }, 'b'),
        pending({ game_date: '2026-10-26' }, 'c'),
      ]),
    )

    expect(model.periodPending[0]?.map((game) => game.nba_game_id)).toEqual(['a', 'b'])
    expect(model.periodPending[1]?.map((game) => game.nba_game_id)).toEqual(['c'])
    expect(model.pending.outsidePeriods).toEqual([])
  })

  it('does not let a timezone move a pending game into the wrong column', () => {
    // `new Date('2026-10-26')` is UTC midnight, which is 2026-10-25 anywhere
    // west of Greenwich — one column to the left, silently. This is the same
    // defect `formatIsoDay` exists to avoid, arriving by a different route, so
    // the comparison is lexicographic on the ISO strings and never via `Date`.
    const model = buildScheduleGridModel(withPending([pending({ game_date: '2026-10-26' })]))

    expect(model.periodPending[0]).toEqual([])
    expect(model.periodPending[1]).toHaveLength(1)
  })

  it('reports a pending game outside every period rather than dropping it', () => {
    // A fantasy calendar need not span the NBA season, so a December knockout
    // fixture can legitimately land in no scoring period at all.
    const model = buildScheduleGridModel(withPending([pending({ game_date: '2026-09-30' })]))

    expect(model.periodPending.every((bucket) => bucket.length === 0)).toBe(true)
    expect(model.pending.outsidePeriods.map((game) => game.nba_game_id)).toEqual(['0022601201'])
    expect(model.pending.placedCount).toBe(0)
    expect(unplacedPendingCount(model.pending)).toBe(1)
  })

  it('refuses to place a date it cannot read, instead of comparing it anyway', () => {
    // `'12/04/2026' <= '2026-10-25'` is a perfectly well-formed string
    // comparison that answers a question about neither date. Left unguarded it
    // would put the game in a column, or in none, with equal confidence and no
    // mention — which is the silent version of this whole defect class.
    const model = buildScheduleGridModel(withPending([pending({ game_date: '12/04/2026' })]))

    expect(model.periodPending.every((bucket) => bucket.length === 0)).toBe(true)
    expect(model.pending.undated.map((game) => game.nba_game_id)).toEqual(['0022601201'])
    expect(model.pending.outsidePeriods).toEqual([])
  })

  it('counts the ids the invariant is written over, not the records', () => {
    // `source_game_count == resolved_game_count + pending_game_ids.length` is
    // stated over the id array. The backend derives the ids from the records so
    // the two agree, but the count on screen has to be the invariant's term.
    const model = buildScheduleGridModel(withPending([pending()], ['0022601201', '0022601202']))

    expect(model.pending.declaredCount).toBe(2)
    expect(model.pending.placedCount).toBe(1)
    expect(unplacedPendingCount(model.pending)).toBe(1)
  })

  it('distinguishes a response with no pending games from one that cannot say', () => {
    // The whole point. `present: false` must never be read as "nothing is
    // pending" — one response asserts the season is fully scheduled and the
    // other asserts nothing at all.
    const declaredNone = buildScheduleGridModel(withPending([]))
    expect(declaredNone.pending.present).toBe(true)
    expect(declaredNone.pending.declaredCount).toBe(0)

    const silent = buildScheduleGridModel(grid())
    expect(silent.pending.present).toBe(false)
    expect(silent.pending.declaredCount).toBe(0)
    expect(silent.periodPending).toEqual([[], []])
  })

  it('is only satisfied when both halves of the block arrived', () => {
    const base = grid()
    const halfBlock: ScheduleGrid = {
      ...base,
      lineage: {
        ...base.lineage,
        schedule: { ...base.lineage.schedule, pending_game_ids: ['0022601201'] },
      },
    }

    expect(buildScheduleGridModel(halfBlock).pending.present).toBe(false)
  })

  it('keeps every declared game accounted for somewhere', () => {
    // The arithmetic a reader does on screen: placed columns plus the stated
    // exceptions must reach the declared total, or the banner is hiding one.
    const model = buildScheduleGridModel(
      withPending([
        pending({ game_date: '2026-10-21' }, 'placed'),
        pending({ game_date: '2026-09-30' }, 'outside'),
        pending({ game_date: 'nonsense' }, 'undated'),
      ]),
    )
    const { pending: summary } = model

    const placedInColumns = model.periodPending.reduce((sum, bucket) => sum + bucket.length, 0)
    expect(placedInColumns).toBe(summary.placedCount)
    expect(
      summary.placedCount + summary.outsidePeriods.length + summary.undated.length,
    ).toBe(summary.declaredCount)
  })
})

describe('formatIsoDay', () => {
  it('formats a calendar date without letting a timezone move it', () => {
    // `new Date('2026-10-19')` is UTC midnight, which renders as the 18th in
    // any negative offset. A period boundary off by a day is a wrong answer.
    expect(formatIsoDay('2026-10-19')).toBe('Oct 19')
    expect(formatIsoDay('2027-01-03')).toBe('Jan 3')
  })

  it('returns an unrecognised value untouched rather than inventing a date', () => {
    expect(formatIsoDay('not-a-date')).toBe('not-a-date')
    expect(formatIsoDay('2026-13-01')).toBe('2026-13-01')
  })

  it('renders a period as its full range', () => {
    expect(
      formatPeriodRange({
        period_number: 1,
        start_date: '2026-10-19',
        end_date: '2026-10-25',
        is_playoff: false,
      }),
    ).toBe('Oct 19 – Oct 25')
  })
})

describe('describeRefreshAge', () => {
  const now = new Date('2026-08-20T12:00:00Z')

  it('reports a same-day refresh as today', () => {
    expect(describeRefreshAge('2026-08-20T09:00:00Z', now)).toEqual({
      days: 0,
      label: 'refreshed today',
    })
  })

  it('counts whole days and singularises one', () => {
    expect(describeRefreshAge('2026-08-19T09:00:00Z', now).label).toBe('refreshed 1 day ago')
    expect(describeRefreshAge('2026-08-10T09:00:00Z', now).label).toBe('refreshed 10 days ago')
  })

  it('says the timestamp is unreadable rather than showing NaN', () => {
    expect(describeRefreshAge('whenever', now)).toEqual({
      days: null,
      label: 'age unknown — the timestamp could not be read',
    })
  })

  it('does not pretend a future timestamp is a fresh one', () => {
    expect(describeRefreshAge('2026-08-25T09:00:00Z', now).label).toBe('timestamped in the future')
  })
})
