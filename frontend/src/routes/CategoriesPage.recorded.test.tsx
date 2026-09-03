/**
 * The contract test for the league category table, against **recorded**
 * responses.
 *
 * `leagueCategoryModel.test.ts` builds its payloads by hand from the TypeScript
 * interfaces, so it can only ever prove the code agrees with itself. The two
 * fixtures here are real 200s captured over HTTP from the running FastAPI
 * service on 2026-08-27, and this file is where the join between them meets
 * something a backend actually produced.
 *
 * **Both fixtures came out of one database in one sitting, and that is load
 * bearing.** This screen is the only one that joins two endpoints, so a pair of
 * recordings from different databases would agree structurally and describe
 * different player populations — the failure would be a table full of confident
 * numbers attributing one player's rates to another, with nothing on screen
 * looking wrong. `pairs with the projection cohort it was recorded beside`
 * checks it in both directions: every holding's id is in the cohort, **and** the
 * cohort's name for that id is character-for-character the label the draft log
 * recorded. Ids agreeing while names disagree is precisely what two databases
 * with the same surrogate key sequence would look like.
 *
 * **Captured as raw bytes.** `HttpClient.GetByteArrayAsync` to
 * `File.WriteAllBytes`, no serialiser in between, for the reason
 * `ProjectionsTable.recorded.test.tsx` records at length: a recording that has
 * been through a JSON round-trip is not a recording, it is the capture tool's
 * opinion of one.
 *
 * ## What this recording cannot check
 *
 * - **Not a real allocation.** The seat sizes (8, 6, 6, 6, 4, 4, 4, 4, 2, 2, 2,
 *   0) were chosen to exercise paths, not to look like an auction. Only the
 *   player names are real; every rate behind them is invented by
 *   `hoops_gm.dev.seed_demo`, which says so itself.
 * - **Not the sparse-rate path.** Every rate in this cohort is non-null, so no
 *   `omittedPlayers` count is ever non-zero here and the `−n` marker never
 *   renders. That is a property of Basketball Monster's import profile rather
 *   than a coincidence — a row missing any required rate is rejected rather
 *   than stored — so this gap closes only with a source that publishes sparse
 *   rows. The null paths are driven from hand-built payloads instead.
 * - **Not the unresolved-holding path**, which is the state the *seeded demo*
 *   shows and this fixture deliberately does not: this draft was recorded with
 *   `player_id` supplied on every sale, and the seeder's own drafts resolve
 *   none. Both are real; only one is recorded here.
 * - **Not a full board.** 48 of 156 slots. Nothing here says the table is
 *   readable at 156.
 */

import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { isDraftState } from '../api/draftEndpoints'
import type { DraftState } from '../api/draftTypes'
import { isCurrentProjections } from '../api/endpoints'
import type { CurrentProjections, ProjectionRates } from '../api/types'
import { PROJECTION_RATE_FIELDS } from '../api/types'
import { LeagueCategoryTable, OwnerCategoryStanding } from '../components/LeagueCategoryTable'
import {
  buildLeagueCategoryModel,
  CATEGORIES,
  formatCounting,
} from '../components/leagueCategoryModel'
import { renderedNumbers } from '../test/adr002'
import currentDraftContract from '../test/fixtures/draft-auction-state.recorded.json'
import recordedDraft from '../test/fixtures/draft-auction-resolved-state.recorded.json'
import recordedProjections from '../test/fixtures/projections-current.recorded.json'

/**
 * Ten seconds. These render one 12×9 table into jsdom with no network and no
 * timers; the default is left implicit nowhere, per `vitest-explicit-timeout`.
 */
const TIMEOUT_MS = 10_000

const draft = recordedDraft as unknown as DraftState
const projections = recordedProjections as unknown as CurrentProjections

const model = buildLeagueCategoryModel(draft, projections)

function ratesById(): Map<number, ProjectionRates> {
  return new Map(projections.projections.map((row) => [row.player_id, row]))
}

