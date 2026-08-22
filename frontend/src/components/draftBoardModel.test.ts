/**
 * Unit tests for the board's derivation.
 *
 * Two habits are deliberate here, both from failures this repository had today.
 *
 * **Every test that iterates first asserts it found something to iterate over,
 * and asserts how many.** Seven separate checks across the project examined an
 * empty set and reported success — a probe computing `count - swatches` where
 * two absences cancel to zero, a suite parametrised over an empty list
 * collecting nothing and passing. A fixture that failed to load would satisfy
 * "no entry is miscategorised" perfectly.
 *
 * **Where a derivation can be cross-checked against a number the server
 * computed separately, it is.** `live_event_count` and `voided_sequences` are
 * the backend's own arithmetic over the same log, so asserting the derivation
 * against them is a check with an independent source rather than against a
 * value this lane wrote down. That check earned its place immediately: the
 * first version of `liveEventCount` counted the `void` entry itself as live and
 * was off by one against a server that did not.
 */

import { describe, expect, it } from 'vitest'
import type { DraftEvent, DraftEventsPage, DraftState } from '../api/draftTypes'
import auctionEventsFixture from '../test/fixtures/draft-auction-events.recorded.json'
import auctionStateFixture from '../test/fixtures/draft-auction-state.recorded.json'
import snakeEventsFixture from '../test/fixtures/draft-snake-events.recorded.json'
import snakeStateFixture from '../test/fixtures/draft-snake-state.recorded.json'
import voidedSaleEventsFixture from '../test/fixtures/draft-auction-voided-sale-events.recorded.json'
import voidedSaleStateFixture from '../test/fixtures/draft-auction-voided-sale-state.recorded.json'
import {
  buildDraftBoardModel,
  buildLogRows,
  describeEvent,
  guaranteedCorrectionSequence,
} from './draftBoardModel'

const auctionState = auctionStateFixture as unknown as DraftState
const auctionEvents = (auctionEventsFixture as unknown as DraftEventsPage).events
const snakeState = snakeStateFixture as unknown as DraftState
const snakeEvents = (snakeEventsFixture as unknown as DraftEventsPage).events
const voidedSaleState = voidedSaleStateFixture as unknown as DraftState
const voidedSaleEvents = (voidedSaleEventsFixture as unknown as DraftEventsPage).events

describe('the recorded fixtures themselves', () => {
  // If this block fails, every assertion below it is vacuous. It runs first for
  // that reason: a test that iterates over a fixture that did not load is a
  // test that passes over nothing.
  it('loaded with the shape the rest of this file assumes', () => {
    expect(auctionEvents).toHaveLength(18)
    expect(snakeEvents).toHaveLength(12)
    expect(auctionState.participants).toHaveLength(12)
    expect(snakeState.participants).toHaveLength(10)
    expect(auctionState.open_lot).not.toBeNull()
    expect(auctionState.voided_sequences).toEqual([13])
    expect(voidedSaleEvents).toHaveLength(20)
    expect(voidedSaleState.voided_sequences).toEqual([13, 19])
    expect(voidedSaleState.open_lot?.nomination_sequence).toBe(16)
  })
})

describe('guaranteedCorrectionSequence', () => {
  it('is the highest sequence in the log', () => {
    expect(guaranteedCorrectionSequence(auctionEvents)).toBe(18)
    expect(guaranteedCorrectionSequence(snakeEvents)).toBe(12)
  })

  it('agrees with the last_sequence the server reported', () => {
    // A second, independent statement of the same fact. If the fixture's events
    // and its state ever disagree, one of them is stale and this notices.
    expect(guaranteedCorrectionSequence(auctionEvents)).toBe(auctionState.last_sequence)
  })

  it('is null when the last entry is itself a void, because a void cannot be undone', () => {
    const throughTheVoid = auctionEvents.filter((event) => event.sequence <= 14)
    const last = throughTheVoid.at(-1)
    // Assert the state observed, not the slice requested: if the fixture's
    // ordering ever changed, `<= 14` might not end on the void at all.
    expect(last?.event_type).toBe('void')
    expect(guaranteedCorrectionSequence(throughTheVoid)).toBeNull()
  })

  it('is null for an empty log rather than throwing', () => {
    expect(guaranteedCorrectionSequence([])).toBeNull()
  })

  it('does not assume the array arrives in order', () => {
    const shuffled = [...auctionEvents].reverse()
    expect(shuffled[0]?.sequence).toBe(18)
    expect(guaranteedCorrectionSequence(shuffled)).toBe(18)
  })
})

