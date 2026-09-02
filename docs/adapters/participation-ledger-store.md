# The participation ledger store

**The ledger is populated. It is not in this repository, and it is not in any
worktree.** The active four-season direct-observation store lives at
`C:\Users\steverones\hoops-gm-data\participation-ledger-direct-2022-26.db`, a
sibling of the main checkout. The prior three-season store is preserved
byte-for-byte at
`C:\Users\steverones\hoops-gm-data\participation-ledger-direct-2023-26.db`.
The original one-season store remains unchanged at
`C:\Users\steverones\hoops-gm-data\hoops_gm.db`; its SHA-256 is
`09ab985caa3ab5ffb3ae5546afb15a37b2e4d1f94e6dc762fb338faf2c63b181`.

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
$env:DATABASE_URL = "sqlite:///C:/Users/steverones/hoops-gm-data/participation-ledger-direct-2022-26.db"
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

Add `--json` for the machine-readable form. Both public forms withhold outcome
and reason marginals while the injury-status-conversion protocol remains
blinded; no flag exposes them. The committed current censuses start with that
safe measured output, then add raw-capture and run-log digests, source-ID
reconciliation, outages, and a production-only audit. The off-repository
generator is
`C:\Users\steverones\.copilot\session-state\8788c8d4-d28e-4bd0-aaee-0c2c3dc1da94\files\build_participation_census_safe.py`;
regenerating with the database, raw root, season, code revisions, and named run
logs is how you check this document rather than trusting it.

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
cached in `hoops-gm-data\data\raw`, keyed by URL, and a completed game's per-game
box scores never expire. A replay therefore makes no per-game requests and runs
at disk speed. `LeagueGameFinder` and `PlayerGameLogs` use a 12-hour cache and
may each make one fresh season-level request after that window; "a replay costs
no requests" was too broad.

```powershell
$env:DATABASE_URL = "sqlite:///C:/Users/steverones/hoops-gm-data/participation-ledger-direct-2023-26.db"
cd C:\Users\steverones\hoops-gm-data          # raw store resolves to .\data\raw
python -m hoops_gm.ingest.backfill season 2025-26 --with-participation
```

Never point this command at the preserved original `hoops_gm.db`; rebuild into
the active multi-season copy or a new copy. **Run it from that directory.**
`RawPayloadStore` resolves its path against the
*current working directory*, not the repo root — the opposite of the database,
which the validator anchors. Launching from anywhere else silently detaches the
cache and re-fetches everything at ~1.1 s per request with nothing saying why.

Resuming is just re-running: commits are per game, participation upserts on
`(game_id, player_id)`, and cache hits skip the throttle entirely.

**Capture stdout per slice.** Per-game failures are collected and printed at the
end of *that invocation* and persisted nowhere, so two interruptions give three
disjoint failure lists and no union.

---

## Addendum, 2026-08-31: what an opportunity denominator would need, checked rather than assumed

`docs/models/reliability-metrics.md` ships `coverage_status=incomplete_r35` /
`opportunity_coverage=null` and states the merged data lacks "authoritative
historical roster intervals and proof that every game returned a complete
participation payload." This addendum re-derives that verdict against the live
store above instead of trusting it, for `docs/backlog.md`'s
`participation-opportunity-coverage`, and it holds — with three findings that
were not on record before.

**No NBA-side roster-interval or transaction table exists in this schema.**
`rosters`, `roster_slots` and `transactions` each carry a
`fantasy_team_id`/`league_id` foreign key into the Fantrax league tables — they
are a fantasy owner's roster, not NBA team membership — and nothing else names
an NBA roster window. `team_schedule` is empty (0 rows) here too, by the
deliberate choice above to keep `ScheduleLeagueV2` out of the tip-off
cross-check, but that specific absence is not load-bearing: which games a team
played reconstructs cleanly from `nba_games.home_team_id`/`away_team_id` alone —
checked, all 30 teams show exactly 82 games each for 2025-26.

