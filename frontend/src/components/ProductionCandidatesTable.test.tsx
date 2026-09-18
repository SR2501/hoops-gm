import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import {
  SYNTHETIC_CATEGORY_ORDER,
  syntheticProductionCandidates,
} from '../test/productionCandidatesStub'
import { ProductionCandidatesTable } from './ProductionCandidatesTable'

describe('ProductionCandidatesTable with an explicitly synthetic payload', () => {
  it('preserves server candidate and category order', () => {
    const payload = syntheticProductionCandidates()
    render(<ProductionCandidatesTable payload={payload} />)

    const table = screen.getByTestId('production-candidates-table')
    const candidateRows = within(table).getAllByTestId(/^production-candidate-/)
    expect(candidateRows.map((row) => within(row).getByRole('rowheader').textContent)).toEqual([
      expect.stringContaining('Zulu Player'),
      expect.stringContaining('Alpha Player'),
    ])

    const headers = within(table)
      .getAllByRole('columnheader')
      .map((header) => header.textContent?.trim())
    expect(headers.slice(3, 12)).toEqual(
      SYNTHETIC_CATEGORY_ORDER.map((key) => {
        const labels = {
          pts: 'PTS',
          reb: 'REB',
          ast: 'AST',
          stl: 'STL',
          blk: 'BLK',
          fg3m: 'FG3M',
          to: 'TO',
          fg_pct: 'FG impact',
          ft_pct: 'FT impact',
        }
        return `${labels[key]} z`
      }),
    )
  })

  it('keeps the full-reference, exclusion, replacement, and null-VOR claims visible', () => {
    render(<ProductionCandidatesTable payload={syntheticProductionCandidates()} />)

    expect(screen.getByTestId('production-reference-counts')).toHaveTextContent(
      '3 scored before draft exclusion · 1 excluded · 2 candidates',
    )
    expect(screen.getByTestId('production-replacement-context')).toHaveTextContent(
      '12 × 13 = 156 structural slots · replacement ordinal 157',
    )
    expect(screen.getByTestId('production-replacement-context')).toHaveTextContent(
      'Structural shortfall 153 · replacement ordinal shortfall 154',
    )
    expect(screen.getAllByText('Unavailable')).toHaveLength(2)
  })

  it('prominently shows stored source metadata without turning it into authenticity proof', () => {
    const payload = syntheticProductionCandidates()
    render(<ProductionCandidatesTable payload={payload} />)

    const provenance = screen.getByTestId('production-source-provenance')
    expect(provenance).toHaveTextContent(payload.source_display_name)
    expect(provenance).toHaveTextContent('synthetic-production-candidates.csv')
    expect(screen.getByTestId('production-candidates-scope')).toHaveTextContent(
      'display metadata, not independently verified publisher identity, authenticity proof, a source classifier, or numeric fingerprint inputs',
    )
  })

  it('shows an absent original filename as not recorded', () => {
    const payload = syntheticProductionCandidates()
    payload.source_original_filename = null
    render(<ProductionCandidatesTable payload={payload} />)

    const provenance = screen.getByTestId('production-source-provenance')
    expect(within(provenance).getByText('Original filename')).toBeInTheDocument()
    expect(within(provenance).getByText('Not recorded')).toBeInTheDocument()
  })

  it('shows observation counts as separate facts and never labels missing rows healthy', () => {
    render(<ProductionCandidatesTable payload={syntheticProductionCandidates()} />)

    const observed = screen.getByText(/3 credited rows · 2025-26/)
    const none = screen.getByText('0 in declared window')

    expect(observed).toHaveClass('production-candidates__health--observed')
    expect(none).toHaveClass('production-candidates__health--none')
    expect(screen.queryByText(/^healthy$/i)).not.toBeInTheDocument()
    expect(observed).not.toHaveClass('status--ok')
    expect(none).not.toHaveClass('status--ok')
    expect(screen.getByTestId('production-health-context')).toHaveTextContent(
      'Row-level source provenance is not_recorded',
    )
  })

  it('expands raw inputs and directed components without computing player percentages', async () => {
    const user = userEvent.setup()
    render(<ProductionCandidatesTable payload={syntheticProductionCandidates()} />)

    const firstRow = screen.getByTestId('production-candidate-101')
    await user.click(within(firstRow).getByRole('button', { name: 'Why' }))

    const evidence = screen.getByRole('region', { name: 'Evidence for Zulu Player' })
    expect(within(evidence).getByText('8.500 / 17.250')).toBeInTheDocument()
    expect(within(evidence).getByText('4.750 / 5.500')).toBeInTheDocument()
    expect(evidence).toHaveTextContent(
      'No candidate raw-percentage comparison is computed here',
    )
    expect(evidence).toHaveTextContent('−1 from scorer')
    expect(evidence).toHaveTextContent('volume impact')
    expect(evidence).toHaveTextContent('metadata source not recorded')
    expect(evidence).toHaveTextContent('Row-level source provenance remains not_recorded')
  })

  it('states import-time and current-source calibration limits next to the scores', () => {
    const payload = syntheticProductionCandidates()
    render(<ProductionCandidatesTable payload={payload} />)

    const warning = screen.getByTestId('production-calibration-warning')
    expect(screen.getByTestId('production-candidates-scope')).toHaveTextContent(
      `Response generated ${payload.generated_at}`,
    )
    expect(warning).toHaveTextContent('not_established_for_current_selected_source')
    expect(warning).toHaveTextContent('not a vendor as-of timestamp or freshness validation')
    expect(warning).toHaveTextContent(
      'Frozen retrospective carry-forward evidence does not calibrate',
    )
  })

  it('renders every strategy and eligibility limitation as excluded', async () => {
    const user = userEvent.setup()
    render(<ProductionCandidatesTable payload={syntheticProductionCandidates()} />)

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
    expect(screen.getByText('production_blend → terminal')).toBeInTheDocument()
  })
})
