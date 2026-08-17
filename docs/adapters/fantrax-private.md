# Adapter — Fantrax private league (`/fxpa/req` via `fantraxapi`)

**Status: UNVERIFIED.** No league id and no session cookie existed when this was
written, so **no call has ever been made** and no payload has ever been seen.
What exists is the session handling, the encrypted cookie store and the error
translation. What does not exist is parsers for roster, standings and matchup
data — deliberately.

Code: `backend/src/hoops_gm/ingest/fantrax_private/`
Pinned: `fantraxapi==1.0.1`

---

## Version pinning

Pinned **exactly**, not with a floor. `fantraxapi` wraps `/fxpa/req`, the
internal JSON-RPC the Fantrax SPA uses. It is undocumented and can change shape
without notice; a floating version means that change arrives as a mysterious
difference in a number rather than as a deliberate upgrade with a contract test
to run against it.

**The plan's suggested `0.3.0` does not exist on PyPI.** Published versions go
`0.1.0 … 0.2.9`, then `1.0.0`, `1.0.1`. The 1.0.x line has a different API
surface from the 0.2.x line most online examples use: a `League` object taking
`(league_id, session)`, with `standings`, `team_roster`,
`scoring_period_results`, `transactions`, `live_scores`, `trade_block`,
`pending_trades`, `team_lookup`, `position_counts` and `scoring_periods_lookup`.

---

## Why there are no parsers yet

Writing parsers against a payload shape nobody has seen produces exactly what
ADR-006 rejects: hand-written mocks encoding what we *assume* rather than what
the source *returns*, with a contract test proving only that our assumption is
self-consistent. Phase 1's handoff already flagged that `fantraxapi` was
developed against an NHL points league and that the `transactions`,
`roster_slots` and `matchup_category_results` shapes are guesses.

So the typed objects `fantraxapi` already returns are passed through, and
`FantraxPrivateClient.capture()` exists for the first person with a live
cookie: it calls an arbitrary method and stores the raw result, so fixtures and
contract tests can be written against reality.

**Next step for whoever has credentials:** run `capture()` against each read,
commit the results as fixtures, write the parsers, and expect the League tables
to need a migration.

---

## Cookie storage and the re-login flow

### How it is stored

* Ciphertext in `data/fantrax_cookie.enc` (Fernet). `data/` is git-ignored.
* Key in `.env` as `FANTRAX_COOKIE_KEY`. **The key, never the cookie.**

Splitting them means neither artefact alone is a credential, and the one that
is easiest to leak accidentally — a dotfile, copied into a shell history, a
container env dump, a screenshot — is the one that is useless on its own.

```bash
# once
python -m hoops_gm.ingest.fantrax_private.cookies --generate-key   # -> .env

# whenever the session expires
python -m hoops_gm.ingest.fantrax_private.cookies --store          # prompts, hidden input
```

`--store` reads the cookie with `getpass`, so it never lands in a shell history.

### Capturing a cookie by hand

1. Log in to Fantrax in a browser.
2. Open developer tools → Application → Cookies → `https://www.fantrax.com`.
3. Copy the value of **`FANTRAXUSER`**.
4. Run `--store` and paste it.

### Why the Selenium login is not implemented

`fantraxapi`'s documented route drives a real browser. That is deliberately not
built here, and the reasoning belongs on the record:

* it needs a browser and a driver in the environment, neither of which exists
  in CI, so it could never be tested where it matters;
* it is brittle in exactly the way a login page is brittle;
* **driving the site's own login form is closer to the write path than to
  ingestion**, and the write path is `bridge`'s to build and `safety`'s to
  approve. A data adapter quietly growing browser automation is how a guardrail
  boundary erodes.

What is implemented is the honest half: detect expiry precisely and tell the
human exactly what to do. `NotLoggedIn` and `NotMemberOfLeague` become
`CredentialsExpired`, whose message contains the recovery command.

**Automating the login is an owner-only decision** — it changes the nature of
Fantrax access, which is on the owner-only list.

---

## Throttling, retry and failure

| Concern | Behaviour |
|---|---|
| **Throttle** | One request every **2 seconds**. This is somebody's live account against undocumented internal infrastructure; there is no reason to be quick. |
| **Retry** | **2** attempts, lower than elsewhere. A failing authenticated request against internal infrastructure is more likely to be a session problem than a blip, and repeating it is how a session gets flagged. |
| **Source down** | Transport exceptions → `SourceUnavailable`, retried once. |
| **Session expired** | `NotLoggedIn` / `NotMemberOfLeague` → `CredentialsExpired`, carrying the recovery command. The expected steady-state failure, so it is a distinct class rather than a generic refusal. |
| **Returns garbage** | Anything else → `SourceContractError`, never retried, meant to be loud. |

`reset_session()` forgets the cached session so a long-running process picks up
a freshly stored cookie without a restart.

---

## Secrets

Nothing here is committed. The Code gate's secret scan covers
`FANTRAXUSER`-shaped values and `userSecretId`, and `.gitignore` already
excludes `.env`, `data/` and `*.cookie`.
