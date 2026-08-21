# Adapter — NBA season schedule via `ScheduleLeagueV2`

**Status:** working, verified live 2026-08-20.

Code: `backend/src/hoops_gm/ingest/nba/schedule.py`,
`backend/src/hoops_gm/ingest/schedule_import.py`
Source: `stats.nba.com` through `nba_api`

## Contract

`ScheduleLeagueV2` is the canonical source for the NBA season calendar.
Captured live on 2026-08-20 (2,474,177 bytes, 173 game dates), the 2026–27
response contains 1,206 regular-season entries:

- 1,200 **resolved** games covering all 30 NBA teams, at exactly 80 currently
  assigned games per team, 2026-10-20 to 2027-04-11;
- six **pending** games — `0022601201`–`04` and `0022601229`/`30`, the Emirates
  NBA Cup quarterfinals and semifinals, whose teams group play decides in
  December.

The parser returns the resolved games and reports the pending ones separately,
with their date and labels. It never invents team assignments.

## Three classes, and why the middle one exists (ADR-013)

Each side of each game falls into exactly one class, decided from the payload
rather than inferred:

| Class | Payload shape | Import behaviour |
|---|---|---|
| Resolved | `teamId > 0` with a valid three-letter `teamTricode` | Persisted |
| **Pending** | `teamId: 0` **and** every one of `teamName`, `teamCity`, `teamTricode`, `teamSlug` absent, null or empty | Recorded, not persisted, does **not** block |
| Unresolved | `teamId: 0` with **any** naming field populated | **Refuses the whole cohort** |

A fourth refusal, separate from the three-way classification above: a game
that resolves cleanly but names a `teamId` the database does not hold is
refused by `_require_known_teams`, not by the parser. It never reaches
`unresolved_game_ids`, because the parser has no view of `nba_teams`. Keeping
these distinct matters — one is the source contradicting itself, the other is
our own identity table being behind.

**One asymmetry worth naming:** `_require_known_teams` walks only the resolved
games. A game with one side pending and the other side a real but unknown
`teamId` classifies as pending, so the unknown id is never reported. Nothing
is persisted and the completeness invariant still holds, so this costs a
diagnostic rather than correctness — but a half-decided Cup fixture is a
realistic shape (group winners are known before the wildcards), and if the
source ever publishes one, the known side is silently discarded.

A pending game's block, verbatim from the live payload:

```json
{"teamId": 0, "teamName": null, "teamCity": null, "teamTricode": null, "teamSlug": null,
 "wins": 0, "losses": 0, "score": 0, "seed": 0}
```

with `gameStatus: 1`, `gameStatusText: "TBD"`, `gameCode: ""`, `arenaName: ""`,
`gameLabel: "Emirates NBA Cup"`, `gameSubLabel: "Quarterfinal"` (×4) or
`"Semifinal"` (×2), `gameSubtype: "in-season-knockout"`, and
`seriesText: "Date subject to change"`.

That **every naming field is null, not merely the id zero**, is what makes the
distinction determinable from the payload rather than guessed. The narrow
middle class is deliberate: it is what keeps the unresolved refusal reachable.
Without it the parser could only resolve, zero out, or raise, and the refusal
would be a guard that reads correctly and can never fire.

Only the naming fields are required absent. `wins`, `losses`, `score` and
`seed` are zero for *every* not-yet-played game, so requiring those absent
would classify the entire future schedule as contradictory.

The official schedule PDF inspection is retained as
[`nba-schedule-2026-27.json`](nba-schedule-2026-27.json) for provenance. Its
1,200 numbered rows corroborate the resolved count, but the JSON endpoint is the
adapter source and no PDF parser exists.

## Operator command

```bash
cd backend
python -m hoops_gm.ingest.schedule_import 2026-27 --dry-run   # fetch, parse, report
python -m hoops_gm.ingest.schedule_import 2026-27             # and import
```

One request. Throttled at one per 1.1 seconds and cached for 12 hours by
`NbaStatsClient` (`--max-age-hours` overrides; `0` forces a live request). It
imports the packaged static team list first, unconditionally and without a
request, because `import_schedule` refuses a cohort referencing a team the
database does not hold and a schedule-only command would therefore always fail
against a fresh database.

