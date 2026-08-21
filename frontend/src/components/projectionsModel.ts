/**
 * The join behind the projections screen.
 *
 * Three arrays arrive keyed by `player_id`: `projections` (the rates),
 * `players` (the labels) and `source_games_played_assumptions` (what the source
 * assumed about availability). This module joins them and reports what did not
 * line up, rather than assuming the backend's guarantees held.
 *
 * **Why report rather than reject.** The endpoint does guarantee that `players`
 * and `projections` describe the same `player_id` set, each exactly once, and
 * that the row count matches the lineage. Checking those in the response
 * validator and refusing on failure would trade a visible, countable
 * inconsistency for a blank screen — and a blank board during a live draft is
 * worse than one carrying a marked hole. So the validator checks value sanity
 * and this module checks collection consistency, out loud.
 *
 * **Membership, not cardinality — for the two comparisons where both directions
 * are meaningful.** `players ↔ rates` is checked both ways
 * (`playersWithoutRates`, `ratesWithoutPlayer`). This is not defensive
 * symmetry; it is the specific defect a sibling lane shipped and caught: a
 * comparison that iterates the rows it received cannot notice a row replaced by
 * a duplicate of another. The count holds, the census holds, and a real value
 * silently becomes the marker meaning "nothing was sent". Length equality is
 * reported as its own signal *in addition to* membership, never as a proxy.
 *
 * **`assumptions → rates` is deliberately one-directional**, and saying so is
 * the point — an earlier version of this paragraph claimed *every* check went
 * both ways, which was false of this one and would have let the next editor
 * stop looking. An assumption naming a player we carry no rates for is a fault
 * (`assumptionsWithoutRates`); a rate carrying no assumption is the modelled
 * `absent` state, which the wire contract declares legitimate, so counting it
 * as an integrity fault would fire on every well-formed sparse cohort. Note
 * what that costs: for Basketball Monster, where the screen's own copy says an
 * absent assumption *cannot* occur, one would render as `·` and this model
 * would still report the cohort consistent. The recorded test pins the absence
 * of that case rather than the model doing it.
 *
 * **The table is built from `projections`, not from `players`.** The rates are
 * what the cohort *is* — `projection_count` counts them — so a rate row with no
 * matching player is rendered under its bare `player_id` rather than dropped,
 * because dropping it would silently shrink the cohort the lineage claims. A
 * player with no rates is counted and reported but not drawn, because a row of
 * sixteen absence markers is indistinguishable from a source that published a
 * player and no numbers.
 *
 * **ADR-002: no rate is ever multiplied by anything here.** See
 * `AssumptionState` for the structural half of that guarantee.
 */

import { PROJECTION_RATE_FIELDS } from '../api/types'
import type {
  CurrentProjections,
  ProjectionLineage,
  ProjectionPlayer,
  ProjectionRateField,
  ProjectionRates,
  SourceGamesPlayedClaim,
} from '../api/types'

