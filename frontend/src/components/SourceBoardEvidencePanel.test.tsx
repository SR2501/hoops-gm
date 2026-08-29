import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { SourceBoardResponse } from '../api/draftTypes'
import { SourceBoardEvidencePanel } from './SourceBoardEvidencePanel'

const caveats = [
  'source_seat is a rendered column ordinal, not DraftParticipant.team_slot or identity',
  'seat labels are mutable display evidence and are never matched to participants',
  'an exact-content undo reuses an existing artifact key and cannot appear as a new regression',
  'evidence is from one football snake draft; NBA and auction board support is unestablished',
]

function evidence(status: SourceBoardResponse['status']): SourceBoardResponse {
  return {
    draft_id: 1,
    as_of: '2026-08-29T18:03:00Z',
    status,
    refusal_reason: status === 'refused' ? 'board_refused:snapshot_truncated' : null,
    contact_at: status === 'no_reading' ? null : '2026-08-29T18:02:59Z',
    contact_age_seconds: status === 'no_reading' ? null : 1,
    board_age_seconds: status === 'no_reading' ? null : 180,
    board:
      status === 'no_reading'
        ? null
        : {
            artifact_key: 'board:now',
            recogniser: 'board_dom',
            observed_at: '2026-08-29T18:00:00Z',
            layout: 'snake',
            seat_count: 2,
            round_count: 2,
            picks_made: 2,
            columns: [
              {
                source_seat: 1,
                mutable_label: 'Mock Drafter 1',
                picks: [
                  {
                    source_seat: 1,
                    round_number: 1,
                    pick_in_round: 1,
                    overall_pick: 1,
                    player_label: 'Alpha Player',
                    player_external_id: 'alpha',
                  },
                ],
              },
              {
                source_seat: 2,
                mutable_label: 'Changed Label',
                picks: [
                  {
                    source_seat: 2,
                    round_number: 1,
                    pick_in_round: 2,
                    overall_pick: 2,
                    player_label: 'Beta Player',
                    player_external_id: null,
                  },
                ],
              },
            ],
          },
    regressions: [
      {
        source_seat: 2,
        round_number: 2,
        pick_in_round: 1,
        player_label: 'Missing Player',
        last_seen_artifact_key: 'board:before',
      },
    ],
    caveats,
  }
}

describe('source-board evidence panel', () => {
  it('renders available picks by source column with labels explicitly mutable', () => {
    render(<SourceBoardEvidencePanel evidence={evidence('available')} />)

    const columns = within(screen.getByTestId('source-board-columns')).getAllByRole('listitem', {
      hidden: false,
    })
    expect(columns.length).toBeGreaterThanOrEqual(2)
    expect(screen.getByTestId('source-column-1')).toHaveTextContent('Alpha Player')
    expect(screen.getByTestId('source-column-2')).toHaveTextContent('Beta Player')
    expect(screen.getByTestId('source-column-2')).toHaveTextContent(
      'Mutable displayed label: Changed Label',
    )
    expect(screen.getByText('Read-only · non-authoritative')).toBeInTheDocument()
    expect(screen.getByText(/does not establish who owns that column/i)).toBeInTheDocument()
  })

  it('shows board freshness separately from newer browser contact', () => {
    render(<SourceBoardEvidencePanel evidence={evidence('available')} />)

    const freshness = screen.getByTestId('source-board-freshness')
    expect(freshness).toHaveTextContent('Board reading3 minutes old')
    expect(freshness).toHaveTextContent('Browser contact1 second old')
    expect(freshness).toHaveTextContent('Freshness clockServer at 2026-08-29T18:03:00Z')
  })

  it('shows no-reading as absence of an attempt, never as an empty board', () => {
    render(<SourceBoardEvidencePanel evidence={evidence('no_reading')} />)

    expect(screen.getByTestId('source-board-no-reading')).toHaveTextContent(
      'neither accepted nor refused',
    )
    expect(screen.getByTestId('source-board-no-reading')).toHaveTextContent(
      'not an empty captured board',
    )
    expect(screen.queryByTestId('source-board-columns')).not.toBeInTheDocument()
  })

  it('shows refusal reason while retaining the last accepted board', () => {
    render(<SourceBoardEvidencePanel evidence={evidence('refused')} />)

    const refusal = screen.getByTestId('source-board-refused')
    expect(refusal).toHaveTextContent('Latest source-board attempt refused')
    expect(refusal).toHaveTextContent('board_refused:snapshot_truncated')
    expect(refusal).toHaveTextContent('last accepted reading remains below')
    expect(screen.getByTestId('source-column-1')).toHaveTextContent('Alpha Player')
  })

  it('names each regression and renders every API caveat', () => {
    render(<SourceBoardEvidencePanel evidence={evidence('available')} />)

    expect(screen.getByTestId('source-board-regression-summary')).toHaveTextContent(
      '1 previously seen source slot is absent',
    )
    expect(screen.getByTestId('source-board-regressions')).toHaveTextContent(
      'Source column 2, round 2, source pick 1: Missing Player',
    )
    const renderedCaveats = within(screen.getByTestId('source-board-caveats')).getAllByRole(
      'listitem',
    )
    expect(renderedCaveats).toHaveLength(caveats.length)
    expect(screen.getByTestId('source-board-caveats')).toHaveTextContent(
      'exact-content undo',
    )
    expect(screen.getByTestId('source-board-caveats')).toHaveTextContent(
      'NBA and auction board support is unestablished',
    )
  })

  it('contains no authoritative seat names, holdings, prices, or bank figures', () => {
    render(<SourceBoardEvidencePanel evidence={evidence('available')} />)

    const panel = screen.getByTestId('source-board-panel')
    expect(panel).not.toHaveTextContent('Load Management')
    expect(panel).not.toHaveTextContent('Trade Deadline')
    expect(panel).not.toHaveTextContent(/\$\d/)
    expect(panel).not.toHaveTextContent(/remaining bank/i)
    expect(panel).not.toHaveTextContent(/holding/i)
  })

  it('distinguishes an available zero-pick board from no-reading and refusal', () => {
    const empty = evidence('available')
    empty.board = { ...empty.board!, picks_made: 0, columns: [] }

    render(<SourceBoardEvidencePanel evidence={empty} />)

    expect(screen.getByTestId('source-board-empty')).toHaveTextContent(
      'available empty board, not a no-reading or refusal state',
    )
  })
})
