# Adapter — Fantrax official API (`/fxea/general/`)

**Status:** working. `getPlayerIds` and `getAdp` verified live 2026-08-17;
`getLeagueInfo` verified live 2026-08-18. `getDraftPicks` remains unverified.

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

### `getLeagueInfo` exposes only part of the rules boundary

Verified against the target private league with one low-frequency request
containing only its non-secret `leagueId`. No `userSecretId` was needed. The
response described the historical 2025–26 league (`seasonYear: 2025`), not the
future 2026–27 configuration.

The response supplied roster totals and position constraints, roster-period
boundaries, scoring-period boundaries, scoring categories, draft type, matchups,
and season dates. It supplied **no fields naming or encoding**:

- lineup-lock type;
- waiver period, processing time, priority or FAAB;
- games-played caps;
- IR slot count or eligibility;
- trade deadline;
- playoff periods or flags;
- keeper rules.

Those values are explicit unknowns in
`hoops_gm.ingest.league_settings.LeagueSettingsDocument`. They are not inferred
from roster-period timing, reserve capacity, matchups, draft type, or the
historical 2025–26 rules baseline. The existing read-only bridge may later fill
an official unknown, but cannot override an official observation.

For the roster and scoring-period fields the parser reserves absent evidence for
a genuinely missing JSON key. A present `null`, wrong-shaped container, malformed
period/position entry, or malformed alias is a `SourceContractError`. Where a
payload supplies both supported aliases (`number`/`period`, `startDate`/`start`,
`endDate`/`end`, or `isPlayoff`/`playoff`), both are validated before the
preferred field wins; valid preferred evidence cannot hide malformed alternate
evidence.

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

The successful fixture removes identity-bearing sections (`leagueName`,
`leagueHistoryId`, `teamInfo`, `playerInfo`, and `matchups`) whole. No retained
source value is edited. Its manifest records the original payload hash, size,
top-level keys, and exact removed sections.

Refresh that fixture deliberately with:

```bash
HOOPS_GM_FANTRAX_LEAGUE_ID=... \
python -m hoops_gm.ingest.record_fixtures fantrax-league-settings
```

The matching live smoke bypasses cache when
`HOOPS_GM_FANTRAX_LEAGUE_ID` is configured and fails on malformed required
fields or newly appearing, unhandled rule-shaped paths.

---

## Not verified

**The final 2026–27 settings are not available yet.** The source returned the
2025–26 season and cannot verify future rule changes. Re-ingest after Fantrax
rolls the league forward; until then, downstream 2026–27 consumers must treat
every setting as unavailable rather than reuse the historical snapshot.

**`getDraftPicks` has not seen a successful real payload.** Its parser remains
defensive and must be checked against both snake and auction responses before
anything depends on it.

**The "ROTI" segment of `HEAD_TO_HEAD_ROTI_MULTI_WIN` remains semantically
unconfirmed.** See "Scoring type and category evidence" above — the mapping to
`ScoringType.H2H_EACH_CATEGORY` is reasoned from this project's own rules
baseline and general terminology, not from a first-party Fantrax reference for
that exact discriminator string.
