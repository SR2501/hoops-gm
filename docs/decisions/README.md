# Decision log

Architecture decisions for hoops-gm, numbered and durable.

**Agents write ADRs as `Proposed`. Only the project owner moves one to `Accepted`.** An agent may never mark its own work accepted.

Each ADR records the context, the decision, its consequences, what was rejected, and — importantly — **the condition that would flip it**. A decision without a stated reversal condition is a belief, not a decision.

## Format

- Filename: `ADR-00N-kebab-title.md`
- Body: 150–400 words. Every sentence should change what an implementer builds.
- **Amend rather than supersede** unless the decision itself actually changed. Add an `## Amendments` section with a date.

New to the project? [`PLAIN-ENGLISH.md`](PLAIN-ENGLISH.md) explains each decision and why it was made, without assuming you already know the codebase.

## Index

| # | Title | Status | Summary |
|---|---|---|---|
| [001](ADR-001-local-first.md) | Local-first architecture with a Postgres seam | **Accepted** | Runs on `127.0.0.1`; SQLite via SQLAlchemy so multi-user is a config change, not a rewrite |
| [002](ADR-002-production-vs-availability.md) | Separate per-game production from expected games played | **Accepted** | The central modelling commitment — fused only at an explicit seam |
| [003](ADR-003-gscore-default.md) | G-score as the default valuation scheme for H2H | **Accepted** | Models weekly variance; absorbs availability risk alongside production variance |
| [004](ADR-004-fantrax-access.md) | Fantrax access: read via API, write only via the browser bridge | **Accepted** | Three tiers; no programmatic writes to `/fxpa/req`, ever |
| [005](ADR-005-supervised-default.md) | Automation is supervised by default; autonomous is opt-in and gated | **Accepted** | Eight guardrails; `safety` holds veto; enabling autonomy is owner-only |
| [006](ADR-006-adapter-isolation.md) | External adapters isolated behind contract tests | **Accepted** | Recorded fixtures; drift fails loudly in CI rather than degrading a number silently |
| [007](ADR-007-availability-in-spine.md) | Availability is a spine concern, modelled before valuation | **Accepted** | It is an input to valuation, not an attribute of it |
| [008](ADR-008-layer-purity.md) | Aggregates are terminal outputs, never inputs | **Accepted** | Rankings and AAV already contain availability; blending them back in double-counts it and destroys decomposability |
| [009](ADR-009-schedule-intelligence-contract.md) | Phase 3 schedule intelligence: table ownership and output contract | **Accepted** | `schedule-ingest`/`schedule-density` are data-engineer facts; `schedule-context` is quant's Phase 4 model, not a Phase 3 ingest |
| [010](ADR-010-local-bridge-pairing.md) | One-time local pairing for the browser bridge | **Accepted** | A displayed, single-use local code provisions the userscript bearer secret without putting it in source control |
| [011](ADR-011-strength-of-schedule-sequencing.md) | Strength of schedule is a living projection dependency, not schedule intelligence | **Accepted** | SOS and every projection set form a versioned recursive loop with at least weekly refreshes and cascaded downstream outputs |
| [012](ADR-012-per-week-game-distribution.md) | Per-week game distribution is a living schedule dependency across decisions | **Accepted** | Weekly game volume is re-ingested and cascaded into projections, SOS, valuations, draft, trades, lineups, streaming, and weekly planning |

## Accepted

ADR-001 through ADR-007 were accepted by the project owner on **2026-08-17**, after review.

They record the decisions reached in the planning conversation of the same day and are now settled — but not immutable. Each states the condition that would flip it, and an accepted ADR can still be amended when reality disagrees with it. If one of those conditions is met, say so rather than working around the decision.

ADR-009 was accepted by the project owner on **2026-08-17**.

ADR-008 was accepted by the project owner on **2026-08-18**, who explicitly
praised it as written.

The recursive weekly refresh amendments to ADR-011 and ADR-012 were accepted by
the project owner on **2026-08-17**. They extend the original sequencing
decisions with versioned cascade and freshness requirements; they do not choose
the SOS formulation or convergence thresholds.
