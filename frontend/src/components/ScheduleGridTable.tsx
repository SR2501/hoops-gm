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
 * distinctions here are between a count, an absent count, a playoff period and
 * a period the source has not finished scheduling, all of which are categories
 * rather than magnitudes.
 *
 * **The pending marker is on the column and never on a cell.** ADR-013's
 * pending games are published by the source with `teamId: 0` and every team
 * name field null, so there is no team to attribute one to. A per-cell "DAL:
 * not yet scheduled" badge would invent exactly the attribution the source
 * withheld. What is true is period-scoped — *this column contains games whose
 * teams are not decided, so any count in it may rise* — and that is what the
 * header says.
 *
 * **The caption carries the other incompleteness, the one nothing can mark.**
 * ADR-013 names two: games published without teams, which are marked per column
 * here, and make-up games for teams eliminated early in the NBA Cup, which are
 * not published at all — absent from `source_game_count`, so neither resolved
 * nor pending, and carrying no field this screen could mark them with. Without
 * saying so, marking one implies its converse: that an unmarked column is
 * settled. It is not, and it fails worst at the moment it looks fixed — bracket
 * drawn, pending set empty, every marker gone, and every team still about two
 * games short.
 *
 * It lives in the `<caption>` rather than in the page lede for three reasons,
 * two of which were found by driving it. It is where a reader's eye already is
 * when they are reading a number, rather than in a second muted paragraph under
 * one ending in a governance citation. It renders if and only if the table
 * does, so it cannot appear above "could not load the schedule grid" claiming
 * something about counts that are not on screen. And it costs no block above a
 * grid that already carries a lineage panel, a notice and a key.
 *
 * **The make-up clause will go stale and no client-side condition can detect
 * it.** When the NBA publishes those games the sentence becomes false, and
 * nothing in the payload distinguishes "80 published because the bracket is
 * open" from "82 published". An earlier draft of this comment claimed the
 * statement was "always true and never an event" — the mirror of the fault it
 * was written to fix, since the notice's failure is going silent on a clock and
 * this one's is continuing to speak on the same clock. The expiry is tracked in
 * `docs/backlog.md` under `schedule-grid-pending-periods` with an owner and a
 * trigger, because prose nothing prompts anyone to revisit is how a screen ends
 * up asserting something it once checked. The re-ingest clause beside it does
 * not expire.
 *
 * **"Floor" would have been the wrong word, and it is the word the ADR uses.**
 * Games are added and never removed *in aggregate*, so a season total can only
 * rise — but a count in a **cell** is a different quantity, and a re-ingest that
 * moves a fixture from one week to the next takes the first week's count down.
 * ADR-012's living-refresh amendment exists because re-ingest changes shape.
 * "Every count here is a floor" is therefore true of the Total column and false
 * of the twenty-one columns beside it, erring toward false comfort at exactly
 * the granularity a manager plans a week on. The caption says "no count here is
 * final" and names both directions. `architect` caught this against their own
 * ADR text before it was accepted; the screen is not waiting for that wording
 * to be corrected before telling the truth.
 *
 * `GridCell` does receive `inPendingPeriod`, because a column rule has to be
 * drawn by the cells (`<col>` borders are ignored under `border-collapse:
 * separate`, which this table needs for its sticky edges). It is a fact about
 * the *period*, named that way so it cannot be mistaken for one about the team,
 * and it touches nothing but the column rule: a cell's `data-state` and its
 * accessible name are identical whether or not its column is pending. A zero in
 * a TBD column is still a zero, and still says so. The recorded contract test
 * asserts that over all thirty cells of the real pending column, because a rule
 * stated in a comment is a rule nothing enforces.
 */

import type { ScheduleGridModel } from './scheduleGridModel'
import { formatIsoDay, formatPeriodRange } from './scheduleGridModel'

interface ScheduleGridTableProps {
  model: ScheduleGridModel
  season: string
}

