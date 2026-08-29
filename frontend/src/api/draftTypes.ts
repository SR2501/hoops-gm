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

/**
 * The four closed vocabularies the draft API publishes, as **runtime arrays**
 * with the types derived from them.
 *
 * Written this way for one reason: a bare `type X = 'a' | 'b'` is erased at
 * build time, so nothing can compare it to anything. `DraftToolUsage` was wrong
 * in **two of its three values** against a 362-test green suite, and the only
 * thing that could have caught it — a comparison against the OpenAPI enum it
 * mirrors — was impossible to write while the union existed only in the type
 * system. `openapiEnums.recorded.test.ts` now performs exactly that comparison
 * against a recorded `openapi.json`, and it can only do so because these are
 * values.
 *
 * `as const` plus `(typeof X)[number]` keeps the type and the array in step by
 * construction, so there is one definition rather than two that can drift.
 */
export const DRAFT_TYPES = ['snake', 'auction', 'linear', 'unknown'] as const

/**
 * `unknown` is on this list and was missing until 2026-08-27.
 *
 * Found by the same sweep that found the `tool_usage` drift, and it is the
 * more consequential of the two: `draftBoardModel.ts` decides whether a board
 * is an auction with `draft_type === 'auction'`, and `LeagueFormatDrift`
 * carries a `DraftType | null` describing what the league row says *now*. A
 * draft recorded under a format the ingest could not classify is exactly the
 * case the backend added `unknown` for, and this build could not name it.
 */
export type DraftType = (typeof DRAFT_TYPES)[number]

export const DRAFT_STATUSES = ['setup', 'in_progress', 'closed'] as const

export type DraftStatus = (typeof DRAFT_STATUSES)[number]

/**
 * Recorded, never inferred: whether this tool was on the recorder's screen.
 *
 * **These are the backend's three values, and this type carried three different
 * ones until 2026-08-27.** It said `'blind' | 'assisted' | 'tool_led'`; the
 * served OpenAPI enum is `blind, partial, instrumented`. Nothing caught it —
 * every committed fixture carries `blind`, the one value both spellings agree
 * on, and `DraftPage` renders the field verbatim inside a `<code>`, so a
 * `partial` draft would have displayed correctly while being unassignable to
 * this type. Found by a `POST /drafts` that was refused with a `422` naming the
 * real enum, which is the only reason it surfaced at all: **the read path
 * cannot see this class of defect**, because a union too narrow on the
 * receiving side is invisible until a value outside it arrives.
 */
export const DRAFT_TOOL_USAGES = ['blind', 'partial', 'instrumented'] as const

export type DraftToolUsage = (typeof DRAFT_TOOL_USAGES)[number]

export const DRAFT_EVENT_TYPES = [
  'pick',
  'nomination',
  'bid',
  'sale',
  'void',
  'closed',
] as const

export type DraftEventType = (typeof DRAFT_EVENT_TYPES)[number]

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
  /**
   * True when this seat's recorded spend has passed the budget the tool
   * *assumed* for it — i.e. when `remaining_budget` is negative.
   *
   * **It is a statement about the tool's assumption, not about the seat.**
   * `format.auction_budget` is one scalar for the whole draft; the backend has
   * no per-seat budget column, and this league sets each seat's bank
   * separately. So a raised flag means "the figure beside this seat is wrong,
   * by `-remaining_budget`", and the sale that revealed it is on the board.
   *
   * Read the flag; do not re-derive it from the sign of `remaining_budget`. It
   * is `false` — not `null` — in a snake draft, where there is no assumption to
   * have passed. That is deliberate: `remaining_budget` already answers "does
   * this draft have a budget", so a second nullable field answering the same
   * question could only ever disagree with the first.
   */
  over_assumed_budget: boolean
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

export const SOURCE_BOARD_STATUSES = ['available', 'refused', 'no_reading'] as const

export type SourceBoardStatus = (typeof SOURCE_BOARD_STATUSES)[number]

/** One player label at the coordinate read from the rendered source board. */
export interface SourceBoardPick {
  source_seat: number
  round_number: number
  pick_in_round: number
  overall_pick: number
  player_label: string | null
  player_external_id: string | null
}

/**
 * One rendered column, not a participant.
 *
 * `mutable_label` is display evidence only. It can change while `source_seat`
 * stays fixed and must never be used to infer participant identity.
 */
export interface SourceBoardColumn {
  source_seat: number
  mutable_label: string | null
  picks: SourceBoardPick[]
}

export interface SourceBoardSnapshot {
  artifact_key: string
  recogniser: string
  observed_at: string
  layout: string
  seat_count: number
  round_count: number
  picks_made: number
  columns: SourceBoardColumn[]
}

/** One coordinate present in an earlier reading and absent from the latest one. */
export interface SourceBoardRegression {
  source_seat: number
  round_number: number
  pick_in_round: number
  player_label: string | null
  last_seen_artifact_key: string
}

/**
 * Rendered-board evidence published separately from authoritative draft state.
 *
 * The contract deliberately contains no participant id, team slot, holding,
 * price, or budget field.
 */
export interface SourceBoardResponse {
  draft_id: number
  as_of: string
  status: SourceBoardStatus
  refusal_reason: string | null
  contact_at: string | null
  contact_age_seconds: number | null
  board: SourceBoardSnapshot | null
  board_age_seconds: number | null
  regressions: SourceBoardRegression[]
  caveats: string[]
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
