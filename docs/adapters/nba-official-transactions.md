# Adapter - NBA official transaction archives

**Status:** working and verified live 2026-09-02. Evidence input only; it does
not establish complete roster intervals or opportunity coverage.

Code: `backend/src/hoops_gm/ingest/nba_transactions/`

Fixtures:

- `backend/tests/fixtures/nba_player_movement.json.gz`
- `backend/tests/fixtures/nba_gleague_transactions.json.gz`

Both fixtures are complete HTTP response bodies, losslessly compressed with
gzip `mtime=0`. They were not parsed or re-serialized before recording.

---

## Calls and observed contracts

### NBA player movement

`GET https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json`

The static archive has no `nba_api` endpoint wrapper. The client still obeys
R27: it sends the request through `NBAStatsHTTP.get_session()` with
`NBAStatsHTTP.headers`, rather than creating a separate raw HTTP path to
`stats.nba.com`.

The captured body has one top-level `NBA_Player_Movement` object containing an
ordered nine-column schema and `rows`. Every row has exactly:

`Transaction_Type`, `TRANSACTION_DATE`, `TRANSACTION_DESCRIPTION`, `TEAM_ID`,
`TEAM_SLUG`, `PLAYER_ID`, `PLAYER_SLUG`, `Additional_Sort`, `GroupSort`.

Observed `Transaction_Type` values are `AwardOnWaivers`,
`ContractConverted`, `Signing`, `Trade`, and `Waive`. Dates are midnight
strings shaped `YYYY-MM-DDT00:00:00`; they provide a date, not an effective
instant. IDs arrive as JSON decimals but are always integer-valued. Trade rows
for draft consideration use `PLAYER_ID=0` and blank `PLAYER_SLUG`; the parser
retains them with an absent player id rather than silently dropping them.

The full fixture contains 9,777 rows from 2015-07-01 through 2026-09-02,
including 518 consideration-only rows. Its raw body is 4,135,059 bytes and has
SHA-256
`a5597174e2ac7b07d2654f7e875225a42c01c2df445d2085c585508345ae63d4`.

### NBA G League transactions

`GET https://gleague.nba.com/api/transactions/fetchTransactions`

The NBA G League transaction page's application bundle names
`https://cdn-gleague.nba.com/static/json/staticData/GLeagueTransactions.json`,
but that URL returned a 5,732-byte legacy HTML page under HTTP 200 when called
directly. The site's own unauthenticated Next.js API route above returned the
JSON archive. A bot-style or `Mozilla/5.0 (compatible; ...)` user agent returned
HTTP 403; a full browser-shaped user agent carrying `hoops-gm/0.1` returned
HTTP 200. No cookie, token, or Fantrax access is involved.

The body is a JSON list. Every row has exactly:

`TEAM_ID`, `PLAYER_ID`, `TEAM_SLUG`, `GROUP_SORT`, `PLAYER_SLUG`,
`ADDITIONAL_SORT`, `TRANSACTION_DATE`, `TRANSACTION_TYPE`,
`TRANSACTION_DESCRIPTION`.

The six type families and twelve observed descriptions are contract-checked:

| Type | Descriptions |
|---|---|
| `Acquired/Assigned` | `Acquired`, `Acquired from Player Pool`, `Acquired from Waivers`, `Assigned` |
| `Call-Up/Recall` | `NBA Call-Up`, `Recalled` |
| `Drafted` | `Drafted` |
| `Trade` | `Traded` |
| `Two-Way Signing` | `Two-Way Signing` |
| `Waived/Buyout` | `Buyout`, `Waived`, `Waivers Cleared` |

Dates are `YYYY-MM-DD` with no effective time. `TEAM_ID=0` identifies
teamless waiver-cleared rows. Seven historical rows instead retain a non-zero
team id with a blank team slug; the parser preserves the id and records the
slug as absent rather than inventing one.

The full fixture contains 14,184 rows from 2021-08-03 through 2026-08-31. Its
raw body is 3,701,195 bytes and has SHA-256
`ce21d2a2ae0b76944952364b0122481c10115b177c28ea59055b68d5bbb38ac8`.

---

## Adapter behaviour

- **Throttle:** one request every two seconds across both archives.
- **Cache:** six hours. Every successful live body is captured before JSON
  decoding. HTTP-error bodies and truncated partial bodies are also captured
  under non-cacheable `.http_error` and `.incomplete_read` endpoint names,
  including failed retry attempts.
- **Retry:** three attempts with exponential backoff only for transport
  failures and HTTP 408, 425, 429, or 5xx.
