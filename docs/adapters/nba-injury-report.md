# Adapter — NBA official injury report PDF

**Status:** working, verified live 2026-08-17.

Code: `backend/src/hoops_gm/ingest/injury_report/`

---

## What this actually is

There is no injury-report API. The NBA publishes a PDF to
`ak-static.cms.nba.com`, updated irregularly through the day, and every public
tool that reads it (including the reference implementations consulted while
building this adapter — `johngoodhand/nba-injury-report-pdf-to-df`,
`mxufc29/nbainjuries`) downloads that PDF and re-derives a table from it. This
adapter does the same, deliberately without a Java dependency (`tabula`, which
those tools use): `pdfplumber` reads the drawn ruling lines and word
positions directly.

The report's own columns, unchanged since at least 2022 per prior art:
`Game Date`, `Game Time`, `Matchup`, `Team`, `Player Name`, `Current Status`,
`Reason`.

---

## The finding that matters most: the table cannot be read top-to-bottom

A naive text extraction reads every PDF word as its own line, and the reading
order **does not match the visual table** whenever a `Reason` cell wraps to
two lines. The report vertically **centres** a short cell (Player Name,
Current Status) inside the full height of a taller cell sharing its row
(the wrapped Reason), rather than top-aligning every cell in the row.

Verified against the real captured 2025-11-01 05:30 PM report: Murray,
Keegan's designation is `Out`, reason `Injury/Illness - Left Thumb; UCL
Injury Recovery`, wrapped across two lines. Reading by ascending vertical
position produces, in order:

```
Injury/Illness - Left Thumb; UCL     <- Reason line 1 (row TOP)
Murray, Keegan   Out                 <- Name/Status (row MIDDLE, centred)
Injury Recovery                      <- Reason line 2 (row BOTTOM)
```

So the reason's *first* line prints **above** the player's own name, not
below it — the opposite of the assumption a naive top-to-bottom reader would
make. A parser reading words in visual order would attach that first Reason
line to the *previous* player instead.

**What actually works:** the report draws real horizontal ruling lines
between rows, but only under the `Player Name` / `Current Status` / `Reason`
columns — never under `Game Date` / `Game Time` / `Matchup` / `Team`, which
are forward-filled merged cells with nothing to rule between. Column divider
lines are drawn once, on page 1 only; every later page shares the same
absolute coordinates (identical page size throughout) but draws no verticals
at all. So: derive column x-boundaries from page 1's own header labels
(anchored on the literal word `"Matchup"`, then verified the full sequence is
exactly `Game Date, Game Time, Matchup, Team, Player Name, Current Status,
Reason` — anything else is a `SourceContractError`), reuse those boundaries
for every page, and use each page's own ruling lines as row boundaries. Every
physical text line inside one cell's height is joined with a space, which
correctly reassembles the wrapped Reason without merging two players'
text.

---

## Other things the source actually does

### A page footer overlaps the last data row

`"Page N of M"` sits in the space below the last ruling line, because no
line is drawn beneath it either. Its own `"Page"` token (searched for in the
bottom 20% of the page) is used to clip the final row before it swallows
footer text into the `Team` / `Player Name` columns.

### A wrapped Reason can also split across a page break

Found while fixing a real defect from independent review (a nonempty,
unrecognised row was previously silently dropped instead of raising — see
below): a wrapped, two-line `Reason` does not always fit inside one page.
Verified against the real captured 2025-11-01 05:30 PM report: `Toppin,
Obi`'s row is the last one on page 2, and the second physical line of his
Reason (`"Fracture"`, completing `"Injury/Illness - Right Foot; Stress
Fracture"`) renders *below* page 2's own bottom margin — it reappears alone
at the very top of page 3, with every other column (`Game Date` through
`Current Status`) blank. Per-page parsing cannot see across the page
boundary, so before this fix that orphaned continuation text was silently
dropped by the same blanket `continue` that used to swallow every
unrecognised blank-name/blank-status row, quietly truncating the real Reason
from `"...Stress Fracture"` to `"...Stress"`.

The fix recognises this one specific shape — the *first* row-segment of any
page after the first, with every column but `Reason` blank and that `Reason`
text not the `NOT YET SUBMITTED` marker — and reattaches it to the
immediately preceding entry's `reason_raw` rather than raising or dropping
it. This shape is deliberately narrow (it requires literally every other
column blank) so it cannot be confused with a genuinely new row that merely
inherits forward-filled `Game Date`/`Game Time`/`Matchup`/`Team` values,
which always still carries its own `Player Name`.

### An unrecognised nonempty row raises loudly, never drops silently

A row that names no player and has no status, and whose `Reason` is not the
`NOT YET SUBMITTED` marker and not the page-break continuation shape above,
has no legitimate place in this report's structure. It now raises
`SourceContractError` instead of being silently skipped — a real defect from
independent review: silently dropping such a row is indistinguishable from
ordinary blank filler and would hide exactly the kind of unnoticed
PDF-extraction drift (a mis-detected row boundary, a shifted column, a new
marker phrase) the Adapter gate exists to surface loudly.

### `"NOT YET SUBMITTED"` is not a player status

Two teams in the captured 2025-11-01 report (San Antonio, the Lakers) — and
three more elsewhere in the same document (Oklahoma City, Charlotte, Phoenix)
— had not filed a report as of the capture time. That row carries a team name
and the literal text `NOT YET SUBMITTED` in the `Reason` column, with `Player
Name` and `Current Status` both blank. It is preserved as a row with
`status = NOT_YET_SUBMITTED` and no player name, never invented as a player
entry and never silently dropped — `InjuryReportParseResult.player_entries`
excludes it for a caller that only wants player designations.

### The status vocabulary is closed, and treated that way

