/**
 * The reliability screen, driven against recorded responses and against the
 * states the owner will actually meet.
 *
 * **Why recorded fixtures rather than hand-built payloads here.** The model
 * tests next door use synthetic cohorts because they need known answers to
 * known-awkward inputs. This file needs the opposite: a payload nobody shaped to
 * make the screen look good. Every number asserted below was read out of the
 * committed recording before the assertion was written, so a change to the
 * screen that alters what it reports fails here rather than being absorbed.
 *
 * **The fixtures are a smaller cohort than the running demo, deliberately
 * stated.** The recorded schedule carries 12 published games across 21 scoring
 * periods; the demo backend currently serves 1,206 across 25. Those are two
 * different objects and asserting the demo's numbers against the fixture — or
 * the reverse — is the stale-fixture failure this project has already paid for
 * once: a real measurement, correctly taken, of the wrong thing. So this file
 * asserts the *recording's* numbers, and the browser probe asserts the *demo's*,
 * and neither one borrows the other's.
 */

import { act, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CurrentProjections, ScheduleGrid } from '../api/types'
import { buildProjectionsModel } from '../components/projectionsModel'
import {
  AVAILABILITY_EVIDENCE,
  buildAvailabilitySummary,
  EVIDENCE_SEASON,
} from '../components/reliabilityModel'
import { detectForbiddenProducts, renderedNumbers } from '../test/adr002'
import recordedProjections from '../test/fixtures/projections-current.recorded.json'
import recordedSchedule from '../test/fixtures/schedule-grid-current.recorded.json'
import { mockFetch, renderWithRouter } from '../test/helpers'
import { ReliabilityPage, STALE_AFTER_MS } from './ReliabilityPage'

const projectionsPayload = recordedProjections as unknown as CurrentProjections
const schedulePayload = recordedSchedule as unknown as ScheduleGrid

/**
 * Both routes served from the recording, unless a test overrides one.
 *
 * Keyed on path substrings because `mockFetch` matches that way, and the two
 * paths are distinct enough that no request can match both.
 */
