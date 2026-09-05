/**
 * What a draft refusal means, and — the part that matters — what happens to one
 * this module has never heard of.
 *
 * **The fallback shows the backend's own words.** Every other error module in
 * this dashboard replaces an unrecognised code with a generic sentence and
 * relies on `AsyncBoundary` to print `Backend said: …` underneath. That is
 * adequate for a read screen. It is not adequate here, and the reason is
 * concrete rather than stylistic: `draft_row_rejected` did not exist when this
 * file was first written, and it arrived on a *reworded existing case* rather
 * than a new endpoint — two inputs that used to answer `409
 * draft_sequence_conflict` now answer `422 draft_row_rejected`, with the
 * OpenAPI document byte-identical either side of the change. A code list here
 * cannot be complete, will silently fall behind, and the cost of it falling
 * behind is a recorder mid-auction reading a sentence about an unrecorded
 * reason instead of the sentence the backend actually wrote.
 *
 * So `describeDraftError` returns the server's `detail` **as the summary** when
 * it does not recognise the code. An unknown code degrades to the raw truth
 * rather than to a shrug.
 *
 * **Transience is one code, checked by equality.** `409
 * draft_sequence_conflict` means the log moved underneath this screen and a
 * re-read will usually succeed. Everything else needs the recorder to do
 * something different. A membership test against a "retryable" set would invite
 * a future editor to add a code without establishing that a second attempt
 * behaves differently, which is the whole of the reasoning a retry rests on.
 */

import { ApiError } from './client'
import type { ErrorDescription } from '../components/AsyncBoundary'

export type DraftErrorCopy = Required<ErrorDescription>

/**
 * The only code that means "try again", named once so the retry policy and the
 * copy describing it cannot drift apart.
 *
 * It became *more* exactly this after the backend split permanent row
 * rejections out into `draft_row_rejected`: two inputs that could never succeed
 * on a retry — a sale naming a `player_id` with no matching row, and a sale
 * carrying `player_id` without `player_label` while a lot is open — were being
 * published as transient, so a conforming client would have retried them
 * forever while telling the recorder another append had reached the draft
 * first.
 */
export const RETRYABLE_DRAFT_ERROR = 'draft_sequence_conflict'

export function isRetryableDraftError(error: Error): boolean {
  return error instanceof ApiError && error.code === RETRYABLE_DRAFT_ERROR
}

/**
 * Whether a refusal is about the log having moved rather than about the input.
 *
 * Used by the recorder to decide whether to keep the typed values in the form.
 * On a conflict the recorder's input was *right* and merely stale, so throwing
 * it away would make them retype a pick they already typed correctly.
 */
export function isStaleWriteError(error: Error): boolean {
  return isRetryableDraftError(error)
}

