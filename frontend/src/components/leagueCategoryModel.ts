/**
 * The live league category table: every seat ranked 1-to-N in every category.
 *
 * The owner asked for this twice, unprompted, in his own words
 * (`docs/what-draft-day-looks-like.md`):
 *
 * > **Q4** *"...visibility on other teams' positional and categorical needs...
 * > some way to show me that of the 4 teams who still have not passed on a
 * > player, only one of them is really competitive in a top category."*
 * >
 * > **Q9** *"Who is winning each category — a tier list for all of the owners,
 * > based on expected performance, 1 to X in rebounds. So I can see categories
 * > I'm deficient in and excelling in."*
 *
 * ## What this module computes, stated so it can be disproved cheaply
 *
 * For one seat and one counting category, **the sum of the per-game rates the
 * projection source published for the players that seat currently holds**,
 * joined on `player_id`. For a ratio category, **Σ makes ÷ Σ attempts** over the
 * same set. Nothing else. Every input is a field of
 * `GET /leagues/{id}/projections/current`; every output is `+` or `÷` over
 * those fields.
 *
 * That definition is the whole reason this is a **Code gate** unit rather than a
 * Model gate one. There is no fitted parameter here, no weighting, no
 * distribution, no z-score and no calibration question, so there is nothing a
 * held-out backtest could report on. Add one and that stops being true.
 *
 * ## What it is *not*, which is the part that matters
 *
 * **It is not expected performance, and Q9 asked for expected performance.**
 * Expected performance is per-game production fused with expected games played,
 * and ADR-002 permits that fusion at exactly one seam — `expected-games` — which
 * does not exist. `p(play)` does not exist either. So the honest deliverable is
 * the production half alone, labelled as the production half alone. The screen
 * says so; `CategoriesPage.tsx` carries that copy and
 * `leagueCategoryModel.test.ts` pins that no rate is ever multiplied by a games
 * count anywhere in here.
 *
 * `source_games_played_assumptions` **is** on the wire and this module
 * deliberately does not read it. The projections route's own docstring is
 * explicit: for a season-total source the assumption is the exact divisor the
 * importer used, so `rate × assumption` reconstructs the source's published
 * season total, and doing that join *is* the forbidden fusion. Not importing the
 * type is the structural half of that guarantee.
 *
 * **A total is not depth-adjusted, and mid-draft that is a real confound.** A
 * seat holding five players sums more rebounds than a seat holding three, and
 * this module will rank it higher for that reason alone. Correcting for it means
 * assuming what the empty slots will produce, which is a projection of a player
 * nobody has drafted — a model, and a large one. So the confound is **surfaced
 * rather than corrected**: `joinedPlayers` is carried per seat, the table draws
 * it beside the seat name, and the on-screen key says the ranking is not
 * depth-adjusted. Naming the limitation is the deliverable here; removing it is
 * a different unit.
 *
 * ## Percentage categories
 *
 * `AGENTS.md` calls raw percentage the single most common bug in homebrew
 * fantasy tools, and it is right, but the failure it names is a *player-level*
 * one: ranking a 90%-on-one-attempt free-throw shooter above a 85%-on-eight
 * shooter. At seat level the correct quantity is the aggregate ratio
 * `Σ makes ÷ Σ attempts`, which is volume-weighted **by construction** — that
 * one-attempt shooter contributes 0.9 to the numerator and 1.0 to the
 * denominator and moves a seat's ratio by almost nothing. It is also exactly
 * what an H2H category is scored on for a week.
 *
 * A ratio is therefore never a mean of player percentages, and no player
 * percentage is computed at any point. `Σ attempts` is carried alongside every
 * ratio and drawn on screen, so a seat leading a percentage on trivial volume is
 * visible rather than inferred.
 *
 * ## Nulls
 *
 * `null` on a rate means the source did not publish that quantity and **is never
 * zero** (the wire contract says so at the field). A player with a null rate
 * therefore does not contribute to that category's sum and is counted in
 * `omittedPlayers` instead. For a ratio, a player needs **both** halves of the
 * shooting pair or contributes to neither: half a pair would move a numerator
 * without its denominator, which is a different and worse lie than omitting the
 * player.
 *
 * ## Unrankable is not last
 *
 * A seat with nothing to aggregate — no holdings, none of them resolved to a
 * `player_id`, or every joined player null in this category — gets
 * `rank: null`, not rank N. "We have no data for this seat" and "this seat is
 * worst" are different claims, and the second one is the fabrication this unit
 * was told not to commit. This is not hypothetical: **every holding in the
 * seeded demo carries `player_id: null`**, because the draft seeder invents
 * player names that the identity crosswalk cannot match, so the all-unranked
 * board is the state a first-time reader actually meets.
 */