/**
 * What the source said about one player's games played — four states, not two.
 *
 * The obvious modelling is "a number or nothing", and it is wrong, because the
 * payload distinguishes cases that collapse into "nothing" under it:
 *
 * - `stated` — a value arrived and parsed.
 * - `unreadable` — the source published text we could not read as a number.
 *   **A value did arrive.** Telling a reader "the source said nothing" here
 *   would be false, and the raw text is shown so they can see what it said.
 * - `absent` — no entry for this player at all. The array is deliberately
 *   sparse and this is its documented meaning: the source said nothing. **It is
 *   never zero.**
 * - `unexplained` — an entry exists carrying neither a value nor the text it
 *   came from. **The contract does not describe this state**, which is exactly
 *   why it gets its own member and is counted rather than folded into `absent`.
 *   The two fields are independently nullable in the backend schema, so it is
 *   expressible — but `backend` traced the producer and
 *   `importer.py:686-690` (`_write_games_played_assumption`) returns before
 *   creating the row when both are `None`, so no current writer can emit one. It is kept as a **contract
 *   guard**, not as a state a user will meet, and nothing in the UI claims it
 *   occurs. Following the convention PR #47 arrived at for date absence:
 *   enumerate the benign readings and let an unrecognised state fall to the
 *   side that gets attention, because the reverse default is the one that
 *   hides a defect.
 *
 * **What is reachable today, traced rather than assumed.** For the only source
 * this screen requests, `absent` and `unreadable` are both unreachable:
 *
 * - `unreadable` cannot occur through any profile. `parser.py:224-239` captures
 *   the raw text first and then parses; a parse failure is fatal and the row is
 *   dropped, and the only other route to a null value is empty text, which
 *   `parser.py:226` has already excluded.
 * - `absent` cannot occur for Basketball Monster. Its
 *   `required_production_fields` is **set-equal to `CANONICAL_STAT_FIELDS` in
 *   both directions** — verified by `backend` rather than inferred — and
 *   `parser.py:293-296` refuses a row on a non-empty `missing_required_values`
 *   list, so it is `any`, not `all`. A row with no games figure has no divisor,
 *   which nulls its 14 `SEASON_TOTAL` columns and, through
 *   `parser.py:448-450`, the 2 derived fields computed from them
 *   (`points_per_game`, `rebounds_per_game`). Every required field is
 *   therefore null and the row is dropped. So every stored Basketball Monster
 *   row carries an assumption *and* a value for every rate, by construction.
 *   Sparsity is reachable only through `MANUAL_PROFILE`, whose columns are
 *   already per-game and whose `gp` column is optional.
 *
 * **That last conclusion is load-bearing for on-screen copy and, as of this
 * commit, unpinned.** The projections screen tells the reader that a `·` should
 * not appear for Basketball Monster, so if the two tuples ever drift the copy
 * becomes actively misleading — and `grep required_production_fields
 * backend/tests/` currently returns nothing across a 1304-test suite. Adding a
 * canonical field without adding it to BBM's required set would make it
 * legitimately nullable in a stored row while `_rates()` still splats it onto
 * the wire, and no test opposes that one-line edit. `ownership.md` already
 * treats `CANONICAL_STAT_FIELDS` as a cross-owner seam, but it pins the
 * vocabulary against the *wire*, not against what the profile *requires*, which
 * is the half this rests on. `backend` is adding the set-equality test with
 * this screen named as the consumer; if it does not land, the copy is true and
 * undefended, which is recorded in `docs/handoff.md` rather than assumed away.
 *
 * All four members are therefore still modelled and tested, but only `stated`
 * is exercised by a recorded response. That is a real gap in the evidence and
 * is recorded as such rather than papered over — see the recorded test's
 * docstring and `docs/handoff.md`.
 *
 * **This type is the structural half of the ADR-002 guarantee**, and it is the
 * load-bearing half. It is a discriminated union rather than a number precisely
 * so a games-played figure is never a bare `number` sitting in the same object
 * as a rate: multiplying requires first destructuring a union member, which is
 * a deliberate act rather than a typo. The DOM test in
 * `ProjectionsTable.adr002.test.tsx` is a *backstop* for the one product that
 * can be named — `rate × assumed_games_played` — and cannot be more than that,
 * because the prohibition is rate × **any** count. A per-week or
 * rest-of-season figure multiplies by a different number and is equally the
 * fusion ADR-002 permits only at `expected-games`. So do not weaken this
 * structure believing the test still covers you; it does not.
 */
export type AssumptionState =
  | { kind: 'stated'; games: number; raw: string | null }
  | { kind: 'unreadable'; raw: string }
  | { kind: 'unexplained' }
  | { kind: 'absent' }

export interface ProjectionRow {
  playerId: number
  /** Null when the cohort carries rates for a player with no player row. */
  player: ProjectionPlayer | null
  rates: ProjectionRates
  assumption: AssumptionState
}

export interface ProjectionsIntegrity {
  /** Labelled players carrying no rates in this cohort. Counted, not drawn. */
  playersWithoutRates: number
  /** Rate rows with no player row. Drawn under a bare id. */
  ratesWithoutPlayer: number
  duplicatePlayerRows: number
  duplicateRateRows: number
  duplicateAssumptionRows: number
  /** Assumptions naming a player this response carries no rates for. */
  assumptionsWithoutRates: number
  /** Entries carrying neither a value nor the text it came from. */
  unexplainedAssumptions: number
  /**
   * `projections.length` against `lineage.projection_import.projection_count`.
   *
   * Reported *alongside* the membership checks rather than instead of them.
   * The endpoint guarantees these agree; a disagreement means the rows carried
   * are not the rows the canonical release verified and digested.
   */
  rowCountMatchesLineage: boolean
  isConsistent: boolean
}

