/**
 * Every recorded draft, newest first.
 *
 * The calm setup surface and every recorded draft, newest first.
 *
 * Creation lives here rather than on the board because the league, evidence
 * declaration, owner binding, and every participant slot become immutable.
 * Those are setup decisions, not controls to carry under an auction clock.
 */

import { Link, useNavigate } from 'react-router-dom'
import { getDraftSetup, getDrafts } from '../api/draftEndpoints'
import { describeDraftError } from '../api/draftErrors'
import type { DraftList, DraftSetupResponse } from '../api/draftTypes'
import { useAsync } from '../api/useAsync'
import { AsyncBoundary } from '../components/AsyncBoundary'
import { DraftSetupForm } from '../components/DraftSetupForm'

export function DraftsPage() {
  const navigate = useNavigate()
  const setup = useAsync<DraftSetupResponse>((options) => getDraftSetup(options), [])
  const drafts = useAsync<DraftList>((options) => getDrafts(options), [])

  return (
    <article className="page page--drafts">
      <header className="page__header">
        <h1>Drafts</h1>
        <p className="page__lede">
          Create a board from persisted league evidence, or open a draft already recorded on this
          machine. Creation freezes the setup; the board remains an append-only account of what
          happened.
        </p>
      </header>

      <section className="draft-setup" aria-labelledby="draft-setup-title">
        <h2 id="draft-setup-title">Create a draft</h2>
        <p className="page__note">
          Choose the league first, then bind every persisted fantasy team to an explicit local
          slot. This screen never turns display order into draft or source-seat evidence.
        </p>
        <AsyncBoundary
          state={setup}
          label="draft setup evidence"
          isEmpty={(data) => data.leagues.length === 0}
          emptyMessage="No persisted league can create a draft yet. Import league settings and fantasy teams, then retry; no setup values are guessed."
          describeError={describeDraftError}
        >
          {(data) => (
            <DraftSetupForm
              leagues={data.leagues}
              onCreated={(draftId) => {
                void navigate(`/draft/${String(draftId)}`)
              }}
              onCreationUncertain={drafts.reload}
            />
          )}
        </AsyncBoundary>
      </section>

      <section className="drafts__recorded" aria-labelledby="recorded-drafts-title">
        <h2 id="recorded-drafts-title">Recorded drafts</h2>
        <AsyncBoundary
          state={drafts}
          label="the recorded drafts"
          isEmpty={(data) => data.drafts.length === 0}
          emptyMessage="No drafts have been recorded in this database. Use the setup form above to create the first board."
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
      </section>
    </article>
  )
}
