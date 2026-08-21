/**
 * The ADR-002 backstop: no rendered cell is a rate multiplied by the source's
 * games-played assumption.
 *
 * **This is the backstop, not the guarantee.** The load-bearing defence is
 * structural and lives in `projectionsModel.ts`: `AssumptionState` is a
 * discriminated union, so a games-played figure is never a bare `number` in
 * the same object as a rate, and writing the forbidden product requires
 * destructuring a union member first. Do not weaken that structure on the
 * strength of this file.
 *
 * The reason the structure has to carry the weight is that the prohibition is
 * **rate × any count**, and no DOM test can enumerate every count. A per-week
 * projection, a rest-of-season figure or a games-remaining number would each be
 * the same ADR-002 fusion and none of them appears below. What this file
 * catches is the one product that can be named — and it is worth naming,
 * because `architect` makes the point that it is precisely the column a
 * reasonable person adds *on purpose*, believing it useful, and it will look
 * correct when they do.
 *
 * **Why a rounding sweep rather than an equality check.** The product recovers
 * the source's published seasonal total only *to within floating-point
 * rounding* — measured at roughly 8.3% of realistic pairs not round-tripping
 * exactly, with fractional games-played values failing routinely. An
 * exact-equality assertion would therefore miss real violations while looking
 * rigorous, which is the shape of defect this project keeps finding.
 *
 * **This test can fail.** `it('fails when a season-total column is added')`
 * below renders a deliberately-violating table and asserts the detector fires,
 * so a mutation that makes the check vacuous is itself caught. A guard nobody
 * has watched fail is a guard nobody has tested.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { CurrentProjections, ProjectionRates } from '../api/types'
import { detectForbiddenProducts, forbiddenProducts } from '../test/adr002'
import { ProjectionsTable } from './ProjectionsTable'
import { buildProjectionsModel } from './projectionsModel'

/** Realistic per-game rates against a realistic, awkward games assumption. */
const RATES: ProjectionRates = {
  player_id: 1,
  minutes_per_game: 34.5,
  points_per_game: 27.3,
  rebounds_per_game: 7.1,
  offensive_rebounds_per_game: 1.2,
  defensive_rebounds_per_game: 5.9,
  assists_per_game: 8.4,
  steals_per_game: 1.3,
  blocks_per_game: 0.7,
  turnovers_per_game: 3.2,
  personal_fouls_per_game: 2.1,
  field_goals_made_per_game: 9.6,
  field_goals_attempted_per_game: 19.4,
  three_pointers_made_per_game: 2.8,
  three_pointers_attempted_per_game: 7.6,
  free_throws_made_per_game: 5.3,
  free_throws_attempted_per_game: 6.1,
}

const ASSUMED_GAMES = 70.5

