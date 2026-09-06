# Cohort manifest drift — pre-unblind ruling

- **Status:** Proposed (quant ruling). Only the owner accepts.
- **Date:** 2026-09-06
- **Author:** `quant`
- **Refers to:** ADR-019, Amendment 2026-09-06, which makes the fingerprint gate
  differential and explicitly refers the pre-unblind drift-safety question here:
  *"whether that is a verified zero or an absence wearing a zero is `quant`'s
  ruling."* This note is that ruling.
- **Constraint honoured:** the committed manifest was **not** modified and
  nothing was written to `docs/adapters/`. Every regeneration went to a temp
  path and was deleted.

## The question

Regenerating `docs/adapters/nba-injury-report-cohort-2025-10-21--2026-04-12.json`
against today's tree moves 33 changed + 2 removed leaves with no code change.
Three questions were put to me:

1. Does this drift **compromise the blind**?
2. Are the two removed `limitations` (**"UNVERIFIED, NOT ZERO"**) honest — a
   verified zero, or an absence wearing a zero?
3. **Refresh or pin** the committed manifest, and is the differential gate right?

## Method — everything below was executed, not reasoned

All runs: `PYTHONPATH` pinned to the main checkout's `backend/src`; offline
(`--allow-fetch` off); store = `cohort-merged-2025-26.db` in the data root
(`C:\Users\steverones\hoops-gm-data`); repo at `b8fb1916` (HEAD — every commit
since my runs is docs-only; `cohort_evidence.py`, `parsers.py`, and
`backfill.py` are byte-identical); leaf comparison by
`scripts/manifest_leaf_diff.py`. #171 was materialised in a detached worktree at
its head `65f5d5dc`.

A **2×2 control** isolates every cause of drift. Rows = generation CWD (which
determines whether the cascade loader finds the persisted coverage reports);
columns = store state.

| regen CWD ↓ / store → | committed (old store) | today's grown store |
|---|---|---|
| **mismatched CWD** (cascade reads nothing) | *= the committed manifest* | `from_backend_cwd` |
| **correct CWD** (data root; cascade reads reports) | — | `control` |

