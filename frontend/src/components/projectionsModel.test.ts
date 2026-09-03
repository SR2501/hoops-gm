/**
 * The join, and specifically what it notices.
 *
 * The interesting tests here are not the happy path. They are the cases where
 * a count still adds up and a census still passes while a value has quietly
 * become its opposite — because that is the failure this module was written
 * against, and a test suite that only exercises well-formed payloads would
 * prove the code agrees with itself and nothing more.
 */

import { describe, expect, it } from 'vitest'
import { PROJECTION_RATE_FIELDS } from '../api/types'
import type {
  CurrentProjections,
  ProjectionPlayer,
  ProjectionRates,
  SourceGamesPlayedClaim,
} from '../api/types'
import {
  buildProjectionsModel,
  formatRate,
  NOT_PUBLISHED,
  projectionTeamOptions,
  selectProjectionRows,
} from './projectionsModel'
import type { ProjectionRow, ProjectionsModel } from './projectionsModel'

/**
 * The row at `index`, asserted to exist.
 *
 * A bare `model.rows[0]` is `ProjectionRow | undefined` under
 * `noUncheckedIndexedAccess`, and silencing that with `!` would let a test that
 * built an empty model pass vacuously — the assertion would run against
 * `undefined?.something` and never fire. This fails loudly instead.
 */
function row(model: ProjectionsModel, index = 0): ProjectionRow {
  const found = model.rows[index]
  if (found === undefined) {
    throw new Error(`expected a row at index ${String(index)}, got ${String(model.rows.length)}`)
  }
  return found
}

function rates(playerId: number, overrides: Partial<ProjectionRates> = {}): ProjectionRates {
  const row = { player_id: playerId } as ProjectionRates
  for (const field of PROJECTION_RATE_FIELDS) {
    row[field] = 1
  }
  return { ...row, ...overrides }
}

function player(playerId: number, name = `Player ${String(playerId)}`): ProjectionPlayer {
  return {
    player_id: playerId,
    full_name: name,
    team_abbreviation: 'BOS',
    primary_position: 'G',
  }
}

function payload(overrides: Partial<CurrentProjections> = {}): CurrentProjections {
  const projections = overrides.projections ?? [rates(1), rates(2)]
  return {
    league_id: 1,
    season: '2026-27',
    source: 'basketball_monster',
    lineage: {
      blend: null,
      projection_import: {
        import_id: 7,
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
        row_count: 2,
        matched_count: 2,
        needs_review_count: 0,
        unmatched_count: 0,
        rejected_count: 0,
      },
    },
    players: [player(1), player(2)],
    projections,
    source_games_played_assumptions: [],
    ...overrides,
  }
}

function browserPayload(): CurrentProjections {
  const projections = [
    rates(6, { points_per_game: 30 }),
    rates(4, { points_per_game: 10 }),
    rates(2, { points_per_game: 20 }),
    rates(5, { points_per_game: 20 }),
    rates(3, { points_per_game: 20 }),
    rates(1, { points_per_game: null }),
  ]
  const base = payload({ projections })
  return {
    ...base,
    players: [
      { ...player(1, 'Alpha Player'), team_abbreviation: 'BOS' },
      { ...player(2, 'Bravo Player'), team_abbreviation: 'NYK' },
      { ...player(3, 'Charlie Player'), team_abbreviation: null },
      { ...player(4, 'Delta Player'), team_abbreviation: 'LAL' },
      { ...player(5, 'Echo Player'), team_abbreviation: 'BOS' },
    ],
    source_games_played_assumptions: [
      { player_id: 1, assumed_games_played: 70, assumed_games_played_raw: '70' },
      { player_id: 2, assumed_games_played: null, assumed_games_played_raw: 'many' },
      { player_id: 3, assumed_games_played: null, assumed_games_played_raw: null },
      { player_id: 5, assumed_games_played: 0, assumed_games_played_raw: '0' },
      { player_id: 6, assumed_games_played: 70, assumed_games_played_raw: '70' },
    ],
    lineage: {
      ...base.lineage,
      projection_import: {
        ...base.lineage.projection_import,
        projection_count: projections.length,
      },
    },
  }
}

