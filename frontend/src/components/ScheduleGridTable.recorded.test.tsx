/**
 * The contract test for the schedule grid, against a **recorded** response.
 *
 * `SchedulePage.test.tsx` builds its payloads by hand from the TypeScript
 * interfaces, which means it can only ever prove the code agrees with itself.
 * `schedule-grid-current.recorded.json` is a real 200 captured from the running
 * FastAPI service on 2026-08-20 against the seeded demo database — 30 teams, 21
 * periods, 630 dense counts — so this file is the only place the frontend's
 * assumptions meet something the backend actually produced.
 *
 * It also settles a question that was guessed at in review: the recorded
 * `refreshed_at` is `2026-08-20T15:10:39.334171Z`, with a `Z` suffix and
 * microsecond precision, not the `+00:00` form the Pydantic model was assumed
 * to emit. Both parse, but the recorded one is the one that is true.
 *
 * If the endpoint's shape changes, this fails here rather than in a browser.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import recorded from '../test/fixtures/schedule-grid-current.recorded.json'
import type { ScheduleGrid } from '../api/types'
import { ScheduleGridTable } from './ScheduleGridTable'
import { buildScheduleGridModel, describeRefreshAge } from './scheduleGridModel'

const grid = recorded as unknown as ScheduleGrid

describe('the recorded schedule grid response', () => {
  it('is dense, exactly as the contract states', () => {
    const model = buildScheduleGridModel(grid)

    expect(grid.counts).toHaveLength(grid.teams.length * grid.periods.length)
    expect(model.integrity).toEqual({
      missingCells: 0,
      unmatchedRows: 0,
      duplicateRows: 0,
      isDense: true,
    })
  })

  it('carries the lineage fields the screen displays', () => {
    const { schedule } = grid.lineage

    expect(schedule.version).toBe('9bcac1c60490b41a')
    expect(schedule.source_game_count).toBe(10)
    expect(schedule.resolved_game_count).toBe(10)
    expect(schedule.persisted_team_row_count).toBe(20)
    expect(schedule.unresolved_game_ids).toEqual([])
    expect(grid.lineage.scoring_period_projection.version).toBe('22a8bac85a909ccd')
    expect(grid.lineage.deadline_calendar).toEqual({ id: 1, version: 1 })
    expect(grid.lineage.settings_snapshot).toEqual({ id: 1, version: 1 })
  })

  it('has a timestamp the age calculation can actually read', () => {
    // The wire form is `Z`, not `+00:00`. Asserted against the recording so a
    // change in serialisation is caught here rather than shown as
    // "age unknown" in the corner of a page nobody is looking at.
    expect(grid.lineage.schedule.refreshed_at).toMatch(/Z$/)
    const age = describeRefreshAge(
      grid.lineage.schedule.refreshed_at,
      new Date('2026-08-27T18:00:00Z'),
    )
    expect(age.days).toBe(7)
    expect(age.label).toBe('refreshed 7 days ago')
  })

  it('renders 30 teams and 21 periods with the seeded counts', () => {
    const model = buildScheduleGridModel(grid)
    render(<ScheduleGridTable model={model} season={grid.season} />)

    expect(model.rows).toHaveLength(30)
    expect(model.periods).toHaveLength(21)

    // The seed produces 20 non-zero team-games: 6 in period 1, 14 in period 21.
    expect(model.periodTotals.reduce((sum, value) => sum + value, 0)).toBe(20)
    expect(screen.getByTestId('league-total-1')).toHaveTextContent('6')
    expect(screen.getByTestId('league-total-21')).toHaveTextContent('14')

    // Zeros are the common case in this recording and every one is explicit.
    expect(screen.getByTestId('cell-1-1')).toHaveTextContent('0')
    expect(screen.getByTestId('cell-1-1')).toHaveAttribute('data-state', 'zero')
    expect(screen.queryAllByTestId(/^cell-/).filter((cell) => cell.textContent === '')).toHaveLength(
      0,
    )

    // Period 21 is a fantasy playoff period in the seeded calendar.
    expect(screen.getByTestId('period-header-21')).toHaveTextContent('PO')
    expect(screen.getByTestId('period-header-1')).not.toHaveTextContent('PO')
  })
})
