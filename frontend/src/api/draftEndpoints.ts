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
import { isFeedStatusResponse } from './draftFeedContract'
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
  DraftSetupLeague,
  DraftSetupResponse,
  DraftState,
  DraftSummary,
  FeedStatusResponse,
  CreateDraftRequest,
  SourceBoardColumn,
  SourceBoardPick,
  SourceBoardRegression,
  SourceBoardResponse,
  SourceBoardSnapshot,
} from './draftTypes'
import { DRAFT_SOURCE_BOARD_PROFILES, SOURCE_BOARD_STATUSES } from './draftTypes'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort()
  const sortedExpected = [...expected].sort()
  return (
    actual.length === sortedExpected.length &&
    actual.every((key, index) => key === sortedExpected[index])
  )
}

function isPositiveDecimalString(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value) &&
    /[1-9]/.test(value)
  )
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
}

/** A money field: a string, or `null` where the concept does not apply. */
function isDecimalOrNull(value: unknown): value is string | null {
  return typeof value === 'string' || value === null
}

function isNumberOrNull(value: unknown): value is number | null {
  return typeof value === 'number' || value === null
}

function isPositiveIntegerOrNull(value: unknown): value is number | null {
  return value === null || (typeof value === 'number' && Number.isInteger(value) && value > 0)
}

function isStringOrNull(value: unknown): value is string | null {
  return typeof value === 'string' || value === null
}

function isDraftSourceBoardProfileOrNull(value: unknown): boolean {
  return (
    value === null ||
    DRAFT_SOURCE_BOARD_PROFILES.some((profile) => profile === value)
  )
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
    isPositiveIntegerOrNull(value.source_seat) &&
    typeof value.display_name === 'string' &&
    typeof value.is_owner === 'boolean' &&
    isNumberOrNull(value.fantasy_team_id) &&
    Array.isArray(value.holdings) &&
    value.holdings.every(isDraftHolding) &&
    typeof value.slots_filled === 'number' &&
    typeof value.slots_remaining === 'number' &&
    isDecimalOrNull(value.spent) &&
    isDecimalOrNull(value.remaining_budget) &&
    typeof value.over_assumed_budget === 'boolean'
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
    isDraftSourceBoardProfileOrNull(value.source_board_profile) &&
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
    isDraftSourceBoardProfileOrNull(value.source_board_profile) &&
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

const DRAFT_SETUP_TEAM_KEYS = ['fantasy_team_id', 'display_name'] as const
const DRAFT_SETUP_FORMAT_KEYS = [
  'draft_type',
  'team_count',
  'roster_size',
  'total_roster_slots',
  'auction_budget',
] as const
const DRAFT_SETUP_LEAGUE_KEYS = [
  'league_id',
  'name',
  'season',
  'format',
  'owner_fantasy_team_id',
  'fantasy_teams',
] as const

function isDraftSetupTeam(value: unknown): value is DraftSetupLeague['fantasy_teams'][number] {
  return (
    isRecord(value) &&
    hasExactKeys(value, DRAFT_SETUP_TEAM_KEYS) &&
    isPositiveInteger(value.fantasy_team_id) &&
    typeof value.display_name === 'string' &&
    value.display_name.trim().length > 0
  )
}

function isDraftSetupFormat(value: unknown): value is DraftSetupLeague['format'] {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, DRAFT_SETUP_FORMAT_KEYS) ||
    !['auction', 'snake', 'linear'].some((draftType) => draftType === value.draft_type) ||
    !isPositiveInteger(value.team_count) ||
    !isPositiveInteger(value.roster_size) ||
    value.total_roster_slots !== value.team_count * value.roster_size
  ) {
    return false
  }

  return value.draft_type === 'auction'
    ? isPositiveDecimalString(value.auction_budget)
    : value.auction_budget === null
}