**A season-long injury absence does not, by itself, vanish.** Damian Lillard
(`player_id=2751`, team 21) carries a row — mostly `inactive` — for **all 82**
of his team's games with zero gap, which is the ledger behaving exactly as the
thesis needs it to. But three players show a multi-game silence the ledger's
own recorded 2025-11-19 outage (`0022500259`/`260`/`261`, above) does not
explain: **Mike Conley** (`player_id=893`) has zero rows of any outcome for
five straight team-14 games (2026-02-04..02-11) while 18 teammates have rows in
that same window — a player-specific silence, not a source-wide one, with no
explanation anywhere in this store; **CJ Huntley** (`player_id=2154`) is
silent for 46 straight team-20 games (2025-11-18..2026-02-26, bookended by real
`inactive` rows on 2025-11-16 and 2026-03-03); **James Wiseman**
(`player_id=5109`) carries a row for only **6 of team 18's 82 games all
season** — three at the start (2025-10-23, 10-25, 10-26), silence for the next
24 straight games (2025-10-29..2025-12-18), three more (2025-12-20, 12-22,
12-23), then silence for the remaining 52 games through the season's end, never
resolving. **CORRECTED 2026-08-31 after independent review**: an earlier draft
of this addendum stated Wiseman's gap as "23 straight games,
2025-10-29..2025-12-18" as if that fully described him, which undercounts the
first block by one game and omits the second, larger 52-game silent block
entirely — the shape is closer to "present for one road trip in October, one in
December, invisible the rest of the season" than to a single bounded absence.
**NARROWED 2026-08-31 by architect ruling, on independent cumulative review**:
this addendum previously read Huntley's and Wiseman's earlier segments as
"matching a two-way/G-League assignment window" and treated the zero-`g_league`
finding below as confirming that mechanism structurally. That overclaimed. What
is verified is only that zero of the season's 43,037 rows carry
`reason='g_league'` and that no `raw_comment` in the store matches the
substrings `parse_participation_comment` checks for (`"g league"`, `"g-league"`,
`"two-way"`, `"assignment"`) — this store's detector for that one cause never
fires, this season. **That does not establish what caused any of the three
gaps**: no dated, independent assignment or transaction record exists anywhere
in this store for Conley, Huntley or Wiseman, so a G-League optioning, an
unreported absence, a capture defect, or something else are all equally
unruled-out. What survives, and is the actual finding this addendum supports,
is narrower: player-specific silence exists, for reasons this store cannot
determine, and it is invisible to the coverage tool below.

**`hoops_gm.availability.coverage.measure_coverage` cannot see any of this.** It
counts a game as observed the moment *any* participation row references it, so
all three windows above report as fully observed — player-level completeness is
currently unmeasured by anything committed. And `inactive_list_available=True`
(all 43,037 rows here) certifies only that the source's `inactives` key was
present, per `parse_box_score_summary_v3`'s own contract — not that the named
list was exhaustive. Conley's window is the existence proof that the two claims
differ: the key is present (his teammates resolve normally) and he is still
absent from it entirely.

