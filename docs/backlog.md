# Build backlog

Generated from the planning session on 2026-08-17. **This is the authoritative task list** - it lived only in a chat session before this, which is exactly what `docs/handoff.md` exists to prevent.

**37 done - 1 blocked - 66 pending - 104 total**

(Counted from the status markers themselves, not carried forward: 104 `###`
headings and 104 markers, 1:1. The line before this entry claimed 37 done / 63
pending against an actual 36 / 64, and that drift predates this work.)

A task is ready when every dependency is done. Update the status line when you finish one.


---

---

## Done

### `absence-splits` - Computing with/without absence splits

- [x] **done**
- **Depends on:** `participation-ledger`

Historical production splits per player pairing when a teammate is absent.
Implemented as descriptive observation-layer evidence, not a causal or
decision-bearing model. `without` requires an explicit observed non-play row.
Missing rows are never inferred: R35 remains unresolved until authoritative,
versioned historical roster intervals and per-game ingestion-completeness
evidence both exist. Complete run cohorts, provenance, sample sizes,
uncertainty, schedule lineage, and volume-aware makes/attempts are persisted.
Sparse splits never become recommendations here; `contingent-value` must pass
the Model gate before using them in a decision.

### `adapter-contract-tests` - Adding contract tests for external adapters

- [x] **done**
- **Depends on:** `ci-pipeline`, `fantrax-private-adapter`, `nba-stats-ingest`

Recorded fixtures and CI contract tests for every external adapter so upstream schema drift from stats.nba.com or /fxpa/req fails loudly in CI rather than at lineup lock.

### `agent-definitions` - Authoring the seven agent definitions

- [x] **done**
- **Depends on:** `governance-docs`

Invocable agent definitions in .github/agents/: architect, data-engineer, quant, backend, frontend, bridge, safety. Each states role, owned scope, explicit non-goals, applicable gates, and escalation triggers. quant is separate from data-engineer because statistical correctness and resilient I/O are different failure modes. safety is separate from bridge because self-approval is what guardrails exist to prevent.

### `backend-skeleton` - Building the FastAPI backend skeleton

- [x] **done**
- **Depends on:** `repo-scaffold`

FastAPI app in backend/ with pydantic settings/config, structured logging, /health endpoint. Wire pytest, ruff, mypy.

### `bridge-capture` - Capturing Fantrax data via the bridge

- [x] **done**
- **Depends on:** `userscript-foundation`

Intercept window.fetch and XMLHttpRequest against /fxpa/req, normalize the payloads and POST them to the backend. Persist raw payloads to bridge_payloads for replay and debugging.

### `bridge-handshake-endpoint` - Adding the backend bridge handshake endpoint

- [x] **done**

The userscript calls POST /api/v1/bridge/handshake and that endpoint validates the shared secret, returns the protocol version, and rejects unauthenticated requests.

### `ci-billing-blocked` - Restoring GitHub Actions (owner-only)

- [x] **done**

The outage began around 12:58Z on 2026-08-17 after a last green run at
12:56Z, when the account-wide private-repository Actions quota was exhausted.
Resolved the same day by the owner making the repository public, deliberately
accepting that the strategy became visible and noting the repository's
portfolio value. Public repositories are exempt from the Actions quota and
receive free secret scanning, push protection, and CodeQL. CI was restored and
PR #3 merged the scheduled live-smoke repair. The incident analysis and
corrected quota diagnosis remain in `docs/governance/OPEN-ci-billing.md`.

### `ci-pipeline` - Setting up the CI pipeline

- [x] **done**
- **Depends on:** `backend-skeleton`, `frontend-skeleton`

GitHub Actions running lint, type-check and tests for both backend and frontend on push and PR.

### `db-foundation` - Establishing the database foundation

- [x] **done**
- **Depends on:** `backend-skeleton`

SQLAlchemy setup with Alembic migrations and session management. Implement core schema: players, player_external_ids, nba_teams, leagues, fantasy_teams, rosters. SQLite for dev, keep Postgres seam clean.

### `deadline-model` - Modelling the league deadline calendar

- [x] **done**
- **Depends on:** `league-settings-ingest`, `schedule-ingest`

Originally scoped to compute every future deadline from the ingested settings: per-player lineup locks at each tipoff, waiver claim cutoffs, waiver clear moments, games-cap thresholds, trade deadline, playoff roster deadlines. `league-settings-ingest` already verified that Fantrax's official `getLeagueInfo` supplies only roster limits and scoring-period boundaries — lineup lock, waivers, trade deadline, playoffs and keeper rules are absent from every source observed so far. Computing any of those from ingested settings would mean inventing them, so this unit delivered the smallest honest contract instead: `league_deadline_calendars`, one immutable, versioned row per league joining an exact `LeagueSettingsSnapshot` with an exact schedule refresh cohort, exposing season bounds and scoring-period boundaries as real timezone-aware instants while carrying lineup lock, waivers, trade deadline, playoffs and keepers forward as explicit unknowns (or their bridge-sourced values, verbatim, when the settings snapshot already has them). Fails closed on missing or mismatched lineage at both derivation and activation time — including when scoring periods themselves are unknown (no `[]` fallback), on out-of-order season/period bounds, and on duplicate period numbers; A→B→A activation cycling is supported by re-deriving over lineage that reverts to prior content. `trade_deadline.deadline_at`/`keepers.deadline_at` are validated offset-aware ISO 8601 at the ingest domain-type boundary, and the read endpoint is loopback-only (bridge-derived values, not a public dashboard fact). A `notification-engine`/`lineup-optimizer` consumer that actually needs a computed lineup-lock instant per game still has no source for one — that gap is real, not an oversight, and stays open until a bridge capture or a new official field closes it. `LeagueDeadlineCalendar` remains the authoritative source-truth calendar; `ScoringPeriod` is now its fail-closed current Eastern-date materialization with separate keyed refresh lineage — see `scoring-period-projection`.

### `draft-format-abstraction` - Abstracting snake and auction draft formats

- [x] **done**
- **Depends on:** `scoring-profiles`

Immutable snake, linear, and auction configuration is derived exclusively from
the current `League.draft_type`, `team_count`, `roster_size`, and
`auction_budget` facts. Unknown formats, missing or nonpositive roster shape,
missing/nonpositive/non-finite auction budgets, and budgets attached to ordered
drafts all fail closed. Snake and linear expose explicit one-indexed
round/pick/team-slot ordering; auction exposes only its stated per-team budget
and roster shape because current league facts do not establish nomination or
bidding order. No historical defaults, market evidence, valuation, price,
inflation, scarcity, recommendation, API, or persistence behavior enters this
Code-gate-only layer.

### `fantrax-official-adapter` - Building the official Fantrax API adapter

- [x] **done**
- **Depends on:** `db-foundation`

Client for fantrax.com/fxea/general/: getPlayerIds, getAdp, getLeagues, getLeagueInfo, getDraftPicks. Handle userSecretId auth where required.

### `fantrax-private-adapter` - Integrating fantraxapi for private league reads

- [x] **done**
- **Depends on:** `fantrax-official-adapter`

Integrate the fantraxapi package (pin the version) for private-league reads via the FANTRAXUSER cookie. Encrypted cookie storage at rest plus a re-login flow on expiry. Sync rosters, standings and matchups.

### `frontend-skeleton` - Building the React frontend skeleton

- [x] **done**
- **Depends on:** `repo-scaffold`

Vite + React + TypeScript in frontend/. Routing, typed API client, layout shell, component conventions.

### `governance-docs` - Writing the governance artifacts

- [x] **done**
- **Depends on:** `repo-create`