function isDraftSetupLeague(value: unknown): value is DraftSetupLeague {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, DRAFT_SETUP_LEAGUE_KEYS) ||
    !isPositiveInteger(value.league_id) ||
    typeof value.name !== 'string' ||
    value.name.trim().length === 0 ||
    typeof value.season !== 'string' ||
    value.season.trim().length === 0 ||
    !isDraftSetupFormat(value.format) ||
    !Array.isArray(value.fantasy_teams) ||
    !value.fantasy_teams.every(isDraftSetupTeam) ||
    value.fantasy_teams.length !== value.format.team_count
  ) {
    return false
  }

  const teamIds = value.fantasy_teams.map((team) => team.fantasy_team_id)
  if (new Set(teamIds).size !== teamIds.length) return false
  const teamLabels = value.fantasy_teams.map((team) =>
    team.display_name.trim().replace(/\s+/g, ' '),
  )
  if (new Set(teamLabels).size !== teamLabels.length) return false

  if (
    value.owner_fantasy_team_id !== null &&
    !teamIds.some((teamId) => teamId === value.owner_fantasy_team_id)
  ) {
    return false
  }
  const ownerOptionLabels = value.fantasy_teams.map(
    (team) =>
      `${team.display_name.trim().replace(/\s+/g, ' ')}${
        team.fantasy_team_id === value.owner_fantasy_team_id ? ' (persisted owner)' : ''
      }`,
  )
  return new Set(ownerOptionLabels).size === ownerOptionLabels.length
}

export function isDraftSetupResponse(value: unknown): value is DraftSetupResponse {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['leagues']) ||
    !Array.isArray(value.leagues) ||
    !value.leagues.every(isDraftSetupLeague)
  ) {
    return false
  }

  const leagueIds = value.leagues.map((league) => league.league_id)
  if (new Set(leagueIds).size !== leagueIds.length) return false
  const leagueLabels = value.leagues.map(
    (league) =>
      `${league.name.trim().replace(/\s+/g, ' ')} (${league.season.trim().replace(/\s+/g, ' ')})`,
  )
  return new Set(leagueLabels).size === leagueLabels.length
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

function isSourceBoardPick(value: unknown): value is SourceBoardPick {
  return (
    isRecord(value) &&
    typeof value.source_seat === 'number' &&
    typeof value.round_number === 'number' &&
    typeof value.pick_in_round === 'number' &&
    typeof value.overall_pick === 'number' &&
    isStringOrNull(value.player_label) &&
    isStringOrNull(value.player_external_id)
  )
}

function isSourceBoardColumn(value: unknown): value is SourceBoardColumn {
  return (
    isRecord(value) &&
    typeof value.source_seat === 'number' &&
    isStringOrNull(value.mutable_label) &&
    Array.isArray(value.picks) &&
    value.picks.every(isSourceBoardPick)
  )
}

function isSourceBoardSnapshot(value: unknown): value is SourceBoardSnapshot {
  return (
    isRecord(value) &&
    typeof value.artifact_key === 'string' &&
    typeof value.recogniser === 'string' &&
    typeof value.observed_at === 'string' &&
    typeof value.layout === 'string' &&
    typeof value.seat_count === 'number' &&
    typeof value.round_count === 'number' &&
    typeof value.picks_made === 'number' &&
    Array.isArray(value.columns) &&
    value.columns.every(isSourceBoardColumn)
  )
}

function isSourceBoardRegression(value: unknown): value is SourceBoardRegression {
  return (
    isRecord(value) &&
    typeof value.source_seat === 'number' &&
    typeof value.round_number === 'number' &&
    typeof value.pick_in_round === 'number' &&
    isStringOrNull(value.player_label) &&
    typeof value.last_seen_artifact_key === 'string'
  )
}

