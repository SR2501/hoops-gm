/**
 * The live league category table, for one draft.
 *
 * The owner named this twice and it had never had a backlog item
 * (`docs/what-draft-day-looks-like.md`, "Named by him, and not in the backlog",
 * item 1). Q4 wants it while he is nominating; Q9 wants it when he is halfway
 * through and over budget.
 *
 * ## Why this is its own route rather than a panel on the draft board
 *
 * Q1: *"Laptop with at least one external monitor."* A nine-column,
 * twelve-row table wants width the draft board does not have to spare, and the
 * recorder's sticky panel already lost that argument once — a full 156-slot
 * board ran to 11,037px and pushed the one control that has to be reachable
 * under an auction clock off screen. A second tab on a second monitor is the
 * arrangement he described, and it keeps `DraftPage`'s "this screen recommends
 * nothing" invariant intact rather than making that sentence negotiate with a
 * ranking.
 *
 * ## Two requests, one of which is allowed to fail
 *
 * The draft state is required — without seats there is no table. The projection
 * cohort is **not**: a league with no released import answers `404` or `409`,
 * and the seats, their holdings and the join counts are all still true facts
 * worth drawing. So the projections failure is caught and carried as a value,
 * and the page renders the roster shape with an explicit "no cohort" banner
 * instead of a blank screen. An empty board mid-auction is worse than a partial
 * one, which is the same reasoning `AsyncBoundary`'s warm path exists for.
 *
 * The league is taken from `state.league_id`, not from the `LEAGUE_ID = 1`
 * constant the other screens hardcode. That is not tidiness: in the seeded demo
 * the drafts are in leagues 2 and 3 while the schedule and projection screens
 * are league 1, so a hardcoded league here would join a league-2 draft against
 * a league-1 cohort and rank seats on another league's players without anything
 * on screen looking wrong.
 */

import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getDraft } from '../api/draftEndpoints'
import { describeDraftError, isRetryableDraftError } from '../api/draftErrors'
import type { DraftState } from '../api/draftTypes'
import { getCurrentProjections } from '../api/endpoints'
import { describeProjectionsError } from '../api/projectionsErrors'
import type { CurrentProjections } from '../api/types'
import { useAsync } from '../api/useAsync'
import { AsyncBoundary } from '../components/AsyncBoundary'
import { LeagueCategoryTable, OwnerCategoryStanding } from '../components/LeagueCategoryTable'
import {
  buildLeagueCategoryModel,
  CATEGORIES,
  CATEGORY_SOURCE,
} from '../components/leagueCategoryModel'

/**
 * Slower than the draft board's two seconds, deliberately.
 *
 * This screen answers "what shape is the league" rather than "what just
 * happened", and it costs two requests where the board costs two cheap ones
 * against the same table. Six seconds is still well inside a two-minute
 * nomination clock (Q3).
 */
export const POLL_INTERVAL_MS = 6000

/** Past this, the page says how old it is. Matched to the draft board's. */
export const STALE_AFTER_MS = 15000

interface CategoryBundle {
  state: DraftState
  projections: CurrentProjections | null
  /** The projections failure, when there was one. The draft is still drawn. */
  projectionsError: Error | null
}

export function CategoriesPage() {
  const params = useParams<{ draftId: string }>()
  const draftId = Number(params.draftId)

  // Split rather than guarded-after-the-hook, which is what `DraftPage` does
  // and is why `/draft/not-a-number` fires a `GET /api/v1/drafts/NaN` before
  // rendering the refusal. Caught here by a test asserting no request was made,
  // not by reading: the screen looks correct either way, and the wasted request
  // is only visible in the network log. The same defect is still live on the
  // draft board, recorded in `docs/handoff.md` rather than fixed from this lane
  // — that component's fetcher carries polling identity semantics this change
  // has no business disturbing.
  if (!Number.isInteger(draftId) || draftId <= 0) {
    return (
      <article className="page">
        <h1>League categories</h1>
        <p className="state state--error" role="alert">
          <code>{params.draftId ?? '(none)'}</code> is not a draft id.
        </p>
      </article>
    )
  }

  return <CategoriesLoader draftId={draftId} />
}

