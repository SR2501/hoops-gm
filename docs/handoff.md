# Handoff log

**Append-only.** Newest entries at the bottom. Do not edit or delete previous entries; if something recorded here turns out to be wrong, add a new entry saying so.

**The rule protects *merged* memory.** An entry on an unmerged branch is not memory yet, so correct it in place rather than deliberately landing something known to be false in order to append a correction afterwards — that serves nobody and pollutes the record it is meant to protect. Once an entry is on `main`, it is permanent and corrections are appended. Either way, keep the original claim visible alongside the correction: the fact that something was believed and wrong is usually the most useful part.

This is the project's memory. It exists because material produced in conversation becomes unfindable the moment the screen changes. If it is worth returning to, it is written here or elsewhere in this repository — never only in a chat.

## Entry format

```
## YYYY-MM-DD — <agent> — <what was worked on>

**Changed:** one paragraph.
**Now true:** what is true that was not true before.
**Could not verify:** MANDATORY. "Nothing" is rarely the honest answer.
**Next:** who is next and what they need from this.
```

---

## 2026-08-17 — planning — Project inception and governance

**Changed:** Created the repository and its governance layer from a planning conversation on 2026-08-17. Committed `docs/plan.md` (the full plan), `AGENTS.md` (entry point), seven agent definitions in `.github/agents/`, four governance documents, and ADR-001 through ADR-007 recording decisions reached during planning.

Research was conducted before planning and is summarised in the plan's research findings table. Key constraints established: Fantrax offers a limited official read API and no write API of any kind; `fantraxapi` reads private leagues via a session cookie; live NBA scoring is free from `cdn.nba.com` at 1–5s latency; `nba_api` is maintained and is the historical stats source; Basketball-Reference is excluded on data-use policy grounds; G-score (arXiv 2307.02188) outperforms z-score in H2H.

**Now true:**
- `SR2501/hoops-gm` exists as a private repository with the plan and governance committed. Nothing important lives only in a chat transcript.
- The build is scoped at 75 tracked work items across 14 phases, with a dependency graph containing no cycles and a single root.
- The spine order is fixed: identity → schedule → availability → projections → valuation, then features. Availability precedes valuation because it is an input to it (ADR-007).
- Both snake and auction draft formats are in scope as first-class engines. The league format for this season is not yet confirmed.
- Seven agents, four readiness gates (Code, Adapter, Model, Automation), and a defined owner-only decision list are in force.

**Could not verify:**
- **The league's draft format.** Auction is likely but unconfirmed. Both are planned; confirmation determines where late-stage rehearsal effort goes.
- **Whether the Fantrax official API endpoints behave as documented.** No live call has been made. `getPlayerIds`, `getAdp`, `getLeagueInfo` and `getDraftPicks` are documented as beta and sparsely specified — the first data-engineer task should verify each against a real request before anything is built on them.
- **Whether `fantraxapi` works against an NBA H2H category league.** Its author developed and tested it against an NHL H2H points league and explicitly notes results may vary by sport and format.
- **Whether the availability model is achievable at the fidelity the plan assumes.** Historical DNP reason codes are inconsistently reported and "rest" is frequently laundered as a minor ailment. The data may not support the granularity described; the backtest harness is the check on this.
- **Whether the overlay can be sufficient without a second monitor.** Designed for one screen, but unproven. `rehearsal-harness` is instrumented specifically to answer this with evidence rather than opinion.
- **Any calibration or accuracy claim.** No model exists yet. Every number in the plan describing model behaviour is an intention, not a measurement.
- **That the governance overhead is worth it.** Seven agents and four gates for a solo project is a judgement call. `architect` owns the decision to cut it if it costs more than it prevents.

**Next:** `architect` to review the seeded ADRs and the phase sequencing, then `backend` and `frontend` to scaffold Phase 1 (FastAPI skeleton, database foundation, Vite/React skeleton, CI enforcing the Code gate). `data-engineer` should independently verify the Fantrax official endpoints early, since several plan assumptions rest on them.

**For the owner:** the seven ADRs are `Proposed` and await acceptance. Confirming auction vs snake with the commissioner is the most useful early input — it does not change the spine, but it decides where the final weeks of effort go.

---

## 2026-08-17 — backend, frontend — Phase 1 foundations

**Changed:** Built all five Phase 1 items. `repo-scaffold`: monorepo layout (`backend/`, `frontend/`, `userscript/`, `scripts/`), MIT licence, `docker-compose.yml`, extended `.gitignore` and `.env.example`. `backend-skeleton`: FastAPI app with pydantic-settings, structlog structured logging, request-id middleware, a stable error envelope, and `/health`, `/health/ready`, `/api/v1/meta`; pytest, ruff and mypy `strict` wired. `db-foundation`: SQLAlchemy 2.0 declarative models, Alembic, session management, and 17 tables covering the Identity, Stats and League groups plus part of Schedule. `frontend-skeleton`: Vite + React + TypeScript with routing, a typed API client, a layout shell and a documented component convention. `ci-pipeline`: GitHub Actions running both Code gates on push and PR, plus a migration-drift job, a secret scan, and three jobs that already select the Adapter and Model gate pytest markers.

Two departures from the brief, argued rather than assumed:

- **`schedule_density`, `off_night_slates` and `opponent_context` were not built.** Their columns are not ingest facts — which density windows matter, what counts as a light slate, how category defence is expressed — they are modelling choices owned by `quant` and `data-engineer` in Phase 3. Fixing that shape before anyone has tried to compute it is exactly the "painted into a corner" outcome Phase 1 exists to avoid. `team_schedule` is built and gives them a stable per-team, per-game row to attach to.
- **`week_definitions` was collapsed into `scoring_periods`.** The plan's data model lists both, but a fantasy week *is* a scoring period, and two tables that must agree with no mechanism to enforce agreement is a bug waiting to happen. If a league-independent NBA week calendar is later needed for streaming analysis, add it then, on evidence. **This is a small error in the plan and it should be corrected there.**

**Now true:**
- The Code gate is real and enforced, not aspirational. Backend: ruff, `ruff format --check`, mypy `strict`, 60 tests. Frontend: eslint (type-checked rules), `tsc --noEmit`, 12 tests, production build. All green locally.
- The stack runs end-to-end. Backend serves on `127.0.0.1:8000`; the dashboard on `127.0.0.1:5173` renders live backend data through the Vite proxy — verified in a real browser, not just by unit test.
- `alembic upgrade head` applies from empty, `alembic check` reports no drift, `alembic downgrade base` works. CI runs all three, so a model change without a migration fails the build.
- Player identity is modelled for the resolver Phase 2 has to write: surrogate keys everywhere, `(source, external_id)` unique, per-source raw name string retained, `confidence` constrained to `[0,1]`, `match_method`, and an `is_manual_override` flag the resolver is required to treat as final. Nine tests cover exactly the R7 failure modes.
- Percentage categories cannot be modelled wrongly by accident. Box scores store makes *and* attempts, ratio scoring categories carry a `numerator_stat` and `denominator_stat` enforced by a CHECK constraint, and a test asserts no column matching `*pct*` exists in the stats tables. That is R9 addressed structurally rather than by convention.
- The versioning seam the plan requires exists: `league_scoring_profiles` is versioned and unique on `(league_id, name, version)`, so a later valuation takes a foreign key to a configuration *row* and stays explainable forever. Punt configs and blend profiles should follow the same pattern.
- The Postgres seam is tested, not asserted. Tests fail on a native enum type, an unnamed constraint, a constraint name over Postgres's 63-character limit, dialect branching outside `db/session.py`, or raw driver SQL in the package. SQLite has `PRAGMA foreign_keys=ON` so it rejects the referential garbage Postgres would.
- The Adapter and Model gates have running CI jobs from today. They select markers that currently match nothing and pass with a notice; the first contract test or backtest is enforced without anyone remembering to wire it.
- **Found and fixed a real trap.** A `PRAGMA foreign_keys=ON` issued on the connection in `alembic/env.py` made Alembic treat the transaction as externally managed: the DDL applied, but the `alembic_version` row was never committed, so the database claimed to be at no revision and the next upgrade tried to recreate everything. It is now registered as an engine connect-event, and `test_the_migration_records_its_revision` exists specifically to catch a regression. This would have been very unpleasant to debug mid-season.

**Could not verify:**
- **That `docker compose up` works.** Docker is not installed on this machine. The compose file and both Dockerfiles are written and reviewed, and the YAML parses with every published port asserted loopback-bound — but no image has ever been built and no container has ever run. **Someone must actually run `docker compose up --build` before relying on it.** The three most likely faults are the backend healthcheck's inline Python, the frontend bind-mount colliding with the image's `node_modules`, and `alembic upgrade head` running against `/data` in the container.
- **That CI passes.** The workflow has never executed. It is validated as YAML and each command was run locally, but on Ubuntu with Python 3.12 and Node 22 — whereas local development was on Windows with Python 3.14 and Node 24. Dependency resolution differences on 3.12 are the most plausible failure.
- **Anything about Postgres.** Every portability claim above is a structural check against SQLite plus a rule about what the code may do. Nothing has been run against a real Postgres. The compose file ships a profile-gated Postgres service so this is cheap to test, and it should be tested before Phase 13 rather than during it.
- **That the schema is right.** It is untested against real data, because no adapter exists. Confidence is highest in Identity and Stats, and lowest in League: the Fantrax shapes for `transactions`, `roster_slots` and `matchup_category_results` are guesses at what `fantraxapi` returns, and the handoff before this one already flagged that `fantraxapi` was developed against an NHL points league. Expect Phase 2 to need migrations here, and treat that as normal rather than as a failure.
- **Whether `player_external_ids` is sufficient for the resolver.** It is modelled from the *description* of the identity problem, not from having seen the disagreements. Specifically unproven: whether one `confidence` float is enough or whether per-field match evidence is needed; and whether `(source, external_id)` uniqueness holds for projection CSVs, where the synthetic key is our own construction.
- **`seconds_played` as the minutes representation.** Exact and portable, but `nba_api` returns `"34:12"` and some sources return decimal minutes; whether every source converts losslessly has not been checked against real data.
- **The scoring-category vocabulary.** `fg_pct`, `ft_pct`, `fg3m`, `pts`, `reb`, `ast`, `stl`, `blk`, `to` are asserted by a test but come from the plan, not from the league's actual Fantrax settings. If Fantrax names them differently, the mapping belongs in the adapter and the keys should stay as they are.
- **That the frontend conventions survive contact with a real view.** `AsyncBoundary` and `useAsync` handle loading, error, empty and stale, but the only data behind them so far is a health check. Staleness is the one that matters, and it has not yet been exercised on anything with a genuine shelf life.

