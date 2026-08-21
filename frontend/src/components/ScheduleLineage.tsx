/**
 * Which schedule cohort produced the numbers on screen.
 *
 * ADR-012 makes the grid a *living* dependency: it is re-ingested and every
 * consumer must expose the version it is reading. A number whose provenance
 * can only be recovered from devtools is not checkable, so this sits on the
 * page, collapsed by default so it does not compete with the grid.
 *
 * `refreshed_at` is shown both derived and verbatim. A self-describing
 * timestamp is precisely the sort of field that can carry a `Z` and not be
 * UTC, and the raw string is what lets someone check the claim against the
 * backend rather than trust this component's arithmetic.
 *
 * `persisted_team_row_count` is shown next to what the grid actually counted,
 * because the two describe the same cohort and a reader can only compare them
 * if both are on the same line. ADR-013 puts `pending` on that same line, since
 * the completeness invariant now reads
 * `source == resolved + pending` and a reader cannot check an equation with a
 * term missing from it.
 *
 * The pending games are listed by id with their dates and labels rather than
 * merely counted. The count is what the invariant needs; the labels are what
 * lets someone check ADR-013's own falsification condition — pending is only
 * *defensible* while the pending set is structurally explicable as an
 * undetermined bracket, and "Emirates NBA Cup — Quarterfinal" is that evidence.
 * A bare count of six would satisfy the arithmetic and show nothing.
 *
 * There is deliberately **no warning** when they differ. On a successful
 * response they differ whenever a persisted game falls outside every scoring
 * period, which is the normal case — a fantasy calendar rarely spans the whole
 * NBA season — so a note would fire on essentially every real response while
 * the fault it was written for (a team persisted but absent from the grid) is
 * refused outright by `schedule_grid.py:482` and never reaches a 200. A caution
 * that fires if and only if nothing is wrong devalues the one beside it that
 * means something. The figures are shown; the interpretation is left to the
 * reader, who has the period boundaries on the same screen.
 */

import type { ScheduleGridLineage, SchedulePendingGame } from '../api/types'
import { describeRefreshAge, REFRESH_CADENCE_DAYS } from './scheduleGridModel'

interface ScheduleLineageProps {
  lineage: ScheduleGridLineage
  now: Date
  /**
   * Games the grid actually counted, so the two can be seen together.
   *
   * Required rather than optional: a cross-check a caller can silently omit
   * without a type error is not a cross-check.
   */
  countedTeamGames: number
}

/**
 * `Emirates NBA Cup — Quarterfinal — In-Season Tournament`, or whichever parts
 * carried text.
 *
 * ADR-013's "what would flip this" clause turns on the pending set staying
 * *structurally explicable*: pending only means "the bracket is undetermined"
 * for as long as the pending games look like knockout fixtures. These labels
 * are the only evidence of that on screen. If they ever stop reading like
 * rounds of a cup, the distinction between "not decided yet" and "the feed is
 * broken" has collapsed, and this row is where a person would notice. A bare
 * count of six would satisfy the arithmetic and show nothing.
 */
function describePendingGame(game: SchedulePendingGame): string {
  const context = [game.game_label, game.game_sub_label, game.game_subtype].filter(
    (part) => part !== '',
  )
  return context.length === 0 ? 'no label given' : context.join(' — ')
}

export function ScheduleLineage({ lineage, now, countedTeamGames }: ScheduleLineageProps) {
  const { schedule } = lineage
  const age = describeRefreshAge(schedule.refreshed_at, now)
  const pastCadence = age.days !== null && age.days >= REFRESH_CADENCE_DAYS
  const pendingIds = schedule.pending_game_ids
  const pendingGames = schedule.pending_games ?? []

  return (
    <details className="lineage" data-testid="schedule-lineage">
      <summary className="lineage__summary">
        <span>
          Schedule <code>{schedule.version}</code>
        </span>
        <span
          className={pastCadence ? 'lineage__age lineage__age--old' : 'lineage__age'}
          data-testid="schedule-age"
        >
          {age.label}
          {pastCadence
            ? ` — older than the weekly re-ingest ADR-012 requires (${String(REFRESH_CADENCE_DAYS)} days)`
            : ''}
        </span>
      </summary>

      <dl className="facts lineage__facts">
        <div className="facts__row">
          <dt>Schedule version</dt>
          <dd>
            <code>{schedule.version}</code> · refresh {schedule.refresh_id}
          </dd>
        </div>
        <div className="facts__row">
          <dt>Refreshed at</dt>
          <dd>
            <code data-testid="schedule-refreshed-at">{schedule.refreshed_at}</code> ({age.label})
          </dd>
        </div>
        <div className="facts__row">
          <dt>Games</dt>
          <dd data-testid="schedule-game-counts">
            {schedule.source_game_count} from source · {schedule.resolved_game_count} resolved ·{' '}
            {pendingIds === undefined ? 'pending not reported' : `${pendingIds.length} pending`} ·{' '}
            {schedule.persisted_team_row_count} team rows persisted · {countedTeamGames} counted in
            this grid
          </dd>
        </div>
        <div className="facts__row">
          <dt>Pending games</dt>
          <dd data-testid="schedule-pending-games">
            {pendingIds === undefined ? (
              'not reported — this response predates the pending-games contract, so it cannot say whether the season is fully scheduled'
            ) : pendingIds.length === 0 ? (
              'none — every game the source published has teams assigned'
            ) : (
              <ul className="lineage__list">
                {pendingGames.map((game) => (
                  <li key={game.nba_game_id}>
                    <code>{game.nba_game_id}</code> · {game.game_date} · {describePendingGame(game)}
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </div>
        <div className="facts__row">
          <dt>Unresolved games</dt>
          <dd>
            {schedule.unresolved_game_ids.length === 0
              ? 'none'
              : schedule.unresolved_game_ids.join(', ')}
          </dd>
        </div>
        <div className="facts__row">
          <dt>Scoring periods</dt>
          <dd>
            <code>{lineage.scoring_period_projection.version}</code> · refresh{' '}
            {lineage.scoring_period_projection.refresh_id} ·{' '}
            <code>{lineage.scoring_period_projection.refreshed_at}</code>
          </dd>
        </div>
        <div className="facts__row">
          <dt>Deadline calendar</dt>
          <dd>
            id {lineage.deadline_calendar.id} · version {lineage.deadline_calendar.version}
          </dd>
        </div>
        <div className="facts__row">
          <dt>Settings snapshot</dt>
          <dd>
            id {lineage.settings_snapshot.id} · version {lineage.settings_snapshot.version}
          </dd>
        </div>
      </dl>

      {/*
        Still no `countsDisagree` note. ADR-013 replaces the old
        `resolved == source` invariant with
        `source == resolved + pending_game_ids.length`, and the backend enforces
        it before the completeness object is built, so a response this endpoint
        serves cannot carry a disagreement for a note to describe. The three
        figures sit on the facts row above where a reader can do the addition
        themselves; a note that can never render is the same error as the
        persisted-count note, in the harmless direction.

        What *is* checkable from here — and is checked, in `SchedulePage` — is
        whether the pending games the response declared could actually be placed
        on the calendar it also sent. That is a property of the pair, not of
        either side, so no backend invariant covers it.
      */}
    </details>
  )
}
