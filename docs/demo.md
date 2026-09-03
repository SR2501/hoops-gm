# Running the demo

**One command, one fresh throwaway database, one URL, every primary tab.** If
you have never seen this repository before, this page is enough.

The demo state used to live in separate SQLite files, and one backend serves one
file. The first composition made Draft, Schedule and Projections coexist but
left Reliability unpublished. `hoops_gm.dev.seed_demo` now builds every
required cohort atomically, and `scripts/run_demo.py` creates a fresh ephemeral
database, starts the backend and Vite, and keeps them behind one browser URL.

---

## Quick start

Nothing here calls an external data source. Install the repository dependencies
once; in particular, `frontend/node_modules` must already exist.

```powershell
python scripts\run_demo.py
```

Open the one URL the launcher prints (normally
**`http://127.0.0.1:5173`**; it chooses an unused loopback port if 5173 or the
backend's 8000 is already occupied). Dashboard, Draft, Schedule, Projections,
Reliability and System all have row-bearing or health-bearing non-error states.
Open the auction draft and follow **League categories**, or go directly to
`/draft/1/categories`. Press Ctrl+C to stop both services; the temporary
database is then deleted.

The lower-level seed remains available for tests and manual serving:
`cd backend; $env:PYTHONPATH="$PWD\src"; python -m
hoops_gm.dev.seed_demo --database-url "sqlite+pysqlite:///../demo_all.db"`.
If you override its `--cohort-size`, it must be at least **7** because the
auction demo has seven planned lots.

---

## Four things that will cost you an hour each

**`DATABASE_URL`, not `HOOPS_GM_DATABASE_URL`.** `Settings` declares no
`env_prefix` and sets `extra="ignore"`, so a prefixed name is not rejected — it
is *silently discarded* and the service falls back to the default
`sqlite:///./hoops_gm.db`. There is no error, no warning and no log line saying
the value was dropped. Worth noticing that the fallback is not harmless:
`hoops_gm.db` is also where the owner's real local database lives.

What you actually see then depends on what that other database holds, and the
three symptoms mean different things. All three driven 2026-08-23:

| what the database holds | `/draft` | `/schedule` | `/projections` |
|---|---|---|---|
| a file with no schema | `OperationalError` | `OperationalError` | `OperationalError` |
| schema, no rows | `200`, empty list | `404` `schedule_grid_league_not_found` | `404` `projections_league_not_found` |
| only the draft seed | `200`, both mocks | `409` `schedule_grid_not_current` | `409` `projections_source_not_imported` |

The first row is what an empty `.db` file gives you, because SQLite creates the
file and nothing creates the tables. It was observed through `TestClient`, which
re-raises rather than rendering, so a real server answers it as a `500`.

**The third row is the original symptom, reproduced from empty.** A backend
pointed at the *draft* database finds league 1 — a `[demo] ` mock configuration
— so the two other screens get past the league lookup and fail on lineage that
database never had. That is why it was a working draft board beside two `409`s
rather than two `404`s: `409` means *this league exists and its schedule was
never seeded here*, which is precisely the partially-composed state `seed_demo`
exists to make impossible.

**The dashboard reads league 1, from a constant.** `SchedulePage.tsx` and
`ProjectionsPage.tsx` both hardcode `LEAGUE_ID = 1`; neither takes it from a
route or a picker. On a fresh database the seed's schedule league is inserted
first and so *is* league 1, which is why the seed prints
`frontend_expects_league_id` — a database where that came out otherwise serves
two 404s and no explanation.

**The dev server proxies `/api` to `127.0.0.1:8000`** (`vite.config.ts`). A
backend on any other port is not the one the dashboard is talking to.

**Check the server's build before checking the data.** A process started before
a route existed keeps answering `200 ok` on `/health` while 404-ing that route.
Health is not evidence the build is current.

---

## What "working" looks like

The seed prints its own proof, grouped by screen:

```json
{
  "schedule_screen":    { "league_id": 1, "season": "2026-27" },
  "projections_screen": { "cohort_size": 60, "projections_written": 60,
                          "identities_accepted": 60, "identities_unresolved": 0 },
  "reliability_screen": { "season": "2025-26", "scorecards": 2,
                          "final_games": 3, "player_game_logs": 4,
                          "participation_rows": 2 },
  "draft_screen":       { "auction_selections": 7, "snake_selections": 12 },
  "frontend_expects_league_id": 1
}
```

Against the committed fixtures the database holds **30 teams, 10 imported games
(12 published, 2 pending), 21 scoring periods, 20 team-games, 60 projection rows
and 2 mock drafts** for the 2026-27 portal context. The Reliability context is a
separate, deliberately tiny **2025-26 synthetic cohort: 2 named synthetic
players, 3 final games, 4 box-score rows and 2 non-play observations**. The
System tab reports backend/database readiness from that same process.

The composed auction selects seven canonical players from that exact synthetic
projection import, through the production nomination/sale/void writers. The
category detail therefore says **7 of 7 selections joined**, and the seven seats
holding one player render visible **1-to-7 per-game-rate rankings**. The player
names are real only because the identity join requires canonical IDs; every
projection value, selection, seat and price remains synthetic, and the page
continues to say this is not expected performance. A composed cohort shorter
than those seven planned lots refuses before any draft write; it never returns
a successful partial board.

Reliability is descriptive only. Its player names begin `[synthetic demo]`, its
schedule lineage begins `synthetic-demo:`, and the screen renders a prominent
disclosure that every game, box score and play/non-play observation is invented
only to exercise the interface. Observation lineage identifies the unchanged
production writer chain; the synthetic origin is carried by the schedule source
and disclosure rather than adding another dynamically sourced refresh call.
The demo emits no reliability grade, projected games, recommendation, calibrated
availability, or `p(play)`.

**Do not test a screen by scanning it for error words.** A scan for
`could not|cannot|failed|no current` returns **true on two working screens**:
`/schedule` legitimately renders *"this season is not fully scheduled"* — the
ADR-013 pending-games affordance, which the demo deliberately exercises — and
`/projections` renders *"we have not computed our own projections yet"*, which
is true and correct, because blended projections are a later phase. Count rows.
Assert the presence you expect.

Backing that up, `backend/tests/test_seed_demo.py` drives Schedule, Projections,
Draft and Reliability against **one** seeded database, then combines the auction
state and current-projections responses exactly as the category page does. It
asserts concrete row counts, the exact projection-import ID set, joined-player
and ranked-seat counts, synthetic Reliability names, and synthetic lineage.

---

## What the seed refuses, and why none of it is a bug

Every seeder here refuses before writing anything, on four separate signals.
Three protect a database you care about; one protects the demo's own honesty.

**Any `player_participation` row outside the unified demo's exact markers.**
The unified seed writes two synthetic non-play rows through the production
participation importer. The guard allows only those exact synthetic game ids,
the reserved synthetic NBA anchor, and the explicit synthetic raw comment.
Anything else still proves a real ingest happened.

**Any `nba_games` row for a season other than 2026-27, outside the three exact
synthetic Reliability game ids.** The additional 2025-26 cohort is narrow and
self-identifying; another foreign-season game still refuses.

**Any league, or any 2026-27 game, this seed did not create.** The original
guard. `nba_games`, `team_schedule` and the `nba-schedule` refresh are global
and season-scoped with no league dimension, so a ten-game fixture aimed at a
working database would become the registered cohort for every consumer.

**Any projection import, or current Basketball Monster crosswalk entry, it did
not create.** Otherwise the demo cohort becomes newest-for-source and retracts
every real `player_external_ids` row.

### The first two were added on 2026-08-23, after a real store slipped through

The owner's local database lives at `hoops-gm-data/hoops_gm.db` — outside every
checkout, because `core/config.py` anchors a relative SQLite path to each
worktree's own root. It holds **0 leagues** and **1,230 games, all 2025-26**,
beside a 43,037-row participation ledger.

Both of those numbers defeat the original guards: one keys on `leagues`, the
other only on *this* season's cohort. Driven against a migrated copy, the
composed seed exited **0** and wrote 3 leagues, 2 drafts, 10 synthetic 2026-27
games and 60 `synthetic-demo-*` rows that became the current Basketball Monster
crosswalk.

The real store escaped only because its schema sits at `0016`, so `seed_drafts`
crashed on a missing `drafts` table and the transaction rolled back. **That is
protection by accident.** Migrating the store would have removed it, and more
code is about to read that store.

Note what this does *not* claim. SQLite creates a database file on connect
rather than refusing, so a **mistyped** path still yields a new empty file and a
seeded demo in a place you did not intend — that is harmless but confusing, and
the seed prints the URL it used so you can see where it went. What is now
prevented is the case that actually costs something: seeding *into* a real
store. If a refusal names a league or a store you recognise, it just saved you.

---

## Reproducible from empty, not idempotent
Running `seed_demo` a second time against its own output **refuses**, and the
message names a league:

> *this database already holds league 2 (None, season '2026-27'), which this
> seed did not create.*

That is correct and it is not about your data. The draft seed creates two
`[demo] ` leagues with `fantrax_league_id IS NULL`, which is exactly the first
arm of `require_safe_demo_target`'s foreign-league refusal. Each seeder
converges on its own re-run; the composition does not, because the later one
leaves rows the earlier one is written to refuse.

**Delete the database file and run the command again.** The seed detects this
case — every league present was created by it — and says so, so the refusal does
not read as "you nearly lost your season".

The refusal that *is* about your data looks identical apart from the league it
names. If it names a league you created, the seed has just stopped a ten-game
fixture from becoming the registered 2026-27 cohort for every consumer of the
schedule version. Point `--database-url` somewhere else.

---

## Driving it against the real 2026-27 season

The committed schedule fixture holds 12 games, which is enough to prove the
grid renders and nothing about how it behaves at scale. To drive the real
season you supply the capture yourself: **no vendor payload is ever committed**,
so this needs a directory outside the repository.

`--fixtures-dir` is a **single** directory and the seed reads **all four**
fixtures from it. Assemble it:

| file | where it comes from |
|---|---|
| `nba_scheduleleaguev2_2026_27.json` | your own live `ScheduleLeagueV2` capture |
| `nba_static_teams.json` | your own capture, or the committed one |
| `nba_commonallplayers_current.json` | copy from `backend/tests/fixtures` |
| `nba_playerindex_current.json` | copy from `backend/tests/fixtures` |

```powershell
cd backend
$env:PYTHONPATH = "$PWD\src"
python -m hoops_gm.dev.seed_demo `
  --database-url "sqlite+pysqlite:///../demo_full.db" `
  --fixtures-dir <that directory>
```

Sanity numbers, so a wrong screen is obvious: **1,206 games published, 1,200
imported, 6 pending, 30 teams, 25 scoring periods, 2,400 team-games** — beside
the same 60 projection rows and 2 mock drafts as the quick start.

### The limit, stated correctly

An earlier reconstruction of this workflow recorded that *real-scale schedule
and projections cannot share a database*, on the strength of this refusal:

> *refused: this database already holds 2026-27 game `0022600004`, which is
> outside the fixture cohort. Refusing before any write rather than after.*

**That refusal is real and that conclusion is wrong**, and the difference
matters because one of them reads as a design limit and the other is a
missing file.

The guard compares what is in the database against **the cohort the seed just
parsed**. It fires when the schedule seed runs against the real payload and the
projection seed is then run against the *committed* one — two different
cohorts, correctly refused. Give both the same `--fixtures-dir` and the cohort
agrees, because it is the same cohort. `seed_demo` passes one `--fixtures-dir`
to everything for exactly this reason.

Driven on 2026-08-23: one database holding **1,200 imported 2026-27 games,
2,400 team-schedule rows, 30 teams, 25 scoring periods, 60 projection rows and
2 drafts**, seeded by one `seed_demo` invocation, exit 0. The schedule version
was byte-identical to the real-season-only seed's (`e80a3aecca0e86eb`), which is
what says the cohort really is the full season and not something narrowed to get
past a check.

**That fingerprint was then confirmed from the other end.** A second lane
pointed a backend at a composed real-season database and read the screens in a
browser: `/schedule` **30 rows, 832 cells** (against 704 on the ten-game
fixture), `/projections` **60 rows, 1,140 cells**, `/draft` both mocks listed —
and the schedule version rendered on screen as `e80a3aecca0e86eb`. Two
independent paths, one fingerprint. The pending-games affordance also appeared
against real data for the first time, which is the six unassigned Emirates NBA
Cup games showing up as *"this season is not fully scheduled"* rather than as a
silently short count.

**Nothing about the guard changed, and nothing about it should.** It was
satisfied honestly rather than bypassed. If you find yourself editing
`require_safe_demo_target` to make a demo work, the demo is claiming a cohort it
did not build.

### What this does and does not claim

**The projections are still invented.** All that changed is which schedule they
sit beside. Sixty synthetic rows against a 1,200-game season is still sixty
synthetic rows; `original_filename` says `synthetic-projections-demo.csv` and
every crosswalk id carries the `synthetic-demo-` prefix. Only the *names* are
real, and they have to be — Basketball Monster publishes no team and no position
column, so a name is the only evidence the identity resolver has.

**A real-season demo database looks much more like a production one.** The
schedule half of it genuinely is real: 1,200 imported games, real dates, real
team assignments. The refusals protect a real database from being *seeded into*;
nothing stops a person mistaking a seeded database for a real one. Name the file
so you can tell, and do not put it where the service would find it by default.

---

## Where the pieces live

| module | what it seeds | composed by |
|---|---|---|
| `hoops_gm.dev.seed_schedule_grid` | teams, games, scoring periods, deadline calendar | `seed_projections` |
| `hoops_gm.dev.seed_projections` | the above, plus players, positions and the synthetic cohort | `seed_demo` |
| `hoops_gm.dev.seed_reliability_demo` | three synthetic final games, two synthetic players, four box scores, two non-play rows and the published descriptive claim | `seed_demo` |
| `hoops_gm.dev.seed_draft` | two mock drafts, through the real recorders; standalone names stay unresolved, while `seed_demo` may supply typed canonical auction players | `seed_demo` |
| `scripts/run_demo.py` | an ephemeral database plus backend and Vite lifecycle | operator entry point |

Running `seed_schedule_grid` before `seed_projections` is **redundant, not
required** — `seed_projections` already calls it. It is harmless, and a runbook
listing it as a mandatory first step is describing a constraint that does not
exist.

Running `seed_draft` **last** is required, and it is the only ordering
constraint here. Its `[demo] ` leagues are what the schedule seed refuses, so a
database seeded drafts-first can never have the other two screens seeded into it
at all.

`seed_demo` runs the whole composition in **one session**, so a refusal from the
draft seed rolls the schedule and projection writes back with it. Composing at
the shell instead — three processes, three transactions — is what produced the
half-seeded files this page replaces: the schedule commits, the draft seed
refuses, and you are left with a database that is neither empty nor usable and
no signal saying which.

Schema is built with `Base.metadata.create_all`, not Alembic, so a demo database
is model-built rather than migration-built. Fine for a throwaway file, wrong for
anything else — the migration tests exist to catch exactly that divergence.

`*.db` is gitignored. A **relative** SQLite path is anchored to the repo root
rather than the working directory (`Settings._resolve_relative_sqlite_path`), so
`sqlite:///./demo_all.db` run from `backend/` lands at `<repo>/demo_all.db`.
