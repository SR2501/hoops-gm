import { ApiError } from './client'
import type { ErrorDescription } from '../components/AsyncBoundary'

const RELIABILITY_ERRORS: Record<string, Required<ErrorDescription>> = {
  reliability_local_only: {
    summary: 'Reliability evidence is served only to the machine running the backend.',
    action: 'Open this dashboard on that machine through 127.0.0.1.',
  },
  reliability_not_published: {
    summary:
      'Reliability evidence has not been published for this store, so there are no scorecards to show.',
    action:
      'Run `python -m hoops_gm.dev.publish_reliability_evidence` against this store, then retry.',
  },
  reliability_incomplete_evidence: {
    summary:
      'The published reliability claim is incomplete or malformed, so the backend refused to serve it.',
    action:
      'Read the backend wording below, repair the named publication evidence, and publish it again.',
  },
  reliability_not_current: {
    summary:
      'The published reliability cohort no longer matches the persisted evidence. Previously loaded scorecards must be treated as stale.',
    action: 'Publish reliability evidence again before using these observations.',
  },
  reliability_inputs_refused: {
    summary:
      'The underlying schedule, game logs, or participation rows cannot form a coherent reliability cohort.',
    action:
      'Read the backend wording below and repair the named input conflict; publishing again alone will not fix it.',
  },
  unreachable: {
    summary: 'The backend did not answer, so no reliability evidence was received.',
    action: 'Start the backend on 127.0.0.1:8000, then retry.',
  },
  timeout: {
    summary: 'The reliability computation did not finish before the request timed out.',
    action: 'Retry once. If it repeats, inspect the backend log for the scorecard request.',
  },
  invalid_response: {
    summary:
      'The backend answered, but the body did not match the reliability scorecards contract, so no evidence is rendered from it.',
    action: 'Check that the backend and dashboard are running the same revision.',
  },
}

export function describeReliabilityError(error: Error): ErrorDescription {
  if (!(error instanceof ApiError)) {
    return {
      summary: error.message,
      action: 'Retry. If it recurs, inspect the browser console and backend log.',
    }
  }
  const copy = Object.hasOwn(RELIABILITY_ERRORS, error.code)
    ? RELIABILITY_ERRORS[error.code]
    : undefined
  return (
    copy ?? {
      summary: `The backend refused reliability evidence with HTTP ${String(error.status)} for an unrecognised reason.`,
      action: 'Quote the code and request id below when reporting it.',
    }
  )
}
