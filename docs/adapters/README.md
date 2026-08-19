# External adapters

One page per source. Each records what the source **actually did** when it was
called, not what its documentation claims — that discrepancy is the most
valuable thing an adapter can tell you.

Every adapter must pass the **Adapter gate** (`docs/governance/gates.md`):
a recorded fixture, an offline contract test, a live smoke test allowed to fail
loudly, documented throttling and retry, and explicit behaviour when the source
is down or returns garbage.

| Source | Page | Status |
|---|---|---|
| Fantrax official `/fxea/general/` | [fantrax-official.md](fantrax-official.md) | Working, verified live |
| `stats.nba.com` via `nba_api` | [nba-stats.md](nba-stats.md) | Working, verified live |
| NBA `ScheduleLeagueV2` via `nba_api` | [nba-schedule.md](nba-schedule.md) | Working, verified live |
| NBA official injury report PDF | [nba-injury-report.md](nba-injury-report.md) | Working, verified live |
| Fantrax private `/fxpa/req` via `fantraxapi` | [fantrax-private.md](fantrax-private.md) | **Unverified** — no credentials yet |
| `cdn.nba.com` live feeds | — | **Blocked** from this network (R26); Phase 6 |

## The two halves of the gate do different jobs

A **contract test** runs offline against a committed fixture. It catches *our*
parser breaking. It cannot, by construction, catch the upstream changing — the
fixture keeps passing forever.

A **live smoke test** hits the real source. It is the only thing that can tell
us Fantrax or `stats.nba.com` moved. It is allowed to fail without blocking a
merge, but it must fail *loudly*: a warning nobody reads paints a real upstream
break green.

Both matter. The live one matters more, and is the one to write carefully.

## Refreshing a fixture

```bash
python -m hoops_gm.ingest.record_fixtures --all
```

**Never do this to make a failing contract test pass.** That defeats the entire
mechanism (ADR-006). If a contract test goes red: find out what changed, record
it in `docs/handoff.md`, and only then refresh.

## Recording what happened

Every response is captured to `data/raw/<source>/<endpoint>/<request-key>/` as
gzipped bytes, with an append-only `index.jsonl` per source. The same store is
the response cache, so a backfill re-run after a crash resumes rather than
restarts. Nothing is ever overwritten or deleted automatically — the whole
point is still having the payload from before the thing that broke.
