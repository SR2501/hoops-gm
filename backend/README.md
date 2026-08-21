# hoops-gm backend

FastAPI service, persistence layer, and the REST contracts everything else
talks to. Owned by the `backend` agent — see `.github/agents/backend.md`.

Read `AGENTS.md` and `docs/handoff.md` at the repo root before changing
anything here.

## Requirements

Python **3.12 or newer**. The package uses PEP 695 type-parameter syntax, and
CI has only ever run 3.12 while local development is on 3.14 — 3.11 was never
a tested claim.

(An earlier version of this README said the `ingest` extra could not install on
3.11 because of numpy. That was wrong: `nba_api`'s numpy pin is version-gated,
so pip would have resolved an older numpy. Corrected in review.)

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -e ".[dev]"
```

`[dev]` pulls in `[ingest]` (`nba_api`, `fantraxapi`, `cryptography`), which
the adapter and identity tests need. Install `.[ingest]` alone to run the
backfill without the toolchain.

Copy the repo-root `.env.example` to `.env` and fill it in. `.env` is
gitignored and must stay that way — it holds the Fantrax cookie key.

## Run

```bash
alembic upgrade head
python -m hoops_gm
```

Serves on `http://127.0.0.1:8000`. Interactive docs at `/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness. Touches nothing. |
| `GET /health/ready` | Readiness. Verifies the database answers. |
| `GET /api/v1/meta` | Service metadata. |
| `GET /bridge/userscript.user.js` | Loopback-only. Serves the built userscript for one-time install and Tampermonkey's `@updateURL`/`@downloadURL` auto-update checks. Unversioned, like `/health`: a static-file surface, not part of the `/api/v1` contract. Never contains a secret. |
| `GET /api/v1/bridge/pairing` | Loopback-only, ten-minute one-time pairing code when no secret exists. |
| `POST /api/v1/bridge/pair` | Loopback-only exchange of `X-Hoops-GM-Pairing-Code` for the bearer secret. |
| `POST /api/v1/bridge/handshake` | Authenticated userscript protocol handshake. |
| `POST /api/v1/bridge/payloads` | Authenticated, bounded raw bridge-envelope capture. |
| `GET /api/v1/leagues/{league_id}/schedule-grid/current` | Loopback-only. Raw game counts for every NBA team in every one of the league's scoring periods, with the exact schedule, projection, calendar and settings lineage behind them. Descriptive only — no thresholds or "light week" judgement (ADR-009). Fails closed with a typed code in `ErrorResponse.error` rather than serving partial or unverifiable counts. |
| `GET /api/v1/leagues/{league_id}/projections/current` | Loopback-only. The current *imported* per-game projection cohort for the league's season (`?source=` defaults to Basketball Monster), with every import fingerprint, the profile that read it, and the source's own games-played assumption in its own array (ADR-002 — never inside a rate). Descriptive only: no blend, no valuation, no ranking, no availability fusion. `lineage.blend` is a typed key that is always `null` — see below. Fails closed with one of eight typed codes, of which **`projections_inconsistent_cohort` is the only retryable one**: retry once and keep the last good payload on screen rather than clearing the view. **A client must not multiply a rate by `assumed_games_played`:** that number is the exact divisor the importer used to produce the rates, so the product recovers the source's published seasonal total to within floating-point rounding, and that fusion is permitted only at `expected-games`. Display it; do not compute with it. |

`GET /bridge/userscript.user.js` reads `userscript/dist/hoops-gm.user.js`
from disk on every request — nothing is cached in the process, so a rebuild
takes effect on the next Tampermonkey update check without restarting the
backend. If that file does not exist yet (a fresh checkout, or `npm run
build` was never run in `userscript/`), the route returns `404` with a
`detail` field that says exactly what to run, rather than a bare 404 — see
`userscript/README.md` for the full install/update workflow.

## Code gate

All of these must be green before anything merges
(`docs/governance/gates.md`):

```bash
ruff check .
ruff format --check .
mypy
pytest
python ../scripts/check_no_secrets.py
```

## Adapter gate

Applies to anything calling an external source
(`docs/adapters/` documents each one).

```bash
pytest -m adapter_contract   # offline, against committed fixtures; must pass
pytest -m live_smoke         # hits the real sources; may fail, must fail loudly
```

A contract test catches *our* parser breaking. It cannot catch the upstream
changing — the fixture keeps passing forever. Only the live smoke test can, so
it is the one worth writing carefully.