**Next:** `data-engineer` owns Phase 2. Everything needed is in place: `players` and `player_external_ids` for the crosswalk, `nba_teams`, `nba_games`, `player_game_logs` and `player_season_stats` for the backfill, `team_schedule` for the fixtures, and the `adapter_contract` / `live_smoke` pytest markers already running in CI. Add fixtures under a `fixtures/` directory — `.gitignore` already exempts those from the CSV exclusion. Add a migration for any schema change; `alembic check` in CI will catch it if you forget.

`quant` should read `db/models/stats.py` and `db/models/league.py` before Phase 4: makes-and-attempts and the ratio-category components are deliberate, and the availability tables must be added, not carved out of these.

**For the owner:**
1. **Run `docker compose up --build` once and report what breaks.** It is the one Definition-of-Done item that could not be verified here.
2. The MIT licence was chosen as the conventional default for a personal project and is not on the owner-only list. It is trivially reversible before the repository is ever shared — say so if you would rather it were something else, or unlicensed.
3. The ADRs remain `Proposed`. ADR-001 in particular is now load-bearing on real code, and its consequences are tested.

---

## 2026-08-17 — backend — Phase 1 CI verified (correction to the entry above)

**Changed:** Nothing in the code. Appending rather than editing the previous entry, per the append-only rule.

**Now true:** The entry above lists "CI has never executed" under *Could not verify*. That is no longer accurate. The first run on `sr2501-phase-1-foundations` completed in 45 seconds with all six active jobs green on Ubuntu with Python 3.12 and Node 22 — backend lint/type-check/tests, migrations from empty, frontend lint/type-check/tests/build, the secret scan, and the adapter and model gate jobs correctly reporting no tests yet. `live-smoke` skipped as designed, since it runs only on schedule or manual dispatch. The Windows/Python 3.14/Node 24 versus Ubuntu/3.12/Node 22 gap named in that entry turned out not to matter.

**Could not verify:** Everything else in the entry above still stands, and `docker compose up` in particular remains entirely unrun — it is the one Definition-of-Done item without evidence behind it. One green CI run also says nothing about flakiness; the migration and frontend jobs are the ones to watch, since both do real I/O.

**Next:** Unchanged — `data-engineer` owns Phase 2.

---

## 2026-08-17 — backend — Phase 1 review remediation, and two guarantees that were not true

**Changed:** Fixed all seven findings from the independent review of PR #1, plus two design errors found while replying to it. Two of the seven falsify claims made in the Phase 1 entry above, which is why this entry leads with them rather than with the fixes.

**What was claimed and was not true:**

1. **Enum CHECK constraints did not exist.** `db/base.py`, `db/models/enums.py` and the migration all stated that enums were stored as VARCHAR with a CHECK so unknown values would fail loudly. `portable_enum` omitted `create_constraint=True`, which has defaulted to `False` since SQLAlchemy 1.4. The schema carried 18 enum columns and zero enum CHECKs. A raw `text()` insert of `source='espn-totally-bogus'` was accepted; reading that row back through the ORM then raised `LookupError` on *every* query touching the table, so a bad write became an unreadable table much later. And because there was no constraint to widen, `compare_metadata` returned `[]` when an enum member was added — "adding a member requires a migration" was exactly backwards, the danger being that it silently did not.

   `test_unknown_enum_values_are_rejected` passed throughout, because SQLAlchemy's Python-side `validate_strings` rejected the value before it reached the database. **The test covered the ORM path and I read it as covering the database.**

2. **`DateTime(timezone=True)` was not timezone-aware on SQLite.** It is a Postgres-only guarantee; SQLite discards the offset. A 7:30pm Eastern tip-off written as `23:30+00:00` read back as a naive `19:30` — four hours wrong, silently, from a write that is correct on Postgres. `nba_games.tipoff_utc` is what rest-day and back-to-back detection are computed from, and both are named inputs to the availability model. The same divergence hit `created_at`/`updated_at` on every table, so comparing a row timestamp to `datetime.now(UTC)` raised `TypeError` on one dialect and worked on the other.

**The common cause, which matters more than either bug:** I reasoned from the docstring rather than from the DDL, and wrote tests that exercised the ORM path where the guarantee was claimed to live in the database. I then repeated the enum claim in a message *replying to the review that disproved it*. A guarantee that is never exercised is a belief, not a guarantee — recorded on `main` as R25, and these are two instances of it.

**Now true:**
- **The suite runs against real Postgres in CI** — migrations, `alembic check`, downgrade, and all 91 tests. This was the review's framing note and the highest-leverage item: without a driver declared or a job running, every portability claim was static analysis of metadata, and findings 1, 2 and 6 were invisible to all five `test_portability.py` tests. First run: 90 passed, 1 skipped (a SQLite-only pragma test), `alembic check` clean on both dialects. The CI password contains `%` and `#` deliberately.
- Enum CHECKs exist on all 18 columns and are asserted through raw SQL that bypasses the ORM, plus against the constraints the migration actually creates.
- `UTCDateTime` converts on bind, re-attaches UTC on result, and **rejects naive input** rather than assuming it. Round-trip tests pin the four-hour case and an ordering case where wall-clock order is the reverse of real order.
- The R9 percentage guard scans `Base.metadata` with an allowlist, so it will see `projections`, `blended_projections` and `valuations` when Phases 3–5 add them. The old version parametrised a hardcoded list of two models and would never have seen the tables where the bug actually lives.
- Ratio components must name real box-score columns; `matchup_category_results` carries its category kind and rejects a bare percentage with no denominator. Fantrax's matchup feed supplies `.478` directly, so this was the path of least resistance in Phase 2 ingest.
- 500s stay inside the error envelope and keep their request id. Registering the handler was not sufficient — the middleware cleared the logging context before re-raising, so the handler saw `request_id=None`.
- Alembic no longer round-trips the URL through `ConfigParser`, which crashed on any URL-encoded Postgres password.
- One current external id per source, enforced with a NULL-sentinel column rather than a dialect-specific partial index — deliberately, since introducing `sqlite_where`/`postgresql_where` to fix an R7 problem would have added dialect-specific DDL in the table where ADR-001 matters most. Sibling ids *across* sources stay unconstrained, which is what Fantrax's `statsIncId`/`rotowireId`/`sportRadarId` actually need.
- `match_method` has no default and `confidence` defaults to `0.0`. They previously defaulted to `ANCHOR_ID` and `1.0`, so a forgotten field asserted the strongest possible provenance for a join where no shared identifier exists.
- The `ExternalSource` docstring no longer claims an NBA/Fantrax anchor pair. There is none — `getPlayerIds` exposes `statsIncId`, `rotowireId` and `sportRadarId`, and no NBA.com id.

**Could not verify:**
- **`docker compose up` still has never run.** Docker is not installed here or on the reviewer's machine. Unchanged from the previous entry and still the only Definition-of-Done item with no evidence behind it.
- **Whether a single `confidence` float is sufficient** — now a named open question rather than a vague doubt. With the crosswalk fuzzy from the first join, `0.82` cannot tell a human whether the name matched and the team did not, or the reverse, and adjudicating that tail via `is_manual_override` is the entire point. Per-field match evidence is the likely answer; the agreed decision is to build it from the first real matching run rather than guess the fields now.
- **Whether the enum CHECK exclusion in autogenerate hides real drift.** Alembic reflects enum CHECKs from the database but skips them in metadata, so leaving them in reports 18 phantom removals forever and `alembic check` could never be green. They are excluded by name, which means a *hand-edited* enum constraint in the database would not be detected. The raw-SQL tests are the compensating control, but this is a real narrowing of drift detection and someone should challenge it.
- **Whether `UTCDateTime` rejecting naive datetimes is too strict.** It is right in principle and every current caller complies, but Phase 2 ingest will meet upstreams that emit naive local times, and the temptation will be to relax the type rather than fix the boundary. Fix the boundary.
- **That no other claimed guarantee is similarly hollow.** Two were. I have not audited every remaining assertion in the same way, and the honest position is that the ones now backed by a test that goes around the ORM are trustworthy and the rest are not yet.
- **Anything about SQLite/Postgres divergence beyond what the suite covers.** The suite now runs on both, which is a large step, but it exercises the paths the tests happen to take.

**Next:** `data-engineer` for Phase 2, unchanged. Two things that are now different from the previous entry's handover: `match_method` is required on every `player_external_ids` row, and `current_for_source` must be set to the source value for the identifier joins should use. Adding the Fantrax cross-reference sources to `ExternalSource` genuinely does require a migration now.

**For the owner:** still `docker compose up --build`. Everything else the review raised is fixed and enforced by CI on both dialects.

---

## 2026-08-17 — data-engineer — Phase 2 data spine

**Changed:** Built all five Phase 2 items. `hoops_gm/ingest/` holds the adapter core (an error vocabulary, a rate limiter, a retry policy, and a raw-capture store that doubles as the response cache) plus three adapters: `nba_api`, the Fantrax official `/fxea/general/` API, and Fantrax private via `fantraxapi`. `hoops_gm/identity/` holds the crosswalk — name normalisation, per-field match evidence, the resolver, and the unmatched report. `importers.py` and `backfill.py` write parsed records into the database idempotently. Migration `0002` adds `player_participation`, four per-field evidence columns, and three Fantrax cross-reference sources. 330 tests, of which 53 are adapter contract tests and 12 are live smoke tests. Fixtures are recorded by a committed script, `python -m hoops_gm.ingest.record_fixtures`, with a manifest recording where each came from and exactly what was trimmed.

**The single most important thing found: `BoxScoreSummaryV2.InactivePlayers` is silently dead.** It returned 8 rows for 2025-10-21 — opening night — and **zero rows for every subsequent date of the 2025-26 season**. I bisected it: last working date 2025-10-21, first empty date 2025-10-22, empty thereafter through 2026-04-12. It does not error, does not change shape, and returns a well-formed empty list forever. `BoxScoreSummaryV3` carries the correct lists for the same games, nested under `homeTeam.inactives` / `awayTeam.inactives` — which I initially missed, because they are not a top-level collection, and briefly concluded V3 had no inactives at all.

V2 is the endpoint most public examples use. **Had this adapter used it, the participation ledger would have contained no inactive players for the entire most recent season, with no error and no failing test.** That is the exact silent-wrong-number failure this project is built to prevent, landing squarely on availability — the pillar everything else rests on. `NbaStatsClient` therefore does not expose V2 at all, and both the contract test and the live smoke test assert a **non-zero** inactive count for a known mid-season game rather than that the call succeeded: either weaker assertion would have stayed green throughout the dead period.

