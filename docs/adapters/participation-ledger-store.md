# The participation ledger store

**The ledger is populated. It is not in this repository, and it is not in any
worktree.** It lives at `C:\Users\steverones\hoops-gm-data\hoops_gm.db`, a
sibling of the main checkout.

This file exists because that sentence was not written down anywhere under
version control, and on 2026-08-22 the cost of that came due.

---

## The contradiction this file closes

Two claims sat on `main` at the same time and **both were correct**:

| Claim | Store it was true of | `player_participation` |
|---|---|---|
| "populated: 43,037 rows, 596 players, 1,227/1,230 games" | `C:\Users\steverones\hoops-gm-data\hoops_gm.db` | 43,037 |
| "the one real database holds 0 rows" | `C:\Users\steverones\hoops-gm\hoops_gm.db` | 0 |

Neither report named the path it read, so neither could be checked and the pair
could not be reconciled without re-deriving both from scratch.

**The mechanism.** `Settings.database_url` defaults to `sqlite:///./hoops_gm.db`,
and the validator at `backend/src/hoops_gm/core/config.py:94` anchors a relative
SQLite path to `REPO_ROOT` — *each checkout's own root*. So every worktree and
the main checkout each resolve that identical URL to a **different file**, all
named `hoops_gm.db`, all empty unless someone ingested into that particular one.

**Why an exhaustive search still missed it.** The coordinator searched nine
worktrees plus the owner's main checkout. `hoops-gm-data` is in none of those —
it is deliberately outside every checkout so that `git worktree remove` cannot
destroy hours of throttled fetching. The search was exhaustive over the wrong
domain, which is the failure mode a confident `0` is worst at revealing.

**A verified absence is a statement about the places you looked, not about the
world.** That is the transferable lesson, and it is why the tool below reports a
path with every count.

---

## Reading the ledger

```powershell
cd backend
$env:PYTHONPATH = "$PWD\src"
$env:DATABASE_URL = "sqlite:///C:/Users/steverones/hoops-gm-data/hoops_gm.db"
python -m hoops_gm.availability.coverage
```

`hoops_gm.availability.coverage` cannot emit a count without the store it came
from: `LedgerCoverage` holds the counts and the `StoreIdentity` as fields of one
frozen record, and there is no public path to one without the other. Passwords
are hidden in the rendered URL, so its output is safe to paste into a handoff
entry or a CI summary.

Exit codes: `0` populated, `1` **read successfully and holds nothing**, `2`
unusable — no database file at that path, no participation schema in it, or it
could not be read at all.

The `1` / `2` split matters more than it looks. An uncaught database error exits
`1` in Python, which would make "the store is empty" and "the store is
unreachable" the same signal to any caller checking only the status. Driven
against a nonexistent PostgreSQL database: the server refuses rather than
creating one, so a server-backed store cannot invent a false zero — but it could
still *report* one through the exit code, and now does not.

The absent-file case is a refusal, not a failure — but **not for the reason it
is tempting to give**, and the difference is worth stating because the tempting
version was published here and had to be withdrawn.

SQLite *creates* a database on connect rather than refusing. Driven 2026-08-23:
pointed at a mistyped path, a reporting command makes an *unmigrated* file and
then dies on `no such table`. That is litter plus a misdiagnosis — the error
blames the schema when the fault is the path — but it is **loud**, and nobody
reads a traceback as a result. So create-on-connect does **not** manufacture a
false zero, and an earlier version of this page said it did.

**The real false-zero vector is a store that is migrated and empty**, which is
what `alembic upgrade head` produces in a fresh worktree and what the main
checkout's `hoops_gm.db` was at schema `0003`: it answers every query honestly,
reports zero, and exits successfully. Nothing about opening the file catches
that. **What catches it is naming the store beside the count**, which is why
`LedgerCoverage` cannot emit one without the other.

The refusal therefore earns its place on the narrower ground of an accurate
message and no stray databases. The inventory of which commands refuse, which
may create, and which are knowingly unguarded is pinned in
`backend/tests/test_store_creating_readers.py`.

Add `--json` for the machine-readable form. The committed census at
[`participation-ledger-2025-26-coverage.json`](participation-ledger-2025-26-coverage.json)
is exactly that output, and regenerating it is how you check this document
rather than trusting it.

---

## What it holds, measured 2026-08-22

2025-26 regular season, sourced entirely from `nba` (`ExternalSource.NBA`):

| | |
|---|---|
| participation rows | 43,037 |
| distinct players | 596 |
| games observed | 1,227 of 1,230 final (99.8%) |
| distinct game dates | 164 |
| box-score rows | 26,651 |
| schema revision | `0016` |

Outcomes — `played` 26,590 · `inactive` 10,937 · `did_not_play` 4,426 ·
`did_not_dress` 1,007 · `not_with_team` 77.

