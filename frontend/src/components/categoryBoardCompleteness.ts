import type {
  DraftState,
  FeedStatusResponse,
  ParticipantFeedSkips,
} from '../api/draftTypes'

export type CategoryBoardCompleteness =
  | {
      kind: 'available'
      byParticipantId: ReadonlyMap<number, ParticipantFeedSkips>
      observationCount: number
      participantSkippedTotal: number
      unattributedSkipped: Record<string, number>
      unattributedSkippedTotal: number
      totalSkipped: number
    }
  | {
      kind: 'context-unavailable'
      detail: string
    }
  | {
      kind: 'mismatch'
      detail: string
    }

function countTotal(counts: Record<string, number>): number {
  return Object.values(counts).reduce((total, count) => total + count, 0)
}

/**
 * Bind feed diagnostics to the exact draft-log version they describe.
 *
 * A single mismatch refuses the whole assignment. Mixing trusted rows with
 * suspect rows would leave the suspect seats looking complete because their
 * missing count happened to render as zero.
 */
export function reconcileCategoryBoardCompleteness(
  state: DraftState,
  feed: FeedStatusResponse,
): CategoryBoardCompleteness {
  if (feed.context_unavailable !== null) {
    return { kind: 'context-unavailable', detail: feed.context_unavailable }
  }
  if (feed.draft_id !== state.id) {
    return {
      kind: 'mismatch',
      detail: `feed draft ${String(feed.draft_id)} does not match draft ${String(state.id)}`,
    }
  }
  if (feed.last_sequence !== state.last_sequence) {
    return {
      kind: 'mismatch',
      detail: `feed log sequence ${String(feed.last_sequence)} does not match draft sequence ${String(state.last_sequence)}`,
    }
  }

  const participants = new Map(state.participants.map((participant) => [participant.id, participant]))
  if (participants.size !== state.participants.length) {
    return { kind: 'mismatch', detail: 'the draft repeats a participant id' }
  }

  const byParticipantId = new Map<number, ParticipantFeedSkips>()
  for (const diagnostic of feed.skipped_by_participant) {
    const participant = participants.get(diagnostic.participant_id)
    if (participant === undefined) {
      return {
        kind: 'mismatch',
        detail: `feed diagnostics name unknown participant ${String(diagnostic.participant_id)}`,
      }
    }
    if (diagnostic.team_slot !== participant.team_slot) {
      return {
        kind: 'mismatch',
        detail: `participant ${String(participant.id)} is seat ${String(participant.team_slot)} in the draft but seat ${String(diagnostic.team_slot)} in feed diagnostics`,
      }
    }
    if (byParticipantId.has(diagnostic.participant_id)) {
      return {
        kind: 'mismatch',
        detail: `feed diagnostics repeat participant ${String(diagnostic.participant_id)}`,
      }
    }
    byParticipantId.set(diagnostic.participant_id, diagnostic)
  }

  const missing = state.participants.find(
    (participant) => !byParticipantId.has(participant.id),
  )
  if (missing !== undefined) {
    return {
      kind: 'mismatch',
      detail: `feed diagnostics omit participant ${String(missing.id)} at seat ${String(missing.team_slot)}`,
    }
  }

  const participantSkippedTotal = [...byParticipantId.values()].reduce(
    (total, entry) => total + entry.total,
    0,
  )
  const unattributedSkippedTotal = countTotal(feed.unattributed_skipped)

  return {
    kind: 'available',
    byParticipantId,
    observationCount: feed.observation_count,
    participantSkippedTotal,
    unattributedSkipped: feed.unattributed_skipped,
    unattributedSkippedTotal,
    totalSkipped: participantSkippedTotal + unattributedSkippedTotal,
  }
}
