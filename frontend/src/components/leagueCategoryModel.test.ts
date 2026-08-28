/**
 * The league category model, driven from hand-built payloads.
 *
 * These prove the code agrees with itself and nothing more; the contract meets
 * something a real backend produced in
 * `CategoriesPage.recorded.test.tsx`. What they are *for* is the arithmetic and
 * the refusals, which a recorded fixture cannot exercise because a well-formed
 * recording contains none of them: a null rate, a broken shooting pair, a seat
 * with no joined players, a duplicate rate row, a stated points-league format.
 *
 * Every number asserted here is worked out by hand in the test, not read back
 * from the implementation.
 */

import { describe, expect, it } from 'vitest'
import type { DraftHolding, DraftParticipant, DraftState } from '../api/draftTypes'
import type { CurrentProjections, ProjectionRateField, ProjectionRates } from '../api/types'
import { PROJECTION_RATE_FIELDS } from '../api/types'
import {
  aggregateValue,
  buildLeagueCategoryModel,
  CATEGORIES,
  formatRatio,
  ordinal,
  type CountingAggregate,
  type RatioAggregate,
} from './leagueCategoryModel'

/** Ten seconds: these are pure-function tests with no I/O and no timers. */
const TIMEOUT_MS = 10_000

function rates(playerId: number, overrides: Partial<Record<ProjectionRateField, number | null>>) {
  const row = { player_id: playerId } as ProjectionRates
  for (const field of PROJECTION_RATE_FIELDS) {
    row[field] = 0
  }
  return Object.assign(row, overrides)
}

function holding(playerId: number | null, label = `player ${String(playerId)}`): DraftHolding {
  return {
    player_id: playerId,
    player_label: label,
    player_key: label.toLowerCase(),
    price: null,
    event_sequence: 1,
    overall_pick: null,
  }
}

function seat(
  id: number,
  holdings: DraftHolding[],
  options: { owner?: boolean } = {},
): DraftParticipant {
  return {
    id,
    team_slot: id,
    display_name: `Seat ${String(id)}`,
    is_owner: options.owner ?? false,
    fantasy_team_id: null,
    holdings,
    slots_filled: holdings.length,
    slots_remaining: 0,
    spent: null,
    remaining_budget: null,
    // These seats carry no budget, so there is no assumption to have passed.
    // `false` rather than a nullable, matching the API: `remaining_budget`
    // already answers whether this draft has a budget at all.
    over_assumed_budget: false,
  }
}

function draft(participants: DraftParticipant[]): DraftState {
  return {
    id: 1,
    league_id: 1,
    name: 'test draft',
    is_mock: true,
    tool_usage: 'blind',
    notes: null,
    status: 'in_progress',
    format: {
      draft_type: 'auction',
      team_count: participants.length,
      roster_size: 13,
      total_roster_slots: participants.length * 13,
      auction_budget: '200.00',
    },
    league_format_drift: null,
    participants,
    open_lot: null,
    next_pick: null,
    selections_made: participants.reduce((n, p) => n + p.holdings.length, 0),
    total_roster_slots: participants.length * 13,
    last_sequence: 1,
    live_event_count: 1,
    voided_sequences: [],
    unresolved_player_count: 0,
  }
}

function cohort(
  rows: ProjectionRates[],
  options: { scoringType?: string | null } = {},
): CurrentProjections {
  return {
    league_id: 1,
    season: '2026-27',
    source: 'basketball_monster',
    lineage: {
      projection_import: {
        import_id: 1,
        source: 'basketball_monster',
        season: '2026-27',
        imported_at: '2026-08-27T00:00:00Z',
        content_sha256: 'a'.repeat(64),
        profile_id: 'test',
        profile_version: '1',
        profile_definition_sha256: 'b'.repeat(64),
        projection_values_sha256: 'c'.repeat(64),
        projection_count: rows.length,
        assumed_scoring_type:
          'scoringType' in options ? (options.scoringType ?? null) : 'h2h_categories',
        original_filename: null,
        row_count: rows.length,
        matched_count: rows.length,
        needs_review_count: 0,
        unmatched_count: 0,
        rejected_count: 0,
      },
      blend: null,
    },
    players: rows.map((row) => ({
      player_id: row.player_id,
      full_name: `player ${String(row.player_id)}`,
      team_abbreviation: 'SAC',
      primary_position: 'F',
    })),
    projections: rows,
    source_games_played_assumptions: [],
  }
}

