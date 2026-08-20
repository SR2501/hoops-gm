# Adapter — NBA season schedule via `ScheduleLeagueV2`

**Status:** working, verified live 2026-08-17.

Code: `backend/src/hoops_gm/ingest/nba/schedule.py`
Source: `stats.nba.com` through `nba_api`

## Contract

`ScheduleLeagueV2` is the canonical source for the NBA season calendar.
The recorded 2026–27 response contains 1,206 regular-season entries:

- 1,200 resolved games covering all 30 NBA teams, with 80 currently assigned
  games per team;
- six NBA Cup games whose teams are still `TBD`.

The parser returns the 1,200 resolved games and reports the six unresolved game
IDs separately. It never invents team assignments. The importer refuses a cohort
that still carries unresolved IDs (see *Completeness contract on import* below);
until the NBA publishes those teams, no schedule refresh is registered for the
season.

The official schedule PDF inspection is retained as
[`nba-schedule-2026-27.json`](nba-schedule-2026-27.json) for provenance. Its
1,200 numbered rows corroborate the resolved count, but the JSON endpoint is the
adapter source and no PDF parser exists.

## Time semantics

`gameDateTimeUTC` is the game instant. `gameDateTimeEst` is an Eastern
wall-clock value and is reconciled through `America/New_York`; it is not treated
as an independently trustworthy instant. The resulting local game date must
agree with the NBA calendar date across both standard and daylight-saving time.

This is the same class of semantic check documented for `gameEt` and
`gameTimeUTC` in [`nba-stats.md`](nba-stats.md): a well-formed timezone marker
does not prove that a field means what its label claims.

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

- the source reported games with unresolved teams;
- the source's own game count disagrees with the resolved count;
- a referenced NBA team is missing from the database;
- a persisted `nba_games` row contradicts the parsed source about the game's
  season, season type, Eastern date, or which teams played — `import_games`
  deliberately never rewrites core identity, so a contradictory pre-existing
  row would otherwise leave `nba_games` and `team_schedule` disagreeing;
- the rows read back afterwards are not exactly two mirrored rows per parsed
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
resolved count, unresolved IDs, and `persisted_team_row_count` under
`summary.schedule_completeness`, and its version is
`hoops_gm.db.lineage.schedule_content_version` — a fingerprint recomputed from
the persisted rows over stable NBA identifiers. `check_cohort` recomputes with
the same function, so a claimed version stops validating the moment the rows
behind it change, including when the row count is unchanged. A completeness
block that contradicts itself, its own refresh scope, or the cohort its version
fingerprints raises rather than falling back to a string comparison.

`source_game_count` is the number of regular-season entries in the returned
`ScheduleLeagueV2` document, not an independently published season total. The
client sends only league `00` and season, the parser verifies the response's
`seasonYear`, and ordinary JSON truncation cannot parse successfully; however,
a coherent upstream response containing only a subset would still describe
that subset consistently. The live 1,206-entry observation and the independent
historical `LeagueGameFinder`/`PlayerGameLogs` equality checks are drift
evidence, not proof that every future `ScheduleLeagueV2` response is whole.

**Limitation.** The recorded 2026–27 payload contains six NBA Cup games whose
teams are still TBD, so under this contract that season registers no schedule
cohort until the NBA resolves them, and everything keyed to a schedule version
refuses in the meantime. That is the chosen behaviour: a season-length
denominator that is quietly six games short is worse than a loud refusal. If an
explicitly-labelled incomplete-cohort state is ever wanted, it is a new,
separately-named state — not a softening of this check.

## Gate evidence and limits

The existing 2026-08-17 live verification established the full 1,200/6 split
and all-30-team coverage. The committed trimmed `ScheduleLeagueV2` fixture and
offline contract tests exercise the parser's resolved/TBD handling and
October/March timezone reconciliation on a representative sample; they do not
independently preserve the full live-response counts. No new live evidence is
claimed here.

The six Cup assignments remain unknown, and this contract does not predict when
the NBA will resolve them. A schedule refresh must preserve their explicit
unresolved state until the source changes.
