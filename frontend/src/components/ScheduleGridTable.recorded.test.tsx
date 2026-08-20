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
 * `refreshed_at` is `2026-08-20T15:10:39.334171Z` — a `Z` suffix with
 * microsecond precision, not the `+00:00` form the Pydantic model was assumed
 * to emit. The test below asserts a UTC designator rather than `Z`
 * specifically, because `+00:00` would be equally correct and equally
 * parseable; pinning the serializer's choice would fail on a change that broke
 * nothing.
 *
 * **What this recording cannot check.** The seed produces 20 non-zero
 * team-games, so 610 of its 630 cells are `0`. It exercises no three-digit
 * league sum, no four-digit season total, no `+?` marker and no column width
 * under realistic magnitudes — precisely the layout questions a recording is
 * otherwise best placed to answer. A second capture against a fully ingested
 * 1,230-game season is worth taking when one exists.
 *
 * If the endpoint's shape changes, this fails here rather than in a browser.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import recorded from '../test/fixtures/schedule-grid-current.recorded.json'
import { isScheduleGrid } from '../api/endpoints'
import type { ScheduleGrid } from '../api/types'
import { ScheduleGridTable } from './ScheduleGridTable'
import { buildScheduleGridModel, DAY_MS, describeRefreshAge } from './scheduleGridModel'

const grid = recorded as unknown as ScheduleGrid

describe('the recorded schedule grid response', () => {
  it('is accepted by the validator that guards the real request', () => {
    // The assertion the whole fixture exists for. Everything else in this file
    // checks fields chosen by hand; this checks the predicate production
    // actually runs, so a renamed or retyped field fails here even if no
    // hand-written assertion happens to touch it.
    expect(isScheduleGrid(recorded)).toBe(true)
  })

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
    // A UTC designator, not `Z` specifically — `+00:00` is equally correct and
    // pinning the serializer's choice would fail on a change that broke nothing.
    expect(grid.lineage.schedule.refreshed_at).toMatch(/(Z|[+-]\d{2}:\d{2})$/)

    // The reference instant is derived from the recording rather than
    // hardcoded. A fixed date makes this assertion depend on what o'clock
    // somebody happened to hit record: the previous hardcoded
    // `2026-08-27T18:00:00Z` left 53 minutes of margin against the next
    // re-capture, and would have failed on a recording taken an hour later
    // while nothing was actually broken.
    const recorded = Date.parse(grid.lineage.schedule.refreshed_at)
    expect(Number.isNaN(recorded)).toBe(false)

    const sevenDaysOn = new Date(recorded + 7 * DAY_MS + 3_600_000)
    const age = describeRefreshAge(grid.lineage.schedule.refreshed_at, sevenDaysOn)
    expect(age.days).toBe(7)
    expect(age.label).toBe('refreshed 7 days ago')

    // And the boundary either side of it, so the derivation is not vacuous.
    expect(describeRefreshAge(grid.lineage.schedule.refreshed_at, new Date(recorded)).label).toBe(
      'refreshed today',
    )
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
    expect(screen.getByTestId('league-total-season')).toHaveTextContent('20')
    // 20 team-games over 30 complete rows.
    expect(screen.getByTestId('league-mean-season')).toHaveTextContent('0.7')

    // Zeros are the common case in this recording and every one is explicit.
    expect(screen.getByTestId('cell-1-1')).toHaveTextContent('0')
    expect(screen.getByTestId('cell-1-1')).toHaveAttribute('data-state', 'zero')

    // A census rather than an emptiness check: every one of the 630 cells is a
    // real count, and none fell through to the no-data marker. An emptiness
    // filter could never fail, since both branches render a glyph.
    const states = screen.getAllByTestId(/^cell-/).map((cell) => cell.dataset.state)
    expect(states).toHaveLength(630)
    expect(new Set(states)).toEqual(new Set(['zero', 'count']))

    // Totals and means are complete, so none of them carries a shortfall mark.
    const derived = screen.getAllByTestId(/^(team-total-|league-total-|league-mean-)/)
    expect(derived.every((cell) => cell.dataset.state === 'complete')).toBe(true)
    expect(derived.every((cell) => (cell.textContent ?? '') !== '')).toBe(true)

    // Period 21 is a fantasy playoff period in the seeded calendar.
    expect(screen.getByTestId('period-header-21')).toHaveTextContent('PO')
    expect(screen.getByTestId('period-header-1')).not.toHaveTextContent('PO')
  })
})
