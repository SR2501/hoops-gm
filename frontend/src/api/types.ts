/**
 * Types mirroring the backend's response models.
 *
 * Hand-written on purpose for now. Generating them from `/openapi.json` is the
 * obvious next step and the reason the backend serves the document, but a
 * codegen step nobody has needed yet is a build dependency without a payoff.
 * When the surface grows past a handful of endpoints, generate these and
 * delete the file.
 *
 * Keep in step with `backend/src/hoops_gm/api/schemas.py`.
 */

export interface Health {
  status: 'ok'
  service: string
  version: string
  environment: string
}

export interface Readiness {
  status: 'ok' | 'degraded'
  database: 'ok' | 'unavailable'
  detail: string | null
}

export interface Meta {
  service: string
  version: string
  environment: string
  season: string
  entity_groups: string[]
}

/** The backend's stable error envelope. */
export interface ApiErrorBody {
  error: string
  detail: string
  request_id: string | null
}

/* --- Schedule grid (ADR-012) ---------------------------------------------- */

/**
 * The schedule refresh that produced the counts on screen.
 *
 * `refreshed_at` is kept as the raw ISO string the backend sent rather than a
 * `Date`. The grid displays it verbatim as well as derived, because a
 * self-describing timestamp is exactly the kind of field that can be
 * mislabelled, and a user who can see the original string can check the claim.
 */
/**
 * A game the source published without team identifiers (ADR-013).
 *
 * There is deliberately no team field, and there cannot be one. The source
 * emits `teamId: 0` with `teamName`, `teamCity`, `teamTricode` and `teamSlug`
 * all null for these games — being undecided is the entire content of the
 * record. Anything on screen attributing a pending game to a named team would
 * be an attribution the source explicitly withheld, so this type gives the UI
 * nothing to make one out of.
 */
/**
 * Why a pending game carries no date (ADR-013's nullable-date contract).
 *
 * A closed set on purpose: the producer validates it and an unrecognised value
 * is a finding rather than a variation, precisely because a consumer keys
 * behaviour on it. `''` means a date *was* published and reconciled.
 *
 * **The split that matters is what it tells an operator to do**, and it is not
 * the split a reader would guess from the names:
 *
 * - `not_offered` — both time fields absent. The source has not committed, and
 *   this is the **only** cause that means *wait*.
 * - `unreadable` — a value was published and *we* could not read it, or the
 *   schema moved. **Our failure.**
 * - `implausible` — both parsed, agreed, and named a date nowhere near the
 *   season. Agreement is not validity: the NBA uses a `1900-01-01` epoch as a
 *   live placeholder, and a placeholder pair reconciles perfectly. **Our
 *   failure to reject a placeholder earlier.**
 * - `irreconcilable` — both parsed and disagree; the source contradicting
 *   itself.
 *
 * **The classification is ADR-013's, and the ADR now assigns every absence
 * cause.** The table at `:194-199` gives `not_offered` *wait* and `unreadable`,
 * `irreconcilable` and `implausible` *investigate* — four rows, because `''` is
 * not an absence cause but a date that resolved. It was decided from the live
 * feed — all six pending games currently
 * carry real dates, so every fault reason fires zero times and the
 * alarm-fatigue objection to `irreconcilable` on the fault side does not apply
 * on the evidence. `:201` records that `irreconcilable` sits there **by decision
 * rather than by derivation**, which is the honest form: a consumer cannot
 * distinguish a sloppy sentinel from a genuine contradiction.
 *
 * That citation is worth more than most because the ADR did not always say it,
 * and the history is the reason this comment is long. An earlier version here
 * reconstructed the whole classification from the producer's **exit codes** — it
 * exits non-zero on `unreadable` and `implausible` only — and that was wrong,
 * because an exit code answers *should this import fail* and this screen answers
 * *should a human look*. Two questions, one signal, and it was taken because it
 * was the one available. ADR-013 `:268-269` now names that conflation as how
 * `irreconcilable` was first classified wrongly, so the trap is documented at
 * the source rather than only here.
 *
 * A later version of this comment then said the ADR assigned no action to any
 * member. That was false too — it already assigned three — and a reviewer caught
 * it: a correction over-claiming in the same direction as the thing it
 * corrected, discarding the evidence that supported this client. Both errors
 * were about the same document and both ran toward a bigger gap than existed.
 *
 * The reason it is a fault is worth keeping, because `code-review` found it and
 * it is sharper than the argument that won: the producer's own docstring says
 * an epoch placeholder pair in the date fields **reconciles perfectly** for
 * 1900 (`-05:00`) and fails only *by accident* for year 0001, because
 * `America/New_York` ran on `-04:56` local mean time before 1883. So the same
 * phenomenon — a sentinel in both fields — lands in `implausible` or
 * `irreconcilable` depending on a nineteenth-century offset, and in
 * `unreadable` if the hour happens to overflow `datetime.min`. One thing, three
 * labels, on criteria no operator can act on. That argues both that
 * `irreconcilable` belongs with the faults and that the cleaner repair is
 * upstream in the producer's own set.
 *
 * **One asymmetry to carry forward when this set grows.** The inversion below
 * makes the *action* safe by default — an unrecognised reason routes to
 * investigate. It does not make the *explanation* safe. The copy for the fault
 * branch says a value came and could not be used, which is true of the three
 * causes that reach it and is **already false of `not_offered`**, where the
 * source published a game and no date at all. What keeps that from being a
 * visible defect is the *routing*, not the copy: `not_offered` goes to
 * `awaitingSource`, so the fault wording never describes it. A new cause
 * meaning *nothing was published* would route to investigate — correct action —
 * and be described as a value we could not use, which would be false.
 *
 * So the mechanism a future editor has to preserve is the routing, and the
 * hypothetical is not hypothetical: a current member already violates the
 * clause and is saved only by never reaching it. That is unreachable today
 * because the boundary refuses reasons outside this list, so a new one arrives
 * as a contract error rather than as false copy. Adding a member is therefore a
 * copy change too, not only a list change.
 */