**Cheapest source discussion, corrected 2026-08-31 by architect ruling on
independent review.** This addendum previously called `CommonTeamRoster` a
"current-snapshot endpoint with no historical form," concluded from enumerating
`nba_api`'s endpoint submodules without calling it. That was wrong: installed
`nba_api` **1.11.4**'s `CommonTeamRoster(team_id, season=..., ...)` accepts a
`season` parameter and returns a genuinely different roster per season —
independently verified with a single throttled live call pair (one team,
`season="2025-26"` vs `"2024-25"`: 18 players each, 8 IDs present in one season
and absent from the other). It is **season-scoped**, not current-only. What it
lacks is a **structured, per-player effective-date field**: its headers are
`TeamID, SEASON, LeagueID, PLAYER, NICKNAME, PLAYER_SLUG, NUM, POSITION,
HEIGHT, WEIGHT, BIRTH_DATE, AGE, EXP, SCHOOL, PLAYER_ID, HOW_ACQUIRED`, none of
them dated by contract. **CORRECTED 2026-08-31 by architect ruling, on a
second independent cumulative review**: an earlier version of this sentence
said `HOW_ACQUIRED` carries "no date." Re-checked directly: it is null for
some rows (3 of 18 on the checked team) and, where populated, is free text
that frequently embeds a date — `"Signed on 03/03/26"`, `"Traded from PHI on
02/09/23"`, `"Draft Rights Traded from MEM on 06/25/25"` — alongside undated
forms like `"#7 Pick in 2022 Draft"`. So: **no structured effective-date
field, but an incomplete, sometimes-null free-text label that may contain
one.** That still falls short of within-season interval reconstruction: the
embedded date, when present, is unparsed prose with no declared format
guarantee, no coverage guarantee, and no guarantee it describes the season
being read rather than an earlier acquisition still shown on a later roster.
`CommonAllPlayers` and `PlayerIndex` are the same shape and already adapted
here (`nba-stats.md`) — existing, cheap, season-level evidence, not a reliable
within-season answer either. No NBA transactions/waiver-wire endpoint exists
in `nba_api` at all. Captured **prospectively** at a regular cadence,
`CommonTeamRoster` snapshots could bound a future roster change to the gap
between two captures, which is cheaper than a new adapter and still short of a
dated transaction record. Any implementation that calls `CommonTeamRoster` or
any other not-yet-adapted NBA endpoint requires the Adapter gate in full —
fixture, parser contract, loud live smoke — regardless of NBA already being an
existing source elsewhere in this project. An authoritative historical
transactions source is a new, currently unvetted adapter, which this addendum
names and does not select.

Reproduce these counts without a committed script — the queries were exploratory
and are not shipped as adapter code, deliberately, because no source or fit is
proposed here. The equivalent ad hoc queries are: join `player_participation` to
`nba_games` grouped by `player_id`, compare each single-team player's row count
against `COUNT(*) FROM nba_games WHERE (home_team_id=? OR away_team_id=?) AND
game_date BETWEEN <first_dt> AND <last_dt>`, and list the dates present in the
second set but absent from the first. None of this used a fitted model, a paid
source, or Fantrax access, and none of it computed a `p(play)`-adjacent
quantity.

## Why the data is not committed and this file is

The split is deliberate and predates this document: **the repository holds the
evidence about the data — manifests, censuses, fingerprints — never the data.**
No vendor payload and no live capture is ever committed.

What went wrong was not the split. It was that the *evidence* side of it was
never written down either, so the store's existence lived only in an
un-versioned `README.md` inside the store's own directory — reachable only by
someone who already knew where to look, and therefore invisible to exactly the
search that needed it.

---

## Multi-season direct-observation population, 2026-09-01

The production season command was run for 2023-24 and 2024-25 against a new
off-repository copy of the preserved 2025-26 ledger. The source and copy both
hashed to
`09ab985caa3ab5ffb3ae5546afb15a37b2e4d1f94e6dc762fb338faf2c63b181`
before the copy was changed. The original file still has that hash after the
backfill. The populated copy now hashes to
`e659f5a4156043d28408d7e58e2a211ac729f593c9dc116f1d8c4b3f2fa69ebe`
and remains at schema `0016`.

| season | direct rows | players | games with rows / final | source dates | production rows |
|---|---:|---:|---:|---:|---:|
| 2023-24 | 43,395 | 595 | 1,230 / 1,230 | 160 | 26,401 |
| 2024-25 | 43,369 | 587 | 1,230 / 1,230 | 163 | 26,306 |
| 2025-26 | 43,160 | 602 | 1,227 / 1,230 | 164 | 26,651 |

Across the store that is 129,924 direct rows, 826 distinct players and 3,687 of
3,690 final games with at least one row. **That last quantity is game-level
source coverage, not player-level opportunity coverage.** A player-game with no
row remains absent evidence, not an `unknown` row and not evidence of play or
non-play. This store still cannot prove roster membership or enumerate who
should have appeared; `participation-opportunity-coverage` owns that separate
question.

