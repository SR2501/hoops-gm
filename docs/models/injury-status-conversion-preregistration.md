# Injury status conversion — frozen pre-registration (v2)

**Owner:** quant
**Freeze id:** `injury-status-conversion-v2-20260821T145900Z`
**Frozen at:** 2026-08-21T14:59:00Z
**Status:** frozen. No model is fitted. No number is emitted.

This document is the protocol. It is not a model card and it does not claim the
Model gate — there is nothing yet to gate. The model card that eventually reports
a result is `injury-status-conversion.md`, and it does not exist yet.

---

## Why this exists, and why it is dated today

`reliability-metrics.md` records that this project has never managed a provable
prospective pre-registration: *"the implementation and evidence first enter git
together… this repository cannot independently prove prospective registration"*,
with a standing instruction that any future release commit its protocol
separately before evaluating its final holdout.

That instruction is satisfiable **only while the outcome data does not exist**.
At this commit the row-level outcomes **of the cohort that will actually be
fitted** are absent from the repository and from every checkout the coordinator
searched — nine worktrees plus the owner's main checkout, where the one real
database (`hoops_gm.db`, 3.97 MB) holds **0 rows** in both
`player_participation` and `player_game_logs`.

**That claim needs a boundary, and review found I had drawn it too wide.** An
earlier draft of this section said the data "could not have been consulted",
full stop. That was false. See the contamination disclosure immediately below:
row-level outcomes for the *invalidated* cohort are reachable in the author's
clone, and are now known to the author in full. What is genuinely unavailable is
narrower and still sufficient: the corrected cohort has no row-level artifact
anywhere, and the widened cohort this protocol will be fitted against **does not
exist at all**.

So the honest form of the argument is not "nobody could have looked". It is that
the cohort this freeze commits to has not been collected, so no split of it, no
outcome in it, and no result from it can have informed a line of this document.
Once that cohort exists, that property is gone permanently.

---

## Contamination disclosure — read this before treating the freeze as a blind

**This is a replication protocol, not a clean blind.** Stating that plainly is
the condition on which the rest of the document is worth anything.

I have read the unblinded held-out results of the v1 study, preserved on the
local-only branch `sr2501-injury-status-conversion` at `3285e647` and never
pushed. I know its selected structure, its three fitted band probabilities, its
held-out Brier scores against the global baseline, its calibration table, and the
reason its five-status candidate was ineligible.

**And the row-level data is reachable, which an earlier draft of this document
failed to disclose.** That commit contains
`backend/tests/model_evidence/injury_status_conversion_v1_rows.json` — 594,951
bytes, 1,934 records, each carrying status, participation outcome, game date,
lead time and exclusion reason. One `git show` yields the full v1 status x
outcome contingency. The earlier draft enumerated only the *aggregates* above,
which left a reader believing summaries were all that was available. They were
not.

**Furthermore, as of the review round that produced this correction, the author
has seen that contingency table in full**, because the reviewer computed and
published it while demonstrating the omission. Whether it had been opened before
that point is a claim about the author's own conduct that no reader can check,
so this document does not rest on it. Treat the v1 row-level contingency as
known.

**How much of the eventual fitting set that covers, stated as the bound it
actually is.** An earlier draft said "roughly 99% of rows" and offered set sizes
as the evidence. Set sizes do not establish overlap, and the two cohorts are
demonstrably **not** nested: `doubtful` went 22 to 21 and `questionable` 152 to
151 even as the correction *added* two games, so v1 rows are genuinely absent
from the corrected cohort. Per status, shared rows cannot exceed the smaller
count:

| Status | v1 canonical | Corrected | Shared, at most |
|---|---:|---:|---:|
| `out` | 1,495 | 1,508 | 1,495 |
| `available` | 206 | 209 | 206 |
| `questionable` | 152 | 151 | **151** |
| `probable` | 59 | 59 | 59 |
| `doubtful` | 22 | 21 | **21** |
| **Total** | 1,934 | 1,948 | **1,932** |

**At most 1,932 of 1,948 rows are shared — ≤99.18% of the corrected cohort.**
There is **no non-trivial lower bound** without row keys, and none can be
computed until the cohort database exists, because an overlap needs both sides'
keys and the corrected side has no row-level artifact anywhere. An upper bound is
the conservative direction here: it caps how much of a future fitting set the
author has already seen.

