/**
 * The reliability screen's model: what hoops-gm knows about availability, and
 * — mostly — what it does not.
 *
 * **Read this before adding a number to this file.** `AGENTS.md` opens by
 * claiming availability is the product: a 70-game player and a 55-game player
 * with identical per-game lines are not the same asset. This screen is the
 * first surface where that claim stops being a sentence in a document. It is
 * therefore also the surface where an invented number would do the most damage,
 * because a plausible durability figure is exactly the kind of wrong that does
 * not crash.
 *
 * So this module computes **two** things and refuses the rest:
 *
 * 1. `AVAILABILITY_EVIDENCE` — the inventory of the quantities a reliability
 *    screen is supposed to show, each one carrying the reason it is not here.
 *    Static, cited, and deliberately not a placeholder for numbers to be
 *    dropped into later: the status is the content.
 * 2. `buildAvailabilitySummary` — descriptive statistics of the **one**
 *    availability figure that is actually on the wire, which is a third
 *    party's assumption rather than our measurement.
 *
 * ## What is not here, and why the gap is the point
 *
 * `reliability-metrics` is `done` and computes observed play/non-play rates, a
 * calendar-month trend, back-to-back evidence, minutes CV and per-category
 * dispersion. **None of it is reachable from a browser.** Its own backlog entry
 * says "no schema, API, or UI was added" and `docs/models/reliability-metrics.md`
 * repeats it: "No result table, migration, API, or UI is part of v2." The
 * computation lives in `backend/src/hoops_gm/availability/reliability.py` and is
 * callable in-process only; `git grep -n reliability -- backend/src/hoops_gm/api`
 * returns nothing.
 *
 * A dependency edge can therefore be satisfied as a *computation* and
 * unsatisfied as a *contract*, and the backlog graph cannot tell those apart.
 * That is worth a paragraph here rather than a line in a commit message,
 * because the next person to open this file will otherwise assume the numbers
 * were forgotten rather than deliberately absent.
 *
 * ## The rule this module follows instead of a threshold
 *
 * No grade, rank, bucket, recommendation or discount. The model card is
 * explicit that "no composite reliability grade is defined", and inventing one
 * on the client would be the same error the backend refused to make, one layer
 * further from anyone who could catch it.
 */

import type { ProjectionPlayer, SchedulePendingGame } from '../api/types'
import type { AssumptionState, ProjectionsModel } from './projectionsModel'

/**
 * Why a quantity this screen should show is not showing.
 *
 * A closed set, and the three members are genuinely different situations that
 * a reader has to be able to act on differently. Collapsing them into one
 * "coming soon" would tell the owner nothing about which of them is his to
 * unblock.
 */
export type EvidenceStatus =
  /** Computed by the backend today, but no route carries it to a browser. */
  | 'not-exposed'
  /**
   * Carried by a route, but this screen does not call it yet.
   *
   * Split out from `not-exposed` on 2026-08-26, when
   * `GET /api/v1/reliability/scorecards` shipped and made "computed, not
   * exposed" false for five rows at once. Folding the two together would have
   * been the cheaper edit and the wrong one: they are unblocked by different
   * people. `not-exposed` is a backend unit; this is a wiring unit on this
   * screen, and a reader who cannot tell them apart cannot tell whose queue a
   * row is in — which is the whole reason this table has a status column.
   */
  | 'not-wired'
  /** No such quantity exists, by a decision that was argued and recorded. */
  | 'not-defined'
  /** Deliberately blocked upstream; the block is the finding, not an oversight. */
  | 'blocked'

export interface EvidenceItem {
  /** Stable key, used for React keys and for probe assertions. */
  id: string
  /** The quantity, named the way the model card names it. */
  quantity: string
  status: EvidenceStatus
  /**
   * Which season this quantity would describe.
   *
   * **Mandatory, and on the screen rather than in a tooltip.** Availability
   * evidence reads **2025-26**, because 2026-27 has no played games until late
   * October and draft day is 18 October — so any durability figure that means
   * anything before the draft is about last season. The cohorts this screen
   * loads from the API are 2026-27. Two seasons on one page, and a durability
   * figure whose season is ambiguous is the `gameEt` shape exactly: well-formed,
   * plausible, and silently about a different thing than the reader assumes.
   *
   * Ruled by `architect`; the season belongs in the endpoint contract rather
   * than in a picker on this screen, so this field states it rather than
   * offering to change it.
   */
  season: string
  /** What the quantity would tell the owner, in one line. */
  purpose: string
  /** Where it already exists, or why it does not exist at all. */
  whereItLives: string
  /**
   * What is **blocking** it — named as a blocker, not as an absence.
   *
   * A reader who sees "not built yet" concludes someone is slow. One who sees
   * "blocked pending a protocol decision the owner has to make" concludes
   * something different and more accurate, and it is the difference between a
   * screen that reports status and one that reports a queue.
   */
  blocker: string
}

