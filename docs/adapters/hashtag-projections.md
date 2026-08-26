# Hashtag Basketball — season projections

**Source:** `https://hashtagbasketball.com/fantasy-basketball-projections`
**Profile:** `hashtag-2026-27` (version `2`), `backend/src/hoops_gm/ingest/projections/profiles.py`
**Fixture:** `backend/tests/fixtures/projections/hashtag_sample.csv` (+ `.metadata.json`)
**Contract tests:** `backend/tests/test_projection_importer.py::TestHashtagProjectionContract`
**Verification checks:** `backend/src/hoops_gm/ingest/projections/verification.py`
**Evidence date:** 2026-08-26

---

## Read this first: what "verified" means here, and what it does not

The Basketball Monster profile is verified against **the SHA-256 of a real paid
export**. This one is not, and cannot be. Hashtag publishes no export: the
projections page is rendered HTML, and the owner's input is a copy-paste of a
table into a spreadsheet. There is no immutable artifact to hash.

So `verified=True` on this profile means something **strictly weaker** than
`verified=True` on Basketball Monster's:

| | Basketball Monster | Hashtag |
|---|---|---|
| Evidence | hash of a paid export file | live-page contract observation |
| Reproducible from the repo | yes, by hashing the file again | no |
| Detects vendor drift | yes, immediately | only via the opt-in live smoke test |
| Fixture hash | pins a derivative of proven bytes | pins only our own synthetic file |

Both metadata files carry a `privacy_safe_fixture_sha256`, which makes them look
equivalent at a glance. They are not, and
`test_fixture_is_synthetic_and_declares_its_weaker_evidence` asserts the
difference so a reader cannot infer parity from a shared key name.

**A field that means two different strengths under one name is the defect this
project keeps finding.** It is recorded here rather than smoothed over.

---

## What the source actually publishes

### There is no CSV export

Searched the rendered page (345 KB) for `csv`, `export`, `download` and
`per game`: **zero occurrences each**. Positive-controlled before that zero was
trusted — the same extractor returned `TREB` × 5, `Jokic` × 2, `ADP` × 7 on the
same document, so the zeros are the source's, not the extractor's.

### The header sequence

```
R#, PLAYER, ADP, POS, TEAM, GP, MPG, FG%, FT%, 3PM, PTS, TREB, AST, STL, BLK, TO, TOTAL
```

Pinned exactly as `HASHTAG_2026_27_HEADERS` and matched on **names and order**.
A paste that does not match is refused outright rather than best-effort mapped.

### The column set is browser state, not a vendor contract

The page carries **sixteen category checkboxes**. Nine are ticked by default
(`CBFGP CBFTP CB3PM CBPTS CBREB CBAST CBSTL CBBLK CBTO`); `CBFGM`, `CBFTM`,
`CBOREB`, `CBDREB`, `CB3PP`, `CBATO` and `CBDD` exist and are unticked.

A paste therefore carries **values and none of the configuration that produced
them**. The default selection looks like a stable contract and is not one. This
is why the header match is exact and fail-closed: a paste made with a different
selection must be a loud refusal, not a partial import.

### `FG%` and `FT%` are composite cells — this is the finding

```
0.573 (10.5/18.3)
```

Hashtag publishes **makes and attempts inside the percentage cell**.

Version 1 of this profile declared both shooting columns as
`percentage_fallback_aliases`, whose documented meaning is *"the source
published no volume"*. That was **true of the header and false of the cell**.

The consequence was the silent one: a fixed import would have succeeded, warned
about percentages, and **discarded every shooting volume in the file**. That is
`AGENTS.md`'s *"single most common bug in homebrew fantasy tools"* — a 90%-on-
one-attempt free-throw shooter pricing identically to a 90%-on-eight — reached
not by writing the bug but by inheriting a profile that described a header
correctly and a cell wrongly.

`CompositeShootingColumn` now decomposes the cell into canonical makes and
attempts, and the profile **refuses** to declare the same field as both a
composite column and a percentage-only fallback, because that would assert the
source did and did not publish volume for the same category.

### The header repeats inside the table

Observed **32 times in 429 data rows**, roughly every 13. A paste carries them
through. Left alone they parse as a player named `PLAYER`, surfacing as a
scatter of per-row numeric errors rather than as the structural artefact they
are. Rejected explicitly, as a row-level fatal.

### `DDRANK` switches shape while the headers stay identical

The page has a `TOT` / `AVG` / `COM` control. Measured:

| | AVG mode | TOT mode |
|---|---|---|
| `MPG` (Jokic) | 35.1 | **35.1** |
| `PTS` (Jokic) | 28.4 | **2042.6** |
| Header text | identical | identical |

**TOT mode is mixed**: minutes stay per-game, counting stats become season
totals. Nothing in the exported text distinguishes the two modes.

This is the `gameEt` shape exactly — a well-formed, self-describing artefact
whose self-description is detached from its contents — and it is the same defect
that hit the Basketball Monster adapter, where the page said "Per Game Stats"
and served season totals.

