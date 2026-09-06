# Adapter - preseason NBA player news

**Status:** working and verified live 2026-09-06. This is raw availability
evidence for the period before the NBA's per-game injury report exists. It does
not infer an injury status or change a valuation.

Code: `backend/src/hoops_gm/ingest/preseason_news/`

Fixture: `backend/tests/fixtures/rotowire_nba_news.xml.gz`

---

## Source and observed contract

The adapter reads RotoWire's public, unauthenticated NBA RSS feed:

```text
GET https://www.rotowire.com/rss/news.php?sport=NBA
```

RotoWire's `/rss/` page describes its XML feeds as usable in RSS readers and
personal websites. No account, cookie, API key, paid subscription, browser
automation, or Fantrax request is involved.

The response observed on 2026-09-06 was HTTP 200 with
`Content-Type: application/xml`. It was a 1,632-byte RSS 2.0 body containing two
items, newest first. Each item carried:

- a unique `guid` shaped `nba<news id>`;
- a title shaped `<player name>: <headline>`;
- an HTTPS RotoWire player link whose final path segment ends in a stable
  numeric RotoWire player id;
- source prose in `description`; and
- a publication time shaped `Sat, 05 Sep 2026 11:21:00 AM PDT`.

The committed fixture is the complete HTTP response body, losslessly gzip
compressed with `mtime=0`. It was not parsed or re-serialized before recording.
Its raw SHA-256 is
`0650edfe710f53f571573e1a3a9dae852c93c4bb8b9d0c3e48a1151f04b949a2`.

The recorder is:

```powershell
cd backend
python -m hoops_gm.ingest.record_fixtures preseason-news
```

Refreshing a fixture because a contract test failed is prohibited by ADR-006;
first establish what changed upstream.

---

## Meaning checks

The parser does more than validate XML:

- The player name in the title must agree with the player-link slug, including
  generational-suffix evidence. Consecutive dotted initials are closed only for
  this comparison because URL slugs remove their punctuation (`P.J.` -> `pj`).
  A suffix present on only one side is unknown evidence because observed
  RotoWire pages omit real suffixes retained by Fantrax; two different stated
  suffixes are a contradiction.
- The stated `PST` or `PDT` suffix must agree with the
  `America/Los_Angeles` timezone rules on that calendar date. Both DST folds
  are evaluated and round-tripped through UTC, so a valid repeated fall-back
  time is accepted while a nonexistent spring-forward wall time is rejected.
  The timestamp is then converted to UTC.
- A publication time more than five minutes after the independently observed
  response time is rejected.
- Items must remain newest first and GUIDs must be unique.
- DTD and entity declarations are rejected before XML parsing.

The identity join does not introduce another name matcher. The numeric
RotoWire id joins only to a **current**
`player_external_ids.source = 'fantrax_rotowire'` row created by the existing
crosswalk build. The feed name is compared with that row's `external_name`,
including generational suffixes, as an independent veto: base-name disagreement
or two different stated suffixes remain unresolved rather than attaching the
item to whichever player owns the id. A suffix present on only Fantrax is
unknown evidence, not disagreement; committed Fantrax evidence includes
`Oubre Jr., Kelly` and `Payton II, Gary`, while RotoWire omits those suffixes.

This works because Fantrax `getPlayerIds` already publishes `rotowireId` for
most players and the existing crosswalk records it. It does **not** establish
that Fantrax's visible player notes are the same RotoWire text. No Fantrax notes
payload has been captured, and the adapter makes no such claim.

---

## Operator path

After the crosswalk exists:

```powershell
cd backend
python -m hoops_gm.ingest.preseason_news
```

The command writes `data/reports/preseason_news.json` atomically and returns a
non-zero exit code when any feed item is unresolved. The report contains the
source observation time and raw-body SHA-256, each resolved local `player_id`,
and every unresolved item with its refusal reason. Raw response bytes are kept
under `data/raw/rotowire_nba_news/`.

The report preserves the source headline and description. It deliberately has
no normalized `status`, probability, rank, or valuation field. "Concern",
"expected", "suspended", and similar prose are reporting, not a stable status
vocabulary; converting them into availability meaning belongs downstream and
requires its own evidence.

---

## Throttling, retry, cache, and failure

- **Throttle:** one request every two seconds in-process.
- **Cache:** ten minutes, matching the feed's stated `<ttl>10</ttl>`.
- **Retry:** three attempts with exponential backoff only for transport
  failures and HTTP 408, 425, 429, or 5xx.
- **Refusal:** other 4xx responses raise non-retryable `SourceRejected`.
- **Garbage or drift:** wrong content type, a body over 1 MiB, non-UTF-8 or
  malformed XML, changed RSS/channel/item fields, invalid identifiers,
  contradictory names or dates, duplicate GUIDs, and changed ordering raise
  non-retryable `SourceContractError`.
- **Raw failures:** HTTP-error, truncated, oversized, and contract-invalid
  bodies are retained under diagnostic raw-store endpoint names and never enter
  the success cache. A partial body from a truncated HTTP-error response is
  retained under `latest_nba_news.http_error_incomplete_read`.
- **Live smoke:** bypasses cache, requires an item published within 14 days,
  then fetches live Fantrax `getPlayerIds` and requires at least one feed item
  to share a RotoWire id and normalized player name.

---

## Limits

### Observed window and silent-loss bound

The 2026-09-06 capture exposed **2 items**:

| Published (source) | Published (UTC) |
|---|---|
| `Sat, 05 Sep 2026 11:21:00 AM PDT` | `2026-09-05T18:21:00Z` |
| `Thu, 03 Sep 2026 1:50:00 PM PDT` | `2026-09-03T20:50:00Z` |

One capture proves an observed window size of 2; it does **not** prove that 2
is the feed's configured cap. The poll cadence is 10 minutes, derived from the
feed's observed `<ttl>10</ttl>` declaration. At an observed two-item window,
that tolerates at most `2 / 10 = 0.2` items per minute between polls. If more
than two items arrive in a ten-minute interval and the feed retains only two,
displaced items are lost **silently and unrecoverably**. The raw store preserves
every successful observation but cannot reconstruct displaced news or news
published before collection started.

The feed contains RotoWire summaries that cite reporting sources; it is not a
direct firehose of every beat reporter. It can carry preseason injury,
training-camp, suspension, transaction, and role news when RotoWire publishes
them, but absence from this two-item feed is not evidence that no relevant news
exists. Fantrax's in-page notes remain unverified because no real notes payload
has been observed; guessing that shape would violate ADR-006.