Unlike `player_participation`'s free-text DNP comments, `Current Status` is
the league's own fixed designation — OUT, DOUBTFUL, QUESTIONABLE, PROBABLE,
AVAILABLE (official.nba.com's stated reporting policy). An unrecognised
sixth value is a `SourceContractError`, not an `OTHER` bucket: the report
changing its designations is real drift, not messy free text needing
normalisation.

### The filename format has two eras, and may have a third

Verified live 2026-08-17 against archived reports:

| Requested (ET) | Filename | Era |
|---|---|---|
| 2025-11-01 17:30 | `Injury-Report_2025-11-01_05PM.pdf` | legacy, hourly, on the hour |
| 2026-01-15 17:30 | `Injury-Report_2026-01-15_05_30PM.pdf` | current, 15-minute granularity |

The boundary is 2025-12-22 00:00 ET. **The legacy filename only ever encodes
the hour**, yet the report's own masthead consistently reads `:30` past that
hour (`01PM.pdf`'s masthead says `1:30 PM`, not `1:00 PM`) — so masthead
verification (below) tolerates up to 45 minutes of difference rather than
requiring an exact match, which would reject every legacy-era fetch as
"stale" when nothing is wrong.

The NBA changed this format once already, without any announcement found.
It may again for 2026-27. Nothing in `report_url()` can protect against
that in advance — the live smoke test exists specifically to catch it.

### A missing report is 403, not always 404

Verified live 2026-08-17: an in-season historical timestamp that has no
report returns 404, as expected. A **pre-season** date — months before any
report existed — returns **403 Forbidden**, not 404. This CDN does not
consistently distinguish "nothing here" from "you may not have this" for a
report path. Both become `ReportNotAvailable`
(`hoops_gm.ingest.injury_report.client`), a `SourceRejected` subtype, so a
caller does not have to branch on the status code itself.

### The masthead is cross-checked, not trusted blindly

Every parse verifies the PDF's own `"Injury Report: <date> <time> <AM|PM>"`
masthead against the timestamp the caller requested (with the 45-minute
tolerance above). This guards against a stale or mismatched cache entry
silently attributing one report's content to the wrong timestamp — the same
category of failure the schedule adapter's `gameEt`/`gameTimeUTC`
reconciliation exists to catch, applied to a document instead of a JSON
field.

### The persisted timestamp is the masthead's, never the request's

A real defect found in independent review: the legacy hourly-filename era
truncates every request to the hour (`report_url()`), and the masthead
tolerance above accepts up to 45 minutes of drift from that truncated
request — so two different requested instants (e.g. `17:12` and `17:41`) can
both resolve to the identical PDF and identical masthead (`17:30`). Because
`report_timestamp` is part of `injury_report_entries`'s natural key
(`report_timestamp, team_raw, player_name_raw, game_date`), persisting the
*request* instant on each import would let each of those different requests
create its own row for what is really one report capture — manufacturing
false status history for `injury-status-conversion` to (wrongly) learn from.
Fixed: `parse_injury_report_pdf` returns (and stamps every entry with) the
masthead's own parsed instant, converted to UTC, never the caller's
`report_timestamp` argument — that argument is now only ever a request hint
used for the tolerance check above.

A second, independently-found defect in the same natural key: `game_date`
was originally *not* part of it, even though every parsed entry already
carries its own `game_date` column. One masthead reporting a team's
back-to-back can legitimately produce two rows for the identical player, on
the identical team, at the identical `report_timestamp` — one per night —
differing only in `game_date`. Without `game_date` in the key, the second
night's import silently overwrote the first as though it were a correction,
permanently losing one of the two nights. Migration `0013` (see below)
adds `game_date` to the unique constraint
(`uq_injury_report_entries_report_team_player_date`); the importer's natural
key and existing-row lookup were updated to match, and a regression test
(`test_import_never_collapses_a_back_to_back_split_across_game_dates`)
pins the fix.

---

## Resolution: team, game and player are best-effort, never guessed

* **Team** resolves ``team_raw`` (e.g. `"Sacramento Kings"`), the report's
  own free-text `Team` column, directly against `nba_teams.name` — the same
  "City Nickname" string `import_teams` populates from the stats API's own
  `full_name`. That match is then cross-verified against the row's own
  `Matchup` tricode pair (`"SAC@MIL"`): the resolved team's abbreviation must
  be one of the two, or the row is left unresolved. Earlier drafts inferred
  which tricode was "this" row's team from order of appearance within the
  matchup block (away always listed first in a full report) — a real defect
  found in independent review: a caller importing a partial subset of a
  report (e.g. only one team's rows because the other team's report had not
  been filed yet) or a re-ordered sequence sees appearance order disagree
  with the report's actual away-then-home structure, resolving a team to its
  opponent. Name+tricode verification needs no other row for context and
  cannot be fooled by import order or a partial batch.
* **Game** resolves from the two tricodes plus `game_date` against
  already-ingested `nba_games` rows. `NULL` if the game has not been
  ingested yet.
* **Player** resolves via `hoops_gm.identity.names.normalize_name` against
  `players.normalized_name`, disambiguated by current team when more than one
  player shares a normalized name. An ambiguity that cannot be narrowed to
  exactly one candidate is left `NULL` — never guessed (R7).

All three are nullable foreign keys on `injury_report_entries`, and every
`*_raw` text field is retained regardless of whether resolution succeeded, so
a later, better crosswalk pass can re-resolve history without re-fetching
anything.

---

## Throttling, retry and failure

| Concern | Behaviour |
|---|---|
| **Throttle** | One request every 2 seconds — the same politeness Fantrax gets, for the same reason: an undocumented CDN path deserves no less care than an undocumented API, even though nothing here needs to be fast. |
| **Retry** | 3 attempts, exponential backoff, only on `SourceUnavailable` (timeout, connection error, 5xx). |
| **Cache** | A captured report is immutable — the URL itself names the exact timestamp — so a capture is reused forever, the same reasoning as a completed game's box score. |
| **Not published (403 or 404)** | `ReportNotAvailable`, never retried. The ordinary case for most timestamps, not upstream drift. |
| **200 with a non-PDF body** | `SourceContractError` immediately, before spending time inside `pdfplumber` on a body that was never a PDF — an HTML error page served under HTTP 200, for instance. |
| **Column layout changed** | `SourceContractError` naming the unexpected header sequence. |
| **Unrecognised status value** | `SourceContractError`. |
| **Masthead does not match the requested timestamp** | `SourceContractError`, beyond the legacy format's 45-minute tolerance. |

---

## Live smoke coverage: two archived eras plus one dynamic, schedule-grounded probe

`test_live_smoke.py::TestInjuryReportIsAlive` pins two **permanently
archived** timestamps — one legacy-hourly (2025-12-01), one 15-minute-era
(2026-01-15) — each fetched against a fixed, already-published PDF. Archived
URLs survive a filename-format rotation by construction: the CDN keeps
serving the exact bytes it always served for that historical path. Neither
probe can therefore ever detect the NBA introducing a **third** filename
convention or column layout for 2026-27 — they can only ever re-prove what
already worked on 2026-08-17.

`TestInjuryReportCurrentSeasonIsAlive` (added after independent review
flagged this gap) closes it with a probe built from *now*, at test-run time,
so it has an actual chance of being served by whatever the source looks like
today rather than what it looked like when these tests were written.
`select_recent_report_candidate` (`test_injury_report.py`, unit-tested
offline) is the guard that makes this safe to run unattended — redesigned
twice after two rounds of focused review found real defects:

1. **Never a future timestamp.** An earlier version clamped "yesterday"
   forward to a fixed season-start date on opening day itself, which could
   select *today* at 17:30 ET even while "now" was still that morning — a
   future timestamp, guaranteeing a false-red 404 against a report that had
   not been published yet. Fixed: a candidate date's own 17:30 ET evening
   must be strictly before "now", never equal to or after it.
2. **Never an assumed game day.** The same earlier version treated every
   "yesterday" as a game day, which silently mistook a routine no-game date
   (the All-Star break, a scattered rest day) for source drift — a 403/404
   on a genuine no-game date is the *correct* response, not a bug. Fixed: a
   candidate is only ever built from a date this project has independently
   confirmed had a real game — never a calendar guess.
3. **Never a coarse, sparse anchor set.** The first game-backed version
   grounded candidates in `nba_scheduleleaguev2_2026_27.json`'s three
   deliberately-sparse kept dates (chosen for schedule-density/timezone test
   coverage, not for this purpose), leaving a roughly 100-day gap between the
   December and March anchors during which the probe would either go blind
   for weeks or reuse a 45-day-stale candidate that no longer meaningfully
   proved anything current. Fixed by deriving
   `nba_scheduleleaguev2_2026_27_gamedates.json` — a compact, **dates-only**
   calendar (no game objects, team/player identities, or box scores) built
   from the real, live `ScheduleLeagueV2` response for the full season: all
   173 recorded `gameDates`, with the 13 preseason-only dates excluded (the
   injury-report adapter is out of scope before the season's first game,
   R40) — leaving 160 real regular-season dates, October 20 through April
   11, whose largest gap is 7 days (the All-Star break). `FRESHNESS_WINDOW`
   tightened from 45 days to **10**, sized directly from that measured
   7-day maximum plus a small buffer, rather than a guess.

Both guards compose into one rule: among the known game dates, only the
**most recent one that is both already-published (`< now`) and within the
10-day `FRESHNESS_WINDOW`** is eligible. If none qualify — before the season
starts, or well after the season's last recorded date — `None` comes back
and the live test explicitly `pytest.skip`s with the reason spelled out,
rather than producing a noisy failure or silently treating an expected
403/404 as success. When a candidate *is* returned, a 403/404 or parse
failure on it is a **real, unswallowed failure**: the whole point of the
guards above is that the candidate is always a timestamp a report is
actually expected to exist for. Exactly one candidate, therefore at most
one HTTP request, per run.

**What the dynamic probe can detect:** the CDN URL pattern or PDF column
layout breaking for a current, game-backed, already-published request — the
one drift shape the two archived probes structurally cannot see — at any
point across the real regular season, not just three sparse dates.

**What it cannot detect:** which specific format era is in effect, or
anything about a fixed historical instant (that is what the archived probes
are for, and this is not a substitute for either); nor, beyond what the
known-game-dates + freshness guard already rules out, can it distinguish
every possible "the source broke" from every possible "there happened to be
no game that day" — it only ever probes a date this project has actually
recorded as a real game day, so it says nothing about any other date. It
also cannot detect anything for a 2027-28 (or later) season without the
dates-only fixture being refreshed for that season's calendar.

---

## Historical backfill: populating a real cohort without a documented publication schedule

Code: `backend/src/hoops_gm/ingest/injury_report/backfill.py` (tests:
`backend/tests/test_injury_report_backfill.py`).

Only one PDF is committed as a fixture (2025-11-01 05:30 PM ET) — a contract
test needs exactly one real capture, not a corpus. That single snapshot
cannot make `injury-status-conversion` (`docs/backlog.md`) evidence-ready: a
model card claiming a calibrated conversion rate needs many report-to-outcome
pairs across many dates, not one. `backfill.py` is the bounded, resumable
*data-engineering* tool — reused fetch/parse/import, no new schema — that
populates that historical cohort against the real, already-completed 2025-26
season.

### The document has no published schedule, so candidates are guesses, checked live

This is the one place this adapter cannot lean on a documented contract: the
report is not exposed by an API with a request calendar, it is a document
published irregularly through the day. This tool cannot ask "what times was a
report published on this date" — it can only propose plausible instants and
let `ReportNotAvailable` (403/404) say when a guess missed, exactly as the
live-smoke dynamic probe already does for one date at a time.

The strategy is **era-conditional**, because the two URL eras behave
differently at the level that matters — whether a wrong-minute guess can
still be recovered:

* **`evening_before`, 17:30 ET the day prior — tried in both eras.**
  Pre-December-2025 NBA policy required a report by 5:00 PM local the day
  before a game. Both of this project's own independently-pinned archived
  timestamps — 2025-11-01 17:30 ET and 2026-01-15 17:30 ET
  (`test_live_smoke.py`) — land inside this window, which is exactly why they
  were reachable at all.
* **Legacy era (before 2025-12-22): `game_day`, a fixed 13:00 ET the day of.**
  ESPN reported the NBA's memo announcing the 15-minute-cadence change
  (2025-12-20): teams must "submit injury reports on game day between 11 a.m.
  and 1 p.m. local time" before 15-minute public updates begin — 1:00 PM ET
  sits on the far edge of that window. This single fixed guess is workable
  here specifically because the legacy filename truncates to the hour and the
  masthead check tolerates 45 minutes of drift — so a same-hour miss is still
  recoverable.
* **15-minute era (2025-12-22 onward): a bounded, tip-off-anchored offset
  set, grid-aligned, not a fixed clock.** **A defect an earlier version of
  this tool had, found in independent review:** `report_url()` does *not*
  round to the source's own 15-minute marks in this era — it formats the
  requested minute verbatim (`_STRF_NEW`) — so a single fixed 13:00 ET guess
  is an exact-minute gamble with **no** tolerance at the URL level; the
  parser's 45-minute masthead check is a *post-fetch* sanity check of
  whichever file the URL actually named, and cannot rescue a URL that already
  404'd before any body was read. An earlier draft of this document wrongly
  claimed the legacy era's 45-minute recovery tolerance carried over to this
  era; it does not. Fixed: for a date in this era with a known tip-off,
  `backfill.py` requests four fixed offsets before that date's own *earliest*
  applicable tip-off — 150, 90, 45 and 15 minutes prior (`NEAR_TIP_OFFSETS`)
  — instead of one fixed wall-clock guess. **A second defect, found in a
  later independent review round:** a non-grid-aligned tip-off (e.g. 19:10 or
  19:40 ET, not on `:00`/`:15`/`:30`/`:45`) moves every offset-derived
  candidate off the source's own exact-minute grid too, so the offset alone
  is not enough — the source can never have published at, say, 18:55. Fixed:
  every near-tip candidate is floored to the prior 15-minute Eastern
  wall-clock mark (`_floor_to_quarter_hour_et`), never rounded forward past
  its own offset or past tip-off itself. Two offsets that floor to the same
  grid mark collapse to one request rather than two. Still bounded (at most
  four requests, not a sweep of the afternoon), and no-lookahead by
  construction. A 15-minute-era date with no ingested tip-off yet falls back
  to the legacy `game_day@13:00` guess rather than silently proposing
  nothing.

That memo's effective date, 2025-12-22, is **independently** the exact
filename-format-era boundary this codebase found by fetching the CDN
directly (`FIFTEEN_MINUTE_ERA_START`, `client.is_fifteen_minute_era`) — two
independent observations of the same NBA policy change corroborating each
other, rather than one stated claim taken on faith.

**The falsifiable limitation.** No anchor claims a report exists at that
instant for every date — most of the calendar has no report at all (the
ordinary case `ReportNotAvailable` already documents) — only that *if* one
exists nearby, one of the era-appropriate candidates is likely to land within
recoverable range of it. A report published as an emergency update at, say,
3:00 AM ET (an injury discovered overnight), or one published at a 15-minute
era minute none of the four bounded offsets happen to land on, is not
reachable by this scheme, and no larger anchor set fully closes that gap
either — this is a document with no documented schedule. The tool's own
`observations` CLI subcommand and the durable `CoverageReport` JSON artifact
record, per game, which of "canonical observation found" / "no candidate
covered it" / "only NOT_YET_SUBMITTED before tipoff" / "tip-off not yet
ingested" applies — so this limitation is checkable per game, not asserted as
an aggregate rate.

### No lookahead, enforced twice

A candidate only applies to a game whose `tipoff_utc` is strictly *after* it
— checked once in `build_plan` (deciding which games a fetch is even relevant
to) and again, independently, by `select_canonical_pregame_observations` at
read time against each row's own resolved `game_id`. The second check does
not trust the first plan: a game's `tipoff_utc` can be corrected later (a
postponement, a schedule fix), and re-deriving the gate from the row's own
foreign key — rather than a precomputed set from an earlier run — is what
keeps a later schedule correction from leaving a stale, wrong observation
looking canonical.

### Everything else is reused, not reinvented

Fetch/rate-limit/retry/cache is the unmodified `InjuryReportClient`. Parsing
is the unmodified `parse_injury_report_pdf`. Persistence is
`import_injury_report_entries`, whose natural key now includes `game_date`
(see above) and which already makes "canonical masthead dedupe" structural:
two different requested candidate instants that resolve to the same
underlying PDF (the legacy hourly-truncation case documented above) converge
on the same natural key rather than duplicating, and the first-seen
`source_url` is preserved on that convergence rather than being overwritten
by a later, unrelated request's URL. `select_canonical_pregame_observations`
is a pure query over already-existing columns; this remediation required two
schema changes: migration `0013`, adding `game_date` to the unique
constraint, and migration `0014`, adding `import_schema_version` (confirmed
via `alembic check`: no other new upgrade operations detected).

**Evidence is versioned, and pre-fix rows are not silently trusted.**
Migrations `0013`/`0014` fixed real data-loss and identity defects; rows
written by earlier code cannot be retroactively repaired from the surviving
columns alone (the B2B collision migration `0013` fixes lost the
overwritten row's own data before this project ever noticed). Every row now
carries `import_schema_version`: existing rows are stamped
`LEGACY_EVIDENCE_SCHEMA_VERSION` by the `0014` migration itself; every row
written by the current importer carries `CURRENT_EVIDENCE_SCHEMA_VERSION`.
`select_canonical_pregame_observations` excludes legacy-versioned rows by
default — an explicit `include_legacy=True` override is required to see them
— so a canonical-observation query never silently blends known-untrustworthy
pre-fix rows with current ones. Any local database populated before this
round needs its legacy rows re-captured (re-run the backfill for the
affected dates; the natural-key fix means a genuine re-import upgrades a
row's version in place) or its checkpoint reset so a resumed run does not
skip candidates whose only local evidence is a legacy row.

### Bounded and resumable

* `build_plan` is network-free — it only reads already-ingested `nba_games`
  rows for one explicit `(season, season_type)` and checks local cache
  freshness — so an operator sees the exact candidate and live-request count
  *before* deciding to run it (the `plan` CLI subcommand).
* `enforce_full_tipoff_coverage` refuses to run against a requested game
  scope with any missing tip-off, by default (`--allow-missing-tipoff 0`) —
  fail-closed before any network call, so a small, incidentally-reachable
  subset of a much larger requested range cannot be mistaken for a
  cohort-ready backfill of that whole range. A deliberately partial run needs
  an explicit, disclosed `--allow-missing-tipoff N` override.
* `enforce_request_budget` refuses to run a plan whose live-fetch count
  exceeds an explicit `--max-requests` cap, rather than making an unbounded
  number of requests to a CDN this project is a guest on.
* A JSON checkpoint (`data/reports/injury_backfill_<season>_<season_type>
  .json`) records each candidate's outcome as it settles, so an interrupted
  run resumes by skipping already-settled candidates rather than
  re-requesting them. **Caching never gates whether a candidate is
  processed** — a real defect found in independent review: an earlier
  version only ever iterated the *uncached* subset of the plan, so a
  candidate whose raw PDF reached disk but crashed before its checkpoint
  write was silently skipped forever on every subsequent resume. Only the
  checkpoint's own settled-outcome gate decides that now.
* **The database commit happens before the checkpoint records a candidate as
  settled, not after** — another defect found in independent review. A
  commit is a round-trip that can fail after a checkpoint write already
  happened, which would leave the checkpoint permanently, wrongly believing
  the candidate is done with nothing actually persisted. A commit failure is
  now caught, rolled back, and checkpointed as an *unsettled* `"error"` so a
  resumed run retries it.
* A per-candidate failure does not abort the run (the same pattern
  `backfill_season` uses for a per-game failure), but `ReportNotAvailable`
  (missing — the ordinary case) and any other `SourceError` (drift) are
  counted and reported **separately**: conflating "no report existed for this
  guess" with "the source's contract broke" is exactly the silent-degradation
  failure mode the house rules warn against. A 404 (or a non-403 absence) is
  checkpointed as settled immediately. **A 403 is never checkpointed as
  settled, full stop — redesigned twice by independent review.** The first
  design buffered a 403 streak and only checkpointed each one once the streak
  was confirmed not to be an abort; a later review found this still let a
  short streak that never crossed the abort threshold settle as confirmed
  absence, which is wrong for the same reason a long streak is wrong — a 403
  can be a WAF/rate-limit response at any length, and settling it (in any run,
  any process boundary) throws away the fact that it was never confirmed. The
  current design: a 403 is recorded under its own permanent, always-unsettled
  checkpoint status (`"forbidden"`), distinct from `"not_available"`
  (404-only from here on). Every 403 is retried on every future run,
  indefinitely, until it either 404s (genuinely confirmed absent) or is
  fetched. A **streak** of consecutive HTTP 403s still raises
  `SuspectedSourceBlock` and aborts the run early — but this is now purely an
  early-abort optimization to stop wasting requests against a suspected
  block, not something checkpoint correctness depends on, since nothing about
  a 403 is ever settled regardless of streak length or how many separate CLI
  invocations touch it. A 403 is documented to mean "refused" and can be a WAF
  or rate-limit response wearing a client-error status, unlike an in-season
  404's documented "nothing published here".
* **Checkpoint identity includes the exact resolved `report_timestamp`, not
  merely `(date, anchor)`** — a defect found by independent review. A
  near-tip candidate's actual instant is derived from a date's *earliest*
  ingested tip-off; if that earliest tip-off is later corrected (a
  postponement, or a newly-ingested game whose tip-off is *earlier* than
  every game already known that date), the same `(date, anchor)` pair now
  names a genuinely different URL. Keying only on `(date, anchor)` let a
  stale settled entry silently vouch for a URL it was never actually checked
  against. Embedding the resolved instant means a changed candidate simply
  misses the old key — unsettled again, correctly re-fetched — rather than
  trusted under a mismatch.
  * **This does not cover every case, though — a newly-ingested game does
    not necessarily change the resolved timestamp at all.** If the new
    game's tip-off is *later* than the date's already-known earliest, the
    earliest tip-off (and every near-tip candidate anchored to it) is
    completely unaffected: the checkpoint key is bit-for-bit identical to
    before the game was ingested. This is exactly the shape of an
    `--allow-missing-tipoff` partial day — round-10 review point 3. Without
    a further fix, resume would see the identical key, believe the
    candidate already settled, and skip it forever — permanently stuck at
    `no_candidate_coverage` for the newly-ingested game even though the
    exact URL this candidate names was already fetched (or already
    confirmed `not_available`) and genuinely does apply to it now.
    `Checkpoint.record`/`is_settled` therefore also carry each candidate's
    *applicable stable NBA game ids* as part of its settled scope, alongside
    the resolved-timestamp key: a game id present in the current plan but
    absent from what was recorded when this candidate last settled makes it
    unsettled again — regardless of whether the timestamp key changed — and
    `run_backfill` reprocesses it. Reprocessing is idempotent either way (the
    raw payload is already cached, re-import is idempotent by natural key, a
    `not_available` candidate simply stays `not_available`), so this only
    ever *expands* correctly-attributed coverage, never duplicates anything.
* **An independent expected-game-slate gate runs before any injury-report
  HTTP call**, in addition to (not instead of) `enforce_full_tipoff_coverage`
  above — a defect found by independent review: that tip-off gate can only
  ever compare games already present in this project's own `nba_games` table,
  so it is structurally blind to a game the project never ingested at all. A
  small, incidentally-ingested subset of a much larger requested range (e.g.
  22 games out of a 527-game season) could otherwise pass "by construction".
  `enforce_expected_game_coverage` compares the requested range against the
  official schedule — one cached, throttled `LeagueGameFinder` call via the
  same `NbaStatsClient`/`parse_league_game_finder` `hoops_gm.ingest.backfill`
  already uses to ingest a season's games — and fails closed
  (`IncompleteExpectedGameCoverage`) unless every expected game is at least
  ingested, persisting the durable evidence of what was expected and what was
  missing (`ExpectedGameCoverage` JSON) even on this failure path. An
  explicit, disclosed `--allow-missing-games N` override exists for a
  deliberately partial run, the same escape-hatch pattern as
  `--allow-missing-tipoff`.
* A game whose `tipoff_utc` has not been ingested yet is reported loudly in
  the plan (never silently skipped or guessed) — schedule ingest is this
  tool's precondition, not something it duplicates — and, by default, blocks
  the run entirely via `enforce_full_tipoff_coverage` above.
* Durable, structured coverage evidence — not just console counts — is
  written per run as a `CoverageReport` JSON file
  (`data/reports/injury_backfill_<season>_<season_type>_coverage.json`):
  per candidate, its era, lead time relative to tip-off, HTTP outcome,
  canonical masthead instant (when fetched), a split of listed vs.
  `NOT_YET_SUBMITTED` entries, and — a defect found by independent review —
  the coverage merge key now includes the requested `report_timestamp`
  itself (not just date and anchor), matching the checkpoint-identity fix
  above, and coverage is now written even on an aborted run
  (`SuspectedSourceBlock.partial_result.coverage`) rather than only on a
  clean finish, so a 403-abort followed by resume never loses the candidates
  already attempted before the abort. The `observations` CLI subcommand
  (network-free, reads only the database) reports the per-game rollup —
  observed, no-candidate-coverage, unsubmitted-only, or missing-tip-off — as
  a reproducible operator command, replacing an ad hoc, uncommitted script as
  the way to answer "what did this backfill actually cover". **A full
  exclusion cascade** — expected games, ingested-with-tipoff games, candidates
  attempted, mastheads recovered, entries resolved to a game, entries
  resolved to a player, and team-submitted/status-listed entries —
  is computed by `exclusion_cascade`/`render_exclusion_cascade` so the actual
  model denominator at each stage (and where it narrows) is queryable and
  renderable, not merely a single game-level "observed" count that one
  player's row could satisfy while every teammate's row is missing.
* **Round-5 review found the denominator machinery itself dishonest in five
  ways** — not the coverage gap it measures, but the measurement. Each is
  fixed and regression-tested:
  * The unresolved-game-id cascade stage was **tautological**: the underlying
    query filtered `game_id.in_(...)` before counting how many entries
    resolved to a game_id, so the stage could never show loss by
    construction. `exclusion_cascade` now scopes raw entries by
    `game_date.in_(...)` (always populated) first, then counts resolution
    separately, and persists a bounded sample of unresolved
    `(game_date, matchup, team, player_name_raw)` rows.
  * `no_candidate_coverage` (a `GameObservationCoverage` outcome) conflated
    "no candidate was ever attempted for this game" with "a candidate was
    fetched and the team submitted zero injured players" — two structurally
    different absences with different implications for a downstream model.
    `coverage_for_games` now distinguishes `no_candidate_coverage`,
    `not_yet_submitted_only`, `submitted_zero_listed`, and `legacy_excluded`
    as separate outcomes, and `observations` renders all four.
  * Legacy (pre-`0013`/`0014` natural-key fix) rows were inconsistently
    excluded across cascade stages. `exclusion_cascade` now splits raw
    entries into `trusted`/`legacy` by `import_schema_version` **before**
    computing any resolution-dependent stage, and every one of stages 11–18
    is computed from `trusted` only; a `NOT_YET_SUBMITTED`-only legacy row is
    never reported as `not_yet_submitted_only` — it is `legacy_excluded`,
    because it is equally subject to the collapse the schema fix corrected.
  * `ExpectedGameCoverage` and `CoverageReport` were not bound to the exact
    requested season/season_type/date range. `observations` now requires an
    exact match (season, season_type, start, end) between persisted evidence
    and the current invocation via `_expected_coverage_matches_scope`,
    refusing to silently answer a March request with a persisted November
    file's evidence.
  * `lead_minutes` on a `ReportCandidate`/`CandidateCoverage` was the
    **anchor's intended offset** from a date's earliest tip-off (shared
    across every game on that date), not a realized per-game lead time — it
    is renamed `anchor_offset_minutes`. A new, genuinely per-game
    `CanonicalPregameObservation.lead_time_minutes` is computed as
    `tipoff_utc - report_timestamp` for that specific game and exposed in
    `observations`/the exclusion cascade for downstream stratification by
    realized lead time, not anchor offset.
* The expected-game-slate gate (`enforce_expected_game_coverage`) now **fails
  closed on an empty in-range response** from the official schedule source
  (previously an empty payload passed vacuously) and the CLI **restricts
  season type to `REGULAR`/`PLAYOFFS`** — `PRESEASON`/`PLAY_IN` are rejected
  before any HTTP call rather than silently mapped onto `PLAYOFFS`, which
  would have compared the wrong slate.
* The canonical player-game surface (`select_canonical_pregame_observations`)
  now collapses by resolved `player_id` where available, so spelling variants
  of the same player's name across mastheads do not double-count as distinct
  observations; a player who never resolved to an id is kept as a distinct,
  separately-counted unresolved identity rather than silently merged with a
  resolved row.
* **Round-6 review found three more honesty defects, all in the coverage
  machinery, not the source's actual coverage gap** — fixed and
  regression-tested:
  * **Checkpoint settlement and coverage evidence were not atomic.**
    `run_backfill` used to accumulate every candidate's `CandidateCoverage`
    in memory and write the whole run's coverage file once at the end, but
    checkpointed each candidate as settled immediately as it was processed.
    A crash between those two points (settlement durable, coverage evidence
    not yet flushed) left a permanently-settled candidate with no coverage
    record and no way to regenerate one, since resume skips settled
    candidates by design. `run_backfill` now accepts a `persist_coverage`
    callback and calls it — writing that single candidate's
    `CandidateCoverage` to the durable, merge-idempotent coverage file —
    strictly *before* `checkpoint.record(...)` in every outcome branch
    (forbidden, not-available, error/commit-failure, fetched). A crash
    between the two calls now either leaves both durable, or leaves coverage
    durable with the checkpoint still unsettled (safe: reprocessed on
    resume, and idempotent both for import via its natural key and for
    coverage via `_coverage_merge_key`) — never the reverse.
  * **An unresolved report entry could let a game falsely read as a clean
    zero-injury submission.** `coverage_for_games`'s entry query filtered by
    `InjuryReportEntry.game_id.in_(...)`, so a listed (non-`NOT_YET_SUBMITTED`)
    row whose `game_id` never resolved was invisible to it — reproduced
    exactly: a report with one unresolved `OUT` entry classified its game as
    `submitted_zero_listed`. The query now scopes by `game_date.in_(...)`
    (always populated) first, and a supplementary lookup conservatively
    re-attributes an unresolved row to a single unambiguous `ready` game on
    its date via the report's own `Matchup` tricodes. When no single game can
    be identified, the row is never silently dropped: it vetoes
    `submitted_zero_listed` for every game sharing that date via a new
    `unresolved_evidence` outcome, distinct from and taking priority over
    `not_yet_submitted_only`/`submitted_zero_listed`, so an unattributable
    listed row can only ever make a game's outcome *more* honest, never
    silently disappear.
  * **A tip-off correction could leave stale, now-post-tip coverage still
    vouching for a clean submission.** `coverage_for_games` trusted a fetched
    candidate's persisted `applicable_game_ids` unconditionally; if a game's
    `tipoff_utc` was corrected *after* that candidate's canonical masthead
    instant was recorded, the same evidence that was legitimately pre-tip
    when fetched can retroactively become post-tip, and only strictly
    pre-tip evidence may support a clean-submission claim. Each candidate's
    `canonical_report_timestamp` is now revalidated against the game's
    *current* `tipoff_utc` (re-read fresh from the database on every call,
    not from a stale precomputed set) before it is allowed to contribute to
    `submitted_zero_listed`; a stale candidate simply stops counting for that
    game (falling to `no_candidate_coverage` if nothing else applies) without
    vetoing a separate, still-valid candidate for the same game.
* **Round-7 review found three more evidence-identity defects in the same
  coverage machinery** — fixed and regression-tested:
  * **The round-6 tip-off revalidation still trusted the caller's own
    `BackfillGame.tipoff_utc` snapshot, not the database's current value.**
    `ready` is ordinarily built by an earlier `games_to_backfill` call and
    can go stale before `coverage_for_games` actually runs — a schedule
    correction landing in that window (in this process or an earlier one)
    could still let post-tip evidence prove a clean submission, because the
    comparison was against the caller's stale number, not today's. Every
    game's identity and `tipoff_utc` are now re-queried fresh from the
    database inside `coverage_for_games`'s own read scope, and only that
    freshly-read value is ever compared against a masthead timestamp; a
    game whose live row disappeared or lost its tip-off since the caller's
    snapshot was built now reports `missing_tipoff` instead of trusting a
    value that no longer reflects the database.
  * **The round-6 unresolved-row veto was date-wide, not per-game, and its
    precedence could be masked by `legacy_excluded`.** An unattributable
    current-schema row used to veto every game on its date, including ones
    it demonstrably could not concern (a report published after a game
    already tipped off cannot be pregame evidence for it); it also excluded
    `NOT_YET_SUBMITTED` rows from the veto even though such a row still
    proves genuine uncertainty about whichever game it actually concerns;
    and a game with both a legacy row and separate current-schema
    unresolved evidence could report the coarser `legacy_excluded` instead
    of the more specific `unresolved_evidence`. The veto is now per-game and
    strictly pre-tip — it applies only to same-date games whose *current*
    tip-off is strictly after the row's own report timestamp — covers
    `NOT_YET_SUBMITTED` rows like any other current-schema row, and
    `unresolved_evidence` now outranks `legacy_excluded` in the final
    outcome precedence.
  * **Persisted coverage relied on reusable surrogate `NbaGame.id` values
    as evidence identity.** `CandidateCoverage.applicable_game_ids` named
    games by their surrogate database primary key, which a rebuild or
    reingestion can reassign to an unrelated game — stale coverage could
    then prove `submitted_zero_listed` for whatever game now holds that
    recycled id. `CandidateCoverage` gained a required
    `applicable_nba_game_ids` field (the NBA's own stable game identifier)
    and a defaulted `evidence_schema_version`; `coverage_for_games` now
    matches fetched-candidate evidence by stable NBA game id only, and
    `CoverageReport.from_json` stamps any record missing these fields as
    `LEGACY_COVERAGE_SCHEMA_VERSION` on load so it is excluded entirely
    from `submitted_zero_listed` classification rather than trusted
    against whichever game holds its surrogate id today.
* **Round-9 review found two more HIGH defects and two more MEDIUM
  release-blocking defects in the same coverage machinery** — fixed and
  regression-tested:
  * **Round-8's "re-query fresh" tip-off fix could still return a stale
    value from the session's own ORM identity map.** A plain re-query
    still executes SQL against the database, but by default SQLAlchemy
    leaves an already-identity-mapped instance's attributes untouched
    rather than overwriting them with the fresh row — and this project's
    session factory has `expire_on_commit=False`, so even the session's
    own commit does not clear that staleness. All three `NbaGame` queries
    in `coverage_for_games`/`select_canonical_pregame_observations` that
    matter for freshness now use `.execution_options(populate_existing=True)`,
    forcing a real repopulation from each query's own result row.
  * **Persisted coverage validated only stable NBA game id + timestamp,
    not full schedule-scope binding or an exact schema version.** An
    *unrecognized future* schema version still passed (the check was
    `<`, not `!=`); nothing checked that a candidate's `report_date`
    still matched the game's *current* `game_date` (letting a reschedule
    keeping the same stable id inherit stale evidence for a different
    date); and nothing checked that the `CoverageReport`'s own
    `season`/`season_type` matched the game's current schedule scope.
    The schema-version check is now exact equality, and two new binding
    checks (game-date match, season/season_type match via a
    `game_scope_by_id` map) gate every `submitted_zero_listed` claim.
  * **A retracted-tip-off game was emitted twice** — once inline in the
    `ready` results loop and again via the separate `newly_missing` loop.
    The inline emission was removed; the game is now captured exactly
    once.
  * **Resolved-but-out-of-scope evidence fanned out onto unrelated
    same-date games.** A row with a non-null `game_id` that no longer
    resolved to a currently-live game (e.g. its own game's tip-off was
    retracted) was treated like a genuinely unattributable row
    (`game_id is None`) and vetoed every later same-date game it
    pre-dated. The conservative date-wide fan-out veto now applies only
    when `row.game_id is None`; a resolved-but-out-of-scope row stays
    bound to its own (now-missing) game and never contaminates others.
* **Round-10 review found one more HIGH, one more MEDIUM-but-release-blocking,
  and one settlement-identity defect in the same coverage/checkpoint
  machinery** — fixed and regression-tested:
  * **Classification still mixed state across separate statements.**
    `coverage_for_games` issued an initial `NbaGame` query building
    `games_by_id`, then `select_canonical_pregame_observations` issued its
    *own*, separately-timed `NbaGame` query solely to look up tip-offs for
    lead-time computation. A schedule correction landing between the two
    could let one game's trust-classification see an old tip-off while
    another game's observation lead-time, computed moments later in the
    same call, already saw a new one — internally inconsistent within a
    single `coverage_for_games` invocation, and (per round-9's ORM-identity
    finding) not fixed merely by re-querying, since a second statement is a
    second opportunity for the world to have moved. All classification-
    relevant fields — stable id, local id, date, tip-off, season,
    season_type, and both teams' abbreviations for tricode matching — are
    now read in **exactly one** `SELECT` at the top of `coverage_for_games`;
    `select_canonical_pregame_observations` accepts that same query's
    tip-off map instead of issuing its own. Selecting individual columns
    (not full `NbaGame` entities) also means there is no ORM identity map
    for a stale instance to hide in at all — `populate_existing` becomes
    moot, not merely applied. A genuine regression proves this with a real
    second connection: a `before_cursor_execute` hook — fired by the engine
    itself as the classification statement is about to run, not by test
    code sequenced before the call — commits a tip-off correction for one
    game and retracts another's entirely, and the single resulting query
    is shown to read exactly one consistent post-commit instant of both
    facts together.
  * **Persisted coverage validated identity and per-game schedule scope, but
    not the *file's own* declared scope, nor each candidate's own recorded
    scope.** `_persist_coverage` could merge a candidate carrying a
    different `season`/`season_type` than the file (or than the caller's
    request) into a rewritten file trusted under the caller's label — the
    coverage schema version is bumped to 3, `CandidateCoverage` now
    self-describes its own `season`/`season_type`, and `_persist_coverage`
    raises `CoverageScopeMismatch` on a whole-file scope disagreement and
    silently excludes (never trusts) any individual candidate whose own
    recorded scope disagrees, even inside an otherwise-matching file.
    `coverage_for_games` applies the same self-described-scope check as a
    defense-in-depth measure on top of the existing DB-derived
    `game_scope_by_id` check.
  * **Checkpoint settlement identity ignored applicable-game scope
    entirely** — see the corrected `--allow-missing-tipoff` discussion
    above. `Checkpoint.is_settled`/`record` now carry each candidate's
    settled `applicable_nba_game_ids` and treat a current request naming a
    game id absent from what was recorded as unsettled, regardless of
    whether the resolved-timestamp key itself changed.


### What this tool is not

It never fits or reports a status-to-outcome rate.
`select_canonical_pregame_observations` picks one row per `(game, team,
player)` — the latest pregame observation — and nothing more; the empirical
conversion of that status to an actual play rate is `injury-status-
conversion`, a separate `quant`, Model-gated deliverable that consumes this
tool's output and its coverage evidence. The `observations` command's own
per-game outcome counts are tool-validation and coverage evidence, not a
reported conversion or hit rate.

---

## What this table deliberately is not

`injury_report_entries` is the ingested-fact analogue of `team_schedule`, not
of `opponent_context` (ADR-009): it carries no `model_version` or
`schedule_version`, because it asserts nothing beyond what the league
published. The empirical conversion of a status to an actual play rate
(`injury-status-conversion`, `docs/backlog.md`) is a modelled quantity that
belongs to `quant` in a later phase and consumes this table — it does not
live in it.
