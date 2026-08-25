/**
 * Reliability — what hoops-gm actually knows about availability.
 *
 * **This screen is mostly empty on purpose, and that is its content.**
 *
 * The project's central claim is that availability is the product. The
 * machinery behind that claim exists: `reliability-metrics` computes observed
 * play and non-play evidence, a monthly trend, back-to-back evidence, minutes
 * consistency and per-category dispersion, all with lineage. What does not
 * exist is a route carrying any of it to a browser — its own backlog entry ends
 * "no schema, API, or UI was added", and `docs/models/reliability-metrics.md`
 * says the same in the same words. So the quantities this screen is named for
 * are computed, current, and unreachable from here.
 *
 * Two options were available. Render the quantities from something else — a
 * heuristic, a proxy, the source's own assumption dressed as ours — or render
 * the gap. The first is how a dashboard ends up confidently wrong, which in
 * this project is the failure that does not crash: a plausible durability
 * number is indistinguishable from a real one until draft day. So the screen
 * shows the gap, names what would close each part of it, and shows the one
 * availability figure that genuinely is on the wire while saying whose it is.
 *
 * **Two independent reads, two independent boundaries.** The assumptions come
 * from the projections cohort and the schedule facts from the schedule cohort.
 * They are deliberately not merged into one load: they are different cohorts
 * with different lineage, and a single spinner over both would let one screen
 * imply they were read together when they were not.
 */

import { useMemo } from 'react'
import { getCurrentProjections, getScheduleGrid } from '../api/endpoints'
import { describeProjectionsError, isRetryableProjectionsError } from '../api/projectionsErrors'
import { describeScheduleGridError } from '../api/scheduleGridErrors'
import type { CurrentProjections, ScheduleGrid } from '../api/types'
import { useAsync } from '../api/useAsync'
import { AsyncBoundary } from '../components/AsyncBoundary'
import { AvailabilityAssumptionPanel } from '../components/AvailabilityAssumptionPanel'
import { EvidenceInventory } from '../components/EvidenceInventory'
import { buildProjectionsModel } from '../components/projectionsModel'
import { buildAvailabilitySummary, EVIDENCE_SEASON } from '../components/reliabilityModel'
import { SeasonNote } from '../components/SeasonNote'

/** ADR-001: one owner, one local league. A picker arrives with a second one. */
const LEAGUE_ID = 1

/**
 * Both cohorts change only when someone re-imports, so this is about the
 * reader's confidence that what is on screen came from this sitting rather than
 * about the underlying facts decaying. Matched to the projections screen for
 * the same reason it was chosen there.
 */
export const STALE_AFTER_MS = 5 * 60_000

export function ReliabilityPage() {
  const projections = useAsync((options) => getCurrentProjections(LEAGUE_ID, options), [], {
    shouldRetry: isRetryableProjectionsError,
  })
  const schedule = useAsync((options) => getScheduleGrid(LEAGUE_ID, options), [])

  return (
    <article className="page">
      <header className="page__header">
        <h1>Reliability</h1>
        <p className="page__lede">
          A 70-game player and a 55-game player with identical per-game lines are not the same
          asset. That claim is what this project is built around, and this is the screen where
          it is supposed to become checkable.{' '}
          <strong>Most of it is not checkable yet, and this screen says which parts.</strong>{' '}
          The durability evidence is computed by the backend and carried by no route, so nothing
          below is a placeholder waiting for a number to be dropped into it — where a quantity
          is missing, the reason is the content.
        </p>
        <p className="season-band" data-testid="season-band">
          <strong>Which season this is about.</strong> Availability evidence reads{' '}
          <strong data-testid="season-band-evidence">{EVIDENCE_SEASON}</strong> — the last
          completed season — because 2026-27 has no played games until late October and draft day
          is 18 October, so any durability figure that means anything before the draft is about
          last season. That is an endpoint-contract decision, not a toggle here. Each panel below
          names the season its own cohort was loaded for, and states how that relates to this one
          rather than leaving two labels sitting near each other to be conflated.
        </p>
      </header>

      <section className="reliability__section">
        <h2>The evidence inventory</h2>
        <EvidenceInventory />
      </section>

      <section className="reliability__section" data-testid="section-assumptions">
        <AsyncBoundary
          state={projections}
          label="the imported cohort's games-played assumptions"
          staleAfterMs={STALE_AFTER_MS}
          isEmpty={(data) => data.projections.length === 0}
          emptyMessage="The current import for this season carries no projection rows, so there are no games-played assumptions to describe. That is an empty cohort, not a failed request."
          describeError={describeProjectionsError}
        >
          {(data) => <AssumptionsView payload={data} />}
        </AsyncBoundary>
      </section>

      <section className="reliability__section" data-testid="section-schedule">
        <AsyncBoundary
          state={schedule}
          label="the schedule this evidence would be measured against"
          staleAfterMs={STALE_AFTER_MS}
          isEmpty={(data) => data.teams.length === 0}
          emptyMessage="The current schedule cohort carries no teams, so there is no season for availability evidence to be measured against."
          describeError={describeScheduleGridError}
        >
          {(data) => <ScheduleEvidenceView payload={data} />}
        </AsyncBoundary>
      </section>
    </article>
  )
}

function AssumptionsView({ payload }: { payload: CurrentProjections }) {
  // Derived from the projections model rather than from the payload directly,
  // so this screen and the projections screen cannot disagree about which
  // players are in the cohort or what the source said about them.
  const summary = useMemo(
    () => buildAvailabilitySummary(buildProjectionsModel(payload)),
    [payload],
  )

  return (
    <AvailabilityAssumptionPanel
      summary={summary}
      source={payload.source}
      season={payload.season}
    />
  )
}

