# Adapter — Fantrax official API (`/fxea/general/`)

**Status:** working. `getPlayerIds` and `getAdp` verified live 2026-08-17;
`getLeagueInfo` verified live 2026-09-05. `getDraftPicks` **verified reachable
live 2026-08-28 and returned an empty list for a completed 216-pick draft**; its
meaning is unresolved.

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

### `getLeagueInfo` now exposes playoff-period boundaries

Verified against the target private league with one low-frequency request
containing only its non-secret `leagueId`. No `userSecretId` was needed. The
response described the historical 2025–26 league (`seasonYear: 2025`), not the
future 2026–27 configuration.

The 2026-09-05 response retained the same historical 2025–26 settings and
added this top-level object:

```json
{
  "lastRegularSeasonPeriod": 18,
  "numPlayoffTeams": 4,
  "firstPlayoffPeriod": 19,
  "mergePlayoffPeriods": false,
  "used": true
}
```

This is not a field-name guess. The same `used` / `firstPlayoffPeriod` /
`lastRegularSeasonPeriod` contract was independently recorded live for another
league on 2026-08-27 in
[`TheCiege23/allfantasy-v2-main`](https://github.com/TheCiege23/allfantasy-v2-main/blob/2511dd8019f57fc5b3f6a72d580da820a3fd93ff/lib/league-import/fantrax/fantraxApi.ts#L93-L104),
whose schedule test classifies periods at and after `firstPlayoffPeriod` as
playoffs only when `used` is true. In this capture, period 18 exists in
`scoringPeriods`, period 19 immediately follows it, and periods 19–21 are the
remaining configured periods.

The normalized `PlayoffRules` therefore records `(19, 20, 21)`. A known
`used: false` records an empty period set, which is distinct from an absent
`playoffs` key. The deadline calendar turns a known period set into explicit
per-period booleans and the scoring-period projection persists those booleans;
unknown evidence still remains `None` and cannot be projected.

The exact five-key object and strict value types are always enforced, including
a non-negative integer for `numPlayoffTeams`. When `used` is true, the
regular/playoff boundary must be adjacent, both boundaries must reference real
scoring-period numbers, and any inline scoring-period playoff markers must
agree. When `used` is false, the boundary fields are still shape/type-validated
but are not used to classify periods, and `scoringPeriods` need not be present.
A missing top-level object preserves the older marker-based contract or remains
absent; a present `null`, malformed object, added or missing key, or enabled
configuration with a conflicting boundary is a `SourceContractError`.
`numPlayoffTeams` and `mergePlayoffPeriods` are shape-validated but not
interpreted by the calendar: the current pipeline models period classification,
not bracket membership or multi-period matchup behavior.
Inline markers are reconciled as sorted period membership, not response-array
order. With a top-level object present, an explicit all-false marker set
corroborates `used=false` and conflicts with `used=true`; without that object,
the legacy marker-only path still refuses an all-false set as ambiguous.

The response still supplied **no fields naming or encoding**:

- lineup-lock type;
- waiver period, processing time, priority or FAAB;
- games-played caps;
- IR slot count or eligibility;
- trade deadline;
- keeper rules.

Those remaining values are explicit unknowns in
`hoops_gm.ingest.league_settings.LeagueSettingsDocument`. They are not inferred
from roster-period timing, reserve capacity, matchups, draft type, or the
historical 2025–26 rules baseline. The existing read-only bridge may later fill
an official unknown, but cannot override an official observation.

For the roster, scoring-period, and playoff fields the parser reserves absent
evidence for a genuinely missing JSON key. A present `null`, wrong-shaped
container, malformed period/position entry, or malformed alias is a
`SourceContractError`. Where a payload supplies both supported aliases
(`number`/`period`, `startDate`/`start`, `endDate`/`end`, or
`isPlayoff`/`playoff`), both are validated before the preferred field wins;
valid preferred evidence cannot hide malformed alternate evidence.

The persisted boundary is `league_settings_snapshots`: immutable versions of
the validated document with per-concern evidence, source-payload hash, and
observation time. Import rejects a document whose `seasonYear` does not match
the target `League.season`; the observed 2025 payload therefore cannot be
attached to a 2026–27 league.

### Scoring type and category evidence — what is consumed, what is dropped

`getLeagueInfo` publishes the same scoring configuration in **two** shapes
under `scoringSystem`, and only one is a fit for a fail-closed vocabulary
mapping. `scoringSystem.scoringCategorySettings[*].configs[*]` is consumed:
each entry's `scoringCategory.code` (a stable identifier — e.g.
`INDIVIDUAL_ASSISTS`), `scoringCategory.name`, `scoringCategory.shortName`
(abbreviation) and `weight` are parsed into
`LeagueSettingsDocument.scoring_categories`, and `scoringSystem.type` (e.g.
`HEAD_TO_HEAD_ROTI_MULTI_WIN`) is parsed into `scoring_type`.
`hoops_gm.scoring.profiles.map_source_categories` maps on `code` — the
numeric `scoringCategory.id` and `shortName` are retained only as display
evidence, never as the mapping anchor, because `id` is unverified as stable
across seasons and `shortName` alone cannot distinguish two categories that
happen to share an abbreviation.

