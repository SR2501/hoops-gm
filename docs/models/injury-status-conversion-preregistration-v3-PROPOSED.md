# Injury-status conversion — preregistration v3

**Status: `Proposed`.** Not accepted, not binding, not in force. v2 remains the
governing protocol until the owner binds this document. It is written by `quant`
— the agent this protocol grades — and for that reason `quant` does not approve
it. The separation is the same one `bridge` has from `safety` on the write path,
and it is not waived by the proposer being confident.

**Supersedes:** `docs/models/injury-status-conversion-preregistration.md` (v2,
freeze id `injury-status-conversion-v2-20260821T145900Z`), if and only if bound.

**Author:** `quant`. **Drafted:** 2026-08-23, pre-unblind.
**Decision required from:** owner. **Recommendation:** adopt.

---

## 1. Why this is a v3 and not an amendment to v2

Because v2's freeze had already bound when the need was found. v2 §10 binds the
freeze "at the earlier of (a) merge to `main`, and (b) the first row of the
cohort it will be fitted against being collected."

| | moment | source |
|---|---|---|
| (a) merge to `main` | **2026-08-21T16:03:03Z** | commit `b64fd96`, the merge of `docs/models/injury-status-conversion-preregistration.md` |
| (b) first cohort row collected | **2026-08-22T00:25:43Z** | `source_capture_summary."nba_injury_report/InjuryReportPdf".first_fetched_at` |

(a) is earlier by **8h 23m**. Both have passed. Every change below is therefore
post-binding by construction, and v2 §10 is explicit about what that means: "any
change to this protocol creates **v3** and leaves this freeze and its result
intact."

Falsify both in two commands, from a clean checkout:

```
git log -1 --format=%cI b64fd96 -- docs/models/injury-status-conversion-preregistration.md
python -c "import json;print(json.load(open('docs/adapters/nba-injury-report-cohort-2025-10-21--2026-04-12.json',encoding='utf-8'))['source_capture_summary']['nba_injury_report/InjuryReportPdf']['first_fetched_at'])"
```

(The earliest capture of *any* source in that manifest is `CommonAllPlayers` at
2026-08-22T00:24:01Z, 1m42s before the first injury-report row. Reading (b) that
way moves the margin to 8h 21m and changes nothing.)

**What this costs, stated plainly.** v2 was prospective with respect to both the
cohort and the outcomes. v3 is prospective only with respect to the outcomes:
the cohort exists, and its predictor-side composition has been read — by the
author of this document, in the review of PR #92. §5 below is the argument that
this is sufficient. It is a weaker guarantee than v2 carried, and anyone citing
v3 must cite it as the weaker one. v3 may never be presented as v2's freeze.

---

## 2. What does not change, and must not be reopened

**§7's lead-time bands stay exactly as frozen: `<=60`, `61-180`, `181-540`,
`>540`.** Together with §7's existing rules — report only where a band holds at
least 10 eligible held-out observations, otherwise counts alone; an empty band is
reported as empty rather than merged away.

**§4's 50/25/25 chronological split stays exactly as frozen.**

This is a deliberate refusal, not an oversight. The review of PR #92 raised
collapsing the bands on two grounds — `doubtful` sparsity (held-out `<=60` holds
0 `doubtful`, 14 `questionable`, 4 `probable`) and era confounding (`<=60` is
7.2% of legacy rows against 39.7% of short-lead rows). **The condition was
withdrawn by its author.** Two reasons, both of which should survive this
document:

1. **Lead time is not a fitted covariate.** v2 §5's three candidates —
   `global_jeffreys`, `three_band_jeffreys`, `five_status_jeffreys` — are
   status-only. §6 selects among them on selection-partition Brier. §8's
   activation conditions reference no band. The bands are a *descriptive held-out
   reporting stratification* and feed nothing that sparsity can corrupt. §7's
   ≥10 rule already handles every case observed, at zero cost.
2. **Re-drawing them now would be re-drawing them after seeing the table.** The
   only thing a prospective boundary declaration buys is the guarantee that the
   boundaries were not chosen to suit the data. Moving them post-hoc spends that
   guarantee to buy nothing.

**v3 is not a licence to reopen §4 or §7's band definitions.** Anything below
that appears to touch them does not.

---

## 3. Change A — register report era as a §7 sensitivity

