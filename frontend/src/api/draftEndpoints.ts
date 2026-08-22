/**
 * Draft tracker endpoints, with runtime guards.
 *
 * Kept beside `endpoints.ts` rather than inside it because the draft tracker is
 * the first surface in this dashboard that **writes**, and the guards a write
 * path needs are not the guards a read path needs. Mixing them makes it easy to
 * add a fourth read helper and quietly inherit none of that.
 *
 * **Every guard here asserts presence rather than the absence of a problem.**
 * `isDraftState` requires `participants` to be an array of shapes it recognises
 * and requires the numeric fields to be numbers; it never concludes a payload is
 * fine because nothing objectionable was found in it. An empty array satisfies
 * `every()` and this repository has lost seven checks to exactly that, so where
 * emptiness would be a lie the *view* asserts a count and says so.
 */

import { apiFetch, type RequestOptions, type ResponseContract } from './client'
import type {
  DraftEvent,
  DraftEventRequest,
  DraftEventsPage,
  DraftFormat,
  DraftHolding,
  DraftList,
  DraftNextPick,
  DraftOpenLot,
  DraftParticipant,
  DraftState,
  DraftSummary,
} from './draftTypes'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** A money field: a string, or `null` where the concept does not apply. */
function isDecimalOrNull(value: unknown): value is string | null {
  return typeof value === 'string' || value === null
}

function isNumberOrNull(value: unknown): value is number | null {
  return typeof value === 'number' || value === null
}

function isStringOrNull(value: unknown): value is string | null {
  return typeof value === 'string' || value === null
}

function isDraftFormat(value: unknown): value is DraftFormat {
  return (
    isRecord(value) &&
    typeof value.draft_type === 'string' &&
    typeof value.team_count === 'number' &&
    typeof value.roster_size === 'number' &&
    typeof value.total_roster_slots === 'number' &&
    isDecimalOrNull(value.auction_budget)
  )
}

function isDraftHolding(value: unknown): value is DraftHolding {
  return (
    isRecord(value) &&
    isNumberOrNull(value.player_id) &&
    typeof value.player_label === 'string' &&
    typeof value.player_key === 'string' &&
    isDecimalOrNull(value.price) &&
    typeof value.event_sequence === 'number' &&
    isNumberOrNull(value.overall_pick)
  )
}

function isDraftParticipant(value: unknown): value is DraftParticipant {
  return (
    isRecord(value) &&
    typeof value.id === 'number' &&
    typeof value.team_slot === 'number' &&
    typeof value.display_name === 'string' &&
    typeof value.is_owner === 'boolean' &&
    isNumberOrNull(value.fantasy_team_id) &&
    Array.isArray(value.holdings) &&
    value.holdings.every(isDraftHolding) &&
    typeof value.slots_filled === 'number' &&
    typeof value.slots_remaining === 'number' &&
    isDecimalOrNull(value.spent) &&
    isDecimalOrNull(value.remaining_budget)
  )
}

function isDraftOpenLot(value: unknown): value is DraftOpenLot {
  return (
    isRecord(value) &&
    typeof value.nomination_sequence === 'number' &&
    isNumberOrNull(value.player_id) &&
    typeof value.player_label === 'string' &&
    typeof value.player_key === 'string' &&
    typeof value.nominated_by_participant_id === 'number' &&
    isDecimalOrNull(value.high_bid_amount) &&
    isNumberOrNull(value.high_bid_participant_id) &&
    isNumberOrNull(value.high_bid_sequence)
  )
}

function isDraftNextPick(value: unknown): value is DraftNextPick {
  return (
    isRecord(value) &&
    typeof value.overall_pick === 'number' &&
    typeof value.round_number === 'number' &&
    typeof value.pick_in_round === 'number' &&
    typeof value.team_slot === 'number' &&
    isNumberOrNull(value.participant_id)
  )
}

function isDraftEvent(value: unknown): value is DraftEvent {
  return (
    isRecord(value) &&
    typeof value.sequence === 'number' &&
    typeof value.event_type === 'string' &&
    isNumberOrNull(value.participant_id) &&
    isNumberOrNull(value.player_id) &&
    isStringOrNull(value.player_label) &&
    isDecimalOrNull(value.amount) &&
    isNumberOrNull(value.supersedes_sequence) &&
    isStringOrNull(value.occurred_at) &&
    isStringOrNull(value.note) &&
    isNumberOrNull(value.voided_by_sequence)
  )
}

