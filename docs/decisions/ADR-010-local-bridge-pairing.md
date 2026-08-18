# ADR-010 — One-time local pairing for the browser bridge

**Status:** Accepted
**Accepted:** 2026-08-17 by the project owner
**Date:** 2026-08-17

## Context

The userscript has an isolated Tampermonkey storage world and already creates a random bearer secret. The backend currently requires `BRIDGE_SECRET`, but asking the owner to copy a secret into `.env` is the wrong setup experience. Pairing must remain local-only and must not turn the dashboard into a remote authentication surface.

## Decision

When no persisted bridge secret exists, the backend creates a 10-minute pairing record containing a cryptographically random, single-use token. The local dashboard displays the token once as a 12-character grouped code and offers “Pair bridge”. The userscript exposes a Tampermonkey menu command, prompts for that code, and sends it in a custom `X-Hoops-GM-Pairing-Code` header over `GM_xmlhttpRequest` to `POST /api/v1/bridge/pair`. The endpoint is loopback-only, accepts no cookies, requires the custom header, atomically consumes the token, rate-limits failures, and returns the newly generated 32-byte secret exactly once. The userscript stores it in GM storage; the backend stores only a protected local copy (with `BRIDGE_SECRET` remaining an explicit recovery/override).

Pairing tokens expire after ten minutes, are invalidated after five failed attempts, and cannot be replayed. Pairing and reset responses never contain or log secrets. Reset/revoke is deliberately deferred until there is a clearly owned local
operator surface; this flow does not expose a reset endpoint. A same-machine
compromise is out of scope: a process that can read the user's files or
localhost traffic can steal the bearer secret.

## Consequences

Setup is copy/paste once, with no source-controlled secret and no page-world dependency. Existing authenticated bridge endpoints remain unchanged. The custom header and same-origin/`Origin` checks prevent ordinary cross-site form CSRF; the token's one-time atomic consumption limits races.

## Rejected

Embedding a secret in the userscript, QR/cloud pairing, and unauthenticated “accept whatever the script sends” endpoints. A six-digit code was rejected as unnecessarily brute-forceable.

## What would flip this

Remote access, multiple users, or a host threat beyond the owner's trusted local account would require a new authentication design and owner approval.
