/**
 * The log, and the only way to correct it.
 *
 * ## Two correction affordances, because there are two different guarantees
 *
 * Corrections are `void` entries: nothing is edited and nothing is deleted. But
 * **voiding the most recent entry always works, and voiding an older one may be
 * refused** — the log is replayed without the voided entry, and a later entry's
 * preconditions may no longer hold.
 *
 * The measurement behind offering both is in `draftBoardModel.ts`: across all
 * 27 events of the two seeded drafts, one fresh database per attempt, 4 voided
 * and **2 of those were not the most recent entry**. An "undo last only" screen
 * would have refused half the corrections the backend accepts. And a refused
 * void writes nothing, so attempting one costs the recorder nothing but the
 * round trip.
 *
 * So the last entry gets **Undo**, plainly, with no caveat — that is the
 * auction-clock path. Every earlier live entry gets **Try to void**, which says
 * in its own label that it may be refused. The screen does not promise more
 * than it can deliver, and it does not withhold what it can.
 *
 * ## The refusal is shown verbatim
 *
 * When a non-tail void is refused the backend now names the later entry that
 * stopped it: *"Voiding sequence 5 was refused because sequence 6, which comes
 * after it, no longer holds once it is gone: … Void back from the most recent
 * event instead."* That is better than any paraphrase, so it is printed as
 * given.
 *
 * It is worth recording what it replaced, because it is the reason this screen
 * does not attempt its own explanation. The same refusal used to read *"This
 * event must name the player as the recorder saw the name"* — a message about
 * an entry the recorder never posted, describing a field the void form does not
 * have. It read as a bug in the tool. The fix was upstream and belonged there.
 */

import { useState } from 'react'
import { appendDraftEvent } from '../api/draftEndpoints'
import { describeDraftError, isRetryableDraftError } from '../api/draftErrors'
import type { DraftState } from '../api/draftTypes'
import {
  describeEvent,
  splitRefusalRemedy,
  type DraftBoardModel,
  type LogRow,
} from './draftBoardModel'

/**
 * One auction roster's worth of recent activity.
 *
 * The existing draft screen is designed around 13 roster spots and browser
 * evidence measured roughly 11 log rows per laptop viewport. Thirteen keeps a
 * complete roster-sized tail available without returning to the 170-row,
 * fifteen-screen default this control replaces.
 */
export const RECENT_LOG_ENTRY_LIMIT = 13

interface DraftLogProps {
  model: DraftBoardModel
  onRecorded: (state: DraftState) => void
}