function ids(rows: readonly ProjectionRow[]): number[] {
  return rows.map((candidate) => candidate.playerId)
}

describe('buildProjectionsModel', () => {
  it('joins a well-formed cohort and reports it consistent', () => {
    const model = buildProjectionsModel(
      payload({
        source_games_played_assumptions: [
          { player_id: 1, assumed_games_played: 70, assumed_games_played_raw: '70' },
        ],
      }),
    )

    expect(model.rows).toHaveLength(2)
    expect(row(model).player?.full_name).toBe('Player 1')
    expect(row(model).assumption).toEqual({ kind: 'stated', games: 70, raw: '70' })
    expect(row(model, 1).assumption).toEqual({ kind: 'absent' })
    expect(model.integrity.isConsistent).toBe(true)
  })

  it('carries the lineage through from the same payload the rows came from', () => {
    // Not a tautology worth skipping: the alternative design threads lineage
    // and rows to the component tree as separate props, which is what makes a
    // mixed-lineage render expressible in the first place.
    const source = payload()
    const model = buildProjectionsModel(source)

    expect(model.lineage).toBe(source.lineage)
  })

  describe('the four assumption states', () => {
    const cases: [string, SourceGamesPlayedClaim | null, unknown][] = [
      [
        'a stated value',
        { player_id: 1, assumed_games_played: 68, assumed_games_played_raw: '68 GP' },
        { kind: 'stated', games: 68, raw: '68 GP' },
      ],
      [
        'text we could not read as a number',
        { player_id: 1, assumed_games_played: null, assumed_games_played_raw: 'most of them' },
        { kind: 'unreadable', raw: 'most of them' },
      ],
      [
        'a row stating nothing at all',
        { player_id: 1, assumed_games_played: null, assumed_games_played_raw: null },
        { kind: 'unexplained' },
      ],
      ['no row at all', null, { kind: 'absent' }],
    ]

    for (const [label, claim, expected] of cases) {
      it(`reads ${label} distinctly`, () => {
        const model = buildProjectionsModel(
          payload({ source_games_played_assumptions: claim ? [claim] : [] }),
        )
        expect(row(model).assumption).toEqual(expected)
      })
    }

    it('never collapses a zero into an absence', () => {
      // The one that would be a real modelling error rather than a display
      // one: a source that explicitly assumed zero games is making a strong
      // claim, and reading it as "said nothing" would erase it.
      const model = buildProjectionsModel(
        payload({
          source_games_played_assumptions: [
            { player_id: 1, assumed_games_played: 0, assumed_games_played_raw: '0' },
          ],
        }),
      )

      expect(row(model).assumption).toEqual({ kind: 'stated', games: 0, raw: '0' })
    })

    it('counts an unexplained row rather than letting it pass as an absence', () => {
      const model = buildProjectionsModel(
        payload({
          source_games_played_assumptions: [
            { player_id: 1, assumed_games_played: null, assumed_games_played_raw: null },
          ],
        }),
      )

      expect(model.integrity.unexplainedAssumptions).toBe(1)
      expect(model.integrity.isConsistent).toBe(false)
    })
  })

  describe('what a length check would miss', () => {
    it('notices a rate row replaced by a duplicate of another', () => {
      // **The defect this module exists for.** Two rows arrive, the count is
      // two, the lineage count is two, and every row that arrived has a
      // matching player. But player 2's rates are gone and player 1's appear
      // twice — so on a naive join player 2 renders as though the backend sent
      // nothing for them, which is a real value silently becoming the marker
      // that means "nothing was sent".
      const model = buildProjectionsModel(
        payload({ projections: [rates(1, { points_per_game: 30 }), rates(1)] }),
      )

      expect(model.rows).toHaveLength(1)
      expect(model.integrity.duplicateRateRows).toBe(1)
      // The direction a single length comparison cannot see: player 2 is
      // named and carries no rates.
      expect(model.integrity.playersWithoutRates).toBe(1)
      expect(model.integrity.isConsistent).toBe(false)
    })

    it('checks membership in both directions, not one plus a count', () => {
      const source = payload({
        projections: [rates(1), rates(99)],
        players: [player(1), player(2)],
      })
      const model = buildProjectionsModel(source)

      // Same length on both sides, and every row drawn. Only a two-directional
      // membership check sees that these describe different sets.
      expect(source.projections).toHaveLength(source.players.length)
      expect(model.rows).toHaveLength(2)
      expect(model.integrity.ratesWithoutPlayer).toBe(1)
      expect(model.integrity.playersWithoutRates).toBe(1)
      expect(model.integrity.isConsistent).toBe(false)
    })

    it('draws a rate row with no player record rather than dropping it', () => {
      const model = buildProjectionsModel(payload({ players: [player(1)] }))

      expect(model.rows).toHaveLength(2)
      expect(row(model, 1).player).toBeNull()
      expect(model.integrity.ratesWithoutPlayer).toBe(1)
    })

    it('flags a row count that disagrees with the lineage block', () => {
      const base = payload()
      const model = buildProjectionsModel({
        ...base,
        lineage: {
          ...base.lineage,
          projection_import: { ...base.lineage.projection_import, projection_count: 5 },
        },
      })

      expect(model.integrity.rowCountMatchesLineage).toBe(false)
      expect(model.integrity.isConsistent).toBe(false)
    })

    it('notices an assumption naming a player the cohort has no rates for', () => {
      const model = buildProjectionsModel(
        payload({
          source_games_played_assumptions: [
            { player_id: 404, assumed_games_played: 70, assumed_games_played_raw: '70' },
          ],
        }),
      )

      expect(model.integrity.assumptionsWithoutRates).toBe(1)
      expect(model.integrity.isConsistent).toBe(false)
    })

    it('keeps the first of duplicate assumptions and counts the rest', () => {
      const model = buildProjectionsModel(
        payload({
          source_games_played_assumptions: [
            { player_id: 1, assumed_games_played: 70, assumed_games_played_raw: '70' },
            { player_id: 1, assumed_games_played: 12, assumed_games_played_raw: '12' },
          ],
        }),
      )

      expect(row(model).assumption).toEqual({ kind: 'stated', games: 70, raw: '70' })
      expect(model.integrity.duplicateAssumptionRows).toBe(1)
    })

    it('keeps the drawn rows and the counted duplicates in step', () => {
      // The two use the same first-wins rule. If they diverged, the banner
      // would report a number of ignored rows the table did not actually
      // ignore.
      const model = buildProjectionsModel(
        payload({ projections: [rates(1), rates(1), rates(1), rates(2)] }),
      )

      expect(model.rows.map((row) => row.playerId)).toEqual([1, 2])
      expect(model.integrity.duplicateRateRows).toBe(2)
    })
  })

  it('preserves the backend ordering rather than re-sorting', () => {
    // The endpoint guarantees both arrays are ordered by `player_id`. Sorting
    // again here would mask a response that was not, and this screen's job is
    // to make that visible rather than tidy it away.
    const model = buildProjectionsModel(
      payload({
        projections: [rates(9), rates(3), rates(5)],
        players: [player(3), player(5), player(9)],
      }),
    )

    expect(model.rows.map((row) => row.playerId)).toEqual([9, 3, 5])
  })
})

