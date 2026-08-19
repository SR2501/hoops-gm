# Build backlog

Generated from the planning session on 2026-08-17. **This is the authoritative task list** - it lived only in a chat session before this, which is exactly what `docs/handoff.md` exists to prevent.

**31 done - 1 blocked - 68 pending - 100 total**

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

Originally scoped to compute every future deadline from the ingested settings: per-player lineup locks at each tipoff, waiver claim cutoffs, waiver clear moments, games-cap thresholds, trade deadline, playoff roster deadlines. `league-settings-ingest` already verified that Fantrax's official `getLeagueInfo` supplies only roster limits and scoring-period boundaries — lineup lock, waivers, trade deadline, playoffs and keeper rules are absent from every source observed so far. Computing any of those from ingested settings would mean inventing them, so this unit delivered the smallest honest contract instead: `league_deadline_calendars`, one immutable, versioned row per league joining an exact `LeagueSettingsSnapshot` with an exact schedule refresh cohort, exposing season bounds and scoring-period boundaries as real timezone-aware instants while carrying lineup lock, waivers, trade deadline, playoffs and keepers forward as explicit unknowns (or their bridge-sourced values, verbatim, when the settings snapshot already has them). Fails closed on missing or mismatched lineage at both derivation and activation time — including when scoring periods themselves are unknown (no `[]` fallback), on out-of-order season/period bounds, and on duplicate period numbers; A→B→A activation cycling is supported by re-deriving over lineage that reverts to prior content. `trade_deadline.deadline_at`/`keepers.deadline_at` are validated offset-aware ISO 8601 at the ingest domain-type boundary, and the read endpoint is loopback-only (bridge-derived values, not a public dashboard fact). A `notification-engine`/`lineup-optimizer` consumer that actually needs a computed lineup-lock instant per game still has no source for one — that gap is real, not an oversight, and stays open until a bridge capture or a new official field closes it. `LeagueDeadlineCalendar` is the authoritative source-truth calendar; the existing `ScoringPeriod` table is a separate, not-yet-built concern — see `scoring-period-projection`.

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

### `injury-report-historical-backfill` - Backfilling historical NBA injury reports for a real evidence cohort

- [x] **done**
- **Depends on:** `injury-report-ingest`

