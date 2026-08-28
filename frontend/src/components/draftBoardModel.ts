/**
 * The draft board's view model: everything the screen draws, derived here so it
 * can be tested without a DOM.
 *
 * **This module is the boundary the "no decision numbers" rule is enforced at.**
 * The API deliberately publishes no ranking, valuation, auction price,
 * inflation figure or `p(play)`; a reviewer walked all 26 OpenAPI models and 67
 * fields against a list of 30 forbidden terms to establish that. Every number
 * that reaches the screen therefore has to come from a response field, and the
 * only arithmetic below is over *positions in the log* — which entry is last,
 * which entries are superseded. No money is computed here. `remaining_budget`
 * and `spent` are the backend's own subtraction and are passed through as the
 * strings it sent, unparsed.
 *
 * ## Correctability, which is the subtle part
 *
 * Corrections are `void` events. **Voiding the most recent entry always works;
 * voiding an older one may be refused**, because the log is replayed without
 * the voided entry and a later entry's preconditions may no longer hold — a bid
 * whose nomination is gone, a pick whose turn has shifted.
 *
 * This was measured rather than assumed. Probing all 27 events of the two
 * seeded drafts, one fresh database per attempt so a success could not
 * contaminate the next probe: **4 voided, and 2 of those 4 were not the most
 * recent entry** — a bid nothing downstream depended on, and a standalone sale
 * with no later entry referencing it. So a screen that offered correction *only*
 * on the last entry would refuse two of four corrections the backend accepts.
 *
 * The second measurement is what makes offering the rest safe: **a refused void
 * writes nothing.** A doomed void against the snake draft left `last_sequence`
 * at 13 and the log at 13 entries, before and after.
 *
 * Hence two states rather than one, labelled differently on screen:
 *
 * - `guaranteed` — the last entry. One key, no caveat, this is the auction-clock
 *   path.
 * - `may-be-refused` — any earlier live entry. Attempting costs nothing, and
 *   when it is refused the backend now names the *later* entry that stopped it
 *   and why. That message is surfaced verbatim; it is better than anything this
 *   screen could paraphrase it into.
 */

import type {
  DecimalString,
  DraftEvent,
  DraftOpenLot,
  DraftParticipant,
  DraftState,
} from '../api/draftTypes'

/** Whether a `void` against this entry is certain, possible, or meaningless. */
export type Correctability = 'guaranteed' | 'may-be-refused' | 'none'

export interface LogRow {
  event: DraftEvent
  /** True when a later `void` superseded this entry. */
  isVoided: boolean
  /** True when this entry is itself a correction. */
  isVoid: boolean
  correctability: Correctability
  /** Why correction is unavailable, for the entries where it is not. */
  correctabilityReason: string | null
  /** The seat this entry names, resolved. Null where the entry names none. */
  participantName: string | null
  /**
   * The player this entry concerns.
   *
   * A `sale` of an open lot carries no `player_label` of its own — the lot named
   * the player and the sale inherits it, which is why the recorder is not asked
   * to retype it. So the row is filled in from the seat's `holdings`, matching
   * on `event_sequence`: **the backend's own resolution of which entry produced
   * which holding**, not this screen re-deriving it by walking back for the
   * nearest nomination. Null when the entry concerns no player, or when the
   * backend published no holding for it — an unresolved sale reads as
   * unresolved rather than acquiring a name from a guess.
   */
  playerLabel: string | null
}

/**
 * A seat's budget, as two claims that must not be read as one number.
 *
 * `remainingBudget` is `budget - spent` over **recorded sales**. It is an
 * identity over facts, not a spending limit, and the backend says so in the
 * field's own docstring.
 *
 * `liveBidAmount` is set only for the seat currently holding the high bid on
 * the open lot. That money is committed in the room and absent from the
 * subtraction above, so a seat with $200 remaining and a live $150 bid is
 * reporting two true things that a single figure would turn into a lie.
 */
export interface SeatBudget {
  remainingBudget: DecimalString | null
  spent: DecimalString | null
  budget: DecimalString | null
  liveBidAmount: DecimalString | null
  liveBidPlayerLabel: string | null
  /**
   * Passed through from the backend, **not re-derived from the sign of
   * `remainingBudget`**. Deriving it here would be a second computation of a
   * fact the API already publishes, and the two could drift.
   */
  overAssumedBudget: boolean
}

export interface SeatRow {
  participant: DraftParticipant
  budget: SeatBudget
  /** True when this seat holds the high bid on the lot currently on the block. */
  holdsHighBid: boolean
}