Each census is self-contained and pins the store path and hash, schema revision,
`nba_api==1.11.4`, endpoint set, ingest/census code revision, off-repository run
logs, and a digest over the exact raw-capture manifest:

- [`participation-ledger-2023-24-coverage.json`](participation-ledger-2023-24-coverage.json)
  — committed Git-blob content SHA-256
  `b158eec09b6b16df9ef044bd25a22271871ccb79a8c783c2fe563239fb8beb5a`
- [`participation-ledger-2024-25-coverage.json`](participation-ledger-2024-25-coverage.json)
  — committed Git-blob content SHA-256
  `111a6694e247895857e9f80dfd2e6cedcf4b2205017cd91857c17ab3d12a40cd`
- [`participation-ledger-2025-26-direct-coverage.json`](participation-ledger-2025-26-direct-coverage.json)
  — committed Git-blob content SHA-256
  `86b0533d31e9e1e8639127be4ced995a72382a41de069ac3581b7596592d339c`

These hashes are over the LF bytes stored by Git, read directly with
`git cat-file blob HEAD:<path>`. The corresponding CRLF working-tree byte
hashes on this Windows checkout are, in the same order,
`13dd2e9773210cd92d7da3ade3059810899dcf85fd4168cf6fac5512e0ccb6e0`,
`f8455eeb4b4834f7776f66bd98368389079bcc46e2fc370091b4b9692178eb69`,
and `4314b732b7ec3c827d6d9897042866f5f2cc980653d70095ede216f246841441`.
They describe checkout bytes only and are not the authoritative publication
identities.

The original
[`participation-ledger-2025-26-coverage.json`](participation-ledger-2025-26-coverage.json)
is preserved unchanged as the already-accepted historical disclosure. The
current three-season censuses publish no direct `PlayerParticipation.outcome`
marginal and no new outcome-keyed map. Their played-only `PlayerGameLogs` row
totals remain source-reconciliation evidence; those totals are outcome-valued,
but are neither participation fitting labels nor opportunity denominators.
Exact direct-participation marginals were computed privately from the
off-repository store and withheld under quant arbitration; reviewers who saw
them are spent for choices that could respond to those values.

The spent injury-conversion holdout was not regenerated or consumed. At the
clean publication revision, `python scripts\fingerprint_closure.py` reports 31
transitive cohort dependencies outside its declared fingerprint set, including
the changed `backend/src/hoops_gm/ingest/importers.py`. This is a provenance gap,
not evidence that the holdout changed. It remains assigned to
`cohort-fingerprint-closure-check`; this lane does not update a spent manifest
with code that did not produce it.

### What the live run found

Both new season runs fetched all 1,230 games and ended with zero source
failures. The first persistence pass nevertheless skipped 53 direct rows in
2023-24 and 55 in 2024-25. This was not a transport outage:
`CommonAllPlayers` omitted five players whom the per-game NBA payloads named by
hard NBA person ID — Charles Bediako (30 rows), Sir'Jabari Rice (23), DJ Steward
(31), Boo Buie III (23), and Erik Stevenson (1). Running `nba-identity` for the
historical seasons did not add them. The production participation importer
therefore creates a canonical NBA anchor from a previously unknown per-game NBA
person ID and stated name before writing participation. The cached replay
created five anchors and all 108 rows. A subsequent raw-to-ledger audit found
the inherited 2025-26 store had the same defect: 123 direct rows for Nikola
Djurisic (56), Eli John Ndiaye (34), Alex Toohey (25), Kyle Mangas (4), Gabe
McGlothan (2), and Tyreke Key (2). The clean publication implementation at
`50e44e5a78cb66842de699956c7ae147d1b0a85c` created those anchors without
projecting a historical game team onto `current_team_id`; the directly observed
team remains only on each participation row. All three seasons were replayed
again at that exact commit and converged with zero skipped rows. The three
summary-endpoint outages remain loud failures.