describe('the recorded pair', () => {
  it(
    'is accepted by the validators that guard the real requests',
    () => {
      // The assertion both fixtures exist for: the predicates production runs,
      // not hand-picked fields. A renamed or retyped field fails here even if
      // nothing below happens to touch it.
      expect(isDraftState(currentDraftContract)).toBe(true)
      expect(isDraftState(recordedDraft)).toBe(true)
      expect(isCurrentProjections(recordedProjections)).toBe(true)
    },
    TIMEOUT_MS,
  )

  it(
    'pairs with the projection cohort it was recorded beside',
    () => {
      const names = new Map(
        projections.players.map((player) => [player.player_id, player.full_name]),
      )
      const holdings = draft.participants.flatMap((seat) => seat.holdings)

      expect(holdings.length).toBeGreaterThan(0)
      for (const held of holdings) {
        expect(held.player_id).not.toBeNull()
        // Ids agreeing is the weaker half. Two databases sharing a surrogate
        // key sequence agree on ids and disagree on who they denote, which is
        // exactly the failure a joined screen cannot see.
        expect(names.get(held.player_id ?? -1)).toBe(held.player_label)
      }
    },
    TIMEOUT_MS,
  )

  it(
    'carries a tool_usage value the old frontend type could not express',
    () => {
      // `DraftToolUsage` said `blind | assisted | tool_led` until 2026-08-27;
      // the backend enum is `blind | partial | instrumented`. Every other
      // committed fixture carries `blind`, the one value both spellings share,
      // which is why nothing caught it. This one carries `partial`.
      expect(draft.tool_usage).toBe('partial')
    },
    TIMEOUT_MS,
  )

  it(
    'states a category scoring format, so ranking nine categories is defensible',
    () => {
      // A points-league projection consumed as a 9-cat one is wrong in a way no
      // downstream check can see, so this is checked rather than assumed.
      expect(projections.lineage.projection_import.assumed_scoring_type).toBe('h2h_categories')
      expect(model.scoringTypeMismatch).toBe(false)
    },
    TIMEOUT_MS,
  )
})

describe('the table drawn from it', () => {
  it(
    'draws every seat, and ranks only the seats holding something',
    () => {
      render(<LeagueCategoryTable model={model} />)

      const table = screen.getByTestId('league-category-table')
      const rows = within(table).getAllByRole('row')
      // One header row plus twelve seats.
      expect(rows).toHaveLength(draft.participants.length + 1)

      expect(model.join.joinedPlayers).toBe(48)
      expect(model.join.unresolvedHoldings).toBe(0)
      expect(model.join.unmatchedHoldings).toBe(0)
      // The twelfth seat holds nothing.
      expect(model.rankedSeatCount).toBe(11)
    },
    TIMEOUT_MS,
  )

  it(
    'gives the empty seat no rank in any category, rather than last place',
    () => {
      render(<LeagueCategoryTable model={model} />)

      const emptySeat = screen.getByTestId('category-seat-12')
      const ranked = emptySeat.querySelectorAll('td[data-rank]')
      expect(ranked).toHaveLength(0)
      expect(within(emptySeat).getAllByText('unranked')).toHaveLength(CATEGORIES.length)

      // And nothing else claims a twelfth place, which is the assertion that
      // actually distinguishes "unranked" from "ranked last and labelled".
      const table = screen.getByTestId('league-category-table')
      expect(table.querySelectorAll('td[data-rank="12"]')).toHaveLength(0)
    },
    TIMEOUT_MS,
  )

  it(
    'assigns each category the ranks 1..11 exactly once across the ranked seats',
    () => {
      for (const [index, category] of CATEGORIES.entries()) {
        const ranks = model.seats
          .map((seat) => seat.cells[index]?.rank)
          .filter((rank): rank is number => rank !== null && rank !== undefined)
          .sort((a, b) => a - b)
        expect(
          ranks,
          `${category.label} did not rank the eleven holding seats 1..11`,
        ).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
      }
    },
    TIMEOUT_MS,
  )

  it(
    'sums the owner seat to values worked out from the fixtures by hand',
    () => {
      // Computed outside this file by summing the eight held players' rates
      // straight out of the two recorded JSON files, then written down. If the
      // model changes what it sums, these stop matching.
      render(<LeagueCategoryTable model={model} />)
      const ownerRow = screen.getByTestId('category-seat-1')

      for (const displayed of ['93.6', '37.0', '21.4', '5.6', '4.0', '8.0', '10.9']) {
        expect(within(ownerRow).getByText(displayed)).toBeInTheDocument()
      }
      // Σ made ÷ Σ attempted, with the attempt volume beside it.
      expect(within(ownerRow).getByText('44.6%')).toBeInTheDocument()
      expect(within(ownerRow).getByText('75.7 att')).toBeInTheDocument()
      expect(within(ownerRow).getByText('77.0%')).toBeInTheDocument()
      expect(within(ownerRow).getByText('23.5 att')).toBeInTheDocument()
    },
    TIMEOUT_MS,
  )

  it(
    'ranks the deepest seat first in every counting category, which is the confound the screen names',
    () => {
      // Not a nice property — it is the depth confound, stated out loud. The
      // eight-player seat leads all six "more is better" counting categories
      // and is worst in turnovers, because it holds more players. If this ever
      // stops being true of this fixture the copy about depth still stands, but
      // the demonstration of it has gone.
      const ownerCells = model.seats[0]?.cells ?? []
      for (const key of ['pts', 'reb', 'ast', 'stl', 'blk', 'tpm']) {
        expect(ownerCells.find((cell) => cell.category.key === key)?.rank, key).toBe(1)
      }
      expect(ownerCells.find((cell) => cell.category.key === 'to')?.rank).toBe(11)
    },
    TIMEOUT_MS,
  )

  it(
    'writes the rank as text in every cell, not only as a colour',
    () => {
      render(<LeagueCategoryTable model={model} />)
      const table = screen.getByTestId('league-category-table')

      const rankedCells = table.querySelectorAll('td[data-rank]')
      expect(rankedCells).toHaveLength(11 * CATEGORIES.length)
      for (const cell of rankedCells) {
        const tier = cell.getAttribute('data-tier')
        expect(['1', '2', '3', '4', '5']).toContain(tier)
        // A red-green scale is the worst possible axis for a colour vision
        // deficiency. The ordinal is the claim; the colour accelerates it.
        expect(cell.querySelector('.catgrid__rank')?.textContent).toMatch(/^\d+(st|nd|rd|th)$/)
      }
    },
    TIMEOUT_MS,
  )

  it(
    "names the owner's best and worst category",
    () => {
      render(<OwnerCategoryStanding model={model} />)
      const standing = screen.getByTestId('owner-standing')
      expect(standing).toHaveTextContent('Bench Mob')
      expect(standing).toHaveTextContent('Strongest PTS, weakest TO')
      expect(standing).toHaveTextContent('of 11 seats')
    },
    TIMEOUT_MS,
  )
})

