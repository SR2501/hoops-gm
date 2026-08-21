/**
 * The absence-reason contract, against **recorded** responses.
 *
 * `schedule-grid-current.recorded.json` cannot exercise any of this. Every one
 * of the four non-empty `date_absence_reason` values fires **zero times**
 * against the live source — all six real pending games carry a date and an
 * empty reason, only their *teams* are undecided — so the whole absence-reason
 * mechanism, both buckets, rested on payloads written from the TypeScript
 * interfaces. That is a mock in the shape of the thing it mocks, and it is
 * structurally blind to the failure a recording exists to catch: a renamed
 * field, a changed serialisation, a value the producer stopped emitting.
 *
 * These two fixtures close that. Neither is hand-written. Each was produced by
 * driving the **in-tree importer** with a doctored `ScheduleLeagueV2` *source*
 * payload, seeding a real database, serving it and capturing the response — so
 * the bytes are the producer's, and the only thing authored was the upstream
 * payload the NBA would have sent:
 *
 * - `schedule-grid-date-faults.recorded.json` — a `1900-01-01` epoch pair in
 *   both time fields (which reconciles, so the parser calls it `implausible`)
 *   and a pair one day apart (`irreconcilable`).
 * - `schedule-grid-date-absent.recorded.json` — both time fields empty
 *   (`not_offered`) and one field withheld (`unreadable`).
 *
 * Between them the four reasons are covered by bytes the producer emitted,
 * which is the only kind of evidence that would survive a field rename.
 *
 * **What they still cannot check.** The doctored source payloads are mine, so
 * these prove the producer classifies *those inputs* that way, not that the NBA
 * will ever send them. And the `''` case — a date published and reconciled — is
 * the one the live cohort does cover, in the fixture beside them.
 */

import { describe, expect, it } from 'vitest'
import absent from '../test/fixtures/schedule-grid-date-absent.recorded.json'
import faults from '../test/fixtures/schedule-grid-date-faults.recorded.json'
import { isScheduleGrid } from '../api/endpoints'
import type { ScheduleGrid } from '../api/types'
import { buildScheduleGridModel } from './scheduleGridModel'

const faultsGrid = faults as unknown as ScheduleGrid
const absentGrid = absent as unknown as ScheduleGrid

describe('recorded responses carrying a date-absence reason', () => {
  it('are accepted by the validator that guards the real request', () => {
    // The assertion these fixtures exist for. Both carry `game_date: null`
    // beside a non-empty reason, which is the pairing the boundary cross-checks
    // — so a producer that stopped sending the reason, or sent one outside the
    // closed set, fails here rather than in a browser.
    expect(isScheduleGrid(faults)).toBe(true)
    expect(isScheduleGrid(absent)).toBe(true)
  })

  it('carry all four non-empty reasons between them, as the producer emitted', () => {
    const reasons = [faultsGrid, absentGrid]
      .flatMap((grid) => grid.lineage.schedule.pending_games)
      .map((game) => game.date_absence_reason)

    expect(new Set(reasons)).toEqual(
      new Set(['implausible', 'irreconcilable', 'not_offered', 'unreadable']),
    )
  })

  it('sorts the producer bytes into wait and investigate', () => {
    // The classification, driven against real serialisation rather than an
    // object built from the interface it is meant to be checking.
    const faulted = buildScheduleGridModel(faultsGrid).pending
    expect(faulted.dateFaulted.map((game) => game.date_absence_reason).sort()).toEqual([
      'implausible',
      'irreconcilable',
    ])
    expect(faulted.awaitingSource).toEqual([])

    const notDated = buildScheduleGridModel(absentGrid).pending
    // `not_offered` waits; `unreadable` does not, even though both arrive with
    // a null date and look identical to anything reading only `game_date`.
    expect(notDated.awaitingSource.map((game) => game.date_absence_reason)).toEqual([
      'not_offered',
    ])
    expect(notDated.dateFaulted.map((game) => game.date_absence_reason)).toEqual(['unreadable'])
  })

  it('places none of them in a column, and loses none of them from the count', () => {
    for (const grid of [faultsGrid, absentGrid]) {
      const model = buildScheduleGridModel(grid)
      const { pending } = model

      expect(model.periodPending.every((bucket) => bucket.length === 0)).toBe(true)
      expect(pending.placedCount).toBe(0)
      // Still counted at season level: a game with no date belongs to no week
      // and cannot be attributed to one, but it exists.
      expect(pending.declaredCount).toBe(2)
      expect(
        pending.placedCount +
          pending.outsidePeriods.length +
          pending.unreadableDate.length +
          pending.awaitingSource.length +
          pending.dateFaulted.length,
      ).toBe(pending.declaredCount)
    }
  })

  it('still satisfies the completeness invariant with no date on either game', () => {
    for (const grid of [faultsGrid, absentGrid]) {
      const { schedule } = grid.lineage
      expect(schedule.resolved_game_count + schedule.pending_game_ids.length).toBe(
        schedule.source_game_count,
      )
      expect(schedule.unresolved_game_ids).toEqual([])
      expect(schedule.pending_games.every((game) => game.game_date === null)).toBe(true)
    }
  })
})