function CategoriesLoader({ draftId }: { draftId: number }) {
  const [tick, setTick] = useState(0)
  const refresh = useCallback(() => {
    setTick((value) => value + 1)
  }, [])

  const bundle = useAsync<CategoryBundle>(
    async (options) => {
      const state = await getDraft(draftId, options)
      try {
        const projections = await getCurrentProjections(state.league_id, options)
        return { state, projections, projectionsError: null }
      } catch (cause) {
        // Rethrown only for an abort, which is this component unmounting rather
        // than the cohort being unavailable. Everything else is a fact about
        // the league worth putting on screen.
        if (options.signal.aborted) throw cause
        return {
          state,
          projections: null,
          projectionsError: cause instanceof Error ? cause : new Error(String(cause)),
        }
      }
    },
    [draftId, tick],
    { shouldRetry: isRetryableDraftError },
  )

  useEffect(() => {
    const timer = setInterval(refresh, POLL_INTERVAL_MS)
    return () => {
      clearInterval(timer)
    }
  }, [refresh])

  return (
    <article className="page page--categories">
      <AsyncBoundary
        state={bundle}
        label="the league category table"
        staleAfterMs={STALE_AFTER_MS}
        describeError={describeDraftError}
      >
        {(data) => <CategoriesView bundle={data} draftId={draftId} />}
      </AsyncBoundary>
    </article>
  )
}

