/**
 * Projections — the imported Basketball Monster cohort, with its lineage.
 *
 * The draft board's first surface, and deliberately the smallest honest version
 * of one: every player Basketball Monster published, their per-game rates, and
 * the fingerprints behind them.
 *
 * **What this screen is not, said out loud rather than left implied.** It is
 * not a comparison. No blend profile, source weighting or activation pointer is
 * persisted anywhere, so there is no "our number" for these to sit beside yet —
 * `architect` is proposing ADR-015 to make a blend recipe durable, and until
 * something like it is accepted and built, a side-by-side would be two columns
 * of the same source's numbers wearing different labels. The screen states that
 * rather than showing one column and letting a reader assume the other is
 * coming.
 *
 * **The retry policy is the draft-day requirement, not a nicety.**
 * `projections_inconsistent_cohort` means a concurrent import moved the cohort;
 * it is the only retryable code of the eight and the board must not clear
 * itself when it arrives. Two independent things make that true: the retry
 * below, and `AsyncBoundary`'s warm path, which keeps the last good payload on
 * screen for *any* failed refresh. An empty board mid-auction is worse than a
 * slightly stale one.
 */

import { useMemo } from 'react'
import { getCurrentProjections } from '../api/endpoints'
import { describeProjectionsError, isRetryableProjectionsError } from '../api/projectionsErrors'
import type { CurrentProjections } from '../api/types'
import { useAsync } from '../api/useAsync'
import { AsyncBoundary } from '../components/AsyncBoundary'
import { ProjectionLineagePanel } from '../components/ProjectionLineage'
import { ProjectionsTable } from '../components/ProjectionsTable'
import { buildProjectionsModel } from '../components/projectionsModel'

/**
 * The single league this build serves (ADR-001: one owner, one local league).
 * A league picker arrives with the league-management surface, not before.
 */
const LEAGUE_ID = 1

/**
 * A cohort changes when a CSV is re-imported, which is a deliberate act rather
 * than a background process — so this is about the reader's confidence that
 * what is on screen came from this sitting, not about the projections going out
 * of date. How old the *import* is, which is the different and slower question,
 * is in the lineage panel with the timestamp beside it.
 */
export const STALE_AFTER_MS = 5 * 60_000

export function ProjectionsPage() {
  const projections = useAsync(
    (options) => getCurrentProjections(LEAGUE_ID, options),
    [],
    { shouldRetry: isRetryableProjectionsError },
  )

  return (
    <article className="page">
      <header className="page__header">
        <h1>Projections</h1>
        <p className="page__lede">
          Basketball Monster&apos;s published per-game rates, exactly as imported, with the
          fingerprints behind them. <strong>These are their numbers, not ours.</strong> We have
          not computed our own projections yet, so there is nothing here to compare against —
          this screen shows one source and says where it came from. No ranking, no valuation, no
          availability adjustment. See{' '}
          <code>docs/decisions/ADR-002-production-vs-availability.md</code>.
        </p>
      </header>

      <AsyncBoundary
        state={projections}
        label="the imported projections"
        staleAfterMs={STALE_AFTER_MS}
        isEmpty={(data) => data.projections.length === 0}
        emptyMessage="The current Basketball Monster import for this season carries no projection rows, so there is nothing to draw. That is a cohort with no players in it, not a failed request."
        describeError={describeProjectionsError}
      >
        {(data) => <ProjectionsView payload={data} />}
      </AsyncBoundary>
    </article>
  )
}

function ProjectionsView({ payload }: { payload: CurrentProjections }) {
  // The model carries the lineage through from the same payload object the
  // rows came from, so the panel below and the table below it cannot describe
  // different cohorts.
  const model = useMemo(() => buildProjectionsModel(payload), [payload])
  const { integrity } = model

  return (
    <>
      <ProjectionLineagePanel lineage={model.lineage} drawnRowCount={model.rows.length} />

      {!integrity.isConsistent ? (
        <p
          className="state state--error grid__integrity"
          role="status"
          data-testid="projections-integrity"
        >
          This cohort does not line up with itself.
          {!integrity.rowCountMatchesLineage
            ? ` The response carried ${String(model.rows.length)} rate rows but its lineage block counts ${String(model.lineage.projection_import.projection_count)}, so these are not exactly the rows the backend verified.`
            : ''}
          {integrity.ratesWithoutPlayer > 0
            ? ` ${String(integrity.ratesWithoutPlayer)} player(s) have rates but no player record and are shown under a bare id.`
            : ''}
          {integrity.playersWithoutRates > 0
            ? ` ${String(integrity.playersWithoutRates)} player(s) are named but carry no rates and are not drawn.`
            : ''}
          {integrity.duplicateRateRows > 0
            ? ` ${String(integrity.duplicateRateRows)} duplicate rate row(s) were ignored; the first was kept.`
            : ''}
          {integrity.duplicatePlayerRows > 0
            ? ` ${String(integrity.duplicatePlayerRows)} duplicate player record(s) were ignored.`
            : ''}
          {integrity.duplicateAssumptionRows > 0
            ? ` ${String(integrity.duplicateAssumptionRows)} duplicate games-played assumption(s) were ignored.`
            : ''}
          {integrity.assumptionsWithoutRates > 0
            ? ` ${String(integrity.assumptionsWithoutRates)} games-played assumption(s) name a player this response carries no rates for.`
            : ''}
          {integrity.unexplainedAssumptions > 0
            ? ` ${String(integrity.unexplainedAssumptions)} games-played assumption row(s) state neither a value nor the text they came from, which is not a state the contract describes.`
            : ''}
        </p>
      ) : null}

      {/* Above the table, not below it: the first `·` a reader meets is in row
          one, and a key under five hundred rows is a key they have already
          needed. */}
      <p className="page__note grid__key">
        <span className="grid__key-item">
          <span className="grid__cell grid__key-swatch">0.00</span> the source published zero
        </span>
        <span className="grid__key-item">
          <span className="grid__cell grid__cell--nodata grid__key-swatch">·</span> the source
          did not publish this quantity — <strong>not zero</strong>
        </span>
        <span className="grid__key-item">
          {/* Stated because a marker whose meaning is "this never happens" is
              more useful than one a reader assumes is routine. Basketball
              Monster's `required_production_fields` is set-equal to the
              canonical rate vocabulary, and `parser.py:293-296` drops a row on
              *any* missing required value, so a stored row always carries
              every rate and a games figure.

              This sentence depends on those two tuples staying set-equal, and
              at time of writing nothing in CI enforces that — `backend` is
              adding the pin. If it drifts, this becomes the misleading claim
              rather than the useful one. See `projectionsModel.ts`. */}
          A <code>·</code> should not appear for Basketball Monster: its import profile requires
          every rate shown here and a games-played figure, and a row missing any of them is
          rejected rather than stored. If one appears, something upstream has changed.
        </span>
        <span className="grid__key-item">
          <strong>Source GP</strong> is what Basketball Monster assumed about games played. It is
          shown so you can see the assumption our availability model will replace. It is{' '}
          <strong>not</strong> a rate, and multiplying a rate by it reconstructs the source&apos;s
          own season total — the fusion ADR-002 permits only at the expected-games seam, which is
          not built.
        </span>
        <span className="grid__key-item">
          <strong>Pos</strong> is NBA&apos;s own coarse label and is not Fantrax lineup
          eligibility. This project ingests no Fantrax position data, so the table cannot filter
          or group by position.
        </span>
      </p>

      <ProjectionsTable model={model} />
    </>
  )
}
