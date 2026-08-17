# Ownership

One owner per module. Ownership means: you write it, you are accountable for it, and cross-module changes need the owning agent's agreement. `architect` arbitrates when ownership is genuinely unclear.

## Module → owner

| Path / concern | Owner | Notes |
|---|---|---|
| `docs/decisions/` | `architect` | Anyone may propose; `architect` shapes and sequences |
| `docs/governance/` | `architect` | |
| `backend/app/ingest/` | `data-engineer` | nba_api, Fantrax official + private, injury reports |
| `backend/app/identity/` | `data-engineer` | Player crosswalk — highest-risk foundational item |
| `backend/app/schedule/` | `data-engineer` | Ingest and density; `quant` consumes |
| `backend/app/availability/` | `quant` | Participation ledger, p(play), reliability, shutdown, contingent value |
| `backend/app/projections/` | `quant` | CSV import mapping is shared with `data-engineer` |
| `backend/app/valuation/` | `quant` | z-score, G-score, risk-adjusted, punts, auction pricing |
| `backend/app/engines/` | `quant` | Draft, lineup, trade, streaming |
| `backend/app/api/` | `backend` | REST + SSE contracts |
| `backend/app/models/`, `backend/migrations/` | `backend` | Schema is `backend`-owned even where `quant` defines the fields |
| `backend/app/bridge/` | `backend` | Server side of the bridge; `bridge` owns the client side |
| `backend/app/automation/` | `bridge` | **Reviewed by `safety`, always** |
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
| Valuation output | `quant` → `backend` → `frontend` | Every value carries its input versions |
| Action protocol | `bridge` ↔ `backend` | Typed schema; changes need `safety` review |
| Surface parity | `frontend` ↔ `bridge` | No draft-critical decision may exist in only one surface |

## Escalation

- **Unclear ownership** → `architect`
- **Anything in the write path** → `safety`, who may veto
- **Owner-only decision** → stop and escalate to the project owner; see `owner-decisions.md`
