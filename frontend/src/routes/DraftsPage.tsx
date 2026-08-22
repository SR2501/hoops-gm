/**
 * Every recorded draft, newest first.
 *
 * Deliberately thin. It exists so the board is reachable without typing an id
 * into the URL, and it is not a management surface: creating a draft fixes its
 * seats and its format permanently and neither can be changed afterwards, which
 * is a decision that wants more care than a screen built the night before a
 * mock can honestly give it. Creation stays with the seed script and the API
 * until someone can design the seat setup properly.
 */

import { Link } from 'react-router-dom'
import { getDrafts } from '../api/draftEndpoints'
import { describeDraftError } from '../api/draftErrors'
import type { DraftList } from '../api/draftTypes'
import { useAsync } from '../api/useAsync'
import { AsyncBoundary } from '../components/AsyncBoundary'

export function DraftsPage() {
  const drafts = useAsync<DraftList>((options) => getDrafts(options), [])

  return (
    <article className="page">
      <header className="page__header">
        <h1>Drafts</h1>
        <p className="page__lede">
          Every draft recorded on this machine. A draft is an append-only log of what was watched
          happening; opening one shows the board derived from it.
        </p>
      </header>

      <AsyncBoundary
        state={drafts}
        label="the recorded drafts"
        isEmpty={(data) => data.drafts.length === 0}
        emptyMessage="No drafts have been recorded in this database. That is an empty database, not a failed request — seed one with `python -m hoops_gm.dev.seed_draft`, or create a draft through the API."
        describeError={describeDraftError}
      >
        {(data) => (
          <ul className="drafts__list" data-testid="drafts-list">
            {data.drafts.map((draft) => (
              <li key={draft.id} className="drafts__item">
                <Link to={`/draft/${String(draft.id)}`} className="drafts__link">
                  {draft.name}
                </Link>
                <span className="drafts__meta">
                  {draft.format.draft_type} · {draft.format.team_count} teams ·{' '}
                  {draft.selections_made} of {draft.format.total_roster_slots} slots ·{' '}
                  {draft.status.replace('_', ' ')}
                  {draft.is_mock ? ' · mock' : ' · real'}
                </span>
              </li>
            ))}
          </ul>
        )}
      </AsyncBoundary>
    </article>
  )
}
