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
        pending_game_ids: [],
        pending_games: [],
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
      date_absence_reason: '',
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
    // The reason first written here was measured and found false. It claimed
    // `'12/04/2026' <= '2026-12-13'` compares false and would drop a game
    // silently; it compares **true**, and a slash date simply fails
    // `start_date <= game_date` against every period, so unguarded it lands in
    // `outsidePeriods` and the notice prints it. Loud, not silent.
    //
    // The drift worth guarding is `date` → `datetime` on the Pydantic field.
    // That buckets correctly everywhere *except* a period whose `end_date` is
    // the game's own day — see the next test — where it falls out of the one
    // column it belongs in and is then explained as "falls outside every
    // scoring period this grid shows", which is a claim about the fantasy
    // calendar made about a data defect. A mis-attributed explanation is the
    // failure this prevents.
    const model = buildScheduleGridModel(withPending([pending({ game_date: '12/04/2026' })]))

    expect(model.periodPending.every((bucket) => bucket.length === 0)).toBe(true)
    expect(model.pending.unreadableDate.map((game) => game.nba_game_id)).toEqual(['0022601201'])
    expect(model.pending.outsidePeriods).toEqual([])
  })

  it('catches a datetime where a date was promised, at the boundary that would hide it', () => {
    // `'2026-10-25T00:00:00Z' <= '2026-10-25'` is false, so without the guard
    // this game falls out of period 1 — the period it is in — and every other
    // period too, and would then be reported as outside the calendar entirely.
    // Measured: with `end_date` later than the game day it buckets correctly,
    // which is what makes this drift so easy to miss.
    const model = buildScheduleGridModel(
      withPending([pending({ game_date: '2026-10-25T00:00:00Z' })]),
    )

    expect(model.pending.unreadableDate.map((game) => game.nba_game_id)).toEqual(['0022601201'])
    expect(model.pending.outsidePeriods).toEqual([])
    expect(model.periodPending.every((bucket) => bucket.length === 0)).toBe(true)
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

  it('reads an empty pending block as a season that is fully scheduled', () => {
    // There used to be a companion assertion here that an *absent* block reads
    // as "this response cannot say". That state is gone: the backend lane
    // merged, `pending_game_ids` and `pending_games` are required, and
    // `isPendingBlock` refuses a response without them — so the model can
    // assume the block rather than narrate its absence. The refusal is pinned
    // in `SchedulePage.test.tsx` ("refuses a pending block that is present but
    // not the contract"), which is where a boundary belongs.
    const model = buildScheduleGridModel(withPending([]))

    expect(model.pending.declaredCount).toBe(0)
    expect(model.periodPending).toEqual([[], []])
    expect(unplacedPendingCount(model.pending)).toBe(0)
  })

  it('sorts an absent date by what it tells an operator to do, not by its shape', () => {
    // The error ADR-013 names as the one that matters: rendering an
    // investigate-class cause as a wait-class one. `not_offered` is the only
    // cause that means wait — both time fields absent, nothing published.
    //
    // `irreconcilable` sits with the faults **by ADR-013's decision, not by
    // derivation**. An earlier version of this test put it on the wait side and
    // justified that in a comment as mirroring the producer's exit codes, which
    // was a reconstruction rather than a rule: an exit code answers "should
    // this import fail", and this screen answers "should a human look".
    const model = buildScheduleGridModel(
      withPending([
        pending({ game_date: null, date_absence_reason: 'not_offered' }, 'wait-a'),
        pending({ game_date: null, date_absence_reason: 'irreconcilable' }, 'look-a'),
        pending({ game_date: null, date_absence_reason: 'unreadable' }, 'look-b'),
        pending({ game_date: null, date_absence_reason: 'implausible' }, 'look-c'),
      ]),
    )

    expect(model.pending.awaitingSource.map((game) => game.nba_game_id)).toEqual(['wait-a'])
    expect(model.pending.dateFaulted.map((game) => game.nba_game_id)).toEqual([
      'look-a',
      'look-b',
      'look-c',
    ])
    // None of them reaches a column, and all four are still counted.
    expect(model.pending.declaredCount).toBe(4)
    expect(model.pending.placedCount).toBe(0)
    expect(model.periodPending.every((bucket) => bucket.length === 0)).toBe(true)
  })

  it('sends an unrecognised reason to investigate rather than to wait', () => {
    // The wait set is the enumerated one, so a default has to point somewhere
    // and it points at the expensive-but-safe answer. The boundary refuses
    // reasons outside the closed set, so this can only fire on a response the
    // API would not serve — which is the point: the safe direction survives
    // someone else loosening the boundary.
    const model = buildScheduleGridModel(
      withPending([pending({ game_date: null, date_absence_reason: 'newly-invented' }, 'x')]),
    )

    expect(model.pending.dateFaulted.map((game) => game.nba_game_id)).toEqual(['x'])
    expect(model.pending.awaitingSource).toEqual([])
  })

  it('separates a date the source has not set from one this screen cannot read', () => {
    // The two look identical in a summary and mean opposite things. `null` is
    // the source stating it has not decided when — a published fact about an
    // undrawn fixture, the same kind of statement as the `TBD` column marker
    // one field along. Anything else that fails `ISO_DAY` is something having
    // gone wrong between the source and this grid. Reporting the first as the
    // second would tell a reader a fact in the words of a fault, which is the
    // collapse `0` versus `·` refuses at cell level.
    const model = buildScheduleGridModel(
      withPending([
        pending({ game_date: null, date_absence_reason: 'not_offered' }, 'no-date'),
        pending({ game_date: '12/04/2026' }, 'unreadable'),
      ]),
    )

    expect(model.pending.awaitingSource.map((game) => game.nba_game_id)).toEqual(['no-date'])
    expect(model.pending.unreadableDate.map((game) => game.nba_game_id)).toEqual(['unreadable'])
    expect(model.pending.outsidePeriods).toEqual([])
    expect(model.periodPending.every((bucket) => bucket.length === 0)).toBe(true)
    // Still counted. ADR-013: a consumer must treat it as belonging to no known
    // period rather than dropping it, because the game is still published.
    expect(model.pending.declaredCount).toBe(2)
    expect(unplacedPendingCount(model.pending)).toBe(2)
  })

  it('keeps every declared game accounted for somewhere', () => {
    // The arithmetic a reader does on screen: placed columns plus the stated
    // exceptions must reach the declared total, or the notice is hiding one.
    // All five outcomes at once, so the sum is over the whole partition rather
    // than over whichever branches happened to be exercised.
    //
    // This assertion summed four terms and omitted `dateFaulted` until a
    // reviewer compared it against the same sum in
    // `ScheduleAbsenceReasons.recorded.test.tsx`. It passed, because the fixture
    // it built contained no faulted game — a partition assertion that cannot see
    // the term it is missing. The two sums must agree on how many terms the
    // partition has; if you add a bucket, both fail.
    const model = buildScheduleGridModel(
      withPending([
        pending({ game_date: '2026-10-21' }, 'placed'),
        pending({ game_date: '2026-09-30' }, 'outside'),
        pending({ game_date: 'nonsense' }, 'unreadable'),
        pending({ game_date: null, date_absence_reason: 'not_offered' }, 'no-date'),
        pending({ game_date: null, date_absence_reason: 'implausible' }, 'faulted'),
      ]),
    )
    const { pending: summary } = model

    // Each term non-empty, so no branch can be dropped without the sum noticing.
    expect(summary.outsidePeriods).toHaveLength(1)
    expect(summary.unreadableDate).toHaveLength(1)
    expect(summary.awaitingSource).toHaveLength(1)
    expect(summary.dateFaulted).toHaveLength(1)

    const placedInColumns = model.periodPending.reduce((sum, bucket) => sum + bucket.length, 0)
    expect(placedInColumns).toBe(summary.placedCount)
    expect(
      summary.placedCount +
        summary.outsidePeriods.length +
        summary.unreadableDate.length +
        summary.awaitingSource.length +
        summary.dateFaulted.length,
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
