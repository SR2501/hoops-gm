# hoops-gm — Fantasy Basketball League Management Tool

**Target season:** 2026–27 NBA
**Repo:** new repo `SR2501/hoops-gm` (name changeable)
**Primary user:** you, then possibly 1–2 leaguemates
**Primary format:** H2H 9-cat (FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO), architected for points/roto later

---

## Problem

Managing a competitive 9-cat league well requires stitching together things that live in different places: Fantrax league state, NBA stats, projections, category-aware player valuation, the schedule, and — increasingly the whole ballgame — **who is actually going to play**.

Missed games are epidemic. Load management, soft-tissue caution, rest on the second night of back-to-backs, DNP-CDs, late-season shutdowns on eliminated teams, and availability that swings on no stated reason at all. Predicting who suits up on a given night is materially harder than it was even two or three seasons ago, and it is where leagues are won and lost. A 70-game player and a 55-game player with identical per-game lines are not remotely the same asset, and the market still prices them as if they were.

`hoops-gm` treats availability as a first-class modelled quantity rather than a footnote, and threads it through every downstream decision: valuation, draft, lineup, streaming, and trades.

## Approach

A Python/FastAPI backend owns data ingestion, availability modelling, projection blending, and valuation math. A React/TypeScript frontend is the primary dashboard (live scorecard, draft board, trade lab, schedule/availability grid). A Tampermonkey userscript acts as a two-way bridge to Fantrax: it captures authenticated league data the public API doesn't expose, and renders recommendations as an overlay inside Fantrax so decisions can be actioned in place.

Build order is deliberately spine-first: player identity, schedule, and availability must be solid before any feature work, because every number downstream depends on them.

**The central modelling decision:** projections are decomposed into **per-game production × expected games played**, computed separately and fused explicitly. Most homebrew tools conflate these and end up systematically overvaluing fragile stars and undervaluing iron-man mid-rounders.

The work is built by a set of specialist agents under an explicit governance model — see *Agent governance* below. Every artifact that matters lives in the repository, not in a chat transcript.

---

## Research findings that shaped this plan

Gathered before planning; these are load-bearing constraints, not trivia.

| Area | Finding | Consequence |
|---|---|---|
| Fantrax official API | Beta REST at `fantrax.com/fxea/general/` — `getPlayerIds`, `getAdp`, `getLeagues`, `getLeagueInfo`, `getDraftPicks`. No auth for some; `userSecretId` for others. | Use for player ID map, ADP, league settings, draft picks. Free and low-risk. |
| Fantrax gaps | No documented endpoints for matchups/live scores, transactions, waivers, or **any write operation**. | Everything else must come from `fantraxapi` or the Tampermonkey bridge. |
| `fantraxapi` (MIT, maintained) | Wraps internal `/fxpa/req`. Read-only. Private leagues need a `FANTRAXUSER` session cookie, obtained via Selenium login. | Primary private-league read path. Pin the version — internal schema can change without notice. |
| `/fxpa/req` | Internal JSON-RPC used by the Fantrax SPA. Undocumented; no public login endpoint. | Treat as unstable. Isolate behind an adapter with contract tests. |
| Write automation | No supported write API. Reverse-engineered writes violate ToS. Fantrax *does* natively offer auto-draft and auto-subs. | Writes go through the browser bridge as real DOM interaction on your own account, defaulting to supervised, with hard guardrails. |
| Tampermonkey viability | `GM_xmlhttpRequest` runs at extension privilege — bypasses both CORS and the page CSP. No existing Fantrax userscripts exist publicly. | The localhost bridge works cleanly. We're building from scratch. |
| `nba_api` (v1.11.4, Feb 2026) | Actively maintained, Python 3.10+. `stats.nba.com` needs specific headers and ~1 req/s throttling. `PlayByPlayV2`/`ScoreboardV2` deprecated → use V3. | Primary historical stats source. Also the source of inactive lists and DNP reasons — critical for the availability ledger. |
| Live scoring | `cdn.nba.com/static/json/liveData/` — scoreboard + boxscore JSON, 1–5s refresh, no auth, no key. | Free live scorecard. Poll every ~5s, only while games are live. |
| Projections | No source has an API. Hashtag (Patreon), Basketball Monster (~$9.95/mo), FantasyPros (free CSV), DARKO (historical CSV only). | CSV import is the only integration path. Most published projections bundle a games-played assumption — capture it separately so our availability model can override it. |
| Basketball-Reference | 20 req/min hard limit; data-use policy forbids database building. | ❌ Avoid entirely. `nba_api` covers the same ground. |
| Valuation math | Z-score is standard; **G-score** (arXiv 2307.02188) models weekly variance and outperforms z-score specifically in H2H. | Implement both. G-score is the better default — and its variance framework is the natural place to absorb availability risk, not just production variance. |

