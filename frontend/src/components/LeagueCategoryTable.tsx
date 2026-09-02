/**
 * The league category table — twelve seats down, nine categories across.
 *
 * Every number in a cell comes out of `leagueCategoryModel`, which does `+` and
 * `÷` over published per-game rates and nothing else. Read that module's
 * docstring before changing anything here; the honesty of this screen lives
 * there, and the only thing this file adds is colour.
 *
 * **Colour is on the rank, not on the value.** The owner asked for it in those
 * terms — *"a tier list for all of the owners... 1 to X in rebounds"* — and a
 * value-based scale would need a spread, which is a distribution statistic this
 * unit is not entitled to compute. Five tiers, red through green, assigned by
 * position among the seats that could be ranked.
 *
 * **Colour is never the only carrier.** Every cell renders its rank as text
 * beside its value, because a red-green scale is invisible to the eight percent
 * of men with a colour vision deficiency and this is a fantasy basketball tool.
 * The tier is also in `data-tier`, so a test asserts the scale without reading
 * a computed style.
 */

import {
  CATEGORIES,
  formatAggregate,
  NOT_COMPUTABLE,
  ordinal,
  type LeagueCategoryModel,
  type SeatCategoryCell,
  type SeatRow,
} from './leagueCategoryModel'
import type { CategoryBoardCompleteness } from './categoryBoardCompleteness'