export function ScheduleGridTable({ model, season }: ScheduleGridTableProps) {
  const {
    rows,
    periods,
    periodTotals,
    periodReportingTeams,
    periodMissing,
    periodPending,
    teamCount,
  } = model
  const seasonTotal = periodTotals.reduce((sum, value) => sum + value, 0)
  const anyMissing = model.integrity.missingCells > 0

  // The season mean is the mean of the Total column, so its denominator is
  // teams with a complete row — not team-periods, and not teams whose own
  // total is itself short a period.
  const completeRows = rows.filter((row) => row.missingCells === 0)
  const completeRowTotal = completeRows.reduce((sum, row) => sum + row.total, 0)

  return (
    <div className="grid-scroll">
      <table className="grid" data-testid="schedule-grid">
        <caption className="grid__caption">
          Scheduled games per team, per {season} fantasy scoring period. Counts only — no
          availability, no opponent quality.{' '}
          <strong className="grid__caption-caveat">No count here is final.</strong> Make-up games
          for teams eliminated early from the Emirates NBA Cup have not been released and will
          raise season totals, and a re-ingest can move a fixture between weeks, so a weekly count
          can fall as well as rise — in columns carrying no mark as much as in marked ones.
        </caption>
        <thead>
          <tr>
            <th scope="col" className="grid__corner">
              Team
            </th>
            {periods.map((period, index) => {
              const pending = periodPending[index] ?? []
              const pendingNote = describePendingPeriod(pending.length)
              return (
                <th
                  key={period.period_number}
                  scope="col"
                  className={periodClass('grid__period', period.is_playoff, pending.length > 0)}
                  data-testid={`period-header-${String(period.period_number)}`}
                  data-pending={pending.length > 0 ? 'true' : 'false'}
                  // The pending sentence goes in the accessible name below and
                  // *not* here. The visually-hidden span is the name; `title`
                  // becomes the description, and screen readers with
                  // description reporting on announce both — so appending
                  // ninety characters to each would have this column read twice
                  // at triple length on every focus change. Sighted readers get
                  // the badge, the key below the lede, and the notice naming
                  // the periods, which is where a sentence belongs anyway.
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
                  {pending.length > 0 ? (
                    <span className="grid__pending-badge" aria-hidden="true">
                      TBD
                    </span>
                  ) : null}
                  <span className="visually-hidden">
                    {`Period ${String(period.period_number)}, ${formatPeriodRange(period)}${
                      period.is_playoff ? ', fantasy playoff period' : ''
                    }${pendingNote === null ? '' : `. ${pendingNote}`}`}
                  </span>
                </th>
              )
            })}
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
                  inPendingPeriod={(periodPending[index] ?? []).length > 0}
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
            {periods.map((period, index) => {
              const pending = (periodPending[index] ?? []).length
              const total = periodTotals[index] ?? 0
              return (
                <TotalCell
                  key={period.period_number}
                  value={total}
                  missing={periodMissing[index] ? 1 : 0}
                  className={periodClass('grid__cell--league', false, pending > 0)}
                  testId={`league-total-${String(period.period_number)}`}
                  incompleteLabel={`Period ${String(period.period_number)} league team-games ${String(
                    total,
                  )}, incomplete — at least one team had no data`}
                  pendingLabel={
                    pending > 0
                      ? `Period ${String(period.period_number)} league team-games ${String(
                          total,
                        )} so far. ${describePendingPeriod(pending) ?? ''}`
                      : null
                  }
                />
              )
            })}
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
              Mean
            </th>
            {periods.map((period, index) => (
              <MeanCell
                key={period.period_number}
                total={periodTotals[index] ?? 0}
                reporting={periodReportingTeams[index] ?? 0}
                expected={teamCount}
                testId={`league-mean-${String(period.period_number)}`}
                label={`Period ${String(period.period_number)} mean games per team`}
                setNoun="that reported"
                pendingGames={(periodPending[index] ?? []).length}
                className={periodClass('', false, (periodPending[index] ?? []).length > 0)}
              />
            ))}
            <MeanCell
              total={completeRowTotal}
              reporting={completeRows.length}
              expected={teamCount}
              testId="league-mean-season"
              label="Season mean games per team"
              setNoun="with a complete row"
              // Zero on purpose, and not because nothing is pending.
              //
              // This was `model.pending.declaredCount` and said two wrong
              // things. The lesser one: `describePendingPeriod` is a
              // *period-scoped* sentence, and the season column is not a
              // period, so it read "this period contains…" on an aggregate
              // over twenty-one of them.
              //
              // The substantive one: `declaredCount` includes pending games
              // dated outside every scoring period the grid shows. Those have
              // fixed dates that no column can ever hold, so they cannot enter
              // any period count and therefore cannot enter this total either
              // — while the notice above says in as many words that no column
              // can carry them. The screen contradicted itself, and the
              // sibling season `TotalCell` on the row above disagreed with
              // this cell about whether the season was pending at all.
              //
              // The season-scoped claim is not dropped; it is stated once, in
              // `PendingNotice`, where it can be qualified precisely. A weaker
              // paraphrase in a tooltip on one of two adjacent aggregates was
              // never adding anything the notice does not say better.
              pendingGames={0}
            />
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

/**
 * The one sentence this feature exists to say, in the terms the data supports.
 *
 * Period-scoped and count-bearing, with no team in it. "Any count in this
 * column may rise" is the actionable part: it is what stops a reader taking a
 * `0` here for a confirmed bye. It deliberately does not say *whose* count may
 * rise, because a pending game carries `teamId: 0` and four null team fields —
 * naming a team would be inventing the one thing the source withheld.
 */
function describePendingPeriod(pendingGames: number): string | null {
  if (pendingGames <= 0) {
    return null
  }
  const games = pendingGames === 1 ? '1 game' : `${String(pendingGames)} games`
  return `This period contains ${games} whose teams are not yet decided, so any count in this column may rise.`
}

/** Column classes shared by a period's header, cells and footer aggregates. */
function periodClass(base: string, isPlayoff: boolean, isPending: boolean): string {
  return [
    base,
    isPlayoff && base !== '' ? `${base}--playoff` : '',
    isPending ? 'grid__col--pending' : '',
  ]
    .filter(Boolean)
    .join(' ')
}

/**
 * require dividing by 30 in your head under a pick clock.
 *
 * The denominator is the teams that **reported** in that period, not every team
 * the response named. Summing over the reporters and dividing by everyone
 * produces a quotient that is the mean of no set at all — understated by
 * exactly the missing share, and understated in the direction that makes every
 * team's own count read as relatively healthier than it is. Where teams are
 * missing the cell says so, because a mean over a set the reader cannot see is
 * not the same number as a mean over the whole league.
 *
 * Still descriptive within a single period: integers the backend sent, divided
 * by how many of them there were. No reference set is chosen, because the set
 * is "whoever reported"; nothing is compared against a threshold; and both
 * operands are on screen. Aggregating *across* periods would be a different
 * matter entirely — that acquires the playoff/partial/sparse-week choices that
 * make `schedule-grid-reference-distribution` a Model-gated `quant` item.
 */
function MeanCell({
  total,
  reporting,
  expected,
  testId,
  label,
  setNoun,
  pendingGames,
  className,
}: MeanCellProps) {
  const partial = reporting < expected
  const value = reporting === 0 ? '—' : (total / reporting).toFixed(1)
  const base = partial
    ? `${label}: ${value}, over the ${String(reporting)} of ${String(expected)} ${setNoun}`
    : `${label}: ${value}`
  // Two independent reasons this number is provisional, and they stack. The
  // partial clause says the *denominator* is short; the pending clause says the
  // *numerator* is not final yet. Collapsing them would leave a reader unable
  // to tell which of the two is happening.
  const pendingNote = describePendingPeriod(pendingGames)
  const description = pendingNote === null ? base : `${base}. ${pendingNote}`
  const provisional = partial || pendingNote !== null

  return (
    <td
      className={['grid__cell', 'grid__cell--mean', partial ? 'grid__total--partial' : '', className]
        .filter(Boolean)
        .join(' ')}
      data-testid={testId}
      data-state={partial ? 'partial' : 'complete'}
      data-pending={pendingNote === null ? 'false' : 'true'}
      aria-label={description}
      {...(provisional ? { title: description } : {})}
    >
      {value}
      {partial ? (
        <span className="grid__partial-mark" aria-hidden="true">
          +?
        </span>
      ) : null}
    </td>
  )
}

interface MeanCellProps {
  total: number
  /** Teams that actually reported — the honest denominator. */
  reporting: number
  /** Teams that should have reported, so a shortfall can be named. */
  expected: number
  testId: string
  label: string
  /**
   * What the denominator counts, in words.
   *
   * A period column is over teams that reported *that period*; the season
   * column is over teams whose *whole row* arrived. Same phrasing for both
   * would give a screen-reader user one sentence describing two different
   * sets, in the row whose entire purpose is saying what a mean is over.
   */
  setNoun: string
  /**
   * Pending games bearing on this mean, which is a statement about the
   * numerator and so a different thing from `reporting < expected`.
   *
   * No visible mark is added for it. The `+?` glyph already means "this is
   * short by an unknown amount because data is missing", and reusing it for
   * "the schedule is not finished" would merge the two states the column header
   * exists to keep apart. The column rule and the `TBD` badge above carry the
   * pending signal; this only makes the tooltip and accessible name honest.
   */
  pendingGames: number
  className?: string
}

interface TotalCellProps {
  value: number
  /** Cells that never arrived and so are not counted in `value`. */
  missing: number
  testId: string
  incompleteLabel: string
  /** Set when this total sits under a period the source has not finished scheduling. */
  pendingLabel?: string | null
  className?: string
}

/**
 * A total is a sum over the cells that arrived. When some did not, the number
 * is smaller than the truth, and saying so only in screen-reader text would
 * leave the two most scannable numbers on the grid — the ones a reader compares
 * teams by — looking exactly as trustworthy as a complete sum.
 *
 * A pending period makes a total provisional for an unrelated reason, and gets
 * a label rather than the `+?` mark for the reason `MeanCellProps.pendingGames`
 * gives: one glyph cannot mean two things and stay useful.
 */
function TotalCell({
  value,
  missing,
  testId,
  incompleteLabel,
  pendingLabel,
  className,
}: TotalCellProps) {
  const incomplete = missing > 0
  const classes = ['grid__cell', 'grid__total', className, incomplete ? 'grid__total--partial' : '']
    .filter(Boolean)
    .join(' ')
  // Incompleteness is the more serious of the two and wins the label when both
  // apply: a sum missing cells is wrong now, where a sum under a pending period
  // is right now and will change later.
  const label = incomplete ? incompleteLabel : (pendingLabel ?? null)

  return (
    <td
      className={classes}
      data-testid={testId}
      data-state={incomplete ? 'partial' : 'complete'}
      data-pending={pendingLabel == null ? 'false' : 'true'}
      {...(label === null ? {} : { 'aria-label': label, title: label })}
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
  /**
   * Whether this cell's **period** contains pending games — never whether this
   * team does, which is unknowable.
   *
   * Used for the column rule and nothing else. It must not reach `data-state`
   * or the accessible name: a `0` in a TBD column is a real zero today, and the
   * cell says exactly that.
   */
  inPendingPeriod: boolean
}

function GridCell({
  games,
  teamAbbreviation,
  teamId,
  periodNumber,
  isPlayoff,
  inPendingPeriod,
}: GridCellProps) {
  const testId = `cell-${String(teamId)}-${String(periodNumber)}`
  const columnClass = periodClass('grid__cell', isPlayoff, inPendingPeriod)

  // Absence is not zero. A blank here would let the reader guess, so it gets a
  // marker of its own and an unambiguous label.
  if (games === null) {
    return (
      <td
        className={`${columnClass} grid__cell--nodata`}
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
      className={columnClass}
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