export interface ProjectionsModel {
  /**
   * Carried through from the same payload object the rows came from.
   *
   * Not a separate prop the page could pass from somewhere else. The backend
   * brackets every read between two runs of the canonical release so a 200 can
   * never carry a lineage block that does not describe its own rows; threading
   * both through one model object is how that property survives into the
   * component tree instead of being re-established by convention.
   */
  lineage: ProjectionLineage
  season: string
  source: string
  rows: ProjectionRow[]
  /**
   * Rate rows the response *carried*, before duplicates were dropped.
   *
   * Distinct from `rows.length`, and carried explicitly because the integrity
   * banner must be able to quote the number the failing check actually
   * compared. `rowCountMatchesLineage` tests this against
   * `projection_count`; the banner previously reported `rows.length` instead,
   * so with a duplicated row it announced a disagreement while displaying two
   * identical numbers — "carried 1 rate rows but its lineage block counts 1".
   * Found in review. A message that picks a different operand from the check
   * it explains is worse than no message.
   */
  carriedRowCount: number
  integrity: ProjectionsIntegrity
}

/**
 * Index by `player_id`, keeping the first of any duplicate and counting them.
 *
 * First-wins matches the schedule grid's behaviour for duplicate counts. The
 * count is what matters: a duplicate is the mechanism by which a real value
 * becomes an absence marker while every length check still passes.
 */
function indexById<T extends { player_id: number }>(
  rows: readonly T[],
): { byId: Map<number, T>; duplicates: number } {
  const byId = new Map<number, T>()
  let duplicates = 0
  for (const row of rows) {
    if (byId.has(row.player_id)) {
      duplicates += 1
      continue
    }
    byId.set(row.player_id, row)
  }
  return { byId, duplicates }
}

/** How many keys of `left` are absent from `right`. Directional on purpose. */
function countMissingFrom(left: Iterable<number>, right: ReadonlySet<number>): number {
  let missing = 0
  for (const key of left) {
    if (!right.has(key)) missing += 1
  }
  return missing
}

function readAssumption(claim: SourceGamesPlayedClaim | undefined): AssumptionState {
  if (claim === undefined) return { kind: 'absent' }
  if (claim.assumed_games_played !== null) {
    return {
      kind: 'stated',
      games: claim.assumed_games_played,
      raw: claim.assumed_games_played_raw,
    }
  }
  if (claim.assumed_games_played_raw !== null) {
    return { kind: 'unreadable', raw: claim.assumed_games_played_raw }
  }
  return { kind: 'unexplained' }
}

export function buildProjectionsModel(payload: CurrentProjections): ProjectionsModel {
  const players = indexById(payload.players)
  const rates = indexById(payload.projections)
  const assumptions = indexById(payload.source_games_played_assumptions)

  const rateIds = new Set(rates.byId.keys())
  const playerIds = new Set(players.byId.keys())

  const rows: ProjectionRow[] = []
  let unexplainedAssumptions = 0

  // Iterating `payload.projections` rather than the map preserves the
  // backend's ordering, which is by `player_id` and is part of its contract.
  // A duplicate is skipped here on the same first-wins rule the index used, so
  // the drawn rows and the counted rows cannot disagree.
  const drawn = new Set<number>()
  for (const row of payload.projections) {
    if (drawn.has(row.player_id)) continue
    drawn.add(row.player_id)
    const assumption = readAssumption(assumptions.byId.get(row.player_id))
    if (assumption.kind === 'unexplained') unexplainedAssumptions += 1
    rows.push({
      playerId: row.player_id,
      player: players.byId.get(row.player_id) ?? null,
      rates: row,
      assumption,
    })
  }

  const integrity: ProjectionsIntegrity = {
    playersWithoutRates: countMissingFrom(playerIds, rateIds),
    ratesWithoutPlayer: countMissingFrom(rateIds, playerIds),
    duplicatePlayerRows: players.duplicates,
    duplicateRateRows: rates.duplicates,
    duplicateAssumptionRows: assumptions.duplicates,
    assumptionsWithoutRates: countMissingFrom(assumptions.byId.keys(), rateIds),
    unexplainedAssumptions,
    rowCountMatchesLineage:
      payload.projections.length === payload.lineage.projection_import.projection_count,
    isConsistent: false,
  }

  integrity.isConsistent =
    integrity.playersWithoutRates === 0 &&
    integrity.ratesWithoutPlayer === 0 &&
    integrity.duplicatePlayerRows === 0 &&
    integrity.duplicateRateRows === 0 &&
    integrity.duplicateAssumptionRows === 0 &&
    integrity.assumptionsWithoutRates === 0 &&
    integrity.unexplainedAssumptions === 0 &&
    integrity.rowCountMatchesLineage

  return {
    lineage: payload.lineage,
    season: payload.season,
    source: payload.source,
    rows,
    carriedRowCount: payload.projections.length,
    integrity,
  }
}

