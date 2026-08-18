# hoops-gm Tampermonkey bridge

This directory contains the Phase 9 userscript. It installs on Fantrax league
pages, pairs a backend-generated bridge secret into Tampermonkey storage on an
explicit owner command, provides a loopback `GM_xmlhttpRequest` transport with a
`/health` probe and an authenticated handshake, and **read-only captures**
Fantrax's internal `/fxpa/req` responses for forwarding to the backend —
automatically via page-world `fetch`/`XHR` hooks and a best-effort Cache
Storage watcher, and on explicit owner command via a manual page-state export
for the traffic neither of those can reach (see "Root cause #2" below). It
does not mutate the Fantrax DOM, does not touch any other endpoint, does not
render an overlay, and does not execute any action. `bridge-overlay` and
Phase 10 automation are separate, later work.

## Install

1. Start the local backend on `http://127.0.0.1:8000`.
2. Install Tampermonkey and enable developer mode if the browser asks for it.
3. Run `npm install` and `npm run build` in this directory.
4. With the backend running, open
   `http://127.0.0.1:8000/bridge/userscript.user.js` in the same browser and
   install it in Tampermonkey. This is a one-time step — see "Updating"
   below for why you should not need to repeat it.
5. Open a Fantrax URL matching `https://www.fantrax.com/fantasy/league/*`.

In Tampermonkey's extension menu, choose **Pair hoops-gm bridge**. The command
obtains and displays a one-time 12-character code from the local backend, then
asks you to paste it back to confirm the pairing. It is never automatic on page
load. The successful response's bridge secret is stored under a Tampermonkey-only
key and sent only as the `X-Bridge-Secret` request header. Neither the secret nor
pairing code is logged to the console. A pairing code expires after ten minutes
and can be used only once.

## Updating

The built script's `@updateURL`/`@downloadURL` metadata both point at
`http://127.0.0.1:8000/bridge/userscript.user.js` — the same loopback backend
that serves the handshake and pairing endpoints, never a public host.
Tampermonkey periodically re-fetches that URL, compares `@version`, and
prompts to update in place when it changes:

1. From `userscript/`, run `npm run build` after any source change. The build
   reads `@version` from `package.json`, so bump that field for the change to
   be seen as an update at all — an unchanged version is invisible to
   Tampermonkey's comparison, not merely slow to arrive.
2. Keep the local backend running: Tampermonkey's update check is a plain GET
   against that URL, so if the backend (and therefore the built file) is
   unreachable, the check silently finds nothing to update rather than
   erroring visibly.
3. Trigger Tampermonkey's check manually (its dashboard has a "Check for
   userscript updates" action) or wait for its own schedule, then approve the
   update prompt when it appears.

This means step 4 in **Install** above is a true one-time action for source
changes going forward: rebuilding is enough, without reopening Tampermonkey's
editor or reinstalling the file by hand. Rebuilding without bumping the
version still regenerates `dist/hoops-gm.user.js` correctly; it only means
Tampermonkey has nothing new to detect until the version moves.

