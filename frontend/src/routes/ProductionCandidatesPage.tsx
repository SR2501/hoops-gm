import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  getProductionCandidates,
  isProductionCandidateSource,
} from '../api/productionCandidatesEndpoints'
import {
  describeProductionCandidatesError,
  isRetryableProductionCandidatesError,
} from '../api/productionCandidatesErrors'
import {
  PRODUCTION_CANDIDATE_SOURCES,
  type ProductionCandidateSource,
} from '../api/productionCandidatesTypes'
import { useAsync } from '../api/useAsync'
import { AsyncBoundary } from '../components/AsyncBoundary'
import {
  ProductionCandidatesTable,
} from '../components/ProductionCandidatesTable'
import { productionSourceLabel } from '../api/productionCandidatesLabels'

export const PRODUCTION_CANDIDATES_POLL_INTERVAL_MS = 2000
export const PRODUCTION_CANDIDATES_STALE_AFTER_MS = 6000
export const DEFAULT_PRODUCTION_CANDIDATE_SOURCE: ProductionCandidateSource =
  'basketball_monster'

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
        <div className="production-candidates__route-controls">
          <label>
            <span>Supported sources</span>
            <select
              value={source}
              aria-describedby="production-source-help"
              onChange={(event) => {
                if (isProductionCandidateSource(event.target.value)) {
                  setSource(event.target.value)
                }
              }}
            >
              {PRODUCTION_CANDIDATE_SOURCES.map((candidateSource) => (
                <option key={candidateSource} value={candidateSource}>
                  {productionSourceLabel(candidateSource)}
                </option>
              ))}
            </select>
          </label>
          <p id="production-source-help">
            Supported does not mean currently imported. A missing or unadmitted source is shown as
            a typed refusal rather than removed from this list.
          </p>
          <Link to={`/draft/${String(draftId)}`}>Back to the recorded draft</Link>
        </div>
      </header>

      {/*
        `useAsync` deliberately retains a last-good response. Keying the loader
        by the complete query scope makes that retention correct: a refresh of
        this draft/source keeps its whole payload, while a source or draft
        change mounts a cold scope and cannot relabel the old response.
      */}
      <ProductionCandidatesLoader
        key={`${String(draftId)}:${source}`}
        draftId={draftId}
        source={source}
      />
    </article>
  )
}

function ProductionCandidatesLoader({
  draftId,
  source,
}: {
  draftId: number
  source: ProductionCandidateSource
}) {
  const [tick, setTick] = useState(0)
  const refresh = useCallback(() => {
    setTick((value) => value + 1)
  }, [])

  const candidates = useAsync(
    (options) => getProductionCandidates(draftId, source, options),
    [draftId, source, tick],
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
      )}`}
      staleAfterMs={PRODUCTION_CANDIDATES_STALE_AFTER_MS}
      describeError={describeProductionCandidatesError}
    >
      {(payload) => <ProductionCandidatesTable payload={payload} />}
    </AsyncBoundary>
  )
}