export const DATE_ABSENCE_REASONS = [
  '',
  'not_offered',
  'unreadable',
  'irreconcilable',
  'implausible',
] as const

export type DateAbsenceReason = (typeof DATE_ABSENCE_REASONS)[number]

/**
 * Absence causes that mean *wait*.
 *
 * **Enumerated on the wait side on purpose, and it is the whole design.** The
 * obvious shape is a fault list with everything else defaulting to wait; this
 * is the inversion, so a reason nobody has enumerated — a value added to the
 * contract next month, a typo, anything — falls to **investigate**. ADR-013
 * names rendering an investigate-class cause as a wait-class one as the error
 * that matters, and a default has to point somewhere: it points at the
 * expensive-but-safe answer rather than the comforting one.
 *
 * It also removes a guarantee rather than restating it. There was a
 * `FAULT_ABSENCE_REASONS` here documented as *mirroring* the producer's
 * `_FAULT_ABSENCE_REASONS`, and ADR-013's ruling on `irreconcilable` made that
 * false — the sets diverge now, deliberately. Rewriting the comment to describe
 * a superset would have left a cross-file claim that nothing enforces, of
 * exactly the kind this branch has removed three times. **The producer has no
 * constant this one could mirror**, because it never asks "should a human
 * look" — its frozenset answers "should this import fail", which is a different
 * question, and reading one as the other is the mistake that put
 * `irreconcilable` on the wrong side in the first place.
 *
 * `not_offered` is the only member and that is not an anomaly: it is an action
 * with one known cause, and it is the one cause whose meaning is certain by
 * construction — both time fields absent, nothing published. The fault side is,
 * by the ruling's own words, a decision about causes a consumer *cannot* tell
 * apart. Collapsing the certain case into the uncertain one would leave one
 * clause spanning two operator actions, which is the flattening this whole
 * split exists to remove.
 */
export const WAIT_ABSENCE_REASONS: readonly DateAbsenceReason[] = ['not_offered']

export interface SchedulePendingGame {
  nba_game_id: string
  /**
   * ISO day, or `null` when no trustworthy date could be derived.
   *
   * `null` does **not** mean the source withheld a date, and an earlier version
   * of this screen said it did. Three of the four absence causes involve a
   * value that *was* published — unreadable, irreconcilable and implausible all
   * describe something arriving and being rejected. Only `not_offered` means
   * nothing came. Which is why the cause is carried beside it rather than
   * inferred from the `null`.
   */
  game_date: string | null
  /** e.g. "Emirates NBA Cup". */
  game_label: string | null
  /** e.g. "Quarterfinal". */
  game_sub_label: string | null
  /** e.g. "in-season-knockout". */
  game_subtype: string | null
  /** Empty string when `game_date` is present. See `DATE_ABSENCE_REASONS`. */
  date_absence_reason: string
}

/**
 * ADR-013 replaces the old `resolved == source` invariant with
 * `source_game_count == resolved_game_count + pending_game_ids.length`.
 *
 * `pending_game_ids` is the term the invariant counts; `pending_games` carries
 * the dates, labels and absence reasons. The backend derives the first from the
 * second and refuses any stored block where they name different games in a
 * different order, so on a 200 they are the same set.
 *
 * **Both are required.** They were optional on the wire while this dashboard
 * was stacked under an unmerged backend lane, and the absence was rendered as
 * its own statement. That lane has merged, so the tolerance and the notice that
 * described it are gone: a response without the block is now a response that is
 * not the contract, and the boundary refuses it rather than the screen
 * narrating it.
 */