If `http://127.0.0.1:8000/bridge/userscript.user.js` returns 404, the backend
is running but `userscript/dist/hoops-gm.user.js` does not exist yet — the
response's `detail` field says so directly. Run `npm install && npm run
build` in this directory and reload the URL; the route reads the file from
disk on every request; nothing needs restarting.

The served bytes are always exactly what a local `npm run build` produces:
the endpoint is loopback-only and never contains a bridge secret, ADR-010's
pairing exchange is the only path to one. Neither the build nor the serving
route reads `BRIDGE_SECRET` or the on-disk paired secret file.

The handshake calls the backend contract at
`POST /api/v1/bridge/handshake` with `{ "protocol": 1 }` and the
`X-Bridge-Secret` header. A successful response confirms `{ "status": "ok",
"protocol": 1 }`. The independent `/health` probe remains available as a
browser-to-backend round trip.

## `/fxpa/req` capture (read-only)

`src/capture.js` injects a tiny, self-contained hook into Fantrax's **page
world**. The original capture attempted to wrap `window.fetch` and
`window.XMLHttpRequest` from Tampermonkey's isolated world; in Brave and Edge
that does not affect the SPA's page-world globals, which explains a healthy,
paired backend with zero stored payloads. The page-world hook observes its own
globals and sends a narrow response-only record via `window.postMessage`; the
Tampermonkey-world receiver validates it and forwards through
`GM_xmlhttpRequest`. The hook is deliberately narrow and non-disruptive:

### Root cause #2: some `/fxpa/req` calls never touch page script at all

After the page-world fix above, a live check still showed a healthy, paired
backend and **zero** rows in `bridge_payloads`. DevTools traced the relevant
`/fxpa/req` calls to an **initiator of `fx-sw.js`** — Fantrax's own service
worker — not to any page script. A service worker runs in its own global
scope, entirely separate from `window`. There is no supported browser API,
and no Tampermonkey grant, that lets a userscript observe or instrument
another origin's *internal* `self.fetch()` call or the response it produces
without that response ever being handed to `window.fetch`/`XMLHttpRequest`.
**This is a platform boundary, not a bug in the page-world hook above** —
patching `window.fetch`/`XMLHttpRequest` can only ever see requests page
script itself issues, and structurally cannot see one the service worker
issued on its own.

Two things follow from that, both implemented here:

1. **Cache Storage watcher (best-effort, automatic).** Cache Storage
   (`window.caches`) is a *per-origin* store shared by both `window` and the
   service worker — if `fx-sw.js` persists a response there (a common
   Workbox pattern for background sync / offline support), a page script can
   legitimately read the same entry, the same way it could read any other
   origin-scoped browser storage. While the tab is visible, the page-world
   hook polls Cache Storage every 5 seconds, matches entries against the
   exact `/fxpa/req` filter (using `{ignoreMethod: true}` so a cached `POST`
   entry is still found), and publishes any match through the same channel
   as `fetch`/`xhr` captures, tagged `source: "cache-storage"`. **This is
   opportunistic and unverified against the live site** — it depends
   entirely on whether Fantrax's service worker actually uses Cache Storage
   for this endpoint, which the owner's live check (below) determines. IndexedDB
   is the same idea in principle but was deliberately left undone: its schema
   would have to be reverse-engineered per Fantrax version, which is a far
   more likely source of silent drift than Cache Storage's simple
   Request/Response shape.
2. **Manual export (guaranteed, owner-triggered).** Independent of which
   layer produced the data, the owner can invoke **hoops-gm: capture current
   Fantrax view** from Tampermonkey's extension menu at any moment. This runs
   entirely in Tampermonkey's isolated world (DOM access is not
   CSP-restricted, only script/resource loading is) and exports whatever is
   already rendered on screen: it prefers an exposed client-side state object
   (`__NEXT_DATA__`, `__NUXT__`, `__INITIAL_STATE__`, or `__APOLLO_STATE__`,
   checked in that order) as structured JSON, and otherwise clones the page's
   main content region (`main`, `#root`, `#app`, or `body`, in that order),
   strips `<script>`/`<style>`/`<noscript>` from the clone, and forwards the
   resulting HTML. Output is bounded to 500,000 characters. This never
   depends on Fantrax's network layer at all, so it is the one path
   guaranteed to work regardless of what `fx-sw.js` does. See "Customer
   workflow: manual export" below for exactly when and how to use it.

Both new sources are stored in the same `bridge_payloads` table via the same
authenticated envelope contract (`schema`, `capturedAt`, `request`,
`response`, `body`, `dedupeKey`) — only `source` and, for the manual export,
the meaning of `request.url`/`response.status` differ. `source` is now one of
`"fetch"`, `"xhr"`, `"cache-storage"`, or `"manual-export"`; the backend's
`BridgeRequest` model enforces exactly these four.


- **Read-only, response-only.** Nothing about an outgoing request is ever
  changed, delayed, or blocked — the page's own promise/callback still
  resolves with the exact, unmodified response it would have received with
  the userscript absent. Fetch bodies are read from a **clone** of the
  response so the page's own read of the stream is never consumed.
  Outgoing request bodies are never read or forwarded at all.
