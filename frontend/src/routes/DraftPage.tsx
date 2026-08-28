/**
 * The draft board — the screen the owner has open during his auction.
 *
 * **It recommends nothing.** No valuation, no suggested price, no inflation
 * figure, no `p(play)`, no ranking, no tiers, no value column. Those are
 * `quant`'s and every one of them is blocked upstream on work that has not
 * happened. The API publishes no decision numbers at all — verified by a
 * reviewer walking all 26 OpenAPI models and 67 fields against a list of 30
 * forbidden terms — so every number on this screen came out of a response
 * field, and this screen is not the layer that reintroduces them. The one piece
 * of arithmetic anywhere near it, `remaining_budget = budget - spent`, is the
 * backend's own identity over recorded facts and is passed through as the
 * string it arrived as.
 *
 * ## Polling, and why there is no stream
 *
 * `last_sequence` is a complete version token: append is the log's only
 * mutation, so everything at or below a sequence is immutable and two responses
 * carrying the same value describe the same draft. The backend deliberately
 * ships no SSE endpoint — an SSE generator holds a database session open for
 * the life of the connection, which is the failure mode most likely to bite
 * during the one hour of the year this must not break.
 *
 * So this polls, and it re-reads on a timer rather than diffing: the payload is
 * a whole board and `useAsync` retains it whole, which is what keeps a failed
 * refresh from mixing rows from two reads.
 *
 * It does, however, *compare* — one integer, not the payload. A poll that comes
 * back carrying the `last_sequence` it already had describes a draft that has
 * not moved, so the previous bundle is returned by identity and the memoised
 * board below skips re-rendering entirely. This is the use `last_sequence` was
 * published for; `draftTypes.ts` says so at the field, and nothing was doing it.
 * Retaining the payload whole and comparing a version token are compatible: the
 * comparison decides whether to *replace* the retained payload, never whether to
 * merge into it.
 *
 * **A failed refresh keeps the board on screen.** An empty board mid-auction is
 * worse than a slightly stale one, and `AsyncBoundary`'s warm path plus the
 * single-code retry policy are the two independent things that make it true.
 */

import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getDraft, getDraftEvents } from '../api/draftEndpoints'
import { describeDraftError, isRetryableDraftError } from '../api/draftErrors'
import type { DraftEvent, DraftState } from '../api/draftTypes'
import { useAsync } from '../api/useAsync'
import { AsyncBoundary } from '../components/AsyncBoundary'
import { DraftLog } from '../components/DraftLog'
import { DraftRecorder } from '../components/DraftRecorder'
import { DraftSeats } from '../components/DraftSeats'
import { buildDraftBoardModel } from '../components/draftBoardModel'

/**
 * How often the board re-reads.
 *
 * Two seconds because there is one recorder at one screen and the poll exists
 * to catch a write this tab did not make, not to animate. A read is a single
 * indexed query with no lock taken (ADR-014), so the cost is real but small,
 * and the alternative — a stream — trades it for a held session.
 */
export const POLL_INTERVAL_MS = 2000

/**
 * Past this, the board says how old it is.
 *
 * Much shorter than the read screens' five minutes, and for a different reason:
 * this is not about data going out of date upstream, it is about the recorder
 * knowing whether what they are looking at is this second's board. Under an
 * auction clock, six seconds of silence is worth saying out loud.
 */
export const STALE_AFTER_MS = 6000

interface DraftBundle {
  state: DraftState
  events: DraftEvent[]
}

export function DraftPage() {
  const params = useParams<{ draftId: string }>()
  const draftId = Number(params.draftId)

  // Split rather than guarded after the hook. Until 2026-08-27 the `useAsync`
  // below ran unconditionally and this refusal was rendered afterwards, so
  // `/draft/not-a-number` fired a `GET /api/v1/drafts/NaN` and then drew the
  // error. The screen looked correct either way and the wasted request was
  // visible only in the network log, which is why reading never found it; a
  // test asserting *no request was made* did.
  //
  // The restructure is behaviour-preserving for the polling path because
  // `DraftBoardLoader` mounts once for a valid id and stays mounted across a
  // draft change, so `lastBundleRef` survives exactly as it did — which is why
  // it is still keyed by draft id, and why that keying now has its own test.
  if (!Number.isInteger(draftId) || draftId <= 0) {
    return (
      <article className="page">
        <h1>Draft board</h1>
        <p className="state state--error" role="alert">
          <code>{params.draftId ?? '(none)'}</code> is not a draft id.
        </p>
      </article>
    )
  }

  return <DraftBoardLoader draftId={draftId} />
}

