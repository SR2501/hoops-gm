/**
 * Tests for the reliability model.
 *
 * **What these can and cannot establish.** `buildAvailabilitySummary` is a
 * description of a cohort, not a prediction about one, so there is no
 * calibration to check and no held-out set to check it against — the Model gate
 * does not apply. What *can* go wrong is quieter: a sort that is not total so
 * the strip reshuffles between renders of one payload, a blank string parsing
 * to zero and agreeing with a parsed zero, a "nothing stated" cohort reporting a
 * range of `0 to 0`. Each of those produces a screen that looks right, which is
 * this project's characteristic failure and the reason these are written
 * against hand-built payloads with known answers rather than against a fixture
 * whose contents nobody has enumerated.
 *
 * The inventory tests are a different kind. `AVAILABILITY_EVIDENCE` is prose,
 * and no test can check that a sentence is true. What they check is that the
 * *shape* of the claim survives editing: that every item still names a season, a
 * location and a blocker; that `p(play)` is still presented as held rather than
 * as unstarted; and that the four quantities the backlog names for this unit are
 * all still accounted for. A future editor deleting the p(play) row because "we
 * don't have it anyway" is exactly the mutation worth failing on.
 */

import { describe, expect, it } from 'vitest'
import { PROJECTION_RATE_FIELDS } from '../api/types'
import type {
  CurrentProjections,
  ProjectionPlayer,
  ProjectionRates,
  SourceGamesPlayedClaim,
} from '../api/types'
import { buildProjectionsModel } from './projectionsModel'
import {
  AVAILABILITY_EVIDENCE,
  barPercent,
  buildAvailabilitySummary,
  describeSeasonSplit,
  EVIDENCE_SEASON,
  EVIDENCE_STATUS_LABELS,
  tallyEvidence,
} from './reliabilityModel'
import type { AvailabilitySummary, EvidenceItem, EvidenceStatus } from './reliabilityModel'

function rates(playerId: number): ProjectionRates {
  const row = { player_id: playerId } as ProjectionRates
  for (const field of PROJECTION_RATE_FIELDS) {
    row[field] = 1
  }
  return row
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
  const projections = overrides.projections ?? [rates(1)]
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
        row_count: projections.length,
        matched_count: projections.length,
        needs_review_count: 0,
        unmatched_count: 0,
        rejected_count: 0,
      },
    },
    players: projections.map((rate) => player(rate.player_id)),
    projections,
    source_games_played_assumptions: [],
    ...overrides,
  }
}

/** Summarise a cohort described only by its assumption claims. */
function summarise(
  claims: SourceGamesPlayedClaim[],
  overrides: Partial<CurrentProjections> = {},
): AvailabilitySummary {
  const ids = claims.map((claim) => claim.player_id)
  const projections = overrides.projections ?? ids.map((id) => rates(id))
  return buildAvailabilitySummary(
    buildProjectionsModel(
      payload({ projections, source_games_played_assumptions: claims, ...overrides }),
    ),
  )
}

function stated(playerId: number, games: number, raw?: string | null): SourceGamesPlayedClaim {
  return {
    player_id: playerId,
    assumed_games_played: games,
    assumed_games_played_raw: raw === undefined ? String(games) : raw,
  }
}