**Never refresh a fixture to make a contract test pass** (ADR-006). Find out
what changed, record it in `docs/handoff.md`, then:

```bash
python -m hoops_gm.ingest.record_fixtures --all

# Successful getLeagueInfo is separate because it needs the target league id.
# The recorder removes identity-bearing sections and never uses userSecretId.
HOOPS_GM_FANTRAX_LEAGUE_ID=... \
python -m hoops_gm.ingest.record_fixtures fantrax-league-settings
```

Set `HOOPS_GM_FANTRAX_LEAGUE_ID` when running `pytest -m live_smoke` to include
the cache-bypassing league-settings drift check.

The Basketball Monster projection smoke is private-file-only and opt-in. Set
`HOOPS_GM_BBM_PROJECTION_CSV` to an explicit local export path and select
`BasketballMonsterProjectionExport`; no default path is searched or logged.

## Ingestion

```bash
# Persist one immutable official settings snapshot. This intentionally sends
# only leagueId; a source-season mismatch aborts instead of writing.
python -m hoops_gm.ingest.backfill league-settings LOCAL_LEAGUE_ID FANTRAX_LEAGUE_ID

# Optionally merge one operator-selected, already captured bridge settings file.
# This does not capture, poll, or authenticate the bridge.
python -m hoops_gm.ingest.backfill league-settings \
  LOCAL_LEAGUE_ID FANTRAX_LEAGUE_ID \
  --bridge-capture data/manual/league-settings.json

# Build the NBA/Fantrax crosswalk. Use the CURRENT season: matching against a
# historical one invents a team disagreement for every offseason move.
python -m hoops_gm.ingest.backfill crosswalk --season 2026-27

# One season of games and box scores (2 requests, seconds).
python -m hoops_gm.ingest.backfill season 2024-25

# ...plus the participation ledger: DNP reasons and inactive lists.
# ~2 requests per game at 1.1s each, so roughly 45 minutes for a season.
python -m hoops_gm.ingest.backfill season 2024-25 --with-participation
```

Bound a participation run to an explicit inclusive game-date window without
changing the season-wide schedule and production ingest:

```powershell
python -m hoops_gm.ingest.backfill season 2025-26 --with-participation `
  --start 2025-12-08 --end 2026-01-04