import type { DraftParticipant, DraftState } from '../api/draftTypes'
import type { CurrentProjections, ProjectionRateField, ProjectionRates } from '../api/types'

/**
 * The nine scoring categories.
 *
 * **Source: `docs/league/2025-26-rules-baseline.md`, which says of itself
 * "Historical reference only. Not verified for 2026-27."** No endpoint publishes
 * this league's scoring settings — verified by walking the served OpenAPI
 * document on 2026-08-27, which exposes nineteen paths and not one carrying
 * league scoring configuration — so there is nothing to read it from and nothing
 * to check it against. `league-settings-ingest` is the backlog item that would
 * close it.
 *
 * That makes the category set itself the least-defended claim on this screen,
 * which is why it is a named constant with its provenance attached rather than
 * an inline array, and why `CategoriesPage.tsx` tells the reader where it came
 * from and that it is unverified.
 */
export const CATEGORY_SOURCE = 'docs/league/2025-26-rules-baseline.md'

/** Whether a bigger number is a better one. Turnovers are the only `lower`. */
export type CategoryDirection = 'higher' | 'lower'

interface CategoryBase {
  key: string
  /** Column header. */
  label: string
  /** Expanded name, for the column's `title` and the key below the table. */
  description: string
  direction: CategoryDirection
}

/** A category that is the sum of one published per-game rate. */
export interface CountingCategory extends CategoryBase {
  kind: 'counting'
  field: ProjectionRateField
}

/**
 * A category that is a ratio of two published per-game rates.
 *
 * Two fields, never one. There is no percentage anywhere on the wire and this
 * module never derives one for a player.
 */
export interface RatioCategory extends CategoryBase {
  kind: 'ratio'
  madeField: ProjectionRateField
  attemptedField: ProjectionRateField
}

export type Category = CountingCategory | RatioCategory

export const CATEGORIES: readonly Category[] = [
  {
    kind: 'counting',
    key: 'pts',
    label: 'PTS',
    description: 'Points',
    direction: 'higher',
    field: 'points_per_game',
  },
  {
    kind: 'counting',
    key: 'reb',
    label: 'REB',
    description: 'Rebounds',
    direction: 'higher',
    field: 'rebounds_per_game',
  },
  {
    kind: 'counting',
    key: 'ast',
    label: 'AST',
    description: 'Assists',
    direction: 'higher',
    field: 'assists_per_game',
  },
  {
    kind: 'counting',
    key: 'stl',
    label: 'STL',
    description: 'Steals',
    direction: 'higher',
    field: 'steals_per_game',
  },
  {
    kind: 'counting',
    key: 'blk',
    label: 'BLK',
    description: 'Blocks',
    direction: 'higher',
    field: 'blocks_per_game',
  },
  {
    kind: 'counting',
    key: 'tpm',
    label: '3PM',
    description: 'Three-pointers made',
    direction: 'higher',
    field: 'three_pointers_made_per_game',
  },
  {
    kind: 'counting',
    key: 'to',
    label: 'TO',
    // The only category where fewest wins, and the only place in this module
    // where a rank is not simply "biggest first".
    description: 'Turnovers — fewest wins',
    direction: 'lower',
    field: 'turnovers_per_game',
  },
  {
    kind: 'ratio',
    key: 'fg',
    label: 'FG%',
    description: 'Field goal percentage — made ÷ attempted, aggregated',
    direction: 'higher',
    madeField: 'field_goals_made_per_game',
    attemptedField: 'field_goals_attempted_per_game',
  },
  {
    kind: 'ratio',
    key: 'ft',
    label: 'FT%',
    description: 'Free throw percentage — made ÷ attempted, aggregated',
    direction: 'higher',
    madeField: 'free_throws_made_per_game',
    attemptedField: 'free_throws_attempted_per_game',
  },
]

/** A seat's aggregate in one counting category. */
export interface CountingAggregate {
  kind: 'counting'
  /** Σ of the published per-game rate. Null when nothing contributed. */
  total: number | null
  /** Joined players that published this rate. */
  contributingPlayers: number
  /** Joined players whose rate was `null` — not published, never zero. */
  omittedPlayers: number
}

