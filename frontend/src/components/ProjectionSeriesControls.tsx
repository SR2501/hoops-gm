import { useId, useState, type ReactNode } from 'react'
import {
  getDraftProjectionSeries,
  getProjectionSeries,
  isProjectionSource,
} from '../api/projectionSeriesEndpoints'
import {
  type ProjectionSelection,
  type ProjectionSeriesCatalog,
} from '../api/projectionSeriesTypes'
import {
  PRODUCTION_CANDIDATE_SOURCES,
  type ProductionCandidateSource,
} from '../api/productionCandidatesTypes'
import { productionSourceLabel } from '../api/productionCandidatesLabels'
import { useAsync } from '../api/useAsync'
import { AsyncBoundary, type ErrorDescription } from './AsyncBoundary'

/** The existing publisher vocabulary, not invented Josh/Bonus provider variants. */
export function ProjectionSourceSelect({
  source,
  onChange,
}: {
  source: ProductionCandidateSource
  onChange: (source: ProductionCandidateSource) => void
}) {
  const helpId = useId()
  return (
    <>
      <label>
        <span>Supported sources</span>
        <select
          value={source}
          aria-describedby={helpId}
          onChange={(event) => {
            if (isProjectionSource(event.target.value)) onChange(event.target.value)
          }}
        >
          {PRODUCTION_CANDIDATE_SOURCES.map((publisher) => (
            <option key={publisher} value={publisher}>
              {productionSourceLabel(publisher)}
            </option>
          ))}
        </select>
      </label>
      <p id={helpId}>
        Supported does not mean currently imported. The inventory below lists only recorded
        series for this source and season; it is not release approval.
      </p>
    </>
  )
}

interface ProjectionSeriesScopeProps {
  resource: 'league' | 'draft'
  resourceId: number
  source: ProductionCandidateSource
  describeError: (error: Error) => ErrorDescription
  children: (selection: ProjectionSelection) => ReactNode
}

/**
 * The caller keys this catalog loader by release domain + resource + publisher.
 * The returned league/season keys the choice boundary; a draft never guesses league 1.
 */
export function ProjectionSeriesScope({
  resource,
  resourceId,
  source,
  describeError,
  children,
}: ProjectionSeriesScopeProps) {
  const inventory = useAsync<ProjectionSeriesCatalog>(
    (options) => resource === 'draft'
      ? getDraftProjectionSeries(resourceId, source, options)
      : getProjectionSeries(resourceId, { ...options, source }),
    [resource, resourceId, source],
    { deferInitialRequest: true },
  )

  return (
    <>
      <div className="projection-series__inventory" data-testid="projection-series-inventory">
        <p>
          Series labels are operator declarations, not proof of vendor authenticity or forecast
          calibration. Legacy imports have no declared variant. Each selection follows its current
          import on refresh; this is not historical pinning.
        </p>
        <button
          type="button"
          onClick={inventory.reload}
          disabled={inventory.status === 'idle' || inventory.status === 'loading'}
        >
          Reload series
        </button>
      </div>
      <AsyncBoundary
        state={inventory}
        label={`recorded projection series for ${resource} ${String(resourceId)} from ${productionSourceLabel(source)}`}
        describeError={describeError}
      >
        {(catalog) => (
          <SeriesChoice
            key={JSON.stringify([catalog.league_id, catalog.season])}
            catalog={catalog}
          >
            {children}
          </SeriesChoice>
        )}
      </AsyncBoundary>
    </>
  )
}

function SeriesChoice({
  catalog,
  children,
}: {
  catalog: ProjectionSeriesCatalog
  children: (selection: ProjectionSelection) => ReactNode
}) {
  // Initialize once, not on every inventory refresh. Even a now-missing explicit
  // selection must never become the first/latest/sole remaining series silently.
  const [seriesKey, setSeriesKey] = useState<string | null>(
    () => catalog.series.length === 1 ? catalog.series[0]!.key : null,
  )
  const helpId = useId()
  const selectedIsRecorded = catalog.series.some((entry) => entry.key === seriesKey)

  return (
    <>
      <div className="projection-controls" data-testid="projection-series-controls">
        <label>
          <span>Projection series</span>
          <select
            value={seriesKey ?? ''}
            aria-describedby={helpId}
            disabled={catalog.series.length === 0 && seriesKey === null}
            onChange={(event) => { setSeriesKey(event.target.value || null) }}
          >
            <option value="">Choose a recorded series…</option>
            {seriesKey !== null && !selectedIsRecorded ? (
              <option value={seriesKey}>{seriesKey} · no longer in inventory</option>
            ) : null}
            {catalog.series.map((entry) => (
              <option key={entry.key} value={entry.key}>
                {entry.display_name} · {entry.key}
              </option>
            ))}
          </select>
        </label>
        <p id={helpId}>
          League {catalog.league_id} · season {catalog.season}. Latest recorded candidates only,
          including imports whose numerical release may refuse. Exact import details below come
          from the successful numerical response, not this inventory.
        </p>
      </div>
      {seriesKey !== null && !selectedIsRecorded ? (
        <p className="state state--error" role="alert">
          Selected series <code>{seriesKey}</code> is no longer in this inventory. No other series
          was substituted. Choose a recorded series or reload the inventory.
        </p>
      ) : catalog.series.length === 0 ? (
        <p className="state state--empty" role="status">
          No recorded projection imports for this source and season. Import the intended source
          series before loading rates or rankings, then reload the series inventory.
        </p>
      ) : seriesKey === null ? (
        <p className="state state--empty" role="status">
          Choose a projection series to load its current import. No first or latest series is
          selected for you when multiple series are recorded, including legacy.
        </p>
      ) : children({ leagueId: catalog.league_id, season: catalog.season, seriesKey })}
    </>
  )
}
