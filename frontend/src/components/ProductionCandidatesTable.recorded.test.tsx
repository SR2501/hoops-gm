/**
 * Contract and rendering coverage against the genuine normal-seed series release.
 *
 * Copied byte-for-byte from:
 * C:\Users\steverones\.copilot\session-state\d46e1efa-c5df-4003-a999-0f94f6b61d73\files\projection-series-candidate\frontend-http\normal-seed-candidates.json
 *
 * Response SHA-256: 68b91a609c1d285e9fa6758080345101c2d47fd4620d517c2d352d94bacb6907
 * Response size: 143894 bytes (exact HTTP response bytes plus one LF).
 *
 * Manifest recorded_at: 2026-09-18T20:55:48.663058+00:00.
 * Fresh disposable SQLite store migrated through Alembic 0024, real writers /
 * producers and normal seed_demo only, captured BEFORE any named-series import.
 * Draft 1 belongs to league 2, import 1, full reference 60 / candidates 53.
 *
 * The actual HTTP GET was /api/v1/drafts/1/production-candidates with the BBM
 * source and sole-series omission. No service/live source, hand-written scores
 * or metadata retagging was used. Native Copy-Item verified the manifest hash.
 *
 * draft-production-candidates.recorded.json remains the OLD unversioned
 * recording, unchanged and rejected by the successor client. This is synthetic
 * transport/render evidence, not Model PASS or promotion of an old model card.
 */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { isProductionCandidatesResponse } from '../api/productionCandidatesEndpoints'
import type { ProductionCandidatesResponse } from '../api/productionCandidatesTypes'
import recordedResponse from '../test/fixtures/draft-production-candidates.series-release.recorded.json'
import { ProductionCandidatesTable } from './ProductionCandidatesTable'

const RECORDED_CATEGORY_ORDER = [
  'ast',
  'blk',
  'pts',
  'reb',
  'stl',
  'fg3m',
  'to',
  'fg_pct',
  'ft_pct',
] as const

function payload(): ProductionCandidatesResponse {
  if (!isProductionCandidatesResponse(recordedResponse)) {
    throw new Error(
      'The recorded series-release production-candidates response no longer matches the client contract.',
    )
  }
  return structuredClone(recordedResponse)
}

