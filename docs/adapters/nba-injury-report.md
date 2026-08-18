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
(`report_timestamp, team_raw, player_name_raw`), persisting the *request*
instant on each import would let each of those different requests create its
own row for what is really one report capture — manufacturing false status
history for `injury-status-conversion` to (wrongly) learn from. Fixed:
`parse_injury_report_pdf` returns (and stamps every entry with) the
masthead's own parsed instant, converted to UTC, never the caller's
`report_timestamp` argument — that argument is now only ever a request hint
used for the tolerance check above.

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
once already after a second focused review found two real defects in a
first, calendar-only version:

1. **Never a future timestamp.** An earlier version clamped "yesterday"
   forward to a fixed season-start date on opening day itself, which could
   select *today* at 17:30 ET even while "now" was still that morning — a
   future timestamp, guaranteeing a false-red 404 against a report that had
   not been published yet. Fixed: a candidate date's own 17:30 ET evening
   must be strictly before "now", never equal to or after it.
2. **Never an assumed game day.** The same earlier version treated every
   "yesterday" as a game day, which silently mistook a routine no-game date
   (the All-Star break, a scattered rest day, a gap beyond the recorded
   regular-season schedule) for source drift — a 403/404 on a genuine
   no-game date is the *correct* response, not a bug. Fixed: a candidate is
   only ever built from a date `known_game_dates_from_schedule_fixture`
   reads directly from the real, committed `nba_scheduleleaguev2_2026_27.json`
   capture (the actual `leagueSchedule.gameDates[].gameDate` values,
   currently `2026-10-20`, `2026-12-04`, `2027-03-14`) — never a calendar
   guess. A date this project has not independently confirmed as a game day
   is never used.

Both guards compose into one rule: among the known game dates, only the
**most recent one that is both already-published (`< now`) and within a
45-day `FRESHNESS_WINDOW`** is eligible. If none qualify — before the
season starts, in a gap between recorded anchors wider than 45 days, or on
a known game date before its own evening has arrived — `None` comes back
and the live test explicitly `pytest.skip`s with the reason spelled out,
rather than producing a noisy failure or silently treating an expected
403/404 as success. When a candidate *is* returned, a 403/404 or parse
failure on it is a **real, unswallowed failure**: the whole point of the
guards above is that the candidate is always a timestamp a report is
actually expected to exist for. Exactly one candidate, therefore at most
one HTTP request, per run.

**What the dynamic probe can detect:** the CDN URL pattern or PDF column
layout breaking for a current, game-backed, already-published request — the
one drift shape the two archived probes structurally cannot see.

**What it cannot detect:** which specific format era is in effect, or
anything about a fixed historical instant (that is what the archived probes
are for, and this is not a substitute for either); nor, beyond what the
known-game-dates + freshness guard already rules out, can it distinguish
every possible "the source broke" from every possible "there happened to be
no game that day" — it only ever probes a date this project has actually
recorded as a real game day, so it says nothing about any other date. The
freshness window also means the probe goes quiet (skips) for stretches
between the sparse anchors the trimmed fixture happens to record — a real
limitation, documented rather than hidden, that would shrink if the fixture
recorded more game dates.

---

## What this table deliberately is not

`injury_report_entries` is the ingested-fact analogue of `team_schedule`, not
of `opponent_context` (ADR-009): it carries no `model_version` or
`schedule_version`, because it asserts nothing beyond what the league
published. The empirical conversion of a status to an actual play rate
(`injury-status-conversion`, `docs/backlog.md`) is a modelled quantity that
belongs to `quant` in a later phase and consumes this table — it does not
live in it.
