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

import type { ProjectionPlayer } from '../api/types'
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
  /** What the quantity would tell the owner, in one line. */
  purpose: string
  /** Where it already exists, or why it does not exist at all. */
  whereItLives: string
  /** The specific thing that would put it on this screen. */
  whatWouldFillIt: string
}

export const EVIDENCE_STATUS_LABELS: Record<EvidenceStatus, string> = {
  'not-exposed': 'computed, not exposed',
  'not-defined': 'not defined',
  blocked: 'deliberately blocked',
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
    status: 'not-exposed',
    purpose:
      'Of the games we directly observed, how often he suited up. Not a complete availability rate: missing rows are never counted as absences.',
    whereItLives:
      'compute_reliability_scorecards in backend/src/hoops_gm/availability/reliability.py, callable in-process only.',
    whatWouldFillIt:
      'A backend route serving the scorecard. reliability-metrics shipped with "no schema, API, or UI"; that route is a separate unit and is not this screen\'s to add.',
  },
  {
    id: 'back-to-back',
    quantity: 'Back-to-back sit evidence',
    status: 'not-exposed',
    purpose:
      'Whether he sits the second night of a back-to-back, from direct observation rather than reputation.',
    whereItLives:
      'The same scorecard. Back-to-backs themselves are a pure-calendar computation over the schedule (build_schedule_density) and do not depend on any model.',
    whatWouldFillIt:
      'The same missing route. Note that this one also needs every game to carry a date, because a back-to-back is a statement about two dates.',
  },
  {
    id: 'monthly-trend',
    quantity: 'Availability trend by month',
    status: 'not-exposed',
    purpose:
      'Whether the missed games cluster — a bad November and a clean spring is a different asset from steady attrition.',
    whereItLives:
      'The same scorecard, grouped by calendar month. No slope, smoothing or direction label is fitted, by design.',
    whatWouldFillIt:
      'The same missing route, plus a decision about which season it reads. As of today the 2026-27 season has not started, so the only season with observations is the previous one.',
  },
  {
    id: 'minutes-consistency',
    quantity: 'Minutes consistency',
    status: 'not-exposed',
    purpose:
      'How stable his minutes are in the games he does play, which is a different question from whether he plays.',
    whereItLives:
      'The same scorecard: sample standard deviation over mean minutes, null below two observations.',
    whatWouldFillIt: 'The same missing route.',
  },
  {
    id: 'category-dispersion',
    quantity: 'Per-category dispersion',
    status: 'not-exposed',
    purpose:
      'Empirical p20/p80 and sample SD per category, so a category line can be read as a range rather than a point.',
    whereItLives:
      'The same scorecard. These are historical lower and upper observations, explicitly not predictive intervals.',
    whatWouldFillIt: 'The same missing route.',
  },
  {
    id: 'composite-grade',
    quantity: 'A single durability grade',
    status: 'not-defined',
    purpose:
      'The one letter or number most tools put beside a player. This project does not have one.',
    whereItLives:
      'Nowhere. docs/models/reliability-metrics.md states that no composite reliability grade is defined, because no composite has a defensible target to be calibrated against.',
    whatWouldFillIt:
      'An argued definition and something to validate it against. Until then a grade here would be a number invented by the dashboard, which is the failure mode this screen exists to avoid.',
  },
  {
    id: 'roster-fragility',
    quantity: 'Roster-level fragility summary',
    status: 'not-defined',
    purpose: 'How much of your own roster is carrying availability risk at once.',
    whereItLives:
      'Nowhere, and it needs two things this build has neither of: a roster, and a per-player durability measure to sum over one.',
    whatWouldFillIt:
      'A route carrying league rosters, plus whichever durability quantity above lands first. No endpoint on this backend serves a roster today.',
  },
  {
    id: 'p-play',
    quantity: 'p(play) — the availability model',
    status: 'blocked',
    purpose:
      'The per-game probability that he suits up. The quantity the whole project is built around.',
    whereItLives:
      'Not built. It is blocked on two independent routes at once, both recorded in docs/backlog.md.',
    whatWouldFillIt:
      'Direct non-play labels at scale from player_participation, and the injury-status conversion it depends on. Under R35 a missing row is never an absence, so the labels cannot be manufactured from silence — and no heuristic stands in for them here.',
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
export function barPercent(games: number, maximum: number | null): number {
  if (maximum === null || maximum <= 0) return 0
  return (games / maximum) * 100
}