So the candidate set and grouping below are **inherited knowingly** from a study
whose answers I have seen, at row level, on data overlapping the corrected cohort
by at most 99.18%. Anyone reading a future result against this freeze must
discount the selection step accordingly: the three-band structure is not an
independent rediscovery, and a report that it "was selected again" is close to
uninformative.

**What this does not contaminate.** The cohort this protocol will actually be
fitted against is a widened one that does not exist. No row of it has been
collected, so nothing in it has been seen by anyone. The contamination is real
and bounded: it attaches to the *structure* carried forward from v1, not to the
outcomes the fit will be evaluated on.

What this freeze *can* honestly establish is narrower and still worth having:
the split boundaries, the metrics, the calibration requirement, the sensitivity
analyses, the activation floors, and the stopping rule are fixed **before** any
outcome from the cohort that will actually be fitted has been observed by anyone.

---

## 1. Question and eligible cohort

**Question.** For one NBA regular-season game, how well does the latest canonical
pre-tip-off official NBA injury-report designation for a player predict whether
that player appears in that game?

This is availability only. It consumes no production statistic, projection,
ranking, AAV, or market signal. It is not the availability model; it is one
candidate input to it (ADR-002, ADR-007).

**Unit.** One canonical latest pre-tip-off observation per (stable NBA game id,
stable NBA player id).

**Statuses.** `out`, `doubtful`, `questionable`, `probable`, `available`.

**Play outcome.** `played`.
**Direct non-play outcomes.** `did_not_play`, `did_not_dress`, `not_with_team`,
`inactive`.

**Excluded, never relabelled:** unresolved canonical player identity; missing
participation row; explicit `unknown` participation outcome; `not_yet_submitted`
team marker; legacy injury evidence; post-tip-off report.

**Missing or unknown is never non-play.** R35 holds throughout. A silent ledger
is not an absence.

**Stated DNP reason is not a feature** and never will be in this model. Per
`AGENTS.md`, "Rest" is routinely laundered as a minor ailment; the corrected
cohort prints 9 `Rest` observations against 1,324 `Injury/Illness`, which is not
a credible split and is evidence about the reporting regime rather than about
players.

---

## 2. Cohort admissibility — checked **before** unblinding, and binding

This section is the substantive change from v1 and the reason the freeze is
worth committing separately.

### The gate

A cohort is **admissible** for fitting only if, within the declared held-out date
range, **every one of the five statuses carries at least 30 direct outcomes.**

**The unit is direct outcomes, matching §8 condition 6 exactly.** An earlier
draft said "observations", meaning canonical observations. Both reviewers caught
it independently, and it defeated the gate's whole purpose: canonical
observations include unresolved identities and rows with no participation row, so
the canonical count is the *looser* of the two. A cohort could clear a
canonical-30 pre-check and then be vetoed by condition 6 at 29 — which is exactly
the wasted unblind the gate exists to prevent. The exclusions are not uniformly
spread, so this is not a rounding concern: v1's own evidence puts its 28
exclusions entirely on `out` (26) and `questionable` (2), leaving `questionable`
with 152 canonical observations but 150 direct outcomes.

Direct-outcome counts remain *inputs*. They are a count of which rows have a
usable outcome, not of what those outcomes were, so the gate is still checkable
without unblinding a single participation result — which is the property that
makes it a gate rather than a post-mortem.

### Requirement on the cohort manifest, owned by `data-engineer`

An earlier draft asked for `status_counts` broken down by declared partition.
That was the wrong shape, and the better one below is `data-engineer`'s, adopted
with attribution: baking `quant`'s split boundaries into an ingest artifact is a
backward flow under **ADR-008**, whose decision is that layers are ordered
`observations → projections → availability → valuation` and information flows one
way only. A split boundary is an availability-layer parameter; the cohort
manifest is an observations-layer artifact. It also forces a manifest
regeneration every time the split moves, which needs no ADR at all.

