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

interface DraftLogProps {
  model: DraftBoardModel
  onRecorded: (state: DraftState) => void
}

export function DraftLog({ model, onRecorded }: DraftLogProps) {
  const [pendingSequence, setPendingSequence] = useState<number | null>(null)
  const [failure, setFailure] = useState<{ sequence: number; error: Error } | null>(null)

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

  // Newest first: under a clock the entry a recorder wants is the one that just
  // landed, and it is also the only one correction is guaranteed against.
  const rows = model.logRows.slice().reverse()

  return (
    <section className="log" aria-labelledby="log-title">
      <h2 id="log-title">Log</h2>
      <p className="log__lede">
        Every entry, in the order it was recorded. <strong>Nothing here is ever edited.</strong> A
        correction is a new entry that withdraws an earlier one, so the record of what was
        originally typed survives alongside it.{' '}
        <strong>Undoing the most recent entry always works; undoing an older one may be refused</strong>{' '}
        — the log is replayed without it, and a later entry may no longer hold. Trying costs
        nothing: a refused correction records nothing at all.
      </p>

      {rows.length === 0 ? (
        <p className="state state--empty" data-testid="log-empty">
          Nothing has been recorded against this draft yet.
        </p>
      ) : (
        <ol className="log__list" data-testid="log-list">
          {rows.map((row) => (
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
    </section>
  )
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
