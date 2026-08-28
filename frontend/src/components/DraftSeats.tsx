/**
 * The board: every seat, what it holds, and what it has left.
 *
 * ## The budget caveat, and why it is two lines rather than one number
 *
 * `remaining_budget` is `budget - spent`, and `spent` counts **recorded sales
 * only**. A seat sitting on a live $150 high bid therefore reports its full
 * remaining budget — in the seeded demo, Trade Deadline shows $200.00 left
 * while holding a $150.00 bid on the block. Both figures are true. A single
 * "available" number reconciling them would not be, because this screen does
 * not know whether that bid will clear, and inventing the subtraction would be
 * inventing a decision number the API deliberately does not publish.
 *
 * So they are rendered as **two claims of different kinds**, and the words do
 * the work rather than the layout:
 *
 * - *Left, of sales recorded* — a subtraction over facts in the log.
 * - *live on <player>, not a sale* — an obligation in the room that the log has
 *   no entry for yet.
 *
 * The failure this is written against is the reader glancing at $200 and
 * bidding as though it were spendable. So the caveat sits directly beneath the
 * figure it qualifies, on the one seat it applies to, and says "not subtracted
 * above" in as many words. It is deliberately not a footnote, an asterisk or a
 * tooltip: all three are read after the decision.
 *
 * **A seat with no live bid gets no caveat line at all**, so the presence of
 * the line is itself the signal. An absent marker and a present one are
 * different claims here, which is the distinction the previous frontend lane
 * could not answer for its own screen.
 *
 * ## The third claim: a seat that has spent past the assumed budget
 *
 * `remaining_budget` is **signed**, and a negative value is a fact about this
 * tool rather than about the seat. The budget in that subtraction is one scalar
 * for the whole draft; the backend has no per-seat budget column, and this
 * league sets each seat's bank from last season's final totals. So the figure
 * is wrong for most seats by construction, and the backend admits a sale above
 * it instead of refusing it — refusing it deleted a pick the recorder had
 * watched clear.
 *
 * That produced a rendering bug this screen had no way to notice: `$-300.00`
 * beneath the words *left, of sales recorded*. Legible, and false in the one
 * word that matters. A recorder glancing at it reads a negative balance as the
 * seat's problem, when it is ours.
 *
 * So a flagged seat reads **`$300.00 over` / *past the budget this tool
 * assumed*** and carries a note saying, in as many words, that nothing was
 * rejected and no pick is missing. Both are driven by
 * `over_assumed_budget`, which the backend publishes as its own field — this
 * screen never infers the condition from a minus sign, because two derivations
 * of one fact can disagree and a label disagreeing with its own figure is the
 * failure being avoided.
 */

import type { DraftBoardModel, SeatBudget, SeatRow } from './draftBoardModel'

/**
 * The headline figure, as a magnitude plus a word rather than a signed number.
 *
 * `remainingBudget` is signed and may be negative, because the backend admits a
 * sale above the assumed budget rather than refusing it — refusing it lost a
 * pick that really happened. `$-300.00` under the words "left, of sales
 * recorded" is legible and false: nothing is left, and the label claims
 * otherwise. So a flagged seat reads `$300.00 over` instead.
 *
 * **The digits are not recomputed.** The sign is stripped from the string the
 * backend sent, so `"-300.00"` becomes `"300.00"` with the cents intact. A
 * parse-and-reformat here would round-trip through a float and is exactly what
 * `renders money byte-identically to what the backend sent` exists to catch.
 */
function renderRemaining(budget: SeatBudget): string {
  if (budget.remainingBudget === null) return 'not recorded'
  if (!budget.overAssumedBudget) return `$${budget.remainingBudget}`
  const magnitude = budget.remainingBudget.startsWith('-')
    ? budget.remainingBudget.slice(1)
    : budget.remainingBudget
  return `$${magnitude} over`
}

/**
 * The words under the figure, which are the part that was wrong.
 *
 * "left, of sales recorded" is a true claim about a seat with money left and a
 * false one about a seat that has spent past the assumption. The label is
 * chosen from the flag rather than from the sign of the figure, so it cannot
 * disagree with the flag that drives the note beneath it.
 */