*(An earlier draft cited ADR-006 here, in four places. ADR-006 is "External
adapters isolated behind contract tests" and concerns adapter-versus-upstream
isolation — fixtures, contract tests, throttling. It says nothing about a
downstream consumer's parameter entering an ingest artifact. `code-review` caught
it: I adopted a reviewer's rationale without re-deriving the citation, which is
the same defect as the PR #30 mis-citation one round earlier and is exactly what
`gates.md` says to re-derive at the moment of writing.)*

Publish instead:

1. per-status counts of the **joined direct-outcome** set, **by game date**; and
2. the exclusion classes — `unresolved_identity`, `without_nba_anchor`,
   `without_participation_row` — broken down **by status**.

That is partition-agnostic: it makes *any* chronological split checkable rather
than only the currently declared one, and needs no knowledge of this protocol.
Those three are the exact `continue` branches in `_participation_join`, and all
three are **pure absence predicates**: `row.outcome` is not in scope on any of
them, so publishing them by status discloses no outcome value.

*(An earlier draft listed `explicit_unknown` as the third and called all three
absence predicates. That was wrong twice over: `explicit_unknown` is defined by
an outcome **value**, `ParticipationOutcome.UNKNOWN`, so it is a status x outcome
cell rather than an absence; and it is not a `continue` branch in the generator at
all. `code-review` found it.)*

### The disclosure surface is a closed set, not a granularity rule

An earlier draft stated the constraint as *"outcome-valued counts stay
whole-cohort; only denominators get the finer breakdown."* **Both reviewers
showed that rule is necessary but not sufficient, and it mis-sorted its own first
two applications** — a direct-outcome count is itself defined by a predicate on
the outcome value, so the rule forbade and permitted the same object.

Three ways granularity fails as a safety property, all demonstrated by
`data-engineer` against the *committed* manifest rather than hypothesised:

- **It constrains coarseness, not informativeness.** The two existing
  whole-cohort marginals already yield the exact global play rate
  `292/1918 = 0.15224` and bound the non-`out` play rate at `≤ 292/410 = 0.712`.
  Real inference, available today, from fields the granularity rule calls safe.
- **It is stated per-manifest, and git makes cross-manifest differencing free.**
  The manifest path has 12+ committed revisions, and the planned operation is
  *widening the same window*, so cohort B ⊃ cohort A with both committed. Then
  `M_B[outcome] − M_A[outcome]` is the outcome marginal of the added dates, and
  the new by-date denominators supply their status composition. The granularity
  rule is satisfied at every step. **The widening this document recommends is the
  thing that opens it.**
- **"Whole-cohort" is a label, not a size guarantee.** Coarseness depends on `N`;
  on a small cohort a whole-cohort marginal is nearly row-level.

A rule reached by enumerating attacks is stale the next time a field is added. So
the constraint is stated as a closed set, which is what the gate actually needs —
§2 and §8 condition 6 consume **only denominators**:

> The pre-unblind disclosure surface carries **no outcome-valued count beyond the
> single whole-cohort `participation_outcome_counts` the manifest already
> contains**, which is inherited adapter evidence and not a gate input. **No new
> outcome-keyed field may be added, at any granularity, in any manifest version.**

`data-engineer` owns a contract test asserting the set of outcome-keyed manifest
fields equals a frozen allow-list and never grows, landing with the widened
cohort. That is enforceable in CI, which the granularity rule was not.

### An inadmissible cohort is not fitted

If the gate fails, no fit is run, no outcome is unblinded, and the finding is
reported as a cohort-sizing result. Spending an unblind on a cohort that cannot
activate destroys the pre-registration for no return.

### The currently committed cohort fails this gate on arithmetic alone

Re-derived from `docs/adapters/nba-injury-report-cohort-2025-12-08--2026-01-04.json`
at this commit — whole-cohort canonical `status_counts`:

| Status | Whole cohort |
|---|---:|
| `out` | 1,508 |
| `available` | 209 |
| `questionable` | 151 |
| `probable` | 59 |
| `doubtful` | **21** |

A chronological holdout is a subset of the cohort, and direct outcomes are a
subset of canonical observations, so held-out direct `doubtful` is at most 21
under **either** unit. **21 < 30 unconditionally.** No split, no seed, and no
outcome can change it. Using the canonical count here is deliberate: it is an
upper bound on the direct count the gate actually measures, so the argument is
conservative rather than merely valid. `probable` at 59 would require the holdout
to contain 30 of 59 — more than half of the `probable` observations — which no
conventional chronological split produces.