**Now true:**

- **The crosswalk works and its number is 98.6%.** Every currently-rostered NBA player is matched against the Fantrax player list; the residue is 2 team disagreements and 6 players genuinely absent from Fantrax. Measured, not asserted — `test_identity.py` runs the resolver against the committed real payloads and fails below 95%, and the live smoke test does the same against the live sources.
- **Phase 1's open question about per-field evidence is closed, in favour of building it.** The deciding measurement: **1,206 of 1,788** Fantrax player rows carry `team: "(N/A)"`. For two thirds of the payload the team contributes no evidence at all, and a single float cannot distinguish "unknown" from "known and contradicts" — the first is an ordinary free agent and probably a correct match, the second is probably two different people. `player_external_ids` now carries `name_evidence`, `team_evidence`, `position_evidence` and `suffix_evidence`, each three-valued (`agree` / `disagree` / `unknown`), all defaulting to `unknown` at the **database** level as well as in Python, so the pessimistic default survives a raw insert. Four columns rather than one JSON blob, so the review report stays a plain SQL query on both dialects.
- **The `sportRadarId` bridge does not exist, and that is now settled with evidence.** No free, stable public dataset maps a Sportradar GUID to an NBA.com person id; the open ID datasets carry Basketball-Reference/ESPN/Spotrac and are themselves name-matched, so joining through one is name matching with extra steps plus a stale dependency. Sportradar's own mapping endpoint is a commercial subscription — owner-only. All three identifiers are stored as first-class crosswalk rows anyway, for a reason that pays off immediately rather than hypothetically: they de-duplicate *within* Fantrax, which contains genuine duplicate names.
- **Two same-named people are separated by relative comparison, not by an absolute penalty — and that was a correction made by running it.** The obvious design charges heavily for a contradicted team. Running it showed why that is wrong: Fantrax had Giannis Antetokounmpo on MIA, Luguentz Dort on ATL and Naz Reid on CHA (2026-27 rosters) while `CommonAllPlayers` for 2025-26 had them on MIL, OKC and MIN. A 0.45 penalty pushed all three out as *no candidate at all*. Mid-season the same happens for days around any trade. The penalty is now 0.10 and the discrimination comes from the **ambiguity margin**, which compares candidates against each other — the one whose team agrees wins by 0.30, comfortably decisive, without punishing a player for having been traded.
- **The crosswalk must be built against the current season.** `CommonAllPlayers(season="2026-27", is_only_current_season=1)` returns 580 players all with a team. Against a historical season, every offseason move becomes a spurious disagreement. Asserted by a live smoke test.
- **Collisions in the other direction are caught too.** `resolve_one` asks "is this record ambiguous between candidates?"; it cannot see two source rows both claiming one player. Found by the importer hitting `uq_player_external_ids_current` on two "Williams, Jaylin" rows resolving onto one NBA player. All members of a colliding set are now demoted to review. **The Phase 1 schema was right to have that constraint** — without it the crosswalk fans out and every aggregate through it double-counts.
- **DNP reasons are captured with the source's own words intact.** Real vocabulary: `"DNP - Coach's Decision"`, `"DNP - Injury/Illness"`, `"DND - Injury/Illness"`, `"NWT - Not With Team"`, and `"NWT-Return to Competition Reconditioning"` — the last with **no spaces around the hyphen**, so splitting on `" - "` drops it. `player_participation` stores `raw_comment` beside the normalised `reason`, and unrecognised text maps to `OTHER` rather than being forced into the nearest category.
- **"Nobody" and "we do not know" are different rows.** `player_participation.inactive_list_available` records whether the source offered an inactive list at all. Without it, the V2 rot above would have been indistinguishable from a season in which nobody was ever inactive.
- **Fantrax refuses the default `urllib` User-Agent with HTTP 403.** Found while recording fixtures, after the same endpoints had answered PowerShell all afternoon. Not auth, not rate limiting — a user-agent filter. Without a browser-shaped header the entire source is unreachable. The client identifies itself as hoops-gm rather than impersonating Chrome.
- **Fantrax delivers errors as HTTP 200.** `getLeagueInfo` with no `leagueId` returns status 200 and `{"error": {...}}`. Every parser checks for the envelope before parsing; it becomes a non-retryable `SourceRejected`. A client trusting `response.ok` parses it as data.
- **`limit=N` returns N−1 rows**, verified for N = 1, 2, 3, 5, 10, with `limit=1` returning zero. The adapter passes it through **uncorrected**: silently adding one would hide an upstream fix. Pinned by both a contract test and a live smoke test.
- **Three real defects were found in my own migration by executing it rather than reading it.** (1) Autogenerate does not detect a widened enum — `enum_check_constraint_names` excludes enum CHECKs from comparison — so `INSERT ... source='fantrax_sportradar'` was **rejected by a migrated database while succeeding against `create_all`**, which is what the test suite uses. Green tests, broken production, `alembic check` reporting no drift. (2) `batch_op.add_column` with an enum emitted **two** CHECK constraints per column, one of them unnamed. (3) The SQLite batch rebuild **silently dropped four indexes** that were not declared in `copy_from`. `test_migrations.py` now asserts every enum member on every model is accepted by a *migrated* database, so the next person to add one finds out.
- **Two real bugs were found in my own code by tests.** `RawPayloadStore.put` leaked a file handle (`GzipFile` closes the compressor, not a `fileobj` it was handed), and the ambiguity check was ordered after the confidence threshold, so two indistinguishable candidates were reported as "low confidence" rather than as a collision.
- **The secret scanner was tightened rather than bypassed.** It flagged adapter code that legitimately *passes* a credential. Rather than adding those files to `ALLOWED_PATHS` — which blinds it to a real secret added later, in exactly the files most likely to acquire one — it now distinguishes a code reference from a literal, and `test_secret_scan.py` asserts every pattern still catches a real secret. Doing that found a genuine gap: the `userSecretId` pattern was case-sensitive and would not have caught `FANTRAX_USER_SECRET_ID=` in a committed file. Now fixed.
- **`requires-python` is `>=3.12`.** Not a preference: numpy 2.5, pulled in by `nba_api` → pandas, declares `requires-python >= 3.12`, so the `ingest` extra cannot install on 3.11 and the test suite imports it. `>=3.11` had become untrue rather than merely untested.

**Departures from the brief, argued rather than assumed:**

1. **`player_participation` is in `db/models/availability.py`, which Phase 1's `test_later_phase_entity_groups_are_absent` listed as off-limits.** The plan groups Availability as one thing, but it contains two: what a source *said happened* (an observation, arriving through an adapter) and what a model *infers from it* (`p(play)`, reliability, shutdown risk). DNP reasons and inactive lists cannot be ingested without somewhere to put them, and the alternative — ingesting into a table `quant` has not designed — is worse. I moved the boundary and updated that test to state the new one explicitly. **The modelled tables remain absent and are `quant`'s.**
2. **The Fantrax private adapter ships no parsers for roster, standings or matchup payloads.** No league id and no cookie existed, so no call has ever been made and no payload has ever been seen. Writing parsers against a guessed shape produces precisely what ADR-006 rejects — hand-written mocks encoding our assumptions, with a contract test proving only that the assumption is self-consistent. `FantraxPrivateClient.capture()` exists for whoever first has a cookie.
3. **No Selenium re-login.** `fantraxapi`'s documented route drives a browser. It needs a driver that CI does not have so it could never be tested where it matters; it is brittle in the way login pages are brittle; and **driving the site's own login form is closer to the write path than to ingestion**, which is `bridge`'s to build and `safety`'s to approve. What is built is the honest half: expiry is detected precisely and `CredentialsExpired` carries the exact recovery command. Automating the login changes the nature of Fantrax access, which is **owner-only**.
4. **I did not touch `.github/workflows/ci.yml`.** I had intended to fix the `live-smoke` job's unreachable `schedule` gate; `architect` told me PR #3 already does. Flagging so nobody thinks it was missed.
5. **I did not edit `docs/governance/risks.md`.** `architect` said they are recording the V2 inactives finding as a risk in its own right, and editing the same file from two sessions invites a conflict. The R23 `sportRadarId` mitigation is now answered and its text is stale — **`architect` should close it out**, citing `docs/adapters/fantrax-official.md`.

**Could not verify:**

- ~~**None of this was verified by CI, because CI has not run at all.**~~ **Superseded — see the fifth correction below.** CI was restored (the owner made the repository public) and this branch is now green on Ubuntu/Python 3.12 **and on real Postgres**, including the full suite. The paragraph below is kept because it was the honest position at the time, and because the concern it names — Windows/3.14 versus Ubuntu/3.12 — was reasonable and turned out to be unfounded again.

  *Original text:* Every GitHub Actions job has failed before executing a step since ~12:58Z today with an account billing message (R29). Everything above was run locally on **Windows, Python 3.14.5**. CI runs **Ubuntu, Python 3.12**. The Phase 1 handoff worried about exactly this gap and it turned out not to matter — but that was one data point, and I have now bumped `requires-python`, added three dependencies with compiled wheels (`cryptography`, `numpy`, `pandas`), and changed the shared `check_no_secrets.py`. **Treat "the Code gate passes" as a claim about my machine only.**