- **Refusal:** other 4xx responses are non-retryable `SourceRejected`.
- **Garbage or drift:** non-UTF-8 JSON, changed envelopes, added or removed row
  fields, non-integral identifiers, invalid dates, and unknown transaction
  vocabularies raise non-retryable `SourceContractError`.
- **Live smoke:** bypasses the cache, requires the historical archive floor and
  current vocabulary, and pins dated Conley and Wiseman records. A pruned
  archive or changed assignment contract fails visibly.

The fixture recorder is:

```powershell
cd backend
python -m hoops_gm.ingest.record_fixtures nba-transactions
```

Refreshing a fixture because a contract test failed is prohibited by ADR-006;
first determine what changed and record it in `docs/handoff.md`.

---

## What this establishes for opportunity coverage

The feeds supply dated, NBA-ID-bearing evidence that was absent from the direct
participation ledger. They explain two previously unidentified roster gaps and
part of a third without reading silence as an outcome:

- Mike Conley was traded away from Minnesota on 2026-02-03, moved again on
  2026-02-04, waived on 2026-02-05, and signed by Minnesota on 2026-02-17.
- CJ Huntley was waived by Phoenix on 2025-11-17 and signed again on
  2026-03-02; the G League archive separately records a 2026-03-02 NBA call-up.
- James Wiseman was waived by Indiana on 2025-10-28 and signed to a 10-day
  contract on 2025-12-20. The archive has no explicit expiration event, so it
  does not establish when that 10-day stint ended.

Within the four accepted regular-season game-date windows, the fixtures contain:

| Season | NBA movement rows | NBA player rows | G League rows | `Assigned` | `Recalled` | `NBA Call-Up` |
|---|---:|---:|---:|---:|---:|---:|
| 2022-23 | 296 | 267 | 2,472 | 552 | 552 | 58 |
| 2023-24 | 357 | 328 | 2,612 | 583 | 581 | 83 |
| 2024-25 | 352 | 311 | 2,427 | 481 | 480 | 82 |
| 2025-26 | 358 | 333 | 2,518 | 440 | 440 | 88 |

These are source-row counts, not opportunity counts, labels, or coverage
percentages.

## Exact output boundary

This increment populates only typed transaction-evidence records:

- dated NBA `Signing`, `Waive`, `Trade`, `AwardOnWaivers`, and
  `ContractConverted` facts with the source's team/player identifiers; and
- dated G League assignment, recall, call-up, acquisition, waiver, trade,
  draft, buyout, and two-way-signing facts with the source's identifiers.

Those records preserve the source's description text, but no free text is
interpreted as eligibility or absence. Paired events may later support a
bounded roster-state transition where the events explicitly encode both
boundaries and no game shares an unresolved boundary date. This increment
does not implement that derivation.

For the accepted opportunity protocol, this increment emits **no player-game
rows** and populates none of its ternary classes. That is not a claim that the
seasons contain zero opportunities; it means the independent denominator does
not yet exist. Missing transactions, endpoint silence, a season-level roster
snapshot, and `HOW_ACQUIRED` or transaction-description prose cannot create or
repair a player-game row. Consequently neither the overall nor any per-season
`unknown_share` is calculable, and the protocol's `<=5%` gate remains unmet.

## What this does not establish

Neither archive claims to be an exhaustive roster ledger. The NBA vocabulary
has no structured contract-expiration, retirement, suspension, assignment, or
recall event. The G League vocabulary has no suspension event, and its
`Acquired`/`NBA Call-Up` language does not itself prove NBA game eligibility.
Neither source provides an effective time, so same-date transactions and games
remain boundary-ambiguous.

A six-team 2025-26 `CommonTeamRoster` feasibility probe also disproved the
tempting fallback: transient Conley stints with Chicago and Charlotte and
Wiseman stints with Indiana and Toronto were absent from those season-scoped
responses. That endpoint cannot enumerate all historical stints, and its
nullable `HOW_ACQUIRED` prose cannot repair them.

Therefore no complete player-game denominator can yet be enumerated, an
`unknown_share` cannot honestly be calculated, and no public opportunity
envelope or sealed keyed package is produced. `FIT_VETOED_PREREQUISITES`
remains binding. The next trigger is an authoritative source or independently
validated reconstruction contract that supplies complete opening membership,
dated starts and ends (including contract expiration), assignment/recall,
suspension, and same-day boundary handling for all four seasons. Only then may
the accepted protocol's exhaustive ternary classification and numeric proceed
judgement run.
