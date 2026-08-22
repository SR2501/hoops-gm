/**
 * The draft tracker's payload shapes, transcribed from the OpenAPI document.
 *
 * **Money arrives as a string, and stays one.** Every `Decimal` in
 * `api/routes/drafts.py` serialises as a JSON string — `"200.00"`, not `200`.
 * That is not an inconvenience to normalise away: an auction budget is exact
 * decimal arithmetic, and the moment a price becomes a JavaScript number the
 * screen has silently opted into binary floating point for the one quantity in
 * this application where a cent of drift is a wrong answer. So prices are
 * carried as strings, compared as strings where equality is the question, and
 * parsed only at the point a comparison genuinely needs ordering.
 *
 * **No field here carries a decision number, and that is checkable rather than
 * asserted.** The backend publishes no ranking, valuation, auction price,
 * inflation figure or `p(play)` — a reviewer walked all 26 models and 67 fields
 * against a list of 30 forbidden terms. These interfaces are a transcription of
 * that document, so any decision number appearing on this screen would have to
 * be invented here. `draftBoardModel.ts` is where that would happen and it is
 * where the guard against it lives.
 */

/** Money, exactly as the backend serialised it. Never a `number`. */
export type DecimalString = string

export type DraftType = 'snake' | 'auction' | 'linear'

export type DraftStatus = 'setup' | 'in_progress' | 'closed'

export type DraftToolUsage = 'blind' | 'assisted' | 'tool_led'

export type DraftEventType = 'pick' | 'nomination' | 'bid' | 'sale' | 'void' | 'closed'

/** The configuration a draft was recorded under, frozen at creation. */
export interface DraftFormat {
  draft_type: DraftType
  team_count: number
  roster_size: number
  total_roster_slots: number
  auction_budget: DecimalString | null
}

/**
 * What the league row says now, when it disagrees with the frozen snapshot.
 *
 * `null` on the response means the two agree. Published rather than resolved,
 * so a screen can say the prices were paid under a different configuration
 * instead of relabelling them.
 */
export interface LeagueFormatDrift {
  draft_type: DraftType | null
  team_count: number | null
  roster_size: number | null
  auction_budget: DecimalString | null
  error: string | null
}

/** A player one seat holds, and the single log entry that put them there. */
export interface DraftHolding {
  player_id: number | null
  player_label: string
  player_key: string
  price: DecimalString | null
  event_sequence: number
  overall_pick: number | null
}

export interface DraftParticipant {
  id: number
  team_slot: number
  display_name: string
  is_owner: boolean
  fantasy_team_id: number | null
  holdings: DraftHolding[]
  slots_filled: number
  slots_remaining: number
  spent: DecimalString | null
  /**
   * `budget - spent`. **An identity over recorded sales, not a spending limit.**
   *
   * A seat holding a live $150 high bid still reports its full remaining
   * budget, because no sale has been recorded. The screen must not let this
   * read as money available to spend; `open_lot.high_bid_participant_id` names
   * the seat where that is currently false.
   */
  remaining_budget: DecimalString | null
}

export interface DraftOpenLot {
  nomination_sequence: number
  player_id: number | null
  player_label: string
  player_key: string
  nominated_by_participant_id: number
  high_bid_amount: DecimalString | null
  high_bid_participant_id: number | null
  high_bid_sequence: number | null
}

export interface DraftNextPick {
  overall_pick: number
  round_number: number
  pick_in_round: number
  team_slot: number
  participant_id: number | null
}

/** One log entry, as recorded. */
export interface DraftEvent {
  sequence: number
  event_type: DraftEventType
  participant_id: number | null
  player_id: number | null
  player_label: string | null
  amount: DecimalString | null
  supersedes_sequence: number | null
  /**
   * The recorder's claim about wall-clock time.
   *
   * **Never sort on this.** `sequence` is the ordering, and the backend says so
   * in the field's own docstring. A self-describing timestamp is exactly the
   * kind of field this project has been burned by before (AGENTS.md: `gameEt`
   * carries a `Z` and is Eastern), and an ordering a client's clock can permute
   * is not one.
   */
  occurred_at: string | null
  note: string | null
  voided_by_sequence: number | null
}

export interface DraftSummary {
  id: number
  league_id: number
  name: string
  is_mock: boolean
  tool_usage: DraftToolUsage
  status: DraftStatus
  format: DraftFormat
  last_sequence: number
  selections_made: number
  created_at: string
  updated_at: string
}

export interface DraftList {
  drafts: DraftSummary[]
}

/** Everything a draft screen needs, derived from the log on this request. */
export interface DraftState {
  id: number
  league_id: number
  name: string
  is_mock: boolean
  tool_usage: DraftToolUsage
  notes: string | null
  status: DraftStatus
  format: DraftFormat
  league_format_drift: LeagueFormatDrift | null
  participants: DraftParticipant[]
  open_lot: DraftOpenLot | null
  next_pick: DraftNextPick | null
  selections_made: number
  total_roster_slots: number
  /**
   * The version token. Two responses carrying the same value describe the same
   * log, because append is the log's only mutation — so a poll compares one
   * integer instead of diffing the payload.
   */
  last_sequence: number
  live_event_count: number
  voided_sequences: number[]
  unresolved_player_count: number
}

export interface DraftEventsPage {
  draft_id: number
  events: DraftEvent[]
  since_sequence: number
  /** The end of the *whole* log, not of this page. */
  last_sequence: number
}

/**
 * The fields every append shares.
 *
 * `expected_last_sequence` makes the append conditional on the log not having
 * moved. This screen supplies it on every write: there is one recorder, but
 * there is also a poll running, and a double-submitted pick under an auction
 * clock is the exact failure it prevents.
 */
interface DraftEventRequestBase {
  occurred_at?: string
  note?: string
  expected_last_sequence?: number
}

export interface PickRequest extends DraftEventRequestBase {
  event_type: 'pick'
  participant_id: number
  player_label: string
  player_id?: number
}

export interface NominationRequest extends DraftEventRequestBase {
  event_type: 'nomination'
  participant_id: number
  player_label: string
  player_id?: number
  amount?: DecimalString
}

/** Carries no player: the open lot names it, so a bid cannot disagree with it. */
export interface BidRequest extends DraftEventRequestBase {
  event_type: 'bid'
  participant_id: number
  amount: DecimalString
}

export interface SaleRequest extends DraftEventRequestBase {
  event_type: 'sale'
  participant_id: number
  amount: DecimalString
  player_label?: string
  player_id?: number
}

export interface VoidRequest extends DraftEventRequestBase {
  event_type: 'void'
  supersedes_sequence: number
}

export interface CloseRequest extends DraftEventRequestBase {
  event_type: 'closed'
}

export type DraftEventRequest =
  | PickRequest
  | NominationRequest
  | BidRequest
  | SaleRequest
  | VoidRequest
  | CloseRequest