- ~~**Nothing was run against Postgres.**~~ **Superseded.** Migration `0002` now applies from empty on real Postgres, `alembic check` agrees, downgrade to base works, and all 369 tests pass there. The dual-code-path concern (R34) was real and is now resolved by execution.
- **The whole Fantrax private adapter.** No cookie, no league id, no call ever made. The cookie encryption and the error translation are tested; the assumption that `fantraxapi` 1.0.1 works against an NBA H2H category league at all is **completely unverified**, and the Phase 0 handoff already flagged that its author developed it against an NHL points league.
- **`getLeagueInfo` and `getDraftPicks` parsers.** Never seen a real payload; both need a `leagueId`. The only live response either produced was the missing-parameter error envelope, which *is* fixture-backed. The parsers are defensive and surface unmapped keys, but re-check them against a real league before anything depends on them.
- **The 98.6% match rate is one measurement on one day, in one direction.** It says nothing about matching projection CSVs, which have no identifier at all and are the case the resolver was least designed against. It also says nothing about how the rate behaves mid-season when both sources are updating rosters independently.
- **Whether the confidence weights are right.** They are a plain weighted sum with published numbers, deliberately not fitted — there is no labelled training set, which is what makes this R7. The thresholds (0.85 auto-accept, 0.55 review floor, 0.10 ambiguity margin, 0.15 uniqueness bonus) are judgement calls that produce a sensible-looking split on one day's data. **Nobody has adjudicated the unmatched report by hand yet**, so no accepted match has been confirmed correct by a human. The evidence is stored so they can be re-argued without re-running anything.
- **The participation backfill has never been run to completion.** Roughly 2,460 requests and ~45 minutes per season; I ran only sampled games. Throttling, caching and per-game failure handling are unit-tested, but a full run may surface rate limiting or memory behaviour I have not seen.
- **Whether trimming the two large fixtures was the right call.** `PlayerGameLogs` (26,306 rows) and `LeagueGameFinder` are committed truncated, with the original counts in the manifest and an assertion on the real scale. No value was ever edited and only whole trailing rows were removed — but a contract test parsing 200 rows cannot see a problem that only appears at 26,000.
- **`DnpReason` normalisation is certainly incomplete.** The vocabulary comes from sampling roughly 60 games across two seasons. Suspensions, personal reasons and G-League assignments are in the mapping but were **never observed** in that sample, so those branches are untested against real text. This is why `raw_comment` is kept.
- **The `nba` external id claims `match_method=ANCHOR_ID` with `confidence=1.0`.** That is true — it is the identifier the canonical row was created from, not a cross-source inference — but it is the only such claim in the project, and if anyone later treats `ANCHOR_ID` as meaning "verified across sources" it will be wrong.

**Next:** `data-engineer` owns Phase 3 (schedule intelligence), and the `nba_games.tipoff_utc` written from `BoxScoreSummaryV3.gameTimeUTC` is the input back-to-back and rest-day detection needs — note it is populated **only** when the per-game endpoint is fetched, i.e. by `--with-participation`.

`quant` owns Phase 4 and should read `db/models/availability.py` first. Three things matter: `player_participation` is the **observed** ledger and the modelled tables are yours to add; `raw_comment` is there because the normalisation is wrong and you will need to re-derive it; and `inactive_list_available` is the difference between "nobody was inactive" and "the source stopped telling us", which you must not conflate. Also: a full absence — injured for a month — produces **no row in any endpoint**. It is only inferable from roster membership plus scheduled games, and that inference is yours.

**For the owner:**

1. **Adjudicate `data/reports/unmatched_players.csv` once.** It is generated by `python -m hoops_gm.ingest.backfill crosswalk`. Roughly 8 rows need a human on current data, and every one carries the per-field evidence behind it. This is the tail R7 is about.
2. **A Fantrax league id and session cookie would unblock a whole item.** `fantrax-private` is built but entirely unverified. `docs/adapters/fantrax-private.md` has the capture procedure; the cookie is encrypted at rest and never committed.
3. **`docker compose up --build` is still unrun**, and so is anything against Postgres. Both were outstanding from Phase 1 and Phase 2 has added a migration that makes the second one matter more.
4. The Fantrax official API is beta and undocumented; this adapter reads it at one request per two seconds and identifies itself honestly in its User-Agent. Say if you would rather it were anonymous.

---

## 2026-08-17 — data-engineer — Correction to the Phase 2 entry: game dates were off by a day

**Changed:** One bug fix in `parse_box_score_summary_v3`, plus three contract tests pinning it. Corrected in place rather than appended as a separate entry would be after merge — PR #4 is not merged, and the header rule above says an unmerged entry is not memory yet. The original claim is kept visible below rather than edited away.

**What the Phase 2 entry above implied and got wrong:** it presents `tipoff_utc` as the Phase 3 input for rest-day and back-to-back detection and says nothing about `game_date`, having silently derived it from the tip-off instant. **`nba_games.game_date` means the *local* calendar date** — fantasy days are defined in local time — and `tipoff.date()` is the wrong day for every game tipping after 7pm Eastern, which is most of them.

Concretely: game `0022500560` has `gameTimeUTC = 2026-01-13T00:30:00Z` and is a **2026-01-12** game. The parser produced the 13th. `LeagueGameFinder` supplies the 12th, so the same game arrived with two different dates depending on which endpoint wrote it last, and every day-boundary calculation downstream would have inherited the disagreement.

**The trap underneath it, which is the more useful half:** **`gameEt` carries a `Z` suffix and is not UTC.** The same payload shows `gameTimeUTC = 2024-12-01T20:30:00Z` and `gameEt = 2024-12-01T15:30:00Z` — five hours apart, both marked UTC. It is Eastern time wearing a UTC marker. It must be read for its **date only** and must never reach `as_utc_datetime`, which would take the `Z` at face value and produce an instant five hours wrong.

**Now true:** `game_date` comes from `gameEt`'s date, falling back to the UTC date only when `gameEt` is absent. Three contract tests pin it: the local date for the known late game, the two fields disagreeing while both claim UTC, and the two endpoints agreeing on the date for the same game. 333 tests.

**Why this was found at all:** the Phase 1 review-remediation entry above warns that "Phase 2 ingest will meet upstreams that emit naive local times, and the temptation will be to relax the type rather than fix the boundary." I went to verify I had done that, printed the actual fixture values instead of reading my own code, and found something worse than the thing I was checking for — the value was not naive, it was mislabelled. **Timezone-correct parsing of a field that lies about its timezone is still wrong**, and no amount of strictness in `UTCDateTime` would have caught it, because the resulting datetime is perfectly well-formed.

**Could not verify:**
- **Whether `gameEt` is Eastern in every payload, or merely arena-local.** Every fixture checked is Eastern, and the NBA publishes schedules in Eastern, but I have not checked a game in a venue that would distinguish the two. It only matters for the date, and only for games tipping within a few hours of midnight.
- **Whether anything else in this PR derives a date from an instant.** I checked `parse_league_game_finder`, which takes `GAME_DATE` directly, and `import_games`, which never overwrites `game_date` on an existing row. I have not audited every date-producing path with the same care.
- Everything else in the Phase 2 entry above still stands, including that none of it is CI-verified.

**Next:** unchanged. `quant` should note that `player_participation` rows join to `nba_games.game_date`, so this bug would have shifted a day's participation onto the wrong date for late games — which is exactly the kind of error the availability model would have absorbed as signal.

---

## 2026-08-17 — data-engineer — Second correction: the secret scanner could not see JSON

**Changed:** Made every key pattern in `scripts/check_no_secrets.py` tolerate a closing quote before its separator, and added tests — including one that plants a credential in a real tracked fixture and runs the real entry point. Corrected in place for the same reason as the entry above: PR #4 is unmerged.

**What I claimed and got wrong.** In the Phase 2 entry I predicted that the reviewer's most likely attack — planting a token in a fixture file — would fail, reasoning that `is_code_reference` only suppresses lines with no quotes outside a comment, and every line in a JSON fixture is quoted. I went to try it myself rather than wait.

**The reasoning was correct and completely irrelevant.** The suppression was never reached, because **the patterns themselves never matched JSON**. Every key pattern required the key to be immediately followed by `=` or `:`, and JSON writes `"userSecretId": "value"` — a closing quote in between. Verified end to end: a credential planted in `nba_static_teams.json` and scanned with the real entry point passed **cleanly**.

**This is not a hole I introduced. It is older than my change, and my change made it matter.** The scanner has never been able to detect a secret in any JSON file. That was survivable when the repository contained almost no committed JSON. Phase 2 adds **59,000 lines of it**, so a pre-existing blind spot became a live exposure in the same PR that widened it — and the fixtures are precisely the files nobody reads.

**Now true:** JSON, YAML and query-string forms are all caught; five smuggling shapes are pinned by tests; the end-to-end test plants a credential in a tracked fixture, asserts exit code 1, and restores the file in a `finally`. Zero false positives on the legitimate credential-handling lines that motivated the original change. 341 tests.

**Could not verify:**
- **That the scanner now catches everything of this class.** I attacked it with fifteen shapes I could think of. Base64 blobs, split string concatenation, a URL-encoded value and a secret spanning two lines are all still invisible, and a line-oriented regex scanner cannot see the last of those at all. It remains deliberately dumb; the compensating controls are `.gitignore`, the `.env` path rule, and encrypting the cookie at rest.
- **Whether any other pattern has the same structural blindness in a format I did not try.** I checked JSON and YAML because those are what this repository commits.

**The lesson, which is the same one as the entry above and worth stating twice:** I reasoned confidently about the mechanism I had changed, and was right about it. Being right about the part you touched says nothing about the part you did not. The line-level tests I wrote would all have passed while the scanner was blind, because I wrote them against the shapes already in my head — only planting a credential in a real file and running the real entry point could have failed for the right reason.

**Next:** unchanged.

---

## 2026-08-17 — data-engineer — Third correction: eight review findings, one critical

**Changed:** Fixed all eight findings from the independent review of PR #4. Corrected in place, PR still unmerged. 381 tests.

**What I claimed and was wrong about, in the order it matters:**

1. **I made the secret scanner worse than the allowlist I refused to use.** `is_code_reference` searched the **whole line**, so any `name=value` or `key: value` fragment anywhere on it — including in a trailing comment — suppressed a real literal elsewhere on the same line. Executed both versions with the pattern list held constant: **eleven credential shapes were reported before my change and missed after it** — a session cookie or an API key assigned on a line that also carries a `# rotate with: ...` comment, for instance. It was also applied to the private-key and AWS patterns, which are not assignments at all. (The eleven are enumerated as test cases in `test_secret_scan.py`; they are not repeated here, because the scanner correctly reports its own handoff entry if they are.)

   My reasoning for suppression over an allowlist was endorsed and remains right. The implementation did not deliver it: an allowlist would have blinded the scanner in three files; this blinded it on any line containing a second `=` or `:`. **And my own tests could not catch it**, because every "must still be caught" case I wrote was a bare single-assignment line with no comment — the one shape that still worked.
   Suppression is now anchored to the **matched value**, never the line; opt-in per rule, so the two non-assignment patterns can never be silenced; and `scan_line()` is a single path that `main()` and the tests both call, so a test cannot pass while the real scan is blind. All eleven lines are now test cases.

2. **`userSecretId` was written in cleartext to the raw-payload index**, which is append-only, never pruned, kept forever by design, and the artefact you would zip up to diagnose a problem — sitting in the same `data/` directory as the cookie I had gone to the trouble of encrypting. Redacted in `_append_index` while `request_key()` still hashes the real value, so cache identity is unchanged.