describe('selectProjectionRows', () => {
  it('combines player search and NBA-team filtering without mutating or dropping the cohort', () => {
    const source = browserPayload()
    const sourceBefore = JSON.stringify(source)
    const model = buildProjectionsModel(source)
    const originalIds = ids(model.rows)

    const selected = selectProjectionRows(model.rows, {
      searchQuery: '  alpha  ',
      teamFilter: { kind: 'team', abbreviation: 'BOS' },
      sort: null,
    })
    const missingLabel = selectProjectionRows(model.rows, {
      searchQuery: 'player 6',
      teamFilter: { kind: 'missing' },
      sort: null,
    })
    const reset = selectProjectionRows(model.rows, {
      searchQuery: '',
      teamFilter: { kind: 'all' },
      sort: null,
    })

    expect(ids(selected)).toEqual([1])
    expect(ids(missingLabel)).toEqual([6])
    expect(ids(reset)).toEqual(originalIds)
    expect(reset).not.toBe(model.rows)
    expect(new Set(reset)).toEqual(new Set(model.rows))
    expect(ids(model.rows)).toEqual(originalIds)
    expect(JSON.stringify(source)).toBe(sourceBefore)
  })

  it('sorts player and NBA-team labels in both directions with missing labels last', () => {
    const rows = buildProjectionsModel(browserPayload()).rows

    expect(
      ids(
        selectProjectionRows(rows, {
          searchQuery: '',
          teamFilter: { kind: 'all' },
          sort: { key: 'player_name', direction: 'ascending' },
        }),
      ),
    ).toEqual([1, 2, 3, 4, 5, 6])
    expect(
      ids(
        selectProjectionRows(rows, {
          searchQuery: '',
          teamFilter: { kind: 'all' },
          sort: { key: 'player_name', direction: 'descending' },
        }),
      ),
    ).toEqual([5, 4, 3, 2, 1, 6])
    expect(
      ids(
        selectProjectionRows(rows, {
          searchQuery: '',
          teamFilter: { kind: 'all' },
          sort: { key: 'nba_team', direction: 'ascending' },
        }),
      ),
    ).toEqual([1, 5, 4, 2, 3, 6])
    expect(
      ids(
        selectProjectionRows(rows, {
          searchQuery: '',
          teamFilter: { kind: 'all' },
          sort: { key: 'nba_team', direction: 'descending' },
        }),
      ),
    ).toEqual([2, 4, 1, 5, 3, 6])
  })

  it('sorts a published rate in both directions, with null last and deterministic ties', () => {
    const rows = buildProjectionsModel(browserPayload()).rows

    expect(
      ids(
        selectProjectionRows(rows, {
          searchQuery: '',
          teamFilter: { kind: 'all' },
          sort: { key: 'points_per_game', direction: 'ascending' },
        }),
      ),
    ).toEqual([4, 2, 3, 5, 6, 1])
    expect(
      ids(
        selectProjectionRows(rows, {
          searchQuery: '',
          teamFilter: { kind: 'all' },
          sort: { key: 'points_per_game', direction: 'descending' },
        }),
      ),
    ).toEqual([6, 2, 3, 5, 4, 1])
  })

  it('sorts only stated Source GP numbers and keeps every unavailable state after them', () => {
    const rows = buildProjectionsModel(browserPayload()).rows
    const ascending = selectProjectionRows(rows, {
      searchQuery: '',
      teamFilter: { kind: 'all' },
      sort: { key: 'source_games_played', direction: 'ascending' },
    })
    const descending = selectProjectionRows(rows, {
      searchQuery: '',
      teamFilter: { kind: 'all' },
      sort: { key: 'source_games_played', direction: 'descending' },
    })

    expect(ids(ascending)).toEqual([5, 1, 6, 2, 3, 4])
    expect(ids(descending)).toEqual([1, 6, 5, 2, 3, 4])
    expect(ascending.map((candidate) => candidate.assumption.kind)).toEqual([
      'stated',
      'stated',
      'stated',
      'unreadable',
      'unexplained',
      'absent',
    ])
  })

  it('builds deterministic team choices and preserves a separate missing-label option', () => {
    expect(projectionTeamOptions(buildProjectionsModel(browserPayload()).rows)).toEqual({
      abbreviations: ['BOS', 'LAL', 'NYK'],
      hasMissingLabel: true,
    })
  })
})

describe('formatRate', () => {
  it('renders a published zero differently from an absent value', () => {
    // The single most load-bearing line in this module. If these two ever
    // render the same string, the screen is lying about what the source said.
    expect(formatRate(0)).toBe('0.00')
    expect(formatRate(null)).toBe(NOT_PUBLISHED)
    expect(formatRate(0)).not.toBe(formatRate(null))
  })

  it('keeps trailing zeros so decimal points align down a column', () => {
    expect(formatRate(8.6)).toBe('8.60')
    expect(formatRate(34.5)).toBe('34.50')
  })
})
