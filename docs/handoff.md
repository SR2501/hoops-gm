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

---

## 2026-08-17 — bridge — ADR-010 browser-side local pairing

**Changed:** Added the explicit Tampermonkey **Pair hoops-gm bridge** menu
command and its `GM_registerMenuCommand` grant. Invoking it fetches a
loopback-only one-time pairing code without sending `X-Bridge-Secret`, displays
the code in a browser alert, prompts the owner to paste it, and exchanges it in
`X-Hoops-GM-Pairing-Code`. The returned secret is shape-validated and stored
only through Tampermonkey storage; codes and secrets are never sent to the
console. Pairing is never triggered during page load. Existing authenticated
health, handshake, and payload transport dynamically read the stored secret, so
capture behavior resumes after successful pairing without a reload.

**Now true:** The transport has explicit unauthenticated pairing methods and
does not send a bridge-secret header on either pairing request. Tests inject
menu registration, prompt, alert, request, and storage dependencies; they cover
manual-only execution, successful storage, invalid/used-code handling, and an
invalid pairing response. The root and userscript READMEs document the exact
owner flow and the need to rebuild **and reinstall/update** the generated script.

**Verified:** `npm --prefix userscript test` passes (29 tests) and
`npm --prefix userscript run build` succeeds. An independent `safety` review
found no additional secret exposure or automatic trigger and confirmed this
authentication pairing work is outside the action write path, so the Automation
gate's dry-run transcript is not applicable.

**Could not verify:** `python -m pytest backend/tests/test_bridge_pairing.py -q`
could not start any test because the only available Python is 3.14 and the
installed `pytest-asyncio` invokes Python 3.16-deprecated
`asyncio.get_event_loop_policy()` under warnings-as-errors. No compatible
project virtual environment/interpreter exists on this machine; the userscript
contract tests do run.
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

---

## 2026-08-18 — data-engineer — PR #6 Postgres portability follow-up

**Changed:** The post-format CI run passed the original backend check
(`95553580175`) but exposed one Postgres-only failure in the new schedule
test. Its synthetic abbreviations (`T` plus the full NBA numeric ID) exceeded
the existing `nba_teams.abbreviation` `VARCHAR(8)` contract; SQLite did not
enforce that length. Changed only the test fixture to generate unique,
eight-character abbreviations.

**Now true:** The schedule test passes locally, and Ruff format, lint and mypy
remain green. The original two failing checks are fixed; the Postgres failure
was PR-caused by the test data and is addressed in the follow-up commit.

**Could not verify:** Docker is unavailable in the local environment, so the
native Postgres suite cannot be reproduced here. CI must confirm the
cross-dialect fix.

**Next:** Push this test-data correction and rerun the full CI workflow.

---

## 2026-08-18 — data-engineer — PR #6 checks verified

**Now true:** The final CI runs for commit `e26f0f6` passed both original
backend checks, including lint, format, type-check and tests. The Postgres
suite also passed after the fixture correction. The two original failures were
PR-caused, shared the formatting root cause, and are closed; the subsequent
Postgres-only fixture defect was also PR-caused and is closed.

**Could not verify:** Native Postgres could not be run locally because Docker
is unavailable; GitHub Actions supplied the cross-dialect verification.

**Next:** No follow-up is required for these checks.
## 2026-08-17 — architect — ADR-011: strength of schedule sequenced to Phase 5, not Phase 3/4

**Changed:** The owner flagged that strength of schedule (SOS) is missing from the plan entirely, and that it can't be computed until team/player projections exist. Drafted ADR-011 to lock the scope split and sequencing before anyone conflates it with the `schedule-context`/`opponent_context` work already in flight in a sibling session — both consume `team_schedule` and are "about the schedule," but `opponent_context` is defensive quality conditioning `p(play)` (Phase 4, availability), while SOS is opponent quality weighted by fantasy *value* (Phase 5, valuation), and the latter cannot exist before a real valuation does without inventing a placeholder that gets thrown away later — the exact aggregate-contamination failure ADR-008 already names.

Added `strength-of-schedule` to `docs/plan.md` Phase 5 and `docs/backlog.md` (depends on `schedule-context`, `gscore-engine`), and noted on `playoff-schedule`'s backlog entry that its Phase 3 pass is game-count-only — a value-weighted second pass happens later under `strength-of-schedule`, so it isn't silently "finished" twice under different names.

**Now true:** SOS has a named backlog item, a stated dependency chain, and an explicit non-goal (do not build early on a placeholder value) that the sibling `schedule-context` session and future `quant` work can point to instead of re-deriving the boundary.

**Could not verify:** Which SOS formulation (opponent record, per-category defensive rank, pace-adjusted, recency-weighted) actually predicts realized value — deliberately left unresolved in the ADR pending a backtest, per the Model gate.

**Next:** Owner to accept or reject ADR-011. `quant` should treat `strength-of-schedule` as blocked until `gscore-engine` exists; no early work should assume a specific formulation.

---

## 2026-08-17 — architect — ADR-012: per-week game distribution as a draft/trade-facing view

**Changed:** The owner flagged a third, distinct schedule concern: per-week game *count* distribution (front vs. back-loaded team schedules across the season) matters for draft and trade decisions independent of both `schedule-density` (calendar arithmetic) and `strength-of-schedule`/ADR-011 (opponent quality). Drafted ADR-012. Unlike SOS, this needs no valuation and no opponent judgment at all — it's a raw count already available the moment `schedule-ingest` lands — so unlike SOS it does NOT wait for Phase 5. The actual gap: nothing currently consumes it early enough. `schedule-ui` exists but is gated behind the full `availability-model` and framed as availability-adjusted, not raw draft-prep; `draft-recommender` and the auction items had no dependency on schedule data at all.

Added `schedule-ingest` as a dependency of `draft-recommender` and extended `trade-evaluator`'s existing schedule-impact scope (it already depended on `schedule-ingest`) to explicitly cover per-week shape, not just fantasy-playoff-week strength, in `docs/backlog.md` and `docs/plan.md`.

**Now true:** Three schedule concerns are now distinguished by name and phase rather than risking convergence into one under-specified "schedule stuff": `schedule-density` (Phase 3, calendar facts), `strength-of-schedule` (Phase 5, opponent-quality weighted, needs valuation), and per-week game-count distribution (available from Phase 3, feeds draft/trade directly, ADR-012). `draft-recommender` has a schedule dependency where it previously had none.

**Could not verify:** Whether per-week game-count timing carries meaningful marginal fantasy value once `strength-of-schedule` exists, or whether it's dominated by it — the ADR's own reversal condition, deferred to `quant` on evidence rather than decided now.

**Next:** Owner to accept or reject ADR-012. No implementation is scheduled yet — `draft-recommender` and `trade-evaluator` are both later-phase items; this only fixes the dependency graph so the work isn't skipped when their time comes.

---

## 2026-08-17 — owner, architect — ADR-011 and ADR-012 accepted; weekly schedule volume elevated

**Changed:** The owner accepted ADR-011 (strength of schedule sequencing) and ADR-012 (per-week game distribution). The owner clarified that weekly game-count variance is not merely a marginal tiebreaker: a player can have two games in one H2H period and five in another, and for top players that volume difference can swing the matchup. ADR-012 now treats the weekly schedule profile as a first-class draft, trade, and weekly-management input while keeping it separate from long-run player valuation and from opponent-quality SOS.

**Now true:** ADR-011 and ADR-012 are accepted. The schedule work has three explicit consumers with distinct meanings: calendar/density facts, value-weighted strength of schedule after projections, and weekly game-volume management. The plan and backlog now require the weekly profile to expose light/heavy H2H periods, including two-game/five-game weeks and front/back-loaded team schedules, rather than burying it as a tie-breaker.

**Could not verify:** The exact decision threshold for when schedule fit should override a value difference in draft or trade recommendations. That is a product/model calibration question for `quant`; the raw weekly counts are facts, but the recommendation policy must be tested against held-out H2H outcomes.

**Next:** `schedule-density` should preserve weekly counts as a stable, queryable output rather than recomputing them in UI code. Later `draft-recommender`, `trade-evaluator`, and weekly-management surfaces must consume the same schedule-grid contract; `quant` should calibrate recommendation thresholds instead of hard-coding a universal “two games is bad/five is good” rule.

---

## 2026-08-17 — backend — Recursive refresh lineage: schedule/projection/model cohort contract