Two things in the same payload are deliberately **not** modeled:

- `scoringSystem.scoringCategories` — a second, flatter rendering of the same
  nine categories (`{"PLAYER": {"AST": {"Default": "1.0"}, ...}}`). It carries
  no `code`, only the abbreviation and a stringified weight, so it cannot
  anchor a fail-closed mapping and would be pure duplication of what
  `scoringCategorySettings` already supplies with more evidence.
- `configs[*].position` — every observed row is `{"code": "DEFAULT", ...}`.
  This league has no position-conditioned category weighting to represent, so
  the field is **not** read or carried into the domain document at all; a
  league that actually used it would need a deliberate design decision to
  parse and store it, not a silent default.

**The `HEAD_TO_HEAD_ROTI_MULTI_WIN` → `ScoringType.H2H_EACH_CATEGORY` mapping
is reasoned evidence, not a confirmed one-to-one contract.** The "H2H" and
"MULTI_WIN" segments match this project's own historical rules baseline
(`docs/league/2025-26-rules-baseline.md`: "H2H each category, 9-cat") and
public head-to-head-categories terminology. The **"ROTI" segment has no
confirmed meaning** — it does not appear in this project's own documentation
or in any first-party Fantrax API reference found during this work, only in
the raw discriminator string itself. Any *other* Fantrax scoring-format
discriminator this adapter has not yet observed and mapped is rejected
(`UnsupportedScoringFormatError`) rather than guessed at; extending the
mapping requires the same standard: independent corroborating evidence, not
just a plausible-sounding string.

### Bridge fallback is explicit and offline

The official ingest command accepts `--bridge-capture PATH` for one
operator-selected JSON file. It never captures a page, reads the bridge
database, authenticates, or polls. The file contract is versioned and rejects
unknown fields:

```json
{
  "schema_version": 1,
  "league_id": "<same Fantrax leagueId>",
  "season_year": 2025,
  "start_date": "2025-10-21",
  "end_date": "2026-03-15",
  "observed_at": "2026-08-18T13:00:00Z",
  "settings": {
    "lineup_lock": {"lock_type": "per_player_tipoff"},
    "roster_limits": {
      "injured_reserve": 3,
      "injured_reserve_eligibility": ["IR", "IR+"]
    }
  }
}
```

Omitted settings are recorded as bridge-absent. Merge requires exact league id,
season year, start date, and end date equality. Official values win field by
field; bridge values can fill only official unknowns. The merged snapshot
records both exact payload digests and the later source observation time. Any
validation or scope failure occurs before the database insert.

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

### `getDraftPicks` is read with provenance, and may not be about a draft at all

`get_draft_picks_with_provenance(league_id, *, max_age)` returns
`(picks, payload_sha256, observed_at)` rather than just the picks. The digest is
the SHA-256 of the exact bytes decoded; `observed_at` is when those bytes
arrived, or on a cache hit when they *originally* arrived — not now.

This exists for `hoops_gm.draft.feed`, which compares this source against the
bridge. An agreement between two readings is only evidence of two readings if
each can name the artifact it came from; without a real digest the feed would
have to invent an identifier, and an invented identifier is how one read gets
counted as two. `observed_at` is the same argument applied to time: a cache hit
reported as fresh is a stale board that says it is live.

**One unknown was settled on 2026-08-28 and the other survived intact.**

The endpoint **is reachable**, and reachable *unauthenticated*: with only a
non-secret `leagueId` it answered `HTTP 200`, `Content-Type: text/plain`, 24
bytes —

```json
{"currentDraftPicks":[]}
```

`sha256:b5811c858f69d6f11a9f6e0d5a878d9622edd21fe1d6f202a9d2bf5cfb915fca`,
recorded as `backend/tests/fixtures/fantrax_getdraftpicks_completed_snake_empty.json`.
League `b2gyornvms4606iv` held a **completed 18-round, 12-team snake draft** at
the time — 216 selections had happened. The endpoint reported none of them. No
`userSecretId` was sent, so the empty list **cannot** be explained by
authentication, and no owner credentials decision is needed to use this endpoint.

**The container key was `currentDraftPicks`, which was not one of the two names
this parser was guessing** (`draftPicks`, `picks`). That mattered independently
of the emptiness: had the endpoint been publishing selections all along,
`parse_draft_picks` would have returned zero of them and the feed would have
reported a healthy, *silent* source — green tests, empty board. The observed key
is now first in `_DRAFT_PICK_LIST_KEYS`; the other two are kept, because one real
payload names one key and does not disprove the others.

**What is still unresolved is meaning, and this read could not settle it.**
`fantraxapi==1.0.1` models a "draft pick" as `round` + `year` + `origOwnerTeam` —
a **tradeable future pick asset**, not a selection that happened. A completed
draft has no unused picks left, so *both* readings predict the empty list that
was observed:

