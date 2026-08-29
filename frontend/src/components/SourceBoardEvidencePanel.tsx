import type { SourceBoardResponse } from '../api/draftTypes'
import { buildSourceBoardEvidenceModel } from './sourceBoardModel'

export function SourceBoardEvidencePanel({ evidence }: { evidence: SourceBoardResponse }) {
  const model = buildSourceBoardEvidenceModel(evidence)
  const { board, response } = model

  return (
    <section
      className="source-board"
      aria-labelledby="source-board-heading"
      data-testid="source-board-panel"
    >
      <header className="source-board__header">
        <div>
          <p className="source-board__eyebrow">Read-only · non-authoritative</p>
          <h2 id="source-board-heading">Rendered source-board evidence</h2>
        </div>
        <span className={`source-board__status source-board__status--${response.status}`}>
          {response.status.replace('_', ' ')}
        </span>
      </header>

      <p className="source-board__lede">
        This is a separate reading of rendered source columns. It does not alter or identify the
        participant/event board above. A source column number or displayed label does not establish
        who owns that column.
      </p>

      {response.status === 'no_reading' ? (
        <div className="source-board__notice" role="status" data-testid="source-board-no-reading">
          <strong>No source-board reading.</strong> The backend has neither accepted nor refused a
          rendered-board attempt for this draft. This is not an empty captured board.
        </div>
      ) : null}

      {response.status === 'refused' ? (
        <div
          className="source-board__notice source-board__notice--refused"
          role="alert"
          data-testid="source-board-refused"
        >
          <strong>Latest source-board attempt refused.</strong>{' '}
          {board === null
            ? 'No accepted board reading is available.'
            : 'The last accepted reading remains below; the refusal is not rendered as an empty board.'}
          {response.refusal_reason !== null ? (
            <span className="source-board__reason">
              Reason: <code>{response.refusal_reason}</code>
            </span>
          ) : null}
        </div>
      ) : null}

      <dl className="source-board__freshness" data-testid="source-board-freshness">
        <div>
          <dt>Board reading</dt>
          <dd>
            {model.boardAge === null ? (
              'No accepted reading'
            ) : (
              <>
                {model.boardAge} old ·{' '}
                <time dateTime={board?.observed_at}>{board?.observed_at}</time>
              </>
            )}
          </dd>
        </div>
        <div>
          <dt>Browser contact</dt>
          <dd>
            {model.contactAge === null ? (
              'No rendered-board contact'
            ) : (
              <>
                {model.contactAge} old ·{' '}
                <time dateTime={response.contact_at ?? undefined}>{response.contact_at}</time>
              </>
            )}
          </dd>
        </div>
        <div>
          <dt>Freshness clock</dt>
          <dd>
            Server at <time dateTime={response.as_of}>{response.as_of}</time>
          </dd>
        </div>
      </dl>

      {board !== null ? (
        <>
          <div className="source-board__summary">
            <strong>
              {board.picks_made} captured {board.picks_made === 1 ? 'pick' : 'picks'}
            </strong>
            <span>
              {board.seat_count} source columns · {board.round_count} rendered rounds · source layout{' '}
              <code>{board.layout}</code>
            </span>
          </div>

          {board.picks_made === 0 ? (
            <p className="source-board__notice" data-testid="source-board-empty">
              {response.status === 'refused'
                ? 'This retained accepted empty reading contains no picks. It remains visible beneath the refused latest attempt; it does not describe that refused attempt as an empty board.'
                : 'This accepted source reading contains no picks. It is an available empty board, not a no-reading or refusal state.'}
            </p>
          ) : null}

          <ol className="source-board__columns" data-testid="source-board-columns">
            {model.columns.map((column) => (
              <li
                className="source-board__column"
                key={column.sourceSeat}
                data-testid={`source-column-${String(column.sourceSeat)}`}
              >
                <h3>Source column {column.sourceSeat}</h3>
                <p className="source-board__mutable-label">
                  Mutable displayed label:{' '}
                  <strong>{column.mutableLabel ?? 'not present in this reading'}</strong>
                </p>
                {column.picks.length === 0 ? (
                  <p className="source-board__empty-column">No captured picks in this column.</p>
                ) : (
                  <ol className="source-board__picks">
                    {column.picks.map((pick) => (
                      <li key={`${String(pick.round_number)}-${String(pick.pick_in_round)}`}>
                        <span>{pick.player_label ?? 'Unnamed source pick'}</span>
                        <small>
                          Round {pick.round_number}, source pick {pick.pick_in_round}, overall{' '}
                          {pick.overall_pick}
                          {pick.player_external_id !== null
                            ? ` · source player id ${pick.player_external_id}`
                            : ''}
                        </small>
                      </li>
                    ))}
                  </ol>
                )}
              </li>
            ))}
          </ol>
        </>
      ) : null}

      <section
        className={`source-board__regressions${
          model.regressions.length > 0 ? ' source-board__regressions--present' : ''
        }`}
        aria-labelledby="source-board-regressions-heading"
      >
        <h3 id="source-board-regressions-heading">Board regressions</h3>
        {model.regressions.length === 0 ? (
          <p>No previously seen source slots are reported missing from the latest reading.</p>
        ) : (
          <details open={model.regressions.length <= 6}>
            <summary data-testid="source-board-regression-summary">
              {model.regressions.length} previously seen source{' '}
              {model.regressions.length === 1 ? 'slot is' : 'slots are'} absent from the latest
              reading. Earlier observations were not retracted.
            </summary>
            <ol data-testid="source-board-regressions">
              {model.regressions.map((item) => (
                <li
                  key={`${String(item.source_seat)}-${String(item.round_number)}-${String(
                    item.pick_in_round,
                  )}`}
                >
                  Source column {item.source_seat}, round {item.round_number}, source pick{' '}
                  {item.pick_in_round}: {item.player_label ?? 'unnamed source pick'} · last seen in{' '}
                  <code>{item.last_seen_artifact_key}</code>
                </li>
              ))}
            </ol>
          </details>
        )}
      </section>

      <section className="source-board__caveats" aria-labelledby="source-board-caveats-heading">
        <h3 id="source-board-caveats-heading">Limits of this evidence</h3>
        <ul data-testid="source-board-caveats">
          {response.caveats.map((caveat) => (
            <li key={caveat}>{caveat}</li>
          ))}
        </ul>
      </section>
    </section>
  )
}
