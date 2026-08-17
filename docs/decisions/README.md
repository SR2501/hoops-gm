# Decision log

Architecture decisions for hoops-gm, numbered and durable.

**Agents write ADRs as `Proposed`. Only the project owner moves one to `Accepted`.** An agent may never mark its own work accepted.

Each ADR records the context, the decision, its consequences, what was rejected, and — importantly — **the condition that would flip it**. A decision without a stated reversal condition is a belief, not a decision.

## Format

- Filename: `ADR-00N-kebab-title.md`
- Body: 150–400 words. Every sentence should change what an implementer builds.
- **Amend rather than supersede** unless the decision itself actually changed. Add an `## Amendments` section with a date.

## Index

| # | Title | Status | Summary |
|---|---|---|---|
| [001](ADR-001-local-first.md) | Local-first architecture with a Postgres seam | Proposed | Runs on `127.0.0.1`; SQLite via SQLAlchemy so multi-user is a config change, not a rewrite |
| [002](ADR-002-production-vs-availability.md) | Separate per-game production from expected games played | Proposed | The central modelling commitment — fused only at an explicit seam |
| [003](ADR-003-gscore-default.md) | G-score as the default valuation scheme for H2H | Proposed | Models weekly variance; absorbs availability risk alongside production variance |
| [004](ADR-004-fantrax-access.md) | Fantrax access: read via API, write only via the browser bridge | Proposed | Three tiers; no programmatic writes to `/fxpa/req`, ever |
| [005](ADR-005-supervised-default.md) | Automation is supervised by default; autonomous is opt-in and gated | Proposed | Eight guardrails; `safety` holds veto; enabling autonomy is owner-only |
| [006](ADR-006-adapter-isolation.md) | External adapters isolated behind contract tests | Proposed | Recorded fixtures; drift fails loudly in CI rather than degrading a number silently |
| [007](ADR-007-availability-in-spine.md) | Availability is a spine concern, modelled before valuation | Proposed | It is an input to valuation, not an attribute of it |

## Awaiting the owner

All seven are `Proposed`. They record decisions reached in the planning conversation of 2026-08-17 and are committed so they are challengeable rather than folklore — but none is accepted until the owner says so.