export function DraftLog({ model, onRecorded }: DraftLogProps) {
  const [pendingSequence, setPendingSequence] = useState<number | null>(null)
  const [failure, setFailure] = useState<{ sequence: number; error: Error } | null>(null)
  const [query, setQuery] = useState('')
  const [showFullHistory, setShowFullHistory] = useState(false)

  async function voidEntry(sequence: number) {
    setPendingSequence(sequence)
    setFailure(null)
    try {
      const next = await appendDraftEvent(model.state.id, {
        event_type: 'void',
        supersedes_sequence: sequence,
        expected_last_sequence: model.state.last_sequence,
      })
      onRecorded(next)
    } catch (cause) {
      setFailure({
        sequence,
        error: cause instanceof Error ? cause : new Error(String(cause)),
      })
    } finally {
      setPendingSequence(null)
    }
  }

  const rows = model.logRows
  const recentRows = rows.slice(-RECENT_LOG_ENTRY_LIMIT)
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const isSearching = normalizedQuery.length > 0
  const visibleRows = isSearching
    ? rows.filter((row) => logRowMatches(row, normalizedQuery))
    : showFullHistory
      ? rows
      : recentRows

  return (
    <section className="log" aria-labelledby="log-title">
      <h2 id="log-title">Log</h2>
      <p className="log__lede" data-testid="log-lede">
        Entries stay in recorded sequence order. The recent tail is shown by default; search and
        complete history use the whole log. <strong>Nothing here is ever edited.</strong> A
        correction is a new entry that withdraws an earlier one, so the original record survives
        alongside it.{' '}
        <strong>
          Undoing the most recent entry always works, unless it is itself a correction; undoing an
          older one may be refused
        </strong>{' '}
        — the log is replayed without it, and a later entry may no longer hold. Trying costs
        nothing: a refused correction records nothing at all.
      </p>

      {rows.length === 0 ? (
        <p className="state state--empty" data-testid="log-empty">
          Nothing has been recorded against this draft yet.
        </p>
      ) : (
        <>
          <div className="log__controls">
            <label className="log__search">
              <span>Search complete log</span>
              <input
                type="search"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value)
                }}
                placeholder="Sequence, event, player, or seat"
                aria-describedby="log-search-help log-results"
              />
            </label>
            <p className="log__search-help" id="log-search-help">
              Searches all recorded entries, including history outside the recent tail.
            </p>
            <div className="log__control-row">
              <p className="log__results" id="log-results" aria-live="polite" data-testid="log-count">
                {isSearching
                  ? `${String(visibleRows.length)} matching ${visibleRows.length === 1 ? 'entry' : 'entries'} from ${String(rows.length)} total.`
                  : showFullHistory
                    ? `Showing all ${String(rows.length)} entries.`
                    : `Showing ${String(visibleRows.length)} recent entries of ${String(rows.length)} total.`}
              </p>
              {!isSearching && (
                <button
                  type="button"
                  className="log__history-toggle"
                  aria-controls="draft-log-entries"
                  aria-expanded={showFullHistory}
                  onClick={() => {
                    setShowFullHistory((current) => !current)
                  }}
                >
                  {showFullHistory ? 'Show recent entries' : 'Show complete history'}
                </button>
              )}
            </div>
          </div>

          {isSearching && visibleRows.length === 0 ? (
            <p className="state state--empty" data-testid="log-no-results">
              No log entries match <strong>{query.trim()}</strong>. The complete log contains{' '}
              {rows.length} entries.
            </p>
          ) : (
            <ol
              className="log__list"
              id="draft-log-entries"
              data-testid="log-list"
              aria-label={
                isSearching
                  ? 'Matching draft log entries'
                  : showFullHistory
                    ? 'Complete draft log history'
                    : 'Recent draft log entries'
              }
            >
              {visibleRows.map((row) => (
                <LogEntry
                  key={row.event.sequence}
                  row={row}
                  isPending={pendingSequence === row.event.sequence}
                  anyPending={pendingSequence !== null}
                  failure={failure?.sequence === row.event.sequence ? failure.error : null}
                  onVoid={() => {
                    void voidEntry(row.event.sequence)
                  }}
                />
              ))}
            </ol>
          )}
        </>
      )}
    </section>
  )
}