It takes **no `--database-url`**; it reads `Settings` like
`hoops_gm.ingest.backfill` does, so no connection URL enters `argv` and none
can be echoed. Two prior defects in this repository leaked a credential through
exactly such a flag — one printed it verbatim, one leaked libpq's `password`
query argument past `render_as_string(hide_password=True)`, which masks
`URL.password` and nothing else. The flag is absent rather than guarded, and a
test asserts it stays absent.

Typed exits: `0` success, `2` source contract or completeness refusal (nothing
written), `3` source unreachable after retries, `4` database error (nothing
written).

Verified end to end on 2026-08-20 against a migrated SQLite database: 30 teams,
1,200 `nba_games`, 2,400 `team_schedule` rows at exactly 80 per team, six
pending games recorded with dates and labels, cohort status `current`. A second
run converged on the same version `e80a3aecca0e86eb` with one refresh row.

## Time semantics

`gameDateTimeUTC` is the game instant. `gameDateTimeEst` is an Eastern
wall-clock value and is reconciled through `America/New_York`; it is not treated
as an independently trustworthy instant. The resulting local game date must
agree with the NBA calendar date across both standard and daylight-saving time.

This is the same class of semantic check documented for `gameEt` and
`gameTimeUTC` in [`nba-stats.md`](nba-stats.md): a well-formed timezone marker
does not prove that a field means what its label claims.

The reconciliation runs for pending games too. Their published tip-off is a
provisional Eastern midnight and the two fields agree exactly
(`2026-12-04T00:00:00Z` Eastern against `2026-12-04T05:00:00Z` UTC). Exempting
them would leave the one unchecked time claim in the parser on precisely the
entries the source is most likely to reshape.

## Persistence boundary

The adapter emits observable schedule facts only: game ID, local date, UTC
tipoff, home/away teams, and status. `backend` owns database and API mechanics;
`data-engineer` owns source parsing and interpretation. Fantasy scoring-period
boundaries come from the league calendar and are joined to schedule facts; this
adapter does not define them.

### Completeness contract on import (`backend`)

`import_schedule` consumes the whole `ScheduleParseResult`, not just its games,
and **fails closed rather than registering a partial cohort**. It raises
`SourceContractError` and registers nothing when:

- the source named a team it gave no id for, or named a team the database does
  not hold (the unresolved class above);
- the source's own game count disagrees with resolved **plus** pending;
- the same game is reported as both resolved and pending;
- a persisted `nba_games` row contradicts the parsed source about the game's
  season, season type, Eastern date, or which teams played — `import_games`
  deliberately never rewrites core identity, so a contradictory pre-existing
  row would otherwise leave `nba_games` and `team_schedule` disagreeing;
- the rows read back afterwards are not exactly two mirrored rows per **resolved**
  game on the parsed dates, **including** when the season already holds
  regular-season rows the parsed cohort does not contain.

Nothing is deleted. A leftover row is inconsistent evidence, and the importer
cannot tell a real postponement from a truncated response; deleting it would
cascade into `quant`'s `opponent_context` and could not be undone by re-running
the import. The refusal leaves the rows, the previously registered cohort, and
the operator's options intact. All writes and the final persisted-cohort
readback run inside a savepoint: if a library caller catches the refusal and
commits unrelated outer-transaction work, schedule/game mutations attempted by
the rejected import are still rolled back.

On success the refresh row records the season, season type, source game count,
resolved count, `pending_game_ids`, the richer `pending_games` records,
unresolved IDs (always empty on a registered refresh), and
`persisted_team_row_count` under `summary.schedule_completeness`. The invariant
is `source_game_count == resolved_game_count + len(pending_game_ids)`, replacing
the pre-ADR-013 `source_game_count == resolved_game_count`. A block written
before ADR-013 carries no pending keys and is read as zero pending, which is
exactly what its own contract required.

Its version is `hoops_gm.db.lineage.schedule_content_version` — a fingerprint
recomputed from the persisted rows over stable NBA identifiers. `check_cohort`
recomputes with the same function, so a claimed version stops validating the
moment the rows behind it change, including when the row count is unchanged. A
completeness block that contradicts itself, its own refresh scope, or the cohort
its version fingerprints raises rather than falling back to a string comparison.

