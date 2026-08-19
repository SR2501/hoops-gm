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
IDs separately. It never invents team assignments. The importer writes every
resolved game idempotently; the unresolved Cup games remain absent until the NBA
publishes their teams.

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

## Gate evidence and limits

The committed `ScheduleLeagueV2` fixture and offline contract tests pin the
resolved/TBD split, team coverage, and October/March timezone reconciliation. No
new live evidence is claimed here beyond the existing 2026-08-17 verification.

The six Cup assignments remain unknown, and this contract does not predict when
the NBA will resolve them. A schedule refresh must preserve their explicit
unresolved state until the source changes.
