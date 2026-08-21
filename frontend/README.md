# hoops-gm dashboard

React + TypeScript + Vite. The evidence surface: where a recommendation is
checked. Owned by the `frontend` agent — see `.github/agents/frontend.md`.

Read `AGENTS.md` and `docs/handoff.md` at the repo root before changing
anything here.

## Setup

```bash
cd frontend
npm install
npm run dev
```

Serves on `http://127.0.0.1:5173`. Start the backend first — the dev server
proxies `/api` and `/health` to `http://127.0.0.1:8000`, so the browser only
ever sees one origin and CORS is not part of the development path.

Point at a different backend with `VITE_API_PROXY_TARGET`. Talk to one
cross-origin — without the proxy — with `VITE_API_BASE_URL`.

## Code gate

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

## Layout

```
src/
├── main.tsx           entry point, router provider
├── App.tsx            route table
├── styles.css         design tokens and the base layer
├── api/               client, endpoint functions, response types, useAsync
├── components/        layout shell and shared components
├── routes/            one file per page
└── test/              setup and helpers
```

## Conventions

These are the ones worth arguing about; the rest is ordinary React.

**Data enters a component through `useAsync` and renders through
`AsyncBoundary`.** Never a bare `fetch` in a component. `AsyncBoundary` handles
loading, error, empty and stale in one place, so no view can quietly skip one.

**Stale data must look stale.** Pass `staleAfterMs` for anything with a
shelf life. A `p(play)` computed from a six-hour-old injury report is not the
same number as a fresh one, and rendering them identically is lying by
omission. `AsyncBoundary` also keeps the last good data on screen when a
refresh fails, and says that it did.

**Errors are never swallowed.** `apiFetch` turns every non-2xx into an
`ApiError` carrying the backend's error code and request id. A blank panel
where an error happened is worse than an error message.

**Requests time out.** The backend is local; a request that has not answered
in eight seconds means it is hung. Waiting forever during a pick clock is the
worst available behaviour.

**Tests exercise the real client** against a stubbed `fetch`, not a stubbed
client. A test that mocks the module under test proves nothing.

**One screen.** The owner works from a laptop. Dense and scannable beats
spacious. Numbers use tabular figures so columns align.

**A number we did not compute must never look like one we did.** `/projections`
shows Basketball Monster's imported per-game rates and says on the page that
they are not ours. It renders "not blended" from `lineage.blend === null` — a
fact the backend publishes — rather than from a key it failed to find.

**ADR-002: never multiply a rate by a count.** `source_games_played_assumptions`
carries the exact divisor the importer used, so `rate × assumed_games_played`
recovers the source's published season total, and that fusion is permitted only
at the `expected-games` seam. It is a two-line change that looks like a feature.
The defence is structural: `AssumptionState` is a discriminated union, so a
games figure is never a bare number in the same object as a rate.
`ProjectionsTable.adr002.test.tsx` is a *backstop* for the one product that can
be named — the prohibition is rate × **any** count, and no DOM test enumerates
those.

**Verify CSS in a real browser, with `getComputedStyle`.** jsdom resolves no
cascade, so a rule that loses on specificity renders nothing while the markup,
the data attributes and every unit test pass. That has happened here once
already. `.grid th, .grid td` sits at (0,1,1), so any rule overriding what it
sets must be qualified with `th`/`td` to match.

## Seeing it with real data

Both screens are driven by one database, seeded offline through the production
importers:

```bash
cd backend
python -m hoops_gm.dev.seed_projections --database-url sqlite:///./projections_demo.db
DATABASE_URL=sqlite:///./projections_demo.db python -m hoops_gm
```

```bash
cd frontend
npm run dev
```

If port 8000 is busy the server exits with `[Errno 10048]` and a curl against it
returns **somebody else's 404**, which is indistinguishable from an answer.
Read the server's own log before believing an unexpected status; use
`python -m uvicorn "hoops_gm.app:create_app" --factory --host 127.0.0.1 --port 8017`
and `VITE_API_PROXY_TARGET=http://127.0.0.1:8017` if so.

**The seeded projection numbers are invented — only the player names are real.**
Sixty rows scroll; sixty rows are not a league. Nothing seen there is evidence
the screen handles a real auction board.

## Types

`src/api/types.ts` mirrors `backend/src/hoops_gm/api/schemas.py` by hand. That
is a deliberate trade for now: the backend serves `/openapi.json`, so
generating them is a small step whenever the surface outgrows a handful of
endpoints. Until then a codegen step nobody needs is a build dependency
without a payoff.