export const DRAFT_ERRORS: Record<string, DraftErrorCopy> = {
  drafts_local_only: {
    summary:
      'Recorded drafts are served to this machine only, and this request did not arrive from 127.0.0.1.',
    action:
      'Open the dashboard on the machine running the backend. See ADR-001 — the API binds loopback and is never exposed to the network.',
  },
  draft_not_found: {
    summary: 'This database holds no draft with that id.',
    action: 'Check the id in the URL, or pick a draft from the list.',
  },
  draft_league_not_found: {
    summary: 'The league this draft would belong to does not exist in this database.',
    action: 'Seed a demo database, or create the league first. See `backend/README.md`.',
  },
  draft_setup_settings_invalid: {
    summary: 'Persisted league settings do not form trustworthy draft setup evidence.',
    action:
      'Correct or re-import the league settings named by the backend, then retry the setup read. No partial league list was used.',
  },
  draft_setup_settings_stale: {
    summary: 'The newest persisted settings describe a different league, season, or roster size.',
    action:
      'Refresh league settings before creating a draft. The screen will not freeze stale setup evidence into a new board.',
  },
  draft_multiple_owner_seats: {
    summary: 'Persisted setup evidence marks more than one fantasy team as yours.',
    action:
      'Correct the league team ownership evidence, then retry. The screen will not guess which team is yours.',
  },
  draft_name_required: {
    summary: 'A draft needs a name.',
    action: 'Name this mock or real draft so it can be distinguished in the recorded drafts list.',
  },
  [RETRYABLE_DRAFT_ERROR]: {
    summary:
      'Another append reached this draft after this screen last read it, so the log has moved and this write was refused rather than applied on top of a state it did not see.',
    action:
      'The board has been re-read. Nothing was recorded, and what you typed is still in the form — check the log below, then submit again if it is still what happened.',
  },
  draft_closed: {
    summary: 'This draft has been declared over, so nothing further can be recorded against it.',
    action: 'Void the close event in the log below to reopen the draft, then record again.',
  },
  draft_no_open_lot: {
    summary: 'There is no lot on the block, so there is nothing for a bid to be a bid on.',
    action:
      'Record the nomination first, or record the sale directly with the player named — a sale needs no nomination.',
  },
  draft_lot_already_open: {
    summary:
      'A lot is already on the block, and a second nomination cannot open while it is unresolved.',
    action: 'Record the sale that cleared it, or void the nomination.',
  },
  draft_lot_player_mismatch: {
    summary: 'The player named does not match the player currently on the block.',
    action:
      'While a lot is open, a sale clears that lot. Leave the player blank to sell the open lot, or void the nomination first.',
  },
  draft_bid_not_increasing: {
    summary: 'A bid at or below the standing high bid is not a bid the room would have accepted.',
    action: 'Record the amount actually called. The standing high bid is shown on the open lot.',
  },
  draft_roster_full: {
    summary: 'This seat already holds a full roster under the format this draft was recorded with.',
    action: 'Check the seat. If an earlier selection went to the wrong one, correct it below.',
  },
  draft_board_full: {
    summary: 'Every roster slot in this draft is already filled.',
    action: 'The draft is complete. Close it, or correct an earlier entry below.',
  },
  draft_player_already_taken: {
    summary: 'A player under this name is already held in this draft.',
    action:
      "If this is a different player with the same name, add a distinguishing word such as a team abbreviation. A digit or a suffix will not work — the duplicate key drops both, so 'Player 2' and 'Player 1' are the same key.",
  },
  draft_player_label_required: {
    summary: 'This entry has to name the player, as the recorder saw the name written.',
    action: 'Type the player name and submit again.',
  },
  draft_pick_out_of_turn: {
    summary: 'This selection does not belong to the seat whose turn the recorded order says it is.',
    action: 'Check the seat against the pick shown as next. Corrections go in the log below.',
  },
  draft_unknown_participant: {
    summary: 'The seat named is not one of the seats this draft was created with.',
    action: 'Pick a seat from the list. Seats are fixed at creation and cannot be added later.',
  },
  draft_amount_required: {
    summary: 'This entry needs a price and none was given.',
    action: 'Type the amount actually paid.',
  },
  draft_sale_below_recorded_bid: {
    summary: 'The clearing price is below a bid already recorded against this lot.',
    action:
      'A lot cannot clear for less than a bid the room already called. Correct the bid below, or record the price actually paid.',
  },
  draft_void_target_missing: {
    summary: 'The entry this correction names is not an earlier entry of this draft.',
    action: 'Pick the entry to correct from the log below.',
  },
  draft_void_target_already_voided: {
    summary: 'That entry has already been corrected, so it is not in force and cannot be voided.',
    action: 'The log below marks corrected entries. Nothing further is needed for this one.',
  },
  draft_cannot_void_a_void: {
    summary: 'A correction cannot itself be undone.',
    action:
      'Record the original event again as a new entry. The log keeps both, and the sequence shows the order it happened in.',
  },
  draft_participants_incomplete: {
    summary: 'This draft does not have one seat per team in the format it was recorded under.',
    action: 'This is a creation-time fault and cannot be corrected from this screen.',
  },
  draft_duplicate_sequence: {
    summary: 'Two entries in this log claim the same position in it, which cannot describe a draft.',
    action:
      'This is a storage-level fault rather than something you typed. Quote the request id below.',
  },
  draft_event_not_applicable: {
    summary: 'That kind of entry does not exist in this draft format.',
    action:
      'An auction records nominations, bids and sales; an ordered draft records picks. The recorder offers only the ones this format accepts, so seeing this means the request came from somewhere else.',
  },
  draft_format_invalid: {
    summary: 'The configuration this draft was recorded under does not describe a runnable draft.',
    action: 'This is a creation-time fault and cannot be corrected from this screen.',
  },
}

