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
