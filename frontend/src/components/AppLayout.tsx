/**
 * The layout shell: a persistent sidebar and a routed outlet.
 *
 * Designed for one screen. The owner works from a laptop, and extra monitors
 * are a comfort rather than a requirement, so navigation is dense and the
 * content area gets the space.
 *
 * Backend connectivity lives in the shell rather than on a settings page: if
 * the backend is down, every number on screen is suspect, and that has to be
 * visible without going looking for it.
 */

import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { ApiError } from '../api/client'
import { getHealth } from '../api/endpoints'
import { useAsync } from '../api/useAsync'
import { useIsStale } from '../api/useStale'
import { RenderErrorBoundary } from './RenderErrorBoundary'

const HEALTH_STALE_AFTER_MS = 60_000

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/draft', label: 'Draft' },
  { to: '/schedule', label: 'Schedule' },
  { to: '/projections', label: 'Projections' },
  { to: '/system', label: 'System' },
] as const

export function AppLayout() {
  const health = useAsync((options) => getHealth(options), [])
  const location = useLocation()

  return (
    <div className="shell">
      <aside className="shell__sidebar">
        <div className="shell__brand">
          <span className="shell__brand-name">hoops-gm</span>
          <span className="shell__brand-season">2026–27</span>
        </div>

        <nav aria-label="Primary">
          <ul className="nav">
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={'end' in item ? item.end : false}
                  className={({ isActive }) => (isActive ? 'nav__link nav__link--active' : 'nav__link')}
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="shell__status">
          <BackendStatus
            status={health.status}
            version={health.data?.version ?? null}
            environment={health.data?.environment ?? null}
            error={health.error}
            fetchedAt={health.fetchedAt}
            reload={health.reload}
          />
        </div>
      </aside>

      <main className="shell__main">
        <RenderErrorBoundary resetKey={location.key}>
          <Outlet />
        </RenderErrorBoundary>
      </main>
    </div>
  )
}

interface BackendStatusProps {
  status: 'idle' | 'loading' | 'success' | 'error'
  version: string | null
  environment: string | null
  error: Error | null
  fetchedAt: Date | null
  reload: () => void
}

export function BackendStatus({
  status,
  version,
  environment,
  error,
  fetchedAt,
  reload,
}: BackendStatusProps) {
  const isStale = useIsStale(fetchedAt, HEALTH_STALE_AFTER_MS)
  const code = error instanceof ApiError ? error.code : null
  const requestId = error instanceof ApiError ? error.requestId : null

  if (version && environment) {
    const refreshFailed = status === 'error'
    const refreshPending = status === 'loading'
    return (
      <div
        className="shell__status-error"
        role={refreshFailed ? 'alert' : 'status'}
        data-testid="backend-status"
      >
        <p
          className={
            refreshFailed
              ? 'status status--error'
              : isStale || refreshPending
                ? 'status status--pending'
                : 'status status--ok'
          }
        >
          <span className="status__dot" aria-hidden="true" />
          Backend {version} · {environment}
        </p>
        {refreshPending ? <p className="shell__status-detail">Checking backend…</p> : null}
        {isStale && !refreshPending ? (
          <p className="shell__status-detail">Health status is stale.</p>
        ) : null}
        {refreshFailed && error ? (
          <p className="shell__status-detail">Refresh failed. {error.message}</p>
        ) : null}
        {refreshFailed && (code || requestId) ? (
          <p className="shell__status-detail">
            {code ? `Code ${code}` : ''}
            {code && requestId ? ' · ' : ''}
            {requestId ? `Request ${requestId}` : ''}
          </p>
        ) : null}
        {(refreshFailed || isStale) && !refreshPending ? (
          <button type="button" className="shell__status-retry" onClick={reload}>
            Check backend again
          </button>
        ) : null}
      </div>
    )
  }
  if (status === 'error') {
    const proxyCouldNotReachBackend =
      error instanceof ApiError &&
      error.code === 'http_error' &&
      error.status >= 500 &&
      error.requestId === null
    const unreachable = code === 'unreachable' || code === 'timeout' || proxyCouldNotReachBackend
    return (
      <div className="shell__status-error" role="alert" data-testid="backend-status">
        <p className="status status--error">
          <span className="status__dot" aria-hidden="true" />
          {unreachable ? 'Backend unreachable' : 'Backend error'}
        </p>
        {error ? <p className="shell__status-detail">{error.message}</p> : null}
        {code || requestId ? (
          <p className="shell__status-detail">
            {code ? `Code ${code}` : ''}
            {code && requestId ? ' · ' : ''}
            {requestId ? `Request ${requestId}` : ''}
          </p>
        ) : null}
        <button type="button" className="shell__status-retry" onClick={reload}>
          Check backend again
        </button>
      </div>
    )
  }
  return (
    <p className="status status--pending" data-testid="backend-status">
      <span className="status__dot" aria-hidden="true" />
      Checking backend…
    </p>
  )
}
