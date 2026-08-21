/**
 * What each projections refusal means, and what to do about it.
 *
 * Eight typed codes, and collapsing them into "something went wrong" would
 * throw away the distinction that matters most here: **exactly one of them is
 * retryable.** `projections_inconsistent_cohort` means a concurrent import
 * moved the cohort while it was being read, and the correct response is to ask
 * again. The other seven need a human — import a CSV, fix the crosswalk,
 * re-import under a verified profile — and retrying them only delays the
 * message.
 *
 * **The code arrives in the response body, not in a header.** `X-Bridge-Error`
 * is an internal route-to-handler transport inside the backend; the exception
 * handler in `app.py` builds a fresh response carrying only `X-Request-ID`.
 * `client.ts` parses `{error, detail, request_id}` off the body into
 * `ApiError.code`, and that is the value keyed here.
 *
 * Consumed as a *description* rather than as a rendered panel, so the same
 * words reach both failure paths: the cold one, where nothing is on screen, and
 * the warm one, where the cohort is still showing and a refresh has just
 * failed. The warm path is where `projections_inconsistent_cohort` actually
 * arrives.
 *
 * **A refusal's code does not reach the server log.** The middleware records
 * `status_code` only, so five of these eight read identically as `409` to an
 * operator tailing it. That is why every message below is written to stand on
 * its own in the browser rather than as a pointer to a log line, and it is
 * tracked as `error-code-observability` in `docs/backlog.md`.
 */

import { ApiError } from './client'
import type { ErrorDescription } from '../components/AsyncBoundary'

export type ProjectionsErrorCopy = Required<ErrorDescription>

/**
 * The only retryable code, named once so both consumers read the same constant.
 *
 * `ProjectionsPage` hands this to `useAsync`'s retry policy and the copy below
 * describes it; a second literal in either place could drift from this one
 * silently, and the failure would be invisible — a board that clears itself
 * mid-auction looks like a slow backend, not like a bug.
 */
export const RETRYABLE_PROJECTIONS_ERROR = 'projections_inconsistent_cohort'

/**
 * Whether this failure is the transient one.
 *
 * Deliberately an equality check against a single code rather than membership
 * of a "retryable" set. The set has one member and the backend documents it as
 * the only one; a set invites a future editor to add a code to it without
 * establishing that a second read would behave differently, which is exactly
 * the reasoning that has to happen for a retry to be correct.
 */
export function isRetryableProjectionsError(error: Error): boolean {
  return error instanceof ApiError && error.code === RETRYABLE_PROJECTIONS_ERROR
}

