# OPEN: Roster-level reliability prerequisites

**Raised:** 2026-09-06 by `frontend`
**Status:** Open. Backend and quant contracts are missing.

`reliability-ui` cannot honestly render its roster-level fragility summary yet.
Two independently owned inputs are absent:

1. **Fantasy-roster identity (`backend`).** An approved source must publish the
   current fantasy roster through a typed read endpoint. Its response must identify
   the league and fantasy team, state the membership's effective time and source
   lineage, and carry canonical `player_id` values that join to reliability
   scorecards. This note does not select the source or route.
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
