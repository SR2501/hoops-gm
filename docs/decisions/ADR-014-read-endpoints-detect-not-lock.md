# ADR-014 — Read endpoints detect a moved cohort; they do not lock to prevent one

**Status:** Proposed
**Date:** 2026-08-20
**Originated by:** `backend`, from three review rounds on `projections-api-early`

## Context

`GET /api/v1/leagues/{id}/projections/current` must never return 200 with a lineage
block that does not describe the rates beside it. The obvious construction is a lock,
and it was built twice and was wrong twice.

The first version took the importer's own `projection_sources` row `FOR UPDATE` and
claimed both dialects therefore serialized. **That was false on SQLite**, which is the
configured default: pysqlite emits `BEGIN` only before DML, and SQLAlchemy drops `FOR
UPDATE` entirely, so a read-only session holds nothing. Review drove a concurrent writer
straight through it and produced exactly the forbidden 200 — post-write rates beside a
pre-write `projection_values_sha256`, cardinality unchanged so a count-only guard passed.

The second version added SQLite's write reservation, which makes the lock real and costs
more than it buys. Every read becomes a *writer*: concurrent polls serialize against each
other (measured at 2.05s and 4.17s, with an untyped 500 for the loser of a slower pair),
an open dashboard tab can make the owner's hand-run `import_projection_csv` fail with
`database is locked`, and the "no-op" update mutates `updated_at` through
`TimestampMixin.onupdate` — a read endpoint writing to the row it reads, held harmless
only by a rollback nobody would notice deleting.

The endpoint's writer is a person at a keyboard. A read path that can stall or fail him
is the wrong trade, and it is the worst possible trade on draft day.

## Decision

**A read endpoint must not hold a lock that can block a writer.** Where a read can
*observe* whether its cohort moved and refuse, that is the construction to use. A lock in
a read path is permitted only where the invariant cannot be checked after the fact, and
the reason must be stated at the call site.

The mechanism is to bracket every read between two runs of the producer's own canonical
release function and compare the immutable lineage records whole — never a locally
re-implemented digest, which would be a second definition of the thing the digest exists
to pin.

**State the detection property at the strength it was driven at, not at the strength that
reads well.** For the projections route, driving both regimes apart established: a write
landing *before* the rows are loaded is caught; one landing *after* is not, because the
route holds those ORM objects strongly. Both outcomes satisfy the guarantee — the rates
and the lineage beside them come from the same objects and cannot diverge — but
**freshness is not promised**, and "refuses if anything moved" implied it was.

The resulting refusal code is **retryable**, and must be marked as such in the contract.
A client retries once and keeps the last good payload on screen rather than clearing the
view; an empty draft board mid-auction is worse than a slightly stale one.

## Consequences

A concurrent import can make a read answer 409 instead of blocking. That is a typed,
documented, transient outcome, and it is strictly better than an untyped 500 or a failed
import.

`schedule_grid.py` takes lineage locks and predates this rule. **It is debt, not
precedent** — and this rule would have prevented the ABBA deadlock that route shipped
against a concurrent seed, because the better fix was not to order the locks but to not
take them. Converting it is `schedule-grid-read-without-locks`.

The lock-order test this rule retires — executing both paths and comparing emitted lock
sequences, compiled against PostgreSQL inside an ORM listener so SQLite cannot make it
pass vacuously — is a technique worth keeping for whatever write paths still need it. It
was good work on a mechanism that should not have existed, and test quality is not
evidence for a design.

## Rejected

**Locking, correctly.** Prevents the race and blocks the owner. See above.

**Re-implementing the digest in the consumer.** A second definition of "normalised rates",
free to drift from the producer's. Invoking the one canonical function twice is not a
second verifier; re-implementing its logic would be.

**Cardinality as a proxy for content.** The first guard compared row counts, which cannot
see a same-size in-place edit — and that is precisely the edit review used to produce a
wrong 200.

## What would flip this

A read whose invariant genuinely cannot be observed after the fact — one that must return
a value derived from state it cannot re-check. Or a move to multi-user, where a reader
blocking a writer is normal and the writer is not a person waiting at a terminal. Either
would justify a lock, and the reason belongs at the call site.
