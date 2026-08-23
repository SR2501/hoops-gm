# Cohort admissibility — the cross-store check, and why it is legal to run

**Owner:** `data-engineer`
**Artifact:** `docs/adapters/nba-injury-report-cohort-admissibility-2025-26.json`
**Generator:** `hoops_gm.ingest.injury_report.cohort_admissibility`
**Contract tests:** `backend/tests/test_cohort_admissibility.py`,
`backend/tests/test_cohort_admissibility_join.py`

This artifact answers one question — *can this cohort activate the model at
all?* — and it answers it **before** an unblind is spent. It counts inputs. It
fits nothing, and it emits no outcome value.

---

## Why a cross-store join was necessary

**No single store holds both halves.** Verified rather than assumed:

| store | participation rows | injury report rows |
|---|---:|---:|
| `hoops-gm-data/hoops_gm.db` | 43,037 | 0 |
| `hoops-gm-data/throwaway-report-sweep.db` | 0 | 69,922 |

`cohort_evidence._participation_join` joins on local surrogate keys
`(game_id, player_id)` inside **one** session, which is correct for the
artifact it serves — `PlayerParticipation` carries a unique constraint on
`(player_id, game_id)`, so within one build the join can neither fan out nor
lose a row. Across two independently built stores that guarantee is worth
nothing: a rebuild reassigns surrogates freely.

So this join is on **source-stable identity**:

```
nba_games.nba_game_id  x  player_external_ids[source='nba'].external_id
```

The two stores' surrogates happen to coincide (1,230/1,230 games,
5,206/5,206 anchors). That was checked, and deliberately **not** relied on.

### The trap this shape sets, hit by an independent reviewer

Reproducing the headline with raw SQL, the coordinator's first attempt joined
`injury_report_entries.game_id` **directly to** `nba_games.nba_game_id` — a
local surrogate *integer* against a source-stable *string*, across two
databases. It returned **zero rows and no error.**

That is the dangerous failure, not a loud one: an empty result set is
indistinguishable from a clean run that simply found nothing, and it would have
read as "no observations join across these stores" rather than "this join key is
wrong". `injury_report_entries.game_id` is a foreign key into its **own**
database's `nba_games.id`; it means nothing in the other store.

The generator resolves both sides through source-stable identity for exactly
this reason, and `test_every_observation_joins_despite_disjoint_surrogate_ids`
builds the two fixture stores with **disjoint id bases** so a silent fallback to
surrogates fails loudly rather than passing by coincidence.

---

## The contamination question, and why the answer is "sound"

`hoops-gm-data/README.md` warns that the sweep store took its tip-offs from
`ScheduleLeagueV2` rather than `BoxScoreSummaryV3`, which makes it *"unusable
for any cohort manifest, forever"* — its own
`cross_source_tipoff_reconciliation` would degenerate into comparing one
endpoint with itself, and **nothing records the provenance of a persisted
instant**, so no reader could tell.

That warning is about *tip-offs*, and tip-offs are not incidental here: every
lead time, and the pre-tip-off selection that defines a canonical observation
at all, rests on `tipoff_utc`.

**The generator removes the exposure rather than bounding it.**
`select_canonical_pregame_observations` accepts a `game_tipoffs` mapping. The
generator feeds it the **participation store's** instants while reading report
rows from the sweep, so the sweep contributes report rows and nothing else. Its
own `tipoff_utc` column is never read.

`test_shifting_the_report_store_tipoff_is_reported_but_changes_no_count` is the
falsifiable form of that claim: it moves the report store's tip-offs four hours
and asserts every count and both lead-time ranges are unchanged, while the
disagreement is still *reported*.

### The check the README says cannot be done, done across stores

Comparing the two stores against each other is a genuine two-endpoint
reconciliation rather than a self-comparison:

```
games compared            1,227
tip-off disagreements         0
game_date disagreements       0
without both instants         3   = 0022500259/260/261
```

Those three are exactly the documented known gap — no `boxScoreSummary` body at
source.

**Positive evidence that the stores really are different endpoints**, rather
than trust in the README's attribution: the sweep carries tip-offs for **1,230**
games including those three, and `BoxScoreSummaryV3` cannot have produced them.
The ledger's own README proxy also holds exactly — 1,227 tip-offs against 1,227
games with participation.

This remains an **operational** independence, not a structural one. Nothing
records the provenance of a persisted instant, so the check witnesses that the
two stores agree; it does not witness which endpoint each one read.

---

## The result

Cohort: full 2025-26 regular season, 164 game dates, `2025-10-21..2026-04-12`.
§4's rule gives development 82 / selection 41 / **held out 41**
(`2026-03-02..2026-04-12`).