**Why.** v2 §7's "Sensitivity, all pre-declared" list has exactly three entries:
unresolved identity, missing participation row, explicit unknown outcome. **Era
is not among them.** The remedy the project adopted after the era analysis was
"declare the composition and register era as a sensitivity, do not move the
50/25/25 split." The split half was honoured. The registration half was never
written into the protocol.

Because §7's list is closed and pre-declared, the omission is not neutral:
reporting an era-split held-out result after the unblind would be an **undeclared
analysis**, and not reporting one discards the only handle on a confound
measured at 5.5× in band composition and 68.2%/0% in partition composition.

**Text, to be added to v2 §7's sensitivity list:**

> **Sensitivity — report era.** The held-out result is additionally reported
> split by `report_era`, alongside the pooled figure. Composition, declared here
> from counts alone: development 4,166 legacy / 1,946 short-lead (68.2% legacy);
> selection 0 / 3,546; held-out 0 / 3,940. The held-out partition is therefore
> 100% short-lead and the split cannot be computed within it; the sensitivity is
> discharged by refitting on the legacy-only and short-lead-only development
> subsets and reporting both against the same held-out partition. Where either
> subset holds fewer than 20 development observations for a status, that status
> is reported as counts alone. The pooled figure remains primary; the split is
> diagnostic and does not enter §8.

---

## 4. Change B — add §8 condition 9, calibration on the informative statuses

**Why.** v2 §8's conditions 2 and 3 are close to unfailable against this
holdout's composition. This is arithmetic on published denominators, and it has
been true since v2 froze.

Held-out direct outcomes: `out` 2,963 (75.2%), `available` 467 (11.9%),
`questionable` 335, `probable` 92, `doubtful` 83. Informative statuses
(`questionable` + `probable` + `doubtful`) = **510 = 12.94%**.

- **Condition 3** (|calibration-in-the-large error| ≤ 0.10): a model exactly
  right on `out` and `available` — 87.06% of the holdout — and wrong by δ on
  *every* informative row yields a CITL error of 0.1294·δ. Breaching 0.10
  requires **δ > 0.773**. The model must be wrong by 77 percentage points on
  every `questionable`, `probable` and `doubtful` row in the holdout to fail.
  CITL is a signed mean, so errors across statuses may additionally cancel,
  making the real threshold looser still.
- **Condition 2** (paired-bootstrap Brier beat over `global_jeffreys`): the
  baseline predicts one rate for all 3,940 rows. Any status-aware model that
  places `out` near zero captures 75.2% of the holdout at near-zero Brier. The
  improvement is delivered almost entirely by separating `out` from the pool,
  and swamps whatever happens on the 12.9% the model is actually asked about.

As frozen, §8 can be cleared by a model whose pooled reliability diagram is
excellent and whose `questionable` cell is worthless. In a project whose stated
rule is that **calibration beats accuracy for `p(play)`**, that is the exact
failure the gate exists to prevent.

**Text, to be added to v2 §8:**

> **Condition 9.** Calibration-in-the-large and the binned calibration table of
> §7 are additionally computed over the held-out rows carrying status in
> {`questionable`, `probable`, `doubtful`} only (n = 510 direct outcomes,
> declared here). Activation requires |CITL error| ≤ 0.10 **on this restricted
> set as well as on the pooled set**. Where the restricted set holds fewer than
> 30 direct outcomes for a status, that status is reported as counts alone and
> the restricted CITL is computed over the remainder. The restricted figure is
> the operative one for any downstream availability consumer; the pooled figure
> is reported for comparability and is not sufficient on its own.

---

## 5. Why this is legal pre-unblind

The property that makes a post-binding change defensible is that it could not
have been chosen to favour a result, because no result has been seen.

- **Every motivating number above is a denominator or a predictor-side count** —
  held-out counts by status, by lead-time band, by report era, by stated reason
  head. Each is either already published in
  `docs/adapters/nba-injury-report-cohort-admissibility-2025-26.json`, or was
  driven by the author from `injury_report_entries` and `nba_games` alone.
- **No participation outcome was read.** The author's reproduction of the cohort
  (below) queried only those two tables and never opened `player_participation`.
  **The author does not know the conversion rate of any status.**
- **Both changes are restrictive-only.** Change A adds a required report. Change
  B adds a required condition to a gate that already defaults to veto. Neither
  can make activation easier. A *loosening* change at this point would deserve
  scrutiny this document does not supply, and none is proposed.