describe('buildLogRows', () => {
  it('orders by sequence and never by occurred_at', () => {
    // The backend's own field docstring says a client that sorts on the
    // timestamp is wrong. Prove ordering survives a payload where the two
    // disagree, rather than a payload where they happen to coincide.
    const scrambled: DraftEvent[] = auctionEvents.map((event, index) => ({
      ...event,
      occurred_at: `2026-08-21T19:${String(59 - index).padStart(2, '0')}:00Z`,
    }))
    const rows = buildLogRows(scrambled, auctionState.participants)

    expect(rows).toHaveLength(18)
    expect(rows.map((row) => row.event.sequence)).toEqual(
      Array.from({ length: 18 }, (_, index) => index + 1),
    )
  })

  it('classifies every entry, and the counts of each class are what the log says', () => {
    const rows = buildLogRows(auctionEvents, auctionState.participants)
    expect(rows).toHaveLength(auctionEvents.length)

    const byClass = {
      guaranteed: rows.filter((row) => row.correctability === 'guaranteed'),
      mayBeRefused: rows.filter((row) => row.correctability === 'may-be-refused'),
      none: rows.filter((row) => row.correctability === 'none'),
    }
    // Exactly one guaranteed correction, always. Two entries cannot both be
    // last, and offering two would be promising something untrue about one.
    expect(byClass.guaranteed).toHaveLength(1)
    expect(byClass.guaranteed[0]?.event.sequence).toBe(18)
    // The two that cannot be corrected are the superseded sale and the void
    // that superseded it — named, not merely counted.
    expect(byClass.none.map((row) => row.event.sequence)).toEqual([13, 14])
    expect(byClass.mayBeRefused).toHaveLength(15)
    // And the three classes partition the log with nothing left over.
    expect(
      byClass.guaranteed.length + byClass.mayBeRefused.length + byClass.none.length,
    ).toBe(rows.length)
  })

  it('gives a superseded entry a reason naming the entry that superseded it', () => {
    const rows = buildLogRows(auctionEvents, auctionState.participants)
    const voided = rows.filter((row) => row.isVoided)

    expect(voided).toHaveLength(1)
    expect(voided[0]?.event.sequence).toBe(13)
    expect(voided[0]?.correctabilityReason).toBe('Already corrected by entry 14.')
  })

  it('resolves seat names for every entry that names a seat', () => {
    const rows = buildLogRows(auctionEvents, auctionState.participants)
    const withSeat = rows.filter((row) => row.event.participant_id !== null)

    expect(withSeat.length).toBeGreaterThan(0)
    expect(withSeat.every((row) => row.participantName !== null)).toBe(true)
  })

  it('leaves a seat unresolved rather than inventing a name for it', () => {
    // The failure mode this guards is a name appearing that the response never
    // sent. An unresolvable seat must read as unresolved.
    const rows = buildLogRows(auctionEvents, [])
    expect(rows).toHaveLength(18)
    expect(rows.filter((row) => row.participantName === null)).toHaveLength(18)
  })

  it('names the player on a sale that inherited it from the open lot', () => {
    // A sale of an open lot carries no `player_label`: the lot named the player
    // and the recorder is not asked to retype it. Before this, four entries in
    // this log read "the open lot sold to …" and named nobody.
    const rows = buildLogRows(auctionEvents, auctionState.participants)
    const inherited = rows.filter(
      (row) => row.event.event_type === 'sale' && row.event.player_label === null,
    )

    // The count is the assertion. If the fixture stopped containing this shape,
    // this test would pass over nothing and prove the opposite of its name.
    expect(inherited).toHaveLength(4)
    expect(inherited.every((row) => row.playerLabel !== null)).toBe(true)
    expect(rows.find((row) => row.event.sequence === 12)?.playerLabel).toBe('Oskar Vellamo')
    expect(describeEvent(rows.find((row) => row.event.sequence === 12)!)).toBe(
      'Oskar Vellamo sold to Load Management for $22.00',
    )
  })

  it('says a player is unnamed rather than filling the gap with a guess', () => {
    // Holdings stripped: the resolution has nothing to draw on. The row must
    // then say so, not fall back to walking the log for a nearby nomination —
    // which would be this screen inventing a fact the backend did not state.
    const withoutHoldings = auctionState.participants.map((seat) => ({ ...seat, holdings: [] }))
    const rows = buildLogRows(auctionEvents, withoutHoldings)
    const inherited = rows.filter(
      (row) => row.event.event_type === 'sale' && row.event.player_label === null,
    )

    expect(inherited).toHaveLength(4)
    expect(inherited.every((row) => row.playerLabel === null)).toBe(true)
    expect(describeEvent(inherited[0]!)).toContain('does not name')
  })

  it('names the player on a withdrawn sale, from the lot the withdrawal reopened', () => {
    // Recorded from a live backend after driving record-then-undo in a browser:
    // voiding sale 19 removed the holding that named its player and reopened
    // the lot. Without this the entry the recorder just corrected reads as
    // naming nobody, which is the moment it matters most.
    const rows = buildLogRows(
      voidedSaleEvents,
      voidedSaleState.participants,
      voidedSaleState.open_lot,
    )
    const withdrawn = rows.find((row) => row.event.sequence === 19)

    expect(voidedSaleState.open_lot).not.toBeNull()
    expect(voidedSaleState.voided_sequences).toEqual([13, 19])
    expect(withdrawn?.event.event_type).toBe('sale')
    expect(withdrawn?.event.player_label).toBeNull()
    expect(withdrawn?.isVoided).toBe(true)
    // No holding exists for it — so this resolution really is the only route,
    // rather than passing because the holdings map happened to cover it.
    const holdingSequences = voidedSaleState.participants.flatMap((seat) =>
      seat.holdings.map((holding) => holding.event_sequence),
    )
    expect(holdingSequences).not.toContain(19)
    expect(withdrawn?.playerLabel).toBe('Rune Halvorsen')
  })

  it('does not attach a lot nominated after the withdrawn sale', () => {
    // The guard that makes the rule above sound. A lot nominated later is a
    // different lot, and claiming it here would put a wrong name on the entry.
    const laterLot = {
      ...voidedSaleState.open_lot!,
      nomination_sequence: 19,
      player_label: 'Someone Else',
    }
    const rows = buildLogRows(voidedSaleEvents, voidedSaleState.participants, laterLot)
    const withdrawn = rows.find((row) => row.event.sequence === 19)

    expect(withdrawn?.isVoided).toBe(true)
    expect(withdrawn?.playerLabel).toBeNull()
  })
})

