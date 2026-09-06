# ADR-019: The cohort fingerprint boundary is the derivation closure, and the check claims bytes, not entitlement

- **Status:** Proposed
- **Date:** 2026-08-27
- **Deciders:** owner (accepts), architect (proposes)
- **Supersedes:** nothing. **Amends:** nothing. Bounds ADR-006 without revising
  it: the Adapter gate's decision is unchanged, and this states one thing it
  cannot see.

## Context

`docs/adapters/nba-injury-report-cohort-2025-10-21--2026-04-12.json` pins six
source files by whole-file SHA-256. Editing any of them turns
`test_cohort_evidence.py` red, which has left `record-refresh-lineage-relabel` a
latent defect on `main` rather than a fix (register `c283`, `c288`, `c295`).

The complaint was that `db/lineage.py` is a general-purpose primitive with
nothing injury-specific about it. **Driven tonight, that complaint is wrong and
the real defect is the opposite one.** An AST walk of the generator's transitive
`hoops_gm` import closure returns **34 files. Three are fingerprinted.**
`db/lineage.py` is one of the three and is genuinely reached through the import
graph. The thirty-one that are not include `db/models/availability.py`,
`db/models/stats.py`, `db/models/identity.py` and `ingest/rawstore.py` — the ORM
and store code every cohort row is read through. **The set is over-inclusive
nowhere and under-inclusive by thirty-one files**, and `_source_fingerprints`
refuses a missing *declared* path while nothing checks the declaration against
the derivation.

## Decision

**1. Membership is the derivation closure plus the store producers, and the two
rationales are named separately rather than merged.** `derivation` = files the
generator imports, transitively, within `hoops_gm`. `provenance` = files that
produced the persisted stores and that the generator does not import:
`ingest/backfill.py` and `ingest/injury_report/merge_stores.py` today.
**Nothing is dropped.** `db/lineage.py` stays, under `derivation`. Narrowing a
provenance claim to make an edit convenient is the failure this module's own
docstring already names: a claim narrower than the truth that looks complete.

**2. The declared set is checked against the import graph, not asserted.** A test
in `backend/tests/` AST-walks the closure and fails when a closure file is
absent from the declared set. It lives outside `backend/src/`, so the check
itself costs no regeneration.

**3. A fingerprinted file may be edited, in the same commit that regenerates the
manifest, with `scripts/manifest_leaf_diff.py` output attached.** If the only
moved leaves are under `operator.source_fingerprints` and `operator.commands`,
no cohort number moved and the edit stands. **Any other moved leaf stops for
`quant`, pre-unblind.**

> **Read the 2026-09-06 amendment below before acting on this item.** The
> comparison stated here is *absolute*: it measures a regeneration against the
> committed manifest, and so charges an edit for environment drift it did not
> cause. The amendment makes it **differential**. On 2026-09-06 a lane entered at
> this paragraph, stopped where it says to stop, discarded a correct
> regeneration, and reported a gap that did not exist.
>
> ADR-013's amendment of 2026-08-21 states the better practice — an ADR asserts
> the present contract, so it is corrected in place rather than left contradicted
> by a block below, because a reader entering at the earlier block builds the
> wrong thing. This pointer is deliberately weaker than that. Both this ADR and
> the amendment are `Proposed`, so rewriting item 3 would present an unaccepted
> change as the decision. **When the owner accepts the amendment, correct item 3
> in place and delete this note.**

**4. Regeneration is offline and takes one command.** Driven on 2026-08-27
against the unmodified tree: exit 0, no network, **1664 leaves, 0 added, 0
removed, 1 changed**, and the one change is `operator.commands[8]` echoing the
`--out` path. The belief that it needs live `stats.nba.com` sweeps is false;
`--allow-fetch` is off by default and the stores are already on disk.

**5. The lane making the edit may run the regeneration.** `data-engineer` still
owns the artefact and reviews it. The leaf diff is what makes another lane's
regeneration reviewable instead of trusted, which is the answer to `c288`'s
boundary objection.