AGENTS.md as the single entry point (roster, rules, gates). docs/governance/ownership.md (module to owning agent matrix), gates.md (the four readiness gates), owner-decisions.md (what only the owner decides), risks.md (live risk register covering ToS exposure, upstream fragility, model risk, seasonal deadlines).

### `handoff-log` - Initialising the handoff log

- [x] **done**
- **Depends on:** `repo-create`

Create docs/handoff.md as an append-only log. Seed with current state, locked decisions, and the first entry. Every agent finishing work appends: what changed, what is now true, what it could not verify and why (mandatory field), and who is next.

### `injury-report-historical-backfill` - Bounded, resumable operator workflow for backfilling historical NBA injury reports

- [x] **done**
- **Depends on:** `injury-report-ingest`

Bounded, resumable operator tool (`hoops_gm.ingest.injury_report.backfill`) that fetches and imports historical NBA official injury-report captures from the NBA's archived CDN into durable per-game evidence, so `injury-status-conversion` has more than the single committed fixture to build against once a genuinely representative cohort exists. Candidate report timestamps are derived per calendar date from exact ingested `nba_games.tipoff_utc` values and the documented publication cadence: `evening_before` (17:30 ET the day prior) in both URL eras, plus an era-conditional game-day strategy — a single fixed 13:00 ET guess pre-2025-12-22 (safe there because the legacy URL truncates to the hour and the masthead check tolerates 45 minutes of drift), and four bounded, tip-off-anchored, 15-minute-grid-aligned offsets (150/90/45/15 minutes before the date's earliest tip-off, floored to the source's own quarter-hour marks so a non-grid-aligned tip-off like 19:10 ET does not push every candidate off-grid) from 2025-12-22 onward, where the URL is an exact-minute match with no drift tolerance. No lookahead is enforced twice (plan time and read time). The natural key (`report_timestamp, team_raw, player_name_raw, game_date`), checkpoint identity that includes the exact resolved timestamp (not just date+anchor, so a corrected tip-off cannot silently reuse a stale candidate's settled status), and two fail-closed gates — `enforce_full_tipoff_coverage` and an independent `enforce_expected_game_coverage` against the official `LeagueGameFinder` schedule (migrations `0013`/`0014`) — prevent a same-player back-to-back split across two game dates from colliding, and prevent running against a requested or incidentally-ingested game scope (e.g. 22 of 527 games) as though it were cohort-ready. Reuses the existing `InjuryReportClient`/parser/importer — two schema changes (natural key; evidence schema version). Checkpointed (cache-independent) and idempotent so an interrupted run resumes, including across a mid-write import/commit failure and mid-flight tip-off correction. A 403 is never checkpointed as settled — recorded under its own permanent `"forbidden"` status and retried indefinitely across every future run, regardless of streak length or process boundary; a streak still raises an early-abort optimization, but checkpoint correctness never depends on it. Durable per-run `CoverageReport` evidence (persisted even on an aborted run, keyed on the exact requested timestamp so a corrected tip-off cannot silently reuse stale coverage, and bound to an exact evidence schema version so an incompatible legacy, unrecognized-future, or malformed-current artifact is quarantined for read-only classification but makes persistence fail loudly without rewriting the original bytes) is classified against the database's *current* tip-off and game identity — re-read fresh on every `coverage_for_games` call, never a possibly-stale caller snapshot — and matched by each candidate's stable NBA game identifier (`applicable_nba_game_ids`), never a reusable surrogate database id; coverage evidence recorded before this stable-identity fix is stamped a legacy coverage-schema version and excluded from `submitted_zero_listed` classification entirely rather than trusted against whichever game holds its old surrogate id today. An unresolved (unattributable) report row vetoes a clean `submitted_zero_listed` claim only for the same-date games whose current tip-off is strictly after that row's own report timestamp — never date-wide — and this `unresolved_evidence` outcome outranks the coarser `legacy_excluded` when both apply to the same game. A full `exclusion_cascade` denominator breakdown (expected → ingested-with-tipoff → candidate-scoped → attempted → recovered → resolved-game → resolved-player → status-listed, split by legacy vs. trusted evidence schema so a pre-fix row is never silently counted as trusted), and a network-free `observations` CLI command expose per-game outcome (`observed` / `no_candidate_coverage` / `not_yet_submitted_only` / `submitted_zero_listed` / `legacy_excluded` / `missing_tipoff`) so the falsifiable coverage gap is checkable per game and per cascade stage, not asserted as an aggregate rate. Rows written before the natural-key/versioning fix are stamped a legacy evidence-schema version and excluded from every trust-dependent cascade stage and canonical-observation query by default. `CanonicalPregameObservation.lead_time_minutes` is the realized per-game `tipoff_utc - report_timestamp`, distinct from a `ReportCandidate`'s `anchor_offset_minutes` (the anchor's shared, intended offset for the date) — the two were conflated before round-5 review and are now separately named and computed. `ExpectedGameCoverage`/`CoverageReport` are bound to the exact requested season/season_type/date range and rejected if mismatched. Coverage classification also forces a fresh (`populate_existing`) re-read of each game's tip-off inside `coverage_for_games`'s own read scope, closing a residual ORM identity-map staleness gap where an already-loaded session object could otherwise retain a pre-correction value even after a separate session's committed fix; rejects an *unrecognized future* `evidence_schema_version` exactly like a legacy one (not merely anything below current); rejects evidence whose `report_date` no longer matches a rescheduled game's current `game_date`, or whose `CoverageReport.season`/`season_type` does not match the game's current schedule scope; emits a retracted-tip-off game exactly once (not duplicated across the ready/newly-missing paths); and keeps a resolved-but-currently-out-of-scope `game_id` (e.g. its own game's tip-off was itself retracted) bound to that one game rather than fanning the conservative unattributable-row veto onto unrelated same-date games. `coverage_for_games` now reads every classification-relevant game field (stable id, local id, date, tip-off, season, season_type, both teams' abbreviations) in exactly one `SELECT`, deriving `select_canonical_pregame_observations`'s tip-off lookups from that same snapshot rather than a second, separately-timed query a schedule correction could land between — proven immune to a real mid-call commit via a `before_cursor_execute` engine hook against a genuine second database connection. Persisted coverage is now bound to an exact evidence schema version (bumped to 3) and each candidate's own self-described `season`/`season_type`, not merely per-game schedule scope: a whole-file scope mismatch against the current request raises rather than silently rewriting the file under the wrong label, an individual out-of-scope candidate is excluded even inside an otherwise-matching file, and the merge key itself now also carries the canonical masthead timestamp and applicable stable game-id set so two genuinely distinct fetched records sharing every other field still coexist rather than one silently overwriting the other. Checkpoint settlement identity now also carries the settled scope's stable NBA game ids, so a genuine `--allow-missing-tipoff` partial day — where a later-ingested same-day game's tip-off is *later* than the date's already-known earliest and therefore never changes the near-tip candidate's resolved instant or checkpoint key — is correctly reprocessed on resume (idempotently) rather than trusted forever under the narrower, stale settled scope.

**What "done" means here, precisely — and what it does not:** this item closes the *bounded, resumable operator workflow* (the tool, its fail-closed gates, its checkpoint/coverage durability and idempotency, and its test coverage) as scoped and reviewed. It does **not** mean a representative, conversion-ready historical cohort has been populated against the live archive. Per `docs/handoff.md`, the only live-archive run performed against this tool produced a deliberately small, non-representative sample (22 of 527 games, spanning a handful of dates) used to validate the tool's own mechanics, not to seed `injury-status-conversion`. Populating an actual multi-date, multi-game cohort large and diverse enough to be evidence-ready for that downstream item is separate, unstarted work — running this tool at scale against the live archive, within its own rate-limit and request-budget bounds — and is now tracked as its own explicit backlog item, `injury-conversion-cohort-population`, precisely so `injury-status-conversion` cannot appear structurally ready merely because every dependency it lists here is done. `injury-status-conversion` remains explicitly blocked until that cohort exists and is independently reviewed.


### `injury-report-ingest` - Ingesting NBA official injury reports

- [x] **done**
- **Depends on:** `player-identity`

Ingest the NBA official injury report (day-before release plus game-day updates) with full status history per player per game: OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, AVAILABLE.

### `league-settings-ingest` - Ingesting full league settings and rules

- [x] **done**
- **Depends on:** `db-foundation`, `fantrax-official-adapter`

Versioned, source-attributed settings snapshots covering lineup locks, waivers, games caps, roster/IR limits, scoring periods, trade deadlines, playoffs, and keeper rules. Verified live that official `getLeagueInfo` supplies roster and scoring-period configuration but omits the other rule families; omissions remain explicit unknowns and may be filled only by lower-priority read-only bridge evidence. Historical 2025-26 values never default 2026-27 rules, and a season-coherence guard rejects importing the observed 2025 payload into a 2026-27 league.

### `nba-stats-ingest` - Ingesting NBA stats via nba_api

- [x] **done**
- **Depends on:** `db-foundation`

nba_api adapter with ~1 req/s throttling, required stats.nba.com headers, retry and caching. Use V3 endpoints. Backfill teams, games, player game logs, plus inactive lists and DNP reasons, across multiple seasons for availability model training.

### `participation-ledger` - Building the player participation ledger

- [x] **done**
- **Depends on:** `nba-stats-ingest`, `player-identity`

Historical per-player, per-game participation reconstructed from box scores and inactive lists, with normalized reason codes: played, DNP-CD, injury (with body part), rest/load management, personal, suspension, G-League, inactive. Multi-season for model training.

### `player-identity` - Resolving cross-source player identity

- [x] **done**
- **Depends on:** `fantrax-official-adapter`, `nba-stats-ingest`

Crosswalk resolver joining Fantrax IDs, NBA IDs and projection-CSV name strings. Fantrax exposes no NBA.com player id, so there is no anchor pair; matches begin with normalized name + team + position and retain per-field three-valued evidence, confidence, and manual overrides. Ship an unmatched-players report and a manual-override UI. Highest-risk foundational item - needs its own test suite.

### `playoff-schedule` - Analysing fantasy playoff week schedules

- [x] **done**
- **Depends on:** `schedule-density`

Game counts for the fantasy playoff weeks specifically, surfaced during the draft and at the trade deadline rather than discovered in March. `playoff_scheduled_game_counts` exposes a league-scoped, ordered scoring-period x active-NBA-team grid from `scoring_periods.is_playoff` and `team_schedule`, including explicit zero-game rows, one required schedule-refresh cohort on every row, and no duplicate week table. Schedule lineage currently versions the NBA calendar only: `league-settings-ingest` now versions source settings and `deadline-model` versions their authoritative calendar, but `scoring-period-projection` must project and cascade that lineage into `ScoringPeriod` and this count grid before consumers may treat a changed playoff flag or boundary as invalidating an older result. This first pass is calendar fact only (game counts); a value-weighted second pass happens once `strength-of-schedule` exists in Phase 5 (ADR-011) — do not compute opponent-quality-weighted schedule strength here.

### `refresh-lineage` - Recording schedule/projection/model refresh provenance

- [x] **done**
- **Depends on:** `schedule-ingest`

A small `refresh_runs` registry and `/api/v1/lineage` contract recording when a schedule, projection, or model artifact was last (re)computed at a given version, and letting a downstream consumer check whether its claimed `schedule_version`/`model_version`/`projection_version` cohort is still current, stale, or unregistered. `import_schedule` stamps a content-fingerprinted schedule refresh as a side effect. Deliberately does not compute anything the registry describes — not SOS convergence (ADR-011), not p(play), not a projection blend — it only makes an existing versioning claim (ADR-009's `model_version`/`schedule_version` columns on `opponent_context`/`off_night_slates`) mechanically checkable. `quant` owns stamping its own rows consistently with what this reports as current and owns registering projection/model refreshes when those exist; this item does not modify the already-merged `schedule_context` schema.

### `reliability-metrics` - Building player reliability and consistency metrics

- [x] **done**
- **Depends on:** `participation-ledger`, `schedule-context`, `schedule-density`

V1 is the smallest scorecard current data can support honestly. It exposes
directly observed play/non-play evidence, a monthly observed trend, and observed
B2B sit evidence with counts and `incomplete_r35` coverage; missing and unknown
rows never become absences. Played-game production remains separate and reports
minutes CV, per-category sample SD, empirical p20/p80, and volume-weighted FG/FT
impact. A chronological three-season study rejected player-level
blowout-minutes suppression because calibration reversed sign in one bin, and no
composite grade has a defensible target, so neither field exists at runtime.
Results are computed on demand with schedule/source/derivation lineage; no
schema, API, or UI was added.

### `repo-create` - Creating the repo and pushing the handoff commit

- [x] **done**

Create SR2501/hoops-gm on GitHub and push the initial commit carrying docs/plan.md plus all governance artifacts, so nothing important lives only in a chat transcript. This is the chat-to-repo handoff.

### `repo-scaffold` - Creating the hoops-gm repo and monorepo layout

- [x] **done**
- **Depends on:** `agent-definitions`, `handoff-log`, `seed-adrs`

Create SR2501/hoops-gm on GitHub. Set up monorepo: backend/, frontend/, userscript/, docs/, docker-compose.yml, .github/workflows/. Add licence, README, .gitignore, .env.example.

### `schedule-context` - Building opponent and slate context

- [x] **done**
- **Depends on:** `nba-stats-ingest`, `schedule-ingest`

Versioned off-night slate percentiles, opponent pace, volume-correct
per-category defensive profiles, and held-out-calibrated blowout likelihood.
Descriptive schedule/box-score facts are separated from the decision-bearing
probability. Every output binds schedule/source/model cohorts and rejects stale
or mismatched currentness. The released model is loaded only from its packaged,
gate-passed artifact; training and holdout sources have separate fingerprints.
Regular-season context rejects partial team-minute box scores and refuses runs
below the persisted 95% fixture-coverage threshold. Garbage-time minutes
suppression remains null because
blowout calibration alone does not validate its magnitude; it belongs to
`reliability-metrics` once player-minutes evidence exists.

### `schedule-density` - Modelling schedule density

- [x] **done**
- **Depends on:** `schedule-ingest`

Back-to-backs, 3-in-4 / 4-in-5 / 4-in-6 stretches, rest-day differentials, road-trip length and structure. Direct input to the availability model.

### `schedule-grid-early` - Exposing the current raw schedule grid

- [x] **done**
- **Depends on:** `scoring-period-projection`

Loopback-only `GET /api/v1/leagues/{league_id}/schedule-grid/current` over
`scheduled_game_counts`: the complete ordered active-team x scoring-period raw
count matrix including explicit zeroes, plus the `teams` and `periods` a
browser screen needs to label its own rows and columns, plus the exact current
NBA schedule, scoring-period projection, deadline-calendar and
settings-snapshot lineage. `teams` and `periods` are read inside the same
transaction and lock scope as `counts`, so a screen can never render one
lineage's numbers against another lineage's headers. No classifications,
rankings, recommendations or schedule recomputation cross this boundary
(ADR-009).

Completeness evidence comes from `db/lineage.py`'s `verify_refresh` and
`schedule_completeness` — the canonical verifier the producer stamps against —
never from a second reader in the route. Missing, stale, unverifiable or
self-contradicting evidence, a wholly zero grid, an empty grid, a non-loopback
caller and an unknown league each fail closed with a typed code in
`ErrorResponse.error` and no partial data. (`X-Bridge-Error` is the internal
route-to-handler transport, not a response header: `api/app.py` consumes it and
returns the code in the body — verified, not assumed.)
`schedule_grid_incomplete_evidence` is a **family**: some members mean "the
refresh cannot state what it imported", others mean "it states what it imported
perfectly well, but that is not the cohort this grid counts". A consumer
rendering one fixed sentence for the code will be wrong for the second kind, and
must not substring-match `detail`, which is free-form prose rather than a
contract surface. Splitting the code or adding a machine-readable discriminator
is an open `architect` + `frontend` decision.

Operational, not merely safe: `python -m hoops_gm.dev.seed_schedule_grid`
brings a local database to a verified state offline from the committed NBA
fixtures, through the production importers, and the endpoint returns a real
200 against it (see `backend/README.md`). The first attempt at this item was
fail-closed but permanently unavailable, which is why the seed path is part of
the deliverable rather than a convenience.

### `schedule-ingest` - Ingesting the NBA season schedule

- [x] **done**
- **Depends on:** `nba-stats-ingest`

Season schedule ingestion, fantasy week definitions, and per-week scheduled game counts per team. Foundation for schedule density and the availability model.

### `scoring-period-projection` - Deriving `ScoringPeriod` from the active deadline calendar

- [x] **done**
- **Depends on:** `deadline-model`, `schedule-density`

`LeagueDeadlineCalendar` remains the immutable, versioned authority.
`project_scoring_periods` is the sole production writer for the older
`ScoringPeriod` table: it validates the active calendar against the current
league-settings snapshot and keyed NBA schedule refresh, rejects unknown
playoff evidence, converts every boundary to `America/New_York` before taking
its inclusive date, and records a deterministic keyed refresh containing the
exact settings, calendar, schedule, and projected-period cohorts. Changed
materializations replace only unreferenced rows; matchup references fail closed,
while immutable calendars and refresh summaries preserve replacement history.
`scheduled_game_counts` and `playoff_scheduled_game_counts` now validate that
both the materialized rows and projection lineage match current inputs before
returning counts, and each result carries all four cohort identifiers and
versions. The existing schema supports this contract honestly, so no migration
or reserved revision number was used. This remains calendar fact only: no
opponent-quality, availability, or model math is added.

### `scoring-profiles` - Abstracting scoring profiles for multi-format support

- [x] **done**
- **Depends on:** `db-foundation`, `league-settings-ingest`

Scoring-profile abstraction so points and roto formats can slot in later without rewriting the valuation engine. H2H 9-cat is the first concrete profile. Implemented: `league_scoring_profiles`/`league_scoring_categories` (already scaffolded in `db-foundation`) gained `settings_snapshot_id` (source attribution to a `LeagueSettingsSnapshot` version) and `active_league_id` (a nullable, uniquely-constrained self-FK replacing the old `is_active` boolean, enforcing "at most one active profile per league" as a database constraint with no dialect branching -- see `db/models/league.py`, migration `0012`). `LeagueSettingsDocument` (`ingest/league_settings.py`) now carries `scoring_type`/`scoring_categories` as first-class sourced fields (document `schema_version` 2; migration `0012` backfills every pre-existing snapshot row with an explicit, honestly-evidenced *absent* observation for both, never a guess), parsed by the same `getLeagueInfo` importer that produces roster limits and scoring periods, so a scoring profile's lineage is genuinely tied to a specific settings snapshot rather than an independently-supplied argument. `hoops_gm.scoring.profiles.build_scoring_profile` derives a profile exclusively from a league's current settings snapshot -- no caller-supplied category list -- mapping on the Fantrax `code` (fixture-verified, fail closed on unmapped/duplicate/non-unit-weight/malformed-shape categories) to a canonical 9-category vocabulary (AST, BLK, PTS, REB, ST, 3PTM, TO, FG%, FT%); percentage categories are stored as made/attempted component pairs, never a raw percentage. `scoring_type` is derived from the snapshot's own discriminator via a verified mapping, never defaulted, with evidence citing whichever of the two possible source fields actually won under official-priority precedence. Content-fingerprint idempotency means re-deriving from an unchanged snapshot returns the existing profile row unchanged; reactivating a version whose content matches the *current* snapshot after cycling through another (A -> B -> A) mints a new version carrying A's content but the current snapshot's own FK -- never repointing an existing row's snapshot reference, which would rewrite historical lineage. Activation (`activate_scoring_profile_version`) revalidates exact league binding, current-snapshot freshness, and a non-empty category set before touching whatever profile is active, and is a separate, explicit, two-phase deactivate-then-activate step. A production seam (`derive_scoring_profile` / `scoring-profile` CLI subcommand) runs this end to end from an ingested settings snapshot to an explicit, opt-in activation. No rankings/AAV/market evidence enter this layer (ADR-008); no projection, availability or valuation math is computed here (ADR-002 stays intact -- this is configuration, not production or `p(play)`). Model gate does not apply: nothing decision-bearing is computed or backtested, only Code and Adapter gates. See `docs/handoff.md` for the full entry, including the remediation rounds that made the settings snapshot the sole source of scoring lineage, fixed the A -> B -> A activation dead-end, and backfilled schema v2 for pre-existing snapshots.

### `seed-adrs` - Seeding ADRs from decisions already made

- [x] **done**
- **Depends on:** `governance-docs`

Write ADR-001 to ADR-007 as Proposed: local-first with Postgres seam; separate production from expected games played; G-score default for H2H; Fantrax read via API and write only via browser bridge; supervised-by-default automation; adapters isolated behind contract tests; availability modelled before valuation. Agents may not mark their own ADRs Accepted.

### `userscript-foundation` - Building the Tampermonkey userscript foundation

- [x] **done**
- **Depends on:** `backend-skeleton`

Userscript build pipeline, @match rules for fantrax.com, shared-secret handshake with the backend, and GM_xmlhttpRequest transport to localhost (bypasses CORS and page CSP).

---

## Blocked

### `blind-mocks` - Running blind mocks when auction lobbies open

- [ ] **blocked**

EXTERNALLY BLOCKED 2026-08-17: the owner found no site currently offering live mocks, including auction mocks. Do not manufacture simulated clearing prices and call them market evidence. When auction lobbies open, run observation-only mocks without this tool and capture each using docs/mocks/TEMPLATE.md. They remain the uncontaminated control group for R38, the counterfactual baseline for measuring whether the tool helps, and the empirical AAV evidence R37 needs. League configuration is mandatory on every capture.

---

## Pending

### `aav-blending` - Blending AAV across sources with per-source weights

- [ ] **pending**
- **Depends on:** `aav-empirical`, `aav-source`, `layer-purity`

AUCTION CRITICAL (R37). Weighted blend of seed AAV sources plus the empirical corpus source, reusing projection-blending machinery rather than a second implementation. Versioned so every dollar value traces to its inputs. Manual per-source weight overrides supported, since the owner has priors about which sources are good.

### `aav-calibration` - Scoring AAV sources against observed clearing prices

- [ ] **pending**
- **Depends on:** `aav-blending`, `aav-empirical`

AUCTION CRITICAL (R37/R38). Once the corpus is large enough, measure each seed source error against what players actually cleared for, and re-weight on evidence rather than assertion. Expect the empirical source weight to rise as the corpus grows and seed weights to differentiate sharply. GUARD AGAINST CIRCULARITY (R38): mock participants price from the same public AAV we seed from, so early clearing prices echo the seeds rather than independently testing them, and if we bid using our own model the corpus is contaminated with our own output. Record per mock whether our model drove our bidding; treat model-driven mocks as separate evidence; run early mocks observation-only.

### `aav-empirical` - Deriving empirical AAV from the mock corpus

- [ ] **pending**
- **Depends on:** `blind-mocks`, `draft-format-abstraction`, `mock-ingestion`

AUCTION CRITICAL (R37, track B). Every auction mock yields real clearing prices for real players. Aggregate into an AAV source in its own right - unlike published seeds it reflects THIS format and player pool. Also yields observed inflation curves, which is a separate quantity from baseline AAV and feeds auction-inflation directly.

### `aav-source` - Sourcing and importing seed auction values

- [ ] **pending**
- **Depends on:** `csv-importer`, `fantrax-official-adapter`

AUCTION CRITICAL (R37, track A). Import published AAV from whatever sources the owner finds, through the generic CSV importer rather than a bespoke path. Each source is a row in projection_sources with its own weight. MUST normalise to this league budget pool, team count and roster size before anything downstream uses it (R39) - a $200/12-team/13-spot league produces entirely different dollar values than $100/10-team/10-spot, and a raw import is silently wrong. Capture each source assumed scoring format too; most published AAV targets points leagues or default 9-cat.

### `action-protocol` - Defining the automation action protocol

- [ ] **pending**
- **Depends on:** `bridge-overlay`

Typed action schema, backend command queue, userscript-side executor, and result reporting back to the backend.

### `adherence-experiment` - Measuring list adherence across mocks

- [ ] **pending**
- **Depends on:** `blind-mocks`, `list-perturbation`, `mock-ingestion`

Owner will follow the list, so list reliability is the product. Measure adherence per decision (~13 per auction, 10 mocks = ~130 observations). Track overall rate and where deviation clusters by position, price tier and draft stage. Separate systematic deviation (bias to guard against) from situational deviation (real information the model lacks, therefore a feature). Cannot measure whether a deviation was correct - mocks do not play out and scoring against the list own valuation is circular.

### `auction-budget-manager` - Building the auction budget manager

- [ ] **pending**
- **Depends on:** `auction-values`, `draft-tracker`

AUCTION IS THE CONFIRMED FORMAT (2026-08-17) - this is now critical path, not insurance. Max bid computed as budget minus the $1-per-unfilled-slot reserve, recomputed continuously. Budget burn rate tracked against roster construction shape (stars-and-scrubs vs balanced) so the shape is deliberate rather than accidental.

### `auction-inflation` - Building the live auction inflation tracker

- [ ] **pending**
- **Depends on:** `aav-empirical`, `aav-source`, `auction-values`, `draft-tracker`

AUCTION IS THE CONFIRMED FORMAT (2026-08-17) - this is now critical path, not insurance. Track inflation continuously as money leaves the board and restate prices for the remaining pool. If the top tier goes over value, everything after deflates. This is the single largest edge available in an auction and most managers only eyeball it.

### `auction-nomination` - Building the nomination strategy engine

- [ ] **pending**
- **Depends on:** `auction-budget-manager`, `auction-inflation`

AUCTION IS THE CONFIRMED FORMAT (2026-08-17) - this is now critical path, not insurance. Recommend who to nominate and when: drain opponent budgets on players you do not want while they still have money, and surface your targets once opponents are budget-constrained.

### `auction-values` - Deriving auction dollar values

- [ ] **pending**
- **Depends on:** `aav-blending`, `aav-source`, `draft-format-abstraction`, `risk-adjusted-valuation`

AUCTION IS THE CONFIRMED FORMAT (2026-08-17) - this is now critical path, not insurance. Convert risk-adjusted G-score to dollar values via value over replacement scaled to the league total budget pool, accounting for roster size and the minimum-bid reserve.

### `automation-audit` - Building the automation audit log

- [ ] **pending**
- **Depends on:** `action-protocol`

Persist every planned and executed action with timestamp, trigger, inputs, recommendation and outcome. Review UI so runs can be inspected and diffed after the fact.

### `automation-guardrails` - Implementing automation guardrails

- [ ] **pending**
- **Depends on:** `action-protocol`

Mandatory guardrails for all write actions: kill switch (incl. auto-halt on backend disconnect), dry-run default for new action types, roster/position/IR/lock validity precheck, scope caps, confidence floor with escalation, availability-freshness check (never auto-set on stale injury data), and human-paced execution.

### `autonomous-mode` - Implementing opt-in autonomous mode

- [ ] **pending**
- **Depends on:** `supervised-mode`

Explicit per-session opt-in allowing the userscript to action decisions directly - N draft rounds or a lineup set - bounded by every guardrail. Isolated in one swappable module.

### `availability-backtest` - Backtesting the availability model

- [ ] **pending**
- **Depends on:** `availability-model`

Backtest harness scoring the availability model against held-out seasons. Scores calibration explicitly, not just accuracy - a well-calibrated 70% is more useful for lineup decisions than an overconfident model with a better raw hit rate.

### `availability-model` - Building the per-game availability model

- [ ] **pending**
- **Depends on:** `injury-status-conversion`, `participation-ledger`, `schedule-density`

Per-player p(play) for each scheduled game, conditioned on B2B/density, rest days, road trips, age, career and recent minutes load, injury history and body part recurrence, current report status (via its conversion rate), and team playoff/tanking situation. Aggregates to expected games over any window (RoS, fantasy week, playoff weeks). Persists driver features for explainability.

### `baseline-model` - Building an in-house projection model

- [ ] **pending**
- **Depends on:** `nba-stats-ingest`, `projection-blending`

Own per-game production model from historical logs, accounting for minutes,
usage and role. Exposed as another source inside the blending layer. Its
experiments must follow the
[`projection experiment sequestration protocol`](governance/projection-experiment-protocol.md):
the model worker receives only independently released immutable packages,
freezes the experiment before held-out outcomes are unblinded, and may never use
mock outcomes as production or availability evidence.

### `behavioural-baseline` - Modelling the owner own drafting tendencies

- [ ] **pending**
- **Depends on:** `adherence-experiment`, `blind-mocks`, `mock-ingestion`

From the blind mock captures, identify systematic tendencies worth flagging live: overpaying at particular positions, chasing after a loss, freezing, finishing with budget unspent, neglecting a category until too late. A tool that says you are bidding 8 dollars over your own model on centers, and you did this in three of the last five mocks, is more useful than one that only prices players. Requires enough captures to distinguish tendency from noise.

### `bias-guardrails` - Warning on known bias patterns during the draft

- [ ] **pending**
- **Depends on:** `adherence-experiment`, `behavioural-baseline`, `overlay-auction-panel`

Once adherence data shows systematic tendencies, surface them live in the overlay - for example that the current bid is well over list on a position the owner has consistently overpaid for across prior mocks. Requires enough captures to distinguish tendency from noise. Read-only advisory, not a block.

### `bridge-overlay` - Building the in-page recommendation overlay

- [ ] **pending**
- **Depends on:** `punt-builds`, `userscript-foundation`

Shadow-DOM overlay rendering hoops-gm recommendations directly on Fantrax pages, so decisions surface where they are made.

### `contingent-value` - Building the contingent value graph

- [ ] **pending**
- **Depends on:** `absence-splits`

Usage-redistribution graph: when player X sits, who gains, in which categories, and by how much. Powers stock movement, waiver targeting, and draft handcuff awareness.

### `csv-importer` - Building the generic projection CSV importer

- [x] **done**
- **Depends on:** `player-identity`

Reusable, versioned CSV importer with exact-byte lineage, immutable
source-season profiles, fail-closed identity resolution and exact-output
reconciliation. Basketball Monster's 2026-27 contract is verified against
private paid-export evidence whose hashes are committed without its rows or
path; the committed fixture preserves the exact headers/order/dialect with
synthetic values. The source's season totals are divided by its separately
persisted `games` assumption, with PTS and REB derivations recorded explicitly.
FantasyPros and Hashtag remain unverified parse-preview examples and cannot
write production until they independently earn source evidence. Blending and
expected-games fusion remain separate tasks.

### `dashboard-evidence-views` - Building the dashboard evidence views

- [ ] **pending**
- **Depends on:** `draft-recommender`, `frontend-skeleton`, `risk-adjusted-valuation`

The reasoning behind every overlay recommendation: full category math, punt-fit breakdown, durability and shutdown detail, contingent-value implications, schedule context, and live inflation state in auction. The overlay shows the decision, the dashboard shows why.

### `deployment` - Preparing deployment and the Postgres migration path

- [ ] **pending**
- **Depends on:** `multi-user`

Docker Compose setup, SQLite to Postgres migration path, and a backup/restore runbook.

### `draft-day-synthesis` - Building the draft-morning final synthesis

- [ ] **pending**
- **Depends on:** `auction-values`, `layer-purity`, `risk-adjusted-valuation`

One versioned, reproducible run on the morning of 18 October producing our own rankings and dollar values end-to-end from our own projections and availability, with no external ranking anywhere in the lineage (ADR-008). The version is recorded so it is always knowable exactly which numbers we walked in with. Must be rehearsed during the mock window, not attempted for the first time on the day.

### `draft-recommender` - Building the draft recommendation engine

- [ ] **pending**
- **Depends on:** `contingent-value`, `draft-format-abstraction`, `draft-tracker`, `playoff-schedule`, `punt-builds`, `schedule-ingest`, `shutdown-risk`

DEPRIORITISED - league confirmed auction on 2026-08-17. Snake is retained for multi-format support and for ingesting snake mock corpora, but is no longer a draft-day deliverable. Snake-format recommendations: value over replacement against pick slot, ADP value and reach, positional scarcity, tier cliffs, with durability, shutdown and handcuff flags from the availability engine. Per ADR-012, also exposes per-week game-count distribution (from `schedule-ingest`, not a model) as a first-class schedule-volume input: two-game/five-game weeks, front/back-loaded schedules, and roster fit, distinct from `strength-of-schedule`'s opponent-quality weighting.

### `draft-simulator` - Building the mock draft simulator

- [ ] **pending**
- **Depends on:** `auction-nomination`, `draft-recommender`, `opponent-calibration`

Mock drafts for both snake and auction against calibrated opponent models, including durability-weighted and stars-and-scrubs strategies. Used to pressure-test builds before the real thing.

### `draft-tracker` - Building the live draft tracker

- [ ] **pending**
- **Depends on:** `bridge-capture`, `draft-format-abstraction`, `fantrax-official-adapter`, `frontend-skeleton`

Live draft state for both snake and auction: pick-by-pick board or nomination board, plus roster construction view. Fed by the bridge and official API.

### `secret-scan-fixture-isolation` - Making the secret scan safe to run concurrently

- [ ] **pending**
- **Depends on:** `backend-skeleton`

`backend/tests/test_secret_scan.py` plants a fake credential **into the real
committed fixture `backend/tests/fixtures/nba_static_teams.json`** and restores
it in a `finally`. Two consequences, both observed rather than theorised. Any
concurrent reader of that fixture — the schedule-grid seed, `test_importers.py`,
a second pytest process in the same worktree — can read it mid-mutation and fail
with a `JSONDecodeError` that looks like flakiness in an unrelated test; this
cost one lane an hour and produced two successive wrong explanations before an
independent reviewer caught the failure in the act. And a hard kill inside that
window leaves a credential-shaped string sitting in a tracked fixture. Copy the
fixture to `tmp_path` and plant there, or point the scanner at a temporary tree.

### `error-code-observability` - Logging the error code, not just the status

- [ ] **pending**
- **Depends on:** `backend-skeleton`

`api/middleware.py` logs `status_code` and `app.py`'s HTTP exception handler
logs nothing, so every typed refusal reads identically in the log. The schedule
grid made this concrete: four of its five refusals are `409`, and
`schedule_grid_not_current` and `schedule_grid_incomplete_evidence` demand
different operator actions — re-import versus a refresh that can never populate
the contract — yet an operator reading logs cannot tell them apart. Log the
`ErrorResponse.error` code alongside the status. App-wide and pre-existing;
surfaced here because this is the first route whose codes carry distinct
operator actions.

### `expected-games` - Fusing production with expected games played

- [ ] **pending**
- **Depends on:** `availability-model`, `layer-purity`, `projection-blending`

Combine per-game production projections with the availability model expected games. The seam that makes durability visible in every downstream number and prevents systematically overvaluing fragile stars.

### `games-cap-tracker` - Tracking games-played caps against the schedule

- [ ] **pending**
- **Depends on:** `league-settings-ingest`, `schedule-density`

Where the league caps games per week or per position, burning the cap early strands roster spots later. Track games used and remaining against the cap alongside the schedule grid, so streaming and lineup decisions account for it rather than discovering the cap after it binds.

### `gscore-engine` - Implementing the G-score engine for H2H

- [ ] **pending**
- **Depends on:** `zscore-engine`

G-score per arXiv 2307.02188, absorbing both production variance and availability variance into the same framework. Default valuation scheme for H2H leagues.

### `injury-conversion-cohort-population` - Populating a representative historical injury-report/participation cohort

- [x] **done** - Regenerated 2026-08-20 from corrected sources after PR #37 invalidated the 2026-08-19 artifact, and independently reviewed at exact head for evidence correctness, code correctness and extract privacy. The corrected bounded cohort is 173 games across 26 game dates in `2025-12-08..2026-01-04`, including `0022501229` and `0022501230` on 2025-12-13 and their 39 production logs. Every count and fingerprint was recomputed from corrected sources; nothing was carried forward. The manifest is the deterministic output of a committed generator (`hoops_gm.ingest.injury_report.cohort_evidence`) rather than hand-assembled, and refuses to emit unless four views of the window name exactly the same games as sets — with an explicit published map of which views are actually independent of the ingest path, because only `ScheduleLeagueV2` is. Review withdrew the previous cohort's positional-diversity claim: `BoxScoreTraditionalV3.position` is emitted only for the five starters, always as `F,F,C,G,G`, so positional representativeness is **not** established by either cohort. The 2026-08-19 artifact remains preserved in history and stays non-consumable.
- **Depends on:** `injury-report-historical-backfill`, `participation-ledger`

Run the bounded, resumable `injury-report-historical-backfill` operator tool at scale against the live NBA official injury-report archive — within its own rate-limit and request-budget bounds — to populate an actual multi-date, multi-game historical cohort of canonical pregame observations joined against the participation ledger's realized outcomes: large and diverse enough (multiple teams, positions, report statuses, and a genuine calendar span, not a handful of adjacent dates) to be evidence-ready for `injury-status-conversion`. Tracked as its own explicit dependency, separate from the operator tool itself, precisely because "the tool exists and passes its tests" and "a representative cohort has been populated with it" are different claims — conflating them is what let `injury-status-conversion` appear structurally ready (every backlog dependency it listed marked done) while the cohort it actually needs did not exist. The only live-archive run performed to date produced a deliberately small, non-representative sample (22 of 527 games, spanning a handful of dates) used to validate the backfill tool's own mechanics, not to seed this item. Done only once that representative cohort exists, is committed as real fetched evidence (never fabricated or extrapolated), and has been independently reviewed for actual representativeness — team/date/status-code coverage, no lookahead, and no selection bias toward easy-to-fetch dates.

### `injury-status-conversion` - Modelling injury status conversion rates

- [ ] **pending**
- **Depends on:** `injury-report-ingest`, `injury-report-historical-backfill`, `injury-conversion-cohort-population`, `participation-ledger`

Empirical conversion of report status to actual play rate, segmented by team, player and game context. QUESTIONABLE is not a coin flip and varies meaningfully by source - this rate is itself a modelled quantity.

### `layer-purity` - Enforcing layer purity in the schema and tests

- [ ] **pending**
- **Depends on:** `db-foundation`, `projection-blending`

ADR-008 / R41. Every stored quantity records which layer it belongs to (observation, projection, availability, valuation, terminal). A test rejects any flow from a higher layer into a lower one - make it inexpressible rather than merely documented, the same pattern used for the Postgres seam. Specifically: no ranking, AAV or composite value may be an input to any earlier layer at any weight. External aggregates may only appear on the comparison side of model-vs-market, never in a blend.

### `lineup-autoset` - Implementing scheduled lineup auto-set

- [ ] **pending**
- **Depends on:** `automation-guardrails`, `deadline-model`, `injury-report-ingest`, `lineup-optimizer`

Scheduled auto-set with a pre-lock injury-report refresh and evaluation pass, routed through the automation guardrails.

### `lineup-optimizer` - Building the lineup optimizer

- [ ] **pending**
- **Depends on:** `availability-model`, `punt-builds`, `schedule-density`, `schedule-ingest`

Optimal daily/weekly lineups from projections x p(play), schedule density, category needs and roster eligibility rules.

### `list-perturbation` - Building perturbed lists for blind testing

- [ ] **pending**
- **Depends on:** `aav-blending`

Generate test lists with known distortions injected - shuffled tier, inflated position, planted overvalue at a specific slot - so adherence is measured against known ground truth rather than inferred. Owner must not know which list is perturbed at capture time; sealed record in docs/mocks/lists/ opened only afterwards. Mocks only, never a real draft. Perturbation records are terminal experimental metadata under ADR-008 and must never feed a model.

### `live-draft-availability` - Recomputing values from live availability during the draft

- [ ] **pending**
- **Depends on:** `contingent-value`, `draft-day-synthesis`, `draft-tracker`, `preseason-news-ingest`

News breaking mid-draft - a player out, suspended, a rotation change - updates the AVAILABILITY layer and the valuation and dollar values recompute downstream. It must not patch rankings directly: a hand-edited ranking is an aggregate with no lineage and reintroduces exactly the contamination ADR-008 prevents. Contingent value recomputes with it, so the overlay shows the beneficiaries as well as the casualty.

### `live-lock-advisor` - Exploiting per-player lock timing for late-slate decisions

- [ ] **pending**
- **Depends on:** `deadline-model`, `lineup-optimizer`, `live-matchup-state`

Fantrax locks each player individually at his own tipoff, so late-slate decisions can be made with early-slate results already in hand. If the early games leave the matchup needing blocks and comfortably ahead in assists, the correct late start changes. Combines live matchup state with remaining unlocked players to recommend the category-optimal late-game start. A category-management edge, not merely a punctuality one.

### `live-matchup-state` - Computing live matchup state

- [ ] **pending**
- **Depends on:** `availability-model`, `fantrax-private-adapter`, `live-poller`

Map live box scores onto my roster to produce per-category running totals versus my opponent, with availability-adjusted games remaining rather than raw scheduled counts.

### `live-poller` - Building the live game poller

- [ ] **pending**
- **Depends on:** `nba-stats-ingest`

Poller against cdn.nba.com/static/json/liveData/ scoreboard and boxscore endpoints. ~5s interval, active only while games are live, with backoff.

### `market-model` - Building the empirical market model

- [ ] **pending**
- **Depends on:** `aav-source`, `mock-ingestion`

Empirical ADP and auction price curves built from the 10+ mock corpus, reflecting real drafting behaviour rather than published estimates. NOTE: league is auction, so the corpus must be predominantly AUCTION mocks - snake mocks cannot calibrate inflation curves or budget behaviour.

### `mock-ingestion` - Ingesting external mock draft results

- [ ] **pending**
- **Depends on:** `draft-format-abstraction`, `player-identity`

Capture results from external mock sites (ESPN, Yahoo, FantasyPros, RTSports) via paste or CSV import, resolved through the player identity layer. Different DOM so no bridge rehearsal, but the results are the market corpus. NOTE: league is auction, so the corpus must be predominantly AUCTION mocks - snake mocks cannot calibrate inflation curves or budget behaviour.

### `model-vs-market` - Building the model-versus-market divergence report

- [ ] **pending**
- **Depends on:** `layer-purity`, `market-model`, `risk-adjusted-valuation`

Name where our valuation disagrees with the market. This is the edge stated explicitly: which players to target because the market underrates them, and which to let go because it does not.

### `multi-user` - Adding multi-user support

- [ ] **pending**
- **Depends on:** `db-foundation`

Auth, per-user Fantrax credentials and league scoping so one or two leaguemates can use the tool.

### `notification-engine` - Building the deadline notification engine

- [ ] **pending**
- **Depends on:** `deadline-model`

Read-only alerting, carrying none of ADR-005 write-path concerns. Configurable lead times per deadline type. Contextual rather than chronological - "lineup locks in 30 minutes and two of your players are on teams already ruled out" beats a bare countdown. Actionable, linking to the relevant view. Quiet hours and severity tiers so the system stays worth listening to. Scheduler must be PLUGGABLE (R42) so the host decision can be made separately.

### `opponent-calibration` - Calibrating simulated opponents from mock behaviour

- [ ] **pending**
- **Depends on:** `blind-mocks`, `market-model`

Tune the draft simulator opponent models from observed behaviour in the mock corpus rather than invented priors, for both snake and auction. NOTE: league is auction, so the corpus must be predominantly AUCTION mocks - snake mocks cannot calibrate inflation curves or budget behaviour.

### `overlay-auction-panel` - Building the auction overlay panel

- [ ] **pending**
- **Depends on:** `auction-budget-manager`, `auction-inflation`, `blind-mocks`, `bridge-overlay`

AUCTION IS THE CONFIRMED FORMAT (2026-08-17) - this is now critical path, not insurance. Auction draft surface: current nomination, inflation-adjusted max bid, value versus standing bid, budget and slots remaining, tier-exhaustion alerts. Optimised for a seconds-long bid clock - one number, big and unambiguous.

### `overlay-draft-panel` - Building the draft-day overlay panel

- [ ] **pending**
- **Depends on:** `bridge-overlay`, `draft-recommender`

DEPRIORITISED - league confirmed auction on 2026-08-17. Snake is retained for multi-format support and for ingesting snake mock corpora, but is no longer a draft-day deliverable. Snake draft surface: compact, collapsible, keyboard-toggled Shadow-DOM panel docked in the Fantrax draft room, positioned so it never obscures the draft board or player list. Must be sufficient to make a pick without leaving the tab. Fantrax must be the visible active tab during a draft because Chrome throttles background-tab timers to ~1/min after 5 minutes hidden, stalling Fantrax own draft polling.

### `preseason-news-ingest` - Ingesting preseason availability news for draft day

- [ ] **pending**
- **Depends on:** `injury-report-ingest`, `player-identity`

R40. The NBA official injury report is published per-game and the season opens AFTER the 18 October draft, so injury-report-ingest covers nothing on the day it matters most. Build a separate path for preseason reporting, training-camp news, suspensions and Fantrax player notes. Must be working before the rehearsal window opens on 5 October, not during it.

### `projection-blending` - Implementing configurable projection blending

- [x] **done**
- **Depends on:** `csv-importer`

Migration-free domain/service contract over exact current verified imports:
category-wise normalized user weights, deterministic immutable profile/output
fingerprints, separate auditable manual replacements, explicit activation with
A -> B -> A currentness, and fail-closed lineage/category/cohort validation.
Ratio categories blend made/attempt volume. Games played, availability,
expected games, rankings, market/mock outcomes, valuation and recommendations
cannot enter. No learned source-accuracy path exists without a preregistered
held-out experiment. Profile persistence/API/UI remain an architecture decision.

### `punt-builds` - Modelling punt builds

- [ ] **pending**
- **Depends on:** `gscore-engine`, `risk-adjusted-valuation`

Punt-config modelling with recomputed rankings per build, side-by-side comparison, and fit-to-my-current-roster scoring. Operates on risk-adjusted values.

### `rehearsal-harness` - Building the instrumented rehearsal harness

- [ ] **pending**
- **Depends on:** `blind-mocks`, `draft-day-synthesis`, `draft-simulator`, `surface-parity-tests`

Instruments the Fantrax dress-rehearsal mocks (no fewer than 10): per pick, whether the overlay alone sufficed, when the dashboard was opened and what was checked, time-to-decision, and recommendation take rate. Produces an evidence-based answer on whether a second monitor is actually needed and identifies anything repeatedly checked elsewhere that belongs in the overlay. NOTE: league is auction, so the corpus must be predominantly AUCTION mocks - snake mocks cannot calibrate inflation curves or budget behaviour.

### `reliability-ui` - Building the reliability UI

- [ ] **pending**
- **Depends on:** `frontend-skeleton`, `reliability-metrics`

Durability scorecards, B2B sit patterns, availability trend charts, and a roster-level fragility summary.

### `risk-adjusted-valuation` - Implementing risk-adjusted valuation

- [ ] **pending**
- **Depends on:** `gscore-engine`, `reliability-metrics`

Durability discount/premium layered over raw value. Separate total-value and per-game-value views so the fragile-star tradeoff is explicit rather than hidden in one number.

### `schedule-ui` - Building the schedule tracker UI

- [ ] **pending**
- **Depends on:** `availability-model`, `frontend-skeleton`, `playoff-schedule`, `schedule-ingest`

Games-per-week grid showing availability-adjusted expected games (scheduled games x p(play)) rather than raw counts, plus streaming windows and fantasy playoff week planning.

### `scorecard-ui` - Building the live scorecard UI

- [ ] **pending**
- **Depends on:** `frontend-skeleton`, `live-matchup-state`

Live scorecard fed by SSE: category-by-category win/loss/margin, games remaining, and projected final with confidence bands derived from production and availability variance.

### `shutdown-risk` - Modelling late-season shutdown risk

- [ ] **pending**
- **Depends on:** `availability-model`, `playoff-schedule`

Shutdown/tanking risk for the fantasy playoff weeks: team elimination probability crossed with player age, minutes load, injury status and contract situation. Priced into draft and deadline decisions months ahead.

### `stock-watch` - Building the stock watch dashboard

- [ ] **pending**
- **Depends on:** `contingent-value`, `frontend-skeleton`, `injury-report-ingest`, `risk-adjusted-valuation`

Live value-mover dashboard: injury news lands, affected players are recomputed via the contingent value graph, and the UI surfaces who moved, why, and whether they are available in your league.

### `streaming-engine` - Building the off-night streaming engine

- [ ] **pending**
- **Depends on:** `games-cap-tracker`, `lineup-optimizer`, `schedule-context`

Streaming recommendations for light NBA slates, targeting your weakest categories and ranked by expected marginal category impact rather than generic player value.

### `strength-of-schedule` - Building strength of schedule, weighted by opponent quality

- [ ] **pending**
- **Depends on:** `schedule-context`, `gscore-engine`

Per-team/per-week strength of schedule, weighting scheduled opponents by quality (via `opponent_context`'s per-category defensive profiles) and expressing the result relative to league average. Deliberately sequenced in Phase 5, not alongside `schedule-density`/`schedule-context` in Phase 3/4, because it needs a settled valuation to weight the schedule by (ADR-011) — building it earlier would mean weighting by a placeholder value that gets thrown away once real projections land. Feeds `draft-recommender`, gives `games-cap-tracker` and `playoff-schedule` a second, value-weighted pass beyond raw game counts, and (draft-day only) `auction-values`, using projected rather than known opponent quality since the season hasn't started.

### `supervised-mode` - Implementing supervised decision mode

- [ ] **pending**
- **Depends on:** `automation-audit`, `automation-guardrails`

Default mode: backend computes a recommendation, overlay highlights it in the Fantrax UI, user clicks to confirm. Covers both lineup and draft decisions.

### `surface-parity-tests` - Enforcing surface parity

- [ ] **pending**
- **Depends on:** `dashboard-evidence-views`, `overlay-auction-panel`, `overlay-draft-panel`

Test-enforced rule that no draft-critical decision is available in only one surface: anything the overlay recommends must be inspectable in the dashboard, and anything the dashboard supports must be actionable from the overlay.

### `trade-evaluator` - Building the trade evaluator

- [ ] **pending**
- **Depends on:** `playoff-schedule`, `punt-builds`, `risk-adjusted-valuation`, `schedule-ingest`, `shutdown-risk`

Multi-asset trade evaluation: category deltas, punt-build impact, schedule and fantasy-playoff-week impact, rest-of-season value, and durability/shutdown risk on both sides. Per ADR-012, schedule impact explicitly includes the first-class per-week game-count shape (including two-game/five-game H2H periods, front/back-loaded weeks, and sparse league-wide In-Season Tournament/All-Star-break periods). Surface schedule-driven trade targets and high-value weeks rather than treating schedule as a generic rest-of-season adjustment.

### `trade-finder` - Building the trade finder

- [ ] **pending**
- **Depends on:** `trade-evaluator`

Scan league rosters for mutually beneficial trades from category surplus/deficit matching and differing risk tolerance between managers.

### `waiver-clear-monitor` - Monitoring waiver clears and free agent availability

- [ ] **pending**
- **Depends on:** `deadline-model`, `fantrax-private-adapter`, `notification-engine`, `risk-adjusted-valuation`

The single largest timing edge. When a player clears waivers he is first-come-first-served, and a useful player clearing at 3am goes to whoever is present. Compute exact clear moments from league settings, monitor the free agent pool, and alert on players clearing who match this roster category needs. Read-only; automatic claiming is a separate write-path item requiring safety review and owner enabling.

### `zscore-engine` - Implementing the 9-cat z-score engine

- [ ] **pending**
- **Depends on:** `expected-games`, `projection-blending`, `scoring-profiles`

Z-score valuation for FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO. Volume-weighted impact for percentage categories (not raw pct) and correct TO sign handling. League-context replacement level from league size x roster spots.
