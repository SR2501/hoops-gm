# ADR-013 — Forward-schedule completeness: source-declared pending is not a resolution failure

**Status:** Accepted
**Accepted:** 2026-08-20 by the project owner
**Date:** 2026-08-20

## Context

`import_schedule` refuses any cohort containing a game whose teams did not resolve
(`ingest/importers.py:580`). That rule exists because a parser once read `MATCHUP`
wrongly and silently returned 1,225 of 1,230 games, contaminating committed model
evidence (R46, ADR-009's adapter contract).

Applied to the **forward** 2026-27 schedule it refuses everything. Verified live on
2026-08-20: `ScheduleLeagueV2` returns 1,206 regular-season entries, of which our parser
resolves 1,200 covering all 30 teams at 80 games each, 2026-10-20 to 2027-04-11. The
remaining six — `0022601201`–`04`, `0022601229`, `0022601230` — are Emirates NBA Cup
quarterfinals and semifinals whose teams are decided by group play in December.

The NBA is not failing to tell us something; it is correctly telling us the bracket is
undetermined. The season is also legitimately unfinished beyond those six: teams
eliminated early receive make-up games, so 80 games per team today becomes 82 later.

Draft day is 18 October and does not move. Under the present rule the schedule grid
cannot show the real league before the draft it exists to serve.

## Decision

Distinguish **source-declared pending** from **resolution failure**.

A game the source publishes with explicitly absent team identifiers is *pending*. It is
recorded by ID in the completeness block, does not block registration, and must be
surfaced by consumers. A game the source claims to have assigned but which we cannot
resolve remains a failure and still refuses.

The completeness invariant changes from `resolved == source_game_count` to
`resolved + pending == source_game_count`, with `pending_game_ids` recorded alongside
`unresolved_game_ids`. A registered refresh asserts *"this is what the source has
published"*, not *"the season is fully scheduled"*.

Consumers displaying schedule counts must show the pending set, not merely omit it. The
schedule grid's lineage panel already carries source, resolved and persisted counts; it
gains pending.

## Consequences

The grid can show the real 2026-27 season now. Counts will change as the NBA publishes
fixtures, and the content fingerprint changes with them — correctly, because the facts
changed. Anything downstream that consumes games-per-period must treat counts before
December as provisional; `quant` should not fit anything to an 80-game team season.

## Amendments

### 2026-08-20 — the content fingerprint does not cover the pending set

The Consequences paragraph above says the content fingerprint changes as the pending set
resolves. **That is true only when a bracket is drawn, and false for a change in the
pending set alone.** Measured by the frontend lane on two real responses: a cohort of
10 source / 10 resolved and one of 12 source / 10 resolved / **2 pending** both fingerprint
to `9bcac1c60490b41a`.

The mechanism is that `schedule_content_version` is computed over persisted `team_schedule`
rows (`ingest/importers.py`), and a pending game has no rows by definition. So two refreshes
differing only in *which* games are pending share a version.

Two consequences, and the second is the larger one.

**A consumer must not cache the pending set keyed on the schedule version alone.** The hole
is narrow — it closes the moment a bracket is drawn, because that creates rows — but a
reader who assumes the version covers everything the completeness block reports will be
wrong in exactly this way.

**The pending set is currently unverifiable.** `verify_refresh` recomputes a fingerprint
from persisted content and compares it to the registered label; pending games have no
persisted artifact to recompute from, so a forged or drifted `pending_game_ids` cannot be
detected by the mechanism that detects every other kind of schedule drift. Closing that
requires persisting pending games — schema and migration — and is filed as a separate unit
rather than bolted onto the lane implementing this ADR.

This amendment corrects a factual claim in Consequences. **The decision itself is
unchanged**, which is why this is an amendment rather than a superseding ADR.

## Rejected

**Wait until December.** Delivers none of the value to avoid 0.5% incompleteness, and
misses draft day entirely.

**Import the 1,200 and omit the six silently.** That is precisely the 1,225-of-1,230
failure, reintroduced deliberately.

**Weaken the completeness contract.** It caught a real defect today. The correction is to
make it distinguish two situations, not to make it see less.

## What would flip this

If the source is ever observed publishing absent team identifiers for a reason other than
an undetermined bracket — a partial outage, a schema change, a data error — then "pending"
no longer means "not yet decided", and the distinction collapses. The live smoke must
therefore assert the pending set is structurally explicable (currently: NBA Cup knockout
labels), not merely that it is small. If that assertion fails, revert to refusing.
