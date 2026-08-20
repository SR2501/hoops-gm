/**
 * The schedule grid: teams down, scoring periods across, scheduled game counts
 * in the cells.
 *
 * Descriptive only. There is no colour scale, no "light week" badge and no
 * threshold anywhere in this file, because every one of those is a judgement
 * and judgements about schedule volume belong to `quant` behind the Model gate
 * (ADR-009/ADR-012).
 *
 * Every count renders identically to every other count, **including zero**. An
 * earlier version muted zeros for legibility, which was a two-stop colour scale
 * on the count axis wearing a legibility justification: zero is a count, and it
 * was the one count drawn differently from the rest. It is also the wrong count
 * to de-emphasise — ADR-012's sparse-period amendment makes a zero-game period
 * one of the most decision-bearing values in the table. The only visual
 * distinctions here are between a count, an absent count, and a playoff period,
 * all of which are categories rather than magnitudes.
 */

import type { ScheduleGridModel } from './scheduleGridModel'
import { formatIsoDay, formatPeriodRange } from './scheduleGridModel'

interface ScheduleGridTableProps {
  model: ScheduleGridModel
  season: string
}

export function ScheduleGridTable({ model, season }: ScheduleGridTableProps) {
  const { rows, periods, periodTotals, periodMissing, teamCount } = model
  const seasonTotal = periodTotals.reduce((sum, value) => sum + value, 0)
  const anyMissing = model.integrity.missingCells > 0

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
                title={`Period ${String(period.period_number)}: ${formatPeriodRange(period)}${
                  period.is_playoff ? ' (fantasy playoff period)' : ''
                }`}
              >
                <span className="grid__period-number" aria-hidden="true">
                  {period.period_number}
                </span>
                <span className="grid__period-dates" aria-hidden="true">
                  {formatIsoDay(period.start_date)}
                </span>
                {period.is_playoff ? (
                  <span className="grid__playoff-badge" aria-hidden="true">
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
            <th scope="col" className="grid__total-header" title="Total scheduled games this season">
              Total
            </th>
          </tr>
        </thead>

        <tbody>
          {rows.map((row) => (
            <tr key={row.team.team_id}>
              <th scope="row" className="grid__team" title={row.team.name}>
                <span className="grid__team-abbr" aria-hidden="true">
                  {row.team.abbreviation}
                </span>
                <span className="visually-hidden">{row.team.name}</span>
              </th>
              {periods.map((period, index) => (
                <GridCell
                  key={period.period_number}
                  games={row.cells[index] ?? null}
                  teamAbbreviation={row.team.abbreviation}
                  periodNumber={period.period_number}
                  teamId={row.team.team_id}
                  isPlayoff={period.is_playoff}
                />
              ))}
              <TotalCell
                value={row.total}
                missing={row.missingCells}
                testId={`team-total-${String(row.team.team_id)}`}
                incompleteLabel={`${row.team.abbreviation} season total ${String(
                  row.total,
                )}, incomplete — ${String(row.missingCells)} periods had no data`}
              />
            </tr>
          ))}
        </tbody>

        <tfoot>
          <tr>
            <th scope="row" className="grid__team">
              League
            </th>
            {periods.map((period, index) => (
              <TotalCell
                key={period.period_number}
                value={periodTotals[index] ?? 0}
                missing={periodMissing[index] ? 1 : 0}
                className="grid__cell--league"
                testId={`league-total-${String(period.period_number)}`}
                incompleteLabel={`Period ${String(period.period_number)} league team-games ${String(
                  periodTotals[index] ?? 0,
                )}, incomplete — at least one team had no data`}
              />
            ))}
            <TotalCell
              value={seasonTotal}
              missing={anyMissing ? 1 : 0}
              className="grid__cell--league"
              testId="league-total-season"
              incompleteLabel={`Season league team-games ${String(seasonTotal)}, incomplete`}
            />
          </tr>
          <tr>
            <th scope="row" className="grid__team">
              Per team
            </th>
            {periods.map((period, index) => (
              <td
                key={period.period_number}
                className="grid__cell grid__cell--mean"
                data-testid={`league-mean-${String(period.period_number)}`}
                aria-label={`Period ${String(
                  period.period_number,
                )} mean games per team: ${formatMean(periodTotals[index] ?? 0, teamCount)}`}
              >
                {formatMean(periodTotals[index] ?? 0, teamCount)}
              </td>
            ))}
            <td className="grid__cell grid__cell--mean">{formatMean(seasonTotal, teamCount)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

/**
 * The league mean, so "is this team's 2 unusual for this period?" does not
 * require dividing by 30 in your head under a pick clock.
 *
 * Still descriptive: the integers the backend sent, divided by the number of
 * teams it sent. No reference set is chosen and nothing is compared against a
 * threshold, which is what would make it a model output rather than arithmetic.
 */
function formatMean(total: number, teamCount: number): string {
  if (teamCount === 0) return '—'
  return (total / teamCount).toFixed(1)
}

interface TotalCellProps {
  value: number
  /** Cells that never arrived and so are not counted in `value`. */
  missing: number
  testId: string
  incompleteLabel: string
  className?: string
}

/**
 * A total is a sum over the cells that arrived. When some did not, the number
 * is smaller than the truth, and saying so only in screen-reader text would
 * leave the two most scannable numbers on the grid — the ones a reader compares
 * teams by — looking exactly as trustworthy as a complete sum.
 */
function TotalCell({ value, missing, testId, incompleteLabel, className }: TotalCellProps) {
  const incomplete = missing > 0
  const classes = ['grid__cell', 'grid__total', className, incomplete ? 'grid__total--partial' : '']
    .filter(Boolean)
    .join(' ')

  return (
    <td
      className={classes}
      data-testid={testId}
      data-state={incomplete ? 'partial' : 'complete'}
      {...(incomplete ? { 'aria-label': incompleteLabel, title: incompleteLabel } : {})}
    >
      {value}
      {incomplete ? (
        <span className="grid__partial-mark" aria-hidden="true">
          +?
        </span>
      ) : null}
    </td>
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

  return (
    <td
      className={`grid__cell${playoffClass}`}
      data-testid={testId}
      data-state={games === 0 ? 'zero' : 'count'}
      aria-label={`${teamAbbreviation}, period ${String(periodNumber)}: ${String(games)} ${
        games === 1 ? 'game' : 'games'
      }`}
    >
      {games}
    </td>
  )
}