- **Narrow filter.** Only responses from `fantrax.com` or
  `www.fantrax.com` whose URL path is exactly `/fxpa/req` (Fantrax's
  undocumented internal JSON-RPC endpoint, see ADR-004) are captured.
  Everything else, including the official `/fxea/general/*` API calls the
  page also makes, passes through untouched and uninspected.
- **No headers, no secrets.** The captured envelope carries only method,
  URL, response status/`ok`, response `Content-Type`, and the response
  body. Request headers, response headers other than `Content-Type`
  (notably never `Set-Cookie`), cookies, and outgoing request bodies are
  never read, stored, or forwarded.
- **Typed, normalized envelope.** Every capture is wrapped in a
  `hoops-gm.bridge-payload.v1` envelope (see the `@typedef` in
  `src/capture.js`) with the raw response body always preserved verbatim,
  a best-effort `JSON.parse`, and an explicit `parseError` field so a
  non-JSON or malformed body (an HTML error page, a truncated response, an
  empty body) is captured for diagnosis rather than dropped or thrown.
- **Explicit non-disruptive failure.** Every capture, normalization, and
  forwarding step is wrapped so a bug in this module can at most silently
  drop one capture — it can never throw into Fantrax's own page code or
  delay a response the page is waiting on. Forwarding failures (backend
  unreachable, non-2xx, invalid JSON) are logged as a warning and dropped;
  they are never retried in a way that could burst traffic.
- **Bounded dedupe.** A small in-memory recency cache collapses
  byte-identical consecutive captures of the same method/URL/body (e.g. a
  page polling the same RPC call every few seconds), so an unchanged draft
  board does not flood the backend on every tick.
- **Forwarded over the existing authenticated transport.** Captured
  envelopes are POSTed via `transport.sendPayload(envelope)`, which reuses
  the same loopback `GM_xmlhttpRequest` channel and `X-Bridge-Secret`
  header as the handshake — to `POST /api/v1/bridge/payloads`. **That
  backend endpoint stores raw payloads in `bridge_payloads` before any
  normalization.
- **One-way and validated.** The page hook has no GM API, no bridge secret,
  and no backend address. Its `postMessage` record is accepted only when its
  `source` is the top-level page window, its `origin` is the exact current
  Fantrax origin, its per-load channel matches, its schema is exact, and every
  field has the expected primitive type. The receiver applies the exact
  Fantrax-host and `/fxpa/req` filter again. Malformed, cross-origin, and
  lookalike events are dropped.
- **CSP/execution modes.** The build requests Tampermonkey's `GM_addElement`
  and uses it to inject the page-world script, which is the CSP-safe path.
  For compatible managers/modes without that API it falls back to a temporary
  inline script element; a strict site CSP may reject that fallback, in which
  case it warns rather than claiming capture is active. The receiver and
  forwarding always remain in Tampermonkey's isolated, GM-privileged context.

## Local development loop

```text
npm install
npm test
npm run build
```

`npm run build` concatenates `src/userscript.js` and `src/capture.js` (in
that order, since capture's auto-install checks for the transport the first
file creates) into one readable installable file at
`userscript/dist/hoops-gm.user.js`, prefixed with the `==UserScript==`
metadata block; `dist/` is ignored. The `@version` in that block comes from
`package.json`, and `@updateURL`/`@downloadURL` both point at the backend's
`GET /bridge/userscript.user.js`, so Tampermonkey's own update check is what
picks up a rebuild after the version is bumped — see "Updating" above. This
is a change from the original workflow, which required reopening
Tampermonkey's editor or reinstalling the file by hand after every rebuild.

The backend must remain loopback-bound. The userscript connects only to
`http://127.0.0.1:8000`; do not change this to `0.0.0.0` or a public hostname.
`GM_xmlhttpRequest` is intentionally used instead of page `fetch`: it runs at
extension privilege and bypasses both page CSP and CORS. The page-world hook
only observes Fantrax's own requests; it never reaches the backend itself.

## Live capture check (owner-run)