describe('ADR-002, against the recorded numbers', () => {
  /**
   * Every numeric quantity this screen is *entitled* to draw, in both the stored
   * and the **displayed** form.
   *
   * The displayed half is not a refinement; without it the check is wrong. A
   * seat's FG% is stored as `0.4456` and drawn as `44.6`, and a per-player
   * season total of 44.5 blocks then collides with the drawn percentage inside
   * any sane tolerance. The first version of this test reported fifteen
   * "violations", every one of them a rounded or scaled legitimate value the
   * comparison could not recognise — the same over-sensitivity `adr002.ts`
   * records for `container.textContent`, and the same consequence: a check that
   * cries wolf on a correct screen gets loosened by whoever meets it next.
   */
  function legitimateValues(): number[] {
    const values: number[] = []
    const add = (value: number) => {
      values.push(value)
    }

    for (const seat of model.seats) {
      add(seat.join.totalHoldings)
      add(seat.join.joinedPlayers)
      add(seat.participant.team_slot)
      for (const cell of seat.cells) {
        if (cell.rank !== null) add(cell.rank)
        const { aggregate } = cell
        if (aggregate.kind === 'counting') {
          if (aggregate.total === null) continue
          add(aggregate.total)
          add(Number(formatCounting(aggregate)))
        } else {
          add(aggregate.made)
          add(aggregate.attempted)
          add(Number(aggregate.attempted.toFixed(1)))
          if (aggregate.ratio === null) continue
          add(aggregate.ratio)
          // As drawn: a percentage, scaled by a hundred and rounded.
          add(aggregate.ratio * 100)
          add(Number((aggregate.ratio * 100).toFixed(1)))
        }
      }
    }
    add(model.rankedSeatCount)
    add(model.join.totalHoldings)
    add(model.join.joinedPlayers)
    return values
  }

  const matches = (a: number, b: number) => Math.abs(a - b) <= 0.5 + Math.abs(b) * 1e-6

  /**
   * Products of a rate and the source's games-played assumption.
   *
   * Two families, because they are two different mistakes. The per-player
   * product is the one `adr002.ts` names. The **seat-level sum** of those
   * products is the number this screen would produce if someone joined the
   * assumptions array to make the table say what Q9 actually asked for — it is
   * "expected performance", and it is exactly the fusion ADR-002 reserves for
   * the `expected-games` seam.
   */
  function forbiddenProducts(): { label: string; value: number }[] {
    const rates = ratesById()
    const assumptions = new Map(
      projections.source_games_played_assumptions.map((claim) => [
        claim.player_id,
        claim.assumed_games_played,
      ]),
    )
    const products: { label: string; value: number }[] = []

    for (const seat of model.seats) {
      const seatRates = seat.participant.holdings
        .map((held) => (held.player_id === null ? undefined : rates.get(held.player_id)))
        .filter((row): row is ProjectionRates => row !== undefined)

      for (const field of PROJECTION_RATE_FIELDS) {
        let seatProduct = 0
        for (const row of seatRates) {
          const rate = row[field]
          const games = assumptions.get(row.player_id) ?? null
          if (rate === null || games === null) continue
          seatProduct += rate * games
          products.push({
            label: `player ${String(row.player_id)} ${field}`,
            value: rate * games,
          })
        }
        if (seatProduct > 0) {
          products.push({
            label: `seat ${String(seat.participant.team_slot)} Σ ${field}`,
            value: seatProduct,
          })
        }
      }
    }

    return products
  }

  /** Forbidden products that are on screen and not accounted for by a legitimate value. */
  function detect(container: HTMLElement): { found: string[]; discriminable: number } {
    const rendered = renderedNumbers(container)
    const legitimate = legitimateValues()
    const candidates = forbiddenProducts().filter(
      (product) => !legitimate.some((value) => matches(value, product.value)),
    )

    return {
      found: candidates
        .filter((product) => rendered.some((value) => matches(value, product.value)))
        .map((product) => `${product.label} → ${String(product.value)}`),
      discriminable: candidates.length,
    }
  }

  it(
    'renders no product of a rate and the source games-played assumption',
    () => {
      const { container } = render(<LeagueCategoryTable model={model} />)
      const { found, discriminable } = detect(container)

      expect(found).toEqual([])
      // Not a vacuous pass. Most of the 800-odd products are distinguishable
      // from anything the screen legitimately draws, so an empty result is a
      // real absence rather than a detector that can see nothing.
      expect(discriminable).toBeGreaterThan(500)
    },
    TIMEOUT_MS,
  )

  it(
    'catches a forbidden product when one is planted, so the check above reaches something',
    () => {
      // The Code gate's precondition: prove the test reaches the code before
      // trusting what it says about it. A detector that returns `[]` because it
      // is looking in the wrong place is indistinguishable from one that
      // returns `[]` because the screen is clean.
      const { container } = render(<LeagueCategoryTable model={model} />)
      const legitimate = legitimateValues()
      const planted = forbiddenProducts().find(
        (product) => !legitimate.some((value) => matches(value, product.value)),
      )
      expect(planted).toBeDefined()

      const cell = container.querySelector('td.catgrid__cell')
      expect(cell).not.toBeNull()
      const tripwire = container.ownerDocument.createElement('span')
      // Written the way a season-total column would write it, so the detector is
      // tested against the formatting a real regression would use.
      tripwire.textContent = (planted?.value ?? 0).toFixed(1)
      cell?.append(tripwire)

      expect(detect(container).found).toContain(
        `${planted?.label ?? ''} → ${String(planted?.value ?? 0)}`,
      )

      tripwire.remove()
      // And green again once it is gone, so the red above is attributable to the
      // plant and not to anything else this render happens to contain.
      expect(detect(container).found).toEqual([])
    },
    TIMEOUT_MS,
  )

  it(
    'has no decision-number column beyond the categories and feed completeness',
    () => {
      // Independent of the product detector, and for the reason `adr002.ts`
      // gives: the detector asks whether a specific forbidden value is on
      // screen, and this asks whether a column nobody agreed to has appeared —
      // which catches a "value", "$", "z-score" or "expected games" column the
      // detector cannot compute and so cannot look for.
      const { container } = render(<LeagueCategoryTable model={model} />)
      const headers = [...container.querySelectorAll('thead th')].map(
        (th) => th.textContent?.replace(/\s*↓$/, '').trim() ?? '',
      )
      expect(headers).toEqual([
        'Team',
        'Players',
        'Feed skipped',
        'PTS',
        'REB',
        'AST',
        'STL',
        'BLK',
        '3PM',
        'TO',
        'FG%',
        'FT%',
      ])
    },
    TIMEOUT_MS,
  )
})
