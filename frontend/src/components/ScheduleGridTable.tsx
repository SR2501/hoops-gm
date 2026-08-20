/**
 * The schedule grid: teams down, scoring periods across, scheduled game counts
 * in the cells.
 *
 * Descriptive only. There is no colour scale, no "light week" badge and no
 * threshold anywhere in this file, because every one of those is a judgement
 * and judgements about schedule volume belong to `quant` behind the Model gate
 * (ADR-009/ADR-012). What the screen owes the reader here is the count, the
 * zeros, and an honest marker where a count is missing.
 *
 * Zeros are muted rather than coloured. That is a legibility choice so a row of
 * nothing does not compete with the counts, not a claim that zero is bad — the
 * counts themselves are all rendered identically to each other.
 */

import type { ScheduleGridModel } from './scheduleGridModel'
import { formatIsoDay, formatPeriodRange } from './scheduleGridModel'

interface ScheduleGridTableProps {
  model: ScheduleGridModel
  season: string
}

export function ScheduleGridTable({ model, season }: ScheduleGridTableProps) {
  const { rows, periods, periodTotals, periodMissing } = model

  return (
    <div className="grid-scroll">
      <table className="grid" data-testid="schedule-grid">
        <caption className="grid__caption">
          Scheduled games per team, per {season} fantasy scoring period. Counts only — no
          availability, no opponent quality.
        </caption>
        <thead>
          <tr>
            <th scope="col" className="grid__corner">
              Team
            </th>
            {periods.map((period) => (
              <th
                key={period.period_number}
                scope="col"
                className={period.is_playoff ? 'grid__period grid__period--playoff' : 'grid__period'}
                data-testid={`period-header-${String(period.period_number)}`}
              >
                <span className="grid__period-number">{period.period_number}</span>
                <span className="grid__period-dates">{formatIsoDay(period.start_date)}</span>
                {period.is_playoff ? (
                  <span className="grid__playoff-badge" title="Fantasy playoff period">
                    PO
                  </span>
                ) : null}
                <span className="visually-hidden">
                  {`Period ${String(period.period_number)}, ${formatPeriodRange(period)}${
                    period.is_playoff ? ', fantasy playoff period' : ''
                  }`}
                </span>
              </th>
            ))}
            <th scope="col" className="grid__total-header">
              Total
            </th>
          </tr>
        </thead>

        <tbody>
          {rows.map((row) => (
            <tr key={row.team.team_id}>
              <th scope="row" className="grid__team" title={row.team.name}>
                <span className="grid__team-abbr">{row.team.abbreviation}</span>
                <span className="visually-hidden">{` ${row.team.name}`}</span>
              </th>
              {row.cells.map((games, index) => {
                const period = periods[index]
                if (!period) return null
                return (
                  <GridCell
                    key={period.period_number}
                    games={games}
                    teamAbbreviation={row.team.abbreviation}
                    periodNumber={period.period_number}
                    teamId={row.team.team_id}
                    isPlayoff={period.is_playoff}
                  />
                )
              })}
              <td className="grid__cell grid__total" data-testid={`team-total-${String(row.team.team_id)}`}>
                {row.total}
                {row.missingCells > 0 ? (
                  <span className="visually-hidden">
                    {` — incomplete, ${String(row.missingCells)} periods had no data`}
                  </span>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>

        <tfoot>
          <tr>
            <th scope="row" className="grid__team">
              League
            </th>
            {periods.map((period, index) => (
              <td
                key={period.period_number}
                className="grid__cell grid__cell--league"
                data-testid={`league-total-${String(period.period_number)}`}
              >
                {periodTotals[index] ?? 0}
                {periodMissing[index] ? (
                  <span className="visually-hidden"> (incomplete)</span>
                ) : null}
              </td>
            ))}
            <td className="grid__cell grid__total">
              {periodTotals.reduce((sum, value) => sum + value, 0)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

interface GridCellProps {
  games: number | null
  teamAbbreviation: string
  teamId: number
  periodNumber: number
  isPlayoff: boolean
}

function GridCell({ games, teamAbbreviation, teamId, periodNumber, isPlayoff }: GridCellProps) {
  const testId = `cell-${String(teamId)}-${String(periodNumber)}`
  const playoffClass = isPlayoff ? ' grid__cell--playoff' : ''

  // Absence is not zero. A blank here would let the reader guess, so it gets a
  // marker of its own and an unambiguous label.
  if (games === null) {
    return (
      <td
        className={`grid__cell grid__cell--nodata${playoffClass}`}
        data-testid={testId}
        data-state="no-data"
        aria-label={`${teamAbbreviation}, period ${String(periodNumber)}: no data`}
        title="No data — the backend sent no count for this team and period"
      >
        <span aria-hidden="true">·</span>
      </td>
    )
  }

  const isZero = games === 0
  return (
    <td
      className={`grid__cell${isZero ? ' grid__cell--zero' : ''}${playoffClass}`}
      data-testid={testId}
      data-state={isZero ? 'zero' : 'count'}
      aria-label={`${teamAbbreviation}, period ${String(periodNumber)}: ${String(games)} ${
        games === 1 ? 'game' : 'games'
      }`}
    >
      {games}
    </td>
  )
}
