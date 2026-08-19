# ADR-009 — Phase 3 schedule intelligence: table ownership and output contract

**Status:** Accepted
**Accepted:** 2026-08-17 by the project owner
**Date:** 2026-08-17

## Context

Phase 1 deliberately deferred `schedule_density`, `off_night_slates` and `opponent_context` rather than guess their shape before anyone had tried to compute it (handoff, 2026-08-17). That deferral is now due: `schedule-ingest` is the next critical-path item (R18), and it directly gates the availability model (ADR-007). Without a stated contract, `data-engineer` and `quant` risk the same "shape guessed, then wrong" failure this project keeps finding elsewhere (R30, R33, R36).

Two agents touch this phase. `data-engineer` owns the `ScheduleLeagueV2` source parser in `backend/src/hoops_gm/ingest/nba/schedule.py` (ownership matrix); `quant` consumes its facts for `p(play)` conditioning. Backend-owned persistence and API mechanics remain under `backend/src/hoops_gm/db/`, `backend/alembic/`, and `backend/src/hoops_gm/api/`. The boundary between "ingested fact" and "modelling choice" was the open question Phase 1 raised and did not answer.

## Decision

`schedule-ingest` and `schedule-density` are **data-engineer's** at the source/fact boundary: they emit observable facts only — `team_schedule` (date, opponent, home/away, tipoff), and `schedule_density` fields that are pure calendar arithmetic (days since last game, games in trailing N days, back-to-back flag). No judgment calls (what counts as "light," what counts as "risky") belong here. The canonical source contract is [`docs/adapters/nba-schedule.md`](../adapters/nba-schedule.md).

`schedule-context` (`off_night_slates`, `opponent_context`: pace, category defence, blowout risk) is **quant's**, built in Phase 4 alongside the availability model, not Phase 3. These require modelling decisions (defensive rating windows, pace normalization) that are inputs to `p(play)` and reliability metrics, not raw schedule facts — the same production/availability separation ADR-002 already requires, applied one layer up.

`playoff-schedule` stays with `data-engineer`: it is schedule fact (game counts in playoff weeks), not a model.

Fantasy week boundaries remain solely on `scoring_periods` (plan.md, already decided) — `schedule-ingest` must join against it, never redefine it.

## Consequences

Phase 3 as run by `data-engineer` alone produces only `team_schedule` and `schedule_density`. `schedule-context` moves into Phase 4 and is `quant`'s deliverable, gated on the availability model's calibration requirement (Model gate), not the Adapter gate.

## Rejected

**Building all four Phase 3 items as one data-engineer block** — bakes modelling assumptions into ingestion code before any backtest exists to validate them, repeating the exact mistake Phase 1 avoided by deferring in the first place.

## What would flip this

If `quant` finds `schedule-context` has no model-dependent free parameters (i.e., it reduces to a fixed formula with no calibration), it can move back to Phase 3 under `data-engineer` as a pure derived fact.