export function isDraftState(value: unknown): value is DraftState {
  return (
    isRecord(value) &&
    typeof value.id === 'number' &&
    typeof value.league_id === 'number' &&
    typeof value.name === 'string' &&
    typeof value.is_mock === 'boolean' &&
    typeof value.tool_usage === 'string' &&
    isStringOrNull(value.notes) &&
    typeof value.status === 'string' &&
    isDraftFormat(value.format) &&
    (value.league_format_drift === null || isRecord(value.league_format_drift)) &&
    Array.isArray(value.participants) &&
    value.participants.every(isDraftParticipant) &&
    (value.open_lot === null || isDraftOpenLot(value.open_lot)) &&
    (value.next_pick === null || isDraftNextPick(value.next_pick)) &&
    typeof value.selections_made === 'number' &&
    typeof value.total_roster_slots === 'number' &&
    typeof value.last_sequence === 'number' &&
    typeof value.live_event_count === 'number' &&
    Array.isArray(value.voided_sequences) &&
    value.voided_sequences.every((entry) => typeof entry === 'number') &&
    typeof value.unresolved_player_count === 'number'
  )
}

function isDraftSummary(value: unknown): value is DraftSummary {
  return (
    isRecord(value) &&
    typeof value.id === 'number' &&
    typeof value.league_id === 'number' &&
    typeof value.name === 'string' &&
    typeof value.is_mock === 'boolean' &&
    typeof value.tool_usage === 'string' &&
    typeof value.status === 'string' &&
    isDraftFormat(value.format) &&
    typeof value.last_sequence === 'number' &&
    typeof value.selections_made === 'number' &&
    typeof value.created_at === 'string' &&
    typeof value.updated_at === 'string'
  )
}

function isDraftList(value: unknown): value is DraftList {
  return isRecord(value) && Array.isArray(value.drafts) && value.drafts.every(isDraftSummary)
}

function isDraftEventsPage(value: unknown): value is DraftEventsPage {
  return (
    isRecord(value) &&
    typeof value.draft_id === 'number' &&
    Array.isArray(value.events) &&
    value.events.every(isDraftEvent) &&
    typeof value.since_sequence === 'number' &&
    typeof value.last_sequence === 'number'
  )
}

const DRAFT_LIST_CONTRACT = {
  isSuccess: isDraftList,
  invalidResponseDetail: 'The draft list response did not match the expected backend contract.',
} satisfies ResponseContract<DraftList>

const DRAFT_STATE_CONTRACT = {
  isSuccess: isDraftState,
  invalidResponseDetail: 'The draft response did not match the expected backend contract.',
} satisfies ResponseContract<DraftState>

const DRAFT_EVENTS_CONTRACT = {
  isSuccess: isDraftEventsPage,
  invalidResponseDetail: 'The draft log response did not match the expected backend contract.',
} satisfies ResponseContract<DraftEventsPage>

export function getDrafts(options?: RequestOptions): Promise<DraftList> {
  return apiFetch('/api/v1/drafts', DRAFT_LIST_CONTRACT, options)
}

export function getDraft(draftId: number, options?: RequestOptions): Promise<DraftState> {
  return apiFetch(`/api/v1/drafts/${String(draftId)}`, DRAFT_STATE_CONTRACT, options)
}

export function getDraftEvents(
  draftId: number,
  options?: RequestOptions,
): Promise<DraftEventsPage> {
  return apiFetch(`/api/v1/drafts/${String(draftId)}/events`, DRAFT_EVENTS_CONTRACT, options)
}

/**
 * Append one event and receive the whole new state.
 *
 * The full state comes back rather than the created event, which is the
 * backend's decision and the right one: holding an event known to have landed
 * beside a board that predates it would force this screen to either re-poll
 * immediately or reimplement derivation in the browser.
 *
 * **A longer timeout than a read.** The default 8s is tuned for a read that
 * either answers or is a hung backend. A write that times out leaves the
 * recorder genuinely unsure whether the pick landed, which is the worst state
 * this screen can be in mid-auction — so it is given room to answer, and the
 * caller re-reads afterwards regardless.
 */
export function appendDraftEvent(
  draftId: number,
  body: DraftEventRequest,
  options?: RequestOptions,
): Promise<DraftState> {
  return apiFetch(`/api/v1/drafts/${String(draftId)}/events`, DRAFT_STATE_CONTRACT, {
    ...options,
    method: 'POST',
    body,
    timeoutMs: options?.timeoutMs ?? 15000,
  })
}
