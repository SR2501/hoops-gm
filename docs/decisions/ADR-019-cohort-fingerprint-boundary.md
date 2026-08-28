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
