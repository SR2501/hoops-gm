/**
 * The contract test for the projections screen, against a **recorded** response.
 *
 * `ProjectionsPage.test.tsx` and `projectionsModel.test.ts` build their
 * payloads by hand from the TypeScript interfaces, so they can only ever prove
 * the code agrees with itself. `projections-current.recorded.json` is a real
 * 200 captured over HTTP from the running FastAPI service on 2026-08-21,
 * against the database `hoops_gm.dev.seed_projections` builds — so this file is
 * the only place the frontend's assumptions meet something the backend actually
 * produced.
 *
 * **Captured as raw bytes, and that mattered.** The first capture went through
 * PowerShell's `ConvertFrom-Json`/`ConvertTo-Json`, which parsed `imported_at`
 * into a `DateTime` and re-emitted it as `08/21/2026 15:57:03` — US locale,
 * no timezone, no sub-second precision. The file still looked like a recorded
 * fixture and every structural assertion below would have passed against it,
 * while the one field this project has already been bitten by would have been
 * silently replaced by the capture tool's opinion of it. A recording that has
 * been through a serialiser is not a recording. This one is
 * `WriteAllBytes(response)`.
 *
 * The recorded `imported_at` carries a `Z` suffix with microsecond precision.
 * The exact literal is deliberately not quoted here — it changes on every
 * re-capture — and the assertion below checks for a UTC designator rather than
 * `Z` specifically, because `+00:00` would be equally correct.
 *
 * **What this recording cannot check, stated because the seed's author said it
 * first and unprompted.** Only the player *names* are real; every number in it
 * is invented. So it proves shape and nothing else:
 *
 * - **not column width, not a real distribution.** Sixty rows scroll, which is
 *   enough to see the sticky header engage. Sixty rows are not a league, and
 *   nothing here is evidence this screen handles a 550-row auction board.
 * - **not long, accented or suffixed names.** The widest name in the cohort is
 *   ordinary.
 * - **not the sparse-assumption path.** All 60 players carry a games-played
 *   assumption, which is *not* representative: the array is deliberately sparse
 *   in general and absence is its documented "the source said nothing" signal.
 *   The absent, unreadable and unexplained states are therefore driven only
 *   from hand-built payloads, and that is a real gap rather than a formality —
 *   asked of `backend` and recorded in `docs/handoff.md`.
 * - **not the unresolved-identity path.** `identities_unresolved` is 0 here and
 *   a real Basketball Monster import will have a tail, so a non-zero
 *   `needs_review_count` or `unmatched_count` has never rendered.
 *
 * If the endpoint's shape changes, this fails here rather than in a browser.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import recorded from '../test/fixtures/projections-current.recorded.json'
import { isCurrentProjections } from '../api/endpoints'
import { PROJECTION_RATE_FIELDS } from '../api/types'
import type { CurrentProjections } from '../api/types'
import {
  detectForbiddenProducts,
  discriminableProductCount,
  tableColumnHeaders,
} from '../test/adr002'
import { ProjectionsTable } from './ProjectionsTable'
import {
  buildProjectionsModel,
  NO_LABEL,
  NOT_PUBLISHED,
  RATE_LABELS,
  selectProjectionRows,
} from './projectionsModel'

const payload = recorded as unknown as CurrentProjections

describe('the recorded projections response', () => {
  it('is accepted by the validator that guards the real request', () => {
    // The assertion the whole fixture exists for. Everything else in this file
    // checks fields chosen by hand; this checks the predicate production
    // actually runs, so a renamed or retyped field fails here even if no
    // hand-written assertion happens to touch it.
    expect(isCurrentProjections(recorded)).toBe(true)
  })

  it('carries the cohort guarantees the endpoint promises', () => {
    const playerIds = payload.players.map((player) => player.player_id)
    const rateIds = payload.projections.map((row) => row.player_id)

    expect(new Set(playerIds).size).toBe(playerIds.length)
    expect(new Set(rateIds).size).toBe(rateIds.length)
    // Both directions, not one plus a length check.
    expect(new Set(playerIds)).toEqual(new Set(rateIds))
    expect(payload.projections).toHaveLength(
      payload.lineage.projection_import.projection_count,
    )
  })

  it('is ordered by player_id on both arrays, as the contract states', () => {
    const ascending = (ids: number[]) =>
      ids.every((id, i) => {
        const previous = ids[i - 1]
        return previous === undefined || previous < id
      })

    expect(ascending(payload.players.map((p) => p.player_id))).toBe(true)
    expect(ascending(payload.projections.map((r) => r.player_id))).toBe(true)
  })

  it('publishes the games-played assumption outside every rate object', () => {
    // ADR-002's separation is in the wire format, not only in the schema. If a
    // durability figure ever appears inside a rate object, a component can pick
    // one up while reading a rate — which is the accident the separate table
    // and the separate array both exist to prevent.
    const forbidden = ['games', 'expected_games', 'assumed_games_played', 'rank', 'aav', 'z_score', 'g_score']
    for (const row of payload.projections) {
      const keys = Object.keys(row)
      expect(keys.sort()).toEqual([...PROJECTION_RATE_FIELDS, 'player_id'].sort())
      for (const key of forbidden) {
        expect(keys).not.toContain(key)
      }
    }
    for (const key of forbidden) {
      expect(Object.keys(payload)).not.toContain(key)
    }
  })

  it('computes no shooting percentage — makes and attempts only', () => {
    const first = payload.projections[0]
    expect(first).toBeDefined()
    const keys = new Set(Object.keys(first ?? {}))
    for (const suspect of ['field_goal_percentage', 'free_throw_percentage', 'three_point_percentage']) {
      expect(keys.has(suspect)).toBe(false)
    }
  })

  it('reports a blend of exactly null, not a missing key', () => {
    expect('blend' in payload.lineage).toBe(true)
    expect(payload.lineage.blend).toBeNull()
  })

  it('carries a UTC designator on the import timestamp', () => {
    // The field kind this project has already been bitten by: `gameEt` in the
    // NBA box score carries a `Z` and is Eastern time. Asserting the shape of
    // the designator is all a client can honestly do; the screen shows the raw
    // string beside the derived one so a reader can check the claim.
    //
    // Deliberately **not** pinned to a literal: `imported_at` is a wall clock
    // and changes on every capture, so a literal here would be flaky by
    // construction rather than informative.
    expect(payload.lineage.projection_import.imported_at).toMatch(/(Z|[+-]\d{2}:\d{2})$/)
  })

  it('pins the two digests, so a re-capture of a different cohort fails here', () => {
    // `imported_at` moves on every run; these do not. Pinning them literally is
    // what makes "the seed's writes did not change" a checkable statement from
    // the consumer side rather than something taken on the producer's word —
    // and it is what turns an unnoticed re-capture into a red test that forces
    // this file's docstring to be revisited alongside the new fixture. Same
    // discipline as the schedule grid pinning `schedule.version`.
    //
    // `content_sha256` is the generated CSV bytes; `projection_values_sha256`
    // is the stored normalised rates, and is the one that moves when a row is
    // edited in place while the other looks untouched.
    const { projection_import: imported } = payload.lineage

    expect(imported.content_sha256).toBe(
      '5970c8f285d606a489943e7d47479e261087bd336e17edf4dd3cb711ddf2356c',
    )
    expect(imported.projection_values_sha256).toBe(
      '25a89365aff066ec1bb01ebcedb8a39d74283820c6175546ba7ba42c5dbf6d27',
    )
  })

  it('pins the assumptions and labels the producer digests do not cover', () => {
    // **The gap in "the digests are unchanged, so the cohort is unchanged".**
    // `ReleasedProjectionImport` deliberately never selects
    // `source_games_played_assumptions`, and the player labels are read outside
    // any lineage scope — both stated as exemptions on
    // `CurrentProjectionsResponse`, and the first is the open
    // `release-digests-assumptions` item. So two matching digests are entirely
    // consistent with this array having changed, which is exactly the defect
    // that once served an *empty* assumptions array for a byte-identical
    // re-import while reporting a clean lineage.
    //
    // The producer cannot pin these yet. The consumer can, so it does: this is
    // coverage the endpoint's own guarantee does not provide, asserted on the
    // values a reader would actually see.
    const claims = payload.source_games_played_assumptions

    expect(claims).toHaveLength(60)
    expect(claims.every((claim) => claim.assumed_games_played !== null)).toBe(true)

    const games = claims.map((claim) => claim.assumed_games_played ?? 0)
    expect(Math.min(...games)).toBe(59)
    expect(Math.max(...games)).toBe(79)
    expect(claims.slice(0, 3)).toEqual([
      { player_id: 1, assumed_games_played: 65, assumed_games_played_raw: '65' },
      { player_id: 2, assumed_games_played: 73, assumed_games_played_raw: '73' },
      { player_id: 3, assumed_games_played: 59, assumed_games_played_raw: '59' },
    ])

    // Labels are outside the digest too, and this is the column a reader is
    // most likely to mistake for lineup eligibility.
    expect(payload.players[0]).toEqual({
      player_id: 1,
      full_name: 'Precious Achiuwa',
      team_abbreviation: 'SAC',
      primary_position: 'F',
    })
  })

  it('joins into a model with nothing to report', () => {
    const model = buildProjectionsModel(payload)

    expect(model.rows).toHaveLength(payload.projections.length)
    expect(model.integrity).toEqual({
      playersWithoutRates: 0,
      ratesWithoutPlayer: 0,
      duplicatePlayerRows: 0,
      duplicateRateRows: 0,
      duplicateAssumptionRows: 0,
      assumptionsWithoutRates: 0,
      unexplainedAssumptions: 0,
      rowCountMatchesLineage: true,
      isConsistent: true,
    })
  })

  it('renders every recorded player', () => {
    render(<ProjectionsTable model={buildProjectionsModel(payload)} />)

    expect(screen.getAllByTestId(/^projection-row-/)).toHaveLength(payload.projections.length)
    expect(screen.queryAllByTestId('unlabelled-player')).toHaveLength(0)
  })

  it('filters and sorts the recorded cohort as a reversible view over the same rows', () => {
    const before = JSON.stringify(payload)
    const model = buildProjectionsModel(payload)
    const sourceIds = model.rows.map((row) => row.playerId)
    const filtered = selectProjectionRows(model.rows, {
      searchQuery: 'precious',
      teamFilter: { kind: 'team', abbreviation: 'SAC' },
      sort: { key: 'points_per_game', direction: 'descending' },
    })
    const sorted = selectProjectionRows(model.rows, {
      searchQuery: '',
      teamFilter: { kind: 'all' },
      sort: { key: 'points_per_game', direction: 'descending' },
    })
    const reset = selectProjectionRows(model.rows, {
      searchQuery: '',
      teamFilter: { kind: 'all' },
      sort: null,
    })

    expect(filtered.map((row) => row.player?.full_name)).toEqual(['Precious Achiuwa'])
    expect(sorted).toHaveLength(model.rows.length)
    expect(new Set(sorted)).toEqual(new Set(model.rows))
    expect(reset.map((row) => row.playerId)).toEqual(sourceIds)
    expect(model.rows.map((row) => row.playerId)).toEqual(sourceIds)
    expect(JSON.stringify(payload)).toBe(before)
  })

  it('renders no rate × assumed_games_played product, against the real cohort', () => {
    // The ADR-002 backstop run against numbers the backend actually produced
    // rather than ones chosen for the test. `backend` flagged that this
    // payload is the live trap: every one of these assumptions is the exact
    // divisor used to produce the rates beside it, so each product recovers
    // the source's seasonal total.
    const model = buildProjectionsModel(payload)
    const { container } = render(<ProjectionsTable model={model} />)

    expect(detectForbiddenProducts(container, model)).toEqual([])
  })

  it('has something for the detector to have looked at, in every field', () => {
    // The green above means nothing if the cohort yielded no products to check
    // — a verifier that passes because it examined nothing is the defect this
    // project keeps finding. **Per field, not in aggregate:** the previous
    // magnitude floor excluded 278 of 960 real products here, including 60 of
    // 60 steals and 60 of 60 blocks, while an aggregate count looked healthy.
    const counts = discriminableProductCount(buildProjectionsModel(payload))

    for (const field of PROJECTION_RATE_FIELDS) {
      expect(counts[field], `${field} has no discriminable product`).toBeGreaterThan(0)
    }
  })

  it('renders exactly the agreed columns and no others', () => {
    const model = buildProjectionsModel(payload)
    const { container } = render(<ProjectionsTable model={model} />)

    expect(tableColumnHeaders(container)).toEqual([
      'Player',
      'Team',
      'Pos',
      ...PROJECTION_RATE_FIELDS.map((field) => RATE_LABELS[field]),
      'Source GP',
    ])
  })

  it('renders no absence marker in any rate cell or Source GP cell', () => {
    // The assertion behind the screen's own copy, which tells the reader a `·`
    // should not appear for this source. Scoped to the cells the claim is
    // about — review found the unqualified version false against this very
    // fixture, because a player with a null `primary_position` rendered one in
    // the Pos column under a key saying it meant something upstream changed.
    //
    // **Two DOM reads, not ~1,020.** This previously called `getByTestId` once
    // per cell — 60 players × 16 rates plus 60 assumptions — each a full
    // traversal with testing-library's suggestion machinery attached. It
    // measured 6,161 ms against vitest's 5,000 ms default and **timed out in
    // CI on the exact head this branch offered for merge**, while the
    // `pull_request` run of the same commit passed. It had been printing 3.1s,
    // 3.3s, 3.7s, 4.3s in local runs the whole time.
    //
    // A timeout is the failure mode a re-run erases: re-running turns an
    // assertion that never completed into a green check, permanently, and this
    // is the guard behind a sentence the screen prints to the reader. Raising
    // the timeout would have hidden it and left the next person to raise it
    // again.
    //
    // **The key-set assertion is not a rewrite of the loop, it is more than
    // the loop had.** `getByTestId` threw on a *missing* cell, so the old
    // version doubled as a completeness check — but it could never see an
    // *extra* cell, because it only asked for the ones it expected. Comparing
    // the rendered key set against the expected one catches both directions,
    // which is the discipline this module's own join already uses.
    const model = buildProjectionsModel(payload)
    const { container } = render(<ProjectionsTable model={model} />)

    // Scoped to `tbody`. An unscoped `[data-testid^="rate-"]` also matches the
    // 16 `rate-header-*` column headers — which the key-set assertion caught
    // on its first run, in the *extra cell* direction the `getByTestId` loop
    // this replaced could never have seen. Left as a comment rather than a
    // silent fix because it is the argument for the assertion's shape.
    const body = container.querySelector('tbody')
    expect(body).not.toBeNull()

    const rateCells = new Map(
      [...(body?.querySelectorAll('[data-testid^="rate-"]') ?? [])].map((cell) => [
        cell.getAttribute('data-testid') ?? '',
        cell.textContent ?? '',
      ]),
    )
    const assumptionCells = new Map(
      [...(body?.querySelectorAll('[data-testid^="assumption-"]') ?? [])].map((cell) => [
        cell.getAttribute('data-testid') ?? '',
        cell.getAttribute('data-assumption') ?? '',
      ]),
    )

    const expectedRateKeys = model.rows.flatMap((row) =>
      PROJECTION_RATE_FIELDS.map((field) => `rate-${String(row.playerId)}-${field}`),
    )
    const expectedAssumptionKeys = model.rows.map(
      (row) => `assumption-${String(row.playerId)}`,
    )

    // Both directions: a missing cell and an unexpected extra one both fail.
    expect([...rateCells.keys()].sort()).toEqual([...expectedRateKeys].sort())
    expect([...assumptionCells.keys()].sort()).toEqual([...expectedAssumptionKeys].sort())

    const withMarker = [...rateCells.entries()]
      .filter(([, text]) => text.includes(NOT_PUBLISHED))
      .map(([key]) => key)
    expect(withMarker).toEqual([])

    const notStated = [...assumptionCells.entries()]
      .filter(([, state]) => state !== 'stated')
      .map(([key]) => key)
    expect(notStated).toEqual([])
  })

  it('has a player with no position, which is why labels carry their own marker', () => {
    // Pins the case that disproved the earlier copy, so nobody restores the
    // unqualified claim. A label we do not hold says nothing about what
    // Basketball Monster published, and shares no marker with one that does.
    const unlabelled = payload.players.filter((player) => player.primary_position === null)
    expect(unlabelled.length).toBeGreaterThan(0)

    const model = buildProjectionsModel(payload)
    render(<ProjectionsTable model={model} />)

    const cell = screen.getByTestId(`position-${String(unlabelled[0]?.player_id ?? 0)}`)
    expect(cell).toHaveTextContent(NO_LABEL)
    expect(cell).not.toHaveTextContent(NOT_PUBLISHED)
  })

  it('renders no rate as null, because Basketball Monster cannot publish one', () => {
    // Not a formality. All 16 canonical fields are in this profile's
    // `required_production_fields`, and `parser.py:293-305` drops any row
    // missing one as fatal — so a stored Basketball Monster row carries a
    // value for every rate, by construction. The `·` marker is therefore a
    // contract guard on this screen rather than a state a user meets, and
    // this assertion is what would tell us if that ever stopped being true.
    for (const row of payload.projections) {
      for (const field of PROJECTION_RATE_FIELDS) {
        expect(row[field]).not.toBeNull()
      }
    }
  })

  it('has every assumption populated, which is why the sparse path is untested here', () => {
    // Asserted rather than only described, so that if a future re-capture does
    // carry sparse assumptions this test fails and the docstring above gets
    // corrected instead of quietly going stale — which is how three comments
    // in this repository came to describe fixtures they no longer matched.
    expect(payload.source_games_played_assumptions).toHaveLength(payload.projections.length)
    expect(
      payload.source_games_played_assumptions.every(
        (claim) => claim.assumed_games_played !== null,
      ),
    ).toBe(true)
  })

  it('has a clean identity resolution, which is why the review tail is untested here', () => {
    const { projection_import: imported } = payload.lineage

    expect(imported.needs_review_count).toBe(0)
    expect(imported.unmatched_count).toBe(0)
    expect(
      imported.matched_count +
        imported.needs_review_count +
        imported.unmatched_count +
        imported.rejected_count,
    ).toBe(imported.row_count)
  })
})
