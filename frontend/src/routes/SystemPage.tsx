/**
 * System — backend and database health.
 *
 * The page to open when a number looks wrong and the first question is whether
 * the backend is even answering.
 */

import { getReadiness } from '../api/endpoints'
import { useAsync } from '../api/useAsync'
import { AsyncBoundary } from '../components/AsyncBoundary'

/** Readiness is cheap to refetch, so anything older than a minute is stale. */
const STALE_AFTER_MS = 60_000

export function SystemPage() {
  const readiness = useAsync((options) => getReadiness(options), [])

  return (
    <article className="page">
      <header className="page__header">
        <h1>System</h1>
        <p className="page__lede">
          Local-first: the backend binds <code>127.0.0.1</code> and nothing is exposed to the
          network. See <code>docs/decisions/ADR-001-local-first.md</code>.
        </p>
      </header>

      <section aria-labelledby="readiness-heading">
        <h2 id="readiness-heading">Readiness</h2>
        <AsyncBoundary state={readiness} label="readiness" staleAfterMs={STALE_AFTER_MS}>
          {(data) => (
            <dl className="facts">
              <div className="facts__row">
                <dt>Service</dt>
                <dd data-testid="readiness-status">{data.status}</dd>
              </div>
              <div className="facts__row">
                <dt>Database</dt>
                <dd data-testid="readiness-database">{data.database}</dd>
              </div>
              {data.detail ? (
                <div className="facts__row">
                  <dt>Detail</dt>
                  <dd>{data.detail}</dd>
                </div>
              ) : null}
            </dl>
          )}
        </AsyncBoundary>
        <p className="page__note">
          <button type="button" onClick={readiness.reload}>
            Check again
          </button>
        </p>
      </section>
    </article>
  )
}
