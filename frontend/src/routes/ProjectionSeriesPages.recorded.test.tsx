/**
 * Real client + useAsync + React against genuine named-series HTTP recordings.
 * This is jsdom interaction coverage, NOT actual-browser observation.
 * Capture provenance is in test/projectionSeriesRecordings.ts. Adversarial
 * catalog subsets / delayed replies below are explicitly transport test cases;
 * neither the captured JSON files nor any producer scores are rewritten.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  candidateRecordings,
  projectionRecordings,
  recordedDraftCatalog,
  recordedLeagueCatalog,
  recordedSingleCatalog,
} from '../test/projectionSeriesRecordings'
import { requestUrl } from '../test/helpers'
import { PROJECTION_RATE_FIELDS } from '../api/types'
import { ProjectionsPage, STALE_AFTER_MS } from './ProjectionsPage'
import {
  ProductionCandidatesPage,
  PRODUCTION_CANDIDATES_POLL_INTERVAL_MS,
  PRODUCTION_CANDIDATES_STALE_AFTER_MS,
} from './ProductionCandidatesPage'

type Surface = 'projections' | 'candidates'
type SeriesKey = keyof typeof projectionRecordings
const TIMEOUT_MS = 10_000

const paths = {
  projections: {
    catalog: '/api/v1/leagues/1/projections/series',
    numerical: '/api/v1/leagues/1/projections/current',
    route: '/projections',
    table: 'projections-table',
    summary: 'projection-import-summary',
  },
  candidates: {
    catalog: '/api/v1/drafts/1/projection-series',
    numerical: '/api/v1/drafts/1/production-candidates',
    route: '/draft/1/production-candidates',
    table: 'production-candidates-table',
    summary: 'production-candidates-scope',
  },
} as const

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'series-ui-test' },
  })
}

function deferred() {
  let resolve!: (value: Response) => void
  const promise = new Promise<Response>((complete) => { resolve = complete })
  return { promise, resolve }
}

function catalogFor(surface: Surface, keys: SeriesKey[] = ['bonus', 'josh', 'legacy']) {
  if (surface === 'candidates' && keys.length === 1 && keys[0] === 'legacy') {
    return structuredClone(recordedSingleCatalog)
  }
  const catalog = structuredClone(surface === 'projections' ? recordedLeagueCatalog : recordedDraftCatalog)
  catalog.series = catalog.series.filter((entry) => keys.includes(entry.key as SeriesKey))
  catalog.selection_required = catalog.series.length > 1
  return catalog
}

function recording(surface: Surface, key: SeriesKey) {
  return surface === 'projections' ? projectionRecordings[key] : candidateRecordings[key]
}

function serve(surface: Surface, overrides: {
  catalog?: (url: URL) => Promise<Response>
  numerical?: (url: URL, init?: RequestInit) => Promise<Response>
} = {}) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(requestUrl(input), 'http://127.0.0.1')
    if (url.pathname.endsWith('/projection-series') || url.pathname.endsWith('/projections/series')) {
      return overrides.catalog?.(url) ?? Promise.resolve(response(catalogFor(surface)))
    }
    if (url.pathname.endsWith('/production-candidates') || url.pathname.endsWith('/projections/current')) {
      if (overrides.numerical) return overrides.numerical(url, init)
      const key = url.searchParams.get('series_key')
      if (key !== 'legacy' && key !== 'josh' && key !== 'bonus') {
        throw new Error(`Unexpected numerical request without an explicit recorded key: ${url.href}`)
      }
      return Promise.resolve(response(recording(surface, key)))
    }
    throw new Error(`Unexpected request: ${url.href}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function DraftNavigation() {
  const navigate = useNavigate()
  return <button type="button" onClick={() => { void navigate('/draft/2/production-candidates') }}>Open draft 2</button>
}

function mount(surface: Surface) {
  return render(
    <MemoryRouter initialEntries={[paths[surface].route]}>
      <DraftNavigation />
      <Routes>
        <Route path="/projections" element={<ProjectionsPage />} />
        <Route path="/draft/:draftId/production-candidates" element={<ProductionCandidatesPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

function choose(key: string) {
  fireEvent.change(screen.getByRole('combobox', { name: 'Projection series' }), { target: { value: key } })
}

async function loadJosh(surface: Surface) {
  await screen.findByRole('combobox', { name: 'Projection series' })
  choose('josh')
  await screen.findByTestId(paths[surface].table)
}

async function refreshNumerical(surface: Surface) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(
      surface === 'projections' ? STALE_AFTER_MS + 1 : PRODUCTION_CANDIDATES_POLL_INTERVAL_MS + 1,
    )
  })
  if (surface === 'projections') fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

for (const surface of ['projections', 'candidates'] as const) {
  describe(`${surface}: recorded series choice`, () => {
    it('does not choose first/latest in a multi-series catalog (legacy counts) or issue a numerical read', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      const fetchMock = serve(surface)
      mount(surface)
      const chooser = await screen.findByRole('combobox', { name: 'Projection series' })
      expect(chooser).toHaveValue('')
      expect(within(chooser).getAllByRole('option').map((option) => option.getAttribute('value')))
        .toEqual(['', 'bonus', 'josh', 'legacy'])
      expect(screen.getByRole('status')).toHaveTextContent('Choose a projection series')
      expect(screen.queryByTestId(paths[surface].table)).not.toBeInTheDocument()
      await act(async () => { await vi.advanceTimersByTimeAsync(8000) })
      expect(fetchMock).toHaveBeenCalledTimes(1)
      expect(requestUrl(fetchMock.mock.calls[0]![0])).toBe(`${paths[surface].catalog}?source=basketball_monster`)
    }, TIMEOUT_MS)

    it('shows zero recorded imports honestly and sends no numerical read', async () => {
      const fetchMock = serve(surface, { catalog: () => Promise.resolve(response(catalogFor(surface, []))) })
      mount(surface)
      expect(await screen.findByText(/No recorded projection imports for this source and season/)).toBeVisible()
      expect(screen.getByRole('combobox', { name: 'Projection series' })).toBeDisabled()
      expect(fetchMock).toHaveBeenCalledTimes(1)
      expect(screen.queryByTestId(paths[surface].table)).not.toBeInTheDocument()
    })

    it.each(['legacy', 'josh'] as const)('auto-selects a sole %s series but still sends its key explicitly', async (key) => {
      const fetchMock = serve(surface, { catalog: () => Promise.resolve(response(catalogFor(surface, [key]))) })
      mount(surface)
      await screen.findByTestId(paths[surface].table)
      expect(screen.getByRole('combobox', { name: 'Projection series' })).toHaveValue(key)
      expect(fetchMock.mock.calls.map(([input]) => requestUrl(input))).toEqual([
        `${paths[surface].catalog}?source=basketball_monster`,
        `${paths[surface].numerical}?source=basketball_monster&series_key=${key}`,
      ])
      expect(screen.getByTestId(paths[surface].summary)).toHaveTextContent(recording(surface, key).series.display_name)
    })

    it('loads distinct genuine Josh, Bonus, and legacy responses with visible exact-import lineage', async () => {
      const user = userEvent.setup()
      const fetchMock = serve(surface)
      mount(surface)
      await screen.findByRole('combobox', { name: 'Projection series' })
      for (const key of ['josh', 'bonus', 'legacy'] as const) {
        choose(key)
        await screen.findByTestId(paths[surface].table)
        const payload = recording(surface, key)
        const imported = payload.lineage.projection_import
        const summary = screen.getByTestId(paths[surface].summary)
        expect(summary).toHaveTextContent(payload.source_display_name)
        expect(summary).toHaveTextContent(payload.series.display_name)
        expect(within(summary).getByText(new RegExp(`\\bimport ${String(imported.import_id)}\\b`, 'i'))).toBeVisible()
        expect(within(summary).getByText(imported.imported_at, { exact: true })).toBeVisible()
        const filename = surface === 'projections'
          ? projectionRecordings[key].lineage.projection_import.original_filename
          : candidateRecordings[key].source_original_filename
        expect(within(summary).getByText(filename!, { exact: true })).toBeVisible()
        expect(summary).toHaveTextContent(imported.profile_id)
        expect(summary.closest('details')).toBeNull()

        if (surface === 'projections') {
          const recorded = projectionRecordings[key]
          const first = recorded.projections[0]!
          for (const field of PROJECTION_RATE_FIELDS) {
            expect(screen.getByTestId(`rate-${String(first.player_id)}-${field}`))
              .toHaveTextContent(first[field]!.toFixed(2))
          }
          expect(screen.getByTestId(`assumption-${String(first.player_id)}`))
            .toHaveTextContent(String(recorded.source_games_played_assumptions[0]!.assumed_games_played))
          await user.click(screen.getByText(/Full import lineage/))
        } else {
          const recorded = candidateRecordings[key]
          const rows = screen.getAllByTestId(/^production-candidate-\d+$/)
          expect(rows.map((row) => row.getAttribute('data-testid'))).toEqual(
            recorded.candidates.map((candidate) => `production-candidate-${String(candidate.player_id)}`),
          )
          for (const [index, row] of rows.entries()) {
            expect(row.querySelector('.production-candidates__score--total'))
              .toHaveTextContent(recorded.candidates[index]!.total_z.toFixed(3))
          }
          await user.click(screen.getByText('Full lineage, category scales, and explicit limitations'))
        }
        expect(screen.getByText(imported.content_sha256, { exact: true })).toBeVisible()
        expect(screen.getByText(imported.profile_definition_sha256, { exact: true })).toBeVisible()
        expect(screen.getByText(imported.projection_values_sha256, { exact: true })).toBeVisible()
      }
      expect(fetchMock.mock.calls.map(([input]) => requestUrl(input))).toEqual([
        `${paths[surface].catalog}?source=basketball_monster`,
        ...['josh', 'bonus', 'legacy'].map((key) => `${paths[surface].numerical}?source=basketball_monster&series_key=${key}`),
      ])
    }, TIMEOUT_MS)

    it('keeps the explicit key when inventory changes and never wraps catalog labels around old rows', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      let inventory = catalogFor(surface)
      const fetchMock = serve(surface, { catalog: () => Promise.resolve(response(inventory)) })
      mount(surface)
      await loadJosh(surface)
      const original = screen.getByTestId(paths[surface].summary).innerHTML
      inventory = catalogFor(surface)
      const josh = inventory.series.find((entry) => entry.key === 'josh')!
      josh.display_name = 'Catalog-only revised label'
      josh.latest_import.original_filename = 'catalog-only-not-yet-read.csv'
      josh.latest_import.import_id = 999
      fireEvent.click(screen.getByRole('button', { name: 'Reload series' }))
      await screen.findByRole('option', { name: /Catalog-only revised label/ })
      expect(screen.getByRole('combobox', { name: 'Projection series' })).toHaveValue('josh')
      expect(screen.getByTestId(paths[surface].summary).innerHTML).toBe(original)
      expect(fetchMock.mock.calls.filter(([input]) => requestUrl(input).includes(paths[surface].numerical))).toHaveLength(1)
    })

    it('does not silently substitute the sole remaining series when the selected key disappears from inventory', async () => {
      let inventory = catalogFor(surface)
      const fetchMock = serve(surface, { catalog: () => Promise.resolve(response(inventory)) })
      mount(surface)
      await loadJosh(surface)
      inventory = catalogFor(surface, ['bonus'])
      fireEvent.click(screen.getByRole('button', { name: 'Reload series' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('No other series was substituted')
      expect(screen.getByRole('combobox', { name: 'Projection series' })).toHaveValue('josh')
      expect(screen.queryByTestId(paths[surface].table)).not.toBeInTheDocument()
      expect(fetchMock.mock.calls.filter(([input]) => requestUrl(input).includes(paths[surface].numerical))).toHaveLength(1)
    })

    it('mounts a cold choice boundary when the same resource catalog reports another season', async () => {
      let inventory = catalogFor(surface)
      const fetchMock = serve(surface, { catalog: () => Promise.resolve(response(inventory)) })
      mount(surface)
      await loadJosh(surface)
      inventory = { ...catalogFor(surface), season: '2025-26' }
      fireEvent.click(screen.getByRole('button', { name: 'Reload series' }))
      await screen.findByText(/season 2025-26/)
      expect(screen.getByRole('combobox', { name: 'Projection series' })).toHaveValue('')
      expect(screen.queryByTestId(paths[surface].table)).not.toBeInTheDocument()
      expect(screen.queryByTestId(paths[surface].summary)).not.toBeInTheDocument()
      expect(fetchMock.mock.calls.filter(([input]) => requestUrl(input).includes(paths[surface].numerical))).toHaveLength(1)
    })

    it('mounts cold on a series switch and ignores an abandoned numerical refresh even if it resolves late', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      const abandoned = deferred()
      const incoming = deferred()
      let reads = 0
      let abandonedSignal: AbortSignal | null | undefined
      serve(surface, {
        numerical: (url, init) => {
          if (url.searchParams.get('series_key') === 'bonus') return incoming.promise
          if (++reads === 1) return Promise.resolve(response(recording(surface, 'josh')))
          abandonedSignal = init?.signal
          return abandoned.promise
        },
      })
      mount(surface)
      await loadJosh(surface)
      await refreshNumerical(surface)
      await waitFor(() => { expect(reads).toBe(2) })
      choose('bonus')
      expect(screen.queryByTestId(paths[surface].table)).not.toBeInTheDocument()
      expect(screen.queryByTestId(paths[surface].summary)).not.toBeInTheDocument()
      expect(abandonedSignal?.aborted).toBe(true)
      await act(async () => {
        abandoned.resolve(response(recording(surface, 'josh')))
        await Promise.resolve()
      })
      expect(screen.queryByTestId(paths[surface].table)).not.toBeInTheDocument()
      await act(async () => {
        incoming.resolve(response(recording(surface, 'bonus')))
        await Promise.resolve()
      })
      expect(await screen.findByTestId(paths[surface].summary)).toHaveTextContent('Bonus (synthetic)')
      expect(screen.getByTestId(paths[surface].summary)).not.toHaveTextContent('Josh (synthetic)')
    }, TIMEOUT_MS)

    it('clears the catalog as well as rows on a publisher switch and ignores a late old inventory', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      const abandoned = deferred()
      const incoming = deferred()
      let oldCatalogReads = 0
      serve(surface, {
        catalog: (url) => {
          if (url.searchParams.get('source') === 'fantasypros') return incoming.promise
          return ++oldCatalogReads === 1 ? Promise.resolve(response(catalogFor(surface))) : abandoned.promise
        },
      })
      mount(surface)
      await loadJosh(surface)
      fireEvent.click(screen.getByRole('button', { name: 'Reload series' }))
      await waitFor(() => { expect(oldCatalogReads).toBe(2) })
      fireEvent.change(screen.getByRole('combobox', { name: 'Supported sources' }), { target: { value: 'fantasypros' } })
      expect(screen.queryByTestId(paths[surface].table)).not.toBeInTheDocument()
      expect(screen.queryByRole('combobox', { name: 'Projection series' })).not.toBeInTheDocument()
      await act(async () => {
        abandoned.resolve(response(catalogFor(surface)))
        await Promise.resolve()
      })
      expect(screen.queryByRole('combobox', { name: 'Projection series' })).not.toBeInTheDocument()
      const empty = { ...catalogFor(surface, []), source: 'fantasypros', source_display_name: null }
      await act(async () => {
        incoming.resolve(response(empty))
        await Promise.resolve()
      })
      expect(await screen.findByText(/No recorded projection imports/)).toBeVisible()
      expect(screen.queryByTestId(paths[surface].table)).not.toBeInTheDocument()
    }, TIMEOUT_MS)

    it('retains exactly the whole same-scope last-good payload after a wrong-series HTTP200 and stops polling', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      let reads = 0
      serve(surface, {
        numerical: () => Promise.resolve(response(recording(surface, ++reads === 1 ? 'josh' : 'bonus'))),
      })
      mount(surface)
      await loadJosh(surface)
      const oldRows = screen.getByTestId(paths[surface].table).innerHTML
      const oldLineage = screen.getByTestId(paths[surface].summary).innerHTML
      await refreshNumerical(surface)
      expect(await screen.findByTestId('async-stale-failure')).toHaveTextContent('invalid_response')
      expect(screen.getByTestId(paths[surface].table).innerHTML).toBe(oldRows)
      expect(screen.getByTestId(paths[surface].summary).innerHTML).toBe(oldLineage)
      await act(async () => { await vi.advanceTimersByTimeAsync(20_000) })
      expect(reads).toBe(2)
    }, TIMEOUT_MS)

    it('replaces a same-series current import as a whole on refresh without historical pinning', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      // UI-only future-response metadata stub; recorded rates/scores stay intact.
      const newer = structuredClone(recording(surface, 'josh'))
      newer.series.display_name = 'Josh later import (synthetic transport case)'
      newer.lineage.projection_import.import_id = 202
      newer.lineage.projection_import.imported_at = '2026-09-19T12:00:00Z'
      const imported = newer.lineage.projection_import
      if ('original_filename' in imported) imported.original_filename = 'synthetic-josh-later.csv'
      if ('source_original_filename' in newer) newer.source_original_filename = 'synthetic-josh-later.csv'
      let reads = 0
      const fetchMock = serve(surface, {
        numerical: () => Promise.resolve(response(++reads === 1 ? recording(surface, 'josh') : newer)),
      })
      mount(surface)
      await loadJosh(surface)
      await refreshNumerical(surface)
      await waitFor(() => { expect(screen.getByTestId(paths[surface].summary)).toHaveTextContent(newer.series.display_name) })
      expect(screen.getByTestId(paths[surface].summary)).toHaveTextContent('synthetic-josh-later.csv')
      expect(screen.getByTestId(paths[surface].summary)).toHaveTextContent('2026-09-19T12:00:00Z')
      expect(screen.getByRole('combobox', { name: 'Projection series' })).toHaveValue('josh')
      expect(fetchMock.mock.calls.filter(([input]) => requestUrl(input).includes(paths[surface].numerical))
        .every(([input]) => requestUrl(input).endsWith('source=basketball_monster&series_key=josh'))).toBe(true)
    }, TIMEOUT_MS)

    it.each([
      ['series_required', 409, 'An explicit choice is required'],
      ['series_not_imported', 404, 'not imported'],
      ['validation_error', 422, 'blank, malformed, or repeated series key'],
    ] as const)('shows terminal %s copy without retries, polling or fallback', async (suffix, status, copy) => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      const prefix = surface === 'projections' ? 'projections' : 'production_candidates'
      const code = suffix === 'validation_error' ? suffix : `${prefix}_${suffix}`
      const fetchMock = serve(surface, {
        numerical: () => Promise.resolve(response({ error: code, detail: 'selector refused by backend', request_id: 'selector-refusal' }, status)),
      })
      mount(surface)
      await screen.findByRole('combobox', { name: 'Projection series' })
      choose('josh')
      expect(await screen.findByRole('alert')).toHaveTextContent(copy)
      expect(screen.getByRole('alert')).toHaveTextContent('selector-refusal')
      expect(screen.queryByTestId(paths[surface].table)).not.toBeInTheDocument()
      await act(async () => { await vi.advanceTimersByTimeAsync(20_000) })
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })

    it('shows invalid inventory as a terminal refusal rather than an empty or admitted list', async () => {
      const fetchMock = serve(surface, {
        catalog: () => Promise.resolve(response({
          error: 'projection_series_incomplete_evidence', detail: 'invalid recorded descriptor', request_id: 'inventory-refusal',
        }, 409)),
      })
      mount(surface)
      expect(await screen.findByRole('alert')).toHaveTextContent('invalid or incomplete evidence')
      expect(screen.queryByRole('combobox', { name: 'Projection series' })).not.toBeInTheDocument()
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })
  })
}

describe('draft and season cold boundaries', () => {
  it('uses the selected publisher in projection captions and GP copy rather than labelling every source BBM', async () => {
    const manual = structuredClone(projectionRecordings.josh)
    manual.source = manual.lineage.projection_import.source = 'manual'
    manual.source_display_name = 'Synthetic manual rates'
    const fetchMock = serve('projections', {
      catalog: (url) => Promise.resolve(response(url.searchParams.get('source') === 'manual'
        ? { ...catalogFor('projections', ['josh']), source: 'manual', source_display_name: 'Synthetic manual inventory' }
        : recordedLeagueCatalog)),
      numerical: () => Promise.resolve(response(manual)),
    })
    const { container } = mount('projections')
    fireEvent.change(screen.getByRole('combobox', { name: 'Supported sources' }), { target: { value: 'manual' } })
    await screen.findByTestId(paths.projections.table)
    expect(screen.getByTestId(paths.projections.table).querySelector('caption'))
      .toHaveTextContent('Synthetic manual rates · Josh (synthetic)')
    expect(screen.getByRole('button', { name: 'Sort by Manual import source games played ascending' })).toBeVisible()
    expect(container.querySelector('.grid__key')).not.toHaveTextContent('Basketball Monster')
    expect(container.querySelector('.grid__key')).toHaveTextContent('what the selected source assumed')
    expect(fetchMock.mock.calls.map(([input]) => requestUrl(input))).toContain(
      '/api/v1/leagues/1/projections/current?source=manual&series_key=josh',
    )
  })

  it('does not carry selection or late rows into another draft and uses that draft catalog’s league/season', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const lateRows = deferred()
    const newCatalog = deferred()
    let oldReads = 0
    const fetchMock = serve('candidates', {
      catalog: (url) => url.pathname.includes('/drafts/2/')
        ? newCatalog.promise : Promise.resolve(response(recordedDraftCatalog)),
      numerical: (url) => {
        if (url.pathname.includes('/drafts/1/')) {
          return ++oldReads === 1 ? Promise.resolve(response(candidateRecordings.josh)) : lateRows.promise
        }
        const next = structuredClone(candidateRecordings.bonus)
        next.draft_id = 2
        next.league_id = 3
        next.season = next.lineage.projection_import.season = '2025-26'
        return Promise.resolve(response(next))
      },
    })
    mount('candidates')
    await loadJosh('candidates')
    await refreshNumerical('candidates')
    await waitFor(() => { expect(oldReads).toBe(2) })
    fireEvent.click(screen.getByRole('button', { name: 'Open draft 2' }))
    expect(screen.queryByTestId(paths.candidates.table)).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Projection series' })).not.toBeInTheDocument()
    await act(async () => {
      lateRows.resolve(response(candidateRecordings.josh))
      await Promise.resolve()
    })
    expect(screen.queryByTestId(paths.candidates.table)).not.toBeInTheDocument()
    await act(async () => {
      newCatalog.resolve(response({ ...recordedDraftCatalog, draft_id: 2, league_id: 3, season: '2025-26' }))
      await Promise.resolve()
    })
    expect(await screen.findByRole('combobox', { name: 'Projection series' })).toHaveValue('')
    expect(screen.getByText(/League 3 · season 2025-26/)).toBeInTheDocument()
    choose('bonus')
    expect(await screen.findByTestId(paths.candidates.summary)).toHaveTextContent('Bonus (synthetic)')
    expect(screen.getByTestId(paths.candidates.summary)).toHaveTextContent('Draft 2')
    expect(fetchMock.mock.calls.map(([input]) => requestUrl(input))).toContain(
      '/api/v1/drafts/2/projection-series?source=basketball_monster',
    )
    expect(fetchMock.mock.calls.every(([input]) => !requestUrl(input).includes('/leagues/'))).toBe(true)
  }, TIMEOUT_MS)

  it('keeps the six-second stale threshold while a successful two-second poll is slow', async () => {
    expect(PRODUCTION_CANDIDATES_POLL_INTERVAL_MS).toBe(2000)
    expect(PRODUCTION_CANDIDATES_STALE_AFTER_MS).toBe(6000)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const slow = deferred()
    let reads = 0
    serve('candidates', {
      numerical: () => ++reads === 1 ? Promise.resolve(response(candidateRecordings.josh)) : slow.promise,
    })
    mount('candidates')
    await loadJosh('candidates')
    expect(screen.queryByText(/Showing data from/)).not.toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(PRODUCTION_CANDIDATES_POLL_INTERVAL_MS + 1) })
    expect(reads).toBe(2)
    await act(async () => { await vi.advanceTimersByTimeAsync(PRODUCTION_CANDIDATES_STALE_AFTER_MS) })
    expect(screen.getByText(/Showing data from/)).toBeVisible()
    expect(screen.getByTestId(paths.candidates.summary)).toHaveTextContent('Josh (synthetic)')
    await act(async () => {
      slow.resolve(response(candidateRecordings.josh))
      await Promise.resolve()
    })
  }, TIMEOUT_MS)
})
