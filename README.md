# hoops-gm

End-to-end fantasy basketball league management for the 2026–27 NBA season. Built for a head-to-head 9-category league on Fantrax.

Personal project. Not affiliated with Fantrax or the NBA.

---

## Why

Managing a competitive 9-cat league means stitching together league state, NBA stats, projections, category-aware valuation, the schedule — and, increasingly, **who is actually going to play**.

Missed games are epidemic. Load management, rest on back-to-backs, DNP-CDs, late-season shutdowns on eliminated teams, availability that swings for no stated reason. A 70-game player and a 55-game player with identical per-game lines are not the same asset, and the market still prices them as if they were.

hoops-gm models availability as a first-class quantity — `p(play)` for every scheduled game — and threads it through valuation, draft, lineup, streaming and trades.

## What it does

- **Availability engine** — per-game `p(play)`, reliability and consistency metrics, B2B sit patterns, late-season shutdown risk, and a contingent-value graph for when a player sits and someone else's stock moves
- **Valuation** — z-score and G-score, volume-weighted percentage categories, punt-build modelling, risk-adjusted values
- **Projections** — CSV import from any source, configurable blending, plus an in-house baseline model
- **Draft** — snake and auction, both first-class. Auction includes live inflation tracking, max-bid management and nomination strategy
- **Live scorecard** — category-by-category matchup state with availability-adjusted games remaining
- **Schedule intelligence** — density, back-to-backs, off-night streaming windows, fantasy-playoff-week strength
- **Lineup and trades** — optimiser, streaming recommendations, multi-asset trade evaluation
- **Fantrax bridge** — a Tampermonkey userscript that captures league data and surfaces recommendations inside the Fantrax UI

## Architecture

Python/FastAPI backend, React/TypeScript dashboard, Tampermonkey userscript bridge. Local-first — binds to `127.0.0.1`, SQLite in development with a clean Postgres seam.

Fantrax only needs to be open and foreground during a live draft and for lineup writes. Everything else runs without it.

## Status

**Phase 1 (Foundations) built.** 75 tracked work items across 14 phases; the
scaffold, backend skeleton, database foundation, dashboard skeleton and CI are
in place. No ingestion, no modelling, no automation yet.

Build order is spine-first: player identity → schedule → availability →
projections → valuation, then features. Availability comes before valuation
because it is an input to it, not an attribute of it.

## Running it

Requires Python 3.11+ and Node 20.19+.

```bash
cp .env.example .env          # fill in; .env is gitignored and stays that way

cd backend
python -m venv .venv && .venv/Scripts/activate    # source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
python -m hoops_gm            # http://127.0.0.1:8000

cd ../frontend
npm install
npm run dev                   # http://127.0.0.1:5173
```

Or the whole stack at once:

```bash
docker compose up --build
```

Everything binds to `127.0.0.1`. Nothing is exposed to the network — see
[`docs/decisions/ADR-001-local-first.md`](docs/decisions/ADR-001-local-first.md).

| Where | What |
|---|---|
| [`backend/`](backend/) | FastAPI service, SQLAlchemy models, Alembic migrations |
| [`frontend/`](frontend/) | React + TypeScript dashboard |
| [`userscript/`](userscript/) | Reserved for the Tampermonkey bridge (Phase 8) |

## Working on this

Start with **[`AGENTS.md`](AGENTS.md)**, then **[`docs/handoff.md`](docs/handoff.md)**.

| Where | What |
|---|---|
| [`docs/plan.md`](docs/plan.md) | The full plan, including the research that constrains it |
| [`docs/backlog.md`](docs/backlog.md) | **The task list.** 96 items with dependencies and status. A task is ready when every dependency is done |
| **[`docs/governance/OPEN-ci-billing.md`](docs/governance/OPEN-ci-billing.md)** | ⚠️ **Open, needs the owner.** GitHub Actions is stopped by billing, so all four gates are currently unenforced |
| [`docs/handoff.md`](docs/handoff.md) | Append-only project memory. Read before starting; append when finishing |
| [`docs/decisions/`](docs/decisions/) | ADRs — what was decided, what was rejected, what would flip it |
| [`docs/governance/`](docs/governance/) | Ownership, readiness gates, owner-only decisions, risk register |
| [`docs/models/`](docs/models/) | Model cards for anything producing a decision-bearing number |
| [`.github/agents/`](.github/agents/) | Agent definitions |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | CI enforcing the Code gate, with the Adapter and Model gates already wired |

Nothing important lives only in a chat transcript. If it is worth returning to, it is in this repository.

## Notes

Imported projection data is personal-use only and is not redistributed. Fantrax automation operates the owner's own account on the owner's own team; writes are supervised by default and go through the browser as ordinary interaction.
