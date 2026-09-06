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

## Pushing to origin, which does not work the obvious way

`git push` fails with:

```
remote: Permission to SR2501/hoops-gm.git denied to steverones_microsoft
fatal: ... HTTP 403
```

**The cause is not the repository and not `gh`.** The runtime injects a
**command-scope** credential helper into every git invocation:

```
> git config --show-scope --get-all credential.helper
system   manager
command  copilot
```

That `copilot` helper authenticates as a Microsoft-tenant account with no write
access here. **Command scope outranks system, global and local**, so nothing you
put in `.git/config` can override it — a local `credential.helper` reset looks
correct, resolves correctly under `git config --get-all`, and still loses. Only a
*later* command-line `-c` wins.

**The form that works:**

```
git -c credential.helper= -c "credential.helper=!gh auth git-credential" push -u origin HEAD
```

The leading empty `-c credential.helper=` is **required**; it resets the helper
list. Passing only the `gh` helper still fails, because the injected helper runs
first and a helper that returns credentials ends the search.

`gh` itself is authenticated as `SR2501` with `repo` scope, so **`gh pr create`,
`gh pr merge` and every other `gh` command work normally.** Only raw `git push`
is affected.

**Do not use `git ls-remote` to check push access.** This repository is public,
so it succeeds for anyone with no credentials at all. It was used as a
verification on 2026-09-06 and confirmed nothing — the same shape as a green
test that passes for a reason unrelated to what it claims. Use
`git push --dry-run` with the incantation above, which actually authenticates.

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

### The way appending to `docs/handoff.md` actually goes wrong

The rule above says *do not edit past entries*. That is not the failure anyone
has actually had. On 2026-09-05 **three of three independent agents**, working
separately and each intending only to append, produced the same incident: a
whole-file text write through an ordinary editing tool **silently normalised
historical CR bytes** in a legacy block, turning a ~31-line append into a diff
of 150–184 deletions and 183–329 insertions, and breaking the append-only
byte-prefix contract that `scripts/check_append_only.py` enforces.

Nobody edited a past entry. The tool rewrote them on the way past.

**So: never round-trip this file through a whole-file text write.** Not
PowerShell `Set-Content`, not a naive Python `open().write()`, not a patch tool
that reflows the file. Append bytes to the existing bytes:

```
git show HEAD:docs/handoff.md   # capture as BYTES, not text
# append the new UTF-8 entry bytes, write once
```

Verify with `git diff --ignore-space-at-eol` — if the semantic change is your
entry alone, the byte damage is elsewhere in the diff and must be undone. All
three agents recovered by restoring the exact `HEAD` blob and re-appending; none
used `checkout`/`reset`, which would have discarded unrelated working-tree work.

*Corollary for parallel work:* when several units run at once, have them **report**
their handoff entry and let one writer append centrally. Eight concurrent
appends to a byte-guarded, CI-checked file is a queue, not parallelism.

## The Python environment on this machine, which is not the obvious one

Confirmed independently by three agents on 2026-09-05. Each lost turns to all of
the first two before finding the working form.

- **`ruff`, `pytest` and `mypy` are not on `PATH`.** `ruff check .` fails with
  *"The term 'ruff' is not recognized"* even though the module is installed. Use
  `python -m ruff`, `python -m pytest`, `python -m mypy`. The Code gate as written
  in older prompts uses the bare names and will fail on the first command.
- **There is no virtualenv, and an editable `.pth` points at a deleted worktree.**
  A focused test run fails at `conftest.py` import with
  `ModuleNotFoundError: No module named 'hoops_gm.app'`. Two working fixes:

  ```
  cd backend; $env:PYTHONPATH = (Resolve-Path 'src').Path    # per-shell, no side effects
  cd backend; python -m pip install --quiet --editable .      # repairs the install
  ```

  Prefer the `PYTHONPATH` form in a parallel run — repointing a shared editable
  install changes the environment underneath every other lane.
- **Python 3.12 is present and is a trap.** It has `pytest` and `ruff` but **no
  `mypy`**, and its legacy `httpx` turns a Starlette deprecation warning into an
  error at import. Use 3.14.
- **The full backend suite takes 18–19½ minutes** (~2,600 tests). Budget for it;
  it will exceed a default wait window several times. This is why the gate should
  be run once, deliberately, and not casually re-run to "check".

*Why this is in the runbook rather than a comment:* an import error from a stale
editable install is indistinguishable from a real failure, and it has already
caused one agent to report two complete mutation matrices that were entirely
`ModuleNotFoundError` scored as passes — see `docs/governance/coordinator-register.md`.