describe('buildDraftBoardModel', () => {
  it('agrees with the counts the server computed over the same log', () => {
    const model = buildDraftBoardModel(auctionState, auctionEvents)

    expect(model.liveEventCount).toBe(auctionState.live_event_count)
    expect(model.voidedCount).toBe(auctionState.voided_sequences.length)
    expect(model.liveEventCount).toBeGreaterThan(0)
  })

  it('agrees with the server on the snake draft too, where no entry is voided', () => {
    const model = buildDraftBoardModel(snakeState, snakeEvents)

    expect(model.liveEventCount).toBe(snakeState.live_event_count)
    expect(model.voidedCount).toBe(0)
    expect(model.isAuction).toBe(false)
  })

  it('attaches the live bid to the one seat holding it and to no other', () => {
    const model = buildDraftBoardModel(auctionState, auctionEvents)
    const withLiveBid = model.seats.filter((seat) => seat.budget.liveBidAmount !== null)

    expect(model.seats).toHaveLength(12)
    // The count is the assertion. "No other seat has one" is satisfied by every
    // seat lacking one, which is the shape of the bug this file exists to avoid.
    expect(withLiveBid).toHaveLength(1)
    expect(withLiveBid[0]?.participant.id).toBe(9)
    expect(withLiveBid[0]?.participant.display_name).toBe('Trade Deadline')
    expect(withLiveBid[0]?.budget.liveBidAmount).toBe('150.00')
    expect(withLiveBid[0]?.budget.liveBidPlayerLabel).toBe('Rune Halvorsen')
    // And the caveat is real: this seat reports a full budget while holding a
    // committed $150 bid. If these two were ever equal the caveat would be
    // pointless and this test would be testing nothing.
    expect(withLiveBid[0]?.budget.remainingBudget).toBe('200.00')
    expect(withLiveBid[0]?.budget.spent).toBe('0.00')
  })

  it('passes money through as the string the backend sent, with no arithmetic', () => {
    const model = buildDraftBoardModel(auctionState, auctionEvents)
    const sent = new Map(
      auctionState.participants.map((seat) => [seat.id, seat.remaining_budget]),
    )

    expect(sent.size).toBe(12)
    for (const seat of model.seats) {
      const original = sent.get(seat.participant.id)
      expect(original).toBeDefined()
      // Byte-identical, not numerically equal: a float round-trip would turn
      // "200.00" into "200" and pass a numeric comparison while losing the
      // exactness that is the whole reason these arrive as strings.
      expect(seat.budget.remainingBudget).toBe(original)
      expect(typeof seat.budget.remainingBudget).toBe('string')
    }
  })

  it('orders seats by team slot so the board matches the room', () => {
    const model = buildDraftBoardModel(auctionState, auctionEvents)
    const slots = model.seats.map((seat) => seat.participant.team_slot)

    expect(slots).toHaveLength(12)
    expect(slots).toEqual([...slots].sort((a, b) => a - b))
  })
})

