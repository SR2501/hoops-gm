# The decisions in plain English

> **Frozen historical walkthrough.** This document covers ADR-001 through
> ADR-009 and is not extended for later decisions. The individual ADRs and
> [`README.md`](README.md) index are the current authoritative record.

A readable walkthrough of why each architectural decision was made and what it means in practice. The ADRs themselves are the authoritative record; this is the version you can read without already knowing the codebase.

All nine were accepted by the project owner. Each records the condition that would flip it — a decision without a reversal condition is a belief.

---

## ADR-001 — Local-first, with a Postgres seam

**Decision.** The app runs on your machine, binds to `127.0.0.1`. SQLite for development, but every database access goes through SQLAlchemy so nothing SQLite-specific leaks in.

**Why it matters to you.** Nothing is exposed to the internet, your Fantrax cookie isn't reachable remotely, and imported projection data isn't redistributed. When you eventually add a leaguemate, moving to Postgres is a config change rather than a rewrite.

**Rejected:** a hosted service (obligations without users), and raw SQL (faster now, rewrite later).

**Would flip it:** more than about three users, or needing access away from your machine.

- [x] Accept  · [ ] Discuss

---

## ADR-002 — Separate per-game production from expected games played

**Decision.** Never bundle "how good is he" with "how often does he play." They're modelled independently and combined at one explicit point.

**Why it matters to you.** This is the central commitment of the whole project. It's what lets the tool answer *"is this guy actually good, or just available?"* — and price a 70-game player differently from a 55-game player with identical per-game lines. Most published projections bundle a games-played assumption; we strip it out and substitute our own.

**Rejected:** a single blended seasonal projection (makes durability invisible), and applying a flat durability discount afterwards (can't express that availability varies by opponent, schedule and date).

**Would flip it:** nothing foreseeable.

- [x] Accept  · [ ] Discuss

---

## ADR-003 — G-score as the default valuation method

**Decision.** Implement both z-score (the industry standard) and G-score (from a 2023 academic paper), and default to G-score for head-to-head.

**Why it matters to you.** Z-score values a season average. Your league is weekly head-to-head, where *consistency* changes who wins matchups — a player who scores the same total via steady output beats one who gets it in bursts. G-score models that. It's also where availability risk gets absorbed, since an unreliable player adds variance through both channels.

**The tradeoff:** your rankings will differ from Basketball Monster and Hashtag, which are z-score based. That divergence is intentional and is what the model-vs-market report is for — but it has to be explainable, not just different.

**Would flip it:** backtesting showing G-score doesn't actually beat z-score on your league's specific settings.

- [x] Accept  · [ ] Discuss

---

## ADR-004 — Fantrax: read via API, write only through the browser

**Decision.** Three tiers — the official free API for player IDs and ADP; the community `fantraxapi` library for your private league's rosters and matchups; and the Tampermonkey bridge for everything else **and for all writes**. No programmatic writes to Fantrax's internal endpoints, ever.

**Why it matters to you.** Fantrax has no write API at all, so lineup and draft actions must happen as real interaction in your own browser session. This is also what forces the draft-day constraint: Fantrax has to be the visible, active tab during a draft, because Chrome throttles hidden tabs and would stall Fantrax's own polling.

**Rejected:** programmatic writes to `/fxpa/req` — a clear terms violation with no benefit over the browser path.

**Would flip it:** Fantrax publishing a supported write API.

- [x] Accept  · [ ] Discuss

---

## ADR-005 — Automation is supervised by default; autonomous is opt-in

**Decision.** One pipeline, two modes. Supervised (default): the tool recommends, the overlay highlights it, you click. Autonomous (explicit, per-session): the script acts, bounded by eight mandatory guardrails — kill switch, dry-run default, validity precheck, scope caps, confidence floor, injury-data freshness check, human pacing, full audit log.

**Why it matters to you.** You asked for both, and you're right that detection isn't the real risk — *bugs* are. A defect that auto-drafts a bust or submits an illegal lineup at 11:59pm costs a season. So the write path is isolated in one swappable module, and a separate `safety` agent reviews it and holds veto. **Enabling autonomous mode is your call, not any agent's.**

**Rejected:** fully autonomous from the start (unearned trust), and read-only (you rejected it, and the guardrails make supervised writes reasonable).

**Would flip it:** sustained evidence across many rehearsals that specific caps can loosen — still your decision.

- [x] Accept  · [ ] Discuss

---

## ADR-006 — External adapters isolated behind contract tests

**Decision.** Every external source sits behind an adapter with a **recorded real response** committed to the repo, an offline test that runs in CI forever, and a live test that may fail but must fail loudly.

**Why it matters to you.** This has already paid for itself repeatedly. It's the discipline that caught `BoxScoreSummaryV2` silently returning zero inactive players for an entire season, and the `gameEt` field that claims UTC and isn't. The failure mode that matters isn't an outage — it's a **silent** change that still parses and quietly produces wrong numbers.

**One rule that matters:** never regenerate a fixture to make a failing test pass. That defeats the whole mechanism.

**Would flip it:** a source offering a versioned, stable API with change notifications. None do.

- [x] Accept  · [ ] Discuss

---

## ADR-007 — Availability is modelled *before* valuation

**Decision.** Build order is identity → schedule → **availability** → projections → valuation → features. Availability is an input to valuation, not an attribute of it.

**Why it matters to you.** This is why there's nothing visually impressive yet. The draft board and live scorecard are the tempting things to build first and they're worthless sitting on a broken identity table or a naive games-played assumption. Building valuation first and retrofitting availability means rewriting the valuation layer.

**Rejected:** valuation first (guarantees a rewrite), and a flat games-played assumption (the exact error this project exists to beat).

**Would flip it:** the backtest showing a simple seasonal average predicts as well as a contextual per-game model. If so, simplify the engine.

- [x] Accept  · [ ] Discuss

---

## ADR-008 and ADR-009

Added after this walkthrough was written. See [ADR-008-layer-purity.md](ADR-008-layer-purity.md) — aggregates like rankings and auction values already contain an availability assumption, so blending them back into projections double-counts it and destroys the ability to tell "he is good" from "he is durable" — and [ADR-009-schedule-intelligence-contract.md](ADR-009-schedule-intelligence-contract.md).