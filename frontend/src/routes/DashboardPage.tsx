import { Link } from 'react-router-dom'
import { getDrafts } from '../api/draftEndpoints'
import { describeDraftError } from '../api/draftErrors'
import type { DraftList, DraftSummary } from '../api/draftTypes'
import { useAsync } from '../api/useAsync'
import { AsyncBoundary } from '../components/AsyncBoundary'

const SURFACES = [
  {
    name: 'Drafts',
    to: '/draft',
    kind: 'Working surface',
    description:
      'Recorded snake and auction boards. They show observed draft state and support manual recording; they do not recommend a player or price.',
  },
  {
    name: 'Projections',
    to: '/projections',
    kind: 'Evidence only',
    description:
      'Published per-game source evidence and lineage. The route can still report that this database has no released projection cohort.',
  },
  {
    name: 'Reliability',
    to: '/reliability',
    kind: 'Evidence only',
    description:
      'An inventory of the durability and availability evidence that is reachable now, including explicit blockers. It publishes no reliability score.',
  },
  {
    name: 'Schedule',
    to: '/schedule',
    kind: 'Evidence only',
    description:
      'Imported schedule counts and source status. These are raw schedule facts, not availability-adjusted expected games.',
  },
  {
    name: 'System',
    to: '/system',
    kind: 'Operations',
    description:
      'Database readiness and operational detail. Backend health remains visible in the shell on every route.',
  },
] as const

export function DashboardPage() {
  const drafts = useAsync<DraftList>((options) => getDrafts(options), [])

  return (
    <article className="page page--launchpad">
      <header className="page__header">
        <h1>Start here</h1>
        <p className="page__lede">
          Open the draft workspace or inspect the evidence already exposed by the backend. A
          reachable surface and a database with usable data are different things; each destination
          reports its own empty or refusal state.
        </p>
      </header>

      <section aria-labelledby="draft-launch-heading">
        <h2 id="draft-launch-heading">Draft workspace</h2>
        <p className="page__note">
          This section reads the current database&apos;s draft list. Direct links appear only for a
          draft returned by that endpoint; no draft or league id is assumed.
        </p>
        <AsyncBoundary
          state={drafts}
          label="the draft launch data"
          isEmpty={(data) => data.drafts.length === 0}
          emptyMessage="The draft surfaces exist, but this database has no recorded drafts. Open Drafts below for the available setup path."
          describeError={describeDraftError}
        >
          {(data) => <DraftLaunch drafts={data.drafts} />}
        </AsyncBoundary>
      </section>

      <nav aria-labelledby="surfaces-heading">
        <h2 id="surfaces-heading">Available surfaces</h2>
        <p className="page__note">
          Every route below is present now. Evidence-only means the screen explains source data and
          gaps; it does not produce a draft recommendation, valuation, or availability estimate.
        </p>
        <ul className="launchpad__surfaces">
          {SURFACES.map((surface) => (
            <li key={surface.to} className="launchpad__surface">
              <span className="launchpad__kind">{surface.kind}</span>
              <h3>
                <Link to={surface.to}>{surface.name}</Link>
              </h3>
              <p>{surface.description}</p>
            </li>
          ))}
        </ul>
      </nav>
    </article>
  )
}

function DraftLaunch({ drafts }: { drafts: DraftSummary[] }) {
  const currentAuction =
    drafts.find(
      (draft) => draft.status === 'in_progress' && draft.format.draft_type === 'auction',
    ) ?? null
  const launchDraft = currentAuction ?? drafts[0]

  if (!launchDraft) return null

  return (
    <div className="launchpad__draft" data-testid="draft-launch">
      <span className="launchpad__kind">
        {currentAuction ? 'In-progress auction' : 'Latest recorded draft'}
      </span>
      <h3>{launchDraft.name}</h3>
      <p className="launchpad__draft-meta">
        {launchDraft.format.draft_type} · {launchDraft.format.team_count} teams ·{' '}
        {launchDraft.selections_made} of {launchDraft.format.total_roster_slots} slots ·{' '}
        {launchDraft.status.replace('_', ' ')}
        {launchDraft.is_mock ? ' · mock' : ' · real'}
      </p>
      <nav className="launchpad__actions" aria-label={`${launchDraft.name} destinations`}>
        <Link to={`/draft/${String(launchDraft.id)}`}>
          {currentAuction ? 'Open auction board' : 'Open draft board'}
        </Link>
        <Link to={`/draft/${String(launchDraft.id)}/categories`}>Open league category rates</Link>
        <Link to="/draft">View all recorded drafts</Link>
      </nav>
      <p className="launchpad__caveat">
        The category table is evidence-only: it uses this draft&apos;s league and reports when that
        league has no usable projection cohort.
      </p>
    </div>
  )
}
