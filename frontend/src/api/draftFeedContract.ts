import type {
  FeedDisagreement,
  FeedFreshness,
  FeedIndependence,
  FeedMatch,
  FeedReconciliation,
  FeedStatusResponse,
  ParticipantFeedSkips,
  SourceBoardRegression,
} from './draftTypes'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value)
  return actual.length === keys.length && keys.every((key) => Object.hasOwn(value, key))
}

function isStringOrNull(value: unknown): value is string | null {
  return typeof value === 'string' || value === null
}

function isNumberOrNull(value: unknown): value is number | null {
  return typeof value === 'number' || value === null
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === 'string')
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function isPositiveInteger(value: unknown): value is number {
  return isNonNegativeInteger(value) && value > 0
}

function isCountMap(value: unknown): value is Record<string, number> {
  return isRecord(value) && Object.values(value).every(isNonNegativeInteger)
}

const FRESHNESS_KEYS = [
  'transport',
  'last_seen_at',
  'age_seconds',
  'instant_count',
  'silent',
  'silence_threshold_seconds',
  'source_claimed_at',
  'claim_skew_seconds',
  'contact_at',
  'contact_age_seconds',
  'contact_is_known',
] as const

function isFeedFreshness(value: unknown): value is FeedFreshness {
  return (
    isRecord(value) &&
    hasExactKeys(value, FRESHNESS_KEYS) &&
    typeof value.transport === 'string' &&
    isStringOrNull(value.last_seen_at) &&
    isNumberOrNull(value.age_seconds) &&
    isNonNegativeInteger(value.instant_count) &&
    typeof value.silent === 'boolean' &&
    typeof value.silence_threshold_seconds === 'number' &&
    isStringOrNull(value.source_claimed_at) &&
    isNumberOrNull(value.claim_skew_seconds) &&
    isStringOrNull(value.contact_at) &&
    isNumberOrNull(value.contact_age_seconds) &&
    typeof value.contact_is_known === 'boolean'
  )
}

const INDEPENDENCE_KEYS = [
  'independent',
  'reason',
  'left_transports',
  'right_transports',
  'shared_artifacts',
  'shared_transports',
] as const

function isFeedIndependence(value: unknown): value is FeedIndependence {
  return (
    isRecord(value) &&
    hasExactKeys(value, INDEPENDENCE_KEYS) &&
    typeof value.independent === 'boolean' &&
    typeof value.reason === 'string' &&
    isStringArray(value.left_transports) &&
    isStringArray(value.right_transports) &&
    isStringArray(value.shared_artifacts) &&
    isStringArray(value.shared_transports)
  )
}

const MATCH_KEYS = ['player_label', 'key', 'bridge_artifact', 'official_artifact'] as const

function isFeedMatch(value: unknown): value is FeedMatch {
  return (
    isRecord(value) &&
    hasExactKeys(value, MATCH_KEYS) &&
    isStringOrNull(value.player_label) &&
    typeof value.key === 'string' &&
    typeof value.bridge_artifact === 'string' &&
    typeof value.official_artifact === 'string'
  )
}

const DISAGREEMENT_KEYS = [
  'player_label',
  'field_name',
  'bridge_value',
  'official_value',
  'bridge_artifact',
  'official_artifact',
] as const

function isFeedDisagreement(value: unknown): value is FeedDisagreement {
  return (
    isRecord(value) &&
    hasExactKeys(value, DISAGREEMENT_KEYS) &&
    isStringOrNull(value.player_label) &&
    typeof value.field_name === 'string' &&
    isStringOrNull(value.bridge_value) &&
    isStringOrNull(value.official_value) &&
    typeof value.bridge_artifact === 'string' &&
    typeof value.official_artifact === 'string'
  )
}

const RECONCILIATION_KEYS = [
  'independence',
  'witnessed_by_two_transports',
  'agreements',
  'unwitnessed_matches',
  'disagreements',
  'only_bridge',
  'only_official',
  'caveats',
] as const