/** Generic client-side failures, so every transport path has words of its own. */
const TRANSPORT_ERRORS: Record<string, DraftErrorCopy> = {
  unreachable: {
    summary: 'The backend did not answer at all, so nothing was recorded and nothing was read.',
    action:
      'Start the backend and retry. Nothing you typed has been lost — a request that never arrived cannot have been applied.',
  },
  timeout: {
    summary:
      'The backend accepted the request but did not answer in time, so whether it was recorded is genuinely unknown.',
    action:
      'Re-read the board before submitting again. The log below is the only authority on what landed — do not assume either way.',
  },
  invalid_response: {
    summary:
      'The backend answered, but the body did not match the draft contract, so nothing is drawn rather than drawing a board from a shape we do not recognise.',
    action: 'Check that the backend and dashboard are from the same revision.',
  },
}

/**
 * The reader's words for a failure, falling back to the backend's own.
 *
 * The fallback is the point of this function. See the module docstring: an
 * unrecognised code yields the server's `detail` verbatim as the summary, so a
 * code added upstream after this file was written still reaches the recorder as
 * a sentence about their draft rather than as an apology.
 */
export function describeDraftError(error: Error | null): DraftErrorCopy {
  if (!(error instanceof ApiError)) {
    return {
      summary: error?.message ?? 'The draft request failed for an unrecorded reason.',
      action: 'Retry. If it recurs, check the browser console and the backend logs.',
    }
  }

  // `Object.hasOwn` rather than a bare lookup: a code named `constructor` would
  // otherwise resolve to an inherited function and be treated as known copy.
  const copy = Object.hasOwn(DRAFT_ERRORS, error.code)
    ? DRAFT_ERRORS[error.code]
    : Object.hasOwn(TRANSPORT_ERRORS, error.code)
      ? TRANSPORT_ERRORS[error.code]
      : undefined

  if (copy) {
    return copy
  }

  return {
    // The backend's sentence, promoted to the summary rather than buried under
    // a generic one. `error.message` is `detail` off the response body — see
    // `client.ts`, which parses `{error, detail, request_id}` into `ApiError`.
    summary: error.message,
    action: `This dashboard has no specific guidance for code ${error.code}, so the backend's own wording is shown above unaltered. Quote the code and request id if it recurs.`,
  }
}

const UNCERTAIN_CREATION_CODES = new Set(['timeout', 'unreachable', 'invalid_response'])

export function isDraftCreationOutcomeUncertain(error: Error | null): boolean {
  return error instanceof ApiError && UNCERTAIN_CREATION_CODES.has(error.code)
}

/** Creation-specific transport guidance for a write whose result may be uncertain. */
export function describeDraftCreationError(error: Error | null): DraftErrorCopy {
  if (isDraftCreationOutcomeUncertain(error)) {
    return {
      summary:
        'The creation response was not trustworthy, so whether the draft was created is unknown.',
      action:
        'The recorded drafts list is refreshing below. Check it before doing anything else, then reload this page before trying to create again; a retry here could create a duplicate.',
    }
  }
  return describeDraftError(error)
}