function cellFor(
  model: ReturnType<typeof buildLeagueCategoryModel>,
  slot: number,
  key: string,
) {
  const row = model.seats.find((s) => s.participant.team_slot === slot)
  if (row === undefined) throw new Error(`no seat ${String(slot)}`)
  const cell = row.cells.find((c) => c.category.key === key)
  if (cell === undefined) throw new Error(`no category ${key}`)
  return cell
}

describe('the nine categories', () => {
  it(
    'are exactly the nine in the league rules baseline, with turnovers reversed',
    () => {
      expect(CATEGORIES.map((c) => c.label)).toEqual([
        'PTS',
        'REB',
        'AST',
        'STL',
        'BLK',
        '3PM',
        'TO',
        'FG%',
        'FT%',
      ])
      expect(CATEGORIES.filter((c) => c.direction === 'lower').map((c) => c.key)).toEqual(['to'])
      // Percentages are ratios of two published volumes and never a single
      // field, because there is no percentage anywhere on the wire.
      expect(CATEGORIES.filter((c) => c.kind === 'ratio').map((c) => c.key)).toEqual(['fg', 'ft'])
    },
    TIMEOUT_MS,
  )

  it(
    'reads no games-played field, so no rate can be fused with availability',
    () => {
      const fields = CATEGORIES.flatMap((category) =>
        category.kind === 'counting'
          ? [category.field]
          : [category.madeField, category.attemptedField],
      )
      // ADR-002. Every field consumed is a per-game rate on `ProjectionRates`,
      // and `SourceGamesPlayedClaim` lives in a different array that this
      // module does not import. A field named here that is not a rate field
      // would be a fusion.
      for (const field of fields) {
        expect(PROJECTION_RATE_FIELDS).toContain(field)
      }
      expect(fields).not.toContain('assumed_games_played')
    },
    TIMEOUT_MS,
  )
})

describe('counting aggregates', () => {
  it(
    'sums the published per-game rate across a seat',
    () => {
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(10), holding(11)])]),
        cohort([
          rates(10, { points_per_game: 20.5, rebounds_per_game: 4 }),
          rates(11, { points_per_game: 9.25, rebounds_per_game: 11 }),
        ]),
      )

      const pts = cellFor(model, 1, 'pts').aggregate as CountingAggregate
      expect(pts.total).toBeCloseTo(29.75, 10)
      expect(pts.contributingPlayers).toBe(2)
      expect(pts.omittedPlayers).toBe(0)
      expect((cellFor(model, 1, 'reb').aggregate as CountingAggregate).total).toBeCloseTo(15, 10)
    },
    TIMEOUT_MS,
  )

  it(
    'treats a null rate as unpublished rather than zero',
    () => {
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(10), holding(11)])]),
        cohort([
          rates(10, { points_per_game: 20 }),
          rates(11, { points_per_game: null }),
        ]),
      )

      const pts = cellFor(model, 1, 'pts').aggregate as CountingAggregate
      // 20, not 20 — but the counts are what distinguish this from a genuine
      // zero contributor, and they are the assertion that matters.
      expect(pts.total).toBe(20)
      expect(pts.contributingPlayers).toBe(1)
      expect(pts.omittedPlayers).toBe(1)
    },
    TIMEOUT_MS,
  )

  it(
    'reports no total at all when every joined player is null in a category',
    () => {
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(10)])]),
        cohort([rates(10, { blocks_per_game: null })]),
      )

      const blk = cellFor(model, 1, 'blk')
      expect((blk.aggregate as CountingAggregate).total).toBeNull()
      // Not ranked last. Not ranked at all.
      expect(blk.rank).toBeNull()
      expect(blk.tier).toBeNull()
    },
    TIMEOUT_MS,
  )
})

