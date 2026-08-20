# Adapter — `stats.nba.com` via `nba_api`

**Status:** working, verified live 2026-08-17.

Code: `backend/src/hoops_gm/ingest/nba/`
Pinned: `nba_api==1.11.4`

---

## The most important finding in Phase 2

### `BoxScoreSummaryV2`'s inactive list is silently dead

`BoxScoreSummaryV2.InactivePlayers` returned **8 rows for 2025-10-21** — the
season opener — and **zero rows for every subsequent date of the 2025-26
season**. Bisected on 2026-08-17: last working date 2025-10-21, first empty
date 2025-10-22, empty thereafter through 2026-04-12.

It does not error. It does not change shape. It returns an empty list, forever.

`BoxScoreSummaryV3` returns the correct inactive lists for the same games —
nested under `boxScoreSummary.homeTeam.inactives` and `.awayTeam.inactives`,
which is easy to miss because they are not a top-level collection.

**V2 is the endpoint most public examples use.** Anything built on it would
have held no inactive players for an entire season while looking completely
healthy: no error, no exception, no failing test. That is precisely the
silent-wrong-number failure this project is most exposed to, and it lands
directly on the pillar the whole tool is built around.

Consequences, all deliberate:

* `NbaStatsClient` **does not expose `BoxScoreSummaryV2` at all.** Asking for
  it raises. An endpoint that answers "nobody was inactive" when it means "I no
  longer know" is worse than one that fails.
* The contract test asserts a **non-zero inactive count** for a known
  mid-season game, not that the call succeeded and not that the key exists.
  Either weaker assertion would have passed throughout the dead period.
* The live smoke test asserts the same thing against the real endpoint, with a
  failure message saying to treat the availability ledger as suspect.
* `player_participation.inactive_list_available` records whether the source
  *offered* an inactive list, so "nobody was inactive" and "we no longer know"
  stay distinguishable in the data.

---

## Other things the source actually does

### Only `nba_api` can reach the host (risk R27)

`curl` against `stats.nba.com` with the complete documented header set — UA,
Referer, Origin, `x-nba-stats-origin`, `x-nba-stats-token` — is met with a
connection reset after ~21 seconds. `nba_api` reaches the same host and returns
data. **Do not hand-roll requests, and do not conclude the host is down from a
curl failure.**

### The library does not fail cleanly

A nonexistent game id produces `AttributeError: 'NoneType' object has no
attribute 'get'` from inside `nba_api`, not an exception describing the
problem. Every call is wrapped: transport exceptions become `SourceUnavailable`
and anything else becomes a `SourceContractError` naming the endpoint and
parameters, so a backfill log says what failed instead of showing an
unexplained `AttributeError`.

### Parameter names are inconsistent between endpoints

`CommonAllPlayers` takes `league_id`. `LeagueGameFinder` and `PlayerGameLogs`
take `league_id_nullable`. Getting it wrong raises a `TypeError` from the
constructor, which the wrapper reports as a contract error. Every call site is
exercised by a live smoke test rather than trusted.

### `LeagueGameFinder` matchup strings are not always reciprocal

The endpoint returns two team rows per game, but the `MATCHUP` text is not
reliably written from each row's point of view. Ten real games across 2024-25
and 2025-26 repeat the same canonical matchup on both rows. For example, both
the Indiana and San Antonio rows for game `0022400633` say `IND @ SAS`.

The old parser treated `@` as proof that the current row was the away row. Both
rows therefore overwrote the away side, the home side remained absent, and the
game was silently dropped. That produced 1,225 parsed game IDs against 1,230
`PlayerGameLogs` IDs in both seasons, excluding 118 and 102 player logs from
model evidence.

