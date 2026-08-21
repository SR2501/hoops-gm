/**
 * The projections screen end to end, through the real client and the real
 * `useAsync`.
 *
 * `mockFetch` stubs the global rather than the client, so these exercise the
 * error-envelope parsing, the retry policy and the boundary's warm path
 * together. A test that mocked `getCurrentProjections` would prove the page
 * agrees with a fake.
 */

import { act, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PROJECTIONS_ERRORS, RETRYABLE_PROJECTIONS_ERROR } from '../api/projectionsErrors'
import type { CurrentProjections, ProjectionRates } from '../api/types'
import { PROJECTION_RATE_FIELDS } from '../api/types'
import { mockFetch, renderWithRouter } from '../test/helpers'
import { ProjectionsPage, STALE_AFTER_MS } from './ProjectionsPage'

const PATH = '/projections/current'

function rates(playerId: number, overrides: Partial<ProjectionRates> = {}): ProjectionRates {
  const row = { player_id: playerId } as ProjectionRates
  for (const field of PROJECTION_RATE_FIELDS) {
    row[field] = 2.5
  }
  return { ...row, ...overrides }
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
        import_id: 3,
        source: 'basketball_monster',
        season: '2026-27',
        imported_at: '2026-08-19T12:00:00.123456Z',
        content_sha256: 'a'.repeat(64),
        profile_id: 'basketball-monster',
        profile_version: '1',
        profile_definition_sha256: 'b'.repeat(64),
        projection_values_sha256: 'c'.repeat(64),
        projection_count: projections.length,
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
    projections,
    source_games_played_assumptions: [],
    ...overrides,
  }
}