describe('percentage categories', () => {
  it(
    'aggregate made over attempted, never a mean of player percentages',
    () => {
      // 9/10 and 1/10. The mean of the two percentages is 50%; the correct
      // aggregate is 10/20 = 50% here by coincidence, so the discriminating
      // case is the next test.
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(10), holding(11)])]),
        cohort([
          rates(10, { free_throws_made_per_game: 9, free_throws_attempted_per_game: 10 }),
          rates(11, { free_throws_made_per_game: 1, free_throws_attempted_per_game: 10 }),
        ]),
      )
      const ft = cellFor(model, 1, 'ft').aggregate as RatioAggregate
      expect(ft.ratio).toBeCloseTo(0.5, 10)
    },
    TIMEOUT_MS,
  )

  it(
    'is volume-weighted, so a 90%-on-one-attempt shooter barely moves it',
    () => {
      // The failure `AGENTS.md` names as the most common bug in homebrew tools.
      // Mean of the percentages: (0.9 + 0.5) / 2 = 70%.
      // Volume-weighted aggregate: (0.9 + 10) / (1 + 20) = 51.9%.
      // A test asserting 70% would be asserting the bug.
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(10), holding(11)])]),
        cohort([
          rates(10, { free_throws_made_per_game: 0.9, free_throws_attempted_per_game: 1 }),
          rates(11, { free_throws_made_per_game: 10, free_throws_attempted_per_game: 20 }),
        ]),
      )
      const ft = cellFor(model, 1, 'ft').aggregate as RatioAggregate
      expect(ft.ratio).toBeCloseTo(10.9 / 21, 10)
      expect(ft.ratio).not.toBeCloseTo(0.7, 3)
      expect(formatRatio(ft)).toBe('51.9%')
      // The volume is carried so a reader can see what the ratio stands on.
      expect(ft.attempted).toBeCloseTo(21, 10)
    },
    TIMEOUT_MS,
  )

  it(
    'omits a player missing either half of the shooting pair',
    () => {
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(10), holding(11), holding(12)])]),
        cohort([
          rates(10, { field_goals_made_per_game: 4, field_goals_attempted_per_game: 10 }),
          // Makes with no attempts would inflate a numerator against a
          // denominator that never saw it.
          rates(11, { field_goals_made_per_game: 8, field_goals_attempted_per_game: null }),
          rates(12, { field_goals_made_per_game: null, field_goals_attempted_per_game: 12 }),
        ]),
      )
      const fg = cellFor(model, 1, 'fg').aggregate as RatioAggregate
      expect(fg.made).toBe(4)
      expect(fg.attempted).toBe(10)
      expect(fg.ratio).toBeCloseTo(0.4, 10)
      expect(fg.contributingPlayers).toBe(1)
      expect(fg.omittedPlayers).toBe(2)
    },
    TIMEOUT_MS,
  )

  it(
    'has no percentage at all when nothing was attempted',
    () => {
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(10)])]),
        cohort([
          rates(10, { field_goals_made_per_game: 0, field_goals_attempted_per_game: 0 }),
        ]),
      )
      const cell = cellFor(model, 1, 'fg')
      // Not NaN, not Infinity, and not 0% — none of which is true.
      expect((cell.aggregate as RatioAggregate).ratio).toBeNull()
      expect(cell.rank).toBeNull()
      expect(formatRatio(cell.aggregate as RatioAggregate)).toBe('·')
    },
    TIMEOUT_MS,
  )
})