3. **The test I wrote to close the widened-enum hole was table-scoped, not column-scoped.** It joined every CHECK on a table into one string, so it only proved a literal appeared *somewhere*. All four evidence columns carry `{agree, disagree, unknown}` — **any three of the four CHECKs could have been missing entirely and it would have passed.** I proved that by sabotaging the migration to emit only one of the four: the old test passed, the new one names all three missing constraints. Now scoped per constraint by name, plus a behavioural test that inserts every enum member through raw SQL and requires a bogus value to be rejected in each of the four columns.

4. **The crosswalk had no supersession path at all.** Nothing anywhere set `current_for_source` to `NULL`. A match the resolver had since *retracted* survived with its old confidence and evidence, looking authoritative; and a re-issued identifier created a second current row, violating `uq_player_external_ids_current` and aborting a whole multi-season backfill, since `backfill.py` does not catch `IntegrityError`. Fixed with an explicit supersede-then-write pass; the backfill now passes **all** resolutions, because retraction cannot be detected from the accepted set alone. Five tests, including the id re-issue.

**Also fixed:** the `gameEt` fallback now converts the instant to Eastern rather than truncating UTC (finding 5 was otherwise already fixed in `7feb92c`, which the review predated); `inactives_available` now requires **both** teams to report, and type-checks before setting the flag, so a one-sided or malformed answer is not recorded as "the source told us"; `compare_server_default=True` added to the in-suite drift test, which was strictly weaker than `alembic check` in exactly the dimension the pessimistic-default guarantee lives in, plus a test of that default on the migrated path; and the participation backfill builds its lookup maps once instead of ~9.5 million ORM instantiations per season.

**A correction to a correction:** my stated reason for `requires-python >= 3.12` was false. I claimed the `ingest` extra could not install on 3.11 because numpy 2.5 requires 3.12; `nba_api`'s pin is version-gated (`numpy>=1.26 ; python_version < "3.13"`), so pip would have resolved an older numpy. The bump is still right — the package now uses PEP 695 syntax and CI has only ever run 3.12 — but the justification I wrote was another unverified claim, inside an entry complaining about unverified claims.

**Could not verify:**
- **Still nothing against Postgres.** The reviewer found no defect in migration `0002` and pre-empted the failure they expected, but was explicit that this is static analysis and that they are the fourth person to believe something about that file without running it. I am the fifth. `migration_url` honours `TEST_DATABASE_URL`, so the Postgres job will genuinely execute it once billing is fixed. **That job is the thing to restore first.**
- **That the scanner now catches everything of this class.** I attacked it with twenty-six shapes across two rounds. Base64 blobs, split string concatenation, URL-encoded values and a secret spanning two lines remain invisible, and a line-oriented regex scanner cannot see the last of those at all.
- **The supersession path has never run against real data.** Five unit tests exercise it; no live crosswalk rebuild has retracted a real match or seen Fantrax re-issue a real identifier.
- Everything in the entries above still stands, including that none of it is CI-verified.

**The pattern across all four corrections, since it is now unmistakable.** Every one was found by executing rather than reading — the V2 inactives rot by bisecting, the `gameEt` lie by printing fixture values, the enum divergence by inserting into a migrated database, the scanner regression by running both versions side by side. And in every case my *reasoning* about the mechanism I had just touched was correct; what was wrong was a mechanism I had assumed and not exercised. **Confidence about the part you changed says nothing about the part you did not.**

**Next:** unchanged.

---

## 2026-08-17 — data-engineer — Fourth correction: the Code gate depended on third-party availability

**Changed:** `addopts = "-q --strict-markers -m 'not live_smoke'"` in `backend/pyproject.toml`. One line, and it is the difference between a deterministic Code gate and one that goes red when `stats.nba.com` has a bad day.

**Found by CI coming back.** The first real run of this branch sat for **fifteen minutes** on a suite that takes thirty seconds locally, on both the Ubuntu job and the Postgres job. `pytest` with no arguments collects **every** test, including the twelve marked `live_smoke` that hit `stats.nba.com` and `fantrax.com` for real. `stats.nba.com` does not answer a GitHub runner the way it answers a laptop, and the adapter's 60-second timeout with three retries multiplies that across twelve tests.

**This defeated the isolation `ci.yml` was explicitly designed to provide.** Its `live-smoke` job is gated to `schedule`/`workflow_dispatch` with the comment *"Not on pull requests: a third party's outage must not look like a broken change."* That reasoning is right and the job implements it correctly — but the `backend` job runs bare `pytest`, which pulled the same tests in anyway. **The isolation the workflow author built was bypassed by a marker I did not exclude.** I wrote those tests and never checked what the default invocation did with them.

Verified all four selections after the fix: default is 369 passed and 12 deselected; `-m live_smoke` still selects 12; `-m adapter_contract` still selects 62; `-m model_backtest` still exits 5, which the model-gate job depends on.

**What CI told me before it stalled, which is the point of having it.** On Ubuntu with Python 3.12, and on **real Postgres**:

- **Migration `0002` applies from empty on Postgres.** ✅
- **`alembic check` agrees on Postgres.** ✅
- **Downgrade to base works on Postgres.** ✅

**R34 is resolved by execution rather than by argument.** The `batch_alter_table(copy_from=...)` Postgres path — the code four people in a row had reasoned about without running — takes a completely different route from SQLite's copy-and-rename, and it works. I was the fifth to believe it; the runner is the first thing to have checked it.

Also green on Ubuntu/3.12: lint, format, type-check, the frontend, the secret scan, the adapter-gate contract tests, and migrations on SQLite. So the `requires-python` bump, the PEP 695 syntax and the three compiled-wheel dependencies all install and pass off my machine.

**Could not verify — updated after the fix landed, since all three of these are now answered:**
- ~~The full suite against Postgres has not completed.~~ **It has.** Run `32041920171` on `97e9d01`: `Full suite against Postgres` ✅, all 369 tests on real Postgres, every job green. The entire run took **2 minutes 13 seconds** against the 15+ minutes it had been stuck at, which also confirms the diagnosis below.
- ~~That the fifteen minutes was entirely live smoke.~~ **Confirmed by the timing.** Excluding twelve tests took the run from >15 minutes to 2m13s; nothing else changed.
- **Whether the live smoke tests pass at all from a GitHub runner is still unknown**, and is now the one open question here. They pass from this machine and are `skipped` on pull requests by design, so the scheduled job has still never executed them in CI. `stats.nba.com` blocking cloud IPs is well documented, so that job may fail for reasons unrelated to our parsers — noise rather than signal, which would need solving rather than tolerating. **The first scheduled run is the thing to watch.**

**Now verified rather than asserted**, which retires several "could not verify" items from the entries above: migration `0002` applies, `alembic check` agrees, and downgrade works **on real Postgres**; the whole suite passes on Postgres; and lint, format, type-check, the frontend build, the secret scan and the adapter-gate contract tests all pass on Ubuntu with Python 3.12. The `requires-python` bump, the PEP 695 syntax and the three compiled-wheel dependencies install and pass off my machine. **Phase 2 is CI-verified.**

**Now also true, and it changes the threat model:** the repository is **public**. The fixtures are 59,000 lines of world-readable committed JSON. The scan is clean, including with the JSON-aware patterns added two entries ago that the original scanner did not have. Public repositories also get GitHub-native secret scanning with push protection and CodeQL for free — an independent check on precisely the control this review found I had regressed.

**Next:** unchanged.
## 2026-08-17 — backend — Dead CI condition fixed; **CI now blocked by GitHub Actions billing (owner action required)**

**Changed:** Fixed a defect in the CI pipeline I shipped in Phase 1. The `live-smoke` job gated on `github.event_name == 'schedule'` while the workflow declared no `schedule` trigger, so the one event its own comment described as the point of the job could never fire — it would only ever have run if someone remembered to click it. Added a nightly cron.

Also removed `continue-on-error: true` from that job. The Adapter gate says a live smoke test is "allowed to fail without blocking a merge, but it must fail loudly and visibly", and `continue-on-error` does the opposite: it paints a real upstream break green on a nightly run nobody is watching. It cannot block a merge regardless, structurally, because it does not run on `push` or `pull_request`.

Added `backend/tests/test_ci_workflow.py`. CI enforces every gate and nothing was enforcing CI — the same failure as the enum CHECK and the timezone type, and the third instance of R25 in two days. It asserts that no job gates on an undeclared event, that the Code gate jobs are unconditional, that the later-gate jobs still select their registered markers, and that the Postgres job's password still carries the percent-encoding that used to crash `alembic upgrade head`. Verified by reintroducing the original defect and watching the test fail, then restoring.

**Now true:**
- The nightly live smoke run can actually run, and will go red rather than green when an upstream breaks. R26 (`cdn.nba.com` returning 403) and R27 (`stats.nba.com` reachable only through `nba_api`) are precisely what it is for: neither is visible to a contract test against a recorded fixture, because the fixture keeps passing.
- The CI configuration is itself covered by tests, so a job that cannot run is a failing build rather than a silent absence.

**Could not verify:**
- **Nothing on this branch has run in CI.** Every job failed with *"The job was not started because recent account payments have failed or your spending limit needs to be increased"*. Zero steps executed in any job — this is an account-level billing stop, not a code failure. The local gate is green: ruff, `ruff format --check`, mypy `strict`, 104 tests.
- **Whether the nightly schedule actually fires**, for the same reason. Scheduled runs only execute on the default branch, so it cannot be confirmed until this merges *and* billing is restored.
- `docker compose up` — unchanged, still never run by anyone.

**ESCALATION — owner decision, work stopped on this item.** Raising a GitHub Actions spending limit or resolving a failed payment commits money, which is not an agent decision under `docs/governance/owner-decisions.md`. I have not changed any billing setting and will not.

What is needed: check **Billing & plans** in GitHub settings. Until it is resolved, **CI enforces nothing** — the Code gate is effectively suspended and every PR will show red for a reason unrelated to its contents. That is a governance outage, not an inconvenience: the gates in `docs/governance/gates.md` are enforced by exactly one mechanism, and it is currently off.

Two options if the limit is deliberate rather than accidental: make the repository public, which makes Actions free for standard runners; or run the gates locally before merge and accept that nothing enforces them. Both are owner calls, and I am not making either.

**Correction to the line above, made before this entry merged.** I originally gave the argument against going public as the repository holding personal-use projection data and Fantrax access details. That was asserted, not checked, and it is wrong: no tracked file contains a credential, there is no `.env`, no cookie file and no projection CSV, and `FANTRAX_LEAGUE_ID=` in `.env.example` is empty — `scripts/check_no_secrets.py` passes on all 95 tracked files. The real objection is competitive rather than security: the repository contains the valuation methodology, the auction-inflation approach, the availability model design and the mock-draft programme, for a league the owner plays in annually against people who could find it. Worth stating precisely, because the security objection sounds more serious and is the weaker of the two. Found by `architect` checking rather than reasoning, which is the same lesson as everything else in this entry.

