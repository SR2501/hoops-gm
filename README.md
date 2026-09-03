# hoops-gm

End-to-end fantasy basketball league management for the 2026–27 NBA season. Built for a head-to-head 9-category league on Fantrax.

Personal project. Not affiliated with Fantrax or the NBA.

---

## Why

Managing a competitive 9-cat league means stitching together league state, NBA stats, projections, category-aware valuation, the schedule — and, increasingly, **who is actually going to play**.

Missed games are epidemic. Load management, rest on back-to-backs, DNP-CDs, late-season shutdowns on eliminated teams, availability that swings for no stated reason. A 70-game player and a 55-game player with identical per-game lines are not the same asset, and the market still prices them as if they were.

hoops-gm models availability as a first-class quantity — `p(play)` for every scheduled game — and threads it through valuation, draft, lineup, streaming and trades.

## What it does

- **Availability engine** — per-game `p(play)`, reliability and consistency metrics, B2B sit patterns, late-season shutdown risk, and a contingent-value graph for when a player sits and someone else's stock moves
- **Valuation** — z-score and G-score, volume-weighted percentage categories, punt-build modelling, risk-adjusted values
- **Projections** — CSV import from any source, configurable blending, plus an in-house baseline model
- **Draft** — snake and auction, both first-class. Auction includes live inflation tracking, max-bid management and nomination strategy
- **Live scorecard** — category-by-category matchup state with availability-adjusted games remaining
- **Schedule intelligence** — density, back-to-backs, off-night streaming windows, fantasy-playoff-week strength
- **Lineup and trades** — optimiser, streaming recommendations, multi-asset trade evaluation
- **Fantrax bridge** — a Tampermonkey userscript that captures league data and surfaces recommendations inside the Fantrax UI

## Architecture

Python/FastAPI backend, React/TypeScript dashboard, Tampermonkey userscript bridge. Local-first — binds to `127.0.0.1`, SQLite in development with a clean Postgres seam.

Fantrax only needs to be open and foreground during a live draft and for lineup writes. Everything else runs without it.

## Status

**Phase 1 (Foundations) built.** 75 tracked work items across 14 phases; the
scaffold, backend skeleton, database foundation, dashboard skeleton and CI are
in place. No ingestion, no modelling, no automation yet.

Build order is spine-first: player identity → schedule → availability →
projections → valuation, then features. Availability comes before valuation
because it is an input to it, not an attribute of it.

## Running it

Requires Python 3.12+ and Node 20.19+.

```bash
cp .env.example .env          # fill in; .env is gitignored and stays that way

cd backend
python -m venv .venv && .venv/Scripts/activate    # source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
python -m hoops_gm            # http://127.0.0.1:8000

cd ../frontend
npm install
npm run dev                   # http://127.0.0.1:5173
```

Or the whole stack at once:

```bash
docker compose up --build
```

Everything binds to `127.0.0.1`. Nothing is exposed to the network — see
[`docs/decisions/ADR-001-local-first.md`](docs/decisions/ADR-001-local-first.md).

A fresh database has no data in it, so every screen fails closed. To get all
three working screens offline from committed fixtures, in one command against
one database:

```bash
cd backend
python -m hoops_gm.dev.seed_demo --database-url sqlite:///./demo_all.db
DATABASE_URL=sqlite:///./demo_all.db python -m hoops_gm
```

[`docs/demo.md`](docs/demo.md) is the whole runbook, including the four
environment traps that each cost an hour and how to drive it against the real
2026-27 season.

| Where | What |
|---|---|
| [`backend/`](backend/) | FastAPI service, SQLAlchemy models, Alembic migrations |
| [`frontend/`](frontend/) | React + TypeScript dashboard |
| [`userscript/`](userscript/) | Tampermonkey bridge: local pairing and read-only Fantrax capture |

## Working on this

Start with **[`AGENTS.md`](AGENTS.md)**, then **[`docs/handoff.md`](docs/handoff.md)**.

| Where | What |
|---|---|
| [`docs/plan.md`](docs/plan.md) | The full plan, including the research that constrains it |
| [`docs/demo.md`](docs/demo.md) | **How to bring the demo up.** One command, one database, three screens — plus the environment traps and the real-season path |
| [`docs/backlog.md`](docs/backlog.md) | **The task list.** Every work item with its dependencies and status; the counts live in that file's own header, recomputed from it. A task is ready when every dependency is done |
| [`docs/governance/OPEN-ci-billing.md`](docs/governance/OPEN-ci-billing.md) | Resolved 2026-08-17: the repository was made public and GitHub Actions was restored |
| [`docs/handoff.md`](docs/handoff.md) | Append-only project memory. Read before starting; append when finishing |
| [`docs/decisions/`](docs/decisions/) | ADRs — what was decided, what was rejected, what would flip it |
| [`docs/governance/`](docs/governance/) | Ownership, readiness gates, owner-only decisions, risk register |
| [`docs/models/`](docs/models/) | Model cards for anything producing a decision-bearing number |
| [`.github/agents/`](.github/agents/) | Agent definitions |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | CI enforcing the Code gate, with the Adapter and Model gates already wired |