function isFeedReconciliation(value: unknown): value is FeedReconciliation {
  return (
    isRecord(value) &&
    hasExactKeys(value, RECONCILIATION_KEYS) &&
    isFeedIndependence(value.independence) &&
    isNonNegativeInteger(value.witnessed_by_two_transports) &&
    Array.isArray(value.agreements) &&
    value.agreements.every(isFeedMatch) &&
    Array.isArray(value.unwitnessed_matches) &&
    value.unwitnessed_matches.every(isFeedMatch) &&
    Array.isArray(value.disagreements) &&
    value.disagreements.every(isFeedDisagreement) &&
    isStringArray(value.only_bridge) &&
    isStringArray(value.only_official) &&
    isStringArray(value.caveats)
  )
}

const PARTICIPANT_SKIPS_KEYS = ['participant_id', 'team_slot', 'total', 'reasons'] as const

function isParticipantFeedSkips(value: unknown): value is ParticipantFeedSkips {
  return (
    isRecord(value) &&
    hasExactKeys(value, PARTICIPANT_SKIPS_KEYS) &&
    isPositiveInteger(value.participant_id) &&
    isPositiveInteger(value.team_slot) &&
    isNonNegativeInteger(value.total) &&
    isCountMap(value.reasons) &&
    Object.values(value.reasons).reduce((total, count) => total + count, 0) === value.total
  )
}

const BOARD_REGRESSION_KEYS = [
  'source_seat',
  'round_number',
  'pick_in_round',
  'player_label',
  'last_seen_artifact_key',
] as const

function isBoardRegression(value: unknown): value is SourceBoardRegression {
  return (
    isRecord(value) &&
    hasExactKeys(value, BOARD_REGRESSION_KEYS) &&
    isPositiveInteger(value.source_seat) &&
    isPositiveInteger(value.round_number) &&
    isPositiveInteger(value.pick_in_round) &&
    isStringOrNull(value.player_label) &&
    typeof value.last_seen_artifact_key === 'string'
  )
}

const STATUS_KEYS = [
  'draft_id',
  'as_of',
  'context_unavailable',
  'freshness',
  'reconciliation',
  'observation_count',
  'applied_count',
  'pending_count',
  'blocked',
  'retryable',
  'skipped',
  'skipped_by_participant',
  'unattributed_skipped',
  'last_sequence',
  'board_regressions',
] as const

function addCounts(target: Record<string, number>, source: Record<string, number>): void {
  for (const [reason, count] of Object.entries(source)) {
    target[reason] = (target[reason] ?? 0) + count
  }
}

function countMapsEqual(left: Record<string, number>, right: Record<string, number>): boolean {
  const leftKeys = Object.keys(left).sort()
  const rightKeys = Object.keys(right).sort()
  return (
    leftKeys.length === rightKeys.length &&
    leftKeys.every((key, index) => key === rightKeys[index] && left[key] === right[key])
  )
}

export function isFeedStatusResponse(value: unknown): value is FeedStatusResponse {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, STATUS_KEYS) ||
    !isPositiveInteger(value.draft_id) ||
    typeof value.as_of !== 'string' ||
    !isStringOrNull(value.context_unavailable) ||
    !Array.isArray(value.freshness) ||
    !value.freshness.every(isFeedFreshness) ||
    !(value.reconciliation === null || isFeedReconciliation(value.reconciliation)) ||
    !isNonNegativeInteger(value.observation_count) ||
    !isNonNegativeInteger(value.applied_count) ||
    !isNonNegativeInteger(value.pending_count) ||
    !isStringArray(value.blocked) ||
    !isCountMap(value.retryable) ||
    !isCountMap(value.skipped) ||
    !Array.isArray(value.skipped_by_participant) ||
    !value.skipped_by_participant.every(isParticipantFeedSkips) ||
    !isCountMap(value.unattributed_skipped) ||
    !isNonNegativeInteger(value.last_sequence) ||
    !Array.isArray(value.board_regressions) ||
    !value.board_regressions.every(isBoardRegression)
  ) {
    return false
  }

  const participantIds = value.skipped_by_participant.map((entry) => entry.participant_id)
  if (new Set(participantIds).size !== participantIds.length) return false

  const partitioned: Record<string, number> = {}
  for (const entry of value.skipped_by_participant) addCounts(partitioned, entry.reasons)
  addCounts(partitioned, value.unattributed_skipped)
  return countMapsEqual(partitioned, value.skipped)
}
