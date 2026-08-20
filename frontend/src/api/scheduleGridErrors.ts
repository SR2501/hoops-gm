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
 * One module rather than two, and consumed as a *description* rather than as a
 * rendered panel, so that the same words reach both failure paths: the cold
 * one, where nothing is on screen, and the warm one, where the grid is still
 * showing and a refresh has just failed. The warm path is where
 * `schedule_grid_not_current` actually arrives — the schedule is re-ingested
 * while a grid is open — and it is the path where "these counts are from a
 * superseded cohort" is the most decision-bearing sentence on the page.
 *
 * **One code, nine backend conditions.** `schedule_grid_incomplete_evidence` is
 * raised from nine places in `schedule_grid.py`, on four different objects: the
 * refresh's completeness evidence, the cohort it describes, the league's team
 * rows, and the league's scoring calendar. No single string can be both
 * specific and true across all of them, so the copy here names the families and
 * defers to the backend's own wording for which applies — and says outright
 * that the remedy differs, because re-importing the schedule cannot create a
 * missing scoring period. An earlier version asserted that remedy for every
 * condition, which was a confident instruction that would have sent an operator
 * to re-run an import three of the nine conditions do not respond to.
 *
 * Do not branch on the backend's prose to recover specificity. Matching on
 * detail text is the form-over-meaning coupling AGENTS.md warns about and would
 * break silently on a reword. The clean fix is a code split or a
 * machine-readable discriminant in the body; it is `backend`'s, and is recorded
 * in `docs/backlog.md` as `schedule-grid-refusal-discriminant`.
 */

import { ApiError } from './client'
import type { ErrorDescription } from '../components/AsyncBoundary'

export type ScheduleGridErrorCopy = Required<ErrorDescription>

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
      'Check the league id in the URL, or seed a demo database — see `backend/README.md` for the offline seed path.',
  },
  schedule_grid_not_current: {
    summary:
      "The evidence is well-formed but no longer describes current reality: the schedule may have changed after this version was recorded, or the league's scoring-period projection may be stale. Verification worked and returned a clear verdict — nothing here is unknown, it is simply out of date, so the grid is withheld rather than served from a superseded cohort.",
    action:
      "Read the backend's wording below and act on what it names: re-import the schedule, or re-run the scoring-period projection. Both bring the registered version and the rows it describes back into step.",
  },
  schedule_grid_incomplete_evidence: {
    summary:
      "The backend could not verify the evidence behind the counts it was asked for, so it served none. Which check failed differs: the schedule refresh may be unable to account for what it imported, it may have imported a different cohort from the one this grid counts, or the counted rows may not line up with this league's teams and scoring periods. This is not a claim that the schedule is wrong — it is that nothing on record establishes the counts this request asked for.",
    action:
      "Read the backend's wording below: it names the check that failed, and the remedy is not the same for each. A refresh that cannot state its completeness needs the schedule re-importing; a team or scoring period with no row needs the league's team data or calendar corrected, and re-importing the schedule will not create one.",
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

/**
 * The description `AsyncBoundary` renders. Just the words — the code and the
 * request id are read off the `ApiError` by the boundary itself, so carrying
 * them here as well would be a second copy nothing reads.
 */
export type ScheduleGridErrorDescription = ScheduleGridErrorCopy

export function describeScheduleGridError(error: Error | null): ScheduleGridErrorDescription {
  if (!(error instanceof ApiError)) {
    return {
      summary: error?.message ?? 'The schedule grid failed to load for an unrecorded reason.',
      action: 'Retry. If it recurs, check the browser console and the backend logs.',
    }
  }

  // `Object.hasOwn` rather than a bare lookup: a code named `constructor` or
  // `toString` would otherwise resolve to an inherited function and be treated
  // as a known one.
  const copy = Object.hasOwn(SCHEDULE_GRID_ERRORS, error.code)
    ? SCHEDULE_GRID_ERRORS[error.code]
    : Object.hasOwn(TRANSPORT_ERRORS, error.code)
      ? TRANSPORT_ERRORS[error.code]
      : undefined

  return {
    summary:
      copy?.summary ??
      `The backend refused the schedule grid with HTTP ${String(error.status)} and did not give a reason this dashboard recognises.`,
    action:
      copy?.action ??
      'Quote the code and request id below when reporting it; both appear in the backend log for the same request.',
  }
}
