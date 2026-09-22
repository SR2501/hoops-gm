import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RETRYABLE_PRODUCTION_CANDIDATES_ERROR } from '../api/productionCandidatesErrors'
import { PRODUCTION_CANDIDATE_SOURCES } from '../api/productionCandidatesTypes'
import { requestUrl } from '../test/helpers'
import { syntheticProductionCandidates } from '../test/productionCandidatesStub'
import { withSingleSeriesCatalog } from '../test/projectionSeriesStub'
import {
  ProductionCandidatesPage,
  PRODUCTION_CANDIDATES_POLL_INTERVAL_MS,
} from './ProductionCandidatesPage'

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPage(route = '/draft/2/production-candidates') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route
          path="/draft/:draftId/production-candidates"
          element={<ProductionCandidatesPage />}
        />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('ProductionCandidatesPage', () => {
  it('uses the draft id in the header and requests Basketball Monster explicitly by default', async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL) =>
      Promise.resolve(response(syntheticProductionCandidates())),
    )
    vi.stubGlobal('fetch', withSingleSeriesCatalog(fetchMock))

    renderPage()

    expect(
      screen.getByRole('heading', { name: 'Production-only rankings · Draft 2' }),
    ).toBeInTheDocument()
    expect(await screen.findByTestId('production-candidates-table')).toBeInTheDocument()
    expect(requestUrl(fetchMock.mock.calls[0]![0])).toBe(
      '/api/v1/drafts/2/production-candidates?source=basketball_monster&series_key=legacy',
    )
  })

  it('labels all five choices as supported sources rather than available imports', async () => {
    vi.stubGlobal(
      'fetch',
      withSingleSeriesCatalog(vi.fn(() => Promise.resolve(response(syntheticProductionCandidates())))),
    )
    renderPage()

    const selector = screen.getByRole('combobox', { name: 'Supported sources' })
    expect(selector.querySelectorAll('option')).toHaveLength(
      PRODUCTION_CANDIDATE_SOURCES.length,
    )
    expect(screen.getByText(/Supported does not mean currently imported/)).toBeInTheDocument()
    await screen.findByTestId('production-candidates-table')
  })

  it.each([
    ['letters', 'not-a-number'],
    ['hexadecimal', '0x10'],
    ['exponential', '1e3'],
    ['decimal alias', '1.0'],
    ['leading whitespace', '%201'],
    ['trailing whitespace', '1%20'],
    ['plus sign', '%2B1'],
    ['minus sign', '-1'],
    ['leading zero', '01'],
    ['zero', '0'],
    ['unsafe integer', '9007199254740992'],
    ['rounding unsafe integer', '9007199254740993'],
  ])('makes no request for an invalid %s draft id', async (_label, rawDraftId) => {
    const fetchMock = vi.fn()
    // Count ALL I/O here: a catalog request for an invalid id is also a bug.
    vi.stubGlobal('fetch', fetchMock)

    renderPage(`/draft/${rawDraftId}/production-candidates`)

    expect(await screen.findByRole('alert')).toHaveTextContent('is not a draft id')
    await act(async () => {
      await Promise.resolve()
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it.each(['1', '42', '9007199254740991'])(
    'accepts canonical safe draft id %s without rewriting it',
    async (rawDraftId) => {
      const draftId = Number(rawDraftId)
      const fetchMock = vi.fn((_input: RequestInfo | URL) =>
        Promise.resolve(response(syntheticProductionCandidates({ draftId }))),
      )
      vi.stubGlobal('fetch', withSingleSeriesCatalog(fetchMock))

      renderPage(`/draft/${rawDraftId}/production-candidates`)

      expect(
        screen.getByRole('heading', {
          name: `Production-only rankings · Draft ${rawDraftId}`,
        }),
      ).toBeInTheDocument()
      expect(await screen.findByTestId('production-candidates-table')).toBeInTheDocument()
      expect(requestUrl(fetchMock.mock.calls[0]![0])).toBe(
        `/api/v1/drafts/${rawDraftId}/production-candidates?source=basketball_monster&series_key=legacy`,
      )
    },
  )

  it('retries an inconsistent snapshot exactly once and then renders success', async () => {
    let call = 0
    const fetchMock = vi.fn(() => {
      call += 1
      return Promise.resolve(
        call === 1
          ? response(
              {
                error: RETRYABLE_PRODUCTION_CANDIDATES_ERROR,
                detail: 'snapshot moved',
                request_id: 'req-moving',
              },
              409,
            )
          : response(syntheticProductionCandidates()),
      )
    })
    vi.stubGlobal('fetch', withSingleSeriesCatalog(fetchMock))

    renderPage()

    expect(await screen.findByTestId('production-candidates-table')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('does not retry another 409 refusal', async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        response(
          {
            error: 'production_candidates_source_not_imported',
            detail: 'no admitted fantasypros import',
            request_id: 'req-no-import',
          },
          409,
        ),
      ),
    )
    vi.stubGlobal('fetch', withSingleSeriesCatalog(fetchMock))

    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'no admitted projection import',
    )
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('keeps one whole last-good response visible and stops polling after a terminal refresh failure', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let call = 0
    const fetchMock = vi.fn(() => {
      call += 1
      return Promise.resolve(
        call === 1
          ? response(syntheticProductionCandidates())
          : response(
              {
                error: 'production_candidates_input_evidence_refused',
                detail: 'health fingerprint no longer agrees',
                request_id: 'req-health-moved',
              },
              409,
            ),
      )
    })
    vi.stubGlobal('fetch', withSingleSeriesCatalog(fetchMock))

    renderPage()
    expect(await screen.findByText('Zulu Player')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(PRODUCTION_CANDIDATES_POLL_INTERVAL_MS + 10)
    })

    expect(await screen.findByTestId('async-stale-failure')).toHaveTextContent(
      'health fingerprint no longer agrees',
    )
    expect(screen.getByText('Zulu Player')).toBeInTheDocument()
    expect(screen.getByText('Alpha Player')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(PRODUCTION_CANDIDATES_POLL_INTERVAL_MS * 3)
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('clears old-source rows immediately and ignores a late response from the abandoned scope', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let basketballMonsterCalls = 0
    let resolveLateBasketballMonster = (_response: Response): void => {
      throw new Error('late Basketball Monster poll did not start')
    }
    const lateBasketballMonster = new Promise<Response>((resolve) => {
      resolveLateBasketballMonster = resolve
    })

    const basketballMonster = syntheticProductionCandidates()
    basketballMonster.candidates[0]!.full_name = 'Initial BBM Player'
    const fantasyPros = syntheticProductionCandidates({ source: 'fantasypros' })
    fantasyPros.candidates[0]!.full_name = 'FantasyPros Player'
    const late = syntheticProductionCandidates()
    late.candidates[0]!.full_name = 'Late BBM Player'

    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = requestUrl(input)
      if (url.includes('source=fantasypros')) {
        return Promise.resolve(response(fantasyPros))
      }
      basketballMonsterCalls += 1
      return basketballMonsterCalls === 1
        ? Promise.resolve(response(basketballMonster))
        : lateBasketballMonster
    })
    vi.stubGlobal('fetch', withSingleSeriesCatalog(fetchMock))

    renderPage()
    expect(await screen.findByText('Initial BBM Player')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(PRODUCTION_CANDIDATES_POLL_INTERVAL_MS + 10)
    })
    await waitFor(() => {
      expect(basketballMonsterCalls).toBe(2)
    })

    fireEvent.change(screen.getByRole('combobox', { name: 'Supported sources' }), {
      target: { value: 'fantasypros' },
    })

    expect(screen.queryByText('Initial BBM Player')).not.toBeInTheDocument()
    expect(await screen.findByText('FantasyPros Player')).toBeInTheDocument()

    resolveLateBasketballMonster(response(late))
    await act(async () => {
      await Promise.resolve()
    })

    expect(screen.getByText('FantasyPros Player')).toBeInTheDocument()
    expect(screen.queryByText('Late BBM Player')).not.toBeInTheDocument()
  })

  it('changes the explicit source query when the reader selects another supported namespace', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = requestUrl(input)
      const source = url.includes('source=darko') ? 'darko' : 'basketball_monster'
      return Promise.resolve(response(syntheticProductionCandidates({ source })))
    })
    vi.stubGlobal('fetch', withSingleSeriesCatalog(fetchMock))

    renderPage()
    await screen.findByTestId('production-candidates-table')

    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Supported sources' }),
      'darko',
    )

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([input]) =>
          requestUrl(input).endsWith('production-candidates?source=darko&series_key=legacy'),
        ),
      ).toBe(true)
    })
    expect(await screen.findByText(/selected DARKO pool/)).toBeInTheDocument()
  })
})