`PlayerGameLogs` remains audit evidence only and supplied no fitting label.
Private auditing found one production-log disagreement in 2023-24; it supplied
no fitting label and its outcome-valued detail is withheld. For 2025-26 the
season-level logs name 61 production rows across
`0022500259`/`260`/`261`, while
`BoxScoreSummaryV3` remains unavailable and no participation rows exist. None of
those production rows was converted into a participation label.
The three source outages remain unresolved exactly as before.

### Off-repository holdings and resumption

- Database:
  `C:\Users\steverones\hoops-gm-data\participation-ledger-direct-2023-26.db`
- Reversible pre-repair backup:
  `C:\Users\steverones\hoops-gm-data\backups\participation-ledger-direct-2023-26-before-identity-repair-20260901T174354.db`
  (SHA-256
  `674a1ba4352a88ccb32c4f61db0b85f316bc42d59d398388accbd337922059dd`)
- Reversible pre-2025-repair backup:
  `C:\Users\steverones\hoops-gm-data\backups\participation-ledger-direct-2023-26-before-2025-identity-repair-20260901T182610.db`
  (SHA-256
  `5d0f87035850c57c4ecaa3adc48d6301f373c8cfe620edc317f606b67dff26f3`)
- Reversible pre-current-team-correction backup:
  `C:\Users\steverones\hoops-gm-data\backups\participation-ledger-direct-2023-26-before-current-team-correction-20260901T183500.db`
  (SHA-256
  `fc8d1b34f340011c0d3a59ef261265eacd1d4ae608c2af6a67b8d324475ed3e5`)
- Raw captures: `C:\Users\steverones\hoops-gm-data\data\raw`
- Run logs: `C:\Users\steverones\hoops-gm-data\logs`

Resume or re-audit from the data directory so `data\raw` resolves to the same
cache:

```powershell
$env:PYTHONPATH = "C:\path\to\hoops-gm\backend\src"
$env:DATABASE_URL = "sqlite:///C:/Users/steverones/hoops-gm-data/participation-ledger-direct-2023-26.db"
cd C:\Users\steverones\hoops-gm-data
python -m hoops_gm.ingest.backfill season 2023-24 --with-participation
python -m hoops_gm.ingest.backfill season 2024-25 --with-participation
python -m hoops_gm.ingest.backfill season 2025-26 --with-participation
python -m hoops_gm.availability.coverage --json
```

To regenerate a current census, invoke the safe generator path named above with
positional arguments
`DATABASE RAW_ROOT SEASON INGEST_COMMIT CENSUS_COMMIT OUTPUT`, pass each path
already recorded in that census's `provenance.run_logs` as a repeated `--log`,
and pass the recorded original-store hash through `--original-store-sha256`.
The generator has no option to serialize marginals. Each census pins the
generator's own SHA-256 as well as the repository code revision.

The first two season manifests each hold 1,230 traditional box scores, 1,230
summary box scores, one `CommonAllPlayers`, one `LeagueGameFinder`, and one
`PlayerGameLogs` capture. The 2025-26 manifest holds 1,230 traditional and 1,227
summary captures plus the three season-level captures; its missing summary
requests are the three game IDs above. No raw payload, live database or run log
is committed.

---

## Four-season preregistration support expansion, 2026-09-02

The owner-accepted availability preregistration requires a direct-ledger census
for 2022-23 through 2025-26. The 2022-23 season is historical Marcel support
only; this unit did not enumerate opportunities, classify silence, or fit a
model.

The completed 2023-26 artifact was measured before work and remains unchanged:

- path:
  `C:\Users\steverones\hoops-gm-data\participation-ledger-direct-2023-26.db`
- bytes: `40,513,536`
- SHA-256:
  `e659f5a4156043d28408d7e58e2a211ac729f593c9dc116f1d8c4b3f2fa69ebe`

It was copied to the truthfully named active store and backed up before the
first write:

- active store:
  `C:\Users\steverones\hoops-gm-data\participation-ledger-direct-2022-26.db`