```

The crosswalk writes `data/reports/unmatched_players.csv` — the tail a human
has to adjudicate, with the per-field evidence behind every decision. Read it.

Raw responses are captured under `data/raw/` and double as the cache, so an
interrupted backfill resumes rather than restarts.

### Fantrax private league

```bash
python -m hoops_gm.ingest.fantrax_private.cookies --generate-key  # once, into .env
python -m hoops_gm.ingest.fantrax_private.cookies --store         # whenever it expires
```

See `docs/adapters/fantrax-private.md`.

## Local demo data

The schedule grid fails closed on missing, stale or unverifiable lineage, so
"it returns 409" says nothing about whether it can ever return anything else.
This seeds one database to a genuinely verified state, offline, from the
committed NBA fixtures and through the production importers:

```bash
cd backend
python -m hoops_gm.dev.seed_schedule_grid --database-url sqlite:///./schedule_grid_demo.db
DATABASE_URL=sqlite:///./schedule_grid_demo.db python -m hoops_gm
curl http://127.0.0.1:8000/api/v1/leagues/1/schedule-grid/current
```

It seeds 30 teams, the 10 resolved games in
`tests/fixtures/nba_scheduleleaguev2_2026_27.json`, and 21 Monday-to-Sunday
scoring periods covering them, so the grid returns 630 dense count rows with
20 team-games. Re-running it converges rather than advancing "current": the
registered schedule version is a fingerprint of the persisted rows. It is not
a strict no-op — the refresh's `refreshed_at` moves to the wall clock.

It **refuses** to run against a database holding any league it did not create,
or any 2026-27 game outside the fixture cohort. Schema is built with
`Base.metadata.create_all`, not Alembic, so the demo database is model-built
rather than migration-built; that is fine for a throwaway file and wrong for
anything else.

A relative SQLite path is anchored to the **repo root**, not the working
directory (`Settings._resolve_relative_sqlite_path`), so the file above lands
at `../schedule_grid_demo.db`. `*.db` is gitignored.

Nothing here reaches the network. The recorded payload is imported
**unmodified**, including the two Emirates NBA Cup games it publishes with no
teams assigned: under ADR-013 those are recorded as *pending* rather than
refused. Until ADR-013 the seed carried a filter and a reconciliation pair
whose only purpose was to get past a refusal that no longer exists; both were
retired with it.

**Read the served lineage accordingly.** The response says
`source_game_count: 12`, `resolved_game_count: 10`,
`pending_game_ids: ["0022601201", "0022601202"]`, `unresolved_game_ids: []`.
Twelve is what the source published; ten is what has `team_schedule` rows.
The seed's console output names the same two populations —
`games_recorded_in_fixture: 12`, `games_pending_no_teams_assigned: [...]`,
`games_imported_into_cohort: 10` — so nobody has to guess which of the two a
screen is showing.

The demo database therefore **exercises the pending path rather than hiding
it**, which is the point: a screen that must distinguish "no games this week"
from "not scheduled yet" can be driven locally instead of mocked. Note that a
pending game carries no team, by definition — the honest statement is
period-scoped ("this week holds games whose teams are not yet decided"), never
per-team.

The demo's two pending games are also the reason its `game_sub_label` and
`game_subtype` are empty strings: that fixture is field-trimmed and predates
those fields mattering. `nba_scheduleleaguev2_2026_27_pending_knockout.json`
keeps whole objects and is what covers label handling offline.

For the same reason the seed refuses to run against a database holding any
league it did not create, or any 2026-27 game outside the fixture cohort:
`nba_games`, `team_schedule` and the `nba-schedule` refresh are global and
season-scoped, with no league dimension, so a ten-game fixture aimed at a
working database would become the current registered cohort for every consumer.

The demo's scoring periods are Monday-to-Sunday weeks derived from the NBA game
dates, not a real Fantrax calendar, and its playoff weeks are synthesized — the
settings contract cannot express "authoritatively zero playoff periods". Do not
read the demo as evidence that a real league's calendar joins correctly.

### Projections on screen

`seed_schedule_grid` seeds no players and no projections, so
`/api/v1/leagues/{id}/projections/current` could only ever answer
`projections_source_not_imported` — it had never returned 200 outside pytest.
`seed_projections` composes the schedule seed and then adds both:

```bash
cd backend
python -m hoops_gm.dev.seed_projections --database-url sqlite:///./projections_demo.db
DATABASE_URL=sqlite:///./projections_demo.db python -m hoops_gm
curl "http://127.0.0.1:8000/api/v1/leagues/1/projections/current"
```

**The projection numbers it writes are invented.** Nothing derived from that
cohort is a projection anyone should look at, and a fixture captured from the
screen it drives proves *shape* and nothing else — not column width, not long
names, not a real cohort size, not a real distribution. Sixty players is enough
to scroll and sort and is not a league.

Only the **names** are real, and they have to be: Basketball Monster's contract
publishes no team and no position column, so a name is the only evidence the
identity resolver has, and a seed that invented names would resolve nothing. The
demo CSV is generated in memory at seed time from the canonical players the same
run imported, in the verified profile's exact committed header order, and goes
through `import_projection_csv` unmodified. There is no committed demo CSV, on
purpose: a checked-in file of real NBA names beside real captures would read as
one.

The committed Basketball Monster fixture cannot do this job.
`tests/fixtures/projections/basketball_monster_sample.csv` holds two rows named
*Player Alpha* and *Player Gamma* — its metadata says the paid rows were removed
and the committed ones are synthetic — so it resolves to zero players, writes
zero rows, and `release_projection_import` then raises. Seeding it through the
real importer produces **a new refusal, not a 200**. That fixture is Adapter-gate
evidence of the column contract and is doing that job correctly.

## Importing a real projection CSV

```bash
cd backend
# Rehearse: does the real thing, reports the real match count, rolls back.
python -m hoops_gm.ingest.projections.import_csv 2026-27 ~/bbm-2026-27.csv --dry-run

