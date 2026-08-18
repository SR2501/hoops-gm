# 2025-26 Philly Stud Rules Baseline

**Status:** Historical reference only. Not verified for 2026-27.

**Source:** Owner-provided Fantrax League Rules Summary and written league rules,
received 2026-08-17. The current season's settings must be ingested or captured
from Fantrax before any decision depends on them.

## Stable-looking baseline

| Concern | 2025-26 evidence |
|---|---|
| Format | H2H each category, 9-cat: AST, BLK, PTS, REB, STL, 3PTM, TO, FG%, FT% |
| League size | 10 teams |
| Roster | 14 total players; up to 4 G, 4 F, 2 C active; 3 IR |
| Lineups | Manager-set daily; locks one minute before player tipoff |
| Waivers | Daily automated priority order, processes 1:00am CDT; all free agents enter waivers at first game each day |
| Auction rules | $200 per team, $1 minimum; random nomination order; 45s nomination, 20s initial bid, 15s reset |
| Draft timing | Sunday before NBA season |
| Playoffs | Three periods; final two NBA weeks excluded; All-Star weeks combined |
| Trades | Manager vote; 24-hour minimum voting period in written rules |

## Conflicts and unverified details

- **Weekly pickups conflict:** Fantrax export says four claims per week; written
  rules say three pickups. Do not model a cap until current settings resolve it.
- **Draft format changed as expected:** the historical export is a snake draft,
  but 2026-27 auction is separately confirmed.
- **Team-count-dependent rules:** written rules contain both 10- and 12-team
  playoff/schedule branches. The historical export is 10 teams; current
  membership still needs confirmation.
- Historical trade deadline, scoring-period dates, and draft date are not
  reusable for 2026-27.

## Implementation use

This document is a requirements hint for `league-settings-ingest`, not a data
source. The live Fantrax adapter or browser capture must record every setting
used by timing, lineup, draft, and valuation code with its source and timestamp.
