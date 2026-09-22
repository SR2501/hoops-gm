import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getProductionCandidates } from '../api/productionCandidatesEndpoints'
import {
  describeProductionCandidatesError,
  isRetryableProductionCandidatesError,
} from '../api/productionCandidatesErrors'
import type { ProductionCandidateSource } from '../api/productionCandidatesTypes'
import {
  DEFAULT_PROJECTION_SOURCE,
  projectionSeriesScopeKey,
  type ProjectionSelection,
} from '../api/projectionSeriesTypes'
import { useAsync } from '../api/useAsync'
import { AsyncBoundary } from '../components/AsyncBoundary'
import {
  ProductionCandidatesTable,
} from '../components/ProductionCandidatesTable'
import { productionSourceLabel } from '../api/productionCandidatesLabels'
import {
  ProjectionSeriesScope,
  ProjectionSourceSelect,
} from '../components/ProjectionSeriesControls'

export const PRODUCTION_CANDIDATES_POLL_INTERVAL_MS = 2000
export const PRODUCTION_CANDIDATES_STALE_AFTER_MS = 6000
export const DEFAULT_PRODUCTION_CANDIDATE_SOURCE: ProductionCandidateSource =
  DEFAULT_PROJECTION_SOURCE

const CANONICAL_POSITIVE_DECIMAL_ID = /^[1-9]\d*$/

function parseCanonicalDraftId(rawDraftId: string | undefined): number | null {
  if (rawDraftId === undefined || !CANONICAL_POSITIVE_DECIMAL_ID.test(rawDraftId)) {
    return null
  }
  const draftId = Number(rawDraftId)
  return Number.isSafeInteger(draftId) ? draftId : null
}

export function ProductionCandidatesPage() {
  const params = useParams<{ draftId: string }>()
  const draftId = parseCanonicalDraftId(params.draftId)

  if (draftId === null) {
    return (
      <article className="page">
        <h1>Production-only rankings</h1>
        <p className="state state--error" role="alert">
          <code>{params.draftId ?? '(none)'}</code> is not a draft id.
        </p>
      </article>
    )
  }

  return <ProductionCandidatesRoute draftId={draftId} />
}

function ProductionCandidatesRoute({ draftId }: { draftId: number }) {
  const [source, setSource] = useState<ProductionCandidateSource>(
    DEFAULT_PRODUCTION_CANDIDATE_SOURCE,
  )

  return (
    <article className="page page--production-candidates">
      <header className="page__header">
        <h1>Production-only rankings · Draft {draftId}</h1>
        <p className="page__lede">
          Source projections scored by the production engine, relative to the selected source
          pool. This read-only partial view is not the strategy-aware shortlist and includes no
          availability fusion, <code>p(play)</code>, expected games, punt fit, affordability,
          position fit, or Fantrax roster eligibility.
        </p>
        <div className="projection-controls">
          <ProjectionSourceSelect source={source} onChange={setSource} />
          <Link to={`/draft/${String(draftId)}`}>Back to the recorded draft</Link>
        </div>
      </header>

      {/*
        `useAsync` deliberately retains a last-good response. Keying the loader
        by the release domain and complete query scope makes retention correct.
        Catalogs also mount cold on source/draft changes. No league is guessed.
      */}
      <ProjectionSeriesScope
        key={projectionSeriesScopeKey('draft', draftId, source)}
        resource="draft"
        resourceId={draftId}
        source={source}
        describeError={describeProductionCandidatesError}
      >
        {(selection) => (
          <ProductionCandidatesLoader
            key={projectionSeriesScopeKey('draft', draftId, source, selection)}
            draftId={draftId}
            source={source}
            selection={selection}
          />
        )}
      </ProjectionSeriesScope>
    </article>
  )
}

function ProductionCandidatesLoader({
  draftId,
  source,
  selection,
}: {
  draftId: number
  source: ProductionCandidateSource
  selection: ProjectionSelection
}) {
  const [tick, setTick] = useState(0)
  const refresh = useCallback(() => {
    setTick((value) => value + 1)
  }, [])

  const candidates = useAsync(
    (options) => getProductionCandidates(draftId, source, {
      ...options,
      seriesKey: selection.seriesKey,
      expectedSeason: selection.season,
      expectedLeagueId: selection.leagueId,
    }),
    [draftId, source, selection.leagueId, selection.season, selection.seriesKey, tick],
    {
      shouldRetry: isRetryableProductionCandidatesError,
      deferInitialRequest: true,
    },
  )

  useEffect(() => {
    // Poll only after a successful whole response. A typed terminal refusal
    // stays on screen until the reader asks again; it is not retried every two
    // seconds under the name of polling. The one retryable snapshot conflict is
    // spent exactly once inside `useAsync`.
    if (candidates.status !== 'success') return
    const timer = setTimeout(refresh, PRODUCTION_CANDIDATES_POLL_INTERVAL_MS)
    return () => {
      clearTimeout(timer)
    }
  }, [candidates.fetchedAt, candidates.status, refresh])

  return (
    <AsyncBoundary
      state={candidates}
      label={`production-only candidates for Draft ${String(draftId)} from ${productionSourceLabel(
        source,
      )} / ${selection.seriesKey}`}
      staleAfterMs={PRODUCTION_CANDIDATES_STALE_AFTER_MS}
      describeError={describeProductionCandidatesError}
    >
      {(payload) => <ProductionCandidatesTable payload={payload} />}
    </AsyncBoundary>
  )
}