# Do it.
python -m hoops_gm.ingest.projections.import_csv 2026-27 ~/bbm-2026-27.csv
```

Players must already exist — run `python -m hoops_gm.ingest.backfill crosswalk
--season 2026-27` first, or there is nothing for the CSV's names to resolve
against.

`--dry-run` is a rehearsal rather than a preview: it runs the real import,
identity resolution included, and rolls back. That means it holds the database
write lock for its duration and a concurrent real import will wait. It does not
relax profile verification, so a green dry run cannot promise an import that
then refuses.

Nothing from inside the file is printed. The export is paid content whose rows
are deliberately absent from this repository, and a terminal scrollback is one
paste away from being somewhere else. The summary is counts, identifiers and
digests; source names appear only in the unresolved-players CSV under gitignored
`data/reports/projections/`.

There is no `--database-url`, for the reason `hoops_gm.ingest.schedule_import`
has none: both prior credential leaks in this repository were leaks *of that
flag*.

Exit codes: `0` clean · `2` refused, nothing written · `3` no such file · `4`
database refused, nothing written · **`5` imported, and the cohort is smaller
than the file**. `5` exists because the alternative is exit `0` on an import
where a hundred players silently failed to match.

## Why the projections endpoint takes no lock

It reads `projection_sources`, `projection_imports`, `projections`, `players`
and `source_games_played_assumptions` without locking any of them.

**The guarantee is narrower than "nothing moved", and the narrow version is the
true one.** What is pinned is exactly what `ReleasedProjectionImport` covers —
one lineage record over the `projections` rows — so a rate edit, a row added or
removed, a superseded import or broken profile lineage are all caught. What is
*not* pinned: `players` is checked for membership, never for its label values,
so a player renamed mid-request is served without comment; and
`source_games_played_assumptions` is not digested at all, because the canonical
release deliberately never selects that table. Both are stated again on the
response model, where a consumer will meet them.

An earlier version took the importer's own `projection_sources` row `FOR UPDATE`
and claimed both dialects therefore serialized. **The SQLite half was false**:
pysqlite emits `BEGIN` only before DML, and SQLAlchemy drops `FOR UPDATE` on
SQLite, so a read-only session held nothing at all. A concurrent writer
committed straight through it and the endpoint served a 200 whose rates were
post-write beside a pre-write `projection_values_sha256`.

Adding SQLite's write reservation makes the lock real, and it was tried and
rejected. It turns every read into a *writer* on the development database, so an
open dashboard tab can make a hand-run `import_projection_csv` fail with
`database is locked`; it mutates `updated_at` through `TimestampMixin`'s
`onupdate`, held harmless only by a rollback nobody would notice deleting; and
on PostgreSQL it stalls an import for the whole request. For a single-user local
tool whose writer is a person at a keyboard, that is the wrong way round.

So every read is **bracketed between two runs of `release_projection_import`**
and the two immutable lineage records are compared whole. The trade in one line:
a lock prevents the race and blocks the owner's import; the digest detects it and
asks the caller to retry.

**What "detects" means precisely, because two looser phrasings were wrong in
turn and a screen would have been built on either.** Three regimes, driven:

1. a write landing *before* the rows are loaded is seen and refused;
2. a write landing *after* them that leaves the row primary keys alone — an
   in-place edit — is not seen, because the route holds those ORM objects
   strongly and the second release digests the same instances. A consistent
   *older* snapshot is served;
3. a write landing after them that **replaces the primary keys** — which is every
   re-import, since the importer deletes and re-inserts the cohort — defeats that
   shadowing, and the request is refused.

**Regime 3 is dialect-dependent.** PostgreSQL's `SERIAL` never recycles, so a
re-import always lands there. SQLite recycles the top free rowid, so in a
one-import database the same race lands in regime 2. An earlier version of this
section said the construction behaves identically on both dialects; it does not,
and that was a claim nobody had run.

**The guarantee is unconditional even though the behaviour is not:** on any 200
the rates and the lineage block beside them describe the same cohort state. What
is not promised is freshness, and what is not *measured* is how often a
PostgreSQL deployment answers 409 in regime 3 — no real server was available. A
caller needing "latest" re-requests and compares `projection_values_sha256`.

**`projections_inconsistent_cohort` is retryable.** It is the only one of the
eight that is. A client should retry once and **keep the last good payload on
screen rather than clearing the view** — an empty draft board mid-auction is
worse than a slightly stale one. (One member of that code, an orphaned
`player_id`, is not retryable, but a foreign key makes it unreachable through the
route; it is driven directly against the helper.) The other seven are terminal
and need a human: import a CSV, fix the crosswalk, re-import under a verified
profile.

## Why the projections endpoint serves no blend

`GET /api/v1/leagues/{league_id}/projections/current` reports the **imported**
per-game cohort, not a blended one, and `lineage.blend` is a typed key that is
always `null`.

That is not an omission. `hoops_gm.projections.blending` computes a blend from a
`BlendCatalog`, and that catalog is an explicitly caller-owned in-memory value:
`define_blend_profile` and `activate_blend_profile` each return a *new* catalog
rather than writing one, because the accepted schema has no blend tables and
adding them is an architecture decision rather than a side effect of blending.
So no blend profile, no activation pointer and no source weights are persisted
anywhere for an HTTP request to read. Serving a blend here would mean the route
constructing a profile itself, which is choosing weights, which is a number a
decision rests on — the Model gate, and `quant`'s to pass.

The key exists so a consumer renders "not blended" from a fact rather than
inferring it from a key it failed to find. At the JSON level it is also where a
persisted blend would surface: a key that has always been `null` starting to
carry an object is additive for a client. At the *contract* level that is not
free — `ProjectionLineage.blend` is typed `None`, not `BlendLineage | None`, so
surfacing a blend is a schema change and not a fill-in. Say the second, because
the first reads like the work is already provisioned for and it is not.

## Do not multiply a projection rate by the source's games-played assumption

`source_games_played_assumptions` is what the source assumed and what our
availability model will replace. It is **also the exact divisor these rates were
derived with** — for a season-total source like Basketball Monster the importer
produced `minutes_per_game` as `2415 / 70` — so multiplying a rate by it
recovers the source's published seasonal total to within floating-point
rounding. The decomposition ADR-002 mandates is reversible at the wire by a
two-line join.

Doing that join is the production-and-availability fusion ADR-002 permits only
at `expected-games`, which is not built. **A client may display the assumption
and must not compute with it.** Rendering "projected season total" from this
payload is an ADR-002 violation implemented one layer away from where anyone is
looking for it.

## Migrations

The database URL comes from `Settings`, not from `alembic.ini`, so migrations
and the running app can never disagree about their target.

```bash
alembic upgrade head                              # apply
alembic revision --autogenerate -m "description"  # create
alembic check                                     # models vs migrations in sync
alembic downgrade -1                              # step back
```

`alembic check` runs in CI. A model change without a migration fails the build.

## Layout

```
src/hoops_gm/
├── app.py            application factory
├── __main__.py       python -m hoops_gm
├── api/              routers, dependencies, schemas, middleware
├── core/             settings and structured logging
├── db/               declarative base, engine/session, ORM models
├── dev/              developer tooling; offline fixture seeding, never imported by the service
├── identity/         the cross-source player crosswalk (risk R7)
└── ingest/           external adapters
    ├── errors.py         the failure vocabulary every adapter speaks
    ├── throttle.py       request pacing
    ├── retry.py          backoff, for the one failure class that deserves it
    ├── rawstore.py       raw capture, which doubles as the cache
    ├── importers.py      parsed records into the database
    ├── backfill.py       multi-season orchestration + CLI
    ├── nba/              stats.nba.com via nba_api
    ├── fantrax_official/ /fxea/general/
    └── fantrax_private/  /fxpa/req via fantraxapi
alembic/              migration environment and versions
tests/
└── fixtures/         recorded responses + manifest.json
```

## Conventions

- **Surrogate primary keys.** No upstream identifier is ever a primary key.
  Fantrax, NBA and projection-CSV identities disagree (risk R7); external
  identifiers live in `player_external_ids` with a confidence score.
- **No dialect branching outside `db/session.py`.** SQLite is the development
  database and Postgres is the destination (ADR-001). Engine construction is
  the only place allowed to know the difference.
- **Makes and attempts, never percentages.** FG% and FT% are volume-weighted
  downstream, which is impossible if the denominator was discarded (risk R9).
- **Versioned configuration is immutable.** Scoring profiles carry a `version`
  and are never updated in place, so a stored number's inputs stay recoverable.
- **Secrets are `SecretStr`.** They cannot then be printed into a log line by
  accident.
- **Bridge pairing is local-only.** With no explicit `BRIDGE_SECRET`, the
  backend writes the generated bearer secret to `data/bridge_secret` using an
  atomic replacement and restrictive file permissions. `BRIDGE_SECRET` remains
  the explicit recovery/override and takes precedence over that file. Pairing
  codes are never logged, expire after ten minutes, and lock after five failed
  attempts.