function DraftBoardLoader({ draftId }: { draftId: number }) {
  // A tick, bumped by the timer and by every append, so one effect drives both
  // the scheduled re-read and the immediate one after a write.
  const [tick, setTick] = useState(0)
  const refresh = useCallback(() => {
    setTick((value) => value + 1)
  }, [])

  // The last bundle handed out, with the version token it was built from. Keyed
  // by draft id as well, so navigating between drafts cannot match a sequence
  // number from a different log — they are per-draft counters, and draft 3's
  // entry 170 is not draft 2's.
  const lastBundleRef = useRef<{ draftId: number; sequence: number; bundle: DraftBundle } | null>(
    null,
  )

  const draft = useAsync<DraftBundle>(
    async (options) => {
      // Both reads, then the pair is held together. `last_sequence` on the
      // events response is the end of the *whole* log, so the two can be
      // checked against each other rather than assumed to agree.
      const state = await getDraft(draftId, options)
      const page = await getDraftEvents(draftId, options)

      // Unmoved log, unchanged draft: hand back the very same object so
      // `setData` bails out and the memoised board is skipped.
      const previous = lastBundleRef.current
      if (
        previous !== null &&
        previous.draftId === draftId &&
        previous.sequence === page.last_sequence
      ) {
        return previous.bundle
      }

      const bundle = { state, events: page.events }
      lastBundleRef.current = { draftId, sequence: page.last_sequence, bundle }
      return bundle
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
    <article className="page page--draft">
      <AsyncBoundary
        state={draft}
        label="the draft board"
        staleAfterMs={STALE_AFTER_MS}
        describeError={describeDraftError}
      >
        {(bundle) => <DraftBoardView bundle={bundle} onRecorded={refresh} />}
      </AsyncBoundary>
    </article>
  )
}

/**
 * Memoised on the bundle's identity, which is what makes the version-token
 * comparison above worth anything. Without this the board re-renders on every
 * poll regardless, because `useAsync` sets `fetchedAt` and `status` each time
 * and those changes reach this component's parent no matter what `data` does.
 * The two changes only work as a pair.
 */
const DraftBoardView = memo(function DraftBoardView({
  bundle,
  onRecorded,
}: {
  bundle: DraftBundle
  onRecorded: () => void
}) {
  // Built fresh from the bundle rather than memoised on the state object: an
  // append replaces the whole bundle, and a stale model here would show a board
  // one entry behind the log beside it.
  const model = buildDraftBoardModel(bundle.state, bundle.events)
  const { state } = model

  return (
    <>
      <header className="page__header">
        <h1>{state.name}</h1>
        <p className="page__lede">
          A record of what happened, derived from an append-only log on every read.{' '}
          <strong>This screen recommends nothing.</strong> There is no valuation, no suggested
          price, no inflation figure and no availability estimate here, because none of them exist
          yet — see <code>docs/decisions/ADR-002-production-vs-availability.md</code>. Every number
          below is either something that was recorded or the backend&apos;s own subtraction over
          things that were recorded.
        </p>
        <ul className="page__facts">
          <li>
            {state.format.draft_type} · {state.format.team_count} teams ·{' '}
            {state.format.roster_size} roster
            {state.format.auction_budget !== null ? ` · $${state.format.auction_budget}` : ''}
          </li>
          <li data-testid="draft-progress">
            {state.selections_made} of {state.total_roster_slots} slots recorded
          </li>
          <li data-testid="draft-sequence">
            log at entry {state.last_sequence} · {state.live_event_count} in force ·{' '}
            {state.voided_sequences.length} withdrawn
          </li>
          <li>
            {state.is_mock ? 'Mock draft' : 'Real draft'} · tool usage recorded as{' '}
            <code>{state.tool_usage}</code>
          </li>
          <li>
            <Link to={`/draft/${String(state.id)}/categories`} data-testid="draft-categories-link">
              League category table
            </Link>{' '}
            — every seat ranked 1-to-N in each category, on published per-game rates only
          </li>
        </ul>
        {state.notes !== null ? <p className="page__note">{state.notes}</p> : null}
      </header>

      {/* Published rather than resolved: the snapshot stays authoritative, so
          the screen says the prices were paid under a different configuration
          instead of quietly relabelling them. */}
      {state.league_format_drift !== null ? (
        <p className="state state--error" role="status" data-testid="draft-drift">
          The league&apos;s settings no longer match the configuration this draft was recorded
          under. What is shown below is the frozen snapshot, which is what the prices were actually
          paid against.
          {state.league_format_drift.error !== null
            ? ` The league row also could not be read as a format: ${state.league_format_drift.error}`
            : ''}
        </p>
      ) : null}

      {/* An unresolved name is still a real selection. Reporting the count
          rather than hiding the rows, because a screen that silently dropped
          them would show a draft that did not happen. */}
      {state.unresolved_player_count > 0 ? (
        <p className="page__note" data-testid="draft-unresolved">
          {state.unresolved_player_count} of the selections below are recorded under a name the
          player crosswalk has not matched to a known player. They are shown exactly as they were
          typed. <strong>This is not a fault</strong> — it is what a name typed under a clock looks
          like before anything has resolved it, and the selection is real either way.
        </p>
      ) : null}

      <div className="draft__panels">
        <DraftRecorder model={model} onRecorded={onRecorded} onAttempted={onRecorded} />
        {/*
          The seats and the log share the right column so that the recorder's
          sticky containing block spans both. With the log as a sibling of
          `draft__panels`, a full 156-slot board ran to 11,037px and the
          recorder — the one panel that has to be reachable under an auction
          clock — was off screen for 11 of the 15.3 screens.
        */}
        <div className="draft__stream">
          <DraftSeats model={model} />
          <DraftLog model={model} onRecorded={onRecorded} />
        </div>
      </div>
    </>
  )
})
