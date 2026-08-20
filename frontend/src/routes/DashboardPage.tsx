/**
 * Dashboard — the landing surface.
 *
 * Phase 1 has no numbers to show yet, so it does not pretend to. It shows what
 * is actually wired and what is not, because a dashboard full of placeholder
 * charts is the fastest way to lose track of what has really been built.
 */

import { Link } from 'react-router-dom'
import { AsyncBoundary } from '../components/AsyncBoundary'
import { getMeta } from '../api/endpoints'
import { useAsync } from '../api/useAsync'

const PLANNED_SURFACES = [
  { name: 'Live scorecard', phase: 'Phase 7', owner: 'frontend' },
  { name: 'Schedule & availability grid (availability-adjusted)', phase: 'Phase 6', owner: 'frontend' },
  { name: 'Reliability scorecards', phase: 'Phase 6', owner: 'frontend' },
  { name: 'Draft board', phase: 'Phase 9', owner: 'frontend' },
  { name: 'Stock watch', phase: 'Phase 6', owner: 'frontend' },
  { name: 'Trade lab', phase: 'Phase 12', owner: 'frontend' },
] as const

export function DashboardPage() {
  const meta = useAsync((options) => getMeta(options), [])

  return (
    <article className="page">
      <header className="page__header">
        <h1>Dashboard</h1>
        <p className="page__lede">
          The evidence surface. Every recommendation the overlay makes is checkable here.
        </p>
      </header>

      <section aria-labelledby="wired-heading">
        <h2 id="wired-heading">Wired up</h2>
        <AsyncBoundary state={meta} label="service metadata">
          {(data) => (
            <dl className="facts">
              <div className="facts__row">
                <dt>Service</dt>
                <dd>
                  {data.service} {data.version}
                </dd>
              </div>
              <div className="facts__row">
                <dt>Environment</dt>
                <dd>{data.environment}</dd>
              </div>
              <div className="facts__row">
                <dt>Season</dt>
                <dd>{data.season}</dd>
              </div>
              <div className="facts__row">
                <dt>Entity groups</dt>
                <dd>{data.entity_groups.join(', ')}</dd>
              </div>
            </dl>
          )}
        </AsyncBoundary>
      </section>

      <section aria-labelledby="planned-heading">
        <h2 id="planned-heading">Not built yet</h2>
        <p className="page__note">
          Listed so the gap between the plan and the code stays visible. See <code>docs/plan.md</code>.
          The <Link to="/schedule">schedule grid</Link> is built and shows raw per-period game
          counts; the availability-adjusted grid below is a separate, later surface (ADR-012).
        </p>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Surface</th>
              <th scope="col">Phase</th>
              <th scope="col">Owner</th>
            </tr>
          </thead>
          <tbody>
            {PLANNED_SURFACES.map((surface) => (
              <tr key={surface.name}>
                <td>{surface.name}</td>
                <td>{surface.phase}</td>
                <td>
                  <code>{surface.owner}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </article>
  )
}
