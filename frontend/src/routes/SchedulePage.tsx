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
        renderError={(error, reload) => <ScheduleGridError error={error} reload={reload} />}
      >
        {(data) => <ScheduleGridView grid={data} />}
      </AsyncBoundary>
    </article>
  )
}

function ScheduleGridView({ grid }: { grid: ScheduleGrid }) {
  const model = useMemo(() => buildScheduleGridModel(grid), [grid])
  const { integrity } = model

  return (
    <>
      <ScheduleLineage lineage={grid.lineage} now={new Date()} />

      {!integrity.isDense ? (
        <p className="state state--error grid__integrity" role="alert" data-testid="grid-integrity">
          This grid is not complete.
          {integrity.missingCells > 0
            ? ` ${String(integrity.missingCells)} of ${String(
                model.rows.length * model.periods.length,
              )} cells had no count and are shown as “·”, which is not the same as zero.`
            : ''}
          {integrity.unmatchedRows > 0
            ? ` ${String(integrity.unmatchedRows)} counts named a team or period that is not in this response and were dropped.`
            : ''}
          {integrity.duplicateRows > 0
            ? ` ${String(integrity.duplicateRows)} duplicate counts were ignored; the first was kept.`
            : ''}
        </p>
      ) : null}

      <ScheduleGridTable model={model} season={grid.season} />

      <p className="page__note grid__key">
        <span className="grid__key-item">
          <span className="grid__cell grid__cell--zero grid__key-swatch">0</span> no game scheduled
        </span>
        <span className="grid__key-item">
          <span className="grid__cell grid__cell--nodata grid__key-swatch">·</span> no data sent
        </span>
        <span className="grid__key-item">
          <span className="grid__playoff-badge">PO</span> fantasy playoff period
        </span>
        <span className="grid__key-item">
          League row: total games scheduled across all teams in that period.
        </span>
      </p>
    </>
  )
}

function ScheduleGridError({ error, reload }: { error: Error | null; reload: () => void }) {
  const described = describeScheduleGridError(error)

  return (
    <div className="state state--error" role="alert" data-testid="schedule-grid-error">
      <p>Could not load the schedule grid.</p>
      <p className="state__detail" data-testid="schedule-grid-error-summary">
        {described.summary}
      </p>
      <p className="state__detail" data-testid="schedule-grid-error-action">
        {described.action}
      </p>
      {described.detail ? (
        <p className="state__meta">
          Backend said: <q>{described.detail}</q>
        </p>
      ) : null}
      {described.code || described.requestId ? (
        <p className="state__meta">
          {described.code ? (
            <>
              Code <code>{described.code}</code>
            </>
          ) : null}
          {described.code && described.requestId ? ' · ' : null}
          {described.requestId ? (
            <>
              Request <code>{described.requestId}</code>
            </>
          ) : null}
        </p>
      ) : null}
      <button type="button" onClick={reload}>
        Retry
      </button>
    </div>
  )
}