function logRowMatches(row: LogRow, normalizedQuery: string): boolean {
  const sequenceQuery = /^(?:#|sequence\s+)?(\d+)$/.exec(normalizedQuery)
  if (sequenceQuery !== null) {
    return row.event.sequence === Number(sequenceQuery[1])
  }

  return [
    row.event.event_type,
    row.playerLabel ?? '',
    row.participantName ?? '',
  ].some((value) => value.toLocaleLowerCase().includes(normalizedQuery))
}

interface LogEntryProps {
  row: LogRow
  isPending: boolean
  anyPending: boolean
  failure: Error | null
  onVoid: () => void
}

function LogEntry({ row, isPending, anyPending, failure, onVoid }: LogEntryProps) {
  const { event, isVoided, correctability, correctabilityReason } = row
  const described = failure ? describeDraftError(failure) : null

  /*
   * A refused void needs the *server's* wording as its headline, not this
   * screen's copy for the error code.
   *
   * The code on a refused non-tail void does not describe the void. It describes
   * the precondition of the **later entry** that stopped it — so the code-keyed
   * copy is about a different event than the one the recorder acted on. Driven
   * in a browser against the live API: voiding entry 5 refuses with
   * `draft_player_label_required`, whose copy reads "This entry has to name the
   * player, as the recorder saw the name written." The void form has no player
   * field. The reader reads that headline first and looks for a field that is
   * not there.
   *
   * That is precisely the misreading the backend lane fixed upstream, and
   * leading with the code here would reintroduce it one layer down. The
   * backend's own sentence names the knock-on entry and what to do instead, and
   * it is already self-explanatory.
   *
   * The exception is a sequence conflict, which genuinely *is* about the void
   * that was posted, so its copy stays.
   */
  const codeDescribesThisAction = failure !== null && isRetryableDraftError(failure)
  const headline =
    failure === null
      ? null
      : codeDescribesThisAction
        ? (described?.summary ?? failure.message)
        : failure.message
  // Nothing is added beneath a refused void. The code-keyed *action* is about
  // the later entry too — driven in a browser, the refusal above rendered
  // "Type the player name and submit again" under a form with no player field,
  // which is the same misreading one line down. The backend's sentence already
  // ends with what to do instead, so this stays empty rather than filling the
  // space with copy that has to be about a different event.
  const supporting = codeDescribesThisAction ? (failure?.message ?? null) : null
  const showsSupporting = supporting !== null && supporting !== headline

  // Weight the instruction that works, without removing the one that does not.
  // Only ever applied to the backend's own sentence: this build's copy carries
  // no competing remedy to disambiguate.
  const { lead: headlineLead, remedy: headlineRemedy } =
    headline !== null && !codeDescribesThisAction
      ? splitRefusalRemedy(headline)
      : { lead: headline ?? '', remedy: null }

  return (
    <li
      className={isVoided ? 'log__entry log__entry--voided' : 'log__entry'}
      data-testid={`log-entry-${String(event.sequence)}`}
    >
      <div className="log__row">
        <span className="log__seq">#{event.sequence}</span>
        <span className="log__what">{describeEvent(row)}</span>

        {isVoided ? (
          <span className="log__badge" data-testid={`log-voided-${String(event.sequence)}`}>
            withdrawn by #{event.voided_by_sequence}
          </span>
        ) : null}

        {correctability === 'guaranteed' ? (
          <button
            type="button"
            className="log__undo log__undo--sure"
            onClick={onVoid}
            disabled={anyPending}
            data-testid={`log-undo-${String(event.sequence)}`}
          >
            {isPending ? 'Undoing…' : 'Undo'}
          </button>
        ) : null}

        {correctability === 'may-be-refused' ? (
          <button
            type="button"
            className="log__undo log__undo--maybe"
            onClick={onVoid}
            disabled={anyPending}
            data-testid={`log-tryvoid-${String(event.sequence)}`}
            title="Undoing an entry that is not the most recent may be refused, because the log is replayed without it."
          >
            {isPending ? 'Trying…' : 'Try to void'}
          </button>
        ) : null}
      </div>

      {event.note !== null ? <p className="log__note">{event.note}</p> : null}

      {correctabilityReason !== null ? (
        <p className="log__reason" data-testid={`log-reason-${String(event.sequence)}`}>
          {correctabilityReason}
        </p>
      ) : null}

      {failure !== null && headline !== null ? (
        <div className="log__failure state state--error" role="alert">
          {/* The backend's sentence, verbatim, as the thing read first. It names
              the later entry that stopped this correction and what to do
              instead; paraphrasing it would lose the sequence number, which is
              the only actionable part.

              Where the sentence carries two competing instructions, the one
              that works is weighted rather than extracted -- see
              `splitRefusalRemedy`. Nothing is dropped: the two spans
              concatenate to the original string. */}
          <p data-testid={`log-failure-${String(event.sequence)}`}>
            {headlineRemedy === null ? (
              headline
            ) : (
              <>
                {headlineLead}
                <strong
                  className="log__remedy"
                  data-testid={`log-remedy-${String(event.sequence)}`}
                >
                  {headlineRemedy}
                </strong>
              </>
            )}
          </p>
          {showsSupporting ? (
            <p className="state__detail" data-testid={`log-failure-backend-${String(event.sequence)}`}>
              {supporting}
            </p>
          ) : null}
          <p className="state__meta">Nothing was recorded. The log is unchanged.</p>
        </div>
      ) : null}
    </li>
  )
}