Useful prior art: `zer2/Fantasy-Basketball` (clearest z-score/punt walkthrough), `GrahamAlbert744/nba-fantasy-decision-system` (9-cat draft/waiver/trade), `pmurley/go-fantrax` (endpoint reference), `DimaKudosh/pydfs-lineup-optimizer` (LP lineup optimization).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Browser                                                    │
│  ┌──────────────────┐        ┌───────────────────────────┐  │
│  │ Fantrax web app  │        │  hoops-gm dashboard       │  │
│  │  + Tampermonkey  │        │  (React + TS + Vite)      │  │
│  │    overlay       │        │  scorecard · draft board  │  │
│  └────────┬─────────┘        │  trade lab · stock watch  │  │
│           │ GM_xmlhttpRequest└───────────┬───────────────┘  │
└───────────┼──────────────────────────────┼──────────────────┘
            │                              │ REST + SSE
            ▼                              ▼
┌─────────────────────────────────────────────────────────────┐
│  FastAPI backend (127.0.0.1)                                │
│                                                             │
│  bridge/       captured payloads · action queue             │
│  ingest/       nba_api · cdn.nba.com live · injury reports  │
│                · fantrax adapters                           │
│  identity/     cross-source player ID resolution            │
│  schedule/     density · rest · B2B · off-nights · playoffs │
│  availability/ participation ledger · p(play) model         │
│                · reliability · shutdown · contingent value  │
│  projections/  CSV import · blending · own model            │
│                · expected-games fusion                      │
│  valuation/    z-score · g-score · risk-adjusted · punts    │
│  engines/      draft · lineup · trade · stock watch         │
│  automation/   action planner · guardrails · audit log      │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
              SQLite (dev) → SQLAlchemy → Postgres seam