Bounded, resumable operator tool (`hoops_gm.ingest.injury_report.backfill`) that populates a real multi-date, multi-game historical injury-report cohort from the NBA's archived CDN, so `injury-status-conversion` has more than the single committed fixture to work from. Candidate report timestamps are derived per calendar date from exact ingested `nba_games.tipoff_utc` values and the documented publication cadence: `evening_before` (17:30 ET the day prior) in both URL eras, plus an era-conditional game-day strategy — a single fixed 13:00 ET guess pre-2025-12-22 (safe there because the legacy URL truncates to the hour and the masthead check tolerates 45 minutes of drift), and four bounded, tip-off-anchored, 15-minute-grid-aligned offsets (150/90/45/15 minutes before the date's earliest tip-off, floored to the source's own quarter-hour marks so a non-grid-aligned tip-off like 19:10 ET does not push every candidate off-grid) from 2025-12-22 onward, where the URL is an exact-minute match with no drift tolerance. No lookahead is enforced twice (plan time and read time). The natural key (`report_timestamp, team_raw, player_name_raw, game_date`), checkpoint identity that includes the exact resolved timestamp (not just date+anchor, so a corrected tip-off cannot silently reuse a stale candidate's settled status), and two fail-closed gates — `enforce_full_tipoff_coverage` and an independent `enforce_expected_game_coverage` against the official `LeagueGameFinder` schedule (migrations `0013`/`0014`) — prevent a same-player back-to-back split across two game dates from colliding, and prevent running against a requested or incidentally-ingested game scope (e.g. 22 of 527 games) as though it were cohort-ready. Reuses the existing `InjuryReportClient`/parser/importer — two schema changes (natural key; evidence schema version). Checkpointed (cache-independent) and idempotent so an interrupted run resumes, including across a mid-write commit failure and mid-flight tip-off correction. A 403 is never checkpointed as settled — recorded under its own permanent `"forbidden"` status and retried indefinitely across every future run, regardless of streak length or process boundary; a streak still raises an early-abort optimization, but checkpoint correctness never depends on it. Durable per-run `CoverageReport` evidence (persisted even on an aborted run, keyed on the exact requested timestamp so a corrected tip-off cannot silently reuse stale coverage) is classified against the database's *current* tip-off and game identity — re-read fresh on every `coverage_for_games` call, never a possibly-stale caller snapshot — and matched by each candidate's stable NBA game identifier (`applicable_nba_game_ids`), never a reusable surrogate database id; coverage evidence recorded before this stable-identity fix is stamped a legacy coverage-schema version and excluded from `submitted_zero_listed` classification entirely rather than trusted against whichever game holds its old surrogate id today. An unresolved (unattributable) report row vetoes a clean `submitted_zero_listed` claim only for the same-date games whose current tip-off is strictly after that row's own report timestamp — never date-wide — and this `unresolved_evidence` outcome outranks the coarser `legacy_excluded` when both apply to the same game. A full `exclusion_cascade` denominator breakdown (expected → ingested-with-tipoff → candidate-scoped → attempted → recovered → resolved-game → resolved-player → status-listed, split by legacy vs. trusted evidence schema so a pre-fix row is never silently counted as trusted), and a network-free `observations` CLI command expose per-game outcome (`observed` / `no_candidate_coverage` / `not_yet_submitted_only` / `submitted_zero_listed` / `legacy_excluded` / `missing_tipoff`) so the falsifiable coverage gap is checkable per game and per cascade stage, not asserted as an aggregate rate. Rows written before the natural-key/versioning fix are stamped a legacy evidence-schema version and excluded from every trust-dependent cascade stage and canonical-observation query by default. `CanonicalPregameObservation.lead_time_minutes` is the realized per-game `tipoff_utc - report_timestamp`, distinct from a `ReportCandidate`'s `anchor_offset_minutes` (the anchor's shared, intended offset for the date) — the two were conflated before round-5 review and are now separately named and computed. `ExpectedGameCoverage`/`CoverageReport` are bound to the exact requested season/season_type/date range and rejected if mismatched. Coverage classification also forces a fresh (`populate_existing`) re-read of each game's tip-off inside `coverage_for_games`'s own read scope, closing a residual ORM identity-map staleness gap where an already-loaded session object could otherwise retain a pre-correction value even after a separate session's committed fix; rejects an *unrecognized future* `evidence_schema_version` exactly like a legacy one (not merely anything below current); rejects evidence whose `report_date` no longer matches a rescheduled game's current `game_date`, or whose `CoverageReport.season`/`season_type` does not match the game's current schedule scope; emits a retracted-tip-off game exactly once (not duplicated across the ready/newly-missing paths); and keeps a resolved-but-currently-out-of-scope `game_id` (e.g. its own game's tip-off was itself retracted) bound to that one game rather than fanning the conservative unattributable-row veto onto unrelated same-date games. `coverage_for_games` now reads every classification-relevant game field (stable id, local id, date, tip-off, season, season_type, both teams' abbreviations) in exactly one `SELECT`, deriving `select_canonical_pregame_observations`'s tip-off lookups from that same snapshot rather than a second, separately-timed query a schedule correction could land between — proven immune to a real mid-call commit via a `before_cursor_execute` engine hook against a genuine second database connection. Persisted coverage is now bound to an exact evidence schema version (bumped to 3) and each candidate's own self-described `season`/`season_type`, not merely per-game schedule scope: a whole-file scope mismatch against the current request raises rather than silently rewriting the file under the wrong label, and an individual out-of-scope candidate is excluded even inside an otherwise-matching file. Checkpoint settlement identity now also carries the settled scope's stable NBA game ids, so a genuine `--allow-missing-tipoff` partial day — where a later-ingested same-day game's tip-off is *later* than the date's already-known earliest and therefore never changes the near-tip candidate's resolved instant or checkpoint key — is correctly reprocessed on resume (idempotently) rather than trusted forever under the narrower, stale settled scope.

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

### `schedule-ingest` - Ingesting the NBA season schedule

- [x] **done**
- **Depends on:** `nba-stats-ingest`

Season schedule ingestion, fantasy week definitions, and per-week scheduled game counts per team. Foundation for schedule density and the availability model.

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

Own per-game production model from historical logs, accounting for minutes, usage and role. Exposed as another source inside the blending layer.

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

- [ ] **pending**
- **Depends on:** `player-identity`

Generic CSV importer with per-source column-mapping profiles (FantasyPros, Hashtag, Basketball Monster, manual). Name resolution via the identity layer, validation, import history. Captures each source embedded games-played assumption separately from per-game rates so our own availability model can override it.

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

### `draft-format-abstraction` - Abstracting snake and auction draft formats

- [ ] **pending**
- **Depends on:** `scoring-profiles`

Snake and auction as first-class draft formats alongside scoring profiles. They are not variants of each other - snake optimises pick-by-pick value against ADP and scarcity, auction is a constrained budget-allocation problem with live price discovery. Neither may be a special case bolted onto the other.

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

### `injury-status-conversion` - Modelling injury status conversion rates

- [ ] **pending**
- **Depends on:** `injury-report-ingest`, `injury-report-historical-backfill`, `participation-ledger`

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

- [ ] **pending**
- **Depends on:** `csv-importer`

Configurable weighted blending of per-game production rates across sources including manual overrides. Versioned blend profiles so downstream valuations are reproducible. Production rates only - games played is handled by the availability model.

### `punt-builds` - Modelling punt builds

- [ ] **pending**
- **Depends on:** `gscore-engine`, `risk-adjusted-valuation`

Punt-config modelling with recomputed rankings per build, side-by-side comparison, and fit-to-my-current-roster scoring. Operates on risk-adjusted values.

### `rehearsal-harness` - Building the instrumented rehearsal harness

- [ ] **pending**
- **Depends on:** `blind-mocks`, `draft-day-synthesis`, `draft-simulator`, `surface-parity-tests`

Instruments the Fantrax dress-rehearsal mocks (no fewer than 10): per pick, whether the overlay alone sufficed, when the dashboard was opened and what was checked, time-to-decision, and recommendation take rate. Produces an evidence-based answer on whether a second monitor is actually needed and identifies anything repeatedly checked elsewhere that belongs in the overlay. NOTE: league is auction, so the corpus must be predominantly AUCTION mocks - snake mocks cannot calibrate inflation curves or budget behaviour.

### `reliability-metrics` - Building player reliability and consistency metrics

- [ ] **pending**
- **Depends on:** `participation-ledger`, `schedule-context`

Durability scorecard: availability rate and its trend, B2B sit rate (most actionable single pattern), minutes volatility (CV), per-category nightly standard deviation, floor/ceiling percentiles, blowout-minutes suppression, and a composite reliability grade shown wherever a player appears.

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

### `scoring-period-projection` - Deriving `ScoringPeriod` from the active deadline calendar

- [ ] **pending**
- **Depends on:** `deadline-model`, `schedule-density`

`LeagueDeadlineCalendar` (`deadline-model`) is the league's one authoritative, versioned source of scoring-period boundaries; `ScoringPeriod` (`db/models/league.py`) is a separate, older table with `Date`-only bounds and a non-null `is_playoff` default of `False` that cannot honestly represent "the source never said" — populating it directly from a settings snapshot would silently convert an explicit unknown into a confident `False`. This unit makes `ScoringPeriod` a derived, non-authoritative *projection* of the currently active `LeagueDeadlineCalendar` — never a second ingest target, never written from anywhere but that projection — computed only when the active calendar's scoring periods and playoff flags are actually known. Required for ADR-012's `scheduled_game_counts` (per-week game-count distribution), which joins on `ScoringPeriod`'s `Date` bounds against `TeamScheduleEntry.game_date`. The projection must convert each boundary's timezone-aware instant to `America/New_York` *before* calling `.date()`, not use UTC or the source's raw offset directly — the boundary and `game_date` must agree on a wall-clock day, or the projection double-counts or drops games at the DST transition and around a scoring period's midnight boundary.

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
