import { act, fireEvent, screen, within } from '@testing-library/react'
import { StrictMode } from 'react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { isReliabilityScorecardsResponse } from '../api/reliabilityEndpoints'
import type { ObservedRateEvidence, ReliabilityScorecardsResponse } from '../api/reliabilityTypes'
import notPublished from '../test/fixtures/reliability-not-published.recorded.json'
import recorded from '../test/fixtures/reliability-scorecards.recorded.json'
import { mockFetch, renderWithRouter } from '../test/helpers'
import {
  ReliabilityPage,
  RELIABILITY_PAGE_SIZE,
  RELIABILITY_STALE_AFTER_MS,
} from './ReliabilityPage'

function payload(): ReliabilityScorecardsResponse {
  if (!isReliabilityScorecardsResponse(recorded)) {
    throw new Error('The recorded reliability fixture no longer matches the frontend contract.')
  }
  return structuredClone(recorded)
}

function serve(body: unknown = payload()) {
  return mockFetch({ '/api/v1/reliability/scorecards': { body } })
}

function noB2BEvidence(): ObservedRateEvidence {
  return {
    direct_play: 0,
    direct_non_play: 0,
    explicit_unknown: 0,
    observed_opportunities: 0,
    observed_play_rate: null,
    observed_non_play_rate: null,
    coverage_status: 'incomplete_r35',
    opportunity_coverage: null,
  }
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('ReliabilityPage recorded contract', () => {
  it('renders the named evidence season, cohort counts, and the incomplete-coverage warning', async () => {
    serve()
    renderWithRouter(<ReliabilityPage />)

    expect(await screen.findByRole('heading', { name: '2025-26' })).toBeInTheDocument()
    expect(screen.getByTestId('cohort-scorecards')).toHaveTextContent('2')
    expect(screen.getByTestId('cohort-final-games')).toHaveTextContent('3')
    expect(screen.getByTestId('cohort-game-logs')).toHaveTextContent('4')
    expect(screen.getByTestId('cohort-participation-rows')).toHaveTextContent('2')
    expect(screen.getByTestId('coverage-warning')).toHaveTextContent(
      'Missing rows are not absences',
    )
    expect(screen.getByTestId('coverage-warning')).toHaveTextContent(
      'must not be read as season games played or predictions',
    )
    expect(screen.queryByTestId('synthetic-demo-warning')).not.toBeInTheDocument()
    expect(screen.getByText(/whether its evidence is historical or synthetic/)).toBeInTheDocument()
    expect(screen.getByText('Internal player record 1')).toBeInTheDocument()
    expect(screen.queryByText(/NBA player id/)).not.toBeInTheDocument()
  })

  it('shows all source labels in the lineage detail', async () => {
    serve()
    renderWithRouter(<ReliabilityPage />)

    await userEvent.click(
      await screen.findByText('Evidence lineage and cohort coverage', { selector: 'summary' }),
    )

    const lineage = screen.getByText('Schedule cohort').closest('dl')
    expect(lineage).not.toBeNull()
    expect(lineage).toHaveTextContent('test:canonical-schedule')
    expect(lineage).toHaveTextContent(
      'nba_games+team_schedule+player_game_logs+player_participation',
    )
    expect(lineage).toHaveTextContent('quant:reliability-descriptive-derivation')
  })

  it.each(['schedule_source', 'observation_source'] as const)(
    'shows the synthetic cohort disclosure before the coverage warning for synthetic %s',
    async (source) => {
      const body = payload()
      body.lineage[source] = `synthetic-demo:reliability-${source}`
      serve(body)
      renderWithRouter(<ReliabilityPage />)

      const warning = await screen.findByTestId('synthetic-demo-warning')
      expect(warning).toHaveTextContent('Synthetic demo cohort')
      expect(warning).toHaveTextContent(
        'Every game, box score, and resulting played-game observation is invented solely to exercise the interface',
      )
      expect(warning).toHaveTextContent(
        'not historical evidence, a projection, a recommendation, calibrated availability, or p(play)',
      )
      const coverageWarning = screen.getByTestId('coverage-warning')
      expect(warning.compareDocumentPosition(coverageWarning) & Node.DOCUMENT_POSITION_FOLLOWING)
        .toBeTruthy()
    },
  )

  it('loads the expensive cohort once under the application StrictMode wrapper', async () => {
    const fetchMock = serve()
    renderWithRouter(
      <StrictMode>
        <ReliabilityPage />
      </StrictMode>,
    )

    expect(await screen.findByRole('heading', { name: '2025-26' })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('shows direct non-play and back-to-back evidence without turning it into a score', async () => {
    serve()
    renderWithRouter(<ReliabilityPage />)

    const card = await screen.findByText('Glass Cannon')
    const summary = card.closest('summary')
    expect(summary).not.toBeNull()
    expect(summary).toHaveTextContent('1 play · 2 non-play · 0 explicit unknown')
    expect(summary).toHaveTextContent('1 non-play of 1')
    expect(summary).toHaveTextContent('33.3% direct-observation rate')

    const text = document.body.textContent ?? ''
    expect(text).not.toMatch(/\bgrade[:\s]+[A-F][+-]?\b/i)
    expect(text).not.toMatch(/\b(?:rank|fragility index)[:\s]+\d/i)
    expect(text).not.toMatch(/p\(play\)\s*[:=]?\s*0?\.\d/i)
  })

  it('keeps availability evidence and played-game production in separate regions', async () => {
    serve()
    renderWithRouter(<ReliabilityPage />)

    await userEvent.click(await screen.findByText('Iron Man'))
    const detail = screen.getByText('Iron Man').closest('details')
    expect(detail).not.toBeNull()
    expect(within(detail as HTMLElement).getByRole('heading', { name: 'Availability evidence' }))
      .toBeInTheDocument()
    expect(
      within(detail as HTMLElement).getByRole('heading', {
        name: 'Played-game production consistency',
      }),
    ).toBeInTheDocument()
    expect(detail).toHaveTextContent('A non-play observation is never inserted as zero production')
  })

  it('adds the published-rate visual before the exact monthly evidence table', async () => {
    serve()
    renderWithRouter(<ReliabilityPage />)

    await userEvent.click(await screen.findByText('Glass Cannon'))
    const detail = screen.getByText('Glass Cannon').closest('details')
    expect(detail).not.toBeNull()

    const card = within(detail as HTMLElement)
    const trace = card.getByRole('list', {
      name: 'Monthly direct-observation play-rate trace',
    })
    const traceRow = within(trace).getByRole('listitem')
    expect(traceRow).toHaveTextContent('2026-01')
    expect(traceRow).toHaveTextContent('33.3%')
    expect(traceRow).toHaveTextContent('1 direct play + 2 direct non-play = denominator 3')
    expect(traceRow).toHaveTextContent('0 explicit unknown (outside direct denominator)')
    expect(traceRow.querySelector('.monthly-observation-trace__fill')).toHaveStyle({
      inlineSize: '33.33333333333333%',
    })

    const tableRegion = card.getByRole('region', {
      name: 'Exact monthly availability evidence table',
    })
    expect(trace.compareDocumentPosition(tableRegion) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy()
    expect(within(tableRegion).getByRole('row', { name: /2026-01 1 2 0 33.3%/ }))
      .toBeInTheDocument()
  })

  it('labels percentage categories as volume-weighted impact and shows their attempt baseline', async () => {
    serve()
    renderWithRouter(<ReliabilityPage />)

    await userEvent.click(await screen.findByText('Iron Man'))
    const detail = screen.getByText('Iron Man').closest('details')
    expect(detail).not.toBeNull()
    const fgImpact = within(detail as HTMLElement).getByRole('row', { name: /FG impact/i })
    expect(fgImpact).toHaveTextContent('Volume-weighted impact')
    expect(fgImpact).toHaveTextContent('20/40 = 50.0%')
    expect(fgImpact).not.toHaveTextContent('Raw percentage')
  })

  it('surfaces no B2B evidence and a missing name as missing evidence, not zero quality', async () => {
    const body = payload()
    const card = body.scorecards[0]
    if (!card) throw new Error('Recorded fixture contains no scorecards.')
    card.player_name = null
    card.availability.back_to_back = noB2BEvidence()
    serve(body)
    renderWithRouter(<ReliabilityPage />)

    const player = await screen.findByText(`Name unavailable · player ${String(card.player_id)}`)
    const summary = player.closest('summary')
    expect(summary).not.toBeNull()
    expect(within(summary as HTMLElement).getByText('No direct B2B play/non-play observations'))
      .toBeInTheDocument()
    expect(within(summary as HTMLElement).getByText(/0 explicit unknown · back-to-back subset only/))
      .toBeInTheDocument()
    expect(screen.queryByText('0.0% direct-observation rate', { selector: 'strong' }))
      .not.toBeInTheDocument()
  })

  it('discloses explicit-unknown-only B2B evidence instead of classifying it as no evidence', async () => {
    const body = payload()
    const card = body.scorecards[0]
    if (!card) throw new Error('Recorded fixture contains no scorecards.')
    card.availability.back_to_back = {
      ...noB2BEvidence(),
      explicit_unknown: 2,
    }
    serve(body)
    renderWithRouter(<ReliabilityPage />)

    const player = await screen.findByText(card.player_name ?? '')
    const summary = player.closest('summary')
    expect(summary).toHaveTextContent('No direct B2B play/non-play observations')
    expect(summary).toHaveTextContent('2 explicit unknown')

    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Evidence filter' }),
      'no_b2b',
    )
    expect(screen.queryByText(card.player_name ?? '')).not.toBeInTheDocument()
  })

  it('searches and filters client-side without mounting a wall of expanded cards', async () => {
    serve()
    renderWithRouter(<ReliabilityPage />)
    await screen.findByText('Iron Man')

    await userEvent.type(screen.getByRole('searchbox', { name: 'Search player or id' }), 'glass')
    expect(screen.queryByText('Iron Man')).not.toBeInTheDocument()
    expect(screen.getByText('Glass Cannon')).toBeInTheDocument()

    await userEvent.clear(screen.getByRole('searchbox', { name: 'Search player or id' }))
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Evidence filter' }),
      'non_play',
    )
    expect(screen.queryByText('Iron Man')).not.toBeInTheDocument()
    expect(screen.getByText('Glass Cannon')).toBeInTheDocument()
    expect(document.querySelectorAll('details[open]')).toHaveLength(0)
  })

  it('mounts only the first page for a 596-style cohort and progressively reveals more', async () => {
    const body = payload()
    const template = body.scorecards[0]
    if (!template) throw new Error('Recorded fixture contains no scorecards.')
    body.scorecards = Array.from({ length: 75 }, (_, index) => ({
      ...structuredClone(template),
      player_id: index + 1,
      player_name: `Player ${String(index + 1).padStart(3, '0')}`,
    }))
    body.counts.scorecards = body.scorecards.length
    serve(body)
    renderWithRouter(<ReliabilityPage />)

    expect(await screen.findByTestId('reliability-result-count')).toHaveTextContent(
      `Showing ${String(RELIABILITY_PAGE_SIZE)} of 75 matching players`,
    )
    expect(document.querySelectorAll('.reliability-card')).toHaveLength(RELIABILITY_PAGE_SIZE)
    await userEvent.click(screen.getByRole('button', { name: 'Show 25 more' }))
    expect(document.querySelectorAll('.reliability-card')).toHaveLength(75)
  })

  it('renders the live demo unpublished-cohort refusal as an actionable data state', async () => {
    mockFetch({
      '/api/v1/reliability/scorecards': { status: 409, body: notPublished },
    })
    renderWithRouter(<ReliabilityPage />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Reliability evidence has not been published for this store')
    expect(alert).toHaveTextContent('python -m hoops_gm.dev.publish_reliability_evidence')
    expect(alert).toHaveTextContent('Code reliability_not_published')
    expect(alert).toHaveTextContent('Request recorded-reliability-not-published')
  })

  it('marks an open page stale and offers manual refresh rather than polling', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-01T12:00:00Z'))
    const fetchMock = serve()
    renderWithRouter(<ReliabilityPage />)
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    const requestCount = fetchMock.mock.calls.length

    act(() => {
      vi.advanceTimersByTime(RELIABILITY_STALE_AFTER_MS)
    })

    expect(screen.getByText(/Showing data from/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(requestCount)
  })

  it('shows an explicit empty result when filters match nobody', async () => {
    serve()
    renderWithRouter(<ReliabilityPage />)
    await screen.findByText('Iron Man')

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'nobody here' } })
    expect(screen.getByText('No players match this search and evidence filter.'))
      .toBeInTheDocument()
  })
})