| Reading | Predicts `[]` for a completed draft? |
|---|---|
| Selections that happened | Yes — if the endpoint simply is not populated for this league |
| Tradeable future pick assets a team owns | Yes — correctly, there are none left |

The key name `currentDraftPicks` is *weak* evidence for the second reading and
nothing more. **Do not record either as established.** Every per-record field
name (`teamId`, `playerId`, `round`, `overallPick`, `amount`) is still a guess,
because no populated row has ever been seen on this path.

**One hypothesis was deliberately left untested.** The verified league is NFL and
the request sends no `sport` parameter. Trying one would have been adjusting the
request until it succeeded, which is precisely what the smoke was scoped to avoid,
so it is recorded here rather than answered.

`parse_draft_picks` is therefore still treated as a source that may legitimately
return nothing useful, and the feed reports that as a silent source rather than
as an error.

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

## Fixtures and live smoke

The successful fixture was refreshed from the exact 2026-09-05 response after
those raw bytes were preserved outside the repository. It removes
identity-bearing sections (`leagueName`,
`leagueHistoryId`, `teamInfo`, `playerInfo`, and `matchups`) whole. No retained
source value is edited; every previously retained value is byte-for-byte
unchanged, and only the new `playoffs` object was added. Its manifest records the
original payload hash, size, top-level keys, and exact removed sections.

Refresh that fixture deliberately with:

```bash
HOOPS_GM_FANTRAX_LEAGUE_ID=... \
python -m hoops_gm.ingest.record_fixtures fantrax-league-settings
```

The matching live smoke bypasses cache when
`HOOPS_GM_FANTRAX_LEAGUE_ID` is configured and requires the configured
historical league to resolve playoff periods 19–21, rather than merely
allow-listing the `playoffs` key. It also fails on malformed required fields or
newly appearing, unhandled rule-shaped paths.

### The `getDraftPicks` fixture is a 24-byte recording and must stay one

`fantrax_getdraftpicks_completed_snake_empty.json` is the raw response body,
byte for byte, with **no trailing newline**. Its contract test asserts the
SHA-256 as well as the bytes, because a reformatting would otherwise arrive
looking like an ordinary content change: `json.dumps` of the same payload with
default separators is 26 bytes, and that two-byte gap is the whole distance
between a recording and a re-emission. If you re-capture deliberately, update
`CAPTURED_SHA256` in `TestFantraxDraftPicks` and the manifest together.

Its live smoke defaults to league `b2gyornvms4606iv` — the completed snake mock
the finding came from — and is overridable with
`HOOPS_GM_FANTRAX_DRAFT_LEAGUE_ID`. It does **not** skip when unset: a skipped
smoke on the one endpoint whose behaviour the draft plan depends on is a silent
degradation, and the Adapter gate asks this to fail loudly instead. It goes red
in two directions and both are good news — the list becoming non-empty, or
`currentDraftPicks` disappearing. The second is the one no offline test can
catch, since an absent key and an empty list both parse to zero picks.

---

## Not verified

**The final 2026–27 settings are not available yet.** The source returned the
2025–26 season and cannot verify future rule changes. Re-ingest after Fantrax
rolls the league forward; until then, downstream 2026–27 consumers must treat
every setting as unavailable rather than reuse the historical snapshot.

**The playoff bracket semantics are not fully modeled.** The captured
`numPlayoffTeams` and `mergePlayoffPeriods` values are retained and
shape-validated, but no accessible first-party reference established how
Fantrax applies `mergePlayoffPeriods`, and the existing deadline/scoring-period
pipeline has no bracket representation. Only enabled state and period
classification are normalized.

**`getDraftPicks` has never returned a populated payload.** It is reachable —
verified live 2026-08-28, see the section above — but it returned `[]` for a
league whose 216-pick draft was already complete, so **no row has ever been
observed** and every per-record field name in `parse_draft_picks` remains a
guess. It must be checked against real snake *and* auction responses before
anything depends on it. Beyond shape, its *meaning* is unconfirmed: the pinned
`fantraxapi` models a draft pick as a tradeable future asset
(`round`/`year`/`origOwnerTeam`), so this endpoint may describe pick ownership
rather than pick results, and the observed empty list is consistent with both.
`hoops_gm.draft.feed` consumes it on the assumption that it may be either, and
never treats its silence as failure.

**Whether `getDraftPicks` needs a `sport` parameter is untested.** The verified
league is NFL and the request sends only `leagueId`.

**The "ROTI" segment of `HEAD_TO_HEAD_ROTI_MULTI_WIN` remains semantically
unconfirmed.** See "Scoring type and category evidence" above — the mapping to
`ScoringType.H2H_EACH_CATEGORY` is reasoned from this project's own rules
baseline and general terminology, not from a first-party Fantrax reference for
that exact discriminator string.
