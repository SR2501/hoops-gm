import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { PROJECTION_RATE_FIELDS } from '../api/types'
import type { CurrentProjections, ProjectionRates } from '../api/types'
import { PROJECTION_PAGE_SIZE, ProjectionsBrowser } from './ProjectionsBrowser'
import { buildProjectionsModel } from './projectionsModel'

function rates(playerId: number, points: number): ProjectionRates {
  const row = { player_id: playerId } as ProjectionRates
  for (const field of PROJECTION_RATE_FIELDS) row[field] = 1
  row.points_per_game = points
  return row
}

function payload(): CurrentProjections {
  const projections = [rates(3, 20), rates(1, 30), rates(2, 20)]
  return {
    league_id: 1,
    season: '2026-27',
    source: 'basketball_monster',
    lineage: {
      blend: null,
      projection_import: {
        import_id: 3,
        source: 'basketball_monster',
        season: '2026-27',
        imported_at: '2026-08-19T12:00:00Z',
        content_sha256: 'a'.repeat(64),
        profile_id: 'basketball-monster',
        profile_version: '1',
        profile_definition_sha256: 'b'.repeat(64),
        projection_values_sha256: 'c'.repeat(64),
        projection_count: projections.length,
        assumed_scoring_type: null,
        original_filename: 'bbm.csv',
        row_count: projections.length,
        matched_count: projections.length,
        needs_review_count: 0,
        unmatched_count: 0,
        rejected_count: 0,
      },
    },
    players: [
      {
        player_id: 1,
        full_name: 'Alpha Player',
        team_abbreviation: 'BOS',
        primary_position: 'G',
      },
      {
        player_id: 2,
        full_name: 'Bravo Player',
        team_abbreviation: 'LAL',
        primary_position: 'F',
      },
      {
        player_id: 3,
        full_name: 'Charlie Player',
        team_abbreviation: 'BOS',
        primary_position: null,
      },
    ],
    projections,
    source_games_played_assumptions: [
      { player_id: 1, assumed_games_played: 70, assumed_games_played_raw: '70' },
      { player_id: 2, assumed_games_played: 60, assumed_games_played_raw: '60' },
      { player_id: 3, assumed_games_played: 65, assumed_games_played_raw: '65' },
    ],
  }
}

function renderedIds(): number[] {
  return screen
    .queryAllByTestId(/^projection-row-/)
    .map((row) => Number(row.getAttribute('data-testid')?.replace('projection-row-', '')))
}