export interface ScheduleRefreshLineage {
  refresh_id: number
  version: string
  refreshed_at: string
  source_game_count: number
  resolved_game_count: number
  persisted_team_row_count: number
  unresolved_game_ids: string[]
  pending_game_ids: string[]
  pending_games: SchedulePendingGame[]
}

export interface ProjectionRefreshLineage {
  refresh_id: number
  version: string
  refreshed_at: string
}

export interface RecordLineage {
  id: number
  version: number
}

export interface ScheduleGridLineage {
  schedule: ScheduleRefreshLineage
  scoring_period_projection: ProjectionRefreshLineage
  deadline_calendar: RecordLineage
  settings_snapshot: RecordLineage
}

export interface ScheduleGridTeam {
  team_id: number
  nba_team_id: number
  abbreviation: string
  name: string
}

export interface ScheduleGridPeriod {
  period_number: number
  start_date: string
  end_date: string
  is_playoff: boolean
}

export interface ScheduleGridCount {
  period_number: number
  team_id: number
  games: number
}

/**
 * `counts` is dense by contract: one row per (team, period), zeros explicit.
 * The client does not assume it, because a missing cell and a zero cell mean
 * completely different things and the grid has to be able to say which.
 */
export interface ScheduleGrid {
  league_id: number
  season: string
  lineage: ScheduleGridLineage
  teams: ScheduleGridTeam[]
  periods: ScheduleGridPeriod[]
  counts: ScheduleGridCount[]
}

/* --- Imported projections (ADR-002) --------------------------------------- */

/**
 * Every per-game rate field a projection row carries, in the order the screen
 * shows them.
 *
 * This mirrors `ingest/projections/profiles.py`'s `CANONICAL_STAT_FIELDS`,
 * which `ownership.md:42` records as a **wire contract** rather than an
 * ingestion detail: `api/routes/projections.py`'s `_rates()` splats that tuple
 * into `ProjectionRates`, and a backend test pins the two in lockstep. So this
 * list is a third copy of the same vocabulary and the recorded-fixture test is
 * what keeps it honest — a field renamed upstream fails there rather than
 * rendering an empty column.
 *
 * **The vocabulary is per-game rates only, and that is load-bearing rather than
 * descriptive.** A seasonal total or an expected-games field added to the tuple
 * upstream would reach the wire and then this array, so ADR-002's separation
 * depends on it staying what its name says. If one appears here, the correct
 * response is to refuse to render it and report it, not to add a column.
 *
 * Order is display order, not the backend's: makes and attempts are adjacent so
 * a volume pair reads as a pair. No percentage is derived from them anywhere —
 * a percentage without its volume is the single most common bug in homebrew
 * fantasy tools, and a 90% free-throw shooter on one attempt is worthless.
 */
export const PROJECTION_RATE_FIELDS = [
  'minutes_per_game',
  'points_per_game',
  'rebounds_per_game',
  'offensive_rebounds_per_game',
  'defensive_rebounds_per_game',
  'assists_per_game',
  'steals_per_game',
  'blocks_per_game',
  'turnovers_per_game',
  'personal_fouls_per_game',
  'field_goals_made_per_game',
  'field_goals_attempted_per_game',
  'three_pointers_made_per_game',
  'three_pointers_attempted_per_game',
  'free_throws_made_per_game',
  'free_throws_attempted_per_game',
] as const

export type ProjectionRateField = (typeof PROJECTION_RATE_FIELDS)[number]

/**
 * The exact import these rates were read from.
 *
 * Three digests, and they answer different questions: `content_sha256` is the
 * CSV bytes, `profile_definition_sha256` is the parsing recipe those bytes were
 * read under, and `projection_values_sha256` is over the *stored, normalised
 * rates* — the one that moves when a row is edited in place while the other two
 * still look untouched.
 *
 * **The five audit counts partition the file**, and the backend asserts that on
 * the served body rather than only claiming it in prose. `projection_count` is
 * separate and is what this response actually carries: the rows the canonical
 * release validated. Both are published rather than one derived from the other,
 * so the screen shows both rather than picking.
 */
export interface ProjectionImportLineage {
  import_id: number
  source: string
  season: string
  imported_at: string
  content_sha256: string
  profile_id: string
  profile_version: string
  profile_definition_sha256: string
  projection_values_sha256: string
  projection_count: number
  /**
   * The scoring format the source's numbers assume, when anybody stated one.
   *
   * `null` means nobody stated it, and is never defaulted to this league's
   * format — a points-league projection consumed as a 9-cat one is wrong in a
   * way no downstream check can see. Which of the two origins won is
   * deliberately not carried, so the screen must not claim one.
   */
  assumed_scoring_type: string | null
  original_filename: string | null
  row_count: number
  matched_count: number
  needs_review_count: number
  unmatched_count: number
  rejected_count: number
}

