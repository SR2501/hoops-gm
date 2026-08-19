# Readiness gates

Four gates. Apply the one matching your work type; apply several where work spans types. A change that ingests data, models it, and exposes it in the write path passes all four.

Gates exist because this project's failure modes are unusual — see the four points in `AGENTS.md`.

---

## Code gate

**Applies to:** all code.

- Lint clean
- Type-check clean
- Tests green
- No secrets, cookies, tokens or `userSecretId` values committed

Enforced by CI.

---

## Adapter gate

**Applies to:** anything calling an external source — `nba_api`, `cdn.nba.com`, Fantrax official API, `fantraxapi`, injury reports, projection CSVs.

- **Recorded fixture committed.** A real captured response, checked in.
- **Contract test** asserting the parser still works against that fixture. Runs in CI, offline, always.
- **Live smoke test** hitting the real source, marked so it may fail without blocking a merge — but it must fail *loudly and visibly*, never silently.
- Throttling and retry documented for the source's known limits (`stats.nba.com` ~1 req/s; Fantrax read-only, low frequency).
- Failure behaviour is explicit: what the system does when the source is down, changed, or returns garbage.

**Why:** `/fxpa/req` is undocumented internal infrastructure and can change without notice. The contract test is how we find out in CI instead of at 11:59pm on lineup lock.

---

## Model gate

**Applies to:** anything producing a number a decision rests on — `p(play)`, reliability metrics, projections, blending, z-score, G-score, risk-adjusted valuation, auction dollar values, inflation, contingent value.

- **Backtest against chronologically held-out observations.** Never evaluate on observations the model was fit or selected on. A whole held-out season is valid when available, but the gate requires a time-ordered cutoff, not an arbitrary season boundary.
- **Report calibration, not just accuracy.** For probabilistic outputs this is the primary metric. A model that says 70% and is right 70% of the time is more useful for lineup decisions than a higher-accuracy model that is overconfident. Reliability diagrams or binned calibration tables.
- **Model card in `docs/models/`** — inputs, method, training window, evaluation results, known failure modes.
- **State what the model cannot see.** Trades, coaching changes, undisclosed injuries, personal matters, front-office intent. Be explicit about the blind spots.
- **Version the output and its lineage.** Every stored number records the model version, input/source cohort fingerprints, forecast origin/cutoff, and scoring profile where applicable.

**Why:** wrong models don't crash. They produce confident, plausible, wrong numbers, and green tests say nothing about it.

---

## Automation gate

**Applies to:** anything in the write path — action protocol, guardrails, audit log, supervised mode, autonomous mode, lineup auto-set, the overlay's action executor.

- **Dry-run transcript attached** to the change, showing exactly what would have been done.
- **Independent `safety` sign-off.** `bridge` may not approve its own work. **No exceptions, including changes that look trivial.**
- All guardrails verified still active: kill switch, dry-run default for new action types, validity precheck, scope caps, confidence floor, availability freshness, pacing.
- Audit log entry produced for every action, including refusals and escalations.
- Failure mode is fail-safe: on any ambiguity, escalate to the human rather than act.

**Why:** this operates a live account under ToS-grey conditions, and a bug can wreck a season in one click. The category of automation is sanctioned — Fantrax ships auto-draft and auto-subs natively — but the implementation path is not, and the real risk is our own bugs.

---

## Gate discipline

- Gates are not paperwork; if one is not catching anything, say so and change it.
- Failing a gate is information, not failure. Record it in `docs/handoff.md`.
- No gate may be waived by the agent whose work it applies to.