function CategoriesView({ bundle, draftId }: { bundle: CategoryBundle; draftId: number }) {
  const model = buildLeagueCategoryModel(bundle.state, bundle.projections)
  const { state } = bundle

  return (
    <>
      <header className="page__header">
        <h1>League categories · {state.name}</h1>
        <p className="page__lede">
          {/* "1-to-0" is not a range. A board where nothing joined is the state
              the seeded demo actually shows, so the sentence has to survive it
              rather than degrade into a number that reads like a bug. */}
          {model.rankedSeatCount > 0
            ? `Every seat ranked 1-to-${String(model.rankedSeatCount)} in each of the nine categories, on `
            : 'Seats are ranked in each of the nine categories on '}
          <strong>the sum of the per-game rates the projection source published</strong> for the
          players it currently holds. That is the only arithmetic on this page: addition, and
          division for the two percentages.
        </p>
        <p className="page__lede">
          <strong>This is not expected performance.</strong> Expected performance is production
          fused with expected games played, and that fusion is permitted at exactly one seam —{' '}
          <code>expected-games</code> — which is not built. <code>p(play)</code> does not exist
          either. So a fragile star and a durable one are counted identically here, which is the
          exact mistake this project exists to stop making. See{' '}
          <code>docs/decisions/ADR-002-production-vs-availability.md</code>.
        </p>
        <ul className="page__facts">
          <li>
            {state.format.team_count} seats · {state.selections_made} of{' '}
            {state.total_roster_slots} slots recorded
          </li>
          <li data-testid="category-join">
            {model.join.joinedPlayers} of {model.join.totalHoldings} selections joined to a
            projection row
            {model.join.unresolvedHoldings > 0
              ? ` · ${String(model.join.unresolvedHoldings)} carry no player id`
              : ''}
            {model.join.unmatchedHoldings > 0
              ? ` · ${String(model.join.unmatchedHoldings)} not in the cohort`
              : ''}
          </li>
          <li>
            <Link to={`/draft/${String(draftId)}`}>Back to the draft board</Link>
          </li>
        </ul>
      </header>

      {bundle.projectionsError !== null ? (
        <p className="state state--error" role="status" data-testid="category-no-cohort">
          No projection cohort could be read for league {state.league_id}, so every category
          below is unranked. The seats and their selections are still exactly what was recorded.{' '}
          {describeProjectionsError(bundle.projectionsError).summary}
        </p>
      ) : null}

      {model.scoringTypeMismatch ? (
        <p className="state state--error" role="alert" data-testid="category-scoring-mismatch">
          The projection source states its numbers assume{' '}
          <code>{model.assumedScoringType}</code>, which is not a category format. Ranking a
          points-league projection across nine categories is wrong in a way nothing downstream
          can see, so treat everything below as unusable until the import is replaced.
        </p>
      ) : null}

      {bundle.projections !== null && model.assumedScoringType === null ? (
        <p className="page__note" role="status" data-testid="category-scoring-unstated">
          The projection source did not state what scoring format its numbers assume. That is
          published as absent rather than defaulted to this league&apos;s format, so the nine
          categories below are being applied to numbers nobody has confirmed were produced for
          them.
        </p>
      ) : null}

      {model.emptyReason?.kind === 'nothing-joined' ? (
        <p className="state state--error" role="status" data-testid="category-nothing-joined">
          None of the {model.join.totalHoldings} recorded selections could be joined to a
          projection row, so no seat can be ranked.{' '}
          {model.emptyReason.unresolved > 0
            ? `${String(model.emptyReason.unresolved)} of them carry no player id — the log recorded a typed name and the player crosswalk has not matched it. `
            : ''}
          {model.emptyReason.unmatched > 0
            ? `${String(model.emptyReason.unmatched)} name a player id the projection cohort does not carry. `
            : ''}
          <strong>Nothing here is matched by name.</strong> A browser guessing which projection
          row a typed name meant would attribute one player&apos;s rates to another and rank a
          seat on them.
        </p>
      ) : null}

      {model.emptyReason?.kind === 'no-holdings' ? (
        <p className="page__note" role="status" data-testid="category-no-holdings">
          No selections have been recorded in this draft yet, so there is nothing to aggregate.
        </p>
      ) : null}

      <OwnerCategoryStanding model={model} />

      <p className="page__note grid__key">
        <span className="grid__key-item">
          <span className="catgrid__key-swatch catgrid__cell--tier1">1st</span>
          <span className="catgrid__key-swatch catgrid__cell--tier3">mid</span>
          <span className="catgrid__key-swatch catgrid__cell--tier5">last</span> Red through
          green by <strong>rank position</strong>, not by distance from an average — a spread is
          a distribution statistic and this page computes none. The rank is written in every cell
          as well as coloured.
        </span>
        <span className="grid__key-item">
          <strong>Players</strong> is how many of a seat&apos;s selections joined to a projection
          row. <strong>Totals are not depth-adjusted:</strong> a seat holding five players
          outranks one holding three on a sum for that reason alone. Correcting for it means
          projecting the players nobody has drafted yet, which is a model this page is not.
        </span>
        <span className="grid__key-item">
          <strong>FG% and FT%</strong> are Σ made ÷ Σ attempted across the seat, never a mean of
          player percentages, and the attempt volume is printed beside each one. A 90% free-throw
          shooter on one attempt moves a seat&apos;s ratio by almost nothing, which is the
          behaviour that makes the aggregate honest.
        </span>
        <span className="grid__key-item">
          <strong>TO ranks in reverse</strong> — fewest turnovers is 1st.
        </span>
        <span className="grid__key-item">
          <span className="catgrid__key-swatch catgrid__cell--nodata">·</span> the seat has
          nothing to aggregate in this category. It is shown as{' '}
          <strong>unranked, not last</strong>: no data and worst are different claims.
        </span>
        <span className="grid__key-item">
          A <code>−n</code> in a cell counts joined players who did not publish that quantity and
          are therefore absent from the total. <strong>Not zero</strong> — the wire contract says
          a null rate means the source published nothing.
        </span>
        <span className="grid__key-item">
          The nine categories are taken from <code>{CATEGORY_SOURCE}</code>, which describes
          itself as historical and <strong>not verified for 2026-27</strong>. No endpoint
          publishes this league&apos;s scoring settings, so there is nothing to check them
          against. {CATEGORIES.map((category) => category.label).join(' · ')}
        </span>
      </p>

      <LeagueCategoryTable model={model} />
    </>
  )
}