function remainingLabel(budget: SeatBudget): string {
  if (budget.remainingBudget === null) return 'left, of sales recorded'
  return budget.overAssumedBudget
    ? 'past the budget this tool assumed, of sales recorded'
    : 'left, of sales recorded'
}

export function DraftSeats({ model }: { model: DraftBoardModel }) {
  return (
    <section className="seats" aria-labelledby="seats-title">
      <h2 id="seats-title">Seats</h2>
      <ol className="seats__list">
        {model.seats.map((seat) => (
          <Seat key={seat.participant.id} seat={seat} isAuction={model.isAuction} />
        ))}
      </ol>
    </section>
  )
}

function Seat({ seat, isAuction }: { seat: SeatRow; isAuction: boolean }) {
  const { participant, budget, holdsHighBid } = seat

  return (
    <li
      className={participant.is_owner ? 'seat seat--owner' : 'seat'}
      data-testid={`seat-${String(participant.id)}`}
    >
      <header className="seat__header">
        <h3 className="seat__name">
          {participant.display_name}
          {participant.is_owner ? <span className="seat__you"> you</span> : null}
        </h3>
        <p className="seat__slots">
          {participant.slots_filled} of {participant.slots_filled + participant.slots_remaining}{' '}
          slots
        </p>
      </header>

      {isAuction ? (
        <div className="seat__budget">
          <p className="seat__budget-main">
            <span
              className={
                budget.overAssumedBudget ? 'seat__money seat__money--over' : 'seat__money'
              }
              data-testid={`seat-remaining-${String(participant.id)}`}
            >
              {/* Words, not an em dash. This screen uses an em dash as ordinary
                  punctuation in the caveat line directly below, and a glyph
                  cannot be a missing-value marker and punctuation in the same
                  element without one reading as the other. */}
              {renderRemaining(budget)}
            </span>
            <span className="seat__budget-label">{remainingLabel(budget)}</span>
          </p>
          {/* Rendered only for a seat whose recorded spend has passed the
              assumed budget. Its presence is the signal, exactly like the live
              bid caveat below it, so it must never be emitted empty. */}
          {budget.overAssumedBudget ? (
            <p
              className="seat__budget-over"
              data-testid={`seat-over-budget-${String(participant.id)}`}
              role="note"
            >
              <span className="seat__budget-label">
                Every seat in this draft is assumed to have{' '}
                <strong>{budget.budget === null ? 'the same budget' : `$${budget.budget}`}</strong>,
                because that is the only figure recorded — the backend holds no per-seat budget.
                This seat has cleared more than that, so{' '}
                <strong>the assumption is wrong here, not the sale</strong>. Nothing was rejected
                and no pick is missing.
              </span>
            </p>
          ) : null}
          {/* Rendered only for the seat holding the high bid. Its presence is
              the signal, so it must never be emitted empty. */}
          {holdsHighBid && budget.liveBidAmount !== null ? (
            <p
              className="seat__budget-live"
              data-testid={`seat-live-bid-${String(participant.id)}`}
            >
              <span className="seat__money seat__money--live">${budget.liveBidAmount}</span>
              <span className="seat__budget-label">
                live on {budget.liveBidPlayerLabel ?? 'the open lot'} — not a sale, so{' '}
                <strong>not subtracted above</strong>
              </span>
            </p>
          ) : null}
          {budget.spent !== null && budget.budget !== null ? (
            <p className="seat__spent">
              ${budget.spent} spent
              {budget.overAssumedBudget ? ', against an assumed ' : ' of '}${budget.budget}
            </p>
          ) : null}
        </div>
      ) : null}

      {participant.holdings.length === 0 ? (
        <p className="seat__empty">No selections recorded.</p>
      ) : (
        <ul className="seat__holdings">
          {participant.holdings.map((holding) => (
            <li key={holding.event_sequence} className="seat__holding">
              <span className="seat__holding-name">{holding.player_label}</span>
              {holding.price !== null ? (
                <span className="seat__holding-price">${holding.price}</span>
              ) : null}
              {holding.overall_pick !== null ? (
                <span className="seat__holding-pick">pick {holding.overall_pick}</span>
              ) : null}
              {/* Lineage. Every holding names the single log entry that put it
                  here, so "where did this come from" is answerable with a
                  number rather than by reconstruction. */}
              <span className="seat__holding-seq" title="the log entry this came from">
                #{holding.event_sequence}
              </span>
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}