| status | canonical | direct outcomes | held-out direct | floor |
|---|---:|---:|---:|---:|
| `out` | 10,453 | 10,278 | 2,963 | 30 |
| `doubtful` | 221 | 217 | **83** | 30 |
| `questionable` | 1,191 | 1,184 | 335 | 30 |
| `probable` | 435 | 434 | 92 | 30 |
| `available` | 1,489 | 1,485 | 467 | 30 |

**Admissible. `doubtful` is binding at 2.77x the floor.**

### The reduction that matters, because it is not the one the floor suggests

A full-season raw `doubtful` count of 2,087 is ~70x the floor and says almost
nothing:

```
2,087 raw rows -> 221 canonical -> 217 direct -> 83 held-out
```

**Canonicalisation costs 9.4x on its own** — one latest pre-tip-off row per
player-game, so a player listed `doubtful` on six successive reports whose last
pre-tip status is `out` contributes **zero** `doubtful`. The direct-outcome and
holdout steps cost only 1.02x and 2.6x. Reading a raw status histogram as
evidence of cohort size overstates it by an order of magnitude.

---

## What the count cannot see, declared pre-unblind

Both are in the artifact under
`section_2_admissibility.limitations_that_the_count_cannot_see`.

1. **The holdout is the end-of-season shutdown window, and it is not the regime
   the tool is used in.** Late February to mid-April: eliminated teams shutting
   players down, seeding races, pre-playoff load management. v1's holdout was
   late December — mid-season and unremarkable — so widening did not merely make
   the holdout bigger, it silently changed its character. *"Widen the cohort" is
   satisfied without being met*, and no count distinguishes the two outcomes.
   Owner-ruled a stated limitation; **it must reach the model card verbatim.**

2. **The reporting-era boundary falls inside the cohort and the split does not
   respect it.** `FIFTEEN_MINUTE_ERA_START` is 2025-12-22 Eastern
   (`client.py:81`). In direct outcomes:

   | partition | legacy | short-lead |
   |---|---:|---:|
   | development | 4,166 | 1,946 |
   | selection | **0** | 3,546 |
   | held out | **0** | 3,940 |

   The fit would rest substantially on a regime the holdout contains none of.
   §2's gate is pooled over the held-out range and cannot see this.

**The split boundaries are deliberately not moved.** §4 already names the trap:
choosing different proportions *because these ones are inconvenient* is a worse
reason than keeping them.

Era is classified from each observation's **own `report_timestamp`**, never from
its game date — an evening-before report for a 2025-12-22 game is filed on
2025-12-21 and is legacy, so game-date classification would mislabel exactly the
boundary rows the table exists to expose.

### ADR-007's era figures do not replicate at this scale

ADR-007 line 62 records **1.596** unresolved `doubtful` per date short-lead
against **0.917** legacy. Measured here: **0.019** short-lead (2/104) against
**0.033** legacy (2/60) — roughly fifty times smaller and reversed.

**That is not a claim that ADR-007 is wrong.** A 50x gap is not sampling noise;
it means the two count different populations. This counts *canonical*
observations whose identity did not resolve; a count over raw report rows would
be far larger, because a player carried `doubtful` across many successive
reports is one canonical row and many raw ones. ADR-007 does not say which it
used, and this lane did not re-derive it.

What *is* measured: era-dependent unresolved exclusion is 2 rows in each era and
does not concentrate on `doubtful`; in both eras it lands overwhelmingly on
`out` (74 legacy, 45 short-lead). The era **composition** finding above is a
different mechanism and is unaffected.

---

## The disclosure surface is a closed set, scoped to the surface

§2 permits **no new outcome-keyed field, at any granularity, in any manifest
version**. `OUTCOME_KEYED_MANIFEST_FIELDS` freezes the permitted set as
`(filename, dotted path)` pairs with list indices normalised to `[]`, and the
contract test scans **every committed JSON under `docs/`**.

**Scoped to the surface, not to the manifest** — and that mattered immediately.
A manifest-scoped guard missed `participation-ledger-2025-26-coverage.json`,
which publishes `seasons[].outcomes`, a real outcome marginal, and sat outside
the old cohort glob entirely. It is **not** a §2 breach in substance: it is a
whole-*ledger* marginal over all 43,037 rows, unconditioned on injury-report
status, and therefore strictly less informative than the cohort-restricted
marginal §2 already permits. It is listed because an unlisted field is
indistinguishable from an unnoticed one.