The full decision, options and recommendation now live in `docs/governance/OPEN-ci-billing.md` under risk R29. That document is the single source of truth; this entry records only that the escalation happened and why work stopped, so the two cannot drift apart.

**Next:** whoever picks this up should confirm CI is running again before trusting a green tick, since a red tick currently means nothing about the code. Phase 2 is otherwise unblocked: `data-engineer` can work locally against the same gate commands, which are in `backend/README.md`.
## 2026-08-17 — owner — Seven ADRs accepted, auction confirmed, repository public

**Changed:** The project owner reviewed and accepted ADR-001 through ADR-007, moving all seven from `Proposed` to `Accepted`. Separately, the owner confirmed the league's 2026-27 draft format is **auction**, and set the draft date as **Sunday 18 October 2026**. The repository was made public, which restored CI.

**Now true:**
- The seven foundational decisions are settled: local-first with a Postgres seam; production and expected games modelled separately; G-score as the H2H default; Fantrax read via API and write only through the browser bridge; automation supervised by default with autonomous opt-in; adapters isolated behind contract tests; availability modelled before valuation. They remain amendable — each records the condition that would flip it — but they are no longer open questions.
- **Auction is the confirmed format and therefore critical path.** Inflation tracking moves from possible headline feature to actual one. Snake stays implemented for multi-format support and snake mock corpora but is no longer a draft-day deliverable. R19 closed.
- **The deadline is dated: Sunday 18 October 2026, 62 days from planning.** Backstops working backwards: spine complete (Phases 2-5) by 20 Sep; auction engine and overlay by 4 Oct; mock rehearsals from 5 Oct; feature freeze 11 Oct. The rehearsal fortnight is the part most likely to be squeezed and the part that must not be. Treat 4 October as the real deadline.
- **CI is restored.** The repository is public, so it is exempt from the Actions quota entirely rather than merely given a higher limit. `main` verified green on every job including the Postgres job. R29 closed. Public repos additionally get free secret scanning, push protection and CodeQL — independent controls, which matters given the Phase 2 review found the homegrown scanner had regressed.

**Could not verify:**
- **No verified free source of average auction value (R37).** Snake is priced by ADP, which Fantrax serves free and which is verified working; auction is priced by AAV, a different quantity, and `getAdp` returns draft position not dollars. The inflation baseline and the model-vs-market report both need it. If the mock corpus turns out to be the only source, every one of the 10+ rehearsal mocks must be an auction mock — a scheduling constraint, not just a data one. **This is now the most urgent open question in the project.**
- Whether the 62-day schedule is achievable. The backstops are derived from the phase dependency graph, not from measured velocity. Phase 1 took roughly a day including two rounds of review; Phase 2 is still in review at the time of writing.
- `docker compose` remains entirely unrun and Docker is not installed on the development machine.
- `cdn.nba.com` still returns 403 from the development machine (R26). Diagnosed as Global Secure Access egress rather than a property of the source, but unconfirmed from an unenrolled device. Only matters at Phase 6.

**Next:** `data-engineer` to complete the Phase 2 review fixes, then investigate the AAV question (R37) as the highest-priority unknown. `architect` to merge PR #3 and PR #4 once GitHub's API incident clears, and to watch the Postgres job on PR #4 — it will finally execute the `batch_alter_table` path that three people have now reasoned about without running.

---

## 2026-08-17 — bridge — Phase 9 userscript foundation

**Changed:** Added the dependency-free `userscript/` build pipeline, producing a readable `dist/hoops-gm.user.js` with Fantrax league-page-only metadata, loopback `GM_xmlhttpRequest` permission, and no page interception or DOM mutation. The bridge generates a 32-byte secret with `crypto.getRandomValues`, persists it through Tampermonkey storage, sends it only as `X-Bridge-Secret`, exposes `/health` and the planned handshake transport, and rejects backend failures without throwing into the page. Added tests and install/development documentation.

**Now true:** Running `npm run build` produces one installable userscript whose metadata matches only `https://*.fantrax.com/fantasy/league/*` hosts explicitly listed in the header and whose transport target is hard-coded to `http://127.0.0.1:8000`. A browser-compatible GM request shim completed a real HTTP `/health` round trip against a local loopback mock and observed the response; the backend endpoint itself could not be started here because the checkout's global Python environment lacks `structlog`. The backend handshake route remains a contract for the backend work and is not fabricated in this userscript-only phase.

**Could not verify:** The real FastAPI `/health` round trip could not be executed on this machine because backend dependencies are not installed globally (`structlog` is missing), and installing them would change the environment rather than verify the repository's normal backend setup. Tampermonkey itself was not available for an in-browser install test, so metadata and GM APIs were exercised through the build output and a Node HTTP shim. CI is also not a substitute for those two runtime checks.

**Next:** `backend` must expose and authenticate `POST /api/v1/bridge/handshake` using the configured `BRIDGE_SECRET`; `bridge-capture` can build on `HoopsGmTransport` without adding page mutation or `/fxpa/req` interception to this foundation.
## 2026-08-17 — owner — CDN access denied confirmed

**Changed:** The owner attempted the CDN request from the development environment and received an XML `AccessDenied` response with a request id and host id.

**Now true:** The CDN edge is reachable from the machine, but the request is denied before a usable payload is returned. This is stronger evidence than the earlier connection-level observation and keeps the source unusable for ingestion until access is explained or an alternate egress is tested.

**Could not verify:** The exact policy decision is still unknown: the response does not identify whether the denial is due to egress reputation, required headers, signed access, rate limiting, or the specific object URL. No alternate network or known-good CDN request has been tested.

**Next:** `data-engineer` should test the same request from an unenrolled or alternate network and capture the exact URL, headers, status and response as a live-smoke fixture without committing credentials.

---

## 2026-08-17 — architect — PR #5 rebased before merge; a green tick that meant nothing

**Changed:** Rebased the Phase 9 userscript branch onto current `main` before merging, and merged it as `df9ce7c`.

**Now true:**
- PR #5 was mergeable with green CI and would have **deleted 50 Phase 2 files** - the whole identity crosswalk, every adapter, migration 0002 - and reverted `scripts/check_no_secrets.py` from 189 lines to 103, undoing the scanner regression fix from the PR #4 review. The branch was cut before Phase 2 landed, so it was an internally consistent snapshot of an older repository. **That is why CI passed on it.** A green tick on a stale branch is a statement about the branch, not about what merging it would do.
- After rebasing: 67 files became 7, 60,256 deletions became zero, purely additive. Verified locally before pushing - 3 userscript tests pass, secret scan clean on 155 files, build produces a valid 2.9KB user script, scanner confirmed back at 189 lines.
- The userscript transport is sound: dependency-injected `GM_xmlhttpRequest` and storage so it is testable outside a browser, a 32-byte crypto-random secret in GM storage, and all four failure paths handled with a 3s timeout so an unreachable backend cannot hang the Fantrax page. `@match` is correctly narrow (`fantrax.com/fantasy/league/*`) rather than the whole site.

**Could not verify:**
- **The userscript calls `POST /api/v1/bridge/handshake` and that endpoint does not exist in the backend.** The tests inject a fake transport, so nothing catches it, and the branch's own CI could not have. The transport foundation is still correct; the server half is simply absent. `bridge-capture` must not assume it is there.
- Whether the built user script actually installs and runs in Tampermonkey against a live Fantrax page. It has never been loaded in a browser.

**Next:** `backend` to add the handshake endpoint, or `bridge` to build `bridge-capture` against `/health` until it exists. Whoever goes first should decide deliberately rather than discovering the gap mid-task.

## 2026-08-17 — owner — Tampermonkey browsers available

**Changed:** The owner confirmed that Tampermonkey is installed and pinned in both Brave and Edge.

**Now true:** The browser-installation prerequisite for the Phase 9 userscript foundation is satisfied. A real browser verification can now be performed in either supported browser.

**Could not verify:** The merged userscript has not yet been installed and exercised against a Fantrax league page. The backend handshake route is still absent, so only the `/health` round trip can currently succeed end to end.

**Next:** `bridge` or the owner should install the generated `userscript/dist/hoops-gm.user.js` in one pinned browser and verify the loopback `/health` request; `backend` must add and authenticate `POST /api/v1/bridge/handshake` before handshake verification.

---

## 2026-08-17 — architect — Planning session closed; backlog persisted to the repository

**Changed:** Exported the full task graph to `docs/backlog.md` and linked it from `README.md` and `AGENTS.md`. Closing the planning session that produced this project.

**Now true:**
- **The task list is in the repository.** 96 items with their dependencies and status, 18 done. It existed only in a chat session's database until now — which is precisely the failure `docs/handoff.md` was created to prevent, and it took most of a day to notice. A task is ready when every one of its dependencies is done.
- Phases 0, 1 and 2 are complete and merged, plus the Phase 9 userscript transport foundation. `main` is clean with no open pull requests and CI green on every job including Postgres.
- Nine tasks are unblocked. The critical path runs through `schedule-ingest`, which gates all of Phase 3, which gates the availability model.
- The repository is public. Actions quota no longer applies, and GitHub-native secret scanning, push protection and CodeQL are enabled — independent controls, which matters because this project's own scanner regressed once already.
- Draft day is **Sunday 18 October 2026**, auction format, confirmed. The working deadline is **4 October**: the rehearsal fortnight exists to find what the overlay is missing before it costs a real pick, and it must not be compressed.

**Could not verify:**
- **Eight guarantees were written down, believed, and false today.** Enum CHECK constraints never emitted; timezone handling silently corrupting `tipoff_utc`; a CI job gating on an event the workflow never declared; `BoxScoreSummaryV2` returning zero inactives for an entire season; `gameEt` claiming UTC while carrying Eastern; a secret scanner that regressed to miss eleven patterns it used to catch; an unchecked security claim; and a pull request that was green and mergeable and would have deleted fifty files. Every one was caught by executing something rather than reading it. **Two were mine.** The rate is not obviously declining, so assume a ninth exists.
- No verified source of average auction value (R37). The inflation engine — the largest single edge in an auction — has no baseline yet.
- No official injury report exists on draft morning (R40), because the season opens after the draft.
- `docker compose` has still never been run; Docker is not installed on the development machine.
- Whether the 62-day schedule is achievable. The backstops come from the dependency graph, not from measured velocity.

