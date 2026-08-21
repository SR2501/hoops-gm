# Build backlog

Generated from the planning session on 2026-08-17. **This is the authoritative task list** - it lived only in a chat session before this, which is exactly what `docs/handoff.md` exists to prevent.

**41 done - 1 blocked - 73 pending - 115 total**

(Recomputed from the status markers in this finished file, never reconciled from
two headers: 114 `###` headings and 114 markers, 1:1, no duplicate
item names. Neither side of a rebase conflict is ever a usable input here, because
each was computed before the other lane's items landed - one lane measured main at
39/71/111 and its own branch at 40/69/110 when the truth was 40/71/112, so no
reconciliation could have reached the answer. The position lane sharpened
`player-position-eligibility` without closing it: the NBA-position half landed, the
Fantrax-eligibility half did not, so that marker stays `pending`.)

The uniqueness check earns its place: resolving this rebase by taking both sides
of a hunk left a bare duplicate `schedule-grid-ui` heading whose body had been
replaced, and *both* status header blocks. The totals disagreed with each other
in the same file, and only a count of unique slugs against markers found it.)

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

### `player-position-eligibility` - Ingesting player position and Fantrax position eligibility

- [ ] **pending** — *NBA-position half landed 2026-08-20; Fantrax-eligibility half outstanding*
- **Depends on:** *(nothing, for the NBA-position half — **done**)*; `player-identity` for the Fantrax-eligibility half

**The dependency deliberately does not point at `player-identity` for the whole item.** `player-identity` specifies matching on "normalized name + team + **position**" — with no position data in the project, that third field did not exist, so ordering all position work behind identity would have left the highest-risk foundational item permanently short of one of the three fields it was specified to use. The NBA-position half needed no crosswalk and landed first; only Fantrax eligibility, which is per-player-per-league, needs the crosswalk.

#### NBA-position half — done (2026-08-20)

`PlayerIndex` supplies the NBA's listed position for every player in one request, and it is persisted on `players.primary_position` with source, season and observed-at lineage (migration 0016). Contract tests, live smoke and the full evidence are in `docs/adapters/nba-stats.md`. R7's third matching key is now real: crosswalk position evidence went from 576 `UNKNOWN` and nothing else to 531 `AGREE` / 35 `DISAGREE` / 10 `UNKNOWN`.

**It is coarse, and this does not close the draft-board requirement.** The vocabulary is `G/F/C` plus hybrids, with **no `PG`/`SG`/`SF`/`PF` on any NBA endpoint checked** — `PlayerIndex`, `CommonPlayerInfo` and `CommonTeamRoster` all agree, and `PlayerIndex` rejects a `PlayerPosition=PG` filter with `{"PlayerPosition": ["Invalid parameters"]}`. It separates a centre from a guard. It cannot express a Fantrax lineup slot.

#### Fantrax-eligibility half — outstanding, and it is a different quantity

**Fantrax's stated eligibility is the only authoritative source. It is read, never derived.** Whatever Fantrax says a player is eligible at *is* what he is eligible at, because that is what the lineup validator enforces on draft night. There is no computation that outranks it.

Everything below is **the owner's expectation, recorded with its provenance and to be confirmed nearer the season** — not established fact. A threshold written down as fact when it was someone's recollection is how a wrong number becomes load-bearing.