export function LeagueCategoryTable({
  model,
  completeness,
}: {
  model: LeagueCategoryModel
  completeness?: CategoryBoardCompleteness | undefined
}) {
  return (
    // The same scroll wrapper the schedule grid uses. A `display: block` table
    // would scroll too, and would also stop being a table: the column widths
    // decouple and the sticky header loses the cell box its bottom rule travels
    // with, which is the exact failure `.grid`'s `border-collapse` comment
    // records for a different reason.
    <div className="grid-scroll">
      <table className="grid catgrid" data-testid="league-category-table">
      <caption className="catgrid__caption">
        {model.rankedSeatCount > 0
          ? `Every seat, ranked 1-to-${String(model.rankedSeatCount)} in each category on the sum of the per-game rates the source published for the players it holds. `
          : 'No seat could be ranked in any category, because none of them hold a selection that joined to a projection row. '}
        <strong>Not adjusted for availability, and not adjusted for roster depth.</strong>
      </caption>
      <thead>
        <tr>
          <th scope="col" className="catgrid__seat-head">
            Team
          </th>
          <th scope="col" className="catgrid__count-head" title="Holdings joined to a projection row">
            Players
          </th>
          <th
            scope="col"
            className="catgrid__feed-head"
            title="Feed observations permanently skipped rather than applied"
          >
            Feed skipped
          </th>
          {CATEGORIES.map((category) => (
            <th key={category.key} scope="col" title={category.description}>
              {category.label}
              {category.direction === 'lower' ? <span aria-hidden="true"> ↓</span> : null}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {model.seats.map((seat) => (
          <SeatLine key={seat.participant.id} seat={seat} completeness={completeness} />
        ))}
      </tbody>
      </table>
    </div>
  )
}

function SeatLine({
  seat,
  completeness,
}: {
  seat: SeatRow
  completeness?: CategoryBoardCompleteness | undefined
}) {
  const { participant, join } = seat
  const feedSkips =
    completeness?.kind === 'available'
      ? completeness.byParticipantId.get(participant.id)
      : undefined
  return (
    <tr
      className={participant.is_owner ? 'catgrid__row catgrid__row--owner' : 'catgrid__row'}
      data-testid={`category-seat-${String(participant.team_slot)}`}
    >
      <th scope="row" className="catgrid__seat">
        {participant.display_name}
        {participant.is_owner ? <span className="catgrid__you"> you</span> : null}
      </th>
      <td className="catgrid__count">
        {/* The depth confound, drawn where it cannot be missed: a seat holding
            five players outranks one holding three on a sum, for that reason
            alone. Correcting for it would mean projecting the empty slots. */}
        <span className="catgrid__count-joined">{join.joinedPlayers}</span>
        {join.totalHoldings !== join.joinedPlayers ? (
          <span
            className="catgrid__count-gap"
            title={`${String(join.unresolvedHoldings)} selection(s) carry no player id; ${String(join.unmatchedHoldings)} name a player the projection cohort does not carry.`}
          >
            {' '}
            of {join.totalHoldings}
          </span>
        ) : null}
      </td>
      <td
        className={
          feedSkips !== undefined && feedSkips.total > 0
            ? 'catgrid__feed catgrid__feed--incomplete'
            : 'catgrid__feed'
        }
        data-testid={`category-feed-skips-${String(participant.id)}`}
      >
        {feedSkips === undefined ? (
          <span className="catgrid__feed-unknown">unknown</span>
        ) : (
          <>
            <span className="catgrid__feed-total">{feedSkips.total}</span>
            {feedSkips.total > 0 ? (
              <>
                <span className="catgrid__feed-warning">roster may be incomplete</span>
                <span className="catgrid__feed-reasons">
                  {Object.entries(feedSkips.reasons)
                    .sort(([left], [right]) => left.localeCompare(right))
                    .map(([reason, count], index) => (
                      <span key={reason}>
                        {index > 0 ? ' · ' : ''}
                        <code>{reason}</code> × {count}
                      </span>
                    ))}
                </span>
              </>
            ) : null}
          </>
        )}
      </td>
      {seat.cells.map((cell) => (
        <CategoryCell key={cell.category.key} cell={cell} />
      ))}
    </tr>
  )
}

function CategoryCell({ cell }: { cell: SeatCategoryCell }) {
  const { aggregate, rank, tier } = cell
  const value = formatAggregate(aggregate)

  if (rank === null) {
    return (
      <td className="grid__cell catgrid__cell catgrid__cell--nodata">
        <span className="catgrid__value">{NOT_COMPUTABLE}</span>
        <span className="catgrid__rank catgrid__rank--none">unranked</span>
      </td>
    )
  }

  return (
    <td
      className={`grid__cell catgrid__cell catgrid__cell--tier${String(tier ?? 3)}`}
      data-tier={String(tier ?? '')}
      data-rank={String(rank)}
    >
      <span className="catgrid__value">{value}</span>
      <span className="catgrid__rank">{ordinal(rank)}</span>
      {aggregate.kind === 'ratio' ? (
        // The volume behind the percentage, always. A 90% free-throw shooter on
        // one attempt is worthless, and the seat-level version of that mistake
        // is a percentage leading on almost no shots.
        <span className="catgrid__volume" title="Attempts per game behind this percentage">
          {aggregate.attempted.toFixed(1)} att
        </span>
      ) : null}
      {aggregate.omittedPlayers > 0 ? (
        <span
          className="catgrid__omitted"
          title={`${String(aggregate.omittedPlayers)} joined player(s) did not publish this quantity and are not in the total.`}
        >
          −{aggregate.omittedPlayers}
        </span>
      ) : null}
    </td>
  )
}

/**
 * The owner's own line: where he is deficient and where he is excelling.
 *
 * Q9, almost verbatim. It is a re-presentation of ranks already in the table
 * rather than a second computation, which is why it takes the model rather than
 * the payload.
 */
export function OwnerCategoryStanding({ model }: { model: LeagueCategoryModel }) {
  const seat = model.ownerSeat
  if (seat === null) return null

  const ranked = seat.cells.filter(
    (cell): cell is SeatCategoryCell & { rank: number } => cell.rank !== null,
  )
  if (ranked.length === 0) return null

  const best = ranked.reduce((a, b) => (b.rank < a.rank ? b : a))
  const worst = ranked.reduce((a, b) => (b.rank > a.rank ? b : a))

  return (
    <p className="page__facts catgrid__standing" data-testid="owner-standing">
      <strong>{seat.participant.display_name}</strong> ranks{' '}
      {ranked.map((cell, index) => (
        <span key={cell.category.key} className="catgrid__standing-item">
          {index > 0 ? ' · ' : ''}
          <span className={`catgrid__standing-tier catgrid__standing-tier--${String(cell.tier ?? 3)}`}>
            {ordinal(cell.rank)}
          </span>{' '}
          {cell.category.label}
        </span>
      ))}
      {'. '}
      Strongest {best.category.label}, weakest {worst.category.label}, of{' '}
      {model.rankedSeatCount} seats with anything to rank.
    </p>
  )
}