Empirically confirmed on near-identical data: v1's actual held-out `doubtful`
count was **4**.

**The 2025-12-08..2026-01-04 cohort can therefore never activate this model.**
That conclusion required no outcome data and is disprovable by re-reading the
manifest.

For calibration of what "wide enough" means: v1's split put 616 of 1,906 direct
outcomes in the holdout, a 32% share. At that share a status needs roughly
`30 / 0.32 ≈ 94` whole-cohort observations to clear the floor. Against `doubtful`
at 21 that is about a 4.5× widening — four weeks to roughly eighteen, i.e. most
of a regular season, or multiple seasons.

**That multiplier is an estimate and is explicitly conditional on the status mix
holding.** It probably does not: December reporting is not April reporting, and
late-season shutdowns inflate `out` without inflating `doubtful`, which would
make the true requirement *larger*. The multiplier is a planning figure for the
owner's sweep decision, not a preregistered threshold. **The gate is the
per-status count in the declared holdout, measured, not this estimate.**

---

## 3. Cohort identity visible at freeze time

Recorded to establish what I could and could not see when this was frozen.

| Field | Value |
|---|---|
| Manifest | `docs/adapters/nba-injury-report-cohort-2025-12-08--2026-01-04.json` |
| Manifest SHA-256, LF-normalised | `383fa77a9aaa47a66f1fcddc1ead65843302b8ca0a6e0d37b53cbbcfdb2b4105` |
| Canonical observation fingerprint | `6ca4d37f3dd97226141d43f0c6c1b97053d742e7629f63c4104b8b040aec278b` |
| Joined outcome fingerprint | `3227730fe6d07866aca81f4bc31efbbd953d6cab0ddcdb6350375fb949c78b44` |
| Canonical player-games | 1,948 |
| Joined player-games | 1,918 |
| Admissible under §2 | **no** |

**`joined_player_games` is not by construction a count of *direct* outcomes**, and
an earlier draft labelled it as one. `ParticipationOutcome.UNKNOWN` is a valid
enum member and `_participation_join` counts it into `joined_player_games` like
any other value. The label happened to be true here only because this cohort has
zero `unknown` rows — `participation_outcome_counts` has no `unknown` key and its
five values sum to exactly 1,918. On a cohort with `unknown > 0`, reading this
field as the direct-outcome count would carry non-direct rows into the fitting
denominator, and §1 excludes them. A future manifest should emit
`joined_direct_outcomes` separately.

**The manifest hash is LF-normalised, and that is a deliberate correction.** The
v1 freeze pinned a field named `manifest_worktree_sha256`, which is
checkout-newline-dependent: the same committed bytes hash differently on a CRLF
checkout (19,261 bytes) than on an LF one (18,799 bytes). That is precisely the
defect class PR #30 had to correct after publication, recorded at
`docs/handoff.md:7543` and again at `:8080`. **Not** in the manifest's own
`source_fingerprint_method`, which an earlier draft cited: that field states the
method and carries no history, and a reader who opened it to check would have
found nothing — a provenance error inside a section headed "re-derived from
files". Verified here: the LF-normalised digest equals the digest of the raw git
blob, byte for byte.

**The canonical fingerprint above is not the value quoted in the PR #39 handoff
entry** (`80b3e563…`). The manifest was regenerated during later remediation
rounds and the prose was not updated. The joined fingerprint quoted alongside it
is **not** stale, and this claim is scoped to the canonical one only. This table
was re-derived from the file at this commit, per the `gates.md` instruction to
re-derive any number appearing in prose at the moment of writing.

**A warning this lane was handed in its superseded form — and `data-engineer` had
already corrected it.** The brief that opened this unit relayed PR #39's original
entry, which tells `quant` that maximum lead time moved 540 → 1,650 minutes and
that "any lead-time stratification built on the old 9-hour maximum is wrong".
That is true of *canonical* observations and **false of the data this model
fits**: `participation_join.joined_lead_time_minutes` maximum is still **540**,
so the 1,650-minute observation is excluded from the joined set and cannot enter
any fit. The joinable range is unchanged at 15..540 minutes, which is why §7's
`>540` band is expected empty.

