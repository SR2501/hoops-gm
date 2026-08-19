# Basketball Monster projection CSV

## Boundary

Basketball Monster is a paid, manually downloaded CSV source. The adapter never
logs in, calls a network endpoint, discovers a local file, or reads a default
path. Production import receives explicit bytes; the live smoke reads a path
only when `HOOPS_GM_BBM_PROJECTION_CSV` is explicitly set.

The 2026-27 contract was verified on 2026-08-19 against a private export with
SHA-256
`FA13AD188E8ACADD410DFEAE7FF296A25078842E22CE17046CF19DFBCA9D3ABD`.
A private semantic screenshot with SHA-256
`3BA42FD80072E8C35C191C38BA19EB0C8A8BE4182D484FEFD73A31D1ED36C29B`
independently reconciled 13 of 13 visible quantities at Basketball Monster's
display rounding. Neither private artifact, its path, nor any paid row is
committed or logged.

## Proven contract

The exact headers and order are pinned by
`BASKETBALL_MONSTER_2026_27_HEADERS`. The CSV is UTF-8, comma-delimited,
double-quote-capable, has no leading BOM, and the observed export uses CRLF
records. A privacy-safe fixture preserves the exact headers, order and dialect
with synthetic identifiers, names and values.

The source values are season totals even though the visible page labels the
presentation "Per Game Stats." `games` is persisted only as the source
games-played assumption. Every production total is divided by that value:

- `field_goals`, `field_goals_attempted`, `free_throws`,
  `free_throws_attempted`, `threes`, and `threes_attempted` retain shooting
  volume as makes/attempts.
- `points_per_game = 2 * field_goals_per_game + threes_per_game +
  free_throws_per_game`.
- `rebounds_per_game = offensive_rebounds_per_game +
  defensive_rebounds_per_game`.

`player_id` is the stable Basketball Monster crosswalk key. The canonical
player remains NBA-anchored, and ambiguous name resolution still goes to
review. The export has no team or position field, so the adapter never invents
either. `technicals`, `double_doubles`, `triple_doubles`, and `comments` are
explicitly excluded from projection quantities and recorded as ignored source
headers in transformation lineage.

## Drift and failure behavior

Header spelling, header order, a missing required row value, an invalid finite
number, zero/missing games for a season-total conversion, duplicate source ids,
or impossible makes/attempts rejects the affected row or the whole contract
without a projection write. The parser never falls back to guessed aliases.
The verified private export contains a small tail of zero/missing-games rows;
those rows are expected to be rejected because their season totals cannot be
converted honestly, while rows with positive games remain usable.
Profile version `1` is verified only for season `2026-27`; another season needs
new private evidence and a new immutable profile version.

There is no remote request to throttle or retry. A local file read is attempted
once and failure is surfaced. The live smoke is deliberately opt-in:

```powershell
$env:HOOPS_GM_BBM_PROJECTION_CSV = '<explicit-private-csv>'
pytest -m live_smoke -k BasketballMonsterProjectionExport
```

When the variable is absent, the probe skips. When present, errors are
re-raised with generic contract messages so private paths and paid row values do
not enter test logs.
