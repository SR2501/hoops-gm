# OPEN — CLI entry points have no shared contract

**Raised:** 2026-09-06, architect, during review of two independent overnight lanes.
**Status:** open, unassigned. Not an ADR yet — see "Whether this needs an ADR".

## The observation

Two lanes running in parallel, on unrelated backlog items, each fixed **one
instance** of a defect that spans every command-line entry point in the backend.
Neither lane could see the other. Both fixes are correct and both are in scope for
their items. The gap is that nothing in the repository makes the *class* visible.

| Defect class | Fixed by | Instances remaining |
|---|---|---|
| `main()` ignores `argv`, so `--help` performs the program's real work | lane 5, `5318354`, in `hoops_gm/__main__.py` | **19 of 20** modules with a `def main(` under `backend/src` are unaudited |
| Console writes are unguarded, so a non-ASCII runtime name raises on cp1252 | lane 6, `38d92a4`, in `ingest/projections/import_csv.py` | **11 of 12** modules that write to `sys.stderr` |

Counts derived 2026-09-06 by enumerating `def main(` and `file=sys.stderr` across
`backend/src`. The most exposed unfixed module is
`backend/src/hoops_gm/ingest/injury_report/backfill.py`: **9** unguarded stderr
writes, handling injury-report data that is almost entirely player names.

## Why this is one problem and not two

`docs/governance/coordinator-register.md` `c39` already reached the same
conclusion from one of the two classes, before the other existed:

> This is the SAME defect class I fixed in `scripts/resolve_doc_conflicts.py`
> earlier today... Two independent instances in one repository on one day
> suggests it is worth a convention rather than two fixes.

That note was written about argv handling alone. The console-safety class is a
second, independent symptom of the same underlying absence: **there is no shared
contract that a command-line entry point must satisfy, and no test that
enumerates entry points to enforce one.** So each class is discovered per-module,
by whoever happens to trip on it, and fixed per-module. Three fixes so far
(`resolve_doc_conflicts.py`, `__main__.py`, `import_csv.py`), each correct, none
preventing the fourth.

The existing `backend/tests/test_console_encoding.py` is the near miss that
proves the point. It walks **string literals** under `scripts` and
`backend/tests`, so it cannot see a name arriving from a vendor file at runtime,
and it does not enumerate entry points at all. A test that walks *sources* cannot
enforce a contract about *behaviour*.

## The shape a fix would take

One test that enumerates every module exposing `def main(` and asserts, per
module:

1. `--help` exits 0, prints usage, and reaches neither the network, the settings
   loader (which reads `.env`, including Fantrax credentials), nor logging
   configuration.
2. An unrecognised flag exits 2 rather than falling through to real work.
3. The module's console streams tolerate a non-ASCII name without raising.

Enumeration is the load-bearing part. A hand-listed set of entry points decays
the moment someone adds the twenty-first, which is exactly how this arrived.

Lane 5 and lane 6 have each been asked to file the backlog item for their own
class with these counts in it. This note exists so the two items are recognisable
as one problem when someone picks them up.

## Whether this needs an ADR

Genuinely unclear, and deliberately not decided here.

**For:** cross-module contracts are architect scope, and "every entry point
satisfies X, enforced by one enumerating test" is a contract, not a chore. Two
distinct defect classes and three separate fixes is enough evidence that
per-module discovery is the default behaviour.

**Against:** an ADR that says "add a walking test" changes very little about what
an implementer builds, which is the bar `AGENTS.md` sets for an ADR body. Two
backlog items may carry the work perfectly well without one. ADR-017 and ADR-021
are both already `Proposed` and awaiting owner acceptance, and adding a third to
that pile has diminishing returns.

**Recommendation:** file the two backlog items, do not write an ADR yet, and
revisit if a **third defect class** appears in the same surface. A third class
would establish that the problem is the missing contract rather than the two
symptoms, and that is the point at which an ADR earns its length.

## What would falsify this

If someone enumerates the 20 `def main(` modules and finds most are internal
helpers never invoked from a shell, the counts above overstate the exposure and
this collapses to two ordinary bugs. That enumeration has **not** been done — the
counts are of modules defining `main`, not of modules documented as commands.