/** The marker for a quantity the source did not publish. Never a zero. */
export const NOT_PUBLISHED = '·'

/**
 * The marker for a label *we* do not hold, which is a different claim.
 *
 * `team_abbreviation` and `primary_position` come from our own player record —
 * the second through an outer join that yields `null` when the crosswalk has no
 * position — so their absence says nothing about what Basketball Monster
 * published. Sharing `NOT_PUBLISHED` with the rate columns made the screen's
 * key false: it tells the reader a `·` should not appear for this source,
 * which is true of rates and was never true of labels. The committed fixture
 * disproved it on the same commit that shipped it — `Patrick Baldwin Jr.` has
 * a null `primary_position` and rendered a `·` under a key saying one means
 * something upstream changed.
 *
 * Found in review. The reasoning behind the copy was sound and its *scope* was
 * not, which is the failure `gates.md` records as copy true of one condition
 * and false of the next raising the same marker.
 */
export const NO_LABEL = '—'

/**
 * Two decimals, always, including trailing zeros.
 *
 * Fixed rather than trimmed so the decimal points align down a column of
 * sixteen numeric fields; a ragged column of per-game rates is materially
 * harder to scan. `0` renders as `0.00` and is a published zero — visibly
 * different from `NOT_PUBLISHED`, which is the distinction this whole screen
 * turns on.
 *
 * This rounds for *display only*. The underlying value is not rounded and
 * nothing downstream reads this string, because nothing downstream exists: the
 * screen computes no aggregate, no total and no derived quantity.
 */
export function formatRate(value: number | null): string {
  return value === null ? NOT_PUBLISHED : value.toFixed(2)
}

/** The display label for a rate field, used by the header and by tests. */
export const RATE_LABELS: Record<ProjectionRateField, string> = {
  minutes_per_game: 'MIN',
  points_per_game: 'PTS',
  rebounds_per_game: 'REB',
  offensive_rebounds_per_game: 'OREB',
  defensive_rebounds_per_game: 'DREB',
  assists_per_game: 'AST',
  steals_per_game: 'STL',
  blocks_per_game: 'BLK',
  turnovers_per_game: 'TO',
  personal_fouls_per_game: 'PF',
  field_goals_made_per_game: 'FGM',
  field_goals_attempted_per_game: 'FGA',
  three_pointers_made_per_game: '3PM',
  three_pointers_attempted_per_game: '3PA',
  free_throws_made_per_game: 'FTM',
  free_throws_attempted_per_game: 'FTA',
}

/**
 * Volume pairs shown adjacent, so a made column is never read without its
 * attempted column beside it.
 *
 * No percentage is derived from them anywhere on this screen. A 90% free-throw
 * shooter on one attempt is worthless, and a percentage rendered without its
 * volume is the single most common bug in homebrew fantasy tools — so the
 * volumes are published and the percentage is not computed at all, which is
 * also exactly what the backend does.
 */
export const VOLUME_PAIR_STARTS: ReadonlySet<ProjectionRateField> = new Set([
  'field_goals_made_per_game',
  'three_pointers_made_per_game',
  'free_throws_made_per_game',
])

export { PROJECTION_RATE_FIELDS }