/**
 * The season a cohort was loaded for, stated against the season evidence reads.
 *
 * Lives in `components/SeasonNote.tsx` — see there for why the relationship is
 * computed rather than left as two labels near each other.
 */

/**
 * The schedule cohort, framed as an availability question rather than a
 * scheduling one.
 *
 * The same facts appear on the Schedule screen, where they answer "how many
 * games does this team play this period?". Here they answer a different
 * question: **what can availability evidence even be measured against?** A
 * back-to-back is a claim about two dates, so a game with no date cannot be
 * classified as one in either direction — and that is a real, live limit on one
 * of the four quantities in the inventory above, not a hypothetical.
 */
function ScheduleEvidenceView({ payload }: { payload: ScheduleGrid }) {
  const { schedule } = payload.lineage
  // Two different facts that a review caught this screen conflating.
  //
  // `pending_game_ids` is **teams not yet decided** (ADR-013, and the route's
  // own docstring). It does *not* mean undated: in this cohort all six pending
  // games carry a date. The undated count is a separate quantity, carried per
  // game as `game_date === null` with a `date_absence_reason` beside it.
  //
  // The first version of this rendered `pending_game_ids.length` under the
  // label "Undated games" — a well-formed, plausible integer silently about a
  // different thing than the reader was told, which is the `gameEt` shape on
  // the one screen built to refuse it. Worse, the browser probe *agreed*: it
  // checked that the number on screen matched the number from the API, which
  // it did. Agreement on a value says nothing about agreement on its meaning.
  const teamsUndecided = schedule.pending_game_ids.length
  const undated = schedule.pending_games.filter((game) => game.game_date === null).length

  // Read from the payload rather than asserted. ADR-013 makes "pending means an
  // undrawn knockout bracket" a *falsifiable* reading, not a definition, which
  // is why ScheduleLineage renders the label per game so an operator can check
  // it. An earlier version of this row hard-coded "knockout fixtures whose
  // brackets are undrawn" and would have kept asserting it after it stopped
  // being true — the one thing ADR-013 asks a consumer to watch for.
  const pendingLabels = [
    ...new Set(
      schedule.pending_games.map((game) => game.game_label).filter((label) => label !== ''),
    ),
  ].join(', ')

  return (
    <section className="assumptions" data-testid="schedule-evidence">
      <h2>The season this would be measured against</h2>

      <p className="page__lede">
        Availability evidence is a statement about scheduled games, so the schedule bounds what
        can be observed at all. This is the cohort currently loaded, read from the same lineage
        block the Schedule screen renders.
      </p>

      <SeasonNote season={payload.season} testId="schedule-evidence-split" />

      <dl className="facts assumptions__facts">
        <div className="facts__row">
          <dt>Season</dt>
          <dd data-testid="schedule-evidence-season">
            <code>{payload.season}</code> · {payload.teams.length} teams ·{' '}
            {payload.periods.length} scoring periods
          </dd>
        </div>
        <div className="facts__row">
          <dt>Games</dt>
          <dd data-testid="schedule-evidence-games">
            {schedule.source_game_count} published by the source · {schedule.resolved_game_count}{' '}
            resolved into this cohort · {schedule.persisted_team_row_count} team-rows
          </dd>
        </div>
        <div className="facts__row">
          <dt>Teams not yet decided</dt>
          <dd data-testid="schedule-evidence-pending">
            {teamsUndecided === 0 ? (
              'Every published game has both teams assigned.'
            ) : (
              <>
                <strong>{teamsUndecided}</strong> published game
                {teamsUndecided === 1 ? ' has' : 's have'} no teams assigned yet
                {pendingLabels === '' ? '' : `, all labelled ${pendingLabels}`}. A game with no
                teams cannot be attributed to any team&rsquo;s calendar, so none of them can be
                classified as a back-to-back in either direction.
              </>
            )}
          </dd>
        </div>
        <div className="facts__row">
          <dt>Undated games</dt>
          <dd data-testid="schedule-evidence-undated">
            {undated === 0 ? (
              'No scheduled game is missing a date, so no game is excluded from back-to-back classification for want of one.'
            ) : (
              <>
                <strong>{undated}</strong> of those {teamsUndecided} also
                {undated === 1 ? ' carries' : ' carry'} no date. This is a subset of the row above,
                not a further count — a back-to-back is a claim about two dates, so these are
                blocked twice over rather than blocking two different games.
              </>
            )}
          </dd>
        </div>
        <div className="facts__row">
          <dt>Observed games</dt>
          <dd data-testid="schedule-evidence-observed">
            {/* The load-bearing sentence on this screen. It is stated as a
                property of the API rather than as a claim about the season,
                because this client cannot see the participation ledger and
                should not pretend to know what is in it. */}
            <strong>Not on the API.</strong> No route serves observed participation, so this
            screen cannot say how many of these games have been played, let alone who played
            them. Everything in the inventory above depends on that, and none of it can be
            derived from the schedule alone.
          </dd>
        </div>
        <div className="facts__row">
          <dt>Schedule cohort</dt>
          <dd>
            refresh {schedule.refresh_id} · version <code>{schedule.version}</code> · refreshed{' '}
            <code>{schedule.refreshed_at}</code>
          </dd>
        </div>
      </dl>
    </section>
  )
}
