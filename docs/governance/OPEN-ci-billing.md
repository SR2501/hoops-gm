# Open: GitHub Actions is stopped by billing

**Raised:** 2026-08-17
**Status:** Awaiting the owner. Nothing else can resolve it.
**Risk:** R29

---

## What is happening

Since roughly 12:58Z on 2026-08-17, every GitHub Actions job fails **before executing a single step** (`steps: 0` on all jobs), with:

> recent account payments have failed or your spending limit needs to be increased

**Confirmed from the billing page on 2026-08-17: the monthly Actions quota is exhausted — 2,000 of 2,000 included minutes used, resetting in 15 days.** The account is on GitHub Free, which includes 2,000 minutes per month for private repositories. Metered spend is $0 and there is no payment due, so nothing has actually failed to pay; the message is GitHub's generic wording for "no minutes and no spending limit set".

### A correction worth keeping

This was first recorded as *likely a lapsed card*, on the reasoning that the message mentions failed payments and that this project had used only about an hour of runner time. **That was wrong, and the error is instructive.**

The hour was an estimate for *this repository*. The 2,000 minutes are *account-wide*, across every private repository. A plausible mechanism was asserted rather than the number being looked at — which is precisely the failure mode this project has now catalogued seven times, this time by `architect` while writing the document that catalogues it.

The general form, already in the house rules: a mechanism that sounds right is not evidence. The billing page was one click away throughout.

## Why it matters more than it looks

The four readiness gates in `governance/gates.md` are enforced by exactly one mechanism, and that mechanism is currently off.

Right now a red tick says nothing about the code, and a green one cannot be obtained. That includes the Postgres job stood up specifically to make ADR-001 enforceable rather than asserted — and **R34 now depends on it**, because the Phase 2 migration uses `batch_alter_table(copy_from=...)`, whose Postgres code path has never executed.

This project has already produced seven cases where a guarantee was believed and false. Every one was caught by executing something. Losing the thing that executes them is the single worst tool outage this project can have.

## Why no agent can resolve it

Both available fixes are on the owner-only list in `owner-decisions.md`:

- **Raising a spending limit or fixing a payment method** commits money.
- **Changing repository visibility** is a disclosure decision.

No agent has touched a billing setting, and none should.

## Options, with what is actually true about each

### 1. Set an Actions spending limit — *recommended, and it is cheap*

The quota is exhausted, not unpaid, so this is the direct fix. **Settings → Billing → Manage budgets / spending limit for Actions.**

Beyond the included minutes, Linux 2-core runners bill at **$0.008 per minute**. A full push of this project's CI is roughly 5–6 minutes across all jobs, so **about 5 cents per push**. Twenty pushes in the remaining fifteen days is around **$1**; a hundred pushes is around **$4**. Setting a small limit — $5 or $10 — restores CI immediately and caps the exposure.

Worth checking at the same time *what* consumed 2,000 minutes, since this project used a fraction of it. Another private repository is doing the bulk of it, and if that is a scheduled workflow running more often than intended, fixing that is free.

### 2. Wait for the reset — free, costs fifteen days

The quota resets in 15 days. No money, no disclosure, no action. But it means the entire Phase 2 review, the Postgres migration verification that R34 depends on, and PR #3 all sit until then, with every merge in between unverified.

### 3. Make the repository public — free unlimited runners *and* free security tooling

Public repositories are **exempt from the Actions quota entirely** — not given a higher limit, but removed from the pool. Whatever else on the account is consuming the 2,000 minutes would get all of them back.

Verified feature difference on the Free plan (checked 2026-08-17):

| | Private (Free) | Public (Free) |
|---|---|---|
| Actions minutes | 2,000/month, shared across all private repos | **Unlimited standard runners, exempt from the quota** |
| Secret scanning + push protection | Paid add-on (GitHub Secret Protection) | **Free** |
| CodeQL code scanning | Paid add-on (Advanced Security) | **Free** |

**The security tooling is pointed directly at this project's demonstrated weak spot.** Within one hour on 2026-08-17 the project found (a) its own secret scanner had regressed to miss eleven credential patterns it previously caught, and (b) a live `userSecretId` being written to disk in cleartext. GitHub's native scanning is an **independent** control — not the same scanner this project wrote and broke — and push protection blocks a real secret at the push, before it enters history. That is the "verify with something that did not write the claim" principle, automated and free.

**The git history is verifiably clean.** Every commit on every branch was scanned on 2026-08-17 for credential patterns. The only matches are deliberately-planted test fixtures in `test_secret_scan.py`: `hunter2hunter2hunter2`, `AKIAIOSFODNN7EXAMPLE` (AWS's own published documentation example), and bare `BEGIN PRIVATE KEY` headers with no key material. **No real credential has ever been committed**, so going public would not expose one retroactively.

**The cost is competitive, not security — and it is smaller than it feels.** The repository contains the valuation methodology, punt-build approach, auction-inflation design and the mock-draft programme, for a league the owner plays annually against people who could find it. But the *methods* are public knowledge: z-scores are standard, G-score is a published arXiv paper, and Basketball Monster sells inflation and category analysis commercially. What is genuinely proprietary is the implementation, the specific weightings, and the draft-day workflow. A leaguemate would have to find the repository, read roughly forty thousand words, and then build it.

Not cleanly reversible: forks and search indexing persist after a repository is made private again.

**Two coherent paths:**

- **Public now.** CI works today at no cost, security tooling improves, quota freed. Accept modest strategy exposure.
- **Stay private with a small spending limit (~$1–4/month), go public after the draft.** Keeps the edge for this season and takes the features afterwards.

If the goal is working CI today without spending anything, public is the answer. If the exposure is unwelcome at all, the spending limit is cheap enough that this stops being a financial decision.

### 4. Self-hosted runner — free, some setup

A runner on the owner's own machine gives unlimited free CI for a private repository. Reasonable here because the repository is private and the code is the owner's own — the usual warning about self-hosted runners applies to *public* repos accepting untrusted pull requests, which is not this situation.

Costs: the machine must be on for CI to run, and it would not reproduce the Ubuntu/Python 3.12 environment that currently catches cross-platform problems, which is exactly the gap Phase 2 flagged. It also cannot run the Postgres service job as cleanly. Viable as a supplement, weaker as a replacement.

### 5. Run the gates locally only — *not recommended as a standing state*

The commands are in `backend/README.md`. Fine for a day. As a standing arrangement it means nothing enforces the gates, on a project whose defining lesson is that unexercised guarantees are false ones.

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
