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

---

## Resolution: team, game and player are best-effort, never guessed

* **Team** resolves from the `Matchup` tricode (`"SAC@MIL"`), not the
  free-text `Team` column, because the tricode is an exact match against
  `nba_teams.abbreviation`. Which tricode belongs to *this* row is derived
  from team order of appearance within the matchup block — the away team's
  roster is always listed first, verified against the real capture.
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

## What this table deliberately is not

`injury_report_entries` is the ingested-fact analogue of `team_schedule`, not
of `opponent_context` (ADR-009): it carries no `model_version` or
`schedule_version`, because it asserts nothing beyond what the league
published. The empirical conversion of a status to an actual play rate
(`injury-status-conversion`, `docs/backlog.md`) is a modelled quantity that
belongs to `quant` in a later phase and consumes this table — it does not
live in it.
