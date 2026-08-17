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

import { NavLink, Outlet } from 'react-router-dom'
import { getHealth } from '../api/endpoints'
import { useAsync } from '../api/useAsync'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/system', label: 'System' },
] as const

export function AppLayout() {
  const health = useAsync((options) => getHealth(options), [])

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
          />
        </div>
      </aside>

      <main className="shell__main">
        <Outlet />
      </main>
    </div>
  )
}

interface BackendStatusProps {
  status: 'idle' | 'loading' | 'success' | 'error'
  version: string | null
  environment: string | null
}

function BackendStatus({ status, version, environment }: BackendStatusProps) {
  if (status === 'success') {
    return (
      <p className="status status--ok" data-testid="backend-status">
        <span className="status__dot" aria-hidden="true" />
        Backend {version} · {environment}
      </p>
    )
  }
  if (status === 'error') {
    return (
      <p className="status status--error" role="alert" data-testid="backend-status">
        <span className="status__dot" aria-hidden="true" />
        Backend unreachable
      </p>
    )
  }
  return (
    <p className="status status--pending" data-testid="backend-status">
      <span className="status__dot" aria-hidden="true" />
      Checking backend…
    </p>
  )
}