**An earlier draft presented that as a novel correction. It was not.**
`docs/handoff.md:7719-7722`, in the later remediation round of the same lane,
already says it: *"My earlier framing of the tail as a precondition for `quant`
was right in direction and wrong in the detail that matters: it would have sent
them looking for a tail absent from the data they use."* The record had corrected
itself before this unit began; the author read PR #39's first entry and not the
round that superseded it. **A claim of the form "the record is wrong" is
invalidated by another lane's later work**, which is the same class as the stale
`80b3e563…` above — hit here while auditing exactly that class in someone else's
prose.

Which exclusion class the 1,650-minute row falls into is **not determinable from
the manifest**, which publishes only class totals (28 unresolved identities, 2
missing participation rows). But the repository is not silent on it, and an
earlier draft wrongly implied it was: `docs/adapters/nba-injury-report.md:1309`
states in bold that *"It is one of the two observations with no participation
row, so it is excluded from the joined set"*, and `docs/handoff.md:7717-7718`
says the same. Both were written by the lane holding the database. This freeze
declines to *rely* on that attribution, because it is not checkable from the
manifest — not because the record does not make it. The load-bearing claim is the
one the manifest settles on its own: it is not in
the fitting set.

---

## 4. Splits

Chronological, never random. A random split leaks: the same player's status on
consecutive days is not independent, and same-game teammates share one opponent,
one travel leg and one reporting decision.

**The denominator is the ordered list of distinct game dates in the admissible
cohort**, written `N`. Not calendar days. An earlier draft used "date range" in
one sentence and "share of game dates" in the next, which are different
denominators giving different boundaries — for the currently committed cohort,
`scope.game_dates` is 26 while `2025-12-08..2026-01-04` is 28 calendar days. It
also gave no rounding rule, and 25% of 26 is 6.5. That is the same undefined
boundary this document faults v1 for in §7, in the section that determines every
downstream number, and it would have left a future author choosing the split
after the cohort was in hand. Stated explicitly instead:

| Partition | Definition | Purpose |
|---|---|---|
| Development | first `floor(0.50 · N)` game dates | fit candidates |
| Selection | next `floor(0.25 · N)` game dates | choose structure |
| Final training | development + selection | refit selected structure |
| Held out | all remaining game dates | evaluated **once** |

The holdout takes the remainder, so the three partitions are exhaustive and
disjoint by construction and no rounding rule is needed for it. Boundaries fall
on game-date edges, never inside a date. The held-out range is declared, and its
per-status direct-outcome counts checked under §2, **before** any outcome in it
is read.

**Inherited, not discovered — and this was checked rather than assumed.**
`data-engineer` asked whether this rule merely reproduces v1's realized split,
which only the author could settle because v1's date list lives in a local-only
artifact. It does. v1 ran over 25 distinct game dates; its 12th is `2025-12-21`
and its 18th is `2025-12-28`, so `floor(0.50 · 25) = 12` and
`floor(0.25 · 25) = 6` recover v1's boundaries **exactly**: development
`2025-12-08..2025-12-21`, selection `2025-12-22..2025-12-28`, holdout
`2025-12-29..2026-01-04`.

So §4 carries the same contamination as §5: it is the split under which the
author has already seen v1's answers, expressed as a general rule rather than
rediscovered. It is stated here because a rule that happens to reproduce the
split you already unblinded is exactly the thing a reader must be able to
discount, and no reader with only `origin` could have found it — the check needs
`injury_status_conversion_v1_rows.json`, which was never pushed.

The rule is retained anyway: a 50/25/25 chronological split is conventional and
the alternative is picking different proportions *because* these ones are
contaminated, which is a worse reason. On the corrected cohort's 26 game dates
the same rule gives 13/6/7 rather than 12/6/7, so the boundary moves by one date.

