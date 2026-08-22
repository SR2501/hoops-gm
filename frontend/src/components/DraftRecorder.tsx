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
              {state.next_pick.overall_pick}). The seat is fixed by the recorded order, so only the
              player is typed.
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
          {lastRecorded}. Log is at entry {state.last_sequence}.
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
    </section>
  )
}