/** A seat's aggregate in one ratio category. */
export interface RatioAggregate {
  kind: 'ratio'
  made: number
  attempted: number
  /** `made / attempted`, or null when no attempts were published. */
  ratio: number | null
  /** Joined players that published **both** halves of the shooting pair. */
  contributingPlayers: number
  omittedPlayers: number
}

export type CategoryAggregate = CountingAggregate | RatioAggregate

/** The comparable scalar behind an aggregate, or null when there is none. */
export function aggregateValue(aggregate: CategoryAggregate): number | null {
  return aggregate.kind === 'counting' ? aggregate.total : aggregate.ratio
}

/**
 * How a seat's holdings divided up when joined against the projection cohort.
 *
 * Three ways a holding fails to contribute, kept apart because they mean
 * different things and want different fixes:
 *
 * - `unresolvedHoldings` — the log recorded a typed name and no `player_id`. The
 *   player crosswalk has not matched it. This is the demo's entire population.
 * - `unmatchedHoldings` — a `player_id` was recorded and the projection cohort
 *   does not carry it. The source did not publish this player.
 * - `joinedPlayers` — a `player_id` that the cohort carries. Only these
 *   contribute to any aggregate.
 *
 * **No name matching, anywhere.** A holding without a `player_id` is not matched
 * to the cohort by its label, however close the strings look. Fuzzy identity is
 * `data-engineer`'s crosswalk, behind its own gate, and a browser guessing at it
 * would attribute one player's rates to another and rank a seat on them.
 */
export interface SeatJoin {
  totalHoldings: number
  unresolvedHoldings: number
  unmatchedHoldings: number
  joinedPlayers: number
}

export interface SeatCategoryCell {
  category: Category
  aggregate: CategoryAggregate
  /**
   * 1-to-N among seats this category could be computed for. Null when it could
   * not be computed for this seat — **which is not the same as last.**
   */
  rank: number | null
  /**
   * Rank position expressed as a five-step tier, for the red-to-green scale the
   * owner asked for ("the way BBM uses RED for poor performance and green for
   * excellence"). Null exactly when `rank` is.
   *
   * Derived from rank position among *ranked* seats, not from the value's
   * distance from a mean — a spread-based scale would be a distribution
   * statistic, and the tier list he described is positional.
   */
  tier: 1 | 2 | 3 | 4 | 5 | null
}

export interface SeatRow {
  participant: DraftParticipant
  join: SeatJoin
  cells: SeatCategoryCell[]
}

/**
 * Why the table has nothing to draw, when it has nothing to draw.
 *
 * A discriminated reason rather than a boolean, because "this draft has no
 * selections yet" and "every selection is unresolved so nothing can be joined"
 * look identical on screen and call for completely different actions.
 */
export type EmptyReason =
  | { kind: 'no-holdings' }
  | { kind: 'nothing-joined'; unresolved: number; unmatched: number }
  | null

export interface LeagueCategoryModel {
  seats: SeatRow[]
  /** The seat flagged `is_owner`, if the draft names one. */
  ownerSeat: SeatRow | null
  /** Seats that contributed at least one joined player. */
  rankedSeatCount: number
  join: SeatJoin
  emptyReason: EmptyReason
  /**
   * What the projection source said its numbers were scored for.
   *
   * `h2h_categories` is the only value this table is honest under. `null` means
   * nobody stated it, and the wire contract is emphatic that it must never be
   * defaulted to this league's format: *"a points-league projection consumed as
   * a 9-cat one is wrong in a way no downstream check can see."* So it is
   * carried through to the screen and said out loud rather than assumed.
   */
  assumedScoringType: string | null
  /** True when the source stated a format and it is not a category format. */
  scoringTypeMismatch: boolean
}

/**
 * Float noise, not a rounding policy.
 *
 * Two seats holding sets of rates that sum to the same real number can differ in
 * the last bit or two because the additions happen in a different order. Calling
 * those a tie is arithmetically correct. This is deliberately far too small to
 * merge two genuinely different totals: at a seat total of 100 points it is
 * 1e-7, and the displayed precision is two decimal places.
 */
function isTie(a: number, b: number): boolean {
  return Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b))
}