**The version does not cover the pending set.** It fingerprints persisted
`team_schedule` rows and a pending game has none, so two cohorts differing only
in which games are pending share a version — measured, not reasoned to: the
demo seed's 10-source cohort and its 12-source, 2-pending successor both
fingerprint to `9bcac1c60490b41a`. So a consumer must not cache the pending set
keyed on the schedule version alone, and `verify_refresh` cannot detect a forged
pending list, though it still detects a forged resolved cohort. The gap closes
per game as the bracket is drawn, because that is when rows appear. Making it
verifiable means persisting pending games, which is schema and migration, and is
filed as a follow-up.

`source_game_count` is the number of regular-season entries in the returned
`ScheduleLeagueV2` document, not an independently published season total. The
client sends only league `00` and season, the parser verifies the response's
`seasonYear`, and ordinary JSON truncation cannot parse successfully; however,
a coherent upstream response containing only a subset would still describe
that subset consistently. The live 1,206-entry observation and the independent
historical `LeagueGameFinder`/`PlayerGameLogs` equality checks are drift
evidence, not proof that every future `ScheduleLeagueV2` response is whole.

**The season is legitimately unfinished beyond the six pending games.** Teams
eliminated from the Cup receive make-up games, so 80 games per team today
becomes 82 later. A registered refresh asserts *"this is what the source has
published"*, not *"the season is fully scheduled"*. `quant` must not fit
anything to an 80-game team season, and any consumer of games-per-period must
treat counts before December as provisional.

## Consumer contract for pending games

A pending game **carries no team, by definition** — withholding the team is
what makes it pending. A consumer may say the scoring period containing
`game_date` is provisional; it may **not** attribute the game to a team.
"DAL and LAL have an unscheduled game" is an attribution the source explicitly
declined to make. The honest statement is period-scoped: *this week contains N
games whose teams are not yet decided, so any count in it is provisional.*

**Provisional is not the same as a floor.** A drawn bracket adds games to the
week it lands in, but a rescheduled fixture leaves one week and joins another,
taking the first week *down*. Only the season total is monotone. A consumer
that renders "at least N games" is making the one-directional claim that
ADR-012's living-refresh amendment exists to deny.

The schedule-grid API surfaces this on `lineage.schedule`:

```jsonc
{
  "source_game_count": 1206,
  "resolved_game_count": 1200,
  "persisted_team_row_count": 2400,
  "pending_game_ids": ["0022601201", "..."],
  "pending_games": [
    {"nba_game_id": "0022601201", "game_date": "2026-12-04",
     "game_label": "Emirates NBA Cup", "game_sub_label": "Quarterfinal",
     "game_subtype": "in-season-knockout"}
  ],
  "unresolved_game_ids": []
}
```

`pending_game_ids` and `pending_games` are cross-checked to hold the identical
sequence, so they cannot drift; both are recorded because ADR-013 names the ID
list as the completeness operand while a screen needs the dates.

## Gate evidence and limits

**Recorded fixtures.** `nba_scheduleleaguev2_2026_27_pending_knockout.json`
holds whole, unmodified game objects for all six pending games plus 18 resolved
ones, captured 2026-08-20. It is what covers label handling offline.
`nba_scheduleleaguev2_2026_27.json` is the older 12-game slice and is
**field-trimmed**: each game object retains six keys and each team block four,
so its pending games carry `gameSubLabel: null` and no `gameSubtype` at all. A
green offline test against that fixture alone says nothing about label
handling — which is exactly why the second fixture exists. Re-verified against
a fresh live capture on 2026-08-20: all 12 games still present and every
retained field byte-identical, including both pending team blocks.

**Live smoke** (`TestTheForwardScheduleStillMeansWhatADR013AssumedItMeant`)
asserts the pending set is *structurally explicable* — every pending game
carries an Emirates NBA Cup label and the `in-season-knockout` subtype — not
merely that it is small. ADR-013's flip condition is precisely that: if the
source ever withholds team identities for another reason, "pending" stops
meaning "not yet decided" and the correct response is to revert to refusing,
not to widen the allowed label set. An empty pending set fails too, because the
Cup bracket is published undecided until December.

**What none of this can see:** whether the resolved games are correct against
any independent view of the 2026-27 season. The cross-source reconciliation
that does that runs against completed seasons, where `LeagueGameFinder` and
`PlayerGameLogs` have rows; a forward schedule has no second witness.
