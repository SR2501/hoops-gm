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
score is invented. Full-season parsing also requires NBA league `00`, team
rows, and neutral values for every other declared request parameter. A date,
game, team, opponent, player, statistical, or other narrowing filter therefore
cannot masquerade as a complete season payload. Recorded fixtures select whole
game groups rather than a raw row boundary, so fixture generation cannot
manufacture an incomplete pair.
One repeated-canonical game is also checked against `BoxScoreSummaryV3`'s
independent home/away team IDs, rather than treating cardinality as proof of
correct orientation. Season backfill supports only the source's `Regular
Season` and `Playoffs` labels; every other label is rejected before a request.
Both supported scopes have recorded fixtures and live identity-set smoke tests.
Participation backfill also compares every fetched `BoxScoreSummaryV3` game ID,
Eastern date, designated teams, and score against its `LeagueGameFinder` row and
records a loud per-game source failure on any contradiction. The live smoke
checks the independent home/away anchor for all ten known repeated-canonical
games. Production season backfill parses both whole-season sources before any
write, rejects an empty `LeagueGameFinder` cohort, and requires exact game-ID
set equality with `PlayerGameLogs`; player logs for a game omitted from the
schedule can no longer degrade into a successful import with skipped rows.
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

### `PlayerIndex` is the only source of a player position this project has

**Status:** added 2026-08-20. Verified live the same day.

Until this landed, **hoops-gm ingested no player position at all.** The only
position-shaped field anywhere was `BoxScoreTraditionalV3.position`, which is a
*starting-lineup slot*: exactly five per team per game, always `F,F,C,G,G`,
blank for everyone else, verified across all 346 team-games of the injury
cohort window. It answers "which slot did he start in tonight". It is not a
player attribute, and a distribution over it is forced to 2F:2G:1C for any
cohort whatsoever.

That mattered because risk R7 specifies the identity crosswalk to match on
"normalized name + team + **position**". The first link in the spine was
specified as three-key and could only ever have been two-key.

`PlayerIndex` supplies the missing field in **one request for the whole
league**:

| Property | Observed 2026-08-20 |
|---|---|
| Rows, season 2026-27 | 578, **one per `PERSON_ID`, zero duplicates** |
| Rows, season 2025-26 | 582, likewise |
| Position stated | 572 of 578 (98.9%) |
| Vocabulary | `G` 241, `F` 180, `C` 61, `G-F` 37, `F-C` 25, `C-F` 17, `F-G` 11 |
| Per-team rows | 15–24, position mix uneven (ATL: 13 `G`, 7 `F`, 2 `C`) |

#### It was checked against something independent, not believed

A field that describes itself is a claim, not a fact — the house rule that came
out of `gameEt`. So `PlayerIndex.POSITION` was attacked with the specific
hypothesis that it might be another lineup slot:

* **One row per person id**, against a per-team-per-game field.
* **Roster-sized groups**, 15–24 per team rather than five.
* **Hybrids** (`G-F`, `F-C`) that a five-slot string cannot express.
* **Cross-season stability**: 490 players appear in both 2025-26 and 2026-27,
  and **all 490 carry identical positions**. Nothing derived from games does
  that.
* **A second endpoint agrees.** Two players sampled per position value, 14
  total, checked against `CommonPlayerInfo.POSITION` — 14/14 exact
  (`C`↔`Center`, `F-G`↔`Forward-Guard`, …).

#### The vocabulary is coarse, and that is load-bearing

**There is no `PG`, `SG`, `SF` or `PF` anywhere.** Three endpoints agree:
`PlayerIndex` says `G`, `CommonPlayerInfo` says `"Guard"`, `CommonTeamRoster`
says `G`. Asking `PlayerIndex` to filter on `PlayerPosition=PG` is answered
`{"PlayerPosition": ["Invalid parameters"]}` — the parameter exists in
`nba_api`'s signature and the server rejects the value.

So this field separates a centre from a guard, which is what R7 needs, and it
**cannot express a Fantrax lineup slot**. It is not Fantrax position
eligibility and cannot be made into it by derivation: eligibility is a policy
decision by a third party that changes through a season and never decreases,
not a computable function of NBA game data. See `player-position-eligibility`
in `docs/backlog.md`.

#### Six players genuinely have no position

All six are `FROM_YEAR: 2026`, and `CommonPlayerInfo` returns `''` for them
too. They are persisted as `NULL`. Inventing a position would corroborate an
identity match on evidence nobody supplied.

#### What it did to the crosswalk

Measured against the committed fixtures rather than assumed. Position evidence
across candidate pairs went from **576 `UNKNOWN` and nothing else** to
**531 `AGREE`, 35 `DISAGREE`, 10 `UNKNOWN`**.

Accepted matches: **570 before, 570 after — and not the same 570.**

* **Gained `Johnson, Jalen`.** Fantrax carries two rows of that name, one on
  ATL listed `SF` and one with no team listed `SG`; the NBA has one, on ATL,
  listed `F`. Position agrees with the first and contradicts the second. That
  is exactly the duplicate-name disambiguation R7 specified position to do.
* **Lost `Tillman, Xavier`.** Fantrax `C` with no team, NBA `F` — the same
  human, two defensible readings of a borderline big. With team absent there is
  nothing to offset the 0.12 position penalty, so a correct match falls to
  0.730 and under the accept floor.

All 35 disagreements are of the second kind — Klay Thompson `SF`/`G`, Evan
Mobley `PF`/`C`, Kevon Looney `C`/`F`. **Position disagreement is weak evidence
of identity mismatch**, for the same reason `evidence.py` already lowered the
*team* penalty: the sources genuinely classify borderline players differently.
The penalty is the identity lane's to re-tune; this lane recorded the effect
and pinned it in a test rather than changing a matcher it does not own.

#### Guards, and what each can and cannot see

| Guard | Fires when | Blind to |
|---|---|---|
| Required columns | any column this parser **reads** disappears, including the two name columns nothing consumes yet | a renamed-but-present column |
| Usable `PERSON_ID` | a row's person id is present but not an integer | — |
| Declared season | the season is not `YYYY-YY`, or the payload's `parameters.Season` contradicts the requested one | a payload that echoes no parameters (withholds rather than fails) |
| Vocabulary | any value outside the seven, **including a merely new one** | a same-vocabulary meaning change |
| One row per person id | a repeated `PERSON_ID` | an exact duplicate row is reported with the same message as a per-stint one, which overstates that case |
| Coverage floor (90%) | the column empties, **or thins to a starters-only shape** (5 of a 15–24 man roster ≈ 26%) | a fully-populated meaning change; and its message names starters-only or emptied, which are the causes near the *bottom* of its range, not at 87% |

The **usable `PERSON_ID`** row exists because of a defect review found in the
first version: unparseable ids were skipped with a bare `continue`, and the
coverage floor divides by the rows that *survived* parsing. So losing 500 of 578
rows reported **100% coverage** and raised no error — a guard whose denominator
moves with the failure it watches for. It is now fatal.

No assertion over a single payload can see a payload that keeps full coverage
and this exact vocabulary while the values come to mean something else. The
live smoke's **cross-season stability check** is what covers that, and it is
the reason that test exists. Each guard above was verified by neutering it in
the parser and confirming its test goes red — **after** confirming that test
was green beforehand, because a mutation run against a test that errors on
collection is a red that proves nothing. That happened once here, on a test
name that did not exist yet.

The **declared-season** guard exists because independent review found `season`
was a pure caller assertion: stamped onto every record and thence onto
`players.primary_position_season`, whose whole justification is that a stored
position must know which season it describes, and checked against nothing. That
is the `gameEt` shape. The payload echoes the season the server actually
served, so it is now corroborated against that.

#### One writer, one reader — and they are not the same path

`players.primary_position` is **written** by `backfill.build_crosswalk` (via
`import_player_positions`) and **read** by exactly one consumer:
`projections.importer.build_player_targets`, the projection-CSV matcher.

That distinction was wrong here until review caught it, and it matters:

* `build_crosswalk` never reads the column. It feeds the resolver from the
  in-memory `NbaPlayerPositionRecord` list that `parse_player_index` returned,
  then writes the column as a side effect.
* So **the crosswalk evidence measured above is produced entirely by the parse
  path** and is unchanged whether `import_player_positions` persists a single
  row or not.
* `build_player_targets` has **always** passed `position=player.primary_position`
  into `ResolvableRecord.build`. Because nothing ever wrote the column, that
  path was silently position-blind for its entire life, and it flips to
  position-aware the first time the crosswalk runs — which is a behaviour
  change with no diff.

The same trade-off applies to both paths, with the same weights: a vendor
calling a borderline big `C` where the NBA lists `F`, with no team to offset it,
drops a correct match under the accept floor. Pinned by
`TestProjectionTargetsAreNowPositionAware`. Anyone re-tuning
`_DISAGREEMENT_PENALTY["position"]` moves both, though only one of them is
reading the persisted value.

**No test exercises the persisted column feeding a crosswalk**, because no code
path does.



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
| **Cache** | A completed game's box score is immutable, so per-game captures effectively never expire. Player and schedule listings get a 12-hour window, and `PlayerIndex` uses the same roster window: a position changes across seasons, not across an afternoon. This is what makes a ~2,460-request season backfill resumable rather than restartable. |
| **Source down** | `requests` transport exceptions → `SourceUnavailable`, retried. |
| **Returns garbage** | Anything else escaping `nba_api` → `SourceContractError` naming the endpoint and parameters. Never retried. |
| **One bad game** | Does not abort a backfill. Failures are counted, named with their game ids, and reported at the end with a non-zero exit code. |

The live `LeagueGameFinder` smoke test requires exactly 1,230 regular-season
games and exact game-ID equality with `PlayerGameLogs`. A loose “more than
1,000” assertion previously accepted the 1,225-game cohort and could not detect
this defect.

### Cohort-window reconciliation (`cohort_evidence`)

`hoops_gm.ingest.injury_report.cohort_evidence` adds one more consumer of this
source, with the same throttle, retry and cache behaviour as every other — it
uses the same `NbaStatsClient`, so no separate rate budget exists.

| Concern | Behaviour |
|---|---|
| **Requests** | Zero on a normal regeneration: the three views are read from retained captures. Exactly one throttled request per view the store has never seen, and only with `--allow-fetch`. |
| **Cache** | Reads whatever the raw store holds for each endpoint's exact parameter set. A cohort manifest is meant to describe the sweep that produced it, so a stale-but-retained capture is the correct input, not a defect. |
| **A view is absent** | Exit 1, naming the missing views. Publishing a cohort over an absent witness is exactly the failure the reconciliation exists to prevent, so fewer agreeing views is never treated as agreement. |
| **Views disagree** | Exit 1, printing which view lacks which game ids. Never a count — the count is what let the first defect survive review. |
| **Tip-off instants disagree** | Exit 1, printing both instants for each disagreeing game. `BoxScoreSummaryV3` and `ScheduleLeagueV2` must agree on when a game started, because every lead time and the pre-tipoff rule that defines the dataset rest on it. |
| **No `ScheduleLeagueV2` capture retained** | Exit 1. The tip-off comparison is not skipped when its witness is missing; an unverified instant is not published as a verified one. |
| **Zero games, or zero tip-off instants, compared** | Exit 1. Views that all found nothing agree perfectly and witness nothing — `agreed` and `witnessed` are separate questions and both are checked. |
| **Source down / garbage** | Only reachable under `--allow-fetch`, where the shared client's `SourceUnavailable` / `SourceContractError` behaviour above applies unchanged. |

The manifest it writes reads no clock and generates no identifiers, so it is a
pure function of the persisted database, the raw store and the operational
report files: regenerating over the same state reproduces it byte for byte. A
fresh live sweep necessarily does not, because capture timestamps record when
requests were made.

---

## Backfill cost

| Work | Requests | Wall clock |
|---|---|---|
| Crosswalk (teams, players, positions, Fantrax) | ~4 | seconds |
| One season: games + box scores | 2 | seconds |
| One season: participation (per game) | ~2,460 | **~45 minutes** |

Position costs exactly **one** request, which is why `PlayerIndex` is used
rather than `CommonPlayerInfo`: the latter states the same position in long
form but per player, so ~580 players is a ten-minute throttled sweep to learn
what one request already says. It rides in `build_crosswalk` because that is
where the identity evidence it corroborates is assembled.

Participation is opt-in (`--with-participation`) for that reason. Production
and availability are separated everywhere else in this project; separating how
they are fetched follows.
