/**
 * The recording panel. This is the screen's reason to exist.
 *
 * The first real user is the owner recording a mock auction he is playing in,
 * and an auction clock does not wait. So the design question is not "what can
 * be recorded" but **"what is the fewest keystrokes for the thing that actually
 * happens, and what does a mistake cost"**.
 *
 * ## What actually happens in a room
 *
 * The recorder is bidding as well as typing. The realistic floor is that they
 * catch the *sale* — "Whitcombe went to Dave for $41" — and miss the nomination
 * and every bid in between. The backend supports that directly: a `sale` may
 * name its own player when no lot is open. So **sale is the default mode**, and
 * nomination and bid are the modes for when the recorder is keeping up rather
 * than the mandatory path into one.
 *
 * When a lot *is* open the player is no longer a free field — the lot names it,
 * and a sale naming a different player is refused with
 * `draft_lot_player_mismatch`. So the field is replaced by the lot's player,
 * shown and not editable, and the sale drops to two fields. A field that cannot
 * be wrong beats a field that is validated.
 *
 * **An ordered draft is one field.** `next_pick` names the seat, and a pick
 * recorded against any other seat is refused with `draft_pick_out_of_turn`, so
 * offering a seat picker would offer a choice with exactly one correct answer.
 * The seat is shown, the player is typed, Enter submits.
 *
 * ## What a mistake costs
 *
 * Every append carries `expected_last_sequence`. The recorder is one person at
 * one screen, but there is also a poll running, and a double submit under time
 * pressure is the failure this prevents: the second lands as `409
 * draft_sequence_conflict` instead of recording the pick twice.
 *
 * **A failed submit never clears the form.** On a conflict what was typed was
 * *correct* and merely stale; on a refusal it is usually one field away from
 * correct. Clearing it would make the recorder retype, under the clock, the
 * thing they had already typed right — so the values stay and the message says
 * what to change.
 *
 * ## Why this panel explains itself, and where
 *
 * The owner opened the finished board and said he had no idea how to use it.
 * The gap was precise and measurable: the **log** panel carried four sentences
 * of prose about what a correction is, and the panel he actually types into
 * carried none. Driven in a browser against the seeded auction at `/draft/1`,
 * the whole text content of this section was:
 *
 *     Sale Bid Nomination PLAYER SEAT <twelve seat names> PRICE Record
 *
 * Thirty-nine words, none of them explanatory. **The half he reads was
 * documented and the half he uses was not.** Snake was better but not by much —
 * it already said the seat is fixed by the recorded order, and said nothing
 * about anything else.
 *
 * Three claims are made on screen below, and each was driven against the live
 * API rather than read off a docstring:
 *
 * - **A sale needs no nomination before it.** Recorded `Probe Onlysale` to a
 *   seat for $7 with no lot open: accepted, the seat's holdings gained the
 *   player, and `selections_made` moved 7 → 8.
 * - **Nomination and bid fill no roster slot.** Recorded one of each:
 *   `selections_made` stayed at 8 across both. (The seats panel *does* print
 *   the nominee's name against the high bidder — that is the live-bid caveat,
 *   not a holding, and a substring check on the panel cannot tell them apart.
 *   The count is the measurement that can.)
 * - **A recorded entry lands at the top of the log with Undo on it.** The
 *   append above became `#16 Probe Onlysale sold to Bench Mob for $7.00` with
 *   `log-undo-16` beside it.
 *
 * ## Why the guidance recedes, and why it does not disappear
 *
 * This screen has two users who are the same person in different states: one
 * who has never recorded anything and needs to learn the panel, and one who is
 * mid-auction with thirty seconds a pick and needs the space. So the split is
 * by cost. The two lines that are cheapest and most load-bearing — *this
 * records, it does not advise*, and *only a sale fills a slot* — are always
 * visible. Everything else sits in a disclosure that **recedes on the first
 * successful record and only that once**; a second auto-collapse would fight a
 * reader who had deliberately reopened it.
 *
 * It recedes to a summary line rather than to nothing, because the state that
 * produced this defect is *"has recorded before, does not remember"* — the
 * owner a week later, on a draft that already has entries. Teaching that only
 * ever fires on an empty draft would be gone exactly when it was next needed.
 *
 * And the disclosure sits **below** the submit button. Expanding it therefore
 * cannot displace a field, which is what makes reopening it safe to do at any
 * point in a draft rather than only before one starts.
 */

