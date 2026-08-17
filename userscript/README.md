# hoops-gm Tampermonkey bridge

This directory contains the Phase 9 userscript foundation. It currently does
only three things: installs on Fantrax league pages, stores a locally generated
bridge secret in Tampermonkey storage, and provides a loopback
`GM_xmlhttpRequest` transport with a `/health` probe. It does not inspect or
mutate the Fantrax DOM, intercept `/fxpa/req`, or execute actions.

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

The handshake request is prepared for the backend contract at
`POST /api/v1/bridge/handshake`. The current backend foundation does not expose
that route yet, so the request reports a controlled failure until the backend
bridge endpoint lands. The independent `/health` probe is the executable
browser-to-backend round trip for this phase.

## Local development loop

```text
npm install
npm test
npm run build
```

`npm run build` creates one readable installable file at
`userscript/dist/hoops-gm.user.js`; `dist/` is ignored. Rebuild after source
changes, then use Tampermonkey's editor or reinstall the generated file.

The backend must remain loopback-bound. The userscript connects only to
`http://127.0.0.1:8000`; do not change this to `0.0.0.0` or a public hostname.
`GM_xmlhttpRequest` is intentionally used instead of page `fetch`: it runs at
extension privilege and bypasses both page CSP and CORS.

During a live draft, Fantrax must remain the visible active tab. After roughly
five minutes in a hidden tab, Chrome throttles timers to about once per minute,
which stalls Fantrax's own draft polling. Later overlay work must therefore
avoid requiring an alt-tab during a pick clock.