- **The cohort's predictor side has been read, and that is disclosed.** See §1.
  This is the residual exposure and it is not zero: a reader must take on trust
  that reading composition did not steer the choice of amendment. The mitigation
  is that both amendments are restrictive, so steering them toward a favourable
  outcome is not a coherent action.

**Independent reproduction, supporting the claim that only the predictor side was
touched.** The author reimplemented `select_canonical_pregame_observations` as a
standalone read-only query against `cohort-merged-2025-26.db` (SHA-256 verified
against the merge receipt) and obtained 13,789 canonical observations with
`status_counts` and `stated_reason_categories` **identical to the committed
artefact in every cell**. This is a third derivation path, independent of both
`cohort_evidence.py` and `cohort_admissibility.py`. It confirms the cohort's
predictor side. It says nothing about the outcome side, which cannot be checked
before the unblind and is not claimed here.

---

## 6. Sample adequacy — recorded so it is not later misremembered

**Five status-only rates is the right size for this cohort, and always was.**
The review of PR #92 remarked that the data would not support a status ×
lead-time-band × era model. That was true about the data and **irrelevant as a
criticism, because no such model was ever proposed.** It should not be repeated
as "the reviewer found the data thin."

Driven counts supporting adequacy:

- **§5 eligibility for `five_status_jeffreys` (≥20 development observations per
  status):** development = `out` 4,754 / `doubtful` **75** / `questionable` 578 /
  `probable` 228 / `available` 586. The binding minimum is 75. Clear.
- **§8 condition 6 (≥30 held-out direct outcomes per status):** `doubtful` binds
  at **83**. Clear.

**One correction to how that floor should be read.** 18.6% of `doubtful`
observations (41 of 221 season-wide) carry the stated reason `G League` — a
Two-Way player who may be recalled. That is genuine uncertainty, but it is a
**roster mechanic, not a health event**, and its conversion rate has no reason to
resemble injury-`doubtful`. Restricting to health reasons:

> **`doubtful`'s held-out floor is 83 as published, but ~74 on health reasons,
> against a ≥30 requirement — 2.5× headroom, not 2.8×.**

Across the whole cohort, ~27.7% of rows are not health events (G League 3,385,
Not With Team 247, suspensions 56, Personal 82, Trade Pending 37, Coach's
Decision 15, and the balance). **The recommendation is to cut none of them** —
excluding would change the fingerprint v2 §8 condition 8 requires to reproduce,
and the downstream question is "will this player play tonight given today's
report", not why. The requirement is disclosure, not exclusion: the model card
must publish the health/non-health split by status, so that "10,278 `out`
observations" is never read as 10,278 injury observations, and so the 41
G-League-`doubtful` rows are visible to anyone reading the `doubtful` rate.

**Recommended for publication by the ingestion lane while PR #92 is open:**
`reason_category × status`, as a cohort denominator. It is computed pre-join and
is outcome-free — the reason categories sum to exactly 13,789, the canonical
total, which is itself the proof that they are not outcome-conditioned. Costs no
unblind, and retires the most load-bearing reasoned claim in this section.

---

## 7. If this is declined

The fit proceeds under v2. That is worse, not fatal, and the owner should see the
real cost rather than a threat:

- **The era split can still be reported**, as a clearly-labelled post-hoc
  diagnostic carrying no pre-registered status. It will be correct and it will be
  less persuasive, because a reader cannot distinguish it from an analysis chosen
  after seeing the result.
- **The restricted calibration can still be computed and reported**, likewise
  post-hoc. The loss is sharper here: it will not *gate* activation. A model that
  is badly calibrated on `questionable` can pass v2 §8 and be activated, with the
  restricted table published beside it saying so. Whether anyone stops the
  activation then is a judgement call made under pressure, which is the situation
  a pre-registered gate exists to avoid.
- **Nothing about PR #92 changes.** v3 must bind before the unblind, not before
  the merge. Declining costs no schedule.

The honest summary of "no" is: the analyses still happen, but the second one
stops being a brake and becomes a footnote.

---

## 8. What this document cannot do

- It cannot restore v2's prospectivity with respect to the cohort. §1.
- It cannot verify its own author's conduct. The author read the cohort's
  predictor-side composition before drafting and says so; no reader can check
  that this did not steer the drafting. The mitigation is structural, not
  personal: both changes are restrictive-only.
- It cannot make the outcome side of the participation join independently
  verified. That remains true of v2 and is unverifiable before the unblind.
- It cannot be adopted by its author. `Proposed` is the only status `quant` may
  write on it.