import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { appendDraftEvent } from '../api/draftEndpoints'
import { describeDraftError, isStaleWriteError } from '../api/draftErrors'
import type { DraftEventRequest, DraftState } from '../api/draftTypes'
import type { DraftBoardModel } from './draftBoardModel'

type AuctionMode = 'sale' | 'bid' | 'nomination'

interface DraftRecorderProps {
  model: DraftBoardModel
  /** Called with the state the backend returned, so the board updates at once. */
  onRecorded: (state: DraftState) => void
  /** Called after any append attempt, so the poll can resynchronise. */
  onAttempted?: () => void
}

export function DraftRecorder({ model, onRecorded, onAttempted }: DraftRecorderProps) {
  const { state, isAuction, openLot } = model
  const [mode, setMode] = useState<AuctionMode>('sale')
  const [playerLabel, setPlayerLabel] = useState('')
  const [participantId, setParticipantId] = useState<string>('')
  const [amount, setAmount] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [lastRecorded, setLastRecorded] = useState<string | null>(null)
  // Open to begin with: a reader who has never used this panel is the case the
  // guidance exists for, and there is no cheap way to recognise one.
  const [guideOpen, setGuideOpen] = useState(true)
  // Whether the one automatic collapse has already been spent.
  const hasReceded = useRef(false)

  const firstFieldRef = useRef<HTMLInputElement | HTMLSelectElement | null>(null)
  const ids = useId()

  const isClosed = state.status === 'closed'
  const lotIsOpen = openLot !== null

  // A sale of the open lot must not name a player, so the mode's own affordance
  // disappears rather than being disabled with an explanation.
  // A bid names no player at all — the lot does, so a bid cannot disagree with
  // the lot it is a bid on. A sale names one only when there is no lot to
  // inherit it from. An ordered draft always names one.
  const needsPlayer = isAuction ? mode === 'nomination' || (mode === 'sale' && !lotIsOpen) : true

  const nextPickParticipantId = state.next_pick?.participant_id ?? null
  const nextPickSeat = state.participants.find((seat) => seat.id === nextPickParticipantId) ?? null

  useEffect(() => {
    // Focus follows the mode, so switching mode leaves the caret in the field
    // the recorder is about to type into rather than where the last one was.
    firstFieldRef.current?.focus()
  }, [mode, isAuction])

  function resetAfterSuccess(summary: string) {
    setPlayerLabel('')
    setAmount('')
    setError(null)
    setLastRecorded(summary)
    // The recorder has now seen the panel work once, so the space the guidance
    // occupies is worth more than the guidance. Once only — after this the
    // disclosure belongs to whoever opened it.
    if (!hasReceded.current) {
      hasReceded.current = true
      setGuideOpen(false)
    }
    // The seat is deliberately *not* cleared in an auction: consecutive entries
    // on one lot are usually the same seat bidding itself up, and re-picking it
    // every time is the keystroke this screen can most afford to save.
    firstFieldRef.current?.focus()
  }

  async function submit(body: DraftEventRequest, summary: string) {
    setPending(true)
    try {
      const next = await appendDraftEvent(state.id, {
        ...body,
        expected_last_sequence: state.last_sequence,
      })
      onRecorded(next)
      resetAfterSuccess(summary)
    } catch (cause) {
      const failure = cause instanceof Error ? cause : new Error(String(cause))
      setError(failure)
      // A stale write means the board this screen is showing is behind. Ask the
      // page to re-read so the *next* attempt carries a current
      // `expected_last_sequence` rather than failing the same way forever.
      if (isStaleWriteError(failure)) {
        onAttempted?.()
      }
    } finally {
      setPending(false)
    }
  }

  function handleSubmit(submitEvent: FormEvent) {
    submitEvent.preventDefault()
    if (pending || isClosed) return

    const player = playerLabel.trim()
    const price = amount.trim()

    if (!isAuction) {
      if (nextPickParticipantId === null) return
      void submit(
        { event_type: 'pick', participant_id: nextPickParticipantId, player_label: player },
        `Pick recorded: ${player}`,
      )
      return
    }

    const seatId = Number(participantId)
    if (!Number.isInteger(seatId) || seatId <= 0) return

    if (mode === 'bid') {
      void submit(
        { event_type: 'bid', participant_id: seatId, amount: price },
        `Bid recorded: $${price}`,
      )
      return
    }

    if (mode === 'nomination') {
      const body: DraftEventRequest =
        price === ''
          ? { event_type: 'nomination', participant_id: seatId, player_label: player }
          : {
              event_type: 'nomination',
              participant_id: seatId,
              player_label: player,
              amount: price,
            }
      void submit(body, `Nomination recorded: ${player}`)
      return
    }

    const body: DraftEventRequest = lotIsOpen
      ? { event_type: 'sale', participant_id: seatId, amount: price }
      : { event_type: 'sale', participant_id: seatId, amount: price, player_label: player }
    void submit(body, `Sale recorded: ${lotIsOpen ? openLot.player_label : player} at $${price}`)
  }

  const described = error ? describeDraftError(error) : null
  const backendWording = error?.message ?? null
  const showsBackendWording = backendWording !== null && backendWording !== described?.summary

  if (isClosed) {
    return (
      <section className="recorder recorder--closed" aria-labelledby={`${ids}-title`}>
        <h2 id={`${ids}-title`}>Recording</h2>
        <p className="state state--empty" data-testid="recorder-closed">
          This draft has been declared over, so nothing further can be recorded. Void the closing
          entry in the log to reopen it.
        </p>
      </section>
    )
  }

  return (
    <section className="recorder" aria-labelledby={`${ids}-title`}>
      <h2 id={`${ids}-title`}>Recording</h2>

      {/* Two sentences, always visible, chosen because they are the two a
          reader cannot afford to be missing while typing. Everything else is
          in the disclosure below the form.

          Says "does not advise" rather than "is not a recommender", and that is
          not a stylistic preference. The `no-decision-numbers` guard in
          `DraftPage.recorded.test.tsx` word-boundary matches `recommend` over
          everything inside `.draft__panels`, and the page lede is exempt only
          because it sits outside them. Widening that scope to fit this sentence
          would trade a real guard for a phrasing, so the phrasing moved. The
          cost is worth naming: the guard matches vocabulary as a proxy for
          leaked decision numbers, so it constrains prose *denying* them too. */}
      <p className="recorder__lede" data-testid="recorder-lede">
        <strong>You type what happened in the room.</strong> This panel records; it does not
        advise.
      </p>

      {isAuction ? (
        <div className="recorder__modes" role="group" aria-label="What to record">
          {(['sale', 'bid', 'nomination'] as const).map((candidate) => (
            <button
              key={candidate}
              type="button"
              className={
                mode === candidate ? 'recorder__mode recorder__mode--on' : 'recorder__mode'
              }
              aria-pressed={mode === candidate}
              onClick={() => {
                setMode(candidate)
              }}
              data-testid={`recorder-mode-${candidate}`}
            >
              {candidate === 'sale' ? 'Sale' : candidate === 'bid' ? 'Bid' : 'Nomination'}
            </button>
          ))}
        </div>
      ) : null}

      {/* Sits directly under the three buttons because it is about the choice
          between them, and because a recorder who reads only one line should
          read the one that says two of the three are optional. Driven, not
          assumed: a nomination and a bid each left `selections_made` where it
          was, and a sale with no lot open moved it. */}
      {isAuction ? (
        <p className="recorder__hint" data-testid="recorder-mode-hint">
          Only <strong>Sale</strong> fills a roster slot. Nomination and bid are optional detail —
          skip them and the roster is still right.
        </p>
      ) : null}

      {isAuction && lotIsOpen ? (
        <p className="recorder__context" data-testid="recorder-open-lot">
          On the block: <strong>{openLot.player_label}</strong>
          {openLot.high_bid_amount !== null ? (
            <>
              {' '}
              — high bid <strong>${openLot.high_bid_amount}</strong>
              {model.openLotHighBidderName !== null ? ` from ${model.openLotHighBidderName}` : ''}
            </>
          ) : (
            <> — no bid recorded yet</>
          )}
        </p>
      ) : null}

      {!isAuction ? (
        <p className="recorder__context" data-testid="recorder-next-pick">
          {state.next_pick === null ? (
            <>Every pick in this draft has been recorded.</>
          ) : nextPickSeat === null ? (
            <>
              Pick {state.next_pick.overall_pick} belongs to team slot {state.next_pick.team_slot},
              which no seat in this draft holds. Nothing can be recorded against it.
            </>
          ) : (
            <>
              On the clock: <strong>{nextPickSeat.display_name}</strong> — round{' '}
              {state.next_pick.round_number}, pick {state.next_pick.pick_in_round} (overall{' '}
              {state.next_pick.overall_pick}). The seat is fixed by the recorded order, so it is
              derived rather than asked for
              {state.format.auction_budget === null
                ? ', and this draft has no budget, so there is no price either'
                : ''}
              . The player&apos;s name is the only thing to type.
            </>
          )}
        </p>
      ) : null}

      <form className="recorder__form" onSubmit={handleSubmit}>
        {needsPlayer ? (
          <label className="recorder__field">
            <span>Player</span>
            <input
              ref={(node) => {
                // The player field, when rendered, is always the first field.
                firstFieldRef.current = node
              }}
              type="text"
              value={playerLabel}
              onChange={(changeEvent) => {
                setPlayerLabel(changeEvent.target.value)
              }}
              autoComplete="off"
              required
              data-testid="recorder-player"
              placeholder="as the name was written"
            />
          </label>
        ) : null}

        {isAuction ? (
          <label className="recorder__field">
            <span>Seat</span>
            <select
              ref={(node) => {
                // The seat is the first field only when no player is being
                // named — a bid, or a sale of an already-open lot.
                if (!needsPlayer) firstFieldRef.current = node
              }}
              value={participantId}
              onChange={(changeEvent) => {
                setParticipantId(changeEvent.target.value)
              }}
              required
              data-testid="recorder-seat"
            >
              <option value="">Choose a seat</option>
              {model.seats.map((seat) => (
                <option key={seat.participant.id} value={String(seat.participant.id)}>
                  {seat.participant.display_name}
                  {seat.participant.is_owner ? ' (you)' : ''}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        {isAuction ? (
          <label className="recorder__field recorder__field--amount">
            <span>{mode === 'nomination' ? 'Opening bid' : mode === 'bid' ? 'Bid' : 'Price'}</span>
            <input
              type="text"
              inputMode="decimal"
              value={amount}
              onChange={(changeEvent) => {
                setAmount(changeEvent.target.value)
              }}
              autoComplete="off"
              required={mode !== 'nomination'}
              data-testid="recorder-amount"
              placeholder={mode === 'nomination' ? 'optional' : '0'}
            />
          </label>
        ) : null}

        <button
          type="submit"
          className="recorder__submit"
          disabled={pending || (!isAuction && nextPickParticipantId === null)}
          data-testid="recorder-submit"
        >
          {pending ? 'Recording…' : 'Record'}
        </button>
      </form>

      {lastRecorded !== null && error === null ? (
        <p className="recorder__ok" role="status" data-testid="recorder-ok">
          {/* Deliberately does not claim the entry is *at the top*: the poll can
              pick up a write this tab did not make between the append and this
              render, and "look in the log beside this panel" stays true either
              way. */}
          {lastRecorded}. Log is at entry {state.last_sequence} — it is in the log beside this
          panel, where it can be undone.
        </p>
      ) : null}

      {error !== null && described !== null ? (
        <div className="recorder__error state state--error" role="alert">
          <p data-testid="recorder-error-summary">{described.summary}</p>
          <p className="state__detail" data-testid="recorder-error-action">
            {described.action}
          </p>
          {showsBackendWording ? (
            <p className="state__meta" data-testid="recorder-error-backend">
              Backend said: <q>{backendWording}</q>
            </p>
          ) : null}
          <p className="state__meta">
            Nothing was recorded, and what you typed is still above.
            {error instanceof ApiError && error.code !== null ? (
              <>
                {' '}
                Code <code data-testid="recorder-error-code">{error.code}</code>
              </>
            ) : null}
          </p>
        </div>
      ) : null}

      {/*
        Below the form on purpose. Opening it cannot move a field, which is
        what makes it safe to reopen mid-draft rather than only before one
        starts. See the note at the top of this file.

        The last point overlaps the log's own lede, and that overlap is
        deliberate rather than an oversight: the log explains what a correction
        *is*, which is a different question from where the thing you just typed
        went. Nothing is taken from the log to pay for it.
      */}
      <details
        className="recorder__guide"
        data-testid="recorder-guide"
        open={guideOpen}
        onToggle={(toggleEvent) => {
          setGuideOpen(toggleEvent.currentTarget.open)
        }}
      >
        <summary data-testid="recorder-guide-summary">
          {isAuction ? 'What each of the three records' : 'What this form records'}
        </summary>
        <ul className="recorder__guide-points" data-testid="recorder-guide-points">
          {isAuction ? (
            <>
              <li>
                <strong>Sale</strong> — who bought whom, and for how much. The only entry that puts
                a player on a roster.
              </li>
              <li>
                <strong>Nomination</strong> and <strong>Bid</strong> — who put a player up, and the
                prices called on the way. Colour, not the record. A room moves faster than typing,
                and a draft recorded as sales alone still has every roster right.
              </li>
              <li>
                A sale needs no nomination in front of it. While a lot <em>is</em> on the block the
                sale takes its player from the lot, so the player field goes away and only the seat
                and the price are typed.
              </li>
              <RecordDestinationPoint />
            </>
          ) : (
            <>
              <li>
                The player&apos;s name is the whole entry. No seat is asked for because the
                recorded turn order already fixes who is on the clock, and a picker would offer a
                choice with one correct answer.
              </li>
              <li>
                No price is asked for either
                {state.format.auction_budget === null
                  ? ' — this draft has no budget for one to come out of'
                  : ''}
                . Their absence is a derivation, not a missing feature.
              </li>
              <RecordDestinationPoint />
            </>
          )}
        </ul>
      </details>
    </section>
  )
}

/**
 * Where a recorded entry goes, which is the same answer in both formats.
 *
 * Says *newest first* rather than *at the top*: the ordering is this build's
 * own decision in `DraftLog` and is therefore something the screen can promise,
 * where a claim about which row is first is only true until the poll picks up a
 * write from somewhere else.
 */
function RecordDestinationPoint() {
  return (
    <li>
      <strong>Record</strong> puts what you typed into the log beside this panel, which runs newest
      first, with <strong>Undo</strong> on it. Nothing there is edited in place — the log explains
      how corrections work.
    </li>
  )
}
