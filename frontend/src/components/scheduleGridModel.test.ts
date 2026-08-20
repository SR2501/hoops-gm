import { describe, expect, it } from 'vitest'
import type { ScheduleGrid } from '../api/types'
import {
  buildScheduleGridModel,
  describeRefreshAge,
  formatIsoDay,
  formatPeriodRange,
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
