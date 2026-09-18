import type { ErrorDescription } from '../components/AsyncBoundary'
import { ApiError } from './client'

export const RETRYABLE_PRODUCTION_CANDIDATES_ERROR =
  'production_candidates_inconsistent_snapshot'

export function isRetryableProductionCandidatesError(error: Error): boolean {
  return (
    error instanceof ApiError &&
    error.code === RETRYABLE_PRODUCTION_CANDIDATES_ERROR
  )
}

const PRODUCTION_CANDIDATES_ERRORS: Record<string, Required<ErrorDescription>> = {
  production_candidates_local_only: {
    summary:
      'Production candidates are served only to the machine running the backend.',
    action: 'Open this dashboard through 127.0.0.1 on that machine.',
  },
  production_candidates_draft_not_found: {
    summary: 'This database holds no recorded draft with that id.',
    action: 'Return to the recorded drafts list and open an existing draft.',
  },
  production_candidates_source_unsupported: {
    summary:
      'The requested source is not one of the projection namespaces this endpoint supports.',
    action:
      'Choose one of the five supported sources in the selector. This does not assert that an import currently exists for it.',
  },
  production_candidates_source_not_imported: {
    summary:
      'The selected source has no admitted projection import for this recorded draft’s league and season.',
    action:
      'Choose another supported source or admit the intended source import. The selector lists supported namespaces, not available imports.',
  },
  production_candidates_draft_state_refused: {
    summary:
      'The recorded draft cannot currently form a coherent read-only candidate scope.',
    action:
      'Read the backend wording below and repair the named draft-state conflict before using this ranking.',
  },
  production_candidates_draft_identity_incomplete: {
    summary:
      'At least one recorded holding lacks a resolved player identity, so drafted-player eligibility cannot be established safely.',
    action:
      'Resolve the holding named by the backend. The browser will not guess identity from a player label.',
  },
  production_candidates_league_structure_mismatch: {
    summary:
      'The persisted league team or roster structure no longer matches the structure frozen on this recorded draft.',
    action:
      'Use a draft recorded under the current structure or repair the underlying league evidence. Budget differences are not part of this check.',
  },
  production_candidates_scoring_profile_unavailable: {
    summary:
      'No active scoring-profile release can support this production-only ranking.',
    action:
      'Publish or repair the scoring profile named by the backend, then refresh.',
  },
  production_candidates_incomplete_production: {
    summary:
      'The selected projection cohort cannot supply every required scoring input for every player, so the backend served no partial ranking.',
    action:
      'Repair or replace the source import. The browser will not drop incomplete players or renormalize fewer than nine categories.',
  },
  production_candidates_input_evidence_refused: {
    summary:
      'One of the source, blend, scoring, or historical-observation evidence blocks failed its production check.',
    action:
      'Read the backend wording below and repair the named evidence. No subset is treated as a successful response.',
  },
  [RETRYABLE_PRODUCTION_CANDIDATES_ERROR]: {
    summary:
      'The draft, projection release, scoring profile, or historical snapshot moved while this response was being composed, so the backend refused a mixed snapshot.',
    action:
      'This screen retried once automatically. If it still failed, let the concurrent update finish and refresh; any retained rows are the last whole response for this exact draft and source.',
  },
  validation_error: {
    summary:
      'The backend rejected the request shape before attempting to produce candidates.',
    action:
      'Return to the draft page and reopen this view. If it recurs, report the code and request id below.',
  },
  unreachable: {
    summary: 'The backend did not answer, so no production-candidate response arrived.',
    action: 'Start the intended local backend and refresh this view.',
  },
  timeout: {
    summary: 'The backend did not finish the production-candidate read before timeout.',
    action:
      'Refresh once. If it repeats, inspect the backend request log rather than treating the previous rows as current.',
  },
  invalid_response: {
    summary:
      'The backend answered, but the body did not match the production-candidates contract for this draft and selected source.',
    action:
      'Check that the backend and frontend are running the same revision. The mismatched body is not rendered.',
  },
}

export function describeProductionCandidatesError(error: Error): ErrorDescription {
  if (!(error instanceof ApiError)) {
    return {
      summary: error.message,
      action: 'Refresh. If it recurs, inspect the browser console and backend log.',
    }
  }

  const copy = Object.hasOwn(PRODUCTION_CANDIDATES_ERRORS, error.code)
    ? PRODUCTION_CANDIDATES_ERRORS[error.code]
    : undefined

  return (
    copy ?? {
      summary: error.message,
      action: `This dashboard has no specific guidance for code ${error.code}. The backend wording is shown unaltered; quote it with the request id.`,
    }
  )
}