describe('ProductionCandidatesTable with the normal-seed series-release HTTP response', () => {
  it('accepts and reconciles the normal-seed response', () => {
    const recorded = payload()
    const healthStates = recorded.candidates.reduce<Record<string, number>>(
      (counts, candidate) => {
        counts[candidate.health.status] = (counts[candidate.health.status] ?? 0) + 1
        return counts
      },
      {},
    )
    const ordinals = recorded.candidates.map((candidate) => candidate.ordinal)

    expect(recorded).toMatchObject({
      draft_id: 1,
      league_id: 2,
      season: '2026-27',
      source: 'basketball_monster',
      source_display_name: 'Basketball Monster (synthetic demo cohort)',
      source_original_filename: 'synthetic-projections-demo.csv',
    })
    expect(recorded.lineage.projection_import.import_id).toBe(1)
    expect(recorded.series).toEqual({
      key: 'legacy', display_name: 'Unspecified legacy series', provenance: 'legacy_unspecified',
    })
    expect(recorded.lineage.projection_import.release_schema_version).toBe(
      'projection-import-release-series-v1',
    )
    expect(recorded.lineage.score).toMatchObject({
      input_kind: 'production_blend',
      output_layer: 'terminal',
    })
    expect(recorded.lineage.score).not.toHaveProperty('input_layer')
    expect(recorded.category_scales.map((scale) => scale.category_key)).toEqual(
      RECORDED_CATEGORY_ORDER,
    )
    expect(
      recorded.lineage.blend.category_weights.map((weight) => weight.category_key),
    ).toEqual(RECORDED_CATEGORY_ORDER)
    expect(recorded.reference.count).toBe(60)
    expect(recorded.reference.player_ids).toHaveLength(60)
    expect(recorded.reference.excluded_drafted_player_ids).toHaveLength(7)
    expect(recorded.reference.candidate_count).toBe(53)
    expect(recorded.candidates).toHaveLength(53)
    expect(healthStates).toEqual({ no_observations: 48, observed: 5 })
    expect(
      recorded.candidates
        .filter((candidate) => candidate.health.status === 'observed')
        .map((candidate) => candidate.health.credited_appearances),
    ).toEqual([2, 2, 2, 2, 2])
    expect(
      recorded.candidates.every(
        (candidate) =>
          candidate.components.length === 9 &&
          candidate.components.every(
            (component, index) =>
              component.category_key === RECORDED_CATEGORY_ORDER[index],
          ),
      ),
    ).toBe(true)
    expect(ordinals).toEqual([...ordinals].sort((left, right) => left - right))
    expect(new Set(ordinals).size).toBe(ordinals.length)
    expect(recorded.replacement).toMatchObject({
      state: 'unavailable_insufficient_projected_pool',
      structural_roster_count: 156,
      replacement_ordinal: 157,
      projected_count: 60,
      structural_roster_shortfall: 96,
      replacement_ordinal_shortfall: 97,
      replacement_player_id: null,
      replacement_total_z: null,
    })
    expect(
      recorded.candidates.every((candidate) => candidate.value_above_replacement === null),
    ).toBe(true)
  })

  it('renders every candidate in response order with provenance and expandable evidence', async () => {
    const user = userEvent.setup()
    const recorded = payload()
    const { container } = render(<ProductionCandidatesTable payload={recorded} />)
    const table = screen.getByTestId('production-candidates-table')
    const rows = [
      ...table.querySelectorAll<HTMLTableRowElement>(
        'tr.production-candidates__candidate',
      ),
    ]

    expect(rows).toHaveLength(53)
    expect(
      rows.map((row) =>
        Number(row.getAttribute('data-testid')?.replace('production-candidate-', '')),
      ),
    ).toEqual(recorded.candidates.map((candidate) => candidate.player_id))
    expect(
      rows.map((row) =>
        Number(row.querySelector('.production-candidates__rank')?.textContent),
      ),
    ).toEqual(recorded.candidates.map((candidate) => candidate.ordinal))
    expect(
      rows.every((row) => row.querySelectorAll('[data-category-key]').length === 9),
    ).toBe(true)
    expect(container.querySelectorAll('.production-candidates__health--observed')).toHaveLength(5)
    expect(container.querySelectorAll('.production-candidates__health--none')).toHaveLength(48)
    expect(container.querySelectorAll('.production-candidates__health--unknown')).toHaveLength(0)
    expect(container.querySelectorAll('.production-candidates__unavailable')).toHaveLength(53)

    const provenance = screen.getByTestId('production-source-provenance')
    expect(provenance).toHaveTextContent('Basketball Monster (synthetic demo cohort)')
    expect(provenance).toHaveTextContent('synthetic-projections-demo.csv')
    expect(screen.getByTestId('production-candidates-scope')).toHaveTextContent(
      'not independently verified publisher identity',
    )
    expect(screen.getByTestId('production-reference-counts')).toHaveTextContent(
      '60 scored before draft exclusion · 7 excluded · 53 candidates',
    )
    expect(screen.getByTestId('production-replacement-context')).toHaveTextContent(
      'replacement ordinal 157',
    )
    expect(screen.getByTestId('production-replacement-context')).toHaveTextContent(
      'Structural shortfall 96 · replacement ordinal shortfall 97',
    )

    const first = recorded.candidates[0]!
    const firstRow = screen.getByTestId(`production-candidate-${String(first.player_id)}`)
    const evidenceButton = within(firstRow).getByRole('button', { name: 'Why' })
    await user.click(evidenceButton)

    expect(evidenceButton).toHaveAttribute('aria-expanded', 'true')
    const evidence = screen.getByRole('region', {
      name: `Evidence for ${first.full_name}`,
    })
    const componentTable = evidence.querySelector<HTMLTableElement>(
      '.production-candidates__component-table',
    )
    if (componentTable === null) {
      throw new Error('The expanded recorded row has no directed-component table.')
    }
    expect(within(componentTable).getAllByRole('row')).toHaveLength(10)
    expect(evidence).toHaveTextContent('Field goals made / attempted per game')
    expect(evidence).toHaveTextContent('Free throws made / attempted per game')

    await user.click(
      screen.getByText('Full lineage, category scales, and explicit limitations'),
    )
    const limitations = screen.getByTestId('production-limitations')
    expect(limitations).toHaveTextContent('Strategy included: no')
    expect(limitations).toHaveTextContent('Punt adjustment included: no')
    expect(limitations).toHaveTextContent('Budget or affordability included: no')
    expect(limitations).toHaveTextContent('Position fit included: no')
    expect(limitations).toHaveTextContent('Fantrax roster eligibility included: no')
    expect(limitations).toHaveTextContent('Partial browser increment: yes')
  })
})