describe('buildAvailabilitySummary', () => {
  it('sorts every stated assumption ascending, independent of payload order', () => {
    const summary = summarise([stated(1, 72), stated(2, 59), stated(3, 65)])

    expect(summary.stated.map((point) => point.games)).toEqual([59, 65, 72])
    expect(summary.stated.map((point) => point.playerId)).toEqual([2, 3, 1])
  })

  it('breaks ties on player id so the drawing order is total', () => {
    // Without the tiebreak this passes or fails on the engine's sort stability,
    // which is a guarantee about `Array.prototype.sort` rather than about this
    // model, and is not what the strip's stability should rest on.
    const summary = summarise([stated(9, 70), stated(4, 70), stated(6, 70)])

    expect(summary.stated.map((point) => point.playerId)).toEqual([4, 6, 9])
  })

  it('reports minimum and maximum from stated values only', () => {
    const summary = summarise([
      stated(1, 66),
      { player_id: 2, assumed_games_played: null, assumed_games_played_raw: null },
      stated(3, 74),
    ])

    expect(summary.minimum).toBe(66)
    expect(summary.maximum).toBe(74)
    expect(summary.stated).toHaveLength(2)
  })

  it('reports null rather than zero when the cohort states nothing', () => {
    // The whole point of the screen. A minimum of `0` renders as "0 to 0 games",
    // which is a claim the source never made and is indistinguishable on screen
    // from a cohort of players nobody expects to play.
    const summary = summarise([
      { player_id: 1, assumed_games_played: null, assumed_games_played_raw: null },
    ])

    expect(summary.minimum).toBeNull()
    expect(summary.maximum).toBeNull()
    expect(summary.distinctValues).toBe(0)
  })

  it('counts absent, unreadable and unexplained apart rather than folding them into zero', () => {
    const summary = summarise(
      [
        stated(1, 70),
        { player_id: 2, assumed_games_played: null, assumed_games_played_raw: 'DNP' },
        { player_id: 3, assumed_games_played: null, assumed_games_played_raw: null },
      ],
      { projections: [rates(1), rates(2), rates(3), rates(4)] },
    )

    expect(summary.unreadable).toBe(1)
    expect(summary.unexplained).toBe(1)
    expect(summary.absent).toBe(1)
    expect(summary.cohortSize).toBe(4)
    expect(summary.stated).toHaveLength(1)
  })

  it('keeps a rate row whose player record is missing, under a bare id', () => {
    const summary = summarise([stated(1, 70)], {
      projections: [rates(1)],
      players: [],
    })

    expect(summary.stated).toHaveLength(1)
    expect(summary.stated[0]?.name).toBeNull()
    expect(summary.stated[0]?.playerId).toBe(1)
  })

  it('reports how many distinct values the cohort holds, not just its range', () => {
    const summary = summarise([stated(1, 70), stated(2, 70), stated(3, 70), stated(4, 82)])

    expect(summary.distinctValues).toBe(2)
    expect(summary.stated).toHaveLength(4)
  })

  it('publishes no mean, median or percentile under any key', () => {
    // Each would need an interpolation or a threshold convention, and both were
    // scoped out. Asserted on the keys rather than trusted to review, because
    // adding one is a two-line change that looks like an improvement.
    const summary = summarise([stated(1, 60), stated(2, 70)])

    expect(Object.keys(summary).some((key) => /mean|median|average|percentile|p\d/i.test(key))).toBe(
      false,
    )
  })
})

describe('the raw-vs-parsed divergence check', () => {
  it('flags a raw string that does not read back to the parsed number', () => {
    const summary = summarise([stated(1, 70, '17')])

    expect(summary.rawDivergences).toEqual([{ playerId: 1, raw: '17', parsed: 70 }])
  })

  it('accepts a raw string that differs only by whitespace or a trailing decimal', () => {
    const summary = summarise([stated(1, 70, ' 70 '), stated(2, 65, '65.0')])

    expect(summary.rawDivergences).toEqual([])
  })

  it('flags a blank raw string rather than letting it agree with a parsed zero', () => {
    // `Number('')` is `0`. A bare `Number(raw) !== games` comparison reports no
    // divergence here, and the false zero arrives through the comparison rather
    // than through the value.
    const summary = summarise([stated(1, 0, '   ')])

    expect(summary.rawDivergences).toEqual([{ playerId: 1, raw: '   ', parsed: 0 }])
  })

  it('flags raw text that is not a number at all', () => {
    const summary = summarise([stated(1, 70, 'seventy')])

    expect(summary.rawDivergences).toHaveLength(1)
  })

  it('does not flag a stated assumption carrying no raw text', () => {
    const summary = summarise([stated(1, 70, null)])

    expect(summary.rawDivergences).toEqual([])
    expect(summary.stated).toHaveLength(1)
  })
})

describe('barPercent', () => {
  it('scales from zero to the cohort maximum rather than from the minimum', () => {
    // Scaling min-to-max would draw a 59 as an empty bar and a 79 as a full one,
    // turning a 25% spread into a 100% one — the chart overstating the data,
    // which is the one thing a chart of real numbers can still get wrong.
    expect(barPercent(80, 80)).toBe(100)
    expect(barPercent(40, 80)).toBe(50)
    expect(barPercent(0, 80)).toBe(0)
  })

  it('returns zero rather than dividing by a null or non-positive maximum', () => {
    expect(barPercent(70, null)).toBe(0)
    expect(barPercent(70, 0)).toBe(0)
    expect(barPercent(70, -5)).toBe(0)
  })
})

