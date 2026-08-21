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

  it('uses no em dash as punctuation in the key, so the defined mark is unambiguous', async () => {
    // The key defines `—` as a distinct mark meaning "we hold no label". An
    // earlier version then used em dashes as ordinary punctuation twice more
    // in the same element, including inside the sentence explaining that it is
    // a distinct mark. A sighted reader is saved by the styled swatch; a
    // screen reader, or anything consuming `textContent`, receives the defined
    // glyph and the punctuation as the same character two words apart.
    //
    // Pinned rather than left to care, because it is a class of defect no
    // renderer, type or linter can see, and it returns the moment somebody
    // writes a natural sentence.
    mockFetch({ [PATH]: { body: payload() } })
    renderWithRouter(<ProjectionsPage />)

    await screen.findByTestId('projections-table')
    const key = document.querySelector('.grid__key')
    const emDashes = (key?.textContent?.match(/—/g) ?? []).length

    // Exactly one: the swatch that defines the mark.
    expect(emDashes).toBe(1)
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
    it('quotes the backend wording on the warm path, not just the cold one', async () => {
      // Four refusal messages tell the reader to read "the backend's wording
      // below" to learn which condition fired. Review found it was rendered
      // only on the cold path, so on a failed refresh — the path those
      // messages were actually written for — there was nothing below.
      vi.useFakeTimers({ shouldAdvanceTime: true })
      try {
        let call = 0
        const fetchMock = vi.fn(() => {
          call += 1
          return Promise.resolve(
            call === 1
              ? new Response(JSON.stringify(payload()), {
                  status: 200,
                  headers: { 'Content-Type': 'application/json' },
                })
              : new Response(
                  JSON.stringify({
                    error: 'projections_not_current',
                    detail: 'a newer import superseded this cohort',
                    request_id: 'req-9',
                  }),
                  { status: 409, headers: { 'Content-Type': 'application/json' } },
                ),
          )
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

        await waitFor(() => {
          expect(screen.getByTestId('async-stale-backend-wording')).toBeInTheDocument()
        })
        expect(screen.getByText(/a newer import superseded this cohort/)).toBeInTheDocument()
        expect(screen.getByTestId('projections-table')).toBeInTheDocument()
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

  it('quotes the number the row-count check actually compared', async () => {
    // Review found the banner reporting the post-dedup row count while the
    // check that fired used the pre-dedup one, so with a duplicated row it
    // announced a disagreement between two identical numbers: "carried 1 rate
    // rows but its lineage block counts 1".
    const base = payload({ projections: [rates(1), rates(1)] })
    mockFetch({
      [PATH]: {
        body: {
          ...base,
          lineage: {
            ...base.lineage,
            projection_import: { ...base.lineage.projection_import, projection_count: 1 },
          },
        },
      },
    })
    renderWithRouter(<ProjectionsPage />)

    const banner = await screen.findByTestId('projections-integrity')
    expect(banner).toHaveTextContent('carried 2 rate rows but its lineage block counts 1')
  })

  it('refuses a negative games-played assumption rather than rendering it', async () => {
    // A count rendered verbatim under a header saying the source assumed it.
    // The same bound the file already applies to schedule counts and rates.
    mockFetch({
      [PATH]: {
        body: payload({
          source_games_played_assumptions: [
            { player_id: 1, assumed_games_played: -5, assumed_games_played_raw: '-5' },
          ],
        }),
      },
    })
    renderWithRouter(<ProjectionsPage />)

    const summary = await screen.findByTestId('async-error-summary')
    expect(summary).toHaveTextContent(/did not match the projections contract/i)
  })

  it('accepts a fractional assumption, which the producer permits', async () => {
    mockFetch({
      [PATH]: {
        body: payload({
          source_games_played_assumptions: [
            { player_id: 1, assumed_games_played: 70.5, assumed_games_played_raw: '70.5' },
          ],
        }),
      },
    })
    renderWithRouter(<ProjectionsPage />)

    expect(await screen.findByTestId('assumption-1')).toHaveTextContent('70.5')
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
