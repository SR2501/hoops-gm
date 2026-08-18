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