function refusal(code: string, detail = 'backend wording') {
  return { status: 409, body: { error: code, detail, request_id: 'req-1' } }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ProjectionsPage', () => {
  it('renders the cohort with its lineage', async () => {
    mockFetch({ [PATH]: { body: payload() }, '/health': { body: { status: 'ok', service: 'x', version: '1', environment: 'test' } } })
    renderWithRouter(<ProjectionsPage />)

    expect(await screen.findByTestId('projections-table')).toBeInTheDocument()
    expect(screen.getByText('Alpha Player')).toBeInTheDocument()
    expect(screen.getByTestId('projections-lineage')).toBeInTheDocument()
  })

  it('says these are not our numbers, rather than implying a comparison', async () => {
    mockFetch({ [PATH]: { body: payload() } })
    renderWithRouter(<ProjectionsPage />)

    await screen.findByTestId('projections-table')
    expect(screen.getByText(/These are their numbers, not ours/i)).toBeInTheDocument()
    expect(screen.getByTestId('projections-blend-state')).toHaveTextContent('not blended')
  })

  describe('a published zero against an absent value', () => {
    it('renders them differently', async () => {
      mockFetch({
        [PATH]: {
          body: payload({
            projections: [rates(1, { points_per_game: 0, blocks_per_game: null })],
          }),
        },
      })
      renderWithRouter(<ProjectionsPage />)

      await screen.findByTestId('projections-table')
      const zero = screen.getByTestId('rate-1-points_per_game')
      const absent = screen.getByTestId('rate-1-blocks_per_game')

      expect(zero).toHaveTextContent('0.00')
      expect(absent).toHaveTextContent('·')
      expect(zero.textContent).not.toBe(absent.textContent)
      // The class carries the styling distinction; the browser check that it
      // actually renders is in the manual pass, because jsdom resolves no
      // cascade and cannot tell us whether the rule won.
      expect(absent).toHaveClass('projections__rate--nodata')
      expect(zero).not.toHaveClass('projections__rate--nodata')
    })

    it('marks an absent games assumption as not-zero too', async () => {
      mockFetch({ [PATH]: { body: payload() } })
      renderWithRouter(<ProjectionsPage />)

      await screen.findByTestId('projections-table')
      const cell = screen.getByTestId('assumption-1')

      expect(cell).toHaveAttribute('data-assumption', 'absent')
      expect(cell).toHaveTextContent('·')
      expect(cell.getAttribute('title')).toMatch(/not zero/i)
    })
  })

  describe('the retryable refusal', () => {
    it('retries once and shows the cohort when the second read succeeds', async () => {
      let call = 0
      const fetchMock = vi.fn(() => {
        call += 1
        const response =
          call === 1
            ? new Response(
                JSON.stringify({
                  error: RETRYABLE_PROJECTIONS_ERROR,
                  detail: 'the cohort moved',
                  request_id: 'req-1',
                }),
                { status: 409, headers: { 'Content-Type': 'application/json' } },
              )
            : new Response(JSON.stringify(payload()), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
              })
        return Promise.resolve(response)
      })
      vi.stubGlobal('fetch', fetchMock)

      renderWithRouter(<ProjectionsPage />)

      expect(await screen.findByTestId('projections-table')).toBeInTheDocument()
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })

    it('retries exactly once, not repeatedly, when it keeps failing', async () => {
      // A retry loop against a backend that is already refusing is the failure
      // mode a retry is most likely to have and least likely to be tested for.
      const fetchMock = vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              error: RETRYABLE_PROJECTIONS_ERROR,
              detail: 'still moving',
              request_id: 'req-1',
            }),
            { status: 409, headers: { 'Content-Type': 'application/json' } },
          ),
        ),
      )
      vi.stubGlobal('fetch', fetchMock)

      renderWithRouter(<ProjectionsPage />)

      await screen.findByTestId('async-error-summary')
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })

    it('does not retry a terminal code', async () => {
      const fetchMock = vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              error: 'projections_source_not_imported',
              detail: 'nothing imported',
              request_id: 'req-1',
            }),
            { status: 409, headers: { 'Content-Type': 'application/json' } },
          ),
        ),
      )
      vi.stubGlobal('fetch', fetchMock)

      renderWithRouter(<ProjectionsPage />)

      await screen.findByTestId('async-error-summary')
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })

    it('keeps the last good cohort on screen when a refresh fails', async () => {
      // The draft-day requirement: an empty board mid-auction is worse than a
      // slightly stale one. Asserted on the board still being there, not on
      // the banner, because the banner is the consolation and the board is the
      // requirement.
      //
      // Driven through the page's own refresh control rather than by calling
      // `reload` directly, which means waiting for the staleness threshold —
      // that control does not exist until the boundary considers the data
      // stale, so a test that conjured it would be exercising a path a user
      // cannot reach.
      vi.useFakeTimers({ shouldAdvanceTime: true })
      try {
        let call = 0
        const fetchMock = vi.fn(() => {
          call += 1
          const response =
            call === 1
              ? new Response(JSON.stringify(payload()), {
                  status: 200,
                  headers: { 'Content-Type': 'application/json' },
                })
              : new Response(
                  JSON.stringify({
                    error: RETRYABLE_PROJECTIONS_ERROR,
                    detail: 'the cohort moved',
                    request_id: 'req-1',
                  }),
                  { status: 409, headers: { 'Content-Type': 'application/json' } },
                )
          return Promise.resolve(response)
        })
        vi.stubGlobal('fetch', fetchMock)

        renderWithRouter(<ProjectionsPage />)
        await screen.findByTestId('projections-table')

        await act(async () => {
          await vi.advanceTimersByTimeAsync(STALE_AFTER_MS + 1_000)
        })

        const refresh = await screen.findByRole('button', { name: /refresh/i })
        act(() => {
          refresh.click()
        })

        // The retry is spent on the failing refresh, then the failure surfaces.
        await waitFor(() => {
          expect(screen.getByTestId('async-stale-failure')).toBeInTheDocument()
        })
        expect(screen.getByTestId('projections-table')).toBeInTheDocument()
        expect(screen.getByText('Alpha Player')).toBeInTheDocument()
      } finally {
        vi.useRealTimers()
      }
    })
  })

  describe('refusal copy', () => {
    it.each(Object.entries(PROJECTIONS_ERRORS))(
      'explains %s in its own terms',
      async (code, copy) => {
        mockFetch({ [PATH]: refusal(code) })
        renderWithRouter(<ProjectionsPage />)

        const summary = await screen.findByTestId('async-error-summary')
        expect(summary).toHaveTextContent(copy.summary)
        expect(screen.getByTestId('async-error-action')).toHaveTextContent(copy.action)
      },
    )

    it('still quotes the backend wording, so a failure can be correlated to a log line', async () => {
      mockFetch({ [PATH]: refusal('projections_incomplete_evidence', 'profile is not verified') })
      renderWithRouter(<ProjectionsPage />)

      await screen.findByTestId('async-error-summary')
      expect(screen.getByText(/profile is not verified/)).toBeInTheDocument()
    })
  })

  it('reports an inconsistent cohort rather than drawing it silently', async () => {
    mockFetch({
      [PATH]: {
        body: payload({ projections: [rates(1), rates(1)] }),
      },
    })
    renderWithRouter(<ProjectionsPage />)

    const banner = await screen.findByTestId('projections-integrity')
    expect(banner).toHaveTextContent(/duplicate rate row/i)
    expect(within(screen.getByTestId('projections-table')).getAllByRole('row')).toHaveLength(2)
  })

  it('refuses a payload whose blend key is absent rather than reading it as unblended', async () => {
    const body = payload() as unknown as Record<string, unknown>
    const lineage = { ...(body.lineage as Record<string, unknown>) }
    delete lineage.blend
    body.lineage = lineage

    mockFetch({ [PATH]: { body } })
    renderWithRouter(<ProjectionsPage />)

    const summary = await screen.findByTestId('async-error-summary')
    expect(summary).toHaveTextContent(/did not match the projections contract/i)
  })
})