function serveRecorded(overrides: Parameters<typeof mockFetch>[0] = {}) {
  return mockFetch({
    'projections/current': { body: projectionsPayload },
    'schedule-grid/current': { body: schedulePayload },
    ...overrides,
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the reliability screen, against the recorded cohorts', () => {
  it('renders both cohorts and the inventory in one pass', async () => {
    serveRecorded()
    renderWithRouter(<ReliabilityPage />)

    expect(await screen.findByTestId('availability-assumptions')).toBeInTheDocument()
    expect(await screen.findByTestId('schedule-evidence')).toBeInTheDocument()
    expect(screen.getByTestId('evidence-inventory')).toBeInTheDocument()
  })

  it('lists every quantity in the inventory with a state and a season', async () => {
    serveRecorded()
    renderWithRouter(<ReliabilityPage />)
    await screen.findByTestId('availability-assumptions')

    for (const item of AVAILABILITY_EVIDENCE) {
      const row = screen.getByTestId(`evidence-${item.id}`)
      expect(row, item.id).toBeInTheDocument()
      expect(screen.getByTestId(`evidence-status-${item.id}`)).toHaveAttribute(
        'data-status',
        item.status,
      )
      expect(screen.getByTestId(`evidence-season-${item.id}`)).toHaveTextContent(
        item.season.slice(0, 20),
      )
    }
  })

  it('states how many quantities reached the screen, above the table', async () => {
    // A probe measured this page at 4.01 laptop screens of scroll, with the
    // headline finding — how much is missing — only readable by working through
    // eight rows of paragraphs. The tally is that finding in one line, derived
    // from the same array the table renders so the two cannot disagree.
    serveRecorded()
    renderWithRouter(<ReliabilityPage />)
    await screen.findByTestId('availability-assumptions')

    const tally = screen.getByTestId('evidence-tally')
    expect(tally).toHaveTextContent('0 of 8 availability quantities are on this screen')
    // Five moved from "carried by no route" to "served by an endpoint this
    // screen does not call yet" when the reliability route shipped. Both
    // phrases are asserted, and the zero on the first is the point: a category
    // emptying out must show as zero rather than as a sentence quietly rewritten
    // to be about the other one.
    expect(tally).toHaveTextContent('5 are served by an endpoint this screen does not call yet')
    expect(tally).toHaveTextContent('0 are computed by the backend and carried by no route')
    expect(tally).toHaveTextContent('1 is deliberately held')
  })

  it('states the evidence season on the screen rather than in a tooltip', async () => {
    // The architect's ruling, and the `gameEt` shape it guards against: a
    // durability figure whose season is ambiguous is well-formed, plausible and
    // silently about a different thing than the reader assumes.
    serveRecorded()
    renderWithRouter(<ReliabilityPage />)
    await screen.findByTestId('availability-assumptions')

    const band = screen.getByTestId('season-band')
    expect(band).toBeVisible()
    expect(within(band).getByTestId('season-band-evidence')).toHaveTextContent(EVIDENCE_SEASON)
  })

  it('marks both recorded cohorts as a season other than the one evidence reads', async () => {
    serveRecorded()
    renderWithRouter(<ReliabilityPage />)
    await screen.findByTestId('availability-assumptions')

    // Both recordings are 2026-27 and the evidence season is 2025-26, so both
    // panels must say so. Asserted through the derived attribute rather than
    // the copy, so it tracks the comparison and not the sentence.
    expect(screen.getByTestId('assumptions-split')).toHaveAttribute('data-season-kind', 'differs')
    expect(screen.getByTestId('schedule-evidence-split')).toHaveAttribute(
      'data-season-kind',
      'differs',
    )
    expect(projectionsPayload.season).not.toBe(EVIDENCE_SEASON)
  })

  it('reports the recorded cohort size, range and distinct-value count', async () => {
    serveRecorded()
    renderWithRouter(<ReliabilityPage />)
    await screen.findByTestId('availability-assumptions')

    expect(screen.getByTestId('assumptions-cohort')).toHaveTextContent(
      '60 players carrying rates · 60 with a stated assumption',
    )
    expect(screen.getByTestId('assumptions-range')).toHaveTextContent(
      '59 to 79 games, across 11 distinct values',
    )
    expect(screen.getByTestId('assumptions-not-stated')).toHaveTextContent(
      '0 absent · 0 unreadable · 0 unexplained',
    )
  })

  it('draws one bar per stated assumption, carrying the recorded value', async () => {
    serveRecorded()
    renderWithRouter(<ReliabilityPage />)
    const strip = await screen.findByTestId('assumption-strip')

    const bars = [...strip.querySelectorAll('[data-games]')]
    const games = bars.map((bar) => Number(bar.getAttribute('data-games')))

    expect(bars).toHaveLength(60)
    expect(Math.min(...games)).toBe(59)
    expect(Math.max(...games)).toBe(79)
    expect(new Set(games).size).toBe(11)
    // Ascending, which is what makes the strip a distribution rather than a
    // scatter of the payload's arbitrary order.
    expect([...games].sort((a, b) => a - b)).toEqual(games)
  })

  it('scales the bars from zero to the cohort maximum, not from its minimum', async () => {
    serveRecorded()
    renderWithRouter(<ReliabilityPage />)
    const strip = await screen.findByTestId('assumption-strip')

    const heights = [...strip.querySelectorAll('[data-games]')].map((bar) =>
      Number.parseFloat((bar as HTMLElement).style.height),
    )

    // 79/79 is full and 59/79 is roughly three-quarters. A min-to-max scale
    // would draw the shortest bar at zero, turning a 25% spread into a 100%
    // one — the chart overstating data that is itself correct.
    expect(Math.max(...heights)).toBeCloseTo(100, 5)
    expect(Math.min(...heights)).toBeCloseTo((59 / 79) * 100, 5)
  })

  it('names the lowest and highest player from the recorded cohort', async () => {
    serveRecorded()
    renderWithRouter(<ReliabilityPage />)
    await screen.findByTestId('assumption-strip')

    expect(screen.getByTestId('assumption-lowest')).toHaveTextContent(
      'Lowest: Steven Adams: 59 games assumed',
    )
    expect(screen.getByTestId('assumption-highest')).toHaveTextContent(
      'Highest: Christian Braun: 79 games assumed',
    )
  })

  it('reports that all 60 recorded assumptions read back, having checked each', async () => {
    serveRecorded()
    renderWithRouter(<ReliabilityPage />)
    await screen.findByTestId('availability-assumptions')

    expect(screen.getByTestId('assumptions-divergence')).toHaveTextContent(
      'All 60 stated assumptions read back to the number beside them',
    )
  })

  it('reports the recorded schedule counts and the games that cannot be classified', async () => {
    serveRecorded()
    renderWithRouter(<ReliabilityPage />)
    const evidence = await screen.findByTestId('schedule-evidence')

    // The recording's own numbers. The demo serves 1,206/1,200/2,400 and this
    // fixture serves 12/10/20; asserting the demo's here would be a plausible
    // reading of the wrong object.
    expect(within(evidence).getByTestId('schedule-evidence-season')).toHaveTextContent(
      '2026-27 · 30 teams · 21 scoring periods',
    )
    expect(within(evidence).getByTestId('schedule-evidence-games')).toHaveTextContent(
      '12 published by the source · 10 resolved into this cohort · 20 team-rows',
    )
    // The two pending quantities, which an earlier version of this screen
    // conflated. This fixture's two pending games BOTH carry a date
    // (2026-12-04), so the undated count is 0 and the teams-undecided count
    // is 2. The previous assertion here read "2 scheduled games carry no date
    // yet" and passed — it pinned the error in place rather than catching it.
    expect(within(evidence).getByTestId('schedule-evidence-undated')).toHaveTextContent(
      'No scheduled game is missing a date',
    )
    // Asserted in full, not by leading substring. The previous version checked
    // only '2 published games have no teams assigned yet' and sailed past a
    // trailing clause ("These are dated") that a later payload makes false.
    expect(within(evidence).getByTestId('schedule-evidence-pending')).toHaveTextContent(
      '2 published games have no teams assigned yet, all labelled Emirates NBA Cup. A game with no ' +
        'teams cannot be attributed to any team’s calendar, so none of them can be classified as a ' +
        'back-to-back in either direction.',
    )
  })

  it('derives the pending-game label from the payload rather than asserting it', async () => {
    // ADR-013 makes "pending means an undrawn knockout bracket" falsifiable
    // rather than definitional. A hard-coded characterisation would keep
    // asserting it after it stopped being true, so this drives a payload where
    // it has.
    const grid = structuredClone(schedulePayload)
    for (const game of grid.lineage.schedule.pending_games) {
      game.game_label = 'Play-In Tournament'
    }

    serveRecorded({ 'schedule-grid/current': { body: grid } })
    renderWithRouter(<ReliabilityPage />)
    const evidence = await screen.findByTestId('schedule-evidence')

    expect(within(evidence).getByTestId('schedule-evidence-pending')).toHaveTextContent(
      'all labelled Play-In Tournament',
    )
    expect(within(evidence).getByTestId('schedule-evidence-pending')).not.toHaveTextContent(
      /knockout/i,
    )
  })

  it('does not say "all labelled" when only some pending games carry a label', async () => {
    // "All labelled X" is a claim about every counted game. A cohort where one
    // game has a label and another does not makes it false while leaving the
    // count correct — the same shape as the prose this row replaced.
    const grid = structuredClone(schedulePayload)
    const pending = grid.lineage.schedule.pending_games
    pending[0]!.game_label = 'Emirates NBA Cup'
    pending[1]!.game_label = ''

    serveRecorded({ 'schedule-grid/current': { body: grid } })
    renderWithRouter(<ReliabilityPage />)
    const evidence = await screen.findByTestId('schedule-evidence')
    const row = within(evidence).getByTestId('schedule-evidence-pending')

    expect(row).toHaveTextContent('2 published games have no teams assigned yet, 1 of them labelled')
    expect(row).not.toHaveTextContent('all labelled')
  })

  it('says nothing about labels when no pending game carries one', async () => {
    const grid = structuredClone(schedulePayload)
    for (const game of grid.lineage.schedule.pending_games) {
      game.game_label = ''
    }

    serveRecorded({ 'schedule-grid/current': { body: grid } })
    renderWithRouter(<ReliabilityPage />)
    const evidence = await screen.findByTestId('schedule-evidence')
    const row = within(evidence).getByTestId('schedule-evidence-pending')

    expect(row).toHaveTextContent('2 published games have no teams assigned yet. A game with no')
    expect(row).not.toHaveTextContent(/labelled/i)
  })

  it('separates a missing date from undecided teams when only one of them applies', async () => {
    // The control for the pair above, and the test that would have caught the
    // original bug. Both games are pending, but only one lacks a date, so a
    // screen reading `pending_game_ids.length` for both rows reports 2 and 2
    // and fails here.
    const grid = structuredClone(schedulePayload)
    const pending = grid.lineage.schedule.pending_games
    pending[0]!.game_date = null
    // `not_offered` is one of the closed set in DATE_ABSENCE_REASONS. An
    // invented string is rejected by the endpoint validator, which
    // cross-checks the reason against `game_date` in both directions — the
    // first version of this test used free text and never rendered at all.
    pending[0]!.date_absence_reason = 'not_offered'

    serveRecorded({ 'schedule-grid/current': { body: grid } })
    renderWithRouter(<ReliabilityPage />)
    const evidence = await screen.findByTestId('schedule-evidence')

    expect(within(evidence).getByTestId('schedule-evidence-undated')).toHaveTextContent(
      '1 of those 2 also carries no date. This is a subset of the row above, not a further count',
    )
    expect(within(evidence).getByTestId('schedule-evidence-pending')).toHaveTextContent(
      '2 published games have no teams assigned yet',
    )
  })

  it('says observed participation is not on the API rather than reporting zero', async () => {
    // The load-bearing sentence. A `0` here would read as "nobody has played",
    // which is a claim about the season; the truth is a claim about the API.
    serveRecorded()
    renderWithRouter(<ReliabilityPage />)
    const observed = await screen.findByTestId('schedule-evidence-observed')

    expect(observed).toHaveTextContent('Not on the API')
    expect(observed).toHaveTextContent(/no route serves observed participation/i)
  })

  it('renders no p(play) value and no durability grade anywhere', async () => {
    serveRecorded()
    const { container } = renderWithRouter(<ReliabilityPage />)
    await screen.findByTestId('availability-assumptions')

    const text = container.textContent ?? ''
    // A probability would be a decimal in [0, 1] rendered beside p(play), and a
    // letter grade would be a bare A–F token. Neither exists; this fails if one
    // is added without the model behind it.
    expect(text).not.toMatch(/p\(play\)\s*[:=]?\s*0?\.\d/i)
    expect(text).not.toMatch(/\bgrade[:\s]+[A-F][+-]?\b/i)
    expect(screen.getByTestId('evidence-status-p-play')).toHaveAttribute('data-status', 'blocked')
  })

  it('renders, in the assumptions panel, only numbers the payload accounts for', async () => {
    // **The shared ADR-002 detector does not work on this screen, and tuning it
    // until it went green would have been the wrong move.** Run over the whole
    // page against the recorded cohort it reports six products, every one of
    // them false: it counts digits inside *prose* as rendered quantities, and
    // this screen's content is largely prose about numbers. `A 70-game player
    // and a 55-game player` in the lede supplies 70; `Empirical p20/p80` in the
    // inventory supplies 80. Six low-rate season totals — free throws made,
    // offensive rebounds, threes, steals — land within half a unit of those,
    // because a low per-game rate times a games count lands in the same 60-85
    // band that this screen legitimately fills with games counts.
    //
    // That is the same lesson its own docstring already records once, arriving
    // somewhere new: the detector's dangerous failure is being *too* sensitive,
    // because a check that cries wolf on a correct screen gets loosened by
    // whoever meets it next. So it is scoped to the region it can judge, and
    // the region is then checked exhaustively instead — which is strictly
    // stronger here, since a whitelist rejects any unaccounted number rather
    // than only the one product a test knew to look for.
    serveRecorded()
    renderWithRouter(<ReliabilityPage />)
    const panel = await screen.findByTestId('availability-assumptions')

    const model = buildProjectionsModel(projectionsPayload)
    expect(detectForbiddenProducts(panel, model)).toEqual([])

    const summary = buildAvailabilitySummary(model)
    const allowed = new Set<number>([
      0,
      summary.cohortSize,
      summary.stated.length,
      summary.distinctValues,
      ...summary.stated.map((point) => point.games),
      // Season labels, which are rendered as `2026-27` and `2025-26` and so
      // arrive as four separate tokens.
      ...[projectionsPayload.season, EVIDENCE_SEASON].flatMap((season) =>
        (season.match(/\d+/g) ?? []).map(Number),
      ),
    ])

    const unaccounted = renderedNumbers(panel).filter((value) => !allowed.has(value))
    expect(unaccounted).toEqual([])
  })

  it('the exhaustive check fails when an unaccounted number is added', async () => {
    // The control. An empty result from a check that cannot see is not
    // evidence, and this project has already paid once for a probe that could
    // not distinguish "nothing changed" from "I am blind". A season total is
    // the specific number ADR-002 forbids, so that is what gets planted.
    serveRecorded()
    renderWithRouter(<ReliabilityPage />)
    const panel = await screen.findByTestId('availability-assumptions')

    const model = buildProjectionsModel(projectionsPayload)
    const summary = buildAvailabilitySummary(model)
    const allowed = new Set<number>([
      0,
      summary.cohortSize,
      summary.stated.length,
      summary.distinctValues,
      ...summary.stated.map((point) => point.games),
      ...[projectionsPayload.season, EVIDENCE_SEASON].flatMap((season) =>
        (season.match(/\d+/g) ?? []).map(Number),
      ),
    ])

    const firstRow = model.rows[0]
    if (firstRow === undefined || firstRow.assumption.kind !== 'stated') {
      throw new Error('the recorded cohort no longer opens with a stated assumption')
    }
    const rate = firstRow.rates.points_per_game
    if (rate === null) {
      throw new Error('the recorded cohort no longer opens with a points rate to multiply')
    }
    const product = rate * firstRow.assumption.games
    const planted = panel.ownerDocument.createElement('p')
    planted.textContent = String(product)
    panel.append(planted)

    expect(renderedNumbers(panel).filter((value) => !allowed.has(value))).not.toEqual([])
    // And the scoped product detector sees it too, so both halves are live.
    expect(detectForbiddenProducts(panel, model).length).toBeGreaterThan(0)
  })
})

describe('the states the owner will actually meet', () => {
  it('announces each cohort as loading before either arrives', () => {
    // Never resolves, so both boundaries stay cold and the labels are the only
    // thing on screen. Asserted because a screen that renders its headings and
    // nothing else looks broken rather than busy.
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => undefined)),
    )
    renderWithRouter(<ReliabilityPage />)

    const loading = screen.getAllByRole('status')
    expect(loading).toHaveLength(2)
    expect(loading.map((node) => node.textContent).join(' ')).toContain(
      "the imported cohort's games-played assumptions",
    )
  })

  it('keeps the inventory readable when both requests fail', async () => {
    // The inventory is static content and is the screen's main claim, so it
    // must survive both cohorts failing. If it did not, a backend outage would
    // hide the one part of this page that is never data-dependent.
    serveRecorded({
      'projections/current': { status: 500, body: { detail: 'boom' } },
      'schedule-grid/current': { status: 500, body: { detail: 'boom' } },
    })
    renderWithRouter(<ReliabilityPage />)

    await waitFor(() => {
      expect(screen.getAllByRole('alert')).toHaveLength(2)
    })
    expect(screen.getByTestId('evidence-inventory')).toBeInTheDocument()
    expect(screen.getByTestId('evidence-p-play')).toBeInTheDocument()
  })

  it('fails the two cohorts independently rather than together', async () => {
    // Two reads, two boundaries. A single spinner over both would let one
    // screen imply they were read together when they were not, and a failure
    // in one would erase the other's numbers for no reason.
    serveRecorded({ 'schedule-grid/current': { status: 500, body: { detail: 'boom' } } })
    renderWithRouter(<ReliabilityPage />)

    expect(await screen.findByTestId('assumption-strip')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getAllByRole('alert')).toHaveLength(1)
    })
    expect(screen.getByTestId('assumptions-range')).toHaveTextContent('59 to 79 games')
  })

  it('says the cohort is empty rather than drawing an empty strip', async () => {
    serveRecorded({
      'projections/current': {
        body: {
          ...projectionsPayload,
          players: [],
          projections: [],
          source_games_played_assumptions: [],
          lineage: {
            ...projectionsPayload.lineage,
            projection_import: {
              ...projectionsPayload.lineage.projection_import,
              projection_count: 0,
              row_count: 0,
              matched_count: 0,
            },
          },
        },
      },
    })
    renderWithRouter(<ReliabilityPage />)

    expect(
      await screen.findByText(/carries no projection rows/i, {}, { timeout: 3_000 }),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('assumption-strip')).not.toBeInTheDocument()
  })

  it('says there is nothing to draw when the cohort states no assumption', async () => {
    // Distinct from the empty case above: there are players, and none carries a
    // figure. An empty strip here is indistinguishable from a strip of zeroes,
    // which is the invented number this screen exists to refuse.
    serveRecorded({
      'projections/current': {
        body: {
          ...projectionsPayload,
          source_games_played_assumptions: projectionsPayload.source_games_played_assumptions.map(
            (claim) => ({
              ...claim,
              assumed_games_played: null,
              assumed_games_played_raw: null,
            }),
          ),
        },
      },
    })
    renderWithRouter(<ReliabilityPage />)

    const empty = await screen.findByTestId('assumptions-empty')
    expect(empty).toHaveTextContent('there is nothing to draw')
    expect(screen.queryByTestId('assumption-strip')).not.toBeInTheDocument()
    expect(screen.getByTestId('assumptions-range')).toHaveTextContent(
      'Nothing stated, so there is no range to report. That is not a range of zero.',
    )
  })

  it('marks availability data as stale once a refresh fails behind it', async () => {
    // Stale availability data must be visibly stale — the one requirement of
    // this unit that is about time rather than about content. Driven through
    // the boundary's own refresh control, which does not exist until the data
    // is considered stale, so the path is one a reader can actually reach.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      let projectionCalls = 0
      vi.stubGlobal(
        'fetch',
        vi.fn((input: RequestInfo | URL) => {
          const url = typeof input === 'string' ? input : String((input as Request).url ?? input)
          const json = (body: unknown, status = 200) =>
            Promise.resolve(
              new Response(JSON.stringify(body), {
                status,
                headers: { 'Content-Type': 'application/json' },
              }),
            )
          if (url.includes('schedule-grid/current')) return json(schedulePayload)
          projectionCalls += 1
          return projectionCalls === 1
            ? json(projectionsPayload)
            : json({ detail: 'the cohort moved' }, 500)
        }),
      )

      renderWithRouter(<ReliabilityPage />)
      await screen.findByTestId('assumption-strip')

      await act(async () => {
        await vi.advanceTimersByTimeAsync(STALE_AFTER_MS + 1_000)
      })

      // Both boundaries go stale together, so there are two refresh controls on
      // screen and an unscoped query matches both. Scoped to the section whose
      // data this test is about — the failure that surfaced this was a query
      // matching multiple elements, which is the harmless form of the same
      // mistake as measuring the wrong object.
      const section = screen.getByTestId('section-assumptions')
      const refresh = within(section).getByRole('button', { name: /refresh/i })
      act(() => {
        refresh.click()
      })

      await waitFor(() => {
        expect(within(section).getByTestId('async-stale-failure')).toBeInTheDocument()
      })
      // The numbers stay on screen, labelled stale, rather than vanishing.
      expect(screen.getByTestId('assumptions-range')).toHaveTextContent('59 to 79 games')
    } finally {
      vi.useRealTimers()
    }
  })
})
