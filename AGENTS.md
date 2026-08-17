# AGENTS.md — hoops-gm

**Read this first. Then read `docs/handoff.md`.** Everything else follows from those two.

---

## What this is

An end-to-end fantasy basketball league management tool for the 2026–27 NBA season, built for a single H2H 9-cat league on Fantrax, with one or two leaguemates as possible later users.

The full plan is `docs/plan.md`. Do not work from a summary of it in your prompt — read the file.

## What makes it different

**Availability is the product.** Missed games are epidemic in the modern NBA, and predicting who actually suits up is where leagues are won. A 70-game player and a 55-game player with identical per-game lines are not the same asset. This tool models availability as a first-class quantity — `p(play)` per scheduled game — and threads it through valuation, draft, lineup, streaming and trades.

The central modelling rule: **per-game production and expected games played are computed separately and fused explicitly.** Never conflate them. Conflating them is why most tools overvalue fragile stars.

---

## The four things that make this project unusual

Governance exists because of these. If you understand nothing else, understand these.

1. **Wrong models don't crash.** A miscomputed z-score or badly calibrated `p(play)` produces confident, plausible, wrong numbers. Green tests prove nothing about correctness here. Statistical work needs a statistical gate.
2. **Upstreams break without warning.** `/fxpa/req` is undocumented internal Fantrax infrastructure; `stats.nba.com` is unstable. Drift must fail loudly in CI, never silently degrade a number.
3. **The write path touches a live account** under ToS-grey conditions, and a bug can wreck a season in one click. Whoever builds it does not approve it.
4. **Draft day does not move.** Sequencing is calendar-bound, not just dependency-bound.

---

## The roster

Full definitions in `.github/agents/`. Ownership matrix in `docs/governance/ownership.md`.

| Agent | Owns | Does not |
|---|---|---|
| **architect** | Boundaries, cross-module contracts, ADRs, phase sequencing, arbitration | Implement specialist feature code |
| **data-engineer** | External adapters, throttling/retry/caching, fixtures, contract tests, player identity crosswalk | Statistical modelling; UI |
| **quant** | Availability model, reliability metrics, contingent value, projections, valuation, auction pricing, backtests | Ingestion plumbing; UI; the write path |
| **backend** | FastAPI app, schema and migrations, REST/SSE contracts, persistence, observability | Model math; browser code |
| **frontend** | React/TS dashboard, scorecard, draft board, schedule and reliability views, stock watch | Backend logic; model math |
| **bridge** | Tampermonkey userscript: capture, overlay, action executor, transport | Decide *what* action to take; approve its own guardrails |
| **safety** | Independent review of the entire write path. **Holds veto.** | Implement the bridge it reviews |

`quant` and `data-engineer` are separate because resilient I/O against hostile APIs and statistical correctness are different skills with different failure modes.

`bridge` and `safety` are separate because self-approval is precisely what guardrails exist to prevent.

---

## The four gates

Nothing merges without passing the gate matching its work type. Gates are cumulative where work spans types. Details in `docs/governance/gates.md`.

| Gate | Applies to | Requires |
|---|---|---|
| **Code** | All code | Lint, type-check, tests green |
| **Adapter** | Anything calling an external source | Recorded fixture committed + contract test; separate live smoke test allowed to fail loudly |
| **Model** | Anything producing a number a decision rests on | Backtest against held-out data reporting **calibration**, not just accuracy; model card in `docs/models/`; explicit statement of what the model cannot see |
| **Automation** | Anything in the write path | Dry-run transcript attached + independent `safety` sign-off. No exceptions, including "trivial" changes |

---

## Owner-only decisions

Escalate and stop. Do not decide these. Full list in `docs/governance/owner-decisions.md`.

- Anything changing ToS exposure or the nature of Fantrax access
- Enabling autonomous mode, or widening its scope caps
- Any paid data subscription
- Anything acting on the real draft or a live lineup lock for the first time
- Accepting an ADR — **agents write `Proposed` only, never `Accepted`**

---

## House rules

- **Nothing important lives only in a chat.** If it is worth returning to, it is in this repository. That is why this file exists.
- **Append to `docs/handoff.md` when you finish a unit of work.** The "could not verify" field is mandatory, and "nothing" is rarely the honest answer.
- **Separate production from availability.** Always. See ADR-002.
- **Percentage categories are volume-weighted impact, not raw percentage.** A 90% FT shooter on one attempt is worthless. This is the single most common bug in homebrew fantasy tools.
- **Calibration beats accuracy for `p(play)`.** A model that says 70% and is right 70% of the time is more useful than a higher-accuracy model that is overconfident.
- **Do not trust stated DNP reasons.** "Rest" is routinely laundered as a minor ailment. Lean on observed patterns.
- **Prefer reversible.** The owner is one person building for himself first. The smallest structure that honestly supports the requirement beats the most complete one.

## Judgement

Disagree with the brief when you think it is wrong, and argue it rather than complying quietly. Report what proved ambiguous or wrong when you tried to build it — that is more valuable than a clean report.

If this governance ever costs more than it prevents, say so. `architect` owns the call to cut it.