* **The player pages are the source of truth, not necessarily the API.** The pages are a UI surface and `getPlayerIds` is an endpoint; they may disagree, and if they do, *the pages win*. Capture both and compare rather than assuming the convenient one is authoritative — the same discipline that caught `gameEt` and `MATCHUP`.
* **It updates on a cadence — believed weekly.** So a stored eligibility value needs a **staleness window**, not merely a timestamp: the system must be able to say "this is as of Tuesday and may be up to seven days behind". Freshness is part of the contract, not metadata.
* **It is monotonic and time-dependent.** Eligibility never decreases, and eligibility on draft day is not eligibility in March. Any stored value carries an **as-of** date; a snapshot without one silently becomes wrong.
* **The owner's general expectation of the rule** is that starting at a position **5 times** grants eligibility there, never lost. He is explicit that other sites and leagues differ and that **Fantrax does not abide by it 100%**, so *there will at times be a rule/logical mismatch that takes some catching up*.
* **Therefore anything derived from starts is a prediction of a third party's behaviour, not a reading of eligibility.** Counting starts and presenting the output as eligibility would be modelling an undocumented, not-strictly-followed policy and dressing it as fact — the confident, plausible, wrong number `AGENTS.md` opens with. If it is ever built it belongs to `quant` behind the **Model gate**, labelled as an expectation with its calibration stated, and it may never be displayed as eligibility or used to construct a lineup Fantrax would reject.
* **The divergence is the product, not a nuisance.** The useful framing keeps the two claims separate: *"Fantrax lists him at G. He has started at forward 4 times, and the usual pattern suggests F eligibility is due; pages update about weekly."* One read, one inferred, never blended. A player four starts from gaining eligibility is exactly the league-specific, time-sensitive fact Basketball Monster does not provide, and it matters at the draft and on waivers.
* **Adaptability is a stated design requirement.** The owner: *a lot of the rules in these leagues require very dynamic tools.* That argues against hard-coding league rules as constants, and for holding them as data with provenance and building things that **detect divergence** rather than assume conformance. It applies well beyond position eligibility.

**A checkable lead, verified offline against the committed fixture on 2026-08-20:** `getPlayerIds` already carries a `position` field per row, and the parser already reads it to separate the 30 franchise entities (`position: "Tm"`) from the 1,788 players. The player values *are* fine-grained — `SG` 486, `PG` 345, `SF` 339, `PF` 310, `C` 246, plus a small tail of `F` 31, `G` 30 and one `Default`. **But it is a single value per row, not a multi-position eligibility set**, and Fantrax eligibility is routinely multi-slot. So this is plausibly the *primary* position rather than the eligibility list, and that is the first thing to check against a player page. Do not assume the convenient reading.

**There is probably an ADR here** — where eligibility truth lives, what freshness it carries, and how divergence is surfaced without being resolved — but that is for the lane that builds it, with evidence from a real capture.

The `injury-conversion-cohort-population` waiver of its own "positions" criterion was one downstream consequence of the NBA-position gap, now closed.

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

### `projections-api-early` - Exposing the imported per-game projection cohort

- [x] **done**
- **Depends on:** `csv-importer`, `projection-blending`

Loopback-only `GET /api/v1/leagues/{league_id}/projections/current`, with
`?source=` defaulting to Basketball Monster: the per-game production rates one
projection source published, exactly as the importer decomposed them, plus the
`players` labels a browser screen needs and every fingerprint behind the numbers
— the CSV bytes, the parsing recipe, and the digest over the stored normalised
rates that changes when a row is edited in place while the other two look
untouched. The foundation of the draft board. Browser-*reachable*, not
browser-visible: the screen is `projections-ui`'s, below, and `schedule-grid-ui`
is still the only thing in this repository a person can look at.

Descriptive only. No valuation, z-score, G-score, ranking, auction price, risk
adjustment, availability fusion or recommendation crosses this boundary — those
are `quant`'s behind the Model gate (ADR-002, ADR-008). The only arithmetic in
the route is `len()`.

**A client must not multiply a rate by `assumed_games_played`.** That number is
not merely a games-played figure: for a season-total source it is the exact
divisor the importer used to produce the rates beside it, so the product
recovers the source's published seasonal total to within floating-point
rounding. The ADR-002 decomposition is reversible at the wire by a two-line join, and doing
that join is the fusion ADR-002 permits only at `expected-games`, which is not
built. Display the assumption; do not compute with it.

**It serves the *imported* cohort, not a blended one, and `lineage.blend` is a
typed key that is always `null`.** `projection-blending` computes a blend from a
`BlendCatalog` that is an explicitly caller-owned in-memory value —
`define_blend_profile` and `activate_blend_profile` each return a *new* catalog
because the accepted schema has no blend tables, by design. So no blend profile,
activation pointer or source weights are persisted for any HTTP request to read,
and serving a blend would mean the route choosing weights itself. The key exists
so a consumer renders "not blended" from a fact rather than from a key it failed
to find; at the JSON level it is also where a blend would surface, though the
declared type is `None` rather than `BlendLineage | None`, so that is a schema
change and not a fill-in. Persisting blend profiles is a separate `architect` +
`quant` unit, and is on the path to the owner's stated requirement of seeing
Basketball Monster and our own numbers side by side during the draft.