- **committed → control** (absolute gate, today's store, correct CWD):
  `0 added, 2 removed, 33 changed`. Reproduces the lane's number and the
  architect's exactly.
- **committed → from_backend_cwd** (store grew, CWD held mismatched):
  `26 changed` = **25 `source_capture_summary` + 1 `operator.commands[8]`**;
  cascade stays `null` in both, `limitations` stays 7 in both. **Isolates store
  growth.**
- **from_backend_cwd → control** (same grown store, CWD corrected):
  `8 changed + 2 removed` = the 7 `trusted_entry_cascade.*` + `scope.expected_games`,
  and `limitations[5,6]` removed; `source_capture_summary` **identical**.
  **Isolates the cascade population.** 25 + 8 = the 33.
- **control → treatment(#171)** (same store, same window, edit applied — the
  **differential** gate): `0 added, 0 removed, **1 changed**` =
  `operator.source_fingerprints…/parsers.py`, #171's own fingerprint. Nothing
  else.

Supporting facts, all verified on disk:

- The persisted `…_expected_games.json` (162 B) and `…_coverage.json` (590 947 B)
  are **byte-identical** to the SHA-256s the committed manifest already recorded
  in `operational_artifacts`. The reports **did not change** since commit.
- `…_expected_games.json` = `{expected_count: 1230, ingested_count: 1230,
  missing: [], start: null, end: null}` — a **whole-season** slate.
- `…_coverage.json`: 643 candidates, outcomes `{fetched: 640, error: 3}`,
  `report_date` ∈ [2025-10-21, 2026-04-12]. The 3 non-fetched are transient
  **DNS failures** (`[Errno 11001]`, `status_code = null`) on 2026-01-19 — not
  403/404.
- Cross-check: the manifest's own independent `scope.games_in_scope = 1230`
  (counted from the DB by `games_to_backfill`) **equals** the slate's
  `expected_count = 1230`. Two independent derivations agree.
- Byte-identical between committed and every regeneration:
  `canonical_observations`, `cross_source_reconciliation` (1245 leaves),
  `cross_source_tipoff_reconciliation`, `reason_evidence`, `position_evidence`,
  `participation_join` — **including the withheld outcome marginal**.

## The drift is three independent things, and only the gate conflated them

1. **Store growth — 25 leaves, all `source_capture_summary.*`.** Four live
   sweeps re-captured the same games (`BoxScoreTraditionalV3` 1230 → 4920
   captures; `distinct_content_sha256` moved in lockstep, so each re-capture
   differs). The manifest **already discloses** this section as *"provenance,
   not reproducible values: a fresh live sweep necessarily produces different
   ones."* This is the section doing its job. It is not a cohort number.

2. **Cascade population — 8 leaves + 2 `limitations`.** This is **not** store
   growth. The reports are byte-identical to commit and were present at commit
   (the committed `operational_artifacts` inventories them). The committed
   manifest shows `null` because it was generated from a CWD where the cascade
   loader's **hard-coded, CWD-relative** `data/reports` missed files that
   `operational_artifacts` — which honours the explicit `--report-dir` — found.
   I reproduced this exactly: run from `backend/` with an absolute
   `--report-dir`, and today's code emits `null` cascade + populated
   `operational_artifacts` + 7 `limitations`, i.e. the committed state.

3. **#171's edit — 1 leaf**, its own fingerprint.

## Ruling

### Q1 — Does the drift compromise the blind? **No.**

The blind protects the status→outcome relationship. Its sensitive quantity,
`participation_join.participation_outcome_counts`, is **withheld** in the
committed manifest and in every regeneration (verified byte-identical to the
withhold sentinel). Every moved leaf is either capture provenance (§1) or a
coverage **denominator** (§2). None is outcome-keyed. The cohort-signal and
reconciliation sections did not move at all.

Coverage completeness — "the window is the full 1230-game season and ingest is
complete" — is exactly what a blind analysis is *permitted* to see: you must
know your denominator to design the analysis; you must not see the answer. A
`null → 1230` on `expected_games` and a retracted coverage caveat change what an
analyst sees about **coverage**, not about **outcomes**. The blind is intact.

Boundary condition, stated so it is not assumed away: this holds *because* every
moved leaf is a denominator or provenance. If a future regeneration ever moved
an outcome-side leaf, that would be a different ruling — and the differential
technique (below) is what proves an edit outcome-inert.

### Q2 — Are the removed limitations honest? **Yes — verified zero, not vacuous. With a caveat that matters.**

The zeros that appear are `missing_from_ingest = 0` and the three candidate
failure counts `= 0`.

- `missing_from_ingest = 0` is a **verified** zero. The slate enumerated **1230**
  official games (`expected_count = 1230`, not 0 — so *not* the empty-slate
  vacuity that defeated `enforce_expected_game_coverage` when PRESEASON was
  mislabelled) and found all 1230 ingested. Cross-checked against the manifest's
  independent `games_in_scope = 1230`.
- `candidate_forbidden_403 = 0` / `candidate_not_available_404 = 0` /
  `candidate_quarantined_unscoped = 0` are **verified** zeros against a real,
  non-empty denominator of **643** in-range candidates. No 403 or 404 is hiding
  behind the `error` outcome — the 3 errors are DNS failures with
  `status_code = null`.

So the specific "absence wearing a zero" the referral feared — a `0` produced by
the same emptiness that produced the `null` — is **not** what happened. The
denominators are real.

The stronger finding runs the other way: the **committed manifest's `null` was
itself the dishonest artifact.** Its two `limitations` assert the stages are
null *"because the report was computed against a different date range."* That is
**false** — the report is present, byte-identical, and correctly scoped to this
window. The null was a path-resolution accident. Regenerating to the true
values and dropping the false caveat is not merely honest; it **repairs a
standing misstatement**.

**The caveat, which keeps this from being a clean bill of health.** The
generator reaches the correct `1230 / 0` through an **unguarded** path. Unlike
the `observations` CLI, `build_cohort_evidence` does **not** apply
`_expected_coverage_matches_scope`; it consumes a whole-season slate
(`start = null`) for a windowed request and is correct *only because this window
equals the whole season*. It did not verify that coincidence. One refactor to a
different window and this same code emits `expected_games = 1230,
missing_from_ingest = 0` for four weeks — a genuinely vacuous number. **The zero
is verified today; the code that produces it is not self-verifying.** That must
be fixed (or externally cross-checked) before the manifest is trusted for any
window other than the full season.

### Q3 — Refresh, not pin. Differential gate endorsed, with one pairing rule.

- **Pin is wrong.** The committed manifest is *defective* — internally
  inconsistent (inventories coverage files it reports as absent) and carrying a
  false explanation. Pinning freezes a known-wrong artifact, and ADR-019's own
  Rejected section declined a freeze. A growing store plus this bug makes every
  future fingerprinted edit stop here — the de-facto code freeze ADR-019
  refused.
- **Refresh, conditionally.** A correct regeneration (from the data root) is
  strictly more faithful than what is committed. Before an analyst relies on the
  refreshed manifest, re-verify: (a) `games_in_scope == expected_count` (window
  == slate); (b) the outcome marginal stays withheld (it does); (c) the
  `limitations` text, if any stage is ever genuinely null, states the *true*
  reason.
- **The differential gate is the right repair** and my differential run proves
  it works: it isolates #171 to one leaf. The absolute gate is now permanently
  confounded because the manifest summarises mutable state, so it will keep
  charging environment drift to whichever edit trips the byte test next.

  **Pairing rule the gate must not lose:** the differential answers *"is the
  edit inert?"* It does **not** answer *"is the environment drift safe to
  ship?"* Those are two questions. The differential clears #171; shipping also
  requires clearing the 35-leaf environment drift — which is what this note
  does. So the procedure is **both** diffs: (1) absolute `regen-vs-committed` to
  see the whole drift, quant-certified; (2) differential `with-edit vs
  without-edit` to prove the edit inert. The user's proposal supplies (2); it
  must be paired with (1), never replace it. `manifest_leaf_diff`'s own warning —
  *a leaf agreement is about change, never truth* — is exactly why (2) needs the
  certification in (1) beside it.

  How a fingerprinted file is edited again, without a freeze: run (1); a
  `source_capture_summary`-only drift is disclosed-nonreproducible and needs no
  quant ruling, anything else escalates on its own terms; run (2), require
  `operator.*`-only; commit the with-edit regeneration (updates the fingerprint,
  absorbs the certified drift); attach both diffs.

## Correction to the referred causal story

ADR-019's amendment classes the cascade `null → number` as *environment
description* that populates *"once the store covers the window."* My evidence
says otherwise, and the distinction changes the remedy. The store **already
covered the window at commit time** — the slate and coverage reports are
byte-identical to commit and were inventoried by the committed manifest itself.
The cascade populated on regeneration because the correct CWD lets the loader
**read reports it could always have read**, not because a growing store newly
covered the window. It is a **generation-context defect + a latent generator
bug**, orthogonal to the `source_capture_summary` growth. This is why the answer
is *refresh and fix the generator*, not *accept it as unavoidable environment
noise*.

## What I could not verify

- **Entitlement / authorisation** of any regeneration — ADR-019 already states
  no gate represents it; the differential does not change that.
- **Truth of the frozen cohort numbers.** Leaf agreement is about change, not
  truth; a whole-leaf diff cannot certify `canonical_observations` is *correct*,
  only that it did not move. That certification lives in the earlier reviews,
  not here.
- **The exact historical invocation** that produced the committed manifest. I
  reproduced a CWD that yields its precise state; I did not recover the original
  command line.
- Whether a **future** widened/playoff window would keep `games_in_scope ==
  expected_count`. It holds now; the generator does not enforce it.

## Actions to file (not blockers for #171)

1. Port `_expected_coverage_matches_scope` into `build_cohort_evidence`: refuse
   or null a scope-mismatched slate the way the `observations` CLI does.
2. Unify report-dir resolution — the cascade loader must read the **same**
   directory `operational_artifacts` reports on (honour `--report-dir` in both),
   so "inventoried but reported absent" can never recur.
3. Consider a content-addressed store snapshot pinned per cohort (the amendment
   names this): it removes the drift at its source and would let the absolute
   gate be correct again.
4. Surface transient `error` candidates as their own cascade field; today the 3
   DNS failures are visible only as `attempted − fetched`.

## Verdict on #171

**#171 may proceed on the strength of its one permitted leaf.** Holding the
store fixed, its edit moves exactly `operator.source_fingerprints…/parsers.py`
and nothing else — no cohort, coverage, provenance, or outcome leaf. The 35-leaf
environment drift that trips the absolute gate is **not** #171's (it appears
identically with no edit) and is certified honest here: 25 disclosed-
nonreproducible provenance leaves, 8 correct cascade populations, 2 correct
limitation retractions. #171's commit must carry the **data-root** regeneration
(never a `backend/` run, which would empty `operational_artifacts` and re-null
the cascade) plus both leaf diffs.
