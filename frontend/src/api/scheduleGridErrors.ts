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
    // Three raisers: `schedule_grid.py:226` (no refresh registered at all),
    // `:282` (registered version no longer matches the persisted schedule),
    // and `:430`, which the backend documents as covering roughly twenty-five
    // causes of which only one actually means "stale". Phrased open for that
    // reason. An earlier version asserted a two-way disambiguation with a
    // per-branch remedy over that site, which is the construction removed from
    // `incomplete_evidence` for exactly this reason — and it told an operator
    // with no active deadline calendar to re-run a projection that cannot
    // create the calendar it projects from.
    summary:
      "The backend could not establish that a grid served now would describe current reality, so it served none. The backend's wording below names what failed; common cases are no schedule refresh registered for this season, a registered version that no longer matches the persisted schedule, and a league deadline calendar or scoring-period projection that cannot be resolved.",
    action:
      "Read the backend's wording below — the remedy differs. Nothing registered means importing the schedule for the first time; a version that no longer matches means re-importing it, since the schedule changed after that version was recorded; a calendar or projection problem lives in the league's own configuration, and re-importing the schedule will not touch it.",
  },
  schedule_grid_incomplete_evidence: {
    summary:
      "The backend could not verify the evidence behind the counts it was asked for, so it served none. The backend's wording below names the check that failed; common cases are a refresh that cannot account for what it imported, a refresh describing a different cohort from the one this grid counts, and counted rows that do not line up with this league's teams or scoring calendar. This is not a claim that the schedule is wrong — it is that nothing on record establishes the counts this request asked for.",
    action:
      "Read the backend's wording below: it names the check that failed, and the remedy is not the same for each. A refresh that cannot state its completeness needs the schedule re-importing; a team or scoring period with no row needs the league's team data or calendar corrected, and re-importing the schedule will not create one.",
  },
  schedule_grid_incomplete: {
    // Two raisers today: `schedule_grid.py:435` (no rows at all) and `:485`
    // (a team holding schedule rows inside the verified cohort but absent from
    // the grid). Phrased open rather than closed, like its sibling, because a
    // third raiser would otherwise make this silently wrong — which is how
    // `incomplete_evidence` went stale.
    //
    // `rows` comes from a cross join of the league's scoring periods with
    // active teams, so it is empty only when the league has no scoring periods
    // or there are no active teams. A calendar that exists but does not cover
    // the imported season yields rows that are all zero, which is a different
    // condition and raises `incomplete_evidence` at `:453` instead. An earlier
    // version of this action sent that operator to the wrong place.
    summary:
      "The schedule verified cleanly, but the grid assembled from it does not hold together. The backend's wording below names what failed; common cases are no counts at all for this league, or a team left out of the grid that has schedule rows inside the verified cohort. It refuses to serve counts that contradict their own lineage rather than showing a grid quietly short a team.",
    action:
      "Read the backend's wording below. No counts at all means the league has no scoring periods, or no active teams — note that a calendar which exists but does not cover the imported season is a different refusal. A team present in the schedule but absent from the grid points at that team being marked inactive while still holding rows.",
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