ADR-002's separation is in the wire format, not only in the schema: the source's
own games-played assumption is a separate top-level array, never a key inside a
rate object, mirroring the one-to-one table it comes from, and a test asserts
`games`/`expected_games`/`rank`/`aav`/`z_score`/`g_score` appear in no rate
object and at no top level. No shooting percentage is ever computed — makes and
attempts only.

Currency, profile verification and row validity come from
`blending.release_projection_import`, the canonical function the rest of the
pipeline already trusts, never from a second reader in the route; the route's
own "which import" query is a *selector* the canonical release arbitrates, so
drift in the definition of "current" fails closed rather than serving a
superseded cohort. Eight typed codes in `ErrorResponse.error`:
`projections_local_only`, `projections_league_not_found`,
`projections_source_unsupported`, `projections_source_not_imported`,
`projections_not_current`, `projections_incomplete`,
`projections_incomplete_evidence` and `projections_inconsistent_cohort`.

`projections_incomplete_evidence` is a **family of nine driven members** —
unverified import row, unverified profile-version row, season outside verified
scope, self-contradicting immutable lineage, a negative rate, a non-finite rate,
a half-present three-point made/attempted pair (the only pair with no CHECK
constraint), a row whose denormalised season drifted from its import, and makes
exceeding attempts. That last was called *unreachable* through two review rounds
on the ground that the CHECK constraints block it at the same `+0.001` tolerance
the validator uses; the constant is the same but the arithmetic is not — the
CHECK is IEEE-754 double, the validator compares exact `Fraction`s — so a band
about one ULP wide inserts and then fails validation. Driven. It stays one code
under `architect`'s rule — *split when two members imply different operator
actions; keep one when every member implies the same one* — because re-importing
rewrites the whole row cohort and so repairs every member. **This enumeration was
short at five, then at eight, before it was nine**, and each recount came from
someone walking the raise sites rather than reading the previous list. A consumer
must render a summary true of every member and must not substring-match `detail`,
which is free-form prose. `test_the_blending_error_family_is_pinned` fails if
`ProjectionBlendError` gains a subclass, so convergence is decided rather than
inherited.

Guaranteed on any 200 or refused instead: `players` and `projections` describe
the same `player_id` set, each exactly once, both ordered; and
`len(projections) == lineage.projection_import.projection_count`.
`source_games_played_assumptions` is deliberately sparse and absent never means
zero.

**The route takes no lock, and that is the decision rather than the omission.**
An earlier version took the importer's `projection_sources` row `FOR UPDATE` and
claimed both dialects serialized; review drove it and the SQLite half was false,
because pysqlite emits `BEGIN` only before DML and SQLAlchemy drops `FOR UPDATE`
— a concurrent writer committed straight through the reader and produced a 200
whose rates were post-write beside a pre-write digest. Adding SQLite's write
reservation fixed that and cost more than it bought: every read became a writer,
so concurrent polls serialized against each other (measured at 2.05s and 4.17s,
with an untyped 500 for the loser of a slower pair) and an open dashboard tab
could make a hand-run import fail with `database is locked`; it also mutated
`updated_at` through `TimestampMixin`. Instead every read is **bracketed between
two runs of the canonical release**.