describe('ProjectionsBrowser', () => {
  it('searches, filters, reports counts, and resets to every imported row', async () => {
    const user = userEvent.setup()
    const model = buildProjectionsModel(payload())
    const sourceOrder = model.rows.map((row) => row.playerId)
    render(<ProjectionsBrowser model={model} />)

    expect(screen.getByRole('status')).toHaveTextContent(
      'Showing 3 of 3 matches from 3 imported players',
    )
    await user.type(screen.getByRole('searchbox', { name: 'Search players' }), 'charlie')
    expect(renderedIds()).toEqual([3])
    expect(screen.getByRole('status')).toHaveTextContent(
      'Showing 1 of 1 matches from 3 imported players',
    )

    await user.selectOptions(screen.getByRole('combobox', { name: 'NBA team' }), 'LAL')
    expect(renderedIds()).toEqual([])
    expect(screen.getByText(/No imported players match/)).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(
      'Showing 0 of 0 matches from 3 imported players',
    )

    await user.click(screen.getByRole('button', { name: 'Reset view' }))
    expect(renderedIds()).toEqual(sourceOrder)
    expect(screen.getByRole('searchbox', { name: 'Search players' })).toHaveValue('')
    expect(screen.getByRole('combobox', { name: 'NBA team' })).toHaveValue('')
    expect(screen.getByRole('status')).toHaveTextContent(
      'Showing 3 of 3 matches from 3 imported players',
    )
    expect(screen.getByRole('button', { name: 'Reset view' })).toBeDisabled()
    expect(model.rows.map((row) => row.playerId)).toEqual(sourceOrder)
  })

  it('sorts through accessible headers, toggles direction, and exposes every rate', async () => {
    const user = userEvent.setup()
    render(<ProjectionsBrowser model={buildProjectionsModel(payload())} />)

    const points = screen.getByRole('button', { name: 'Sort by PTS per game ascending' })
    await user.click(points)
    expect(renderedIds()).toEqual([2, 3, 1])
    expect(points.closest('th')).toHaveAttribute('aria-sort', 'ascending')

    await user.click(screen.getByRole('button', { name: 'Sort by PTS per game descending' }))
    expect(renderedIds()).toEqual([1, 2, 3])
    expect(points.closest('th')).toHaveAttribute('aria-sort', 'descending')

    const table = screen.getByTestId('projections-table')
    for (const field of PROJECTION_RATE_FIELDS) {
      const header = within(table).getByTestId(`rate-header-${field}`)
      expect(within(header).getByRole('button')).toBeInTheDocument()
    }
    expect(within(table).queryByRole('button', { name: /Pos/ })).not.toBeInTheDocument()
  })

  it('progressively mounts a large sorted cohort without losing rows from the view', async () => {
    const user = userEvent.setup()
    const large = payload()
    const firstRate = large.projections[0]
    if (firstRate === undefined) throw new Error('expected a projection row')

    large.projections = Array.from({ length: PROJECTION_PAGE_SIZE + 1 }, (_, index) => ({
      ...firstRate,
      player_id: index + 1,
      points_per_game: PROJECTION_PAGE_SIZE - index,
    }))
    large.players = large.projections.map((row) => ({
      player_id: row.player_id,
      full_name: `Player ${String(row.player_id).padStart(3, '0')}`,
      team_abbreviation: 'BOS',
      primary_position: 'G',
    }))
    large.source_games_played_assumptions = []
    large.lineage.projection_import.projection_count = large.projections.length
    large.lineage.projection_import.row_count = large.projections.length
    large.lineage.projection_import.matched_count = large.projections.length

    const model = buildProjectionsModel(large)
    render(<ProjectionsBrowser model={model} />)

    expect(renderedIds()).toHaveLength(PROJECTION_PAGE_SIZE)
    expect(screen.getByRole('status')).toHaveTextContent(
      `Showing ${String(PROJECTION_PAGE_SIZE)} of ${String(PROJECTION_PAGE_SIZE + 1)} matches`,
    )

    await user.click(screen.getByRole('button', { name: 'Sort by PTS per game ascending' }))
    expect(renderedIds()).toHaveLength(PROJECTION_PAGE_SIZE)
    expect(renderedIds()[0]).toBe(PROJECTION_PAGE_SIZE + 1)

    await user.click(screen.getByRole('button', { name: 'Show more players' }))
    expect(renderedIds()).toHaveLength(PROJECTION_PAGE_SIZE + 1)
    expect(new Set(renderedIds())).toEqual(new Set(model.rows.map((row) => row.playerId)))
    expect(screen.getByRole('status')).toHaveTextContent(
      `Showing ${String(PROJECTION_PAGE_SIZE + 1)} of ${String(
        PROJECTION_PAGE_SIZE + 1,
      )} matches`,
    )
  })

  it('clears a selected NBA team immediately when a refreshed cohort no longer offers it', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<ProjectionsBrowser model={buildProjectionsModel(payload())} />)
    const team = screen.getByRole('combobox', { name: 'NBA team' })

    await user.selectOptions(team, 'BOS')
    expect(team).toHaveValue('BOS')
    expect(renderedIds()).toEqual([3, 1])

    const refreshed = payload()
    refreshed.players = refreshed.players.map((player) => ({
      ...player,
      team_abbreviation: 'LAL',
    }))
    rerender(<ProjectionsBrowser model={buildProjectionsModel(refreshed)} />)

    expect(team).toHaveValue('')
    expect(screen.getByRole('status')).toHaveTextContent(
      'Showing 3 of 3 matches from 3 imported players',
    )
    expect(renderedIds()).toEqual([3, 1, 2])
    expect(screen.getByRole('button', { name: 'Reset view' })).toBeDisabled()
  })

  it('clears the missing-team filter immediately when a refreshed cohort has no missing labels', async () => {
    const user = userEvent.setup()
    const initial = payload()
    initial.players = initial.players.map((player) =>
      player.player_id === 3 ? { ...player, team_abbreviation: null } : player,
    )
    const { rerender } = render(<ProjectionsBrowser model={buildProjectionsModel(initial)} />)
    const team = screen.getByRole('combobox', { name: 'NBA team' })

    await user.selectOptions(team, screen.getByRole('option', { name: 'No NBA team label' }))
    expect(renderedIds()).toEqual([3])

    rerender(<ProjectionsBrowser model={buildProjectionsModel(payload())} />)

    expect(team).toHaveValue('')
    expect(screen.queryByRole('option', { name: 'No NBA team label' })).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(
      'Showing 3 of 3 matches from 3 imported players',
    )
    expect(renderedIds()).toEqual([3, 1, 2])
    expect(screen.getByRole('button', { name: 'Reset view' })).toBeDisabled()
  })
})