- active bytes: `52,932,608`
- active SHA-256:
  `93d2b607c2274586067a4e7a6422c1d05057adc021824ddb5ddc0a5f5d1a245a`
- schema: `0016`
- pre-write backup:
  `C:\Users\steverones\hoops-gm-data\backups\participation-ledger-direct-2022-26.pre-2022-23-20260902T040259Z.db`
- backup SHA-256:
  `e659f5a4156043d28408d7e58e2a211ac729f593c9dc116f1d8c4b3f2fa69ebe`
- pre-work manifest:
  `C:\Users\steverones\hoops-gm-data\backups\participation-ledger-direct-2022-26.prework-20260902T040259Z.json`

No migration ran. Exactly one writer used the active store at a time.

### 2022-23 measured result

| season | direct rows | players | games with rows / final | source dates | production rows |
|---|---:|---:|---:|---:|---:|
| 2022-23 | 40,932 | 554 | 1,230 / 1,230 | 164 | 25,894 |

The production pass created those rows with zero skips and zero source
failures. The final cached replay reported `0 created / 40,932 updated / 0
skipped`; game and production rows likewise converged at `1,230` and `25,894`.
All 554 direct-ledger players are present in the recorded `CommonAllPlayers`
source capture, so `recovered_source_named_anchors` is empty for this season.
The existing fixture contracts still pin the hard-ID-only recovery path and the
fail-loud nameless-ID refusal; no external-call or parser contract changed in
this unit.

The first census pass ran `nba-identity --season 2022-23` against the active
store to obtain that capture. That was wrong: `import_nba_players` treats the
source's historical `TEAM_ID`/`TEAM_ABBREVIATION` as current metadata and
changed 371 `players.current_team_id` rows plus 631 NBA
`player_external_ids.external_team` rows. A pre-repair backup preserves that
state at
`C:\Users\steverones\hoops-gm-data\backups\participation-ledger-direct-2022-26-before-identity-restore-20260902T055244Z.db`,
SHA-256
`5468882709a59e50335cd45e0aef05a8e7d8ee39a04af72462499e25ebf7a19d`.

The active store was repaired by restoring `players`, `player_external_ids`,
and `nba_teams` exactly from the preserved 2023-26 database, by primary key,
without touching any game, production, or participation row. The repair
receipt is
`C:\Users\steverones\hoops-gm-data\backups\participation-ledger-direct-2022-26-identity-restore-20260902T055244Z.json`,
SHA-256
`59c3db1b77f3941478595f47a48f003a94d994b976dfff6d41dc99aa83eaae17`.
The repair script is
`C:\Users\steverones\.copilot\session-state\a4e600b1-a630-4087-aaca-1efdfde01e8c\files\restore_participation_ledger_identity.py`,
SHA-256
`da87f9e0ca5cdd8ff79f77a0b6b97f2fa9acfa72b41f0092c8e12ea9d295352e`.
A final cached season replay still converged at `0 created / 40,932 updated /
0 skipped` and left all three identity tables exactly equal to the preserved
prior.

The source manifest contains 2,463 captures: 1,230
`BoxScoreTraditionalV3`, 1,230 `BoxScoreSummaryV3`, and one each of
`CommonAllPlayers`, `LeagueGameFinder`, and `PlayerGameLogs`. Its canonical
manifest SHA-256 is
`6179399e75f955f2a23c546cdcdce2640fde1b718322f318fad805da4eb2f27d`;
there are no missing captures or unresolved source outages. The stable game-ID
sets from both season sources and the database are exactly equal.