export interface DraftBoardModel {
  state: DraftState
  isAuction: boolean
  seats: SeatRow[]
  openLot: DraftOpenLot | null
  /** The seat nominating the open lot, resolved to a name. */
  openLotNominatorName: string | null
  openLotHighBidderName: string | null
  logRows: LogRow[]
  /** The single entry a correction is guaranteed against, or null. */
  guaranteedCorrectionSequence: number | null
  /**
   * Entries that record something that still stands: neither superseded by a
   * later `void`, nor a `void` themselves.
   *
   * This matches the backend's own `live_event_count` deliberately, so a test
   * can check this derivation against a number the server computed separately.
   * The first draft of it counted the `void` entry as live and disagreed with
   * the server by one — which is exactly the sort of quiet arithmetic error a
   * test with no independent source cannot see.
   */
  liveEventCount: number
  /** Entries the response says were superseded. */
  voidedCount: number
}

function nameOf(participants: readonly DraftParticipant[], id: number | null): string | null {
  if (id === null) return null
  return participants.find((seat) => seat.id === id)?.display_name ?? null
}

/**
 * Which entry, if any, a correction is guaranteed against.
 *
 * The highest sequence in the log, unless it is itself a `void` — a void cannot
 * be undone, and the backend refuses with `draft_cannot_void_a_void`. It cannot
 * be an already-superseded entry, because a `void` always follows its target,
 * so the last entry is never one that has been voided.
 */
export function guaranteedCorrectionSequence(events: readonly DraftEvent[]): number | null {
  if (events.length === 0) return null
  const last = events.reduce((best, event) => (event.sequence > best.sequence ? event : best))
  if (last.event_type === 'void') return null
  return last.sequence
}

export function buildLogRows(
  events: readonly DraftEvent[],
  participants: readonly DraftParticipant[],
  openLot: DraftOpenLot | null = null,
): LogRow[] {
  const guaranteed = guaranteedCorrectionSequence(events)

  // Which log entry produced which holding, as the backend resolved it. This is
  // how a sale that inherited its player from the open lot gets a name in the
  // log without this screen reconstructing the lot's history itself.
  const playerBySequence = new Map<number, string>()
  for (const participant of participants) {
    for (const holding of participant.holdings) {
      playerBySequence.set(holding.event_sequence, holding.player_label)
    }
  }

  /**
   * The one case holdings cannot cover: a **withdrawn** sale.
   *
   * Voiding a sale removes the holding, so the entry loses the only published
   * link to its player — which is the entry the recorder is staring at one
   * second after clicking Undo. But voiding it also *reopens the lot*, and the
   * reopened lot names the player.
   *
   * The lot on the block belongs to a withdrawn sale exactly when it was
   * nominated **before** that sale: a lot nominated after it is a different lot,
   * and no lot can be open at all unless its sale was withdrawn. So the test is
   * `nomination_sequence < sale.sequence`, and it uses only fields the response
   * published rather than replaying the log in the browser.
   */
  function playerForWithdrawnSale(event: DraftEvent): string | null {
    if (openLot === null) return null
    if (event.event_type !== 'sale' || event.voided_by_sequence === null) return null
    return openLot.nomination_sequence < event.sequence ? openLot.player_label : null
  }

  return events
    .slice()
    // `sequence`, never `occurred_at`. The backend's own field docstring says a
    // client that sorts on the timestamp is wrong: it is the recorder's claim
    // about wall-clock time, stored and displayed and never used to order.
    .sort((a, b) => a.sequence - b.sequence)
    .map((event) => {
      const isVoided = event.voided_by_sequence !== null
      const isVoid = event.event_type === 'void'

      let correctability: Correctability = 'may-be-refused'
      let correctabilityReason: string | null = null

      if (isVoided) {
        correctability = 'none'
        correctabilityReason = `Already corrected by entry ${String(event.voided_by_sequence)}.`
      } else if (isVoid) {
        correctability = 'none'
        correctabilityReason =
          'A correction cannot itself be undone. Record the original entry again instead.'
      } else if (event.sequence === guaranteed) {
        correctability = 'guaranteed'
      }

      return {
        event,
        isVoided,
        isVoid,
        correctability,
        correctabilityReason,
        participantName: nameOf(participants, event.participant_id),
        playerLabel:
          event.player_label ??
          playerBySequence.get(event.sequence) ??
          playerForWithdrawnSale(event),
      }
    })
}