**Changed:** Added the smallest useful persistence/API contract for refresh provenance, `refresh-lineage` in the backlog. `schedule_context.py` (merged Phase 4 schema, PR #8) already stamps `opponent_context`/`off_night_slates` rows with `model_version`/`schedule_version` per ADR-009's versioning seam, but nothing recorded where those strings come from or let a consumer check whether a claimed version is still current. Added:

- `RefreshArtifactType` enum (`schedule`, `projection`, `model`) and a `refresh_runs` table (`db/models/lineage.py`, migration `0005`) — a registry of when an artifact was last (re)computed at a given version, idempotent by `(artifact_type, version)` so a re-run that changes nothing does not open a new cohort. History is retained; "current" is the latest `refreshed_at` per artifact type.
- `hoops_gm.db.lineage` — `record_refresh`, `current_refresh`, `content_fingerprint` (a stable content hash for deriving a version label from a set of rows), and `check_cohort`, which reports `"current"` / `"stale"` / `"unknown"` per claimed version without deciding whether a mismatch is fatal — that stays the caller's policy.
- `GET /api/v1/lineage/current` and `POST /api/v1/lineage/validate` (`api/routes/lineage.py`) — the read/validate surface over the registry. An empty claim (no fields supplied) is never `accepted`; asserting nothing must not read as "everything is fine".
- `import_schedule` now registers a schedule refresh as a side effect: the version is a content fingerprint over that season's `team_schedule` rows, so two imports of identical facts converge on the same registered version rather than advancing "current" for no reason (test: `test_schedule_import_registers_a_refresh_that_converges_on_re_import`).

Explicitly out of scope, by design: this does **not** implement SOS convergence (ADR-011), p(play), or any projection/model computation. `PROJECTION` and `MODEL` artifact types are registered and checkable today but nothing writes them yet — that remains `quant`'s call under the Model gate when `gscore-engine`/`baseline-model` land. This also does not modify the already-merged `schedule_context` schema (no FK from `opponent_context.schedule_version` to this registry) — `quant` is responsible for stamping its own rows consistently with what `/api/v1/lineage/current` reports, and adding referential enforcement there is a separate, larger change deliberately not taken here to avoid speculative schema redesign.

**Now true:** A downstream consumer can ask "what is the current schedule/projection/model version" and "does my claimed cohort still match" through one small, generic contract instead of trusting a free-floating string. `import_schedule`'s refresh registration is idempotent and content-derived, matching the same natural-key idempotency discipline the rest of `ingest/importers.py` already uses. 22 new tests added (21 in `test_lineage.py`, 1 in `test_schedule.py`); full backend suite (432 tests total, up from 410 before this change), ruff, ruff format, mypy strict, `alembic upgrade head` from empty, and `alembic check` (no drift) all pass locally.

**Could not verify:** Native Postgres was not exercised locally (Docker unavailable, consistent with every prior handoff entry on this point); the new enum column and JSON column follow the exact pattern already proven portable elsewhere in the schema, but CI's Postgres job is the actual check. Whether a content fingerprint over `team_schedule` rows is the right granularity for a schedule cohort long-term is also unverified — it changes whenever any team's game, date, or opponent changes for that season, which is deliberately coarse; a consumer needing per-team or per-game-level staleness (rather than whole-season) is not served by this and would need a finer-grained registration, which was not built speculatively here.

**For `quant`:** this registry is a `backend`-owned mechanism, not a model. It does not choose what "current" should be, does not validate that a `schedule_version`/`model_version` you stamp is *correct*, and does not implement any part of ADR-011/ADR-012. When `opponent_context`/`off_night_slates` computation exists, call `record_refresh(artifact_type=SCHEDULE, ...)` is already done for you by `import_schedule`; you additionally register your own `MODEL` refresh when the availability model version changes, and read `GET /api/v1/lineage/current` (or call `current_refresh`/`check_cohort` directly in-process) before trusting a `schedule_version` you did not just compute yourself.

**Next:** `quant` should register a `MODEL` refresh the first time the availability model produces a version, and consult `check_cohort` before persisting `opponent_context` rows against a `schedule_version` it did not just observe as current. `data-engineer` should decide, when `schedule-density`/`schedule-context` are actually built, whether the whole-season fingerprint granularity here is sufficient or whether a finer-grained (per-team, per-week) version is needed — flagged above as unverified rather than assumed.

---

## 2026-08-17 — backend — PR #9 Postgres-only test isolation fix

**Changed:** PR #9's Postgres CI job failed with `assert 'xhr' == 'cache-storage'` / `assert 'xhr' == 'manual-export'` in `test_bridge_payloads.py`. Checked first whether this branch caused it: the identical failure reproduces on the latest `main` push (PR #8, "Phase 4: schedule-context schema") — this was pre-existing, not introduced by the refresh-lineage work, and just hadn't blocked a merge before now.

Root cause: `conftest.py`'s `client` fixture created the schema (`Base.metadata.create_all`) but never dropped it first. On SQLite, isolation happens for free because each test's `settings` fixture builds a URL from a unique per-test `tmp_path` — a fresh database file every time. `TEST_DATABASE_URL` (what CI's Postgres job sets) points every test at the *same* external database instead, so rows from an earlier `client`-based test in the same module persist into the next one. `test_bridge_payloads.py`'s cache-storage and manual-export tests each run an unfiltered `session.scalar(select(BridgePayload))` and got back a leftover `source="xhr"` row written earlier in the file by `test_payload_persists_exact_envelope_and_raw_diagnostic_fields`, instead of the row they had just inserted.

Fixed by adding `Base.metadata.drop_all(...)` before `create_all` in the `client` fixture — the same guarantee the `database` fixture already gives `session`-based tests. Deliberately did not add a matching teardown drop: `test_readiness_degrades_when_the_database_is_unreachable` intentionally swaps `app.state.database` for an unreachable one mid-test, and a teardown drop against that engine raised instead of cleaning up when tried. Every test already drops before its own use, which is sufficient.

**Now true:** PR #9's full CI is green, including both Postgres jobs (~2m20s–2m35s each). Full backend suite (432 tests), ruff, ruff format, and mypy strict all pass locally. Scope was kept to the isolation fix only — no changes to the lineage contract itself, no broader test-suite audit.

**Could not verify:** Whether any other `client`-fixture test elsewhere in the suite was silently relying on the old, unisolated behavior (accumulating rows across tests) rather than merely being unaffected by it — none surfaced as a new failure locally or in CI, but that is absence of evidence rather than a proof of absence. Docker remains unavailable locally, so the fix's effect on Postgres was verified only through CI, not a local run against real Postgres.

**Next:** No further action expected on this specific fix. If another Postgres-only failure surfaces in a `client`-based test elsewhere, the same class of bug (unfiltered query against a shared, un-isolated Postgres test database) is the first thing to check.

---

## 2026-08-17 — bridge, backend, safety — Userscript 0.5.0 update and live capture path

**Changed:** Replaced the "reinstall in Tampermonkey's editor after every
rebuild" workflow with the auto-update path implied by ADR-010: `npm run
build` in `userscript/` now reads `@version` from `package.json` (previously
hardcoded separately in `build.mjs`, which had already drifted once) and
stamps `@updateURL`/`@downloadURL` onto the built file, both pointing at a
new loopback-only backend route, `GET /bridge/userscript.user.js`. That route
lives unversioned next to `/health` (it's a static-file surface, not part of
the `/api/v1` JSON contract), reads `userscript/dist/hoops-gm.user.js` fresh
off disk on every request via a setting (`Settings.userscript_dist_path`, not
a module-level constant, so tests can point it at a throwaway file), and
returns a clear, actionable `404` (`X-Bridge-Error: userscript_build_missing`,
`detail` naming the exact `npm install && npm run build` to run) when the
file is absent — the failure mode the owner's live log actually hit. Response
headers set `Cache-Control: no-store` so neither an intermediate cache nor
Tampermonkey's own check can serve a stale build. Extracted the loopback-host
check that bridge pairing already had into a shared `hoops_gm.api.security`
module so this route and pairing share one definition of "local" rather than
diverging. Integrated the verified bridge 0.5.0 live fixes: service-worker-
hidden views now produce bounded, deduped `rendered-view` captures after
initial settle, SPA navigation, and rate-limited visible DOM changes; the
backend accepts that source; and bridge authentication normalizes both
environment-loaded `SecretStr` values and runtime-paired plain strings before
the same constant-time comparison.

**Now true:** The one-time install step in `userscript/README.md` and the
root `README.md` now targets `http://127.0.0.1:8000/bridge/userscript.user.js`
directly (installable from that URL in the browser) instead of the generated
file path, and is genuinely one-time going forward: a source change is now
`npm run build` (after bumping `package.json`'s `version` — an unchanged
version is invisible to Tampermonkey's own comparison, not merely slow) plus
keeping the backend running, and Tampermonkey's own update check does the
rest. New backend tests (`test_userscript_serving.py`) cover the missing-build
404 with its exact detail text, a present build served with the right
content-type/cache header, a non-loopback caller rejected with the
`app`/`client` test fixtures deliberately bypassed (built via `create_app`
directly with `environment="development"`, since the shared fixtures always
force `environment="test"` to satisfy Starlette's synthetic `TestClient` host
— that escape hatch meant this exact 403 branch, and pairing's equivalent
branch, had zero prior coverage), and — the specific ADR-010 guarantee this
task called for — that neither a configured `SecretStr` nor a runtime-paired
plain-string `bridge_secret` appears in the served bytes. A new userscript test
(`test/build.test.js`) runs the real `build.mjs` and asserts `@updateURL`/
`@downloadURL` are present, identical, and loopback; freezes the legacy script
identity, storage key, match/grant/connect/noframes permission surface; checks
package/package-lock version agreement; and rejects hex-64 or base64url-43
secret-shaped literals in the output. The complete userscript suite passes
(63/63), the full backend suite passes against this worktree's explicitly
pinned source (417/417, 12 deselected), and ruff check/format, strict mypy, and
`check_no_secrets.py` are clean. A
`userscript` CI job was added — there was none before, so these new tests
would otherwise never run in CI; `test_ci_workflow.py`'s own coherence check
still passes against the edited `ci.yml`. Live owner verification persisted
successful automatic `rendered-view` rows for roster, players, and a paginated
players view, plus a separate `manual-export` row; the synthetic test row was
removed. The served script reported the frozen identity, version `0.5.0`, and
matching loopback update/download URLs.

**Could not verify:** The owner verified live capture and the served 0.5.0
metadata, but not a complete background-update cycle from one installed
version to a higher one; Tampermonkey's real update interval and prompt
behaviour remain unmeasured. The Cache Storage watcher remains best-effort and
was not needed for the successful live rendered-view path. Rendered-view
capture forwards sanitized but otherwise broad league-page markup over
loopback, including links and data attributes; it removes active elements and
form state but does not redact every possible attribute token. No Postgres
service was available for local validation, so issue #11's pre-existing test
isolation failure remains separately tracked. This machine also has a stale
editable install pointing at a sibling worktree: bare `python -m pytest` can
silently test the wrong source, so all reported backend evidence explicitly
prepended this worktree's `backend/src` to `PYTHONPATH`.

**Next:** Owner should verify one real background update by bumping beyond
0.5.0, rebuilding, and confirming Tampermonkey replaces the installed script
without a manual reinstall. Independent `safety` review signed off this
read-only capture loop after checking scope, clone-only DOM handling, timing
and size bounds, secret containment, fail-safe transport failure, and the
absence of clicks/submits/action execution. That precedent is narrow: the
timer-driven pattern is safe only because it observes and posts to loopback;
giving it any Fantrax action executor requires a new Automation-gate review,
all write-path guardrails, and the owner-only first-live-action decision.

---

## 2026-08-17 — data-engineer — `injury-report-ingest`: NBA official injury report PDF adapter

**Changed:** Built the `injury-report-ingest` backlog item end to end. There is no injury-report API — the NBA publishes a PDF to `ak-static.cms.nba.com`, updated irregularly through the day — so this is a document adapter, not a JSON one. Added `backend/src/hoops_gm/ingest/injury_report/` (`client.py` for transport, `parser.py` for the PDF table extraction, `models.py` for the parsed dataclasses), a new `injury_report_entries` table (migration `0006`, following merged refresh-lineage migration `0005`) and importer (`import_injury_report_entries`), a real captured fixture (`nba_injury_report_2025-11-01_0530pm.pdf`, 7 pages, 14 matchups), 14 offline contract tests and 2 live smoke tests. Full Code and Adapter gates pass locally: ruff format/lint clean, mypy strict clean on 81 source files, full default suite green (446 passed, 14 live-smoke tests deselected), the recorded-fixture adapter suite green (82 passed), and the separately invoked live smoke suite green (14 passed, including the 2 new injury-report checks) against the real source as of this session.

**Now true:**
- The report cannot be read by extracting text top-to-bottom. Verified against the real capture: when a player's `Reason` cell wraps to two lines, the report **vertically centres** the shorter `Player Name`/`Current Status` cell inside that row's full height rather than top-aligning it — so the Reason's first line prints *above* the player's own name, and a naive reader would attach it to the *previous* player. The parser instead derives column x-boundaries from page 1's own header labels and row y-boundaries from each page's own drawn ruling lines (present only under Name/Status/Reason, never under the forward-filled Date/Time/Matchup/Team columns), then joins every physical line inside one cell's height with a space. This is the single most important finding in this adapter and is fully written up in `docs/adapters/nba-injury-report.md`.
- The filename format has (at least) two eras: hourly-on-the-hour before 2025-12-22 ET, 15-minute granularity after. Verified live both ways. The legacy filename only encodes the hour, but the report's own masthead consistently reads `:30` past it — `Injury-Report_2025-12-01_01PM.pdf`'s masthead says `1:30 PM`. Masthead cross-verification (added specifically so a stale/mismatched capture cannot silently be read as the wrong timestamp) tolerates 45 minutes for exactly this reason.
- A missing report is not always HTTP 404. Verified live: an off-season date (2025-08-15, months before any report existed) returns **403 Forbidden**. Both codes are folded into one `ReportNotAvailable` (a `SourceRejected` subtype), documented as evidenced fact rather than assumed.
- `"NOT YET SUBMITTED"` rows (a team with no filed report yet — 5 of them in the captured fixture, across 3 different matchups) are preserved as their own marker status (`InjuryReportStatus.NOT_YET_SUBMITTED`) with no player name, never invented as a player entry and never dropped. `InjuryReportParseResult.player_entries` excludes them for a caller that only wants designations.
- The status vocabulary (OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, AVAILABLE) is treated as closed, unlike `DnpReason`'s free text: an unrecognised sixth value is a loud `SourceContractError`, not an `OTHER` bucket, because the league's own reporting policy names exactly five designations.
- Team, game and player resolution on `injury_report_entries` are all best-effort nullable FKs, never guessed. Team/game resolve from the `Matchup` tricode (an exact match against `nba_teams.abbreviation`) rather than the free-text `Team` column; which tricode is "this" row's team is derived from team order of appearance within the matchup block (away always listed first, verified against the real capture). Player resolves via the existing `identity.names.normalize_name` crosswalk, disambiguated by current team, left `NULL` on any remaining ambiguity per R7.
- `injury_report_entries` is deliberately **not** versioned like `opponent_context`/`off_night_slates` (ADR-009): it is the injury-report analogue of `team_schedule` (data-engineer, Adapter gate, ingested fact), not of `schedule-context` (quant, Model gate). It carries no `model_version`/`schedule_version` because it asserts nothing beyond what the league published; `injury-status-conversion` is where a modelled quantity built from this table would carry that cascade, not here. State the claim precisely rather than gesture at it: neither ADR-011 nor ADR-012 actually names a "refresh/version cascade" mechanism by that phrase — the versioning pattern lives in `db.models.schedule_context` and is governed by ADR-009's ingested-fact/modelled-output boundary, which is the discipline actually being respected here.
- `(report_timestamp, team_raw, player_name_raw)` is the natural key: a report re-ingested twice converges (idempotent), while a later capture at a genuinely different timestamp is retained as real history, never overwriting the earlier row — the whole point of the table per the backlog item's "full status history per player per game" requirement.
- Added `pdfplumber==0.11.10` to the `ingest` extra, pinned exactly like `nba_api`/`fantraxapi`: the parser depends on its word-position and ruling-line extraction behaviour directly, and an upgrade silently changing that behaviour is exactly the kind of drift ADR-006 exists to catch. Deliberately did **not** add `tabula`/Java, unlike the prior-art packages consulted (`johngoodhand/nba-injury-report-pdf-to-df`, `mxufc29/nbainjuries`) — `pdfplumber` is pure Python and needs no JVM in CI.
- Found and fixed a pre-existing gap while adding the fixture: `test_adapter_contracts.py::TestFixtureManifest` only globbed `*.json` on disk, so a `.pdf` fixture could exist without ever being checked against the manifest. Widened the glob to include `*.pdf`.
- Found and fixed a duplicate-index bug in my own first draft of the ORM model: `mapped_column(index=True)` on `report_timestamp`/`game_date` plus an explicit same-named `Index(...)` in `__table_args__` collided under `Base.metadata.create_all` (SQLite raised "index already exists"). Removed the redundant explicit entries.

**Could not verify:**
- Whether the 2026-27 season will keep the current 15-minute filename granularity, or the NBA official CMS keeps the same URL path at all — no announcement of the prior format change was found anywhere, so there is no reason to expect advance notice of another one. The two live smoke tests (`TestInjuryReportIsAlive`) exist specifically to catch this; treat their failure as "check `docs/adapters/nba-injury-report.md` and re-derive the format," not as a flaky test.
- Whether the 403-for-missing-report behaviour generalises to every kind of "no report" case, or is specific to pre-season dates. Only one negative case (an off-season date) was tested live; an in-season, never-published historical timestamp returned a normal 404 during development probing, so both codes are handled, but the full space of "why does this CDN 403 instead of 404" was not explored beyond what was needed to make the live smoke test pass honestly.
- The live match rate of the player-name crosswalk against a full day's real report rather than the tiny two-player synthetic crosswalk used in the offline import test. A live smoke test asserting a specific match-rate threshold (matching the pattern `TestCrosswalkAgainstLiveData` already uses for the Fantrax/NBA crosswalk) was not added, because doing so honestly needs a live-ingested `players`/`nba_teams`/`nba_games` set from `nba-stats-ingest`/`schedule-ingest`, not a report parsed in isolation — worth adding once `injury-status-conversion` or a real backfill run needs the number.
- Whether the two-team-per-matchup, away-team-listed-first ordering assumption used to disambiguate a tricode holds for every matchup shape the report can produce (e.g. the NBA Cup's in-progress/TBD team slots the schedule adapter already had to special-case). Only ordinary two-resolved-team matchups appear in the captured fixture; an NBA Cup game with an unresolved team would currently just fail to resolve `team_id`/`game_id` (both left `NULL`), which is the safe default, but was not specifically exercised.

**Next:** `injury-status-conversion` can now be unblocked to consume `injury_report_entries` alongside `player_participation` — its backlog dependency (`injury-report-ingest`, `participation-ledger`) is satisfied. A scheduled backfill/poll of the live endpoint (which report timestamps to actually fetch, on what cadence) is explicitly out of scope here — this unit is the adapter and its import, not automation, and any scheduling belongs to whichever later item drives it (`lineup-autoset`'s pre-lock refresh is the nearest named consumer in the plan). `preseason-news-ingest` remains a separate, still-`pending` item: this adapter covers nothing before the season's first game, by design (R40).

---

## 2026-08-17 — owner, architect — ADR-012 amendment: sparse event weeks and trade targets

**Changed:** The owner added an important operational consequence to the accepted weekly schedule decision: In-Season Tournament and All-Star-break periods are often sparse across the league, so schedule value is relative to both a team's normal weekly distribution and the league-wide period baseline. Updated ADR-012, the draft plan, and `trade-evaluator`'s backlog scope. Trade analysis must surface schedule-driven targets and high-value weeks, not reduce schedule to a generic rest-of-season adjustment.

**Now true:** The shared schedule-grid contract must label or make detectable sparse league-wide periods, including tournament and All-Star-break weeks, and expose per-player/per-team counts against both baselines. A player with an unusually high count in a sparse period can be materially more valuable for that H2H matchup; a low-count player can become a trade target or liability even when their rest-of-season value is unchanged.

**Could not verify:** The exact sparse-period thresholds and which scoring periods the league's Fantrax configuration will use; these require the imported `scoring_periods` and league settings rather than calendar assumptions.

**Next:** `schedule-density` should preserve the raw weekly counts and event-date facts needed to derive these comparisons. `trade-evaluator` and weekly-management surfaces should consume the same contract and calibrate target thresholds on observed H2H outcomes.

---

## 2026-08-17 — owner — Local browser bridge paired

**Changed:** The owner successfully completed the one-time Tampermonkey pairing
command against the locally running backend.

**Now true:** The userscript and backend share a locally provisioned bridge
secret without putting it in source control or asking the owner to edit `.env`.
The protected local secret file exists and the backend health endpoint remains
available.

**Could not verify:** No Fantrax payload has reached `bridge_payloads` yet; the
table exists and currently contains zero rows. Pairing proves the authentication
exchange, not read-only `/fxpa/req` capture or persistence.

**Next:** With the paired script active, navigate normally between Fantrax
Players, Roster, and League pages, then check that a captured payload appears
in `bridge_payloads`.

---

## 2026-08-17 — owner, architect — Historical rules baseline and mock-data block

**Changed:** Recorded the owner-provided 2025-26 Fantrax rules as
`docs/league/2025-26-rules-baseline.md`, explicitly marked historical rather
than current. Updated `blind-mocks` and R37 after the owner found no live mock
site, including no auction mock lobby.

**Now true:** The project has a concrete provisional baseline for 10-team,
14-player, 9-cat, daily per-player-lock auction-league behavior, including a
$200 auction budget and the historical waiver timing. The record exposes a
material conflict: the Fantrax export says four weekly claims while written
rules say three. The mock corpus is accurately marked externally blocked; no
simulated clearing prices will be laundered into market evidence.

**Could not verify:** Any of these settings for 2026-27, including league size,
weekly pickup cap, waiver time, playoff dates, and auction clock. The current
Fantrax settings remain the required source of truth. When mock lobbies will
open, and whether a free AAV source exists, are also unknown.

**Next:** `league-settings-ingest` must reconcile the current Fantrax settings
against this baseline. Resume observation-only auction mocks as soon as a real
lobby becomes available; until then, pursue published AAV sources without
mixing them into production or availability layers.

---

## 2026-08-17 — bridge — page-world capture bridge for Chromium Tampermonkey

**Changed:** Replaced capture auto-installation from Tampermonkey's isolated
world with a minimal page-world observer. The observed zero-row result after a
successful pairing is consistent with the original isolated-world
`window.fetch`/`XMLHttpRequest` patches not affecting Fantrax's page-world
globals in Brave and Edge. The new self-contained hook is injected with
Tampermonkey `GM_addElement` (the CSP-safe path), observes only exact
`fantrax.com`/`www.fantrax.com` `/fxpa/req` responses, and emits a narrow
response-only `postMessage` record. The isolated-world receiver verifies
same-window source, exact current origin, per-load channel, exact schema and
primitive fields, repeats the exact endpoint filter, then uses the existing
GM-privileged authenticated transport. No secret, backend address, request
body, headers, cookies, overlay, action, or write code enters page world.
Compatible managers without `GM_addElement` use a temporary-script fallback;
if site CSP rejects it, capture warns rather than claiming success. Updated
the userscript README with this root cause, CSP/execution-mode behavior, and
an owner-run live check.

**Now true:** Page-world fetch and XHR hooks, source/origin/channel/schema
validation, malformed/cross-origin/lookalike event rejection, and response
field minimization are unit tested. `npm --prefix userscript test` passes all
32 tests and `npm --prefix userscript run build` succeeds. Forwarding remains
entirely in Tampermonkey's isolated GM context, and the only added grant is
`GM_addElement`.

**Could not verify:** A real Brave/Edge/Tampermonkey page-world injection and
payload persistence run has not been performed in this session. The owner
must rebuild/update the script, reload the Fantrax tab, visit Players/Roster/
League, and check `bridge_payloads`; this entry does not claim that live check
has passed. The temporary inline-script fallback can be CSP-blocked by design,
so a browser lacking `GM_addElement` must report its non-sensitive warning.

**Next:** Owner repeats the documented live capture check and reports only
row-count/result plus non-sensitive Tampermonkey warning text if it fails.
Bridge should diagnose any remaining browser-specific injection behavior from
that result; no write-path work is involved, so the Automation gate remains
out of scope.

---

## 2026-08-17 — bridge — service-worker-owned `/fxpa/req` traffic: Cache Storage watcher + guaranteed manual export

**Changed:** The owner's live check (previous entry) found the page-world
fetch/XHR hook still healthy-but-empty: DevTools traced the relevant
`/fxpa/req` calls to an initiator of `fx-sw.js` — Fantrax's own service
worker, not page script. A service worker executes in its own global scope,
which no page-injected script (Tampermonkey isolated or MAIN-world) can
instrument; `window.fetch`/`XMLHttpRequest` patching can only ever see
requests page script itself issues, so it structurally cannot see one the
service worker issues on its own. This is a platform boundary, not a bug in
the existing hook, and I did not attempt to fake otherwise (e.g. unregistering
Fantrax's service worker or registering a competing one for the same scope
was considered and rejected: both would alter Fantrax's own behavior, which
is out of scope for a strictly observational bridge).

Implemented two additions in `userscript/src/capture.js`, both reusing the
existing `bridge_payloads` envelope contract:

1. **Cache Storage watcher (best-effort, automatic).** The page-world hook
   now also polls `window.caches` every 5 seconds while the tab is visible
   (skipping entirely when `document.visibilityState === "hidden"`, so it
   never competes with Fantrax's own already-throttled background-tab
   polling), matching entries against the same exact `/fxpa/req` filter with
   `{ignoreMethod: true}` so a cached `POST` entry is still found, and
   publishing any match as `source: "cache-storage"` over the same
   `postMessage` channel as `fetch`/`xhr`. This is opportunistic: it depends
   entirely on whether Fantrax's service worker persists responses in Cache
   Storage (a common Workbox pattern), which is **not yet verified against
   the live site**. IndexedDB is the same idea in principle but was
   deliberately left unimplemented — its schema would have to be
   reverse-engineered per Fantrax version, a much likelier source of silent
   drift than Cache Storage's simple Request/Response shape.
2. **Manual export (guaranteed, owner-triggered).** A new Tampermonkey menu
   command, "hoops-gm: capture current Fantrax view", runs entirely in the
   isolated world (DOM access is not CSP-restricted) and exports whatever is
   already rendered: it prefers an exposed client-state global
   (`__NEXT_DATA__`, `__NUXT__`, `__INITIAL_STATE__`, `__APOLLO_STATE__`, in
   that order) as structured JSON, else clones the page's main content region
   (`main`, `#root`, `#app`, `body`), strips `<script>`/`<style>`/`<noscript>`
   from the clone, and forwards the result (bounded to 500,000 chars) tagged
   `source: "manual-export"`. This never depends on which layer produced the
   underlying data, so it is the one path guaranteed to work regardless of
   `fx-sw.js`'s behavior. `createCapture().captureManual` deliberately
   bypasses the `/fxpa/req` URL filter, since a manual export's `request.url`
   is the current Fantrax page, not the RPC endpoint.

Extended the backend contract minimally so both new sources persist:
`BridgeRequest.source` in `backend/src/hoops_gm/api/routes/bridge.py` is now
`Literal["fetch", "xhr", "cache-storage", "manual-export"]` (was
`Literal["fetch", "xhr"]`). No migration was needed — `bridge_payloads.source`
is a plain `Text` column with no database-level CHECK constraint. This is a
narrow extension of an existing contract, in the same spirit as the handshake
path having been built ahead of its backend route; `backend` should still
review the enum choice.

This is capture (read) work only: no DOM mutation, no write request to
Fantrax, and no action executor code, so the Automation gate does not apply
and no `safety` sign-off was sought for it — same framing as the prior
page-world-hook entry.

**Now true:** `npm --prefix userscript test` passes 47 tests (32 previous +
15 new): the Cache Storage watcher (matching entries, the hidden-tab skip,
and never throwing when `caches.keys()` rejects), `pageEventDetails` accepting
`cache-storage` while still rejecting `manual-export` over the page channel
(it never travels that way), `captureManual` bypassing the URL filter,
`buildDomSnapshotHtml`/`selectSnapshotRoot`/`readExposedAppState` (stripping,
truncation, fallback order, throwing-getter survival), `captureManualSnapshot`
preferring app state over DOM and reporting failure without throwing, and
`installManualCaptureMenu` wiring/no-op-without-a-register-function.
`npm --prefix userscript run build` succeeds; userscript version bumped to
0.3.0. `userscript/README.md` documents the root cause, both new paths, and an
explicit "Customer workflow: manual export" section with exact owner steps;
the root `README.md`'s bridge section points to the same fallback.

Backend: added `test_payload_accepts_cache_storage_source_for_service_worker_owned_traffic`,
`test_payload_accepts_manual_export_source_with_no_response_status`, and
`test_payload_rejects_an_unknown_source` to
`backend/tests/test_bridge_payloads.py`. The full backend suite
(`backend/tests`) passes with these changes.

**Could not verify:** Whether Fantrax's service worker actually uses Cache
Storage for `/fxpa/req` — the watcher is unverified against the live site and
may find nothing, which the docs state explicitly rather than implying the
capture gap is definitely closed. Whether Fantrax exposes any of the checked
`__NEXT_DATA__`/`__NUXT__`/`__INITIAL_STATE__`/`__APOLLO_STATE__` globals is
also unverified; the DOM-snapshot path is the one guaranteed to produce
*something*. No live browser run of either new path has been performed in
this session; the owner must repeat the live capture check and, if
`bridge_payloads` is still empty for the automatic paths, use the new manual
export menu command and report only the row's `source`/`contentType`, never
its `body_raw` content if it might contain identifying league data beyond
what's already expected.

**Environment finding, unrelated to this change's correctness but blocking
verification of it and any other backend gate on this machine:** running
`python -m pytest backend/tests/...` in this worktree by default imports a
**different** worktree's `hoops_gm` package. A user-site editable install
(`_editable_impl_hoops_gm_backend.pth`) points at
`C:\Users\steverones\copilot-worktrees\hoops-gm\sr2501-curly-telegram\backend\src`,
which shadows this worktree's `backend/src` on `sys.path` for any bare
`import hoops_gm`. Concretely: `python -c "import hoops_gm; print(hoops_gm.__file__)"`
resolved to that other worktree, and this session's new `Literal["fetch",
"xhr", "cache-storage", "manual-export"]` was invisible until tests were run
with `PYTHONPATH=<this worktree>/backend/src` prepended, which is what all
test runs recorded above actually used. Without that override, backend tests
silently exercise **stale code from a sibling session's checkout** rather than
this worktree's source — a correctness risk for any agent trusting a green
`pytest` run here without checking `hoops_gm.__file__` first. This is on top
of the previously-reported `pytest-asyncio`/Python 3.14
`get_event_loop_policy()` deprecation-as-error, which was also worked around
here with `-W ignore::DeprecationWarning -o filterwarnings=` for verification
purposes only — neither workaround was made permanent in any config file, so
a plain `pytest` invocation on this machine still fails exactly as previously
documented.

**Next:** Owner repeats the live capture check with the rebuilt script; if
`bridge_payloads` is still empty, invoke the manual export menu command once
and report only its outcome (row count, `source`, `contentType`) rather than
contents. Separately and not specific to bridge: someone with machine access
should either fix the stale editable install (point it at the correct
worktree, or uninstall it if it belongs to a finished session) or add an
explicit `PYTHONPATH`/`pytest.ini`/`tool.pytest.ini_options` `pythonpath`
entry so `backend/tests` cannot silently run against another worktree's code;
until then, any agent running backend tests here should verify
`hoops_gm.__file__` resolves inside their own worktree first.

## 2026-08-18 — quant — Implemented schedule-context schema after schedule-ingest merge

**Changed:** Rebased onto the current `main`, reviewed the merged
`team_schedule` contract, and implemented the quant-owned Phase 4 context tables
without touching the pure calendar arithmetic owned by `schedule_density`.
`opponent_context` and `off_night_slates` were added via the ORM and Alembic
migration, exported from the model package, and verified against the portability
suite. The earlier schema issue was resolved by removing redundant `index=True`
attributes and keeping only explicit `Index(...)` declarations so the model and
migration agree.

**Now true:** The repository now contains the explicit model-output tables for
schedule context: per-game opponent environment and per-date light-slate
classification. They stay separated from schedule facts and from production
availability logic, matching the ADR-002 and ADR-007 framing for this phase.
The portability checks for the new tables pass in the current backend test
suite.

**Could not verify:** No live backtest or calibration run was executed for the
actual blowout-risk and off-night model; the current patch adds the schema, not a
trained model or held-out evaluation. The chosen windows and thresholding remain
design assumptions until real NBA data is observed. No Postgres or live NBA data
run was performed in this change, so the only verified evidence is the schema and
metadata checks in the repository’s SQLite portability suite.

**Next:** `quant` should run the Phase-4 backtest once live `team_schedule` data
and historical results are available, validating the pace/defence windows,
blowout probability calibration, and off-night detection thresholds against a
held-out sample before computing anything production-facing.

---

## 2026-08-17 — quant — Schedule-context freshness provenance

**Changed:** Updated the schedule-context contract after acceptance of ADR-011
and ADR-012. Both quant-owned output tables now carry an immutable
`schedule_version` and `schedule_refreshed_at` alongside `model_version`,
`computed_at`, and the input snapshot. The natural keys include
`schedule_version`, retaining each model output against the schedule snapshot
that produced it rather than overwriting it when the calendar refreshes. Added
the missing model card with the required version-cohort, refresh, and Model-gate
rules.

**Now true:** A schedule-context consumer can require a single matching
schedule/model version cohort and identify whether its context derives from a
stale schedule refresh. Context must refresh at least weekly and after a
schedule-version change. This keeps Phase 4 opponent context from mixing with
newer schedule, projection, or future SOS outputs; the downstream component must
reject a version mismatch or trigger recomputation, not silently combine rows.

**Could not verify:** There are no downstream projection, SOS, or availability
consumers yet, so the actual invalidation/recompute cascade cannot be exercised.
`team_schedule` does not itself yet expose a schedule snapshot version; the
future context computation must produce the persisted version from its ingest
refresh provenance rather than inventing a value per row. No live or held-out
model evaluation was run.

**Next:** `quant` should make the availability model and Phase 5
strength-of-schedule consumer require matching provenance cohorts when they are
implemented. `data-engineer` should expose schedule-ingest refresh provenance
for the context computation to record. The Model gate remains required before
any decision-facing computation.

---

## 2026-08-17 — backend — Fix schedule-context Code-gate failure

**Changed:** Classified both failed PR #8 Backend Code-gate jobs as
PR-caused: each failed only
`tests/test_schema.py::test_no_table_anywhere_stores_a_percentage` after
`off_night_slates` introduced `light_slate_percentile` and
`threshold_percentile`. Added those two fields to the test's explicit
allowlist with the required explanation: they are schedule-distribution
percentiles, not fantasy shooting ratios, so no volume denominator is lost.

**Now true:** The R9 guard still rejects percentage-shaped columns by default,
while permitting only the two non-ratio percentile fields introduced by this
schedule-context change. Local verification used this worktree's
`backend/src` explicitly and passed `ruff check .`, `ruff format --check .`,
`mypy`, and `pytest` (410 passed, 12 deselected).

**Could not verify:** The local interpreter is Python 3.14 whereas CI uses
Python 3.12, and its pre-existing `pytest-asyncio` deprecation must still be
suppressed for the local full suite; no Postgres service was available locally.
The CI failure itself was reproduced before the correction and was a
deterministic assertion failure, not transient infrastructure.

**Next:** Push the correction and re-run the two failed Backend Code-gate
checks on PR #8; both should pass if the Ubuntu/Python 3.12 environment
matches its prior successful lint and type-check steps.

---

## 2026-08-18 — architect — Autonomous delivery authority and ADR-008 acceptance

**Changed:** Recorded the owner's decision that ordinary read-only and code PRs
may merge autonomously only after every applicable gate is green and an
independent review approves. The authority does not cross owner-only decisions,
an unresolved `safety` veto, paid services, ToS changes, first live-account
actions, or ADR acceptance. Also marked ADR-008 `Accepted` with the owner's
2026-08-18 acceptance and recorded that the owner praised it as written.

**Now true:** Autonomous delivery has an explicit repository policy without
weakening any readiness gate or escalation boundary, and ADR-008's metadata and
decision index match the owner's decision.

**Could not verify:** Independent review and remote required checks have not yet
completed. This documentation PR must not merge until both approve it.

**Next:** An independent reviewer should confirm that the delivery authority is
bounded exactly as stated and that ADR-008 was changed only in status metadata
and the decision index.

---

## 2026-08-18 — data-engineer — `schedule-density` from `team_schedule` only

**Changed:** Added pure calendar-arithmetic density helpers in
`backend/src/hoops_gm/ingest/nba/schedule.py` built only from `team_schedule`
rows. The logic computes back-to-back flags, `rest_days`, 3-in-4 / 4-in-5 /
4-in-6 windows, opponent rest-day differential, and the current road-trip
length/structure by walking each team's games in date order. An off-day does
not end a consecutive-away-game run; the run ends at the next home game. The
builder rejects mixed season or season-type cohorts rather than silently using
one season's prior game as another season's rest baseline. The code stays in the
ingest-data boundary and does not infer any scoring-model or risk judgment.

**Now true:** `team_schedule` alone is sufficient to derive the required density
facts without consulting the availability model, opponent context, or any
non-schedule source. The helper exports a stable `ScheduleDensityRecord` and
supports the common `build_schedule_density` / `team_schedule_density` /
`schedule_density` call patterns. After rebasing onto refresh-lineage migration
`0005`, callers must provide that cohort's `schedule_version` and timezone-aware
`schedule_refreshed_at`; every density row preserves both values for downstream
cohort checks. Tests pin the opponent-relative rest differential and a road trip
that continues across an off-day rather than silently treating rest as a return
home, reject cross-season and cross-season-type input, and show the stamped
version passing `check_cohort` as current while a mismatched version is stale.
Against the current `main`, the pinned backend Code gate passes Ruff, formatting,
strict mypy, the secret scan, 443 default tests, all 10 schedule tests, and
SQLite migration upgrade/check/downgrade.

**Could not verify:** No Postgres service or live NBA schedule request was
available in this environment. The schedule records expose consecutive
away-game runs and opponent IDs, but the calendar alone cannot prove where a
team physically spent an off-day. No downstream availability-model claims are
made from these numbers yet.

**Next:** `quant` can consume these density facts once the schedule facts are in
place; no extra schedule-context work should be folded into this Phase 3 item.

---

## 2026-08-18 — quant — Descriptive teammate absence splits

**Changed:** Implemented `absence-splits` as versioned descriptive evidence
rather than a decision-bearing model. `compute_absence_splits` now compares a
beneficiary's observed game-log production when a teammate played versus when
the teammate had an explicit observed non-play participation row. The first
implementation inferred absence inside gaps bounded by same-team observations.
**Independent review disproved that claim before merge:** bracketing
observations do not prove continuous roster membership, and roster membership
alone would not prove that an upsert-only participation ingest returned a
complete game payload. No missing row is now classified. Added complete
`absence_split_runs` cohorts (including zero-result runs), exact source
provenance, current schedule lineage, complete-input fingerprints, sample-size
and uncertainty fields, a latest-run selector, denominator-aware shooting
summaries without attempt-independence intervals, and focused regressions. The
contract and blind spots are documented in
`docs/availability/absence-splits.md`.

**Now true:** R35 fails closed: no missing row of any kind can enter an absence
split. Full absences remain invisible until authoritative roster intervals and
per-game ingestion-completeness evidence both exist. Every persisted row
identifies itself as `data_layer=observations` and
`claim_type=descriptive`, with database CHECK constraints preventing those
claims from drifting. Makes and attempts remain reconstructable, sparse groups
state whether variance is estimable, and percentage intervals are omitted
rather than treating clustered shot attempts as independent. Every successful
computation persists a run even when no pair remains; the current selector reads
only the newest run, so corrected input can remove an obsolete pair without
deleting its audit history. Every successful computation creates a fresh
activation even if its fingerprint matches an older run, preserving A-to-B-to-A
ordering. Cohorts are fully validated before activation, so a caught input error
cannot install an empty latest run. No output claims causality or recommendation value.
The Model gate does not apply to this descriptive artifact; it does apply to
the future `contingent-value` model that turns this evidence into a
decision-bearing quantity.

**Could not verify:** No real multi-season NBA backfill is present in this
worktree, so sample-size distributions and the practical frequency of
contradictory source rows remain unmeasured. No Postgres service was available
locally. Full absences represented by missing rows are deliberately not counted,
so the evidence undercovers the exact long-injury cases R35 warns about rather
than fabricating labels from silence. The splits cannot separate teammate
absence from coaching, matchup, lineup, or role changes. Schedule-density facts
from the newly merged Phase 3 contract are intentionally not consumed because
this artifact is an unadjusted historical description, not an availability or
production model.

**Next:** `quant` may use these rows as candidate features for
`contingent-value`, but must first define temporal held-out validation and a
model card; no stock-watch, waiver, draft, lineup, or trade recommendation
should read raw absence deltas directly.
---

## 2026-08-18 - data-engineer - Versioned league-settings ingestion

**Changed:** Verified the target private league's official `getLeagueInfo`
response with one low-frequency request containing only its non-secret
`leagueId`; no `userSecretId`, cookie, private adapter, bridge polling, or write
path was used. Added `LeagueSettingsDocument` schema version 1, covering lineup
locks, waivers, games caps, roster/IR limits, scoring-period boundaries, trade
deadline, playoffs, and keepers. Every concern carries source evidence even
when absent. Official observations have priority; bridge evidence may fill only
missing nested fields, and only when league id, season year, and season
boundaries match exactly.

The live response is the **2025-26** league (`seasonYear: 2025`, 2025-10-21
through 2026-03-15). It exposes roster totals/position constraints and 21
scoring-period boundaries. It exposes no lineup-lock, waiver/claim/FAAB,
games-cap, IR-specific, trade-deadline, playoff-marker, or keeper fields. Those
remain explicit unknowns; no value is read from
`docs/league/2025-26-rules-baseline.md`. `import_league_settings` requires the
linked Fantrax league id and matching source season, so this payload cannot be
attached to a 2026-27 `League`.

Migration `0006` adds immutable `league_settings_snapshots` with document
version, schema version, evidence summary, exact raw-response SHA-256, and the
capture's actual observation time. Idempotency compares only the latest
snapshot's normalized values and semantic provenance, excluding capture-specific
hashes; repeated observations are skipped, source changes and A-to-B-to-A
reversions create new versions. The operator command is
`python -m hoops_gm.ingest.backfill league-settings LOCAL_LEAGUE_ID
FANTRAX_LEAGUE_ID` and deliberately constructs a credentials-free official
client.

**Adapter evidence:** Committed
`fantrax_getleagueinfo_settings_sanitized.json`. `leagueName`,
`leagueHistoryId`, `teamInfo`, `playerInfo`, and `matchups` were removed whole;
no retained source value was edited. The manifest records the original 106,773
bytes, SHA-256
`722b95c7bbecde2950aea9fea0ccc24519311248ee79a1320fe07455d718ae54`,
source capture time, original top-level keys, and removed sections. The
recorder bypasses cache. Offline contract tests pin the verified fields and
explicit omissions. The live smoke bypasses cache, rejects top-level or nested
rule drift, scans every array item, and receives the league id through an
out-of-source GitHub Actions repository variable.

**Now true:** R43 is closed on evidence: official `getLeagueInfo` does not carry
the timing fields. The Code and Adapter gates pass on the rebased branch:
Ruff, format, strict mypy, secret scan, 477 default tests, 75 offline adapter
contract tests, all 13 live smoke tests, and SQLite migration
upgrade/check/downgrade. Independent review reported no remaining significant
issues after fixes for identity binding, cross-season fallback, raw provenance,
freshness, drift coverage, nested fallback, semantic idempotency, provenance
changes, and settings reversions.

**Could not verify:** Fantrax has not rolled this league to 2026-27, so no final
2026-27 rule can be claimed yet. The missing rule families could not be
corroborated from the bridge because no new bridge capture was requested and
the existing rendered-view contents were deliberately not inspected. No local
Postgres service was available; the migration was exercised on SQLite and the
repository's Postgres CI remains the cross-dialect check. `getDraftPicks`
remains unverified against a successful live snake or auction response.

**Next:** Re-run the credentials-free settings ingest after Fantrax exposes the
2026-27 season. Use the existing read-only bridge only for official unknowns,
without widening access or polling, and keep the 2025-26 snapshot historical.

---

## 2026-08-18 - data-engineer - Bridge fallback integration correction

**Changed:** Closed an integration gap found by exact-head release review. The
first implementation had a correct `merge_settings` library function but no
production path that called it; bridge fallback existed only in tests, while
the operator command imported the official document directly. Added a
versioned, strict `BridgeLeagueSettingsPayload` contract and
`load_bridge_league_settings_capture`. The `league-settings` operator command
now accepts one explicit `--bridge-capture PATH`, validates the file's exact
league id, season year, start/end boundaries, timezone-aware observation time,
and typed rule values, merges it with official settings, and imports the result
in the same database transaction.

**Now true:** Bridge fallback is honestly reachable without any new Fantrax
access. The code does not inspect the bridge database, capture a page,
authenticate, or poll; an operator must deliberately supply an already
captured JSON file. Official values win at nested-field granularity, bridge
values fill only official unknowns, and the snapshot provenance combines both
exact payload digests and uses the later observation time. An end-to-end
production-entry regression proves official roster total 14 survives a bridge
value of 99 while bridge-only lineup-lock and IR values are persisted with
both sources' evidence.

**Could not verify:** No real bridge settings capture was supplied, and the
existing rendered-view contents remain deliberately uninspected. The committed
regression uses a synthetic file conforming to the new handoff contract, so the
first real operator-created capture may expose vocabulary that requires a
schema-versioned adapter change. No access or ToS claim changed.

**Next:** When an official unknown is needed, export only that evidence from
the existing read-only bridge into the documented JSON contract and pass it
explicitly. Do not make bridge capture automatic.

---

## 2026-08-18 — quant — Scoring-profile abstraction: derivation, activation, fail-closed vocabulary

**Changed:** Implemented the `scoring-profiles` backlog unit. `db-foundation`
had already scaffolded `league_scoring_profiles`/`league_scoring_categories`
(unique `(league_id, name, version)`, ratio components + box-score vocabulary
CHECKs, percentage-keys-must-be-ratio CHECK) but nothing derived, activated,
or attributed a profile to a league's rules -- the tables were unused by every
other module. Added two schema changes (migration `0011`): a required
`settings_snapshot_id` FK to `league_settings_snapshots`, so every profile is
provably derived from a specific version of that league's rules; and
`active_league_id`, a nullable self-FK to `leagues` that mirrors `league_id`
only while a profile is the league's active one, protected by a bare
`UniqueConstraint`. This replaces the previous plain `is_active: bool` column
and enforces "at most one active profile per league" as a database guarantee
rather than a convention, without a dialect-specific partial index --
`test_portability.py::test_no_module_outside_engine_construction_branches_on_
dialect` forbids exactly that keyword pattern (`sqlite_where=`/`postgresql_
where=`), and NULL-is-distinct-in-a-unique-constraint is portable to both
SQLite and Postgres. Added `hoops_gm.scoring.profiles`: `build_scoring_profile`
derives a new (inactive) profile version from a league, its *current* settings
snapshot, and a plain `SourceCategory(abbreviation, name)` sequence decoupled
from the Fantrax adapter's own `FantraxScoringCategory`; `map_source_categories`
maps only the nine abbreviations actually observed in the captured Fantrax
fixture (AST, BLK, PTS, REB, ST, 3PTM, TO, FG%, FT%) to a canonical 9-category
vocabulary, raising `UnsupportedCategoryError` on anything else (fail closed,
not a best-effort guess) and a plain `ValueError` on a duplicate mapped key or
an empty category list (an independent-review pass caught that an empty
`source_categories` list was silently accepted and even activatable before
this fix -- the degenerate case of "missing a category", all of them, slipping
past the fail-closed guarantee the module claimed);
`activate_scoring_profile_version` is a separate, explicit, two-phase
deactivate-then-activate call, so A -> B -> A re-activation is a plain repeat
of the same call with no special case; `current_scoring_profile` is the
canonical single-active-row selector. Percentage categories (`fg_pct`,
`ft_pct`) are always derived as made/attempted component pairs
(`field_goals_made`/`field_goals_attempted`,
`free_throws_made`/`free_throws_attempted`), never a stored raw percentage --
the R9 guard the schema already enforced now has a builder that can never
violate it. New test file `test_scoring_profiles.py` (16 tests): category
order preservation, duplicate-category rejection, unsupported-category
rejection, empty-category-list rejection, percentage volume-weighting,
missing-makes/attempts defense in depth, exact league binding (cross-league
snapshot rejected), stale-settings rejection, A -> B -> A activation,
per-league activation scoping, the database-level one-active-per-league
guarantee bypassing the service function, and a full 9-category round trip.
`test_schema.py`'s existing scoring-profile tests and helpers were updated
for the new required `settings_snapshot_id` column. An independent
`code-review` sub-agent pass (see below) reviewed the diff before opening the
PR and found no other high-confidence issues.

**Now true:** A scoring profile is league+season scoped (via `league_id` on a
`League` row that is itself one season), source-attributed to a specific
`LeagueSettingsSnapshot` version, immutable per version, and has exactly one
database-enforced active version per league with clean A -> B -> A semantics.
An unknown or unsupported scoring category cannot silently produce a
plausible-looking profile; it raises before anything is persisted. No
ranking, AAV, or other market aggregate is anywhere in this module's inputs or
outputs (ADR-008), and no production, availability, or `p(play)` quantity is
computed here (ADR-002 stays intact: this is category/direction/ratio-component
*configuration*, produced from a league's own stated rules and its own stated
scoring categories only). Full Code gate: Ruff, Ruff format, strict mypy (94
source files, zero errors), and the full backend suite (541 passed, 17
deselected `live_smoke`, up from 525 before this unit's 16 new tests) all
pass locally, including the pre-existing migration-agreement,
portability, and schema tests, which caught a Postgres 63-character
identifier overflow on the new foreign key's autogenerated name before it
became a problem (fixed with an explicit shortened constraint name). Model
gate is explicitly assessed as **not applicable**: nothing in this unit
predicts, blends, or estimates anything, so there is no held-out evaluation or
calibration to report and no model card was written -- see
`docs/models/README.md`'s required-sections list, none of which (training
window, evaluation, calibration, what-it-cannot-see) has meaning for a
configuration importer. Adapter gate is not claimed: no external source is
called by this code: it consumes `SourceCategory` values a caller already
extracted, the same boundary `import_league_settings` already draws for its
own `LeagueSettingsDocument` input.

**Could not verify:** No production code path yet calls
`build_scoring_profile` with real Fantrax scoring-category evidence -- the
adapter's `FantraxScoringCategory` parsing exists, but no importer wires it
into `SourceCategory` and into this module end-to-end against a live
`getLeagueInfo` response; the 9-category round trip is tested against the
captured fixture's abbreviations, not a live call. Whether "ST" and "3PTM" are
the only abbreviation spellings Fantrax ever returns for steals and
three-pointers-made (as opposed to, say, "STL" or "3PM" in some other league
configuration or API version) is unverified beyond this one captured payload;
the mapping table is deliberately restricted to only what has been observed,
so a genuinely different spelling will raise `UnsupportedCategoryError` rather
than silently mis-map, which is the intended fail-closed behaviour but means a
real points- or roto-format league's categories are entirely unhandled until
someone extends the vocabulary against verified evidence. No local Postgres
service was available in this session; the new migration and schema were
exercised on SQLite only here, with the repository's Postgres CI job as the
cross-dialect check (as in the prior entry). An independent `code-review`
sub-agent pass reproduced a `League` delete cascading correctly through both
its settings snapshot and a scoring profile citing it simultaneously on
SQLite (both via ORM cascade and a raw `DELETE`), so the `ondelete="RESTRICT"`
(implicit-default) versus explicit-`RESTRICT` question raised in an earlier
draft of this entry is resolved for SQLite specifically; whether Postgres'
implicit `NO ACTION` behaves identically in the same cascading-delete
scenario is still unverified, since no dedicated test exercises this exact
multi-table cascade and no local Postgres was available this session.

**Next:** Wire an importer that turns a live `getLeagueInfo` scoring-category
response into `SourceCategory` values and calls `build_scoring_profile`
end-to-end, extending `_FANTRAX_ABBREVIATION_TO_KEY` only against newly
verified evidence if a different league's spelling turns up. When points or
roto formats are built, add their category vocabularies and `ScoringType`
handling here rather than special-casing them inside whatever consumes a
profile -- the `scoring_type` column and per-category `direction`/`kind`
fields already generalize past H2H categories. Valuation, draft
recommendation, and UI consumption of a scoring profile remain fully
out of scope of this unit, by design. PR #22 opened against `main`. `main`
advanced to `ffd838c` (PR #19, versioned schedule context) between the first
push and PR review, which also added a migration numbered `0010`; this
unit's migration was renumbered `0011` (`down_revision` repointed at the
newly-merged `0010`) after a clean rebase, and the full suite (576 passed, 17
deselected), ruff, ruff format, mypy strict, and a from-empty
`alembic upgrade head` were all re-verified green at the new head. Awaiting
independent review; not merged or self-approved.

---


## 2026-08-18 — quant — Scoring-profiles: snapshot-authoritative lineage rework (PR #22 remediation)

*(Corrected in place on `sr2501-scoring-profiles`, still unmerged: the header
above originally read "2026-08-19", one day ahead of every other entry in
this file and of the work it describes -- a plain date typo, fixed here
rather than left to propagate. The "Now true" paragraph below also
originally claimed cross-snapshot A -> B -> A reuse that a later
independent review found to be a lineage-rewriting bug, not a feature --
corrected below; see the third-remediation-round entry later in this file
for the actual fix and why cross-snapshot reuse specifically was wrong.)*

**Changed:** An independent review at `b91bf7c` found the prior entry's
central claim false: `build_scoring_profile` accepted an arbitrary caller-
supplied `source_categories` sequence and separately stored
`settings_snapshot_id`, so a profile could cite lineage from a snapshot that
had no bearing on the categories it actually contained -- a lineage lie, not
a lineage. This also retires the prior entry's own "Next" guidance to extend
`_FANTRAX_ABBREVIATION_TO_KEY` and wire a caller-supplied `SourceCategory`
flow into `build_scoring_profile`: that plan is superseded entirely by
making the snapshot genuinely authoritative below, not carried out as
originally described -- `_FANTRAX_ABBREVIATION_TO_KEY` is renamed to
`_FANTRAX_CODE_TO_KEY` (keyed on the stable `code`, not the abbreviation) and
`build_scoring_profile` no longer accepts any caller-supplied category
sequence at all. Fixed by making the snapshot genuinely authoritative: extended
`LeagueSettingsDocument` with first-class `scoring_type`/`scoring_categories`
`SourcedSetting`s, parsed by shared functions in `ingest/league_settings.py`
(`parse_scoring_category_configs`, `parse_scoring_type_raw`) that the Fantrax
adapter's own `parse_official_league_settings` now calls -- so the *same*
`getLeagueInfo` payload that produces roster limits and scoring periods also
produces the scoring rules a profile derives from, and a real settings-rules
change now produces a genuinely new snapshot version rather than an
unrelated caller argument. `build_scoring_profile` no longer accepts
`source_categories` or `scoring_type` parameters at all; both are parsed
exclusively from `LeagueSettingsDocument.model_validate(settings_snapshot.
settings)`, with an explicit `ValueError` if either is absent (an
unattempted or partial settings ingest cannot silently produce a profile).
The adapter's `FantraxScoringCategory` was corrected to key on the stable
`code` (e.g. `INDIVIDUAL_ASSISTS`) rather than the numeric `id` or bare
`shortName` -- `SourceCategory.code` is now the primary mapping anchor in
`_FANTRAX_CODE_TO_KEY`, with `abbreviation` retained only as display
evidence. Category `weight` is now parsed and explicitly asserted `== 1.0`;
a non-unit weight raises `NonUnitCategoryWeightError` rather than being
silently dropped, since weighted categories are undesigned and `point_value`
already carries distinct points-league semantics this must not borrow.
`scoring_type` is derived from the snapshot's exact discriminator via a
verified `_FANTRAX_SCORING_TYPE_TO_LOCAL` mapping
(`HEAD_TO_HEAD_ROTI_MULTI_WIN` -> `ScoringType.H2H_EACH_CATEGORY`, backed by
this project's own `docs/league/2025-26-rules-baseline.md` line 13 stating
the target league's format as "H2H each category, 9-cat" -- stronger than
generic terminology alone); any other raw value raises
`UnsupportedScoringFormatError` before a write, and the caller can no longer
pass a default. `_parse_scoring_categories` now raises `SourceContractError`
explicitly on a present-but-empty category list, rather than relying on an
incidental `pydantic.ValidationError` from `ScoringCategoriesRules`'
`min_length=1` to do that job. `activate_scoring_profile_version` gained
three revalidation checks before touching whatever profile is currently
active -- exact league binding, that `profile.settings_snapshot` is still
the league's current snapshot, and `len(profile.categories) > 0` -- each
raising before the previously-active profile is looked up or deactivated, so
a failed activation never gets partway through. Added content-fingerprint
idempotency: `build_scoring_profile` now computes a canonical fingerprint
over scoring type, the settings document's own `content_sha256()` (which
excludes capture-specific evidence, so two different snapshot rows with
identical rules content fingerprint identically), and each category's key,
direction, kind, ratio components and weight, then returns an existing
`(league, name)` profile unchanged if its fingerprint matches rather than
minting an indistinguishable new version -- this is what makes A -> B -> A
honest reactivation rather than version churn. Added a production seam,
`derive_scoring_profile` in `ingest/backfill.py` (plus a `scoring-profile`
CLI subcommand with an explicit `--activate` opt-in, never automatic): looks
up a league's current settings snapshot and derives from it, so an operator
does not look that snapshot up by hand. Rewrote `test_scoring_profiles.py`
top to bottom (27 tests, up from 16): every snapshot in the file is now
built by calling the real `parse_official_league_settings` against a
synthetic `getLeagueInfo`-shaped payload (own `_scoring_payload` builder)
rather than a hand-constructed `LeagueSettingsDocument`, so the tests are
tied to the actual ingestion boundary. New coverage: non-unit weight
rejection (both through the builder and directly through
`map_source_categories`), missing/unsupported scoring-type rejection,
present-but-empty category list rejection at parse time (distinct from
absent), verified scoring-type mapping, re-derivation from an unchanged
snapshot returning the same profile, A -> B -> A content-fingerprint reuse
across three distinct snapshot rows (v1 and v3 byte-identical in canonical
content despite different rows; v2 different), activation revalidation
rejecting a stale-settings profile and a direct-ORM-constructed empty-
category profile (both leaving the prior active profile untouched), and an
end-to-end production-seam test running the real captured fixture through
`parse_league_info` -> `ingest_official_league_settings` ->
`derive_scoring_profile` -> `activate_scoring_profile_version`.
`test_adapter_contracts.py::TestFantraxLeagueSettings` gained exact
code<->abbreviation<->weight fixture-contract assertions for all nine
categories plus the settings-document-level `scoring_type`/
`scoring_categories` values, tying the adapter gate to the modified payload
contract. Wrote an evidence-fidelity section in
`docs/adapters/fantrax-official.md` naming exactly what is consumed
(`code`/`name`/`shortName`/`weight`/`scoringSystem.type`), what is
deliberately not modeled (the flatter `scoringSystem.scoringCategories` map,
which lacks `code` and cannot anchor a mapping; the `position` sub-object,
always `DEFAULT` in this league), and flagging the "ROTI" segment of the raw
discriminator as unconfirmed by any first-party reference found. Rebased
onto `main` twice during this rework as it advanced out from under the
branch: first to `ffd838c` (PR #19), then -- after PR #20 ("deadline-model")
merged as `0ff417a` and claimed migration `0011` via
`0011_league_deadline_calendars.py` -- renumbered this unit's migration
`0011_scoring_profile_lineage.py` to `0012_scoring_profile_lineage.py`
(`revision="0012"`, `down_revision="0011"`); the migration's schema content
is unchanged from the original PR (no new columns -- scoring lineage still
lives in the existing `LeagueSettingsSnapshot.settings` JSON blob), only the
revision numbering moved.

**Now true:** A scoring profile's lineage is real: its `scoring_type` and
categories are derived exclusively from its cited `LeagueSettingsSnapshot`,
never from an argument a caller could supply independently of that
snapshot, and a genuine scoring-rules change in a re-ingested settings
payload produces a new snapshot version that a re-derivation will pick up.
The Fantrax `code` is the verified, fixture-pinned mapping anchor; a
category with an unmapped code, a duplicate, a non-unit weight, or an
absent/unmapped scoring format all fail closed before any write, matching
the same discipline the module already applied to an empty category list.
Re-deriving from an unchanged current snapshot returns the existing row
rather than creating an indistinguishable new version. *(Correction: this
paragraph originally also claimed that reactivating a previously-superseded
profile version whose content matches the current one across a **different**
snapshot row (A -> B -> A) returns/reactivates that old row directly. A later
independent review found that false and worse than merely inaccurate: the
old row still cites the stale (A) snapshot, so reusing it verbatim is a dead
end -- activation correctly refuses it as stale under the current (C)
snapshot, with no way to ever escape that refusal by re-deriving again.
Same-snapshot identical derivation does reuse the existing row, exactly as
stated above; cross-snapshot identical content does not -- it mints a fresh
lineage version carrying A's content but the new snapshot's own FK, which is
what actually makes A -> B -> A activatable and honest. See the
third-remediation-round entry later in this file for the real fix.)*
Activation cannot make a stale-lineage or
zero-category profile the league's active one, however that profile came to
exist, and a rejected activation leaves the previously-active profile
untouched. A real operator path (`derive_scoring_profile` /
`scoring-profile` CLI subcommand) exists end to end from an ingested
settings snapshot to an explicitly activated profile, exercised in tests
against the real captured fixture rather than only library functions. ADR-008
and ADR-002 both still hold: no ranking, AAV, or market aggregate is anywhere
in this module's inputs or outputs, and no production, availability, or
`p(play)` quantity is computed here -- this remains category/direction/ratio-
component/scoring-type *configuration*, sourced only from a league's own
stated rules. Local Code gate green: ruff check, ruff format --check, and
project-wide `mypy` (strict config, 108 source files, zero errors) all pass;
full backend suite 626 passed / 17 deselected (`live_smoke`), including
`test_scoring_profiles.py`'s 27 tests and the extended adapter-contract
assertions. Adapter gate: `pytest -m adapter_contract` passes (the modified
`getLeagueInfo` scoring payload contract is pinned by
`test_adapter_contracts.py`'s fixture-tied assertions); no new live call was
added beyond the existing `getLeagueInfo` smoke coverage. Model gate remains
explicitly not applicable -- nothing in this rework predicts, blends, or
estimates anything; it is still configuration derivation, not a statistical
model, so no model card was written. Migrations: `alembic upgrade head` from
empty, `alembic check` (no drift detected), and `alembic downgrade base` all
pass on SQLite at the new head; the migration file's content is byte-
identical to the original PR, only its revision/down_revision numbers moved
to `0012`/`0011`.

**Could not verify:** The "ROTI" segment of `HEAD_TO_HEAD_ROTI_MULTI_WIN` has
no confirmed meaning found in this project's own documentation or any
first-party Fantrax reference during this work -- only the raw discriminator
string itself and this project's own historical rules-baseline document
support the `H2H_EACH_CATEGORY` mapping; a genuinely different Fantrax
scoring format (points, roto) remains completely unhandled and unverified,
by design, until built against real evidence for that format specifically.
No local Postgres was available in this session (no `docker`/`psql` on
PATH) -- the migration and full suite were exercised on SQLite only here,
with the repository's Postgres CI job as the cross-dialect check, as in
prior entries for this unit. Whether PR #21 has independently landed and
already claimed migration `0012` was not re-checked immediately before this
entry was written; a final rebase/renumber check against `origin/main`
happens right before requesting review, per the race-condition coordination
already flagged by the reviewing session.

**Next:** Confirm `origin/main` has not advanced further and that PR #21 has
not claimed migration `0012` before requesting final review; renumber again
if it has. Push this remediation, request two focused independent reviews
(percentage-math/layer-purity concerns already resolved in a prior round;
this round's ask is specifically the lineage/idempotency/activation-
revalidation fixes), and report back to the reviewing session with exact
head/base, gate results, and this uncertainty list. Not merged or self-
approved.

---


## 2026-08-18 — data-engineer — Historical injury-report backfill

**Changed:** `injury-status-conversion` was blocked on evidence — only one
committed injury PDF snapshot existed, from the initial adapter build (PR #13).
Built `hoops_gm.ingest.injury_report.backfill`, a bounded, resumable operator
workflow that derives candidate archived-report timestamps from exact ingested
schedule tip-off instants plus the documented NBA publication cadence
(pre-2025-12-22: report due 5pm local the evening before; from 2025-12-22:
report due 11am–1pm local game day, per the ESPN-reported NBA memo — a date
that independently matches this codebase's own observed filename-format-era
boundary), fetches through the existing unmodified `InjuryReportClient` with
its existing throttle/retry/cache semantics, imports through the existing
unmodified `import_injury_report_entries` (whose natural key already
structurally dedupes two candidate timestamps that resolve to the same
masthead), and exposes `select_canonical_pregame_observations` as a pure query
— the single latest pre-tipoff report row per `(game, team, player)`,
re-deriving the no-lookahead gate independently at read time rather than
trusting the plan. No rate is fitted and no status-conversion number is
reported here; that remains `quant`'s Model-gated work. No schema migration
was needed (`alembic check`: no new operations). Checkpointing is a JSON file
written atomically (tmp + rename); `ReportNotAvailable` (403/404) is the
ordinary "ungettable" case and is never counted as a failure, while any other
`SourceError` is rolled back, recorded as a genuine failure, and left
unsettled so a resumed run retries it. `enforce_request_budget` refuses to run
an unbounded plan. Added 21 offline tests (`adapter_contract`-marked) covering
candidate derivation, no-lookahead selection around tip-off (including "no
expected game-day report"), plan cache-awareness, request-budget enforcement,
checkpoint settle/resume including disk persistence, run atomicity on partial
failure, duplicate-masthead convergence, and canonical-selection semantics.
Added a "Historical backfill" section to `docs/adapters/nba-injury-report.md`,
a new done backlog item `injury-report-historical-backfill` (blocking
`injury-status-conversion`), and risk `R44` (the scheme's anchors are a
heuristic, not a documented schedule, so an off-cadence emergency report is a
disclosed, falsifiable gap, not a claimed one).

Independent review (PR #21, before merge) found a real bug: `--no-cache` /
`force_refetch` was documented in three places (CLI help, module docstring,
`enforce_request_budget`'s own docstring) to force a live re-fetch of every
candidate, but `run_backfill` only ever iterated `plan.to_fetch`, which
excludes already-cached candidates regardless of the flag — the one case the
flag exists for could never be reached, and the checkpoint's settled-outcome
gate had the identical unconditional exclusion. The reviewer reproduced this
directly against the shipped code before any fix. Corrected in the same PR:
`run_backfill` now takes a `force_refetch` parameter that, when set, iterates
`plan.fetches` (not `plan.to_fetch`) and bypasses `checkpoint.is_settled`,
and the CLI now threads `args.no_cache` into it. Added a test
(`test_run_backfill_force_refetch_bypasses_cache_and_checkpoint`) that seeds
a candidate that is both cache-hit and checkpoint-settled and asserts
`force_refetch=True` genuinely re-requests and re-imports it. The review also
flagged that the exact-tip-off boundary (`report_timestamp == tipoff_utc`)
had no test even though the `<` comparison was already correct; added
`test_select_canonical_pregame_observations_excludes_exact_tipoff_boundary`.
Also clarified the live-evidence entry below to state the exact
`build_plan(start=2025-11-01, end=2026-01-15)` window the "505 excluded
games" figure came from (527 games in that window minus the 22 patched),
since the reviewer correctly could not reproduce it from the original text.
21 → 23 tests; full suite re-run green (548 passed, 17 deselected).

Ran a real, bounded live evidence sample against the completed 2025-26 season
(script kept out of the repository, in this session's own scratch state — not
a committed tool, since it exists only to produce a real-network number this
one time): ingested the season schedule (1,225 games) and teams/players (dates
only, no tip-off) with two `nba_api` requests, then patched tip-off instants
for exactly the 22 real games on three known-good dates (2025-11-01,
2025-12-01, 2026-01-15) via 22 `BoxScoreSummaryV3` calls — every other game's
`tipoff_utc` stayed `None` on purpose. `build_plan` was run with
`start=2025-11-01, end=2026-01-15` — a window covering 527 of the season's
1,225 games — and correctly generated exactly 6 candidates (two per date) and
loudly excluded the other 505 in-range games (527 − 22) for having no
ingested tip-off, rather than guessing. All 6 fetches against the real
`ak-static.cms.nba.com` CDN succeeded on the
first attempt (0 failures, 0 `not_available`): distinct archived masthead
timestamps recovered were 2025-10-31T21:30Z, 2025-11-01T17:30Z,
2025-11-30T22:30Z, 2025-12-01T18:30Z, 2026-01-14T22:30Z and
2026-01-15T18:00Z. 645 injury-report-entry rows were imported in total (each
report's rolling window covers players from an adjacent calendar date too, not
only its nominal date — real, previously undocumented behaviour, confirmed
from the actual payloads rather than assumed); 372 of those rows carry a
`game_date` matching the three target dates, and
`select_canonical_pregame_observations` recovered 203 canonical pregame
player-game observations across the 22 real games on those three dates.

**Now true:** A real, non-fabricated, multi-date, multi-game historical
cohort exists in principle and was proven reachable end-to-end against the
live archive — 6/6 candidate fetches succeeded with zero retries needed —
without widening Fantrax access, without committing a large raw corpus (the
evidence run's raw PDFs and database live outside the repository), and
without any new schema. `injury-status-conversion` is unblocked to build its
own committed fixture set using this tool, deliberately scoped to whatever
date range `quant` chooses for the Model gate's held-out backtest.

**Could not verify:**
- **Whether `ScheduleLeagueV2` (the schedule-with-future-dates endpoint) works
  for a past season.** The evidence run sidestepped the question entirely by
  using `LeagueGameFinder` + per-game `BoxScoreSummaryV3` patch-back instead —
  the same approach `backfill_season` already uses and is confirmed to work
  historically. If a future caller wants `ScheduleLeagueV2` specifically for a
  past season, that is untested.
- **Whether every archived report in the 2025-26 season is reachable by this
  scheme.** Only three dates were exercised live, all three chosen because
  they were already confirmed reachable in earlier research. A full-season
  run was not attempted here — the task was to prove the mechanism and its
  gates, not to produce the full committed fixture corpus, which is
  `injury-status-conversion`'s job.
- **Whether an emergency, off-cadence report (e.g. a 3am ET injury update)
  exists anywhere in the archive and is reachable by a different anchor.**
  Not probed; recorded as risk R44 rather than assumed away.
- **The discrepancy between 645 total imported rows and 372 scoped to the
  three target dates was investigated and explained** (each report's rolling
  window bleeds into one adjacent calendar date), not left as an unexplained
  number — but whether this rolling-window behaviour is stable across the
  whole season or particular to these three dates was not checked further.

**Next:** `quant` builds the committed fixture corpus and the held-out
backtest for `injury-status-conversion` using this tool, choosing its own
date range and reporting calibration — that gate is separate from this one.
If a wider historical cohort is ever wanted, re-run this same tool with a
wider `--start`/`--end` after ingesting the corresponding schedule tip-offs,
watching `enforce_request_budget`.

---

## 2026-08-18 — data-engineer — Historical injury-report backfill: correcting the record after independent review found real defects

**Changed:** A second, more thorough independent review of PR #21 at exact
head `e96788a` found the above entry premature on multiple points and found
real bugs the earlier review's fix did not catch. Recorded honestly, in the
order found, because the house rules require correcting rather than quietly
rewriting a prior entry:

1. **Natural-key data loss (critical).** `injury_report_entries`'s unique
   constraint was `(report_timestamp, team_raw, player_name_raw)` — missing
   `game_date`. One masthead reporting a player's back-to-back split across
   two calendar dates collapsed to one row: the second date's import
   silently overwrote the first as an ordinary "update", permanently losing
   one night's row. Fixed: migration `0012` (`down_revision = "0011"`, after
   PR #20 merged and claimed `0011` — this migration was originally cut as
   `0011` before that merge and had to be renumbered) adds `game_date` to the
   constraint; the importer's natural key and existing-row lookup were
   updated to match. New regression test
   (`test_import_never_collapses_a_back_to_back_split_across_game_dates`)
   pins it.
2. **Cache was gating processing, not just avoiding network.** `run_backfill`
   only ever iterated the plan's *uncached* subset; `already_cached` is now
   purely `build_plan`/CLI-render metadata, and the only gate on whether a
   candidate is processed is the checkpoint's own settled-outcome state.
   Fixed the case a cached-but-never-checkpointed candidate (a crash between
   writing the raw payload and writing the checkpoint) was silently skipped
   forever on every resume. New cache-not-gating and
   cached-after-parse-error resume tests.
3. **Commit/checkpoint ordering was backwards.** A candidate was checkpointed
   `"fetched"` before its database commit, so a commit failure after that
   checkpoint write left the checkpoint permanently, wrongly believing the
   row was persisted. Fixed: commit now happens first; a commit exception is
   caught, the session rolled back, and the candidate checkpointed as
   unsettled `"error"` so a resume retries it. New simulated-commit-failure
   atomicity/resume test.
4. **O(n²) importer reload.** `import_injury_report_entries`'s existing-row
   lookup reloaded the whole table per candidate. Fixed: scoped to the
   batch's own `report_timestamp` values.
5. **No durable coverage evidence, only console counts.** Added
   `CandidateCoverage`/`CoverageReport` (JSON, atomic-written next to the
   checkpoint) recording per candidate: era, lead time before tip-off, HTTP
   outcome, canonical masthead instant, and listed-vs-`NOT_YET_SUBMITTED`
   split; and `GameObservationCoverage`/`coverage_for_games`, exposed as a new
   network-free `observations` CLI subcommand, distinguishing four per-game
   outcomes (observed / no-candidate-coverage / unsubmitted-only /
   missing-tipoff) so "no report" is never conflated with "no schedule data"
   or "collision with another game".
6. **No fail-closed gate on incomplete tip-off coverage.** The prior entry's
   own "22/527" evidence run would previously have been indistinguishable
   from a genuine full-range backfill. Fixed: `enforce_full_tipoff_coverage`
   now refuses to run (raises `IncompleteScheduleCoverage`) against any
   requested game scope with a missing tip-off, unless explicitly overridden
   via `--allow-missing-tipoff N`.
7. **The 45-minute masthead-tolerance claim does not hold past
   2025-12-22.** The prior entry's design section wrongly implied the
   parser's 45-minute drift tolerance recovers a fixed-clock guess in both
   URL eras. In fact `report_url()` only truncates to the hour (and is only
   safely recoverable within 45 minutes) in the legacy, pre-2025-12-22
   filename era; from 2025-12-22 the URL is an exact-minute match with *no*
   tolerance at the request level, so a single fixed `game_day@13:00` guess
   is a minute-exact gamble, frequently hours stale relative to a real
   tip-off. Fixed: dates in the 15-minute era with a known tip-off now use
   four bounded, tip-off-anchored offsets (150/90/45/15 minutes before that
   date's earliest tip-off, `NEAR_TIP_OFFSETS`) instead of the fixed clock
   guess. `docs/adapters/nba-injury-report.md` and risk `R44` are corrected
   to state this precisely rather than repeat the wrong claim. New
   era-boundary and near-tip-anchor selection tests confirm no lookahead.
8. **403 was being treated identically to 404.** A 403 can be a WAF or
   rate-limit response and is not the same evidentiary claim as an in-season
   404's documented "nothing published here." Fixed: `SourceError` now
   carries `status_code`; a streak of consecutive 403s (default threshold 3,
   never triggered by a single 403 or by any 404) raises a new
   `SuspectedSourceBlock` and aborts the run rather than recording each as
   confirmed absence. New 403-streak-abort test.
9. **Provenance URL could be silently overwritten.** Two different requested
   instants converging on the same masthead (the legacy hourly-truncation
   case) previously let a later request's URL overwrite the first-seen
   `source_url` with no audit trail. Fixed: `source_url` is now set only on
   row creation. New convergence-preserves-provenance regression test.
10. **Coverage exposure for the downstream join.** `select_canonical_pregame_
    observations` and the new coverage artifacts above expose stable
    per-player-game evidence and coverage; the join to `player_participation`
    itself remains, correctly, `injury-status-conversion`'s job, not this
    tool's — not changed, only clarified.

All ten points were independently re-verified against the actual pre-fix code
(not accepted on the reviewer's word alone) before being fixed, per house
rules. 67 tests now cover `test_injury_report_backfill.py` +
`test_injury_report.py` combined (up from 23), all passing; ruff/format/mypy
clean.

**Now true:** The natural key, cache/checkpoint/commit ordering, coverage
gate, era-conditional candidate strategy, 403 handling, and provenance
preservation described in the entry above are corrected. The **645
imported rows / 372 scoped rows / 203 canonical observations** figures in
the entry above are retained as a real, historically accurate record of what
that specific tool-validation run produced against the pre-fix code and a
deliberately small, non-representative 22-game sample (patched tip-offs on
3 of many dates) — **not** a representative or complete cohort, and not
re-claimed here as evidence toward `injury-status-conversion`. That entry's
closing claim, "`injury-status-conversion` is unblocked," is retracted: it
was written before this review found the natural-key collision above, which
alone means some of those 203 observations could have silently discarded a
real back-to-back row. `injury-status-conversion` remains blocked pending a
fresh live sample against the corrected code and independent re-review of
this remediation.

**Could not verify:** A fresh live-archive sample against the corrected code
(spanning both URL eras) had not been run when this entry was written — see
the following entry, if present, for that result or its absence. Native
PostgreSQL remains unavailable locally; migration `0012`'s chain
(`... -> 0011 -> 0012`) was validated only against a throwaway SQLite DB
locally, not GitHub's real PostgreSQL job, as of this entry.

**Next:** Run a corrected live bounded sample if network-accessible: report
real numbers, expected to differ from the retracted 645/372/203 figures.
Push the rebased, renumbered branch; get a fresh independent review of this
remediation (the prior reviews were both against pre-fix code); do not merge
or self-approve; do not report `injury-status-conversion` as unblocked until
that fresh review passes.

---

## 2026-08-18 — data-engineer — Fresh live sample against the corrected code, both URL eras, after PR #20 rebase and migration renumber

**Changed:** Rebased this branch onto `origin/main` at `0ff417a` (PR #20,
"Add league deadline calendar contract"). PR #20 claimed migration `0011`
(`0011_league_deadline_calendars.py`); this branch's migration — cut before
that merge as `0011` — was renamed and renumbered to
`0012_injury_report_natural_key_game_date.py`
(`revision="0012"`, `down_revision="0011"`). Rebase was clean, no conflicts
(PR #20 touches an unrelated subsystem). Ran a fresh, genuinely new live
sample against `ak-static.cms.nba.com` using the corrected `backfill.py`
directly (not an ad hoc counting script — the sample script only drives the
real `build_plan` / `enforce_full_tipoff_coverage` / `run_backfill` /
`coverage_for_games` functions and prints their own `.render()` output),
against 4 target dates chosen to cover **both** URL eras and include two
dates never previously probed in this project:

- **Legacy era (pre-2025-12-22):** 2025-11-01 (previously probed) and
  **2025-12-10 (new)** — 2 candidates each (`evening_before`, fixed
  `game_day@13:00`).
- **15-minute era (2025-12-22 onward):** 2026-01-15 (previously probed) and
  **2026-01-20 (new)** — 5 candidates each (`evening_before` plus the four
  bounded `near_tip_150/90/45/15` offsets anchored to that date's real
  earliest tip-off, patched from a live `BoxScoreSummaryV3` call per game).

Each date was run through `build_plan(start=date, end=date)` individually so
`enforce_full_tipoff_coverage` passed honestly (every game in each
single-date scope had a real patched tip-off; no `--allow-missing-tipoff`
override used anywhere) — the fail-closed gate added in the remediation
above was exercised for real, not bypassed.

**Result, all against the real, completed 2025-26 season:** 22 real games
across the 4 dates (5 + 2 + 8 + 7), all with live-patched tip-offs. 14 live
HTTP requests total (2+2+5+5, one per candidate) — **all 14 returned HTTP
200 on the first attempt** (0 failures, 0 `not_available`, 0 403s, no
`SuspectedSourceBlock` triggered), recorded in the raw payload store's own
`index.jsonl` with real `fetched_at` timestamps, byte sizes and SHA-256
content hashes (not fabricated — verified directly from that file after the
run). 14 distinct archived masthead timestamps recovered: `2025-10-31T21:30Z,
2025-11-01T17:30Z, 2025-12-09T22:30Z, 2025-12-10T18:30Z, 2026-01-14T22:30Z,
2026-01-15T21:30Z/22:30Z/23:15Z/23:45Z, 2026-01-19T22:30Z,
2026-01-20T21:30Z/22:30Z/23:15Z/23:45Z`. 860 `injury_report_entries` rows
imported for these 4 dates (natural key now includes `game_date`, so this
count is safe from the B2B-collision bug the remediation above fixed).
`select_canonical_pregame_observations` recovered **214** canonical pregame
player-game observations across the 22 games. `coverage_for_games` /
`render_observation_coverage` — the new committed `observations`-equivalent
reporting, not console counting — classified **all 22 games as `observed`,
0 as `no_candidate_coverage`, 0 as `not_yet_submitted_only`, 0 as
`missing_tipoff`** for this specific bounded sample.

A second invocation of the same script (immediately after, same database and
raw-store directory) exercised resume/idempotency for real: every one of the
14 candidates showed `already_cached` and `skipped (already settled)`, 0
re-fetches, 0 re-imports — confirming the cache-not-gating-but-checkpoint-
gating design from the remediation above behaves correctly on a genuine
second run, not just in the unit tests.

**Now true:** The corrected code has now recovered real archived reports
from **both** URL eras, including two dates (`2025-12-10`, `2026-01-20`)
never previously probed by any script in this project, with a 100% first-
attempt success rate on this specific bounded sample and zero coverage gaps
in it. The migration chain is `... -> 0010 -> 0011 (PR #20) -> 0012 (this
PR)`, single head, verified via `alembic upgrade head` + `alembic check` on a
fresh SQLite DB with no drift. Local gates all green post-rebase: `ruff
check` clean, `ruff format --check` clean (121 files), `mypy src` clean (78
source files), full `pytest -q` **635 passed, 17 deselected** (up from 558
pre-rebase, reflecting PR #20's own new tests plus this remediation's ~44 new
tests), `pytest -m adapter_contract` **142 passed, 510 deselected**, and the
repository's `scripts/check_no_secrets.py` reports no secrets in 229 tracked
files.

**Could not verify:**
- **Whether this 100%-success, zero-gap sample generalises to the rest of
  the season.** This remains a deliberately small, bounded 4-date/22-game
  sample chosen to exercise both eras and the fail-closed coverage gate
  honestly, not a full-season run — building the full committed fixture
  corpus for `injury-status-conversion` is explicitly that task's own job,
  as before.
- **GitHub's real PostgreSQL/migration-drift CI job** had not run against
  this exact rebased head when this entry was written — only local SQLite.
- **A fresh independent code review of the full remediation** (all 10
  points from the second review, against the new code, not the pre-fix
  `e96788a` code either prior review actually examined) had not completed
  when this entry was written.

**Next:** Push this rebased, renumbered branch. Get a fresh independent
review of the complete remediation. Coordinate the migration-slot race with
PR #22 explicitly — whichever of PR #21/PR #22 is independently reviewed and
merge-ready first keeps `0012`; the other restacks again onto whatever `main`
then owns. Do not merge or self-approve. Do not report
`injury-status-conversion` as unblocked until independent review of this
exact head passes.

---

## 2026-08-18 - data-engineer - Restack after absence-splits migrations

**Changed:** Rebased the league-settings branch onto main commit `5f75968`,
which added absence-splits revisions `0006` and `0007`. Renumbered the
league-settings migration from its former historical revision `0006` to
revision `0008` and changed its parent from `0005` to `0007`. The earlier
handoff entry remains unchanged because `0006` was accurate when originally
written; this entry records the effective revision after restacking.

The rebase conflicted only in this append-only handoff. Resolution retained the
complete quant `Descriptive teammate absence splits` entry from main first,
then retained both complete data-engineer league-settings entries, separated by
their original section boundaries. No production bridge-seam code changed
relative to pre-restack commit `e8c0ee4`.

**Now true:** Alembic reports exactly one head, `0008`, with the linear chain
`0005 -> 0006 -> 0007 -> 0008`. SQLite upgrade from empty, `alembic check`, and
downgrade to base pass. The rebased Code and Adapter gates pass locally: Ruff,
format, strict mypy, secret scan, 494 default tests, 75 recorded-fixture
contract tests, and all 13 live smoke tests.

**Could not verify:** No local Postgres service was available. The rebased
exact head still requires the repository's Postgres CI job and focused release
review before merge. No 2026-27 settings or real bridge settings capture became
available during the restack.

**Next:** Require green migration-from-empty and full-suite Postgres CI at the
new exact head, then repeat focused release review. Do not merge from the
pre-restack review.

---

## 2026-08-18 — data-engineer — PR #13 rebased after refresh-lineage merge

**Changed:** Rebased `sr2501-injury-report-ingest` onto `origin/main` after PR
#9 merged. The merged refresh-lineage migration is revision `0005` over
`0004`, so the injury-report migration was renamed from
`0005_injury_report.py` to `0006_injury_report.py` and changed consistently to
`revision = "0006"` / `down_revision = "0005"`. Resolved the append-only
handoff conflict by retaining both merged PR #9 entries and the injury adapter
entry; no adapter, fixture, importer, read-only boundary, or automation scope
was removed or widened.

**Now true:** Alembic has one linear head: `0001 -> 0002 -> 0003 -> 0004 ->
0005_refresh_lineage -> 0006_injury_report`. A fresh SQLite database upgraded
through every revision, reported `0006 (head)`, produced no operations from
`alembic check`, and downgraded through every revision to base. The full local
backend Code gate passed (Ruff lint and format, mypy strict on 81 source files,
446 tests with 14 live-smoke tests deselected, and the secret scan over 192
tracked files). The recorded-fixture Adapter gate passed separately (82
tests), and the live smoke suite passed separately against the real upstreams
(14 tests).

**Could not verify:** Native Postgres was not available locally, so the
rebased `0005 -> 0006` path was exercised from empty on SQLite only. The
repository's Postgres CI job remains the cross-dialect check after the
force-with-lease push. The live checks prove the archived source paths and
current parser contract still answer on 2026-08-18; they cannot prove the NBA
will retain the same CMS filename or PDF layout for 2026-27.

**Next:** PR #13 remains read-only and must not be merged by this session.
Review the post-rebase CI results, especially the Postgres migration job, then
merge only through the normal PR review path.

---

## 2026-08-18 — data-engineer — PR #13 re-rebased onto PR #10 (userscript auto-update); Postgres CI verified green

**Changed:** `main` advanced again after the previous rebase, past the
userscript auto-update PR (#10, `1c88325`), reopening conflicts on PR #13.
Re-ran `git rebase origin/main`: the migration numbering from the prior
rebase (`0006_injury_report.py` on `down_revision = "0005"`) needed no further
change, since PR #10 touched only the bridge/backend/userscript surfaces
(`api/routes/bridge.py`, new `api/routes/userscript.py`, `api/security.py`,
`core/config.py`, the userscript package itself) with zero overlap against
this branch's injury-report files. The only conflict was the same append-only
`docs/handoff.md` collision as before, now against PR #10's entry instead of
PR #9's; resolved identically by keeping both dated 2026-08-17 entries in
full (PR #10's bridge/backend/safety entry first, then this branch's
data-engineer entry), deleting only the conflict markers. Force-pushed with
`--force-with-lease` and let the repository's own GitHub Actions CI run
rather than approximating it locally.

**Now true:** `gh pr view 13` reports `mergeStateStatus: CLEAN` and
`mergeable: MERGEABLE` against current `main`. Both CI runs triggered by the
push (the `push` event on the branch and the `pull_request` synchronize
event) completed with `conclusion: success`, and critically this resolves the
prior entry's open gap: **`Backend — the same suite against Postgres
(ADR-001)` passed on GitHub's runner** (job `95712350451`, 2m40s), not just
the SQLite-only local check this session could run. Every other required
check also passed on both runs: Code gate — no secrets committed, Backend —
lint/type-check/tests, Backend — migrations apply from empty, Frontend,
Userscript, Model gate — backtests, and Adapter gate — recorded-fixture
contract tests. `Adapter gate — live smoke` reported `skipping` on both runs
(by design — it is allowed to fail loudly without blocking a merge, per
`docs/governance/gates.md`; it did not fail here, it simply did not execute,
consistent with how that job is gated in `ci.yml`) and did not affect
`mergeStateStatus`.

**Could not verify:** Why `Adapter gate — live smoke` shows `skipping` rather
than actually running or explicitly being skipped with a stated reason in the
job log — did not open the raw log for that job since it is documented as
non-blocking either way, but a future session should confirm this is the
job's designed conditional behavior (e.g. gated on a schedule/secret) rather
than an unnoticed regression in the workflow trigger logic. Did not attempt a
local Postgres run in this worktree (no `docker`/`psql`/`pg_ctl` on this
machine); the Postgres verification here rests entirely on the GitHub-hosted
runner's service container, which is the same authority CI merges are
normally judged against.

**Next:** PR #13 is CI-clean and mergeable as of this session; no further
rebase should be needed unless `main` advances again before merge. This
session made no write-path, automation, or scope changes beyond the rebase
and the handoff-conflict resolution described above.

---

## 2026-08-18 — data-engineer — PR #13: fixed 4 blocking findings from independent review

**Changed:** Independent review blocked PR #13 on four findings; fixed all
four with regression tests, then rebased again onto `main` (which had
advanced twice more, past PR #16 and PR #7). (1) `parser.py` was persisting
the caller's *requested* `report_timestamp` on every entry rather than the
PDF's own masthead instant. Because that field is part of
`injury_report_entries`'s natural key, and the legacy hourly-filename era
truncates a request to the hour while the masthead check tolerates 45
minutes of drift from it, two different in-tolerance requests for the same
PDF could each fabricate their own history row. `_verify_masthead` now
returns the masthead's own parsed instant (converted to UTC), and every
entry — and the returned `InjuryReportParseResult` itself — is stamped with
that canonical value, never the request argument. (2) `importers.py`
resolved which matchup tricode was "this" row's team from order-of-
appearance across the imported batch — a real defect: importing a partial
subset of a report (e.g. only the home team's rows, because the away team's
report had not been filed yet) or a reordered sequence let appearance order
disagree with the report's actual away-then-home structure and resolve a
team to its opponent. Replaced it with direct `team_raw -> nba_teams.name`
matching (the same "City Nickname" string `import_teams` already populates
from the stats API's own `full_name`), cross-verified against the row's own
matchup tricode pair — a resolution that needs no other row for context and
so cannot be fooled by import order or a partial batch. (3) A nonempty row
naming no player and no status, whose Reason was not the `NOT YET SUBMITTED`
marker, was silently `continue`-d past instead of raising. Fixed to raise
`SourceContractError`. Fixing this immediately surfaced a genuine,
previously-hidden defect in the real committed fixture: `Toppin, Obi`'s
wrapped, two-line Reason splits across a page break (`"...Stress"` on page
2, `"Fracture"` alone at the top of page 3), and that orphaned continuation
was being silently dropped, truncating the real reason. Added a narrowly-
scoped exception — only the first row-segment of a page after the first,
with every column but Reason blank — that reattaches the continuation to
the preceding entry instead of raising or dropping it. (4) Added a second
live-smoke probe against the active 15-minute-granularity filename era
(`2026-01-15 17:30`, the convention 2026-27 will actually use), distinct
from the existing legacy-era probe, with documented rotation/failure
behavior in the test's own docstring; it remains `live_smoke`-marked
(visible on demand, never part of the blocking Code/Adapter gate).

**Now true:** All four fixes have dedicated regression tests: masthead
canonicalization proven by parsing the same fixture PDF with two different
in-tolerance request instants and asserting both the parse result and an
idempotent import converge on one canonical timestamp and one row set; team
resolution proven by a partial-subset case (only the home team's row
present) and a reordered-entries case, both asserting the correct team
survives rather than swapping to its opponent; the loud raise proven by
exercising the full `parse_injury_report_pdf` entry point (not a private
helper) against a synthetic pdfplumber-page double with a monkeypatched
`pdfplumber.open`; and the page-break reattachment proven directly against
the real fixture, asserting `Toppin, Obi`'s reason now reads
`"Injury/Illness - Right Foot; Stress Fracture"` in full. `docs/adapters/
nba-injury-report.md` was updated to describe all of the above, including
the corrected team-resolution rationale (the order-of-appearance claim it
previously documented was itself part of the defect). Rebased cleanly onto
current `main` (past PR #16's docs-only ADR-008/governance commit and PR
#7's `schedule-density` work, neither of which touches any injury-report
file); the only conflict was the same append-only `docs/handoff.md`
collision as both prior rebases, resolved identically by keeping every
dated entry in full. Local Code gate green: ruff lint/format, mypy strict
(84 source files), full default pytest suite, and the 3
`TestInjuryReportIsAlive` live smoke tests run separately against the real
source (including the new active-era probe). Pushed with
`--force-with-lease`; both GitHub Actions CI runs (`push` and `pull_request`
synchronize) completed `success`, including `Backend — the same suite
against Postgres (ADR-001)`. `gh pr view 13` reports `mergeStateStatus:
CLEAN`, `mergeable: MERGEABLE`.

**Could not verify:** Whether a third, still-undiscovered malformed-row
shape exists elsewhere in the real report that the new loud-raise would
also need a reattachment exception for — only the one page-break case
surfaced by the committed fixture was found and handled; a different capture
could still expose another shape the raise correctly flags as unexpected
review-worthy behavior rather than something this fix silently papers over.
Did not re-verify `Adapter gate — live smoke`'s `skipping` conclusion in this
pass (open from the prior entry); still believed non-blocking by design, not
re-inspected further here.

**Next:** PR #13 is CI-clean and mergeable as of this session. Did not merge
and did not self-approve, per instructions; the branch awaits an independent
reviewer's confirmation that these four fixes actually close the findings
they were raised against.

---

## 2026-08-18 — data-engineer — PR #13: current-season dynamic live-smoke probe (MEDIUM finding)

**Changed:** Focused re-review confirmed the four core fixes but held one
MEDIUM Adapter-gate finding: the new "active-era" live smoke probe added to
close finding 4 still used a fixed, permanently archived January 2026
timestamp. An archived URL survives a filename-format rotation by
construction — the CDN keeps serving the exact bytes it always served for
that historical path — so it can never detect the NBA introducing a
*third* filename convention or PDF layout for 2026-27. Added
`select_recent_report_candidate` (`test_injury_report.py`, offline,
unit-tested, no `live_smoke` marker) and a new
`TestInjuryReportCurrentSeasonIsAlive` live test
(`test_live_smoke.py`) built on it, rather than a fixed archive. The
candidate is grounded in an independently defensible fact, not a calendar
guess: `SEASON_2026_27_START = date(2026, 10, 20)`, the actual first
`gameDate` in the already-recorded, really-captured `ScheduleLeagueV2`
fixture (`nba_scheduleleaguev2_2026_27.json`). Only within that season's
window (through a documented 240-day span covering the regular season and
playoffs) does the function return a candidate — yesterday-evening-ET, the
report's own documented publication window — clamped so opening day never
probes a "yesterday" before the season existed. Outside that window it
returns `None`, and the live test explicitly `pytest.skip`s with the reason
spelled out, rather than either a noisy off-season red failure or the
failure mode the review specifically called out: silently treating an
expected 403/404 as evidence the adapter still works. When in season, a
403/404 or parse failure on the chosen candidate is a real, unswallowed test
failure — the whole point of picking a timestamp a report is actually
expected to exist for. Exactly one candidate, therefore at most one HTTP
request, per run. The archived legacy and 15-minute-era probes from finding
4 are unchanged and still run alongside this one.

**Now true:** Six new offline unit tests in `test_injury_report.py` pin the
selection logic directly: naive-`now` rejection, `None` before the season
starts (exercised against the real current date, 2026-08-18, which *is*
before the season), `None` long after the season span, the ordinary
in-season case, the opening-day clamp, and a non-Eastern-aware `now`
(UTC) converting correctly. Ran the live test directly today: it
`pytest.skip`s with the exact off-season message, confirming the guard
behaves as designed against the real current date rather than only in
unit tests. `docs/adapters/nba-injury-report.md` gained a "Live smoke
coverage" section stating plainly what the dynamic probe can detect (URL/
layout drift for a *current* request) and cannot (which specific format
era is active, or "source broke" vs. "no game that day" any more precisely
than the 240-day approximation allows). Full local Code gate green: ruff
lint/format (one file needed `ruff format` after adding the new tests, now
clean), mypy strict (84 source files), full default pytest suite, and the
injury-report live smoke tests run separately (3 passed, 1 skipped — the
new current-season probe, correctly, since today is off-season).

**Could not verify:** Whether the dynamic probe actually executes (rather
than skips) once the 2026-27 season starts — by construction, that cannot
be observed until October 2026. The 240-day season span is an approximation
extrapolated from typical regular-season-plus-playoffs length, not a
captured end-of-season date; no fixture yet records when the 2026-27 season
actually concludes, so a future session should tighten this once one does.

**Next:** PR #13 awaits the independent reviewer's focused re-review of
this fix. This closes the last outstanding finding raised so far; no other
follow-up is expected from this session absent further review feedback.

---

## 2026-08-18 — data-engineer — PR #13: fixed 2 remaining blockers in the dynamic live-smoke probe

**Changed:** Final focused review of the prior commit found two real
defects in the current-season dynamic probe: (1) the opening-day clamp
could select a **future** timestamp — on opening day itself, if "now" was
earlier that same morning, the clamp returned that same day at 17:30 ET,
which is *after* "now", guaranteeing a false-red 404 against a report not
yet published; (2) the fixed "yesterday always has a game" rule silently
treated routine no-game dates (All-Star break, scattered rest days, gaps
beyond the recorded schedule) as source drift, when a 403/404 on a genuine
no-game date is the correct response, not a bug. Redesigned
`select_recent_report_candidate` from scratch to eliminate both classes of
guess rather than patch around them: a candidate is now **only** ever built
from a date `known_game_dates_from_schedule_fixture` reads directly from the
real, committed `nba_scheduleleaguev2_2026_27.json` capture (currently
`2026-10-20`, `2026-12-04`, `2027-03-14`) — never "yesterday", never a
clamped guess — and among those known dates, only the most recent one that
is both **strictly before now** (never future/present) and within a 45-day
`FRESHNESS_WINDOW` (so a stale, months-old anchor is not silently treated as
current) is eligible. `SEASON_2026_27_START`/`SEASON_SPAN` are gone entirely,
replaced by this schedule-grounded selection. The function also now accepts
an optional `known_game_dates` override so its offline unit tests can
exercise arbitrary calendar shapes (a no-game gap, a stale anchor, multiple
candidates) without waiting for the real fixture's sparse three dates to
line up. `test_live_smoke.py`'s `TestInjuryReportCurrentSeasonIsAlive` and
its skip message were updated to match; the archived legacy/15-minute probes
and the one-bounded-request property are unchanged.

**Now true:** Eight offline unit tests in `test_injury_report.py` pin the
new logic directly, including the two specific defects found: a same-day
game date is rejected until its own evening has passed (proves fix 1) and a
day with no confirmed game is skipped in favour of the true most recent
known game date rather than assumed to have one (proves fix 2), plus
naive-`now` rejection, the pure off-season case (empty known-dates list),
multi-candidate "most recent wins", the stale-anchor freshness cutoff, a
non-Eastern-aware `now`, and a direct pin of
`known_game_dates_from_schedule_fixture`'s three real dates so the whole
design stays anchored to what the committed fixture actually contains.
Ran the live test directly today (2026-08-18): it `pytest.skip`s with the
new, more precise reason (no known game date is both published and fresh
enough) rather than the old season-window message. `docs/adapters/
nba-injury-report.md`'s "Live smoke coverage" section was rewritten to
describe both fixes and the new schedule-grounded design plainly. Full
local Code gate green: ruff lint/format (one reformat needed after the new
tests, now clean), mypy strict (84 source files), full default pytest
suite, and the injury-report live smoke tests run separately (3 passed, 1
skipped — the dynamic probe, correctly, for the new stated reason).

**Could not verify:** Whether the dynamic probe actually fetches (rather
than skips) once a known game date both exists and is fresh — by
construction, the earliest that can happen live is 2026-10-20 evening
onward, which has not arrived yet. The 45-day `FRESHNESS_WINDOW` is a
judgment call, not a captured value; a future session may need to widen it
if the schedule fixture's recorded anchors are not refreshed often enough
to keep the probe from going quiet for long season stretches.

**Next:** PR #13 awaits another focused re-review of this HEAD. No other
follow-up is expected from this session absent further review feedback; did
not merge or self-approve.

---

## 2026-08-18 — data-engineer — PR #13 re-rebased onto PR #17/#18 (absence-splits, league-settings); migration renumbered 0006 → 0009

**Changed:** `main` advanced again, past two migration-bearing PRs
(`#17` absence-splits, revisions `0006`–`0007`; `#18` league-settings
snapshots, revision `0008`) that both landed on the same `0006` revision id
this branch's injury-report migration already claimed — an unavoidable
collision, since both were authored independently against the same prior
head (`0005`). Rebased onto `origin/main`; the only textual conflicts were
the same recurring append-only `docs/handoff.md` collision (resolved
identically, keeping every dated entry) and import-ordering conflicts in
`importers.py` (both sides added new alphabetically-ordered imports at the
same location — merged to keep all of both: `datetime`/`date`,
`InjuryReportEntry`/`League`/`LeagueSettingsSnapshot`, and
`InjuryReportEntryRecord`/`LeagueSettingsDocument`). Renamed
`0006_injury_report.py` to `0009_injury_report.py` and changed
`revision = "0009"` / `down_revision = "0008"` to sit after the new head.

**Now true:** Alembic has one linear chain: `0001 -> 0002 -> 0003 -> 0004 ->
0005 -> 0006_absence_splits -> 0007_absence_split_activations ->
0008_league_settings_snapshots -> 0009_injury_report`. A fresh SQLite
database upgrades through every revision, `alembic check` reports no new
operations, and downgrade to base succeeds cleanly. Full local Code gate
green: ruff lint/format, mypy strict (91 source files, up from 84 — this
rebase pulled in the absence-splits and league-settings modules), full
default pytest suite, and the injury-report live smoke tests run separately
(3 passed, 1 skipped — the dynamic probe, correctly, for the same reason as
before). No adapter, fixture, importer, read-only boundary, or automation
scope was removed or widened by this rebase; only the migration number and
merged import lines changed outside of `docs/handoff.md`.

**Could not verify:** Native Postgres was not available locally, so
`0008 -> 0009` was exercised from empty on SQLite only in this pass; the
repository's Postgres CI job remains the cross-dialect authority after the
push.

**Next:** PR #13 awaits another focused re-review at this new HEAD. Did not
merge or self-approve.

---

## 2026-08-18 — data-engineer — PR #13: dates-only 2026-27 calendar fixture closes the Dec→Mar blind interval

**Changed:** A third focused review at the exact HEAD accepted the future-
timestamp and unconfirmed-game-day fixes but found the remaining anchor set
too coarse: `nba_scheduleleaguev2_2026_27.json`'s three deliberately-sparse
kept dates (chosen for schedule-density/timezone test coverage, not for
this purpose) produced up to a 54-day midseason skip, up to 100-day
detection latency, and never covered anything after 2027-03-14 — and since
archived CDN URLs stay live indefinitely, an up-to-45-day-old candidate
barely improved on the fixed-archive probes this whole redesign exists to
get past. Fetched the real, live `ScheduleLeagueV2` response for the
2026-27 season directly via `NbaStatsClient.schedule_league` (the same
adapter method `schedule-ingest` already uses) — confirmed all 173
`gameDates` the existing fixture's manifest note already claimed — and
derived a new, compact **dates-only** fixture,
`nba_scheduleleaguev2_2026_27_gamedates.json`: every `gameDate`'s date
string, no game objects, team/player identities, or box scores, with the
13 preseason-only dates (every game that day labelled `gameLabel ==
"Preseason"`) excluded, since the injury-report adapter is out of scope
before the season's first game (R40, `docs/backlog.md`). 160 real
regular-season dates remain, 2026-10-20 through 2027-04-11, whose largest
gap is 7 days (the All-Star break, 2027-02-18 → 2027-02-25). Registered it
in `tests/fixtures/manifest.json` following the existing trimmed-fixture
schema, with a note explaining the derivation and preseason exclusion.
`known_game_dates_from_schedule_fixture` now reads this new fixture instead
of the old three-date one (which is untouched and still serves
`test_schedule.py`). Tightened `FRESHNESS_WINDOW` from 45 to **10 days** —
sized directly from the measured 7-day maximum gap plus a small buffer,
not a guess.

**Now true:** Three new offline unit tests in `test_injury_report.py` prove
exactly what was asked: the December-to-March blind interval is gone (four
probe dates spanning that old gap all now find an eligible, bounded-age
candidate); candidate age stays within `FRESHNESS_WINDOW` for *every*
calendar day across the entire real season (a day-by-day walk from the
season opener through the last recorded date, including the All-Star break
and every other real gap, against the actual committed fixture rather than
a synthetic list); and a run well past the season's last recorded date
skips rather than reusing a stale archive. The existing fixture-reading
test was rewritten to pin the new fixture's actual shape (160 dates, first/
last, preseason exclusion, 7-day max gap) instead of the old three dates.
Ran the live test directly today: it still `pytest.skip`s (correctly —
today, 2026-08-18, precedes every 2026-27 date), now citing the 10-day
window. Full local Code gate green: ruff lint/format, mypy strict (91
source files), full default pytest suite (fixture-manifest contract tests
included), and the injury-report live smoke tests run separately (3
passed, 1 skipped for the updated reason).

**Could not verify:** Whether the live `NbaStatsClient.schedule_league`
fetch used to derive this fixture will keep returning the same 173
`gameDates` if re-run later (the NBA can and does revise its own published
schedule); this fixture is therefore a point-in-time capture like every
other one in `manifest.json`, not a live source of truth, and a future
session refreshing it should re-derive rather than hand-edit it. Whether
10 days remains the right freshness threshold for a future season's
calendar (a longer All-Star break, a lockout-shortened season, etc.) was
not tested beyond the one real 2026-27 shape measured here.

**Next:** PR #13 awaits another focused re-review at this new HEAD. Did not
merge or self-approve.

---

## 2026-08-18 — backend — Schedule-context schema provenance extension

**Changed:** Added keyed, season-scopeable refresh lineage with a portable
`source` artifact type, and registered NBA schedule cohorts under the stable
`nba-schedule` key. Extended both schedule-context tables with a required
`source_version`; added the off-night input snapshot, nullable uncalibrated
garbage-time suppression, bounded probability/percentile checks, nonnegative
count checks, and the team/opponent inequality. Alembic revision `0009`
preserves existing history and backfills explicit legacy provenance before
removing its temporary server defaults.

---

## 2026-08-18 — quant — `scoring-profiles`: third remediation round (A→B→A dead-end, schema v2 backfill, category-shape drift, evidence path)

**Changed:** Five findings from an independent review at
`4565f65877032884b39b17e54cd6b3fc3b8649d9` (PR #22), all fixed:

1. **A→B→A dead-end.** `build_scoring_profile`'s reuse query previously
   matched an existing profile by `(league_id, name)` plus a content
   fingerprint alone, so a stale row from an old snapshot could be "reused"
   even though it still cited that old snapshot's now-non-current FK —
   activation then correctly rejected it, and no later derive could ever
   escape. Fixed by adding `settings_snapshot_id == settings_snapshot.id` to
   the reuse query itself: only a profile already derived from the *exact*
   current snapshot row can ever be returned as a dedupe hit. A new snapshot
   row with content identical to an old one now always mints a new,
   immediately activatable profile version citing the current snapshot —
   A→B→A yields a genuine v3, not a resurrection of v1. Rewrote the A→B→A
   test to assert this (new id/version, correct snapshot FK, activatable)
   instead of claiming row reuse across snapshots, which this design
   deliberately no longer does (see `profiles.py`'s updated docstrings for
   why: reusing an old row's *identity* across snapshots would silently
   rewrite which snapshot every historical activation record points at).
2. **Schema v1 → v2 backward compatibility.** `LeagueSettingsDocument`
   gained two required fields (`scoring_type`, `scoring_categories`) in the
   prior round without bumping its own `schema_version`, so every
   pre-existing `league_settings_snapshots.settings` blob became unreadable
   — breaking `import_league_settings`'s re-ingest dedupe and
   `derive_deadline_calendar`'s current-snapshot read, both of which call
   `LeagueSettingsDocument.model_validate()` on a stored blob. Bumped
   `SCHEMA_VERSION` to `2`, added a `MIGRATION_SOURCE = "schema_migration"`
   evidence source distinct from `fantrax_official`/`fantrax_bridge`, and
   extended migration `0012` (still the provisional slot — see below) to
   backfill every existing snapshot row: both new fields become an explicit
   *absent* observation evidenced as `schema_migration` (never a real
   source, since nothing was actually observed for that row), built from
   that row's own provenance (payload hash, observed-at instant), not one
   placeholder reused everywhere. `downgrade()` refuses with a loud
   `RuntimeError` if any row carries genuine post-migration
   `fantrax_official`/`fantrax_bridge` scoring evidence (real data would be
   silently discarded), and only cleanly reverts rows whose evidence is
   entirely migration-sourced. Three new regression tests in
   `test_migrations.py` prove: the backfilled shape and evidence are
   correct; a real `import_league_settings` call against the migrated row
   succeeds (creating a new version rather than raising, since a
   `schema_migration`-sourced absent observation is evidentially distinct
   from a fresh `fantrax_official`-sourced one — by design, not a bug: the
   migrated row honestly means "we never asked", not "the source confirmed
   nothing"); the downgrade refusal fires on genuine evidence; and a clean
   downgrade succeeds on a purely-synthesized row.
3. **Category-config shape drift.** `parse_scoring_category_configs`
   previously `continue`d past a non-dict `scoringCategorySettings` entry, a
   non-list `configs`, a non-dict `config`, or a non-dict `scoringCategory` —
   letting one malformed entry among nine silently produce eight
   valid-looking categories instead of a loud failure. All four now raise
   `SourceContractError` with an indexed, descriptive message. Four new
   regression tests in `test_scoring_profiles.py` exercise each level
   through the real `parse_official_league_settings` seam.
4. **`scoring_type` evidence `source_path`.** Previously hardcoded to the
   nested `$.scoringSystem.type` path regardless of which field actually
   won under official-priority precedence (a top-level `scoringType` wins
   when present). Refactored `parse_scoring_type_raw` to delegate to a new
   `_scoring_type_with_source_path()` helper returning both the value and
   the winning path; `_parse_scoring_type` now cites the correct one. Two
   new tests cover both precedence outcomes (nested-only, and top-level
   winning over a losing nested value) and assert the evidence path matches.
5. **Doc correction.** `docs/adapters/fantrax-official.md` previously said
   `configs[*].position` is "read but not carried" into the domain document
   — it is not read at all. Corrected.

**Now true:** Full local Code gate green: `ruff check .`, `ruff format
--check .`, bare `mypy` (matching CI's whole-project invocation, not just
`mypy src`) clean across 108 source files, full `pytest -q` (all backend
tests, SQLite) green including the three new migration-lifecycle tests and
the five new scoring-profile regression tests. Migration `0012`'s
`upgrade()`/`downgrade()` round-trip verified on SQLite with populated data
in both directions (backfill-then-read, and both downgrade outcomes).

**Could not verify:** Postgres CI (no local Postgres in this environment;
relies on GitHub Actions' Postgres job, not yet observed for this exact
push). **Migration slot collision:** PR #21 (`sr2501-historical-injury-
backfill`) independently also claims revision `0012`/`down_revision 0011`
(its own commit history references this explicitly), and its GitHub state
was observed as `mergeStateStatus=CLEAN`, `mergeable=MERGEABLE`, fully green
CI, having already been through multiple independent-review rounds — i.e.
plausibly closer to merge-ready than this round's fresh, not-yet-reviewed
head. `origin/main` is still `0ff417a` (unchanged since PR #20), so neither
PR has actually landed `0012` yet and the slot remains formally open to
whichever merges first, per the standing instruction — this was not
resolved unilaterally here (deciding which PR is "more merge-ready" is a
merge-queue coordination call, not this session's to make), and is reported
back to the coordinating session rather than acted on. Whichever PR merges
second will need another restack/renumber to whatever slot is open at that
point. GitHub CI status for this exact push (beyond local gates) not yet
observed.

**Next:** Push this head, wait for CI (Postgres included), then two fresh
independent focused reviews (code correctness/layer-purity, and
quant/statistical semantics) against this new diff. Report the collision
above to the coordinating "Autonomous merge queue" session explicitly. Not
merged, not self-approved.

**Now true:** Refresh streams can reuse version labels without colliding across
artifact keys, callers can distinguish an omitted season filter from an
explicit unscoped (`NULL`) season, and changed descriptive sources create new
schedule-context history rather than overwriting an existing natural key.

**Could not verify:** Native Postgres was not available locally. The migration
and its legacy-row backfill were exercised on SQLite, and the existing CI
Postgres migration job remains the required dialect verification. Downgrading
after writing `source` refresh rows, duplicate legacy keys, or null
garbage-time values will correctly refuse lossy conversion rather than delete
or invent data.

**Next:** The quant-owned computation may populate these contracts only after
its Model gate; no schedule-context math, thresholding, playoff behavior, or
schedule-density logic was added here.

---

## 2026-08-18 — quant — Versioned schedule context and held-out blowout calibration

**Changed:** Completed `schedule-context` without moving any pure calendar
arithmetic out of the merged `schedule-density` contract. Added a quant-owned
service that derives per-date slate counts and empirical light-slate percentiles
directly from `team_schedule`, trailing pace from possession estimates, and
volume-correct opponent category allowances (counting categories per 100
possessions; FG/FT as summed makes and attempts). Added a simple empirical
blowout-probability model based on strictly pre-game trailing point-margin gaps,
plus transactional publication/persistence that binds each row to keyed
schedule, scoring-source, and model cohorts. Stale schedule, changed source,
superseded model, and unknown cohorts raise before writes; natural keys retain
older source/model/schedule outputs. `streaming_window_score` and
`garbage_time_suppression` remain null because no held-out evidence supports
their magnitude.

**Now true:** The descriptive/model boundary is executable rather than only
documented. Off-night rows make no fantasy-period or playoff-date assumption,
and opponent rows use only observations before each fixture with exact game IDs,
feature cutoff, and offseason-carryover flag in `input_snapshot`. The blowout
bin count was selected on a 2024–25 validation season after fitting 2023–24,
then locked, refit on 2024–25, and evaluated once on untouched 2025–26:
1,225 held-out games, Brier 0.23314 versus 0.23464 for the constant-rate
baseline, and ECE 0.03229. The improvement is deliberately described as small;
the highest-risk bin predicted 36.7% and realized 44.0%, so v1 is context for a
human, not permission to alter minutes, values, or automated actions. The
committed evidence and blind spots are in
`backend/tests/model_evidence/schedule_context_blowout_v1.json`, the reproducible
live run is `python -m hoops_gm.schedule_context.backtest`, and the model card is
`docs/models/schedule-context.md`. Local gates pass: Ruff, format, strict mypy,
458 default tests, four dedicated `model_backtest` tests, and SQLite migration
upgrade/check/downgrade from empty.

**Could not verify:** Native Postgres was not available locally, so CI remains
the dialect check for revision `0009` and its enum/constraint rebuilds. The
committed gate validates the evidence contract but does not recreate all 3,676
source games offline; the live reproduction was run successfully against
`nba_api:LeagueGameFinder` in this session, and a future source change must
produce a new evidence/model version. No full production database containing
multi-season player logs plus the complete 2026–27 schedule was available, so
the persistence run is integration-tested on constructed rows rather than
executed for every real fixture. The model cannot see trades, coaching/rotation
changes, injuries, market spreads, front-office intent, or where a team spent an
off-day. Opening-week pace/defence and margin windows carry prior-season form
and are marked as such; they are especially fragile after offseason turnover.
No downstream availability, reliability, streaming, projection, or
strength-of-schedule consumer exists yet to exercise cohort rejection across a
second module.

**Next:** `reliability-metrics` may consume blowout probability only as visible
context until it separately validates player-specific minutes suppression.
`availability-model` and later `strength-of-schedule` consumers must pass the
exact schedule/source/model versions they used and reject this service's stale
cohort error rather than falling back. `frontend` may display off-night,
pace/defence, and blowout evidence, but must not present the null suppression or
streaming score as zero.

---

## 2026-08-18 — quant — Serialize schedule-context cohort publication

**Changed:** Closed the last concurrency gap in schedule-context publication.
The database seam now uses transaction-level PostgreSQL advisory locks, including
for unpublished scopes, and an SQLite no-op update to reserve the writer before
cohort validation. Schedule and scoring-observation importers acquire the same
scopes before mutation, while context publication locks before fingerprinting its
source snapshot. Migration `0009` now refuses any populated downgrade that would
discard keyed/source lineage, context provenance, nullable suppression, or
version history before altering the schema.

**Now true:** Schedule/source/model currentness checks and context writes execute
under one transaction whose refresh scopes cannot be concurrently superseded on
either supported database. Final local gates pass against current `main`: Ruff,
format, strict mypy, 466 default tests, four dedicated `model_backtest` tests,
the secret scan, and SQLite migration upgrade/check/downgrade.

**Could not verify:** Native PostgreSQL was not available locally. PostgreSQL's
advisory-lock path remains covered by the required CI Postgres job rather than a
local contention test.

**Next:** CI must exercise the full suite and migration round trip on PostgreSQL;
this PR must not merge or self-approve.

---

## 2026-08-18 — quant — Close schedule-context release-integrity blockers

**Changed:** Made the Model-gate evidence the packaged production release
artifact instead of a test-only file. The production registry allowlists model
`4809af29ed135f6f`, pins the artifact SHA-256, and independently derives the
version from its training fingerprint and fitted parameters; publish/compute no
longer accept arbitrary `BlowoutModel` objects. Reproduced the live backtest and
added immutable training, validation, and held-out source fingerprints plus
sample boundaries. Restricted v1 scoring/history to regular-season rows, added
team player-minute completeness checks, staged all profiles before writes,
enforced a version-bound 95% fixture-coverage floor, persisted the coverage
audit in every output, and rejected naive `computed_at` values.

**Now true:** The exact model that passed the gate is loadable from an installed
wheel and an edited, self-relabelled, or locally fitted variant cannot become
production lineage. A three-player subset, unequal/incomplete team minutes,
systemically empty context, playoff history, weak caller-supplied coverage
threshold, or host-local naive timestamp cannot silently produce a successful
cohort. Final local gates pass: Ruff, format, strict mypy, 487 default backend
tests, six dedicated `model_backtest` tests, secret scan, SQLite migration
upgrade/check/downgrade, and a built-wheel resource check.

**Could not verify:** Native PostgreSQL was not available locally, so advisory
lock behavior and the migrated schema still rely on CI's Postgres job. The live
reproduction confirms the currently returned NBA source fingerprints, but only
a future re-run can demonstrate that an upstream score correction changes them.
V1 has no automated online calibration monitor and cannot establish that the
2024-25 training base rate remains current for 2026-27.

**Next:** Independent reviewers should recheck the six blockers against the new
exact HEAD. CI must pass Code and Model gates, including PostgreSQL, before this
PR is eligible; it must not be merged or self-approved here.

---

## 2026-08-18 — quant — Restack schedule-context provenance after league settings

**Changed:** Rebased the complete schedule-context remediation onto league
settings commit `2369d8f`, preserved both append-only handoff histories, and
renumbered schedule-context provenance from revision `0008` to `0009` with
`down_revision = "0008"`. No descriptive feature, released model, source
fingerprint, completeness, coverage, timestamp, or cohort-lock behavior changed.

**Now true:** Alembic has one linear head, `0009`, after league-settings `0008`.
The cumulative local gates pass against the rebased tree: Ruff, format, strict
mypy, 525 default backend tests, six dedicated `model_backtest` tests, secret
scan, SQLite upgrade/check/downgrade, and the built-wheel release-resource check.

**Could not verify:** GitHub's real PostgreSQL and migration jobs had not run on
this exact restacked head when this repository entry was written. Local SQLite
cannot prove PostgreSQL advisory-lock execution.

**Next:** Require all exact-head GitHub checks, especially PostgreSQL and
migrations, to pass and repeat the two focused reviews. Do not merge or
self-approve from this session.

---

## 2026-08-18 — quant — Canonicalize the packaged release digest

**Changed:** Exact-head Linux CI exposed that the release registry hashed the
JSON artifact's raw bytes, so Git's CRLF/LF checkout normalization made the
Windows-gated artifact fail its Linux digest check. The registry now hashes the
parsed artifact in canonical sorted, compact JSON form and pins that content
identity. Added a regression proving LF and CRLF encodings produce the same
release digest.

**Now true:** The production loader still rejects changed Model-gate evidence,
but line-ending-only checkout differences no longer change the verified
identity. Final local gates pass: Ruff, format, strict mypy, 526 default backend
tests, seven dedicated `model_backtest` tests, secret scan, SQLite
upgrade/check/downgrade with one `0009` head, and loading release
`4809af29ed135f6f` directly from the newly built wheel.

**Could not verify:** GitHub's Linux and PostgreSQL jobs had not rerun against
this correction when this entry was written. Canonical serialization removes
the observed platform-dependent mechanism; exact-head CI remains the required
independent verification.

**Next:** Push with force-with-lease against the reviewed remote head and require
every exact-head GitHub check, including real PostgreSQL and migrations, to pass.
Do not merge or self-approve from this session.

---

## 2026-08-18 — quant, backend — Close final schedule-context history gaps and restack after injury reports

**Changed:** Rebased PR #19 onto injury-report main commit `875d40e`, preserved
both sides of the append-only handoff conflict, and restacked schedule-context
provenance as Alembic `0010` with `down_revision = "0009"`. Off-night slates now
stamp `claim.source_version`; source version is part of their natural key and
indexed, so two scoring-source cohorts retain two independently valid coverage
audits instead of overwriting one row. Pace/defence history now audits the last N
**scored** regular-season games for each team/fixture against complete team box
scores. Any incomplete member raises before slate or opponent writes, rather
than letting `_team_history` backfill from arbitrarily old valid games.

**Now true:** Successful opponent rows persist exact scored/complete game IDs,
latest scored/complete dates, and recency days for both teams. Every opponent and
slate row also persists an aggregate observation-completeness audit alongside
fixture coverage. The off-night derivation version includes the history window
and minimum history because those settings affect its persisted coverage audit.
Regressions invalidate the recent 15 of 30 team games and prove zero writes, keep
the 95% fixture-coverage failure, and prove two slate source histories survive.
The model card now explains the 1,146 examples from 1,225 training games (79
cold-start drops), all 1,225 carryover holdout examples, fit/serve offseason
asymmetry, statistically significant top-bin underprediction, canonical-JSON
SHA-256 pinning, and display-only 2026-27 posture. It also corrects the earlier
handoff's `3,676` source-game total to the artifact-backed `3,680` without
rewriting that historical entry.

Local cumulative gates pass on the rebased tree: Ruff, format, strict mypy, 558
default backend tests including seven `model_backtest` tests, 12 frontend tests
plus lint/type-check/build, 63 userscript tests plus build, secret scan, SQLite
upgrade/check/downgrade through the single `0010` head, and loading release
`4809af29ed135f6f` from a newly built wheel.

**Could not verify:** Native PostgreSQL remains unavailable locally. GitHub's
real PostgreSQL, migration, and cumulative CI jobs had not run against this
exact remediation when this entry was written. V1 still has no online drift
monitor; serving it as 2026-27 display context does not establish current-season
calibration.

**Next:** Force-push with lease, require every exact-head GitHub check including
PostgreSQL and migrations to pass, and return the new head to both reviewers for
focused recheck. Do not merge or self-approve from this session.

---

## 2026-08-18 — quant, backend — Separate opponent derivation and blowout release lineage

**Changed:** Closed the final reproducibility gap in opponent context. The old
`OpponentContext.model_version` represented only the calibrated blowout release,
so changing the descriptive pace/defence history window reused the same natural
key and overwrote prior numeric rows. Opponent context now carries two explicit
dimensions: `opponent_derivation_version`, a fingerprint of the complete
pace/category-defence specification plus trailing window, minimum history, and
coverage threshold; and `blowout_model_version`, the separately pinned calibrated
release. Both have independent MODEL refresh keys, transaction locks, current
activation checks, indexes, and positions in the opponent natural key.

**Now true:** Publishing a configuration explicitly activates its opponent
derivation cohort and its blowout release cohort; computation requires the exact
claim and recomputed config fingerprint. No maximum-version or row-reuse
heuristic selects current context. A regression computes `trailing_games = 10`,
then explicitly publishes and computes `trailing_games = 5`: all eight opponent
rows remain queryable (four per derivation), windows and pace/defence values
differ, the blowout release stays identical, the superseded 10-game activation
is rejected as stale, and a config/claim mismatch is rejected. Alembic remains
revision `0010` over injury-report `0009`; its populated upgrade backfills
`legacy-unbound` derivation lineage while preserving the old model value as
`blowout_model_version`, and its downgrade refuses incompatible history.

**Could not verify:** Native PostgreSQL was not available locally when this entry
was written. GitHub's real PostgreSQL and migration jobs remain required on the
new exact head. This is a provenance/persistence correction only; no blowout
math, fitted parameter, evidence cohort, calibration result, or display-only
posture changed.

**Next:** Run cumulative Code and Model gates, SQLite lifecycle and built-wheel
loading, force-push with lease, require exact-head GitHub/PostgreSQL green, and
return the head for one narrow code recheck. Do not merge or self-approve.

---

## 2026-08-18 — backend — `deadline-model`: the smallest honest calendar contract

**Changed:** Implemented `deadline-model` against merged `league-settings-ingest`
and `schedule-ingest`. `league-settings-ingest`'s own handoff entry already
established, against the live `getLeagueInfo` response, that Fantrax's official
source supplies only roster limits and scoring-period boundaries — lineup lock,
waivers, trade deadline, playoffs, and keeper rules are absent from every source
observed so far and can only become known through the existing bridge capture.
Computing "every future deadline" as originally scoped would therefore mean
inventing five of the seven concerns the backlog item names. Built the smallest
contract that is still honest instead.

Migration `0011` adds `league_deadline_calendars`: one immutable, versioned row
per league joining an exact `LeagueSettingsSnapshot` with an exact schedule
refresh cohort (`hoops_gm.db.lineage`'s `RefreshRun`, `artifact_type=SCHEDULE`).
`hoops_gm.calendar.deadline_calendar.derive_deadline_calendar` fails closed with
`DeadlineCalendarLineageError` when either lineage is missing or the settings
snapshot's own league/season identity does not match the target league — never
falls back to `docs/league/2025-26-rules-baseline.md` or any other historical
value. It is idempotent by exact lineage (re-deriving unchanged lineage returns
the existing row) and opens the next `version` only when either input has
actually moved. `season_start_date`/`season_end_date` and each scoring period's
`start_at`/`end_at` are parsed with `_require_aware`, which rejects a naive
timestamp outright (`ValueError` on missing `tzinfo`) rather than assuming UTC
or local time — real enforcement this module adds, since
`ScoringPeriodBoundary.start_at`/`end_at` are plain, unvalidated strings at the
ingestion boundary. `is_playoff` is `None`, never `False`, for any scoring
period when the settings document's own `playoffs` field is unknown; an
All-Star-style combined week (a 14-day span in the test fixture, versus the
usual 7) passes through unchanged since nothing in this module assumes a
uniform cadence. `unsupported_rules` is a verbatim copy of `lineup_lock`,
`waivers`, `trade_deadline`, `keepers`, and `playoffs` as their own
`{value, evidence}` pairs from the settings document — this table adds no
second override seam of its own.

`activate_deadline_calendar` re-validates lineage currency at activation time,
separately from derivation-time validation: it fails closed with
`DeadlineCalendarStaleActivationError` if the settings snapshot or schedule
refresh a calendar version was built from is no longer each source's current
state, so a stale version can never be silently reinstated as "current."
Genuine A→B→A cycling is still fully supported (verified in
`test_a_to_b_to_a_activation_cycle`) by deriving again once the schedule
lineage has actually reverted to prior content, then reactivating. Fixed one
real bug this same test caught: SQLAlchemy batched the "clear the old current
row" and "set the new current row" updates into a single `executemany`, and
when the new row's primary key sorted before the old row's the batch briefly
gave two rows the same `current_for_league` marker mid-flush, tripping the
unique constraint even though the end state was valid — the clearing update is
now flushed on its own before the new one is set.

Deliberately did **not** touch `db/models/league.py`'s existing `ScoringPeriod`
table. Its `start_date`/`end_date` are plain `Date` columns and its
`is_playoff` defaults to `False` (not nullable) — populating it with
timezone-aware instants and an honest three-state playoff flag would be a
wider, riskier change to an already-shipped table outside this item's scope.
The new `scoring_periods` JSON field is not a second competing calendar: it is
a versioned pass-through of the settings document's own already-JSON
`scoring_periods`, exactly as `LeagueSettingsSnapshot.settings` already stores
it. This is a defensible but debatable call — `architect` or a reviewer may
reasonably push back and ask for `ScoringPeriod` to be populated from this same
join instead of leaving it a dead table.

A read-only `GET /api/v1/leagues/{league_id}/deadline-calendar/current` mirrors
`lineage.py`'s style: 404 when the league does not exist, 404 when no calendar
has been activated, 200 with the full contract (including `unsupported_rules`)
otherwise. It performs no derivation or activation itself — those stay internal
operations a producer calls inside its own transaction.

**Now true:** `league_deadline_calendars` exists, migrated, and portable —
`test_portability.py` passes, including the Postgres identifier-length check
(the auto-generated FK constraint name for `settings_snapshot_id` overflowed
63 characters and needed an explicit shorter name in both the model and the
migration). 28 new tests in `test_deadline_calendar.py` cover: table/constraint
registration (version uniqueness, current-marker uniqueness, the
`current_marker_matches_league` and `season_dates_ordered` CHECKs,
cascade-on-league-delete, cascade-on-settings-snapshot-delete); every fail-closed
derivation path (missing settings, missing schedule, season/league identity
mismatch, naive scoring-period timestamp); idempotent re-derivation and
version-opening on new lineage; DST-crossing and combined-week boundary
pass-through; playoff-flag-as-`None`-when-unknown and
populated-when-known; bridge-supplied `trade_deadline` flowing through
unaltered; the full A→B→A activation cycle with fail-closed reactivation in
between; activation failing closed when settings lineage has moved on; and the
HTTP contract (404s, 200 shape, OpenAPI advertisement). Full local Code gate
green: ruff check, ruff format, mypy strict (96 source files including tests,
`strict = true` per `pyproject.toml`), and the full default backend suite (553
passed).

**Could not verify:** Whether the suite actually ran against Postgres in this
session — `TEST_DATABASE_URL` was not set in this environment, so
`test_portability.py`'s static-analysis checks (constraint names, enum CHECKs,
JSON-column dialect handling) ran, but no live Postgres connection exercised
`0011`'s upgrade/downgrade the way CI's Postgres job does; that remains the
cross-dialect check of record. Whether `architect` or an independent reviewer
agrees with leaving `ScoringPeriod` unpopulated rather than widening it to carry
this same join — argued above, not settled. Whether a bridge capture will ever
actually supply `lineup_lock`/`waivers`/`trade_deadline`/`keepers`/`playoffs`
for this league; nothing here changes that, it only guarantees the calendar
carries whichever of those become known without reconstructing the join logic.
Whether `notification-engine` or `lineup-optimizer`, both of which depend on
`deadline-model` in `docs/backlog.md`, can actually be built against
`unsupported_rules` staying largely unknown — that dependency's real
usefulness rests on the open bridge-capture gap, not on anything this PR
controls.

**Next:** PR open, not merged or self-approved, awaiting independent review per
governance (`backend` owns the persistence/API boundary this item lives in;
architecture-level pushback on the `ScoringPeriod` decision should route to
`architect`). Whoever picks up `notification-engine` or `lineup-optimizer`
should read `unsupported_rules` as evidence of absence, not silently treat a
`None` value as "no deadline this season."


## 2026-08-18 — backend — `deadline-model`: PR #20 review remediation, four fixes

**Changed:** An independent reviewer examined PR #20 at exact head
`e0f764ace934e405f4d4fffffa0c244446f3df96`, confirmed the architecture sound,
and returned four required fixes plus one ratified architecture decision.
All four are fixed on top of that head.

1. `_scoring_periods` returned `[]` when `document.scoring_periods.is_known`
   was `False`, which disappeared from `unsupported_rules` (scoring periods
   were never in that dict to begin with) and left the calendar looking like
   a confirmed zero-period season rather than an unasked question. It now
   raises `DeadlineCalendarLineageError` before any row is written. Added
   `test_deriving_fails_closed_when_official_scoring_periods_are_omitted`,
   which omits `scoringPeriods` from the official payload entirely (a normal,
   non-error absence at `_parse_scoring_periods`, confirmed via
   `document.scoring_periods.is_known is False` before deriving) and asserts
   both the raise and that `LeagueDeadlineCalendar` gained zero rows.
2. `TradeDeadlineRules.deadline_at` and `KeeperRules.deadline_at` were plain
   `str` fields with no format constraint, so a naive or garbage string could
   reach `unsupported_rules` unvalidated. Added a shared
   `_require_offset_aware_timestamp` helper and a `field_validator` on both
   fields directly in `hoops_gm.ingest.league_settings` (the reviewer's
   preferred location, since every consumer — official parsing, bridge
   parsing, `merge_settings`, hand-built documents in tests — gets the
   guarantee at construction time rather than each caller re-checking it).
   `KeeperRules.deadline_at=None` is still accepted; `None` means "never
   asked," not a value to validate. Checked the only two existing fixtures
   that construct these types (`test_league_settings.py`, one
   `"...-0500"`-suffixed string) before adding the validator — both are
   already offset-aware and unaffected. Added six new tests in
   `test_league_settings.py` covering naive rejection, unparseable rejection,
   and the `None` pass-through, for both rule types.
3. `GET /leagues/{id}/deadline-calendar/current` returned bridge-derived
   `unsupported_rules` values — including `source_path`/`capture_ref`
   provenance — to any caller, unlike `lineage.py`'s summary-only reads.
   Applied the existing `hoops_gm.api.security.require_loopback_host` guard
   (the same one `bridge.py`/`userscript.py` already use) at the top of the
   route, with no bridge-secret requirement — this stays an ordinary
   dashboard read, not a bridge write. Added
   `test_current_deadline_calendar_endpoint_rejects_a_non_loopback_caller`,
   which builds a fresh app with `environment="development"` (the same
   pattern `test_userscript_serving.py` already uses to bypass the
   `environment == "test"` escape hatch) and asserts a `403` with
   `error == "deadline_calendar_local_only"`; the two existing endpoint tests
   already prove loopback callers still work, since the default
   `app`/`client` fixtures run with `environment="test"`.
4. Added three more fail-closed checks ahead of any DB write, none of which
   existed before: `season_end_date < season_start_date` (previously only
   caught by the DB's own `CHECK` constraint, now raised as
   `DeadlineCalendarLineageError` first); duplicate scoring-period numbers
   (the official parser already rejects these, but a hand-built or
   bridge-merged document has no such guard, so this is real defense, not a
   duplicate of an existing check); and `end_at <= start_at` per period
   (nothing checked this anywhere before). Added one regression test per
   check, all constructing the document directly (via a new
   `_known_scoring_periods` test helper) rather than going through the
   official parser, since the parser's own duplicate-number check would
   otherwise mask the derivation-layer check being exercised.

**Architecture decision (ratified, not new):** `LeagueDeadlineCalendar`
remains the one authoritative source-of-truth calendar. `ScoringPeriod`
(`db/models/league.py`) stays out of scope for this PR and must never become
a second ingest target — future work must derive it as a non-authoritative
*projection* of the active `LeagueDeadlineCalendar` only, and must convert
each boundary to `America/New_York` before calling `.date()` so it agrees
with `TeamScheduleEntry.game_date`'s wall-clock day (UTC or the source's raw
offset would double-count or drop games across the DST transition and around
scoring-period midnight boundaries). Filed as a new backlog item,
`scoring-period-projection`, depending on `deadline-model` and
`schedule-density`, and referenced from the `deadline-model` entry itself.

**Now true:** All four fixes landed on `sr2501-deadline-model`; local Code
gate green again: `ruff check` and `ruff format --check` clean across the
repo, `mypy` strict clean (96 source files, `strict = true` per
`pyproject.toml`), full backend suite `564 passed, 17 deselected` (up from
553 — 11 new regression tests: 5 in `test_deadline_calendar.py`, 6 in
`test_league_settings.py`). `origin/main` then advanced past `875d40e` when
PR #19 (`schedule-context`) merged as `ffd838c`, taking Alembic revision slot
`0010` for `schedule_context_provenance` — this branch's calendar migration
is renumbered `0011` with `down_revision = "0010"`, rebased cleanly onto that
new main (only `docs/handoff.md`'s append-only conflict needed manual
resolution, both entries preserved), and the full local suite re-run green
again after the rebase.

**Could not verify:** Whether the suite ran against a live Postgres in this
session — `TEST_DATABASE_URL` is still unset here, so only
`test_portability.py`'s static-analysis checks ran locally (identical
situation to the original entry above); CI's Postgres job remains the
cross-dialect check of record for `0011` and for this round's changes, none
of which touch the schema beyond the renumbering itself. Whether the
independent reviewer will accept the domain-layer validation location for
fix #2 over the alternative (validating in `deadline_calendar.py` itself) —
chosen per their own stated preference, but not re-confirmed with them
before pushing. Whether GitHub's own merge-readiness check (CI green, no
conflicts, mergeable state) reflects this push yet at the moment this entry
was written — reported separately to the reviewing session once available.

**Next:** Push to `origin/sr2501-deadline-model` with `--force-with-lease`
(PR #20 updates in place, no new PR; the rebase rewrites this branch's
history), report the new exact head commit back to the reviewing session,
and wait for CI (including Postgres and the `0011` migration lifecycle)
before any merge — still not self-approved.


## 2026-08-18 — backend — `deadline-model`: docs-only authority-wording correction

**Changed:** The independent focused-release review flagged that
`db/models/deadline_calendar.py`'s module docstring still called
`league.ScoringPeriod` "the league-scoped calendar" and framed
`LeagueDeadlineCalendar` as not competing for that role — contradicting the
ratified architecture decision from the prior remediation round (this table
is authoritative; `ScoringPeriod` is the thing that must later become a
derived, non-authoritative projection). Rewrote that section to say plainly:
`LeagueDeadlineCalendar` is the authoritative source-truth calendar;
`ScoringPeriod` has no writer yet and must eventually become a derived,
non-authoritative `America/New_York`-date projection of this table's active
calendar for ADR-012's `scheduled_game_counts` consumers, converting each
boundary to that zone before `.date()` to align with
`TeamScheduleEntry.game_date` and avoid DST/UTC double-counting — never a
second ingest target. No behavior changed; diff is confined to the
docstring (`git diff --stat`: one file, docstring lines only).

**Now true:** `ruff format --check` / `ruff check` clean on the changed
file. Diff scope confirmed single-file, comment-only via `git diff --stat`.

**Could not verify:** Whether CI treats this as a fully independent run or
reuses a cached result for the unchanged code paths — reported once GitHub's
checks for this push are observed, same as prior rounds.

**Next:** Push, confirm exact head/CLEAN state and required-check status,
report back to the reviewing session. Still not merged, not self-approved.
---

## 2026-08-18 — data-engineer — Fantasy playoff schedule game-count facts

**Changed:** Extended the existing `scheduled_game_counts` query boundary into a
complete scoring-period x active-NBA-team grid and added
`playoff_scheduled_game_counts` as the typed playoff-only entry point. It reads
the league-scoped `ScoringPeriod.is_playoff` flag and counts `team_schedule`
rows inside the period's inclusive date boundaries. Every returned row carries
the current registered schedule version and timezone-aware refresh timestamp;
the query fails rather than return unversioned facts when no matching-season
schedule refresh exists. It does not create another week table or compute
opponent quality, schedule strength, projections, availability, or
recommendation policy.

**Now true:** Draft and trade consumers can request an ordered row for every
active NBA team in every flagged fantasy playoff scoring period, including
explicit zero-game teams and wholly empty periods. Period boundaries are
inclusive, schedule rows from other seasons and NBA season-type cohorts are
excluded, another league's period flags cannot leak into the result, and a
requested season must match the referenced league's season. A league with no
flagged playoff periods returns an empty list. Every non-empty result is stamped
from exactly one current schedule refresh cohort. The query holds that cohort's
keyed, season-scoped lineage lock while reading both the refresh stamp and
schedule rows, so a concurrent refresh cannot mix cohorts.

**Could not verify:** The 2026-27 Fantrax league's actual playoff scoring periods
have not been imported, so this verifies the query against explicit league
fixtures rather than claiming which real dates or period numbers are playoffs.
The six unresolved NBA Cup schedule games remain absent until the NBA assigns
their teams, as recorded by `schedule-ingest`; counts will reflect the current
schedule refresh until that source changes. After rebasing onto current `main`,
`league-settings-ingest` and `deadline-model` provide versioned source settings
and an authoritative calendar, but `ScoringPeriod` still has no writer or
lineage. The schedule refresh fingerprint versions `team_schedule`, so changing
`ScoringPeriod` boundaries or `is_playoff` still does not advance this result's
version. The pending `scoring-period-projection` unit must project the active
calendar and cascade its lineage to this grid before a consumer may claim the
schedule version alone captures future rules changes.

**Next:** `draft-recommender` and `trade-evaluator` should consume this raw count
contract directly. `quant` owns the later Model-gated value-weighted
`strength-of-schedule` pass from ADR-011 and must not fold it into this fact
query.

## 2026-08-18 — quant — `scoring-profiles`: explicit-null and precedence-vs-validation fixes (PR #22, round 5)

**Changed:** The immediately preceding "snapshot-authoritative lineage rework"
entry's own correction round (present-but-wrong-*type* values in
`parse_scoring_category_configs`/`_scoring_type_with_source_path` raising
instead of being read as absent) left one gap: `payload.get(key) is None`
cannot distinguish a key that is genuinely missing from a key present with an
explicit JSON `null` value -- both produce Python `None` from `.get()`. All
four affected checks (`scoringSystem`, `scoringSystem.scoringCategorySettings`,
top-level `scoringType`, nested `scoringSystem.type`) now use membership
(`"key" in payload`) to decide absence, and only then inspect the value's
shape -- so a present `null` now raises `SourceContractError` exactly like any
other malformed shape, rather than silently degrading to an official 'absent'
observation. Separately, `_scoring_type_with_source_path` validated the
top-level `scoringType` and, only if that failed or was absent, the nested
`scoringSystem.type` -- so a valid top-level value returned immediately
without ever inspecting a simultaneously present but malformed nested value.
It now validates both present candidates unconditionally first (raising on
whichever is malformed) and applies top-level-wins precedence only to select
between two already-valid candidates.

**Now true:** `null` is evidence of a real, if invalid, upstream value and is
treated identically to any other malformed shape across all four fields.
Top-level/nested precedence for the scoring-format discriminator can only
choose which valid value is authoritative; it can no longer be used to smuggle
an unvalidated, malformed alternate field past the parser because the
preferred field happened to already be fine. Six new regression tests exercise
this through the production `parse_official_league_settings` seam: explicit
`null` for each of the four fields, plus two "valid top-level scoringType with
a malformed-or-null nested scoringSystem.type" cases that assert the raise is
not bypassed by precedence.

**Could not verify:** No live Fantrax capture is known to actually return an
explicit JSON `null` for any of these four fields -- this closes a category of
possible-but-unobserved malformed evidence the same way the wrong-type case
already committed to, not a defect seen in a real payload. The scoring-type
precedence rule itself (top-level wins over nested) remains inferred from
adapter code, not an explicit statement from Fantrax documentation.

**Next:** None outstanding for this ingestion path; `quant` still owns the
later Model-gated valuation work that consumes `ScoringCategoriesRules`, which
is unaffected by this parser-only fix.

---

## 2026-08-18 — data-engineer — League-settings null evidence fidelity

**Changed:** Corrected the remaining official `getLeagueInfo` evidence-fidelity
paths in `ingest/league_settings.py`. `rosterInfo`, `scoringPeriods`, roster
subfields, scoring-period aliases, and playoff-marker aliases now distinguish a
genuinely missing key from a present JSON `null`: only the former can produce
absent evidence, while `null` and every wrong-shaped present value raise
`SourceContractError`. When both supported aliases are present
(`number`/`period`, `startDate`/`start`, `endDate`/`end`, or
`isPlayoff`/`playoff`), both are validated before the preferred alias is chosen.
Focused production-seam regressions cover null and malformed outer/inner shapes,
missing-key absence, malformed-alternate bypass attempts, and valid precedence.
The directly related official-adapter documentation now states this contract.

**Now true:** A valid preferred roster/scoring-period/playoff value can no longer
hide malformed alternate evidence, and a present `null` can no longer be
persisted as though Fantrax supplied no evidence. The full backend Code gate,
the complete recorded-fixture Adapter contract suite, and the repository secret
scan pass locally; no schema or migration changed.

**Could not verify:** The recorded live fixture contains no explicit `null` in
these fields and uses the preferred scoring-period names, so the new null and
alias-combination cases are synthetic contract regressions through the
production parser rather than claims about a currently observed Fantrax payload.
No live API request was made because this change does not require refreshing the
recorded fixture and the Adapter gate keeps live smoke separate and non-blocking.

**Next:** Re-ingest deliberately if a future live capture introduces either
supported alias or a new playoff marker; contract drift must be investigated
rather than normalized into absent evidence.

---

## 2026-08-18 — architect — Tracked Markdown consistency audit

**Changed:** Audited all 45 tracked Markdown files against merged repository
history and the current tree. Applied only objectively determined corrections:
the authoritative backlog now groups and counts its 99 unique tasks by their
own checkbox status (27 done, 1 blocked, 71 pending); the resolved Actions
billing incident and Postgres migration-path risk are closed in current
governance documents without rewriting historical handoff entries; stale Python,
identity-crosswalk, league-settings, model-card-index, ADR phase, and bridge
capture claims now match executable or merged evidence. No ADR status, product
behaviour, ownership assignment, or model-gate semantics changed.

**Now true:** Current documentation no longer says CI is unavailable, directs
readers to Python 3.11, treats Fantrax IDs as an NBA identity anchor, calls the
verified `getLeagueInfo` timing-field omissions unknown, omits the existing
schedule-context model card from its index, or places `schedule-ui` in Phase 6.
Every relative Markdown link resolves, every backlog dependency names an
existing task, and the backlog has 99 unique ids with status sections matching
their task markers.

**Could not verify:** Product-facing status wording in `README.md`; ownership
for the real `calendar/` and `scoring/` packages; whether ADR-010 was accepted;
whether the plain-English ADR walkthrough is maintained or frozen; whether the
model-card template is binding; canonical Model-gate split wording; the intended
referent of ADR-008's nonexistent "tenant isolation analogue"; and whether
three incomplete historical handoff entries warrant an appended correction.
Those questions have multiple reasonable answers and were deliberately left
unchanged for owner review. Localhost URLs were not expected to resolve without
running services, and no live Fantrax request was made.

**Next:** The owner should review the separately reported decision list.
Any follow-up should make one named decision at a time rather than folding
product or governance choices into mechanical documentation cleanup.

---

## 2026-08-17 — architect — Recursive SOS and schedule refresh contract

**Changed:** Reworked ADR-011 and ADR-012 together after owner review. SOS and
every projection set in the corpus are now explicitly a versioned recursive
loop: projection changes can change SOS, SOS can require projection changes,
and the dependency-aware cascade repeats until stable or an explicit limit is
reached. Per-week game distribution is now a living schedule dependency,
re-ingested at least weekly during development season and cascaded into
projections, SOS, valuation, draft, auction, trades, lineups, streaming, and
weekly planning. The ADR index summaries were updated to match.

**Now true:** These outputs must carry refresh/version provenance and may not
combine fresh upstream data with stale downstream results. The schedule grid
remains raw count data, while any resulting decision number inherits the
relevant Model gate.

**Could not verify:** No implementation currently executes the recursive
cascade or weekly scheduler; these ADR changes define the contract for the
quant, data-engineer, backend, and feature implementations.

**Next:** `architect` should sequence the cascade contract with the projection
and schedule work; `quant` and `data-engineer` must choose the convergence,
freshness, and backtest details when implementing the model and adapters.

---

## 2026-08-17 — owner — ADR-011 and ADR-012 recursive refresh amendments accepted

**Changed:** The project owner accepted the revised ADR-011 recursive
SOS/projection contract and ADR-012 living per-week schedule dependency
contract.

**Now true:** Work that was waiting on these decisions may resume. The
schedule-context work was explicitly authorized to continue under the weekly
refresh, versioning, and cascade requirements.

**Could not verify:** The downstream implementation has not yet demonstrated
recursive convergence or a weekly refresh run; those remain implementation and
Model-gate work.

**Next:** `quant`, `data-engineer`, and downstream feature owners should
implement and test the cascade without mixing stale versions.

---

## 2026-08-18 — backend, architect, bridge — Preservation snapshot reconciliation

**Changed:** Compared every hunk in local preservation commit `5b2a3f0` against
current remote main `b570c32` instead of replaying the commit. All 24 files were
classified as already merged, byte-identical, superseded by newer reviewed
behavior, genuinely unique, or an owner/product decision. Restored the
owner-accepted recursive weekly refresh amendments to ADR-011 and ADR-012,
their decision-index summaries, and their acceptance narrative. Also ported the
one genuinely unique technical hardening requirement into the current shared
userscript-serving route: a genuinely missing build retains the shipped
`userscript_build_missing` 404 contract, while a present path that cannot be
read now returns a distinct `userscript_build_unreadable` 500 rather than
incorrectly advising the operator to rebuild. Added a regression test using a
directory at the configured file path, which portably exercises a
non-`FileNotFoundError` `OSError` without platform-specific permission
manipulation.

**Now true:** The reconciliation does not regress current route mounting, the
shared loopback guard, `Cache-Control: no-store`, bridge/userscript 0.5.0
behavior, live-verification documentation, migrations, or append-only handoff
history. ADR-011 and ADR-012 now retain both their newer current-main text and
the accepted recursive refresh contract as additive amendments.

**Could not verify:** A native permission-denied file read on POSIX; the
cross-platform regression instead proves the same generic
non-`FileNotFoundError` `OSError` branch, while the concrete exception subtype
is platform-dependent. GitHub Actions and native Postgres were not run locally;
no schema, migration, adapter, fixture, or external-source code changed. The
preservation commit's proposed restricted-input Adapter-gate amendment,
projection experiment protocol, and their associated handoff proposal remain
unaccepted owner/product decisions and were reported rather than ported. The
recursive cascade and weekly refresh scheduler required by accepted ADR-011 and
ADR-012 have not yet been demonstrated end to end.

**Next:** An independent reviewer should inspect this exact branch head before
the focused PR proceeds. The owner may separately decide whether to pursue a
smaller projection-experiment protocol or amend ADR-006 for restricted
personal-use inputs; neither proposal is in force.

---

## 2026-08-19 — architect — Mechanical documentation closure

**Changed:** Corrected only repository-verifiable documentation drift: replaced stale `backend/app` and `backend/migrations` paths with the real `backend/src/hoops_gm` and `backend/alembic` tree; split calendar, scoring, settings-intake, persistence, and API ownership at their actual boundaries; made the existing model-card content the normative minimum and aligned the schedule-context card without changing its claims; preserved the existing universal Model gate at held-out data, calibration, model cards, blind spots, and traceability to model version/inputs; replaced mutable false-guarantee tallies in living docs with qualitative wording; added the canonical `ScheduleLeagueV2` contract page and links; removed ADR-008's dangling tenant-isolation analogue; and moved the already-merged `bridge-handshake-endpoint`, `bridge-capture`, and `deadline-model` backlog items to Done. The backlog now recomputes to 30 done, 1 blocked, 68 pending, 99 total. `csv-importer` remains pending and `blind-mocks` remains the sole blocked item.

**Now true:** Every edited path resolves to the current tree; the ownership matrix distinguishes decision semantics from backend mechanics instead of assigning one misleading owner; the Model-gate summaries retain the same held-out-data and calibration requirement without promoting ADR-011/012-specific lineage into a universal contract; the schedule adapter index points to one canonical contract preserving the existing 1,200 resolved plus six TBD facts and timezone semantics; all relative Markdown links and anchors resolve; and the backlog status summary matches its 99 task sections and dependency references.

**Could not verify:** No new live source was called, so this unit adds no evidence beyond the existing recorded `ScheduleLeagueV2` fixture and 2026-08-17 verification. It does not decide the README public-progress sentence, projection experiment protocol, ADR-006 restricted-input amendment, or historical handoff shape; all were deliberately left unchanged. It also does not claim that any pending injury-model work is ready.

**Next:** Merge only after an independent exact-head review confirms the diff is mechanical and boundary-neutral and existing docs, link/anchor, dependency/count, and secret checks are green. Do not merge or self-approve from this session.

---

## 2026-08-19 — owner via architect liaison — ADR-010 and plain-English disposition

**Changed:** Recorded two explicit owner selections from the 2026-08-19 architect liaison decision dialog: accept ADR-010, and freeze `docs/decisions/PLAIN-ENGLISH.md` as the historical ADR-001–009 walkthrough. ADR-010 already carried `Accepted` metadata, so its decision text and dates were preserved and the decision-index acceptance narrative now records the owner's explicit confirmation. The plain-English document now carries a freeze banner and points readers to the individual ADRs and decision index for the current record; it was not extended to ADR-010 or later decisions.

**Now true:** ADR-010's accepted state has durable owner confirmation in the repository, and nobody should treat `PLAIN-ENGLISH.md` as a current or expanding ADR index.

**Could not verify:** The dialog supplied the selections but no owner rationale beyond them, so none is inferred. No other owner-only choice was made or changed.

**Next:** Keep ADR-010's existing accepted metadata intact, leave the frozen walkthrough at ADR-001–009, and use the decision index for later ADRs.
## 2026-08-18 — data-engineer — Historical injury-report backfill: third round, one more genuine defect found and fixed (403-checkpoint-before-abort)

**Changed:** Pushed the second remediation round (commit `a0989a7`) to
`origin/sr2501-historical-injury-backfill` (PR #21, head now on top of
`0ff417a`/main, migration `0012`/`down_revision="0011"`). GitHub CI then
surfaced a real gap this session's own local validation had missed, and a
subsequent independent `code-review` sub-agent pass against that exact
pushed head found one more genuine, reproducible defect in the streak-abort
handling. Both are now fixed, at commit `7809acf`.

**1. CI mypy failure (process gap, not a design defect).** CI's backend job
runs bare `mypy` (project-wide, tests included); this session had only been
running `mypy src` locally, so 4 errors in
`tests/test_injury_report_backfill.py` were invisible until CI caught them:
two now-unused `# type: ignore[method-assign]` comments on
`session.commit = ...` reassignments, and two dict-invariance errors from
`_ScriptedFetcher`'s `dict[datetime, InjuryReportParseResult | Exception]`
parameter being passed a narrower `dict[datetime, ReportNotAvailable]`
literal. Fixed by removing the unused ignores and explicitly annotating the
two dict comprehensions with the wider value type. No behavior change; all
67 injury-report tests still passed. **Local validation going forward
should run bare `mypy`, not `mypy src`, to match CI exactly** — recorded
here so this gap does not recur silently.

**2. Independent re-review of the pushed head (all 10 second-round points)
found one still-incomplete fix: point 8, 403 vs 404.** The abort-on-streak
mechanism itself worked (`SuspectedSourceBlock` correctly raised on the
Nth consecutive HTTP 403), but `run_backfill` was still calling
`checkpoint.record(candidate, "not_available")` **unconditionally** for
every `ReportNotAvailable`, 403 or 404 alike, *before* checking whether the
403 crossed the abort threshold. That meant the very candidates whose 403
streak triggered the abort were durably checkpointed as settled "confirmed
absence" moments before the exception fired — so a resumed run (after
whatever blocked us, e.g. a WAF or rate-limit condition, cleared) would
silently skip exactly the candidates the abort exists to protect, treating
a suspected block as permanent "no report" forever. This directly
contradicted both the exception's own message ("rather than recording these
as confirmed absence") and the adapter doc's description of the same
behavior — reproduced and confirmed independently before being accepted as
real, not assumed from the review's write-up.

**Fix:** `run_backfill` now buffers a 403's checkpoint write rather than
recording it immediately. A buffered 403 is only flushed to the checkpoint
as settled once its streak is confirmed *not* to be an abort: either a
later non-403 result (a 404, a genuine fetch, or a different `SourceError`)
breaks the streak, or the run ends normally without ever crossing
`max_forbidden_streak`. If the streak *does* cross the threshold,
`SuspectedSourceBlock` is raised **before** any of that streak's buffered
403s are flushed, so every one of them is left unsettled and will be
retried on the next run. A 404 (or any non-403 absence) is still
checkpointed as settled immediately, unchanged — this is scoped to the
one code path that was actually wrong.

Three new regression tests were added (`test_injury_report_backfill.py`):
`test_run_backfill_does_not_settle_a_403_streak_that_triggered_the_abort`
(reloads the checkpoint from disk after the abort and asserts none of the
streak's candidates are settled — this is exactly the bug the fix
addresses, and the test fails against the pre-fix code), 
`test_run_backfill_retries_403s_from_an_aborted_streak_on_resume` (a second
run against the same checkpoint, now returning 404s, proves every candidate
from the aborted streak is genuinely re-fetched, not skipped), and
`test_run_backfill_settles_a_short_403_run_that_never_crosses_the_abort_threshold`
(a 2-candidate 403 run, below the default streak threshold of 3, still
ends up settled once the run completes normally — proving the fix doesn't
regress the documented "a lone or short 403 run is the same trustworthy
signal as a 404" behavior). `run_backfill`'s docstring, the module-level
natural-key mention (which had gone stale, still describing the pre-fix
3-column key), and `docs/adapters/nba-injury-report.md`'s 403/404 section
were all corrected to match.

**Verified:** `ruff check`/`ruff format --check` clean; bare `mypy`
(matching CI) clean, 107 source files; full local `pytest -q` green
(70/70 in the two injury-report test files, exit code 0 across the whole
suite — this environment's pytest does not print a final summary line for
reasons not yet understood, but no `F`/`E` markers appeared and exit code
was consistently `0`); the editable `hoops_gm` install had gone stale again
mid-session (a recurrence of the issue noted in the prior entry) and was
re-run (`pip install -e .` from `backend/`) before trusting collection.
Pushed as `7809acf`. Re-ran `gh pr checks 21`: all jobs pass, including
"Backend — lint, type-check, tests" (previously failing) and "Backend —
the same suite against Postgres (ADR-001)". `gh pr view 21` reports
`mergeStateStatus=CLEAN`, `mergeable=MERGEABLE`, base `0ff417a`
(`origin/main` re-fetched and confirmed unchanged at `0ff417a` — no further
migration-slot race yet from PR #22).

**Could not verify:** whether a fourth independent review pass exists
somewhere finding issues beyond point 8 and the mypy gap — only one
`code-review` sub-agent pass was run this round, and it explicitly listed
point 8 as the *one* remaining blocker rather than a partial list; a
different reviewer could in principle find something this pass missed.
Also could not verify PR #22's current state or whether `main` will
advance again before this PR is merge-ready — that must be re-checked at
merge time, not assumed from this entry.

**Next:** Report this exact head/status back to the reviewing session
(cross-session request originated from a merge-queue session tracking
this PR). Still not merged, not self-approved, and `injury-status-conversion`
remains explicitly not unblocked until an independent reviewer signs off on
this exact commit.

## 2026-08-18 — data-engineer — Historical injury-report backfill: fourth round, eight more integrity gaps closed, first genuine live-cascade evidence

**Changed:** A fourth independent exact-head review of `fb7d095` found 8
further correctness gaps, all now fixed, tested, and validated against a
real live sample (this entry's commit is the first one in this PR to be
built without adding a new gap the next review finds, as far as this round
can tell — but see **Could not verify** below, that is not this session's
call to make).

**1. Checkpoint identity was mutable.** Keying was `(date, candidate_kind)`
only; a corrected or newly-resolved earliest tip-off changes the actual
candidate timestamp/URL under an already-settled key, and the old design
would treat the new timestamp as already done. Fixed: `Checkpoint` now
stores the exact resolved timestamp and the key check compares it — a
stored-timestamp mismatch is treated as **unsettled**, not skipped. Added
tip-change and partial-schedule-expansion resume regressions.

**2. Coverage was lost on abort.** `SuspectedSourceBlock` used to carry only
enough to re-raise; a run that hit the 403 abort mid-way lost every
candidate's coverage evidence gathered before the abort. Fixed: both
`SuspectedSourceBlock` and the new `IncompleteExpectedGameCoverage` now
carry their own `coverage`/partial-result object (mirrored design), and
coverage is written in a `finally`-equivalent durable path so a
success-then-403-then-resume sequence has no coverage holes. Tested
end-to-end.

**3. The full-scope gate only compared DB rows to themselves.** It could
not have caught a narrow-but-internally-consistent 22/527 scope, because
"expected" was derived from the same ingested rows being checked. Fixed:
added `enforce_expected_game_coverage`, which fetches the real official
`LeagueGameFinder` slate for the requested season/type/date window
(cached/throttled through the existing `NbaStatsClient`) and fails closed
*before any injury-report HTTP call* if the ingested game set doesn't
match it, persisting expected-vs-ingested game IDs and reasons
(`IncompleteExpectedGameCoverage`, overridable via an explicit
`--allow-missing-games` count).

**4. Near-tip candidates in the 15-minute era weren't grid-aligned.** A
non-:00/:15/:30/:45 real tip-off (e.g. 19:10) would generate a candidate
that isn't on the source's actual publication grid. Fixed:
`_floor_to_quarter_hour_et` floors every near-tip candidate wall time to
the prior quarter-hour, strictly pre-tip. **Honest finding:** every real
tip-off in this session's sampled archive (`BoxScoreSummaryV3` across three
seasons via `lastFiveMeetings`) falls on `:00`/`:30` ET — no genuinely
off-grid real tip-off was found to validate this against live data. The
fix is unit-tested against a synthetic/monkeypatched off-grid tip-off only;
it remains **unproven against a real off-grid tip-off** because none has
been observed. This is stated here rather than implied to be fully live-
validated.

**5. 403 handling still wasn't fail-closed across invocation boundaries.**
Round 3's buffered-streak design correctly avoided settling a 403 as
confirmed absence *within* one run, but nothing stopped a later run or a
different error from resetting/flushing a still-unresolved 403 to
settled. Fixed, simplified to the honest v1 the review asked for: a
planned-game 403 is **never** settled as `not_available`; it is persisted
as `forbidden`/unsettled coverage and `run_backfill` returns nonzero so an
operator investigates, regardless of run boundaries or intervening
errors. Added a per-date repeated-403 regression proving this survives a
process restart.

**6. The exclusion cascade didn't expose the actual denominator.** A
single "game observed" bit told a reviewer nothing about where player-games
were lost. Fixed: `ExclusionCascade`/`exclusion_cascade`/
`render_exclusion_cascade` now persist and render every stage: expected
games → missing from ingest → ingested → ingested-with-tipoff → candidates
attempted → forbidden (403) → not_available (404) → mastheads recovered →
entries in scope → entries resolved to game_id → entries resolved to
player_id → NOT_YET_SUBMITTED → listed status → games with a canonical
observation. The `observations` CLI subcommand renders this, not just
game-level success.

**7. Pre-fix rows were untrustworthy and undistinguishable from fixed
rows.** Migration `0013` adds `import_schema_version` (current = `2`) to
`injury_report_entries`, defaulted via both the model column
(`server_default`, required for `test_models_and_migrations_agree`) and
the migration itself. Canonical-observation selection can exclude legacy
(`version < 2`) rows unless explicitly overridden; documented that any
locally-imported pre-`0012` data needs re-capture or an explicit override,
not blind trust.

**8. Coverage merge keys didn't include the requested timestamp/URL.**
Fixed alongside point 1 — the same resolved-timestamp field that fixed
checkpoint identity is also part of the coverage merge key, with a
round-trip test for changed candidates.

**Live evidence (real data, not synthetic):** Reused real archived
fixtures cached in an earlier round (`BoxScoreSummaryV3` for 2025-11-01,
2025-12-01, 2026-01-15; a real `LeagueGameFinder` capture for season
2025-26 regular season) to seed a **freshly alembic-migrated** scratch
SQLite DB (`backend/.live_evidence_r4/`, gitignored, not committed) with
22 real games/30 real teams across both URL eras, then ran the actual
`backfill plan`/`run`/`observations` CLI against it:

- `plan` correctly showed legacy fixed-offset candidates
  (`evening_before`+`game_day@13:00`) for the two pre-2025-12-22 dates and
  4 grid-aligned `near_tip_*` candidates for the post-boundary date.
- `run` across the full 2025-11-01→2026-01-15 range correctly **failed
  closed** against the real `LeagueGameFinder` slate: 527 expected games,
  505 missing from this deliberately tiny 22-game seed — a genuine,
  reproducible demonstration of the exact "22/527" failure mode the
  reviewers described, using real official-schedule data, not a
  contrived one.
- `run` for 2025-12-01 alone and for 2026-01-15 alone each passed the
  gate and produced a real fetch/import (9 candidates total across all
  three dates, all cache hits against real archived PDFs; 267 and 726
  entries created respectively). A follow-up run of the full range with
  an explicit `--allow-missing-games 505` override correctly resumed
  with 0 new fetches/imports (all 9 candidates already checkpointed
  settled) — real idempotency evidence, not asserted.
- `observations` for the full range: 22 games in scope, 21 with a
  canonical observation, 1 `not_yet_submitted_only`; exclusion cascade:
  527 expected → 505 missing-from-ingest → 22 ingested (all with a
  tip-off) → 9 candidates attempted (0 forbidden, 0 not_available) → 9
  mastheads recovered → 638 entries in scope → 638 resolved to game_id →
  **0 resolved to player_id** (this scratch DB seeded games/teams only,
  no `Player` rows — an honest limitation of this specific sample, not a
  tool defect) → 25 NOT_YET_SUBMITTED → 613 listed status → 21 canonical
  observations.
- DB query confirmed all 1150 imported rows carry
  `import_schema_version = 2` (current); 9 distinct report timestamps
  (mastheads) spanning 2025-10-31 through 2026-01-16 (report dates
  differ from game dates by design — `evening_before` anchors land the
  night prior); 596 distinct player-games by the corrected
  `(game_date, team_raw, player_name_raw)` natural-key shape.
- **Incidental, real, out-of-scope finding:** two of the sampled real
  games (`0022500147` DAL@DET 2025-11-01, `0022500578` MEM@ORL
  2026-01-15) have a genuine anomaly in the archived `LeagueGameFinder`
  payload — **both** team rows for each game carry an away-style `"@"`
  `MATCHUP` string instead of one `"vs."`/one `"@"` — so the
  already-merged `parse_league_game_finder` (PR #13/#19 territory, not
  this PR) correctly and defensively drops both games as one-sided/
  ambiguous rather than guessing a home team. This is why the "5 of 6"
  and "8 of 9" expected counts for those two dates matched the ingested
  counts exactly: the schedule parser's own existing defensive skip
  already excludes these two games from "expected," independent of
  anything in this backfill. Recorded here for honesty; not something
  this PR should or does fix.
- `stats.nba.com` (needed for a *fresh* `LeagueGameFinder` fetch) timed
  out from this sandbox during this round, same as prior rounds — all
  live-evidence fetches for this round reused cache hits within their
  documented freshness windows, not new network calls. Genuinely fresh
  network reachability against `stats.nba.com` remains unverified from
  this environment.

**Gates:** `ruff check`/`ruff format --check`/bare `mypy` clean;
`pytest -q` green (injury-report test count now 90+, all new round-4
tests included); `pytest -m adapter_contract -q` green;
`scripts/check_no_secrets.py` clean; standalone `alembic upgrade head` →
`alembic check` ("No new upgrade operations detected") → `alembic
downgrade base` clean round-trip (0001→0013→base) against fresh SQLite.
Postgres gate not runnable locally (no Docker in this sandbox, same as
every prior round) — deferred to CI.

**Now true:** All 8 round-4 review points are fixed with regression
tests. The natural-key fix (`0012`) and evidence-versioning fix (`0013`)
both remain on this PR's branch; `origin/main` is unchanged at `0ff417a`
this round, so no rebase or migration renumbering was needed. PR #22 was
still open/unmerged as of this check, so `0012`/`0013` remain
uncontested for now but must be re-verified at push/merge time.

**Could not verify:** A fifth independent review pass has not yet
happened as of this entry — this round's fixes are validated by this
session's own tests, gates, and one live sample, not yet by a fresh
reviewer looking at the actual pushed commit. Whether `injury-status-
conversion`'s non-blocking-but-mandatory follow-ups (a random/unselected-
date recovery study, the full participation join, holdout-by-date,
calibration by status × lead-time × cadence era) have any path forward
also remains unassessed — those are explicitly out of scope for this PR
and belong to `quant`. Genuinely fresh (non-cached) network reachability
against both `ak-static.cms.nba.com` and `stats.nba.com` from this exact
sandbox was not re-verified this round beyond the one reachability probe
already reported.

**Next:** Push this round's commit, request a fresh independent
`code-review` pass against the exact new head, and report status back
honestly — including the "22/527 real evidence," the "no real off-grid
tip-off found" limitation, and the incidental `LeagueGameFinder`
matchup-anomaly finding — without merging or self-approving.
`injury-status-conversion` remains explicitly blocked.

## 2026-08-19 — data-engineer — Historical injury-report backfill: fifth round, the measurement itself was found untrustworthy, not just the source's coverage gap

**Changed:** Two independent exact-head reviews of `962bff4` found 8 further
integrity gaps — this time not in what the tool fetches, but in what its own
denominator/coverage machinery *reports about* what it fetched. All 8 are
now fixed and regression-tested.

**1. The unresolved-game-id cascade stage was tautological.**
`exclusion_cascade`'s underlying query filtered `game_id.in_(...)` before
counting how many entries resolved to a `game_id`, so the stage could never
show loss — 100% "resolved" was true by construction, not by evidence.
Fixed: raw entries are now scoped by `game_date.in_(...)` (always populated)
first, resolution is counted as a separate stage, and a bounded sample of
unresolved `(game_date, matchup, team, player_name_raw)` rows is persisted
and rendered. Added an exact regression proving the old query would have
hidden the loss this one catches.

**2. `no_candidate_coverage` conflated two different absences.** "No
candidate was ever attempted for this game" and "a candidate was fetched and
the team genuinely submitted zero injured players" were the same outcome —
which erases the difference between "we don't know" and "we know, and it's
empty," a distinction a downstream model needs. Fixed: `coverage_for_games`
now distinguishes four outcomes — `no_candidate_coverage`,
`not_yet_submitted_only`, `submitted_zero_listed`, `legacy_excluded` — and
`observations` renders all four separately.

**3. Legacy (pre-`0012`/`0013`) rows were inconsistently excluded across
cascade stages.** Some stages honored `import_schema_version`, others
didn't, so a legacy row could silently inflate a "trusted" count at one
stage while being correctly excluded at another. Fixed: `exclusion_cascade`
splits entries into `trusted`/`legacy` **before** computing any of stages
11–18, and every one of them is computed from `trusted` only. A legacy
`NOT_YET_SUBMITTED` row is reported as `legacy_excluded`, never as
`not_yet_submitted_only` — it is equally subject to the natural-key
collision the schema fix corrected, regardless of its status text.

**4. `ExpectedGameCoverage`/`CoverageReport` were not bound to the exact
requested scope.** Persisted evidence for one season/date-range could
silently answer a request for a different one. Fixed:
`_expected_coverage_matches_scope` requires an exact match (season,
season_type, start, end) between persisted evidence and the current
invocation; `observations` discards and warns on a mismatch rather than
presenting stale evidence as if it answered the live request.

**5. `lead_minutes` was the anchor's intended offset, not a realized
per-game lead time.** The same anchor offset (e.g. "90 minutes before the
date's earliest tip-off") was shared across every game on a date regardless
of that specific game's actual tip-off — wrong for a late game on a
multi-tip date, and mislabelled as if it were a real per-game measurement.
Fixed: renamed to `anchor_offset_minutes` on `ReportCandidate`/
`CandidateCoverage` (what it always was), and added a genuinely new,
per-game `CanonicalPregameObservation.lead_time_minutes` computed as
`tipoff_utc - report_timestamp` for that specific game, exposed in
`observations` and the exclusion cascade for downstream stratification by
realized lead time.

**6. The expected-slate gate didn't fail closed on an empty response, and
season-type mapping was wrong.** An empty in-range `LeagueGameFinder`
payload previously passed the gate vacuously (0 expected, 0 missing — a
false "complete"). The CLI also silently mapped `PRESEASON`/`PLAY_IN` onto
`PLAYOFFS`, which would have compared the wrong slate entirely. Fixed:
`enforce_expected_game_coverage` raises on an empty in-range response, and
`_expected_schedule_season_type_label` restricts v1 to `REGULAR`/`PLAYOFFS`,
raising `ValueError` (caught in `main()` before any HTTP call) for
`PRESEASON`/`PLAY_IN`.

**7. The canonical player-game surface didn't collapse by resolved player
identity.** Spelling variants of the same player's name across different
mastheads could double-count as distinct canonical observations. Fixed:
`_canonical_observation_key`/`select_canonical_pregame_observations` now key
on `entry.player_id` when resolved, falling back to the raw name only when
unresolved — an unresolved row is kept distinct from any resolved row (an
`int` id never coerces to compare equal to a `str` name), so identity
collapse never silently merges an unresolved row into a resolved one.

**8. CLI help text referenced a nonexistent `--expected-coverage` flag, and
gate ordering/coverage-persistence had no end-to-end test.** Fixed the help
text; added 5 new `main()`-level CLI tests (monkeypatching
`get_settings`/`Database`/`default_expected_game_fetcher`/
`default_fetch_and_parse` at the module level, no real network) proving:
scope-mismatched persisted evidence is discarded with a warning,
season-type validation fails closed before any HTTP call, expected-game
coverage is persisted even when the gate itself fails, a full happy-path run
persists a `CoverageReport`, and a 403-abort still persists partial
coverage.

**Live evidence for fix #3 (legacy consistency), reusing real archived
data:** Reused round 4's `live_evidence.db` (645 real `injury_report_entries`
rows across 22 real games, 3 real dates spanning both URL eras) and manually
applied migration `0013`'s exact effect (added `import_schema_version`,
stamped every existing row `1`/legacy — this DB predates `0013`, so every
row is genuinely, not synthetically, legacy). Ran `observations` against it
with the round-5 code: **all 22 games and all 564 in-range rows report
`legacy_excluded` at every cascade stage** (9 through 18 all read 0 for the
trusted-only counts, not a false "resolved" or "listed" number derived from
legacy rows) — proving the legacy-consistency fix holds against real
previously-imported data, not just a synthetic fixture. `--allow-missing-games`
evidence (stages 1–2, "unknown — not yet computed") and coverage evidence
(stages 5–8) correctly report as **unverified, not zero**, because this
session did not re-run `backfill run` against this scratch DB (no network in
this sandbox) — an honest gap in this specific validation run, not a defect;
those two stage groups are otherwise covered by the round-4 live sample and
this round's unit/CLI tests.

**Gates (this branch, pre-rebase):** `ruff check`/`ruff format --check`/bare
`mypy` all clean on the touched files and whole-project `mypy` (107 source
files). `pytest -q` (whole backend suite) green, no failures, no unraisable-
exception warnings (see **Could not verify**-adjacent note below — one was
found and fixed this round, not merely observed). `pytest -m
adapter_contract -q` green. `scripts/check_no_secrets.py` clean (230 tracked
files). No `db/models/`or `alembic/versions/` changes this round — all 8
fixes are query-scoping, derived-field, and CLI-validation changes against
the existing `0012`/`0013` schema.

**A genuine test-environment bug found and fixed, unrelated to backfill
logic:** the new CLI tests initially left a `sqlite3.Connection` unclosed —
`main()`'s own `Database.from_settings(settings)` call constructs a *second*
SQLAlchemy engine against the same SQLite file the test's `database` fixture
already owns, and nothing disposes that second engine's connection pool
before test teardown, which this project's `filterwarnings = ["error"]`
pytest config correctly escalates to a hard error (reported against
whichever *later* test happens to trigger garbage collection, per pytest's
own unraisable-exception collection timing — not necessarily the test that
leaked). Fixed by monkeypatching `backfill_module.Database` to a
`SimpleNamespace(from_settings=lambda settings: database)` in each CLI test,
so `main()` reuses the fixture's already-owned `Database` instance instead
of constructing an undisposed second one. This is a test-harness fix, not a
production-code change — `main()`'s own single real invocation per process
was never the problem.

**Now true:** All 8 round-5 review points are fixed with regression tests
(test count in this file grew from 72 to 90+ across rounds 4→5 additions
this session). No migration or model change this round.

**Could not verify:** A sixth independent review pass has not yet happened
as of this entry — validated by this session's own tests, gates, and one
targeted live-evidence check (fix #3 only), not yet by a fresh reviewer
against the actual pushed/rebased commit. This entry is being written
*before* the required rebase onto `origin/main` (which has since advanced
past this branch's `0ff417a` base through PR #14 and PR #22, with PR #22
taking migration `0012` — this branch's provisional `0012`/`0013` must be
renumbered to `0013`/`0014` before push). Genuinely fresh network
reachability against `stats.nba.com`/`ak-static.cms.nba.com` was not
attempted this round (no new HTTP calls at all this round — only a manual
schema patch against a pre-existing cached DB and re-runs of the CLI's
network-free `observations` command). Whether `injury-status-conversion`'s
non-blocking-but-mandatory follow-ups have any path forward remains
unassessed and out of scope for this PR.

**Next:** Rebase onto `origin/main` at `036e4ca` (PR #22 merged, owns
migration `0012`), renumber this branch's provisional migrations to
`0013`/`0014` (down_revision chain `0012` → `0013` → `0014`), rerun the full
gate suite including Postgres CI and the migration lifecycle
(upgrade/check/downgrade round-trip), push, and request a fresh sixth
independent review — without merging or self-approving.
`injury-status-conversion` remains explicitly blocked.

## 2026-08-19 — data-engineer — Historical injury-report backfill: rebased onto PR #22 (main); migrations renumbered 0012/0013 → 0013/0014

**Changed:** `origin/main` advanced to `036e4ca` (PR #22, "Add configurable
scoring profiles," merged) and claimed migration `0012` for
`0012_scoring_profile_lineage.py`, colliding with this branch's provisional
`0012_injury_report_natural_key_game_date.py`/
`0013_injury_report_evidence_schema_version.py`. Rebased this branch onto
`036e4ca` (one conflict, in `docs/handoff.md` only — resolved by
concatenating both sides' entries in append-only order, since the conflict
was purely "both branches appended new entries at the same location," not a
substantive disagreement) and renumbered:
`0012_injury_report_natural_key_game_date.py` → `0013_...`
(`down_revision` now `0012`), `0013_injury_report_evidence_schema_version.py`
→ `0014_...` (`down_revision` now `0013`). Updated every in-repo prose
reference to the old numbers (`docs/adapters/nba-injury-report.md`,
`docs/backlog.md`, `docs/governance/risks.md`,
`backend/src/hoops_gm/ingest/injury_report/backfill.py`'s docstrings/
comments, one test docstring) to the new `0013`/`0014` numbers — this
historical entry and all earlier ones in this file are deliberately left
referring to whatever numbers were true when they were written, per this
file's own append-only convention.

**Now true:** This branch's migration chain is `... → 0011
(league_deadline_calendars, PR #20) → 0012 (scoring_profile_lineage, PR #22)
→ 0013 (injury_report_natural_key_game_date) → 0014
(injury_report_evidence_schema_version)`, contiguous with current
`origin/main`.

**Could not verify:** Whether another PR will claim `0013`/`0014` before
this one merges — the same race this branch has already been renumbered
around twice (`0011`→`0012` after PR #20, `0012`/`0013`→`0013`/`0014` after
PR #22). Must be re-checked immediately before requesting final review and
again immediately before merge.

**Next:** Re-run the full gate suite (Code, Adapter, migration
upgrade/check/downgrade lifecycle, Postgres CI) against the rebased head,
push, and request a fresh independent review pass. Not merged, not
self-approved. `injury-status-conversion` remains explicitly blocked.

## 2026-08-19 — data-engineer — Historical injury-report backfill: rebased onto PR #23 (main); migration numbers unchanged

**Changed:** `origin/main` advanced again to `4d5ab92` (PR #23, "Fail closed
on null league-settings evidence," merged) — confirmed via
`git show 4d5ab92 --stat` that it touched only
`backend/src/hoops_gm/ingest/league_settings.py`,
`backend/tests/test_league_settings.py`,
`docs/adapters/fantrax-official.md`, and `docs/handoff.md`; no
`backend/alembic/versions/` file changed, so the migration head on main is
still `0012_scoring_profile_lineage.py`. This branch's migrations therefore
keep their `0013`/`0014` numbers unchanged — only a rebase was needed, not a
further renumbering. Rebased onto `4d5ab92` (one conflict, again only in
`docs/handoff.md`, resolved the same way: concatenate HEAD's then the
incoming commit's entries, since both sides only ever append).

**Now true:** Branch head after this rebase sits directly on `4d5ab92`
(PR #23) → `036e4ca` (PR #22) → ... Migration chain unchanged:
`... → 0011 (PR #20) → 0012 (PR #22) → 0013 (this PR, natural-key fix) →
0014 (this PR, evidence-schema-version)`. Re-ran the full local gate suite
after the rebase: `ruff check` clean, `ruff format --check` clean (126
files), bare `mypy .` clean (110 source files), full `pytest -q` all green,
`pytest -m adapter_contract -q` all green, `scripts/check_no_secrets.py`
clean (234 tracked files), and a fresh `alembic upgrade head` → `alembic
check` → `alembic downgrade base` round-trip against a new throwaway SQLite
file — all three steps succeeded, "No new upgrade operations detected," and
the downgrade unwound cleanly to `-> ` (empty).

**Could not verify:** Whether yet another PR merges to main and claims a
migration number before this one is reviewed and merged — this project's
migration slot has now moved three times under this branch (`0011` after
PR #20, `0012`/`0013`→`0013`/`0014` after PR #22, unchanged-but-rebase-required
after PR #23). Must re-check `origin/main`'s migration head immediately
before every future push and again immediately before merge.

**Next:** Push this rebase, confirm GitHub CI (including the Postgres job)
is green against the new head, and obtain a fresh independent review. Not
merged, not self-approved. `injury-status-conversion` remains explicitly
blocked pending that review.

## 2026-08-19 — data-engineer — Historical injury-report backfill: sixth independent review found one missed file in the migration renumbering; fixed

**Changed:** A sixth-round independent review of head `b03b8e9` (correcting
this file's own prior claim that the `0012`/`0013`→`0013`/`0014` renumbering
swept "every in-repo prose reference") found that
`backend/src/hoops_gm/db/models/injury_report.py` — new in this PR — still
used the old provisional pairing (0012 = natural-key fix, 0013 =
evidence-schema-version) in six docstring/comment locations, contradicting
every other reference in the diff and the actual migration files. This is a
comment/docstring-only defect with zero runtime effect (all functional code
paths were correctly renumbered), but it directly undermines this PR's own
premise of trustworthy provenance documentation, so it is fixed rather than
waved through. All six lines corrected to say 0013 (natural-key fix) / 0014
(evidence-schema-version), matching the rest of the diff. Re-ran `ruff
check`, `ruff format --check`, bare `mypy .`, and full `pytest -q` — all
clean.

**Now true:** Every in-repo reference to this PR's two migrations is
internally consistent: 0013 = `injury_report_natural_key_game_date`, 0014 =
`injury_report_evidence_schema_version`. The sixth review's other findings
were all re-verifications of rounds 1-5's fixes holding under fresh,
independent execution (not just trusting commit messages) — chain
integrity, single alembic head, upgrade/check/downgrade round-trip, all
eight round-5 fixes (a)-(h), ruff/mypy/pytest/adapter_contract all
independently re-run and confirmed clean, and no evidence of dropped or
duplicated logic from either rebase's append-only `docs/handoff.md`
conflict resolution. No other defects found.

**Could not verify:** Whether this is genuinely the last inconsistency —
the same "renumbering commit missed one file" failure mode could recur if
main's migration head moves again before this PR merges. A full-repo grep
for the exact old numbers immediately before every future push remains the
only defense.

**Next:** Push this fix, confirm CI stays green, and report final status
(exact head, all gates, CLEAN/MERGEABLE, all round 1-6 fixes) to the
coordinator. Not merged, not self-approved. `injury-status-conversion`
remains explicitly blocked.

## 2026-08-19 — data-engineer — Historical injury-report backfill: seventh round, three coverage-honesty defects found and fixed (checkpoint/coverage atomicity, unresolved-entry veto, stale-tipoff revalidation)

**Changed:** A seventh independent review of head `d08cf88` found three
HIGH-severity defects, all in the coverage/checkpoint machinery itself
rather than in the source's actual coverage gap — each is exactly the
"validation of form cannot catch errors of meaning" failure mode this
project's own house rules warn about: the code ran, the types checked, and
it still produced a confidently wrong per-game claim.

1. **Checkpoint settlement and coverage evidence were not durably atomic.**
   `run_backfill` accumulated every candidate's `CandidateCoverage` in
   memory and wrote the whole run's coverage file once at the very end
   (`main`), but checkpointed each candidate as settled immediately as it
   was decided. A crash (or a later import exception) between those two
   points left a permanently-settled candidate with no coverage record and
   no way to reconstruct one, since resume skips settled candidates by
   design — a durable, silent coverage hole. Fixed by adding a
   `persist_coverage: Callable[[CandidateCoverage], None] | None` parameter
   to `run_backfill` and a `_record_coverage` helper that calls it — merging
   that single candidate's evidence into the durable, merge-idempotent
   coverage file — strictly *before* `checkpoint.record(...)` in every one
   of the four outcome branches (forbidden/403, not-available/404,
   error/commit-failure, fetched). A crash between the two calls now either
   leaves both durable, or leaves coverage durable with the checkpoint
   still unsettled (safe: reprocessed on resume; idempotent for import via
   its natural key and for coverage via `_coverage_merge_key`) — never the
   reverse. `main()` wires this to the existing `_persist_coverage`
   read-merge-write helper, unchanged in its own logic.
2. **An unresolved report entry could let a game falsely read as a clean
   zero-injury submission.** `coverage_for_games`'s entry query filtered on
   `InjuryReportEntry.game_id.in_(...)`, so a listed (non-`NOT_YET_SUBMITTED`)
   row whose `game_id` never resolved was structurally invisible to it.
   Independently reproduced exactly as reported: a fetched report with one
   unresolved `OUT` entry classified its game `submitted_zero_listed` while
   `entries_in_scope=1, resolved_game_id=0, status_listed=1`. Fixed by
   broadening the query to `game_date.in_(...)` (always populated) first,
   then adding a local, conservative supplementary lookup that
   re-attributes an unresolved row to a single unambiguous `ready` game on
   its date via the report's own `Matchup` column tricodes (parsed by a new
   `_matchup_tricodes` helper). When zero or more than one candidate game
   matches, the row is never silently dropped: it vetoes
   `submitted_zero_listed` for every game sharing that date through a new
   `unresolved_evidence` outcome (`GameObservationCoverage.outcome`),
   ranked above both `not_yet_submitted_only` and `submitted_zero_listed`
   — so an unattributable listed row can only ever make a game's reported
   outcome more honest, never disappear from it.
3. **A tip-off correction could leave stale, now-post-tip coverage still
   vouching for a clean submission.** `coverage_for_games` trusted a
   fetched candidate's persisted `applicable_game_ids` unconditionally,
   with no revalidation against the game's *current* `tipoff_utc`. If a
   game's tip-off was corrected after that candidate's canonical masthead
   instant was recorded, evidence that was genuinely pre-tip when fetched
   can retroactively become post-tip — and only strictly pre-tip evidence
   may support a clean-submission claim. Fixed: each fetched candidate's
   `canonical_report_timestamp` is now parsed and compared against the
   game's current `tipoff_utc` (looked up fresh from the live `ready`
   argument on every call, never a stale precomputed set) before its
   `applicable_game_ids` may contribute to `submitted_zero_listed`. A stale
   candidate simply stops counting for that game (falling to
   `no_candidate_coverage` if nothing else applies) without vetoing a
   separate, still-valid candidate covering the same game — verified by a
   dedicated stale-and-corrected-coexist regression.

Six new regression tests were added to
`backend/tests/test_injury_report_backfill.py`: two exact reproductions of
findings #2/#3 (`test_coverage_for_games_does_not_let_an_unresolved_listed
_entry_become_zero_listed`,
`test_coverage_for_games_revalidates_canonical_timestamp_against_current
_tipoff`), one veto-fallback test
(`test_coverage_for_games_vetoes_zero_listed_for_a_genuinely_unattributable
_row`), one coexistence test
(`test_coverage_for_games_stale_and_corrected_coverage_can_coexist`), and
two crash-after-settlement durability tests for finding #1, fetched and 404
outcomes respectively
(`test_run_backfill_persists_coverage_durably_before_settling_a_fetched
_candidate`,
`test_run_backfill_persists_coverage_durably_before_settling_a_404
_candidate`) — each simulates a crash immediately after the first
candidate's coverage is persisted but before its checkpoint would be
written, confirms the process aborts with `_CrashAfterCoverage`, then
resumes and asserts the durable coverage file already has that candidate's
record (proving no hole) and that resuming produces no duplicate for it
(proving no double-write on the merge-idempotent key).

**Now true:** `ruff check` and `ruff format --check` clean across the
repo; bare `mypy .` clean (110 source files); the full backend test suite
(`pytest -q`, default `-m 'not live_smoke'`) exits 0 with no failures,
including all 78 tests in `test_injury_report_backfill.py` (72 prior +
6 new — confirmed via `--collect-only`; an earlier commit-message claim of
"84/84" was a miscount, corrected here); `pytest -m adapter_contract -q`
exits 0; `test_portability.py`'s
static migration-chain checks pass; `scripts/check_no_secrets.py` finds no
secrets in 234 tracked files. `docs/adapters/nba-injury-report.md` gained a
new "Round-6 review found three more honesty defects" section documenting
all three fixes in the same falsifiable style as prior rounds.
`origin/main` was re-fetched and confirmed unchanged at `4d5ab92` (no
rebase or migration renumbering required); the Alembic chain remains
`0011(main)→0012(main, PR #22)→0013(natural-key fix)→0014
(evidence-schema-version)`, confirmed via direct `revision`/`down_revision`
inspection of each versions file.

**Could not verify:** Whether a live Postgres instance is reachable in
this session — Docker is not installed here (`docker` is not a recognized
command), `TEST_DATABASE_URL` is unset, and no local Postgres service was
available to start, so only SQLite-backed unit tests and
`test_portability.py`'s static cross-dialect analysis ran locally; CI's
dedicated Postgres job remains the actual cross-dialect check of record
for this round's changes (none of which touch schema — no new migration
was needed, only application-code and coverage-file-shape changes). Real
403/network behavior against the live NBA CDN was not re-exercised this
round: all three fixes were validated against recorded fixtures and
in-memory doubles (`_CrashAfterCoverage`, scripted 403/404/fetched
candidates), not a fresh live probe, so the actual production frequency of
a genuine mid-run crash, an unresolved-entry-and-zero-listed collision, or
a tip-off correction landing between two backfill runs remains
theoretical rather than empirically observed — the fixes close a proven
*possible* failure mode (each has an exact reproducing regression), not a
measured *frequent* one. Whether GitHub's merge-readiness check (CI green,
CLEAN/MERGEABLE) reflects this specific push is reported separately once
observed after pushing.

**Next:** Push to `origin/sr2501-historical-injury-backfill`, monitor all
GitHub CI jobs (including the Postgres job) to green, confirm
`mergeStateStatus: CLEAN`/`mergeable: MERGEABLE` via `gh pr view`,
commission a fresh independent exact-head code review re-verifying these
three fixes plus re-confirming rounds 1-6 have not regressed, then report
the new exact head/base and full gate status to the coordinator. Still not
merged, not self-approved; `injury-status-conversion` remains explicitly
blocked pending the separate, later Model-gated deliverable.

## 2026-08-19 — data-engineer — Historical injury-report backfill: eighth round, three more evidence-identity defects found and fixed (current-DB tipoff race, per-game unresolved applicability, stable NBA game-id evidence)

**Changed:** An eighth independent review, of exact head `650d74e`, found
three more HIGH-severity defects in `coverage_for_games` and its evidence —
again in the coverage-classification machinery itself, not the source's
actual coverage gap. In-code comments and identifiers for these three
fixes are labelled "round-7 review point 1/2/3" (matching the reviewer's
own numbering of this specific finding set); this handoff entry is titled
"eighth round" to keep this log's own sequential count of independent
review passes against this PR.

1. **Stale caller-supplied `tipoff_utc` snapshot, not the current DB
   value.** `coverage_for_games` validated fetched-candidate mastheads
   against the caller's own `BackfillGame.tipoff_utc` (the `ready`
   argument) — ordinarily built by an earlier `games_to_backfill` call and
   able to go stale before this function actually runs. A schedule
   correction landing in that window could let evidence that is genuinely
   post-tip against the *current* database row still be trusted as
   pre-tip because the caller's own snapshot disagreed. Fixed: every
   game's identity and `tipoff_utc` are now re-queried fresh from the
   database inside `coverage_for_games`'s own read scope, and only that
   freshly-read value is ever compared against a masthead timestamp. A
   game whose live row disappeared or lost its tip-off since the caller's
   snapshot was built is now reported `missing_tipoff` rather than
   classified against a value that no longer reflects the database.

2. **Unresolved-row veto was date-wide, not per-game/strictly-pre-tip,
   and its precedence could be masked by `legacy_excluded`.** The
   round-7 (seventh-round) fix let any current-schema row that never
   resolved to a single game veto every game on that date, including ones
   the row could not possibly concern (a report published after a game
   already tipped off cannot be pregame evidence for that game); it also
   excluded `NOT_YET_SUBMITTED` rows from the veto even though such a row
   still proves genuine uncertainty about whichever game it actually
   concerns; and a game with both a legacy row and separate current-schema
   unresolved evidence could report the coarser `legacy_excluded` instead
   of the more specific `unresolved_evidence`. Fixed: an unresolved row now
   vetoes `submitted_zero_listed` only for the same-date games whose
   *current* tip-off is strictly after the row's own report timestamp
   (built via a `games_by_date` map over freshly-read tip-offs); the
   `row.status is not NOT_YET_SUBMITTED` exclusion was removed, so
   `NOT_YET_SUBMITTED` rows participate in the veto like any other
   current-schema row; and the final outcome precedence now checks
   `unresolved_evidence` before `legacy_excluded`, so current-schema
   uncertainty is never masked by the coarser legacy caveat.

3. **Persisted coverage relied on reusable surrogate `NbaGame.id` values
   as evidence identity.** `CandidateCoverage.applicable_game_ids` named
   games by their surrogate DB primary key, which a DB rebuild or
   reingestion can reassign to a wholly unrelated game — a stale coverage
   record could then prove `submitted_zero_listed` for whatever game now
   holds that recycled id, not the game it actually covered. Fixed:
   `CandidateCoverage` gained a required `applicable_nba_game_ids:
   tuple[str, ...]` field (the NBA's own stable game identifier, already
   carried by `BackfillGame.nba_game_id`) and a defaulted
   `evidence_schema_version: int = CURRENT_COVERAGE_SCHEMA_VERSION`
   field. `coverage_for_games` now matches fetched-candidate evidence
   against games by `applicable_nba_game_ids` only, via a
   `games_by_nba_id` map built from the same freshly-read rows as point 1
   — `applicable_game_ids` is retained solely for human-readable display,
   never as evidence identity. `CoverageReport.from_json` defaults a
   pre-fix record's missing `applicable_nba_game_ids` to `()` and its
   missing `evidence_schema_version` to `LEGACY_COVERAGE_SCHEMA_VERSION`
   on load (rather than letting an absent key silently read as current),
   and `coverage_for_games` explicitly skips any candidate whose
   `evidence_schema_version` is below current — a pre-round-7/8 coverage
   record is excluded entirely rather than trusted against whichever game
   holds its surrogate id today. `PlannedFetch` and `build_plan` were
   extended to compute and thread `applicable_nba_game_ids` alongside the
   existing surrogate ids, and all five `CandidateCoverage.from_candidate`
   call sites in `run_backfill` were updated to pass it.

Nine new regression tests were added to
`backend/tests/test_injury_report_backfill.py`:
`test_coverage_for_games_uses_current_db_tipoff_not_stale_caller_snapshot`
(point 1 — a stale caller snapshot must not launder post-tip evidence as
clean); five staggered-multi-game tests for point 2
(`test_coverage_for_games_unattributable_row_before_both_tipoffs_vetoes
_both_games`,
`..._unattributable_row_between_tipoffs_vetoes_only_the_later_game`,
`..._unattributable_row_after_both_tipoffs_vetoes_neither_game`,
`..._unattributable_not_yet_submitted_row_still_vetoes`,
`..._unattributable_legacy_row_does_not_veto`, and
`test_coverage_for_games_unresolved_evidence_outranks_legacy_excluded` for
the precedence fix); and two for point 3
(`test_coverage_for_games_stable_nba_id_prevents_reused_surrogate_id
_transfer`,
`test_coverage_for_games_legacy_evidence_schema_version_is_excluded_fail
_closed`). All sixteen pre-existing `CandidateCoverage.from_candidate(...)`
call sites across the test file were also updated to pass the new
required `applicable_nba_game_ids` keyword (real games' `.nba_game_id` for
DB-backed tests, parallel placeholder strings like `"nba-1"` for the
JSON-round-trip/merge-key tests that use placeholder surrogate ints and
never call `coverage_for_games` itself).

While rewriting `coverage_for_games`, a mypy variable-shadowing bug was
introduced and caught before commit: an `NbaGame` dict comprehension and a
later `InjuryReportEntry` loop both used the loop variable name `row`
within the same function, and mypy narrowed `row`'s type from the first
usage, flagging every `InjuryReportEntry`-only attribute access on the
second loop as invalid. Fixed by renaming the `NbaGame` comprehension's
variable to `nba_row` throughout its scope; `mypy src/hoops_gm/ingest
/injury_report/backfill.py` confirmed clean afterward. This was caught by
the type checker before any test ran, not by a test — worth noting since
this project's own house rule is that green tests do not prove
correctness; here the type gate is what actually caught the defect.

**Now true:** `ruff check` and `ruff format --check` clean across the
repo; bare `mypy .` clean (110 source files); the full backend test suite
(`pytest -q`, default `-m 'not live_smoke'`) exits 0 with no failures,
including all 87 tests in `test_injury_report_backfill.py` (78 prior + 9
new — confirmed via `--collect-only`); `pytest -m adapter_contract -q`
exits 0; `test_portability.py`'s static migration-chain checks pass;
`scripts/check_no_secrets.py` finds no secrets in 234 tracked files.
`origin/main` was re-fetched and confirmed unchanged at `4d5ab92` (no
rebase or migration renumbering required — this round's changes are an
application-code and coverage-JSON-artifact-shape change, not a database
schema change); the Alembic chain remains
`0011(main)→0012(main, PR #22)→0013(natural-key fix)→0014
(evidence-schema-version)`.

**Could not verify:** Whether a live Postgres instance is reachable in
this session — the same constraint as every prior round: Docker is not
installed, `TEST_DATABASE_URL` is unset, and no local Postgres service was
available to start, so only SQLite-backed unit tests and
`test_portability.py`'s static cross-dialect analysis ran locally; CI's
dedicated Postgres job remains the actual cross-dialect check of record.
Real 403/network behavior and a genuine schedule-correction race against
the live NBA CDN were not re-exercised this round either: all three fixes
were validated against recorded fixtures, seeded SQLite rows, and directly
constructed `CandidateCoverage`/`BackfillGame` doubles, not a fresh live
probe or a real concurrent-write race — the fixes close proven *possible*
failure modes (each has an exact reproducing regression against the
described mechanism), not measured *frequent* ones, and the staggered
multi-game veto tests use synthetic same-date games rather than a
recovered real slate with genuinely staggered tip-offs. Whether GitHub's
merge-readiness check (CI green, CLEAN/MERGEABLE) reflects this specific
push is reported separately once observed after pushing.

**Next:** Push to `origin/sr2501-historical-injury-backfill`, monitor all
GitHub CI jobs (including the Postgres job) to green, confirm
`mergeStateStatus: CLEAN`/`mergeable: MERGEABLE` via `gh pr view`,
commission a fresh independent exact-head code review re-verifying these
three fixes plus re-confirming rounds 1-7 have not regressed, then report
the new exact head/base and full gate status to the coordinator. Still not
merged, not self-approved; `injury-status-conversion` remains explicitly
blocked pending the separate, later Model-gated deliverable.

## 2026-08-19 — data-engineer — Historical injury-report backfill: ninth round, ORM identity-map staleness, full schedule-scope binding, and duplicate/leaked coverage output found and fixed

**Changed:** A ninth independent review, of exact head `b1f2d67`, found four
more defects (two HIGH, two MEDIUM release-blocking) in `coverage_for_games`
— once again in the classification machinery's own evidence handling, not
the source's actual coverage gap. In-code comments are labelled "round-9
review point 1/2/3/4" (matching the reviewer's own numbering); this entry is
"ninth round" to keep this log's sequential count of independent review
passes against this PR.

1. **ORM identity-map staleness could still return a stale tip-off even
   after round-8's "re-query fresh" fix.** Round 8 replaced the caller's
   snapshot with a fresh `session.scalars(select(NbaGame)...)` query, but a
   plain re-query is not automatically a fresh *read*: if the same session
   already has a `NbaGame` row loaded in its identity map (e.g. from an
   earlier call, or a caller that touched the row for an unrelated reason),
   SQLAlchemy's default merge behavior leaves that already-loaded instance's
   attributes untouched, even though the query itself re-executes against
   the database. This project's session factory is configured with
   `expire_on_commit=False`, so even the session's own commit does not clear
   this staleness — it persists until something forces a real refresh.
   Fixed: `.execution_options(populate_existing=True)` was added to all
   three `NbaGame` queries in `coverage_for_games` and
   `select_canonical_pregame_observations` that matter for freshness
   (the `current_rows` query, the `by_tricode_pair`-building loop, and the
   games dict comprehension in `select_canonical_pregame_observations`),
   forcing SQLAlchemy to repopulate any already-identity-mapped instance's
   attributes from the query's own fresh result row rather than trusting
   whatever was cached.

2. **Persisted coverage validated only stable NBA game id + timestamp, not
   full schedule-scope binding or an exact schema version.** Round 7/8
   rejected legacy (`< CURRENT`) schema versions and matched by stable NBA
   game id, but an *unrecognized future* schema version (`>= CURRENT`) still
   passed, and nothing checked that a candidate's `report_date` still
   matched the game's *current* `game_date` (a reschedule keeping the same
   stable id could inherit stale evidence for a different date) or that the
   `CoverageReport`'s own `season`/`season_type` matched the game's current
   schedule scope (evidence built under one season/type could otherwise
   "prove" a claim for an unrelated one sharing the same NBA game id by
   coincidence). Fixed: the schema-version check changed from `<` to `!=`
   (rejects both legacy *and* unrecognized-future versions); a new
   `game.game_date == date.fromisoformat(candidate.report_date)` binding
   check rejects evidence for a game rescheduled to a different date; and a
   new `game_scope_by_id: dict[int, tuple[str, str]]` map (built from the
   same freshly-read rows, no extra query) checks the game's current
   `(season, season_type.value)` against `coverage_report.season`/
   `coverage_report.season_type` before trusting any `submitted_zero_listed`
   claim.

3. **A retracted-tipoff game was emitted twice.** The `for g in ready:`
   results loop appended an inline `missing_tipoff` record whenever
   `games_by_id.get(g.game_id)` was `None`, and the same game was emitted
   again via the separate `for mg in newly_missing:` loop, inflating
   counts. Fixed: the inline emission was removed (now a bare `continue`
   with a comment explaining the game is already captured exactly once via
   `newly_missing`).

4. **Resolved-but-out-of-scope evidence fanned out onto unrelated same-date
   games.** If a row's `game_id` was non-null but no longer resolved to a
   currently-live game (e.g. because that game's own tip-off was
   retracted), it was treated identically to a genuinely unattributable row
   (`game_id is None`) and fanned the conservative date-wide veto across
   every later same-date game — contaminating games it says nothing about.
   Fixed: the fan-out veto logic (`unresolved_evidence_ids`) now applies
   only when `row.game_id is None`; a resolved-but-out-of-scope `game_id`
   is `continue`d without any side effect, remaining bound to its own
   (now-missing) game.

Seven new regression tests were added to
`backend/tests/test_injury_report_backfill.py`:
`test_coverage_for_games_uses_database_current_tipoff_despite_retained_orm_identity`
(point 1 — a genuine two-session reproduction: one session's identity-mapped
row is committed stale, a wholly separate session updates and commits the
correction, and classification through the first session must see the
corrected value);
`test_coverage_report_from_json_loads_real_legacy_serialized_text_as_legacy`,
`test_coverage_report_from_json_rejects_an_unrecognized_future_schema_version`,
`test_coverage_for_games_rejects_evidence_whose_report_date_no_longer_matches_current_game`,
and
`test_coverage_for_games_rejects_evidence_from_a_coverage_report_with_a_different_season`
(point 2 — hand-written literal legacy JSON text, an unrecognized future
`evidence_schema_version`, a rescheduled game_date, and a mismatched
`season`, each proven unable to yield `submitted_zero_listed`);
`test_coverage_for_games_retracted_tipoff_game_is_emitted_exactly_once`
(point 3 — an exact cardinality assertion, not just an outcome check); and
`test_coverage_for_games_resolved_out_of_scope_row_does_not_leak_to_unrelated_game`
(point 4 — a resolved-but-retracted game plus an unrelated later same-date
game, proving the latter is not vetoed).

A mypy narrowing regression was hit and fixed during this round: an initial
refactor of the unattributable-row branch introduced an intermediate
`resolved_by_id = row.game_id is not None` boolean to avoid repeating the
`None`-check, which broke mypy's flow-sensitive narrowing on
`row.game_id: int | None` at the later `games_by_id.get(row.game_id)` call
(mypy could not infer non-`None`-ness through the boolean indirection).
Fixed by checking `row.game_id is not None` directly at both call sites
instead of caching the boolean result — worth remembering for any future
refactor of this function, since this is the second round in a row a
`None`-narrowing subtlety has appeared here (round 8's was a *variable-name
shadowing* issue; this one is an *indirection-breaks-narrowing* issue).

**Now true:** `ruff check` and `ruff format --check` clean across the repo;
bare `mypy .` clean (110 source files); the full backend test suite
(`pytest -q`, default `-m 'not live_smoke'`) exits 0 with no failures,
including all 94 tests in `test_injury_report_backfill.py` (87 prior + 7
new — confirmed via `--collect-only`); `pytest -m adapter_contract -q`
exits 0; `test_portability.py`'s static migration-chain checks pass;
`scripts/check_no_secrets.py` finds no secrets in 234 tracked files.
`origin/main` was re-fetched and confirmed unchanged at `4d5ab92` (no rebase
or migration renumbering required — this round's changes are again an
application-code and coverage-classification-logic change, not a database
schema change); the Alembic chain remains
`0011(main)→0012(main, PR #22)→0013(natural-key fix)→0014
(evidence-schema-version)`.

**Could not verify:** Whether a live Postgres instance is reachable in this
session — the same constraint as every prior round: Docker is not
installed, `TEST_DATABASE_URL` is unset, and no local Postgres service was
available to start, so only SQLite-backed unit tests and
`test_portability.py`'s static cross-dialect analysis ran locally; CI's
dedicated Postgres job remains the actual cross-dialect check of record.
The identity-map-staleness reproduction (point 1) does exercise a genuine
two-session/two-transaction race against a real file-backed SQLite database
(via the `database` fixture, not the single non-committing `session`
fixture), which is a materially stronger reproduction than a synthetic
double built entirely in one session/transaction — but it is still not a
live probe against the real NBA CDN or a real concurrent-write race under
production load, and Postgres's own MVCC/locking behavior for this exact
sequence was not independently exercised this round (SQLite's locking
semantics differ from Postgres's, though `populate_existing` itself is a
SQLAlchemy ORM-layer behavior independent of the backing dialect). Whether
GitHub's merge-readiness check (CI green, CLEAN/MERGEABLE) reflects this
specific push is reported separately once observed after pushing.

**Next:** Push to `origin/sr2501-historical-injury-backfill`, monitor all
GitHub CI jobs (including the Postgres job) to green, confirm
`mergeStateStatus: CLEAN`/`mergeable: MERGEABLE` via `gh pr view`, commission
a fresh independent exact-head code review re-verifying these four fixes
plus re-confirming rounds 1-8 have not regressed, then report the new exact
head/base and full gate status to the coordinator. Still not merged, not
self-approved; `injury-status-conversion` remains explicitly blocked pending
the separate, later Model-gated deliverable.

## 2026-08-19 — data-engineer — Historical injury-report backfill: tenth round, single-snapshot classification, coverage scope/version binding, and scope-sensitive checkpoint settlement

**Changed:** A tenth independent review, of exact head `15e923e`, found three
more release-blocking defects (two HIGH, one MEDIUM) in the same coverage/
checkpoint machinery — again in the classification layer's own evidence
handling, not the source's actual coverage gap. In-code comments are labelled
"round-10 review point 1/2/3"; this entry is "tenth round" to keep this log's
sequential count of independent review passes against this PR.

1. **Classification still mixed state across separate statements, this time
   between two different functions.** `coverage_for_games` issued one
   `NbaGame` query building `games_by_id`, then called
   `select_canonical_pregame_observations`, which issued its *own*,
   separately-timed `NbaGame` query solely to look up tip-offs for lead-time
   computation. A schedule correction landing between the two could let one
   game's trust-classification see an old tip-off while another game's
   observation lead-time, computed moments later in the very same
   `coverage_for_games` call, already saw a new one — self-inconsistent
   within one invocation. Round 9 already established that a second query
   is not automatically fixed by re-querying (ORM identity-map staleness);
   this round removes the second query outright. Fixed: `coverage_for_games`
   now reads every classification-relevant field — stable id, local id,
   date, tip-off, season, season_type, and both teams' abbreviations (via
   `aliased(NbaTeam)` for home/away) for tricode matching — in **exactly
   one** `SELECT`, once, at the top of the function; every downstream map
   (`games_by_id`, `games_by_nba_id`, `game_scope_by_id`, `games_by_date`,
   the tricode-pair index, `game_tipoffs`) is derived solely from that one
   immutable result. `select_canonical_pregame_observations` gained an
   optional `game_tipoffs: Mapping[int, datetime] | None` parameter so
   `coverage_for_games` can pass its own snapshot in rather than triggering
   a second query; its other (exclusion-cascade) call site is unaffected and
   still queries internally when the parameter is omitted. Selecting
   individual columns rather than full `NbaGame` entities also means there
   is no ORM identity map for a stale instance to hide in at all —
   `populate_existing` becomes structurally moot, not merely applied.

   The regression proves this with a real second database connection, not a
   mock: `test_coverage_for_games_reads_one_atomic_snapshot_despite_a_correction_committed_mid_call`
   registers a `before_cursor_execute` hook — fired by the SQLAlchemy engine
   itself as the classification statement is about to run, not sequenced by
   test code before the call — that has a wholly separate session commit a
   tip-off correction for one game and retract another's entirely. The test
   asserts (a) the classification `SELECT` (matched by its unique
   `home_abbr` column label) executes exactly once for the whole call, and
   (b) the one query's result reflects the corrected 20:00 tip-off for the
   first game and the retraction for the second, together and consistently
   — proving there is no second statement left for a correction to land
   between, and that a stale caller-supplied `ready` snapshot cannot win
   either.

2. **Persisted coverage validated stable identity and per-game schedule
   scope, but not the file's own declared scope or each candidate's own
   recorded scope.** `_persist_coverage`/`_merge_coverage` could load a
   candidate carrying a different `season`/`season_type` than either the
   file already held or the caller's current request, merge it by an
   identity key that omitted season/type, and rewrite the file under the
   caller's trusted label — silently laundering wrong-scope evidence into
   a scope it never actually belonged to. Fixed: `CURRENT_COVERAGE_SCHEMA_VERSION`
   bumped 2 → 3; `CandidateCoverage` gained required `season`/`season_type`
   fields (self-describing its own scope, not just inherited from the
   enclosing `CoverageReport`); `_coverage_merge_key` is now a 5-tuple
   including season/season_type; `_persist_coverage` raises the new
   `CoverageScopeMismatch` when the file's own declared scope disagrees
   with the current request (refusing to merge and rewrite under the wrong
   label), and separately excludes — without raising — any individual
   candidate whose own recorded scope disagrees, even inside an otherwise-
   matching file. `coverage_for_games` also gained a defense-in-depth check
   rejecting a fetched candidate whose self-described `season`/`season_type`
   disagrees with the `CoverageReport`'s own, on top of the existing
   DB-derived `game_scope_by_id` check from round 9.

   Three new regression tests exercise the real `_persist_coverage` load +
   merge + save path against hand-built literal serialized JSON (not
   in-memory objects, via a new `_serialized_candidate` test helper):
   `test_persist_coverage_raises_on_whole_file_season_mismatch`,
   `test_persist_coverage_raises_on_whole_file_season_type_mismatch`, and
   `test_persist_coverage_excludes_a_candidate_whose_own_recorded_scope_disagrees`.

3. **Checkpoint settlement identity ignored applicable-game scope
   entirely.** `Checkpoint.key()` embeds `(date, anchor, resolved
   report_timestamp)`, which round 4 fixed to catch a *changed* resolved
   instant — but a near-tip candidate's instant is derived from a date's
   earliest *known* tip-off among currently-ready games. A genuine
   `--allow-missing-tipoff` partial day, where a same-day game's tip-off is
   ingested *later* than the date's already-known earliest, leaves the
   resolved instant (and therefore the checkpoint key) completely
   unchanged — the same key still matches on resume, so the previously
   recorded settlement (covering only the games ready at the time) was
   trusted forever, permanently stuck at `no_candidate_coverage` for the
   newly-ready game even though the exact URL this candidate names was
   already fetched (or confirmed `not_available`) and genuinely does apply
   to it now. Fixed: `Checkpoint.is_settled`/`record` now accept an
   `applicable_nba_game_ids: Sequence[str]` parameter; `record` persists the
   settled scope (stable NBA game ids, not surrogate local ids) alongside
   the existing key fields, and `is_settled` reports unsettled — regardless
   of whether the resolved-timestamp key itself changed — whenever the
   currently requested scope is not a subset of what was actually recorded
   settled. `run_backfill` and `BackfillPlan.PlannedFetch` were threaded
   through: every `checkpoint.record`/`is_settled` call site now passes
   `pf.applicable_nba_game_ids`. Reprocessing on scope expansion is
   idempotent either way — the raw payload is already locally cached, a
   fetched candidate's re-import is idempotent by natural key, and a
   `not_available` candidate simply stays `not_available` — so this only
   ever expands correctly-attributed coverage, never duplicates anything.
   Corrected a false claim this project's own adapter doc made about this:
   it previously implied a newly-ingested game *always* changes the
   resolved timestamp, which is only true when the new game's tip-off is
   *earlier* than the date's already-known earliest — the doc now explains
   both cases and the scope-fingerprint fix that catches the one where the
   timestamp does not change.

   `test_run_backfill_partial_day_missing_tipoff_then_later_tipoff_resumes_and_expands_scope`
   is an end-to-end regression through `build_plan`/`run_backfill`/
   `Checkpoint`/`coverage_for_games` together: run 1 settles a near-tip
   candidate covering only a ready game A while game B is genuinely missing
   a tip-off; game B then gains a tip-off *later* than game A's (so the
   date's earliest tip-off, and this candidate's resolved instant, are
   provably unchanged — asserted directly); the candidate is proven *not*
   settled for the expanded scope, resume reprocesses it (not skipped,
   zero new rows created — a clean idempotent reprocess of a zero-listed
   payload), and `coverage_for_games` afterward classifies both games as
   `submitted_zero_listed`, not leaving game B stuck at
   `no_candidate_coverage`.

Fixing 21 pre-existing `CandidateCoverage.from_candidate(...)` test call
sites for the new required `season`/`season_type` kwargs, and 3 direct
`checkpoint.record(...)` test call sites for the new
`applicable_nba_game_ids` kwarg, surfaced a genuine pre-existing test gap:
several tests recorded settlement with an implicit empty scope and then
checked `is_settled` against a real, non-empty `PlannedFetch.applicable_nba_game_ids`
from an actual `build_plan()` result — which the new subset-check now
(correctly) reports as unsettled, forcing those call sites to pass the real
scope explicitly rather than relying on the previously-inert default.

A mypy variable-shadowing subtlety was hit and fixed this round, a third
consecutive round with a distinct flavor of the same underlying lesson
(round 8: shadowing across an unrelated branch; round 9: an intermediate
boolean breaking flow-sensitive narrowing; this round: reusing the same
local variable name — `row` — for two structurally different query-result
row types across two different loops in the same function body, which
caused mypy to unify/misinfer the type across both usages). Fixed by
renaming the outer snapshot-loop variable to `snap_row`.

**Now true:** `ruff check` and `ruff format --check` clean across the repo;
bare `mypy .` clean (110 source files); the full backend test suite
(`pytest -q`, default `-m 'not live_smoke'`) exits 0 with no failures,
including all 99 tests in `test_injury_report_backfill.py` (94 prior + 5
new — confirmed via `--collect-only`); `pytest -m adapter_contract -q`
exits 0; `test_portability.py`'s static migration-chain checks pass;
`scripts/check_no_secrets.py` finds no secrets in 234 tracked files.
`origin/main` was re-fetched and confirmed unchanged at `4d5ab92` (no
rebase or migration renumbering required — this round is again an
application-code and coverage/checkpoint-logic change, not a database
schema change); the Alembic chain remains
`0011(main)→0012(main, PR #22)→0013(natural-key fix)→0014
(evidence-schema-version)`.

**Could not verify:** Whether a live Postgres instance is reachable in this
session — the same constraint as every prior round: Docker is not
installed, `TEST_DATABASE_URL` is unset, and no local Postgres service was
available to start, so only SQLite-backed unit tests and
`test_portability.py`'s static cross-dialect analysis ran locally; CI's
dedicated Postgres job remains the actual cross-dialect check of record.
The single-snapshot concurrency regression (point 1) does exercise a
genuine two-session/two-transaction race against a real file-backed SQLite
database (via the `database` fixture and a real `before_cursor_execute`
engine hook, not a synthetic double built entirely in one
session/transaction) — but SQLite's locking semantics differ materially
from Postgres's READ COMMITTED snapshot behavior the original finding named,
and this exact interleaving was not independently re-exercised against a
live Postgres connection this round. No live NBA CDN probe was attempted
this round (no code path touching the live archive changed). Whether
GitHub's merge-readiness check (CI green, CLEAN/MERGEABLE) reflects this
specific push is reported separately once observed after pushing.

**Next:** Push to `origin/sr2501-historical-injury-backfill`, monitor all
GitHub CI jobs (including the Postgres job) to green, confirm
`mergeStateStatus: CLEAN`/`mergeable: MERGEABLE` via `gh pr view`, commission
a fresh independent exact-head code review re-verifying these three fixes
plus re-confirming rounds 1-9 have not regressed, then report the new exact
head/base and full gate status to the coordinator. Still not merged, not
self-approved; `injury-status-conversion` remains explicitly blocked pending
the separate, later Model-gated deliverable.

## 2026-08-19 — data-engineer — Historical injury-report backfill: eleventh round, evidence-durability and persistence-boundary fixes, plus a docs overclaim correction

A fresh independent review of exact head `eaf91c2` (base `main` at `5bed586`,
PR #25 merged) found five more release-blocking issues, all now fixed, tested,
and re-gated. `origin/main` was re-fetched and confirmed unchanged at
`5bed586` — no rebase or migration renumbering required this round; this is
again an application-code, test, and docs-only change, not a schema change.

1. **The single authoritative DB snapshot in `coverage_for_games` still
   excluded every game the caller classified as `missing_tipoff`.** Round 10
   built one atomic snapshot query to close a mid-call staleness gap, but
   that query's `WHERE NbaGame.id.in_(...)` clause was built only from
   `ready` game ids — a game the caller believed still had no tip-off never
   appeared in the snapshot at all, so a tip-off ingested for it *during*
   this same call (the exact interleaved-correction scenario round 10's own
   fix targeted) could never be observed within that invocation; the game
   stayed reported `missing_tipoff` forever for that call, trusting the
   caller's stale classification instead of this function's own fresh read.
   Fixed: `ready` and `missing_tipoff` game ids are now unioned into one
   `requested_games` list feeding the single snapshot query; classification
   iterates that unified list and promotes any game whose fresh snapshot row
   shows a non-null `tipoff_utc` into full classification regardless of
   which caller-side list it originally came from. The old separate
   `for mg in missing_tipoff:` passthrough loop — which never re-checked the
   database at all — is deleted entirely.

   New regression:
   `test_coverage_for_games_single_snapshot_promotes_a_newly_tipped_off_missing_game`
   seeds a game with `tipoff_utc=None` and a real canonical entry already
   committed for it, calls `coverage_for_games` classifying it as
   `missing_tipoff`, and uses a real `before_cursor_execute` hook (a second,
   separate DB session) to commit a genuine tip-off for that game exactly as
   the snapshot statement is about to execute — proving the promotion
   happens inside the one snapshot, not via a second read.

2. **`_persist_coverage` could still retain and rewrite an incompatible
   coverage-schema-version candidate as trusted current evidence.**
   `coverage_for_games` already refused to *trust* a candidate whose
   `evidence_schema_version` was not exactly current for a clean-submission
   claim — but that was the only place a wrong version was ever checked.
   `_persist_coverage`'s own `existing` filter checked `(season,
   season_type)` alone; a legacy (pre-round-7) record, or any future record
   with a schema version this code has never seen, would still be read back
   off disk, merged unchanged by `_merge_coverage`, and rewritten into the
   very file this run treats as its own current, trusted artifact for this
   scope — quarantined from classification, but never actually quarantined
   from the persisted evidence itself. Fixed: `_persist_coverage`'s
   `existing` filter now also requires
   `c.evidence_schema_version == CURRENT_COVERAGE_SCHEMA_VERSION`, dropping
   any legacy or unrecognized-future candidate at the moment it is read, so
   it can never be laundered forward into a freshly-rewritten "current" file
   again.

   Two new regressions exercise the real load+merge+save path against
   hand-built literal serialized JSON (the existing `_serialized_candidate`
   test helper, not in-memory objects):
   `test_persist_coverage_quarantines_an_unrecognized_future_schema_version_candidate`
   (schema version `CURRENT_COVERAGE_SCHEMA_VERSION + 1`) and
   `test_persist_coverage_quarantines_a_legacy_pre_versioning_candidate_too`
   (the key entirely absent, exactly as a genuine pre-round-7 record would
   be).

3. **The coverage merge key was still incomplete.** `_coverage_merge_key`
   included `(season, season_type, report_date, anchor, requested_timestamp)`
   — every field describing *what was requested*, but nothing describing
   *what evidence was actually resolved*. Two genuinely distinct fetched
   records sharing every requested-side field (the same requested instant,
   re-attempted) but resolving a *different* canonical masthead timestamp
   (a corrected publish) or a *different* applicable game scope (the
   schedule changed between attempts) collapsed under an identical key —
   the later attempt silently overwrote the earlier one's real, distinct
   trusted evidence. Fixed: the key now also includes
   `canonical_report_timestamp` (`""` for an outcome with none, e.g. a
   404/403/error) and an order-independent fingerprint of
   `applicable_nba_game_ids` (`",".join(sorted(...))`).

   Three new regressions:
   `test_coverage_merge_key_distinguishes_records_differing_only_in_canonical_masthead`
   and `test_coverage_merge_key_distinguishes_records_differing_only_in_applicable_game_scope`
   prove two such records now coexist rather than one clobbering the other;
   `test_coverage_merge_key_dedupes_a_truly_identical_re_fetch` proves an
   ordinary idempotent re-fetch (identical on every field, including these
   two new ones) still correctly collapses to one record rather than
   growing duplicates.

4. **An import-time flush failure bypassed the commit-failure recovery
   boundary entirely.** `import_injury_report_entries` calls
   `session.flush()` internally, before `run_backfill` ever reaches its own
   `session.commit()` — but that call sat outside any `try`/`except` in
   `run_backfill`. A flush can fail for the identical reasons a commit can
   (a constraint violation, a dropped connection); before this fix, such a
   failure propagated straight out of the entire function, aborting every
   other still-unprocessed candidate in the plan, rather than being handled
   as this one candidate's recorded, unsettled `"error"` the way a commit
   failure already was. Fixed: the import call and `session.commit()` now
   share one `try`/`except` — a failure from either path takes the
   identical rollback + failure-coverage + checkpoint-`"error"` treatment,
   and every other candidate in the plan still runs to completion.

   New regression:
   `test_run_backfill_does_not_checkpoint_as_settled_when_the_import_flush_fails`
   is a genuine database constraint violation, not a mocked commit: it
   passes `player_name_raw=None` (bypassing the frozen dataclass's type
   hint, which Python does not enforce at runtime) for one entry, which
   violates `injury_report_entries.player_name_raw`'s real `NOT NULL`
   column and makes the importer's own internal flush raise a real
   `IntegrityError` against the actual SQLite engine. Proves: the candidate
   is rolled back (zero rows persisted), recorded as an unsettled `"error"`
   (never checkpointed settled), the other candidate in the same run (a
   genuine 404) is entirely unaffected, and a subsequent resume with a valid
   entry succeeds and persists exactly one row.

5. **`docs/backlog.md`'s `injury-report-historical-backfill` entry overclaimed
   a representative, trusted real cohort.** Its heading read "...for a real
   evidence cohort" and its opening sentence claimed the tool "populates a
   real multi-date, multi-game historical injury-report cohort ... so
   `injury-status-conversion` has more than the single committed fixture to
   work from" — read together with the entry's `[x] done` marker, this
   implied a representative cohort already exists, when in fact (per this
   file's own round-5 entry, still accurate) the only live-archive run
   performed was a deliberately small, non-representative 22-of-527-game
   sample used to validate the tool's mechanics, not to seed
   `injury-status-conversion`. Fixed: the heading now reads "Bounded,
   resumable operator workflow for backfilling historical NBA injury
   reports"; the opening sentence now says the tool "fetches and imports
   historical NBA official injury-report captures ... into durable per-game
   evidence, so `injury-status-conversion` has more than the single
   committed fixture to build against **once a genuinely representative
   cohort exists**"; and a new closing paragraph states explicitly what
   "done" means here — the bounded operator workflow itself, its gates, its
   durability/idempotency, and its tests — and what it does not: a populated,
   representative, conversion-ready cohort does not yet exist, populating one
   is separate unstarted work, and `injury-status-conversion` remains
   explicitly blocked. `docs/backlog.md`'s heading count (100) and its
   `[x]`/`[ ]` marker counts are unchanged — only this one entry's wording
   changed.

All five points were independently re-verified against the actual pre-fix
code (not accepted on the reviewer's word alone) before being fixed, per
house rules. 7 new tests were added to `test_injury_report_backfill.py`
(99 → 106, confirmed via `--collect-only`), all passing; the full file and
the full backend suite both pass with no regressions.

**Now true:** `ruff check` and `ruff format --check` clean across the repo;
bare `mypy .` clean (110 source files); the full backend test suite
(`pytest -q`, default `-m 'not live_smoke'`) exits 0 with no failures,
including all 106 tests in `test_injury_report_backfill.py`;
`pytest -m adapter_contract -q` exits 0; `test_portability.py`'s static
migration-chain checks pass; `scripts/check_no_secrets.py` finds no secrets
in 234 tracked files. A fresh `alembic upgrade head` from an empty SQLite
database applies the full `0001 → 0014` chain cleanly. `origin/main` remains
at `5bed586` (PR #25) — the Alembic chain remains unchanged:
`0011(main)→0012(main, PR #22)→0013(natural-key fix)→0014
(evidence-schema-version)`. Six files changed this round: the two code/test
files (`backend/src/hoops_gm/ingest/injury_report/backfill.py`,
`backend/tests/test_injury_report_backfill.py`) plus four docs-only files
(`docs/backlog.md`, `docs/governance/risks.md`,
`docs/adapters/nba-injury-report.md`, and this file) — no model, migration,
or route changes. (Corrected here after an independent code-review pass on
`6825f20` caught this file count itself understating its own scope — see the
review verdict recorded for this round.)

**Could not verify:** Whether a live Postgres instance is reachable in this
session — the same constraint as every prior round: Docker is not installed,
`TEST_DATABASE_URL` is unset, and no local Postgres service was available to
start, so only SQLite-backed unit tests and `test_portability.py`'s static
cross-dialect analysis ran locally; CI's dedicated Postgres job remains the
actual cross-dialect check of record. The new missing-tipoff-promotion
concurrency regression (point 1) does exercise a genuine two-session/
two-transaction race against a real file-backed SQLite database (the same
`database` fixture and `before_cursor_execute` engine-hook technique as
round 10's own concurrency regression), but this exact interleaving was not
independently re-exercised against a live Postgres connection this round.
No live NBA CDN probe was attempted this round — no code path touching the
live archive changed, and this round's fixes are entirely about local
persistence/classification correctness and docs wording, not transport.
Whether GitHub's merge-readiness check (CI green, CLEAN/MERGEABLE) reflects
this specific push is reported separately once observed after pushing, and
whether a further independent review finds anything beyond these five points
is likewise unverified until that review runs.

**Next:** Commit this round's three changed files, push to
`origin/sr2501-historical-injury-backfill`, monitor all GitHub CI jobs
(including the Postgres job) to green, confirm `mergeStateStatus: CLEAN`/
`mergeable: MERGEABLE` via `gh pr view`, commission a fresh independent
exact-head code review re-verifying these five fixes plus re-confirming
rounds 1-10 have not regressed, then report the new exact head/base and full
gate status to the coordinator. Still not merged, not self-approved;
`injury-status-conversion` remains explicitly blocked pending a genuinely
representative live-archive cohort and the separate, later Model-gated
deliverable.

## 2026-08-19 — data-engineer — Historical injury-report backfill: round-11 follow-up (two fixes)

A fresh coordinator evidence review of exact head `d0e045d` (round 11's
final, independently-reviewed head, CI green, `mergeable: MERGEABLE`,
`mergeStateStatus: CLEAN`) blocked release on two further findings — not new
runtime-correctness defects like rounds 1-11, but a genuine loader crash the
round-11 quarantine fix never actually exercised, plus a backlog structural
inconsistency the round-11 wording fix did not close.

**Now true:**

1. **`CoverageReport.from_json` no longer crashes on a realistic future
   schema version.** Round 11's fix (quarantining a non-current
   `evidence_schema_version` at `_persist_coverage`/classification) never
   actually protected the *loader itself*: `from_json` still built every
   raw candidate as `CandidateCoverage(**c)` — the entire dict, unpacked as
   keyword arguments — *before* ever inspecting its schema version. The
   original round-11 regression tests only ever bumped the version number
   on an otherwise-unchanged dict, so they never triggered this. A genuine
   future version — one that plausibly adds a field this code has never
   seen, which is the realistic shape a real future version would take —
   raised `TypeError: unexpected keyword argument`, crashing the *entire
   load* before quarantine logic ever ran. This took down both the
   `observations` CLI's read path and `_persist_coverage`'s own internal
   read of `existing` candidates (called on every persist, even one holding
   only current-scope evidence). A future version renaming or dropping a
   currently-required field (e.g. `report_date`, which has no default)
   crashed with a different `TypeError` (missing required positional
   argument) for the same underlying reason. Fixed by inspecting
   `evidence_schema_version` first, before any attempt to build the current
   shape: a non-current version is now routed to a new
   `_quarantined_incompatible_schema_candidate` placeholder that never
   interprets that record's other fields at all — not even
   opportunistically reading fields sharing a name with the current
   schema, since a future version could repurpose a field name entirely. A
   current-version record's own keys are now also filtered to a new
   `_CANDIDATE_COVERAGE_FIELD_NAMES` frozenset before construction, so a
   stray extra key on an otherwise-current record can never reach the
   constructor either. Five new regression tests added: two exercise
   `CoverageReport.from_json` directly with hand-built raw JSON (one with
   an added field, one with a renamed/dropped required field), two exercise
   the real `_persist_coverage` load+merge+save path with the same two
   variants, and one exercises the full `observations`-path chain
   (`CoverageReport.from_json` → `coverage_for_games`) with an added-field
   future record against a seeded game, proving no crash and that the
   quarantined record is never trusted for a `submitted_zero_listed` claim.
   `CURRENT_COVERAGE_SCHEMA_VERSION` remains 3 — no new coverage schema
   fields were added, so no migration was needed for this fix.
2. **`docs/backlog.md`'s dependency graph now agrees with its own prose.**
   Round 11's fix corrected the *wording* of the
   `injury-report-historical-backfill` entry, but never touched the
   *structural* dependency graph: `injury-status-conversion` listed exactly
   three dependencies (`injury-report-ingest`,
   `injury-report-historical-backfill`, `participation-ledger`), all three
   already marked `done`, so the backlog's own stated rule — "a task is
   ready when every dependency is done" — made it appear structurally
   ready despite the prose two paragraphs above saying the representative
   cohort it actually needs does not exist. Fixed by adding a new explicit
   backlog item, `injury-conversion-cohort-population` (not done; depends
   on `injury-report-historical-backfill` and `participation-ledger`;
   describes running the backfill tool at scale against the live archive to
   produce an actual multi-date, multi-game, evidence-reviewed cohort), and
   making `injury-status-conversion` depend on it too. The backlog's
   summary line is updated from "28 done - 1 blocked - 71 pending - 100
   total" to "28 done - 1 blocked - 72 pending - 101 total" — verified via
   direct heading/marker counts (`^### ` = 101, `[x] **done**` = 28,
   `[ ] **pending**` = 72, `[ ] **blocked**` = 1; 28+1+72=101, matching).

**Gates and CI:** `ruff check .` and `ruff format --check .` clean (126
files); `mypy .` clean (110 source files); the full local `pytest -q`
(default `-m 'not live_smoke'`) exits 0 with no failures, including all 111
tests in `test_injury_report_backfill.py` (106 → 111, the five new
regressions above); `pytest -m adapter_contract -q` and
`pytest tests/test_portability.py -q` both exit 0;
`scripts/check_no_secrets.py` finds no secrets in 234 tracked files. A fresh
`alembic upgrade head` from an empty SQLite database applies the full
`0001 → 0014` chain cleanly — unchanged, no migration needed this round.
`origin/main` remains at `5bed586` (PR #25); no rebase needed.

**Could not verify:** The same standing constraint as every prior round —
no live Postgres instance was reachable in this session (Docker not
installed, `TEST_DATABASE_URL` unset), so only SQLite-backed unit tests and
`test_portability.py`'s static cross-dialect analysis ran locally; CI's
dedicated Postgres job remains the actual cross-dialect check of record. No
live NBA CDN probe was attempted this round — no transport code changed;
this round is entirely loader-crash-safety and backlog-structure
correctness. Whether GitHub's merge-readiness check (CI green,
CLEAN/MERGEABLE) reflects this exact push, and whether a further independent
review finds anything beyond these two points, are both unverified until
observed after pushing and reviewing.

**Next:** Commit the two changed source/test files plus the three docs
files, push to `origin/sr2501-historical-injury-backfill`, monitor all
GitHub CI jobs (including the Postgres job) to green, confirm
`mergeStateStatus: CLEAN`/`mergeable: MERGEABLE` via `gh pr view`,
commission a fresh independent exact-head code review re-verifying both
fixes plus re-confirming rounds 1-11 have not regressed, then report the new
exact head/base to the coordinator. Still not merged, not self-approved;
`injury-status-conversion` remains explicitly blocked pending
`injury-conversion-cohort-population` and the separate, later Model-gated
deliverable.

## 2026-08-19 — data-engineer — Historical injury-report backfill: final-review follow-up (fail-closed key validation)

A final coordinator evidence review of exact head `e4559b6` (this session's
prior round, independently reviewed PASS, CI green, `mergeable:
MERGEABLE`) found one surgical release-blocking gap the prior fix left
open: the schema-version check alone was necessary but not sufficient to
trust a raw candidate record.

**Now true:**

`CoverageReport.from_json` no longer silently repairs a malformed
current-schema-claiming record. The prior round's fix correctly quarantines
any record whose `evidence_schema_version` is not exactly
`CURRENT_COVERAGE_SCHEMA_VERSION`, but a record that *does* claim the
current version was still trusted even when its actual keys did not match
the current dataclass contract, in two ways:

1. **An unknown key on a current-claiming record was silently dropped, not
   treated as evidence of contract drift.** The old loader filtered a raw
   dict's keys down to `known = {k: v for k, v in c.items() if k in
   _CANDIDATE_COVERAGE_FIELD_NAMES}` before construction — any key not in
   that set simply vanished, and the record was still constructed and
   trusted as clean current-schema evidence. This is a real gap
   independent of the future-schema-version scenario the prior round
   closed: a field added *without* bumping the version number (a
   plausible real mistake, not a hypothetical) or a corrupted/hand-edited
   record would sail through unnoticed, including the release-blocking
   combination of an unknown key alongside `outcome="fetched"` — the exact
   shape that proves `submitted_zero_listed` if trusted.
2. **A genuinely required field missing from a current-claiming record was
   silently defaulted, not rejected.** `applicable_nba_game_ids` has no
   default in the `CandidateCoverage` dataclass — the dataclass itself
   declares it required — but the old loader unconditionally defaulted a
   missing key to `()` via `c.get("applicable_nba_game_ids", ())`. A
   record genuinely missing its stable game identity (the exact field this
   whole schema exists to make durable — see round 7) was silently treated
   as if it validly named zero games, rather than being rejected as
   incomplete.

Fixed with a new `_current_schema_candidate_or_none` helper
(`backend/src/hoops_gm/ingest/injury_report/backfill.py`) that validates a
current-claiming record's raw key *set* before any construction is
attempted: every key present must be a recognized `CandidateCoverage` field
name (an unknown key now quarantines the whole record, it is never
silently dropped), and every field the dataclass declares with no default —
computed as a new `_CANDIDATE_COVERAGE_REQUIRED_FIELD_NAMES` frozenset via
`dataclasses.fields()`'s own `default`/`default_factory` metadata, not
hand-listed — must be present as a key (a missing required field now
quarantines too, it is never silently defaulted). Only a record passing
both checks is constructed; construction itself is still wrapped in a
narrow `try`/`except (TypeError, ValueError)` as a belt-and-suspenders
guard for a value-level surprise the key-set check would not catch (this
should be unreachable given the checks above, but quarantines rather than
crashes there too, for the same reason the prior round's fix did).
`CoverageReport.from_json`'s per-candidate loop now routes to this helper
only for the `evidence_schema_version == CURRENT_COVERAGE_SCHEMA_VERSION`
case; anything else still goes straight to
`_quarantined_incompatible_schema_candidate` as before.

Five new regression tests added to
`backend/tests/test_injury_report_backfill.py`, all using genuine on-disk
JSON (built from the existing `_serialized_candidate` helper, mutated) not
mocks: `test_from_json_quarantines_current_schema_with_unknown_key` and
`test_from_json_quarantines_current_schema_missing_required_field` exercise
`CoverageReport.from_json` directly;
`test_persist_coverage_quarantines_current_schema_with_unknown_key` and
`test_persist_coverage_quarantines_current_schema_missing_required_field`
exercise the real `_persist_coverage` load+merge+save path (writing actual
bytes to disk, reading them back);
`test_coverage_for_games_quarantines_current_schema_unknown_key_fetched_outcome`
exercises the full `observations`/`coverage_for_games` classification
chain with the release-blocking `outcome="fetched"` plus unknown-key
combination, asserting the game classifies as `no_candidate_coverage`, not
`submitted_zero_listed`.

**Gates and CI:** `ruff check .` and `ruff format --check .` clean (126
files, after one auto-format pass and fixing one Yoda-condition lint and
one over-length docstring line); `mypy .` clean (110 source files, after
removing one now-unused `type: ignore` comment); the full local `pytest -q`
(default `-m 'not live_smoke'`) exits 0 with no failures, including all 116
tests in `test_injury_report_backfill.py` (111 → 116, the five new
regressions above); `pytest -m adapter_contract -q` and
`pytest tests/test_portability.py -q` both exit 0;
`scripts/check_no_secrets.py` finds no secrets in 234 tracked files.
`CURRENT_COVERAGE_SCHEMA_VERSION` remains 3 — this fix is purely
loader-side key-set validation, not a new persisted shape, so no migration
was needed. `origin/main` remains at `5bed586` (PR #25); no rebase needed.

**Could not verify:** The same standing constraint as every prior round —
no live Postgres instance was reachable in this session (Docker not
installed, `TEST_DATABASE_URL` unset), so only SQLite-backed unit tests and
`test_portability.py`'s static cross-dialect analysis ran locally; CI's
dedicated Postgres job remains the actual cross-dialect check of record. No
live NBA CDN probe was attempted this round — no transport code changed;
this round is entirely loader key-set validation. Whether GitHub's
merge-readiness check (CI green, CLEAN/MERGEABLE) reflects this exact push,
and whether a further independent review finds anything beyond this one
point, are both unverified until observed after pushing and reviewing.

**Next:** Commit the two changed source/test files plus the three docs
files, push to `origin/sr2501-historical-injury-backfill`, monitor all
GitHub CI jobs (including the Postgres job) to green, confirm
`mergeStateStatus: CLEAN`/`mergeable: MERGEABLE` via `gh pr view`,
commission a fresh independent exact-head code review re-verifying this fix
plus re-confirming rounds 1-12 have not regressed, then report the new
exact head/base to the coordinator. Still not merged, not self-approved;
`injury-status-conversion` remains explicitly blocked pending
`injury-conversion-cohort-population` and the separate, later Model-gated
deliverable.

**Addendum (same night):** the exact-head report below reflects one further
commit, `70d942a`, on top of the fix described above (still exact head
`1e2fa87`'s production code — nothing in `backfill.py` changed again).
GitHub's real Postgres CI job caught something the local SQLite-backed
suite could not: the new end-to-end regression test used an `nba_game_id`
value 34 characters long against `NbaGame.nba_game_id`'s real
`VARCHAR(32)` column — SQLite does not enforce `VARCHAR` length at all, so
it passed locally, but Postgres correctly raised
`psycopg.errors.StringDataRightTruncation`. This is a test-fixture-only
defect (a test value picked without checking the column's real constraint,
not a production bug), fixed by shortening the value to 19 characters;
re-run confirmed green against Postgres in CI. This is exactly the kind of
gap ADR-001's dedicated Postgres CI job exists to catch, and it did.

## 2026-08-19 — data-engineer, backend — Historical injury-report backfill: round-14 release blockers

**Changed:** Closed two confirmed release blockers without widening the
backfill. `_persist_coverage` no longer drops incompatible existing candidates
and atomically replaces their artifact: legacy/missing-version, future-version
(including added/renamed fields), and malformed-current (unknown/missing
required keys) raw candidates now raise typed
`IncompatibleCoverageEvidence` before a temporary file is created. Observation
loading remains read-only and may quarantine those candidates for
classification. `InjuryReportEntry.import_schema_version` now defaults to
`LEGACY_EVIDENCE_SCHEMA_VERSION` in both SQLAlchemy metadata and unmerged
migration `0014`; only `import_injury_report_entries` explicitly writes
`CURRENT_EVIDENCE_SCHEMA_VERSION` on every validated insert/update. Added
real-file byte-preservation/no-temp/no-trusted-evidence tests for all six
incompatible shapes, direct ORM and raw-SQL omitted-default tests, importer
current-version coverage, canonical exclusion, and an upgrade-from-`0013` /
downgrade / re-upgrade migration test that runs under both the local SQLite
suite and GitHub's Postgres-configured suite.

**Now true:** Existing incompatible coverage evidence is never silently
destroyed by a running binary that cannot interpret it. Operator recovery is
explicit and manual: preserve or move the artifact to quarantine, inspect it
with a compatible binary (or retain it for a future explicit migration), then
retry against a separate compatible coverage file; this change does not invent
an automated migration. Omitted direct/ORM/raw injury-report inserts are
legacy/untrusted and excluded from canonical selection, while a genuine
validated re-import still promotes the exact reconciled row to current. The
Alembic chain remains single-head `0012 -> 0013 -> 0014`, with `0014`
backfilling existing `0013` rows to legacy and using legacy as its server
default. Local Code and Adapter gates are green: Ruff check, Ruff format check
(126 files), bare mypy (110 source files), full pytest, adapter-contract tests,
secret scan (234 tracked files), and a fresh SQLite `upgrade head -> alembic
check -> downgrade base` lifecycle all passed.

**Could not verify:** GitHub Actions, including the real Postgres suite, had
not run against this exact remediation head when this entry was written.
Independent exact-head code and data/evidence reviews had not yet been
commissioned. No live NBA archive call was repeated because transport and
candidate derivation did not change; the standing uncertainty remains whether
the bounded candidate schedule reaches every off-cadence archive report.

**Next:** Commit and push the remediation, require GitHub's Postgres and all
other checks to pass, obtain fresh independent exact-head code and
data/evidence reviews, and resolve every finding before conversion. Do not
merge or self-approve. `injury-status-conversion` remains explicitly blocked
on `injury-conversion-cohort-population` and its separate Model gate.

**Review addendum:** Independent code and data/evidence reviews of exact head
`084cef4` found one release blocker and one adjacent fail-closed defect. A
current-v3 candidate could omit its `season`/`season_type` keys because those
fields have placeholder-oriented dataclass defaults; it passed the initial
malformed-current gate, defaulted to empty scope, and was then silently dropped
by the per-candidate scope filter during atomic rewrite. A current candidate
with explicitly disagreeing scope followed the same destructive filter.
Fixed by making v3 scope keys contractually required on disk and by raising
`CoverageScopeMismatch` for any per-candidate scope disagreement before write;
tests assert bytes unchanged and no temp residue. The code review also found
that a quarantined placeholder's intentionally empty `report_date` made
date-ranged `exclusion_cascade` rendering raise `ValueError`; malformed dates
are now excluded from that read-only range aggregate, with a regression test.
Both findings were resolved before push; a fresh exact-head review is still
required after the follow-up commit.

**Round-14 finalization addendum (rebased onto `6c405ef`):** Rebased the
complete append-only history onto PR #26's exact squash commit
`6c405ef81e2828de390f7dda56489b62f8b21143`; `docs/backlog.md` was reconciled
mechanically to `31 done - 1 blocked - 69 pending - 101 total`. A second
exact-head review cycle found no release blocker. Its two code observations
were resolved: the exclusion cascade now exposes date-unassignable
quarantined coverage candidates as a separate stage 5b rather than silently
shrinking stages 5-8, and the `NOT_YET_SUBMITTED` canonical-selection fixture
explicitly declares current trusted provenance. A subsequent independent
data/evidence review found one medium read-path inconsistency: a non-object
JSON candidate failed loud with `AttributeError` in `CoverageReport.from_json`
instead of becoming an inert quarantine placeholder. The loader now
quarantines that shape too; the real persistence path still raises typed
`IncompatibleCoverageEvidence` before write, and regression tests prove bytes
unchanged, no temporary residue, and no trusted evidence.

**Now true (final local gate):** Ruff check and format check passed for 126
files; bare mypy passed for 110 source files; full pytest passed with 798 tests
and 17 live-smoke tests deselected; the Adapter gate passed with 235 recorded-
fixture contract tests; the secret scan passed over 235 tracked files; and a
fresh SQLite `upgrade head -> alembic check -> downgrade base` lifecycle
passed through the single `0012 -> 0013 -> 0014` tail. Migration `0014`
continues to backfill and default omitted evidence provenance to legacy (`1`);
only the validated importer writes current (`2`).

**Could not verify:** This local host has no real Postgres service. GitHub's
Postgres migration lifecycle and full suite had not run against the final
post-review head when this addendum was written. A fresh independent code and
data/evidence review is still required after the final documentation commit.
No live archive request was repeated because transport and scheduling did not
change; the standing live uncertainty remains whether bounded candidate
scheduling reaches every off-cadence NBA archive report.

**Conversion block:** Do not merge or self-approve this PR.
`injury-status-conversion` remains explicitly blocked on
`injury-conversion-cohort-population` and its separate Model gate, even after
this backfill PR is green.

---

## 2026-08-19 — backend — Authoritative scoring-period projection

**Changed:** Implemented `scoring-period-projection` without a schema change or
an Alembic revision. Added `calendar/scoring_periods.py` as the sole production
writer for `ScoringPeriod`: it locks and validates the current league-settings,
active `LeagueDeadlineCalendar`, keyed NBA schedule, and league projection
scopes; converts authoritative boundaries to `America/New_York` before
extracting inclusive dates; refuses unknown playoff flags; and fingerprints the
exact settings snapshot, calendar, schedule refresh, and projected rows into a
league-scoped `refresh_runs` stream. Unchanged reruns preserve row identities.
Changed projections lock the existing parent rows and replace the complete
current materialization only when no `Matchup` references it; otherwise they
fail closed rather than let an existing or concurrent matchup be
cascade-deleted. Prior immutable calendars and refresh summaries retain the
content and lineage of every replaced version. Added the explicit
`scoring-periods` operator command, with an opt-in `--derive-and-activate` path.

`scheduled_game_counts` and `playoff_scheduled_game_counts` now require current
projection lineage before querying and return the schedule refresh, projection
refresh, deadline calendar, and settings snapshot identifiers and versions on
every row. They reject manual row mutation, stale settings or NBA schedule
lineage, and a mismatched projection refresh. Introducing a second keyed
schedule-type stream exposed two older type-only refresh lookups; deadline
calendar and absence-split selection now explicitly request `nba-schedule`
instead of accidentally accepting the newest scoring-period stream.

**Now true:** A playoff count cannot claim freshness from NBA schedule lineage
alone. Changing authoritative period boundaries or playoff evidence makes the
materialization unreadable until the active calendar is re-projected. Unknown
playoff evidence never becomes `False`, replacement history remains
reconstructable, and all official writers/readers share transaction locks in a
consistent settings -> NBA schedule -> league projection order. The full local
backend Code gate passes (`ruff check`, format check, strict `mypy`, 812 tests
with 17 live-smoke tests deselected), all 237 recorded-fixture Adapter contract
tests pass, the SQLite upgrade/check/downgrade lifecycle through migration
`0014` reports no model drift, and the secret scan is clean.

**Could not verify:** The observed official Fantrax league-settings payload has
no playoff markers, and no authoritative bridge capture supplying the 2026-27
playoff periods was available, so no real league projection was run; projection
correctly remains blocked on that missing evidence. Matchup-reference conflicts,
DST/date-boundary behavior, and stale-lineage paths were verified with
deterministic database fixtures rather than live league data. Native Postgres
was not configured locally; the GitHub Postgres job remains the cross-dialect
execution check of record.

**Next:** After authoritative 2026-27 playoff evidence is ingested, derive and
activate the current deadline calendar and run the `scoring-periods` operator
command. Repeat that projection after settings or NBA schedule lineage changes;
downstream count consumers will fail closed until it succeeds. Recursive
SOS/projection convergence and weekly scheduling remain separate ADR-011/012
work owned by `quant` and `data-engineer`.
---

## 2026-08-19 — quant — Descriptive reliability scorecards and rejected suppression candidate

**Changed:** Implemented `reliability-metrics` without schema, migration, API, UI,
projection, or market dependencies. After rebasing onto `c6a6912`, the unit does
not consume the historical injury cohort introduced by merged PR #21. The new
in-memory scorecard publishes and rechecks exact schedule/source/derivation
cohorts, then reports direct
observed participation evidence separately from played-game production
consistency. Availability evidence includes direct play/non-play/unknown counts,
calendar-month observations, B2B observations derived from the historical
team/game schedule row, source-row IDs, and mandatory
`coverage_status=incomplete_r35`; missing and unknown rows never become
absences. Production reports sample-based minutes CV, per-category sample SD,
Type-7 empirical p20/p80, and volume-weighted FG/FT impact against a
same-window aggregate makes/attempts baseline. DNPs never become zero-production
games. No composite grade, rank, value, projection, recommendation, or runtime
blowout-suppression field exists.

Added a reproducible chronological evidence runner and checked artifact using
2023-24 -> 2024-25 for selection and 2024-25 -> 2025-26 for final held-out
evaluation. The production-consistency statistics have measurable adjacent-year
stability: final-transition minutes CV Spearman is 0.729 and its player-specific
MAE is 0.124 versus 0.149 for the league-median baseline; every tested category
SD also beats its league-median MAE baseline. Held-out p20/p80 coverage is
reported overall and by declared sample-size band across every adjacent-season
player, including 55 final-transition players in the 1-19 band; sparse and
discrete outputs are explicitly not described as calibrated intervals.

The first independent exact-head quant review blocked release on four
falsifiable issues. The corrected implementation now shares category
definitions, sample SD, Type-7 quantiles, and volume-impact math between runtime
and evidence; literal-locks and fingerprints the complete evidence protocol;
binds the artifact to the runtime derivation version; exercises the evidence
runner end to end against parsed synthetic source contracts; tests known answers
for every statistical helper; evaluates rather than empties the sparse band;
checks source game-ID coverage in both directions; and fingerprints percentile
configuration with lossless `float.hex()` values rather than collision-prone
eight-decimal rendering.

**Now true:** Player-specific blowout suppression is rejected despite lower
average error. On 351 selection players, candidate MAE is 2.646 versus 2.947 for
zero effect, but the player-block bootstrap 95% improvement interval is -0.006
to 0.577. On 346 final-holdout players, MAE is 2.426 versus 2.910 and the interval
is 0.203 to 0.739. Both transitions nevertheless reverse sign in the highest
predicted-delta calibration bin: players predicted to gain minutes in blowouts
had a negative observed mean delta. The predeclared calibration veto therefore
keeps the field out of runtime. Availability/B2B calibration is not reported
because the complete non-appearance labels R35 requires still do not exist. The
full boundary, evidence, blind spots, and reproduction command are in
`docs/models/reliability-metrics.md`.

The coordinator approved the protocol before the successful outcome run, but
the protocol and evidence first enter git together. The artifact therefore
states `immutable_repository_preregistration=false`: the repository cannot
independently prove prospective registration, and this is described as
chronological held-out evidence under a predeclared plan rather than an
immutably preregistered experiment.

The local Code, Adapter, and Model gates pass after rebasing onto exact
`origin/main` `c6a6912a8aad3b16b42993596f5f17714891d820`, with this worktree's
`backend/src` explicitly on `PYTHONPATH`: Ruff, format, strict mypy, 836 default
backend tests, 237 recorded-fixture adapter-contract tests, 16 `model_backtest`
tests, the secret scan, and SQLite upgrade/check/downgrade through current head
`0014`. This unit adds no migration. The live evidence run completed against
existing `LeagueGameFinder` and `PlayerGameLogs` adapters.

**Could not verify:** Full availability, B2B opportunity coverage, or
availability calibration. The ledger still lacks authoritative historical
roster intervals and per-game ingestion-completeness evidence, so long absences
represented by silence remain invisible. No real 2026-27 outcomes, native
Postgres run, or downstream API/UI consumer was available.

The live source audit also found an adapter-owned cohort defect that this quant
unit does not hide or repair: `PlayerGameLogs` contains 1,230 game IDs in both
2024-25 and 2025-26, while the existing `LeagueGameFinder` parser produces only
1,225 paired games in each season. Five game IDs per season do not yield a
two-sided home/away record under the parser's reciprocal-matchup assumption.
The evidence fingerprints every player-log-only and parsed-game-only ID,
excludes 118 player logs in 2024-25 and 102 in 2025-26, retains 99.59% of
player-log game IDs and 100% of parsed game IDs, and fails if either mismatch
direction exceeds 1%. These games may be systematically unusual rather than
random. The existing schedule-context evidence also reports 1,225 games from
this parser and should be audited after the adapter is corrected; this entry
does not claim how much that omission changes its calibration.

Local Python is 3.14 and has the previously documented stale editable install,
so validation explicitly used this worktree's `backend/src` and suppressed only
the known Python-3.14 `pytest-asyncio` deprecation that CI's Python 3.12 does not
emit. GitHub Actions remains the Python 3.12 and Postgres verification.

**Next:** `data-engineer` should repair the reciprocal-matchup parser with a
recorded anomalous fixture and contract test, then regenerate affected model
evidence under new source fingerprints. Before this independent PR merges, a
fresh quant reviewer must inspect its exact head; downstream consumers must keep
observed participation, production consistency, and future availability/value
models separate.
---

## 2026-08-19 — architect — Projection experiment sequestration protocol

**Changed:** Recorded the owner's explicit 2026-08-19 decision as the focused
[`projection experiment sequestration protocol`](governance/projection-experiment-protocol.md).
It adopts only five rules: model workers have no direct source access; a
data-engineer custodian prepares packages and an independent quant releases
them; packages are immutable and timestamped; experiment plans freeze before
outcomes are unblinded; and mock outcomes never enter production or
availability. The protocol defines the three separated responsibilities, the
minimal package manifest and digest identity, freeze/unblind records, required
audit evidence, and fail-closed violations. The preserved 387-line local draft
was not ported, summarized, or ratified. This is not an ADR, does not amend
ADR-006, and does not expand the Model gate or source/ToS policy.

**Now true:** The model-document index links the protocol, and the pending
`baseline-model` backlog task requires projection experiments to follow it.
Implementers can identify the exact package, freeze, release, and unblind
evidence needed without adopting new isolation infrastructure or another
project-wide gate.

**Could not verify:** No projection experiment has yet exercised the package,
freeze, or unblind records, so their first real use may expose a missing
operational detail. This documentation cannot prove role separation or source
non-access by itself; the named audit records make those claims reviewable but
do not add technical enforcement. No source data, paid service, Fantrax access,
or mock outcome was inspected.

**Next:** `data-engineer` and an independent `quant` should exercise the
protocol when `baseline-model` begins; the model worker must stop rather than
accept an unmanifested package or an outcome released before its freeze.

---

## 2026-08-19 — data-engineer — Representative injury-conversion cohort population

**Changed:** Populated the pending `injury-conversion-cohort-population`
evidence from the official 2025-26 NBA sources without fitting a model. A
read-only `LeagueGameFinder` preflight selected `2025-12-08..2026-01-04`, an
inclusive four-week window centered on the independently established
2025-12-22 archive cadence/filename boundary, before any per-game or PDF sweep.
That scope contains 171 parsed official games on 25 game dates, all 30 teams,
12 legacy-era dates, 13 fifteen-minute-era dates, and none of the five known
2025-26 player-log-only `LeagueGameFinder` anomaly ids. The existing season
participation command could only fetch a whole season or its first N games, so
the smallest blocking operator fix adds inclusive `--start`/`--end` bounds
(with inverted-range and negative/zero-limit tests) while leaving schedule and
production ingest season-wide and separate from availability.

The operational sequence, run with `PYTHONPATH` set to this worktree's
`backend/src` and `DATABASE_URL=sqlite:///./.live_evidence_cohort/cohort.db`,
was:

```powershell
python -m alembic upgrade head

# One-time NBA anchor bootstrap used only official NBA identity:
# NbaStatsClient.static_teams() -> parse_teams/import_teams, then
# CommonAllPlayers(season="2025-26", only_current=False) ->
# parse_common_all_players/import_nba_players.

python -m hoops_gm.ingest.backfill season 2025-26 --with-participation `
  --start 2025-12-08 --end 2026-01-04

python -m hoops_gm.ingest.injury_report.backfill plan 2025-26 `
  --start 2025-12-08 --end 2026-01-04 --max-requests 100

python -m hoops_gm.ingest.injury_report.backfill run 2025-26 `
  --start 2025-12-08 --end 2026-01-04 --max-requests 100

python -m hoops_gm.ingest.injury_report.backfill observations 2025-26 `
  --start 2025-12-08 --end 2026-01-04
```

The identity bootstrap created 30 teams and 5,206 NBA-anchored canonical
players. The bounded participation run imported 1,225 season schedule rows,
26,549 production rows (102 known player-log rows skipped because their five
game ids are absent from the defensive two-sided schedule parser), and 5,980
participation rows for the selected 171 games. It had zero per-game source
failures. The injury plan had 89 candidates under the explicit budget of 100.
All 89 completed with zero 403, 404, or contract failures; legacy URL
coalescence produced 84 distinct fetched captures/mastheads. The run created
9,250 injury rows and reconciled 694 rows through the natural key. An immediate
resume processed zero candidates, skipped all 89 as settled, and imported
nothing.

**Now true:** Every one of the 171 expected games is ingested with an exact
tip-off and has a canonical pregame observation. The trusted cascade is 9,082
in-scope rows -> 9,082 game-resolved -> 8,190 player-resolved, with 783
`NOT_YET_SUBMITTED` rows and 8,299 listed-status rows. The canonical surface is
1,934 player-games: 1,907 resolve to canonical player ids and 27 remain
unresolved. Joining only by local `(game_id, player_id)`, then proving those
links through stable NBA `nba_game_id` plus NBA-source player external id,
yields 1,906 authoritative outcomes: 291 played, 72 did not play, 125 did not
dress, 10 were not with team, and 1,408 were inactive. The one remaining
resolved `OUT` observation (`0022500491` / NBA player `1641890`) has no
participation row and stays unknown; silence is not converted into an absence.
All five report statuses are present (`OUT` 1,495; `AVAILABLE` 206;
`QUESTIONABLE` 152; `PROBABLE` 59; `DOUBTFUL` 22). Source-observed,
same-window BoxScoreTraditionalV3 labels establish G/F/C diversity for 167 of
363 resolved players; 196 players with no nonempty label remain position-
unknown rather than inferred.

The repository-safe evidence is
`docs/adapters/nba-injury-report-cohort-2025-12-08--2026-01-04.json`. It records
capture timestamps, source/artifact SHA-256 identities, exact scope and
commands, cascade counts, unresolved identities, stable-key join fingerprints,
position evidence, and status-diverse stable-key samples. The sorted canonical
fingerprint is
`9fe70210367d229f711b34bc5b99d779534172fd0e218a335ce67f79d406765d`;
the sorted joined-outcome fingerprint is
`b4dbf93d6b9163bb4370def1a1d425ae800d50da543fa6568170d1ee486ad27b`.
Raw NBA PDFs/JSON, checkpoint, coverage, expected-game evidence, and SQLite
state remain gitignored and were not redistributed.

**Could not verify:** The first independent exact-head data/evidence and code
reviews had not run when this entry was written, so the backlog item remains
pending until they approve representativeness and the bounded-loader change.
The one R35-silent resolved observation cannot be classified without
authoritative historical roster/completeness evidence. Position labels are
available only when BoxScoreTraditionalV3 emitted a nonempty value in this
window; blank labels remain unknown. No live Postgres service was available
locally. No DNP reason was inferred, no conversion rate or probability was
computed, no paid source or Fantrax access was used, and no owner-only decision
was made.

**Next:** Obtain independent exact-head data/evidence and code reviews. If both
pass, mark `injury-conversion-cohort-population` done; then `quant` may begin
the separately Model-gated `injury-status-conversion` work from this frozen
observation cohort.

---

## 2026-08-19 — independent review addendum — Injury cohort accepted

**Reviewed:** Independent data-engineering/evidence and code reviews examined
exact commit `4e89cc5f59c31656508183a2939a82d03a92ec1a` against exact base
`9c4ebac9a4a937594fb6ce18256d5269fe5dee93`. Code review found no actionable
correctness, security or integration issue. The evidence reviewer approved the
cohort as representative enough to unblock the separately Model-gated
`injury-status-conversion` task.

The evidence review independently queried the gitignored database rather than
accepting the manifest claims. It reproduced the 171-game/25-date/all-team
scope, 5,980 bounded participation rows, season-wide 1,225 schedule and 26,549
production rows, trusted-entry cascade arithmetic, canonical status arithmetic,
1,906 joined outcomes, NBA-only identity anchors, empty Fantrax/write-path
tables, and every committed source/artifact hash it checked. It also confirmed
that the 2025-12-22 boundary pre-dated cohort selection and that the one R35
gap remained unknown.

**Now true:** `injury-conversion-cohort-population` is done in
`docs/backlog.md`. This closes only the observation-layer data/evidence task; it
does not approve a conversion rate, probability, availability model, or any
production/availability fusion.

**Could not verify:** The independent reviewer did not repeat the live resume
request because that would re-hit the hostile external source; it reviewed the
settled checkpoint design and recorded zero-import/89-skip transcript instead.
The raw-entry/canonical distinct-player counts differ by one across resolution
layers; downstream cohort identity is the canonical 363-player NBA-id surface,
and no rate should consume raw-entry distinct counts. Local Postgres remained
unavailable; CI is still the Postgres gate.

**Next:** `quant` may consume the frozen cohort under the Model gate, preserving
the unresolved identities, the R35 unknown, and blank source positions as
missing evidence rather than negative outcomes.

---

## 2026-08-19 — review correction — Canonical source fingerprints

**Changed:** Final exact-head code review found that the manifest's two source
fingerprints were SHA-256 values of the Windows working-tree files after
`core.autocrlf=true` had materialized CRLF line endings. They were reproducible
on this checkout but were not canonical identities of the code committed at
the reviewed head. The manifest now names and hashes the Git blob bytes for
`backend/src/hoops_gm/ingest/backfill.py` and
`backend/tests/test_backfill.py` at
`4e89cc5f59c31656508183a2939a82d03a92ec1a`, using binary output from
`git cat-file blob`:

```text
backfill.py      cb1e1c165781ab3a0fcd18c5d60338b5d6fb29d9fdcf150e4d32a541b4d0f7d3
test_backfill.py 74683ea889640855ecb2c3e0ea74c363dd5c307a12eb9a91a6613bf459f46a5a
```

**Now true:** The source fingerprints are invariant across checkout newline
configuration and operating system. The preceding review addendum's phrase
"every committed source/artifact hash it checked" was too broad: the first
review reproduced the checked-out working-tree source hashes and operational
artifact hashes, while the final code review distinguished those source bytes
from the canonical committed blobs. The operational capture/artifact hashes,
cohort fingerprints, counts and backlog status are unchanged.

**Could not verify:** No additional live source request was made for this
metadata-only correction. The correction does not make the uncommitted raw
captures independently downloadable; their provenance remains verifiable only
where the retained gitignored operational state is available.

**Next:** Repeat independent exact-head data/evidence and code review after this
correction; do not publish the branch until both approve the canonical
fingerprint semantics.

---

## 2026-08-18 — data-engineer — PR #12 projection-importer integration repair

**Changed:** Rebased the generic projection CSV importer onto `origin/main`
through `8fb26a7`, preserving PR #9's refresh registry and Postgres fixture
isolation, PR #10's userscript update path, PR #16's autonomous-delivery policy
and accepted ADR-008, and PR #7's schedule-density handoff. Advanced the
importer migration from the conflicting revision `0005` to the single-head
revision `0006` after refresh lineage. Tightened projection-import identity from
`(source_id, content_sha256)` to `(source_id, season, content_sha256)`: a CSV
often does not carry its season in its bytes, so reusing identical content for
a later season previously returned the earlier import and stamped new rows with
the wrong season. Added end-to-end tests proving that cross-season imports stay
distinct and that two indistinguishable canonical players produce a
`needs_review` result with no projection or crosswalk write.

Diagnosed rather than assumed the old Postgres failures. Both red PR #12 jobs
failed only because `client`-fixture rows leaked between tests on the shared
Postgres database (`xhr` was read instead of the just-written `cache-storage` or
`manual-export` row). The rebased PR #9 `drop_all`/`create_all` isolation fixes
that mechanism. On the final rebased head, both native Postgres jobs passed,
including migrations from empty, `alembic check`, downgrade, and the full test
suite.

**Now true:** The importer has one migration head, remains reusable across its
four source profiles, and preserves source/season/content lineage without
collapsing seasons. ADR-002 and accepted ADR-008 remain structural:
`projections` contains per-game production rates only; source games-played
assumptions remain in their own one-to-one table. The independent review later
proved the prior claim that terminal values were excluded was false because
the complete source row, including Rank/AAV/composite/expected-games columns,
was still persisted as `Projection.raw_row`; the focused remediation entry
below records its removal. Ambiguous
identities are reported for human adjudication and never guessed. Local gates
passed Ruff, formatting, strict mypy, 460 default backend tests, 71 offline
adapter-contract tests, SQLite upgrade/check/downgrade, the secret scan,
frontend lint/type-check/12 tests/build, and userscript 63 tests/build. The
final GitHub runs `32141211883` and `32141218621` were green across every
configured blocking job, including native Postgres, but that green Adapter job
was success-shaped evidence: synthetic vendor examples were incorrectly marked
`adapter_contract` and did not satisfy the projection Adapter gate.

**Could not verify:** The FantasyPros, Hashtag and Basketball Monster mappings
still have only synthetic, non-published fixtures because the real exports are
authenticated or paid; their exact live header aliases remain unverified. The
manual canonical profile is the only verified import shape. No
projection-specific live smoke exists, and CI correctly skipped the repository's
network live-smoke job on this PR event. Docker/Postgres is unavailable on this
machine, so native Postgres evidence comes from CI rather than a local service.
No independent reviewer has approved PR #12 yet; green gates do not satisfy the
repository's autonomous-delivery policy by themselves.

**Next:** An independent reviewer should verify the layer boundary, identity
fail-closed behavior, and migration/lineage integration before merge. The first
real vendor CSV must be checked manually against `resolved_headers` and captured
as a privacy-safe contract fixture before its vendor profile is treated as
verified.

---

## 2026-08-18 — data-engineer — PR #12 independent-review remediation

**Changed:** Reworked projection imports so reprocessing atomically reconciles
all import-owned projections and source games-played assumptions to the current
identity resolution. Accepted-to-ambiguous, accepted-to-unmatched, and
player-A-to-player-B transitions now remove stale outputs rather than retaining
plausible rows under an obsolete identity. Import identity now hashes the exact
original bytes before an explicit UTF-8/UTF-8-BOM decode; byte-distinct BOM and
newline forms remain distinct imports, while unsupported encodings fail before
any database write. Parser profiles now enforce production schema signatures,
reject duplicate normalized headers, all-null rows/files, non-finite numbers,
and profile/source misattribution. Source/import creation recovers from a
uniqueness conflict through a savepoint and reselect so concurrent identical
imports converge. Synthetic vendor examples no longer carry
`adapter_contract` markers or claims.

Closed the accepted ADR-008 boundary in both schema and configuration:
`Projection.raw_row` was removed from the ORM and migration, and custom profiles
cannot map Rank, AAV, tier, composite/fantasy value, or expected-games aliases
into identity, source GP, production, or percentage-fallback fields. These
headers can only appear as ignored transient parse evidence. Exact source bytes
belong at the raw-import/observation boundary: `ProjectionImport.content_sha256`
addresses them and `ProjectionImport.raw_payload_ref` may point to durable raw
storage; neither source bytes nor complete source rows are attached to a
projection-layer quantity. `ProjectionSourceRow.raw_row` is transient
adjudication evidence only.

**Now true:** On head `10a3c04` plus the final profile-boundary correction,
latest import output exactly equals latest accepted resolution, ambiguous
players are never guessed, and stale automated crosswalk state cannot force a
prior identity. Per-game production remains in `projections`; source-published
games-played assumptions remain in the separate one-to-one
`source_games_played_assumptions` table and are not fused into production.
Terminal aggregates cannot enter either layer through a custom profile. Local
Code-gate evidence is Ruff, formatting, strict mypy, 485 backend tests with 12
live-smoke tests deselected, SQLite upgrade/check/downgrade, and the secret
scan. GitHub runs `32144985211` and `32144991395` passed every configured
blocking job, including both native Postgres migration/full-suite jobs. A
focused read-only review verified the eight reported importer fixes; the
subsequent ADR purity challenge found the custom-profile loophole described
above, which is now covered by construction-time rejection regressions.

**Could not verify:** The projection Adapter gate remains unmet. FantasyPros,
Hashtag, and Basketball Monster fixtures are synthetic unit examples, not
privacy-safe fixtures derived from real exports; therefore their live header
aliases and source behavior remain unverified even though the repository's
other recorded-fixture adapter tests pass. No projection-specific live smoke
exists. Native Postgres evidence comes from GitHub CI because no local Postgres
service was available. No independent reviewer has reviewed the final
custom-profile correction or approved PR #12, and no claim of merge readiness
supersedes that review.

**Next:** Run the full Code and configured Adapter CI once more on the final
commit, then give its head to an independent reviewer for focused verification
of exact-output reconciliation, custom-profile ADR-008 enforcement, identity
fail-closed behavior, and SQLite/Postgres parity. Keep `csv-importer` blocked
until the first real vendor export is manually checked against
`resolved_headers`, reduced to a privacy-safe recorded fixture, and paired with
an offline contract test plus a loud live-smoke path.

---

## 2026-08-18 — data-engineer — PR #12 ADR-002/ADR-008 purity repair

**Changed:** Rebased PR #12 onto `origin/main` through `2369d8f`, preserving
absence-split revisions `0006`/`0007`, league-settings revision `0008`, and all
append-only handoff entries. The importer migration is now the single-head
revision `0009` after `0008`. Closed the four additional purity findings and
the adversarial bypasses discovered while testing them:

- Production imports now accept only the exact profile object in the immutable
  committed profile registry. Source units have no default, profile ID/version
  and exact season evidence are mandatory, and unverified FantasyPros,
  Hashtag, and Basketball Monster profiles are parse-preview examples only.
  Caller-created profiles cannot self-attest into production, and CSV profiles
  are restricted in code and by database CHECK to the isolated projection
  provider namespaces; NBA and Fantrax identity anchors are not representable
  as projection sources.
- `projection_profile_versions` stores one race-safe immutable definition per
  source/profile/version. Each `projection_imports` row records the profile
  identity, verified status, definition hash, resolved production and
  percentage-observation headers, source/output units, and every field
  transform. Reusing an identifier/version with changed aliases, units,
  evidence, or transforms fails even when the CSV bytes differ; a deliberate
  version bump preserves both interpretations.
- Projection writes use `resolution.best.target` through its NBA anchor
  directly, never a re-derived source crosswalk. A conflicting manual mapping
  demotes an inferred accepted match to review with no projection. A current
  manual alias can promote an otherwise unresolved source name, and a manual
  incumbent under another alias remains final without blocking the accepted
  projection or creating a second current crosswalk row.
- FG% and FT% are usable only with complete makes-and-attempts volume. The
  parser excludes incomplete pairs, records percentage-only exclusion in
  lineage, and ORM/migration CHECK constraints reject partial FG/FT pairs even
  through a direct database write.
- Reconciliation is private to the byte-oriented verified entry point.
  Imports hold a source-scoped process lock through transaction end for
  SQLite and a `FOR UPDATE` source lock for Postgres, so identical and distinct
  concurrent files converge without racing the shared source crosswalk.

**Now true:** The raw-evidence boundary remains the import/observation layer:
`ProjectionImport.content_sha256` addresses the exact original bytes and
`raw_payload_ref` may point to durable private raw storage; full rows and
terminal Rank/AAV/tier/composite/expected-games values do not persist on
`Projection`. `ProjectionSourceRow.raw_row` remains transient adjudication
evidence. Per-game production remains separate from
`source_games_played_assumptions`; no availability or expected-games quantity
is fused here. Latest outputs exactly match current accepted resolutions, and
ambiguous/conflicting identities produce review output rather than guessed
players. Local Code/Adapter evidence on the rebased tree is Ruff, formatting,
strict mypy, 552 default backend tests, 75 existing real-derived adapter
contracts, SQLite upgrade/check/downgrade through `0009`, and the secret scan.
Focused independent defect reviews found and drove each bypass above; the last
code review found no remaining code issue beyond publishing the rebased head.

**Could not verify:** The projection Adapter gate is still explicitly unmet.
No privacy-safe fixture derived from a real FantasyPros, Hashtag, or Basketball
Monster export exists, so none of those profiles is production-enabled and no
claim is made about its live headers or units. No projection-specific live
smoke exists. A local Postgres service was unavailable; native Postgres
migration, constraint, concurrency, and full-suite evidence must come from
fresh GitHub CI on the rebased head. The process lock covers the project's
single-process SQLite deployment; cross-process serialization is provided only
by Postgres row locking. No reviewer has approved the final published head, and
this entry is not merge approval.

**Next:** Force-with-lease the rebased branch, require every configured blocking
job including both native Postgres runs to pass, then give the exact head to an
independent reviewer. Keep `csv-importer` blocked until a real vendor export is
manually verified, reduced to privacy-safe evidence, committed as an offline
contract fixture, and paired with a loud live-smoke path.

---

## 2026-08-18 — data-engineer — PR #12 restacked after injury-report ingestion

**Changed:** Restacked the repaired projection importer onto `origin/main` at
`875d40e`, which includes PR #13's injury-report ingestion and append-only
handoff entries. Renumbered the projection importer migration from the
now-occupied `0009` to the single-head `0010`, revising PR #13's injury-report
`0009`. No importer boundary or migration object was dropped during the
restack.

**Now true:** The combined tree passes Ruff, formatting, strict mypy, all 584
default backend tests, all 106 configured real-derived Adapter contract tests,
SQLite upgrade/check/downgrade through `0010`, and the tracked-file secret
scan. The importer still stores exact-byte identity and optional private raw
payload reference at the import/observation boundary, immutable verified
profile and transformation lineage at the import boundary, per-game production
on projections, and source games-played assumptions separately. Terminal
values remain excluded, and ambiguous or conflicting identities remain
review-only.

**Could not verify:** No local Postgres service was available, so native
Postgres migration, constraints, concurrency, and full-suite behavior require
fresh CI on the published restacked head. The projection-specific Adapter gate
remains unmet: the built-in vendor profiles are unverified preview examples,
and no privacy-safe fixture derived from a real vendor export or corresponding
live-smoke path exists. This entry is neither merge approval nor self-approval.

**Next:** Publish the restacked head with force-with-lease, require both native
Postgres jobs and every other blocking job to pass, then submit that exact head
for independent focused review. Keep `csv-importer` blocked until real-derived
privacy-safe vendor evidence satisfies the projection Adapter gate.

---

## 2026-08-17 — quant — `csv-importer`: the generic projection CSV import boundary

**Changed:** Built the Phase 5 `csv-importer` backlog item — the reusable import/normalisation/versioning boundary for per-game production projections, and nothing past it. Four new tables (`projection_sources`, `projection_imports`, `projections`, `source_games_played_assumptions`), migration `0006`, and a new `hoops_gm.ingest.projections` package: `profiles.py` (per-source column-mapping profiles for FantasyPros, Hashtag, Basketball Monster and a canonical-header `manual` profile), `parser.py` (pure, offline CSV validation — no database, no network), and `importer.py` (the DB-writing boundary).

ADR-002 is structural, not just documented: `projections` holds only per-game rates (makes/attempts, never a bare percentage — CHECK constraints make "makes exceed attempts" inexpressible, the same "make it inexpressible" pattern `db/base.py` uses for enums), and a source's embedded games-played figure lives only in `source_games_played_assumptions`, a separate table 1:1 with a projection row, never a column read alongside a rate. Neither `expected-games` nor blending exist yet and nothing here anticipates their shape beyond the table split the plan already names.

Identity resolution reuses the existing crosswalk rather than inventing a second one: `build_player_targets` builds `ResolvableRecord`s keyed by each canonical player's **NBA** external id (not the player's own primary key — `import_resolutions`'s `nba_links` lookup requires it, the same convention `backfill.build_crosswalk` uses for the Fantrax crosswalk), and `import_resolutions` (unmodified) writes the accepted matches to `player_external_ids` under the projection's own `ExternalSource`. Only accepted resolutions get a `projections` row; needs-review and unmatched rows surface through the existing `hoops_gm.identity.report` (`partition`/`render_summary`/`to_csv`) exactly as the Fantrax crosswalk does — no new report mechanism was built.

Versioning is content-addressed over the original bytes: `projection_imports` is keyed by `(source_id, season, content_sha256)`, so re-running byte-identical content for one source and season converges while BOM/newline differences and a later season remain distinct. Reprocessing one import reconciles its output exactly: every owned projection and games-played assumption is removed and only currently accepted resolutions are rebuilt, while stale automated crosswalk links are superseded.

Validation happens entirely in the pure parser: duplicate normalized headers, a missing profile signature, or a file with no usable production rows rejects the file; missing names, non-finite/unparsable numbers, an implausible games-played value (outside 0–100), and makes exceeding attempts reject their rows. Two rows sharing a normalised name within one file are both rejected. A percentage-only shooting column is a warning, not a fabricated rate. Original bytes are hashed before explicit UTF-8/UTF-8-BOM decoding. `Projection` stores no raw row: terminal Rank/AAV/composite/expected-games columns are identified and ignored under accepted ADR-008, while durable source evidence is referenced only from the raw-import boundary through `ProjectionImport.raw_payload_ref`.

`test_portability.py`'s `test_later_phase_entity_groups_are_absent` previously asserted `projections` did not exist yet; updated to drop it from the not-yet set (and added `blend_profiles`, a plan.md table name for a later backlog item that the set had omitted) and added `test_csv_importer_tables_are_present` alongside the existing schedule-context presence test.

**Now true:** The `csv-importer` implementation accepts `csv_bytes=...` and produces byte-versioned, exactly reconciled, ADR-002/ADR-008-separated rows with an identity-resolution report. The implementation is complete but the backlog item is blocked at the Adapter gate. No Model gate applies because this boundary ingests and normalises source data rather than producing a decision-bearing number.

**Could not verify:** The FantasyPros, Hashtag and Basketball Monster column-mapping profiles are **best-effort guesses at common 9-cat export header conventions, not verified against a real downloaded file**. Their synthetic examples are ordinary unit tests and deliberately carry no `adapter_contract` marker. The projection Adapter gate is unmet until privacy-safe fixtures derived from real exports exist. The `manual` canonical-header profile carries no vendor claim and is the profile to reach for until a real source is checked by hand against `ProjectionParseResult.resolved_headers`.

**Next:** `data-engineer` must replace intended vendor examples with privacy-safe fixtures derived from real exports and mark only those tests `adapter_contract`. `projection-blending` may consume `projections`/`source_games_played_assumptions` only after this gate is met; `expected-games` remains the sole future fusion seam under ADR-002.

---

## 2026-08-18 — data-engineer — PR #12 exact-head review follow-up

**Changed:** Closed three issues found by independent review of published head
`3f93d2a`. A finite season total divided by a finite positive GP can still
overflow, so the parser now checks the transformed per-game result with
`math.isfinite` and rejects the row rather than emitting infinity. Rows with
more cells than the header are now structurally rejected before any identity or
production parsing; `csv.DictReader`'s overflow list can no longer be discarded
while a shifted value is accepted. Restored `docs/handoff.md` to the exact
merged-main prefix and moved the original importer entry to EOF, preserving the
append-only rule.

**Now true:** The full local gate passes after these changes: Ruff, formatting,
strict mypy, all 586 default backend tests, all 106 existing real-derived
Adapter contract tests, SQLite upgrade/check/downgrade through `0010`, and the
tracked-file secret scan. Regression tests cover arithmetic overflow and extra
CSV cells. All main-branch handoff content is byte-for-byte unchanged and every
PR #12 entry follows it.

**Could not verify:** The corrected head still requires fresh native Postgres
and migration CI plus another exact-head independent review. Projection-specific
Adapter readiness remains unmet because no privacy-safe real-derived vendor CSV
fixture or projection live-smoke path exists; vendor profiles remain unverified
and cannot import production. This is not merge approval.

**Next:** Publish the correction, require every blocking job including both
native Postgres runs to pass, and return the exact resulting head to the
independent reviewer. Keep `csv-importer` blocked on real-derived vendor
evidence regardless of Code-gate status.