export const PROJECTIONS_ERRORS: Record<string, ProjectionsErrorCopy> = {
  projections_local_only: {
    summary:
      'Imported projections are served to this machine only, and this request did not arrive from 127.0.0.1.',
    action:
      'Open the dashboard on the machine running the backend. See ADR-001 — the API binds loopback and is never exposed to the network.',
  },
  projections_league_not_found: {
    summary:
      'This database has no such league, so there is no season to look up an imported cohort for.',
    action:
      'Check the league id in the URL, or seed a demo database — see `backend/README.md`.',
  },
  projections_source_unsupported: {
    summary:
      'The source asked for is an identity-anchor namespace rather than a projection CSV publisher, so there is no cohort of that kind to serve.',
    action:
      'Ask for a registered projection source. This screen always asks for Basketball Monster, so seeing this means something other than the screen made the request.',
  },
  projections_source_not_imported: {
    // Two raisers, and they are genuinely different states that happen to
    // share a remedy: the source has never been registered at all, and the
    // source is registered but holds no import for *this league's season*.
    // Both are answered by importing a CSV, so one code and one action is
    // honest here in a way it would not be if the remedies diverged.
    summary:
      "No Basketball Monster projections have been imported for this league's season. This is the expected state of a database nobody has imported a CSV into — it is not a fault, and nothing is broken.",
    action:
      "Import a Basketball Monster CSV for this league's season. The backend's wording below says whether the source has never been registered at all, or is registered with no import for this season.",
  },
  projections_not_current: {
    // Two raisers: a superseded import, and the import row disappearing
    // mid-read. The second is reachable rather than defensive because the
    // route takes no lock. Phrased open for that reason.
    summary:
      "The cohort this request asked for is no longer the current one for its source and season, so the backend served none rather than serving a superseded set of rates. The backend's wording below names which; the common case is that a newer import replaced it while this screen was open.",
    action:
      'Reload. If it recurs immediately, an import is running — let it finish. The backend refuses a superseded cohort rather than serving numbers a newer import has already replaced.',
  },
  projections_incomplete: {
    summary:
      'The import verified cleanly, but the cohort assembled from it does not hold together — the rows carried and the lineage describing them disagree about what this cohort is.',
    action:
      "Read the backend's wording below, and re-import the CSV. It refuses to serve rates that contradict their own lineage rather than showing a cohort quietly short a player.",
  },
  projections_incomplete_evidence: {
    // NINE members, one shared remedy. Enumerated in `docs/backlog.md` under
    // `projections-api-early`: an unverified import row, an unverified
    // profile-version row, a season outside the profile's verified scope,
    // self-contradicting immutable lineage, a negative rate, a non-finite
    // rate, a half-present three-point made/attempted pair, a row whose
    // denormalised season drifted from its import, and makes exceeding
    // attempts.
    //
    // **This enumeration was short at five, then at eight, before it was
    // nine**, and each recount came from someone walking the raise sites
    // rather than reading the previous list. So the copy below is written to
    // survive a tenth: it says a check failed and defers to the backend for
    // which, rather than naming families that a new member could fall outside.
    //
    // The shared remedy is what keeps this one code under `architect`'s rule —
    // split when two members imply different operator actions, keep one when
    // every member implies the same. Re-importing rewrites the entire row
    // cohort under a freshly verified profile, so it repairs every member,
    // including the three that are about the profile rather than the rates.
    // That is why a single action sentence is honest here and was not for
    // `schedule_grid_incomplete_evidence`, where re-importing could not create
    // a missing scoring period.
    //
    // Do not branch on the backend's prose to recover specificity. `detail` is
    // free-form and matching on it is the form-over-meaning coupling AGENTS.md
    // warns about; it would break silently on a reword.
    summary:
      "The backend could not establish that these rates are fit to be read, so it served none. Something about the import, the profile that parsed it, or a stored value failed a check — the backend's wording below names which one. This is not a claim that Basketball Monster's numbers are wrong; it is that nothing on record establishes the cohort this request asked for.",
    action:
      "Re-import the Basketball Monster CSV under a verified profile. That rewrites the whole row cohort, which is why it is the answer whichever check failed — quote the backend's wording below if it recurs afterwards.",
  },
  [RETRYABLE_PROJECTIONS_ERROR]: {
    // The one code this screen retries automatically. If a reader is seeing
    // this copy at all, the automatic retry has already been spent and failed,
    // so the action is what to do *after* that — which is why it does not say
    // "try again" as though nothing had been tried.
    summary:
      'A projection import was running while this cohort was being read, so the rates and the lineage describing them could have come from different states. The backend refused rather than serving a mixture. This is transient.',
    action:
      'This screen already retried once automatically and the import was still running. Wait for it to finish and refresh. Any rates still on screen are from the last complete read and are labelled with the time they arrived.',
  },
}

/** Generic client-side failures, so every path has a specific message too. */
const TRANSPORT_ERRORS: Record<string, ProjectionsErrorCopy> = {
  unreachable: {
    summary: 'The backend did not answer, so no projection data was received at all.',
    action: 'Start the backend on 127.0.0.1:8000, then retry.',
  },
  timeout: {
    summary: 'The backend accepted the request but did not answer in time.',
    action: 'Retry. If it keeps timing out, check the backend logs for a stuck query.',
  },
  invalid_response: {
    summary:
      'The backend answered, but the body did not match the projections contract, so nothing is drawn rather than drawing a table from a shape we do not recognise.',
    action:
      'Check that the backend and dashboard are from the same revision. The response is unusable, not merely unexpected.',
  },
}

export function describeProjectionsError(error: Error | null): ProjectionsErrorCopy {
  if (!(error instanceof ApiError)) {
    return {
      summary: error?.message ?? 'The projections failed to load for an unrecorded reason.',
      action: 'Retry. If it recurs, check the browser console and the backend logs.',
    }
  }

  // `Object.hasOwn` rather than a bare lookup: a code named `constructor` or
  // `toString` would otherwise resolve to an inherited function and be treated
  // as a known one.
  const copy = Object.hasOwn(PROJECTIONS_ERRORS, error.code)
    ? PROJECTIONS_ERRORS[error.code]
    : Object.hasOwn(TRANSPORT_ERRORS, error.code)
      ? TRANSPORT_ERRORS[error.code]
      : undefined

  return {
    summary:
      copy?.summary ??
      `The backend refused the projections with HTTP ${String(error.status)} and did not give a reason this dashboard recognises.`,
    action:
      copy?.action ??
      'Quote the code and request id below when reporting it; both appear in the backend log for the same request.',
  }
}