describe('ranking', () => {
  it(
    'ranks the biggest total first, and the smallest turnover total first',
    () => {
      const model = buildLeagueCategoryModel(
        draft([
          seat(1, [holding(10)]),
          seat(2, [holding(11)]),
          seat(3, [holding(12)]),
        ]),
        cohort([
          rates(10, { points_per_game: 5, turnovers_per_game: 5 }),
          rates(11, { points_per_game: 9, turnovers_per_game: 9 }),
          rates(12, { points_per_game: 1, turnovers_per_game: 1 }),
        ]),
      )

      expect(cellFor(model, 2, 'pts').rank).toBe(1)
      expect(cellFor(model, 1, 'pts').rank).toBe(2)
      expect(cellFor(model, 3, 'pts').rank).toBe(3)

      // Reversed, and this is the whole reason `direction` exists.
      expect(cellFor(model, 3, 'to').rank).toBe(1)
      expect(cellFor(model, 1, 'to').rank).toBe(2)
      expect(cellFor(model, 2, 'to').rank).toBe(3)
    },
    TIMEOUT_MS,
  )

  it(
    'shares a rank on a tie and skips the one it consumed',
    () => {
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(10)]), seat(2, [holding(11)]), seat(3, [holding(12)])]),
        cohort([
          rates(10, { assists_per_game: 7 }),
          rates(11, { assists_per_game: 7 }),
          rates(12, { assists_per_game: 2 }),
        ]),
      )
      expect(cellFor(model, 1, 'ast').rank).toBe(1)
      expect(cellFor(model, 2, 'ast').rank).toBe(1)
      // Standard competition ranking: 1, 1, 3 — never 1, 1, 2.
      expect(cellFor(model, 3, 'ast').rank).toBe(3)
    },
    TIMEOUT_MS,
  )

  it(
    'calls two totals equal when they differ only by float accumulation order',
    () => {
      // 0.1 + 0.2 !== 0.3 in binary floating point, and the two seats hold the
      // same production. Ranking them 1 and 2 would be reporting a difference
      // that does not exist in the quantity being described.
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(10), holding(11)]), seat(2, [holding(12)])]),
        cohort([
          rates(10, { steals_per_game: 0.1 }),
          rates(11, { steals_per_game: 0.2 }),
          rates(12, { steals_per_game: 0.3 }),
        ]),
      )
      expect(0.1 + 0.2).not.toBe(0.3)
      expect(cellFor(model, 1, 'stl').rank).toBe(1)
      expect(cellFor(model, 2, 'stl').rank).toBe(1)
    },
    TIMEOUT_MS,
  )

  it(
    'leaves a seat with nothing to aggregate unranked rather than last',
    () => {
      const model = buildLeagueCategoryModel(
        draft([
          seat(1, [holding(10)]),
          seat(2, []),
          // Recorded under a typed name the crosswalk has not matched. This is
          // every holding in the seeded demo.
          seat(3, [holding(null, 'Ansel Whitcombe')]),
          // A player id the cohort does not carry.
          seat(4, [holding(999)]),
        ]),
        cohort([rates(10, { points_per_game: 12 })]),
      )

      expect(cellFor(model, 1, 'pts').rank).toBe(1)
      for (const slot of [2, 3, 4]) {
        expect(cellFor(model, slot, 'pts').rank).toBeNull()
        expect(cellFor(model, slot, 'pts').tier).toBeNull()
      }
      // One ranked seat, so the ranking never reaches 2 and nothing is "last".
      expect(model.rankedSeatCount).toBe(1)
      expect(model.join).toEqual({
        totalHoldings: 3,
        unresolvedHoldings: 1,
        unmatchedHoldings: 1,
        joinedPlayers: 1,
      })
    },
    TIMEOUT_MS,
  )

  it(
    'never matches an unresolved holding to the cohort by name',
    () => {
      // The label is character-for-character the cohort's name for player 10.
      // Matching on it would be this browser inventing an identity decision
      // that belongs to the crosswalk, behind a different gate.
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(null, 'player 10')])]),
        cohort([rates(10, { points_per_game: 30 })]),
      )
      expect(model.join.joinedPlayers).toBe(0)
      expect(cellFor(model, 1, 'pts').rank).toBeNull()
    },
    TIMEOUT_MS,
  )

  it(
    'spreads five tiers across the ranked seats, best first',
    () => {
      const model = buildLeagueCategoryModel(
        draft(Array.from({ length: 10 }, (_, i) => seat(i + 1, [holding(i + 1)]))),
        cohort(Array.from({ length: 10 }, (_, i) => rates(i + 1, { points_per_game: 10 - i }))),
      )
      const tiers = model.seats.map((row) => cellFor(model, row.participant.team_slot, 'pts').tier)
      expect(tiers).toEqual([1, 1, 2, 2, 3, 3, 4, 4, 5, 5])
    },
    TIMEOUT_MS,
  )
})

