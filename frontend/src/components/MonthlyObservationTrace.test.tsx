import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { MonthlyRateEvidence } from '../api/reliabilityTypes'
import {
  MONTHLY_OBSERVATION_TRACE_LIMITATION,
  MonthlyObservationTrace,
} from './MonthlyObservationTrace'

function month(
  value: string,
  directPlay: number,
  directNonPlay: number,
  explicitUnknown: number,
  observedPlayRate: number | null,
): MonthlyRateEvidence {
  const observedOpportunities = directPlay + directNonPlay
  return {
    month: value,
    evidence: {
      direct_play: directPlay,
      direct_non_play: directNonPlay,
      explicit_unknown: explicitUnknown,
      observed_opportunities: observedOpportunities,
      observed_play_rate: observedPlayRate,
      observed_non_play_rate: observedPlayRate === null ? null : 1 - observedPlayRate,
      coverage_status: 'incomplete_r35',
      opportunity_coverage: null,
    },
  }
}

describe('MonthlyObservationTrace', () => {
  it('renders chronological 0, middle, 1, and unavailable boundaries with exact evidence labels', () => {
    render(
      <MonthlyObservationTrace
        months={[
          month('2025-11-01', 0, 4, 0, 0),
          month('2025-12-01', 2, 2, 1, 0.5),
          month('2026-01-01', 4, 0, 0, 1),
          month('2026-02-01', 0, 0, 3, null),
        ]}
      />,
    )

    const rows = screen.getAllByRole('listitem')
    expect(
      screen.getByRole('list', { name: 'Monthly direct-observation play-rate trace' }),
    ).toBeInTheDocument()
    expect(rows).toHaveLength(4)
    expect(rows.map((row) => within(row).getByRole('time').textContent)).toEqual([
      '2025-11',
      '2025-12',
      '2026-01',
      '2026-02',
    ])
    expect(rows.map((row) => within(row).getByText(/%|Unavailable/).textContent)).toEqual([
      '0.0%',
      '50.0%',
      '100.0%',
      'Unavailable',
    ])
    expect(rows[0]?.querySelector('.monthly-observation-trace__fill')).toHaveStyle({
      inlineSize: '0%',
    })
    expect(rows[1]?.querySelector('.monthly-observation-trace__fill')).toHaveStyle({
      inlineSize: '50%',
    })
    expect(rows[2]?.querySelector('.monthly-observation-trace__fill')).toHaveStyle({
      inlineSize: '100%',
    })
    expect(rows[3]?.querySelector('.monthly-observation-trace__fill')).not.toBeInTheDocument()
    expect(rows[1]).toHaveTextContent('2 direct play + 2 direct non-play = denominator 4')
    expect(rows[1]).toHaveTextContent('1 explicit unknown (outside direct denominator)')
    expect(rows[3]).toHaveTextContent('3 explicit unknown (outside direct denominator)')
  })

  it('uses the endpoint rate for the visual length instead of recomputing from counts', () => {
    const sourceRateSentinel = month('2026-03-01', 1, 3, 0, 0.625)

    render(<MonthlyObservationTrace months={[sourceRateSentinel]} />)

    expect(screen.getByText('62.5%')).toBeInTheDocument()
    expect(document.querySelector('.monthly-observation-trace__fill')).toHaveStyle({
      inlineSize: '62.5%',
    })
    expect(screen.getByText(/1 direct play \+ 3 direct non-play = denominator 4/))
      .toBeInTheDocument()
  })

  it('states the direct-observation boundary without assigning direction or judgment', () => {
    const { container } = render(
      <MonthlyObservationTrace months={[month('2026-01-01', 1, 1, 0, 0.5)]} />,
    )

    expect(screen.getByText(MONTHLY_OBSERVATION_TRACE_LIMITATION)).toBeInTheDocument()
    expect(container.textContent).not.toMatch(
      /\b(?:improving|declining|rising|falling|upward|downward)\b/i,
    )
    expect(container.textContent).not.toMatch(/\b(?:low|medium|high) risk\b/i)
    expect(container.textContent).not.toMatch(/\b(?:rank|recommendation)[:\s]+\d/i)
    expect(container.textContent).not.toMatch(/\bgrade[:\s]+[A-F][+-]?\b/i)
    expect(container.textContent).not.toMatch(/\bcomposite[:\s]+\d/i)
    expect(container.textContent).not.toMatch(/\bprojected games[:\s]+\d/i)
    expect(container.textContent).not.toMatch(/p\(play\)\s*[:=]?\s*0?\.\d/i)
  })

  it('keeps the no-months state explicit', () => {
    render(<MonthlyObservationTrace months={[]} />)

    expect(screen.getByText('No monthly direct observations are available.')).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })
})