```

**Repo layout** (monorepo):
```
hoops-gm/
├── AGENTS.md              single entry point: roster, rules, gates
├── backend/               FastAPI app, Alembic migrations, pytest
├── frontend/              React + TypeScript + Vite
├── userscript/            Tampermonkey source + build
├── docs/
│   ├── plan.md            this plan, committed
│   ├── handoff.md         append-only handoff log
│   ├── decisions/         ADRs
│   ├── governance/        ownership · gates · owner-decisions · risks
│   └── models/            model cards (availability, valuation)
├── .github/agents/        invocable agent definitions
├── docker-compose.yml
└── .github/workflows/
```

### Cross-cutting design decisions

- **Local-first.** Binds to `127.0.0.1`. SQLite for dev, but all access through SQLAlchemy so the Postgres move for leaguemate sharing is a config change.
- **Adapters are isolated.** Every external source sits behind an interface with recorded-fixture contract tests, so upstream breakage is caught by CI rather than at 11:59pm on lineup lock.
- **Everything is versioned and explainable.** Every stored valuation records its inputs (projection blend version, availability model version, scoring profile, punt config). Every availability prediction records its driver features, so "why is this guy projected for 61 games?" always has an answer.
- **Bridge auth.** Userscript and backend share a locally generated secret; the bridge endpoint rejects anything without it.
- **Secrets** (Fantrax cookie, `userSecretId`, API keys) live in `.env`, never committed. Cookie is stored encrypted at rest with a re-login path when it expires.

---

## Interfaces & surfaces

Practical constraint: this is used primarily from a laptop. The design target is **one screen**, with extra monitors as a comfort, never a requirement.

### What actually needs Fantrax open

| Capability | Fantrax tab required? | Why |
|---|---|---|
| Roster / league / standings sync | ❌ No | Runs server-side via `fantraxapi` with the stored session cookie |
| Live scorecard | ❌ No | Live box scores come from `cdn.nba.com`, not Fantrax |
| Projections, valuations, rankings, punt builds | ❌ No | All local computation |
| Schedule, availability, reliability, stock watch | ❌ No | All local computation |
| Trade evaluation | ❌ No | All local computation |
| Bridge capture of data the API doesn't expose | ⚠️ Open, foreground preferred | Event-driven on page XHR; a hidden tab still works but updates lazily |
| **Live draft** | ✅ **Visible and active** | Chrome throttles background-tab timers to roughly once per minute after ~5 minutes hidden, which stalls *Fantrax's own* draft polling — not just ours |
| Lineup writes | ✅ Visible, briefly | DOM interaction against the live page |

So for day-to-day season management, Fantrax does not need to be open at all. Draft day is the real constraint, and it is the one that has to be designed for.

### Overlay-first, dashboard always reachable

**The overlay is the primary draft surface.** A compact, collapsible panel docked inside the Fantrax draft room, toggled by keyboard, positioned so it never obscures the draft board or player list. It must be sufficient to make a pick without leaving the tab, because alt-tabbing on a 60-second pick clock is precisely when mistakes happen.

**The dashboard is the evidence surface.** The overlay shows the *decision*; the dashboard shows the *reasoning behind it* — full category math, punt-fit breakdown, durability and shutdown detail, contingent-value implications, schedule context. It stays one alt-tab away and is never disabled during a draft.

That split is deliberate. Early on you will cross-check every recommendation, and you should — an unverified recommender has not earned anything. As the reasoning proves out, the cross-checks fall away on their own. The architecture should let trust be earned rather than assumed, and never trap you in a surface you don't yet believe.

### Surface parity rule

No draft-critical decision may be available in only one surface. Anything the overlay recommends must be inspectable in the dashboard, and anything the dashboard supports must be actionable from the overlay. This is enforced as a test, not a convention.

### Proving the second monitor unnecessary

The mock-draft rehearsal is instrumented rather than vibes-based. It records, per pick: whether the overlay alone was sufficient, when the dashboard was opened and what was being checked, time-to-decision, and whether the overlay recommendation was ultimately taken.

After a few mock drafts that produces a straight answer to "do I actually need the second screen?" — and if the answer is that you kept alt-tabbing for one specific thing, that thing belongs in the overlay. Multi-monitor stays fully supported either way; the goal is that it becomes a preference rather than a dependency.

---

## Agent governance

Built fresh for this project's actual failure modes, not adapted from a generic template. Four things make this project different from a normal app build, and the governance exists to address exactly those:

1. **Wrong models don't crash.** A miscomputed z-score or a badly calibrated p(play) produces confident, plausible, wrong numbers. Tests passing proves nothing. Statistical work needs a statistical gate.
2. **Upstreams break without warning.** `/fxpa/req` and `stats.nba.com` are undocumented or unstable. The rule is that drift must fail loudly in CI, never silently degrade a number.
3. **The write path touches a live account** under ToS-grey conditions, and a bug can wreck a season in one click. Whoever builds it must not be the one who approves it.
4. **Draft day does not move.** Sequencing is calendar-bound, not merely dependency-bound.

Governance is deliberately thin: a solo owner should not be administering a process. Seven personas, one owner per module, four gates, one append-only log.

### The roster

| Agent | Owns | Explicitly does not |
|---|---|---|
| **architect** | System boundaries, cross-module contracts, ADRs, phase sequencing, arbitration when ownership is unclear | Implement feature code owned by a specialist |
| **data-engineer** | External adapters (`nba_api`, Fantrax official + private, injury reports), throttling/retry/caching, recorded fixtures, contract tests, the player identity crosswalk | Statistical modelling; UI |
| **quant** | Availability model, reliability metrics, contingent value, projection blending, expected-games fusion, z-score/G-score, risk-adjusted valuation, backtests and calibration | Ingestion plumbing; UI; anything in the write path |
| **backend** | FastAPI app, schema and Alembic migrations, REST/SSE contracts, persistence, observability | Model math; browser code |
| **frontend** | React/TS dashboard, live scorecard, draft board, schedule and reliability views, stock watch | Backend logic; model math |
| **bridge** | Tampermonkey userscript: XHR capture, overlay rendering, action executor, transport and handshake | Decide *what* action to take; approve its own guardrails |
| **safety** | Independent review of everything in the write path: guardrails, audit log, dry-run, freshness checks, kill switch. Holds veto. | Implement the bridge it reviews |

`quant` and `data-engineer` are separate on purpose: resilient I/O against hostile APIs and statistical correctness are different skills with different failure modes. `bridge` and `safety` are separate on purpose: self-approval is the thing guardrails exist to prevent.

### The four readiness gates

Nothing merges without passing the gate matching its work type. Gates are cumulative where work spans types.

| Gate | Applies to | Requires |
|---|---|---|
| **Code** | All code | Lint, type-check, tests green |
| **Adapter** | Anything calling an external source | Recorded fixture committed + contract test; a separate live smoke test that is allowed to fail loudly and visibly |
| **Model** | Anything producing a number a decision rests on | Backtest against held-out seasons reporting **calibration**, not just accuracy; model card in `docs/models/` created or updated; explicit statement of what the model cannot see |
| **Automation** | Anything in the write path | Dry-run transcript attached + independent `safety` sign-off. No exceptions, including "trivial" changes |

### Owner-only decisions

Agents may not decide these. They escalate and stop:

- Anything that changes ToS exposure or the nature of Fantrax access
- Enabling autonomous mode, or widening its scope caps
- Any paid data subscription
- Anything acting on the real draft or a live lineup lock for the first time
- Accepting an ADR — agents write them as `Proposed` only

### Handoff contract

Every agent finishing a unit of work appends to `docs/handoff.md`:

- What changed, in one paragraph
- What is now true that was not true before
- **What it could not verify, and why** — this field is mandatory and "nothing" is rarely the honest answer
- Who is next and what they need from this work

The log is append-only. It is the project's memory, and it is the reason nothing important lives only in a chat.

### Seeded decisions

The decisions already settled in this planning conversation get committed as ADRs at handoff, so they are durable and challengeable rather than folklore:

- **ADR-001** Local-first architecture with a SQLite → Postgres seam
- **ADR-002** Separate per-game production from expected games played, fuse explicitly
- **ADR-003** G-score as the default valuation scheme for H2H
- **ADR-004** Fantrax access strategy: read via official API and `fantraxapi`, write only via the browser bridge
- **ADR-005** Automation is supervised by default; autonomous is opt-in, scope-capped, and `safety`-gated
- **ADR-006** External adapters isolated behind contract tests with recorded fixtures
- **ADR-007** Availability is a spine concern, modelled before valuation

---

## Availability & reliability — the core differentiator

This is the pillar that separates competing from winning, so it gets real engineering rather than a "games played" column.

### 1. Participation ledger

Every player, every scheduled team game, with an outcome and a reason code: played · DNP-CD · injury (with body part where stated) · rest / load management · personal · suspension · G-League assignment · inactive. Reconstructed historically from box scores and inactive lists so the model has multi-season training data rather than vibes.

### 2. Injury report ingestion

The NBA official injury report drops the evening before and updates on game day. Ingest status tags (OUT / DOUBTFUL / QUESTIONABLE / PROBABLE / AVAILABLE) and — importantly — **track their historical hit rates**. "Questionable" is not a coin flip and its true play rate varies meaningfully by team, by player, and by game context. That empirical conversion rate is itself a modelled quantity.

### 3. Availability model — p(play) per scheduled game

Per-player probability of suiting up for a specific upcoming game, conditioned on context rather than a flat season average:

- Second night of a back-to-back; 3-in-4, 4-in-5, 4-in-6 density
- Days of rest; road trip length and time zones
- Age, career minutes load, recent minutes spike
- Injury history, body part, and recurrence patterns
- Current injury report status (via its empirical conversion rate)
- Team situation: playoff position, elimination status, tanking posture
- Known individual patterns — some players simply never play B2Bs, and that's learnable

Output is a probability per game, which aggregates to **expected games played** over any window: rest-of-season, a fantasy week, or the fantasy playoff weeks specifically.

### 4. Reliability & consistency metrics

A durability scorecard per player, because two players with the same expected games can still carry very different risk:

- Availability rate, and its trend direction across the season
- B2B sit rate — the single most actionable availability pattern
- Minutes volatility (coefficient of variation)
- **Per-category nightly standard deviation** — feeds G-score directly
- Floor/ceiling percentiles per category
- Blowout-minutes suppression: players on lopsided teams lose fourth quarters
- Composite reliability grade, exposed everywhere a player is displayed

### 5. Late-season shutdown risk

Fantasy playoffs land exactly when eliminated teams start resting veterans and auditioning young players. Model shutdown probability for the fantasy playoff weeks from team elimination odds crossed with player age, minutes load, injury status and contract situation. Draft and trade-deadline decisions should price this in months ahead of time — this is routinely where good seasons die.

### 6. Contingent value — the stock up/down engine

A usage-redistribution graph: when player X sits, who gains, in which categories, and by how much. Built from historical with/without splits and validated against actual absence games.

This powers the thing you described directly:
- **Stock watch** — injury news lands, affected players are recomputed, and the dashboard surfaces who just moved and by how much
- Waiver-wire targeting the moment news breaks, ranked by *your* roster's category needs rather than generic value
- Handcuff awareness during the draft — knowing which late picks are one absence away from top-60 value
- Trade timing: buy low on a returning star, sell high on a temporarily inflated backup

---

## Schedule intelligence

Deeper than games-per-week, since the availability model consumes it and streaming lives on it.

- **Density:** games per fantasy week, back-to-backs, 3-in-4 / 4-in-5 / 4-in-6 stretches
- **Rest:** rest-days differential, road-trip length and structure
- **Off-nights:** light-slate NBA nights where streaming a spot start is cheap and high-value
- **Opponent context:** pace (possession volume drives counting stats), defensive profile by category, blowout likelihood
- **Fantasy playoff weeks:** schedule strength and game counts for the weeks that decide your season, surfaced during the draft — not in March
- **Week-level planning:** expected games = scheduled games × p(play), so the games-per-week grid shows *availability-adjusted* expectations rather than raw counts

---

## Draft formats & rehearsal

### Both formats are first-class

The league may be auction or snake this year — unknown at planning time, so both ship. Format is an abstraction alongside scoring profiles, not a fork in the code.

They are not variants of one another. Snake optimises pick-by-pick value against ADP and positional scarcity. Auction is a constrained budget-allocation problem with live price discovery. The math has almost nothing in common.

**Snake:** value over replacement against pick slot, ADP value and reach, positional scarcity, tier cliffs, and roster construction across the turn.

**Auction:**
- Dollar values derived from risk-adjusted G-score via value over replacement, scaled to the league's total budget pool
- **Live inflation tracking** — as money leaves the board, every remaining player's true price moves. If the top tier goes over value, everything after it deflates. This is the single largest edge available in an auction, and most managers eyeball it.
- **Max bid** — budget minus the $1 per unfilled roster slot you must reserve, recomputed continuously
- **Nomination strategy** — nominate players you don't want while opponents still have money; nominate your targets once they're budget-constrained
- **Budget burn rate vs. roster construction** — whether you're building stars-and-scrubs or balanced, and whether that's deliberate

Worth saying plainly: auction is materially more work than snake. It's also where the edge is largest, because inflation math is genuinely hard to do in your head under a bid clock. If it turns out to be auction, that's the good outcome for a tool like this.

### The overlay in auction mode

A different surface with different content: current nomination, your inflation-adjusted max bid, value versus the standing bid, budget and slots remaining, tier-exhaustion alerts. The pressure profile differs too — an auction gives you seconds rather than a minute, and what you need is one number, big and unambiguous.

### Ten-plus mocks, used for two different things

No fewer than ten mock drafts before the real one. They serve two distinct purposes and the plan keeps them separate:

**Fantrax mocks — the dress rehearsal.** Same DOM, same bridge, same overlay, same automation path. This is the only place the userscript and overlay get genuinely tested, and the rehearsal harness instruments it.

**External mocks (ESPN, Yahoo, FantasyPros, RTSports and similar) — the market corpus.** Different DOM, so no bridge rehearsal, but the *results* are valuable and captured by paste or CSV import:

- **Market model** — empirical ADP and auction price curves from real drafting behaviour, not published estimates
- **Model-vs-market divergence** — the report that actually matters. Where our valuation and the market disagree is exactly where the edge is, and it names the players to target and the ones to let go.
- **Opponent calibration** — simulated opponents in the draft simulator tuned from observed behaviour rather than invented priors

Ten mocks is a real corpus — enough to calibrate inflation curves and opponent models rather than guess at them.

---

## Automation safety model

You asked for both supervised and autonomous. Design applies to both, since the real risk is a bug, not detection.

**Supervised (default).** Backend computes a recommendation → overlay highlights it in Fantrax → you click to confirm.

**Autonomous (explicit opt-in, per-session).** Same pipeline, but the userscript actions it. Guardrails, all mandatory, all owned and signed off by `safety`:

1. **Kill switch** — one keypress halts all pending actions; also auto-halts on backend disconnect.
2. **Dry-run mode** — full plan logged with no DOM interaction. Default for every new action type.
3. **Validity precheck** — roster legality, position eligibility, IR rules, games-remaining, lock status verified before any action is queued.
4. **Scope caps** — autonomous draft is bounded to an explicit N rounds; expires and reverts to supervised.
5. **Confidence floor** — if the top recommendation isn't clearly separated from the next, it escalates to you instead of acting.
6. **Availability freshness check** — never auto-set a lineup on stale injury data; if the injury report hasn't been refreshed within a threshold, escalate rather than act.
7. **Human-paced execution** — actions are paced and sequenced as normal interaction; no burst traffic that could destabilize the page or trip rate limits.
8. **Full audit log** — every action recorded with timestamp, trigger, inputs, recommendation, and outcome. Reviewable and diffable after the fact.

Note kept in `docs/`: this operates your own account on your own team. Fantrax natively ships auto-draft and auto-subs, so the *category* of automation is sanctioned; the implementation path is not. Read paths are low-risk, write paths are the ToS-grey part, which is why they're isolated in one swappable module behind an independent reviewer.

---

## Data model (core entities)

- **Identity** — `players` (canonical), `player_external_ids` (source, source_id, confidence), `nba_teams`
- **Stats** — `nba_games`, `player_game_logs`, `player_season_stats`
- **Availability** — `player_participation` (game, status, reason_code, minutes), `injury_reports` (report_time, status, description), `injury_status_conversion` (empirical status → play rate), `availability_predictions` (game, p_play, driver features, model version), `reliability_metrics` (window, availability rate, B2B sit rate, minutes CV, per-category std dev, floor/ceiling, grade), `shutdown_risk`
- **Contingent value** — `absence_splits` (with/without production deltas), `usage_redistribution` (absent player → beneficiary → category delta), `stock_movements` (trigger, value before/after, driver)
- **Schedule** — `team_schedule`, `schedule_density` (B2B, 3-in-4, 4-in-6, rest diff), `off_night_slates`, `opponent_context` (pace, category defence, blowout risk). Fantasy week boundaries live on `scoring_periods` under League — a fantasy week *is* a scoring period, and two tables that must agree with nothing enforcing agreement is a bug waiting to happen. Add a league-independent NBA week calendar only if streaming analysis later proves it necessary.
- **League** — `leagues`, `league_scoring_profiles`, `fantasy_teams`, `roster_slots`, `rosters`, `scoring_periods`, `matchups`, `matchup_category_results`, `transactions`
- **Projections** — `projection_sources`, `projection_imports`, `projections` (per-game rates), `source_games_played_assumptions`, `blend_profiles`, `blended_projections`, `expected_games`
- **Valuation** — `scoring_profiles`, `punt_configs`, `valuations`, `risk_adjusted_valuations`, `replacement_levels`
- **Draft** — `drafts`, `draft_picks`, `draft_boards`, `adp_snapshots`
- **Decisions** — `trade_scenarios`, `trade_evaluations`, `lineup_plans`, `automation_actions`
- **Bridge** — `bridge_payloads` (raw captured JSON, for replay and debugging)

**Highest-risk foundational item: player identity.** Fantrax IDs, NBA IDs, and projection-CSV name strings all disagree. Resolution is Fantrax `getPlayerIds` + `nba_api` roster as the anchor pair, then normalized-name + team + position matching for CSVs, with a confidence score and a manual-override UI for the tail. Getting this wrong silently corrupts every downstream number, so it ships with its own test suite and an unmatched-players report.

---

## Todos

Tracked in SQL by ID. Phases are ordered by dependency; the spine (0–5) must land before feature work.

**Phase 0 — Governance & handoff** · owner: `architect`
- `repo-create` — Create `SR2501/hoops-gm` and push the initial commit carrying this plan and the governance artifacts, so nothing important lives only in a chat.
- `governance-docs` — `AGENTS.md` entry point, ownership matrix, the four gates, owner-only decision list, risk register.
- `agent-definitions` — The seven invocable agent definitions in `.github/agents/`.
- `handoff-log` — Initialize `docs/handoff.md` with current state and the first entry.
- `seed-adrs` — ADR-001 to ADR-007 capturing decisions already made, written as `Proposed`.

**Phase 1 — Foundations** · owner: `backend`, `frontend`
- `repo-scaffold` — Monorepo layout, licence, README, `.gitignore`, `.env.example`.
- `backend-skeleton` — FastAPI app, config/settings, structured logging, health endpoint, pytest + ruff + mypy.
- `db-foundation` — SQLAlchemy setup, Alembic migrations, core schema, session management.
- `frontend-skeleton` — Vite + React + TS, routing, API client, layout shell, component conventions.
- `ci-pipeline` — GitHub Actions enforcing the Code gate; hooks for the Adapter and Model gates.

**Phase 2 — Data spine** · owner: `data-engineer`
- `nba-stats-ingest` — `nba_api` adapter with throttling, retry, caching. Multi-season backfill including inactive lists and DNP reasons.
- `player-identity` — Crosswalk resolver, confidence scoring, unmatched report, manual-override UI.
- `fantrax-official-adapter` — `/fxea/general/` client: `getPlayerIds`, `getAdp`, `getLeagueInfo`, `getDraftPicks`.
- `fantrax-private-adapter` — `fantraxapi` integration, encrypted cookie storage, re-login flow, roster/matchup sync.
- `adapter-contract-tests` — Recorded fixtures + CI contract tests so upstream schema drift fails loudly.

**Phase 3 — Schedule intelligence** · owner: `data-engineer`, `quant`
- `schedule-ingest` — Season schedule, fantasy week definitions, per-week game counts.
- `schedule-density` — B2Bs, 3-in-4 / 4-in-5 / 4-in-6, rest differentials, road-trip structure.
- `schedule-context` — Off-night light slates, opponent pace, per-category defensive profiles, blowout likelihood.
- `playoff-schedule` — Fantasy playoff week schedule strength and game counts.

**Phase 4 — Availability & reliability engine** · owner: `quant`
- `participation-ledger` — Historical per-player, per-game participation with normalized reason codes.
- `injury-report-ingest` — NBA official injury report ingestion with status history.
- `injury-status-conversion` — Empirical status → actual play rates, segmented by team, player and context.
- `availability-model` — Per-game p(play) conditioned on density, rest, age, load, injury history, report status and team situation. Stores driver features for explainability.
- `reliability-metrics` — Durability scorecard: availability rate + trend, B2B sit rate, minutes volatility, per-category std dev, floor/ceiling, blowout suppression, composite grade.
- `shutdown-risk` — Late-season shutdown/tanking risk for fantasy playoff weeks.
- `absence-splits` — Historical with/without production splits per player pairing.
- `contingent-value` — Usage-redistribution graph powering stock movement and waiver targeting.
- `availability-backtest` — Backtest harness scoring **calibration**, satisfying the Model gate.

**Phase 5 — Projections & valuation** · owner: `quant`
- `csv-importer` — Generic importer with per-source column profiles; captures each source's embedded games-played assumption separately.
- `projection-blending` — Weighted blending of per-game production across sources, with manual overrides.
- `baseline-model` — Own per-game production model from historical logs.
- `expected-games` — Fuse per-game production with availability model expected games.
- `scoring-profiles` — Abstraction so points/roto slot in later without rewriting the engine.
- `zscore-engine` — 9-cat z-scores with volume-weighted FG%/FT% impact and TO sign handling.
- `gscore-engine` — G-score absorbing both production and availability variance. Default for H2H.
- `risk-adjusted-valuation` — Durability discount/premium; separate total-value and per-game-value views.
- `punt-builds` — Punt-config modelling, recomputed rankings, comparison, fit-to-my-roster scoring.

**Phase 6 — Live scorecard** · owner: `backend`, `frontend`
- `live-poller` — `cdn.nba.com` poller, active only during live games, ~5s interval, with backoff.
- `live-matchup-state` — Live box scores mapped onto my roster with availability-adjusted games remaining.
- `scorecard-ui` — Live scorecard via SSE: category win/loss/margin, projected final with confidence bands.

**Phase 7 — Schedule & availability UI** · owner: `frontend`
- `schedule-ui` — Games-per-week grid showing availability-adjusted expected games, streaming windows, playoff planning.
- `reliability-ui` — Durability scorecards, B2B sit patterns, availability trends, roster fragility summary.
- `stock-watch` — Live value-mover dashboard: news → recompute → who moved, why, and are they available.

**Phase 8 — Draft** · owner: `quant`, `frontend`
- `draft-format-abstraction` — Snake and auction as first-class formats alongside scoring profiles, so neither is a special case bolted onto the other.
- `draft-tracker` — Live draft state for both formats, pick/nomination board, roster construction view.
- `draft-recommender` — Snake: VOR against pick slot, ADP value and reach, positional scarcity, tier cliffs — with durability, shutdown and handcuff flags.
- `auction-values` — Risk-adjusted G-score → dollar values via VOR scaled to the league budget pool.
- `auction-inflation` — Live inflation tracking as money leaves the board; continuously restated prices for the remaining pool.
- `auction-budget-manager` — Max bid net of the $1-per-unfilled-slot reserve, budget burn rate, and roster-construction shape.
- `auction-nomination` — Nomination strategy: drain opponent budgets early, surface targets once they're constrained.
- `dashboard-evidence-views` — The "why" behind every overlay recommendation: category math, punt-fit breakdown, durability and shutdown detail, contingent value, schedule context, and inflation state in auction.
- `mock-ingestion` — Capture results from external mock sites (ESPN, Yahoo, FantasyPros, RTSports) by paste or CSV, resolved through the identity layer.
- `market-model` — Empirical ADP and auction price curves built from the mock corpus.
- `model-vs-market` — Divergence report naming where our valuation disagrees with the market. This is the edge, stated explicitly.
- `opponent-calibration` — Tune simulated opponents from observed mock behaviour rather than invented priors.
- `draft-simulator` — Mock drafts for both formats against calibrated opponent models, including durability-weighted and stars-and-scrubs strategies.
- `rehearsal-harness` — Instruments the Fantrax dress-rehearsal mocks (10+): overlay sufficiency per pick, dashboard opens and what was checked, time-to-decision, recommendation take rate. Produces an evidence-based answer on whether a second monitor is actually needed.

**Phase 9 — Tampermonkey bridge** · owner: `bridge`
- `userscript-foundation` — Build pipeline, `@match` rules, shared-secret handshake, `GM_xmlhttpRequest` transport.
- `bridge-capture` — Intercept `fetch`/XHR against `/fxpa/req`, normalize and POST payloads to backend.
- `bridge-overlay` — Shadow-DOM overlay rendering recommendations in place on Fantrax pages.
- `overlay-draft-panel` — Snake draft surface: compact, collapsible, keyboard-toggled, positioned to never obscure the draft board or player list. Must be sufficient to make a pick without leaving the tab.
- `overlay-auction-panel` — Auction surface: current nomination, inflation-adjusted max bid, value vs. standing bid, budget and slots remaining, tier-exhaustion alerts. Optimised for a seconds-long bid clock.
- `surface-parity-tests` — Enforce that no draft-critical decision is overlay-only or dashboard-only, as a test rather than a convention.

**Phase 10 — Automation** · owner: `bridge`, gated by `safety`
- `action-protocol` — Typed action schema, backend command queue, userscript executor, result reporting.
- `automation-guardrails` — Kill switch, dry-run, validity precheck, scope caps, confidence floor, freshness check, pacing.
- `automation-audit` — Full audit log + review UI for every planned and executed action.
- `supervised-mode` — Highlight-and-confirm flow for lineup and draft decisions.
- `autonomous-mode` — Opt-in autonomous execution bounded by all guardrails. Owner-only to enable.

**Phase 11 — Lineup manager** · owner: `quant`, `bridge`
- `lineup-optimizer` — Optimal daily/weekly lineup from projections × p(play), density, category needs, roster rules.
- `streaming-engine` — Off-night streaming targeting weakest categories by expected marginal impact.
- `lineup-autoset` — Scheduled auto-set with pre-lock injury refresh, routed through the guardrails.

**Phase 12 — Trade evaluator** · owner: `quant`
- `trade-evaluator` — Category deltas, punt impact, playoff-week impact, RoS value, durability/shutdown risk both sides.
- `trade-finder` — Scan league rosters for mutually beneficial trades from surplus/deficit and risk-tolerance differences.

**Phase 13 — Sharing** · owner: `backend`
- `multi-user` — Auth, per-user Fantrax credentials, league scoping.
- `deployment` — Docker Compose, Postgres migration path, backup/restore runbook.

---

## Notes & considerations

- **Governance is thin on purpose.** Seven personas, four gates, one append-only log. If it starts costing more than it prevents, cut it — `architect` owns that call and should be willing to make it.
- **Availability is the edge, so it's in the spine.** Phase 4, before valuation, because it's an input to it. Building valuation first and retrofitting availability means rewriting the valuation layer.
- **Separate production from availability, always.** Keeping them separate is what lets you answer "is this guy good, or just present?" and price the two differently.
- **Calibration beats accuracy for p(play).** A model that says 70% and is right 70% of the time is more useful for lineup decisions than one with a better raw hit rate but overconfident probabilities. The Model gate scores calibration explicitly.
- **Draft day is a hard deadline.** Phases 0–5, 8 and 9 must be done and rehearsed before your draft. Phases 6–7 and 11–12 can land during the season. No fewer than ten mocks, with the Fantrax ones serving as true dress rehearsals against the real UI.
- **Auction is the scope risk worth taking.** Building both formats is meaningfully more work than snake alone, and until the format is confirmed both must be ready. If it lands on auction, the inflation engine is the largest single edge in the whole tool — nobody does that math well under a bid clock.
- **Confirm the format as early as you can.** It doesn't change the spine, but it changes what gets rehearsed and where the last few weeks of effort go. Worth asking the commissioner well before draft day.
- **One screen is the design target.** Fantrax only has to be open and foreground for the live draft and for lineup writes; everything else runs without it. The overlay must be sufficient on a laptop, and the rehearsal harness measures whether it actually is rather than assuming.
- **Percentage categories are the classic bug.** FG%/FT% must be modelled as volume-weighted impact, not raw percentage; a 90% FT shooter on 1 attempt is not valuable. This is where most homebrew tools go wrong.
- **Reason codes will be messy.** DNP reasons are inconsistently reported and "rest" is often laundered as a minor ailment. Expect a normalization layer with manual mapping, and don't over-trust stated reasons; the model should lean on observed patterns over official explanations.
- **Upstream fragility is expected, not exceptional.** Contract tests and the raw `bridge_payloads` table exist so breakage is diagnosable rather than mysterious.
- **Projection data is personal-use only.** No redistribution of imported projections if this is ever shared with leaguemates.
- **Deliberately excluded:** Basketball-Reference scraping (data-use policy), paid enterprise feeds (SportsDataIO/Sportradar — cost-prohibitive). BALLDONTLIE All-Star at $9.99/mo remains a cheap fallback if `cdn.nba.com` becomes unreliable.