## What the check is entitled to claim

`test_every_recorded_source_fingerprint_matches_the_file_today` establishes
**that the recorded bytes equal today's bytes**. It cannot establish that the run
which produced them was authorised, because the manifest and the tree are
produced together: **it is green for whoever ran it.** Green means
self-consistent, never entitled.

**Entitlement has no representation in any gate in this repository.** It is
carried by the leaf diff and by review, both human artefacts. That limitation is
written into `backend/tests/test_cohort_evidence.py` — the class docstring and
the assertion message — so it reaches a reader of the check rather than only a
reader of this ADR.

## Rejected

**Dropping `db/lineage.py`.** It is in the closure. The experiment cited for
dropping it showed that one change to it moved no number; that is not evidence
that no change could.

**Freezing the six files.** That is the status quo, and it converts a latent
provenance defect into a permanent one.

**Adding an authorisation field to the manifest.** A field the same run writes
attests to nothing. Entitlement cannot be self-certified, which is the same
reason `bridge` does not approve `safety`'s guardrails.

## What would flip this

A leaf diff showing a cohort number moving under an edit believed inert — then
the closure is wider than the import graph, and membership must be derived from
execution rather than from imports. Or the closure test proving too noisy to
maintain, in which case the set returns to a hand-list and this ADR's claim about
completeness is withdrawn rather than quietly weakened.

## Consequences

`record-refresh-lineage-relabel` is unblocked and has a procedure. The declared
set is currently three of thirty-four closure files, so **every manifest
published before the set is widened carries a provenance claim narrower than its
derivation** — that is true today, it is not repaired by this ADR, and it is
filed as `cohort-fingerprint-closure-check`.

## Amendments

### 2026-08-28 — the closure count is now recountable, and was a number nobody could check

**Status:** Proposed. Written by `architect`, the author of the body above; only
the project owner accepts.

**The decision does not change.** What changes is the standing of the evidence
under it.

This ADR rests on a measurement — *34 files in the closure, 3 fingerprinted* —
that was taken **once, by hand, in a throwaway script that was then deleted**.
Every reader since has had to believe it. That is precisely the shape this
repository has a rule against: `docs/backlog.md`'s header is recounted by
`backlog_graph.py`, `docs/handoff.md`'s terminator by
`check_doc_terminators.py`, and this ADR's central number by nothing. **A
derived number with no tool that re-derives it from the thing it describes is a
claim, not a measurement**, and it decays silently as the generator's imports
move.

`scripts/fingerprint_closure.py` is that tool, with
`backend/tests/test_fingerprint_closure.py` driving its resolution rules against
a synthetic package. It reproduces both figures above and prints the 31
unfingerprinted files by name.

**It reports and exits 0; it does not gate.** A check that is red until the set
is widened is one everyone learns to route around, and the widening is
`cohort-fingerprint-closure-check`'s job. The domain limit is printed in the
tool's own **output**, not only its docstring: this counts imports, so **34 is a
floor**, and a file absent from it has not been shown to be irrelevant — only
not to be imported.

**Two things the tool found that the body above did not know.** The superseded
four-week manifest records **4** fingerprints against **6** declared, missing
`db/lineage.py` and `merge_stores.py` — the declared-versus-recorded divergence
`_source_fingerprints` describes in prose, now visible from a command. That is
not a defect: a frozen manifest describes the code that produced *it*. And the
tool's own refusal path was broken when first driven — `_relative` raised
`ValueError` from `pathlib` instead of printing the refusal, so **the error
message was the thing that failed.** Found by the test that asserts the refusal
rather than trusting it.

**What would flip this amendment.** The tool proving unmaintainable against
`hoops_gm`'s real import graph, or a closure file being shown to matter that no
import reaches — either sends membership back to a hand-list, and the body's
completeness claim is then withdrawn rather than quietly weakened.


### Amendment, 2026-09-06: the gate compares the wrong two things, and section 4 has expired

- **Status:** Proposed
- **Proposed by:** architect. Only the owner accepts.

