/**
 * What each schedule-grid refusal actually means, and what to do about it.
 *
 * The backend fails closed on five distinct conditions, and collapsing them
 * into "something went wrong" would throw that work away. "The schedule
 * evidence could not be verified" and "there is no such league" call for
 * completely different actions from the person reading the screen, so each code
 * gets its own summary and its own next step.
 *
 * **The code arrives in the response body, not in a header.** `X-Bridge-Error`
 * is an internal route-to-handler transport inside the backend; the exception
 * handler in `app.py` builds a fresh response carrying only `X-Request-ID`, so
 * reading `X-Bridge-Error` from the browser returns null on every refusal.
 * `client.ts` already parses `{error, detail, request_id}` off the body into
 * `ApiError.code`, and that is the value keyed here.
 *
 * One module rather than two so the message shown in the error panel and the
 * message shown in the stale banner cannot drift apart.
 */

import { ApiError } from './client'

export interface ScheduleGridErrorCopy {
  /** What happened, in terms of the data rather than the stack. */
  summary: string
  /** The next thing the reader can actually do. */
  action: string
}

export const SCHEDULE_GRID_ERRORS: Record<string, ScheduleGridErrorCopy> = {
  schedule_grid_local_only: {
    summary:
      'The schedule grid is served to this machine only, and this request did not arrive from 127.0.0.1.',
    action:
      'Open the dashboard on the machine running the backend. See ADR-001 — the API binds loopback and is never exposed to the network.',
  },
  schedule_grid_league_not_found: {
    summary: 'This database has no such league, so there are no scoring periods to count games into.',
    action:
      'Check the league id in the URL, or seed the database — `python -m hoops_gm.dev.seed_schedule_grid` creates league 1 for the 2026-27 season.',
  },
  schedule_grid_not_current: {
    summary:
      'The stored schedule no longer matches the games in the database: it changed after it was last verified. The counts are withheld rather than shown from a schedule cohort that may already be out of date.',
    action:
      'Re-run the schedule import so the refresh and the games it counts are the same cohort again.',
  },
  schedule_grid_incomplete_evidence: {
    summary:
      'The schedule refresh cannot state what it imported, so its completeness could not be verified. This is not a claim that the schedule is wrong — it is that nothing on record can show it is right.',
    action:
      'Re-run the schedule import to produce a refresh that records its own completeness, then reload.',
  },
  schedule_grid_incomplete: {
    summary:
      'The schedule verified cleanly but produced no game counts at all for this league, so there is no grid to draw.',
    action:
      "Check that the league's scoring period calendar covers the season the schedule was imported for.",
  },
}

/** Generic client-side failures, so every path has a specific message too. */
const TRANSPORT_ERRORS: Record<string, ScheduleGridErrorCopy> = {
  unreachable: {
    summary: 'The backend did not answer, so no schedule data was received at all.',
    action: 'Start the backend on 127.0.0.1:8000, then retry.',
  },
  timeout: {
    summary: 'The backend accepted the request but did not answer in time.',
    action: 'Retry. If it keeps timing out, check the backend logs for a stuck query.',
  },
  invalid_response: {
    summary:
      'The backend answered, but the body did not match the schedule grid contract, so nothing is drawn rather than drawing a grid from a shape we do not recognise.',
    action:
      'Check that the backend and dashboard are from the same revision. The response is unusable, not merely unexpected.',
  },
}

export interface ScheduleGridErrorDescription extends ScheduleGridErrorCopy {
  /** The machine-readable code, from the response body. */
  code: string | null
  /** The backend's own wording, kept so a report can quote it exactly. */
  detail: string | null
  /** Correlates this failure to a server log line. */
  requestId: string | null
  /** True when the code is one the backend documents for this endpoint. */
  isKnown: boolean
}

export function describeScheduleGridError(error: Error | null): ScheduleGridErrorDescription {
  if (!(error instanceof ApiError)) {
    return {
      summary: error?.message ?? 'The schedule grid failed to load for an unrecorded reason.',
      action: 'Retry. If it recurs, check the browser console and the backend logs.',
      code: null,
      detail: null,
      requestId: null,
      isKnown: false,
    }
  }

  const known = SCHEDULE_GRID_ERRORS[error.code]
  const copy = known ?? TRANSPORT_ERRORS[error.code]

  return {
    summary:
      copy?.summary ??
      `The backend refused the schedule grid with HTTP ${String(error.status)} and did not give a reason this dashboard recognises.`,
    action:
      copy?.action ??
      'Quote the code and request id below when reporting it; both appear in the backend log for the same request.',
    code: error.code,
    // `client.ts` puts the envelope's `detail` on the message, so the backend's
    // own wording survives even when the body itself is not retained.
    detail: error.message === '' ? null : error.message,
    requestId: error.requestId,
    isKnown: known !== undefined,
  }
}