The parser now matches each row's `TEAM_ABBREVIATION` against both named sides
of `MATCHUP`. Reciprocal and repeated-canonical rows reconcile to the same
home/away identity. Duplicate side rows, contradictory matchup orientation,
date disagreement, missing or contradictory payload/row season scope,
noncanonical season/type-specific `GAME_ID`, and same-team home/away identity
raise `SourceContractError`. A one-sided response also raises with the
unsupported side named; it is never silently dropped and no opponent ID or
score is invented. Recorded fixtures select whole game groups rather than a
raw row boundary, so fixture generation cannot manufacture an incomplete pair.
One repeated-canonical game is also checked against `BoxScoreSummaryV3`'s
independent home/away team IDs, rather than treating cardinality as proof of
correct orientation. Season backfill supports only the source's `Regular
Season` and `Playoffs` labels; every other label is rejected before a request.
Output remains sorted by stable NBA `GAME_ID`, `GAME_DATE` remains the NBA's
Eastern local date, and this endpoint still supplies no tip-off instant.

### Inactive players are absent from the traditional box score

`BoxScoreTraditionalV3` lists only players who **dressed** — those who played,
plus those who dressed and did not, carrying a `comment`. A player on the
inactive list has no row there at all. Both endpoints are required to build one
game's participation, which is why the backfill costs two requests per game.

### DNP comment vocabulary, and its inconsistent separator

Observed in the 2025-26 and 2024-25 seasons:

```
"DNP - Coach's Decision"
"DNP - Injury/Illness"
"DND - Injury/Illness"
"NWT - Not With Team"
"NWT-Return to Competition Reconditioning"     <- no spaces around the hyphen
```

Splitting on `" - "` drops the last one on the floor. `DNP` = did not play,
`DND` = did not dress, `NWT` = not with team.

The raw text is **always** preserved beside the normalised code. House rule:
do not trust stated DNP reasons — "rest" is routinely laundered as a minor
ailment — so the normalisation is a convenience for querying, not a fact, and
unrecognised text maps to `OTHER` rather than being forced into the nearest
category.

### Minutes come in three representations

| Source | Form | Exact? |
|---|---|---|
| `PlayerGameLogs.MIN_SEC` | `"48:24"` | yes |
| `PlayerGameLogs.MIN` | `48.4` | **no** — rounded decimal |
| V3 box score `statistics.minutes` | `"25:40"` or `"PT34M12.00S"` | yes |

`MIN_SEC` is preferred wherever both exist. `""` and `None` parse to `None`,
meaning *did not play* — a different claim from zero seconds, and availability
modelling depends on the difference.

### The crosswalk needs the *current* season

`CommonAllPlayers(season="2026-27", is_only_current_season=1)` returned 580
players, all with a team. Against a historical season, every player who moved
in the offseason produces a spurious team disagreement — which, before it was
understood, dropped Giannis Antetokounmpo, Luguentz Dort and Naz Reid out of
the crosswalk entirely.

`DISPLAY_LAST_COMMA_FIRST` happens to be the same `"Last, First"` shape Fantrax
uses. That is a convenience, not a contract: the box-score endpoints give the
name in parts and the game logs give `"First Last"`.

### `gameEt` carries a `Z` suffix and is not UTC

The season-schedule endpoint has its own canonical contract in
[`nba-schedule.md`](nba-schedule.md). Both adapters preserve the same distinction:
the UTC field is the instant, while the Eastern wall-clock field supplies the
NBA game date after independent reconciliation.

The same payload shows `gameTimeUTC = 2024-12-01T20:30:00Z` and
`gameEt = 2024-12-01T15:30:00Z` — five hours apart, both marked UTC. `gameEt`
is Eastern time wearing a UTC marker.

It is read for its **date only** and never passed to the instant parser, which
would take the `Z` at face value and be five hours wrong.

This matters because `nba_games.game_date` means the **local** date — fantasy
days are defined in local time — so it must come from `gameEt`, not from
`gameTimeUTC`. Game `0022500560` has `gameTimeUTC = 2026-01-13T00:30:00Z` and
is a **2026-01-12** game. Deriving the date from the instant is wrong for every
game tipping after 7pm Eastern, which is most of them, and disagrees with
`LeagueGameFinder` for the same game. Pinned by three contract tests.

---

## Throttling, retry and failure

| Concern | Behaviour |
|---|---|
| **Throttle** | One request every **1.1 seconds**, just under the commonly cited ~1 req/s. A season backfill is thousands of requests and being throttled mid-backfill costs far more than the extra 100 ms. |
| **Retry** | 3 attempts, exponential backoff with jitter, **only** on `SourceUnavailable`. |
| **Cache** | A completed game's box score is immutable, so per-game captures effectively never expire. Player and schedule listings get a 12-hour window. This is what makes a ~2,460-request season backfill resumable rather than restartable. |
| **Source down** | `requests` transport exceptions → `SourceUnavailable`, retried. |
| **Returns garbage** | Anything else escaping `nba_api` → `SourceContractError` naming the endpoint and parameters. Never retried. |
| **One bad game** | Does not abort a backfill. Failures are counted, named with their game ids, and reported at the end with a non-zero exit code. |

The live `LeagueGameFinder` smoke test requires exactly 1,230 regular-season
games and exact game-ID equality with `PlayerGameLogs`. A loose “more than
1,000” assertion previously accepted the 1,225-game cohort and could not detect
this defect.

---

## Backfill cost

| Work | Requests | Wall clock |
|---|---|---|
| Crosswalk (teams, players, Fantrax) | ~3 | seconds |
| One season: games + box scores | 2 | seconds |
| One season: participation (per game) | ~2,460 | **~45 minutes** |

Participation is opt-in (`--with-participation`) for that reason. Production
and availability are separated everywhere else in this project; separating how
they are fetched follows.
