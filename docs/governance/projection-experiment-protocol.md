# Projection experiment sequestration protocol

**Owner decision:** 2026-08-19

This protocol applies to experiments that evaluate or select a projection
method for production use. It operationalizes five rules: model workers have no
direct source access; a data-engineer custodian prepares data and an independent
quant releases it; packages are immutable and timestamped; the experiment is
frozen before outcomes are unblinded; and mock outcomes never enter production
or availability.

It is a short experiment protocol, not an ADR and not an expansion of the
project-wide Model gate.

## Roles and separation

- **Data-engineer custodian:** reads source data through the existing adapter
  boundaries, creates each package, records its manifest, and retains the source
  provenance needed to reproduce it. The custodian does not run or select the
  projection model.
- **Independent quant releaser:** verifies package identity, outcome
  sequestration, and manifest completeness before release. The releaser must not
  be the model worker for that experiment.
- **Model worker:** receives only released packages. The worker must not query,
  browse, refresh, or otherwise inspect the underlying source or any unreleased
  outcome data.

Separation is by responsibility for one experiment; it does not require a new
service, account, or isolation platform.

## Immutable package contract

Every handoff to a model worker is a timestamped package. Its `content_sha256`
is computed from the canonical manifest fields other than `package_id` and
`content_sha256`, plus the ordered payload digests. Its `package_id` is the UTC
timestamp plus a prefix of `content_sha256`. A correction creates a new package
with a new timestamp and identity; an existing package is never edited in place.

The manifest contains only the fields needed to audit the handoff:

| Field | Requirement |
|---|---|
| `package_id` | Timestamp plus digest-derived identifier |
| `content_sha256` | SHA-256 over the canonical identity fields and payload digests |
| `created_at` | UTC creation timestamp |
| `dataset_class` | `development`, `sealed_outcome`, or `mock_outcome` |
| `purpose` | Experiment and cohort this package may serve |
| `source_cutoff` | Latest observation time represented |
| `payloads` | Relative filename, byte size, and SHA-256 for every file |
| `fields_released` | Inputs and outcomes present in the payload |
| `fields_withheld` | Outcome fields intentionally sequestered |
| `custodian` | Data-engineer identity and creation attestation |
| `freeze_id` | Required for `sealed_outcome`; absent before a valid freeze |

The manifest may name existing adapter/source versions for reproducibility, but
it does not grant the model worker direct access to those sources. The
independent quant's release is a separate immutable record referencing the
package identity, so release does not mutate the package it approves.

## Freeze and unblind

Before any sealed outcome package is released, the model worker freezes a
pre-registration record with a stable `freeze_id`. It states:

1. the question and eligible cohort;
2. the development package identities;
3. the feature set and model variants to be compared;
4. the held-out outcome and split boundary;
5. the primary metric, required calibration evidence where applicable, and the
   decision rule;
6. the planned outputs and any stopping rule.

The freeze is immutable. A change creates a new freeze and leaves the prior one
in the audit record. The independent quant releaser verifies that the freeze
predates release, then binds the `sealed_outcome` package to that `freeze_id`.

Unblinding occurs only when the model worker receives that released outcome
package. The unblind record names the freeze, package identities, worker,
releaser, and UTC release time. Any post-unblind deviation is recorded beside
the result and cannot be represented as pre-registered.

## Audit evidence and fail-closed handling

The durable experiment record consists of the package manifests and digests,
the custodian attestation, independent release record, frozen pre-registration,
unblind record, and any deviation or violation record. Data that cannot be
committed remains in the project's existing local data storage; its manifest,
digest, and audit records must still be retained with the experiment.

The experiment stops without a production result if any of these conditions is
found:

- the model worker accessed a direct source or unreleased outcome;
- the custodian, releaser, and worker separation was not satisfied;
- a package digest does not match, was overwritten, or lacks its minimal
  manifest;
- an outcome was released without a prior matching freeze;
- a mock outcome entered any production projection, production valuation, or
  availability input.

Recovery starts a new package and, after any outcome exposure, a new experiment
with a new freeze. The affected run remains in the audit record and cannot be
relabelled as valid.

## Explicit non-goals

This protocol does not prescribe new isolation infrastructure, change paid-data
or source-access policy, amend ADR-006, alter Fantrax/ToS policy, broaden the
Model gate, or authorize any production model. Mock outcomes may test workflow
and analysis code, but are permanently ineligible as production or availability
evidence.