export function isSourceBoardResponse(value: unknown): value is SourceBoardResponse {
  const hasShape =
    isRecord(value) &&
    typeof value.draft_id === 'number' &&
    typeof value.as_of === 'string' &&
    typeof value.status === 'string' &&
    SOURCE_BOARD_STATUSES.some((status) => status === value.status) &&
    isStringOrNull(value.refusal_reason) &&
    isStringOrNull(value.contact_at) &&
    isNumberOrNull(value.contact_age_seconds) &&
    (value.board === null || isSourceBoardSnapshot(value.board)) &&
    isNumberOrNull(value.board_age_seconds) &&
    Array.isArray(value.regressions) &&
    value.regressions.every(isSourceBoardRegression) &&
    Array.isArray(value.caveats) &&
    value.caveats.every((caveat) => typeof caveat === 'string')
  if (!hasShape) return false

  if (value.status === 'no_reading') {
    return (
      value.refusal_reason === null &&
      value.contact_at === null &&
      value.contact_age_seconds === null &&
      value.board === null &&
      value.board_age_seconds === null
    )
  }

  const hasContact = value.contact_at !== null && value.contact_age_seconds !== null
  const boardAndAgeAgree =
    (value.board === null && value.board_age_seconds === null) ||
    (value.board !== null && value.board_age_seconds !== null)
  if (!hasContact || !boardAndAgeAgree) return false

  return value.status === 'available'
    ? value.refusal_reason === null && value.board !== null
    : value.refusal_reason !== null
}

const DRAFT_LIST_CONTRACT = {
  isSuccess: isDraftList,
  invalidResponseDetail: 'The draft list response did not match the expected backend contract.',
} satisfies ResponseContract<DraftList>

const DRAFT_SETUP_CONTRACT = {
  isSuccess: isDraftSetupResponse,
  invalidResponseDetail: 'The draft setup response did not match the expected backend contract.',
} satisfies ResponseContract<DraftSetupResponse>

const DRAFT_STATE_CONTRACT = {
  isSuccess: isDraftState,
  invalidResponseDetail: 'The draft response did not match the expected backend contract.',
} satisfies ResponseContract<DraftState>

const CREATED_DRAFT_STATE_CONTRACT = {
  isSuccess: (value: unknown): value is DraftState =>
    isDraftState(value) && isPositiveInteger(value.id),
  invalidResponseDetail: 'The created draft response did not match the expected backend contract.',
} satisfies ResponseContract<DraftState>

const DRAFT_EVENTS_CONTRACT = {
  isSuccess: isDraftEventsPage,
  invalidResponseDetail: 'The draft log response did not match the expected backend contract.',
} satisfies ResponseContract<DraftEventsPage>

const SOURCE_BOARD_CONTRACT = {
  isSuccess: isSourceBoardResponse,
  invalidResponseDetail:
    'The source-board response did not match the expected backend contract.',
} satisfies ResponseContract<SourceBoardResponse>

const FEED_STATUS_CONTRACT = {
  isSuccess: isFeedStatusResponse,
  invalidResponseDetail: 'The draft feed response did not match the expected backend contract.',
} satisfies ResponseContract<FeedStatusResponse>

export function getDrafts(options?: RequestOptions): Promise<DraftList> {
  return apiFetch('/api/v1/drafts', DRAFT_LIST_CONTRACT, options)
}

export function getDraftSetup(options?: RequestOptions): Promise<DraftSetupResponse> {
  return apiFetch('/api/v1/drafts/setup', DRAFT_SETUP_CONTRACT, options)
}

export function createDraft(
  body: CreateDraftRequest,
  options?: RequestOptions,
): Promise<DraftState> {
  return apiFetch('/api/v1/drafts', CREATED_DRAFT_STATE_CONTRACT, {
    ...options,
    method: 'POST',
    body,
    timeoutMs: options?.timeoutMs ?? 15000,
  })
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

export function getSourceBoard(
  draftId: number,
  options?: RequestOptions,
): Promise<SourceBoardResponse> {
  return apiFetch(
    `/api/v1/drafts/${String(draftId)}/source-board`,
    SOURCE_BOARD_CONTRACT,
    options,
  )
}

export function getDraftFeed(
  draftId: number,
  options?: RequestOptions,
): Promise<FeedStatusResponse> {
  return apiFetch(`/api/v1/drafts/${String(draftId)}/feed`, FEED_STATUS_CONTRACT, options)
}

export { isFeedStatusResponse }

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
