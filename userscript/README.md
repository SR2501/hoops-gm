# hoops-gm Tampermonkey bridge

This directory contains the Phase 9 userscript. It does four things: installs
on Fantrax league pages, stores a locally generated bridge secret in
Tampermonkey storage, provides a loopback `GM_xmlhttpRequest` transport with a
`/health` probe and an authenticated handshake, and **read-only captures**
Fantrax's internal `/fxpa/req` responses for forwarding to the backend. It
does not mutate the Fantrax DOM, does not touch any other endpoint, does not
render an overlay, and does not execute any action. `bridge-overlay` and
Phase 10 automation are separate, later work.

## Install

1. Start the local backend on `http://127.0.0.1:8000`.
2. Install Tampermonkey and enable developer mode if the browser asks for it.
3. Run `npm install` and `npm run build` in this directory.
4. Open `dist/hoops-gm.user.js` and install it in Tampermonkey.
5. Open a Fantrax URL matching `https://www.fantrax.com/fantasy/league/*`.

The secret is generated with `crypto.getRandomValues`, stored under a
Tampermonkey-only key, and sent only as the `X-Bridge-Secret` request header.
It is never placed in source control or written to the console. Removing the
userscript's stored data generates a new secret on the next page load.

The handshake calls the backend contract at
`POST /api/v1/bridge/handshake` with `{ "protocol": 1 }` and the
`X-Bridge-Secret` header. A successful response confirms `{ "status": "ok",
"protocol": 1 }`. The independent `/health` probe remains available as a
browser-to-backend round trip.

## `/fxpa/req` capture (read-only)

`src/capture.js` wraps `window.fetch` and `window.XMLHttpRequest` so that,
after each real request the page itself makes, the response is inspected
for forwarding. It is deliberately narrow and non-disruptive:

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
  backend endpoint and the `bridge_payloads` table it stores raw payloads
  in (see `docs/plan.md`) are a contract, not yet implemented as of this
  change** — exactly as `/api/v1/bridge/handshake` was called by the
  userscript before the backend route existed. Until the backend adds it,
  captured payloads are attempted, fail with a logged warning, and are
  dropped; nothing here assumes the endpoint is live.

## Local development loop

```text
npm install
npm test
npm run build
```

`npm run build` concatenates `src/userscript.js` and `src/capture.js` (in
that order, since capture's auto-install checks for the transport the first
file creates) into one readable installable file at
`userscript/dist/hoops-gm.user.js`; `dist/` is ignored. Rebuild after source
changes, then use Tampermonkey's editor or reinstall the generated file.

The backend must remain loopback-bound. The userscript connects only to
`http://127.0.0.1:8000`; do not change this to `0.0.0.0` or a public hostname.
`GM_xmlhttpRequest` is intentionally used instead of page `fetch`: it runs at
extension privilege and bypasses both page CSP and CORS. Note that `fetch`/
`XMLHttpRequest` patching in `capture.js` is a different, page-privilege
mechanism used only to *observe* the page's own already-in-flight requests to
`/fxpa/req` — it is not how captured envelopes reach the backend.

During a live draft, Fantrax must remain the visible active tab. After roughly
five minutes in a hidden tab, Chrome throttles timers to about once per minute,
which stalls Fantrax's own draft polling. Later overlay work must therefore
avoid requiring an alt-tab during a pick clock.

## Tests

`test/userscript.test.js` covers the transport/handshake/secret foundation.
`test/capture.test.js` covers the capture module in isolation via dependency
injection (no real browser, DOM, or network): URL filtering, malformed/
non-JSON body normalization, the typed envelope shape (including that it
never carries headers or a request body), dedupe behaviour, fetch/XHR
wiring (including that the page still receives its real response and that
its own event listeners still fire), and that a failing or misconfigured
transport never throws or produces an unhandled rejection.