function sumCounting(rows: ProjectionRates[], field: ProjectionRateField): CountingAggregate {
  let total = 0
  let contributingPlayers = 0
  let omittedPlayers = 0

  for (const row of rows) {
    const value = row[field]
    // `null` is "the source did not publish this", never zero. Adding zero here
    // would be indistinguishable from a player who genuinely produces none.
    if (value === null) {
      omittedPlayers += 1
      continue
    }
    total += value
    contributingPlayers += 1
  }

  return {
    kind: 'counting',
    total: contributingPlayers === 0 ? null : total,
    contributingPlayers,
    omittedPlayers,
  }
}

function sumRatio(rows: ProjectionRates[], category: RatioCategory): RatioAggregate {
  let made = 0
  let attempted = 0
  let contributingPlayers = 0
  let omittedPlayers = 0

  for (const row of rows) {
    const m = row[category.madeField]
    const a = row[category.attemptedField]
    // Both halves or neither. A made count without its attempts would inflate
    // the numerator against a denominator that never saw it.
    if (m === null || a === null) {
      omittedPlayers += 1
      continue
    }
    made += m
    attempted += a
    contributingPlayers += 1
  }

  return {
    kind: 'ratio',
    made,
    attempted,
    // Guarded rather than relying on `x/0 === Infinity`: a seat whose joined
    // players are all projected to attempt nothing has no percentage, and
    // `Infinity` or `NaN` would render as a number.
    ratio: attempted > 0 ? made / attempted : null,
    contributingPlayers,
    omittedPlayers,
  }
}

/**
 * Standard competition ranking ("1224"), with equal values sharing a rank.
 *
 * Seats with no value are left out of the ordering entirely rather than sorted
 * to the bottom, so an unranked seat never displaces a ranked one.
 */
function rankSeats(
  values: (number | null)[],
  direction: CategoryDirection,
): (number | null)[] {
  const ordered = values
    .map((value, index) => ({ value, index }))
    .filter((entry): entry is { value: number; index: number } => entry.value !== null)
    .sort((a, b) => (direction === 'higher' ? b.value - a.value : a.value - b.value))

  const ranks: (number | null)[] = values.map(() => null)

  let currentRank = 0
  let previousValue: number | null = null
  ordered.forEach((entry, position) => {
    if (previousValue === null || !isTie(entry.value, previousValue)) {
      currentRank = position + 1
      previousValue = entry.value
    }
    ranks[entry.index] = currentRank
  })

  return ranks
}

/**
 * Rank position → one of five tiers, best first.
 *
 * Spread evenly across the seats that could be ranked, so a twelve-team league
 * gives roughly two or three seats a tier and the top and bottom always exist.
 * With fewer ranked seats than tiers the middle tiers are simply unused, which
 * is correct: three seats are a top, a middle and a bottom, not three fifths of
 * a scale.
 */
function tierFor(rank: number, rankedCount: number): 1 | 2 | 3 | 4 | 5 {
  if (rankedCount <= 1) return 3
  const position = (rank - 1) / (rankedCount - 1)
  const tier = Math.min(5, Math.floor(position * 5) + 1)
  return tier as 1 | 2 | 3 | 4 | 5
}

function emptyJoin(): SeatJoin {
  return { totalHoldings: 0, unresolvedHoldings: 0, unmatchedHoldings: 0, joinedPlayers: 0 }
}

function addJoin(a: SeatJoin, b: SeatJoin): SeatJoin {
  return {
    totalHoldings: a.totalHoldings + b.totalHoldings,
    unresolvedHoldings: a.unresolvedHoldings + b.unresolvedHoldings,
    unmatchedHoldings: a.unmatchedHoldings + b.unmatchedHoldings,
    joinedPlayers: a.joinedPlayers + b.joinedPlayers,
  }
}

/**
 * Build the table.
 *
 * `projections` may be null — a league with no released cohort answers `404` or
 * `409`, and that is a state the screen renders rather than a state it refuses
 * to draw. Seats, holdings and the join counts are all still true; only the
 * numbers are missing.
 */