**A vocabulary collision worth knowing about.** That file's `seasons[].reasons`
also trips the detector: **`not_with_team` is a member of both
`ParticipationOutcome` and `DnpReason`**, the two enums' only shared token. The
field is `DnpReason`-keyed and is not an outcome marginal. It is allow-listed
with the mechanism stated rather than the detector weakened, and the overlap is
pinned at exactly `{"not_with_team"}` so a future divergence fails loudly.

Detection is by **intersection, not subset**: a subset test passes a mapping
that hides one outcome key among unrelated ones.

Direct-outcome counts themselves stay publishable, and §2 says why — they say
*which rows have a usable outcome*, not what those outcomes were.

---

## If you are here to regenerate the cohort manifest, read this first

This artifact is **not** a regenerated cohort. It is the admissibility verdict
and its evidence. Regenerating
`nba-injury-report-cohort-*.json` for the widened window is separate work, and
three things about it are non-obvious enough to burn a day each.

**1. `build_cohort_evidence` takes one `Session`, and neither store can serve
it.** Driven: the clean ledger holds **0** `injury_report_entries`; the sweep
holds 69,922 but took its tip-offs from `ScheduleLeagueV2`. So pointing the
generator at the ledger yields an empty cohort, and pointing it at the sweep
yields a manifest whose `cross_source_tipoff_reconciliation` compares one
endpoint **with itself** — reporting `agreed: true`, `witnessed: true`, and
meaning nothing. That is exactly the failure `hoops-gm-data/README.md` was
written to prevent, and **nothing records the provenance of a persisted instant,
so no reader could tell from the output.** The cross-store seam this module uses
is available to a *count*; a manifest needs both halves in one store, which
means importing the reports into the ledger.

**2. It costs zero requests, but only from the right directory.** All 583
injury-report captures and 2,462 stats captures are already in
`hoops-gm-data/data/raw`. `RawPayloadStore` resolves **relative to the current
working directory** while the database is anchored to the repo root, so an
ingest launched from anywhere else silently detaches the cache and re-fetches
everything at ~1.1 s per request with nothing saying why. Run it from
`C:\Users\steverones\hoops-gm-data`.

**3. The disclosure guard will fire, and that is the point.** A regenerated
manifest publishes `participation_join.participation_outcome_counts` under a new
filename, which is a new `(filename, path)` pair outside the frozen allow-list.
Verified by experiment rather than predicted — dropping a copy of the existing
manifest under a widened-window name fails
`test_the_union_over_the_whole_surface_equals_the_frozen_set` and names the
field.

**Do not reflexively add it to the allow-list.** §2 documents the reason: the
four-week manifest is already committed, a widened manifest is a **superset**,
and git makes differencing free — so `M_B[outcome] − M_A[outcome]` yields the
outcome marginal of the added dates, with the by-date denominators supplying
their status composition. **The regeneration is the operation that opens that
attack**, and §2 says so in advance. Whether the widened manifest may carry an
outcome marginal at all is a `quant` question against the freeze, not an
allow-list edit.

**What is already done and should be reused, not rebuilt.** §2's two manifest
requirements — per-status **direct-outcome counts by game date**, and
**exclusion classes by status** — are both computed and committed here, along
with the cross-store tip-off agreement, the era composition, the §7 lead-time
bands and two fingerprints. A regeneration that recomputes them should
**reconcile against these** rather than replace them silently; a disagreement is
a finding.

## Running it

Read-only, no external requests, nothing written to `hoops-gm-data`.

```powershell
cd backend
$env:PYTHONPATH = "$PWD\src"
python -m hoops_gm.ingest.injury_report.cohort_admissibility `
    --participation-db 'C:\Users\steverones\hoops-gm-data\hoops_gm.db' `
    --report-db 'C:\Users\steverones\hoops-gm-data\throwaway-report-sweep.db' `
    --out '..\docs\adapters\nba-injury-report-cohort-admissibility-2025-26.json'
```

Exit `0` admissible, `1` refused. Output is deterministic — regenerating twice
gives byte-identical bytes.

**`read_only_engine` asserts the file exists on the filesystem before opening
it.** SQLite creates a database on connect rather than refusing, so a mistyped
path yields a brand-new empty file and a count against it is an honest,
reproducible, meaningless zero — a false zero manufactured by the very check
written to settle the question.

**The by-date table settles any split without regeneration.** If the split
moves, recompute the §2 block from `direct_outcome_counts_by_game_date` and
`direct_outcomes_by_report_era.by_game_date`; no ingest is needed. That is why
the primary payload is partition-agnostic — baking a split boundary into an
observations-layer artifact is a backward flow under ADR-008.