function payload(): CurrentProjections {
  return {
    league_id: 1,
    season: '2026-27',
    source: 'basketball_monster',
    lineage: {
      blend: null,
      projection_import: {
        import_id: 1,
        source: 'basketball_monster',
        season: '2026-27',
        imported_at: '2026-08-19T12:00:00Z',
        content_sha256: 'a'.repeat(64),
        profile_id: 'basketball-monster',
        profile_version: '1',
        profile_definition_sha256: 'b'.repeat(64),
        projection_values_sha256: 'c'.repeat(64),
        projection_count: 1,
        assumed_scoring_type: null,
        original_filename: 'bbm.csv',
        row_count: 1,
        matched_count: 1,
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
    ],
    projections: [RATES],
    source_games_played_assumptions: [
      { player_id: 1, assumed_games_played: ASSUMED_GAMES, assumed_games_played_raw: '70.5' },
    ],
  }
}

/**
 * Every string form a seasonal total could plausibly be rendered as.
 *
 * Kept for the negative control below, which asserts on a *specific* rendering
 * rather than on the detector's own logic — a negative control that reused the
 * detector could pass because both share a bug.
 */
function forbiddenRenderings(product: number): string[] {
  const forms = new Set<string>()
  for (const digits of [0, 1, 2, 3]) {
    forms.add(product.toFixed(digits))
    forms.add(product.toLocaleString('en-US', { maximumFractionDigits: digits }))
  }
  forms.add(String(product))
  return [...forms].filter((form) => form.replace(/[^0-9]/g, '').length >= 3)
}

describe('ADR-002: the screen never multiplies a rate by the games assumption', () => {
  it('renders no rate × assumed_games_played product anywhere', () => {
    const model = buildProjectionsModel(payload())
    const { container } = render(<ProjectionsTable model={model} />)

    expect(detectForbiddenProducts(container, model)).toEqual([])
  })

  it('had products to look for — the detector did not pass by examining nothing', () => {
    // A green verifier does not tell you it looked at the right artifact, or
    // at any artifact. Sixteen rates against one stated assumption, minus the
    // handful whose product falls below the meaningful-total floor.
    expect(forbiddenProducts(buildProjectionsModel(payload())).length).toBeGreaterThan(8)
  })

  it('fails when a season-total column is added — the guard is not vacuous', () => {
    // The mutation the guard exists to catch, executed rather than imagined.
    // If this ever passes, the detector above has stopped detecting and its
    // green result means nothing.
    const model = buildProjectionsModel(payload())
    const { container } = render(
      <>
        <ProjectionsTable model={model} />
        <p>Projected season points: {(RATES.points_per_game! * ASSUMED_GAMES).toFixed(1)}</p>
      </>,
    )

    expect(detectForbiddenProducts(container, model)).toContain(
      `player 1 points_per_game → ${String(RATES.points_per_game! * ASSUMED_GAMES)}`,
    )
  })

  it('catches a total formatted with a thousands separator', () => {
    // `toLocaleString()` is what someone reaches for on a four-figure total,
    // and a naive string search for `1924.7` would not find `1,924.7`. This is
    // why the detector parses rendered tokens back to numbers rather than
    // matching their string forms.
    const model = buildProjectionsModel(payload())
    const total = RATES.points_per_game! * ASSUMED_GAMES
    const { container } = render(
      <>
        <ProjectionsTable model={model} />
        <p>Season points: {total.toLocaleString('en-US', { maximumFractionDigits: 1 })}</p>
      </>,
    )

    expect(total).toBeGreaterThan(1000)
    expect(forbiddenRenderings(total)).toContain(
      total.toLocaleString('en-US', { maximumFractionDigits: 1 }),
    )
    expect(detectForbiddenProducts(container, model).length).toBeGreaterThan(0)
  })

  it('does not fire on an ordinary correct render — no cross-cell false positives', () => {
    // The first version of this detector concatenated the subtree's
    // `textContent` and reported 200-odd violations against the real cohort,
    // every one of them a substring spanning the junction between two adjacent
    // cells. A guard that cries wolf on a correct screen gets loosened by
    // whoever meets it next, so the absence of false positives is asserted
    // rather than assumed.
    const many = { ...payload() }
    many.projections = [RATES, { ...RATES, player_id: 2 }, { ...RATES, player_id: 3 }]
    many.players = [1, 2, 3].map((id) => ({
      player_id: id,
      full_name: `Player ${String(id)}`,
      team_abbreviation: 'BOS',
      primary_position: 'G',
    }))
    many.source_games_played_assumptions = [1, 2, 3].map((id) => ({
      player_id: id,
      assumed_games_played: ASSUMED_GAMES,
      assumed_games_played_raw: '70.5',
    }))
    many.lineage.projection_import.projection_count = 3

    const model = buildProjectionsModel(many)
    const { container } = render(<ProjectionsTable model={model} />)

    expect(detectForbiddenProducts(container, model)).toEqual([])
  })

  it('shows the assumption itself, because displaying it is the point', () => {
    // The prohibition is on computing with it, not on showing it. "The source
    // assumed 70.5 games and our availability model will replace that" is the
    // product thesis in one line, so a guard that suppressed the number
    // entirely would have removed the reason the field is published.
    const model = buildProjectionsModel(payload())
    render(<ProjectionsTable model={model} />)

    expect(screen.getByTestId('assumption-1')).toHaveTextContent(String(ASSUMED_GAMES))
  })
})