export function buildLeagueCategoryModel(
  state: DraftState,
  projections: CurrentProjections | null,
): LeagueCategoryModel {
  // First occurrence wins on a duplicate, matching `projectionsModel`'s rule.
  // The endpoint guarantees uniqueness; this does not depend on it.
  const ratesById = new Map<number, ProjectionRates>()
  for (const row of projections?.projections ?? []) {
    if (!ratesById.has(row.player_id)) ratesById.set(row.player_id, row)
  }

  const seats = state.participants
    .slice()
    .sort((a, b) => a.team_slot - b.team_slot)
    .map((participant) => {
      const join = emptyJoin()
      const rows: ProjectionRates[] = []

      for (const holding of participant.holdings) {
        join.totalHoldings += 1
        if (holding.player_id === null) {
          join.unresolvedHoldings += 1
          continue
        }
        const rates = ratesById.get(holding.player_id)
        if (rates === undefined) {
          join.unmatchedHoldings += 1
          continue
        }
        join.joinedPlayers += 1
        rows.push(rates)
      }

      return {
        participant,
        join,
        rows,
      }
    })

  const aggregates = seats.map((seat) =>
    CATEGORIES.map((category) =>
      category.kind === 'counting'
        ? sumCounting(seat.rows, category.field)
        : sumRatio(seat.rows, category),
    ),
  )

  const rankedSeatCount = seats.filter((seat) => seat.join.joinedPlayers > 0).length

  const ranksByCategory = CATEGORIES.map((category, categoryIndex) =>
    rankSeats(
      aggregates.map((seatAggregates) => {
        const aggregate = seatAggregates[categoryIndex]
        return aggregate === undefined ? null : aggregateValue(aggregate)
      }),
      category.direction,
    ),
  )

  const rows: SeatRow[] = seats.map((seat, seatIndex) => ({
    participant: seat.participant,
    join: seat.join,
    cells: CATEGORIES.map((category, categoryIndex) => {
      const aggregate =
        aggregates[seatIndex]?.[categoryIndex] ??
        ({
          kind: 'counting',
          total: null,
          contributingPlayers: 0,
          omittedPlayers: 0,
        } satisfies CountingAggregate)
      const rank = ranksByCategory[categoryIndex]?.[seatIndex] ?? null
      const rankedInCategory = (ranksByCategory[categoryIndex] ?? []).filter(
        (value) => value !== null,
      ).length
      return {
        category,
        aggregate,
        rank,
        tier: rank === null ? null : tierFor(rank, rankedInCategory),
      }
    }),
  }))

  const totalJoin = rows.reduce((accumulated, row) => addJoin(accumulated, row.join), emptyJoin())

  let emptyReason: EmptyReason = null
  if (totalJoin.totalHoldings === 0) {
    emptyReason = { kind: 'no-holdings' }
  } else if (totalJoin.joinedPlayers === 0) {
    emptyReason = {
      kind: 'nothing-joined',
      unresolved: totalJoin.unresolvedHoldings,
      unmatched: totalJoin.unmatchedHoldings,
    }
  }

  const assumedScoringType = projections?.lineage.projection_import.assumed_scoring_type ?? null

  return {
    seats: rows,
    ownerSeat: rows.find((row) => row.participant.is_owner) ?? null,
    rankedSeatCount,
    join: totalJoin,
    emptyReason,
    assumedScoringType,
    // Only a *stated* non-category format is a mismatch. `null` is "nobody
    // said", which is a different and weaker signal, reported separately rather
    // than folded in here.
    scoringTypeMismatch:
      assumedScoringType !== null && !assumedScoringType.includes('categories'),
  }
}

/** Marker for a cell whose category could not be computed for this seat. */
export const NOT_COMPUTABLE = '·'

export function formatCounting(aggregate: CountingAggregate): string {
  return aggregate.total === null ? NOT_COMPUTABLE : aggregate.total.toFixed(1)
}

/**
 * A ratio as a percentage to one decimal place.
 *
 * Derived from the aggregate, never from a player. The attempt volume that
 * produced it is rendered beside it by the table rather than folded in here, so
 * a reader can see a leading percentage standing on almost no shots.
 */
export function formatRatio(aggregate: RatioAggregate): string {
  return aggregate.ratio === null ? NOT_COMPUTABLE : `${(aggregate.ratio * 100).toFixed(1)}%`
}

export function formatAggregate(aggregate: CategoryAggregate): string {
  return aggregate.kind === 'counting' ? formatCounting(aggregate) : formatRatio(aggregate)
}

/** `1st`, `2nd`, `3rd`, `11th`. Used in the owner's summary line. */
export function ordinal(rank: number): string {
  const remainderTen = rank % 10
  const remainderHundred = rank % 100
  if (remainderTen === 1 && remainderHundred !== 11) return `${String(rank)}st`
  if (remainderTen === 2 && remainderHundred !== 12) return `${String(rank)}nd`
  if (remainderTen === 3 && remainderHundred !== 13) return `${String(rank)}rd`
  return `${String(rank)}th`
}
