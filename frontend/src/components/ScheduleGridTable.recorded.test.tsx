/**
 * The contract test for the schedule grid, against a **recorded** response.
 *
 * `SchedulePage.test.tsx` builds its payloads by hand from the TypeScript
 * interfaces, which means it can only ever prove the code agrees with itself.
 * `schedule-grid-current.recorded.json` is a real 200 captured from the running
 * FastAPI service against the seeded demo database — 30 teams, 21 periods, 630
 * dense counts — so this file is the only place the frontend's assumptions meet
 * something the backend actually produced.
 *
 * Re-captured for ADR-013, and the diff against the previous recording is the
 * evidence that only what ADR-013 moved has moved: teams, periods, all 630
 * counts and the content version are byte-identical, and the delta is the
 * pending block, `source_game_count` 10 → 12, and the timestamp. Capture and
 * *compare* is the check; capture and replace was right here only because the
 * demo seed genuinely changed underneath, and would have destroyed the baseline
 * on any route that had not.
 *
 * It settled two questions guessed at in review. The recorded `refreshed_at`
 * carries a `Z` suffix with microsecond precision, not the `+00:00` form the
 * Pydantic model was assumed to emit; the exact literal is deliberately not
 * quoted, since it changes on every re-capture and a docstring naming a value
 * the fixture no longer holds is a defect this branch has already shipped
 * twice. And the pending games' `game_sub_label` and `game_subtype` arrive as
 * **empty strings**, where a payload written from these types would have
 * carried plausible text — so the empty-label rendering path exists because a
 * recording found it, not because anyone anticipated it.
 *
 * That second finding is real and is **not** the production shape, which is a
 * distinction this file previously got wrong. The committed 12-game fixture the
 * demo seed reads was trimmed before those fields mattered and nulls them; the
 * live payload carries `Quarterfinal` / `Semifinal` and `in-season-knockout`.
 * So this recording exercises the *degenerate* label case and can never
 * exercise the ordinary one, which is the case ADR-013's flip condition is
 * actually checked against. `SchedulePage.test.tsx` covers the labelled case
 * with the live values, and it was driven in a browser separately. A recording
 * proving something true of a fixture is not the same as proving it true of the
 * source, and the gap is exactly the width of whatever the fixture was trimmed
 * for.
 *
 * **What this recording cannot check.** The seed produces 20 non-zero
 * team-games, so 610 of its 630 cells are `0`. It exercises no three-digit
 * league sum, no four-digit season total, no `+?` marker and no column width
 * under realistic magnitudes — precisely the layout questions a recording is
 * otherwise best placed to answer. Nor can it show a pending set that is
 * *empty*, which is what every response will carry from December onwards, or
 * one absent altogether: no backend at this revision emits either, so both are
 * covered only by hand-built payloads in `SchedulePage.test.tsx`. A second
 * capture against a fully ingested 1,230-game season is worth taking when one
 * exists.
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
    expect(schedule.source_game_count).toBe(12)
    expect(schedule.resolved_game_count).toBe(10)
    expect(schedule.persisted_team_row_count).toBe(20)
    expect(schedule.unresolved_game_ids).toEqual([])
    expect(grid.lineage.scoring_period_projection.version).toBe('22a8bac85a909ccd')
    expect(grid.lineage.deadline_calendar).toEqual({ id: 1, version: 1 })
    expect(grid.lineage.settings_snapshot).toEqual({ id: 1, version: 1 })
  })

  it('satisfies the completeness invariant ADR-013 replaced the old one with', () => {
    // `resolved == source` used to hold and no longer does. The recording is
    // the only artefact here that can show the *new* equation closing on a
    // response the backend actually produced, rather than on one built from
    // these types.
    const { schedule } = grid.lineage

    expect(schedule.pending_game_ids).toEqual(['0022601201', '0022601202'])
    expect(schedule.resolved_game_count + (schedule.pending_game_ids?.length ?? 0)).toBe(
      schedule.source_game_count,
    )
    expect(schedule.persisted_team_row_count).toBe(2 * schedule.resolved_game_count)
  })

  it('records the label shape the hand-written payloads would not have guessed', () => {
    // Captured, not invented: in this cohort `game_sub_label` and
    // `game_subtype` are **empty strings**, not nulls and not text. That is an
    // artifact of the committed fixture having been trimmed before those fields
    // mattered, so it is a fact about this recording and not about the source —
    // production carries `Quarterfinal` and `in-season-knockout`. It is still
    // worth pinning, because it is a shape the running service does emit and
    // one no payload written from the TypeScript interface would have produced.
    const pending = grid.lineage.schedule.pending_games ?? []

    expect(pending).toHaveLength(2)
    expect(pending.map((game) => game.game_date)).toEqual(['2026-12-04', '2026-12-04'])
    expect(pending.map((game) => game.game_label)).toEqual([
      'Emirates NBA Cup',
      'Emirates NBA Cup',
    ])
    expect(pending.map((game) => game.game_sub_label)).toEqual(['', ''])
    expect(pending.map((game) => game.game_subtype)).toEqual(['', ''])
  })

  it('marks the period holding the pending games, and only that period', () => {
    const model = buildScheduleGridModel(grid)
    render(<ScheduleGridTable model={model} season={grid.season} />)

    // 2026-12-04 falls in period 7 (Nov 30 – Dec 6) of the seeded calendar.
    // Derived from the recording rather than asserted as a bare 7, so a
    // calendar change moves the expectation instead of failing the test.
    const holding = model.periods.findIndex(
      (period) => period.start_date <= '2026-12-04' && '2026-12-04' <= period.end_date,
    )
    expect(holding).toBeGreaterThanOrEqual(0)
    const holdingNumber = model.periods[holding]?.period_number

    const marked = screen
      .getAllByTestId(/^period-header-/)
      .filter((header) => header.dataset.pending === 'true')
    expect(marked).toHaveLength(1)
    expect(marked[0]).toHaveAttribute(
      'data-testid',
      `period-header-${String(holdingNumber)}`,
    )
    expect(marked[0]).toHaveTextContent('TBD')
    expect(model.pending.placedCount).toBe(2)
    expect(model.pending.outsidePeriods).toEqual([])
    expect(model.pending.undated).toEqual([])
  })

  it('says nothing about any team in the pending column, because it cannot', () => {
    // The load-bearing assertion of this whole feature. A pending game carries
    // `teamId: 0` and four null name fields, so no cell may claim a team is
    // affected. A `0` under a TBD header is a real zero and reads exactly like
    // a `0` anywhere else — same state, same accessible name, no extra title.
    const model = buildScheduleGridModel(grid)
    render(<ScheduleGridTable model={model} season={grid.season} />)

    const holding = model.periods.find(
      (period) => period.start_date <= '2026-12-04' && '2026-12-04' <= period.end_date,
    )
    const pendingColumn = screen.getAllByTestId(
      new RegExp(`^cell-\\d+-${String(holding?.period_number)}$`),
    )
    expect(pendingColumn).toHaveLength(30)

    for (const cell of pendingColumn) {
      expect(cell.dataset.state).toBe('zero')
      expect(cell).toHaveTextContent('0')
      expect(cell.getAttribute('aria-label')).toMatch(/: 0 games$/)
      expect(cell.getAttribute('aria-label')).not.toMatch(/pending|decided|TBD|not yet/i)
      expect(cell.getAttribute('title')).toBeNull()
    }

    // And no cell anywhere on the grid carries a pending marker.
    expect(document.querySelectorAll('td[data-testid^="cell-"] .grid__pending-badge')).toHaveLength(
      0,
    )
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

    // One boundary, which is enough to show the derivation is not tautological:
    // describeRefreshAge(x, x) returning 'refreshed today' proves the function
    // actually reads its second argument.
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