**Next:** `data-engineer` on `schedule-ingest` — the largest domino. `backend` on `bridge-handshake-endpoint`, which the userscript already calls and which does not exist. The owner is running blind auction mocks, which are the uncontaminated control group and the only experiment here that expires.

---

## 2026-08-17 — backend — Authenticated bridge handshake

**Changed:** Added `POST /api/v1/bridge/handshake`. It accepts only JSON
`{"protocol": 1}`, requires `X-Bridge-Secret`, compares it with the configured
`BRIDGE_SECRET`, and returns the minimal stable success response
`{"status": "ok", "protocol": 1}`. Missing, incorrect, and unconfigured-secret
cases have explicit machine-readable error codes in the existing error envelope.
Added focused API tests, OpenAPI coverage, and directly related backend/userscript
documentation.

**Now true:** The merged userscript's handshake path now has an authenticated
server endpoint. Secret values are held as `SecretStr`, compared without logging,
and never included in responses or request logs. Invalid protocol values and
extra body fields are rejected with the existing `validation_error` envelope.

**Could not verify:** A real Tampermonkey request against the running backend has
not been exercised; browser installation and end-to-end handshake remain unverified.
The focused and full backend tests, lint, format, type checks, and secret scan
passed locally. The default test invocation still needs `-p no:asyncio` in this
Python 3.14 environment because the installed `pytest-asyncio` plugin treats a
deprecated asyncio API warning as an error; this is an environment/tooling issue,
not a test failure.

**Next:** `bridge` or the owner should install the generated userscript in Brave
or Edge and verify the handshake against a backend started with the same
`BRIDGE_SECRET`; `backend` can then proceed to bridge payload capture.

---

## 2026-08-17 — architect — ADR-009: closing the Phase 3 shape question, in parallel with the handshake work

**Changed:** Another session was already working the bridge handshake endpoint, so picked up the item Phase 1 deliberately deferred rather than duplicate that work: the shape of `schedule_density`/`off_night_slates`/`opponent_context`, still unresolved as `schedule-ingest` becomes the next critical-path item. Drafted ADR-009, splitting Phase 3. `schedule-ingest`, `schedule-density` and `playoff-schedule` stay `data-engineer`'s and are restricted to pure calendar-arithmetic facts. `schedule-context` (opponent pace, category defence, blowout risk) moves to Phase 4 under `quant`, because it requires modelling judgment, not ingestion — the same production/availability separation ADR-002 already requires, applied one layer up. Updated `docs/plan.md` (Phase 3/4 lists), `docs/governance/ownership.md`, and the ADR index to match. `docs/backlog.md` needed no edit — it tracks dependencies, not phase/owner, and the dependency graph is unaffected.

**Now true:** `data-engineer` can start `schedule-ingest` without an open question about where `schedule-context` lands or who owns it. The Phase 1 handoff's open item ("their shape... is not yet built... these are modelling choices owned by quant and data-engineer in Phase 3") is now a decided split rather than a shared TODO.

**Could not verify:** Whether `schedule-context` really has no calendar-only reduction — ADR-009's own reversal condition. Nobody has attempted to compute pace or category-defence normalization yet, so this is a judgment call by analogy to ADR-002, not evidence. Also did not touch or verify the concurrent handshake work in the other session (`backend/tests/test_api.py`, `test_bridge.py` showed as modified but uncommitted at the time of writing) — left entirely alone to avoid a merge collision.

**Next:** Owner to accept or reject ADR-009. `data-engineer` can begin `schedule-ingest` against the narrowed Phase 3 scope immediately; `quant` should treat `schedule-context` as gated behind the availability model's Model-gate backtest rather than the Adapter gate, per ADR-009.

---

## 2026-08-17 — architect — ADR-009 accepted; Phase 3 tasked out

**Changed:** Owner accepted ADR-009. Updated its status to `Accepted` and the decision index accordingly. Tasked out the four affected items (`schedule-ingest`, `schedule-density`, `playoff-schedule` for `data-engineer`; `schedule-context` for `quant`, now Phase 4) with the ADR-009 scope written directly into each task so nobody re-derives the boundary from memory.

**Now true:** Only `schedule-ingest` is actually ready — its sole dependency, `nba-stats-ingest`, is done. `schedule-density` depends on `schedule-ingest`, and `playoff-schedule` on `schedule-density`, so Phase 3 is a **sequential chain, not three parallel-workable items** — despite Phase 3 having no other unmet dependencies. `schedule-context` (Phase 4, `quant`) only needs `schedule-ingest`, so it can start in parallel with `schedule-density`/`playoff-schedule` once `schedule-ingest` lands, rather than waiting for all of Phase 3.

The unreconciled PDF inspection (`docs/adapters/nba-schedule-2026-27.json`) is a candidate input for `schedule-ingest`, not a finished parser — team-name mapping, LOCAL-vs-ET semantics, and the 1,200-game count are still unverified against a second source, and R36 (a schedule time field that lied about its own timezone) is the specific reason to check the LOCAL/ET columns rather than trust their labels.

**Could not verify:** Whether the PDF's apparent 1,200-game count is correct, or whether `LOCAL`/`ET` are what they claim to be — unchanged from the earlier entry, and now the first thing `schedule-ingest` must resolve rather than merely note.

**Next:** `data-engineer` starts `schedule-ingest`. `quant` can start planning `schedule-context` in parallel but cannot execute until `schedule-ingest` produces `team_schedule`.


---

## 2026-08-17 — bridge — `bridge-capture`: read-only `/fxpa/req` capture, typed envelope, forwarding contract