export function buildDraftBoardModel(
  state: DraftState,
  events: readonly DraftEvent[],
): DraftBoardModel {
  const openLot = state.open_lot
  const highBidder = openLot?.high_bid_participant_id ?? null

  const seats: SeatRow[] = state.participants
    .slice()
    .sort((a, b) => a.team_slot - b.team_slot)
    .map((participant) => {
      const holdsHighBid = highBidder !== null && participant.id === highBidder
      return {
        participant,
        holdsHighBid,
        budget: {
          remainingBudget: participant.remaining_budget,
          spent: participant.spent,
          budget: state.format.auction_budget,
          overAssumedBudget: participant.over_assumed_budget,
          // Set only for the seat that actually holds the high bid, so the
          // caveat appears exactly where the headline figure is currently
          // incomplete and nowhere else.
          liveBidAmount: holdsHighBid ? (openLot?.high_bid_amount ?? null) : null,
          liveBidPlayerLabel: holdsHighBid ? (openLot?.player_label ?? null) : null,
        },
      }
    })

  const logRows = buildLogRows(events, state.participants, openLot)

  return {
    state,
    isAuction: state.format.draft_type === 'auction',
    seats,
    openLot,
    openLotNominatorName: openLot
      ? nameOf(state.participants, openLot.nominated_by_participant_id)
      : null,
    openLotHighBidderName: nameOf(state.participants, highBidder),
    logRows,
    guaranteedCorrectionSequence: guaranteedCorrectionSequence(events),
    liveEventCount: logRows.filter((row) => !row.isVoided && !row.isVoid).length,
    voidedCount: logRows.filter((row) => row.isVoided).length,
  }
}

/**
 * A human phrase for an event, used in the log and in correction confirmations.
 *
 * Money is interpolated as the string the backend sent. Formatting it would
 * mean parsing it, and parsing an exact decimal into a float to print it back
 * is the one place this screen could invent a wrong number out of a right one.
 */
export function describeEvent(row: LogRow): string {
  const { event, participantName, playerLabel } = row
  const who = participantName ?? (event.participant_id === null ? 'nobody' : 'an unknown seat')
  // "a player this screen cannot name" rather than a stand-in that reads like a
  // name. A sale whose player the backend published no holding for is a sale
  // whose player this screen genuinely does not know, and saying so is more
  // useful than a phrase a reader might mistake for the record.
  const player = playerLabel ?? 'a player this entry does not name'

  switch (event.event_type) {
    case 'pick':
      return `${who} selected ${player}`
    case 'nomination':
      return event.amount === null
        ? `${who} nominated ${player}`
        : `${who} nominated ${player} at $${event.amount}`
    case 'bid':
      return `${who} bid $${event.amount ?? '?'}`
    case 'sale':
      return `${player} sold to ${who} for $${event.amount ?? '?'}`
    case 'void':
      return `Correction: entry ${String(event.supersedes_sequence)} withdrawn`
    case 'closed':
      return 'Draft declared over'
    default:
      // Not a default that silently accepts anything: `event_type` is a closed
      // union in the contract, so reaching here means the backend published a
      // kind this build does not know. Naming it is more useful than hiding it.
      return `Unrecognised entry of kind ${String(event.event_type)}`
  }
}

/**
 * Split a refusal into its lead and the remedy that actually works.
 *
 * A void whose replay refuses carries **two** instructions:
 *
 *   "...Ilario Bexley is still on the block. Record the sale, or void the
 *    nomination at sequence 5. To void sequence 6, void back from sequence 15
 *    to sequence 7 first."
 *
 * The first describes the *hypothetical replayed* log rather than the actual
 * one. Following it produces another well-formed refusal that redirects
 * correctly -- a wasted round trip rather than a dead end, but a wasted round
 * trip under an auction clock. The second is explicit, names this sequence,
 * comes last, and is the one that succeeds; the backend lane drove it to
 * completion, refusal to 201.
 *
 * This does not paraphrase, reorder or drop anything: `lead + remedy` is the
 * original string byte for byte, asserted in the tests. The screen renders both
 * and only weights them differently, because choosing which of two competing
 * instructions to follow is exactly the judgement a screen can carry and a
 * message cannot.
 */
export function splitRefusalRemedy(detail: string): { lead: string; remedy: string | null } {
  const match = /To void sequence \d+,[^.]*\.\s*$/.exec(detail)
  if (match === null) return { lead: detail, remedy: null }
  return { lead: detail.slice(0, match.index), remedy: detail.slice(match.index) }
}
