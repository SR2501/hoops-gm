# ADR-001 — Local-first architecture with a Postgres seam

**Status:** Accepted
**Accepted:** 2026-08-17 by the project owner
**Date:** 2026-08-17

## Context

hoops-gm is built for one user, with one or two leaguemates as possible later additions. It holds a Fantrax session cookie and imported projection data that is licensed for personal use only. It must be reliable at specific high-stakes moments — lineup lock, draft night — on a laptop.

A hosted multi-tenant service would add auth, deployment, and data-handling obligations before a single valuation exists.

## Decision

The application runs locally and binds to `127.0.0.1`. SQLite is the development database, but all data access goes through SQLAlchemy, and no SQLite-specific behaviour may leak into queries. Migrations are managed by Alembic from the outset.

Secrets — Fantrax cookie, `userSecretId`, API keys — live in `.env` and are never committed. The cookie is encrypted at rest with a re-login path on expiry.

## Consequences

Moving to Postgres for shared multi-user access (Phase 13) becomes a configuration change plus a data migration, not a rewrite. The cost is discipline: SQLite conveniences must be avoided even when they would be quicker.

Nothing is exposed to the network by default, so personal-use projection data is not redistributed and the cookie is not reachable remotely.

## Rejected

**Hosted service from the start** — obligations without a user base.
**SQLite with direct SQL** — faster initially, but the Postgres move becomes a rewrite exactly when other people depend on it.

## What would flip this

More than three users, or a requirement for access away from the owner's machine.