export const EVIDENCE_STATUS_LABELS: Record<EvidenceStatus, string> = {
  'not-exposed': 'computed, not exposed',
  'not-wired': 'exposed, not on this screen',
  'not-defined': 'not defined',
  blocked: 'deliberately blocked',
}

/**
 * The season availability evidence would be read from. **A ruling, not a datum.**
 *
 * Ruled by `architect` on 2026-08-25: reliability evidence reads **2025-26**,
 * because a 2026-27 cohort is empty until late October and draft day is 18
 * October, so any reliability figure that means anything before the draft is
 * about last season. It belongs in the endpoint contract rather than in a
 * toggle on this screen, so this constant states it and offers no way to change
 * it.
 *
 * It is written here as a literal because it is a governance decision rather
 * than something on the wire. That is exactly the kind of constant that goes
 * stale silently, so `describeSeasonSplit` compares it against the season the
 * API actually returned instead of letting both sit on screen unrelated.
 */
export const EVIDENCE_SEASON = '2025-26'

/**
 * How the season the API returned relates to the season evidence would read.
 *
 * **This is the `gameEt` lesson applied to a season label.** Two seasons appear
 * on this page — the cohort loaded from the API, and the season durability
 * evidence would be measured over — and a reader who conflates them concludes
 * something false about every number on screen. A well-formed, plausible season
 * string is not self-explaining, so the relationship between the two is
 * computed and rendered rather than left to be inferred from two labels sitting
 * near each other.
 *
 * Returning a discriminated union rather than a boolean is deliberate: the
 * `same` case is not merely "no warning needed", it is a *different world* —
 * one where the season has rolled over and this constant needs revisiting — and
 * a boolean would let a caller render nothing for it.
 */
export type SeasonSplit =
  | { kind: 'differs'; loaded: string; evidence: string }
  | { kind: 'same'; season: string }

export function describeSeasonSplit(loadedSeason: string): SeasonSplit {
  const loaded = loadedSeason.trim()
  if (loaded === EVIDENCE_SEASON) return { kind: 'same', season: EVIDENCE_SEASON }
  return { kind: 'differs', loaded, evidence: EVIDENCE_SEASON }
}

/**
 * The inventory's own shape, counted rather than asserted in prose.
 *
 * A browser probe measured this screen at **4.01 laptop screens** of scroll at
 * 1440x900, and the finding a reader most needs — *how much of this is
 * missing* — was at the bottom of an eight-row table of paragraphs. That is the
 * five-second rule failing: the answer existed and could not be read quickly.
 *
 * Derived from the array rather than written out, so it cannot drift from the
 * table beneath it. `onScreen` is `0` and is stated: it is the one number on
 * this screen that a reader might otherwise assume rather than check.
 */
export interface EvidenceTally {
  total: number
  notExposed: number
  notWired: number
  notDefined: number
  blocked: number
  onScreen: number
}

export function tallyEvidence(items: readonly EvidenceItem[] = AVAILABILITY_EVIDENCE): EvidenceTally {
  return {
    total: items.length,
    notExposed: items.filter((item) => item.status === 'not-exposed').length,
    notWired: items.filter((item) => item.status === 'not-wired').length,
    notDefined: items.filter((item) => item.status === 'not-defined').length,
    blocked: items.filter((item) => item.status === 'blocked').length,
    // Every status in the closed set means "not here". If a further status is
    // ever added for a quantity that *has* arrived, this stops being zero by
    // construction rather than by editing a sentence.
    //
    // `not-wired` was added to this list when the reliability route shipped,
    // and adding it here was the load-bearing half of that edit: a quantity
    // that a route now carries is still not on this screen, and letting it
    // fall through to `onScreen` would have turned an endpoint's existence
    // into a claim that five numbers were rendered. That is the exact
    // substitution — a guarantee about one property read as a guarantee about
    // another — this screen exists to refuse.
    onScreen: items.filter(
      (item) => !['not-exposed', 'not-wired', 'not-defined', 'blocked'].includes(item.status),
    ).length,
  }
}

/**
 * The inventory. Ordered by how directly each answers "will he play?".
 *
 * Every claim in here names a file, a route, or a backlog item, so that a
 * reader can disprove it in about ninety seconds rather than take it on trust.
 * That is the house rule about falsifiable claims applied to on-screen copy,
 * which is where it is easiest to skip.
 */