---

## What is checkable, and what is not

### Checkable

| Property | Check | Where |
|---|---|---|
| Column contract | exact header sequence match | `parser.py`, fail-closed |
| Shooting volume present | composite cell decomposition | `parser.py` |
| Cell internal consistency | stated % vs. stated makes/attempts, volume-aware bound | `parser.py` |
| Percentage that outlived its volume | non-zero % on zero attempts is refused | `parser.py` |
| Per-game vs. season totals | `max(PTS) <= 60` | `verify_value_shape`, called by `import_projection_csv` |
| Volume belongs to its row | `2*FGM + 3PM + FTM == PTS` | `verify_scoring_identity`, called by `import_projection_csv` |
| Availability already baked in | cohort median vs. prior-season minutes per *played* game | `verify_no_baked_in_availability` — **never runs on the import path**, see below |

The first four run at parse time. The next two run **on the import path**:
`import_projection_csv` calls `verify_projection_batch` after parsing and raises
`ProjectionVerificationError` when a **blocking** check fails, so a season-totals
paste is refused rather than persisted.

Only `value_shape` blocks (`IMPORT_BLOCKING_CHECKS`). That is not a ranking of
importance, it is which check has a legitimate false positive. No real per-game
file trips a 60-point ceiling, so refusing on it is never wrong about a real
source. The scoring identity cross-checks columns a vendor may compute from
*separate* models and round independently — and it can only run at all where the
source publishes attempts, since makes without attempts are dropped as an
incomplete volume pair. A source publishing to zero decimals would fail it while
being entirely correct, so it is reported on
`ProjectionImportOutcome.verification` and left to the caller.

That wiring was missing on first delivery and an independent review found it. The
module was written, tested in both directions, and called by nothing — so a
`DDRANK` TOT-mode paste imported silently with every counting category inflated
roughly seventy-fold, while this document already described the check as
protection. **A verification module that no import path consults does not protect
an import path, however green its own tests are.**

The last row is different and stays different. The importer holds no prior-season
observations, so `verify_no_baked_in_availability` is recorded as `NOT_RUN` on
every import. That is visible in `ProjectionImportOutcome.verification` and is
deliberately *not* collapsed into the success of the call: an absent check and a
passing check must not look the same.

### Not checkable — stated rather than papered over

**The `GP` forecast itself.** `GP` is a claim about a season that has not been
played. Comparing it to last season's actuals measures a different quantity and
would fire on every player who got healthier or got hurt. There is no check
here, and building one would have meant building a check that cannot fail.

**The vendor's scoring format.** This was in the original brief and the brief
was wrong. Per-category per-game rates do not depend on the scoring format: a
rebound is a rebound in 8-cat and 9-cat, and the category set changes which
rates get *valued*, not what any rate *is*. The only column whose meaning
depends on the vendor's format is `TOTAL`, its z-score composite — and
**ADR-008 already forbids importing it**. The correct response is to *refuse the
column*, which is a mechanism that can fail, rather than to *verify the format*,
which would be a flag that cannot. `TOTAL`, `R#` and `ADP` are now terminal
aliases: read, logged as ignored evidence, and discarded.

Format risk has not vanished — it belongs to `aav-blending`'s
`basis_category_count`, downstream of here.

**Whether Hashtag's `GP` is its own or licensed.** Unknown. Relevant to
independence claims, not to this import.

---

## The tolerance is volume-weighted, and that is the point

Reconciling the stated percentage against the stated makes/attempts needs a
bound that scales with volume:

```
(0.05 + 0.05·p)/attempts + 0.0005
```

derived by propagating display rounding (volumes to 1 dp, percentages to 3 dp)
through the ratio.

Measured across **429 live rows**: **0 violations**, worst error/bound ratio
**0.915**.

Flat alternatives, on the same rows:

| Flat tolerance | False alarms |
|---|---|
| 0.01 | **257 / 429** |
| 0.02 | 161 / 429 |
| 0.05 | 59 / 429 |

A player projected for 0.3 free-throw attempts has a rounding interval wider
than a third of his own percentage. Loosening the bound far enough to admit him
would wave through a genuinely mangled cell for a high-volume shooter.

**Volume-weighting the check is the same principle as volume-weighting the
category.**

---

## Why the shape check is on points, not minutes

The obvious bound is "nobody plays more than 48 minutes". Measured against both
modes:

| Discriminator | Passes on AVG | Passes on TOT | Separates? |
|---|---|---|---|
| `MPG <= 48` | 100.0% | **100.0%** | **no** |
| `PTS <= 60` | 100.0% | 0.0% | yes |

Because TOT mode leaves minutes per-game, the minutes bound holds on both
shapes and separates nothing. It is pinned as a test
(`test_minutes_would_not_have_caught_it`) so it is not reintroduced as an
apparently-sensible addition.

## Why the scoring identity is not the shape check

`2*FGM + 3PM + FTM == PTS` is the strongest-looking check available and it is
**algebraically scale-invariant**: multiply every column by 72 and it still
holds exactly. It therefore **passes cleanly while the season-totals defect is
fully present**.