After rebuilding and updating/reinstalling the script in Tampermonkey, reload
the Fantrax tab so the new document-start page-world hook is installed:

1. Keep the paired script enabled and the local backend running.
2. Open a matching Fantrax league URL, then visit **Players**, **Roster**, and
   **League** normally.
3. Check `bridge_payloads` in the local database (or the backend logs) for a
   new row. Do not put a bridge secret, cookie, request body, or headers in
   any diagnostic output.
4. If still zero, open Tampermonkey's script console and report only the
   non-sensitive warning text plus browser/version and the active script
   version. Do not alter Fantrax requests to test it.
5. If DevTools shows the relevant `/fxpa/req` request's initiator as
   `fx-sw.js` (Fantrax's service worker) rather than a page script, the
   fetch/XHR hook and the Cache Storage watcher above are both structurally
   unable to help in general — go straight to the manual export below rather
   than continuing to chase the automatic path.

This change has unit/build coverage only; a live browser result — including
whether the Cache Storage watcher actually finds anything on the real site —
is pending the owner repeating this check.

During a live draft, Fantrax must remain the visible active tab. After roughly
five minutes in a hidden tab, Chrome throttles timers to about once per minute,
which stalls Fantrax's own draft polling. Later overlay work must therefore
avoid requiring an alt-tab during a pick clock. The Cache Storage watcher
respects this too: it skips its poll entirely while `document.visibilityState`
is `"hidden"`, so it is never the thing competing for an already-throttled
tick.

## Customer workflow: manual export (guaranteed fallback)

Use this whenever the automatic paths above are silent — most reliably, any
time DevTools shows `/fxpa/req`'s initiator as `fx-sw.js` — or any time you
want a capture of exactly what is on screen right now:

1. Navigate to the Fantrax page showing the data you want captured (for
   example the **Players** list, a **Roster**, or the **Draft Board** during
   a live draft) and make sure it has finished loading.
2. Open Tampermonkey's extension menu (the puzzle-piece icon, then the
   hoops-gm bridge entry) and choose **hoops-gm: capture current Fantrax
   view**.
3. A confirmation alert reports whether something was captured. Nothing is
   sent anywhere else, and nothing on the page is changed — this only reads
   what is already rendered.
4. Check `bridge_payloads` for a new row with `source = 'manual-export'`.
   Its `request.url` is the Fantrax page you were on, not an API endpoint;
   `body.raw` is either the page's own exposed application-state JSON
   (`response.contentType = 'application/json'`) or a stripped HTML snapshot
   of the main content region (`response.contentType = 'text/html'`).

This is deliberately a lower-confidence, unparsed capture compared to a real
`/fxpa/req` JSON-RPC response — it exists so a draft or roster view is never
left completely uncaptured, not to replace the automatic path. Repeat it at
each moment you want a record (e.g. once per draft pick); it does not run on
a timer and nothing is captured until you invoke it.

## Tests

`test/userscript.test.js` covers the transport/handshake/secret foundation.
`test/capture.test.js` covers the capture module in isolation via dependency
injection (no real browser or network): URL filtering, malformed/non-JSON body
normalization, typed envelope shape, dedupe, page-world fetch/XHR wiring,
rejection of cross-origin, wrong-source, wrong-channel, malformed, and
lookalike page events, the Cache Storage watcher (matching entries, the
hidden-tab skip, and a rejecting `caches.keys()` never throwing), and the
manual export (`captureManual` bypassing the `/fxpa/req` filter, app-state
preference over DOM snapshot, script/style stripping, size truncation, and the
Tampermonkey menu wiring). It also verifies that the hook has no request body
or header field and that its real page response remains intact.
`test/build.test.js` runs the real `build.mjs` and asserts on the produced
`dist/hoops-gm.user.js`: `@version` matches `package.json`, `@updateURL` and
`@downloadURL` are both present, identical, and loopback (never a hostname
that could resolve off-machine), and no hex-64 or base64url-43 secret-shaped
literal — the two accepted stored-secret shapes — appears anywhere in the
build (ADR-010).