Reasons — `none_given` 37,527 · `coaches_decision` 4,302 · `injury_or_illness`
1,099 · `suspension` 36 · `rest` 29 · `not_with_team` 29 · `personal` 11 ·
`conditioning` 4.

**Absences are rows, not missing rows.** 16,447 of the 43,037 records a player
who did not appear, which is the distinction the whole availability thesis rests
on: `availability-model` must be able to tell "he did not play" from "we have no
observation", and only an explicit row can carry that.

`inactive_list_available` is true for all 43,037 rows, so no row in this ledger
is silently standing in for an endpoint that stopped reporting — see the
`BoxScoreSummaryV2` regression described in
`backend/src/hoops_gm/db/models/availability.py`.

### The three unobserved games

`0022500259`, `0022500260`, `0022500261`, all **2025-11-19**, all `final`, all
carrying no `boxScoreSummary` body at source. Reproducible, and not an endpoint
change: the neighbouring `0022500258` returns a complete body from the same
endpoint on the same date, and both `LeagueGameFinder` and
`BoxScoreTraditionalV3` list them. It is a cross-source disagreement.

Under R35 they contribute no rows and **nothing is inferred from their silence**.
The coverage tool lists them by date rather than rounding 1,227/1,230 up to
complete, because a gap a report does not name is a gap nobody chases.

---

## Two databases in that directory, and they are not interchangeable
`throwaway-report-sweep.db` sits beside the real one and holds 69,922
`injury_report_entries`, 2,460 `team_schedule` rows and **zero** participation
rows. It took its tip-offs from `ScheduleLeagueV2` **on purpose**, which makes it
permanently unusable for any cohort manifest.

### Three stores, three disjoint slices, none of them joinable alone

Worth stating plainly, because it is the shape of the data rather than an
accident:

| Store | participation | box scores | injury reports | schedule |
|---|---|---|---|---|
| `hoops_gm.db` | 43,037 | 26,651 | 0 | 0 |
| `throwaway-report-sweep.db` | 0 | 26,651 | 69,922 | 2,460 |
| the main checkout's `hoops_gm.db` | 0 | 0 | 0 | 0 |

**No single store holds both participation outcomes and injury-report
statuses.** Any status-to-outcome question therefore needs a deliberate join
across two stores whose tip-offs come from *different and deliberately
independent* sources — which is exactly the contamination the paragraph below
warns about. That join is a Model-gate matter belonging to `quant` under the
frozen protocol in `docs/models/`. It is recorded here so that it is
**requested rather than discovered**.

`hoops_gm.db` took every `tipoff_utc` from `BoxScoreSummaryV3` during the
per-game participation pass. `schedule_import` must never be run against it,
because `ScheduleLeagueV2` is the *independent* source the cohort manifest's
`cross_source_tipoff_reconciliation` compares against. Persisting
`ScheduleLeagueV2` instants there would silently turn that check into a
comparison of one endpoint with itself; it would keep reporting `agreed: true`,
and **nothing records the provenance of a persisted instant**, so no reader could
detect it afterwards.

**The observable proxy, if you want to check rather than trust:**

```
games with tipoff_utc == games with participation rows   -> clean
games with tipoff_utc == 1230, participation partial     -> CONTAMINATED
```

Driven 2026-08-22: **1,227 == 1,227, clean.**

---

## Rebuilding it

A populated database nobody can rebuild is not an asset. Every response is
already cached in `hoops-gm-data\data\raw`, keyed by URL, and a completed game's
box score never changes — so **a re-run costs no requests** and replays at disk
speed.

```powershell
$env:DATABASE_URL = "sqlite:///C:/Users/steverones/hoops-gm-data/hoops_gm.db"
cd C:\Users\steverones\hoops-gm-data          # raw store resolves to .\data\raw
python -m hoops_gm.ingest.backfill season 2025-26 --with-participation
```

**Run it from that directory.** `RawPayloadStore` resolves its path against the
*current working directory*, not the repo root — the opposite of the database,
which the validator anchors. Launching from anywhere else silently detaches the
cache and re-fetches everything at ~1.1 s per request with nothing saying why.

Resuming is just re-running: commits are per game, participation upserts on
`(game_id, player_id)`, and cache hits skip the throttle entirely.

**Capture stdout per slice.** Per-game failures are collected and printed at the
end of *that invocation* and persisted nowhere, so two interruptions give three
disjoint failure lists and no union.

---

## Why the data is not committed and this file is

The split is deliberate and predates this document: **the repository holds the
evidence about the data — manifests, censuses, fingerprints — never the data.**
No vendor payload and no live capture is ever committed.

What went wrong was not the split. It was that the *evidence* side of it was
never written down either, so the store's existence lived only in an
un-versioned `README.md` inside the store's own directory — reachable only by
someone who already knew where to look, and therefore invisible to exactly the
search that needed it.
