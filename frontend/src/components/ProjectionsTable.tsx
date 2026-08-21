/**
 * The imported projection cohort: one row per player, sixteen per-game rates.
 *
 * **Everything on this screen is Basketball Monster's number, not ours.** No
 * ranking, no valuation, no z-score or G-score, no availability weighting, no
 * "who should I draft". Those are `quant`'s behind the Model gate, and a number
 * we did not compute must never look like one we did.
 *
 * **No colour scale on any rate**, for the same reason the schedule grid has
 * none: a value scale encodes a judgement about whether a number is good, and
 * that judgement is a model output rather than a CSS decision. The only visual
 * distinctions here are between a published number, a quantity the source did
 * not publish, and the source's games-played assumption — which is not a rate
 * at all and is separated from them by a rule for exactly that reason.
 *
 * **ADR-002, structurally.** The assumption column reads `row.assumption`, a
 * discriminated union, and the rate columns read `row.rates`. `AssumptionCell`
 * — the one function that narrows that union into a bare number — is passed
 * only `assumption` and `playerId`, so the rates are not in scope at the moment
 * narrowing happens. Writing the forbidden product therefore requires changing
 * a signature, not just typing an expression. See `AssumptionState` for why
 * that structure is the load-bearing guarantee and the DOM test is only a
 * backstop.
 */

import type { AssumptionState, ProjectionRow, ProjectionsModel } from './projectionsModel'
import {
  NO_LABEL,
  NOT_PUBLISHED,
  PROJECTION_RATE_FIELDS,
  RATE_LABELS,
  VOLUME_PAIR_STARTS,
  formatRate,
} from './projectionsModel'

export function ProjectionsTable({ model }: { model: ProjectionsModel }) {
  return (
    /* `grid-scroll` is reused rather than renamed. It carries the height
       constraint that makes `position: sticky` engage at all, and
       `.shell__main:has(.grid-scroll)` keys the wider prose measure off this
       exact class — so a differently-named wrapper would silently lose both.
       The height budget for this page is set separately; see `styles.css`. */
    <div className="grid-scroll">
      <table className="grid projections" data-testid="projections-table">
        <caption className="grid__caption">
          Basketball Monster&apos;s published per-game rates for the {model.season} season,
          exactly as imported.{' '}
          <strong className="grid__caption-caveat">These are not our numbers.</strong> Nothing
          here is ranked, valued or adjusted for availability, and no shooting percentage is
          computed — makes and attempts are shown so volume stays visible.
        </caption>

        <thead>
          <tr>
            <th scope="col" className="grid__corner projections__player-head">
              Player
            </th>
            <th scope="col" className="projections__team-head">
              Team
            </th>
            <th scope="col" className="projections__pos-head" title="NBA's own label, not Fantrax eligibility">
              Pos
            </th>
            {PROJECTION_RATE_FIELDS.map((field) => (
              <th
                key={field}
                scope="col"
                className={
                  VOLUME_PAIR_STARTS.has(field)
                    ? 'projections__rate-head projections__rate-head--pair-start'
                    : 'projections__rate-head'
                }
                title={field}
                data-testid={`rate-header-${field}`}
              >
                {RATE_LABELS[field]}
              </th>
            ))}
            <th
              scope="col"
              className="projections__assumption-head"
              title="What Basketball Monster assumed about games played. Displayed, never multiplied by a rate."
            >
              Source GP
            </th>
          </tr>
        </thead>

        <tbody>
          {model.rows.map((row) => (
            <ProjectionTableRow key={row.playerId} row={row} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ProjectionTableRow({ row }: { row: ProjectionRow }) {
  const { player } = row

  return (
    <tr data-testid={`projection-row-${String(row.playerId)}`}>
      <th scope="row" className="grid__team projections__player">
        {player ? (
          player.full_name
        ) : (
          /* A rate row the response carries no player row for. Drawn under its
             bare id rather than dropped: dropping it would quietly shrink the
             cohort the lineage block claims, which is the one thing this screen
             is supposed to make checkable. */
          <span className="projections__unlabelled" data-testid="unlabelled-player">
            player {row.playerId}
          </span>
        )}
      </th>
      <td className="projections__team">{player?.team_abbreviation ?? NO_LABEL}</td>
      <td
        className="projections__pos"
        data-testid={`position-${String(row.playerId)}`}
        title={
          player?.primary_position == null
            ? 'Our player record holds no position for this player. This says nothing about what Basketball Monster published.'
            : "NBA's own label, not Fantrax eligibility."
        }
      >
        {player?.primary_position ?? NO_LABEL}
      </td>

      {PROJECTION_RATE_FIELDS.map((field) => {
        const value = row.rates[field]
        return (
          <td
            key={field}
            className={[
              'projections__rate',
              value === null ? 'projections__rate--nodata' : '',
              VOLUME_PAIR_STARTS.has(field) ? 'projections__rate--pair-start' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            data-testid={`rate-${String(row.playerId)}-${field}`}
          >
            {formatRate(value)}
          </td>
        )
      })}

      <AssumptionCell assumption={row.assumption} playerId={row.playerId} />
    </tr>
  )
}

/**
 * The source's games-played assumption. Four states, each rendered distinctly.
 *
 * A number here is **not** a rate and must never be read as one, which is why
 * it sits behind a rule and under a header that says whose assumption it is.
 * It is shown because "the source assumed 70 games, we will replace that" is
 * the product thesis in one line — and it is shown *only*.
 *
 * **Takes `assumption` and `playerId` rather than the whole row, and that is
 * the point.** This is the one function that narrows `AssumptionState` into a
 * bare `number`, so it is the one place where the forbidden product would be a
 * single expression. Review found it previously took `row`, which put
 * `row.rates` in scope at exactly that moment and made the component
 * docstring's claim — that no scope holds a rate and a games figure as sibling
 * numbers — true everywhere except where it mattered. Passing the two fields
 * it uses keeps the rates unreachable from here.
 */
function AssumptionCell({
  assumption,
  playerId,
}: {
  assumption: AssumptionState
  playerId: number
}) {
  const testId = `assumption-${String(playerId)}`

  switch (assumption.kind) {
    case 'stated':
      return (
        <td
          className="projections__assumption"
          data-testid={testId}
          data-assumption="stated"
          title={
            assumption.raw === null
              ? 'Basketball Monster assumed this many games played.'
              : `Basketball Monster published “${assumption.raw}”.`
          }
        >
          {assumption.games}
        </td>
      )
    case 'unreadable':
      // A value *did* arrive. Saying "the source said nothing" here would be
      // false, so the raw text is shown rather than a marker standing in for
      // it — the reader can see exactly what was published.
      return (
        <td
          className="projections__assumption projections__assumption--unreadable"
          data-testid={testId}
          data-assumption="unreadable"
          title="Basketball Monster published this, and we could not read it as a number."
        >
          {assumption.raw}
        </td>
      )
    case 'unexplained':
      // An entry carrying neither a value nor the text it came from. The
      // contract does not describe this state, so it gets attention rather
      // than being folded into "the source said nothing".
      return (
        <td
          className="projections__assumption projections__assumption--unexplained"
          data-testid={testId}
          data-assumption="unexplained"
          title="This cohort carries an assumption row for this player that states nothing at all. That is not a documented state; it is counted above."
        >
          ?
        </td>
      )
    case 'absent':
      return (
        <td
          className="projections__assumption projections__assumption--absent"
          data-testid={testId}
          data-assumption="absent"
          title="Basketball Monster stated no games-played assumption for this player. This is not zero."
        >
          {NOT_PUBLISHED}
        </td>
      )
  }
}
