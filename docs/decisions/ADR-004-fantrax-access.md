# ADR-004 — Fantrax access: read via API, write only via the browser bridge

**Status:** Accepted
**Accepted:** 2026-08-17 by the project owner
**Date:** 2026-08-17

## Context

Research established what Fantrax actually offers:

- A beta official REST API at `/fxea/general/` — `getPlayerIds`, `getAdp`, `getLeagues`, `getLeagueInfo`, `getDraftPicks`. Free, some endpoints unauthenticated, others needing a `userSecretId`.
- No documented endpoints for matchups, live scores, transactions, waivers — **or any write operation**.
- `fantraxapi` (MIT, maintained) wraps the internal `/fxpa/req` JSON-RPC endpoint. Read-only. Private leagues require a `FANTRAXUSER` session cookie.
- `/fxpa/req` is undocumented internal infrastructure with no public login endpoint.

Reverse-engineering write calls to `/fxpa/req` would violate Fantrax's terms. Separately, Fantrax natively ships auto-draft and auto-subs, so the *category* of automation is sanctioned by the platform.

## Decision

Three tiers, in order of preference:

1. **Official API** for player IDs, ADP, league settings and draft picks. Free, stable, lowest risk.
2. **`fantraxapi`** (version pinned) for private-league rosters, standings and matchups, via an encrypted stored cookie with a re-login path.
3. **The Tampermonkey bridge** for anything the first two cannot reach, and for **all write operations** — as real DOM interaction inside the owner's own logged-in browser session.

No direct programmatic writes to `/fxpa/req`, ever.

## Consequences

Reads are cheap and mostly work without a browser, so season management needs no Fantrax tab open. Writes require Fantrax visible and active, which constrains the draft-day interface — see the Interfaces section of the plan.

Tier 2 and 3 depend on undocumented internals, so both sit behind adapters with contract tests (ADR-006).

## Rejected

**Programmatic writes to `/fxpa/req`** — clear ToS violation with no offsetting benefit over the browser path.
**Scraping only** — brittle and slower than the official API where it exists.

## What would flip this

Fantrax publishing a supported write API, or adding bot detection that breaks tier 2.