Nothing important lives only in a chat transcript. If it is worth returning to, it is in this repository.

### Pairing the browser bridge

After starting the loopback backend, install the built userscript once —
either by opening `http://127.0.0.1:8000/bridge/userscript.user.js` directly
(Tampermonkey recognizes the `.user.js` URL and offers an install page), or
by building it yourself and opening `userscript/dist/hoops-gm.user.js`. Then
open a matching Fantrax league page. In Tampermonkey's menu choose **Pair
hoops-gm bridge**. The command displays the local backend's one-time
12-character code, then asks you to paste it back to confirm. It stores the
returned bearer secret only in Tampermonkey storage; do not add it to source
control or browser-page storage.

### Building, starting, and updating the userscript

1. **Build once:** `cd userscript && npm install && npm run build` produces
   `userscript/dist/hoops-gm.user.js` (gitignored — this is a local artifact,
   not something committed).
2. **Start the backend** (`python -m hoops_gm` from `backend/`, or `docker
   compose up`) so it can serve that file.
3. **Install once:** with the backend running, open
   `http://127.0.0.1:8000/bridge/userscript.user.js` **by hand, in the
   specific browser where Tampermonkey is installed** and install it there.
   If this 404s, the backend is up but the build from step 1 hasn't happened
   yet — the response says so directly. Don't automate this step with a
   generic "open this URL" command (a script, `start <url>`, a link click):
   that resolves through your OS-registered default browser, which is not
   necessarily where Tampermonkey and the paired secret live — it can silently
   open the wrong browser instead of erroring. Tampermonkey does not have to
   be your system default browser at all (this project has tested Brave and
   Edge, either way).
   If 0.2.0 is already installed, do **not** uninstall it: open this URL and
   approve the in-place 0.5.0 update once. The unchanged
   `@name`/`@namespace` identity and `hoops-gm.bridge-secret` storage key retain
   the paired secret. Uninstalling first can discard it. This one confirmation
   cannot be automated because Tampermonkey controls installation.
4. **Update after any source change:** bump the `version` field in
   `userscript/package.json`, run `npm run build` again, and keep the backend
   running. The installed script's `@updateURL`/`@downloadURL` both point back
   at that same loopback endpoint, so Tampermonkey's own periodic update check
   (or its dashboard's manual "Check for userscript updates") picks up the new
   build without reopening its editor or reinstalling the file by hand — the
   one-time install in step 3 stays one-time. See
   [`userscript/README.md`](userscript/README.md#automatic-updates) for what happens
   if you forget to bump the version, or the backend isn't reachable when the
   check runs.

The backend refuses to serve a build whose `@version` differs from
`userscript/package.json`. On Fantrax, the bridge status strip independently
compares that source version, the exact artifact metadata, and the installed
`GM_info.script.version`; it names an available update or an uncheckable/
mismatched build instead of showing a green currency state.

The served file never contains a bridge secret: pairing (above) is the only
way the userscript ever obtains one, and the serving endpoint is loopback-only
like every other local surface here (see
[`ADR-010`](docs/decisions/ADR-010-local-bridge-pairing.md)).

For userscript source changes, follow the update flow above (bump the
version, rebuild, let Tampermonkey pick it up), then reload the Fantrax tab:
capture uses a CSP-safe, page-world response observer because isolated-world
`fetch`/`XMLHttpRequest` patches do not intercept Fantrax's SPA requests in
Chromium Tampermonkey. Then visit Players, Roster, and League normally and
confirm a new `bridge_payloads` row. Some `/fxpa/req` traffic is issued by
Fantrax's own service worker rather than page script, which no page-world hook
can observe. Version 0.5.0 therefore also records a bounded, deduped
`rendered-view` snapshot
automatically after initial load, SPA navigation, and settled visible-page
changes, using only the paired loopback transport. Use Tampermonkey's
**hoops-gm: capture current Fantrax view** command only as the immediate manual
fallback.
See [`userscript/README.md`](userscript/README.md) for
the non-sensitive live-test and troubleshooting procedure.

## Notes

Imported projection data is personal-use only and is not redistributed. Fantrax automation operates the owner's own account on the owner's own team; writes are supervised by default and go through the browser as ordinary interaction.