describe('describeEvent', () => {
  it('describes every entry in both recorded logs without falling through', () => {
    const rows = [
      ...buildLogRows(auctionEvents, auctionState.participants),
      ...buildLogRows(snakeEvents, snakeState.participants),
    ]
    expect(rows).toHaveLength(30)

    const descriptions = rows.map(describeEvent)
    expect(descriptions.filter((text) => text.includes('Unrecognised'))).toHaveLength(0)
    expect(descriptions.filter((text) => text.length === 0)).toHaveLength(0)
    // And the kinds actually exercised, so a fixture that lost a kind is loud
    // rather than quietly reducing this test's reach.
    const kinds = new Set(rows.map((row) => row.event.event_type))
    expect([...kinds].sort()).toEqual(['bid', 'nomination', 'pick', 'sale', 'void'])
  })

  it('interpolates money as the backend wrote it', () => {
    const sale = buildLogRows(auctionEvents, auctionState.participants).find(
      (row) => row.event.sequence === 3,
    )
    expect(sale?.event.event_type).toBe('sale')
    expect(sale?.event.amount).toBe('62.00')
    expect(describeEvent(sale!)).toContain('$62.00')
  })

  it('names an unknown kind rather than hiding it', () => {
    const row = buildLogRows(
      [{ ...auctionEvents[0]!, event_type: 'auctioneer_sneezed' as DraftEvent['event_type'] }],
      auctionState.participants,
    )[0]!
    expect(describeEvent(row)).toContain('auctioneer_sneezed')
  })
})