It happens to also flag TOT mode in the live data, but only because the absolute
residual grows with magnitude — an accident of rounding, not a property to rely
on. `test_the_scoring_identity_cannot_detect_a_scale_error` asserts the
limitation, so promoting this check into the shape role requires deleting a
passing test.

---

## The availability check, and the decision it protects

The owner, on what he is actually deciding on draft night:

> On draft day, games played is the aggregate of all this intra-year injury
> data. We're assuming those games are fully healthy. The decision I'm making
> is: is sixty games of player X worth more or less than seventy games of
> player Y.

That comparison is only coherent if the per-game rates describe a **healthy**
game. If Hashtag has already folded expected missed games into its rates and
`quant` then applies `p(play)`, the discount lands twice, and hardest on exactly
the fragile stars this tool exists to price correctly. ADR-002 requires the two
to be separate and fused explicitly.

**Design constraints, all deliberate:**

- **Cohort-level only, never a per-row gate.** Any individual player can
  legitimately be projected for far fewer minutes than he played last season.
  Failing his row would be wrong every time.
- **Minimum 20 projected games**, minimum 25-player cohort. Below that the
  median is not a cohort measurement, and it reports `NOT_RUN` — **not a pass**.
- **Direction stated in advance.** Baked-in availability drives the ratio
  *below* 1. A ratio above 1 is a different finding and not one this check is
  entitled to make.
- **Compared against prior-season minutes per *played* game** from
  `player_game_logs` — independent provenance, since the vendor did not supply
  it.

**False-pass reading:** a cohort whose minutes genuinely declined year over year
by roughly what an availability discount would have applied — a league-wide
load-management shift, or a cohort selected toward players losing minutes. The
ratio cannot distinguish "the vendor discounted" from "these players are really
playing less". It is evidence about a direction, reported as a measurement with
a threshold, not a verdict.

**This check does not read `player_participation`.** The injury-conversion
cohort blind is closed and nothing here approaches it.

---

## ADP is recorded, and does not enter the identity score

Hashtag's `ADP` column is a good tiebreaker in principle — the useful
tiebreakers are the ones the vendor did *not* use to build the row — but
**Hashtag's own ADP has unestablished provenance**: we cannot show it is
independent of the projections beside it in the same table.

That is `market.independence`'s existing `LINEAGE_UNESTABLISHED` (101), not a
second notion of independence invented here, and it is **provenance
unestablished, not provenance disproved**. An empty lineage must not pass an
overlap test by having nothing to overlap.

Independent ADP exists (`fantrax_getadp_nba.json`) and is the one worth wiring.

**Deliberately not done in this unit:** adding ADP to `score_evidence` in
`identity/evidence.py`. Its weights (`name .70 / team .20 / position .06 /
suffix .04`) were tuned without it, so introducing a fifth field re-normalises
every existing confidence score — including matches nothing in this unit
touches. That is a change nobody asked for hiding inside a change someone did.
**The weighting is handed back to the architect as its own decision.**

---

## Throttling, retry, and behaviour when the source is down

- **No scheduled polling.** The production path is a copy-paste the owner
  initiates. There is no automated fetch to throttle.
- **The live smoke test is opt-in** and single-request. It exists to fail
  loudly on drift, not to keep the data fresh.
- **Source down / returns garbage:** every failure mode is a loud refusal at
  parse **or import** time. There is no partial-import path and no best-effort
  mapping: header drift, an unparseable shooting cell, a non-reconciling
  percentage, a percentage stated on zero attempts and a repeated header row are
  each fatal at parse time, and a batch whose values are not per-game is refused
  at import time.
- **The page is ASP.NET WebForms.** Any programmatic fetch must post
  `__VIEWSTATE`/`__EVENTVALIDATION` and — the trap — **must echo back every
  already-checked checkbox**, because ASP.NET does not post unchecked boxes.
  Omitting them silently collapses 17 columns to 8 and returns a page that
  parses fine and means something else. This produced four simultaneous zeros
  during this investigation before it was diagnosed.

---

## Sample scope — do not read this as a full guarantee

- **429 data rows** from **one** 900-row page request on **one** date.
- Roughly **500** players are rostered league-wide, so this is not the full
  universe.
- The page defaults to **30 rows**; a 30-row reconciliation suggested max
  |ΔFT%| = 0.0126, and at 429 rows it is **0.3040**. Low-minute players are
  where the shape bound is weakest and where the small sample was most
  misleading.
- **No paste from the owner has ever been seen.** The contract above is the
  live page's; whether his spreadsheet round-trip preserves it is untested.
- Whether the header repetition interval varies with page size is unknown.

## Could not verify

- That the owner's actual paste matches this contract.
- That the header sequence is stable across dates or across a season rollover.
- Whether Hashtag's `GP` figures are its own or licensed from elsewhere.
- Whether the composite cell dialect holds for the seven unticked categories,
  which were never rendered.
- The `GP` forecast itself, which is unverifiable in principle.