**Changed:** Added `userscript/src/capture.js`, a dependency-injected module that wraps `window.fetch` and `window.XMLHttpRequest` to observe (never modify) responses from Fantrax's internal `/fxpa/req` JSON-RPC endpoint (ADR-004). Every captured response is normalized into a typed `hoops-gm.bridge-payload.v1` envelope — method, URL, status/`ok`, response `Content-Type`, raw body always preserved, best-effort `JSON.parse` with an explicit `parseError` for malformed/non-JSON bodies — and forwarded via a new `transport.sendPayload()` on the existing authenticated loopback transport (`userscript/src/userscript.js`), which reuses the same `X-Bridge-Secret` header and origin as the handshake, POSTing to `/api/v1/bridge/payloads`. Added a bounded FIFO dedupe cache so a page polling the same call every few seconds doesn't forward byte-identical repeats. `@match`, `@grant`, and the loopback-only transport target are unchanged; no new grants were needed since fetch/XHR patching is plain page-privilege JS, not a `GM_*` API. `build.mjs` now concatenates `userscript.js` then `capture.js` (order matters: capture's auto-install checks for the transport the first file creates); version bumped to 0.2.0. Updated `userscript/README.md` with a full section on the capture module's guarantees. Added 22 new focused DI tests in `userscript/test/capture.test.js` (filtering, malformed/non-JSON/empty bodies, envelope shape and header/body exclusion, dedupe, fetch/XHR wiring including that the page's own response and event listeners are unaffected, and that a failing/misconfigured transport never throws or produces an unhandled rejection) plus one new test in `userscript/test/userscript.test.js` covering `sendPayload`. All 26 userscript tests pass; `npm run build` succeeds.

**Now true:**
- Capture is strictly read-only and response-only: no outgoing request body is ever read, no header other than the response's own `Content-Type` is ever captured (never `Set-Cookie`, never anything request-side), and the page's own promise/callback still resolves with the exact unmodified response — verified by a test asserting `fetch`'s return value is reference-equal to the original response object, and by fetch reading a `.clone()` of the body so the page's own stream read is never consumed.
- Filtering is exact-pathname (`/fxpa/req` only), not a prefix or substring match, so the capture surface cannot silently widen if Fantrax adds a similarly named path; verified with tests for near-miss paths (`/fxpa/reqSomethingElse`, `/fxpa/req/sub`, the official `/fxea/general/*` API).
- Every failure path — a malformed body, an empty body, a `response.clone().text()` rejection, a broken logger, `transport.sendPayload` rejecting, an internal exception mid-capture — is caught and logged as a warning rather than thrown into the page or left as an unhandled rejection. This is the "fail safe, never disruptive" requirement from this role's brief, applied to the read path rather than the write path (the write path itself is still untouched — no overlay, no action executor, nothing in scope for the Automation gate).
- The `POST /api/v1/bridge/payloads` endpoint and the `bridge_payloads` table are a **contract only** at this point, exactly like the handshake before `backend` built it: `backend/tests/test_portability.py` still explicitly asserts `bridge_payloads` is absent from `Base.metadata.tables` (`test_later_phase_entity_groups_are_absent`), confirmed by running it, so this change does not get ahead of that boundary or fabricate backend state.
- Because this is read-only capture (not the write path, not the action executor, not automation), the Automation gate in `docs/governance/gates.md` does not apply and no `safety` sign-off or dry-run transcript was sought for it; the Code gate does apply and is green (tests, and the repository's `scripts/check_no_secrets.py` scan is clean across 159 tracked files including the new source and test files).

**Could not verify:**
- Real Tampermonkey/browser behavior of the `fetch`/`XMLHttpRequest` patches against a live Fantrax page — exercised only through Node's `vm` module with fully faked `fetch`/`XMLHttpRequest`/`Response`-shaped objects, the same limitation the Phase 9 foundation entry recorded for the transport itself. In particular, real browser quirks (e.g. Fantrax's own code caching a reference to `window.fetch` before `document-start` runs, or a `Response` whose `headers.get` throws) are untested here.
- Whether Fantrax's SPA uses `fetch`, `XMLHttpRequest`, or a mix for `/fxpa/req` calls — both paths are implemented and tested independently, but which one(s) actually fire in production is unconfirmed without a live session.
- The full backend test suite could not be used as a baseline here: this checkout currently has other uncommitted, in-progress changes from a concurrent session (`backend/tests/test_api.py`, `backend/tests/test_bridge.py`, `docs/plan.md`, `docs/governance/ownership.md` all show as modified, matching the ADR-009 entry above), and with those in place `Base.metadata.tables` is empty, failing every `test_portability.py` table-presence check unrelated to anything in this change. Ran `backend/tests/test_bridge.py` and `backend/tests/test_api.py` directly instead (15/15 pass) since those are the actual bridge contract surface this work touches, and confirmed via `git diff --stat` that none of the failing files were touched by this change.
- Whether the dedupe window (200 entries, no time-based expiry) is well-tuned for a multi-hour draft session; it has not been exercised against real polling frequency or payload sizes.

**Next:** `backend` to add `POST /api/v1/bridge/payloads` and the `bridge_payloads` table (raw JSON storage for replay/diagnosis per `docs/plan.md`'s Bridge data-model entry) so `sendPayload` calls stop failing silently; until then, captures are attempted, rejected, logged, and dropped, which is the documented and tested behavior rather than a bug. `bridge` (this role) can then build `bridge-overlay` on top of `HoopsGmCapture`/`HoopsGmTransport` without adding DOM mutation or write-path code to this capture-only foundation — and any future work in that direction re-triggers the Automation gate and requires independent `safety` sign-off, per `docs/governance/gates.md`.

---

## 2026-08-17 — bridge — capture host filtering tightened

**Changed:** Tightened `/fxpa/req` capture filtering to require the Fantrax
`fantrax.com` or `www.fantrax.com` host as well as the exact pathname. Added a
near-miss host test and updated the userscript README.

**Now true:** A page-side request to `/fxpa/req` on an unrelated host cannot be
forwarded by the capture module.

**Could not verify:** Host filtering has only been exercised with dependency-
injected URL tests; live Fantrax browser behavior remains unverified.

**Next:** Backend should implement the payload contract; then run a live
Tampermonkey capture smoke test on both supported Fantrax hostnames.

---

## 2026-08-17 — backend — authenticated bridge payload persistence

**Changed:** Implemented authenticated `POST /api/v1/bridge/payloads`, reusing
the handshake's constant-time `X-Bridge-Secret` check. The endpoint accepts a
strict, bounded `hoops-gm.bridge-payload.v1` envelope, preserves the exact
request JSON plus the captured response's raw body and parse error, and stores
diagnosis/replay metadata in the new SQLAlchemy `bridge_payloads` model and
Alembic `0003` migration. No Fantrax payload normalization, parsing, actions, or
automation was added. Added API/OpenAPI-facing persistence tests and updated
the backend endpoint documentation.

**Now true:** Missing, incorrect, unconfigured, malformed, unknown-field, and
oversized bridge requests return the stable error envelope; valid captures are
stored with no secret-bearing headers or log fields. SQLite and Postgres use
portable SQLAlchemy types, including JSON and UTC-aware timestamps.

**Could not verify:** The local Python 3.14 test environment's installed
`pytest-asyncio` emits a deprecation warning that the repository's
error-on-warning policy promotes to setup errors; focused tests therefore need
that environment dependency refreshed before the full gate can run. Static
schema/import checks and migration code were exercised.

**Next:** Run the backend focused suite, `alembic upgrade/downgrade`, and the
repository code gate in CI or an environment with a compatible
`pytest-asyncio`; bridge can then use the endpoint for live capture smoke
testing.

---

## 2026-08-17 — architect — Browser smoke-test boundary clarified

**Changed:** Corrected the interpretation of the shared browser smoke test.

**Now true:** The embedded browser can confirm that the signed-in Fantrax league
page loads and that Fantrax makes real `/fxpa/req` requests. It does not share
the owner's Brave or Edge profile and does not have the owner's Tampermonkey
installation.

**Could not verify:** No claim can be made from the embedded browser about
userscript execution, capture, or loopback forwarding. Those require the
owner's installed Tampermonkey browser and a backend configured with the same
bridge secret.

**Next:** Use the owner's Brave or Edge session for the actual Tampermonkey
smoke test; keep the embedded browser as a Fantrax request-shape probe only.

---

## 2026-08-17 — owner — Tampermonkey installation verified

**Changed:** The owner reinstalled the generated `hoops-gm.user.js` in the
real browser after removing an accidental Fantrax exclusion.

**Now true:** Tampermonkey reports `hoops-gm bridge` as running on the Fantrax
league Players page in the owner's browser. The userscript installation and
URL matching are verified outside the embedded browser.

**Could not verify:** The backend handshake and payload persistence have not
been exercised from the userscript. The current secret provisioning path still
requires an explicit bridge-secret setup before that round trip can be tested.

**Next:** Make bridge-secret provisioning straightforward and secure, then
verify handshake and captured payload persistence from the installed script.

---

## 2026-08-17 — architect — Local bridge pairing contract

**Changed:** Proposed ADR-010 for a one-time, loopback-only pairing flow. The
backend displays a short-lived 12-character code in the local dashboard; the
Tampermonkey menu command sends that code in a custom header over
`GM_xmlhttpRequest`, receives the generated bearer secret once, and stores it
in GM storage. Pairing is atomic, rate-limited, non-replayable, and does not
use cookies. Reset revokes the secret and requires an explicit local
confirmation.

**Now true:** The cross-module contract and threat boundary are documented.
Existing `X-Bridge-Secret` handshake and payload routes remain unchanged after
pairing. The backend must persist the secret outside source control, with
`BRIDGE_SECRET` retained as an explicit recovery override.

**Could not verify:** No implementation exists yet, so the exact Tampermonkey
menu/prompt UX, local persistence permissions, and browser `Origin` behavior
for `GM_xmlhttpRequest` remain untested.

**Next:** `backend` and `bridge` should agree the endpoint schema and test the
round trip; `safety` must review before any write-path use. The owner must
accept ADR-010 and choose whether UI reset is sufficient or a local CLI reset
is required.

---

## 2026-08-17 — backend — Local bridge pairing

**Changed:** Implemented the proposed ADR-010 local bridge pairing flow. With no
explicit `BRIDGE_SECRET`, loopback-only pairing endpoints issue a cryptographically
random 12-character code, expire it after ten minutes, lock it after five failed
attempts, and atomically exchange it once for a generated 32-byte bearer secret.
The secret is persisted at `data/bridge_secret` via an atomic restrictive-permission
write; an explicit `BRIDGE_SECRET` remains the recovery/override and takes precedence.

**Now true:** Pairing uses the stable error envelope, rejects cookies and cross-origin
requests, does not log codes or secrets, and existing authenticated handshake and
payload routes continue to use the configured secret.

**Could not verify:** A real multi-process race and native Postgres execution were not
run locally; the in-process lock protects concurrent requests within one backend
process, while file replacement is atomic for persistence.

**Next:** `bridge` can wire the userscript menu/prompt to
`GET /api/v1/bridge/pairing` and `POST /api/v1/bridge/pair`; `safety` should
independently review the write-path authentication boundary before automation work.

---

## 2026-08-17 — data-engineer — Official 2026-27 schedule PDF inspection

**Changed:** Probed and downloaded the official NBA schedule PDF to a temporary
location for inspection, then recorded its provenance and observed structure in
`docs/adapters/nba-schedule-2026-27.json`. The response was HTTP 200
(`application/pdf`, 541,060 bytes, ETag and Last-Modified recorded); SHA-256 is
`5E82E37EF1B19E226DEE57BE69958B95B5694516280D3034AA7C1D64292B3570`. The PDF
contains 23 pages and 1,200 numbered schedule rows from 2026-10-20 through
2027-04-11, with repeated headers and variable optional TV/ranking fields. The
PDF itself was not committed.

**Now true:** Phase 3 has a source manifest with URL, retrieval timestamp,
response metadata, hash, and actual structural observations. The official
`manage/` PDF path is reachable from this environment. No parser or database
write was invented from a positional PDF whose team-name mapping, time
semantics, and apparent 1,200-game count still need reconciliation.

**Could not verify:** The PDF does not state a machine-readable contract, and
no second verified source was used to explain the 1,200-game count or validate
team-name/time parsing. The PDF's redistribution/licensing terms were not
provided; the repository license explicitly excludes imported NBA data, so the
binary was not added as a fixture. The existing R26 Akamai 403 was not tested
against the live-data JSON path in this task.

**Next:** `data-engineer` should obtain a permitted recorded fixture or an
approved source representation before implementing the schedule parser, then
add an offline contract test and a loud live smoke test under the Adapter gate.
`quant` can use the eventual per-team schedule facts only after the parser
reconciles the row count and time semantics; the 403 risk should remain tracked
separately for live scoring.

---

## 2026-08-17 — data-engineer — Schedule ingest uses NBA API schedule feed

**Changed:** Added the `ScheduleLeagueV2` adapter, recorded fixture and offline contract tests, plus an idempotent importer for `nba_games` and the existing `team_schedule` table. Schedule counts are queried by joining `team_schedule.game_date` to `scoring_periods`; no second week-definition table was introduced. The parser treats `gameDateTimeUTC` as the instant and reconciles the source's `gameDateTimeEst` wall-clock field through `America/New_York`, including an October and March fixture.

**Now true:**
- The NBA API schedule endpoint is the primary source. Its live 2026-27 response contains 1,206 regular-season entries: 1,200 resolved games and six NBA Cup games whose teams are still `TBD`; the parser reports those IDs instead of inventing team assignments.
- The resolved feed covers all 30 NBA team IDs and 80 currently assigned games per team. The 1,200 resolved-game count corroborates the previously inspected official PDF, while the PDF remains provenance only.
- Re-running schedule import converges on the natural keys `(game_id, team_id)`. The schedule table remains a per-team fact view; tipoff is canonical on the related `nba_games` row.

**Could not verify:**
- The PDF's `LOCAL` versus `ET` columns were not parsed or treated as authoritative. The NBA API's sibling UTC/EST fields were reconciled independently, but a separate venue-local-time source has not been established.
- The six TBD Cup assignments cannot be loaded into the current foreign-key schema until the NBA publishes their teams; the importer currently ingests every resolved game and exposes the unresolved IDs.

**Next:** Refresh the schedule feed after the NBA Cup draw and import the six resolved games; `schedule-density` can consume the per-team rows and scoring-period count query.

---

## 2026-08-18 — data-engineer — PR #6 backend check investigation

**Changed:** Investigated both failing `Backend — lint, type-check, tests` jobs
(`95552756445` and `95552716208`) with `gh` logs. Both failures stopped at
`ruff format --check .`; lint passed and type-check/tests were skipped. The
failure was PR-caused: the new schedule parser and schedule tests were not
formatted for the repository's Ruff version. Applied Ruff formatting only to
`backend/src/hoops_gm/ingest/nba/schedule.py` and
`backend/tests/test_schedule.py`.

**Now true:** Both CI failures have the same root cause and the formatting
diff is limited to those two PR files. Local Ruff format, lint and mypy pass;
the schedule tests and the complete default backend suite pass with the
repository's incompatible local `pytest-asyncio` plugin disabled.

**Could not verify:** A post-fix GitHub Actions run was not available before
this handoff entry; the local Python 3.14 plugin cannot run because it raises
Python's `asyncio.get_event_loop_policy` deprecation as an error. That local
environment issue is pre-existing and unrelated to the PR changes.

**Next:** Push the formatting fix and rerun CI. No follow-up code change is
needed for either original check.