export const AVAILABILITY_EVIDENCE: readonly EvidenceItem[] = [
  {
    id: 'observed-play-rate',
    quantity: 'Observed play / non-play rate',
    status: 'not-wired',
    season: '2025-26',
    purpose:
      'Of the games we directly observed, how often he suited up. Not a complete availability rate: missing rows are never counted as absences.',
    whereItLives:
      'compute_reliability_scorecards in backend/src/hoops_gm/availability/reliability.py, served by GET /api/v1/reliability/scorecards.',
    blocker:
      'The route shipped on 2026-08-26 and this screen does not call it yet. What that route needs from a store is worth stating, because the previous version of this row got it wrong twice: compute_reliability_scorecards requires team_schedule rows, final games, and an exact two-rows-per-game join between them, all in the store it reads. The 2025-26 participation store has 43,037 rows and 1,230 final games and served none of this, and the reason was never a missing table — team_schedule is present and empty, refresh_runs is present and empty, and the first refusal reached is "no current schedule:nba-schedule cohort", with the empty-schedule refusal immediately behind it. python -m hoops_gm.dev.publish_reliability_evidence fills both. Verified against a copy of that store, read-only.',
  },
  {
    id: 'back-to-back',
    quantity: 'Back-to-back sit evidence',
    status: 'not-wired',
    season: '2025-26',
    purpose:
      'Whether he sits the second night of a back-to-back, from direct observation rather than reputation.',
    whereItLives:
      'The same scorecard, but the quantity has two halves with different footings: which nights are back-to-backs is pure calendar (build_schedule_density, no model), whereas whether he sat one is an observation that needs the participation ledger. The calendar half being model-free says nothing about the half that carries the meaning.',
    blocker:
      'On the route, and unwired on this screen, like the rest of the scorecard. The calendar half additionally needs each game attributable to two dated team calendars, counted below; that limit bounds the calendar half only, and the sit half depends on the participation ledger regardless. Note that this row is the reason the publisher refuses a ledger short of 1,230 games: is_back_to_back is set from the gap to the previous game, so a missing played game silently becomes a day of rest rather than a missing row.',
  },
  {
    id: 'monthly-trend',
    quantity: 'Availability trend by month',
    status: 'not-wired',
    season: '2025-26',
    purpose:
      'Whether the missed games cluster — a bad November and a clean spring is a different asset from steady attrition.',
    whereItLives:
      'The same scorecard, grouped by calendar month. No slope, smoothing or direction label is fitted, by design.',
    blocker:
      'On the route, and unwired on this screen. The store half is the same as the row above: the 2025-26 store has team_schedule and refresh_runs as empty tables rather than absent ones, so what it needs is a publish rather than a migration.',
  },
  {
    id: 'minutes-consistency',
    quantity: 'Minutes consistency',
    status: 'not-wired',
    season: '2025-26',
    purpose:
      'How stable his minutes are in the games he does play, which is a different question from whether he plays.',
    whereItLives:
      'The same scorecard: sample standard deviation over mean minutes, null below two observations.',
    blocker:
      'On the route, and unwired on this screen. One call produces every quantity on this scorecard, so it refuses as a whole or returns as a whole — which is also why one fetch will wire all five of these rows at once.',
  },
  {
    id: 'category-dispersion',
    quantity: 'Per-category dispersion',
    status: 'not-wired',
    season: '2025-26',
    purpose:
      'Empirical p20/p80 and sample SD per category, so a category line can be read as a range rather than a point.',
    whereItLives:
      'The same scorecard. These are historical lower and upper observations, explicitly not predictive intervals.',
    blocker:
      'On the route, and unwired on this screen. The response omits the per-observation row ids the in-process dataclass carries — about 70,000 integers on a full season — and carries counts instead, so a per-player evidence drill-down would need its own route rather than this one.',
  },
  {
    id: 'composite-grade',
    quantity: 'A single durability grade',
    status: 'not-defined',
    season: 'None — the quantity does not exist, so it has no season.',
    purpose:
      'The one letter or number most tools put beside a player. This project does not have one.',
    whereItLives:
      'Nowhere. docs/models/reliability-metrics.md states that no composite reliability grade is defined, because no composite has a defensible target to be calibrated against.',
    blocker:
      'Blocked on an argued definition, not on engineering. There is nothing to build until someone states what the grade predicts and what would falsify it; a grade shipped before that is a number invented by the dashboard.',
  },
  {
    id: 'roster-fragility',
    quantity: 'Roster-level fragility summary',
    status: 'not-defined',
    season: '2026-27 rosters read through 2025-26 evidence — two seasons in one number.',
    purpose: 'How much of your own roster is carrying availability risk at once.',
    whereItLives:
      'Nowhere, and it needs two things: a roster, and a per-player durability measure to sum over one. The second arrived on 2026-08-26.',
    blocker:
      'Blocked on the roster. No endpoint on this backend serves a league roster, and until one does there is nothing to sum the reliability scorecards over. This row previously said both inputs were missing; one of them has since landed, which is why it now names one blocker rather than two — a row that keeps claiming the harder version of its own problem is the failure this table exists to avoid.',
  },
  {
    id: 'p-play',
    quantity: 'p(play) — the availability model',
    status: 'blocked',
    season: 'Would predict 2026-27 games from 2025-26 and earlier evidence.',
    purpose:
      'The per-game probability that he suits up. The quantity the whole project is built around.',
    whereItLives:
      'Not built, and not merely unstarted — deliberately held. Recorded in docs/backlog.md under availability-model and injury-status-conversion.',
    blocker:
      'Blocked pending an owner decision on the preregistered protocol, which is a governance hold rather than a queue position: injury-status-conversion is frozen at docs/models/injury-status-conversion-preregistration.md with no model fitted and no number emitted, and the v3 successor is marked Proposed and binds only when the owner binds it. Separately it needs direct non-play labels at scale — under R35 a missing row is never an absence, so they cannot be manufactured from silence.',
  },
] as const

