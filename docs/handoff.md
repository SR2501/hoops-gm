# Handoff log

**Append-only.** Newest entries at the bottom. Do not edit or delete previous entries; if something recorded here turns out to be wrong, add a new entry saying so.

This is the project's memory. It exists because material produced in conversation becomes unfindable the moment the screen changes. If it is worth returning to, it is written here or elsewhere in this repository — never only in a chat.

## Entry format

```
## YYYY-MM-DD — <agent> — <what was worked on>

**Changed:** one paragraph.
**Now true:** what is true that was not true before.
**Could not verify:** MANDATORY. "Nothing" is rarely the honest answer.
**Next:** who is next and what they need from this.
```

---

## 2026-08-17 — planning — Project inception and governance

**Changed:** Created the repository and its governance layer from a planning conversation on 2026-08-17. Committed `docs/plan.md` (the full plan), `AGENTS.md` (entry point), seven agent definitions in `.github/agents/`, four governance documents, and ADR-001 through ADR-007 recording decisions reached during planning.

Research was conducted before planning and is summarised in the plan's research findings table. Key constraints established: Fantrax offers a limited official read API and no write API of any kind; `fantraxapi` reads private leagues via a session cookie; live NBA scoring is free from `cdn.nba.com` at 1–5s latency; `nba_api` is maintained and is the historical stats source; Basketball-Reference is excluded on data-use policy grounds; G-score (arXiv 2307.02188) outperforms z-score in H2H.

**Now true:**
- `SR2501/hoops-gm` exists as a private repository with the plan and governance committed. Nothing important lives only in a chat transcript.
- The build is scoped at 75 tracked work items across 14 phases, with a dependency graph containing no cycles and a single root.
- The spine order is fixed: identity → schedule → availability → projections → valuation, then features. Availability precedes valuation because it is an input to it (ADR-007).
- Both snake and auction draft formats are in scope as first-class engines. The league format for this season is not yet confirmed.
- Seven agents, four readiness gates (Code, Adapter, Model, Automation), and a defined owner-only decision list are in force.

**Could not verify:**
- **The league's draft format.** Auction is likely but unconfirmed. Both are planned; confirmation determines where late-stage rehearsal effort goes.
- **Whether the Fantrax official API endpoints behave as documented.** No live call has been made. `getPlayerIds`, `getAdp`, `getLeagueInfo` and `getDraftPicks` are documented as beta and sparsely specified — the first data-engineer task should verify each against a real request before anything is built on them.
- **Whether `fantraxapi` works against an NBA H2H category league.** Its author developed and tested it against an NHL H2H points league and explicitly notes results may vary by sport and format.
- **Whether the availability model is achievable at the fidelity the plan assumes.** Historical DNP reason codes are inconsistently reported and "rest" is frequently laundered as a minor ailment. The data may not support the granularity described; the backtest harness is the check on this.
- **Whether the overlay can be sufficient without a second monitor.** Designed for one screen, but unproven. `rehearsal-harness` is instrumented specifically to answer this with evidence rather than opinion.
- **Any calibration or accuracy claim.** No model exists yet. Every number in the plan describing model behaviour is an intention, not a measurement.
- **That the governance overhead is worth it.** Seven agents and four gates for a solo project is a judgement call. `architect` owns the decision to cut it if it costs more than it prevents.

**Next:** `architect` to review the seeded ADRs and the phase sequencing, then `backend` and `frontend` to scaffold Phase 1 (FastAPI skeleton, database foundation, Vite/React skeleton, CI enforcing the Code gate). `data-engineer` should independently verify the Fantrax official endpoints early, since several plan assumptions rest on them.

**For the owner:** the seven ADRs are `Proposed` and await acceptance. Confirming auction vs snake with the commissioner is the most useful early input — it does not change the spine, but it decides where the final weeks of effort go.
