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

## Types

`src/api/types.ts` mirrors `backend/src/hoops_gm/api/schemas.py` by hand. That
is a deliberate trade for now: the backend serves `/openapi.json`, so
generating them is a small step whenever the surface outgrows a handful of
endpoints. Until then a codegen step nobody needs is a build dependency
without a payoff.
