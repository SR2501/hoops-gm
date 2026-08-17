# hoops-gm backend

FastAPI service, persistence layer, and the REST contracts everything else
talks to. Owned by the `backend` agent — see `.github/agents/backend.md`.

Read `AGENTS.md` and `docs/handoff.md` at the repo root before changing
anything here.

## Requirements

Python 3.11 or newer. `nba_api` requires 3.10+, and the codebase uses 3.11
features, so 3.11 is the floor.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -e ".[dev]"
```

Copy the repo-root `.env.example` to `.env` and fill it in. `.env` is
gitignored and must stay that way — it holds the Fantrax cookie.

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

## Code gate

All three must be green before anything merges (`docs/governance/gates.md`):

```bash
ruff check .
ruff format --check .
mypy
pytest
```

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
└── db/               declarative base, engine/session, ORM models
alembic/              migration environment and versions
tests/
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
