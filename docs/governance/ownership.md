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
| Valuation output | `quant` → `backend` → `frontend` | Every value carries model version, input/source cohort fingerprints, forecast origin/cutoff, and scoring profile |
| Action protocol | `bridge` ↔ `backend` | Typed schema; changes need `safety` review |
| Surface parity | `frontend` ↔ `bridge` | No draft-critical decision may exist in only one surface |

## Escalation

- **Unclear ownership** → `architect`
- **Anything in the write path** → `safety`, who may veto
- **Owner-only decision** → stop and escalate to the project owner; see `owner-decisions.md`
