# ADR-006 — External adapters isolated behind contract tests

**Status:** Proposed
**Date:** 2026-08-17

## Context

Every external source this project depends on is unstable in some way:

- `/fxpa/req` is undocumented internal Fantrax infrastructure that can change payload schemas without notice.
- `stats.nba.com` requires specific headers, throttling around 1 req/s, and has deprecated endpoints mid-season (`PlayByPlayV2`, `ScoreboardV2` → V3).
- Projection CSVs change format between seasons.
- The NBA injury report is a published document, not an API contract.

The failure mode that matters is not an outage — it is a **silent** change that still parses and quietly produces wrong numbers. That surfaces weeks later as an inexplicable modelling bug.

## Decision

Every external source sits behind an adapter interface and must pass the **Adapter gate**:

- A **recorded fixture** — a real captured response — committed to the repo.
- An offline **contract test** asserting the parser still works against that fixture, running in CI on every change.
- A **live smoke test** against the real source, marked so it may fail without blocking a merge, but which must fail loudly and visibly.
- Documented throttling, retry, and explicit behaviour when the source is down, changed, or returns garbage.

Raw payloads are preserved — `bridge_payloads` and equivalent stores — so any breakage can be replayed and diagnosed rather than guessed at.

## Consequences

CI stays green and deterministic offline while still surfacing upstream drift. Fixture maintenance is ongoing work, and fixtures must be refreshed deliberately rather than regenerated to make a failing test pass — regenerating a fixture to silence a contract test defeats the entire mechanism.

## Rejected

**Live-only integration tests** — flaky, slow, and rate-limit hostile.
**Mocks written by hand** — encode what we assume rather than what the source actually returns, which is exactly the assumption that breaks.

## What would flip this

A source publishing a versioned, stable, contractual API with change notifications.
