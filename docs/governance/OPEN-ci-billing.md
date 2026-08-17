# Open: GitHub Actions is stopped by billing

**Raised:** 2026-08-17
**Status:** Awaiting the owner. Nothing else can resolve it.
**Risk:** R29

---

## What is happening

Since roughly 12:58Z on 2026-08-17, every GitHub Actions job fails **before executing a single step** (`steps: 0` on all jobs), with:

> recent account payments have failed or your spending limit needs to be increased

The last successful run was 12:56Z. Two minutes apart, no workflow change between them. This is an account-level stop, not a code failure.

## Why it matters more than it looks

The four readiness gates in `governance/gates.md` are enforced by exactly one mechanism, and that mechanism is currently off.

Right now a red tick says nothing about the code, and a green one cannot be obtained. That includes the Postgres job stood up hours earlier specifically to make ADR-001 enforceable rather than asserted — it ran green for about forty minutes before this started.

This project has already produced three cases where a guarantee was believed and false (R25, and the CI defect in PR #3). Every one was caught by executing it. Losing the thing that executes them is the single worst tool outage this project can have.

## Why no agent can resolve it

Both available fixes are on the owner-only list in `owner-decisions.md`:

- **Raising a spending limit or fixing a payment method** commits money.
- **Changing repository visibility** is a disclosure decision.

No agent has touched a billing setting, and none should.

## Options, with what is actually true about each

### 1. Fix the payment method or raise the limit — *recommended*

The wording *"recent account payments have failed"* points at a lapsed or declined card rather than an exhausted quota. Personal accounts get 2,000 free Actions minutes per month for private repositories, and this project's entire history to date is on the order of one to two hours of runner time. Quota exhaustion is unlikely; a card is the likely cause.

Check: **GitHub → Settings → Billing and plans → Payment information**, and the Actions spending limit on the same page.

This restores everything with no other consequences.

### 2. Make the repository public — viable, but weigh the second reason

Public repositories get unlimited free standard runners.

**On secrets, the repository is verifiably clean.** Checked on 2026-08-17: no tracked file contains a credential pattern, no `.env`, no cookie file, no projection CSVs. `.env.example` is an empty template — `FANTRAX_LEAGUE_ID=` has no value. `.gitignore` excludes `.env`, `*.cookie`, `data/` and `*.csv`, and a CI job scans for secrets. The earlier concern that publishing would expose personal-use projection data or Fantrax access details does not hold against what is actually committed.

**The stronger argument against is competitive, not security.** This repository contains the complete valuation methodology, the punt-build and auction-inflation approach, the availability model design, and the intent to run 10+ instrumented mock drafts. In a league the owner plays in annually, that is the edge itself, published and searchable. That is a real cost, and it is the owner's to weigh — not a technical one.

Also note it is not cleanly reversible: forks and search indexing persist after a repository is made private again.

### 3. Run the gates locally and merge without CI — *not recommended as a standing state*

The commands are in `backend/README.md`. This is fine for a day. As a standing arrangement it means nothing enforces the gates, on a project whose defining lesson is that unexercised guarantees are false ones.

## Current working arrangement

- Gate commands run locally before any merge.
- **Do not trust a tick** until Actions is running again.
- **PR #3 is held open, not merged.** It repairs a real CI defect — a `live-smoke` job gating on a `schedule` event the workflow never declared, so the one job meant to catch upstream drift could never run — and it adds tests that make the workflow check its own coherence. It is verified locally but unverifiable by CI.

  Merging it now would buy nothing: **the nightly cron it enables cannot fire until Actions is restored**, so merging gets the configuration without the behaviour, while still spending the precedent of merging past a dead gate in the exact circumstance the gate exists for. It merges the moment Actions runs, at which point config and behaviour arrive together.
- Phase 2 continues. It is not blocked by this, only unverified by CI.

## Why this lands hardest on Phase 2

Phase 2 builds the external adapters, and the Adapter gate is its main safeguard — the gate that requires a contract test which "runs in CI, offline, always". That word is doing the work, and right now it cannot.

Worse, the gate's other half is already unavailable for a different reason. **A contract test against a recorded fixture can never detect that an upstream source changed**, because the fixture keeps passing forever. Only the live smoke test catches drift — and that is both the job PR #3 repairs and the job that cannot run while Actions is stopped.

So Phase 2 is building against `/fxpa/req` and `stats.nba.com` — undocumented internal infrastructure and an unstable public endpoint, exactly the pairing the Adapter gate was written for — with neither half of that gate operating. `data-engineer` has been told directly rather than left to discover it when a fixture drifts.