The committed safe census is
[`participation-ledger-2022-23-coverage.json`](participation-ledger-2022-23-coverage.json).
Its LF content SHA-256 is
`476221fcab4053832d0a62beeecbfec8b445082bb6baa9a238cba7ee363db070`.
The generator's Windows working-tree bytes use CRLF and hash to
`9f6151a271e9c2c17381cdd19aab167b55cc13024944d5082e77288f95940bf8`;
that checkout-only identity is not the published artifact identity.
It includes the four-season direct-label availability summary required by the
accepted protocol. No direct `PlayerParticipation.outcome` marginal,
opportunity-class marginal, keyed outcome, or play rate is published.
Played-only `PlayerGameLogs` source-row totals remain source-reconciliation
evidence; they are neither fitting labels nor opportunity denominators. The
pinned safe generator is
`C:\Users\steverones\.copilot\session-state\a4e600b1-a630-4087-aaca-1efdfde01e8c\files\build_participation_census_2022_23_safe.py`,
SHA-256
`591f98ccaba8a45460adc75763165d6576cedc7f35f30365390c44e8ca2eab89`.

Across the active store, the outcome-safe coverage report now measures 170,856
direct rows, 899 distinct players, and 4,917 of 4,920 final games observed. The
three unchanged exceptions remain 2025-26 games `0022500259`,
`0022500260`, and `0022500261`; silence still produces no row and no inferred
label.

### Existing-season non-regression

Before the copy was changed, all rows for each existing season were serialized
in primary-key order and hashed by table. Repeating that procedure after the
final replay produced exact equality. The direct-row SHA-256 values are:

| season | rows | logical SHA-256 |
|---|---:|---|
| 2023-24 | 43,395 | `7a95357a3ec9113255e05c410208c42c6c7fb3eae06d3f945c86aa774659b81f` |
| 2024-25 | 43,369 | `073ad5d85ac42f40bb1343477b14bd83512287c75051c84fca91047f64c6e102` |
| 2025-26 | 43,160 | `c8ff9cb04d7765e0beb8770e3904c8185bcb0ee00644b9fa310127a61d2b1ff2` |

The corresponding `nba_games` and `player_game_logs` logical hashes also match;
the complete comparison is retained at
`C:\Users\steverones\hoops-gm-data\backups\participation-ledger-direct-2022-26.post-2022-23-audit.json`,
SHA-256
`a1a256e4790d5aa933c8c45b923b5c31c61bb00c63651fd076d88e805cc30443`.
The three prior committed census files are unchanged from the Git blobs named
above.

Identity state is now covered by the same non-regression rule. The complete
table digests match the preserved prior exactly:

| table | rows | logical SHA-256 |
|---|---:|---|
| `players` | 5,224 | `210408f6e56c315c270155aa5a150c45f3ef9bbfbd7036001688b888f5d43eda` |
| `player_external_ids` | 5,224 | `185a8ed2535082c1a080729ae23100ed6fae6e67ada691c38a6ced2140166660` |
| `nba_teams` | 30 | `f117b3948146b89c7dd256eefd4767d4ed046359ca69b1032e5e8a513025d200` |

### Logs and recovery

The census pins these off-repository logs and their SHA-256 values:

- production:
  `participation-ledger-2022-23-production-20260902T040318Z.log`,
  `895feabcd5313831fab72e2b7cbd57228a0fd0b854ab2fc342a6964d1a8d2352`
- identity:
  `participation-ledger-identity-2022-23-20260902T045223Z.log`,
  `29b2fadbf42977eedf2522ca065a70fd6ba9a445e901f753c50f852d1551300a`
- final cached replay:
  `participation-ledger-2022-23-post-identity-restore-replay-20260902T055301Z.log`,
  `b5c3d66a0def822fe0d632752fccaffbbaad41e7f9a54cde2306e8a37c968680`
- identity restoration:
  `participation-ledger-2022-26-identity-restore-20260902T055244Z.log`,
  `d5fb9cab869a4bf866855965f7d136aa3a42db9c7fd7168a025b0f87deda6683`

The earlier convergent cached replay is also retained in the same directory
under `participation-ledger-2022-23-cached-replay-20260902T044845Z.log`;
its content is byte-identical to the final replay log.

To discard the expansion and recover the exact completed PR #145 artifact:

```powershell
Copy-Item `
  C:\Users\steverones\hoops-gm-data\participation-ledger-direct-2023-26.db `
  C:\Users\steverones\hoops-gm-data\participation-ledger-direct-2022-26.db `
  -Force
