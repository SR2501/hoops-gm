# Ownership

One owner per module. Ownership means: you write it, you are accountable for it, and cross-module changes need the owning agent's agreement. `architect` arbitrates when ownership is genuinely unclear.

## Module → owner

| Path / concern | Owner | Notes |
|---|---|---|
| `docs/decisions/` | `architect` | Anyone may propose; `architect` shapes and sequences |
| `docs/governance/` | `architect` | |
| `backend/src/hoops_gm/ingest/` | `data-engineer` | nba_api, Fantrax official + private, injury reports, schedule ingest, and league-settings intake |
| `backend/src/hoops_gm/identity/` | `data-engineer` | Player crosswalk — highest-risk foundational item |
| `backend/src/hoops_gm/ingest/nba/schedule.py` | `data-engineer` | Source parsing and observable schedule facts only; no modelling judgment (ADR-009) |
| `backend/src/hoops_gm/schedule_context/`, `backend/src/hoops_gm/availability/` | `quant` | Schedule context, p(play), reliability, shutdown, and contingent-value semantics (ADR-009) |
| Projection, valuation, and decision-engine semantics | `quant` | Includes blending, z-score, G-score, risk adjustment, punts, auction pricing, draft, lineup, trade, and streaming math |
| `backend/src/hoops_gm/scoring/` | `quant` | Scoring category semantics and category math; settings intake remains `data-engineer`-owned |
| `backend/src/hoops_gm/calendar/` | `backend` | Calendar persistence/service mechanics; source meaning remains with the producing specialist |
| `backend/src/hoops_gm/api/` | `backend` | REST + SSE contracts, including scoring and calendar API mechanics |
| `backend/src/hoops_gm/db/`, `backend/alembic/` | `backend` | Persistence and migrations, including scoring/calendar storage; schema mechanics are `backend`-owned even where another specialist defines semantics |
| `backend/src/hoops_gm/dev/` | `backend` | Developer tooling (demo seeds). Must build state through the production writers, never by constructing rows itself, and must not acquire `db/lineage.py` locking primitives — see notes below |
| `backend/src/hoops_gm/core/bridge_pairing.py`, `backend/src/hoops_gm/api/routes/bridge.py` | `backend` | Server side of the bridge; `bridge` owns the client side |
| Automation write-path concern | `bridge` | **Reviewed by `safety`, always** |
| `frontend/` | `frontend` | |
| `userscript/` | `bridge` | |
| `.github/workflows/` | `backend` | `safety` must approve changes affecting the Automation gate |
| `docs/models/` | `quant` | One card per model that produces a decision-bearing number |

## Shared seams

These need agreement from both owners before changing:

| Seam | Between | Contract |
|---|---|---|
| Player identity | `data-engineer` → everyone | Canonical `player_id`; nothing downstream invents its own IDs |
| Schedule density | `data-engineer` → `quant` | Density features are inputs to the availability model |
| `expected-games` fusion | `quant` internal | Production and availability stay separate up to this point (ADR-002) |
| Scoring profile | `data-engineer` → `quant` → `backend` | Settings intake supplies evidence; `quant` defines category semantics/math; `backend` owns persistence and API mechanics |
| Valuation output | `quant` → `backend` → `frontend` | Every value carries its input versions |
| Action protocol | `bridge` ↔ `backend` | Typed schema; changes need `safety` review |
| Surface parity | `frontend` ↔ `bridge` | No draft-critical decision may exist in only one surface |
| `scheduled_game_counts` | `data-engineer` → `backend` → `frontend` | Lives in `ingest/nba/schedule.py` and is `data-engineer`'s under ADR-009 as an observable schedule fact, but is now the sole producer of the schedule-grid API's numbers and the screen built on them. **Its density guarantee is the contract:** a dense cross product of scoring periods × active teams, with zero-game teams and periods as explicit rows rather than absent ones. `backend` guarantees `len(counts) == len(teams) × len(periods)` on any 200 by deriving both axes from those rows; `frontend` renders an explicit `0` distinct from absent data on the strength of it. A change that made the result sparse would not fail a type check and would silently turn "this team plays no games that week" into "we have no data", which is the distinction the screen exists to preserve |
| `CANONICAL_STAT_FIELDS` | `data-engineer` → `backend` → `frontend` | Lives in `ingest/projections/profiles.py` and is `data-engineer`'s as the parser's canonical vocabulary, but is now also the **published rate vocabulary** of the projections API: `api/routes/projections.py`'s `_rates()` splats it into `ProjectionRates`, and `test_the_response_carries_exactly_the_canonical_per_game_fields` pins the two in lockstep against both the model and the served body. **Adding or renaming a field is therefore a wire-contract change, not an ingestion detail**, and needs `backend` agreement; it will fail that test rather than pass silently, which is the intent. The vocabulary is per-game rates only — a seasonal total or an expected-games field added here would reach the wire, so ADR-002's separation depends on this tuple staying what its name says |

## Notes on `backend/src/hoops_gm/dev/`

Two constraints, both learned from concrete defects on 2026-08-20 rather than asserted as
principle.

**Build state through the production writers.** A demo seed that constructs rows itself can
satisfy a contract no real producer can. The rejected first schedule-grid API (PR #36)
passed three success-path tests because a test-local helper wrote a refresh summary in
exactly the shape the route's reader wanted, in a shape `import_schedule` never writes — the
tests played the producer, and the endpoint was permanently unavailable against real data
while looking rigorous.

**Do not acquire `db/lineage.py` locking primitives.** Where a seed needs a particular lock
order, get it by *call order* through the production importers instead. Dev tooling holding
lineage locks is the shape that gets cargo-culted into "dev tools take lineage locks", and
the seed's own composition of `import_schedule` before `import_league_settings` produced a
genuine ABBA deadlock against the serving endpoint on PostgreSQL — a race that exists by
design, because the documented workflow re-seeds the very database being served.

## Escalation

- **Unclear ownership** → `architect`
- **Anything in the write path** → `safety`, who may veto
- **Owner-only decision** → stop and escalate to the project owner; see `owner-decisions.md`
