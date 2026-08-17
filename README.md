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

**Planning complete, implementation starting.** 75 tracked work items across 14 phases.

Build order is spine-first: player identity → schedule → availability → projections → valuation, then features. Availability comes before valuation because it is an input to it, not an attribute of it.

## Working on this

Start with **[`AGENTS.md`](AGENTS.md)**, then **[`docs/handoff.md`](docs/handoff.md)**.

| Where | What |
|---|---|
| [`docs/plan.md`](docs/plan.md) | The full plan, including the research that constrains it |
| [`docs/handoff.md`](docs/handoff.md) | Append-only project memory. Read before starting; append when finishing |
| [`docs/decisions/`](docs/decisions/) | ADRs — what was decided, what was rejected, what would flip it |
| [`docs/governance/`](docs/governance/) | Ownership, readiness gates, owner-only decisions, risk register |
| [`docs/models/`](docs/models/) | Model cards for anything producing a decision-bearing number |
| [`.github/agents/`](.github/agents/) | Agent definitions |

Nothing important lives only in a chat transcript. If it is worth returning to, it is in this repository.

## Notes

Imported projection data is personal-use only and is not redistributed. Fantrax automation operates the owner's own account on the owner's own team; writes are supervised by default and go through the browser as ordinary interaction.