/* --- The one availability figure that is actually on the wire ------------- */

/**
 * One player's stated games-played assumption, ready to draw.
 *
 * `name` is nullable for the same reason the projections table renders a bare
 * id: a rate row with no matching player record is still part of the cohort,
 * and dropping it would silently shrink the thing being described.
 */
export interface AssumptionPoint {
  playerId: number
  name: string | null
  games: number
  raw: string | null
}

/**
 * A stated assumption whose raw text does not read back as the parsed number.
 *
 * This is the one check in this module that can genuinely fail against a real
 * payload, and it is here rather than in the response validator on purpose. The
 * validator's job is to refuse a value that cannot be true; this is two values
 * that are each individually plausible and disagree with each other, which is
 * the shape of defect that survives type-checking and looks like data.
 */
export interface RawDivergence {
  playerId: number
  raw: string
  parsed: number
}

export interface AvailabilitySummary {
  /** Rate rows drawn by the projections model — the cohort being described. */
  cohortSize: number
  /** Every stated assumption, ascending. The order the strip is drawn in. */
  stated: AssumptionPoint[]
  /** Lowest and highest stated assumption. Null when nothing is stated. */
  minimum: number | null
  maximum: number | null
  /**
   * How many distinct values the cohort actually contains.
   *
   * Carried because a strip of sixty identical bars and a strip of sixty
   * varied ones look different but read the same if you only quote a range,
   * and because `1` is the reading that says the source published no
   * availability signal at all while still populating the field.
   */
  distinctValues: number
  /** The source published text we could not read as a number. */
  unreadable: number
  /** An entry carrying neither a value nor the text it came from. */
  unexplained: number
  /** No entry at all for a player in the cohort. Never zero games. */
  absent: number
  rawDivergences: RawDivergence[]
}

/**
 * Read a raw games string strictly.
 *
 * `Number('')` is `0` and `Number(' ')` is `0`, so an empty or blank raw string
 * would silently agree with a parsed zero under a bare `Number()` comparison —
 * the false-zero trap this repository keeps finding, arriving through the
 * comparison rather than through the value. Blank is rejected before parsing.
 */
function readRawGames(raw: string): number | null {
  const trimmed = raw.trim()
  if (trimmed === '') return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : null
}

function pointFrom(
  playerId: number,
  player: ProjectionPlayer | null,
  assumption: Extract<AssumptionState, { kind: 'stated' }>,
): AssumptionPoint {
  return {
    playerId,
    name: player?.full_name ?? null,
    games: assumption.games,
    raw: assumption.raw,
  }
}