*(Note also that the ~4.5× widening multiplier in §2 inherits v1's 32% **row**
share, while this section specifies a **date** rule. v1 shows the two differ —
its holdout was 7 of 25 dates, 28%, but 32% of rows, because holdout dates were
denser. Once a widened cohort exists the multiplier should be derived from this
rule rather than from v1's realized row share.)*

---

## 5. Candidates

All use a Jeffreys estimate, `(plays + 0.5) / (observations + 1)`, which keeps a
zero-play cell off exactly 0 without pretending to knowledge.

| Candidate | Groups | Fitting eligibility |
|---|---|---|
| `global_jeffreys` | one rate for all statuses | always |
| `three_band_jeffreys` | `out`+`doubtful` / `questionable` / `probable`+`available` | always |
| `five_status_jeffreys` | one rate per status | ≥20 development observations for **every** status |

**Fitting eligibility is not activation.** A candidate can clear the ≥20
development threshold and still be unable to activate under §2 and §8. Passing it
is not a green light and must not be reported as one.

**Inherited, not discovered** — see the contamination disclosure. The three-band
grouping comes from v1's selection on data overlapping this cohort by at most
99.18%, with no computable lower bound.

---

## 6. Selection rule

- **Primary metric:** Brier score on the selection partition.
- **Order:** `global_jeffreys` → `three_band_jeffreys` → `five_status_jeffreys`.
- **Rule:** advance to a more complex *eligible* candidate only if its selection
  Brier score is at least **0.005** lower than the incumbent. Ties keep the
  simpler candidate.
- **Final fit:** refit the selected structure on development + selection, with
  no change to groups, priors, thresholds or metrics.

---

## 7. Held-out evaluation

Run **once**.

- **Primary metric: calibration**, per the Model gate — a binned calibration
  table with one row per distinct emitted probability, giving predicted mean,
  observed play rate, count, plays, and a Wilson 95% interval. Accuracy alone is
  not reported as a headline and is not sufficient.
- Brier score; log loss; calibration-in-the-large.
- Paired player-game bootstrap of the Brier difference against the
  final-training `global_jeffreys` baseline: **5,000 resamples, seed 250119**,
  2.5%/97.5% interval. Resampling is by player-game, and the interval is
  therefore **not** valid against within-player or within-game correlation; that
  limitation is reported beside the number rather than fixed by asserting
  independence.
- A descriptive per-status table — count, plays, observed rate, Wilson 95% —
  reported even where statuses share one pooled prediction, and explicitly **not**
  an override of the pooled model.

### Sensitivity, all pre-declared

- **Unresolved identity:** report all-play and all-non-play status-level bounds.
- **Missing participation row:** same, reported as its own class.
- **Explicit unknown outcome:** same, reported as its own class.
- None of these enter fitting or the primary evaluation.

### Lead-time bands — defined here, prospectively

v1 requested lead-time stratification without defining boundaries and had to
record it as unevaluated. Defined now, before data:

**≤60, 61–180, 181–540, >540 minutes** before tip-off.

Reported only where a band holds at least 10 eligible held-out observations;
otherwise counts alone. Given §3, the `>540` band is expected to be empty on any
joinable data resembling the current cohort, and an empty band is reported as
empty rather than merged away.

---

## 8. Activation rule

**Runtime activation defaults to veto.** Every condition must hold:

1. the selected model is status-conditioned rather than global;
2. the upper endpoint of the paired-bootstrap 95% interval for the held-out
   Brier difference against the global baseline is below zero;
3. absolute held-out calibration-in-the-large error is at most 0.10;
4. every emitted held-out calibration bin holds at least 20 observations;
5. every emitted probability lies inside its bin's Wilson 95% interval;
6. the held-out data holds at least 30 direct outcomes for **every** one of the
   five statuses;
7. no monotonic reversal across the pooled unlikely / uncertain / likely bands;
8. the cohort fingerprint and every exclusion count reproduce exactly.

**Condition 8 is stronger than it looks, and `data-engineer` had to point it
out.** `sha256_sorted_joined_stable_records` already hashes each row's status
**and** its outcome together, so the full status x outcome contingency of the
committed cohort is *cryptographically committed* in the manifest at this head.
That is not a leak — it is a whole-set commitment and preimage resistance holds —
but it means a future fit's contingency can be checked against a fingerprint
published before anyone unblinded anything. For a widened cohort the same
property should be preserved deliberately rather than inherited by accident.

**On failure:** publish the offline evidence and the veto. Add no runtime
persistence, no migration, no API, no UI, and no availability-model wiring.

Condition 6 is the one the current cohort fails on arithmetic. Condition 7 is
worth flagging: v1's held-out `probable` (0.9412) and `available` (0.7971) rates
**reversed**, so a five-status model would have inverted on this data, which is a
further reason the pooled bands are not a discovery.

---

## 9. Planned outputs

- a fitted-evidence artifact under `backend/tests/model_evidence/`;
- `docs/models/injury-status-conversion.md` — the model card, including a
  mandatory *what this model cannot see* section;
- tests pinning the evidence contract offline;
- an appended `docs/handoff.md` entry and an accurate `docs/backlog.md` status.

No harness is written under this freeze. Building one against a cohort proved
inadmissible in §2 produces code whose every constant dies when the cohort
widens.

---

## 10. Stopping rule

The held-out evaluation runs **once**.

**When this freeze binds: at the earlier of (a) merge to `main`, and (b) the
first row of the cohort it will be fitted against being collected.** Before that
point it is a draft under review, and the corrections listed in the change log
below were made in that window.

**Condition (b) is the one that makes this a rule rather than this instance's
rationalisation.** Both reviewers, independently, pointed out that an earlier
draft bound only on merge and justified it with a fact specific to today — that
the widened cohort does not exist at merge time. Merge time is not controlled:
widening is an unscheduled owner decision with no recorded ordering against this
branch, so a PR held open across the collection window would still have "bound on
merge" while no longer being prospective. §1 already says the property is gone
once the cohort exists; condition (b) makes §10 agree with it, and it is
falsifiable from `scope` and the merge timestamp.

Binding at that point preserves the guarantee the freeze exists for, because
between two moments that are both strictly before the data exists the choice is
immaterial. Claiming the unreviewed first draft was already immutable would
assert a rigour the review process itself contradicts, and would have forced a v3
for a wrong citation — twice, as it turned out, since a second mis-citation was
found in the round after that argument was written.

**Every pre-merge change was reviewer-driven, and none was driven by an outcome
of the fitting cohort.** The delta is tabulated below so it can be checked. **The
table is a convenience, not the audit trail** — it lives inside the document it
audits and could be amended by the same edit it records. The immutable record is
`git log` on the pushed branch.

After binding, any change to this protocol creates **v3** and leaves this freeze
and its result intact. A post-unblind change is recorded beside the result and
may never be presented as pre-registered.

---

## What this freeze cannot do

- It cannot make an inadmissible cohort admissible. §2 is a gate, not a
  formality, and the cohort that exists today fails it.
- It cannot establish an unblinded selection step. See the contamination
  disclosure.
- **It cannot prove the author did not consult the v1 rows before drafting.**
  That artifact is reachable in the author's clone, the author has now certainly
  seen its contingency, and no reader can verify conduct. The document is written
  to be sound whether or not it was consulted: the structure it carries forward is
  disclosed as inherited, and the cohort it will be fitted against does not exist.
- **It cannot be independently audited on its v1 claims by anyone without this
  clone.** `3285e647` lives on a local-only branch that was never pushed, so every
  v1 figure cited here — the ≤99.18% bound, the exclusion-by-status split, the
  held-out `doubtful` count of 4 — is uncheckable from `origin`.
- It cannot bind a cohort that does not exist yet to a fingerprint. §3 records
  what was visible at freeze time; the eventual fit records its own cohort
  identity and must state plainly that it is a different cohort.
- It cannot see whether the reporting regime is stable. A status vocabulary or
  team-behaviour change invalidates every rate a future fit produces without
  changing one line of code, and nothing in this protocol would detect it.
- It cannot make a status conversion rate into `p(play)`. Conversion is one
  conditional input; the availability model is a separate deliverable with its
  own gate, and a status rate must never be shipped as if it were per-game
  availability.

## Change log

| Version | Date | Change |
|---|---|---|
| 1 | 2026-08-19 | Initial freeze, against the cohort later invalidated by PR #37. Preserved locally at `3285e647`, never pushed. |
| 2 | 2026-08-21 | Re-frozen after the corrected cohort (PR #39). Adds the pre-unblind admissibility gate, a partition-agnostic disclosure requirement on the cohort manifest, defined lead-time bands, an LF-normalised manifest digest, and a mandatory contamination disclosure. Records that the committed cohort fails activation on arithmetic. No model fitted. |

### Pre-merge review delta

Recorded so the edit window between the first freeze commit and binding is
auditable rather than asserted. Independent `data-engineer` and `code-review`
passes at `8f87fe8` and again at `6a4d209` produced these. **`git log` on the
pushed branch is the authoritative record; this table can go stale and is a
convenience.** It was itself incomplete after round 2 — four changes were missing
— which `data-engineer` caught.

| Change | Round | Driver |
|---|---|---|
| §2 admissibility unit moved from canonical observations to **direct outcomes**, matching §8 condition 6 | 1 | both reviewers, independently — the pre-check was looser than the veto it pre-empts |
| §2 manifest requirement replaced with a partition-agnostic by-date/by-status disclosure | 1 | `data-engineer`; the original baked a `quant` split into an ingest artifact |
| §4 split denominator fixed to ordered distinct game dates with explicit `floor` rules and holdout-as-remainder | 1 | `code-review`; the draft used two denominators and no rounding rule, the same defect §7 faults v1 for |
| Contamination disclosure now names the reachable v1 row-level artifact, records that the author has seen the v1 contingency, and replaces "roughly 99%" with the **≤99.18%** upper bound and an explicit absence of any lower bound | 1 | `code-review` found the omission; `data-engineer` supplied the bound and withdrew a claim that it was computable exactly |
| §1 prospectivity claim narrowed from "could not have been consulted" to the cohort that will be fitted | 1 | `code-review` |
| §3 PR #30 citation moved from the manifest field to `docs/handoff.md:7543`/`:8080` | 1 | both reviewers, independently |
| §3 relabels `joined_player_games`, which is not by construction a direct-outcome count | 1 | `data-engineer` |
| §3 records that the 1,650-minute correction had **already been made** by `data-engineer`, and that two committed documents assert the exclusion class this freeze declines to rely on | 1 | author, on re-reading; graded up from both reviewers' milder findings |
| §3 notes the joined fingerprint quoted beside the stale canonical one is **not** stale, scoping the claim | 1 | author, while fixing the above |
| §8 condition 8 records that the joined fingerprint already commits the status x outcome contingency | 1 | `data-engineer` |
| §2 adds v1's actual held-out `doubtful` count of **4** as empirical confirmation | 1 | author. **Taken from the unblinded v1 artifact during the review window** — it is a denominator, a count of rows rather than an outcome value, so it does not breach the input/outcome line this document draws; listed and labelled rather than omitted |
| "What this freeze cannot do" gains two bullets: conduct is unfalsifiable, and v1-derived figures are unauditable without this clone | 1 | author, prompted by `code-review`'s High finding |
| §10 binding clause, and change-log row 2 reworded | 1 | author |
| §2 rationale re-cited from **ADR-006 to ADR-008**, in four places | 2 | `code-review`; ADR-006 is adapter-versus-upstream isolation and says nothing about this. Adopted a reviewer's rationale without re-deriving the citation — same class as the PR #30 mis-citation one round earlier |
| §2 exclusion list corrected: `explicit_unknown` is an outcome **value**, not an absence predicate, and is not a `continue` branch at all; replaced with `without_nba_anchor` | 2 | `code-review` |
| §2 granularity invariant replaced with a **closed-set allow-list**, after both reviewers showed the granularity rule was necessary but not sufficient and mis-sorted its own first two applications | 2 | `code-review` on the discriminator, `data-engineer` on cross-manifest differencing and the closed-set formulation |
| §4 records that the split rule **exactly reproduces v1's realized boundaries**, so it is inherited rather than fresh; plus the row-share vs date-share note on the multiplier | 2 | `data-engineer` asked the question; author computed the answer from v1's row artifact |
| §10 binding condition extended to *the earlier of merge and the first row of the fitting cohort existing*, and the delta table demoted to a convenience beneath `git log` | 2 | both reviewers, independently |
| §5 stale restatement of "99%-overlapping data" corrected to the ≤99.18% bound | 2 | `code-review` |