**What that detects, stated at the strength it was driven at.** A write landing
*before* the rows are loaded is caught. One landing *after* them is caught only
if it replaced the row primary keys — an in-place edit is shadowed by the route's
own strong references and a consistent *older* snapshot is served, while a
re-import replaces every key and is seen. That last is dialect-dependent:
PostgreSQL's `SERIAL` never recycles, SQLite can. The guarantee is unconditional
either way — the rates and the lineage block beside them always describe the same
cohort state — but the behaviour is not, and two earlier versions of this entry
said otherwise (first "refuses if anything moved", then "identically on both
dialects"). Freshness is not promised. `projections_inconsistent_cohort` is the only retryable
code of the eight; a client retries once and keeps the last good payload rather
than clearing the view. Driven with real committed writes from a second
connection, with monkeypatching confined to *timing* rather than to the loader's
result.

### `release-digests-assumptions` - Bringing the games-played assumptions inside the release digest

- [ ] **pending**
- **Depends on:** `projections-api-early`

`ReleasedProjectionImport` digests the `projections` rows and deliberately never selects
`source_games_played_assumptions`, so `projections-api-early`'s assumptions array is the
one part of that response outside the guarantee the endpoint makes about itself. The
array is joined on `projection_import_id` and subset-checked against the players carried,
which makes a claim for an uncarried player inexpressible — but a *changed* assumption is
not detected, and the array's documented semantics ("a missing entry means the source
said nothing") are a strong claim with nothing pinning them.

Found by `architect` reviewing the fix for the defect it enables: a byte-identical
re-import mid-read served a 200 with an **empty** assumptions array, reporting that
Basketball Monster published no games-played assumption when it published 70 and 78. The
route-level fix closes that instance; this closes the class, by making the array inherit
the same mechanism that already catches a rate edit instead of borrowing its credibility.

A producer-contract change in `hoops_gm.projections.blending`, not an API change. ADR-002
is the constraint that makes it delicate: the assumption must be digested *alongside* the
rates as separate evidence, never folded into `projection_values_sha256`, or the
separation the table exists to enforce is lost at the fingerprint. On completion, retire
the exemption stated on `CurrentProjectionsResponse` and amend ADR-014.

### `projections-ui` - Putting the imported projections on screen

- [ ] **pending**
- **Depends on:** `projections-api-early`

The draft board's first surface: every player in the current Basketball Monster
cohort with their per-game rates, at `/projections`. Consumes
`projections-api-early`'s endpoint and renders exactly what it returns — no
ranking, no valuation, no z-score or G-score, no availability weighting and no
"who should I draft" judgement, all of which are `quant`'s behind the Model gate.

**Three contract obligations the endpoint cannot enforce for it.** First, the
source's games-played assumption may be *displayed* and must never be multiplied
by a rate: that number is the divisor the importer used, so the product recovers
Basketball Monster's published seasonal total, and doing that join is the fusion
ADR-002 permits only at `expected-games`. Rendering "projected season total" from
this payload is an ADR-002 violation that is two lines long and looks like a
feature. Second, `projections_inconsistent_cohort` is retryable and means a
concurrent import moved the cohort — retry once and keep the last good payload on
screen, because an empty board mid-auction is worse than a slightly stale one.
The other seven codes are terminal and need a human. Third,
`projections_incomplete_evidence` is a family of nine members with one shared
remedy, so its copy must be true of all of them and must not substring-match
`detail`.

`source_games_played_assumptions` is sparse: absent means the source said
nothing, never zero, and must render distinguishably from a stated value — the
same distinction `schedule-grid-ui` spent four review rounds getting right.
Position eligibility is *not* available: this project ingests no Fantrax position
data, and `player-position-eligibility` is still pending, so a draft board cannot
filter or group by position yet. `players[].primary_position` is NBA's own label
and is nullable.

### `schedule-grid-pending-periods` - Showing that a scoring period is not fully scheduled

- [x] **done**
- **Depends on:** `schedule-grid-ui`

ADR-013 lets a refresh register with games the source published without
deciding their teams, so the grid can now show a count that is honest and
incomplete at the same time. A scoring period containing one is marked `TBD` in
its header with a dashed column rule, and a notice states the only thing the
data supports: *this period contains N games whose teams are not yet decided, so
any count in this column may rise*.

This also depends on the backend emitting `lineage.schedule.pending_game_ids`
and `pending_games`, which is the `data-engineer` lane implementing ADR-013 and
had no backlog slug when this was written. `architect` is creating one; this
item's dependency list should gain it.

The wire types were **optional** on the client (`pending_game_ids?`,
`pending_games?`) while the backend lane was unmerged, and the absence was
rendered as its own statement. That lane merged as `28bd480`, so the tolerance
is gone: both fields are required, the "cannot say" notice is deleted, and the
boundary refuses a response without the block. **Closed.**

Three further follow-ups, each with a trigger, recorded here because prose
nothing prompts anyone to revisit is how a screen keeps asserting something it
once checked:

- **The caption's make-up-game clause expires.** It says those games have not
  been released. When the NBA releases them it becomes false, and no
  client-side condition can detect that — nothing in the payload distinguishes
  80 games published because the bracket is open from 82 published. `frontend`
  owns it; the trigger is the Emirates NBA Cup knockout resolving in December.
  The re-ingest clause beside it does not expire.
- **`grid-integrity` still carries `role="status"`.** The two ADR-013 notices
  dropped theirs, because a region present at first paint that describes data
  rather than announcing a change belongs in no polite queue. The same argument
  applies to `grid-integrity` and it was left alone only to avoid changing an
  already-reviewed surface inside an unrelated diff. `frontend` owns both, so
  this is a note to itself and belongs in a tracker rather than a comment.
- **Neither ADR-013 notice announces on refresh.** Dropping `role="status"` is
  right on load and leaves a refresh that takes the pending set from empty to
  non-empty silent. The fix is a region that is empty at mount and live
  thereafter, if the cost is ever judged worth it.
- **`irreconcilable` was classified as wait-class on an inference, and ADR-013
  has now decided it.** The screen split absence causes into wait
  (`not_offered`, `irreconcilable`) and investigate (`unreadable`,
  `implausible`), mirroring the producer's `_FAULT_ABSENCE_REASONS`, which
  excludes `irreconcilable` so the import stays exit 0. That was a
  reconstruction rather than a rule: an exit code answers *should this import
  fail*, and the screen answers *should a human look*.

  **Resolved: `irreconcilable` is a fault.** `architect` ruled it from the live
  feed rather than by argument — the alarm-fatigue objection to widening the
  fault set is a claim about volume, and all six real pending games carry a
  date and an empty reason, so every fault reason fires zero times today. The
  caveat is recorded in ADR-013: if that stops being true, revisit the row
  rather than letting an operator learn to ignore the channel.

  `code-review` supplied the sharper argument, which is about drift and which
  frequency data cannot retire: the producer's own docstring says an epoch
  placeholder pair **reconciles perfectly** for 1900 (`-05:00`) and fails only
  by accident for year 0001, because `America/New_York` ran on `-04:56` local
  mean time before 1883 — so one phenomenon lands in `implausible`,
  `irreconcilable` or `unreadable` depending on a nineteenth-century offset and
  the hour. **The cleaner repair is upstream in `_FAULT_ABSENCE_REASONS`**, and
  that is `data-engineer`'s to weigh; the client no longer depends on it either
  way, because it enumerates the *wait* set and defaults everything else to
  investigate.
- **`.grid-scroll`'s `18rem` budget is now short by a block.** The constant was
  written for four things above the grid; the pending notice is a fifth and is
  present in every shipping state. Measured at a 720px viewport with scroll at
  zero and the lineage collapsed, the first count sits at 583px against a 270px
  budget — five of thirty teams visible, and `tfoot`'s league totals reachable
  only through the inner scroll. The comment now says so. The fix is the one
  that comment already names, a flex column with `min-height: 0`, rather than a
  larger magic number; it is a whole-screen layout change and does not belong in
  a pending-games diff. `frontend` owns it.
- **The caption is the table's accessible name, now 407 characters.** Announced
  on every entry into the table rather than once in document order. Attaching
  the caveat to the table is right in principle — a reader arriving by table
  navigation never heard the page paragraph — but the clean split is name for
  the identifying clause and `aria-describedby` for the caveat. Not done here
  because `aria-describedby` is announced unreliably on `table`, so the trade is
  not obviously favourable and no one has tested either with a real screen
  reader. `frontend` owns it; the trigger is anyone testing this screen with AT.
- **The doctored-payload derivation should move under `backend/`, and one action
  closes two problems.** `make_pending_date_payloads.py` is a Python script under
  `frontend/src/test/fixtures/` that imports `backend/src` to make *frontend*
  fixtures, so it belongs to neither side. The cost is measurable rather than
  aesthetic: the only ruff config is `backend/pyproject.toml` and CI runs
  `ruff check .` with `working-directory: backend`, so nothing in this repository
  lints, formats or type-checks the file where it sits. Separately, nothing in CI
  pins `input -> reason`; `--verify` is a script a person runs, and the clean
  version is a backend test importing the derived payloads and asserting the four
  reasons. **That test requires the derivation to live under `backend/`, so doing
  the gate does the move.** Filed as one item rather than two, because two items
  with one fix diverge — one gets done and the other stays open describing a
  solved problem. `data-engineer` owns it; the trigger is the next touch of the
  schedule-ingestion lane, not "any change to `_pending_game_date`", which only
  someone already thinking about this file would notice. `architect` holds only
  the ruling that it moves.

**Period-scoped, never cell-scoped.**
A pending game carries `teamId: 0` with
every naming field null, so no team can be named and none is. A per-cell "this
team has an unscheduled game" badge would invent the one attribution the source
withheld; the recorded contract test asserts every cell in a pending column
carries the same state and the same accessible name as a cell anywhere else.

Three states are now kept apart where there were two: `0` is a real count,
`·` is data the backend did not send, and a `TBD` column is the source not
having decided. Each has its own colour, marker and wording, and `+?` is
deliberately not reused for pending — it means a sum is short because data is
missing, which is a different claim. A pending block that is *absent* is a
fourth statement, "this response cannot say", and is never read as "nothing is
pending". The lineage panel gains the pending count and lists each game's id,
date and labels, because ADR-013 reverts to refusing if the pending set stops
being explicable as an undetermined bracket and a bare count shows nothing to
check that against.

The four non-empty `date_absence_reason` values fire zero times against the live
source, so both recorded fixtures covering them were produced by driving the
in-tree importer with authored source payloads. Those payloads are derived by
`frontend/src/test/fixtures/make_pending_date_payloads.py` rather than
remembered: `--verify` re-runs the producer's own classifier over them and
asserts the four reasons, and both fixtures were regenerated end to end through
it — seed, serve, capture — differing from the committed bytes in one leaf,
`refreshed_at`. This exists because the fixtures first landed with the inputs
uncommitted, which made *input -> reason* a claim nothing could check; one of the
two payloads had already been overwritten by the time a reviewer said so.

### `schedule-grid-ui` - Putting the raw schedule grid on screen

- [x] **done**
- **Depends on:** `schedule-grid-early`

Teams down, fantasy scoring periods across, scheduled game counts in the cells,
at `/schedule`. Consumes `schedule-grid-early`'s endpoint and renders exactly
what it returns: no availability weighting, no opponent quality, no colour scale
and no light/heavy judgement (ADR-009).

`games: 0` renders as `0`; a `counts` row the backend never sent renders as its
own marked cell and is counted in a visible notice. A blank cell can never mean
either, which is the failure mode this screen exists to avoid. Totals that are
short a period are marked on screen rather than only in screen-reader text, so
a partial sum cannot be read as a complete one. Each of the five documented
refusal codes gets its own explanation and next step, read from the response
body, on both the cold-load and the failed-refresh path. Schedule lineage —
version, refresh id, raw `refreshed_at`, source/resolved/persisted counts — is
on the page rather than in devtools, and the cohort's age is reported against
ADR-012's weekly re-ingest cadence.

The per-period league sum and the per-team mean satisfy the amendment's
league-wide baseline clause. The team-versus-own-distribution clause is
deliberately not implemented here — see `schedule-grid-reference-distribution`.

### `schedule-ingest` - Ingesting the NBA season schedule

- [x] **done**
- **Depends on:** `nba-stats-ingest`

Season schedule ingestion, fantasy week definitions, and per-week scheduled game counts per team. Foundation for schedule density and the availability model. Extended 2026-08-20 under ADR-013 with the pending/failure distinction and an operator command (`python -m hoops_gm.ingest.schedule_import 2026-27`), which is what makes the real 2026-27 season loadable: 1,206 source entries, 1,200 resolved across 30 teams at 80 games each, six Emirates NBA Cup knockout fixtures recorded as pending. Pending means the source published an explicitly absent identity block — `teamId: 0` with every naming field null; a zero id beside *any* populated naming field is a resolution failure and still refuses the cohort. Two gaps it exposed are filed as `schedule-pending-persistence` and `schedule-cohort-fingerprint-list`.

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

- [x] **done** - Regenerated 2026-08-20 from corrected sources after PR #37 invalidated the 2026-08-19 artifact, through five rounds of independent exact-head review (evidence, code, extract privacy). The corrected bounded cohort is 173 games across 26 game dates in `2025-12-08..2026-01-04`, including `0022501229` and `0022501230` on 2025-12-13 and their 39 production logs. Every count and fingerprint was recomputed; nothing was carried forward. The manifest is the deterministic output of a committed generator (`hoops_gm.ingest.injury_report.cohort_evidence`) rather than hand-assembled; it **refuses to publish** unless four views of the window name exactly the same games as sets *and* two endpoints agree on all 173 tip-off instants, and it publishes a map of which views are actually independent of the ingest path (only `ScheduleLeagueV2` is). **The item's own "multiple positions" criterion is explicitly waived, with cause:** review established that `BoxScoreTraditionalV3.position` is emitted only for the five starters, always as `F,F,C,G,G`, so it is a lineup slot rather than a player attribute and positional composition cannot be established from any source this project currently ingests. Establishing it needs a new adapter under the Adapter gate and is not a precondition for the observation-layer cohort. Team, date, status and stated-reason diversity are established. The 2026-08-19 artifact remains preserved in history and stays non-consumable.
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

### `schedule-cohort-fingerprint-list` - Restoring what the injury cohort manifest watches

- [ ] **pending**
- **Depends on:** `injury-report-backfill`

`DEFAULT_SOURCE_FINGERPRINT_PATHS` in `ingest/injury_report/cohort_evidence.py` omits `backend/src/hoops_gm/ingest/nba/schedule.py`, which the generator directly calls (`parse_schedule`, for the `schedule_league_v2` reconciliation view — the cohort's only genuinely independent witness). Found 2026-08-20 when one change touched that file and `db/lineage.py` together: the alarm fired on the file outside the derivation and stayed **silent** on the file inside it, which is a false green, not merely a coarse one.

**The removal half is already done; only the addition is left, and only it needs a regeneration.** The untrue `db/lineage.py` entry was deleted from the manifest's `source_fingerprints` rather than refreshed, because deleting narrows an over-claim while refreshing would assert the cohort was derived with bytes it was not. The constant itself still lists `db/lineage.py` and was deliberately left alone: editing `cohort_evidence.py` stales that file's own digest, and it *is* in the derivation, so the same false-claim problem simply moves one file over. Both edits therefore belong to the regeneration, together: drop `db/lineage.py` from the constant, add `ingest/nba/schedule.py`, regenerate against the cohort database.

**Consequence to carry until then, stated because it is easy to miss:** with the entry deleted, edits to `db/lineage.py` are **no longer watched at all** by the cohort provenance alarm. That is the correct trade — the alarm was watching a file outside the derivation and missing one inside it, so it was giving a false green on the file that matters — but it means the watch set is now four files, not five, and a lane touching `db/lineage.py` will get no signal rather than a misleading one. Nothing is lost that was true; something misleading was removed.

### `schedule-grid-contract-artefact` - Failing CI when the schedule grid response shape drifts

- [ ] **pending**
- **Depends on:** `schedule-grid-early`, `schedule-grid-ui`

**Precondition for the next frontend increment against this API**, not an
open-ended improvement. Named that way deliberately so it cannot quietly become
permanent.

Nothing currently ties the frontend's wire assumptions to the backend's actual
output. `frontend/src/api/endpoints.ts` hand-writes the response contract, and
`frontend/src/test/fixtures/schedule-grid-current.recorded.json` is a snapshot
captured by hand from a running service — so it catches drift only when someone
thinks to re-record, which is to say exactly when nobody is looking for it. Both
sides can be internally green and mutually wrong.

Owned by `backend`, because the artefact has to be produced where the response
model lives: a backend test serialises a real `ScheduleGridResponse` to a
committed JSON file, and the frontend suite loads that file instead of a
recording. One artefact, both sides, fails in CI on drift rather than in a
browser. Gate: Code.

Deferred from 2026-08-20 by the coordinator with the mechanism stated: building
it while backend PR #38 was in final review would have restarted the review
clock on an otherwise-ready head, and the risk it mitigates has no active source
until the next increment is scheduled against this contract.

### `schedule-grid-refusal-discriminant` - Distinguishing nine conditions that share one refusal code

- [ ] **pending**
- **Depends on:** `schedule-grid-early`, `schedule-grid-ui`

`schedule_grid_incomplete_evidence` is raised from nine places in
`backend/src/hoops_gm/api/routes/schedule_grid.py`, on four different objects:
the refresh's completeness evidence, the cohort it describes, the league's team
rows, and the league's scoring calendar. They call for different operator
actions — a refresh that cannot state its completeness needs the schedule
re-importing, while a scoring period the league has no row for needs the
calendar corrected, and re-importing the schedule will never create one.

A consumer given only the code cannot tell which. The dashboard currently names
all three families in one message and defers to the backend's `detail` prose for
which applies, which is honest but is the weakest form of the information: it
cannot be branched on, and it puts the burden on the reader at the moment they
are least able to carry it.

This has already produced two defects on the frontend, both caught in review
rather than by any test. Copy written against one condition asserted that the
refresh "cannot state what it imported" and was rendered directly above a
backend detail saying it had stated it and imported a playoffs cohort. The
correction then asserted a single remedy — re-import the schedule — which is a
confident, wrong instruction for the three conditions rooted in the league's own
data. Each was true of the condition it was written against.

Owned by `backend`. Either split the code so each family has its own, or add a
machine-readable discriminant to the error body alongside `error`. Gate: Code.
The frontend must not recover specificity by matching on `detail` text — that is
the form-over-meaning coupling `AGENTS.md` warns about and would break silently
on a reword.

### `schedule-grid-reference-distribution` - Comparing a team's period count against its own normal

- [ ] **pending**
- **Depends on:** `schedule-grid-ui`

ADR-012's 2026-08-17 amendment requires a team's raw scheduled-game count be
shown against **both** the league-wide period baseline and *that team's normal
distribution*. `schedule-grid-ui` ships the first and deliberately defers the
second; without this item the amendment is half-implemented and nothing outside
this line says so.

Owned by `quant`, not `frontend`, because "normal" is not arithmetic. It
requires choosing a reference set — whether to include fantasy playoff periods,
partial first and last periods, and the league-wide sparse periods (In-Season
Tournament, All-Star break) that the same amendment singles out as special. A
baseline that includes All-Star week depresses the mean and makes a genuinely
sparse week read as ordinary; excluding it needs a rule for what counts as
league-wide sparse, and that rule is a threshold. The amendment ties the output
to trade targeting, so it is a number a decision rests on.

**Gate:** Model, not Adapter. Needs held-out evaluation of whether the deviation
measure identifies the periods it claims to, a model card in `docs/models/`, and
an explicit statement of what the reference set cannot see. Until then the grid
shows the raw row, which is itself the team's distribution laid out in order —
the missing piece is the quantified comparison, not the evidence.

### `schedule-pending-persistence` - Making the pending set verifiable

- [ ] **pending**
- **Depends on:** `schedule-ingest`

`schedule_content_version` fingerprints persisted `team_schedule` rows, and a pending game has none, so the registered version does not cover the pending set: two cohorts differing only in which games are pending share a version. Measured rather than reasoned to — the demo seed's 10-source cohort and its 12-source, 2-pending successor both fingerprint to `9bcac1c60490b41a`, and `test_the_schedule_version_does_not_change_when_only_the_pending_set_changes` pins it. Consequently `verify_refresh` detects a forged *resolved* cohort but not a forged pending list, and a consumer must not cache the pending set keyed on the schedule version alone. Closing it means persisting pending games as first-class rows — schema, migration, and a fingerprint spanning both populations. The gap is narrow and self-closing per game as the Cup bracket is drawn, which is why it was filed rather than added to the ADR-013 unit.

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