/**
 * Describe the cohort's games-played assumptions. Nothing is multiplied.
 *
 * **Built from `ProjectionsModel` rather than from the raw payload**, and that
 * is deliberate rather than convenient. The join, the first-wins duplicate
 * rule, and the four-state `AssumptionState` union all already exist there and
 * are tested there; a second reader of the same payload would be a second place
 * for those semantics to drift, and drift between two readers of one payload is
 * invisible until the two are shown side by side.
 *
 * It also inherits the structural half of the ADR-002 guarantee for free: a
 * games figure only ever arrives here inside a discriminated union member, so
 * multiplying one by a rate requires destructuring first, which is a deliberate
 * act rather than a typo.
 *
 * **No median, and no mean.** Both would require choosing an interpolation
 * convention, and for an even-sized cohort the usual one produces a number no
 * player in it was assigned — a value on screen that nothing published. The
 * sorted strip shows the distribution directly, which is what a median is a
 * lossy summary of, so nothing is lost by declining to invent one.
 */
export function buildAvailabilitySummary(model: ProjectionsModel): AvailabilitySummary {
  const stated: AssumptionPoint[] = []
  const rawDivergences: RawDivergence[] = []
  let unreadable = 0
  let unexplained = 0
  let absent = 0

  for (const row of model.rows) {
    const { assumption } = row
    switch (assumption.kind) {
      case 'stated': {
        stated.push(pointFrom(row.playerId, row.player, assumption))
        if (assumption.raw !== null) {
          const reread = readRawGames(assumption.raw)
          if (reread === null || reread !== assumption.games) {
            rawDivergences.push({
              playerId: row.playerId,
              raw: assumption.raw,
              parsed: assumption.games,
            })
          }
        }
        break
      }
      case 'unreadable':
        unreadable += 1
        break
      case 'unexplained':
        unexplained += 1
        break
      case 'absent':
        absent += 1
        break
    }
  }

  // Ascending by games, then by id so the order is total and the strip does not
  // reshuffle between renders of the same payload.
  stated.sort((a, b) => a.games - b.games || a.playerId - b.playerId)

  const values = stated.map((point) => point.games)

  return {
    cohortSize: model.rows.length,
    stated,
    minimum: values[0] ?? null,
    maximum: values[values.length - 1] ?? null,
    distinctValues: new Set(values).size,
    unreadable,
    unexplained,
    absent,
    rawDivergences,
  }
}

/**
 * The bar height for one assumption, as a percentage of the tallest.
 *
 * **Zero-based, scaled to the cohort's own maximum**, and both halves of that
 * matter. Zero-based because a strip scaled between the minimum and the maximum
 * turns a 59-to-79 spread into a bar of nothing beside a full-height bar, which
 * overstates the difference by exactly as much as the reader cannot see. Scaled
 * to the cohort's own maximum rather than to 82, because 82 is a constant this
 * screen would be importing from outside the payload — and the served season
 * carries in-season-tournament games that make the true per-team total
 * something a client should not be guessing at.
 *
 * Returns 0 rather than dividing when the maximum is absent or non-positive.
 */
/**
 * How the pending games describe themselves, read from the payload.
 *
 * ADR-013 makes "pending means an undrawn knockout bracket" a **falsifiable**
 * reading rather than a definition, which is why `ScheduleLineage` renders the
 * label per game so an operator can check it. This screen counts rather than
 * lists, so it states the labels and the quantifier — and both are derived,
 * because a hard-coded characterisation keeps asserting itself after it stops
 * being true, which is precisely what ADR-013 asks a consumer to watch for.
 *
 * Three things here are deliberate, and each replaced a sentence that was true
 * of the cohort in front of me and false as a property of the quantity:
 *
 * - **`null` is unlabelled, not labelled.** `game_label` is `string | null` and
 *   the boundary admits `null` on purpose ("tolerate a gap you can describe").
 *   Filtering only on `''` counts a `null`-labelled game as labelled and then
 *   lets `join` coerce it to nothing, rendering "all labelled ." — a false
 *   quantifier with a hole where the evidence should be. `ScheduleLineage`
 *   filters both; this is the consumer that diverged.
 * - **"All" is only said when it is true of every counted game.** A mixed
 *   cohort reports how many.
 * - **"All labelled X" is only said for a single distinct label.** With several,
 *   "all labelled X, Y" reads as though every game carries both.
 */
export function describePendingLabels(games: readonly SchedulePendingGame[]): string {
  const labelled = games.filter((game) => game.game_label !== null && game.game_label !== '')
  const distinct = [...new Set(labelled.map((game) => game.game_label))]
  if (distinct.length === 0) return ''

  const list = distinct.length === 1 ? String(distinct[0]) : distinct.join(' and ')
  if (labelled.length < games.length) return `, ${labelled.length} of them labelled ${list}`
  return distinct.length === 1 ? `, all labelled ${list}` : `, labelled ${list}`
}

export function barPercent(games: number, maximum: number | null): number {
  if (maximum === null || maximum <= 0) return 0
  return (games / maximum) * 100
}