**Section 4's measurement no longer holds, and it cannot be restored.** It
recorded, driven on 2026-08-27, that regeneration against an unmodified tree
moves one leaf. Driven again on 2026-09-06 against an unmodified tree it moves
**thirty-three**, plus two `limitations` removed. Nothing in the repository
changed. The local capture store grew: `data/raw` holds 10,437 files, newest
write 2026-09-01, and `BoxScoreTraditionalV3` went 1,230 to 4,920 captures with
`last_fetched_at` moving 2026-08-22 to 2026-09-02. Four live sweeps landed
between the two measurements.

**The mechanism, which is a design fault and not an accident.** The manifest
mixes three kinds of leaf and the gate treats them alike. *Evidence* —
`canonical_observations`, `cross_source_reconciliation` — must be frozen and
did not move. *Provenance* — `operator.*` — is expected to move on an edit.
*Environment description* — `source_capture_summary` — describes a **mutable
local store that no reviewer controls** and moves on its own, with no code
change at all. Freezing an artefact that records a moving quantity guarantees
the gate fires for reasons unrelated to any edit.

**Corrected 2026-09-06, after `quant` reproduced the committed state.** This
paragraph originally placed the `null` cascade fields in that third class,
saying they populate *"once the store covers the window"*. That was wrong, and
the referral disproved it cheaply: the slate and coverage reports are
**byte-identical to commit** and were inventoried by the committed manifest
itself, so the store already covered the window when the manifest was
generated. The cascade reads `null` because the loader resolves `data/reports`
**CWD-relative and hard-coded**, while `operational_artifacts` honours the
explicit `--report-dir`; run from `backend/` with an absolute `--report-dir`,
today's code reproduces the committed manifest exactly. So 10 of the 35 leaves
are a **generation-context defect plus a latent generator bug**, not store
growth — a distinction that changes the remedy from *tolerate the noise* to
*fix the generator and refresh*, and is filed as such. The differential
amendment below is unaffected: it was argued from the 25 provenance leaves,
which do drift for the reason stated.

**Consequence, which section 3 did not anticipate.** Because every regeneration
now moves environment leaves, every edit to a fingerprinted file stops for
`quant` regardless of what it did. That is a freeze on six source files in
practice, and the Rejected section above declined a freeze explicitly. PR #171
is the demonstration: its footprint is **one** leaf, and it is blocked by
thirty-three it did not cause.

**Amendment.** Section 3's comparison becomes **differential, not absolute**.
Regenerate twice from the same store in the same run — once with the edit, once
with the edit reverted — and require the difference *between those two
regenerations* to be confined to `operator.source_fingerprints` and
`operator.commands`. Compare like against like. Drift shared by both is
environment drift and is not the edit's to answer for; it is a separate finding
against the store, escalated on its own terms rather than attached to whichever
pull request happened to regenerate next.

**What this deliberately does not do.** It does not decide whether the current
store's drift is safe pre-unblind — two `limitations` reading "UNVERIFIED, NOT
ZERO" now report `0`, and whether that is a verified zero or an absence wearing
a zero is `quant`'s ruling, referred on 2026-09-06 and open at the time of
writing. It does not weaken what may move under an edit. It changes only the
baseline the edit is measured against.

**Evidence.** The control was run twice independently — by the lane holding
#171, and by me from the main checkout at `61f3dd72`, from the data root, with
`--repo-root` on main and output to a temp path. Both produce the same
thirty-three. My run additionally moved `operator.commands[8]`, which is the
`--out` path echo that section 4 already names, and is the reason a differential
comparison must hold the output path fixed across both regenerations or it will
report a movement it created itself.

**What would flip this amendment.** The store being made immutable per cohort —
a content-addressed snapshot pinned in the manifest rather than summarised from
whatever is on disk — removes the drift at its source and makes the absolute
comparison correct again, at which point this amendment should be withdrawn
rather than kept as redundant machinery. Equally, if `quant` rules that
environment drift is itself unblinding, then regeneration is not a routine
operation and the differential gate is the wrong shape entirely.
