# Handoff log

**Append-only.** Newest entries at the bottom. Do not edit or delete previous entries; if something recorded here turns out to be wrong, add a new entry saying so.

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
