# ADR-014 — Read endpoints detect a moved cohort; they do not lock to prevent one

**Status:** Proposed
**Date:** 2026-08-20
**Originated by:** `backend`, from five review rounds on `projections-api-early`

## Context

`GET /api/v1/leagues/{id}/projections/current` must never return 200 with a lineage
block that does not describe the rates beside it. The obvious construction is a lock, and
it was built twice and was wrong twice.

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
`database is locked` once a request outlives pysqlite's five-second busy timeout, and the
"no-op" update mutates `updated_at` through `TimestampMixin.onupdate` — a read endpoint
writing to the row it reads.

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
to pin. **If the producer has no single canonical validity-and-lineage function, that
function is the deliverable, not a local re-derivation in the reader.**

**The bracket covers exactly what the producer's lineage record covers, and nothing
else.** Every value in the response must either be inside that coverage or the response
contract must state what pins it. **Enumerate the keys the response is assembled on** —
every join key, every identifier carried across a read boundary — and for each, name what
makes it stable. A surrogate key is not stable: an importer that rewrites a cohort in
place changes it while the content digest, the row count and the parent id all stay
identical. This clause exists because the projections route obeyed everything above it
and still served a false statement: its assumptions array was joined on captured
`Projection.id` values, which a byte-identical re-import recycles, so a 200 reported that
the source published no games-played assumption when it published 70 and 78. **A
consistency guarantee is only as wide as the set of keys someone enumerated**, and the
digest is not that set.

**State the detection property at the strength it was driven at, not at the strength that
reads well** — and check whether it is the same on every dialect before saying so. For
the projections route, driving three regimes apart established: a write landing *before*
the rows are loaded is caught; one landing *after* is not, because the route holds those
ORM objects strongly; but one that *replaces the row primary keys* defeats that shadowing
and is caught. The third is dialect-dependent — PostgreSQL's `SERIAL` never recycles, so
every re-import lands there, while SQLite can recycle and land in the second. The
guarantee is unconditional; the behaviour is not. **Freshness is not promised**, "refuses
if anything moved" implied it was, and "behaves identically on both dialects" was a
second wrong version of the same sentence.

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
take them. **Converting it is not a deletion:** that route has no
`release_projection_import` equivalent, so the canonical lineage function has to be built
first, per the Decision's second paragraph. The coordinator is filing the item; this ADR
deliberately does not depend on its name existing, because a decision log that ships a
pointer to a task nobody filed is worse than one that describes the work.

The bracket does **not** guarantee freshness, does not cover anything outside the
producer's lineage record, and cannot see a change made and exactly reverted between the
two releases. For the projections route that leaves the games-played assumptions array
explicitly outside the guarantee — subset-checked so it cannot name an uncarried player,
but not digested. Closing it means the canonical release digesting that table, which is a
producer-contract change.

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
a value derived from state it cannot re-check. **That claim must name what specifically
cannot be re-read, so a reviewer can falsify it by attempting that re-read.** Without
that clause this condition is an escape hatch: an implementer who does not want to build
the observation can simply assert it is impossible.

Or a move to multi-user, where a reader blocking a writer is normal and the writer is not
a person waiting at a terminal. That one is checkable in a word against ADR-001's
Postgres seam.

Either would justify a lock, and the reason belongs at the call site.

## Amendments

**Pending, not yet made:** if `ReleasedProjectionImport` is extended to digest the
one-to-one `source_games_played_assumptions` table, the projections response's exemption
for that array is retired and the Consequences section above should say so.
