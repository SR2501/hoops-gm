---
name: standup-hoops-gm
description: hoops-gm specifics for the standup skill — where this project keeps its rules, what its gates are, how to bring the demo up, and what its hard deadline is. Use alongside the generic standup skill when running a standup, daily update, status report or fan-out plan in this repository.
---

# hoops-gm standup addendum

Read this **with** the generic `standup` skill, not instead of it. That skill
carries the method; this file carries only the facts about this project that the
method cannot discover on its own.

Everything below is checkable in under a minute. If any of it is wrong, fix it
here rather than working around it.

## Where this project keeps its rules

| What | Where |
|---|---|
| The brief, and the four things that make this project unusual | `AGENTS.md` |
| Full plan, including research findings that constrain it | `docs/plan.md` |
| The four gates | `docs/governance/gates.md` |
| Risk register | `docs/governance/risks.md` |
| Who owns what | `docs/governance/ownership.md` |
| What only the owner may decide | `docs/governance/owner-decisions.md` |
| Which model to run a lane on | `docs/governance/model-selection.md` |
| Decisions, with amendments | `docs/decisions/` |
| Task list with dependencies | `docs/backlog.md` |
| Append-only work log | `docs/handoff.md` |

## The gates, for the fan-out plan

Every unit names the gate it must pass. Details in `gates.md`; do not
paraphrase them from here.

- **Code** — all code.
- **Adapter** — anything calling an external source.
- **Model** — anything producing a number a decision rests on. Calibration, not
  accuracy.
- **Automation** — anything in the write path. Independent `safety` sign-off,
  and `safety` never reviews its own work.

Gates are cumulative where work spans types.

## Owner agents

`architect`, `data-engineer`, `quant`, `backend`, `frontend`, `bridge`,
`safety`. Definitions in `.github/agents/`. One child session per PR-sized unit,
owned by the matching agent, with exact-head reviews from a *different* agent.

**Choosing the model for each lane** is `docs/governance/model-selection.md`.
Read it there rather than from memory — it is a standing file that gets updated,
and the two dated `model-*-2026-09-05-*.md` files beside it are frozen evidence,
one of which is confounded. The short version is that the default is unchanged
and the lanes differ on speed, cost and one judgment item — **not** on whether
the work came out right, where five models were indistinguishable.

## The hard deadline

**Sunday 18 October 2026** — draft day, auction format. It does not move
(`docs/plan.md:4`). Phases 0–5, 8 and 9 are the deadline set. Rehearsal is a
deliverable, not slack. When something slips, protect the spine and the
rehearsal and cut features.

The spine is ordered and load-bearing:
**player identity → schedule → availability → projections → valuation.**

## Bringing the demo up, for the visible-progress step

The dashboard is not a background service; it is started by hand and dies with
the machine. Confirm by request rather than by assumption.

```
backend   http://127.0.0.1:8000/health
frontend  http://127.0.0.1:5173/schedule
```

**5173 is Vite's default, not a guarantee. Read the port Vite actually printed.**
When 5173 is taken, Vite silently increments — 5174, then 5175 — and the runbook
number is then wrong for that run. Worse, a *stale* dev server can hold 5173 on
`::1` only, so `127.0.0.1:5173` is refused while `netstat` still shows something
listening. Observed on 2026-09-06: an orphaned listener on `::1:5173` with the
live dashboard actually serving `127.0.0.1:5174`.

To check rather than guess:

```
Get-NetTCPConnection -State Listen -LocalPort 5173,5174,5175 |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

An entry whose `LocalAddress` is `::1` and not `127.0.0.1` will refuse an IPv4
probe. **The number is not swapped in above deliberately** — pinning this file to
one machine's incidental port is the same error as the `8010` note below.

**8000 is not arbitrary and changing it breaks the frontend.** `vite.config.ts`
proxies both `/api` and `/health` to `http://127.0.0.1:8000` unless
`VITE_API_PROXY_TARGET` says otherwise, so a backend on any other port leaves
every screen unable to reach its data. If you must move it, move both.

*(This line read `8010` until 2026-08-28. That port came from a single run
recorded in `docs/handoff.md`, in an entry that says of itself "that is not how
anyone else will run it" — an atypical one-off lifted into the canonical
runbook. Following it produced a health check that reads DOWN on a working
dashboard, and a dashboard that could not load anything.)*

If it is down, the seed runs entirely from committed fixtures and reaches the
same screen:

```
cd backend
$env:PYTHONPATH="$PWD\src"
python -m hoops_gm.dev.seed_schedule_grid --database-url "sqlite+pysqlite:///../schedule_grid_demo.db"
```

**To load the real season instead**, pass `--fixtures-dir` pointing at a
directory holding a live `ScheduleLeagueV2` payload and the static team list.
That directory is **deliberately outside the repository** — no vendor or live
payload is ever committed. The seed itself is unmodified production code, which
is the point: a demo that took a shortcut around the real importer would prove
nothing.

Sanity numbers for the real 2026-27 season, so a wrong screen is obvious:
**1,206 games published, 1,200 imported, 6 pending, 30 teams, 25 periods,
2,400 team-games.**

## The customer rule

**The next increment must put something useful in the browser.** A unit that
cannot name the screen or the draft behaviour it unlocks is deferred. This tool
complements paid Basketball Monster projections; it does not rebuild them.

## Two standing traps in this repository

- **`docs/handoff.md` is append-only.** Never edit an existing entry to agree
  with a later decision — correct what asserts the present, append to what
  records the past.
- **`docs/backlog.md`'s header is derived.** Recount headings against markers
  from the finished file. Reconciling two headers after a merge cannot produce
  the right answer.
