# OPEN: Roster-level reliability prerequisites

**Raised:** 2026-09-06 by `frontend`
**Status:** Open. Owner-blocked identity evidence and quant semantics are missing.

`reliability-ui` cannot honestly render its roster-level fragility summary yet.
Two independently owned inputs are absent:

1. **Fantasy-roster identity (`Fantrax ingestion` -> `backend`).** The database
   schemas already exist, but `leagues`, `fantasy_teams`, `rosters`, and
   `roster_slots` each hold zero rows. Backend cannot expose membership it does not
   have. The missing evidence depends on owner-blocked Fantrax ingestion from a live
   draft room. `docs/governance/OPEN-draft-day-deliverable.md:131-136` requires at
   least one completed sale; during it, `docs/mocks/instrumented-capture.md:113-116`
   defines the `capture_order_disputed` check. Once captured, a typed read endpoint
   must identify the league and fantasy team, state membership time and lineage, and
   carry canonical `player_id` values joinable to reliability scorecards.
2. **Fragility semantics (`quant`).** Quant must define the roster-level composite,
   including how player evidence is combined, how missing and explicit-unknown
   observations affect the result, and what evidence accompanies the displayed
   number. The Model gate applies before frontend consumption. This note deliberately
   does not propose that formula.

The current absence is checkable in under ninety seconds. As observed on 2026-09-06,
`GET /api/v1/reliability/scorecards` returned 596 cards whose only top-level card
fields were `player_id`, `player_name`, `availability`, and `production`.
`GET /openapi.json` exposed no roster endpoint. In the repository,
`frontend/src/routes/ReliabilityPage.tsx:144-147` therefore renders
“No roster fragility summary is shown” and refuses to infer either membership or
math.

Frontend work becomes actionable only when both contracts exist. A player-level
cohort, draft holdings, or guessed aggregation is not a substitute for either one.