describe('what the model refuses to assume', () => {
  it(
    'flags a stated non-category scoring format instead of ranking under it',
    () => {
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(10)])]),
        cohort([rates(10, { points_per_game: 30 })], { scoringType: 'h2h_points' }),
      )
      expect(model.assumedScoringType).toBe('h2h_points')
      expect(model.scoringTypeMismatch).toBe(true)
    },
    TIMEOUT_MS,
  )

  it(
    'treats an unstated format as unstated, not as a mismatch and not as agreement',
    () => {
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(10)])]),
        cohort([rates(10, { points_per_game: 30 })], { scoringType: null }),
      )
      expect(model.assumedScoringType).toBeNull()
      // Reported separately by the page, with different copy, because "nobody
      // said" and "said the wrong thing" call for different reactions.
      expect(model.scoringTypeMismatch).toBe(false)
    },
    TIMEOUT_MS,
  )

  it(
    'draws the seats and their join counts when there is no cohort at all',
    () => {
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(10), holding(11)]), seat(2, [])]),
        null,
      )
      expect(model.seats).toHaveLength(2)
      expect(model.join.totalHoldings).toBe(2)
      expect(model.join.unmatchedHoldings).toBe(2)
      expect(model.rankedSeatCount).toBe(0)
      expect(model.emptyReason).toEqual({ kind: 'nothing-joined', unresolved: 0, unmatched: 2 })
      expect(model.assumedScoringType).toBeNull()
    },
    TIMEOUT_MS,
  )

  it(
    'distinguishes an empty draft from one where nothing joined',
    () => {
      const empty = buildLeagueCategoryModel(draft([seat(1, []), seat(2, [])]), cohort([]))
      expect(empty.emptyReason).toEqual({ kind: 'no-holdings' })

      const unjoined = buildLeagueCategoryModel(
        draft([seat(1, [holding(null, 'a typed name')])]),
        cohort([]),
      )
      expect(unjoined.emptyReason).toEqual({
        kind: 'nothing-joined',
        unresolved: 1,
        unmatched: 0,
      })
    },
    TIMEOUT_MS,
  )

  it(
    'keeps the first of a duplicated rate row rather than counting a player twice',
    () => {
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(10)])]),
        cohort([rates(10, { points_per_game: 5 }), rates(10, { points_per_game: 500 })]),
      )
      expect((cellFor(model, 1, 'pts').aggregate as CountingAggregate).total).toBe(5)
    },
    TIMEOUT_MS,
  )
})

describe('presentation helpers', () => {
  it(
    'orders seats by team slot and finds the owner',
    () => {
      const model = buildLeagueCategoryModel(
        draft([seat(3, []), seat(1, []), seat(2, [], { owner: true })]),
        cohort([]),
      )
      expect(model.seats.map((row) => row.participant.team_slot)).toEqual([1, 2, 3])
      expect(model.ownerSeat?.participant.team_slot).toBe(2)
    },
    TIMEOUT_MS,
  )

  it(
    'returns no owner seat when the draft names none',
    () => {
      const model = buildLeagueCategoryModel(draft([seat(1, [])]), cohort([]))
      expect(model.ownerSeat).toBeNull()
    },
    TIMEOUT_MS,
  )

  it(
    'renders ordinals the way English does, including the teens',
    () => {
      expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111].map(ordinal)).toEqual([
        '1st',
        '2nd',
        '3rd',
        '4th',
        '11th',
        '12th',
        '13th',
        '21st',
        '22nd',
        '23rd',
        '101st',
        '111th',
      ])
    },
    TIMEOUT_MS,
  )

  it(
    'exposes the comparable scalar behind either aggregate kind',
    () => {
      const model = buildLeagueCategoryModel(
        draft([seat(1, [holding(10)])]),
        cohort([
          rates(10, {
            points_per_game: 3,
            field_goals_made_per_game: 1,
            field_goals_attempted_per_game: 4,
          }),
        ]),
      )
      expect(aggregateValue(cellFor(model, 1, 'pts').aggregate)).toBe(3)
      expect(aggregateValue(cellFor(model, 1, 'fg').aggregate)).toBeCloseTo(0.25, 10)
    },
    TIMEOUT_MS,
  )
})
