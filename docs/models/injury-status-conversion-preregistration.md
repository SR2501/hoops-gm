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
At this commit the row-level outcomes this protocol will be evaluated against are
absent from the repository and from every checkout the coordinator searched —
nine worktrees plus the owner's main checkout, where the one real database
(`hoops_gm.db`, 3.97 MB) holds **0 rows** in both `player_participation` and
`player_game_logs`. A freeze committed here is prospective in a way no later
freeze can be, because the data it commits to could not have been consulted.

Once that database is populated, this window shuts permanently.

---

## Contamination disclosure — read this before treating the freeze as a blind

**This is a replication protocol, not a clean blind.** Stating that plainly is
the condition on which the rest of the document is worth anything.

I have read the unblinded held-out results of the v1 study (preserved locally at
`3285e647`, never pushed). I know its selected structure, its three fitted band
probabilities, its held-out Brier scores against the global baseline, its
calibration table, and the reason its five-status candidate was ineligible. The
v1 cohort and the corrected cohort overlap by roughly 99% of rows — 1,934 versus
1,948 canonical observations, 1,906 versus 1,918 joined outcomes.

So the candidate set and grouping below are **inherited knowingly** from a study
whose answers I have seen on almost the same data. Anyone reading a future result
against this freeze must discount the selection step accordingly: the
three-band structure is not an independent rediscovery, and a report that it
"was selected again" is close to uninformative.

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
range, **every one of the five statuses carries at least 30 observations.**

Per-status counts are *inputs*, not outcomes. They are visible in a cohort
manifest without unblinding a single participation result. So this gate is
checkable in advance, and it must be checked in advance.

**Requirement on the cohort manifest, addressed to `data-engineer`:** the
generator must publish `status_counts` **broken down by the declared partition**
(development / selection / held-out), not only whole-cohort. The current
generator publishes whole-cohort status counts only, which makes this gate
checkable exactly once — after the split is drawn by hand.

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

A chronological holdout is a subset of the cohort, so the held-out `doubtful`
count is at most 21. **21 < 30 unconditionally.** No split, no seed, and no
outcome can change it. `probable` at 59 would require the holdout to contain 30
of 59, i.e. more than half the cohort, which no conventional chronological split
produces.

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
| Joined direct outcomes | 1,918 |
| Admissible under §2 | **no** |

**The manifest hash is LF-normalised, and that is a deliberate correction.** The
v1 freeze pinned a field named `manifest_worktree_sha256`, which is
checkout-newline-dependent: the same committed bytes hash differently on a CRLF
checkout (19,261 bytes) than on an LF one (18,799 bytes). That is precisely the
defect class the cohort manifest's own `source_fingerprint_method` records PR #30
having to correct after publication. Verified here: the LF-normalised digest
equals the digest of the raw git blob, byte for byte.

**The canonical fingerprint above is not the value quoted in the PR #39 handoff
entry** (`80b3e563…`). The manifest was regenerated during later remediation
rounds and the prose was not updated. This table was re-derived from the file at
this commit, per the `gates.md` instruction to re-derive any number appearing in
prose at the moment of writing.

**A correction to the warning handed to this lane.** The PR #39 handoff entry
tells `quant` that maximum lead time moved 540 → 1,650 minutes and that "any
lead-time stratification built on the old 9-hour maximum is wrong". That is true
of *canonical* observations and **false of the data this model fits**: the
manifest's `participation_join.joined_lead_time_minutes` maximum is still
**540**. Since the joined set is the canonical set minus exclusions, and its
maximum is 540, the 1,650-minute observation is **excluded from the joined set**
and cannot enter any fit. The joinable lead-time range is unchanged at 15..540
minutes.

Which exclusion class it falls into — one of the 28 unresolved identities or one
of the 2 missing participation rows — **is not determinable from the manifest**,
which publishes only class totals. The handoff attributes the 1,650 value to a
named player never re-listed before tip-off, but attributing him to a specific
exclusion class would be an inference I cannot check here, so this freeze does
not make it. The load-bearing claim is the one the manifest settles: it is not in
the fitting set.

---

## 4. Splits

Chronological, never random. A random split leaks: the same player's status on
consecutive days is not independent, and same-game teammates share one opponent,
one travel leg and one reporting decision.

Proportions of the **admissible** cohort's date range, in order:

| Partition | Share of game dates | Purpose |
|---|---|---|
| Development | first 50% | fit candidates |
| Selection | next 25% | choose structure |
| Final training | development + selection | refit selected structure |
| Held out | final 25% | evaluated **once** |

Boundaries fall on game-date edges, never inside a date. The held-out range is
declared, and its per-status counts checked under §2, **before** any outcome in
it is read.

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
grouping comes from v1's selection on 99%-overlapping data.

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

Any change to this protocol after any outcome from the fitted cohort has been
observed creates **v3** and leaves this freeze and its result intact. A
post-unblind change is recorded beside the result and may never be presented as
pre-registered.

Amending this document in place defeats its only purpose. If it needs changing
before any unblind, the change is a new dated freeze that names this one.

---

## What this freeze cannot do

- It cannot make an inadmissible cohort admissible. §2 is a gate, not a
  formality, and the cohort that exists today fails it.
- It cannot establish an unblinded selection step. See the contamination
  disclosure.
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
| 2 | 2026-08-21 | Re-frozen after the corrected cohort (PR #39). Adds the pre-unblind admissibility gate, the per-partition status-count requirement on the cohort manifest, defined lead-time bands, an LF-normalised manifest digest, and a mandatory contamination disclosure. Records that the committed cohort fails activation on arithmetic. No model fitted. |
