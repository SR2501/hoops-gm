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
 */

import type { ScheduleGridLineage } from '../api/types'
import { describeRefreshAge, REFRESH_CADENCE_DAYS } from './scheduleGridModel'

interface ScheduleLineageProps {
  lineage: ScheduleGridLineage
  now: Date
}

export function ScheduleLineage({ lineage, now }: ScheduleLineageProps) {
  const { schedule } = lineage
  const age = describeRefreshAge(schedule.refreshed_at, now)
  const pastCadence = age.days !== null && age.days >= REFRESH_CADENCE_DAYS
  const countsDisagree =
    schedule.source_game_count !== schedule.resolved_game_count ||
    schedule.unresolved_game_ids.length > 0

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
            {schedule.persisted_team_row_count} team rows persisted
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

      {countsDisagree ? (
        <p className="lineage__note" role="status">
          Source and resolved game counts differ, so some games in the source were not matched into
          the schedule. The counts above are of what was resolved.
        </p>
      ) : null}
    </details>
  )
}