```

The ordinary production command is not a reproducible recovery command:
`LeagueGameFinder` and `PlayerGameLogs` expire after 12 hours and may refetch
changed upstream data. The pinned offline replayer has no network-capable
endpoint factory. Its manifest names the exact relative gzip path and
uncompressed SHA-256 for each of the 2,462 requests the season ingest consumes.
The raw manifest bytes must first match the trusted SHA-256 supplied through
the required `--manifest-sha256` argument; that comparison occurs before JSON
parsing, and the manifest does not declare its own trusted digest. Every pinned
endpoint/parameter pair must then be consumed exactly once; a repeated runtime
request is rejected before its capture bytes are returned:

- script: `scripts/replay_participation_ledger.py`
- guard-repair code commit:
  `863dffb41e3d2cd60ba0bf7d3b98cf59f12df0e2`
- committed script blob SHA-256:
  `d81ed7f5b5a14f2ec377c05f7adc99667afa884e14f7f9d14714712afb23bafb`
- pinned manifest:
  `C:\Users\steverones\hoops-gm-data\backups\participation-ledger-2022-23-pinned-replay-manifest.json`
- manifest bytes / SHA-256: `788,178` /
  `e1f0ce01578723c6ed8cb1f5c7cbde9cc5dcc09e79ac5c20f3368e0722b25a4a`
- end-to-end proof receipt:
  `C:\Users\steverones\hoops-gm-data\backups\participation-ledger-2022-23-offline-replay-proof-863dffb-20260902T075224Z.json`
- proof receipt SHA-256:
  `f468784dcd72b85f44185959230fb2f85c8edc0b49f6164c8adb20fa6b798e00`

The proof ran exact implementation commit
`863dffb41e3d2cd60ba0bf7d3b98cf59f12df0e2` and script blob
`d81ed7f5b5a14f2ec377c05f7adc99667afa884e14f7f9d14714712afb23bafb`
against a disposable copy of the preserved prior. The rebuild created 1,230
games, 25,894 production rows, and 40,932 participation rows with zero skips;
the second replay updated the same counts with zero creates and zero skips.
Comparing every non-timestamp column in all 33 tables against the active store
found zero differing tables. The SQLite files are not byte-identical because
row timestamps and file history differ; the proof claims semantic state
equality, not file identity.

The two earlier receipts remain byte-identical and distinct: predecessor
`participation-ledger-2022-23-offline-replay-proof.json` retains SHA-256
`47a9f752dfb60339c6aa85248f720955d2ac4ef318c9dd28eda7c68652734d32`,
and local review receipt
`participation-ledger-2022-23-offline-replay-proof-local-a8d5780.json` retains
SHA-256
`1309575acbfc82a51241e004df229524842749c7e1d57c191c011ce634c77682`.

To rebuild the four-season active store, first make the same preserved-prior
copy, check out the pinned replay commit, and run:

```powershell
$env:PYTHONPATH = "C:\path\to\hoops-gm\backend\src"
python scripts\replay_participation_ledger.py `
  C:\Users\steverones\hoops-gm-data\participation-ledger-direct-2022-26.db `
  C:\Users\steverones\hoops-gm-data\data\raw `
  C:\Users\steverones\hoops-gm-data\backups\participation-ledger-2022-23-pinned-replay-manifest.json `
  2022-23 `
  --manifest-sha256 e1f0ce01578723c6ed8cb1f5c7cbde9cc5dcc09e79ac5c20f3368e0722b25a4a
```

`CommonAllPlayers` is already preserved in `data\raw`; the census generator
reads it directly for stable-ID reconciliation. **Do not run a historical
`nba-identity` command against the active store.** If that capture is ever
missing, run the command against a disposable copy of the preserved prior,
verify the raw capture, and delete the disposable database before rebuilding
the active store.

Never run either recovery while another writer has either ledger open. The
pre-write backup is the independent fallback if the preserved prior path is
ever moved.
