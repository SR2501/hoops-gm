# Adapter — Fantrax official API (`/fxea/general/`)

**Status:** working. `getPlayerIds` and `getAdp` verified live 2026-08-17.
`getLeagueInfo` and `getDraftPicks` **parsers are unverified** — see below.

Base URL: `https://www.fantrax.com/fxea/general`
Code: `backend/src/hoops_gm/ingest/fantrax_official/`

---

## What it actually does

Everything here was established by calling the endpoints, not by reading the
beta documentation.

### It refuses the default `urllib` User-Agent with HTTP 403

Found while recording fixtures, after the same endpoints had answered
PowerShell's `Invoke-WebRequest` all afternoon. It is not authentication and not
rate limiting — it is a user-agent filter. Without a browser-shaped
`User-Agent` header **every endpoint on this source is unreachable**.

The client sends a `User-Agent` that names this project rather than
impersonating Chrome, so a read-only client against a beta endpoint stays
identifiable in Fantrax's logs.

### An error arrives as HTTP 200

`getLeagueInfo` with no `leagueId` returns **status 200** with:

```json
{"error": {"onScreen": false, "code": "WARNING", "message": "Missing 'leagueId' parameter"}}
```

A client that trusts `response.ok` hands that envelope to a parser as though it
were data. Every parser calls `raise_for_error_envelope` before parsing
anything, and the result is a `SourceRejected` — not retryable, because the
request is wrong and repeating it is rude.

### `limit=N` returns N−1 rows

Verified for N = 1, 2, 3, 5, 10. `limit=1` returns **zero** rows.

The adapter passes `limit` through **uncorrected**. Silently adding one would
hide an upstream fix and make our behaviour depend on when the caller last read
a docstring. Callers who want N rows should ask for N+1 knowingly, or omit the
parameter and get everything. Pinned by a contract test *and* a live smoke test.

### The player payload is not all players (risk R24)

`getPlayerIds` returned 1,818 entries on 2026-08-17: **1,788 players and 30
franchise entities**, one per NBA team. The team rows carry `position: "Tm"`
and a `#` in the identifier (`40220#3020`).

The importer filters on the **positional label**. The `#` is checked only as
corroboration in a test — baking one source's incidental identifier format into
the identity layer would make it structural, and it is not.

### There is no NBA.com identifier (risk R23)

`getPlayerIds` exposes `statsIncId`, `rotowireId` and `sportRadarId`. NBA.com
publishes none of them. **There is no anchor pair**, so every cross-source
match is inferred from the first join onward.

The `sportRadarId` bridge was investigated as the plan suggested and **does not
exist**: no free, stable public dataset maps a Sportradar GUID to an NBA.com
person id. The open ID datasets carry Basketball-Reference, ESPN and Spotrac
identifiers instead, and are themselves built by name matching — so joining
through one would be name matching with extra steps plus a stale third-party
dependency. Sportradar's own mapping endpoint is behind a commercial
subscription, which is an owner-only decision.

All three identifiers are still stored as first-class crosswalk rows, for two
reasons that pay off immediately: they de-duplicate *within* Fantrax, which
contains genuine duplicate names, and they survive Fantrax rotating its own
`fantraxId`. If a projection source ever carries one, the bridge exists that day.

### Every identifier is optional

Measured on the live payload:

| Field | Present on |
|---|---|
| `rotowireId` | 1,723 / 1,788 |
| `sportRadarId` | 1,438 / 1,788 |
| `statsIncId` | 851 / 1,788 |

A parser requiring any of them would drop between 4% and 52% of the payload.

### Two thirds of rows have no team

`team` is `"(N/A)"` for **1,206 of 1,788** player rows, normalised to `""`.
That is *unknown*, not *disagreeing*, and the difference is why the crosswalk
stores per-field evidence rather than a single confidence float.

### Names are `"Last, First"`, and duplicates exist

Four duplicated names within Fantrax alone on 2026-08-17, including two
"Johnson, Jalen" and two "Williams, Jaylin". Name-only matching is not safe.

---

## Throttling, retry and failure

| Concern | Behaviour |
|---|---|
| **Throttle** | One request every **2 seconds**. No published limit; nothing here needs to be fast, and being conspicuously polite to an undocumented beta endpoint costs nothing. |
| **Retry** | 3 attempts, exponential backoff with jitter, **only** on `SourceUnavailable`. |
| **Cache** | A capture younger than 6 hours is used instead of a request. A player-id map is daily-cadence data at best. |
| **Source down** | Timeout / connection error / 408, 425, 429, 5xx → `SourceUnavailable`, retried. Exhausted retries propagate: the caller decides whether stale data is acceptable, because that depends on what it is for. Nothing silently substitutes old data for new. |
| **401 / 407** | `CredentialsExpired`, which names the remedy. |
| **Other 4xx** | `SourceRejected`. The source answered coherently and refused; conflating that with drift makes a mistyped league id look like an upstream change. |
| **Body is not JSON** | `SourceContractError`. |
| **Body is the error envelope** | `SourceRejected`. |
| **Body is JSON of the wrong shape** | `SourceContractError` from the parser. Never retried, and meant to be loud. |

The raw body is captured **before** decoding, so a response that fails to parse
is exactly the response still available afterwards.

---

## Not verified

**`getLeagueInfo` and `getDraftPicks` parsers have never seen a real payload.**
Both require a `leagueId`, and no league credentials existed when they were
written. The only live response obtained from either was the missing-parameter
error envelope — which *is* covered by a contract test, because it is a real
captured response.

The parsers are therefore written defensively: every field optional,
alternative key spellings accepted, and unrecognised keys surfaced on
`unmapped_keys` rather than dropped, because a league setting we silently
ignore is a setting the draft engine gets wrong. **Re-check both against a real
league before anything depends on them.**