/**
 * What produced this response.
 *
 * `blend` is a typed key that is **always `null` today**, and the distinction
 * between that and a key that is simply absent is the entire reason it exists.
 * Blend profiles, their source weights and their activation state are
 * caller-owned in-memory values with no persistence, so there is nothing for an
 * HTTP request to read. The screen renders "not blended" from this being `null`
 * — a fact — rather than from a lookup that failed.
 *
 * The declared type is `null` rather than `BlendLineage | null`, so a blend
 * arriving here is a schema change and not a fill-in. `architect` is proposing
 * ADR-015 to make a blend *recipe* durable; until that is accepted and built,
 * a non-null value here is a contract violation rather than a new feature, and
 * `isCurrentProjections` refuses it.
 */
export interface ProjectionLineage {
  projection_import: ProjectionImportLineage
  blend: null
}

/**
 * One player in the cohort, with the labels a screen needs.
 *
 * These are the canonical player record's current values, read outside any
 * lineage scope, so a player relabelled between the rates statement and this
 * one is labelled from the newer state. What cannot change is which player a
 * `player_id` denotes. The residual risk is a fresher label on the right
 * player, never a rate attributed to the wrong one.
 *
 * **`primary_position` is not lineup eligibility.** It is NBA's own coarse
 * label (`"G"`, `"F-C"`), it is nullable, and this project ingests no Fantrax
 * position data at all — `player-position-eligibility` is still pending. It
 * returned `null` for every player until `build_crosswalk` first ran, so a
 * populated column here is recent. The screen must not filter, group or sort by
 * it, because doing so would present an NBA label as a draft-board slot.
 */
export interface ProjectionPlayer {
  player_id: number
  full_name: string
  team_abbreviation: string | null
  primary_position: string | null
}

/**
 * One player's per-game production rates, exactly as stored.
 *
 * Per-game only (ADR-002). Nothing here is a season total and nothing here is
 * an expected-games number.
 *
 * Every field is present on every row, and **`null` means the source did not
 * publish that quantity — it is never a zero.** Rendering the two the same way
 * is the defect this type's shape exists to keep visible.
 */
export type ProjectionRates = { player_id: number } & Record<ProjectionRateField, number | null>

/**
 * What the source assumed about one player's availability.
 *
 * **Not a projection of games played, and not ours.** It exists to be
 * overridden by the availability model, never blended with it.
 *
 * **Do not multiply a rate by `assumed_games_played`.** It is not merely *a*
 * games-played figure: for a season-total source it is the exact divisor the
 * importer used to produce the per-game rates beside it, so the product
 * recovers the source's published seasonal total to within floating-point
 * rounding. That join is the fusion ADR-002 permits only at `expected-games`,
 * which does not exist. Display it; never compute with it.
 *
 * The two fields are separate because they carry different claims and a `null`
 * value alone cannot distinguish them: `assumed_games_played_raw` is the
 * source's own text kept verbatim, so a value that arrived and could not be
 * read as a number is distinguishable from one that never arrived.
 */
export interface SourceGamesPlayedClaim {
  player_id: number
  assumed_games_played: number | null
  assumed_games_played_raw: string | null
}

/**
 * The current *imported* cohort. Not a blend, not a valuation, not a ranking.
 *
 * **Guaranteed on any 200**, or the request is refused instead: `players` and
 * `projections` describe exactly the same `player_id` set, each exactly once,
 * both ordered; and `projections.length ===
 * lineage.projection_import.projection_count`.
 *
 * **`source_games_played_assumptions` is outside that guarantee, and is also
 * deliberately sparse.** Only players whose source stated an assumption appear,
 * and the array may be empty. A missing entry means *the source said nothing*
 * and never zero. The canonical release never digests this table, so a
 * *changed* assumption is not detected — a byte-identical re-import mid-read
 * once served a 200 with an empty array, reporting that Basketball Monster
 * published no assumption when it had published 70 and 78. Closing that class
 * is `release-digests-assumptions`, which is pending, so the screen says the
 * array is less well pinned than the rates rather than presenting both with
 * equal confidence.
 */
export interface CurrentProjections {
  league_id: number
  season: string
  source: string
  lineage: ProjectionLineage
  players: ProjectionPlayer[]
  projections: ProjectionRates[]
  source_games_played_assumptions: SourceGamesPlayedClaim[]
}