describe('describeSeasonSplit', () => {
  it('reports the difference when the cohort season is not the evidence season', () => {
    const split = describeSeasonSplit('2026-27')

    expect(split).toEqual({ kind: 'differs', loaded: '2026-27', evidence: EVIDENCE_SEASON })
  })

  it('reports the coincidence when they match, rather than saying nothing', () => {
    // A boolean would let a caller render nothing for the matching case, and
    // "the season rolled over" is the case where the evidence-season ruling
    // needs revisiting rather than silently continuing to hold.
    expect(describeSeasonSplit(EVIDENCE_SEASON)).toEqual({
      kind: 'same',
      season: EVIDENCE_SEASON,
    })
  })

  it('ignores surrounding whitespace when comparing', () => {
    expect(describeSeasonSplit(` ${EVIDENCE_SEASON} `).kind).toBe('same')
  })
})

describe('AVAILABILITY_EVIDENCE', () => {
  it('gives every item a unique id', () => {
    const ids = AVAILABILITY_EVIDENCE.map((item) => item.id)

    expect(new Set(ids).size).toBe(ids.length)
  })

  it('gives every item a status from the closed set, and a label for it', () => {
    for (const item of AVAILABILITY_EVIDENCE) {
      expect(Object.keys(EVIDENCE_STATUS_LABELS)).toContain(item.status)
      expect(EVIDENCE_STATUS_LABELS[item.status]).toBeTruthy()
    }
  })

  it('names a season, a purpose, a location and a blocker for every item', () => {
    for (const item of AVAILABILITY_EVIDENCE) {
      expect(item.season.length, `${item.id} season`).toBeGreaterThan(0)
      expect(item.purpose.length, `${item.id} purpose`).toBeGreaterThan(0)
      expect(item.whereItLives.length, `${item.id} whereItLives`).toBeGreaterThan(0)
      expect(item.blocker.length, `${item.id} blocker`).toBeGreaterThan(0)
    }
  })

  it('points every already-computed quantity at a missing route rather than a missing model', () => {
    // "computed, not exposed" is a claim about a contract gap specifically, and
    // it is the finding this unit surfaced. An item carrying that status whose
    // blocker is about modelling would mean the status is wrong.
    const notExposed = AVAILABILITY_EVIDENCE.filter((item) => item.status === 'not-exposed')

    expect(notExposed.length).toBeGreaterThan(0)
    for (const item of notExposed) {
      expect(item.blocker.toLowerCase(), item.id).toContain('route')
    }
  })

  it('states p(play) as held pending a decision rather than as merely unbuilt', () => {
    const pPlay = AVAILABILITY_EVIDENCE.find((item) => item.id === 'p-play')

    expect(pPlay).toBeDefined()
    expect(pPlay?.status).toBe('blocked')
    expect(pPlay?.blocker).toMatch(/owner decision/i)
    expect(pPlay?.blocker).toMatch(/preregistration|preregistered/i)
  })

  it('accounts for all four quantities the backlog names for this unit', () => {
    const ids = AVAILABILITY_EVIDENCE.map((item) => item.id)

    // "Durability scorecards, B2B sit patterns, availability trend charts, and a
    // roster-level fragility summary." All four are present as rows; none is
    // present as a number.
    expect(ids).toContain('observed-play-rate')
    expect(ids).toContain('back-to-back')
    expect(ids).toContain('monthly-trend')
    expect(ids).toContain('roster-fragility')
  })
})

describe('tallyEvidence', () => {
  it('counts each status and reports how many quantities reached the screen', () => {
    const tally = tallyEvidence()

    expect(tally.total).toBe(AVAILABILITY_EVIDENCE.length)
    expect(tally.notExposed + tally.notDefined + tally.blocked).toBe(tally.total)
    // The number the whole screen exists to state honestly. It is zero, and it
    // is derived rather than written, so it stops being zero the moment a
    // quantity actually arrives.
    expect(tally.onScreen).toBe(0)
  })

  it('counts a status outside the missing set as having reached the screen', () => {
    // The control for the assertion above. `onScreen: 0` computed by a function
    // that can only ever return zero would be a sentence wearing a function's
    // clothes, so this drives the case where it must not be zero.
    const arrived: EvidenceItem = {
      id: 'arrived',
      quantity: 'A quantity that has arrived',
      status: 'served' as unknown as EvidenceStatus,
      season: EVIDENCE_SEASON,
      purpose: 'Drives the non-zero branch.',
      whereItLives: 'Nowhere; this item exists only in this test.',
      blocker: 'None.',
    }

    expect(tallyEvidence([...AVAILABILITY_EVIDENCE, arrived]).onScreen).toBe(1)
  })
})
