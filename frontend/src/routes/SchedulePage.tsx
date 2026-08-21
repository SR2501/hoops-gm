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
import {
  buildScheduleGridModel,
  type ScheduleGridModel,
} from '../components/scheduleGridModel'

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
      <ScheduleLineage
        lineage={grid.lineage}
        now={now}
        countedTeamGames={model.periodTotals.reduce((sum, value) => sum + value, 0)}
      />

      <PendingNotice model={model} />

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
          <span className="grid__pending-badge">TBD</span> this period contains games whose teams
          the source has not decided — counts in that column may rise
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

/**
 * What the grid cannot say by drawing numbers: the schedule itself is not
 * finished (ADR-013).
 *
 * **Why this is period-scoped and not per-cell.** A pending game is published
 * by the source with `teamId: 0` and `teamName`, `teamCity`, `teamTricode` and
 * `teamSlug` all null. Not having teams is the whole content of the record, so
 * no amount of client-side work can say which rows are affected. "DAL: game not
 * yet scheduled" would be an attribution the source explicitly withheld, and
 * inventing it here would be this project's recurring defect class committed on
 * purpose. What the data does support is a statement about a column, so that is
 * what is made.
 *
 * **Why it is not a `state--error`.** Nothing has gone wrong. The NBA has not
 * yet played the group stage that decides the bracket, and a refresh reporting
 * that is a refresh working correctly. It is styled as a note, and it does not
 * appear at all once the pending set is empty — a caution that fires when
 * nothing is wrong devalues the one beside it that means something.
 *
 * **Why it is not a live region, and what that costs.** It carries no
 * `role="status"`, unlike the stale banner beside it. It is present at first
 * paint and describes the data rather than announcing a change, so the polite
 * queue is the wrong place for it on load: assistive technology would read it
 * against three other regions in nondeterministic order, and `aria-atomic`
 * defaults to true, so a refresh altering one word re-reads all 420 characters.
 *
 * That reasoning covers load and **does not cover refresh**. `AsyncBoundary`
 * has a Refresh button, and a refresh that takes the pending set from empty to
 * non-empty now makes this notice appear with no announcement. The old
 * behaviour was worse on the same path — it re-read the whole paragraph on any
 * word change — and the stale banner already announces "Refreshing", so a
 * screen-reader user knows to re-read. But it is a trade rather than a pure
 * win, and the clean fix if anyone wants it is a region that is empty at mount
 * and live thereafter. `grid-integrity` above still carries `role="status"` and
 * on this reasoning should not; that is `frontend`'s own debt, so it is in
 * `docs/backlog.md` rather than flagged to nobody in a comment.
 *
 * **The three states this screen now keeps apart.** A `0` is a real count of
 * zero scheduled games. A `·` is data the backend did not send. A `TBD` column
 * is the source not having decided yet. They are three different claims about
 * three different parties, and the whole difficulty of this unit is that the
 * first two are cell-level and the third cannot be.
 *
 * **And one distinction below that, in the clauses.** A pending game with no
 * date is not one situation. `awaitingSource` means the source has not
 * committed to a date and an operator should **wait**; `dateFaulted` means a
 * value was published and we could not use it, and an operator should
 * **investigate**. ADR-013 names rendering the second as the first as the error
 * that matters, and an earlier version of this screen made exactly that error
 * — it said *"none came with it"*, which is false for three of the four
 * absence causes, and false in the direction that tells a reader to relax. The
 * reason code is printed alongside each id so the claim is checkable rather
 * than trusted.
 */
function PendingNotice({ model }: { model: ScheduleGridModel }) {
  const { pending, periods, periodPending } = model

  if (pending.declaredCount === 0) {
    return null
  }

  const marked = periods
    .map((period, index) => ({ period, count: (periodPending[index] ?? []).length }))
    .filter((entry) => entry.count > 0)
  const games = pending.declaredCount === 1 ? '1 game' : `${String(pending.declaredCount)} games`
  // "1 of them" is a partitive over a set, and when the whole pending set is a
  // single game there is no "them" to take one of. Reachable, and it is the
  // *common* case — these clauses appear one at a time — which is exactly why
  // the tests using two games could not see it.
  const subject = (n: number) =>
    pending.declaredCount === 1 ? 'That game' : `${String(n)} of them`

  return (
    <p className="state grid__pending-note" data-testid="grid-pending">
      <strong>This season is not fully scheduled.</strong> The source has published {games} without
      deciding which teams play in {pending.declaredCount === 1 ? 'it' : 'them'}, so this grid
      cannot say which teams are affected — that is what pending means, and no team column below
      carries the information.{' '}
      {marked.length > 0 ? (
        <>
          {marked.length === 1 ? 'Scoring period ' : 'Scoring periods '}
          {marked
            .map((entry) => `${String(entry.period.period_number)} (${String(entry.count)})`)
            .join(', ')}{' '}
          {marked.length === 1 ? 'is' : 'are'} marked TBD. Any count in{' '}
          {marked.length === 1 ? 'that column' : 'those columns'} may rise, so a 0 there is today’s
          count and not a confirmed bye.{' '}
        </>
      ) : null}
      {pending.outsidePeriods.length > 0
        ? `${subject(pending.outsidePeriods.length)} ${
            pending.outsidePeriods.length === 1 ? 'falls' : 'fall'
          } outside every scoring period this grid shows, so no column can carry ${
            pending.outsidePeriods.length === 1 ? 'it' : 'them'
          }: ${pending.outsidePeriods
            .map((game) => `${game.nba_game_id} on ${String(game.game_date)}`)
            .join(', ')}. `
        : ''}
      {pending.awaitingSource.length > 0
        ? `${subject(pending.awaitingSource.length)} ${
            pending.awaitingSource.length === 1 ? 'has' : 'have'
          } no date the source has committed to, so ${
            pending.awaitingSource.length === 1 ? 'it falls' : 'they fall'
          } in no column here: ${pending.awaitingSource
            .map((game) => `${game.nba_game_id} (${game.date_absence_reason})`)
            .join(', ')}. `
        : ''}
      {pending.dateFaulted.length > 0
        ? `${subject(pending.dateFaulted.length)} ${
            pending.dateFaulted.length === 1 ? 'carries' : 'carry'
          } no date because a published value could not be used, which needs looking at rather than waiting out: ${pending.dateFaulted
            .map((game) => `${game.nba_game_id} (${game.date_absence_reason})`)
            .join(', ')}. `
        : ''}
      {pending.unreadableDate.length > 0
        ? `${subject(pending.unreadableDate.length)} carried a date this screen could not read, so nothing can be said about which period ${
            pending.unreadableDate.length === 1 ? 'it falls' : 'they fall'
          } in: ${pending.unreadableDate
            .map((game) => `${game.nba_game_id} (${String(game.game_date)})`)
            .join(', ')}. `
        : ''}
      {/*
        No residual clause for "declared but not described". `isPendingBlock`
        now refuses any response whose `pending_game_ids` and `pending_games`
        do not name the same games in the same order, so the shortfall this
        used to narrate cannot reach the render — and the sentence it printed
        was user-facing prose that no test drove, because nothing could
        construct the state to drive it. Closing the hole at the boundary is
        what allows the state to be deleted rather than described.
      */}
      Ids, dates and labels are in the lineage panel above.
    </p>
  )
}

