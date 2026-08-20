/**
 * Schedule — scheduled games per team, per fantasy scoring period.
 *
 * The earliest genuinely useful thing the schedule data supports (ADR-012):
 * raw counts, available the moment the schedule is ingested, with no
 * availability model and no opponent quality in them. Two-game weeks and
 * five-game weeks are a draft and trade input on their own.
 *
 * What this screen must never do is imply a verdict. It reports counts and the
 * league-wide baseline for each period, so a sparse period is visible as
 * sparse, and stops there.
 */

import { useMemo } from 'react'
import { getScheduleGrid } from '../api/endpoints'
import { describeScheduleGridError } from '../api/scheduleGridErrors'
import type { ScheduleGrid } from '../api/types'
import { useAsync } from '../api/useAsync'
import { AsyncBoundary } from '../components/AsyncBoundary'
import { ScheduleGridTable } from '../components/ScheduleGridTable'
import { ScheduleLineage } from '../components/ScheduleLineage'
import { buildScheduleGridModel } from '../components/scheduleGridModel'

/**
 * The single league this build serves (ADR-001: one owner, one local league).
 * A league picker arrives with the league-management surface, not before.
 */
const LEAGUE_ID = 1

/**
 * The grid changes when the schedule is re-ingested, not minute to minute, so
 * this is about the reader's confidence that what is on screen came from this
 * sitting rather than one an hour ago — not about the schedule going out of
 * date, which the lineage panel reports separately and on its own clock.
 */
const STALE_AFTER_MS = 5 * 60_000

export function SchedulePage() {
  const grid = useAsync((options) => getScheduleGrid(LEAGUE_ID, options), [])

  return (
    <article className="page">
      <header className="page__header">
        <h1>Schedule</h1>
        <p className="page__lede">
          Scheduled games per team, per fantasy scoring period. Raw counts — no availability, no
          opponent quality, no judgement about whether a week is light or heavy. See{' '}
          <code>docs/decisions/ADR-012-per-week-game-distribution.md</code>.
        </p>
      </header>

      <AsyncBoundary
        state={grid}
        label="the schedule grid"
        staleAfterMs={STALE_AFTER_MS}
        isEmpty={(data) => data.teams.length === 0 || data.periods.length === 0}
        emptyMessage="The backend returned a grid with no teams or no scoring periods, so there is nothing to draw."
        describeError={describeScheduleGridError}
      >
        {(data) => <ScheduleGridView grid={data} fetchedAt={grid.fetchedAt} />}
      </AsyncBoundary>
    </article>
  )
}

function ScheduleGridView({
  grid,
  fetchedAt,
}: {
  grid: ScheduleGrid
  fetchedAt: Date | null
}) {
  const model = useMemo(() => buildScheduleGridModel(grid), [grid])
  // The cohort's age is measured against the moment this response was
  // received, which `useAsync` already records, rather than against a clock
  // read during render. It is a real timestamp tied to the data, so it cannot
  // drift with unrelated re-renders.
  const now = fetchedAt ?? new Date()
  const { integrity } = model

  return (
    <>
      <ScheduleLineage lineage={grid.lineage} now={now} />

      {!integrity.isDense ? (
        <p className="state state--error grid__integrity" role="status" data-testid="grid-integrity">
          This grid is not complete.
          {integrity.missingCells > 0
            ? ` ${String(integrity.missingCells)} of ${String(
                model.rows.length * model.periods.length,
              )} cells had no count and are shown as “·”, which is not the same as zero. Totals containing one are marked “+?”.`
            : ''}
          {integrity.unmatchedRows > 0
            ? ` ${String(integrity.unmatchedRows)} counts named a team or period that is not in this response and were dropped.`
            : ''}
          {integrity.duplicateRows > 0
            ? ` ${String(integrity.duplicateRows)} duplicate counts were ignored; the first was kept.`
            : ''}
        </p>
      ) : null}

      {/* Above the table: the first `·` a reader meets is in row one, and a key
          below thirty rows of grid is a key they have already needed. */}
      <p className="page__note grid__key">
        <span className="grid__key-item">
          <span className="grid__cell grid__key-swatch">0</span> no game scheduled
        </span>
        <span className="grid__key-item">
          <span className="grid__cell grid__cell--nodata grid__key-swatch">·</span> no data sent
        </span>
        <span className="grid__key-item">
          <span className="grid__playoff-badge">PO</span> fantasy playoff period
        </span>
        <span className="grid__key-item">
          <span className="grid__cell grid__total grid__total--partial grid__key-swatch">+?</span>{' '}
          total or mean is missing at least one period
        </span>
        <span className="grid__key-item">
          League row: team-games in that period. Mean row: the same divided by the teams that
          reported it, {model.teamCount} at full strength. In the Total column the mean is over
          teams with a complete row, so it is not the season sum divided by anything on screen.
        </span>
      </p>

      <ScheduleGridTable model={model} season={grid.season} />
    </>
  )
}

