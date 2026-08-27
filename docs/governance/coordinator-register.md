# Coordinator register

**What this is.** The coordination layer of the 2026-08-26 session, and of the
sessions before it: rules derived, defects observed, traps published, near
misses, and the record of who corrected whom. It lived in a session-scoped
SQLite table until it was committed here, which meant the project's own
"nothing important lives only in a chat" rule was being broken by the artefact
enforcing it.

**This is a record of findings and rules. It is not a task list.** That
distinction is the reason for the paragraph below, and getting it wrong once
already produced a confident, well-instrumented, wrong number.

## How to read `**Status:**`, because it does not mean what it looks like

Every entry carries a `**Status:**` line with one of `done`, `pending`,
`in_progress` or `blocked`. **`pending` here means "recorded", not "awaiting
work".** The values were set by one convention: `done` was written when an entry
recorded a *completed event* - a merge, a retraction, an author's error - and
`pending` was written for **everything else**, including pure observations with
no action attached at all. `c292`, *"collection is not execution"*, is `pending`
and is a rule nobody will ever "do".

**This was established the hard way and the sequence is worth keeping.** A
reader classified these entries by regular expression on their headings, was
corrected by finding the `Status:` field, controlled that field properly - every
entry whose title reports a completed event does read `done` - and concluded
from it that 295 entries were open tasks. The control was sound and the
conclusion was still wrong, because **the field distinguishes done-events from
non-done-events, which is not the same property as "does somebody have to act on
this".** That property is recorded nowhere. Neither the heading nor the status
observes it, and only reading the entry does.

So: do not count this file. Do not treat `pending` as a backlog. **The entries
that name real, unscheduled work were promoted into `docs/backlog.md`, where
`scripts/backlog_graph.py` holds them and a dangling edge fails CI**, and one
backlog item covers reading the rest of this file for any that were missed.

## What was removed, what was nearly removed, and what was never read

**12 entries were dropped** from the 332 in the session
table: three self-declared duplicates that say *"do not land separately"* in
their own first line, four records of an event whose real artefact is a merge
commit, and five narrations of completed work units whose findings are already
in `docs/handoff.md`. Every dropped id is listed in the commit that created this
file, each with its own reason.

**13 more were on the deletion list and were kept after being read.**
That list shrank from 25 to 12 across three passes, and every
reduction came from opening the entry rather than from a better pattern - the
first pass would have deleted a published trap aimed at the availability model,
a rule already adopted into `gates.md`, and the observation that **4 October is
the real deadline while 18 October is only when the consequences arrive**. **A
deletion is the one operation that leaves no evidence**, so the near misses are
recorded alongside the removals.

**Every entry here was read during the removal pass.** The register did not grow
between the pass and this build.

---

## `c1-r55-placeholder-pair` - Recording R55: a placeholder pair is internally consistent

**Status:** pending

Risk register entry, to land in the coordinator closure PR (not in any in-flight lane PR, to avoid docs/backlog.md + docs/handoff.md conflict surface across #49/#48/#45/#47). Wording: a placeholder pair is internally consistent, so any check that verifies two representations agree will pass on a value that is wholly fabricated. Cross-field reconciliation validates encoding, never meaning. Same shape as the gameEt finding in AGENTS.md, arriving from the opposite direction. Evidence: NBA emits 1900-01-01 in gameTimeEst on every resolved game in the committed fixture; the EST/UTC reconciliation agrees exactly on such a pair. Found by the schedule-import lane round seven.

## `p1-owner-page` - Drafting the owner definition-of-done page

**Status:** pending

Create docs/what-draft-day-looks-like.md as a SKELETON OF QUESTIONS only - the owner writes the answers and I never edit it. What he wants to be able to do at 7pm on 18 October, in the order he will want to do it. THIS IS THE ANTI-DRIFT DEVICE: any unit that cannot trace to a line on his page gets deferred, so scope arguments become pointing at the page rather than debating priorities.

## `n2-grid-pending` - Showing pending instead of a false zero

**Status:** pending

frontend, stacked on n1: DAL/LAL read 0 in Cup week when their games are not yet scheduled. Surface pending so the cell says not-yet-scheduled rather than no-games. Released when n1 contract is stable.

## `c2-boxscore-date-bound` - Filing: does the plausibility bound belong on the box-score date path

**Status:** pending

Backlog item for docs/backlog.md, to land in the coordinator closure PR. The injury-cohort path derives game dates from box scores through a different adapter than ingest/nba/schedule.py, and the resolved-side plausibility bound added in PR #49 does not touch it. Named consequence: the same player_participation join and therefore the same expected-games denominator. Explicitly NOT scope for #49 - it was kept out to avoid a seventh round. Needs an owner: data-engineer.

## `p2-mentor-lane` - Creating the mentor lane as an owner-created sibling

**Status:** pending

A standing agent whose only job is the owner: plain-language note after each merge saying what changed and what he would have needed to know to make that call himself; answers "what am I looking at" without jargon; maintains docs/learning-log.md which is HIS. IT REVIEWS ME, NOT THE CODE - so the OWNER must create it as a sibling session, not me as a child, otherwise the thing being checked can dismiss its own checker. Same rule that keeps safety independent of bridge.

## `c3-guard-passes-wrong-reason` - Extending the docstring-attribution paragraph in gates.md (NOT a fifth bullet)

**Status:** pending

For the coordinator closure PR. Wording: a guard that passes for a reason other than the one claimed is indistinguishable from a guard that works, until the neighbouring case arrives. Earned five times across five lanes tonight. Cleanest instance: the year-0001 sentinel was caught only because America/New_York ran on -04:56 local mean time before 1883, not by any rule about sentinels - move the placeholder to 1900 and it reconciles cleanly. Arrived through a PASSING test, which is why no gate could surface it. Land as ONE statement, not a fifth variant of the mutation bullet, per the prose-cost rule merged as fcaacc9.

PLACEMENT CORRECTED after reading gates.md line 24 on merged main rather than assuming. That paragraph ALREADY says: "red is not enough on its own: mutate the thing the docstring NAMES, and check the failure matches the docstring's story." That is this rule in one specific form, and adding a fifth bullet would be a restatement - exactly what the prose-cost rule forbids.

THE GENUINE DELTA, and it is why this still belongs: line 24 covers RED FOR THE WRONG REASON (a mutation that reddens against a neighbouring condition). This covers GREEN FOR THE WRONG REASON, which no existing bullet reaches, and which arrives through a PASSING test that nobody is mutating. Canonical instance: the year-0001 sentinel guard was cited as evidence the classifier handled sentinels; it was only catching a pre-1883 timezone artefact, because America/New_York ran on -04:56 local mean time before 1883 and so the value misses reconciliation by four minutes. Move the placeholder one convention over to 1900 and it reconciles cleanly and passes. The guard had never done the job it was credited with.

So: land as TWO SENTENCES EXTENDING that paragraph, not as a new bullet. Both halves are attribution failures and belong in one place.

CROSS-REFERENCE c1 (R55) rather than restating it: R55 is about what a CHECK can establish (cross-field agreement validates encoding, never meaning); this is about what a PASS can establish. Different actions - one changes how you design a check, the other changes how you credit a green - so both are kept, but each states its mechanism once and points at the other.

## `p3-cut-backlog` - Splitting the backlog into deadline set versus deferred

**Status:** pending

141 items reads as a plan and is a superset. The draft-day chain is about twelve: injury-status-conversion -> availability-model -> expected-games -> zscore -> gscore -> risk-adjusted-valuation -> auction-values -> auction-budget-manager + auction-inflation -> draft-recommender, plus overlay-auction-panel. Everything else - live scorecard, schedule UI, lineup manager, trade evaluator - is explicitly cuttable per plan.md:658. Make the distinction visible in the file.

## `c4-worktree-isolation` - Recording the reviewer-worktree isolation rule

**Status:** pending

For the coordinator closure PR, in docs/governance/gates.md beside the mutation bullets. A reviewer that mutates code needs its own detached worktree. Observed in the schedule-import lane: a reviewer mutation and author edits collided in a shared worktree; the reviewer left a narrowed constant behind, produced a JSONDecodeError in an unrelated suite that looked like a real failure, and had its own mutation clobbered by an author write producing a BRIEFLY FALSE GREEN. Both directions produce a green that means nothing.

## `p4-inbox-format` - Replacing the inbox format with decisions first

**Status:** pending

At most THREE decisions, each with options, a recommendation, and what happens if he does nothing. Findings he cannot act on go to the register and reach him only if they change a date or need a decision. If I have more than three, I have failed to prioritise and that is mine to fix before it reaches him.

## `c5-where-else-is-this-true` - Landing the two scope-of-application questions as ONE gates.md entry

**Status:** pending

For the coordinator closure PR, in docs/governance/gates.md under "What gates cannot catch" - as a habit, explicitly not a gate. Wording from the schedule-import lane, which earned it three times in one unit: a fix written while reasoning about one branch does not automatically get asked "where else is this true?" - and nothing in a normal process asks it. The three instances: (1) plausibility bound applied to the lenient path and not the strict one, where the strict one persists and joins player_participation; (2) the date-absent-iff-reason-present invariant enforced on read and not on construction; (3) OverflowError absorbed on one branch and not its sibling, so an out-of-range value bypassed the exit-code channel the same unit had just added exit 5 to make trustworthy. Each time the guard was written correctly and applied to one of the two places it belonged, and each time a reviewer found the other. The question is cheap; the absence of anyone asking it is the defect.

CONSOLIDATED with c6 (do not land separately). These are a PAIR and land as one entry with two bullets under "What gates cannot catch", not as two entries - the prose-cost rule merged as fcaacc9 applies to the coordinator first.

BULLET 2 (was c6), the inverse: new code placed OUTSIDE an existing guard's protection, so the guard silently stopped covering what it was written for. Instance: _plausible_season_date catches ValueError so an odd season string is lenient and can never decide whether a real schedule imports - but the two date() window constructions were placed outside that try, and date() raises ValueError for a year outside 1..9999, so a season leading with a year <= 5 crashed uncaught with rc=1. Same crash-instead-of-typed-refusal class the OverflowError translation in the SAME COMMIT existed to remove, reintroduced two functions away by the commit that removed it. The question is: "what was already protecting this line, and is it still?"

WHY ONE ENTRY: the pairing IS the content. "Where else is this true?" and "what was already protecting this line?" have different blind spots and neither implies the other; a reader given only one will systematically miss the other class. Both are scope-of-application defects. No gate looks at scope of application.

## `p5-slack-number` - Reporting one slack number against 4 October weekly

**Status:** pending

One figure, recomputed from the backlog rather than recalled. 4 Oct is the real deadline (plan.md:658 - 18 Oct is only when the consequences arrive). If slack goes negative the cut list is Phases 6, 7, 11, 12 and it comes to the owner as a decision rather than being made quietly.

## `p6-early-rehearsal` - Scheduling a throwaway mock rehearsal in the week of 6 September

**Status:** pending

The plan starts mocks 5 Oct. Run ONE throwaway auction mock in two weeks on whatever exists, even if embarrassing - not to succeed but to find what is missing while there is time to build it. IF WE CANNOT RUN A MOCK BY 6 SEP THAT IS THE SIGNAL TO CUT FEATURES, four weeks earlier than the current plan would surface it. This is the only real protection against a pretty shell that fails on draft day.

## `c7-green-before-mutating-extension` - Recording that green-before-mutating also catches false test claims

**Status:** pending

For the coordinator closure PR, as an addition to the existing mutation bullets in docs/governance/gates.md - one clause, NOT a new variant, per the prose-cost rule. The assert-green-before-mutating rule was authored to stop a mutation that proves nothing. It has now twice caught something else: a test that ASSERTS THE WRONG THING. Schedule-import lane instance: a new test asserted season 9993-94 goes lenient; it does not, because that season builds a valid window and 2026 is legitimately outside it. The green check failed before the mutation ran, so a test encoding a false claim was never committed. Earlier instance in the same lane: a replacement string that silently never applied. Neither use was anticipated when the rule was written.

## `p7-agentic-os` - DEFERRED to after 4 October - extracting the agentic-OS layer

**Status:** pending

The reusable artefact built here that has nothing to do with basketball: a ~240-entry defect register mostly about how VERIFICATION fails; a parallel-agent merge protocol (freeze windows, base assertions, predicted-union checks); gates with named owners and a veto; and the pre-archive question, which has three times recovered work about to be destroyed. Extract to docs/agentic-os/ AFTER 4 Oct. Recorded so it is deferred rather than silently dropped - the owner named this as the actual vision.

## `c8-when-a-round-stops-paying` - Recording when a review round stops paying

**Status:** pending

For the coordinator closure PR, in docs/governance/gates.md beside the prose-cost section. This is REVIEW PROCESS and belongs to the coordinator, not to any adapter doc - the schedule-import lane explicitly declined to record it in its own file for that reason, and to avoid restarting the PostgreSQL runs the queue was blocked on. Two arguments for stopping a review round, and only one of them terminates: (1) DIMINISHING RETURNS - the gradient of severity is steep and the remaining risk is concentrated in an exhaustively characterised function. True but it never quite says stop, because there is always one more round with some expected value. (2) TERMINATION - once a round begins finding defects in code the PREVIOUS round wrote, a further round examines the previous fix. That regress does not end on evidence, because each round genuinely produces some; it ends only on judgement. The second is the one that licenses stopping. Evidence: schedule-import took 8 rounds; round 8 found a defect in a guard round 7 had just added. Projections lane measured the same shape over 6 rounds - 2 behavioural defects, the rest prose created by the rounds that fixed them.

## `p8-ledger-backup` - DECISION NEEDED - the participation ledger is one copy with no backup

**Status:** pending

43,037 rows at C:\Users\steverones\hoops-gm-data\hoops_gm.db, the unblock the whole spine now rests on, single copy. AND a guard meant to protect it does not: three separate safety checks all pass against it because each keys on a proxy (leagues, current season, prior BBM import) and none looks at the participation rows themselves. It survives today only because its schema is old enough that a later seeder crashes and rolls back - one alembic upgrade head removes that. #81 fixes the guard. The backup is a separate owner decision.

## `c9-coordinator-claim-least-checked` - Recording R56: a coordinator's claim is the least-checked claim

**Status:** pending

For the coordinator closure PR, docs/governance/risks.md. R52 says a self-reported defect is the claim a reviewer is least likely to verify. R56 is its structural sibling: a claim relayed BY THE COORDINATOR arrives with the authority of someone synthesising across lanes, so a lane is least likely to check it - and the coordinator is the one participant with no reviewer. Incident, 2026-08-21 02:52: I told the player-position lane that PR #49 had corrected the cohort watch set by dropping db/lineage.py and adding ingest/nba/schedule.py. Inferred from earlier lane reports, never run. Both halves false - #49 changed ONLY the manifest and deliberately left DEFAULT_SOURCE_FINGERPRINT_PATHS untouched, because editing cohort_evidence.py stales its own digest. The claim was made INSIDE the instruction "establish why the fingerprint moved before you regenerate, never the reverse" - i.e. the coordinator did the exact thing the message forbade. Consequence had it stood: build_manifest computes from the constant, so regeneration reinstates db/lineage.py with digest 6797cb33, a value the cohort was never derived with (it used 8181cf7e; #49 deleted b2f6356e), asserting a Dec-2025 cohort was derived with post-ADR-013 code. It would have READ AS NEW INFORMATION rather than an undone deletion, with the coordinator's explanation the only one on offer. Caught within minutes by the #49 lane, which measured rather than reasoned. Mitigation that worked: keeping the producing lane reachable rather than archiving it at merge.

REFINEMENT from the schedule-import lane, and this is the form to LAND rather than my original: "a coordinator's claim is least-checked" is a true observation but a poor rule, because it argues for lanes checking coordinators generally, which does not scale and depends on the producing lane still being alive and holding the right file in working memory - a property that decays at archive time. The lane caught my error for an unremarkable reason: it had the manifest change in working memory, so a one-line description was falsifiable to it at zero cost. Not reproducible.

The generalisable rule is narrower, cheaper, and unilateral on the coordinator side: A CLAIM ABOUT WHAT ANOTHER LANE'S CHANGE DID MUST BE SOURCED FROM THAT LANE OR FROM THE DIFF, NEVER SYNTHESISED FROM ITS REPORTS. The failure was in compression, not in either input - the lane's summaries were accurate and my synthesis of them was not. A coordinator can guard this without depending on anyone else being reachable.

Land R56 as the rule with the incident as its evidence; do not land the "least-checked" framing as an instruction to lanes.

## `c10-fingerprint-backlog-sentence` - Landing the missing sentence in schedule-cohort-fingerprint-list

**Status:** pending

For the coordinator closure PR, docs/backlog.md, appended to the "removal half" paragraph of the schedule-cohort-fingerprint-list item. The item currently says "The removal half is already done; only the addition is left" - true of the manifest and FALSE through a regeneration, because build_manifest computes source_fingerprints from the constant, not from the previous manifest. A reader following the item would regenerate, believe the removal persists, and have it silently undone by the generator. Exact wording supplied by the schedule-import lane: "**The removal does not survive a regeneration.** build_manifest computes source_fingerprints from the constant, not from the previous manifest, so regenerating before making the two source edits reinstates a db/lineage.py digest - with whatever bytes that file holds on the day, which is a third value the cohort was never derived with. Make both edits first, then regenerate, so the manifest is true of the code that generated it." Lane declined to open a fourth PR into a three-lane queue at 03:00 and handed it to the architect, who owns docs/ and is already editing for the closure set.

## `c11-derivation-method` - Landing the fingerprint derivation method in the repo

**Status:** pending

For the coordinator closure PR. Place as a block on the schedule-cohort-fingerprint-list item in docs/backlog.md - that item is what a lane reads when the fingerprint alarm fires, which is where the method is needed. Supplied by the schedule-import lane, which audited my claim that everything it knew was committed and found this gap: its handoff entries record the method OUTPUTS ("22 of 24 shared definitions identical", "the closure reaches 314 definitions") and never the PROCEDURE. Verified by git grep: "call-graph closure" appears nowhere in docs/; only "AST-identical" appears, in one handoff entry. The alarm fired twice tonight and will fire again; the standard is currently reconstructible only from prose describing its results.

QUESTION IT ANSWERS: a fingerprinted file changed - is the change in the cohort's DERIVATION, or merely in the same repository?

1. DOCSTRING-STRIPPED AST DIFF of the file between merge-base and head. Strip the leading string expression from every Module/ClassDef/FunctionDef body, then compare ast.dump per top-level definition. Report added/removed/altered/identical. Separates "prose moved" from "logic moved" - the distinction commit a6ec4ca relied on.
2. STATIC CALL-GRAPH CLOSURE over the hoops_gm package, seeded from the manifest's OWN operator.commands - for this manifest: cohort_evidence.main, cohort_evidence.build_manifest, ingest.backfill.main, ingest.injury_report.backfill.main. Walk ast.Call AND bare ast.Name per definition, resolving through a per-module alias table built from ImportFrom (absolute and relative), because almost every cross-module edge here is "from X import Y" not "X.Y".
3. INTERSECT. A changed definition not in the closure is not in the derivation.

THE THREE TRAPS, which are the part worth writing down:
(a) A newly-ADDED definition can be reachable and prove nothing. PendingScheduleGame appeared as "changed and reachable" purely because it is new and the parser imports it as a type; it cannot have altered prior behaviour. Intersect against ALTERED, not against added-union-altered, or you block on your own new code.
(b) REACHABILITY IS NECESSARY, NOT SUFFICIENT. ingest/nba/schedule.py is genuinely on the derivation path and was altered, so the closure gives no comfort for it; a behavioural check is needed instead (old and new parse_schedule run side by side over the cohort's own recorded fixture, outputs compared). The closure tells you which files you can DISMISS; it never tells you a file is safe.
(c) BARE ast.Name MATTERS, not just ast.Call. A dataclass referenced only as a type annotation, or a constant, has no call node; dropping those under-approximates the closure in exactly the direction that produces a false "not in the derivation".

## `c13-staging-is-not-resolution` - Adding the resolution application of an existing gates rule

**Status:** pending

For the closure follow-up PR (or #56 if still open), ONE LINE in docs/governance/gates.md attached to the existing "assert the mutation actually applied" bullet - NOT a new section, because the mechanism is already stated there and this is a second address for it. From the projections lane, 2026-08-21: it committed <<<<<<< HEAD conflict markers into docs/handoff.md during a rebase. Its resolver raised on a block whose HEAD side was empty; it ran git add anyway because resolve-and-stage were two steps in one command and it read the exit status of the second; git rebase --continue then committed the markers. Found by grepping the COMMIT rather than the working tree. STAGING IS NOT RESOLUTION - the same shape as the two bad mutation checks, success inferred from an adjacent signal. Fix, which is the correct form: a conflict resolver must verify no marker survives BEFORE it stages anything, and exit non-zero otherwise. Aggravating factor worth one clause: the markers landed in handoff.md, which is append-only, so nobody re-reads old entries and it would not have been found by reading.

## `c14-field-cannot-move` - Recording the inverse failure: a correct system reporting failure through a field that cannot move

**Status:** pending

For the next governance PR, docs/governance/risks.md, as a clause on R54 (a check cannot see whether it is asking the right question). HOLD until #48 and #47 merge - #48 touches risks.md and this would create conflict surface.

Every other finding in this wave was a check reporting SUCCESS about something it was not looking at. This is the opposite direction and it has an opposite remedy. Instance, 2026-08-21: the schedule grid lineage version is content_fingerprint over persisted team_schedule rows, and a pending game persists no rows because it has no teams. So a re-seed that newly recognises six pending games produces a BYTE-IDENTICAL version - measured, e80a3aecca0e86eb before and after, same refresh_id updated in place, while source_game_count moved 1200 to 1206 and pending went 0 to 6. Checking version to confirm the re-seed took would have reported failure on a working system.

Cost profile differs from the usual case: not a missed defect, but hours spent hunting an imaginary one while a correct screen sits there working. THE TWO FAILURE MODES HAVE OPPOSITE REMEDIES - a check that wrongly reports success wants a wider check; a check that wrongly reports failure wants knowing which field answers your question before you read it. Predicted from the mechanism by the frontend lane; independently demonstrated in data by the coordinator before the prediction arrived. Same fact as the architect round-one fingerprint finding and the schedule lane note - one fact seen from three directions.

Second clause, same source: 1,200 was never the season. Last night's block read source 1200 / resolved 1200 / pending key ABSENT (not empty). The six Cup games were filtered upstream of the count, so the figure circulating all day as "the season" was the season minus exactly the games the pending work exists to display, and nothing on that screen could have said so.

## `c15-cross-language-import` - Recording: a cross-language import is a dependency no gate can see

**Status:** pending

For the next governance PR, docs/governance/gates.md under "What gates cannot catch". Found by the frontend lane 2026-08-21 while assessing a rebase.

frontend/src/test/fixtures/make_pending_date_payloads.py imports parse_teams from backend/src/hoops_gm/ingest/nba/parsers.py, parse_schedule from ingest/nba/schedule.py, and weekly_periods from dev/seed_schedule_grid.py. PR #48 modified parsers.py. Nothing detects the coupling: git reports no conflict because the frontend lane does not EDIT that file, the frontend gate does not run Python, the backend gate does not know the frontend imports it, and the PR mergeability label reads CLEAN throughout. Had NbaTeamRecord been reshaped or parse_teams changed signature, the verifier would have broken or - worse - silently compared something different.

Measured this instance: parsers.py added _require_declared_season and parse_player_index and ALTERED NOTHING; models.py added NbaPlayerPositionRecord and altered nothing. So the coupling did not bite this time. The gap is that nothing would have told either lane if it had.

TWO STATEMENTS WORTH LANDING:
1. A cross-language import is a dependency no gate in this repository can see. If a file in one language tree imports from another, name the coupling in both places, because no tool will.
2. From the lane, and it corrects the coordinator too: A FILE LIST ANSWERS "WHAT WILL CONFLICT", NOT "WHAT WILL BREAK." The coordinator characterised #48 as a bigger delta by file count; the lane characterised it by what its own code reaches into, which is the question that mattered.

Connects to the existing architect finding that this generator fits neither side of the tree - that placement question now has a second and sharper reason behind it. Owner: data-engineer per the existing filed item.

REFINEMENT, from the held lane rather than the coordinator, 2026-08-21: pair the hold with a grep. The practice is "hold the producing lane until every consumer has reported", and the observation from the other side is that THE COST OF HOLDING IS NEAR ZERO AND THE COST OF NOT HOLDING IS THAT THE CONSUMER DEBUGS ALONE AGAINST CODE WHOSE AUTHOR IS GONE. What made it cheap in this instance was that the coupling was discoverable in one grep; what would make it expensive is a lane that does not know what reaches into its files. So a held lane should arrive with the exposure already narrowed rather than waiting to be asked.

Worked example of what that produces: instead of "probably fine", the held lane supplied (a) raw source hash of the coupled function including comments, identical before and after, closing the gap in the coordinator AST check which cannot see comments; (b) module-level bound names 44 to 51 with NONE LOST, so no importer can break on a missing name; (c) the consumer exact import sequence run against merged main with the returned record shape shown. That is a specific exclusion the consumer can act on - "if your verifier reddens, it is not this" - rather than a reassurance it must re-derive.

## `c16-argued-gate-downgrade` - Recording: a well-argued gate downgrade passes its own review

**Status:** pending

For the next governance PR, docs/governance/gates.md under Gate discipline, beside "No gate may be waived by the agent whose work it applies to."

Found and self-reported by the architect lane, 2026-08-21, on its own ADR-015 unit. It assigned Code gate only, and argued it: blending version 1 fits no parameters, its card reports no learned-accuracy or calibration claim, so there is no held-out experiment and demanding one would produce a ceremonial backtest of a deterministic transformation. EVERY PREMISE TRUE. The conclusion does not follow.

gates.md names `blending` explicitly in the Model gate applies-to list, and the bullet that bites is "Version the output - every stored number records the model version and inputs that produced it." A persisted blend recipe IS the inputs half of that. Verified independently by the coordinator against gates.md at origin/main. Corrected to Code AND Model, satisfied by a model-card revision and an inputs-versioning statement, no backtest - so the honest gate cost almost nothing, which is itself the point.

THE MECHANISM, and it is distinct from every other entry: the existing rule says no gate may be waived by the agent whose work it applies to. That rule imagines waiving as an ACT - someone deciding to skip. This is waiving as an ARGUMENT: a true, well-reasoned case for a narrower gate, constructed in good faith, which is far more persuasive than a skip and leaves a defensible paper trail. In the lane's own words: "a well-argued gate downgrade is a thing this project should probably watch for, because mine passed my own review."

MITIGATION: gate assignment is checked against the applies-to list by NAME, not by argument. If the work names a module or quantity in a gate's applies-to line, that gate applies regardless of how good the case for narrowing is; argue the CONTENT of satisfying it, never the applicability. A reviewer asked to check a gate assignment should read the list first and the argument second.

MITIGATION SHARPENED by the lane that made the error, and this version is the one to land - mine can be obeyed and still miss. The failure was NOT skipping the applies-to list. The list was read; `blending` was found on it; the entry was then treated as ADDRESSED because the bullets the author could see - backtest, calibration - had been disposed of. THE LIST WAS CHECKED. THE BULLETS WERE NOT.

So the rule is one clause longer: NAME THE MODULE ON THE APPLIES-TO LINE, THEN WALK EVERY BULLET UNDER THAT GATE AND SAY WHICH ARTIFACT SATISFIES IT. The failure would have died at "version the output", because no artifact could have been named for it - the recipe is the inputs half and none had been written.

AND THE TELL IS A TRAP, not a reassurance. The coordinator noted the correct gate was nearly free (a card revision, no backtest) as evidence the downgrade bought nothing. The lane inverted it: a backtest is expensive and a card revision is not, so A GATE WHOSE EXPENSIVE BULLETS ARE INAPPLICABLE LOOKS LIKE A GATE THAT DOES NOT APPLY. Inapplicable bullets and an inapplicable gate are not the same thing, and the cheapness of the remainder is precisely what disguises the difference. Land this beside the rule, because someone obeying the by-name check can still stop at the first two bullets exactly as the author did.

## `c17-two-indexes-drifting` - Filing: two indexes over docs/decisions/ drift independently with no test

**Status:** pending

Backlog item for the next governance PR. Named by the architect lane as a pattern rather than two incidents.

docs/decisions/README.md was missing rows for ADR-013 and ADR-014 as of 2026-08-21 morning - both added by the coordinator only because a merge conflict landed on adjacent lines of that table and forced a look. PLAIN-ENGLISH.md stops at ADR-009, so 010 through 015 are absent from it entirely.

Two indexes over the same directory, drifting independently, NEITHER WITH A TEST. The fix is not an edit - editing both today leaves them drifting again next week. The fix is a test asserting every ADR-0NN-*.md file in docs/decisions/ has a row in README.md and an entry in PLAIN-ENGLISH.md, which fails loudly the next time someone adds an ADR and forgets. Cheap, durable, and it is the difference between correcting an instance and closing a class.

Deferred today under the customer rule: it names no screen and no draft behaviour. But it is the SECOND time in one day that a missing index row was found by accident rather than by a check, and the first time it was found only because of a merge conflict. Owner: architect.

TWO SHARPENINGS from the architect lane, both to land with it.

(1) THE TEST MUST ASSERT BOTH DIRECTIONS, not just that every ADR-0NN-*.md has a row. A row pointing at a file that does not exist is the failure a RENAME produces, and it is the one a human reading the table cannot see - a plausible title and a broken relative link look identical in Markdown until clicked. The lane's own ADR-015 index row was verified by a reviewer resolving the link, not by the author reading the table.

(2) THE DETECTOR THAT FOUND THE FIRST TWO HAS NO COVERAGE GUARANTEE. The missing ADR-013/014 rows surfaced only because a merge conflict happened to land on adjacent lines of that table - it fires only when two lanes touch the same table in the same window. TWO OF THE THREE INDEX DEFECTS TODAY SURFACED BY ACCIDENT. That, more than the drift itself, is the argument for the test.

## `c18-lifetime-not-shape` - Recording: classify an identifier by what invalidates it, not by what it looks like

**Status:** pending

For the next governance PR, docs/governance/risks.md as a clause on R7 or its own row - it is an identity/lifetime rule and generalises past blending. Self-diagnosed by the architect lane after a reviewer found a second instance of a defect the lane had closed well.

THE SHAPE OF IT. ADR-015 correctly separated the owner-authored RECIPE (durable) from the transient IMPORT BINDING (correctly killed by any refresh). That was the finding of the unit and it was right. But scoring_profile_id was filed as recipe - and it is a binding. build_scoring_profile filters reuse candidates on settings_snapshot_id, and its own docstring says a same-content match against a different snapshot row always mints a new version. So A BYTE-IDENTICAL LEAGUE-SETTINGS RE-INGEST KILLS THE PERSISTED RECIPE, with no new projection CSV involved - the same draft-morning failure the ADR exists to prevent, through a door the author never looked at. Remedy: key on (league_id, name) plus a category-content fingerprint that deliberately excludes snapshot-row identity.

THE AUTHOR'S OWN DIAGNOSIS, which is the transferable part: "I classified scoring_profile_id as recipe because it is CONFIGURATION-SHAPED. quant classified it by asking WHAT INVALIDATES IT. The lifetime test is the one that works, and shape is what I actually used."

RULE: when a thing has two lifetimes, every identifier it carries needs the lifetime question asked SEPARATELY - what invalidates this, and does that match the lifetime of the thing holding it. LOOKING CONFIGURATION-SHAPED IS NOT EVIDENCE. This is ADR-014's enumeration clause with a second step: enumerate the keys, then ask each one what kills it.

Note the author closed the door it was looking at correctly and competently. Doing the visible half well is not evidence the class is closed - which is the same shape as the four scope-of-application findings already in gates.md, arriving through classification rather than through placement.

## `c19-approval-is-not-a-check` - Recording: a coordinator approval is not a check, and the plan is not where design defects are caught

**Status:** pending

For the next governance PR, docs/governance/gates.md under Gate discipline. Self-reported by the backend lane, 2026-08-21, about a design the coordinator had explicitly approved.

The lane proposed putting acquire_transaction_lock directly in ingest/projections/importer.py. It described that placement to the coordinator in its plan; the coordinator read it and approved it. IT WAS WRONG. test_lineage_locks_are_acquired_through_exactly_one_import failed: two lock-order recorders monkeypatch hoops_gm.db.lineage.acquire_transaction_lock, and that captures anything only because db/lineage.py is the SOLE module reaching the primitive. A second importer touching the primitive directly would have BLINDED BOTH RECORDERS WHILE LEAVING THEM GREEN. Fixed by moving the lock into db/lineage.py as lock_projection_source_scope.

THE LANE'S OWN SENTENCE, which is the entry: "the approval was not the check that caught it, and nothing in the plan would have."

WHY IT MATTERS: plan review reads intent, and this defect lived in the interaction between a proposed placement and an existing test's monkeypatch target - a fact about the codebase that no prose description of the plan contains. A coordinator approving a plan is agreeing the UNIT is right, not certifying the DESIGN is correct. Say so where lanes read it, because an approval currently reads as more than it is, and a lane that treats it as a check has lost a review round it thinks it still has.

SECOND-ORDER BENEFIT WORTH RECORDING: the corrected placement made the design better for an unrelated reason. The reservation now targets refresh_runs, so the TimestampMixin bump the lane was carefully avoiding on projection_sources became STRUCTURALLY IMPOSSIBLE rather than avoided by a careful values() call. A constraint that removes the need for care beats a care that must be remembered.

## `c20-harness-read-absent-output` - Recording: a verifier that concludes from absent output, found inside the harness built to find that

**Status:** pending

For the next governance PR, as a clause on R57 in docs/governance/risks.md. Backend lane, 2026-08-21.

Its mutation harness reported NOT GREEN BEFORE MUTATING for seven tests that were passing. Cause: pytest addopts already carries -q; the harness added another, making it -qq; and -qq SUPPRESSES THE SUMMARY LINE the harness parsed for the word "passed". So the harness read absent output as failure.

This is R57 exactly - a check computed over what came back cannot distinguish "none of that state" from "no data" - occurring INSIDE THE TOOL BUILT TO FIND R57's SHAPE, and it fired in the safe direction only by luck: had the polarity been reversed it would have reported green over a suppressed failure. Same family as the coordinator's own CI watcher, which read a network error as zero pending checks and declared SETTLED over four outstanding jobs.

MITIGATION, generalising both: a tool that parses another tool's output must assert the output ARRIVED and had the expected SHAPE before interpreting its content, and must not inherit flags from a config it does not read. Verbosity is part of a parser's contract with its source.

## `c21-borrowed-justification` - Recording: a borrowed justification is as unverified as a borrowed number, and does not feel like one

**Status:** pending

For the next governance PR, docs/governance/risks.md as a clause on R56, or its own row. Self-reported by the quant lane, 2026-08-21, after making the same class of citation error twice in consecutive rounds.

ROUND ONE: attributed the PR #30 CRLF correction to a manifest field that contains no such record. ROUND TWO: cited ADR-006 for layer purity in FOUR places - ADR-006 is adapter isolation; layer purity is ADR-008. Verified independently by the coordinator: ADR-006-adapter-isolation.md, ADR-008-layer-purity.md. And the second was committed IN THE SAME CHANGE that recorded the first.

THE MECHANISM, which is why it is not just carelessness: the ADR-006 rationale ARRIVED INSIDE A REVIEW from data-engineer. The lane adopted it and never re-derived the reference. Its own formulation:

"A borrowed justification is exactly as unverified as a borrowed number, AND IT DOES NOT FEEL LIKE ONE, because it arrives already argued and attributed to someone with more context."

gates.md already says re-derive any number or mechanism appearing in prose at the moment you write it. The lane applied that to figures it computed and not to a citation it was handed. So the rule needs the second half stated explicitly: A CITATION RECEIVED FROM A REVIEWER IS AN UNVERIFIED CLAIM. Re-derive the reference itself, not only the argument built on it - and note the reviewer's greater context is exactly what makes the citation feel checked when it is not.

This is R56 (compression) pointed at attribution rather than at content, and it connects to the frontend lane's fabricated ADR citation from 2026-08-20, which was invented rather than borrowed. Two routes, same artifact class: an address that does not resolve, inside an argument that is otherwise sound.

## `c22-gate-measured-looser-unit` - Recording: a gate that measures a looser quantity than the veto it pre-empts

**Status:** pending

For the next governance PR, docs/governance/gates.md. Found by both reviewers independently, quant lane, 2026-08-21.

The lane designed a pre-unblind admissibility gate specifically to stop a wasted sweep: a cohort is admissible only if every status carries >=30 observations in the held-out range. But it measured CANONICAL OBSERVATIONS while the activation veto it pre-empts measures DIRECT OUTCOMES - and direct outcomes are a SUBSET of canonical observations. So the gate measured the looser quantity and WOULD HAVE PASSED THE EXACT CASE IT EXISTS TO CATCH.

A gate whose unit is looser than the veto it pre-empts is not a gate; it is a filter that removes only cases the veto would also have removed. State the veto's unit, then state the gate's unit, then assert they are the same or that the gate's is stricter.

TWO RELATED DEFECTS IN THE SAME UNIT, both in machinery built to prevent that class:
(a) A split rule defined against TWO DIFFERENT DENOMINATORS with no rounding rule - 26 game dates against 28 calendar days, 25% of 26 being 6.5 - which is the exact defect that document's own section 7 faults its predecessor for.
(b) A leak invariant that FORBADE AND PERMITTED THE SAME OBJECT: a direct-outcome count is itself defined by a predicate on the outcome value. The author mis-sorted their own example three paragraphs after stating the rule. Replaced with a closed-set allow-list, because data-engineer showed the granularity rule fails structurally - git makes cross-manifest differencing free, and THE WIDENING BEING RECOMMENDED IS ITSELF WHAT OPENS THE SUBTRACTION ATTACK.

## `c23-jointly-narrow-contract` - Recording: a documented contract property its only real producer cannot exercise

**Status:** pending

For the next governance PR - risks.md as a clause on R50 (verifier only ever seen passing), and a backlog wording fix on projections-api-early which the architect owns. Found by the backend lane, 2026-08-21, verified independently by the coordinator.

THE FINDING. projections-api-early documents source_games_played_assumptions as "deliberately sparse; absent never means zero". Tracing the producer: all 14 of Basketball Monster's stat_columns are ValueShape.SEASON_TOTAL (verified by counting them in profiles.py - 14 SEASON_TOTAL, zero PER_GAME in the BBM block). A SEASON_TOTAL column requires a games-played divisor. A row missing a required production value is FATAL and dropped from result.rows. Therefore every surviving BBM row carries an assumption, and since the endpoint is ?source=-scoped, THE ARRAY CAN NEVER BE SPARSE FOR THE ONLY SOURCE VERIFIED FOR PRODUCTION. Sparsity is reachable only through MANUAL_PROFILE, whose columns are PER_GAME and need no divisor - a source the owner does not buy.

WHY IT IS A NEW ROUTE. The API contract is accurate. The parser is correct. THE TWO ARE ONLY JOINTLY NARROW, and no gate looks at a joint property of two correct components. Every previously recorded empty-verifier instance was a check that could not fire because of HOW IT WAS WRITTEN; this one cannot fire because of WHAT THE ONLY REAL WRITER CAN EMIT. A consumer building against it writes a CONTRACT GUARD, not a guard against an occurring state, and nothing distinguishes the two.

TWO ADJACENT STATES ARE SCHEMA-PERMITTED AND PRODUCER-UNREACHABLE: assumed_games_played null with assumed_games_played_raw non-null (raw text is captured before parsing and an unparsable value is fatal, so the row is dropped), and both fields null (_write_games_played_assumption returns before writing). A schema that permits what no producer writes is a shape a consumer will defend against forever.

MITIGATION: when documenting a contract property, state which producer can exercise it. If none can today, say so - a property with no producer is a contract guard, and a consumer is entitled to know it is defending a shape rather than a state.

## `c24-canonical-fields-seam` - MERGE PREREQUISITE on the projections screen PR: pin CANONICAL_STAT_FIELDS against BBM required_production_fields

**Status:** done

NOT an ordinary backlog item - this is a named condition on the projections-ui PR, because that PR is what first makes the claim load-bearing. It must not merge without this test.

THE GAP, verified by the coordinator: set(CANONICAL_STAT_FIELDS) == set(BASKETBALL_MONSTER_PROFILE.required_production_fields), 16 each, set-equal in BOTH directions, canonical-minus-required and required-minus-canonical both empty. And `grep required_production_fields backend/tests/` returns ZERO matches across 1,304 tests. The equality is a coincidence of two hand-maintained tuples in one file, defended by nothing.

WHY IT MATTERS: the projections screen states that a null rate cannot occur for Basketball Monster, because missing_required_values is `any` not `all`, so a row missing any required value is fatal and dropped. That claim is user-facing copy. Add a canonical field WITHOUT adding it to BBM required_production_fields and: the field appears in the payload (_rates() splats CANONICAL_STAT_FIELDS), it is legitimately nullable in a stored BBM row, and the merged screen SILENTLY TELLS THE USER SOMETHING FALSE - via a one-line tuple edit in data-engineer's file that no test opposes.

ownership.md already names CANONICAL_STAT_FIELDS a cross-owner seam, but it pins the vocabulary against THE WIRE. The half this claim rests on is the vocabulary against WHAT THE PROFILE REQUIRES, and that is unpinned. Same shape as the sparsity finding one level up: two correct components, a joint property nobody owns.

THE TEST: assert set(CANONICAL_STAT_FIELDS) == set(BASKETBALL_MONSTER_PROFILE.required_production_fields). Docstring names the screen as consumer and states what breaks if it drifts. Mutation check must redden it from BOTH sides - add to one tuple, then add to the other - because a one-directional check passes on half the drift.

OWNERSHIP: data-engineer owns the tuple and should review the test against it. The backend lane found this and correctly declined to add it to a frozen tree with two reviews outstanding - the claim is not on main yet, so the test would defend a claim that does not exist, in a unit that does not make it.

SATISFIED 2026-08-21. backend/tests/test_projection_vocabulary_pin.py is present on the projections-screen PR head 0f6430d and green (20 pass / 2 skipping). Verified by the coordinator from the tree, not from the lane report. The lane also drove drift into the REAL tuples rather than stopping at the in-memory mutation, on the reasoning that the mutation helper failing proves the helper works and only real drift proves the pin does. It asserts set-equality AS SETS rather than counts, because counts pass on a swap, which is what a partial rename produces.

NOTE ON THE RECORD: this was tracked as one of two merge prerequisites on that PR. The lane correctly pointed out that only ONE is external - the backend CLI - and this one was inside its own PR and already green. Two open items against a lane when one is satisfied is a stale aggregate of exactly the kind R53 covers, arriving in coordinator tracking rather than in a file.

## `c25-guard-too-sensitive` - Recording: a guard that cries wolf is the one the next person loosens

**Status:** pending

For the next governance PR, docs/governance/gates.md beside the mutation bullets. Frontend lane, 2026-08-21. THIS IS A DIRECTION NOTHING ELSE IN THE REGISTER COVERS.

Every recorded instance so far is a guard that CANNOT FIRE - vacuous, empty, passing for the wrong reason. This is the opposite: a guard that fires when nothing is wrong.

The lane built an ADR-002 detector to catch a forbidden rate x assumed_games_played product on screen. It concatenated the rendered subtree textContent and searched for the product as a string. It PASSED on a one-row synthetic payload and reported OVER 200 VIOLATIONS AGAINST THE REAL 60-ROW COHORT, EVERY ONE FALSE - because a table's textContent runs adjacent cells together, so "12.34" beside "5.67" contains "345".

WHY IT IS AS DANGEROUS AS A VACUOUS GUARD, and less noticed: a guard that cries wolf on a correct screen is the guard the next person loosens, and they will loosen it in the direction that makes it vacuous. The register already records that a limitation repeated without a remedy converges to a ritual; this is the same decay arriving through false positives instead of through disclosure.

FIX: walk text nodes, where a number cannot span a boundary, and parse tokens back to numbers so a toLocaleString() total is caught too.

AND THE DETECTION WAS NEARLY LUCK: it only surfaced because the backend lane happened to seed a 60-row cohort. On the one-row payload the lane had, it passed. A guard validated only against a minimal fixture has not been validated against the shape it will meet.

## `c26-serialised-recording` - Recording: a recording that has been through a serialiser is not a recording

**Status:** pending

For the next governance PR, docs/governance/gates.md under the fixture/verification section. Frontend lane, 2026-08-21.

Its first captured fixture went through PowerShell's JSON round-trip. That parsed `imported_at` into a DateTime and re-emitted it as `08/21/2026 15:57:03` - US locale, NO TIMEZONE, no sub-second precision. Every structural assertion would have passed. The one field this project has already been bitten by (AGENTS.md's gameEt finding: a field that lies about its timezone, and the correction that timezone-correct parsing of a mislabelled field is still wrong) would have been silently REPLACED BY THE CAPTURE TOOL'S OPINION OF IT.

RULE: capture raw bytes. A recording exists to be evidence of what a producer emitted; anything that parses and re-emits substitutes its own representation for the producer's, and the substitution is invisible to every structural check because the SHAPE survives. Note this is the same family as the AST comparison that cannot see comments - a transformation that preserves what you are checking and destroys what you are not.

SECOND, SMALLER, SAME UNIT: the lane's first sticky-header assertion compared header position before and after scrolling and read the caption scrolling away as a failure. The header legitimately moves up by the caption height and THEN pins. Asserting it never moves was asserting the wrong thing - a test that is right about a property nobody has is the R54 family arriving in layout. Verified properly with getComputedStyle at three scroll offsets.

## `c27-citing-extends-scope` - Recording: a statement whose MECHANISM is narrower than its READING (four instances, one class)

**Status:** pending

For the next governance PR, docs/governance/risks.md as ONE entry, not four. Generalised by the backend lane, 2026-08-21, after four instances in one unit. Land as a single row with the four as evidence - filing them separately would be the prose-cost defect in the entry about over-reading.

THE CLASS: a statement that is TRUE, whose mechanism covers less than a reader will take it to cover. Lint, types and a green suite were clean over all four. None is a lie; each invites a generalisation the mechanism does not support.

FOUR INSTANCES, all in one unit:
1. A docstring citing require_safe_demo_target accurately. The guard inspects `leagues` and the schedule cohort; the module added projection tables it has never heard of. UNDERSTATED SCOPE READ AS BROADER PROTECTION. Consequence had it shipped: seed_projections silently retires the real Basketball Monster crosswalk and installs synthetic links, exit 0, saying nothing - 20 real links current before, 0 after, reproduced by a reviewer.
2. A refusal message saying seeding "would retract every real player_external_ids row". False for a MANUAL import - the seed only calls import_resolutions(source=BASKETBALL_MONSTER). OVERSTATED HARM READ AS BROADER COVERAGE. Same failure, opposite sign, inside the fix for instance 1.
3. Evidence handed to the frontend lane led with digests pinning the RATES, not the assumptions array or the labels. THE IMPRESSIVE ARTEFACT AHEAD OF THE COVERING ONE.
4. Three docstrings asserting "refuses before anything is written" - an ordering NO TEST COULD DISTINGUISH FROM ITS OPPOSITE, because the assertion checked COMMITTED state and Database.session() rolls back on exception, so a guard that writes and then refuses is rescued by the caller and looks identical to one that refused first. A CLAIM REPEATED OFTEN ENOUGH TO FEEL ESTABLISHED. The lane wrote the four paragraphs the docstring spends on that property, and the guard had a mutation for WHETHER it refuses and none for WHEN.

THE MOST PORTABLE FORM, from the frontend lane: LEAD WITH THE ITEM WHOSE MECHANISM COVERS THE MOST OF THE CLAIM, NOT THE ITEM THAT LOOKS MOST LIKE PROOF.

UNIFIED RULE: state what a guard INSPECTS and what it PROTECTS as separate sentences; neither is inferred from the other. And when a docstring spends paragraphs on a property, check there is a mutation for THAT property rather than for the headline behaviour.

SEVERITY DISTINCTION - added 2026-08-21 after the frontend lane corrected the coordinator's consolidation. THIS MUST BE INSIDE THE ENTRY, not lost in a flat list of four. The class is one mechanism; ITS SEVERITY DEPENDS ON WHETHER THE OVER-READING ACCOMPANIED THE COVERING EVIDENCE OR REPLACED IT.

ACCOMPANIED (instances 1 and 3): the load-bearing evidence is present, just second, or the citation is accurate but invites generalisation. A reader following the whole artefact reaches the truth. Corrected by the next reader.

REPLACED (instance 2 and especially the leak filter): the covering coverage is GONE, and the replacement LOOKS LIKE ADDED RIGOUR. Checked cells 131 -> 60; the 75 lost were the numeric rates, which for a real Basketball Monster export ARE THE PAID CONTENT the guard exists to keep off stdout. The guard went from crude-but-covering to precise-and-blind on the one class it names.

The frontend lane's phrasing: "THE SECOND IS THE ONE THAT SHIPS." A misordered message is corrected by the next reader; a guard that silently stopped covering the thing it names ships and stays shipped.

UNIFYING LINE, better than the coordinator's and covering both halves: AN ARTEFACT THAT LOOKS MORE LIKE PROOF IS NOT THEREBY COVERING MORE. A digest looks like proof beside a one-line diff; a type check looks like proof beside a length heuristic. Both times the impressive-looking thing covered less. GENERALISES TO ANY "we replaced the heuristic with something principled" CHANGE - which this project will do repeatedly, and which is the specific shape to watch.

PROVENANCE NOTE: the backend lane generalised its own four instances and flattened the severity difference in doing so; the coordinator then landed that flattening. Compression failure inside the entry about over-reading, committed by both parties in sequence.

## `c28-time-indexed-claim` - Recording: a document accurate about the tree it was written in and false about the tree it merges into

**Status:** pending

For the next governance PR, docs/governance/gates.md under "What gates cannot catch". Coordinator found the instance; the frontend lane produced the general statement and recorded the coordinator framing as its source.

THE INSTANCE. The projections-screen README told a reader to run `python -m hoops_gm.dev.seed_projections`. That module exists ONLY on the backend lane's unmerged branch. The coordinator followed the instruction on the screen branch and got "No module named". Verified: dev/ on the screen head holds __init__.py and seed_schedule_grid.py; the backend branch additionally holds seed_projections.py.

WHY NO GATE CATCHES IT. Every gate passed. The branch is green, the screen works, the README is ACCURATE ABOUT THE TREE IT WAS WRITTEN IN and false only about the tree it merges into. It is a claim whose truth is TIME-INDEXED, and nothing we run checks it at the moment it becomes false - CI tests the branch, and the branch is correct.

THE GENERAL FORM: a dependency that lives in a lane's working directory but in nobody's ORDERING is invisible until somebody runs the command. It existed from the moment the lane began building against a sibling branch, which was correct and unavoidable; it simply never became a sentence.

CONSEQUENCE IF UNCAUGHT: the screen merges first and /projections ships with no committed way to put a cohort behind it - the endpoint answers projections_source_not_imported and the screen shows a refusal. That is the exact state a previous endpoint sat in unnoticed, which is why seed_schedule_grid exists at all.

MITIGATION: when a lane builds against an unmerged sibling, the dependency is written in three places chosen by who hits it - beside the command (the operator), in the backlog entry (whoever picks up the task), and in the handoff (the mechanism). And a coordinator holding a merge queue must record cross-PR ordering as a named prerequisite, not as a shared understanding between two sessions.

SECOND-ORDER, from the lane and worth keeping: it fixed the dependency it was shown and explicitly under-claimed the fix - it checked THE COMMANDS IT WROTE DOWN, not everything the screen needs, because answering the general question would require building clean main plus the branch and exercising every path. "The honest scope is the commands I wrote down."

## `c29-disclosure-discipline` - Recording: the could-not-verify field is where reasoning is least disciplined

**Status:** pending

For the next governance PR, docs/governance/gates.md beside the mandatory could-not-verify requirement. Self-diagnosed by the backend lane, 2026-08-21, after being wrong twice in one unit in the same section.

THE OBSERVATION, in the lane's words: "That is the second time today I believe it is unreachable has been wrong in this unit, and BOTH TIMES IT WAS IN A DISCLOSURE RATHER THAN IN CODE. The disclosure section is where I am least disciplined: I have been careful to state WHAT I COULD NOT VERIFY and careless about stating WHY I THOUGHT IT DID NOT MATTER."

WHY THIS IS A REAL GAP. AGENTS.md makes could-not-verify mandatory and says "nothing" is rarely the honest answer - so lanes are disciplined about ENUMERATING gaps. Nothing disciplines the JUSTIFICATION attached to each gap. The sentence "I could not verify X" is checkable and gets checked; the sentence "and I believe X is unreachable" is a load-bearing claim that arrives in the same breath, wearing the humility of the disclosure around it, and nobody reviews it because the section is read as an admission rather than an assertion.

INSTANCE: the lane wrote "I believe those cannot be reached without one of the two states it checks." FALSE for projection_sources - the reviewer built a database holding only a real projection_sources row and the seed proceeded, overwriting display_name and assumed_scoring_type. Harmless and hard to reach, but the claim was wrong and it was doing work.

RULE: a could-not-verify entry states WHAT WAS NOT CHECKED and, separately, whether the reason it is believed harmless was DRIVEN or REASONED. "Reachable, driven, harmless" and "believed unreachable" are different claims and only one of them is evidence. Prefer the first; if only the second is available, say so in those words.

## `c31-cross-lane-claim-prospective` - Recording: the first prospective use of the stale-cross-lane-claim rule

**Status:** pending

For the next governance PR, as a short clause on R51 beside the reader-count decay entry. Frontend lane, 2026-08-21.

Every prior instance of "a fact about the codebase decays when another lane merges" was found AFTER it went stale - a reader count corrected twice then found wrong a third time, a coordinator relaying a watch-set change that was false, a README naming a command that would not exist on the tree it merged into. Diagnosis, every time.

THIS ONE IS PREVENTION. The frontend lane asserts nothing on the backend lane's refusal text - but its README DESCRIBES that refusal's scope. So before reporting, it re-derived that sentence against the backend branch head itself rather than against the backend lane's message to it: both limbs true, exit code still 2, left alone.

Its stated reason: "that sentence describes your behaviour in my file, so it is exactly the kind of cross-lane claim that goes stale when a lane I am not reading merges."

WHY IT IS WORTH A CLAUSE: it shows the rule is operable by the CONSUMER, unprompted, at the moment of writing rather than at the moment of failure - and that the trigger is not "did I assert on it" but "does my file DESCRIBE another lane's behaviour". Description is the wider and more dangerous category, because nothing tests prose.

RULE: if your file describes another lane's behaviour, re-derive that description against that lane's head before you report, not against what that lane told you.

## `c32-warning-becomes-override` - Recording: a coordinator warning about a known false positive is a mechanism for overriding a real one

**Status:** pending

For the next governance PR, docs/governance/gates.md beside the tool/verifier bullets. Frontend lane, 2026-08-21, and it is aimed at the coordinator.

WHAT HAPPENED. The coordinator told several lanes, repeatedly, that PR #58 fixes a false positive in scripts/resolve_doc_conflicts.py on lines beginning with seven equals signs. Well-intentioned: it saves a lane twenty minutes of confusion.

Then the resolver told the frontend lane NOT TO STAGE - flagging make_pending_date_payloads.py:54,99 as surviving conflict markers. The lane had, from the coordinator, a ready-made reason to wave a stop signal through.

It did not. It confirmed the false positive on THREE INDEPENDENT GROUNDS instead: git's own --diff-filter=U reports only docs/handoff.md; the flagged lines are a reStructuredText table separator inside a docstring; and the file is untouched by that branch.

ITS LINE, and it is the entry: "AN AUTHORITY I TRUST SAID IT WAS FINE IS NOT A REASON TO OVERRIDE A TOOL THAT SAYS STOP."

WHY THIS IS A REAL HAZARD AND NOT A PLATITUDE. The register already holds "a verifier that cries wolf is the one the next person loosens" - decay by repeated false alarm. This is the SAME DECAY DELIVERED IN ONE STEP BY A TRUSTED PARTY. The coordinator did not loosen the tool; it supplied every lane with a pre-authorised reason to ignore it, which is faster and leaves no trace in the tool. And the next real marker the resolver catches would be waved through by exactly the same sentence.

MITIGATION: when warning about a known false positive, state the CHECK that distinguishes it from a true positive, not just that it exists. "The resolver false-positives on seven equals signs" invites override; "if it flags a line, confirm with git diff --diff-filter=U before overriding" preserves the signal. A coordinator broadcasting a defect must broadcast its discriminator with it.

## `c33` - Recording: a guard that fails slowly reads as green

**Status:** pending

PR #63, head 09b5b06. Two runs fired 2s apart on the IDENTICAL commit - push run FAILED, pull_request run PASSED. gh pr checks showed only the pass. The failure: ProjectionsTable.recorded.test.tsx:263 "renders no absence marker in any rate cell" TIMED OUT at 6161ms against a 5000ms budget - 960 getByTestId calls in a nested loop. Not flaky by chance: deterministically over budget, the pass is the lucky run. Mechanism worth recording: every other guard we argued about today fails LOUDLY; this one fails SLOWLY, and a re-run converts an assertion that never completed into a permanent green check. Also: this is the guard behind the screens own printed claim that a dot should not appear. Related coordinator lesson: gh pr checks displayed a pass for a job that failed on the same head - verify by run headSha AND by event type, not by the checks table. CORRECTED by frontend: my push-vs-pull_request framing was WRONG. History shows b933c5f was red on BOTH event types, so this was never a display artefact. Two true statements (the checks table did show a pass; that head did split) generalised into a conclusion neither supports - my own "mechanism narrower than reading" entry landing on me inside the message where I filed it. The real finding is frontend's: CI had been failing for HOURS across three heads and nobody read it. A signal with no consumer is not a signal, and fixing the checks table would not touch it.

## `c34` - Recording: a legend that disambiguates one of its two marks

**Status:** pending

Projections screen key. Visually correct - the middot swatch carries grid__cell--nodata, the em-dash swatch does not, and the live table cell computes to rgb(152,161,179) identical to the swatch, so the legend renders the thing it labels. But the KEY TEXT contains four em dashes and only one is the mark being defined; three are punctuation, including one inside the entry that defines the em dash. The tell is the asymmetry: the middot IS wrapped in <code> where it appears mid-sentence, so that mark is disambiguated in the text stream and the em dash is not. The habit was right and was applied to one of the two marks. Class: a distinction that holds in the rendered layer and collapses in the accessible/text layer - no gate looks at textContent.

## `c35` - README: the three-choice composition that 404s the demo

**Status:** pending

vite proxies /api to 127.0.0.1:8000; seed_projections deliberately defaults to throwaway projections_demo.db and ignores DATABASE_URL, seeding schedule AND projections into that one file; a stale backend on 8000 answered /health 200 while 404-ing a route it was never built with. Three independently reasonable choices composing into a failure that looks like the screen is broken. Third instance today of "a stale server is not stale data". Fix: four lines in the README naming the port, the file, and the check-the-build-before-the-data order.

## `c36` - Recording: a trend visible in every run, in a field nobody aggregates

**Status:** pending

Vitest prints slow-test durations on their own line. Across runs on PR #63 that line read 3177 -> 3309 -> 3376 -> 3714 -> 4298 ms, climbing monotonically toward a 5000ms limit, printed every run, directly above the suite total the lane quoted to me four separate times. Each individual number is unremarkable and passing; only the SEQUENCE is alarming. No gate, reviewer or reader compares a number to the same number from the previous run, so the signal that would have given hours of warning gave none - the thing carrying it was the delta and nothing computes the delta. Distinct from c33: not about display or readership, about a quantity that is only meaningful across runs in a system that evaluates each run in isolation. REFINED by frontend, and the refinement is the load-bearing half: do NOT land this as a threshold assertion - a threshold recreates the cry-wolf guard the moment the number legitimately grows, and a guard that cries wolf is the one the next person loosens (already in the register). Land it as TOOLING: print the number next to its previous value. No threshold, no failure, no judgement - just the delta made visible so a human sees 3177 -> 4298 without being asked to remember 3177. Generalises to any per-run quantity unremarkable individually and alarming only as a sequence: suite duration, bundle size, query counts, fixture bytes. Attribution: frontend.

## `c37` - Recording: corrections are applied to the case in front of you, not to where the reasoning holds

**Status:** pending

Fourth instance on a single branch of the same meta-pattern: the fix was RIGHT and was applied to one member of a symmetric pair. (1) middot wrapped in <code> mid-sentence, em dash not; (2) the dot-scope defect; (3) the detector floor; (4) the guard that covered less. This is a pattern in how corrections are applied here, not a pattern in the code. Practical rule: when a fix names a mark, a field or a direction, ask what its counterpart is and whether the fix reached it. REFRAMED by frontend and its reading is better than mine: this is not four code defects with a common shape, it is a defect in HOW A CORRECTION IS APPLIED. gates.md already asks "where else is this true?" but asks it of ORIGINAL WRITING, not of corrections. The correction side is the half nobody was watching, and it is worse, because a correction arrives with the confidence of having just been right about something. Attribution: frontend.

## `c38` - Recording: a .get() default turns a wrong field name into a plausible measurement

**Status:** pending

Verifying the schedule grid on merged main I queried d.get("scoring_periods") and d.get("completeness") - neither key exists; the response uses "periods" and puts completeness under lineage.schedule. My script printed "periods: 0, published: None, imported: None, pending: None" and I was one step from reporting that merged main served an empty grid. The data was fully present: 30 teams, 25 periods, 750 cells, 1206/1200/6. Mechanism: .get() with a default makes a MISSING field indistinguishable from a ZERO field, so a typo in a verification script is reported as a finding about the system under test. This is the verification-script analogue of every claim-vs-mechanism entry today, and it landed on me while I was checking someone else work. Rule: a verification script must assert the key EXISTS before reading its value, or print the top-level keys first.

## `c39` - Defect: python -m hoops_gm --help ignores argv and starts the server

**Status:** pending

Running `python -m hoops_gm --help` does not print help - it starts uvicorn and attempts to bind 127.0.0.1:8000, failing with WinError 10048 when a server is already running. __main__.py:11 main() takes no argv and never consults sys.argv. This is the SAME defect class I fixed in scripts/resolve_doc_conflicts.py earlier today, where --help performed a full resolution: a program that ignores its arguments will do its real work when asked to describe itself. Two independent instances in one repository on one day suggests it is worth a convention rather than two fixes. Low severity, trivial fix, but --help is the first thing an operator types.

## `c40` - Defect: demo databases carry no alembic stamp and cannot be upgraded

**Status:** pending

schedule_grid_real.db predates the primary_position migration (PR #48). Running backfill nba-identity against it fails with "table players has no column named primary_position_source". Running alembic upgrade head against it then fails trying to CREATE the leagues table, because the database has no alembic_version stamp - so alembic replays from zero against a populated database. Consequence: a demo database built before a migration is permanently stranded; it cannot be upgraded and cannot be extended, only rebuilt from scratch. The owner will hit this every time a migration lands between demo sessions. Architect note: I stopped pursuing a combined schedule+projections demo on this basis - it unlocks no new screen, which is my own deferral rule.

## `c41` - Rule: assert the presence you expect, not the absence of what you fear

**Status:** pending

frontend closed the loop on c38 and the two findings turn out to be one rule. Its committed em-dash test asserts toBe(1) - a specific positive value - so if the .grid__key element vanished the count is 0 and the test FAILS. Safe, and it drove that rather than argued it: mutated the class name away, got "expected +0 to be 1", reverted, green. But its ad-hoc browser probe - the one used to tell me the fix worked - computed emDashesAsPunctuation = count - swatches. With the element missing that is 0 - 0 = 0, which reads as THE PROPERTY HOLDING PERFECTLY. Absent and passing render identically. The inversion is the keeper: the usual worry is that a throwaway script is looser than a committed test, but here the committed test was saved by its ASSERTION DIRECTION while the throwaway computed a difference, and a difference of two absences is zero. Unifies my .get() finding (missing field indistinguishable from zero field) with the existing formatRate null-vs-zero rule - the same rule, one in production and one in verification. Both of us shipped this defect in a CHECKING TOOL on the same day, an hour apart, each having already written an entry about the class.

## `c42` - CRITICAL PATH: the whole auction chain is 10 deep behind participation ingest

**Status:** done

Traced 2026-08-21. injury-status-conversion -> availability-model -> expected-games -> zscore-engine -> gscore-engine -> risk-adjusted-valuation -> auction-values -> auction-budget-manager -> auction-inflation -> auction-nomination. Ten deep, 58 days to draft. availability-model is blocked by TWO independent routes and quant recorded this on the item: the injury dependency AND its own need for populated player_participation, because PlayerGameLogs has appearances but not non-appearance labels and R35 forbids treating a missing row as an absence. The injury-history lane independently measured that participation ingest dominates injury reports 2.7x in requests and 4x in wall time - "a box-score ingest wearing a scraping problem clothes". SAME FACT, TWO LANES, NEITHER LOOKING AT THE OTHER. Action taken: promoted participation ingest out of that lane Unit 4 into its own first-sequenced unit, and out of low priority, because it is the only critical-path item whose cost is WALL CLOCK rather than effort - hours of throttled fetching cannot be compressed on the day we discover we need it. CORRECTED 2026-08-21 by the lane: participation is 2,462 requests not 1,230 - backfill_season makes TWO per game (BoxScoreTraditionalV3 + BoxScoreSummaryV3) because only per-game endpoints carry DNP comments and inactive lists. Driven by LeagueGameFinder preflight: 2025-26 = 1,230 games, 164 dates, 45.1 min throttle floor. My promotion was built on half the real number and the conclusion strengthens - which is luck rather than method. Ratios corrected to 3.7x requests / 2.0x wall time for one season. RESOLVED 2026-08-22: participation ledger populated for 2025-26. 1,227 of 1,230 games (99.76%), 164 dates, 43,037 rows, 596 players, durable at C:\Users\steverones\hoops-gm-data outside both checkouts. availability-model participation-label route is UNBLOCKED; its injury-status-conversion route remains separate.

## `c43` - Recording: a true fact written down in two places with no reader whose job is to combine them

**Status:** pending

Coordinator-level instance of the class we recorded all day about code. quant note lived on the availability-model backlog item; the injury lane arithmetic lived in a plan I approved an hour earlier. Both true, both written down, both visible. The dependency graph had the answer the whole time and NOTHING COMPUTES IT - I found it by writing a twenty-line script to find the next visible increment, not by reading. Same shape as frontend "CI had been saying so for hours, to nobody": the signal existed and the consumer did not. Mitigation is tooling not discipline: the backlog dependency graph should be computed and its critical path printed, because a human reading 118 items in file order cannot see a ten-deep chain.

## `c44` - Recording: a wrong locator in a false-positive warning fails as an absence

**Status:** pending

I broadcast a known false positive to two lanes and named the file as backend/src/hoops_gm/dev/make_pending_date_payloads.py. That file DOES NOT EXIST - it is frontend/src/test/fixtures/make_pending_date_payloads.py. The mechanism I gave (21 equals signs in an RST docstring rule vs git 7) was correct and travels; the locator did not survive one afternoon. The nasty part: a lane matching on my path finds NOTHING THERE, and the honest reading of nothing is ambiguous between "the warning does not apply" and "it applies and the coordinator misremembered where". A wrong locator does not fail loudly - it fails as an ABSENCE, and an absence is exactly what a spurious warning is supposed to look like. So a wrong path in a false-positive warning makes the warning look CONFIRMED AS SPURIOUS. Second instance today of assert-the-presence-you-expect, this time landing on me. architect sharpening, adopted verbatim: A BROADCAST FALSE POSITIVE SHOULD CARRY THE TEST, NOT THE LOCATION - a path is a fact about a tree that moves, the test is a fact about the defect.

## `c45` - Practice: capture both baselines BEFORE the rebase, not after

**Status:** pending

From architect on PR #60. Compare-Object needs something to compare against, and after a bad merge the pre-state is gone. Every lane today ran the slug diff AFTER finishing and got away with it only because origin/main was still fetchable - that does not hold when the thing you must diff against is your own pre-rebase branch. General form: a check you can only run when nothing went wrong is not a check.

## `c46` - Recording: a borrowed constraint feels verified because it IS verified - somewhere else

**Status:** pending

The injury lane told me participation ingest had "no partial-season shortcut" and I sequenced a critical-path promotion on it. FALSE. enforce_expected_game_coverage belongs to the INJURY-REPORT backfill, not to participation - backfill_season takes --start/--end/--limit-games and filters through _participation_games_in_scope consulting no coverage gate at all. And the injury gate is itself narrower than the phrasing: expected is filtered by --start/--end BEFORE comparison, with an explicit allow_missing_games escape hatch. Real constraint is "whatever window you request must be complete within itself", never "you must ingest whole seasons". Class, and it is new: a claim about component A applied to component B. Both statements true of their own subject, joined by one sentence, nothing reading as uncertain, and the gate cited GENUINELY EXISTS. Same shape as citing the right principle from the wrong ADR. A borrowed constraint feels verified because it is verified - somewhere else - so checking it confirms it and the check does not reveal that its subject was different.

## `c47` - Tooling: compute the backlog dependency graph in CI

**Status:** pending

Raised by the injury lane and it is right. Today the graph produced two independent failures: (1) availability-model human-readable prose said BLOCKED while its machine-readable Depends-on line said READY - architect added the missing edge; (2) schedule-cohort-fingerprint-list depends on injury-report-backfill, which is NOT A SLUG in the file - the real item is injury-report-historical-backfill, a dangling edge nothing detects. And the ten-deep critical path was found by me writing a twenty-line script while looking for something else, not by any check. Three distinct failures of one artefact in one day. Cheap to add: resolve every Depends-on token against the slug set (catches dangling edges), and print the longest path (catches a chain nobody can see by reading 122 items in file order).

## `c48` - RULE: a check that iterates must first assert it found something to iterate over

**Status:** pending

Four instances on 2026-08-21, four different lanes, ALL FOUR in the verification tool rather than the code. (1) frontend browser probe computed count - swatches; a difference of two absences is zero, reading as the property holding perfectly. (2) coordinator read d.get("scoring_periods") - a key that does not exist - got None and nearly reported merged main served an empty schedule grid. (3) injury lane getattr(g,"tipoff_utc",None) off a wrong attribute path returned None 1,230 times and looked like an authoritative negative; nearly killed a real optimisation. (4) draft-tracker lane: FastAPI keeps an included router as one lazy _IncludedRouter, so a test scanning client.app.routes iterated an EMPTY SET and every "no mutating method" assertion passed vacuously. REPOSITORY-WIDE CONSEQUENCE: any test in this repo scanning app.routes is probably vacuous - tell every lane touching the API. Zero routes, zero cells, zero games and zero rows are all indistinguishable from a clean pass.

## `c49` - My mutation harness published two fictional matrices

**Status:** pending

I ran pytest by subprocess without PYTHONPATH. conftest failed to import, every run exited 4, and my harness scored ANY non-zero exit as CAUGHT. Two full matrices reported across two review rounds were entirely ModuleNotFoundError. Caught by the reviewer getting the OPPOSITE result on one mutation and saying so; re-run properly, a real gap was underneath (the classifier's private separator rule, uncovered). Two compounding causes: (a) the machine has no virtualenv, hoops_gm resolves to a stale namespace package, and an editable .pth points at a deleted worktree - so PYTHONPATH is mandatory and its absence fails as an import error rather than loudly; (b) my harness read an EFFECT (non-zero exit) as a CAUSE (test failed). The tell was in my own output - the summary column printed empty for every row because pytest never ran - and I read the verdict column beside it. gates.md already requires green-before/red/revert/green for mutations; my harness did none of it. Rebuilt to assert green-before, treat only rc==1 as caught, name other non-zero as harness failure, and assert green-after.

## `c50` - Twice today "gates green" meant "the gates I remembered"

**Status:** pending

Both on PR #58, both mine. (1) Ran pytest, not ruff format - CI Format step failed. (2) Ran mypy --strict on the SCRIPT and reported "strict mypy clean" - mypy also covers backend/tests, and eighteen test functions had no annotations. Same substitution the frontend lane made in the morning (ran the local gate, reported ready, CI had been red for hours) which I had already named and recorded. Naming a defect class does not confer immunity from it; I committed the same one twice within four hours of writing it down. Mitigation is not discipline: run the full CI-equivalent command set, or nothing.

## `c51` - PostgreSQL was available all along - ~20 handoff entries deferred on a false claim

**Status:** in_progress

Found 2026-08-21 by the PR #64 reviewer in about ten minutes: PostgreSQL 16.9 running on this machine at 127.0.0.1:55432, another lane dev rig (C:\Users\steverones\qimember-devrig, PID 61240, trust auth, superuser qimember). conftest.py ALREADY honours TEST_DATABASE_URL. docs/handoff.md carries roughly twenty separate "no Postgres locally / Docker unavailable / PostgreSQL is CI-only" entries across many PRs - every one a deferred cross-dialect verification that did not need deferring. Mechanism: twenty entries ASSERTED unavailability and none CHECKED it; the first lane wrote it, every later lane inherited it, and it became a standing excuse. This is unexamined inheritance at project scale - the exact class AGENTS.md names - and it survived because "could not verify" is the field where reasoning is least disciplined. ACTION: connection string into docs/handoff.md; assigned to the draft-tracker lane pass.

## `c52` - Recording: report the state you observed, never the parameter you passed

**Status:** pending

Fifth instance of vacuous verification on 2026-08-21, and the only one caught by its own author. The PR #64 reviewer harness branched on dialect == "postgres" and fell through to SQLite for any other token; it was invoked with "pg". The probe ran, passed, and printed plausible results AGAINST SQLITE WHILE LABELLED POSTGRES. It was caught only because the probe printed engine= read from the LIVE ENGINE rather than echoing the argument - so the label and the reality could disagree visibly. The reviewer then discarded every earlier Postgres result it could not vouch for and re-ran rather than reasoning about which were affected. Rule: a diagnostic must report the state it observed, never the parameter it was given. An argument echo cannot detect a silent fallback, and a silent fallback is what a permissive branch produces.

## `c53` - Recording: a blanket except speaks for a failure domain it never examined

**Status:** pending

PR #64 _append: derive_state validates the LOG SEMANTICS; it does not validate the ROW STORAGE CONSTRAINTS. A blanket except IntegrityError then mapped every storage failure to draft_sequence_conflict, which is in _RETRYABLE, which surfaces as 409 documented to clients as transient. Two reachable inputs - an FK-violating player_id, and a sale carrying player_id without player_label which is LEGAL per derivation because _apply_sale takes the label from the open lot - are PERMANENT input errors published as TRANSIENT ones. A conforming client retries forever, and mid-auction the recorder is told "another append reached this draft first" when nothing of the kind happened. Class: careful validation in one domain licensing a careless catch in an adjacent one - the author reasoned hard about candidate derivation and let one except speak for storage. Also note the author PREDICTED a different Postgres divergence (transaction abort) which did NOT materialise - session.rollback handles it - so the worry was in the wrong place while the real defect sat beside it.

## `c54` - RULE: a test can be accurate and non-independent, and only one of those is checked

**Status:** pending

Best finding of 2026-08-21. code-review MOVED ALL THREE FIXTURE PDFs OUT OF THE TREE and the injury lane central vocabulary test STILL PASSED - because it asserted against status_counts in a JSON file THE SAME LANE HAD WRITTEN. The recorded counts were all CORRECT, which is exactly what made it dangerous: the test verified a number against a copy of itself. Accuracy and independence are different properties and only accuracy was being checked. Generalises past fixtures: any assertion whose expected value is derived from an artefact produced by the code under test is a tautology wearing a measurement costume, and it passes hardest when the recorded value happens to be right. Test for it the way review did - DELETE THE SOURCE OF TRUTH AND SEE IF THE TEST NOTICES.

## `c55` - Recording: pytest parametrisation over an empty list collects zero tests and reports green

**Status:** pending

Sixth instance of vacuous verification on 2026-08-21. The injury lane tests are parametrised over SUPPORTED_SEASONS / SEASONS_WITH_A_PROBED_DOUBTFUL. Emptying the latter collected ZERO DOUBTFUL tests and the suite reported GREEN. Particularly silent because pytest prints a passing summary with a smaller number and nothing flags the delta - the same "trend in a field nobody aggregates" mechanism as the vitest slow-test line. Fix applied by the lane: pin the expected COUNTS rather than assert > 0, on the reasoning that three-seasons-to-one is the realistic regression and a > 0 guard would not see it. Companion to c48: a check that iterates must assert it found something - and for parametrised suites, must assert HOW MANY.

## `c56` - Circular dependency: the fingerprint pin blocks the fix that the regeneration needs

**Status:** pending

injury lane, --raw-root flag. test_every_recorded_source_fingerprint_matches_the_file_today pins the committed cohort manifest to SHA-256s of exactly the three files the flag must modify (ingest/backfill.py, injury_report/backfill.py, cohort_evidence.py). Changing them makes the manifest provenance a claim about files that no longer exist; regenerating the manifest needs the ingest database, which is empty, which the sweep exists to fill. THE FIX NEEDS THE REGENERATION AND THE REGENERATION NEEDS THE FIX. Resolved by deferring the flag to land WITH the regeneration, and using DATABASE_URL + CWD in the interim - zero code change, same durable root. The lane declined to hand-edit fingerprints on the grounds that it publishes provenance nobody can check, which is right. Worth noting the guard is behaving correctly; the circularity is a sequencing artefact, not a defect.

## `c57` - Recording: knowing the class confers no immunity - seventh instance, written in the same sitting as the lesson

**Status:** pending

The injury lane disclosure scanner _leaf_paths descended dicts and STOPPED AT LISTS, so a mutation adding an outcome breakdown inside the probe artifact observations list was invisible and the whole file stayed green. The scan reported clean because IT NEVER LOOKED THERE - the app.routes mechanism exactly - and the lane wrote it IN THE SAME SITTING AS RECORDING THAT LESSON. Pairs with my own two instances: I wrote down "ran one gate and reported another" in the morning after frontend did it, then committed it twice within four hours (ruff format, then mypy-on-tests). And my mutation harness published fictional matrices the same afternoon I recorded that a check must assert it found something. CONCLUSION FOR THE REGISTER: naming a defect class is not a mitigation. Only a mechanism is - the lane fix was two unit tests pinning the list descent DIRECTLY rather than leaving it implied by a higher-level test.

## `c58` - Recording: a blocker worked around rather than characterised will be met again

**Status:** pending

The fingerprint circularity (cohort_evidence.py and two siblings pinned by SHA-256 against a manifest whose regeneration needs the database the sweep exists to fill) blocked --raw-root, was correctly worked around, and then blocked Unit 2 generator half - and the lane did not anticipate it the second time, in the same day, having just resolved it. The first encounter produced a workaround; it did not produce the question "which files are pinned, and what else will want to edit them?" Cheap mitigation: when a guard blocks you, enumerate its full scope once and record the list, so the next unit meets a known constraint rather than a surprise. Note the guard is behaving correctly in both cases - this is about how a team metabolises a constraint, not about a defect.

## `c59` - RULE: a mechanism can be real and its sign wrong - measure the direction, never predict it

**Status:** pending

The sharpest modelling finding of 2026-08-21/22. quant and the injury lane jointly argued that shorter injury-report lead times resolve more players, so the legacy era should carry MORE canonical doubtful per date than the 15-minute era. Careful, mechanistic, endorsed by two lanes, and it DECIDED MY SEQUENCING - I moved Unit 2 ahead of the sweep on the strength of it. Measured: legacy 0.917/date vs 15-minute 1.596/date, ratio 0.57x - the 15-minute era carries 74% MORE doubtful, not fewer. The mechanism is real and THE SIGN WAS WRONG. Took 21 minutes of fetching to falsify. Distinct from every other entry in the register: those are about claims stated beyond their mechanism, or guards covering less than they name. This one is a CORRECTLY IDENTIFIED mechanism whose direction was assumed. Lane rule, adopted: NOBODY MAY PREDICT THE DIRECTION OF A POOLED ESTIMATE BIAS WITHOUT MEASURING IT. Two further falsifications in the same run: the scaled full-season projection was 2.3x too low (37 predicted, 84 measured), and December was BELOW average doubtful density (0.808/date vs 1.348 season) when we had argued it was peak - right that the projection was biased, wrong about the direction, again.

## `c60` - Practice: run the free planning subcommand even when you believe you know the number

**Status:** pending

The injury lane quoted me ~341 requests for the 2025-26 injury sweep; the real figure was 640 - it had conflated it with the ~340 legacy-season estimate, while its own earlier estimate for 2025-26 had been ~670 and was close. It caught this BEFORE spending, by running the plan subcommand which enumerates candidates without fetching. Its general form is the keeper: A PLANNING SUBCOMMAND THAT COSTS NOTHING IS WORTH RUNNING EVEN WHEN YOU BELIEVE YOU KNOW THE NUMBER, BECAUSE THE BELIEF AND THE NUMBER CAME FROM THE SAME PLACE. Companion to the observed-state rule: a re-derivation from the same head as the original estimate is not independent, but an enumeration is.

## `c61` - Defect: a DNS failure is reported as contract drift

**Status:** pending

Injury sweep pass one ended with 3 failures of 640, all getaddrinfo failed - an ordinary DNS blip. The tool reported them as "contract drift, not missing", which is a mislabel: a transport failure and a payload-shape change have completely different remedies, and one of them means STOP AND INVESTIGATE THE UPSTREAM. Benign here because they failed at fetch so nothing cached, and resume retried them cleanly (3 fetched, 637 already settled, exit 0). Same class as the draft-tracker 409-vs-422 defect landed the same night: a permanent and a transient failure published under one label. Worth a small fix in the injury-report backfill error classification.

## `c62` - MEASURED: games played is the soft spot, not minutes - and the careful decomposition is WORSE than naive

**Status:** pending

quant research lane, 2026-08-22, 254,512 player-game rows over 2015-16..2024-25 (2019-20/2020-21 excluded as disrupted). Year-over-year r2, season t->t+1: GAMES PLAYED 0.052, minutes per game 0.597, rates 0.509-0.881. Falsified against range restriction - GP r2 ranges 0.28 (unfiltered) to 0.046 (>=1000 min) while MPG r2 holds ~0.60 at EVERY threshold, so the ordering never changes. The settling number: predicting next-season GP for players with 3 prior seasons (n=500), constant league mean gives MAE 15.90, last season GP gives 15.77, best Marcel-style gives 14.32 - A FULL SEASON OF GAMES-PLAYED HISTORY IS WORTH 0.13 GAMES. And the ceiling: predicting season-total points, naive last-season-total gets r2 0.611 while Marcel-rate x Marcel-MPG x league-mean-GP gets 0.576 - THE CAREFUL DECOMPOSITION IS WORSE, because GP error swamps everything downstream. Residual variance share is CATEGORY DEPENDENT: GP+MPG is 79-92% of unpredictable variance for PTS/REB, but only 34-37% for BLK/FG3M where the rate dominates - which matters for punt builds. My own framing (minutes are the soft spot, expected-minutes is the missing unit) was half right and the wrong half was the one I called load-bearing.

## `c63` - PUBLISHED TRAP aimed at availability-model: healthy-worker survivor effect reverses the sign

**Status:** in_progress

arXiv:2603.26935, Yu and Hu, 2026-03-27, stat.AP - verified twice, including a control fetch on nonsense id 2603.99999 which 404s, so the fetcher does not confabulate. Naive survival models on NBA game-log data yield a paradox where players who recently logged heavy minutes appear LESS likely to be injured - an artifact of conditioning on game participation, which induces severe collider bias. Their simulation shows the selection is MATHEMATICALLY SUFFICIENT TO ENTIRELY REVERSE THE SIGN of the workload-injury association, and models relying strictly on observational game logs will systematically UNDERESTIMATE the true risk of heavy workloads. availability-model is currently specified to condition on exactly what the paper says induces the bias. Arrives the same night the injury lane empirically measured a sign reversal in a different quantity - two independent arrivals at the same warning. Action: amendment to the availability ADR, a risk entry, and an explicit identification strategy required by that unit Model gate.

## `c64` - Two committed adapter claims falsified by measurement

**Status:** pending

From the quant research lane, incidental to its main work. (1) docs/adapters/nba-stats.md line 148 says PlayerGameLogs.MIN is a ROUNDED DECIMAL - false; it agrees with MIN_SEC to within 0.5 seconds across all 254,512 rows. (2) AVAILABLE_FLAG is NOT an appearance flag - flag=2 rows have median 23.4 minutes and none are zero - so it CANNOT be used as a non-participation label. The second is the dangerous one: it is exactly the shape someone reaches for when they need absence labels cheaply, and R35 already forbids treating a missing row as an absence. Both are unexamined inheritance in committed adapter documentation, found only because a lane pulled ten seasons of real data for an unrelated question.

## `c65` - RULE: unreachable AND silent is the bad combination - unreachable and loud is fine

**Status:** pending

auction-values lane. importer.py carried a branch handling "resolver accepted the match but the player has no NBA crosswalk row" which SILENTLY SKIPPED the row. Chasing why no test could enter it revealed the branch was STRUCTURALLY UNREACHABLE: build_player_targets derives its targets from player_external_ids where source=NBA, so a player without an NBA link is never a resolution target. A silent skip there would drop a priced player out of every count WHILE EVERY COUNT STILL ADDED UP - the recount-after-deletion shape, in an importer. Replaced with a raise naming the invariant, so if the two queries ever diverge it fails where the divergence is rather than quietly under-importing. The rule generalises: dead defensive code is not automatically waste, but dead defensive code that SWALLOWS is, because it converts a future invariant break into silent data loss. Companion finding from the same lane, arrived at from the writing end: driving a negative case showed the parser rejects it fatally, so a further non-negative assertion could never be reached - DELETED rather than shipped, because an assertion no input can enter is a vacuous check dressed as coverage.

## `c66` - Recording: convenient reasoning, falsified by checking a sibling

**Status:** pending

The auction lane first wrote its adapter page claiming "no live smoke, deliberately - a probe would mean crawling". Re-reading the adapters README it found Basketball Monster is ALSO manual-download and DOES carry an opt-in live smoke via an env var pointing at a freshly downloaded file. Its own words: "my reasoning had been convenient rather than correct". The substantive correction is the useful part: nothing here can be polled, but THE SHAPE OF THE TABLE THE OPERATOR COPIES OUT DRIFTS, and a contract test pinned to a months-old fixture cannot see that. It then drove the smoke rather than shipping it skipping - passing on a real export, red on a renamed value column, red on header-only, red on a negative figure, at THREE DIFFERENT ASSERTIONS so each does distinct work rather than one catch-all absorbing everything. Mechanism: a decision that exempts you from work should be checked against the nearest sibling that did the work.

## `c67` - Correction to ruling (c): the circularity guard Hashtag arm has no production path

**Status:** pending

I told the auction lane the circularity refusal "will fire on Hashtag the day we import Hashtag projections". The lane checked: import_projection_csv REFUSES AN UNVERIFIED PROFILE and only Basketball Monster is verified, so Hashtag projections cannot be imported at all today and the guard Hashtag arm cannot be driven through the production path - that path refuses Hashtag one step earlier. Pinned as an executable test asserting the refusal and its message. The guard itself IS proved end-to-end against a real BBM projection import through the real CSV path, so the mechanism is genuinely exercised; it is specifically the Hashtag arm that is reachable only via a hand-built import record. My statement was a claim about a path that does not exist yet, stated as a driven fact. Class: a coordinator prediction about future behaviour of a guard, phrased as though observed.

## `c68` - RULE: a scan of a set that excludes your work reports success about nothing

**Status:** pending

NEW SHAPE, and the most dangerous variant of R59 yet. The auction lane ran check_no_secrets.py pre-commit: "No secrets found in 330 tracked files." Green, exit 0 - AND IT HAD NOT SEEN A SINGLE FILE OF THEIRS, because they were untracked. Re-run after committing: 347 files. The 17-file delta is the only thing that makes the result mean anything. Distinct from every other instance today: the tool scanned a REAL, NON-EMPTY, CORRECTLY-PARSED set - just not the set containing the work under test. So "assert you found something to iterate over" does NOT catch it; 330 is plenty of something. The rule needs its own limb: A SCAN MUST ASSERT ITS SCOPE INCLUDES THE ARTEFACT UNDER TEST, not merely that its scope is non-empty. Applies to any git-tracked-file-based tool run before commit, which is most of them.

## `c69` - RULE: a second run of an idempotent command observes a different state than the first

**Status:** pending

Auction lane, alembic. First reported steps: 0 - not a failure, because the count came from a SECOND invocation that was already at head. The correct number was 17, obtainable only by counting within the run that did the work. Companion to "report the state you observed, never the parameter you passed": an idempotent command is specifically designed so the second run differs from the first, so a measurement taken from a re-run is a measurement of the wrong event. Third instance from the same lane in one message: pytest -q against addopts already containing -q yields -qq, which SUPPRESSES THE SUMMARY LINE - they were one keystroke from reporting "exit code 0" as a test count. AN EXIT CODE IS NOT A COUNT.

## `c70` - Practice: report the agreement, not only the disagreement

**Status:** pending

The auction lane recorded its boring backlog slug-diff agreement in the header note, reasoning that A LANE THAT ONLY REPORTS THE PAIR WHEN IT DISAGREES IS A LANE WHOSE SILENCE IS AMBIGUOUS. Same mechanism as the twenty PostgreSQL silences, applied preemptively by the producer rather than diagnosed afterwards. Companion: its slug diff ASSERTS origin/main PARSED NON-EMPTY BEFORE COMPARING, because a diff against zero slugs reports "nothing dropped" for the same reason any empty set answers anything asked of it - which is the guard the frontend lane needed in the afternoon and did not have.

## `c71` - A coordinator endorsement launders a selectively-ranged number

**Status:** pending

The quant lane reported "a naive Marcel reaches r2 0.71-0.89 on per-36 rates". I repeated it back approvingly and INSTRUCTED a lane to put it in projection-blending model card. The range silently EXCLUDED steals at 0.496 and turnovers at 0.655; the honest range across all seven categories is 0.50-0.89. The argument survives - 0.71-0.89 is right for the volume categories - but the number as stated was the flattering subset, and the lane only found it by re-running the raw output instead of reading its own note. Same lane, same pass: its range-restriction table was FOUR ROWS OF A SIX-ROW CURVE and the two missing rows were the awkward ones - at >=1500 min r2(GP) ticks back UP to 0.077 and MPG SAGS TO 0.515, contradicting the "~0.60 at every threshold" claim I also repeated. The ordering claim holds at all six thresholds; the tidiness did not. MECHANISM: a coordinator repeating a lane number adds apparent confirmation without adding any check - my endorsement made it harder to question, not easier, and I had verified nothing. Companion to c56: a claim that arrives already argued is the claim nobody re-derives, now with the coordinator as the laundering step. CORRECTED 2026-08-22 by the lane, verified by me: I wrote that the number "had already escaped into a merged model card". IT HAD NOT. Driven on origin/main: git grep -i "marcel" over docs/ EXITS 1, ZERO MATCHES; the model card bullet on main is still the bare original "- source copying or correlated errors between publishers;" with no number and no correlation note. The range existed in exactly three places - the lane message to me, my message back, and its uncommitted draft - ALL PRE-MERGE, and the correction landed in the same commit as the claim first appearance in the repository. I INFERRED "MERGED" FROM "PROMOTED": I had grounds for "I told a lane to put this in a card" and reported "it is in a merged card", which is a different and stronger fact. Same class as the entry itself, one layer up, committed while writing the entry. The lane reason for insisting is the one that matters: an overstated register entry sends a later reader searching for damage that was never there, and a reader who finds none starts discounting the register.

## `c72` - The most valuable unrun experiment: is consensus actually near the ceiling?

**Status:** in_progress

The quant lane strategy recommendation - ship consensus rates x our availability, do not build baseline-model pre-draft - leans entirely on "consensus sits near the reproducibility ceiling of public box scores", and the lane labelled it REASONED, NOT DRIVEN. It never evaluated a single commercial projection set; everything measured is what a naive Marcel reproduces from public data. The experiment is cheap and needs no season to play out: compare the BBM 2026-27 import we already hold against a Marcel built on 2015-25, measuring AGREEMENT rather than accuracy. If BBM is largely reproducible by the monkey, the recommendation is confirmed and we learn what we are paying for. If it is not, the whole strategy needs revisiting before draft day. Also unmeasured and labelled: age curves (PlayerIndex returns 27 columns and NO birth date - driven negative), whether consensus over-projects star games played, and rookie bias.

## `c73` - RULE: vary the observation, not the assertion - a mutation that coincides with your fixture is invisible to any assertion

**Status:** pending

THE SHARPEST ENTRY OF 2026-08-21/22, because it defeats the standard remedy. The auction lane had 100% branch coverage AND the count-standing-in-for-an-observation defect, having conflated two different checks. It fixed the headline test - matched_count == 10 beside len(values) == 10 was TWO LITERALS, NOT A RELATIONSHIP, and an importer writing correct-looking counts and zero rows passes both - then mutation-tested the fix. Two of three mutations died. The third SURVIVED: replacing row_count = parsed.total_rows with the CONSTANT 10 passed, because the only fixture had ten rows, so the constant and the truth COINCIDED. The assertion is real, the value is right, and the test still cannot distinguish counted from hardcoded - AND NO STRENGTHENING OF THAT ASSERTION WOULD HELP. Every other finding today was fixed by making a check stronger; this one cannot be. What it needs is INDEPENDENT VARIATION IN THE OBSERVED QUANTITY: row_count now checked across three fixtures of lengths 10, 8 and 5, and the mutation dies on the five-row file. General form: a single-cohort test cannot tell a counter from a constant no matter how carefully it is written.

## `c74` - Hashtag is nominally primary, not actually - profile verification is unscoped

**Status:** pending

The auction lane recommended Hashtag as primary source because its configurability lets us generate at our own 9-cat basis rather than converting to it, and I approved. But import_projection_csv refuses an unverified profile and ONLY BASKETBALL MONSTER IS VERIFIED, so Hashtag projections cannot be imported at all today. Consequence: (1) the circularity guard Hashtag arm is a claim about a path that does not exist - pinned as an executable test asserting the refusal rather than left as a comment; (2) "Hashtag is primary" is currently nominal. Verifying that profile is unscoped work and is the next item if Hashtag is to be primary in fact. Owner: data-engineer. Blocks aav-blending rather than aav-source.

## `c75` - RULE: a recording cannot notice that it is old

**Status:** pending

NEW CLASS, found by the draft board lane during a rebase. Two of six committed refusal fixtures held text the backend no longer produces - and ONE OF THEM WAS THE DEAD RE-WRAP THE BACKEND LANE HAD JUST REMOVED, so a committed frontend file asserted verbatim a sentence that asserted something untrue about the log. THE ENTIRE FRONTEND SUITE STAYED GREEN THROUGH THE REBASE. Nothing was wrong with the assertions: they were accurate about what was recorded and no longer accurate about the contract. Mechanism: recorded fixtures are the frontend only contact with the backend contract, and NOTHING CHECKS THEY STILL DESCRIBE IT - the frontend gate does not run the backend, the backend gate does not know the fixtures exist, and git reports no conflict because neither lane edits the other file. Caught only because the coordinator required a browser re-verify after the base moved and the lane re-drove the API by hand. Remedy built: scripts/capture_draft_fixtures.py with --check, which re-drives all nine recorded payloads and reports observed against committed, exiting non-zero on drift and refusing to report success having compared nothing. Reproduces the failure exactly on the old fixtures, 4 of 9. Filed as fixture-drift-gate; needs a CI job-shape change (app importable alongside frontend fixtures) so it is backend-owned. GENERALISES TO ANY LANE RECORDING PAYLOADS.

## `c76` - The agent definition itself claimed an enforcement that does not exist

**Status:** in_progress

Aimed squarely at my own framing. I spent the night arguing that .github/agents/ definitions ARE the mechanism and my prose was a lesser hand-written substitute. The draft board lane read frontend.md and found it states "surface parity is a hard rule, enforced by test" - and searched the whole tree: NO SURFACE-PARITY TEST EXISTS. Nothing is violated today because its board renders no decision, so there is nothing to mirror - but the definition claims an enforcement it does not have. Its own framing: the same thing as a stale fixture, one level up, in the file that is supposed to be the mechanism. CONSEQUENCE FOR THE REGISTER: "use the mechanism rather than prose describing it" is right and insufficient - a mechanism can itself be prose asserting an enforcement. Architect action: either write the parity test or amend the claim to say it is not yet enforced. Do not leave a false guarantee in the file lanes are told to trust.

## `c77` - Recording: deleting the thing found the inert prop, not another test

**Status:** pending

Draft board lane wrote tests for the stale-data state, then DELETED staleAfterMs from DraftPage to watch them fail. ALL 23 STILL PASSED. AsyncBoundary raises its banner on isStale || refreshFailed || refreshPending, and the screen polls every two seconds, so data can only age when a read has failed or is in flight - both of which raise the banner independently. isStale never decides anything on that screen; the prop is inert. Its own words: "my browser observation that the stale state works was true about the banner and wrong about the mechanism". Left wired as a backstop, DOCUMENTED AS INERT rather than claimed as covered. The transferable half: it was deleting the thing that found it, not writing another test - the same technique as delete-the-fixture-and-see-if-the-test-notices, applied to a prop rather than to data.

## `c78` - RULE: reading a mutating artefact once produces a finding about the read, not the artefact

**Status:** pending

NEW CLASS. The injury lane, auditing its raw store index for games with a Traditional capture but no Summary capture, briefly saw a FOURTH game in that state. It was a race with an in-flight write. Reading a growing index once would have MANUFACTURED a fourth failure and reported it as a source defect. Caught by looking twice. Generalises to any audit of a live directory, a running log, an open database or a store being written concurrently: a single read of a mutating artefact is a sample, not a measurement, and the difference is invisible in the output. Companion to "report the state you observed": here the state observed was real and transient, and the error is treating a sample as a census.

## `c79` - Corrected: the cache-corruption risk is narrower than the lane warned and than I relayed

**Status:** pending

The injury lane originally told me a fetch-succeeded/parse-failed response would cache its own corruption and replay it deterministically, and I relayed that to two lanes as a standing hazard. IT DID NOT HAPPEN and the description was wider than the real risk: store.put runs AFTER call_with_retry(_invoke), and the nba_api parse failure happens INSIDE _invoke, so nothing is cached. Verified from the raw store index - the three failing game ids carry a BoxScoreTraditionalV3 capture and NO BoxScoreSummaryV3 one, so every retry is a genuine re-fetch, which is why the failure reproduces rather than replays. The real risk attaches to a NARROWER case: a response that reaches store.put and THEN fails downstream parsing - parse_box_score_summary_v3, not nba_api own deserialisation. Matters operationally: someone would otherwise clear a raw store trying to fix a failure that was never in it.

## `c80` - Defect: an error message conflating two conditions with opposite remedies

**Status:** pending

Three 2025-11-19 games (0022500259/260/261) fail with AttributeError NoneType from inside nba_api. The tool reports "the endpoint may have changed OR the request may name something that does not exist" - different conditions, OPPOSITE REMEDIES (investigate the upstream vs record and move on), and it cannot distinguish them. The lane drove the discriminator instead of accepting the message: neighbouring game 0022500258, same date, same endpoint, returns a complete boxScoreSummary. So the endpoint has NOT changed; those three ids have no summary body while LeagueGameFinder lists them and BoxScoreTraditionalV3 serves them - a CROSS-SOURCE DISAGREEMENT, not drift. Under R35 they contribute no rows and nothing is inferred from their silence. Same family as the DNS-blip-reported-as-contract-drift and the draft-tracker permanent-error-published-as-retryable: a message that merges a transient/local condition with an upstream-change condition sends the reader to the wrong investigation.

## `c81` - MEASURED: BBM games is a TIER, not a per-player estimate - the differentiator aims at real empty space

**Status:** pending

THE HEADLINE RESULT of the ceiling experiment, 2026-08-22. Across 505 parsed rows BBM games takes 31 DISTINCT VALUES; among the rotation cohort it prizes (commercial MPG>=20, n=249) it takes 18, and 84.7% SIT ON JUST TWO VALUES - 71 AND 66. That reframes the weak games agreement entirely: r2 ~0.28-0.50 is NOT "BBM knows something about availability we cannot reproduce", it is "BBM BARELY EXPRESSES AN AVAILABILITY OPINION". So the strategy core bet - consume their rates, assert our own games number - is aimed at a genuinely empty space, and that is now MEASURED rather than hoped. Cross-checked before belief: the adapter screenshot reconciliation established that dividing by games reproduces BBM own displayed per-game figures, so games is demonstrably the divisor BBM itself uses. DRIVEN. What cannot be separated from one file: whether the tiering is BBM modelling choice or an artefact of this export view. REASONED, and flagged.

## `c82` - The ceiling claim is NOT established - and the decision is robust to that

**Status:** pending

The ceiling experiment central honesty note. Agreement is SYMMETRIC and neither side is ground truth: one season, no held-out year, no outcomes. High rate agreement (r2 0.726-0.947 per-game, 0.813-0.958 per-36, full range no trimming) is EQUALLY CONSISTENT with "BBM is near the box-score ceiling" and "BBM is also naive", and nothing in this data can distinguish them. BUT THE DECISION IS ROBUST TO WHICH IS TRUE: if BBM is at the ceiling we cannot beat it; if BBM is naive we would be rebuilding something already free. Either way, do not build an in-house rate model before draft day. So the accepted recommendation SURVIVES while its stated justification does not - the load-bearing sentence "consensus sits near the ceiling" remains unestablished and must not stay in the prose unqualified. What IS established is the weaker sufficient claim: CONSENSUS RATES ARE LARGELY REPRODUCIBLE FROM PUBLIC BOX SCORES, AND IT DOES NOT MATTER WHY. Model instance of separating a conclusion from the argument that was thought to support it.

## `c83` - Two independent experiments reproduced the same ordering: rates >> minutes >> games

**Status:** pending

The sibling measured year-over-year SELF-STABILITY (rates 0.51-0.89, MPG 0.597, GP 0.052-0.28). The ceiling lane measured AGREEMENT WITH A COMMERCIAL SET (per-36 rates 0.813-0.958, MPG 0.395-0.747, GP 0.284-0.504). Completely different experiments, same ordering. Also: the crudest possible baseline - literally last season per-game line, ZERO modelling - reaches r2 0.658-0.942 against BBM and BEATS Marcel on points, threes and MPG at every cohort, so "reproducible by a monkey" understates it. And the disagreement is CONCENTRATED not diffuse: short-history, recently-debuted and returning-from-injury players disagree 1.5-2.4x more, widest on MINUTES (0.896 vs 0.386). 66 commercial rows have NO NBA game log in ten seasons at all, ~8 at rotation minutes - for those the caveat is not "less confident" but "WE HAVE NO NUMBER". Our baseline is structurally blind to rookies and international signings.

## `c84` - Finding 0: the sibling lane window was a year short and it would have wrecked this experiment

**Status:** pending

The projection-strategy lane pulled 2015-16..2024-25. 2025-26 IS COMPLETE AND AVAILABLE - 26,651 rows, fetched by the ceiling lane. BBM projects 2026-27 with 2025-26 in hand, so projecting a baseline from 2024-25 would have made it a year stale and rendered every measured disagreement partly an artefact of that staleness. Does NOT affect the sibling own t->t+1 results, which are self-contained. Class: a data window inherited from a sibling unit without re-checking what is available at the time of use - the inputs were right for the question that lane asked and wrong for the question this one asked.

## `c85` - RULE: getComputedStyle reports the value you passed, not the value the renderer produced

**Status:** pending

Draft board lane, and the first instance of the family found by a lane inside its OWN verification rather than in code. It was about to accept getComputedStyle(el).fontWeight === "650" as proof that emphasis had rendered. But font-weight: 650 on a family with NO 650 FACE rounds silently to the nearest available weight, AND COMPUTED STYLE STILL REPORTS 650. It reports the declared value, not the resolved face. That is "report the state you observed, never the parameter you passed" in the one place a browser API looks like a measurement. Driven instead by measuring the rendered advance width of the same string at both weights: 457.54px at 400, 486.54px at 650, 29px wider - so the weight resolves to a genuinely heavier face. GENERALISES: any browser API that echoes a declared value (computed style, dataset, attributes) is a parameter readback, not an observation; measure a consequence instead.

## `c86` - Recording: a coverage guard blind in exactly the direction it existed to cover

**Status:** pending

The draft board reached-set guard - built specifically to stop the test suite shrinking quietly - lived in a trailing it() INSIDE the refusal block, so a refusal driven by a block BELOW it counted as undriven. On adding a seventh case it reported a shortfall THAT WAS NOT REAL. It failed loudly, which is the only reason it was caught; HAD THE ARITHMETIC GONE THE OTHER WAY IT WOULD HAVE PASSED OVER A SET IT COULD NOT SEE. Now a file-scoped afterAll comparing the driven set against fixture keys, PROVEN BY DELETING ONE REGISTRATION and watching it fail by name. The lane own summary is the entry: "it was the mechanism I built specifically to stop the suite shrinking quietly, and it had a blind spot in exactly the direction it existed to cover. Naming the class did not save me; deleting a thing and watching did."

## `c87` - A screen fixed a contract defect more cheaply than the contract could have

**Status:** pending

Draft board lane, arguing AGAINST a change I had left as the backend call. service.py:579 embeds the inner refusal advice verbatim, producing two instructions where the first describes the hypothetical replayed log. The consuming lane view: the inner advice is CORRECT ABOUT THE LOG IT DESCRIBES, and stripping it would lose the reason the replay refused - the only part telling the recorder WHY. So the defect is ORDERING AND EMPHASIS, not content, and emphasis is a screen concern. Fixed by wrapping the final clause in <strong> with lead + remedy === detail byte for byte, so the recorder still reads the server sentence in the server words in the server order - weighted, not paraphrased. Worth recording BECAUSE IT IS THE INVERSE OF THE USUAL RULE and the lane said so rather than pretending it generalises: normally a contract fixed at the source beats a workaround in the view.

## `c88` - RESOLVED: BBM is not naive - the regression SLOPE answers what the correlation could not

**Status:** pending

The ceiling lane withdrew the strong form of its own limitation. Correlation is symmetric and cannot distinguish "near the ceiling" from "also naive"; THE SLOPE CAN, and needs no outcomes and no held-out year. Slope of commercial per-36 on last-season per-36, n=232: STL 0.824 (17.6% shrink), TOV 0.850, AST 0.912, PTS 0.929, BLK 0.957, FG3M 0.969, REB 1.001 (-0.1%). BBM SHRINKS EACH CATEGORY ALMOST EXACTLY IN PROPORTION TO HOW UNSTABLE THAT CATEGORY IS YEAR-OVER-YEAR - and the stability column is the SIBLING LANE INDEPENDENT MEASUREMENT, made without any sight of BBM (STL least stable at 0.570, REB most stable at 0.881). Inverse-monotone with one exception (AST). A monkey does not do that. The elegance is that neither measurement alone shows it: the evidence is the RELATIONSHIP BETWEEN TWO INDEPENDENT MEASUREMENTS MADE BY DIFFERENT LANES FOR DIFFERENT PURPOSES. Negative result reported alongside: BBM does NOT shrink short-history players rates harder (0.944 vs 0.952) - expected and false, reported because it is the kind of thing that quietly gets dropped.

## `c89` - STRATEGY CHANGE: consume their minutes too, not only their rates - the ADR-002 seam is at GAMES, not at minutes

**Status:** in_progress

The ceiling lane measured BBM minutes slope at 1.157 pooled - it AMPLIFIES rather than regresses, giving high-minute players more and low-minute players less than last season did. That is the opposite of shrinkage and is the signature of OUTSIDE INFORMATION no box score contains: depth charts, offseason moves, role changes. It then caught its own confound - implied MPG is season minutes / games, so a coarse games divisor leaks straight in - and measured within-bucket: 1.086 and 1.057. About half the amplification was the confound; direction survives, magnitude inflated ~2x. Control run to prove the check discriminates: PTS/36 slope barely moves (0.929 -> 0.903/0.972) which is what MUST happen since the divisor cancels for rates. CONSEQUENCE FOR THE ARCHITECTURE: the strategy said consume their rates and assert our own games. It should say CONSUME THEIR RATES AND THEIR MINUTES, ASSERT OUR OWN GAMES. Minutes-per-game is role/production, which BBM does well and with information we lack; games-played is availability, where BBM publishes two tiers for 85% of the pool and has essentially no per-player opinion. That sharpens ADR-002: the production/availability seam falls at GAMES, not at minutes.

## `c90` - PATTERN: the direction has been right every time and the magnitude wrong every time

**Status:** pending

Named by the ceiling lane about its own work, and it is the complement to "a mechanism can be real and its sign wrong". Three instances in one night, all its own, all caught by checking whether its own choices manufactured the effect: the games-level gap +5.1 shrunk -> +3.9 unshrunk (magnitude inflated ~30% by a shrinkage parameter it chose); the minutes slope 1.157 pooled -> ~1.07 within bucket (inflated ~2x by a divisor confound); and the sibling flattering-subset range 0.71-0.89 -> 0.50-0.89. In each case the directional claim SURVIVED measurement and the size did not. So the register now carries both halves: a mechanism can be real and its sign wrong (measure the direction), AND a direction can be right while its magnitude is an artefact of a choice you made (measure whether your own parameter manufactured the size). The second is harder to catch because the finding still reads as confirmed.

## `c91` - COORDINATOR FAILURE: every lane touches two append-only docs, so every merge invalidates every in-flight PR

**Status:** pending

On the night of 2026-08-21/22, PR #64 was forced to rebase THREE TIMES, each time because I merged a different PR that touched docs/handoff.md and docs/backlog.md. #67, #65 and earlier merges each invalidated it. Every lane appends to both files by house rule, so the two files that exist to prevent knowledge loss are also the two that guarantee a merge conflict between any two concurrent units. The cost is real: three rebases of a reviewed, approved PR, each carrying a fresh chance of a resolution error in exactly the file whose resolver silently deleted three items earlier the same day. And #66 was stacked on #64, so each rebase cascaded. MY ERROR, not the lanes: I merged in the order things went green rather than in DEPENDENCY ORDER, and I merged docs-heavy units while a stacked pair was in flight. Mitigations, in order of value: (1) merge a stack bottom-up and hold everything else until it lands; (2) batch docs-only merges into one window rather than interleaving them with code units; (3) note that append-only resolution is mechanical but not free - it is the one file class where a conflict is guaranteed rather than incidental.

## `c92` - RULE: authorship is not evidence - you are the least reliable source on code you remember writing

**Status:** pending

The auction lane wrote TWO false sentences about its own module, in the same document, hours after writing the module. (1) It asserted unresolved names "land in unmatched_count with the verbatim text preserved, so the gap shows up as data rather than as silence" - importer.py:346-348 shows unmatched rows CONTINUE and are never written; the database keeps a count and nothing else. (2) It named the flag --unresolved-report; it is --report-dir. Neither was a typo, both were plausible, and - the load-bearing part - BOTH ERRED IN THE DIRECTION THAT MADE ITS OWN DECISION LOOK CHEAPER. That is rhetorical convenience with ones own code as the subject, which AGENTS.md names as the failure with no CI job. Its own formulation: AUTHORSHIP IS NOT EVIDENCE - it was the least reliable available source on that module PRECISELY BECAUSE it remembered writing it, and recall felt like verification. The fix was mechanical rather than more care: extract every --flag and every Model.attr the adapter page asserts, assert both sets parse non-empty, compare against the parser and the module. Same shape as the agent-definition finding: the thing that would have prevented it was a file, not an intention.

## `c93` - RULE: a scanner for syntax must exclude prose that discusses that syntax

**Status:** pending

The auction lane searched docs/handoff.md for <<<<<<< HEAD and matched LINE 10732 - an earlier handoff entry QUOTING a marker inside a sentence - rather than the real conflict at 14578. It built a resolution on that hit and LEFT THE ACTUAL MARKER IN PLACE. Caught only because a final assertion re-scanned the merged text; without it, a file with a live conflict marker and a green recount would have been committed, because THE RECOUNT DOES NOT READ MARKERS. This is the mirror image of the resolve_doc_conflicts.py defect fixed in 9f0561f an hour earlier (separator matched by prefix rather than equality) - hit by hand, in the file that documents it. A repository whose docs quote their own machinery is exactly where this bites, and this one does so extensively. Fix: anchor to line starts and assert EXACTLY ONE of each of the three markers, not merely that markers exist. Open and unswept: no one has checked whether other docs in the tree quote a conflict marker in prose.

## `c94` - My chat broadcast is a place that cannot recount itself

**Status:** pending

The auction lane framing of my second stale-count error, and it is sharper than my own. I relayed "128 items, 45/1/82" when origin/main recounts to 45/1/83/129 and its own header agrees with itself. Its words: "the number was restated in a place that cannot recount itself, which is exactly the failure the header documents for rebases, ARRIVING THROUGH CHAT INSTEAD". The backlog header prose forbids reconciling from two headers because neither side of a rebase conflict was computed with the other lane items in view. A coordinator message is a third such place - it carries a number with no mechanism to re-derive it, and it arrives with more authority than either header. Recorded in the backlog header as mine-by-route rather than mine-by-fault, alongside the rebase case. Also from the same resolution: the header conflict had HEAD at 129 and the branch at 122, AND THE ANSWER WAS ON NEITHER SIDE.

## `c95` - RULE: a mode is the one summary statistic guaranteed to equal a verbatim cell

**Status:** pending

The ceiling lane leak filter screened NAMES and RATE-SHAPED DECIMALS and treated anything DISTRIBUTIONAL as an aggregate, therefore safe. But it printed the two modal games values from the paid export in prose. Its own diagnosis: A MEAN ALMOST NEVER EQUALS A CELL; A MODE ALWAYS DOES. The filter wiring was correct and PROVEN TO FIRE with a 505/505 scope assertion - its CATEGORY was wrong. AND I AMPLIFIED IT: I quoted the two values back in a coordinator message, which is how the lane noticed them sitting in prose rather than in a table. So a proven-firing leak guard, a coordinator, and a reviewer all passed the same two integers. The finding - 84.7% concentration on two values - SURVIVES THEIR DELETION COMPLETELY, which the lane correctly reads as the tell that they were never load-bearing and were printed out of habit. Rebuilt scan compares text against the MODE, MIN and MAX of every paid column with a tripwire that plants a modal value and must hit or the run is void.

## `c96` - RULE: a check that fires on almost everything tests nothing - the complement of the empty-set class

**Status:** pending

The ceiling lane built an intermediate leak scan flagging ANY number coinciding with ANY cell in the paid file. It returned 436 HITS and the lane DISCARDED IT: a season-totals file contains nearly every small integer, so the scan cannot fail informatively. Its formulation is the entry: A CHECK THAT CANNOT FAIL INFORMATIVELY IS THE SAME DEFECT AS ONE THAT CANNOT FIRE. This is the complement of the dominant class recorded across 2026-08-21/22 - nine instances of a check examining an empty set and reporting success. Here the check examines everything and reports failure, and both are indistinguishable from a check that is not looking. Related and already in the register: a guard that cries wolf is the one the next person loosens. This adds the measurement: if a guard fires on a majority of inputs, its output carries no information regardless of whether anyone loosens it.

## `c97` - A structural guarantee degraded to a discipline, flagged by the lane that degraded it

**Status:** pending

The projection strategy document rests on the claim that our availability model STRUCTURALLY CANNOT SEE BBM games assumption - projection-blending states the assumptions are not inputs and that source_games_played_assumptions is a table the blending service never queries. The ceiling lane then READ THAT COLUMN to score us against it, and flagged unprompted that the guarantee is now true only by discipline: the measurement must never become a fitting input, INCLUDING INFORMALLY, BY AN AUTHOR WHO REMEMBERS THE NUMBER. Note the shape: nothing in the code changed, no gate was weakened, and the guarantee moved from structural to behavioural because a human now knows a number. That is the anti-circularity argument for ADR-002 losing its mechanism while keeping its wording - exactly the failure the strategy document warns about one layer up, arriving through the act of validating the strategy.

## `c98` - A check whose label names a cause it has not established

**Status:** pending

The ceiling lane slug diff reported "1 dropped vs main" and it was NOT a drop - origin/main had advanced one commit past its merge-base (#65 adding vitest-explicit-timeout), and the branch had never touched docs/backlog.md, verified by an empty git log origin/main..HEAD -- docs/backlog.md. The lane point: THE CHECK LABEL IS "DROPPED VS MAIN" AND THE NAIVE READ OF A NON-ZERO VALUE IS "THIS BRANCH REMOVED AN ITEM", but the observed state was that MAIN GAINED ONE. Same shape as the parameter-versus-state entry and as the draft-tracker 409-vs-422: the output named a cause it had not established. Remedy: a set-difference check must report WHICH SIDE MOVED, not merely that the sets differ.

## `c99` - RULE: escalate when you have the answer and it cuts against your own work

**Status:** pending

The governance lane wrote the length rule, then hit a case where it cut against a sentence it wanted to land, argued both sides honestly, and handed the call up. I declined the exception - an exception made by a rule author on the rule first night is how the rule stops meaning anything - and the finding was relocated to gates.md where its instance already sat, at less than half the words. THE LANE OWN ADDITION IS THE USEFUL FORM: "the argument I handed up was already complete, and I handed it up anyway. A lane that only escalates when genuinely undecided will escalate rarely and late. The case worth copying is escalating when you have the answer and it cuts against your own work - because that is precisely when you cannot trust yourself to apply it." It also named its own tell: it would not have needed a view on file contention if it had believed its own paragraph. ASKING PERMISSION WAS THE HONEST HALF; WANTING A YES WAS THE OTHER HALF. Note the outcome was not a compromise - the finding landed shorter, better placed, and attached to the check it motivates, and the branch dropped out of contention with three of five docs branches as a side effect.

## `c100` - STAFFING CONSTRAINT: whoever fits the availability model must not be whoever read the commercial games column

**Status:** in_progress

The first guard in this project that NO REVIEWER CAN CHECK. The ceiling lane read BBM games column to score our baseline against it. That measurement must never become a fitting input - and the lane identified the consequence I had only half-stated: it is itself now the wrong person to choose a shrinkage target, because I CANNOT DEMONSTRATE THAT I HAVE FORGOTTEN A NUMBER AND NO REVIEWER CAN CHECK THAT I HAVE. Every other guard here is externally checkable; this one is not, which is exactly why it must be a STAFFING CONSTRAINT rather than a promise. Landed in docs/models/consensus-reproducibility.md where the next quant lane hits it before starting, not in a message thread. The lane explicitly declined to frame it as a disclaimer: it is a REAL COST OF HAVING RUN THE EXPERIMENT, the experiment was still worth running, and the cost should be paid deliberately rather than discovered by whoever picks up availability-p-play-model.

## `c101` - RULE: a check that cannot find its input must fail, not pass

**Status:** pending

After the ceiling lane removed its scratch worktree, its leak scan CRASHED ON THE MISSING TARGET rather than skipping it and reporting clean - which is precisely the behaviour the nine vacuous-scope instances of 2026-08-21/22 did not have. Repointed at the pushed branch via git show so it reproduces without a worktree; re-ran; tripwire fires. The lane framing is the entry, and it closes the pair: A CHECK MUST BE ABLE TO FAIL INFORMATIVELY (the 436-hit rule - a scan flagging almost everything tests nothing) AND MUST FAIL LOUDLY WHEN IT CANNOT LOOK AT ALL. Both halves are the same defect seen from opposite ends: a check whose output carries no information about the thing it names.

## `c102` - Ruling owed: does locating the ADR-002 seam at games rather than minutes warrant an amendment

**Status:** pending

ARCHITECT DECISION, mine, deferred to the morning rather than taken at 02:20. The ceiling lane measured that BBM minutes carry real information a naive baseline cannot reproduce (slope 1.06-1.09 within bucket, amplification being the signature of depth-chart and offseason knowledge no box score holds) while its games field is two tiers covering 85% of the relevant pool. Strategy changed to CONSUME RATES AND MINUTES, ASSERT GAMES. The lane flagged it as a clarification AND INCLUDED THE ARGUMENT AGAINST ITS OWN READ: locating the seam is what licenses consuming a third party minutes, which is a strategy commitment rather than an implementation detail. My provisional read was implementation; the counter-argument is strong. Leaning AMEND: ADR-002 says production and availability are computed separately and fused explicitly, and an implementer reading only that would reasonably place the seam at minutes. Recording where the boundary actually falls, with the measurement as evidence, changes what someone builds - which is the test for an ADR. Proposed only; the owner accepts.

## `c103` - HAZARD: Select-Object -First closes the pipeline early and $LASTEXITCODE reads 0 on a failing command

**Status:** pending

Found by the backlog-graph lane, and it is aimed at the coordinator practice used all night. Running `python scripts\backlog_graph.py 2>&1 | Select-Object -First 10; echo $LASTEXITCODE` printed a real defect AND rc=0. The true exit was 1 - Select-Object -First closes the pipeline early, so the exit code read belongs to the truncated pipeline rather than the command. The lane nearly reported a bug in its own tool that did not exist: THE FAILURE WAS IN THE VERIFICATION, NOT THE CODE. Second instrument, same session, same shape: `pytest -q | Select-String "passed|failed"` matched NOTHING and returned silently - a green-looking result from a check that found no subject; the suite was confirmed at 1,443 tests by reading junit element counts instead. Coordinator audit: I used `| Select-Object -First N` throughout the night, but every conclusion I drew was from OUTPUT TRUTHINESS (if ($var)) rather than from $LASTEXITCODE after a pipe, and I re-verified the one load-bearing grep without a pipeline. Practice: never read $LASTEXITCODE after a truncating pipe; redirect to a file or capture first.

## `c104` - RULE: documenting a defect class creates false positives for the search that detects it

**Status:** pending

Discovered by re-verifying my own earlier conclusion. On 2026-08-21 I ran `git grep -n "app\.routes"` over merged main and got ZERO matches, which narrowed R59 repository-wide claim to what the evidence supported. Re-run tonight on the new main: FOUR MATCHES. All four are our own prose - one risks.md R59 row and three docs/handoff.md lines describing the finding. Zero code. So the original conclusion stands AND the check that established it is now polluted by the register entry recording it. This will worsen as the register grows: every entry naming a code pattern becomes a false positive for the grep that would find that pattern. Companion to the auction lane rule that a scanner for syntax must exclude prose discussing that syntax - here the prose is OUR OWN and was written BECAUSE of the scan. Remedy: scope such greps to code paths, and note in the entry that the entry itself is a match. Credit: the governance lane had already recorded "the app.routes grep covered merged main at 9f0561f only", anticipating the staleness though not this cause. SHARPENED by the backlog-graph lane, and it is worse than symmetric: THE REGISTER ENTRY IS GUARANTEED TO MATCH, FOREVER, WHILE THE CODE INSTANCE MAY NEVER RECUR. So the signal-to-noise of such a grep ONLY EVER DEGRADES, and it degrades fastest for the classes we cared most about - the ones with the longest entries. Mitigation is producer-side: git grep -- ":!docs/" for a code claim, and SAY SO IN THE CLAIM. Not yet driven on this repo.

## `c105` - open_canvas succeeding is not evidence the canvas works - it echoes the input

**Status:** pending

Found by the draft-tracker lane while diagnosing the wedge blocking #66. open_canvas returns SUCCESS with the url and title THAT WERE PASSED TO IT; every action that must reach the live page - read_page, screenshot_page, navigate_page, evaluate_javascript - times out. So a lane that opened a canvas, saw a success result and concluded the browser was working had a check that COULD NOT FAIL: it reported the parameter passed, never the state observed. Tonight dominant class, in the tool currently holding up a merge, and it is why "the canvas opened" was an unreliable signal across seven instances between four sessions. The lane probe was built so it could not lie in the other direction either: its success marker was COMPUTED IN JS rather than a literal in the file, so a cached blank, a partial load, or a DOM rendered without script execution all fail to produce it. Cause not established - no listener in the 9200-9400 CDP range, so it could not distinguish a dead browser from a non-TCP transport, and it reported that as a negative result rather than dressing it as a diagnosis. Workaround closed: frontend/package.json has no Playwright, jsdom only, which does not render.

## `c106` - VERIFIED and VINDICATED: print-do-not-judge, by a 40.6% improvement that a threshold would have failed on

**Status:** pending

Unit 2 delta path executed on PR #72 - cache prefix hit, baseline restored, both tables printed. First real numbers: backend suite.test_time_ms 348,122 -> 206,746, a -40.6% DELTA. It is almost certainly NOT A SPEEDUP: the top movers all collapse from ~1,500-3,200ms to a ~200-280ms floor, the shape of session-scoped fixture and database warm-up charged to whichever test touches it first, and THE SET OF TESTS PAYING THAT COST DIFFERS BETWEEN RUNS. A THRESHOLD ON SUITE TOTAL WOULD HAVE FIRED ON A 40% IMPROVEMENT, ON THE FIRST RUN IT EVER HAD A BASELINE. Every direction of threshold is wrong on this data. The binding constraint I was handed - print the delta, do not judge it - is now supported by the run rather than by the argument that predicted it. Also driven: the structural fix to the count defect, +12 on the headline and "12 tests not in the baseline, 0 in the baseline and not here" from ONE enumeration, so they cannot disagree - against 1,443 real cases. TWO HONEST LIMITS, both in the handoff: the commissioning bug was a MONOTONE CLIMB ACROSS FIVE RUNS and one baseline cannot show a trend, so nobody should read this as proof it would have caught 3,177->4,298; and the per-test top-fifteen table is dominated by attribution noise on its first real run and may not be worth its width.

## `c107` - A withdrawn claim: an environment that never varies cannot discriminate between two implementations

**Status:** pending

The backlog-graph lane was one sentence from telling me that frontend 0-added/0-removed PROVES its vitest absolute-path relativisation works. It checked first. GitHub workspace root is /home/runner/work/hoops-gm/hoops-gm on BOTH runs - verified in both logs - so UNRELATIVISED ABSOLUTE PATHS WOULD HAVE MATCHED TOO. The run shows the stored names ARE relative; it does not discriminate between the two implementations, because the thing that would break the naive one never varies in this environment. Its own framing: one sentence away from a report that is structurally correct and semantically empty - R59 second limb, IN THE SENTENCE CLAIMING R59 SECOND LIMB HAD BEEN AVOIDED. The relativisation still earns its place for local-vs-CI and a differing runner root, but that remains reasoned and this run did not change it. GENERAL FORM: a passing observation in an environment where the failing input cannot occur is not evidence about the implementation - it is evidence about the environment.

## `c108` - Technique: commit statistics as the check, not confidence in the regex

**Status:** pending

The backlog-graph lane stripped surviving conflict markers by filtering ^=======$ across the whole of docs/handoff.md - a 15,000-line file. That filter WOULD SILENTLY DELETE ANY SETEXT h1 UNDERLINE, which is a destructive edit disguised as a cleanup and is resolve_doc_conflicts.py exact failure mode. It did not reason that the regex was safe. The rebase reported 1 file changed, 65 insertions(+), ZERO DELETIONS - and zero deletions is PROOF no legitimate line was removed, independent of whether the regex was correct. Generalises: after any bulk text transformation, the diffstat is an observation of the RESULT while the regex is a description of the INTENT, and only one of them can be wrong in your favour. Cheap, always available, and it discriminates exactly where confidence does not.

## `c109` - The verification-tool class does not stop at code we wrote - it reached the platform

**Status:** pending

Closing generalisation from the backlog-graph lane, and it is the right summary of 2026-08-21/22. The failure was in the VERIFICATION rather than the code roughly ten times: a mutation harness scoring rc==4 as caught; a grep matching prose about the syntax it searched for; Select-Object -First truncating a pipeline so $LASTEXITCODE read 0 on a failing command; Select-String matching nothing and returning green silently; getComputedStyle echoing a declared font weight; a coverage guard blind in the direction it existed to cover; a leak filter whose category excluded the one statistic that equals a cell; a secret scan over 330 files that contained none of the work; a slug diff whose label named a cause it had not established; AND FINALLY open_canvas, which returns success by echoing the url passed to it, so four sessions across seven attempts each had a check that could not fail. The lane framing: "report the state you observed, never the parameter you passed - the rule from my kickoff, violated by the tool we were all using to check whether the rule held." The class does not stop at code we wrote; it reaches the platform tool-call result, and nothing in a gate can see that.

## `c110` - A number can go stale in the flight time of the message carrying it

**Status:** pending

Fifth stale figure I gave a lane, and the first wrong in a NEW way. I said main read 130 items, 47/1/82. It read 133, 46/1/86 - not a transcription slip, THE SHAPE DIFFERED, because #66 landed between my message being composed and the lane reading it. Earlier instances were all "correct about a tree that no longer exists"; this one was correct about a tree that STOPPED EXISTING DURING THE MESSAGE FLIGHT. There is no verification a sender can perform that survives this - the number was true when written and false when read, and nothing in the message can say so. Confirms the standing practice is the only defence: the recipient recounts from the finished file and treats any figure in a coordinator message as a cross-check that may already be wrong, never as an input. The lane made the recount believable rather than merely recomputed by a different move: THE DELTA BETWEEN ITS NUMBER AND MAIN IS EXACTLY WHAT ITS OWN COMMIT DOES - main 46 done plus its single flip, main 86 pending minus that same one.

## `c111` - A delta with no named baseline is a number with no referent

**Status:** pending

I asked the backlog-graph lane whether its per-run report prints WHICH baseline key it hit. It did not - and the provenance did not exist to print: the artifact carried schema and label and NO RUN IDENTITY AT ALL. So the delta table could not distinguish the commit before it from a fortnight-old cache the restore-key prefix happened to match. Now prints "Current run X against baseline Y - the base a delta is measured from is an input to the delta, so it is named here rather than assumed to be the previous commit." Driven with two synthetic junit files under two different GITHUB_SHA values, five new tests. THE JUDGEMENT CALL IS THE INSTRUCTIVE PART: SCHEMA deliberately NOT bumped, because every cached baseline predates the field and bumping would make read_metrics reject them - SILENTLY DROPPING THE FIRST DELTA AFTER MERGE, which is the unit entire purpose - to gain nothing. A source-less file reads "unknown"; attributing the current sha to a file that never carried one would be the parameter-for-state swap in the module whose docstring forbids it. And the lane RECORDED IN ADVANCE that the first CI run will print "unknown", so nobody reads expected output as a defect.

## `c112` - HAZARD: two of git own commands disagreed about git own index

**Status:** pending

After resolving both files in a rebase, `git rebase --continue` reported "You must edit all merge conflicts" while `git status` in the same second reported "all conflicts fixed: run git rebase --continue" and `git ls-files -u` returned ZERO unmerged entries. Triggered by an earlier `git stash push` that failed with "could not write index" mid-conflict. Recovery that worked: git commit -C <sha> then git rebase --quit then git cherry-pick - operations that reach the identical tree WITHOUT CONSULTING THE WEDGED STATE. Practical rule: DO NOT STASH DURING A CONFLICTED REBASE. Reported by the lane as diagnosed, not understood - a reliable recovery and a plausible cause, not reproduced deliberately, and labelled as such rather than dressed as a diagnosis.

## `c113` - Recording the merge-queue concurrency race

**Status:** pending

COORDINATION DEFECT, mine. I signalled three lanes (#71,#72,#73) to rebase, then merged #70 into that same window. All three rebases went stale on push. Cost: three invalidated full CI runs. Cause is not lane process but a coordinator merging into a window it had just opened. REMEDY: freeze main; exactly one lane holds a rebase window at a time; nothing lands between the signal and that lane's merge. Under the raced shape each lane pays one rebase per merge ahead of it (8 across 4 PRs); under the freeze each pays one (3). The waste is the concurrency, not the rebasing.

## `c114` - Recording that append-only docs serialise the merge queue

**Status:** pending

STRUCTURAL, not a bug. docs/handoff.md is append-only and docs/backlog.md carries a counted header, so EVERY PR in the fleet touches both files and every merge conflicts every other open PR. Five lanes can develop in parallel but cannot land in parallel. Throughput ceiling is one merge per CI cycle regardless of lane count. The counted header has caught 4 real stale counts (none authored by the lane that hit them) so it is earning its cost, but the tradeoff should be stated in gates.md rather than rediscovered. OPEN QUESTION for architect: can the header be verified in CI without being stored in the file.

## `c115` - Recording that an unreachable fix is untested by definition

**Status:** pending

From the auction lane. A defensive correction (is -> ==) survived deliberate reversion because no input can reach that line at all. This is the tripwire rule arriving from the opposite direction: the standing rule is prove a test reaches the code; this is prove the code is reachable at all. Different failure modes - a live path with no test that visits it, versus a path nothing can visit. Only caught by re-running the WHOLE mutation set rather than the subset just touched. OPERATIONAL CONSEQUENCE: re-running only what you changed misses survivors in code you did not change.

## `c116` - Recording that GITHUB_SHA names the run not the commit

**Status:** pending

Driven, not reasoned: run metrics printed baseline source 0d0cc81 where the branch head was b107f1b. GITHUB_SHA is the merge commit for pull_request events and the branch head for push, so the same code is reported under two identities depending on the triggering event. Honest for a delta (it names the run, which is what a delta is between) but NOT a stable key for tracking one commit across event types. Needs one line in the module saying so before someone reaches for it as an identifier.

## `c117` - Recording the true-negative half of a guard claim

**Status:** pending

A guard that fires on every run is reporting on the process, not the artefact. backlog_graph.py passed clean on a docs-only rebase that moved no counts, after four consecutive real catches. Four catches PLUS one clean pass is a materially stronger credibility claim than four catches alone, and almost nobody records the quiet run. Applies to every check in the repo: report the run where it correctly said nothing.

## `c118` - Recording that I propagated a branch capability as a main guarantee

**Status:** pending

MY DEFECT. I told three lanes that scripts/backlog_graph.py checks the backlog header and had caught four stale headers, and offered it as grounds to run before pushing. FALSE ABOUT MAIN: _check_header and HEADER_RE exist only on PR #72 head 09eed61, unmerged. grep header on main returns one docstring line. The four catches were real but occurred on #72 own branch plus resolve_doc_conflicts.py during rebases. This is unexamined inheritance committed in the instruction telling people to check things. Caught only because the governance lane injected before relying. REMEDY: a capability claim must name the tree it holds on, and a coordinator relaying one must verify against that tree.

## `c119` - Recording that a conflict-only check misses every clean merge

**Status:** pending

From the governance lane, and it reframes PR #72 from housekeeping to a live hole. The backlog header recompute lives in resolve_doc_conflicts.py, which runs ONLY when there is a conflict. So a header edited on a branch that merges cleanly is checked by nothing - and the clean merge is the likelier case. This is gates.md own line inverted: a check that runs only when something went wrong misses every case where nothing did. #72 moves the check into CI and closes it.

## `c120` - Recording a no-op mutation scored as a result, by me

**Status:** pending

MY DEFECT, verifying c118. I injected a dangling edge using the string "Depends on: `slug`" when the file uses "**Depends on:** `slug`". No match, file unchanged, tool returned clean, and I was one keystroke from reporting that the tool catches no dangling edges either. A no-op edit scored as a measurement. REMEDY (now applied): assert the mutation changed the file - character count before and after - BEFORE running anything against it. Same family as the mutation harness that exited 4 on every run and scored every non-zero as caught.

## `c121` - Recording that I hit my own documented Select-Object trap twice

**Status:** pending

MY DEFECT. Register already carries: Select-Object -First closes the pipeline early and $LASTEXITCODE reads 0 on a failing command. I hit it twice within five minutes while checking whether a check works, reporting rc=0 for a run that was rc=1. Combined with c120 this nearly produced a confident report that backlog_graph.py catches nothing at all. THE HARNESS WAS THE DEFECT, IN THE INVESTIGATION OF WHETHER THE HARNESS WAS THE DEFECT. Documenting a trap does not immunise the documenter.

## `c122` - Recording a stale count that matched no tree at all

**Status:** pending

From the governance lane, and it is a DIFFERENT failure from the five stale counts before it. Those were real numbers read off the wrong tree - naming the head fixes them. This one (130 total, 47/1/82) was ASSEMBLED FROM LANE REPORTS: internally consistent, arithmetically sound, corresponding to no tree that ever existed. Naming the head cannot fix it because there is no head it came from. REMEDY differs: not "say which tree" but "do not compose a total out of deltas people told you - read the file".

## `c123` - Recording that a check can be right for reasons that expire

**Status:** pending

From the ceiling lane, and it generalises past the base-is-an-input class. They ran the WRONG slug diff (against origin/main) alongside the RIGHT one (against their own merge base) and the two agreed - because they had just rebased, so merge base WAS origin/main. The wrong check looks correct precisely when it cannot mislead you, and stops looking correct only later once the base moves. CONSEQUENCE: "I verified two methods agree" is weak evidence whenever one method depends on state that has not moved YET. It also explains why this class survives review: at the moment anyone looks, they agree. The disagreement is a function of elapsed time and no reviewer holds the clock.

## `c124` - Recording that correcting a claim misses copies that merely cite it

**Status:** pending

From the ceiling lane. A headline claim (naive Marcel reaches r2 0.71-0.89 on per-36 rates) was corrected in docs/models/ where it is argued, while two other files carrying the same flat unsubsetted claim were not - docs/backlog.md and docs/models/projection-blending.md. THE FIX LOOKS COMPLETE FROM INSIDE THE DOCUMENT, because the document that argues a claim is the one you are looking at and the files that cite it are invisible from within it. REMEDY: after correcting a claim, grep the distinctive numeral or phrase across docs/ and confirm every surviving instance carries the qualification.

## `c125` - RETRACTED - the false guarantee did not exist

**Status:** done

RETRACTED BY DRIVING. I claimed docs/handoff.md on main carried a lane conclusion that the header check passed. IT IS NOT THERE AND NEVER WAS. Verified: git grep -i "header check" origin/main -- docs/ returns 2 hits, both #72 own lane text, both true. git log --all -S "no stale header" and -S "header check passed" each return exactly ONE commit - 1f06c35, the governance lane commit RECORDING THAT THE CLAIM DOES NOT EXIST. The sentence existed only in a chat message from the ceiling lane. Two lanes independently refused to write the correction I asked for. I nearly caused a phantom to be appended to the file whose purpose is preventing phantoms.

## `c126` - Correcting the attribution of four header catches

**Status:** pending

I attributed four stale-header catches to backlog_graph.py and told three lanes so. WRONG TOOL. Verified line numbers on main: resolve_doc_conflicts.py L258 sets had_conflict, L364 opens the conditional, L380 closes it, and the header recompute at L382 sits OUTSIDE it - so that script repairs the header unconditionally whenever it runs, and it runs only when a human invokes it during a rebase. That is why every catch arrived that way. I checked the line numbers rather than accepting the lane correction on trust, because taking a second claim on faith after the first failed is how this class propagates.

## `c127` - Recording that CI now checks the backlog header but does not repair it

**Status:** pending

As of b49c6e6 (#72) backlog_graph.py checks the header in CI and fails by name on a mismatch - driven by injection against main, rc=1, control rc=0. But the REPAIR still lives only in resolve_doc_conflicts.py and is manual and opportunistic: invoked by a lane during a rebase, never by CI. A reader will assume CI both checks and fixes. IT CHECKS. IT DOES NOT FIX. Worth one line wherever the tool is described.

## `c128` - Recording that two lanes reached the same rule independently

**Status:** pending

resolve_doc_conflicts.py:390 carries "Assert the presence we expect rather than the absence of what we fear" - R59 verbatim, written by a different lane from a different failure, and the bug it documents is R59 second limb (re.sub matching nothing is not an error, so the script printed a confident claim about an edit that never happened). A rule two lanes reach independently from different failures is not a house style. Cheapest available evidence that the register describes something real rather than something we agreed to say.

## `c129` - Recording that a freeze signal cannot stop work already in flight

**Status:** pending

Cross-session messages are queued behind the recipient current turn, so a coordinator freeze arrives AFTER a lane has begun. Demonstrated twice: #72 rebased onto the tip current when it started and #73 landed mid-rebase, costing a full CI cycle; and the governance lane report proving the header check absent crossed my message saying it had landed. REMEDY that does not depend on timing: the lane asserts git merge-base HEAD origin/main equals git rev-parse origin/main IMMEDIATELY before pushing. A freeze is necessary and insufficient; the base assertion is the half that holds.

## `c130` - Recording that I synthesise coherent claims about main that match no tree

**Status:** pending

MY PATTERN, named by the governance lane, three instances in one night, all about main, all internally consistent, all corresponding to nothing: (1) 130 items 47/1/82 - sums correctly, assembled from lane reports, matches no tree; (2) backlog_graph.py checks the header - real check, real catches, WRONG TREE; (3) a false guarantee is merged in handoff.md - real sentence, real error, WRONG LOCATION (chat, not repo). The lane framing: you did not inherit these, you SYNTHESISED them. SPECIFICITY IS WHAT MADE THEM WORTH CHECKING, NOT WHAT MADE THEM TRUE - which is why three lanes burned time on them. REMEDY: for any claim about main, run the command against main before saying it. Not "name the head" - that presumes there was a head.

## `c131` - Recording that a statistic of an edit is not the edit

**Status:** pending

From the governance lane. Mutating "47 done" to "12 done" is LENGTH-IDENTICAL, so a character-count assertion sees nothing and prints MUTATION DID NOT APPLY on a mutation that did apply - scoring a working check as unverifiable, by a guard built to stop a broken check being scored as working. My own implementation escaped only because the guard was a string comparison; but I PRINTED the character count as the evidence, so the number I displayed as proof was the number that proves nothing. ASSERT THE EDIT, NOT A STATISTIC OF THE EDIT. The sound guard and the unsound report can sit in the same script.

## `c132` - Recording that git stash refs are shared across worktrees

**Status:** pending

From the governance lane: git stash list shows two entries from sr2501-schedule-context-planning visible from a different worktree. Stash is NOT lane-local. This materially changes the hazard advice - "do not stash during a conflicted rebase" was written as a rule about a lane-local resource and is actually a rule about a SHARED one, so one lane stashing can surface in another lane view and be dropped or applied by the wrong session. Tell schedule-context-planning it has two sitting there.

## `c133` - Quant to adjudicate flat r2 citations against measured games agreement

**Status:** pending

Left as could-not-verify by the governance lane, correctly outside its scope. docs/backlog.md:1237 and docs/models/projection-blending.md:119 carry the flat 0.726-0.947 r2 figure, while docs/models/consensus-reproducibility.md:219 measures games agreement at 0.284-0.504. The citing files may be quoting a rates-only figure as if it covered games. QUANT CALL. Recording it here so it is assigned rather than sitting in a handoff nobody is asked to read.

## `c134` - Recording that a known failure mode is a hypothesis not a diagnosis

**Status:** pending

THE SHARPEST FINDING OF THE NIGHT, from the backlog-graph lane, and it is aimed at the governance itself. They read gh pr view mergeable=UNKNOWN three times, recognised it as the recompute lag they had personally been bitten by and had warned me about, and waited twelve minutes. THE PR HAD MERGED - a closed PR reports exactly that shape. Every reading was current and correct; the diagnosis was not. Two existing rules violated: a repeated reading of one instrument is not a second method, and where the producer is available ask it (--jq .state was one call away). THE NEW GENERAL FORM: every entry we write to catch a class also supplies a ready explanation for the next symptom resembling it. We accumulate ready explanations faster than ways to reject them - and unlike grep decay this gets MORE persuasive as the register gets BETTER. Remedy: a second instrument, not a second reading of the first. ARCHITECT NOTE: this is the strongest argument yet that the register has a carrying cost, and it is my call whether governance costs more than it prevents.

## `c135` - Recording two opposite-signed metric deltas closing the threshold argument

**Status:** pending

CORRECTED AFTER LANE CHALLENGE. Two observations, opposite signs, neither a regression. Run 1: backend suite -40.6% (348,122 -> 206,746ms). Run 2: +16.9% (202,458 -> 236,665ms) with +17 tests and NO production code changed. THE -40.6% EXPLANATION IS REASONED, NOT DRIVEN: the lane wrote "almost certainly not a speedup" on a SHAPE argument - top movers collapsing from ~1,500-3,200ms to a ~200-280ms floor, consistent with session-scoped fixture and database warm-up charged to whichever test touches it first. THEY NEVER INSTRUMENTED IT. I restated it as established fact ("that WAS fixture-warmup attribution") in a summary to the owner. The +16.9% cause IS driven - seventeen tests added, no production change. A threshold on suite total would still have fired on both. THE THRESHOLD ARGUMENT SURVIVES; the attribution of the first delta does not.

## `c136` - Per-test top-fifteen table is on its second consecutive noisy run

**Status:** pending

Lane pre-committed to a duration floor or removing the table if successive runs looked the same, and asked to be held to it. Second run: one mover -66.7%, another +281.5%, NEITHER touched by any commit in the diff. Attribution noise dominates the per-test view while the suite totals remain informative. DECISION OWED: add a duration floor, or drop the per-test table and keep totals. Lane correctly declined to change it inside a merge queue.

## `c137` - Baseline names itself not the cache key that produced it

**Status:** pending

From the backlog-graph lane, named not fixed. The run-metrics report prints "Current run <sha> against baseline <source>" where source is what the baseline artifact says about itself. It does NOT print which cache key the workflow actually restored - the restore step knows this as cache-matched-key and does not pass it. Those are different facts and the second is the one that identifies provenance when a restore-key PREFIX hits rather than the exact key. Self-heals for the source field on the first main build after #72; the cache-key half remains unwired. COORDINATOR CALL whether it is worth the wiring.

## `c138` - Recording that .git is a FILE in a worktree, not a directory

**Status:** pending

ENVIRONMENT FACT, verified in my own tree: Test-Path .git -PathType Leaf returns YES. EVERY lane in this project runs in a worktree, so ..\.git\whatever as a redirect target fails for all of us. The governance lane redirected an entire gate run to ..\.git\gate-*.txt: four commands ran to completion and wrote their output NOWHERE. Twenty minutes discarded. The shell happened to return 1; HAD IT RETURNED 0 there would have been a run that could not be read and no reason to look. Remedy: print every artefact with its byte count rather than assuming a redirect landed.

## `c139` - Recording that an invocation which looks equivalent can silently cover less

**Status:** pending

From the governance lane, and it generalises well past mypy. They ran "mypy src" where ci.yml:65 runs bare "mypy", which is config-driven: 106 files against CI 161. GREEN BOTH WAYS, so nothing would ever have contradicted them - they would have reported a gate that checked fifty-five files fewer than the gate, with no failing test capable of distinguishing the two. Only reading the pipeline reveals it. WHERE THE PIPELINE DEFINES THE INVOCATION, RUN THE PIPELINE ONE. Belongs beside "the base you compare against is an input to the result" - both are cases where the thing deciding the answer is a parameter nobody reports.

## `c140` - Recording that I corrected readers downstream of an instruction I never read

**Status:** pending

MY DEFECT, found by the governance lane. docs/backlog.md header block instructed every lane to diff the slug set against origin/main - the WRONG method, which reports another lane merges as your deletions. The ceiling lane seven false drops came from following it. I spent the entire night correcting lanes ONE AT A TIME to use their merge base, while the file every lane reads before counting said otherwise. I was fixing readers downstream of the propagation mechanism and never looked at the source. Now fixed at source. GENERAL FORM: when you find yourself giving the same correction to several people, look for the document giving them the wrong version.

## `c141` - Recording that a coordinator message cannot recount itself

**Status:** pending

STRUCTURAL, from the backlog-graph lane, and it is the deepest form of the stale-number problem. Every figure a coordinator puts in a message is stale BY CONSTRUCTION: the interval between composing a ruling and it being read is exactly when merges land. Care shrinks the window and cannot close it. Demonstrated four times in one night - lane messages and mine crossed each time, and twice the crossing was inside the exchange about the crossing. ADOPTED REMEDY: coordinator messages now carry THE COMMAND THAT DERIVES THE STATE, not the value it returned - git rev-parse origin/main rather than "main is X". Any quoted number is explicitly a cross-check to be re-derived, never an input. This is the same move as the run-metrics baseline provenance line: stop asserting state, start naming how to read it.

## `c142` - Consolidating four independent arrivals at the base-is-an-input rule

**Status:** pending

ONE RULE, FOUR INSTANCES, four lanes, one night, none discussing the same subject: (1) CodeQL went red on a three-line copy change because a RETARGET widened its diff to every line in the PR; (2) run-metrics restore-keys PREFIX hit returned a baseline that was not the exact key; (3) slug diff against origin/main reported another lane merges as SEVEN FALSE DELETIONS; (4) a green CI run against 777ab33 is no evidence about e05f09b. THE BASE YOU COMPARE AGAINST IS AN INPUT TO THE RESULT, AND NONE OF THOSE CHECKS NAMES IT. Should be registered as a rule with the four as instances rather than as four incidents. Only run_metrics.py currently names its base.

## `c143` - Recording that a deliberate trip must not be counted as a catch

**Status:** pending

From the backlog-graph lane, correcting my own overstatement. I described the backlog header guard as having four catches. One of the six rebases fired because the lane PLACEHOLDERED the header deliberately to watch the guard trip - a test of the guard, not a defect in the file. Honest tally: three genuine catches, one deliberate test, clean passes named. A tool credibility is built from its quiet runs and destroyed by one inflated tally, and the inflation is always retrospective and always by someone who was not there.

## `c144` - Recording that a SET of positions cannot distinguish a settle from an oscillation

**Status:** pending

MY MEASUREMENT DEFECT, caught by redesigning the probe. My first layout probe recorded the SET of distinct positions each element occupied and reported /schedule as movedCount=1 span=239px - which reads as a defect. A sequence probe showed transitions=1: absent at t=0, present at t=41ms at top 642, then STABLE FOR NINE SECONDS. A one-time settle during first paint. TWO POSITIONS IN A SET LOOK IDENTICAL WHETHER THEY ALTERNATE A HUNDRED TIMES OR TRANSITION ONCE. Record the sequence with timestamps, not the set. The owner reported jitter, which is oscillation; a set-based metric cannot measure the thing he reported.

## `c145` - Recording my own vacuous banner metric, revealed by its constancy

**Status:** pending

MY DEFECT. The layout probe counted samples where [role=status] was present and reported 106-107 on EVERY page - including /drafts which was a 404 with no data loading at all. Identical counts across a route that loads nothing and routes that poll every 2s proves the selector matched a PERMANENT element (an aria-live region), not the refreshing banner. THE CONSTANCY IS WHAT REVEALED IT: a metric that returns the same value for a page that cannot exhibit the phenomenon is not measuring the phenomenon. Same family as the difference-of-two-absences probe.

## `c146` - Recording that I measured a 404 page and called it a screen

**Status:** pending

MY DEFECT. I probed /drafts for layout stability and got movedCount 0. The route is /draft - /drafts renders NotFoundPage. I measured the stability of a 404 page and would have reported the drafts screen as verified. A SCREEN SHOWING NOTHING MEASURES ZERO DISPLACEMENT PERFECTLY - the draft board lane wrote exactly this warning in its could-not-verify and I hit it within the hour. Remedy applied: assert the rendered body text is the expected screen before trusting any measurement taken from it.

## `c147` - Partially closing the AsyncBoundary six-screen risk

**Status:** pending

The draft board lane merged a change to AsyncBoundary, shared by six screens, having browser-verified only the draft board. I drove headless Edge against a dev server whose AsyncBoundary.tsx, DraftPage.tsx and styles.css are BYTE-IDENTICAL to merged main (verified before trusting the server). Sequence-probed /, /system, /draft, /draft/2, /schedule, /projections: every one settles during first paint and is then stable for nine seconds. NO OSCILLATION ANYWHERE. STILL OPEN AND HONESTLY SO: /schedule and /projections both fail closed with HTTP 409 in this environment, so their WARM path is genuinely unexercised - I verified their error path is stable, not their data path. That half of the lane could-not-verify stands.

## `c148` - ARCHITECT RULING - cheapness is a correctness property of a check

**Status:** pending

Drawn from two honest limits both surfaced tonight by the lanes themselves. LIMIT 1 (backlog-graph lane): a known failure mode is a hypothesis not a diagnosis - the register supplies ready explanations faster than ways to reject them, and unlike grep decay this gets MORE persuasive as the register improves. LIMIT 2 (governance lane): refusal is demonstrated only where refutation is CHEAP - both lanes refused a coordinator instruction on evidence, but git log --all -S costs ten seconds, and neither can say they would have refused an expensive claim. IMPLICATION I AM ADOPTING: an expensive check does not get run and an expensive refutation does not get made, so a gate costly to exercise will be satisfied by ARGUMENT rather than evidence - which is exactly the failure mode gates exist to catch. Evidence: all four techniques with real catches tonight (tripwire, mutation-applied assertion, diffstat, delete-the-source-of-truth) cost under a minute. Elaborate ones produced nothing. ACTION: state both limits in gates.md as the apparatus stated boundary, not as caveats.

## `c149` - Recording that a sound guard with an unsound report is worse than an unsound guard

**Status:** pending

From the governance lane, sharpening my own finding. The guard runs once; the REPORT is what gets read, quoted and believed, and nobody re-derives the assertion from the output. So a correct check that prints misleading evidence of its own correctness survives every review it ever gets. RULE: report the quantity your assertion actually tested - if the guard compares strings, print that it compared strings, not a length that happened to be nearby and looked like evidence. I then committed it again within the hour: my layout probe reported movedCount and a span built from the SET of positions, which cannot distinguish oscillation from a settle, aimed at a defect the owner described as jitter.

## `c150` - Recording that a claim whose subject has an API is a different class

**Status:** pending

From the governance lane. I named PR #71 head as 1f06c35 when it was 3ac68eb - fourth instance of my synthesised-claim pattern, but it BREAKS THE SHAPE of the other three. Those needed a tree, a tool or a history search to refute; this one needed one command against a live authority answering in two seconds. My remedy was "for any claim about main, run the command against main" - a rule about one noun. The lane generalisation retires it: RUN IT AGAINST WHATEVER THE CLAIM IS ABOUT. Root cause named exactly: I had assumed a head I was TOLD is a head I READ.

## `c151` - Redirect ceiling lane - handoff:16423 is history and must stay wrong

**Status:** pending

The wrong slug-diff method at docs/handoff.md:16423 accurately records what that lane ran, and their result was CORRECT because they had just rebased. Editing it would be a retroactive edit to an append-only file - a worse defect than the one it fixes. The copy that INSTRUCTS is already fixed on main at 3a25ff4 (backlog.md header block now names the merge base). So the remaining work is ONE CLARIFYING APPEND saying the method is copyable and should not be - NOT that the entry is mistaken. It is a true report of a check sound at that instant and unsound as a technique.

## `c152` - CUSTOMER-FACING - no single demo database serves all three screens

**Status:** pending

MEASURED, not inferred. The running demo backends fail closed on projections and schedule with HTTP 409 projections_source_not_imported. Cause: the demo state is split across three SQLite files in one worktree, each built ad hoc by a different lane. draft_demo.db = 2 drafts, 27 events, 0 projection sources. projections_demo.db = 60 projections, 580 players, 21 scoring periods, but only 10 nba_games and 20 team_schedule rows. schedule_grid_real.db = 1200 nba_games, 2400 team_schedule, 25 scoring periods, no drafts, no projections. NO SINGLE FILE HAS ALL THREE, and one backend serves one file, so the owner opening the app sees the draft board working and two error pages. scripts/ contains no seeding script (verified by ls-tree on origin/main); docs reference the files but describe them as built by demo and seed paths. CONSEQUENCE: the app works per screen and does not work as an app, and the state that demonstrated each screen cannot be rebuilt by anyone. NAMES THE SCREEN IT UNLOCKS: all of them, simultaneously. I deliberately did NOT hand-merge the databases - an unreviewed fabricated demo is worse than a documented gap.

## `c153` - Recording that per-lane demo artifacts do not compose

**Status:** pending

GENERAL FORM of c152. Five lanes each verified their own screen against a database they built themselves, and every one of those verifications was honest. The defect is not in any lane - it is that NOBODY OWNED THE COMPOSITION. Each lane satisfied "put something useful in the browser" for its own surface; the union was never exercised because no lane owns the union. Same structural shape as the merge-queue race: correct local decisions producing a wrong global state, with no instrument at the seam. REMEDY: one reproducible seed path producing one database that satisfies every screen, owned by backend, exercised in CI or at least by a script anyone can run.

## `c154` - Recording that --is-ancestor reports failure on a squash-merged PR

**Status:** pending

From the governance lane, verified by me in two commands. git merge-base --is-ancestor <pr head> origin/main returns rc=1 (NOT an ancestor) on a correctly merged PR, because a squash merge creates one new commit with one parent and no commit of the branch is reachable from main. Meanwhile git rev-parse main:docs/backlog.md and prhead:docs/backlog.md return the IDENTICAL blob 073e7998ed. TONIGHT CLASS WITH THE SIGN FLIPPED: the dominant instance all day was a check succeeding over an empty set; this is a check FAILING over a real success. Same underlying defect - the instrument answers a question adjacent to the one asked. --is-ancestor answers "is this commit in the history"; under squash merging the honest question is "is this content on main". COMPARE THE BLOBS. Fact about how this repo merges, like .git being a file - not a class of reasoning error.

## `c155` - Recording that I mislabelled my own verification output

**Status:** pending

MY DEFECT, in the command verifying c154. I printed "main parents: 2" from (git rev-list --parents -n 1).Count, which counts the COMMIT ITSELF plus its parents - so main has ONE parent, correctly indicating a squash. My label said 2. The measurement was right and the report was wrong, which is the governance lane rule arriving within the same command that verified their previous one: REPORT THE QUANTITY YOUR ASSERTION ACTUALLY TESTED. Had anyone quoted my line they would have concluded main was a merge commit rather than a squash - the opposite of what the run proved.

## `c156` - ARCHITECT NOTE - the register catches only errors that leave a trace

**Status:** pending

From the governance lane, qualifying its OWN unit as counter-evidence and declining the credit. All three of its self-catches were cheap and all left a checkable trace: .git-as-a-file left four missing artefacts, mypy src left a one-grep discrepancy against ci.yml:65, the merge-base copy surfaced because the r2 class was handed to them the same hour. NONE required doubting a plausible story about a symptom. So the honest claim is narrower than "the register works": THE REGISTER RELIABLY CATCHES ERRORS THAT LEAVE A CHECKABLE TRACE, AND THE HYPOTHESIS-VERSUS-DIAGNOSIS FAILURE LEAVES NONE. A ready explanation costs nothing and produces no missing file to notice. Their proposed structural remedy, offered but not pressed: require the REJECTED explanation to be named alongside the accepted one. ARCHITECT CALL, not taken tonight.

## `c157` - Recording that composition time is staleness

**Status:** pending

From the backlog-graph lane, about ME, and it is measurable. Five of my broadcasts crossed a lane message tonight. THE GAP GROWS WITH THE LENGTH OF THE MESSAGE - my short ones were right; my most carefully constructed ruling (accounting, protocol, two tooling notes, a request) was FOUR HEADS stale. The care put into a ruling is the mechanism by which it becomes wrong. There is no writing-it-better that fixes this, only writing less state into it. Third direction the length rule has arrived from tonight, after grep decay and register-entry length.

## `c158` - Recording that the cheapest mechanism deletes the copy rather than synchronising it

**Status:** pending

From the backlog-graph lane, withdrawing its own offered tool in favour of a no-code fix. Generalises across the whole night: the stale backlog headers, the second parser at 128-against-133, the r2 claim surviving in citing files, my four stale broadcasts - ALL WERE COPIES THAT NEEDED SYNCHRONISING. Every fix that actually held deleted a copy or replaced it with a derivation; every fix that added a synchroniser went stale again. LIMIT, supplied by the same lane: a command carried in a message cannot go stale in transit, but still describes a world that can move between reading and acting - which is what the push-time merge-base assertion covers. The two are complete together and neither alone.

## `c159` - Recording that file mtimes distinguished a working lane from a dead one

**Status:** pending

APPLIED, by me, and it is the different-instrument rule paying off. PR #69 head had not moved in two hours and every PR field said CONFLICTING/DIRTY fcf867f. A fourth reading would have been one reading four times. Instead I listed the lane worktree by modification time: importer.py written 67 seconds earlier, aav_slugs_head.txt one second earlier. THE LANE WAS ALIVE AND MID-GATE. The PR field was current, correct, and answering a different question - it reports the REMOTE branch, and a lane running a local gate has pushed nothing to report. Two ready explanations were available (long gate, dead session) and reaching for either would have been the hypothesis-versus-diagnosis failure. The discriminator cost one directory listing.

## `c160` - Recording the culture line verbatim

**Status:** pending

From the backlog-graph lane, closing: THE LANE THAT SAYS IGNORE MY NUMBER IS WORTH MORE THAN THE ONE THAT IS RIGHT. Earned tonight - two lanes refused a coordinator instruction on evidence, one withdrew a working three-catch tool because a better implementation was landing first, one declined credit its own unit had earned and narrowed its claim to what it could evidence, and one withdrew an offered script in favour of a no-code fix that made its own work unnecessary.

## `c161` - Recording that a verified absence is a statement about a base not a tree

**Status:** pending

THE SHARPEST CLASS OF THE NIGHT, from the auction lane, and it is the general case behind everything else we recorded. A POSITIVE claim - this table exists, this constraint fires - survives a rebase. A NEGATIVE one - nothing else claims this migration number - EXPIRES THE INSTANT ANYTHING MERGES, and nothing in the file recording it marks the transition. Instance: their handoff recorded as DRIVEN that origin/main had a single alembic head with 0017 on 0016 and no collision. True - of 642bdb6. Five merges later both main and their branch carried an 0017 and twenty tests broke. The check that went looking for exactly that collision RAN, WAS CORRECT, AND FOUND NOTHING, because at that moment there was nothing. GENERAL FORM: driven negatives quietly decay into reasoned ones and the record does not say so. REMEDY they applied: annotate the old sentence with the base it was true of rather than deleting it.

## `c162` - ARCHITECT - recording the cost of my own serialisation decision

**Status:** pending

I held the most expensive lane last so it would pay its gate once instead of five times. That saved four full gate runs and I still believe it was right. THE COST, surfaced by that lane rather than by me: the longer a branch holds, the more of its DRIVEN NEGATIVES have quietly decayed into reasoned ones (c161). Worse, the alembic 0017 collision exists ONLY IN THE UNION of two branches, so no branch gate can see it on any run, however green. A serialised queue maximises the window in which union-only defects accumulate unobserved. NOT ZERO, and I am recording it against my decision rather than theirs. Open question: is there a cheap union check - e.g. CI asserting exactly one alembic head after a trial merge with main - that would close the largest instance of this.

## `c163` - Recording that a recount must cross-check its extraction against an independent population

**Status:** pending

From the auction lane. Their backlog recount reported 46/1/82 against a header saying 48/1/86 and THE FILE WAS RIGHT - their marker regex anchored the status to end-of-line, six entries carry trailing content, so it silently dropped six and produced a plausible, self-consistent, WRONG count. Caught only because the script asserts markers == headings before reporting. A RECOUNT THAT DOES NOT CROSS-CHECK ITS EXTRACTION AGAINST AN INDEPENDENTLY PARSED POPULATION IS A NUMBER WITH NO WAY TO BE WRONG OUT LOUD. Fixed by binding each marker to its heading so an unparsed marker RAISES rather than shrinking a total. Note this is the same anchoring bug the governance lane hit at 128-against-133 - third instance of reimplementing a parser the producer already exposes.

## `c164` - Recording that a tripwire restore nearly committed a mangled fixture

**Status:** pending

From the auction lane. Their secret-scan injection worked exactly as designed - exit 1 naming the file and line, which is the scope proof that "No secrets found in 386 tracked files" cannot give. But the hand-rolled trailing-newline RESTORE left the fixture not byte-identical. Caught by SHA-256 plus git status, not by assuming. THE ASSERTION THAT SAVED IT WAS ON THE RESTORE, NOT THE INJECTION - a tripwire proves scope and then leaves the tree modified, so the restore needs its own proof. Also recorded: a background shell reported exit 0 over a suite whose output read 20 failed / PG_EXIT=1, and pytest on a nonexistent test file gives rc 4 - neither pass nor result.

## `c165` - Third independent instance of sound guard with unsound report

**Status:** pending

From the auction lane, and the three instances came from three different lanes in one night. Their handoff-append check asserted after.startswith(before) - a REAL test of append purity. The line it PRINTED read "lines before: 17359 -> after: 2", because a PowerShell single-quoted here-string passed Python a literal backslash-n and .count() counted escape sequences in prose. CAUGHT ONLY BECAUSE 2 WAS ABSURD - had it printed 17496 they would have quoted it and the sound assertion would have gone on being sound while the sentence everyone reads was false. Fell back to git diff --numstat, an INDEPENDENT instrument measuring the same property, which produced 137 insertions 0 deletions. Same defect as the length-identical 48->12 mutation seen from the other side: there the guard compared strings and the evidence printed was a character count.

## `c166` - Recording a correct edit with a wrongly scoped assertion

**Status:** pending

From the auction lane, and it recurred WHILE THEY WERE FIXING the previous instance. Their edit asserted that a phrase was "not in after" - a GLOBAL check for something they meant LOCALLY. It fired on their own previous handoff entry, which correctly recorded what had been run against an older base. The edit was right; the assertion was scoped wrong. Diagnosed by printing each condition separately rather than re-reading the composite - which is the same remedy as a second instrument rather than a second reading.

## `c167` - Recording that a correct result is no evidence a method was right

**Status:** pending

From the auction lane, closing the loop on the slug-diff correction. Their rebased tree already carried the corrected instruction naming the merge base; they ran it against the origin/main ref anyway. Re-run against the merge-base sha: IDENTICAL result, because merge-base HEAD origin/main == rev-parse origin/main after a fresh rebase. This is the ceiling lane expiring-check finding arriving on a third lane: THE WRONG CHECK AGREES WITH THE RIGHT ONE PRECISELY WHEN IT CANNOT MISLEAD YOU, so a correct RESULT is no evidence the METHOD was right. Their entry now names the merge base and states why the result is unchanged.

## `c168` - LIVE DEFECT - handoff instructs --is-ancestor for a squash merge

**Status:** pending

VERIFIED BY ME on main b705f08, and SHARPER than I first stated. git rev-list --parents: last 15 commits = 15 single-parent, 0 multi-parent; last 30 = 28 single-parent, 2 multi-parent. My earlier "wrong 14 times in 15" was correct when measured and the window SLID when #74 merged. THE SHARP VERSION, from the backlog-graph lane: THE ALARM VALUE IS THE DEFAULT OUTCOME. This is not a check that is sometimes wrong - under squash-merge policy --is-ancestor returns 1 on EVERY lane that lands cleanly. A guard that fires on the normal case is the cry-wolf guard, and the cry-wolf guard is the one the next person loosens. docs/handoff.md:11430 and :11441 instruct a future lane to consult an alarm that is always on. L8662 is a correct branch-to-branch use and must not be touched. CORRECT REPLACEMENTS, both already deployed elsewhere: for did-the-work-land, git diff --stat origin/main..HEAD empty; for is-my-base-still-the-tip, the push-time merge-base == rev-parse assertion. TWO INDEPENDENT ARRIVALS hours apart in opposite directions - one lane found it by reading the file, another by hitting it (merged=true with rc=1) and nearly concluding its work had not landed.

## `c169` - Stash-refs-are-shared mechanism is missing from the rule on main

**Status:** pending

docs/handoff.md:16856 carries "Do not stash during a conflicted rebase" but NOT the mechanism, so it reads as a rule about one lane own discipline. It is not: git stash list in one worktree shows two stashes belonging to sr2501-schedule-context-planning, and any lane can drop or apply another lane stash. One sentence. Filed with c168 for the same unit.

## `c170` - ARCHITECT - the safety sign-off needs a cheap artefact, independent of ADR-016

**Status:** pending

Survives even if ADR-016 never lands. The Automation gate safety sign-off is the ONE gate whose cost is paid by a human every single time and which cannot be mechanised, because independence is the point - therefore the single gate most likely to be satisfied by ARGUMENT, and it guards the write path. The dry-run transcript already IS the cheap artefact it signs against. CONSEQUENCE: the requirement should bite on the TRANSCRIPT COMPLETENESS, which can be mechanised, rather than on reviewer effort, which cannot. Concrete change to docs/governance/gates.md:73. Governance lane finding, promoted by me above the rule that produced it.

## `c171` - ARCHITECT - the register only works with several lanes running at once

**Status:** pending

THIRD AND MOST OWNER-RELEVANT LIMIT, from the governance lane closing message. Observation: three lanes independently caught the correction-misses-the-copies class ON THEMSELVES in one night, and EVERY ONE found it because another lane had named it hours earlier. NONE found it unprompted. CONSEQUENCE: the register did not make anyone see their own error - it made someone ELSE error legible in time to check for their own. THE VALUE IS IN THE FAN-OUT, NOT IN THE FILE. A register read by one lane working alone is a catalogue; read by six lanes on the same day it is a shared vocabulary, and the catches happened in the overlap. IF THIS PROJECT DROPS TO ONE ACTIVE LANE, gates.md KEEPS PASSING REVIEW AND STOPS CATCHING ANYTHING, AND NOTHING IN IT WILL SAY SO. The owner is one person building for himself, so this is the operating condition rather than a footnote. Belongs beside the other two limits whenever ADR-016 is written.

## `c172` - Recording that a session held open as an index to a merged change is a defect

**Status:** pending

From the governance lane, refusing my reason for holding it open. I held it because it was "the only one who can answer questions about what merged in #71". They checked: 194 of 237 inserted lines are handoff entries stating what was claimed, what was checked, what commands returned and what could not be verified; gates.md sentences sit in the paragraphs whose rules they bound; the backlog change is in the header block every lane reads. All discoverable by grep from a cold start. THEIR ARGUMENT: if that is NOT enough, the entries are the defect and holding the session open HIDES it. A session kept alive as the index to a merged change is a true signal with exactly one consumer - when it archives the consumer goes and the signal stays, unread and now unreachable. Correct, and I released the hold.

## `c173` - FALSE CLAIM ABOUT A GATE IS IN MERGED MAIN

**Status:** pending

VERIFIED BY ME on main 067cdc0. docs/adapters/published-auction-values.md:292 and docs/handoff.md:17124 both state the live smoke "passes on a real export". docs/handoff.md:17344-45 states "I have never run it against a real one, because I do not have one." SAME AUTHOR, SAME DOCUMENT, SAME SITTING, 220 LINES APART, AND THE FALSE ONE IS THE FLATTERING ONE. Merged in 067cdc0 (#69). This is authorship-is-not-evidence, but NOT decay and NOT an unfamiliar module - the lane re-read the entry many times. WHAT CAUGHT IT was a third party asking a question whose PREMISE depended on it (my pre-archive question about paid-CSV handling, whose premise was itself false - there is no paid AAV export). The honest paragraph and the false one coexisted without ever being read against each other. WEAK BUT MAINTAINABLE CHECK offered by the lane: when a could-not-verify says you lack a thing, grep the same document for prose claiming you used it - one search against a short list you already wrote. Correction is in PR #75.

## `c174` - CI lints only backend so load-bearing gate scripts are unlinted

**Status:** pending

From the auction lane, flagged not fixed. The lint job sets working-directory: backend, so scripts/ is never linted and there is no root ruff config. A BROKEN SCRIPT MERGES GREEN - including scripts/backlog_graph.py and scripts/check_no_secrets.py, both of which ARE gates. The existing scripts do not pass ruff from the repo root either. The lane linted its own new script and fixed its one substantive finding but deliberately did not reformat to a standard no sibling follows and no gate enforces. ARCHITECT CALL.

## `c175` - Committing the mutation harness that was previously only a procedure

**Status:** pending

scripts/mutate_aav.py now committed - it was a procedure that archiving would have destroyed. TRANSFERABLE SCORING RULES: an anchor not found exactly once is a HARNESS FAILURE not a catch (a CRLF checkout produced nine anchor-count-0 false catches); collection/import errors, rc 5 (nothing collected) and rc 4 (usage error) are harness failures not catches; only rc 1 with a parsed N failed counts as CAUGHT; baseline asserted green BEFORE any mutation and every touched file asserted byte-identical AFTER; NEVER run concurrently with a test suite because it edits source in place and an overlapping run reads a mutated tree.

## `c176` - Recording hedge compression as the transmission mechanism for rigour-coupled failure

**Status:** pending

From the backlog-graph lane, catching ME doing it to THEIR words one exchange after we named the family. They wrote a delta was "almost certainly not a speedup" with an explicit shape argument, explicitly reasoned and never instrumented. I summarised it to the owner as "that WAS fixture-warmup attribution" - a hedge promoted to a fact in transit. THEIR DIAGNOSIS OF THE MECHANISM: the hedge is the longest part of the sentence and the first thing summarising drops. A MORE CAREFUL QUALIFICATION IS A LARGER TARGET FOR COMPRESSION. So rigour-coupling is not only that care creates the failure - care creates the MATERIAL THE NEXT READER DISCARDS. This is the transmission mechanism the four members share, and it explains why the family propagates through summaries rather than through code.

## `c177` - Correcting my own tally - the header guard has n=1 clean pass not n=2

**Status:** pending

LANE-DRIVEN CORRECTION to a claim I was about to put in an ADR. I wrote "two backlog-touching merges since, both clean, n=2". Evidenced: ONE named clean pass - #69, 135 items, header at line 5 already correct, driven. #73 ALSO touched docs/backlog.md and did NOT pass cleanly: at rebase six neither side header was usable and the lane recounted from the finished file by hand. SO: n=1 clean, plus one that required a human recount. The lane also corrected its own prior - "assume the header is stale after any backlog change" is now 4-for-5, not 5-for-5, and the miss is in the dangerous direction: following my instruction would have had them EDITING A CORRECT FILE.

## `c178` - ARCHITECT - the ADR naming rigour-coupled failure needs a review date not just a definition

**Status:** pending

From the backlog-graph lane, applying the family to its own name. "Rigour-coupled failure" will be a register entry, so it matches greps forever while instances may not recur - GREP DECAY APPLIED TO THE TERM FOR GREP DECAY. This does not argue against the name. It argues that the ADR must carry a REVIEW DATE rather than a definition alone, because it is the one entry that cannot be maintained by being more careful about it. Concrete requirement for whenever ADR-016 is written.

## `c179` - ARCHITECT - a tool that goes quiet prints that it went quiet; the register does not

**Status:** pending

THE ASYMMETRY, from the backlog-graph lane, and it is the strongest single argument for what belongs in ADR-016. A CHECK that stops catching things still reports its own runs - backlog_graph.py prints "135 items, none of the kind this job can see" whether or not it caught anything. THE REGISTER HAS NO EQUIVALENT: nothing in docs/governance/gates.md reports its own catch rate, so a register that has stopped catching anything reads EXACTLY like one that is working. Combined with c171 (the register only works with several lanes running), the consequence is that governance decay is SILENT while tool decay is LOUD. Concrete requirement: whatever ADR-016 says about the register must include how anyone would notice it had stopped working.

## `c180` - Caveat on the fan-out-dependency claim - n=3 cannot distinguish two stories

**Status:** pending

SELF-CRITICAL CAVEAT from the lane whose tool supplies the evidence. All three genuine backlog_graph.py catches were headers broken by ANOTHER lane change arriving through a rebase; zero were a single lane miscounting its own file. That is consistent with "the tool catches cross-lane collisions, so its value falls with lane count" AND EQUALLY with "cross-lane is simply where the defects happened to be that night". The lane leans to the first and cannot evidence it. WHAT IS SAFE TO SAY: a one-lane project would have GENERATED fewer of the defects it caught - which lowers the value of the tool and the risk TOGETHER, and is NOT the same claim as the register going quiet. Do not let c171 be written up as if n=3 settled it.

## `c181` - Recording that a compacted agent is a summary and inherits the hedge-compression failure

**Status:** pending

From the backlog-graph lane, disclosed unprompted about itself, and it applies equally to ME. Their context was compacted partway through the night, so everything reported afterwards was reconstructed from a summary of their own earlier work rather than from the work. EVIDENCED ONCE: their substring probe searched for "per-commit key" while the file reads "not a stable key for one commit" - they did not misread the file, THEY NEVER RE-READ IT, they searched for their own summary of it. The probe tested the copy and reported on the original. CONSEQUENCE: hedges attached before a compaction are the least likely part to survive into anything said after it, because the qualification is the long part and summarising drops the long part (c176). PRACTICAL REMEDY, already in place: THE ARTEFACT OUTLIVES THE AGENT AND IT IS THE ARTEFACT THAT SHOULD BE QUOTED. docs/handoff.md was written at the time and did not pass through the compression; prefer its driven form over any agent restatement. Not because agents are careless - because a compacted agent is a summary by construction, and you cannot instruct a summary to stop being one. MY OWN CONTEXT WAS ALSO COMPACTED THIS SESSION; the same discount applies to my flat statements.

## `c182` - DEMO FIXED - one database now serves all three screens

**Status:** done

DRIVEN. The three dev seeders DO compose into one SQLite file, in the order schedule -> projections -> draft. Built demo_all.db and verified through the vite proxy on 5173: schedule-grid 200 (30 rows, 704 cells), projections 200 (60 rows, 1140 cells), drafts 200 (both mocks). Screens verified in a real headless browser asserting body text, not just API status. This closes c152/c153 for the fixture-scale demo. NOT YET A COMMITTED SEED PATH - it is three commands in a known order, which is exactly the reproducibility gap c152 names. Backend unit should wrap it.

## `c183` - LIMIT - projections seeder cannot compose with the REAL season schedule

**Status:** pending

DRIVEN AND PRECISE. seed_projections refuses with "this database already holds 2026-27 game 0022600004, which is outside the fixture cohort. Refusing before any write rather than after." So: demo_all.db = 10-game fixture schedule + 60 projections + 2 drafts (ALL THREE SCREENS WORK). demo_full.db = real 1,206-published/1,200-imported season + 2 drafts, NO projections. THE GUARD IS CORRECT - it stops the projections demo claiming a cohort it did not create - but it means the real-season demo and the projections demo are mutually exclusive. NAMES THE SCREEN: /projections and /schedule cannot both show real-scale data until the projections seed can bind to a real-season cohort. Backend/quant call.

## `c184` - Recording my own diagnosis of a state I had already changed

**Status:** pending

MY DEFECT. seed_projections returned rc=2 in a combined command; my Select-String filter had hidden the reason. I re-ran it to read the error - but the DRAFT seeder had run in between and created leagues 2 and 3, so the re-run hit a DIFFERENT guard ("already holds league 2") than the original failure ("holds a game outside the fixture cohort"). I diagnosed the second and would have reported it as the cause of the first. VARY THE OBSERVATION, NOT THE WORLD: re-running a failing command after the tree has moved tests a different question. Fixed by rebuilding from empty in a fixed order.

## `c185` - Recording that my error detector matched prose describing the state

**Status:** pending

MY DEFECT, and the fifth instance of this class in two days. My browser check tested errorish = /could not|cannot|unavailable|failed|no current|never been registered/i against document.body.innerText. It returned TRUE on both working screens: /schedule matched "This season is not fully scheduled" (the legitimate ADR-013 pending-games affordance) and /projections matched "We have not computed our own projections yet" (legitimate explanatory copy). BOTH SCREENS WERE FINE. Had I trusted the boolean I would have reported the fix as failed. What saved it was the row and cell counts - 30/704 and 60/1140 - which are positive evidence of rendered data rather than absence of a scary word. ASSERT THE PRESENCE YOU EXPECT, NOT THE ABSENCE OF WHAT YOU FEAR.

## `c186` - FAN-OUT UNIT - commit the demo runbook and a composite seed script

**Status:** pending

READY, backend-owned, Code gate, no blockers, parallel-safe. The full procedure is DRIVEN and written up at session-state files/demo-runbook.md: seeder order (schedule -> projections -> draft, forced by three refusal guards), DATABASE_URL not HOOPS_GM_DATABASE_URL, uvicorn --factory hoops_gm.app:create_app, vite proxy to 8000, the row/cell counts that constitute proof, the real-season --fixtures-dir variant with its sanity numbers, and the cohort-guard limit. UNIT: land that as docs plus a hoops_gm.dev.seed_demo composite that runs the three in order against one database and prints the counts. NAMES THE SCREEN: all three at once, reproducibly by anyone. Until it lands the demo is unreproducible by anyone who was not told, which is c152 unchanged.

## `c187` - HAZARD - checking out a branch in a worktree disturbs a demo served from it

**Status:** pending

MY DECISION, recorded with the reason. I intended to open a docs PR from this coordinator worktree and did not, because the demo backend and vite dev server are served FROM THIS WORKTREE FILES. vite hot-reloads on change, so a checkout would have altered the running app the owner had just been told was working. Also found: this worktree HEAD is DETACHED at c6fe8b8, so committing would have needed a new branch anyway. GENERAL RULE: a worktree that is serving a running demo is not a free place to do git work, and the coordinator worktree is the likeliest one to be both.

## `c188` - Bounded loss on archiving the draft-board lane

**Status:** done

ASKED AND NOT ANSWERED. I put the pre-archive question to it at 09:15 (CDP driver, measurement harness, failed approaches, which demo database). Last worktree write was 04:10 - idle twelve hours, no reply. Archived at 16:35 with the loss bounded rather than pretended away. PRESERVED INDEPENDENTLY: the headless-Edge CDP technique, which I rebuilt and DROVE today - msedge --headless=new --remote-debugging-port=N --user-data-dir=<temp>, then PUT /json/new?<encoded url> (GET is rejected), Page.enable, wait on Page.loadEventFired not a fixed sleep, Runtime.evaluate with an async IIFE and awaitPromise, Node 24 global WebSocket. Three working probes saved to session files: layout-probe.js, seq-probe.js, datacheck.js. ALSO PRESERVED from its own messages, in this register: the getComputedStyle font-weight that no installed face can render, and MutationObserver reporting ASSIGNMENTS not differences (attributeOldValue showed text->text 45 times). GENUINELY LOST: any further failed approaches it never enumerated. That set is unknown and unbounded, and it is the honest cost of a lane going idle before the question reached it.

## `c189` - CORRECTION to my own remedy - the failure is resolution, not instrument count

**Status:** pending

From the auction lane, and it corrects advice I gave every lane tonight. I prescribed "a second instrument, not a second reading of the first". Their instance: tree came back dirty after a mutation run; first reading was "harness residue, it failed to restore a file" - a named class they carry, fitting perfectly. It was their own uncommitted edit. THE FIX WAS NOT A SECOND INSTRUMENT: git status already contained the answer. They needed to READ THE FIRST INSTRUMENT AT FULL RESOLUTION rather than matching its shape against a catalogue entry. The distinguishing datum was WHICH FILE, not IS IT DIRTY. GENERAL FORM: a catalogue match happens at low resolution, which is exactly why it is fast and why it is wrong. Same shape as hedge compression (c176) - the pattern-match keeps the shape and drops the detail, as summarising keeps the result and drops the qualification.

## `c190` - Recording that proving a non-edit needs positive evidence too

**Status:** pending

From the auction lane. They asserted docs/handoff.md:8662 - the one CORRECT --is-ancestor use, which must not be touched - was byte-identical by diffing against git show HEAD:docs/handoff.md, RATHER THAN BY HAVING AVOIDED IT. That is assert-the-presence-you-expect applied to a non-change. Almost nobody proves they did not change something; they rely on intent. Worth generalising: when a diff must leave one region untouched, diff that region explicitly rather than trusting that you did not go near it.

## `c191` - Recording that a lane tested my claim rather than my evidence

**Status:** pending

I supported the --is-ancestor defect with "28 of 30 commits are single-parent". The auction lane correctly identified this as evidence about the MECHANISM, not a test of the CLAIM - the parent count reads 28/30 whether or not the check actually misfires on a landed lane. They tested the claim on the one branch where the answer was independently known, their own: merge-base --is-ancestor fc4fb62 origin/main returns rc 1 while git diff --stat for their own paths is EMPTY. The guard fires while the work is demonstrably present, on a branch whose landing is not in doubt. THE DIFFERENCE BETWEEN EVIDENCE CONSISTENT WITH A CLAIM AND A TEST OF THE CLAIM, and I offered the weaker one.

## `c192` - Recording that a session-local copy of a repo tool outlives the fix to that tool

**Status:** pending

From the auction lane, found while checking its own session state before archiving. It held files/backlog_graph.py from BEFORE b49c6e6 - confirmed by the absence of header-disagrees-with-items, i.e. exactly the version that returns rc=0 on a wrong header, which is the false negative I corrected them on. GENERAL FORM: A SESSION-LOCAL COPY OF A TOOL READS AS AUTHORITATIVE BECAUSE IT HAS THE RIGHT FILENAME, and it cannot notice that the repo version was fixed. Archiving destroys it, which is the correct outcome - but anything that resurrects session scratch as a convenience would resurrect the version that always says yes. THE REPO COPY IS THE ONLY ONE THAT SHOULD EVER BE RUN. I checked my own session state: no .py copies of repo tools; my three .js probes are instruments with no repo counterpart, so they cannot go stale against one.

## `c193` - Recording that PowerShell Measure-Object -Line does not count blank lines

**Status:** pending

From the auction lane, caught one sentence before being reported to me as a defect in a file I had just merged. Measure-Object -Line reported 177 for scripts/mutate_aav.py against a diffstat of 198 insertions. Python read 198 lines, 21 blank: 177 + 21 = 198 exactly. THE DIRECTION IS THE POINT - the low-resolution instrument DID NOT FAIL. It answered a slightly different question and LABELLED THE ANSWER WITH THE WORD I WANTED (Lines). Same family as gameEt carrying a Z suffix while not being UTC: a self-describing value whose label is true enough to pass and wrong enough to mislead. Use git diff --stat or Python for line counts.

## `c194` - Gate wall-clock costs are unrecorded and must be instrumented not remembered

**Status:** pending

The auction lane named this as the one thing genuinely not written down: the per-stage wall-clock cost of the gate set, which it holds only as impressions. It would help schedule the fan-out. ITS OWN CORRECT ADVICE: ask a future lane to INSTRUMENT it rather than reconstruct theirs, because a remembered duration is the same class of evidence as a remembered header count. Approximate anchors that ARE recorded in handoff entries: SQLite suite ~8 min, Postgres suite ~12-15 min, migrations-from-empty ~30s, adapter contract ~1m20s.

## `c195` - WITHDRAWN AND CORRECTED - create-on-connect does not manufacture a silent false zero

**Status:** pending

THE LANE WITHDREW ITS OWN CLAIM AND I HAD AMPLIFIED IT TO THE OWNER. Driven by me independently: connecting to an absent SQLite path DOES create the file, but the first query raises OperationalError "no such table" - LOUD, not silent. Nobody reads a traceback as a result. THE REAL VECTOR IS A MIGRATED BUT EMPTY STORE: alembic upgrade head on a fresh file, then a coverage query returns "games in scope: 0 / observed: 0" at EXIT 0 WITH NO PATH IN THE OUTPUT. That is exactly what the main checkout hoops_gm.db was - schema 0003, tables present, zero rows. So the original contradiction was never about file creation at all. THE LANE OWN DIAGNOSIS OF WHY IT SAID SO: it reached for the most serious-sounding mechanism instead of the one it could evidence - the RHETORICAL CONVENIENCE failure AGENTS.md names, which has no CI job. CONSEQUENCE FOR NEW READERS: require that a tool PRINTS ITS STORE BESIDE ITS COUNT, not that it refuses to create one. Naming the store is what closes the false zero.

## `c196` - Recording that my stutter probe measured a quantity blind to the defect

**Status:** pending

MY MEASUREMENT DEFECT, caught only by building a positive control. My first probe tracked the POSITION of the main element and reported anchorMoves=0 on BOTH pre-fix and post-fix code. The banner sits at the BOTTOM of the document, so it changes documentElement.scrollHeight WITHOUT MOVING THE ANCHOR ABOVE IT. Height was the signal; position was blind to it. Had I not built the control I would have "confirmed" the fix with an instrument that could not have detected the defect in either direction - an absence claim from a probe never shown able to fire.

## `c197` - DRIVEN - the jitter fix works, proven against a positive control

**Status:** done

Identical probe, same backend, only the frontend code differing. OLD code (worktree at c6fe8b8, vite on 5199): heightChanges=5 in 12s, sequence 1956 -> 2036px at t=2035ms -> 1956px at t=2076ms, repeating at t=6030/6081 - AN 80px HEIGHT JUMP LASTING ~40ms EVERY ~4s. 72 DOM mutations. MERGED code (5173): heightChanges=1 (initial render only), 6 mutations. The 80px/40ms figure independently matches what the draft-board lane reported pre-fix (79px every 2s, ~40ms), measured by a different instrument in a different session. Control worktree torn down, junctioned node_modules removed, owner demo untouched throughout.

## `c198` - RESOLVED - the participation ledger is populated but unreachable by any default config

**Status:** done

DRIVEN, verified independently by me. C:\Users\steverones\hoops-gm-data\hoops_gm.db (15,081,472 bytes) holds player_participation=43037, player_game_logs=26651, nba_games=1230, 596 distinct players, 1227 of 1230 distinct games, created 2026-08-22 05:22:44-06:09:37. C:\Users\steverones\hoops-gm\hoops_gm.db holds 0/0/0. MECHANISM at backend/src/hoops_gm/core/config.py:59 and :94-111 - database_url defaults to sqlite:///./hoops_gm.db and a field_validator anchors the relative path to REPO_ROOT, so EVERY CHECKOUT RESOLVES TO ITS OWN EMPTY FILE. hoops-gm-data is a SIBLING of the main checkout, inside no worktree. Lane counted 0 .env files and DATABASE_URL unset, so nothing in the repo points at the populated store. CONSEQUENCE: participation ingest is the 4x-dominant fetch cost in the backlog and the project believed it faced a full live archive sweep. IT FACES A CONFIGURATION CHANGE. Largest schedule swing produced against a fixed draft day.

## `c199` - NEW DEFECT CLASS - a search exhaustive over the wrong domain

**Status:** pending

WORST-SHAPED MEMBER OF THE DOMINANT CLASS SO FAR. A coordinator searched nine worktrees plus the owner main checkout for participation rows and found 0. The search was COMPLETE over that domain and the result was ACCURATE. But hoops-gm-data is a sibling of the checkout, inside none of them, so the domain excluded the answer by construction. EVERY PREVIOUS INSTANCE was a check that could not fail. THIS ONE COULD FAIL, DID FAIL, REPORTED ACCURATELY, AND WAS STILL MISLEADING - the scope was wrong rather than the check. The standing remedy (a check that iterates must assert it found something) DOES NOT CATCH THIS: it found things, in the wrong place. REMEDY NEEDED: state the search domain alongside the result, and ask whether the answer could lie outside it. It propagated into docs/backlog.md as a load-bearing premise for blocking injury-status-conversion.

## `c200` - Correcting a false premise now on main about row-level outcomes

**Status:** pending

docs/backlog.md injury-status-conversion finding (1) states the corrected row-level outcomes live only in a gitignored database and that the one real database holds 0 rows in player_participation and player_game_logs. FACTUALLY WRONG ABOUT THE STORE - they are present at hoops-gm-data with 43,037 and 26,651 rows. Finding (2), the 21 < 30 arithmetic activation veto, is UNTOUCHED and still blocks the item. Correction assigned to the ledger lane: correct docs/backlog.md which asserts the present; APPEND to docs/handoff.md which records the past, because the original sweep entry was an accurate report of what was run and should stand with its domain limitation noted rather than be rewritten into having been wrong.

## `c201` - Three stores hold three disjoint slices and none is joinable alone

**Status:** pending

Observation from the ledger lane, deliberately not acted on. hoops-gm-data/hoops_gm.db holds participation (43,037) and game logs (26,651) with no injury reports. hoops-gm-data/throwaway-report-sweep.db holds 69,922 injury_report_entries and 2,460 team_schedule rows with ZERO participation. The main checkout store holds nothing. So no single store supports a status x outcome contingency, which is the join injury-status-conversion needs. The lane correctly refused to join them - that is a Model-gated quant decision and should be REQUESTED rather than discovered.

## `c202` - MY DEFECT - I dumped one board and wrote both into a brief

**Status:** pending

I inspected the RECORDING panel text on /draft/1 only, found no explanatory prose, and told the frontend lane that BOTH boards had none. Verified false: git grep on origin/main returns frontend/src/components/DraftRecorder.tsx:242 carrying "The seat is fixed by the recorded order, so only the player is typed" - the ordered board already documented the harder of the two cases. ONE OBSERVATION GENERALISED TO TWO CASES AND STATED AS MEASUREMENT, in the instruction someone else would work from. Same shape as the search exhaustive over the wrong domain (c199), and worse in a coordinator hands because a brief is where a wrong premise gets acted on rather than checked.

## `c203` - Recording that explanation accumulates where it is pleasant to write

**Status:** pending

THE REFRAMING, from the frontend lane, and it predicts the next gap better than my version did. Not "the recorder was never documented" but DOCUMENTED EXACTLY ONCE, WHERE A LANE HAPPENED TO NOTICE AN ABSENCE WHILE BUILDING IT. The auction half had 39 words and zero explanation; the ordered half had one 29-word sentence doing the harder job. UNEXAMINED AND LIKELY TO SHOW THE SAME ASYMMETRY: the schedule grid, the projections table, the stock watch. The lane checked the draft board and correctly stopped.

## `c204` - ARCHITECT ITEM - a fix to a shipped half of a partially-shipped backlog item has nowhere legal to live

**Status:** pending

From the frontend lane, which hit it and correctly withdrew its item rather than falsifying anything. draft-tracker bundles persistence + screen + bridge feed; two of three have landed, so the item is pending. A COMPLETED fix to the shipped screen half cannot be filed as done depending on it, because backlog_graph.py refuses a done item resting on an unfinished one - correctly. Both available repairs were false: mark draft-tracker done (the bridge feed does not exist) or delete a real edge (the tool names and refuses that). THIS WILL RECUR - the same bundling exists for schedule and projections work. MINE to solve, not a lane fix.

## `c205` - Recording that a vocabulary guard exiles the denial from where it is needed

**Status:** pending

CORRECTED BY THE LANE, against my overstatement. I wrote that the forbidden-vocabulary guard makes the most natural phrasing of the screen most important fact PERMANENTLY UNAVAILABLE. Too strong. It is unavailable inside .draft__panels and .log - two containers on one screen. The page lede says "This screen recommends nothing" legally, three lines up the DOM, because the scan never looks there. ACCURATE AND MORE USEFUL: the denial has to live OUTSIDE the scanned containers, so it cannot sit next to the control it is denying things about. THE COST IS NOT THAT THE SENTENCE CANNOT BE WRITTEN, BUT THAT IT CANNOT BE WRITTEN WHERE THE READER IS LOOKING WHEN IT MATTERS - which is this unit own defect one level down: the explanation existed, in the panel that was not the one being used. Also note the exemption is BY POSITION, NOT BY INTENT, so a future lane must not infer that the guard tolerates denials; it simply never looked there. Now documented in the test own comment.

## `c207` - Recording that the damage lands in the concern you are not attending to

**Status:** pending

MERGED FROM TWO ENTRIES at the frontend lane suggestion - it is stronger as one, and both instances were theirs. (1) They piped backlog_graph.py through Select-Object -First and read EXIT=0 on a run that returns 1 with two real defects printed - WITH THE WARNING IN THE PROMPT THAT ASSIGNED THE WORK. They truncated FOR READABILITY, not to read a code. (2) Building a positive control, they copied aside the component they were editing, ran git checkout HEAD on component AND stylesheet, and lost the stylesheet edits made earlier. THE COMMON FORM: neither was ignorance of the trap. The second concern is where it lands, and knowing the trap does not help because you are not looking there. THIS IS WHY DOCUMENTING A CLASS DOES NOT PREVENT IT (c134) stated as a mechanism rather than an observation. Practical rules that survive: read exit codes from untruncated runs; commit before reverting anything to measure against it.

## `c209` - My citation suspicion was wrong and the real defect pointed the other way

**Status:** done

I suspected 0.726-0.947 was a rates-only figure cited as covering games. FALSE - it is rates-only and cannot be otherwise; games agreement never reaches 0.5 by either route, so it cannot sit in a range with a 0.726 floor. THE REAL DEFECT: docs/backlog.md quoted the rates figure, then the minutes finding, then concluded "the seam therefore falls at games, not minutes" WITH NO GAMES FIGURE IN IT ANYWHERE - the strongest channel quoted and the load-bearing one omitted, in the file a reader consults first. "Per game" as a UNIT sat one clause from a games argument where it reads as a SCOPE. It had already misled me, which is the evidence it needed fixing. All four sites now name their subset.

## `c210` - The coarseness test that condemned games had never been run on minutes

**Status:** pending

From the quant lane, unprompted. games was rejected as a tier on concentration; the licence to CONSUME minutes rested only on slope evidence. Applied identically to both on the same cohort (their MPG >= 20, n=249): games 18 distinct, 84.7% on top two, 2.5 EFFECTIVE LEVELS. Minutes-per-game 18 distinct, 20.5% on top two, 14.9 EFFECTIVE LEVELS. DISTINCT-VALUE COUNT ALONE WOULD HAVE CALLED THEM IDENTICAL - 18 against 18; concentration separates them 6x. CLASS: a test applied to the thing you suspected and not to the thing you were relying on. QUALIFICATION THAT MUST TRAVEL WITH THE NUMBER: their MPG is integer-valued for 505/505 rows, so 14.9 effective levels is a real per-player opinion and not a fine one.

## `c211` - OWNER-BLOCKED - a DIFFERENT vendor or a different DATE settles whether the rates carry the games tier

**Status:** pending

CORRECTED BY THE QUANT LANE. I told the owner "download a second BBM export". AS STATED THAT INSTRUCTION CAN BE SATISFIED WITHOUT BEING MET: a re-download of the same view reproduces the same 1dp rounding and the same tier and answers nothing, because THE AMBIGUITY IS A PROPERTY OF THE PUBLICATION FORMAT, NOT OF THE FILE. What discriminates: (a) a DIFFERENT vendor, (b) the SAME vendor at a DIFFERENT date, or best (c) a source publishing per-game figures NATIVELY rather than season totals - in which case the divisor question does not arise at all. THE QUESTION: if the source native quantity is the season total, every rate we consume was manufactured by dividing by a 2.5-effective-level games column, which would sharpen the ADR-002 seam considerably. Publication rounding to 1dp leaves every candidate divisor at chance (2.4-9.9% against a 3.2-10.5% control).

## `c212` - ARCHITECT RULING - the anti-circularity constraint is narrower than I was enforcing

**Status:** done

I HAD BEEN OVER-APPLYING IT. Read the source rather than reasoning from memory: docs/models/consensus-reproducibility.md:365-370 states the rule exactly - "Whoever builds the availability model should not be whoever read that column... I cannot demonstrate that I have forgotten it and no reviewer can check." THE ARTEFACT IS ONE COLUMN: source_games_played_assumptions, the commercial games figure. The rationale is structural and specific - projection-strategy.md argues our availability model cannot be circular with a commercial one BECAUSE the blending service never queries that table, so the one quantity we contest is the one our model never sees. Reading it moved the protection FROM STRUCTURAL TO BEHAVIOURAL. RULING: (1) the constraint is PER-ARTEFACT, not per-lane, and the artefact is that column distribution; (2) it does NOT bind everyone who measured any decision-bearing input, which is the over-broad reading I had been applying; (3) reading the CONCENTRATION counts as reading the distribution - a shrinkage prior is exactly what knowledge of shape contaminates - so the citation lane IS bound, correctly, by its own instinct; (4) MY "THREE LANES EXCLUDED" FIGURE WAS ASSERTED WITHOUT ENUMERATION AND IS RETRACTED. CONSEQUENCE: the schedule risk is materially smaller than I told the owner, because the eligible pool is far larger than my reading implied.

## `c213` - MY DEFECT - I enforced a broader rule than the one written, across multiple lanes

**Status:** pending

I told three lanes they were excluded from building the availability model because they had measured a decision-bearing input, and I told the owner this was a tightening schedule risk. THE WRITTEN RULE IS NARROWER: it names ONE column (source_games_played_assumptions) and one reason (a human who has seen that distribution cannot demonstrate having forgotten it while choosing a shrinkage target, and no reviewer can check). I generalised "whoever read that column" into "whoever measured any input the model consumes". CAUGHT BY READING THE SOURCE rather than reasoning from memory - and I nearly concluded the opposite error, that I had INVENTED the rule entirely, because my first three greps missed it. The rule was at docs/models/consensus-reproducibility.md:365 under a heading about what a measurement COST, not under governance. RULE THAT WOULD HAVE CAUGHT IT: before enforcing a constraint across lanes, quote the sentence that states it and the file it lives in. I enforced it three times without ever citing it.

## `c214` - Recording that a structural guarantee can degrade to a behavioural one silently

**Status:** pending

From docs/models/consensus-reproducibility.md:346-360, written by the lane that caused it. BEFORE: "no one on our side can fit to their games number, because nothing on our side can read it" - enforced by the blending service never querying that table. AFTER a lane read the column offline for evaluation: "no one on our side SHOULD fit to their games number." NOTHING IN THE REPOSITORY WEAKENED, NO GATE MOVED, NO CODE CHANGED - the protection went from structural to behavioural because a human now knows the shape of a distribution. The lane recorded it as a real cost of running the experiment rather than a disclaimer, and stated the staffing consequence itself. THE GENERAL FORM: a guarantee enforced by what code CAN see is destroyed by what a person HAS seen, and no diff shows it.

## `c215` - ARCHITECT RULING v2 - anti-circularity binds on VALUES, not on FACTS, and expires on publication

**Status:** done

ARGUED FROM INSIDE THE CONSTRAINT by the lane it had just bound, and it is better than both my readings. MY FIRST reading (whoever measured any decision-bearing input) was over-broad. MY SECOND (whoever read that column distribution) still binds on any reading of the column. THE LANE DISTINCTION: the predicate is not DID YOU LOOK but DID YOU ACQUIRE A QUANTITY A PRIOR COULD BE TUNED TOWARD. Reading a mode, a mean, a player-level figure or an extremum of a contested column EXCLUDES. Reading a concentration, a correlation or a count DOES NOT - you cannot tune toward "2.5 effective levels" because there is no number there to be pulled toward. SECOND LIMB: the exclusion EXPIRES ON PUBLICATION. Once the fact is in main every lane holds it, so excluding one lane for knowing what the repository tells everyone is theatre - and LEGIBLE theatre, which is how a guardrail loses authority for the cases that matter. WHY MINE WAS WRONG IN DIRECTION: an unbounded monotone exclusion eventually excludes everyone and DOES ITS EXCLUDING HARDEST ON WHOEVER DID THE MOST CAREFUL WORK. ACCEPTED. The lane still recuses itself from choosing a shrinkage target, which is the narrow defensible exclusion; it is NOT excluded from building the availability model.

## `c216` - Recording that a guard shipped with the defect class it was written to prevent

**Status:** pending

From the quant lane, found by committing a control that had lived only in a shell. The shuffled-divisor guard compared a raw COUNT against a PERCENTAGE threshold - if control > 50.0 where control was 55 rows. It refused a valid run at 10.9% so it was caught in one execution. IT FAILED SAFE BY LUCK, NOT DESIGN: the same units error under a cohort below 50 rows passes every input silently, and catching a non-discriminating dataset is the guard whole purpose. A GUARD IS CODE AND GETS NO EPISTEMIC DISCOUNT FOR BEING A GUARD. Remedy applied: every refusal now exercised against a VARIED input rather than asserted - altered export, absent store, unset env, and an empty diff making the leak scan refuse rather than report a clean pass over nothing.

## `c217` - Recording that git checkout path restores from the index not from main

**Status:** pending

From the ledger lane, and it silently destroyed work at exit 0. git checkout <path> restores from the INDEX, which may be stale - it dropped 48 handoff lines with no error, and the same stale index held a backlog.md 33 lines short that would have reverted an entry that had just merged. git checkout origin/main -- <path> is the form that means what it reads like. Also from that lane: gc.collect() does not finalize an undisposed SQLAlchemy pool - capture and dispose the engine explicitly.

## `c218` - BLOCKED - two cohort-evidence readers cannot be fixed without invalidating a committed manifest

**Status:** blocked

From the ledger lane audit. 11 Database.from_settings call sites enumerated (tests, conftest and alembic/env excluded as deliberate engine builders): 2 readers needing the fix, 1 already correct (schedule_import builds its engine only inside the non-dry-run branch), 8 writers. THE BLOCK: the committed cohort manifest pins a whole-file SHA-256 of four sources, two of which ARE those readers, so any edit invalidates its provenance and test_cohort_evidence.py fails. Regenerating needs its own plan/run commands, and per the three-store finding NO STORE NOW HOLDS BOTH SLICES, so the state the manifest claims to be a pure function of may not exist. Recorded as blocked with a test asserting the manifest still fingerprints them, rather than silently reverted. LIFT THIS when the widened cohort regenerates a manifest - that is the moment, and the widened-cohort lane is in that path now.

## `c219` - CRITICAL - the reporting-era boundary falls inside the widened cohort and the split rule puts it in the wrong place

**Status:** pending

FOUND BY THE QUANT LANE when asked for a structural reason counting could not reveal; VERIFIED AND WORSE THAN REPORTED by me. FIFTEEN_MINUTE_ERA_START = 2025-12-22 Eastern (injury_report/client.py:81) sits inside the widened window 2025-10-21..2026-04-12. Applying the frozen 50/25/25 rule to the 164 ledger game dates: development n=82, 60 LEGACY / 22 short-lead (73% legacy); selection n=41, 100% short-lead; holdout n=41, 100% short-lead. THE MODEL WOULD BE FITTED MOSTLY ON A REGIME THE HOLDOUT CONTAINS NONE OF. Section 2 CANNOT SEE THIS - it counts direct outcomes pooled over the held-out range and a pooled count has no era dimension, so the admissibility result is correct AND silent on it. WORSE: ADR-007 amendment records 1.596 unresolved doubtful per date short-lead against 0.917 legacy (74% more), and unresolved rows are EXCLUDED - so the exclusion rate is era-dependent and concentrated on DOUBTFUL, the scarcest status, nearest the floor, and the reason for widening. The cohort may clear the gate BECAUSE OF the era it is evaluated in while being fitted on the other. REMEDY (cheap, in-protocol, pre-unblind only): declare per-partition era composition alongside the section 2 counts - derivable from DENOMINATORS ALONE since counts by game date are already published and the boundary is a constant - plus era as a preregistered sensitivity. NO new outcome-keyed field, so the closed set and contract test are untouched. DO NOT change the 50/25/25 split: section 4 already names choosing proportions because these are inconvenient as the worse reason.

## `c220` - RULING - the widened holdout is the end-of-season shutdown window and ships as a stated limitation

**Status:** pending

The frozen split puts the holdout at late February to April 12 - eliminated teams shutting players down, seeding races, pre-playoff load management. availability-model own backlog entry names playoff/tanking situation as a feature precisely because this period differs. The tool is used from draft day onward, weighted October-March, and section 7 permits ONE evaluation. THE FRAMING THAT DECIDED IT (quant lane): the v1 cohort holdout was late December, mid-season and unremarkable - WIDENING DOES NOT MERELY MAKE THE HOLDOUT BIGGER, IT SILENTLY CHANGES ITS CHARACTER, so "widen the cohort" is satisfied without being met and nothing in the counting distinguishes the two outcomes. Same shape as my export instruction to the owner that could be satisfied without being met. RULING: stated limitation, declared pre-unblind, NOT a reason to move the window. Must reach the model card verbatim - the holdout is the end-of-season shutdown window and is not the regime the tool is used in.

## `c221` - The closed-set contract test is scoped to the manifest while the work now spans two stores

**Status:** pending

From the quant lane. Section 2 closed set says no new outcome-keyed MANIFEST field, and data-engineer owns a contract test asserting the set of outcome-keyed MANIFEST fields never grows. The widened-cohort work CROSSES TWO STORES. If it emits any second artefact - a coverage report, a reconciliation summary, an expected-games rollup - THAT ARTEFACT IS OUTSIDE THE ALLOW-LIST SCOPE AND THE GUARD PASSES WHILE THE DISCLOSURE SURFACE WIDENS. Not hypothetical: an injury-backfill coverage report and an expected-games report already exist as separate files beside the ledger. REMEDY: make the contract test scope THE DISCLOSURE SURFACE rather than the manifest, before the second artefact exists rather than after.

## `c222` - A SOUND FRAMEWORK ON A FALSE PREMISE DOES NOT FAIL SAFE - it launders the premise into a decision nobody re-examines

**Status:** pending

MY DEFECT, caught by the frontend lane, and the sharpest thing this morning. CodeQL failed on PR #82 in 2 SECONDS. I reasoned: too fast to be analysis, therefore a config failure, therefore probably the first .js outside frontend/ defeating build-mode autodetection. I then gave a CORRECT decision framework - suppression illegitimate, moving the file legitimate, and I would merge it RED WITH THE REASON RECORDED if CodeQL simply could not analyse a standalone Node script. VERIFIED BY READING THE CHECK RUNS: Analyze (javascript-typescript) SUCCEEDED IN 59 SECONDS; the 2-second CodeQL check is the ROLLUP that posts the alert count, and its title was "1 new alert including 1 high severity security vulnerability". So "2 seconds is too fast to be analysis" was right about the duration and wrong about the object - A CHECK THAT REPORTS A RESULT IS FAST PRECISELY BECAUSE IT IS NOT DOING THE WORK. Applied to my diagnosis, my sound policy would have SHIPPED A REAL HIGH-SEVERITY FINDING DESCRIBED AS "a check that cannot analyse a file". REMEDY: gh api repos/OWNER/REPO/commits/SHA/check-runs carries .output.title and answers this in one call; gh run view 404s because these are check runs under default setup.

## `c223` - Recording a third triage category - an alert whose mechanism is wrong and whose neighbourhood is right

**Status:** pending

From the frontend lane, and it defeats the usual triage question. CodeQL flagged js/unvalidated-dynamic-method-call at listener(payload.params). DRIVEN, both claims in one run: Map.get("toString") returns undefined so a hostile method name CANNOT reach a prototype member - THE FLAGGED MECHANISM IS NOT REACHABLE AS DESCRIBED. But the line two above it WAS a real unguarded dereference: pending.get(9999).resolve({}) throws TypeError, reachable from a reply carrying an id never sent or a duplicate after its entry was deleted. CODEQL DID NOT FLAG THAT LINE. So dismissing the alert on its mechanism - which the Map evidence fully justifies - would have left the real bug in place AND BEEN CORRECT ON ITS OWN TERMS. The triage question "is this a true positive" returns NO here and acting on it is still right. Not cosmetic: an uncaught exception in a WebSocket listener does not reject the awaited promise, it REPLACES THE EXIT CODE - in a harness whose entire purpose is producing an exit code worth reading.

## `c224` - Recording that a chat answer feels like it discharged the obligation

**Status:** pending

From the quant lane, about our own exchange. I asked the pre-archive question three times; it answered in chat twice and the answer only became durable on the third pass BECAUSE IT COMMITTED THE ARTEFACT RATHER THAN REPLYING. Its diagnosis: NOTHING IMPORTANT LIVES ONLY IN A CHAT is a rule that fails QUIETLY, because answering feels like compliance. The same lane then found my own ruling had the identical problem - my per-artefact narrowing, the withdrawal of the wider reading and the retraction of the unenumerated three-lane count existed ONLY in a cross-session message - and landed it beside the rule it corrects rather than in a governance doc that does not own it.

## `c225` - OPEN - nobody knows how many lanes the anti-circularity rule binds

**Status:** pending

From the quant lane, and it is worse than my retracted "three". Enumerating who is bound means auditing WHO HAS READ WHICH COLUMN, and NO ARTEFACT IN THE REPOSITORY RECORDS THAT. So the true number is unknown to the lane as well as to me - a strictly worse position than a wrong count, because a wrong count can be corrected and an unrecorded one cannot be looked up. The lane also flagged that it cannot referee the width of the narrowing it argued for, being the interested party: the ruling turns on whether shape-without-values suffices to anchor a prior, and it believes it does, which is why it did not argue itself out of its own exclusion.

## `c226` - NEAR MISS - the composed demo seed would have written synthetic rows into the owner real ledger

**Status:** pending

Found by the demo-seed lane because I asked whether its seeder refuses a wrong path, and it checked rather than answered. The real store at hoops-gm-data/hoops_gm.db holds 0 leagues and 1,230 games all 2025-26. require_safe_demo_target keys on LEAGUES and its cohort check keys on THIS season, so both passed cleanly; require_safe_projection_target passed too because the crosswalk is entirely nba-source with no prior BBM import to conflict with. DRIVEN AGAINST A MIGRATED COPY: the composed seed exited 0 and wrote 3 leagues, 2 drafts, 10 synthetic 2026-27 games and 60 synthetic-demo crosswalk rows BESIDE THE 43,037-ROW LEDGER. THE REAL STORE ESCAPED ONLY BECAUSE ITS SCHEMA IS AT 0016, so seed_drafts crashed on a missing table and rolled back - PROTECTION BY ACCIDENT, REMOVED BY ONE alembic upgrade head. Now closed by _require_no_real_ingest on two signals no seeder writes: any player_participation row, and any nba_games row for another season. Refused, exit 2, nothing written, ledger intact. THIRD INSTANCE IN THAT FILE OF A GUARD WHOSE SCOPE IS NARROWER THAN THE HARM, closed the same way as the first two - by widening the evidence, not the intent.

## `c227` - WITHDRAWN - era-dependent exclusion does not concentrate on doubtful at this scale

**Status:** pending

I CITED ADR-007 1.596 unresolved doubtful per date short-lead vs 0.917 legacy to the cohort lane as the reason the era bites hardest on the scarcest status. It measured: legacy 0.033 (2/60 dates), short-lead 0.019 (2/104). FIFTY TIMES SMALLER AND THE OTHER WAY ROUND. All-status unresolved is 81 legacy vs 54 short-lead, also the opposite direction per date. In both eras unresolved exclusions land overwhelmingly on OUT (74 legacy, 45 short-lead), not doubtful. MY CLAIM IS WITHDRAWN. The lane correctly did NOT claim ADR-007 is wrong: a 50x gap is not sampling noise, it means the two count different populations - theirs CANONICAL (one latest pre-tip row per player-game), ADR-007 almost certainly RAW REPORT ROWS, where a player carried doubtful across many reports is one canonical row and many raw ones. ADR-007 does not say which. WHAT SURVIVES: the era-composition concern entirely, a different mechanism, confirmed at 68/100/100 row-level against my 73/100/100 date-level - same finding, two denominators, zeros exact.

## `c228` - OPEN - ADR-007 must state which population its unresolved-doubtful figure counts

**Status:** pending

A fifty-fold discrepancy sits unremarked in a document we cite. Needs someone with the four-week artifact to state whether 1.596/0.917 counts raw report rows or canonical observations - a one-line clarification. The cohort lane correctly declined to amend the ADR, having no artifact to re-derive from, and pinned its own non-replication with a test so it cannot revert to the inherited number. FILE, do not amend.

## `c229` - Recording that classifying by game date mislabels exactly the boundary rows

**Status:** pending

From the cohort lane, correcting my method rather than my number. I proposed classifying era composition by GAME DATE. The lane classified by each observation own REPORT_TIMESTAMP, because an evening-before report for a 2025-12-22 game is filed on the 21st and is LEGACY - so game-date classification mislabels precisely the boundary rows the table exists to expose. General form: when a boundary is defined on one timestamp, classifying by a correlated but different timestamp is wrong exactly where the boundary is, which is the only place the classification matters.

## `c230` - A correction that arrives while your own PR is open is a race, and nothing in the gates watches it

**Status:** pending

From the quant lane, which caught itself. My anti-circularity ruling narrowed the rule in that lane favour. Its PR #84 was ALREADY OPEN and implemented my PREVIOUS, overruled reading - that reading a distribution shape is reading the distribution. HAD IT MERGED AS WRITTEN, MAIN WOULD HAVE CARRIED A SCOPE NOTE CONTRADICTING THE ACCEPTED RULING, silently re-broadening the rule that had just been narrowed, in the file a future reader consults rather than the chat. Caught only because the PR had not landed. NOTHING SWEEPS FOR A MERGED DOCUMENT STATING A SUPERSEDED DECISION - the lane recorded that as unswept rather than claiming it. AND THE INCENTIVE POINTED THE OTHER WAY: the lane would have been the beneficiary of not noticing, and said so.

## `c231` - VERIFIED - expiry-on-publication is load-bearing today, not a courtesy for later

**Status:** pending

The quant lane checked my second limb rather than restating it, and it is stronger than either of us said. docs/models/consensus-reproducibility.md has published "commercial mean 65.0" - A MEAN OF THE CONTESTED GAMES COLUMN - since e05f09b (#70, 2026-08-22). I verified both the line and the commit. A mean is a VALUE by my own ruling test, it is in main, and every lane holds it. SO AN EXCLUSION KEYED ON IT EXCLUDES EVERYONE OR NO ONE. Without the expires-on-publication limb the narrow rule would already bind the entire fleet. The lane also kept its self-recusal from the shrinkage target but LABELLED IT VOLUNTARY, on the grounds that a self-recusal presented as a requirement is how a rule silently widens again - which is the mechanism that produced the wide reading in the first place.

## `c232` - PROTOCOL FINDING - the preregistration >540 lead-time band is not empty on widened data

**Status:** pending

From the cohort lane, found while adding a table it was not asked for. Section 7 expects the >540 band empty "on any joinable data resembling the current cohort". THE WIDENED COHORT HAS 43 DIRECT OUTCOMES IN IT, against a committed four-week manifest that caps joined lead time at exactly 540. STRUCTURALLY THE SAME SHAPE AS THE ERA BOUNDARY: a property of the four-week cohort quietly encoded as a property of the data, so widening satisfied the instruction while breaking an assumption nothing announced. Pinned by a test so it cannot revert. QUANT TO ABSORB - the lane correctly did not touch the frozen document.

## `c233` - Recording the predicted-union check as better than two methods agreeing

**Status:** pending

From the cohort lane, resolving a handoff conflict. It had 240 dated entries, origin/main had 240, shared base 239 - SO THE UNION MUST BE 241, a value PREDICTED FROM THE STRUCTURE OF THE MERGE rather than counted. Both the resolver and an independent count then agreed at 241. THIS RULES OUT THE CASE TWO-METHODS-AGREED CANNOT EXCLUDE: both methods wrong in the same direction, which this project has hit. Where a merge has a known arithmetic, predict the result and check it, rather than counting twice.

## `c234` - Recording that an ADR clarification changing a recorded meaning is an owner decision

**Status:** pending

From the cohort lane, extending the house rule further than it is written. AGENTS.md says agents write Proposed only. The lane extended that to a CLARIFICATION it was confident about: it filed a backlog item NAMING THE CLAUSE TO ADD to ADR-007 rather than proposing the edit, on the grounds that a clarification which changes what a recorded decision MEANT is not a clarification. Correct extension and worth stating explicitly, because the gap between "propose an ADR" and "clarify an ADR" is exactly where an agent would otherwise edit meaning without a gate.

## `c235` - Policing store-opening by IMPORT not by call-site spelling

**Status:** in_progress

UNIT KILLED AND REPLACED 2026-08-23, on the audit lane's ruling, which I accepted in full. Commissioned to session 9116957c as a four-part PR.
WHY THE ORIGINAL WAS WRONG: widening test_every_engine_call_site_is_classified to scan create_engine/sqlite3.connect enumerates SPELLINGS, and spellings are an OPEN SET - sa.create_engine, engine_from_config, a creator= lambda, a helper returning an Engine. Adding two spellings buys exactly two. Also, forcing a verdict on cohort_admissibility.py:368 (mode=ro, cannot create, cannot write) is a CATEGORY ERROR not a hard call: a census whose value is that every token means something cannot afford one nonsense token.
THE REPLACEMENT: scan IMPORTS, not calls. To open a store you must first import an engine factory or a DBAPI driver, and that set is CLOSED and small. Verified myself on 0609c64, filtered to engine factories and drivers rather than sqlalchemy generally (~45 modules import select, which is not the hazard): db/session.py:21 create_engine; cohort_admissibility.py:50 import sqlite3; cohort_admissibility.py:58 create_engine. TWO MODULES, ONE ALLOWLIST ENTRY, and the escapee caught TWICE independently. Must be AST-based (ast.Import/ast.ImportFrom) since "import create_engine as ce" defeats a text grep. Extends the existing test_portability.py _DIALECT_AWARE_MODULES pattern for ADR-001 rather than inventing a mechanism.
WHAT IT CLAIMS: "is the census complete?" NOT "is this site correct?" - correct division, because MEMBERSHIP is what decayed, not verdicts. Fails loudly when a new door appears; silent about what is behind it.
LIMIT, to be asserted as SCOPE_LIMIT in the module: importlib.import_module defeats it. That is ADVERSARIAL; the hazard here is ACCIDENTAL. Nobody reaches for importlib by accident.

## `c236` - Grepping for a withdrawn claim's own words

**Status:** in_progress

THE CHEAPEST REAL DETECTOR ANYONE PRODUCED TODAY. When you withdraw a claim, grep the tree for the claim OWN WORDS. Verified by me on main at 0609c64: the audit lane withdrew the "create-on-connect yields a reproducible and meaningless zero" claim, corrected the DOCSTRING of db/session.py absent_store_refusal, and left the MESSAGE STRING it actually prints (line 169) still asserting it. cohort_admissibility.py:356 and :365 then inherited it. ONE WITHDRAWN CLAIM, THREE LIVE SITES, and the one that SPEAKS is the one still wrong - the docstring is read only by a maintainer, the message is what a human reads at 2am. grep "meaningless zero" finds all three in under a second.
WHAT IT DOES AND DOES NOT FIX: it does NOT fix rhetorical convenience - nothing cheap does and gates.md is right to disclaim it. It fixes PROPAGATION of an already-caught one, a strictly easier problem, and that is what turned one error into three sites. AGENTS.md calls unexamined inheritance the kind we know how to catch; this is that kind wearing the other one clothes.
PROVENANCE, which is the part that survives summarising: the lane did not catch its own contradiction by RE-READING - it had already read the sentence while writing it. It caught it because a test asserting something about the filesystem FAILED FOR THE WRONG REASON. "Rhetorical convenience is invisible to review, including your own; the only detector I have found is executing a check whose outcome the sentence predicts."
Commissioned into session 9116957c as a standalone handoff entry, not buried in its unit.

## `c237` - Constraining non-ASCII in anything a console prints

**Status:** in_progress

Found by the audit lane; second instance found by me. Em-dashes in pytest assert messages render as replacement chars on a Windows cp1252 console. ON CI IT IS FINE - Linux, UTF-8, perfect. So the encoding that mangles the message is THE OWNER OWN MACHINE, and CI would never have shown it: the one reader whose experience matters most is the one no gate was checking. Generalises past encoding - CI runs in an environment chosen for reproducibility, the owner runs in the environment that actually exists, and every gate is green in the first and silent about the second.
SECOND INSTANCE, verified by me via AST on 15c8694: scripts/resolve_doc_conflicts.py lines 269, 415, 528 are sys.exit/print strings carrying non-ASCII. WORSE PLACE than assert messages: these fire when a lane is mid-rebase, blocked, reading the console for what to type next. And that file refusal advice is already known-wrong for the count-parenthetical case ("keep both sides" yields two copies), so a lane can meet a GARBLED rendering of ALREADY-WRONG advice while stuck. I reproduced the defect live while verifying it - my own terminal rendered line 461 back with a replacement char.
METHOD, the reusable half: RUN THE THING AND READ WHAT IT SAYS rather than read what you wrote. Proofreading happens in an editor that renders the character correctly, so proofreading structurally cannot find this.
Commissioned into 9116957c: ASCII the three strings, widen the AST test from assert-messages-in-one-module to anything-a-console-prints across scripts/. Docstrings/comments stay exempt. NOT fixing the wrong refusal advice - behavioural change, own unit.

## `c238` - Writing conclusions with their scope attached

**Status:** in_progress

ADOPTED as architect 2026-08-23 into docs/governance/gates.md. Authored by the teach-the-recorder lane, which found the flaw in my framing. I said the overstatement class was undetectable. It showed all four instances share a mechanical signature: EACH UPGRADED A SCOPED, DATED, COUNTED OBSERVATION INTO AN UNSCOPED PRESENT-TENSE PROPERTY. "two create_engine hits, both in db/session.py, at 74c8ba4" became "the package now has 13 ways in". "passes against committed fixtures" became "passes on a real export".
THE TELL IS NOT THE STRENGTH OF THE CLAIM, IT IS THE DISAPPEARANCE OF THE SCOPE. Strength is unbounded to scan for; absence of a commit/count/file in a sentence sitting beside one that has all three is narrow.
THE RULE: never write a conclusion in a sentence that does not carry its own scope. Not "the package has 13 ways in" but "at 74c8ba4, 13". It does NOT prevent overstatement - nothing cheap does. It makes the claim DECAY VISIBLY: the next reader checks the commit and disagrees in seconds without anyone having needed to catch it when written. Converts an undetectable error into an EXPIRING one, the class this project already knows how to handle.
SHARPEST PART: this is already the house rule for ONE FIELD and not for prose. "Could not verify" demands driven-or-reasoned against every claim and has held up all week. ALL FOUR OVERSTATEMENTS WERE IN PARAGRAPHS. The remedy is not missing - it is applied in exactly one place while the defect lands everywhere else.
CAVEAT THE AUTHOR KEPT AND I REFUSED TO LET DROP: it cannot be claimed this would have caught any of the four, only that it would have made each falsifiable in seconds.

## `c239` - Correcting my own numstat instruction to every lane

**Status:** done

MY ERROR, reported by the regeneration lane 2026-08-23. I told every lane to run "git diff --numstat origin/main -- docs/handoff.md" and confirm zero removed, as a guard against an entry being SWAPPED rather than dropped (which a correct total survives). I did not qualify it. Run BEFORE rebasing it compares against a main that has advanced past the branch base and MANUFACTURES AN ALARM: that lane saw 302 removed lines, EVERY ONE PHANTOM; against the true base it was 161 added, 0 removed. IT IS ONLY MEANINGFUL AFTER REBASING, OR AGAINST THE MERGE-BASE. Worse than useless before: an alarm that cries wolf on a check I told people to trust means the next real 302 gets shrugged at. Goes in the brief for every future lane.

## `c240` - Text census counted a docstring as a call site

**Status:** done

Found by the regeneration lane 2026-08-23, and it is a STRONGER argument for the AST import rule than the one that motivated it. The old literal-string census (test_store_creating_readers.py:132, scanning "Database.from_settings(") strips COMMENTS but not DOCSTRINGS. The lane wrote an honest disclosure that spelled the call verbatim in a docstring, and the scan INSERTED A FALSE ENTRY INTO THE AUDIT REGISTER. So the register was not merely incomplete - it was WRONG, with a fabricated member, and the fabrication was CAUSED BY SOMEONE DOCUMENTING THEIR WORK CAREFULLY. Honesty penalised by the tool. A text scan mistaking a DESCRIPTION of a thing for the thing. Empirical rather than deductive, so it survives someone asking "was the grep really so bad?" - the AST rule rationale must cite it.

## `c241` - Ruling: declared-purpose creators are a distinct census category

**Status:** done

ARCHITECT RULING 2026-08-23, on the regeneration lane request, routed rather than self-allowlisted. "Creates a store deliberately, as its declared purpose" is a DIFFERENT CATEGORY from "opens a store to read it and might create one by accident". merge_stores.py opens three ways: two sqlite3.connect(mode=ro) reads plus ONE PLAIN CONNECT ON THE OUTPUT PATH, which must create a file because writing the merged store IS THE JOB. A mode=ro writer is a contradiction, so it cannot be converted. Refusing it would be the AST rule mistaking its own hazard - the same error as forcing a verdict on a site the question does not fit, which puts a nonsense token in a register whose value is that every token means something. RULING: merge_stores.py gets an allowlist entry with a written reason naming creation as its declared purpose. LEGITIMATE ENTRY, NOT A WIDENING - the mechanism already carries reasons and fails stale entries so an exemption cannot outlive its cause. Cite this ruling in the code comment so the next reader sees it was adjudicated, not assumed.

## `c242` - Guarding the test-name SET, not the test COUNT

**Status:** pending

THE MOST VALUABLE UNBUILT THING LEFT TODAY. Found by the audit lane at its own expense 2026-08-23. Moving one test into its own module, it sliced the source between two function names and DELETED FIVE TESTS - including test_every_engine_call_site_is_classified, the census test that is the entire point of the preceding unit. FULL SUITE PASSED. ruff passed. mypy passed. "1733 passed" was a TRUE STATEMENT ABOUT THE TESTS THAT REMAINED.
It was caught ONLY because the lane had PREDICTED 1738 and got 1733. Nothing else in the repo would have caught it. Restored, then verified by test-name set: base 317 names, now 333, dropped none.
THE SHAPE: a count agrees with itself after a deletion. docs/backlog.md already learned this and gained a slug-set diff for exactly this reason. TEST SUITES HAVE THE IDENTICAL HOLE AND NOTHING GUARDS IT. A green suite cannot distinguish "all tests pass" from "the tests that would have failed are gone".
This is also the adversarial-versus-accidental line crossed: an attacker deleting the census test is obvious, but this happened ACCIDENTALLY, via a refactor, at exit 0, to the single most load-bearing test in the repository.
NOT BUILT deliberately: a repo-wide rule about test-name sets is a bigger claim than that unit earned and belongs to whoever owns CI shape. Needs an owner. Prime candidate for the same treatment as backlog_graph.py - commit the expected set, diff it, fail on a drop.

## `c243` - OWNER DECISION: bind preregistration v3 before the unblind

**Status:** blocked

ESCALATED 2026-08-23. Found by the independent quant review of PR 92. The v2 freeze HAS ALREADY BOUND - driven: para 10 binds at the earlier of merge-to-main (2026-08-21T16:03:03Z) and first cohort row collected (2026-08-22T00:25:43Z); (a) is earlier by 8.4h. So AMENDMENT WAS NEVER AVAILABLE; the only instrument is a v3, which is still pre-unblind and therefore still prospective.
GAP A - the era sensitivity was promised and never written down. Para 7 sensitivity list has exactly three entries and era is not among them. The adopted remedy after the era analysis was "declare composition and register era as a sensitivity, do not move the split". The split half was honoured, the registration half was not. Consequence: reporting an era-split held-out result post-unblind is an UNDECLARED ANALYSIS, and not reporting one discards the only handle on a confound measured at 5.5x in band composition (legacy 7.2% vs short-lead 39.7% in the <=60 band) and 68.2%/0% in partition composition.
GAP B - para 8 conditions 2 and 3 are close to UNFAILABLE, pure arithmetic on published denominators. Held-out informative q/p/d = 510 of 3940 = 12.94%. Condition 3 (|CITL| <= 0.10) requires the model to be wrong by delta > 0.773 on EVERY informative row to breach - 77 percentage points. And CITL is a signed mean so errors cancel. Condition 2 Brier beat over global_jeffreys is delivered almost entirely by separating out (75.2% of holdout) from the pool, the trivial part. SO PARA 8 CAN BE CLEARED BY A MODEL WHOSE POOLED RELIABILITY DIAGRAM IS BEAUTIFUL AND WHOSE QUESTIONABLE CELL IS GARBAGE - precisely the failure the gate exists to prevent, against the house rule that calibration beats accuracy.
Proposed condition 9 adds restricted CITL over q/p/d only (n=510 declared prospectively), operative for downstream consumers, pooled figure not sufficient alone. BOTH CHANGES ARE RESTRICTIVE-ONLY: can make activation harder, never easier.
WHY LEGAL PRE-UNBLIND: every motivating number is a denominator or predictor-side count. The reviewer has read no participation outcome and knows no conversion rate, so it cannot have chosen thresholds to favour a result it has not seen.
WHOSE CALL: authoring is quant (Proposed only); BINDING IS THE OWNER. Reviewer own argument, and it is the decisive one: "I am the agent who will be graded by this gate, proposing changes to it." Same separation as bridge/safety on the write path. FALLBACK IF DECLINED: fit proceeds under v2, era split and restricted calibration reported as clearly-labelled post-hoc diagnostics with no pre-registered status - worse but not fatal. DOES NOT BLOCK PR 92; v3 must bind before the unblind, not before the merge.

## `c244` - Inverting the para-2 disclosure guard to fail closed

**Status:** pending

Found by the independent quant review 2026-08-23. THE GATE IS A SET-EQUALITY OVER DETECTIONS, WHICH CAN NEVER FAIL CLOSED - not a tuning issue, THE WRONG QUANTIFIER. outcome_keyed_field_paths fires on mappings whose KEYS intersect ParticipationOutcome values; para 2 prose forbids an outcome-VALUED count. A field spelled played_by_status: {questionable: 812, probable: 391, doubtful: 40} is keyed by STATUS, is the entire para-2 secret, contributes nothing to the union, and the test stays green. direct_outcomes_by_status already exists in exactly that shape.
FIX, four parts, for data-engineer: (1) INVERT to a whole-surface allow-list - enumerate every index-normalised leaf path of every committed evidence artefact under docs/, assert set EQUALITY over ALL paths not over detections, so any new field of any name or shape fails the build. This is the only part that makes it fail closed. (2) Classify each frozen path with exactly one tag: denominator | outcome_valued | provenance | prose - adding a field costs one line stating which, converting an invisible omission into a visible claim by a named author. (3) Keep the key-based detector as a SECONDARY assertion over denominator-tagged paths only: a denominator whose keys intersect outcome values is a self-contradiction. Catches misclassification. (4) Name-based ADVISORY over path segments (outcome values plus play/played/suited/dressed/active/appearance/conversion/rate) - warn, do not fail.
COST: ~400 frozen entries across five artefacts. Mitigated by freezing PATHS ONLY, NEVER VALUES, so a regeneration moving numbers but no field names passes untouched.
MUTATION PROOF IS FREE AND ALREADY IN HISTORY: PR 92 directory_present fix added a leaf path, so running the widened test against 9d86033 frozen set with 1f19989 artefacts goes red. No probe needs constructing.
LIMIT FOR THE DOCSTRING: it cannot determine that a field CLASSIFIED denominator actually is one. Nothing mechanical can. What it guarantees is that a human classified every field in a reviewable diff - a smaller claim than the current test name implies.

## `c245` - Correcting ADR-007 note: the explanation, not the claim

**Status:** blocked

MY CHARACTERISATION WAS WRONG AND THE REVIEWER CORRECTED IT. I called adr_007_replication_note a KNOWN-FALSE STRING. It is not. Read exactly, the note claims the quantity ADR-007 NAMES - "unresolved doubtful per date" - does not replicate, and THAT IS TRUE: unresolved-doubtful-per-date really is 0.019/0.033 here. The separate finding is that ADR-007 NUMBERS replicate to four significant figures under a one-word correction to its own description. BOTH HOLD.
THE REAL DEFECT IS ONE LAYER DOWN AND IT IS STATISTICAL. The note conjectures "a count over raw report rows would be far larger" to explain the gap. THAT CONJECTURE IS DISPROVABLE FROM THE NOTE OWN NUMBERS: a canonical-vs-raw multiplier inflates BOTH eras and CANNOT REVERSE THEIR ORDERING. The note observes the reversal in its own next clause and offers an explanation that does not explain it. And the reversal needs no population difference at all - the unresolved counts are 2 AND 2. The entire directional claim rests on n=2 versus n=2 over different date counts: sampling noise in four rows treated as evidence of a population difference.
WHY WORSE THAN A PLAIN ERROR: A PLAUSIBLE WRONG EXPLANATION IS MORE DURABLE THAN A VISIBLE MISTAKE, BECAUSE IT STOPS THE SEARCH. Anyone later asking "why does ADR-007 not replicate?" finds an answer sitting there and moves on.
WHY IT BEARS ON THE FIT: this note is the artefact ONLY published statement about era-related risk in the doubtful cell, and as written it reads as evidence the era concern is overstated. It is not - the driven era x band cross shows <=60 is 7.2% of legacy rows against 39.7% of short-lead, holdout 100% short-lead. THE UNCORRECTED NOTE UNDERSTATES PRECISELY THE RISK v3 GAP A EXISTS TO MANAGE.
CONTAMINATION: NONE. Affects no number; the two rates the test asserts (<0.1 both eras) are correct facts; touches no outcome so no blind exposure.
THE CORRECTION SHOULD SAY: "the figures replicate; the word unresolved is the error; the 2-vs-2 comparison does not support a directional claim." NOT "the string was false."
ALSO RENAME test_the_adr_007_figure_does_not_replicate_and_that_is_recorded - NAMES OUTLIVE BODIES.
Stays open on ADR-007 original derivation being unlocated. Close it by FINDING THE CODE, not by asserting the replication.

## `c246` - Day-bucketing injury reports on UTC instead of Eastern

**Status:** pending

LIVE HAZARD, 7 KNOWN ROWS, NOT FIXED. Found by the regeneration lane while closing the era-boundary caveat. The report era is NBA-operational and therefore EASTERN, but 7 timestamps in the corpus have a UTC date ONE DAY AHEAD of their Eastern date - reports at 00:15/00:45 UTC, e.g. 2025-12-31 00:15Z = 2025-12-30 19:15 ET. The lane first pass grouped by UTC date; re-run grouped by Eastern the signature is identical AND THE CONCLUSION HOLDS ONLY BECAUSE NONE OF THE 7 LAND NEAR THE BOUNDARY. THAT IS LUCK, NOT DESIGN. This is the gameEt shape from AGENTS.md again: a correct instant assigned to the wrong day by a grouping that assumed a timezone. ANYTHING THAT BUCKETS INJURY REPORTS PER-DAY HAS A LIVE OFF-BY-ONE ON 7 KNOWN ROWS. The cohort artefact does not bucket that way so it is not a defect there - flagged as INHERITED SURFACE. Whoever builds per-day availability aggregation must convert to Eastern before grouping.

## `c247` - Era boundary verified, and it was 100% of the boundary date

**Status:** done

CLOSED 2026-08-23, and the answer is worse than "no instances". The admissibility lane left this REASONED, NOT VERIFIED: is era classification correct for reports filed ON 2025-12-22 between midnight ET and first tip-off? The lane expected the window empty. IT HOLDS ALL FOUR REPORTS FILED THAT DAY - 16:30, 17:30, 18:15, 18:45 ET against a 19:00 ET first tip. SO IT WAS NEVER A BOUNDARY CASE THAT HAPPENED NOT TO ARISE; IT APPLIED TO 100% OF THE BOUNDARY DATE AND WAS UNVERIFIED. Both classify correctly by two signatures that never consult FIFTEEN_MINUTE_ERA_START: (1) minute-of-hour is era-exclusive - across 121 legacy timestamps the minute is ONLY :30 (116) or :45 (5), with :15 and :00 occurring ZERO times, and the boundary date 18:15 report carries a :15; (2) lead-time cadence is a different regime - the four sit at 150/90/45/15 min before first tip, the new era converging ladder, while the legacy day before ran 18:45 and 22:45 ET against a 15:30 first tip, i.e. AFTER it. Independently corroborated by the quant review. Now VERIFIED rather than reasoned.

## `c248` - backlog_graph.py --summary appends into its own subject

**Status:** pending

BACKEND OWNS scripts/ per ownership.md:26 - filed, not taken. A lane ran "backlog_graph.py --summary docs/backlog.md". --summary means "ALSO APPEND THE REPORT HERE" and the backlog path is POSITIONAL. So it parsed the default backlog and APPENDED ITS OWN 101-LINE REPORT INTO docs/backlog.md. EXIT 0, NO WARNING. Three reasons it matters beyond one lane mistake: (1) what saved the lane was running git add -A BEFORE the gates rather than after - the more natural order commits it silently; (2) IT WOULD HAVE BEEN AN ABSOLUTE-PATH LEAK, since the no-arg default resolves absolute and the appended text carries C:/Users/steverones/... ; (3) A SELF-DESCRIBING REPORT APPENDED INTO ITS OWN SUBJECT IS SELF-INVALIDATING - it says "142 items" while adding headings to the file that count comes from. REMEDY: refuse a --summary target that is the parsed backlog, or emit a relative path.

## `c249` - Masthead tolerance has zero margin, deliberately

**Status:** done

NOT A DEFECT - a live tripwire, flagged so the next cadence shift reads as expected rather than as a surprise. A lane closed its own "could not verify" by checking report_timestamp against PDF mastheads: 582 OF 582 CACHED REPORTS MATCH EXACTLY, stored instant equals the PDF printed masthead converted ET->UTC. Checked against document CONTENT, independent of the filename - the self-describing field that could have lied. It exercises a docstring that was previously believed. THE TOLERANCE HAS ZERO MARGIN: _verify_masthead accepts <=45 min under a strict >. Measured legacy offsets are :30 for 116 reports and :45 for 5. THOSE FIVE PASS ONLY BECAUSE THE COMPARISON IS > AND NOT >=. The lane deliberately did NOT widen it - the bound is doing real work and loosening it on five reports trades a live tripwire for comfort. ARCHITECT RULING: agreed, leave it. Also corrected: a comment claiming legacy reports publish "consistently at :30 past" was measurably false - the five :45s are the last five legacy reports, 2025-12-19 to 12-21, a real cadence shift immediately before the fifteen-minute era.

## `c250` - A green with no number, caused by the flag added to read the number

**Status:** pending

Found by the manifest-leaf-diff lane 2026-08-23. Passing -q on the pytest command line STACKS with the -q already in addopts to make -qq, which SILENTLY SUPPRESSES THE "N passed" SUMMARY LINE while still exiting 0. The lane hit it reaching for the count and spent two runs thinking the summary had vanished.
WHY IT MATTERS BEYOND ANNOYANCE: the missing number is the exact quantity every lane was told today not to trust on its own, and the flag that removes it is the one you add IN ORDER TO READ IT. It is the truncation trap and the false zero wearing the same coat - AN ABSENCE THAT LOOKS LIKE AN ORDINARY RESULT. A run that reports nothing and exits 0 is indistinguishable at a glance from a run that reported success.
Remedy is a documentation line at minimum: do not pass -q to pytest in this repo; addopts already carries it.

## `c251` - Squash merges make ancestry and branch-diff both lie

**Status:** done

ARCHITECT NOTE, and I nearly filed a false alarm from it during closure 2026-08-23. Two traps, same root: this repo SQUASH-merges, so a merged branch commit is NEVER an ancestor of main.
TRAP 1: git rev-list --count origin/main..<branch> reports every merged branch as "N commits ahead". At closure I saw 48 branches all reporting ahead and briefly read it as unpreserved work. It is the expected artefact of squashing, not evidence of anything.
TRAP 2: the obvious correction is also wrong. git diff origin/main..origin/<branch> reports most merged branches as DIFFERING, because they are BEHIND main - the diff includes reverting everything merged after them. Neither number answers "is this work preserved?"
THE VALID EVIDENCE is (a) GitHub PR state MERGED, and (b) the branch distinctive artefact being present on main by path. Both cheap, both direct. This is the same shape as everything else found today: TWO PLAUSIBLE MEASUREMENTS THAT BOTH ANSWER A DIFFERENT QUESTION THAN THE ONE ASKED, and the second is more dangerous because it looks like the careful version of the first.

## `c252` - PRESERVE: reason x status cross exists nowhere in the repo

**Status:** pending

THE ONE THING THE REPOSITORY CANNOT RECOVER from the quant review session. stated_reason_categories is committed as a MARGINAL ONLY (3,385 G League, 9,666 Injury/Illness, ...). THE CROSS WITH STATUS EXISTS IN NO COMMITTED ARTEFACT, in either manifest - checked both.
So what is recoverable is "3,385 rows say G League". What is NOT recoverable is that 41 OF THEM ARE doubtful - 18.6% of the entire doubtful column. A Two-Way player who might be recalled: real uncertainty, but a ROSTER MECHANIC not a health event, whose conversion rate has no reason to resemble injury-doubtful.
v3 section 6 records the CONCLUSION as prose - 83 published, ~74 health-reason, 2.5x headroom not 2.8x over the >=30 floor - WITH NO TABLE BEHIND IT and no way to check it short of re-driving. That is the weakest link in v3: a number quant will be graded against, asserted on its own authority, in a document arguing a floor has less headroom than it appears.
THE TABLE, from the transcript: Injury/Illness out 6938 / doubtful 171 / questionable 1044 / probable 390 / available 1123 = 9666. G League out 2960 / doubtful 41 / questionable 134 / probable 43 / available 207 = 3385. Not With Team out 246 / doubtful 1 = 247. Nine further heads: out 309 / doubtful 8 / questionable 13 / probable 2 / available 159 = 491. Held-out health-reason only: doubtful 74, questionable 270, probable 75.
ERA x BAND, half-recoverable (partition composition IS committed, the band cross is NOT): legacy <=60 308 (7.2%), 61-180 2789, 181-540 1119, >540 34 = 4250. Short-lead <=60 3783 (39.7%), 61-180 4048, 181-540 1676, >540 32 = 9539. THE 5.5x IS THE SHARPEST EVIDENCE FOR GAP A and is nowhere.
SECTION 8 ARITHMETIC IS SAFE: held_out_direct_outcomes_by_status is committed on main. 335+92+83=510; 510/3940=0.129442; 0.10/0.129442=0.7725. Re-derived from the committed blob, matches v3 0.773.

## `c253` - OWNER DECISION CORRECTED: v3 is correctness and a one-way door

**Status:** blocked

I FRAMED THIS WRONG IN THE 8-24 STANDUP AND THE REVIEWER CORRECTED IT. It also corrected its own earlier "worse but not fatal", which described what the ANALYSES lose if v3 is declined - NOT a statement that work can begin. Taken as scheduling it points the wrong way.
THE BLOCKING MECHANISM IS NOT THE HELD-OUT BLIND. IT IS v3 OWN LEGALITY. Section 7 held-out evaluation is the once-only act; section 5 fitting and section 6 selection are not, and neither v3 change touches them - so on the face of it they could run under either protocol. BUT SECTION 5 AND 6 READ THE SELECTION PARTITION OUTCOMES, 3,609 observations. The moment they run, quant knows the conversion rate of every status. And v3 section 5 - the section arguing the amendment is legal - says in terms "the author does not know the conversion rate of any status".
So starting the fit while v3 is unbound does not spend the held-out blind. IT RETROACTIVELY DESTROYS THE PROPERTY THAT MAKES v3 BINDABLE AT ALL, converting it into an amendment proposed by someone who has since seen outcomes. Whether it actually steered becomes UNVERIFIABLE - the precise condition preregistration exists to rule out. CORRECTNESS QUESTION, NOT SCHEDULING.
ONE-WAY DOOR: declining v3 is not deferring v3. Section 10 - after the unblind a change "is recorded beside the result and may never be presented as pre-registered". Once section 7 runs, NO FUTURE AMENDMENT CAN EVER BE PROSPECTIVE AGAIN. "No" is not "later", it is "never". Permanently forgone: a GATED calibration check on the informative statuses. The post-hoc version can still be computed and published; it simply cannot stop an activation. Against the house rule that calibration beats accuracy for p(play), that is the whole substance of Gap B.
WHAT CAN LEGITIMATELY START NOW, a genuine share of the critical path touching no outcome: everything predictor-side (the crosses, driver-feature persistence, identity and lead-time plumbing); the calibration and reliability-diagram machinery developed and tested on SYNTHETIC data; the model card skeleton including "what the model cannot see". What must wait is the first line that reads an outcome.
AND THE REVIEWER GUARDED ITS OWN ARGUMENT: "the 41 blocked items are a deadline argument. They are a real cost and they are not a reason. I would give you the same answer if the number were four hundred."

## `c254` - DEFERRED: contingent-value, and the reason is not the obvious one

**Status:** blocked

ARCHITECT RULING 2026-08-25. contingent-value is READY (absence-splits done) and unblocks 8 items. NOT LAUNCHED. I checked rather than guessing: absence_splits.py reads PlayerParticipation directly and heavily - lines 32, 165-176, 433-518. That IS the outcome table.
THE OBVIOUS ARGUMENT FOR SAFETY, which I am NOT relying on: absence-splits computes usage redistribution (when X sits, who gains) from participation ALONE, without joining to injury_report_entries, so it does not reveal any status->play CONVERSION RATE. The blind is about the conversion rate of a STATUS. On that reading contingent-value is fine, and absence-splits is already merged so the reading is already established.
WHY I DEFERRED ANYWAY: the quant reviewer stated the boundary as "every table it opens is one line from player_participation" and that v3 ENTIRE LEGALITY ARGUMENT rests on that boundary having been held. An agent that has read participation outcomes at scale - even for a different question - is HARDER TO CERTIFY AS BLIND than one that has not. The property v3 needs is not "did not learn the conversion rates" but "cannot be suspected of having learned them", and the second is what preregistration exists to protect.
COST OF BEING WRONG IS PERMANENT AND ASYMMETRIC: if I launch it and the reasoning is thin, v3 becomes unbindable and no future amendment can ever be prospective. If I defer, I lose 8 items of parallelism for a few days.
TRIGGER TO REVISIT: owner binds or declines v3. Either resolves it - if bound, the property is already secured; if declined, there is nothing left to protect. ROUTE TO quant for a ruling at that point, not to me.

## `c255` - A dependency can be satisfied as a computation and unsatisfied as a contract

**Status:** pending

ARCHITECTURAL FINDING 2026-08-25, from the frontend lane, and it applies to EVERY EDGE IN docs/backlog.md. reliability-ui depends on reliability-metrics, which is marked done - but reliability-metrics SHIPPED NO API. Its own done-text at backlog.md:548 says "no schema, API, or UI was added"; docs/models/reliability-metrics.md says "No result table, migration, API, or UI is part of v2"; live GET /openapi.json lists 16 paths and git grep -n reliability -- backend/src/hoops_gm/api returns ZERO. The computation exists as compute_reliability_scorecards(), callable IN-PROCESS ONLY.
So the edge is satisfied as a COMPUTATION and unsatisfied as a CONTRACT, and backlog_graph.py cannot tell those apart - it resolves names. Its own output already disclaims this ("not a statement that the backlog is accurate"); this is the first concrete instance of what that disclaimer covers.
MY ERROR: I selected the unit off the ready list and verified the dependency was DONE without asking DONE AS WHAT. Domain narrower than hazard, again.
REMEDY, unbuilt and needs an owner: either edges carry a kind (computation / contract / artefact), or consuming units state the surface they need and a check verifies it exists. The second is cheaper and fails loudly. NOT trivial - it is a schema change to the backlog format.

## `c256` - Reliability endpoint: the unit that actually matters

**Status:** pending

BACKEND. Filed 2026-08-25 after the frontend lane showed reliability-ui cannot be built without it. compute_reliability_scorecards() in backend/src/hoops_gm/availability/reliability.py is callable in-process only; no route carries any reliability quantity.
SECOND-ORDER PROBLEM, and it is the hard part: THE EVIDENCE IS NOT WHERE THE DEMO IS. The populated ledger (C:\\Users\\steverones\\hoops-gm-data\\hoops_gm.db) has 43,037 participation rows, 596 players, 1,227/1,230 final games observed, 2025-26 ONLY - and has nba_games, player_game_logs, player_participation, players, nba_teams and NOTHING ELSE. No team_schedule, no leagues, no refresh_runs. compute_reliability_scorecards REQUIRES team_schedule plus three current refresh_runs cohorts, so IT CANNOT CURRENTLY RUN AGAINST THE ONLY STORE THAT HAS THE DATA. Meanwhile the demo backend serves 2026-27 (1206/1200/2400) with no participation at all.
ARCHITECT RULING, made 2026-08-25: RELIABILITY EVIDENCE READS 2025-26. The 2026-27 season has ZERO played games as of today and will until late October, which is after draft day. Any reliability screen that means anything before 18 October reads last season. This belongs in the ENDPOINT CONTRACT, not a UI toggle. AND THE SEASON MUST BE NAMED ON THE SCREEN, not in a tooltip - a durability figure whose season is ambiguous is the gameEt shape: well-formed, plausible, silently about a different thing than the reader assumes.
Blocked on nothing. Gate: Code. This is the unit that makes the fragility screen load-bearing.

## `c257` - Producer-side outcome-read census closes the valued clause

**Status:** pending

SPECIFIED BY THE QUANT REVIEWER 2026-08-25, cost settled by me the same hour. It overturned its OWN earlier fix to get here.
THE ARGUMENT, which needs no instances: "OUTCOME-VALUED IS A SEMANTIC PROPERTY OF A NUMBER. IT IS NOT A SYNTACTIC PROPERTY OF JSON. 510 and 3,940 are the same shape of bytes; one is a denominator and one could be a marginal. NO DETECTOR READING THE ARTEFACT CAN EVER CLOSE THE VALUED CLAUSE" - not with a better token list, not a wider scan, not path-segment matching. So neither existing implementation is buggy; both are complete implementations of the only half expressible at the artefact. THE GAP IS IN THE LOCATION, NOT THE CODE, which is why two independent authors reading prose that names both clauses both shipped the same half.
IT CORRECTED ITS OWN BUNDLING: hole 1 (an unclassified field arrives, nothing recognises it) and hole 2 (the valued clause) are DIFFERENT. The whole-surface allow-list closes hole 1 ONLY. For hole 2 it forces a one-word classification - and if the author believes play_rate is a denominator they write "denominator" and the build stays green. "I described it as closure. It isn t."
THE FIX: a field is outcome-valued IFF THE CODE THAT COMPUTES IT READS A PARTICIPATION OUTCOME. Not a pattern question over JSON - a REACHABILITY question over the builder, and reachability is mechanically checkable. Confine every read of PlayerParticipation.outcome / ParticipationOutcome to a small named set of call sites and assert in CI the set has not grown. Any published section produced outside that set is outcome-free BY CONSTRUCTION. The repo already does exactly this shape for engine call sites in test_store_creating_readers.py.
COST SETTLED BY ME, driven on origin/main, the ten-minute check it specified: THREE actual producing reads - cohort_admissibility.py:456, cohort_evidence.py:1118, cohort_evidence.py:1127. Plus the detector itself at :66/:96-100/:104 and a CLI flag at cohort_evidence.py:1670. SO THE CONFINEMENT IS A TEST, NOT A REFACTOR. Its open caveat ("if outcome reads are scattered through the aggregation paths this is a refactor and changes the cost materially") resolves in favour of cheap.
TRAP INSIDE THE CHECK, found while running it: THE WORD "outcome" IS OVERLOADED. backfill.py has 11 hits on .outcome that are NOT participation outcomes - they are fetch-coverage outcomes with an entirely different vocabulary ("fetched", "observed", "legacy_excluded", "forbidden", "not_available"). A census keyed on the ATTRIBUTE NAME drowns in them and would report 14+ sites where there are 3. IT MUST KEY ON THE ParticipationOutcome TYPE / ORM COLUMN, NOT THE NAME. Same shape as gameEt: a self-describing name that means two different things in one package.

## `c258` - POOLED-BAND MASKING: a pre-registered model can pass every condition while being 86 points wrong

**Status:** pending

FOUND BY THE CALIBRATION LANE 2026-08-25, driven on synthetic data. STRONGER THAN THE DILUTION ARGUMENT v3 CURRENTLY RESTS ON, because it does not depend on the 0.7725 arithmetic at all.
v2 section 5 PRE-REGISTERS three_band_jeffreys, which POOLS out WITH doubtful. Held out that is 2,963 to 83 - 35.7 to 1. If each band emits its own realised rate, EVERY BIN GAP IS EXACTLY ZERO: CITL 0.0, ECE 0.0, condition 4 passes, condition 5 passes BECAUSE THE BAND IS ONE BIN AND THAT BIN IS EXACTLY RIGHT, condition 7 finds no reversal. Meanwhile doubtful is predicted at the band rate 134/3046 = 0.0440 against a fictional 0.90 - APPROXIMATELY 86 POINTS WRONG, INVISIBLE. Only subgroup restriction sees it.
WHY IT STRENGTHENS v3: the case for a restricted table stops depending on the dilution bound. Someone can dispute that arithmetic and the masking demonstration still stands, because it is a statement that THE CONDITION SET IS SATISFIABLE BY A PRE-REGISTERED CANDIDATE WHILE BEING ARBITRARILY WRONG ON A STATUS.
v3 section 4 BOTH OVERSTATES AND UNDERSTATES. Overstates: it argues from calibration-in-the-large alone and never analyses CONDITION 5, which under distinct-emitted-probability binning gives real per-status protection wherever a status gets its own bin - Wilson half-width on questionable at n=335 is about 0.054, tighter than 0.10. A five-status model is not as unconstrained as the dilution bound suggests. Understates: the pooled-band hole, which condition 5 cannot touch.
PROVISIONAL until the independent reviewer tries to break it. The lane itself flagged the obvious objection - that "every gap exactly zero" may be circular, an artefact of defining predicted as each cell realised rate - and ASKED THE REVIEWER TO ATTACK IT. Do not propagate as settled until that returns.
IF v3 IS AMENDED BEFORE BINDING, this is the argument to lead with.

## `c259` - A house rule is wrong in one direction: reasons are unreliable BOTH ways

**Status:** pending

AGENTS.md says "Do not trust stated DNP reasons - Rest is routinely laundered as a minor ailment. Lean on observed patterns." TRUE BUT INCOMPLETE, found by the calibration lane 2026-08-25.
7 of the 97 Rest rows carry the subcategories "Left Knee - Injury Management" / "Left Knee Injury Management". THE RULE DESCRIBES AILMENT-LAUNDERED-AS-REST; HERE THE AILMENT IS FILED UNDER REST. So the corruption runs in both directions and the rule only warns about one.
CONSEQUENCE, and it is not cosmetic: THE HEALTH / NON-HEALTH SPLIT v3 SECTION 6 ASKS FOR IS ITSELF A STATED-REASON ARTEFACT, NOT GROUND TRUTH. The 1,609 "health-reason informative rows" figure and the doubtful 83-vs-74 headroom correction both rest on classifying stated reasons, which this shows is unreliable in both directions rather than only optimistic.
ACTIONS: (1) worth a line in v3 if it is amended before binding - the restricted-set definition should say it is reason-derived and therefore approximate; (2) AGENTS.md house rule should be widened from "rest laundered as ailment" to "stated reasons are unreliable in both directions"; (3) any downstream filter keyed on stated reason inherits this.

## `c260` - READ-ONLY AND OUTCOME-FREE ARE DIFFERENT PROPERTIES, and only the first was enforced

**Status:** done

FOUND BY THE data-engineer LANE 2026-08-25, and it corrects THREE agents at once including me. Verified by me on origin/main.
read_only_engine docstring in cohort_admissibility.py is ENTIRELY about file creation and missing paths - the withdrawn meaningless-zero claim, and PR 88 correction that mode=ro refuses a missing file rather than creating it. EVERY WORD IS ABOUT WRITES AND CREATION. NOT ONE IS ABOUT WHICH TABLES MAY BE READ.
And we all leaned on it as if it were. The cohort lane reported its module "read-only by construction". The quant reviewer ruled the escaped census site UNCLASSIFIED NOT UNGUARDED because "it can neither create a store nor write into one" - true, and about writes. I REPEATED THAT RULING TWICE, including in a lane brief, as though read-only implied outcome-free.
MEASURED, not argued: the exact read the new guarded engine refuses returns 43,037 ROWS on a plain read_only_engine. mode=ro stops writes and nothing else; player_participation stays fully readable.
CLASS: unexamined inheritance where THE HAZARD IS REAL AND ITS APPLICABILITY IS WHAT WENT UNCHECKED - the shape the cohort lane named at its own expense on 2026-08-23, recurring in the same week through three agents.
REMEDY, stronger than the producer-side census I filed as c257: a SQLITE AUTHORIZER vetoing reads outside {injury_report_entries, nba_games} BEFORE SQLite executes the statement. "A call graph cannot see a lazily loaded relationship firing on attribute access; an authorizer does not care how the read was spelled." c257 REMAINS NEEDED for cohort_evidence.py and cohort_admissibility.py, which legitimately DO read outcomes and cannot be authorizer-locked - different problem.
BOTH HALVES DRIVEN: shrink the allow-list -> exit 2 naming nba_games; player_participation denied through the guard and readable unguarded, so the denial is the authorizer not an unreadable file; unmutated run BYTE-IDENTICAL, Compare-Object 0 lines - establishing that a permission set of exactly those two tables is SUFFICIENT to compute every number printed. SQLite own error is the bare string "not authorized", so denied names are captured and reported.
SCOPE LIMIT, from the lane own doc correction: told if a change reaches a THIRD table; NOT told if it changes selection semantics within the same two - a different WHERE, join key, or notion of "ready". TYPE-CHECKING SEES SIGNATURES, AN AUTHORIZER SEES TABLE NAMES, NEITHER SEES MEANING.

## `c261` - predict_union.py says to check the count but not WHEN

**Status:** pending

SMALL AND ACTIONABLE, found by the data-engineer lane 2026-08-25 during the PR 97 rebase. A MID-REBASE COUNT MUST NOT BE COMPARED AGAINST A WHOLE-REBASE PREDICTION. Predicted union 268 (263 + 3 + 2). Intermediate counts were 266 then 267. 266 AGAINST A PREDICTED 268 READS LIKE TWO LOST ENTRIES - exactly the alarm the tool exists to raise, arriving falsely. The lane checked each commit contribution (1, 1, 1) rather than trusting either number; final count was 268.
predict_union.py docstring says to check the count and does NOT say at which point. REMEDY: one sentence in the docstring, and ideally in the PRINTED OUTPUT since that is where the reader meets it - the prediction is for the WHOLE rebase; compare only after the last commit is applied, or compare per-commit contributions.
SAME CLASS AS MY OWN NUMSTAT ORDERING ERROR (c239): a check correct at one moment that manufactures a false alarm at another, where the instruction omits the moment. An alarm that cries wolf on a tool people were told to trust is worse than no tool, because the next real discrepancy gets shrugged at.

## `c262` - The harder variant of unexamined inheritance: nothing false to find

**Status:** pending

THE DEEPEST OBSERVATION OF THE DAY, from the data-engineer lane 2026-08-25, offered on its own account.
A WRONG CLAIM CAN BE FALSIFIED BY CHECKING IT. A TRUE CLAIM CARRIED INTO THE WRONG CONTEXT RETURNS *TRUE* WHEN CHECKED, AND THE CHECK FEELS LIKE DILIGENCE. What needs checking is the DOMAIN - and nobody asks that about a guarantee already verified once.
That is why read_only_engine propagated through three agents. Every step was true: the module IS read-only by construction; the escaped census site CAN neither create nor write; mode=ro DOES refuse a missing file. THE FALSE STEP WAS NEVER STATED - it was the inference that read-only implied outcome-free, which nobody wrote down and therefore nobody checked.
WHY THE PREVIOUS RECORD DID NOT PREVENT IT: the cohort lane filed the same shape on 2026-08-23 - "inheriting a real hazard into a new context is an unexamined inheritance even when the hazard is real, because what goes unchecked is not the hazard but its applicability". IT WAS FILED AS AN INSTANCE RATHER THAN AS A SHAPE, so it read as a story about that lane rather than as a rule. THAT IS A LESSON ABOUT HOW THIS PROJECT RECORDS THINGS, not about SQLite.
COULD NOT VERIFY, and it is the honest limit: there is no census of "guarantees cited outside the context they were established in", and the lane does not know how to write one. THE DEFECT IS IN THE CITATION, NOT THE GUARANTEE, SO SCANNING GUARANTEES FINDS NOTHING. If this shape is worth a unit it is NOT A SCAN - it is a review habit. Same conclusion gates.md reached about rhetorical convenience, arrived at independently from the other direction.

## `c263` - STASHES ARE A BLIND SPOT NO CHECK IN THIS PROJECT REACHES

**Status:** pending

Found by the data-engineer lane on its way out, 2026-08-25, and verified by me. CHEAP TO CLOSE, unlike most findings of this shape.
WHY NOTHING SEES THEM: stashes are REPOSITORY-GLOBAL, not per-worktree. They do not appear in git status in ANY worktree. They survive git worktree remove SILENTLY. They are attributed to a BRANCH NAME rather than a location, so the lane that made them may have no worktree left and nothing would say so. EVERY CHECK THIS PROJECT RUNS FOR STRANDED WORK LOOKS AT BRANCHES - that is how PR 96 was found. A STASH IS INVISIBLE TO ALL OF IT.
And I looked straight at these on 2026-08-23 while hunting the permanently-lost handoff edit, listed them, and moved on. So this is my miss twice over: I had the output on screen and did not ask whether anything in it was unlanded.
WHAT IS THERE, verified by me on origin/main: two stashes, 8 days old, from sr2501-schedule-context-planning, both containing docs/handoff.md edits (32 and 39 lines). BOTH SUBSTANTIALLY SUPERSEDED - the lane checked rather than raising an alarm on resemblance. stash@{0} entry is on main at line 1196 with its code hunks landed. stash@{1} substance landed as docs/models/schedule-context.md.
ONE PRECISE RESIDUE: the heading "## 2026-08-17 - quant - Schedule context design" is ABSENT from main - confirmed, two other 2026-08-17 quant entries exist but not that one. Its 39 lines summarise the schedule-context model boundary. The one sentence not obviously duplicated: "schedule context supplies auditable environment features and may condition availability, but it does not blend per-game production with expected games or silently manufacture p(play)" - which is ADR-002 separation applied to schedule context.
ARCHITECT RULING: DO NOT RESTORE THE ENTRY. docs/handoff.md is append-only and records work AS IT HAPPENED; inserting a backdated entry now misrepresents when it was written, and the substance is in a committed model doc. DO NOT DROP THE STASHES EITHER - they are not ours and cost nothing.
REMEDY, and it is genuinely near-free: add "git stash list" to the standup and/or the Code gate. A non-empty result with an entry older than N days is a finding worth one human glance. One command.

## `c264` - v3 section 6 carries TWO population errors, not one

**Status:** in_progress

RESOLVED 2026-08-25, and my two previous accounts were both wrong. The mechanism was committed to main in a docstring before anyone guessed at it.
THE MECHANISM IS CANONICAL-VS-DIRECT. Verified by me in scripts/cohort_predictor_crosses.py on main: "All three are over the CANONICAL selection - 13,789 observations, the same population as status_counts. They are NOT over the DIRECT selection of 13,598 that direct_outcomes_by_lead_time_band uses in the admissibility artifact... anything comparing a number here against that artifact MUST CONVERT FIRST."
That distinction at the doubtful cell IS the 84-vs-83 gap. ONE CANONICAL HELD-OUT DOUBTFUL ROW HAS NO PARTICIPATION OUTCOME ATTACHED. Not a double-categorised row. The committed _held_out_doubtful_note computes exactly the bracket - one non-direct row, either G League or not, so direct non-G-League is in [73, 74] - and REFUSES TO PRINT A BOUND AT ALL if the direct count exceeds the canonical, because "two artifacts disagree; that is a finding, not a rounding error".
SO THE NUMBERS WERE RIGHT AND BOTH ACCOUNTS OF WHY WERE WRONG, which is the worse way round: A CORRECT NUMBER WITH A WRONG MECHANISM SURVIVES REVIEW. I was about to file [73,74] as a HEDGE BETWEEN TWO CANDIDATE BASES. It is a DERIVED BRACKET from two committed integers and a subset relation. Same pair, different epistemic status, and the difference matters the moment someone asks whether it can be tightened.
IT SHARPENS THE v3 DEFECT RATHER THAN SOFTENING IT: 74 IS NOT A RIVAL BASE FOR THE DIRECT COUNT. IT IS THE CANONICAL NON-G-LEAGUE COUNT REPORTED AS THOUGH IT WERE THE DIRECT ONE. So section 6 carries TWO population errors - canonical-for-direct AND non-G-League-for-health - and only the second was under correction. Two well-formed quantities that are not about the same thing.
STILL PUBLISH THE PAIR, now as a derived bracket with its mechanism: direct non-G-League in [73,74]; health-reason 68-69 as an approximate lower reading, reason-derived and contested in both directions. Every reading clears the floor of 30 by more than 2x.
THE TRANSFERABLE LESSON, from the lane: BEFORE GUESSING AT A DISCREPANCY, LOOK FOR THE LANE THAT OWNS THE QUANTITY. A data-engineer lane had committed the answer, in a docstring, on main, and neither of us looked. The guess even came WITH A MECHANISM, which made it more persuasive and no more true.

## `c265` - I asserted the opposite of a decision the repo had written down

**Status:** done

Reported by the data-engineer lane against itself 2026-08-25. It published, in a commit message AND an adapter doc, that scripts/ is outside the pytest, ruff AND mypy scopes so nothing in CI lints it. MYPY CHECKS IT, STRICT - backend/pyproject.toml:134, whose own comment says ../scripts was added DELIBERATELY because "a script that is checked while its tests are not is the gap that shipped a broken harness today".
THE MECHANISM IS THE INTERESTING PART AND IT IS NOT CARELESSNESS: IT DID MEASURE, AND GOT A TRUE ANSWER TO A DIFFERENT QUESTION. Running "mypy <path>" resolves hoops_gm from site-packages and reports import-untyped; the CONFIGURED run resolves it from src and passes. TWO INVOCATIONS, TWO ANSWERS, AND IT GENERALISED FROM THE CONVENIENT ONE. Settled by inserting a deliberate type error and watching the configured run go red.
Same family as the -qq trap and the local-main trap: an invocation that differs from the sanctioned one in a way that changes the answer without announcing it. AND it asserted the opposite of a decision written down IN THE FILE IT WAS READING OTHER CONFIG OUT OF.
The script does pass strict mypy in CI - the lane called that "lucky, not earned", which is the right characterisation.

## `c266` - A probe shares the screen assumptions by construction

**Status:** pending

LIMIT ON A TECHNIQUE I PROPAGATED TO EVERY LANE. Found by the frontend lane 2026-08-25, against its own work.
I have been instructing lanes to CARRY AN INVARIANT AND A MOVER IN THE SAME PAYLOAD, as though it closed the verification problem. IT DOES NOT. It closes DEAD PROBE and NOTHING CHANGED. IT IS STRUCTURALLY BLIND TO A SHARED MISREADING.
THE INSTANCE: the lane rendered pending_game_ids.length under the label "Undated games". That field means TEAMS NOT YET DECIDED (ADR-013, schedule_grid.py:109). Six pending, ALL SIX CARRY A DATE, ZERO UNDATED. Its test asserted the false sentence VERBATIM and was green - defending the bug specifically.
AND ITS BROWSER PROBE PASSED ON IT. The probe carried an undatedOnScreen flag comparing screen against API - AND AGREED, BECAUSE THE SAME FIELD WAS READ INTO BOTH SIDES. "A probe written by whoever wrote the screen shares its assumptions by construction. AGREEMENT ON A VALUE SAYS NOTHING ABOUT AGREEMENT ON ITS MEANING."
The blindness is worst precisely where the probe author is the screen author - which is every case where the technique is cheap enough to use.
PROPOSED RULE, mine, unvalidated: A PROBE FLAGS MUST BE RE-DERIVED FROM THE PRODUCER CONTRACT, NOT FROM THE CONSUMER READING OF IT. The lane fixed the one flag review pointed at and stated plainly that the rest have not been - "the same failure is available to every other flag" - which is the honest residual.
THE GENERALISATION, worth more than the instance: A NUMBER YOU DERIVE GETS CHECKED; A SENTENCE YOU WRITE ABOUT IT DOES NOT. An evidence screen is almost entirely sentences about numbers, which makes it a uniquely bad place for a check that only looks at numbers. ALL THREE REVIEW ROUNDS ON THAT PR FOUND A REAL DEFECT AND NONE WAS IN A NUMBER - lint, types and a green suite were true at every head.

## `c267` - test_name_diff.py: name the scope in the SUCCESS sentence

**Status:** pending

SHARPENED 2026-08-25 by the frontend lane, and the fix is one string rather than a feature.
THE DEFECT: "python scripts/test_name_diff.py origin/main HEAD" returns "No change to the set of test names", exit 0, no warnings - WHILE THE PR ADDS 58 VITEST TESTS THE TOOL NEVER LOOKED AT. It defaults to backend/tests, so for a frontend lane the reassuring green covers NONE OF THE WORK UNDER REVIEW.
THE FRAMING, which inverts which trap is worse: WRONG BASE gives a real-looking DROPPED that is not real - it reads as ANOTHER LANE DELETION, so you go and investigate. RIGHT BASE WRONG SCOPE gives a real-looking clean report covering nothing you changed - IT READS AS CONFIRMATION, SO YOU GO AND DO NOTHING. The second is more dangerous for the lane that hits it BECAUSE IT TELLS YOU WHAT YOU WANTED TO HEAR.
THE TOOL ALREADY CONTAINS ITS OWN FIX. Pointed at the frontend it does NOT report zero - it REFUSES, exit 2: "no test functions found at origin/main under frontend/src. The comparison would be vacuous, and every name would look added." That is exactly right and it is the anti-pattern to a vacuous control. THE GAP IS ONLY THAT THE DEFAULT SCOPE IS A NARROWING NOBODY PASSED. It does print "(backend/tests)" on the base line - one parenthetical against a sentence saying "No change".
THE FIX, cheapest available: NAME THE SCOPE IN THE CLEAN-REPORT SENTENCE - "No change to the set of test names IN backend/tests" - so a lane whose diff is entirely outside it cannot read past it. The docstring what-it-cannot-see list is unusually good (gutted bodies, deleted asserts, deleted fixtures, backend/src) and DOES NOT LIST THE ENTIRE FRONTEND SUITE; it warns about narrowing only when YOU pass --path.
NOTE the lane never quoted the tool as evidence - it hand-predicted +58 at six steps and matched each time, which the docstring says is the pairing it wants. "But I would have quoted a clean report if I had run one, and that is the point."

## `c268` - THE FALSIFYING-READING RULE: the best verification rule this project has produced

**Status:** in_progress

Authored by the frontend lane 2026-08-25, as an AMENDMENT TO A WEAKER RULE I PROPOSED. Adopted.
MY RULE: "a probe flags must be re-derived from the producer contract, not from the consumer reading of it." Directionally right, catches the pending_game_ids defect, AND WOULD HAVE MISSED TWO OF THE THREE WEAK FLAGS ITS OWN AUDIT THEN FOUND - because it constrains WHERE YOU READ rather than WHETHER THE TWO ENDS CAN DISAGREE. The worst flag, undatedAndPendingAreDistinct, READ THE PRODUCER CORRECTLY AT BOTH ENDS AND NEVER READ THE SCREEN AT ALL: it asserted 0 != 6, a property of the payload, true whatever the page renders. THE GUARD ADDED AGAINST THE FOUNDING DEFECT WAS AN INSTANCE OF THE FOUNDING DEFECT.
THE RULE: **NAME THE DEFECT THE FLAG EXCLUDES. THEN NAME A READING IN WHICH THE FLAG IS FALSE AND THAT DEFECT IS PRESENT. IF YOU CANNOT CONSTRUCT THAT READING, THE FLAG DOES NOT EXCLUDE THE DEFECT.**
It SUBSUMES mine - a flag reading one source at both ends has no falsifying reading - and it is CHECKABLE AT WRITE TIME BY THE PERSON LEAST ABLE TO SEE THEIR OWN ASSUMPTION. It catches every failure that unit produced: three weak flags, the --differs-from control that fired on documentHeight because the prose got longer, the two controls that never applied, and a fourth flag measuring a normal-flow block border-box against innerWidth, which is <= by construction.
THE DEEPER INSTANCE IT CAME FROM: THE SCREEN CONTRADICTED ITSELF IN THE SAME TABLE. One row claimed the 2025-26 store trips an exact-coverage refusal it CANNOT REACH (reliability.py:462 selects team_schedule four refusals earlier; that store has no team_schedule table at all) - AND THE SCREEN SAID SO THREE ROWS BELOW. Nothing caught it because THE CHECKS WERE WRITTEN AGAINST THE READING THAT PRODUCED THE CONTRADICTION: the unit test required substrings "route" and "store", both present in the false sentence; the probe read the same cell for the same words; three review passes read the row without checking it against the backend control flow.
AND THE LANE HAD AN ENTRY DATED 2026-08-21 TITLED "Cardinality, which every previous fix compared its way past" - AND THEN WROTE Set.size == Set.size, where {59,60} passes against {70,80}. KNOWING A FAILURE MODE BY NAME DID NOT STOP IT REACHING FOR THE FAILURE MODE.

## `c269` - The reliability screen asserts a mechanism that is false, and a test pins it

**Status:** pending

LIVE ON MAIN at d34e934, merged in PR 98. Driven by me against the real store 2026-08-25, read-only.
THE SCREEN SAYS the 2025-26 participation store has "no team_schedule table at all". THE TABLE EXISTS. Driven: C:\\Users\\steverones\\hoops-gm-data\\hoops_gm.db has 33 TABLES INCLUDING team_schedule, leagues, refresh_runs, scoring_periods, source_games_played_assumptions. The frontend lane reported it held "nba_games, player_game_logs, player_participation, players, nba_teams AND NOTHING ELSE".
ROW COUNTS, which is where the truth is: player_participation 43,037 (confirms it IS the ledger); team_schedule EXISTS WITH 0 ROWS; nba_games 1,230, ALL season 2025-26, ALL status=final; refresh_runs 0; leagues 0; scoring_periods 0.
SO THE REFUSAL IT ACTUALLY HITS IS THE EMPTY CHECK AT reliability.py:476, NOT A MISSING-TABLE ERROR. The lane own distinction applies to itself: it argued that "blocked on exact coverage" describes a schedule present and partial while "no such table" describes an ingest that never ran. The truth is a THIRD state - SCHEMA PRESENT, ZERO ROWS - which is an ingest that never ran, so its CHARACTERISATION IS RIGHT AND ITS MECHANISM IS WRONG.
THIRD TIME TODAY: right conclusion, wrong mechanism. And this one is PINNED BY A TEST written specifically to prevent the previous wrong sentence - the fix for a false mechanism asserted a different false mechanism, and the test defends it.
ITS OWN COULD-NOT-VERIFY RESOLVES IN THE GOOD DIRECTION: it could not check whether the ledger also lacked 2025-26 FINAL nba_games rows. IT HAS 1,230. So two of the three join inputs are present and only team_schedule and refresh_runs are empty.
FIX: correct the screen sentence and the pinning test to say the table is present and empty, and name reliability.py:476 rather than a missing table.

## `c270` - scripts/ is type-checked but NOT linted, and barely tested

**Status:** pending

ARCHITECT FINDING 2026-08-26, driven by me on main at 28d0d88. THE CALIBRATION LANE CLAIMED "no CI job lints, type-checks or runs scripts/ at all". OVERSTATED, AND I AM CORRECTING IT - the precise version is more useful and the lane would want the same discipline applied to it.
DRIVEN: backend/pyproject.toml [tool.mypy] has files = ["src", "tests", "../scripts"], with a comment saying ../scripts is outside the package ON PURPOSE. SO MYPY DOES COVER scripts/, DELIBERATELY. But [tool.ruff] has src = ["src", "tests"], and every Python CI job declares working-directory: backend and runs "ruff check ." - which never sees ../scripts. pytest likewise runs from backend, so scripts are tested ONLY where a lane wrote the test into backend/tests/.
PRECISE STATE: TYPE-CHECKED YES (deliberately). LINTED NO. TESTED ONLY INCIDENTALLY.
WHY IT MATTERS: scripts/ holds FIFTEEN files and they are THE ENTIRE VERIFICATION TOOLCHAIN - predict_union.py, test_name_diff.py, manifest_leaf_diff.py, check_no_secrets.py, resolve_doc_conflicts.py, backlog_graph.py, cohort_predictor_crosses.py, three mutation harnesses, plus browser_probe.mjs and reliability_probe.js which are JavaScript outside the frontend job so NO gate touches them at all. THE TOOLS THIS PROJECT USES TO CATCH ITS OWN DEFECTS ARE THE CODE LEAST GATED, and several backlog items cite mutation-harness output as their evidence.
NOT FIXED: adding scripts/ to ruff would touch files owned by four lanes. Backend-owned per ownership.md:26, wants its own unit, JS files considered separately.

## `c271` - A gate quoted without its working directory is unquotable

**Status:** done

Found by the calibration lane 2026-08-26. BOTH DIRECTIONS FAIL. Every Python job in ci.yml declares working-directory: backend (or frontend/userscript).
FALSE PASS: the lane reported mypy clean from "mypy src" (121 files) while the gate CI runs is BARE mypy (195 files, tests included). Under the real command its branch had FIVE ERRORS and would have failed CI. gates.md ALREADY RECORDS THIS EXACT SHAPE BY NAME - mypy --strict on a script reported strict-clean while eighteen unannotated test functions sat outside the path. SECOND INSTANCE OF A DOCUMENTED FAILURE MODE.
FALSE ALARM, the worse half and the one nobody had considered: run from the REPOSITORY ROOT the same commands report 15 lint errors and 13 unformatted files. From backend, clean. ACTING ON IT WOULD HAVE HAD THE LANE EDITING THREE OTHER LANES FILES DURING A MERGE FREEZE ON THE STRENGTH OF A NUMBER THAT WAS NEVER ITS TO READ. Same shape as the local-main phantom: A FALSE READING THAT PRESENTS AS SOMEBODY ELSE PROBLEM IS WORSE THAN ONE THAT PRESENTS AS YOUR OWN.
RULE ADOPTED: quote a gate with its working directory AND its file count. Neither alone is quotable.

## `c272` - A test added to the module a mutation harness targets weakens it invisibly

**Status:** blocked

PROVISIONAL. The calibration lane asked that this be disbelieved until its sixth review pass reports, on the explicit grounds that "I nearly shipped something catastrophic and caught it myself" is a flattering story it has an interest in reading well. HONOURING THAT.
THE NEAR-MISS: the obvious repair for stale mutation anchors is to assert the anchors in tests. It wrote four and put them in test_calibration_machinery.py - THE MODULE THE HARNESS RUNS. While a mutation is applied the mutated line no longer matches its own anchor, so the anchor test fails, AND THE HARNESS SCORES ANY FAILURE AS CAUGHT. Every mutation of calibration.py would have been marked caught by the ANCHOR test rather than the detector it exists to exercise, and the harness would have printed "44 caught, 0 survived" WHILE ESTABLISHING NOTHING.
Driven not reasoned: with M02 applied the anchor assertion fails "anchor found 0 times". Moved to backend/tests/test_mutation_harness_integrity.py, which the harness never runs and CI always does.
GENERALISATION: the false-zero shape in its most expensive location so far. NOT a detector that fails to fire, but A DETECTOR FIRING SO RELIABLY THAT IT DROWNS OUT THE ONES BEING MEASURED, WITH THE VISIBLE SYMPTOM BEING THE REASSURING NUMBER.
AND IT CAUGHT ITS OWN AUTHOR: of five anchor pathologies driven, one PASSED at first - the payload prefixed a comment without removing the tuple, so len(MUTATIONS) never changed. A DRIVER FAILURE WEARING A DETECTOR RESULT.
SEPARATE AND NOT PROVISIONAL: delattr CANNOT MODEL "this method was never defined" on a heap type. The lane and its reviewer built counterfactual matrices with it for a CPython slot question and GOT TWO DIFFERENT WRONG ANSWERS. The sound experiment builds a fresh type(...) per cell.

## `c273` - The catcher audit is a conclusion with no mechanism, and it has gone stale

**Status:** pending

LIVE ON MAIN at 28d0d88. Reported by the calibration lane against itself; VERIFIED BY ME.
DRIVEN: scripts/mutate_calibration.py defines 55 tuple entries. docs/handoff.md asserts, present tense, "ZERO FALSE CATCHES" and "19 OF THE 44 MUTATIONS ARE PINNED BY EXACTLY ONE TEST". THIRTEEN MUTATIONS WERE ADDED AFTER THAT AUDIT AND NONE HAS EVER BEEN CHECKED for a false catch or for single-pinning. The audit itself was a THROWAWAY THE LANE DELETED - git grep catcher on main returns three docs and ZERO scripts.
SO MAIN CARRIES A PRECISE, REPRODUCIBLE-SOUNDING COUNT ABOUT A SET THAT CHANGED UNDERNEATH IT, AND NOTHING ANYWHERE WOULD NOTICE. That is EXACTLY the FLOW_SCAN_LIMIT defect (c270 area) in a second unit on the same day: THE NUMBER MADE THE CLAIM LOOK CHECKED.
THE FIX, and it is the lane own reviewer recommendation which the lane declined under the freeze: MAKE THE AUDIT A HARNESS MODE rather than a throwaway. Its reviewer said declining was "right for the commit and wrong as a standing position", and the lane agrees it under-weighted this. THE COST IS A REPORTING-PATH CHANGE THAT CANNOT ALTER A VERDICT. The lane words: "if one thing survives this session, it should be that."
NOTE ON HOW TO FIX IT: docs/handoff.md is APPEND-ONLY, so the dated entries are NOT to be edited - append a correction. The model card and backlog carry the claim where it can be corrected in place.

## `c274` - Ten of ten MECHANISMS are pinned; an unknown number of RATIONALES are not

**Status:** pending

The calibration lane conceding the specific way its own audit is incomplete, rather than claiming closure. Worth handing to whoever fits the model.
D01-D07 PIN BEHAVIOUR, NOT RATIONALE. wilson_interval declared "the narrower, stricter arm" is TWO CLAIMS: that no continuity correction is applied, and that this is the STRICTER DIRECTION. D01 MUTATES THE FIRST. NOTHING MUTATES THE SECOND. If the strictness claim were backwards, EVERY ONE OF THE TEN TWINS WOULD STILL PASS.
The lane had already proved the second kind of claim is testable - for a DIFFERENT convention it took the narrower Wilson arm against its own interest and then wrote a test for the DIRECTION rather than asserting it. So it knows the technique and applied it to one convention and not the rest.
HONEST STATE: ten of ten mechanisms pinned; an unknown number of rationales unpinned; AND THE RATIONALE IS THE PART THAT DECIDES WHETHER THE CONVENTION SHOULD BE WHAT IT IS.
This is the architect concern stated back precisely: the risk is not a convention that is WRONG, it is one that is RIGHT WHILE ITS STATED MECHANISM IS NOT - and an assertion protects the sentence without protecting its truth.

## `c275` - Two driver-failures wearing detector results is a class, not an anecdote

**Status:** pending

Second instance recorded by the calibration lane 2026-08-26. The model card records the FIRST (a mutation payload that never applied, so the suite passed and it nearly logged that as evidence a test could not detect a regression). THE SECOND: its W03 driver RENAMED a mutation instead of DUPLICATING one, so the duplicate-content case reported SURVIVED and it nearly recorded a hole that did not exist.
THE GENERALISATION, not in the repo: A DRIVER FAILURE AND A REAL SURVIVOR PRODUCE IDENTICAL OUTPUT, SO EVERY *SURVIVED* NEEDS ITS PAYLOAD CONFIRMED TO HAVE APPLIED - the same way every CAUGHT needs the mutation confirmed present in the file before the run is read. Both directions, not one.
ALSO NOWHERE, from the same session: A FALSE ZERO IN A THREE-LINE REGEX. Counting conflict markers gave 1 start / 0 dividers / 1 end. The zero was ^=======\\s*?$ under CRLF, where $ sits before \\n and the \\r defeats the match; the start and end patterns are PREFIX matches with a trailing space and were immune. THE TWO PATTERNS THAT COULD NOT FAIL AGREED, AND THE ONLY ONE THAT COULD, FAILED SILENTLY. Caught only because 1/0/1 is structurally impossible - a two-conflict file reporting 2/1/2 would have looked perfect.
THE LESSON IS NARROWER AND NASTIER THAN "test your regex": WHEN A CHECK HAS ONE FRAGILE ARM AND TWO ROBUST ONES, AGREEMENT AMONG THE ROBUST ARMS IS NOT EVIDENCE ABOUT THE FRAGILE ONE.

## `c276` - OWNER CONFIRMED: draft-tracker bridge feed is wanted

**Status:** done

2026-08-26. Owner: "that lane two work is a critical omission. It is definitely something I would want, and the reason you do not know that is I have not sat down to write the one pager you asked me for yet. So that is on me."
FIRST DIRECT CONFIRMATION OF A LANE CHOICE. Of four lanes I picked on my own judgement today, ONE was confirmed and ONE was corrected - roughly a 50% hit rate on my judgement standing in for his, which is what the draft-day page exists to fix. Cost is not that work stops without the page; it is that I keep spending days on my guess.
THE PRESSURE POINT IN HIS TERMS, which is what made it land: 7:14pm on 18 October, someone takes Jokic, and he is doing DATA ENTRY WHILE A CLOCK RUNS AND ELEVEN OTHER PEOPLE MOVE. He cannot think about value while he is being a keyboard.

## `c277` - CORRECTION: projection profile verification is not mainly about name collisions

**Status:** in_progress

2026-08-26. MY FRAMING WAS WRONG AND THE OWNER CAUGHT IT. I described the unit to him as mostly identity - "which Steven Adams is this row" - and he reasonably asked whether it only matters on a name collision.
IDENTITY IS THE SMALLER HALF. THE LARGER HALF HAS NO COLLISION IN IT AT ALL: a vendor projection set is built for a PARTICULAR SCORING FORMAT and a PARTICULAR GAMES-PLAYED ASSUMPTION. Import believing 9-cat when the source assumed 8-cat, or believing injury risk is already discounted when it is not, and EVERY DOLLAR VALUE IS WRONG WHILE EVERY NAME MATCHED PERFECTLY. R39 governs: normalise to this league budget pool, team count and roster size first.
OWNER GUIDANCE ON THE IDENTITY HALF, and the principle under it is sharper than his example: "find one or two other tiebreakers where their statistical differences should identify which one is which. ADP would work if nothing else." THE USEFUL TIEBREAKERS ARE THE ONES THE VENDOR DID NOT USE TO BUILD THE ROW - ADP, team, position, prior-season minutes. A tiebreaker derived from the same projection tells you nothing; that is the both-ends-inherit-one-misreading defect in a new costume. TWO AGREEING SOURCES THAT SHARE AN UPSTREAM ARE ONE SOURCE.
LANE INSTRUCTED to return a PLAN before building, per the owner explicit offer to be asked. Must state which vendor declarations are checkable against something INDEPENDENT and which are not - and if a scoring format cannot be verified against anything but its own claim, THAT IS THE FINDING, worth more than a check that assumes its own input.

## `c278` - CORRECTION: the portfolio gap is narrower than I told the owner

**Status:** pending

I told him at 09:23 that "nothing running builds a portfolio constructor" and "everything in the backlog ranks players". DRIVEN AGAINST origin/main AT 02ec617, THAT IS OVERSTATED. The precise version:
ALREADY SPECIFIED, and closer to his need than I said: (1) risk-adjusted-valuation - "Durability discount/premium layered over raw value. SEPARATE TOTAL-VALUE AND PER-GAME-VALUE VIEWS SO THE FRAGILE-STAR TRADEOFF IS EXPLICIT RATHER THAN HIDDEN IN ONE NUMBER." That is precisely his 60-games-of-X-vs-70-of-Y comparison refusing to collapse into a single figure. (2) punt-builds - "recomputed rankings per build, side-by-side comparison, and FIT-TO-MY-CURRENT-ROSTER SCORING. Operates on risk-adjusted values." That IS roster-shape awareness, already planned.
ALSO CORRECTED: draft-recommender is DEPRIORITISED - snake only, not a draft-day deliverable since auction was confirmed 2026-08-17. I have been calling it "the end of the chain" repeatedly. THE AUCTION-SIDE EQUIVALENT IS auction-nomination / auction-budget-manager / overlay-auction-panel.
GENUINELY ABSENT, and these are the three real gaps: (a) RISK CONCENTRATION - nothing can say "you already have three high-variance players, this is your fourth". Fit-to-roster in punt-builds is about category fit, not variance concentration. (b) IR SLOTS AS AN ASSET - and specifically the SECOND return the owner led with, STREAMING CAPACITY: an occupied IR slot frees an active roster slot. Nothing models either return. (c) VOLATILITY AS A TOGGLEABLE DIMENSION beside the nine categories, alongside a weighted games-played toggle. Two toggles, neither baked in, neither specified anywhere.
DO NOT SILENTLY RE-SCOPE NINE ITEMS. Bring the owner a proposal. Re-scoping the backlog on my own reading is the exact habit the draft-day page exists to break, and I would be doing it within an hour of the page landing.

## `c279` - BRIDGE: every captured payload is method-anonymous by construction

**Status:** pending

STRUCTURAL, found by the draft-tracker lane 2026-08-26, read off fantraxapi/api.py (a pinned working client) rather than inferred from a payload.
/fxpa/req IS A JSON-RPC BATCH. THE METHOD NAME IS IN THE *REQUEST* BODY - {"msgs":[{"method",...}]}. userscript/src/capture.js CAPTURES RESPONSES ONLY, never request bodies or headers. SO A CAPTURED RESPONSE IS UN-ATTRIBUTABLE TO A METHOD BY CONSTRUCTION - not by oversight, not fixably downstream.
leagueId IS on the query string and capture preserves the full URL, so LEAGUE attribution is real. Nothing saves METHOD attribution.
CONSEQUENCE: every payload this project has ever captured, or will capture under the current bridge, is method-anonymous. Any downstream code that believes it knows which RPC produced a blob is believing a guess. The draft-tracker lane responded correctly - its recogniser accepts a list only if EVERY record resolves to a fantrax_team_id already seated in this draft AND names a player, so a wrong guess yields ZERO records plus a visible unrecognised-shape count, NEVER A PICK ATTRIBUTED TO THE WRONG SEAT.
REMEDY: capture the request body, or at minimum the method name from it, alongside the response. BRIDGE-owned per ownership.md. Note bridge does not approve its own guardrails - safety reviews the write path, but this is the READ path so Code+Adapter applies.

## `c280` - OWNER ACTION: one mock draft with the userscript loaded

**Status:** pending

THE HIGHEST-VALUE THING THE OWNER CAN DO WITH HIS OWN HANDS BEFORE 18 OCTOBER, and no agent can do it for him.
WHY: NEITHER DRAFT FEED SOURCE HAS EVER SEEN A REAL DRAFT PAYLOAD. (1) getDraftPicks has never returned a successful real payload - stated independently in THREE existing places: docs/adapters/fantrax-official.md:4 and :261-263, the docstring of parse_draft_picks in ingest/fantrax_official/parsers.py ("Also never run against a real payload"), and docs/handoff.md:184. Its parser reads GUESSED key names with or-fallbacks: teamId or fantasyTeamId, round or roundNumber, amount/bid/salary. (2) It may not even be about draft RESULTS - fantraxapi 1.0.1 objs/trade.py models a "draft pick" as round + year + origOwnerTeam, A TRADEABLE FUTURE ASSET, not a selection that happened. UNVERIFIED AND UNVERIFIABLE in this environment: no league id, no FANTRAX_* vars, both .env files absent. NOT DISPROVED - UNESTABLISHED. (3) NO DRAFT-ROOM FIXTURE EXISTS ANYWHERE in backend/tests/fixtures.
SO: the feed may recognise NOTHING until a real draft payload is captured - first mock draft, or draft night. What the current unit CAN deliver is that the failure is LOUD AND DIAGNOSABLE IN MINUTES (status endpoint publishes unrecognised blocks top-level key names) rather than a calm empty board. What it CANNOT deliver is a demonstrated live feed.
ONE MOCK DRAFT WITH THE USERSCRIPT LOADED CONVERTS EVERY GUESS IN THAT UNIT INTO A FIXTURE. Lane instructed to state precisely what he would need to do - which pages, whether any league works or it must be his, roughly how long - because a vague ask gets deferred and a specific one gets done.

## `c281` - RULE REPLACED: byte-prefix check, not numstat zero-removed

**Status:** done

I HAVE NOW GIVEN EVERY LANE A WRONG VERSION OF THIS RULE TWICE. Corrected 2026-08-26 by the reliability lane, driven by me.
VERSION 1 (c239): "run numstat and confirm zero removed" - unqualified, so run BEFORE rebasing it manufactures phantom removals. One lane saw 302, all imaginary.
VERSION 2, todays: "origin/main now ends with a trailing newline, expect 0 REMOVED, and 1 is new." BOTH HALVES FALSE, AND I CREATED THE CONDITION MYSELF. Driven: 28d0d88 bytes=1655587 endsWithNewline=TRUE; my commit 02ec617 bytes=1658934 endsWithNewline=FALSE. My draft-day entry ended "question 15." with nothing after it, so a clean 63-added/0-removed append REMOVED THE TRAILING NEWLINE. Then in the same hour I told a lane that 1-removed would be suspicious.
THE ROOT PROBLEM: "0 removed" IS A PROXY FOR APPEND-ONLY, and it fails exactly when the base lacks a trailing newline - a condition any lane can create by accident, as I proved.
THE REPLACEMENT, from that lane: GIT SHOW origin/main:docs/handoff.md IS A BYTE-PREFIX OF THE COMMITTED BLOB. One command, tests the property directly rather than a proxy, no blind spot, AND unlike the entry count it also catches a SWAPPED entry.
KEEP ITS CAVEAT, which it found in its own version: normalising line endings before comparing made the check return True on a commit that rewrote all 25,410 lines CRLF->LF. A PREFIX CHECK ON NORMALISED BYTES PROVES APPEND-ONLY CONTENT, NOT AN APPEND-ONLY COMMIT. State both. (docs/handoff.md is now all-LF, 0 CRLF / 25,278 LF, and that flip predates today.)
GOES IN EVERY FUTURE LANE BRIEF, replacing the numstat instruction.

## `c282` - A name collision inside our own model: volatility of production vs availability

**Status:** pending

Found by the reliability lane 2026-08-26, and it is the trap the NEXT lane will hit first.
The owner asked for VOLATILITY OF AVAILABILITY as a toggleable dimension - whether a player 60 games arrive in a rhythm or around one long absence. THAT DOES NOT EXIST. AvailabilityEvidence carries exactly overall, monthly_trend, back_to_back; a search of reliability.py for streak/gap/run-length/consecutive/interval/clump returns NOTHING. monthly_trend is a month-granularity proxy that CANNOT separate two 10-game absences inside one month from ten scattered ones. The lane built no proxy, correctly.
THE TRAP: MinutesConsistency.coefficient_of_variation EXISTS and is VOLATILITY OF PRODUCTION - how much his minutes move on nights he PLAYS. DIFFERENT QUESTION, SIMILAR NAME. A lane that finds it and stops has answered the wrong question WITH A REAL NUMBER, which is the hardest kind of wrong to notice.
Same shape as gameEt at model scope: a self-describing name that means two different things inside one package. Whoever builds the volatility toggle must state which volatility in the field name, not in a docstring.

## `c283` - ARCHITECTURE: six source files are frozen by the injury cohort manifest

**Status:** pending

Found 2026-08-26 when PR #105 turned two gates red at once. ARCHITECT-OWNED, not the lanes.
docs/adapters/nba-injury-report-cohort-2025-10-21--2026-04-12.json fingerprints SIX source files under operator.source_fingerprints: db/lineage.py, ingest/backfill.py, ingest/injury_report/backfill.py, ingest/injury_report/cohort_evidence.py, ingest/injury_report/merge_stores.py, ingest/nba/parsers.py.
CONSEQUENCE: ANY edit to any of those six invalidates the committed cohort evidence and fails BOTH the Adapter gate and test_cohort_evidence. db/lineage.py is a GENERAL-PURPOSE lineage primitive with nothing injury-specific about it, yet it is pinned by the injury cohort provenance. A backend lane improving a DB primitive cannot know it is touching the artifact the entire draft-day critical path rests on.
THE FINGERPRINT IS RIGHT IN PRINCIPLE AND POSSIBLY WRONG IN SCOPE: the claim it protects is "this code produced these numbers", which is the same class as the gameEt mislabelling the project cares about. But it conflates "code that produced this" with "code that COULD change this". lineage.py changing does not necessarily move any cohort number.
RESOLUTION FOR #105 (ruled 2026-08-26): REGENERATE, do not revert and do not loosen. operator.manifest_is_a_pure_function_of_persisted_state is TRUE, so regeneration needs the two local stores and NOT a live archive sweep. AND THE REGENERATION IS ITSELF THE TEST - byte-identical numbers prove the lineage change did not touch the cohort; any moved number is a real finding that must surface before availability-model consumes it.
OPEN QUESTION I OWN: is the fingerprint set drawn at the right boundary? Deferred, not dropped. Does not block #105.

## `c284` - CRITICAL PATH RE-DERIVED 2026-08-26: 9 sequential, 19 not-done, and the arithmetic veto is GONE

**Status:** done

Recomputed from the backlog dependency graph, not recalled. Backlog header honest: 54 done / 1 blocked / 89 pending / 144 total, and 144 == the ### heading count.
SPINE CLOSURE: 51 items, 19 NOT DONE. CRITICAL PATH to overlay-auction-panel (the screen he uses live) is 9 STRICTLY SEQUENTIAL items: injury-status-conversion -> availability-model -> expected-games -> zscore-engine -> gscore-engine -> risk-adjusted-valuation -> auction-values -> auction-budget-manager -> overlay-auction-panel. The other 10 parallelise.
I TOLD THE OWNER "NINE SEQUENTIAL ITEMS" AND GAVE ONLY THE FLATTERING HALF. Corrected to him 2026-08-26.
THE HEAD OF THE CHAIN IS NO LONGER VETOED. The old blocker was arithmetic: activation needs 30 held-out direct outcomes PER STATUS and the 2025-12-08..2026-01-04 cohort had doubtful=21, so 21<30 unconditionally. CLEARED 2026-08-23 by data-engineer: the widened cohort covers the full 2025-26 regular season, 164 game dates, 1227 games, section_2_admissibility.admissible=TRUE, held-out doubtful 83 / probable 92 / questionable 335 / available 467 / out 2963, all clear of the floor of 30. Evidence on main at docs/adapters/nba-injury-report-cohort-admissibility-2025-26.json.
WHAT NOW GATES ALL NINE: deriving the status x outcome contingency IS THE UNBLIND, one-shot under the freeze, so it needs the owner to bind or decline preregistration v3 first. That is the single owner-only decision on the critical path.

## `c285` - The widened holdout is the wrong regime, twice over, and both are disclosed pre-unblind

**Status:** pending

From docs/adapters/nba-injury-report-cohort-admissibility-2025-26.json, limitations_that_the_count_cannot_see. Verbatim to the model card per the artifact own instruction.
(1) SEASON REGIME: held_out is 2026-03-02..2026-04-12 - end-of-season shutdowns, seeding races, pre-playoff load management. The tool is used from draft day onward, weighted Oct-Mar. v1 holdout was late December, mid-season and unremarkable, SO WIDENING DID NOT MERELY MAKE THE HOLDOUT BIGGER, IT SILENTLY CHANGED ITS CHARACTER. "Widen the cohort is satisfied without being met, and NO COUNT DISTINGUISHES THE TWO OUTCOMES." That is the falsifying-reading rule applied to a cohort rather than a flag.
(2) REPORTING-ERA REGIME: era_composition_by_partition shows development legacy_hourly 4166 / short_lead 1946, but selection legacy 0 / short_lead 3546 and held_out legacy 0 / short_lead 3940. THE MODEL WOULD BE FITTED SUBSTANTIALLY ON A REPORTING REGIME THE HOLDOUT CONTAINS NONE OF.
Boundaries deliberately NOT moved, by owner ruling, because choosing different proportions BECAUSE these are inconvenient is the trap section 4 already names. Section 7 permits ONE evaluation.
v3 PROPOSED would register (2) as a section 7 sensitivity and add calibration on informative statuses as an ACTIVATION GATE. If declined: both analyses still happen but post-hoc, and the calibration one stops being a brake and becomes a footnote - a model badly calibrated on questionable could pass v2 section 8 and activate. Declining costs NO schedule.

## `c286` - RETRACTED AND FALSE: the review-artifact gap never existed - my query was broken

**Status:** done

FILED 2026-08-26 AND RETRACTED THE SAME DAY. I accused all four lanes of a systemic governance gap. THE GAP WAS MY QUERY.
WHAT I CLAIMED: gh pr view N --json reviews returns EMPTY for #104, #105, #106 AND #107, so every lane reported an independent review and none exists as an artifact anyone else can read. I sent this to all four lanes, twice, and told them to fix it before claiming green.
THE MECHANISM, found by the draft-tracker lane: GITHUB WILL NOT LET AN ACCOUNT SUBMIT A FORMAL REVIEW ON ITS OWN PULL REQUEST. Every PR here is authored by SR2501, the same identity the agents act under. SO --json reviews IS STRUCTURALLY EMPTY FOR EVERY LANE AND ALWAYS WILL BE. It is not that they failed to post; THE API FORBIDS THE OBJECT I WAS QUERYING.
DRIVEN: all four PRs return comments=1, each an independent review with the head SHA it was read at. #104 id=5427802563, 5835 bytes, three rounds at 2bf5a0c/2e06c89/eb31a7a. #105, #106, #107 likewise.
THE PART THAT INDICTS ME MOST: I RAN A POSITIVE CONTROL AND RAN IT ON THE WRONG QUERY. I cited the projection lane --json COMMENTS returning non-zero as proof the other lanes --json REVIEWS zeros were real. A control on a DIFFERENT QUERY than the one under test validates nothing. I have preached "positive-control the extractor before believing a zero" to four lanes today and then committed the subtlest possible version of it while teaching it.
CORRECT QUERY: gh api repos/O/R/issues/N/comments, or gh pr view N --json comments. NEVER --json reviews for agent-authored PRs.
WHAT SURVIVES: nothing. The reviews were posted, dated, and SHA-stamped before I complained. The only real action is to fix the gate documentation to name the right query so the next coordinator does not repeat this.

## `c287` - MERGE TRAP IN MY OWN PROCESS: mergeStateStatus=CLEAN does not mean green

**Status:** pending

Caught 2026-08-26 on PR #105, and I nearly merged on it.
After the lane pushed a fix, gh pr list reported #105 as MERGEABLE/CLEAN. I read that as "all gates pass". It is not what it means. gh pr checks 105 then returned "no checks reported on the sr2501-reliability-endpoint branch" - CI HAD NOT STARTED ON THE NEW HEAD AT ALL.
CLEAN means no conflicts and no FAILING required checks. A PR with ZERO checks satisfies that trivially. SO A PR WHOSE CI HAS NOT STARTED AND A PR THAT PASSED EVERY GATE ARE INDISTINGUISHABLE BY mergeStateStatus, and the not-started one looks BETTER than the mid-run one, which reports UNSTABLE.
This is precisely the falsifying-reading rule turned on my own instrument: name the defect the flag excludes (a red gate), then name a reading in which the flag is CLEAN and a red gate is present (checks never ran, gate would be red when it does). The reading exists, so CLEAN does not exclude the defect.
RULE: NEVER MERGE ON mergeStateStatus. Require gh pr checks to ENUMERATE the expected gates and show them passing. An empty or short check list is a RED FLAG, not a green one.
SECOND-ORDER CATCH FROM THE SAME MINUTE: I piped gh pr checks to Measure-Object -Line and got "total check lines: 1", which I briefly read as a check count. It was counting the ONE LINE OF ERROR TEXT. Counting the lines of a failure message and calling it a result is the same class of error, committed while investigating the first one.

CONFIRMED TWICE 2026-08-26, AND IT IS WORSE THAN A ONE-OFF. #105 at ab633c7 and #106 at d13f874 BOTH showed MERGEABLE/CLEAN with NO CI RUN ON THE CURRENT HEAD. For #106 the rebase push did not trigger the CI workflow at all - CodeQL fired on the pull_request event, CI did not - so gh pr checks returned 4 rows, ALL CodeQL, all passing. Every gate that matters (backend lint/type/tests, Postgres suite, Adapter gate, migrations, frontend, userscript, backlog-deps, no-secrets) had NEVER SEEN THE REBASED TREE.
I HAVE BEEN TREATING MERGEABLE/CLEAN AS THE MERGE SIGNAL ALL WEEK. I do not know that I merged an earlier PR on a false green, and I equally CANNOT CLAIM I DID NOT. That check was mine to build and I did not build it.
RULE: never merge on mergeStateStatus. Require gh pr checks to ENUMERATE the expected gates ON THE EXACT HEAD SHA. Report the COUNT AND THE NAMES - "4 rows all CodeQL" and "15 rows including the Adapter gate" both read as green in a summary and only one is.
COMPANION TRAP FOUND IN THE SAME INVESTIGATION: gh api repos/O/R/actions/runs?head_sha=SHORTSHA SILENTLY RETURNS EMPTY. I concluded "no CI runs exist for any head" and was about to report it. Caught only by running the identical query against 02ec617 full SHA, which I knew was good. ALWAYS USE FULL SHAs, and positive-control the extractor before believing a zero.

## `c288` - OPEN DEFECT ON MAIN (latent, pinned): record_refresh relabels lineage source in place

**Status:** pending

Left deliberately open 2026-08-26 by the reliability lane, with my agreement AFTER I ruled wrongly against it.
THE DEFECT: db/lineage.py record_refresh, when an existing row matches on artifact_type+key+version, does existing.source = source. Two producers that AGREE on content and DISAGREE on source collide on one row because schedule_content_version does not include source. Last writer wins and THE TRUE PROVENANCE IS GONE, NOT AMBIGUOUS - one row that answers "where did this come from" and it lies.
WHY IT IS NOT FIXED: fixing lineage.py invalidates docs/adapters/nba-injury-report-cohort-2025-10-21--2026-04-12.json, which fingerprints that file. Repair = regenerate, which needs live stats.nba.com sweeps to rebuild stores this lane does not hold, AND the manifest is data-engineer's artifact under the Adapter gate. A backend lane regenerating it to unblock its own PR is a boundary violation.
WHY IT IS SAFE FOR NOW: the lane also reverted import_schedule(source=...), the change that ACTIVATED it. Signature confirmed back to (session, parsed). Only one source value is possible for SCHEDULE again, so the defect is LATENT, exactly as before the PR. The publisher additionally skips deriving when a real cohort is current.
HOW IT IS PINNED: test_record_refresh_still_relabels_which_is_why_the_publisher_skips at backend/tests/test_publish_reliability_evidence.py:419, plus a docstring saying DO NOT REMOVE THIS SKIP on the assumption the primitive is safe. A TEST WHOSE NAME ASSERTS A BUG IS STILL PRESENT survives archiving and fails loudly if someone deletes the symptom.
TRIGGER TO FIX: whenever the injury cohort manifest is next regenerated by data-engineer for its own reasons, fix lineage.py in the same change. OWNER: data-engineer + backend jointly. DO NOT fix it standalone.

## `c289` - MY RULING WAS WRONG: I read a pure-function claim and skipped who could run it

**Status:** done

2026-08-26, PR #105. I ruled "regenerate the manifest, do not revert, do not loosen - the regeneration is itself the test." The lane reverted instead and was right.
MY ERROR, PRECISELY: I read operator.manifest_is_a_pure_function_of_persisted_state = true and concluded regeneration needs no network. THE CLAIM IS TRUE AND DOES NOT SAY WHAT I USED IT FOR. Pure-function-of-persisted-state means GIVEN THE STORES the manifest is deterministic. It is silent on whether THIS LANE HOLDS THOSE STORES - and the operator.commands I read IN THE SAME BREATH are full live backfills against stats.nba.com, which is what rebuilding them costs. I had both facts on screen simultaneously and used only the convenient one.
THE SECOND HALF WAS MINE TO CATCH AND I RULED PAST IT: that manifest is data-engineer's artifact under the Adapter gate. A backend lane regenerating the injury cohort to unblock its own PR is a BOUNDARY VIOLATION - and boundaries are the thing I own. I ruled a lane into crossing a line that is my job to hold.
PATTERN: this is the same shape as the numstat rule and the store-refusal mechanism - RIGHT-SOUNDING CONCLUSION FROM A REAL ARTIFACT, WRONG BECAUSE I DID NOT ASK WHO WOULD EXECUTE IT. Three instances today. The lanes have corrected me five times and I have corrected them twice.

## `c290` - THE APPEND-ONLY RULE, v5 FINAL: blob-to-blob, AGAINST THE MERGE-BASE

**Status:** done

Corrected three times on 2026-08-26, by three different lanes, all driven.
v1 (mine, c239): "numstat shows 0 removed" - unqualified, so run before rebasing it manufactures phantom removals.
v2 (mine): "origin/main now ends with a trailing newline, expect 0 removed" - BOTH HALVES FALSE and I created the condition myself.
v3 (reliability lane): byte-prefix check instead of the numstat proxy. Right, but underspecified.
v4 (projection lane, FINAL): THE COMPARISON MUST BE BLOB-TO-BLOB. git show BASE:docs/handoff.md must be a byte-prefix of git show HEAD:docs/handoff.md. NEVER compare against the working file: on a Windows checkout the working file is CRLF and the blobs are LF, so it diverges at byte 13 and yields a GUARANTEED FALSE FAILURE. A false failure on an append-only check is worse than no check, because the lane that hits it concludes the check is noise and stops running it.
CAVEAT that survives (reliability lane, on its own version): if you normalise line endings before comparing, the check passes on a whole-file CRLF->LF rewrite. It proves append-only CONTENT, not an append-only COMMIT. Report both.
NOT A VIOLATION: a branch based on an older main is not a prefix of current main. Check against the branch OWN base.

v5 (reliability lane, 2026-08-26, FOURTH REVISION IN ONE DAY): THE REFERENCE MUST BE THE MERGE-BASE, NOT origin/main.
MECHANISM: the lane check compared docs/handoff.md against origin/main and reported containment FALSE WITH NO VIOLATION PRESENT. origin/main moved 02ec617 -> c07aefb when #106 merged, so main now carries entries this branch has never seen. A BRANCH FILE STOPS BEING A SUPERSET OF MAIN THE MOMENT MAIN APPENDS, WHICH HAS NOTHING TO DO WITH WHETHER THE BRANCH EDITED ANYTHING. It nearly reported an append-only breach against itself.
CORRECT FORM: git merge-base origin/main HEAD, then byte-prefix containment on THAT blob - the last tree both agree on, hence the only content this branch could have edited. Verified against 02ec617: +29,229 bytes, containment true, zero CR.
KEEP BOTH NEGATIVE CONTROLS: a one-byte flip in the base must FAIL; a truncated base PASSES VACUOUSLY, which is why both lengths must be printed.
WHY THIS MATTERS BEYOND CORRECTNESS: a check that emits a false breach the moment a PR outlives a merge TEACHES LANES TO IGNORE IT. That is worse than not having the check.
SAME FAMILY AS MY OWN RETRACTED --json reviews ERROR: a control run against a different thing than the subject. A REFERENCE THAT MOVES IS NOT THE SAME THING TWICE.

## `c291` - My missing trailing newline would have made the NEXT entry invisible to predict_union.py

**Status:** done

Found by the projection lane 2026-08-26; I had stated the newline was missing and NOT stated this consequence.
MECHANISM: origin/main:docs/handoff.md ends "...question 15." with no newline. A lane appending "## 2026-08-26..." lands its heading ON THE LAST LINE OF MY ENTRY. scripts/predict_union.py counts ^## \d{4}-\d{2}-\d{2} AT LINE START, so THE ENTRY BECOMES INVISIBLE TO THE COUNTER WHILE LOOKING PERFECT IN A DIFF. A silent undercount in the very instrument used to verify appends.
DRIVEN ACROSS ALL FOUR BRANCHES: NOTHING IS SWALLOWED. reliability prepended \n; verification-toolchain prepended \n\n---\n\n; both WITHOUT BEING TOLD. All four branches show exactly 290->291 headings and all four blobs end with a newline with 0 CRLF.
SELF-HEALS: whichever PR merges first restores the trailing newline permanently, so NO REPAIR COMMIT IS NEEDED - which is the right outcome, since a fix from me would have conflicted all four lanes to correct a defect I caused.
LESSON: I reported the defect and stopped at the defect. The lane that found the CONSEQUENCE is the one that made it actionable. Reporting a broken thing without tracing what reads it is half a finding.

## `c292` - ENVIRONMENT NOTE: collection is not execution

**Status:** pending

From the projection lane 2026-08-26, and it belongs with the -qq and working-directory traps.
It reported a live drift detector as verified on the strength of pytest --collect-only. COLLECTION PROVES THE TEST IS DISCOVERABLE AND IMPORTS CLEANLY. IT PROVES NOTHING RAN. The detector matched ZERO cells because its reconciliation loop had never executed once.
SAME FAMILY AS: -qq silently deleting the "N passed" line while exiting 0; quoting a gate without its working-directory so 15 lint errors read as clean; mergeStateStatus=CLEAN on a PR with zero checks. ALL FOUR PRODUCE A GREEN-LOOKING SIGNAL FROM A COMMAND THAT DID NOT DO THE THING.
The generalisation the lane put on it, which is the valuable half: ALL FIVE of its review findings were in work it had ALREADY QUOTED AS GREEN, and THREE WERE CHECKS THAT COULD NOT FAIL. A check that cannot fail is indistinguishable from a check that passed.

## `c293` - RULED: verified=True must split into hash_pinned vs live_contract_observed

**Status:** pending

Ruled 2026-08-26 for the projection lane. Not close.
Hashtag has NO CSV - it is an ASP.NET HTML table - so the BBM pattern of hashing a committed artefact does not transfer. The lane built a contract fixture plus offline contract test plus live smoke instead, which is strictly weaker evidence, and recorded that in the metadata IN CAPITALS.
ONE FIELD, TWO STRENGTHS IS THE gameEt SHAPE: a value that is well-formed, type-correct, and lying. AGENTS.md - validation of form cannot catch errors of meaning. A capitalised metadata note is documentation, and documentation is what the next consumer skips.
RULING: the distinction must live in the VALUE, not the prose. hash_pinned vs live_contract_observed, so a consumer that only trusts the strong form can express that in a COMPARISON rather than in a comment.
ALSO RULED: ADP stays as three-valued evidence OUTSIDE score_evidence. The owner guidance is that a useful tiebreaker is one the vendor did not already use; folding ADP into a score destroys the independence that makes it a check.
DEFERRED WITH A TRIGGER: nothing consumes outcome.verification. Whoever builds risk-adjusted-valuation must either consume it OR state in the model card that it deliberately does not. An unread field and a field nobody needs look identical.

## `c294` - I WAS RIGHT, WAS CORRECTED WRONGLY, ACCEPTED IT, AND THE LANE THEN CORRECTED ITSELF

**Status:** done

2026-08-26, PR #105. A four-step chain worth keeping whole.
(1) I ruled: regenerate the cohort manifest, do not revert - operator.manifest_is_a_pure_function_of_persisted_state is true, so no network needed, AND THE REGENERATION IS ITSELF THE TEST.
(2) The lane reverted and told me regeneration "requires live stats.nba.com calls", writing that into a docstring. I READ THE DOCSTRING, QUOTED IT BACK AS GROUNDS, AND RECORDED MY OWN RULING AS WRONG (c289).
(3) THE LANE THEN DROVE ITS OWN CLAIM AND FOUND IT FALSE. cohort_evidence refused only because --raw-root DEFAULTS TO backend/data/raw, WHICH DOES NOT EXIST. The captures are at C:\Users\steverones\hoops-gm-data\data\raw - 3,045 files, 53.8 MB. Pointed at it the generator runs OFFLINE, EXIT 0, all four reconciliation views agreeing. NO NETWORK.
(4) So my inference was sound and the REFUSAL REPORT WAS THE BROKEN INPUT.
LESSON, AND IT CUTS AT ME: I accepted a correction without driving it, from a lane that had correctly corrected me four times that day. A GOOD TRACK RECORD IS NOT EVIDENCE FOR THE NEXT CLAIM. I registered c289 as my own error and it was half wrong - feasibility was mine and correct; the boundary half was genuinely mine and genuinely missed.
THE EXPERIMENT I ASKED FOR WAS RUN AND IT WORKED. Control first: regenerating at an UNMODIFIED tree yields an EMPTY git diff, so the manifest is exactly reproducible and later movement is signal. Then with the fix: 1656 total leaves, EXACTLY 1 DIFFERING - the lineage.py fingerprint itself. Every cohort number byte-identical. Positive proof the lineage change does not reach the injury cohort.

## `c295` - THE GATE CANNOT SEE ENTITLEMENT: a manifest passes its own fingerprint check whoever ran it

**Status:** pending

Sharpening of c283, authored by the reliability lane 2026-08-26. This is the edge that makes the coupling a real architecture problem rather than an inconvenience.
A cohort manifest regenerated by the BACKEND lane PASSES ITS OWN FINGERPRINT CHECK BY CONSTRUCTION. The check compares the manifest against the tree that produced it, so IT IS GREEN WHOEVER RAN IT. Green says THE BYTES AGREE. It does not say THE RUNNER WAS ENTITLED TO REPUBLISH ANOTHER LANE ARTIFACT UNDER THE ADAPTER GATE - and NO GATE IN THIS REPOSITORY DISTINGUISHES THOSE TWO.
So the Adapter gate cannot see the thing that actually matters about the artifact it guards: provenance of the REGENERATION, as distinct from consistency of the RESULT. Same family as record_refresh losing provenance in place, one level up - the artifact is consistent and the question of who was allowed to produce it has no representation anywhere.
ARCHITECT-OWNED. Decide whether the fingerprint set is drawn at the right boundary AND whether an artifact should record the lane that regenerated it. Does not block anything today.

## `c296` - ENVIRONMENT: cohort_evidence --raw-root defaults to a path that does not exist

**Status:** pending

Found 2026-08-26. Will bite the data-engineer lane that next regenerates the injury cohort.
hoops_gm.ingest.injury_report.cohort_evidence defaults --raw-root to backend/data/raw. THAT DIRECTORY DOES NOT EXIST. The real captures are at C:\Users\steverones\hoops-gm-data\data\raw - 3,045 files, 53.8 MB - OUTSIDE EVERY CHECKOUT, the same class of location as the participation ledger at C:\Users\steverones\hoops-gm-data\hoops_gm.db that a ten-location search once missed.
CONSEQUENCE: the generator refuses, and THE REFUSAL READS AS "THE DATA IS MISSING" WHEN IT MEANS "THE DEFAULT POINTS SOMEWHERE ELSE". One lane already turned that refusal into a false docstring claim that regeneration needs live stats.nba.com calls, which then propagated to me and reversed a correct ruling.
PATTERN: THIS IS THE THIRD TIME A DEFAULT RELATIVE PATH ANCHORED TO A CHECKOUT ROOT HAS PRODUCED A CONFIDENT FALSE NEGATIVE. See also core/config.py:94 anchoring the default SQLite path per-checkout, which produced the 0-rows-in-player_participation claim.

## `c297` - ARCHITECTURE: docs/handoff.md is an O(n^2) merge bottleneck and it is the real throughput limit

**Status:** pending

Observed directly 2026-08-26 with four lanes in flight. ARCHITECT-OWNED. Proposal only - do NOT change mid-flight.
MECHANISM: every PR appends to ONE 1.66 MB file. So every merge conflicts EVERY other open PR, each of which must then rebase and re-run CI. With n lanes that is O(n^2) rebases, and CI is SERIALIZED - runs sit queued 16-34 minutes behind each other. Today: 4 PRs, each needing a fresh CI run after each rebase, each merge invalidating the other three. The lanes finished their work hours before the queue could absorb it.
SECOND COST, ALREADY PAID TWICE TODAY: the file is the single most conflict-prone artifact in the repo AND the one whose correctness is hardest to check - append-only-ness needed three rule revisions in one day (c290), and a missing trailing newline nearly made an entry invisible to predict_union.py (c291). The bottleneck and the fragility are the same file.
CANDIDATE FIX: one file per entry under docs/handoff/YYYY-MM-DD-owner-slug.md, with the index generated rather than written. Conflicts become IMPOSSIBLE rather than merely detectable, the byte-prefix check becomes unnecessary, and predict_union.py counts FILES instead of regex-matching headings at line start. Cost: changes an established convention, and 291 existing entries would either migrate or stay as an archive file.
DO NOT ACT TODAY. Changing the conflict-prone file while four lanes hold appends to it is the worst possible moment. Propose as an ADR when the queue is empty.

## `c298` - THE NON-EVENT RULE: failure with zero failed steps and CLEAN with zero runs are the same thing

**Status:** pending

Authored by the draft-tracker lane 2026-08-26, and it SUPERSEDES my c287, which was only half of it.
I found the GREEN-SIDE trap in the morning - mergeStateStatus=CLEAN on a PR whose gates never ran - built a rule against it, and then WALKED INTO THE RED-SIDE VERSION WITHIN THE HOUR. I ranked a lane last because its CI said conclusion=failure. Driven by that lane against the full 40-char SHA:
  run 32985169230, 2e06c89, conclusion=failure
  jobs with a runner assigned:  0/10
  jobs with any steps recorded: 0/10
  steps with conclusion=failure: 0
Ten of ten jobs had an EMPTY steps array and an EMPTY runner_name. The run queued 16 minutes and was evicted from a saturated pool. conclusion=failure is an artefact of mass cancellation; THERE IS NO GATE RESULT UNDERNEATH IT.
AND IT DISPROVED THE TWO OBVIOUS ALTERNATIVES RATHER THAN ASSERTING INFRASTRUCTURE: cancel-in-progress is innocent because the cancel at 15:43:06Z PREDATES the next commit eb31a7a at 15:52:52Z BY TEN MINUTES - the cancel precedes its own supposed cause. Not a timeout: ci.yml declares no timeout-minutes, default 360, and 16 is not 360. Plus repo-wide saturation across three branches in the same window.
THE RULE: neither mergeStateStatus NOR conclusion is a result. THE DISCRIMINATOR IS WHETHER ANY STEP EXISTS. "steps with conclusion=failure: 0" means nothing failed. "jobs with a runner assigned: 0/10" means nothing ran. Report failed-step counts, never the run conclusion.

## `c299` - ARCHITECTURE COST: my serialized merge train guarantees CI pool contention

**Status:** pending

Raised as a could-not-verify by the draft-tracker lane 2026-08-26 and it is MINE, not any lane's.
MECHANISM: four lanes, each PR triggering a TEN-JOB matrix. Every merge forces the other three to rebase; every rebase creates a NEW HEAD and therefore A NEW TEN-JOB RUN, into a pool that ALREADY EVICTED A RUN TODAY. My freeze makes it WORSE rather than better - serializing guarantees the rebases arrive one after another instead of being absorbed together.
SHARED CAUSE WITH c297: one docs/handoff.md that everyone appends to forces a rebase per merge, and each rebase costs a full ten-job CI run. THE CONFLICT BOTTLENECK AND THE CI BOTTLENECK ARE THE SAME DEFECT MEASURED IN DIFFERENT UNITS.
OBSERVED TODAY: all four lanes finished their work hours before the queue could absorb it. The binding constraint on throughput was NOT lane capacity, NOT review, and NOT correctness - it was rebase-triggered CI runs against a serialized pool.
NOT FIXABLE TODAY with four lanes holding appends. Candidates for the ADR: per-entry handoff files so no rebase is needed for the doc; a merge queue; or path-filtered CI so a docs-only rebase does not re-run ten jobs. THAT LAST ONE IS CHEAP AND WOULD HAVE SAVED MOST OF TODAY - the draft-tracker lane top commit is docs-only over a tested tree and still needs a full run.

## `c301` - ROUTED TO data-engineer AS A JOINT UNIT: fix record_refresh + regenerate the cohort manifest together

**Status:** pending

Ruled 2026-08-26 after the reliability lane enumerated the blast radius. Supersedes the standalone framing in c288.
THE ENUMERATION, by AST walk over resolved keywords rather than grep: EIGHT record_refresh call sites. SEVEN pass a compile-time constant, so the relabel CANNOT fire there - structural exclusion, not observation. The EIGHTH is ingest/importers.py:952, which takes source as a VARIABLE. Three import_schedule callers, exactly ONE passes a non-default source: dev/publish_reliability_evidence.py:335, ADDED BY PR #105.
THE LANE CHASED ITS OWN COUNTEREXAMPLE: calendar/scoring_periods.py:184 is ALSO RefreshArtifactType.SCHEDULE and would collide if the keys met. They cannot - scoring_period_artifact_key returns f"league-scoring-periods:{league_id}" against the literal "nba-schedule". DISJOINT NAMESPACES.
SO: the defect is LIVE, in EXACTLY ONE SCOPE, and PR #105 is the sole cause of that scope having two sources.
WHY NOT FIX THE PRIMITIVE IN #105: it edits a file fingerprinted by data-engineer's cohort manifest. Cost is trivial - the lane PROVED regeneration moves 1 leaf of 1,656 and it is the fingerprint of the changed file - BUT CHEAPNESS WAS NEVER THE OBJECTION. A manifest regenerated by backend passes its own fingerprint check BY CONSTRUCTION, and no gate distinguishes "the bytes agree" from "I was entitled to republish this."
TRIGGER: next time that manifest is regenerated by data-engineer for its own reasons, fix lineage.py in the same change.

## `c302` - RULED: turn the call-site enumeration into a TEST, because that is the hole that was actually open

**Status:** pending

2026-08-26. The reliability lane refused to over-claim and that refusal identified the real defect.
ITS WORDS: "This is a reachability result about today's call sites, not a safety result about the primitive. NOTHING - no guard, no type, no test - STOPS THE NEXT LANE ADDING A SECOND SOURCE TO ANY SCOPE AND RE-OPENING IT SILENTLY."
RULING: commit the AST walk it already wrote as a TEST asserting exactly ONE record_refresh call site passes a non-constant source, failing when a second appears. Converts "nothing stops the next lane" into "something does", costs almost nothing because the walk exists, and LIVES ENTIRELY INSIDE THE BACKEND BOUNDARY - no cohort regeneration, no data-engineer artifact, no Adapter gate.
WHY THIS IS THE RIGHT SHAPE: the primitive CANNOT distinguish a legitimate second producer from a relabel. THE CALL-SITE COUNT CAN, and the count is the thing that actually changed today. Pinning it makes the next expansion of the blast radius a DELIBERATE REVIEWED ACT rather than a silent one.
GENERAL FORM WORTH KEEPING: when a primitive cannot tell a legitimate use from a defect, PIN THE POPULATION OF USES INSTEAD.

## `c303` - WHEN THE NON-ZERO CASE DOES NOT EXIST, THE QUESTION IS UNANSWERABLE - report that, do not answer it

**Status:** pending

Authored by the projection lane 2026-08-26, sharpening my own retraction of c286 into something stronger than I had admitted.
I SAID: I ran the positive control on the wrong query. IT SAID: --json reviews HAD NO REACHABLE NON-EMPTY CASE AT ALL. Every PR in this repo is self-authored, GitHub refuses a self-review, so EVERY POSSIBLE INPUT RETURNS EMPTY. "It was not a control that happened to be on the wrong query - it was A QUERY WITH NO POSITIVE CASE IN EXISTENCE, which is the strongest form of the defect: A CHECK THAT CANNOT RETURN THE ANSWER IT IS LOOKING FOR."
A wrong control can in principle be re-pointed. A QUERY WITH NO REACHABLE POSITIVE CASE CANNOT BE CONTROLLED AT ALL, because the non-zero case does not exist to run it against.
THE RULE, which patches a hole in my existing one: the standing form is "before trusting a zero, run the same extraction against a case you know is non-zero." ITS SILENT FAILURE MODE IS THAT NO SUCH CASE EXISTS. In that situation the honest output is UNANSWERABLE, not ZERO. STOP AND REPORT THAT THE QUESTION CANNOT BE ANSWERED BY THIS INSTRUMENT.
Same family as Test-Path .git\rebase-merge in a worktree, which is structurally always False, and -qq deleting the "N passed" line.

## `c304` - ENVIRONMENT: a bulk edit silently re-points tests, and refusal tests are the ones at risk

**Status:** pending

From the projection lane 2026-08-26. Belongs beside "collection is not execution" and it is nastier.
It mechanically rewrote eight verified=True constructors. ONE OF THE EIGHT WAS A DELIBERATELY INVALID PROFILE, and the rewrite made it invalid FOR A DIFFERENT REASON THAN THE RULE IT IS NAMED FOR. It failed loudly ONLY BECAUSE the new rule happened to exist. HAD IT NOT, THE TEST WOULD HAVE KEPT PASSING FOR THE WRONG REASON AND LOOKED UNTOUCHED IN REVIEW.
WHY IT IS PARTICULARLY DANGEROUS: a diff of a mechanical rename looks like the safest change in the world, so it attracts the least review attention of any change type, while being able to silently invert what a test proves.
THE TESTS AT RISK ARE EXACTLY THOSE ASSERTING THAT SOMETHING IS REFUSED, because a refusal test passes whenever ANY refusal occurs - it rarely pins WHICH refusal. Same root as the reliability lane finding that a test named for a coverage check could only ever have reached a different error code.

## `c305` - VINDICATION OF THE AGENTS.md HOUSE RULE: stating the mechanism caught the author

**Status:** done

2026-08-26, projection lane, and it is the clearest evidence for the rule that anyone has produced.
It warned me that a missing trailing newline on docs/handoff.md would make the NEXT appended entry invisible to predict_union.py. ONE COMMIT LATER IT COMMITTED EXACTLY THAT DEFECT ITSELF - Add-Content -NoNewline stripped the trailing newline.
IT CAUGHT IT. Its words: "The reason it was caught is that I had written the mechanism down, SO MY BYTE-PREFIX SCRIPT ALREADY REPORTED endsWithNewline. Stating the mechanism is what converted my own rhetoric into something that could fail on me."
AGENTS.md says to state claims in the form that lets someone disprove them cheaply, and gives as its reason that this converts RHETORICAL CONVENIENCE into UNEXAMINED INHERITANCE - the kind that has a test. THIS IS THAT CONVERSION HAPPENING, AND THEN CATCHING ITS OWN AUTHOR. Not a slogan; a script field that existed because a mechanism had been written down rather than a warning.
STATUS: the hazard is CLOSED on main. c07aefb has docs/handoff.md at 1,675,787 bytes, ending with a newline, 0 CRLF, 291 dated headings. #106 merge healed it with no repair commit.

## `c306` - CONFIRMING A HAZARD IS NOT ESTABLISHING ITS CONSEQUENCE - my two false alarms today

**Status:** done

Phrase authored by the projection lane about itself 2026-08-26; it describes both of my false alarms exactly.
ALARM 1 - the review-artifact gap (c286). I confirmed the reviews WERE ABSENT FROM A QUERY and never asked WHETHER THE QUERY COULD SEE THEM. --json reviews is structurally empty for self-authored PRs. Four lanes accused, twice, of a governance failure that was my broken query.
ALARM 2 - the backlog auto-merge hazard, SAME DAY, WITHIN THE HOUR OF RETRACTING THE FIRST. A lane measured that docs/backlog.md auto-merges clean while its DERIVED header goes stale, and described it as SILENT with no cue to run the repair. I RELAYED IT TO #104 MID-REBASE AS URGENT. The lane retracted four minutes later: there is a CI job, scripts/backlog_graph.py:289 "header-disagrees-with-items", running on EVERY PR, emitting the exact disagreement with both numbers. I verified independently before relaying the retraction - the marker exists at that line and the gate ran green on #106.
BOTH ERRORS ARE THE SAME: I CHECKED THAT A DEFECT COULD OCCUR AND NEVER CHECKED WHETHER ANYTHING ALREADY CAUGHT IT. The lane caught its version in four minutes by going to close a could-not-verify it had just filed. I needed a lane to tell me, twice.
RULE: before escalating a hazard, RUN THE GREP FOR AN EXISTING GATE. It costs one command and it is the falsifying reading.
WHAT SURVIVES OF THE HAZARD: real but gated. A clean auto-merge CAN produce a header disagreeing with its body, because each side edits a different line - main a body marker, the branch the header. Measured: merged body done=56, merged header 55, clean merge, normal exit. resolve_doc_conflicts.py calls resolve_backlog() UNCONDITIONALLY and repairs it; the gate catches it if nobody runs it.

## `c307` - OPEN QUESTION, NO OWNER: which other derived values auto-merge clean without a gate?

**Status:** pending

Raised as a could-not-verify by the projection lane 2026-08-26, restated honestly after it retracted the larger claim.
WHAT IS KNOWN: docs/backlog.md has a recomputed header and IS gated by scripts/backlog_graph.py "header-disagrees-with-items" on every PR. That instance is closed.
WHAT IS NOT KNOWN: whether any OTHER derived value in the repo has the same exposure - a value computed from a file body, editable on a different line from its source, therefore able to auto-merge clean while becoming false. THE CLASS HAS NEVER BEEN SURVEYED. One instance found by re-checking a claim, not by looking for the class.
CANDIDATES NOBODY HAS CHECKED: the handoff dated-entry count used by predict_union.py; manifest leaf counts; model-card row counts; any count in a docstring.
FILED AS AN OPEN QUESTION RATHER THAN A FINDING, which is what it is. Cheap for anyone to start: find every number in a tracked file that is computed from that file body, then ask whether a gate recomputes it.

## `c308` - A CHECK THAT CAN SILENTLY INVERT: docs/demo.md sanity numbers are ungated

**Status:** pending

Found by the projection lane 2026-08-26 doing the survey I filed as an open question with no owner. OWNER: backend. Small, cheap, real.
docs/demo.md:225 states its own purpose: "Sanity numbers, so a wrong screen is obvious: 1,206 games published, 1,200 imported, 6 pending, 30 teams, 25 scoring periods, 2,400 team-games."
NOTHING TIES THOSE NUMBERS TO AN ACTUAL seed_demo RUN. Positive control on the same query: backlog.md appears in 42 places across tests, scripts and workflows; demo.md appears in ZERO. I then checked the test directly - backend/tests/test_seed_demo.py pins ONLY "len(schedule.json()[teams]) == 30". THE OTHER FIVE NUMBERS APPEAR NOWHERE IN ANY TEST.
WHY IT IS NASTIER THAN IT LOOKS, and this is the lane framing: THEIR STATED FUNCTION IS TO BE A CHECK. A user brings up the demo and compares. If the seed output drifts and these do not, the check does not merely stop working - IT INVERTS. A correct screen reads as wrong, or a wrong screen reads as right. A CHECK THAT CAN SILENTLY FLIP ITS ANSWER is a nastier member of the family than a check that cannot fail. AND THE DEMO IS THE OWNER ONLY VERIFICATION TOOL.
I CLOSED THE LANE OWN FALSIFYING READING, which it correctly refused to close itself: git log shows docs/demo.md:225 AND backend/src/hoops_gm/dev/seed_demo.py were BOTH last changed in THE SAME COMMIT 842a289 on 2026-08-23. So they were written together, nothing has drifted, THE NUMBERS ARE CORRECT TODAY and the exposure is PURELY PROSPECTIVE.
FIX: assert the five unpinned numbers in test_seed_demo.py so the doc cannot drift from the seeder. scripts/mutate_seed_demo.py already exists, so the mutation harness is there.

## `c309` - A FIX WHOSE REGRESSION BARRIER IS NOT AT THE DEFECT LOCATION IS A COVERAGE CHECK WEARING A MECHANISM CHECK NAME

**Status:** pending

Authored by the reliability lane 2026-08-26 about its own fix, after an independent review demonstrated it with a mutation table. The sharpest general form produced this week.
THE DEFECT IT FIXED: main() in publish_reliability_evidence.py printed "schedule_source": DERIVED_SOURCE as a HARD-CODED CONSTANT while the skip branch writes no schedule row, so the operator JSON announced a derived source while refresh_runs.source held nba_api:ScheduleLeagueV2. The gameEt shape in new code, on the exact path added to protect that provenance.
THE FIX WAS REAL. THE TESTS WERE NOT. Mutation table:
  restore "schedule_source": DERIVED_SOURCE verbatim in main()  -> ALL 23 TESTS PASSED
  branch-derived constant (DERIVED if derived else "nba_api:...") -> ALL 12 TESTS PASSED
TWO SEPARATE REASONS, BOTH WORTH KEEPING.
(1) EXHAUSTIVENESS ACCIDENT: DERIVED_SOURCE and SCHEDULE_REFRESH_SOURCE happen to EXHAUST the sources reaching nba-schedule today, so a branch-derived constant is indistinguishable from a database read. The tests pinned THAT THE TWO BRANCHES DIFFER, not that either value was ever read from the store - which is what the code comment claimed. THE COMMENT ASSERTED THE STRONG PROPERTY AND THE TESTS PINNED THE WEAK ONE. Killed by stamping an ARBITRARY THIRD source string.
(2) BARRIER IN THE WRONG PLACE: every assertion was on a dataclass field introduced by the same commit, and NOTHING IN THE REPOSITORY CALLED main() AT ALL. The commit message said "nothing covered main() output before this" - technically true, materially misleading, SINCE NOTHING COVERED IT AFTER EITHER. Killed by a capsys test that calls main() and parses the printed JSON - the artefact that actually lied.
TEST: mutate the defect back AT ITS OWN LOCATION. If the suite stays green, the barrier is somewhere else and the fix is undefended.

## `c310` - WHERE A PROPERTY IS OBSERVABLE, OBSERVE IT - a syntactic proxy loses to the next form nobody thought of

**Status:** pending

Authored by the verification-toolchain lane 2026-08-26 after TWO review rounds each defeated its previous round fixes. The most transferable rule of the day.
ITS WORDS: "A FIX VERIFIED AGAINST THE REVIEWER PAYLOAD IS VERIFIED AGAINST THE REVIEWER IMAGINATION. Both rounds ran identically: he named a form, I closed that form, he named a sibling. What worked every time was replacing a check ON THE SHAPE OF THE CODE with a check ON OBSERVED BEHAVIOUR - compare the invocation, not the syntax that built it; pin the command body, not a prefix of it."
THE THREE DEFEATED FIXES, each a syntactic proxy:
(1) A mode-equivalence test recorded kwargs["env"] BY REFERENCE, so both modes stored THE SAME MUTABLE DICT - the comparison was STRUCTURALLY INCAPABLE OF FAILING. It also ran with MUTATIONS emptied, so only the BASELINE invocation was compared and a divergence live only during a mutation passed cleanly.
(2) run() concatenated ALL of stderr after ALL of stdout, destroying chronology, so a pytest-shaped block on stderr lands after the real summary and becomes the block the catcher parser reads. Summary matched by PHRASE rather than by the whole separator line.
(3) Pre-existing: classify used re.search("error|ERROR|INTERNALERROR", out) and "errors" in out - LOOSE IN BOTH DIRECTIONS AT ONCE. First arm matches every test name containing calibration_error, of which this module has several. Second requires the lowercase PLURAL, so a run reporting "1 error" beside failures was classified CAUGHT and its failures credited to the mutation.
AND THE CONVERGENCE POINT: "TWO IDENTICAL ROUNDS IS NOT EVIDENCE OF CONVERGENCE." Sequence was 5 findings then 4, with THREE of the second round INSIDE the first round fixes. It refused to claim a round three would find nothing.

## `c311` - MY ERROR: I merged #106 while a second review was in flight

**Status:** done

2026-08-26. I merged #106 at d13f874, which was ONE COMMIT BEFORE the lane round-2 fixes. Three defects landed on main.
LIVE IMPACT: NIL, and the lane could only say so BECAUSE IT RE-RAN rather than reasoned - catcher figures identical before and after every fix in both rounds, 55/55/0/0, 27 singly pinned, 72 distinct, widest 5. LATENT HOLES, NOT WRONG NUMBERS. Follow-up is PR #108.
MY DEFECT: the standup skill I am running says explicitly "While a review is running: do not move the tree underneath it. A verdict on a tree that moved is not a verdict." I verified CI properly - 0 failed steps, 9 runners, all nine gates by name - AND NEVER ASKED WHETHER A REVIEW WAS STILL RUNNING. I had asked every lane to POST its review; I never asked whether it had FINISHED reviewing.
THE MISSING QUESTION, now mandatory before every merge: "IS ANY REVIEW CURRENTLY READING THIS HEAD?" Green CI plus a posted round-1 review is not the same as review complete. The lane had posted round 1 honestly; round 2 was in flight and I did not know because I never asked.
ALSO NOTE: handoff #291 landed on main with THREE FALSE CLAIMS (that an AST test made verdict-independence checkable, "4 -> 17", and "2053 passed"). Corrected by APPEND in #292 and model-card row 0.13, with #291 and row 0.12 left untouched - which is the correct handling of an append-only log that has already published a wrong claim.

## `c312` - THREE SUMMARY FIELDS LIED TO ME TODAY, AND jobsWithRunner IS A FOURTH

**Status:** pending

Consolidated 2026-08-26. A SUMMARY FIELD IS NOT A RESULT. Four instances in one day, each found by a different lane or by me nearly acting on it.
(1) mergeStateStatus=CLEAN with ZERO checks on the head. CLEAN means no conflicts and nothing failing; a PR whose gates never ran satisfies it trivially AND LOOKS BETTER THAN A MID-RUN PR, which reports UNSTABLE. I used this as my merge signal all week.
(2) conclusion=failure with ZERO started jobs. 10/10 never assigned a runner, 0 steps recorded, evicted from a saturated pool after 16 minutes queued. An EVIDENCE-FREE RED. It cost a lane its queue position until it disproved cancel-in-progress (the cancel PREDATED its supposed cause by ten minutes) and timeout (no timeout-minutes declared, default 360).
(3) conclusion=cancelled with ZERO failed steps. 10 jobs, 6 succeeded, 4 cancelled mid-flight, every job assigned a runner, superseded by later-arriving queue runs. Read as a conclusion it is a non-green; read as failed steps it is nothing at all.
(4) MY OWN jobsWithRunner=9, WHICH I REPORTED ALL AFTERNOON AS EVIDENCE AND WHICH IS AMBIGUOUS. Caught by the toolchain lane: "A SKIPPED JOB AND A JOB STARVED OF A RUNNER ARE INDISTINGUISHABLE IN A JOB COUNT; they differ in whether a step ever failed." On every PR today the tenth job was Adapter live smoke, skipped by design, and I read 9-of-10 as fine without distinguishing skipped from starved. A RUN WITH ONE GENUINELY STARVED JOB AND ONE SKIPPED JOB WOULD HAVE READ IDENTICALLY TO A CLEAN ONE.
THE ONLY RELIABLE DISCRIMINATOR: steps with conclusion=failure, plus an explicit skipped-versus-starved split. Never conclusion, never mergeStateStatus, never a bare job count.

## `c314` - A STATISTIC OVER NOTHING IS NOT A SMALL STATISTIC, IT IS NOT A STATISTIC

**Status:** pending

Unifying principle authored by the verification-toolchain lane 2026-08-26. It names one class that I had been recording as four separate traps.
ALL OF THESE ARE SUMMARIES COMPUTED OVER AN EMPTY OR PARTIAL SET, AND AN EMPTY SET SUMMARISES BEAUTIFULLY:
- mergeStateStatus=CLEAN with zero checks on the head
- conclusion=failure with zero started jobs
- conclusion=cancelled with zero failed steps
- jobsWithRunner=9 conflating skipped with starved
- test_name_diff.py reporting "no test names changed" for a scope containing none of the change
- a mutation harness printing "55 caught" while a universal catcher does the catching
- pytest --collect-only reporting a detector as verified when its reconciliation loop never executed
- gh api ?head_sha=SHORTSHA returning empty for every input
- gh pr view --json reviews returning empty for every self-authored PR
THE CORRECT BEHAVIOUR IS ALREADY IN THIS REPO AND SHOULD BE COPIED: predict_union.py and the census REFUSE AN EMPTY BASE rather than reporting zero. Refusing is the only honest output when the denominator is nothing.
ALSO WORTH KEEPING, on why my #106 rule was too narrow: "A RULE WRITTEN IN TERMS OF WHO ACTS WILL MISS EVERY ROUTE WHERE SOMEBODY ELSE IS MADE TO ACT." Do-not-move-the-tree-under-a-review reads as a rule about MY action; what matters is THE TREE STABILITY DURING A REVIEW, and a merge that forces someone else to rebase disturbs it just as effectively. Same shape as a guard naming a form rather than a property.

## `c315` - BACKLOG: one script that verifies a CI head honestly - gate names, failed steps, skipped vs starved

**Status:** pending

Proposed by the verification-toolchain lane 2026-08-26 and ACCEPTED AS A BACKLOG ITEM rather than done, because adding a script means another PR and another tree movement during a freeze protecting an in-flight review.
THE PROBLEM IT SOLVES: the correct way to verify a CI head currently lives in TWO CHAT MESSAGES, which is precisely what AGENTS.md exists to prevent. I have hand-rolled it about eight times today with gh api one-liners and got the skipped-versus-starved distinction wrong every time until a lane caught it.
SPEC: takes a FULL 40-char SHA. Prints gate count, gate names with conclusions, steps-with-conclusion-failure count, and an explicit SKIPPED versus STARVED split (a skipped job and a job never assigned a runner are indistinguishable in a job count and differ in whether a step ever failed). WITH A POSITIVE CONTROL ON ITS OWN QUERY BUILT IN, because gh api ?head_sha= silently returns empty for a short SHA and I nearly reported "no CI runs exist anywhere" on that.
LIVES IN scripts/ beside predict_union.py. Should REFUSE rather than report zero when the run set is empty, matching what predict_union.py and the census already do.
OWNER: whoever has a quiet queue. Not urgent; it is a coordinator tool, not a draft-day one.

## `c316` - GENERAL RULE: any check comparing a branch to origin/main is broken - use the MERGE-BASE

**Status:** pending

Generalised by the reliability lane 2026-08-26 from the append-only rule to EVERY comparison check. THREE INSTANCES, all the same defect.
(1) docs/handoff.md byte-prefix containment vs origin/main - reported a FALSE BREACH when main appended underneath a branch.
(2) scripts/test_name_diff.py origin/main HEAD - THE INVOCATION I HAVE BEEN PRESCRIBING TO FOUR LANES ALL DAY. Reported SEVEN DROPPED test names that are other lanes tests present in c07aefb and absent from a branch based on 02ec617. NOT DELETIONS. Against the merge-base: nothing dropped.
(3) my own --json reviews control - a reference that could not see the object under test.
THE IRONY IS EXACT AND IT IS MINE: my standing instruction was "use origin/main, NEVER bare main, because the local ref is 188 commits stale and yields phantom DROPPED." I DIAGNOSED THE STALE-REFERENCE FAILURE AND PRESCRIBED A MOVING-REFERENCE ONE AS THE CURE. Both produce phantom DROPPED. I fixed the direction and not the class.
CORRECT FORM EVERYWHERE: git merge-base origin/main HEAD. A CHECK WHOSE REFERENCE IS ALLOWED TO MOVE IS NOT MEASURING WHAT IT NAMES.

## `c317` - NEAR-MISS: I nearly merged a PR after verifying a different branch entirely

**Status:** pending

2026-08-26, merging #108. Caught by luck-adjacent habit, not by design.
I ran git rev-parse origin/sr2501-verification-toolchain-repair to get the head. THAT IS THE #106 BRANCH. It still exists on the remote (the delete failed because a worktree held it) AND HAS SINCE MOVED TO 7eda330, a completely different tree. I got back a plausible SHA, queried CI on it, and received A REAL RUN WITH REAL GREEN GATES - 9 of 10 jobs, Postgres running, 0 failed steps.
EVERYTHING LOOKED RIGHT AND IT WAS ABOUT ANOTHER TREE. #108 is on sr2501-verification-toolchain-round-two at 18adbab.
CAUGHT BY: gh pr view 108 --json headRefName. I only ran it because the head SHA did not match what the lane had told me, and I checked the discrepancy instead of assuming the lane was stale.
RULE: NEVER RESOLVE A PR HEAD FROM A BRANCH NAME YOU RECALL. Always gh pr view N --json headRefOid. Branch names outlive their PRs, get reused, and keep moving after a merge.
COMPOUNDING FACTOR: gh pr merge --delete-branch FAILED SILENTLY-ISH on #106 because a local worktree held the branch, so the remote branch survived. The cleanup failure is what left the trap armed.

## `c318` - MY PRIMARY WORK PRODUCT LIVES ONLY IN A SESSION-SCOPED SQL TABLE

**Status:** pending

Found by the verification-toolchain lane 2026-08-26, which grepped for a backlog item I said I had FILED and could not find it - with a positive control on every query.
THE ITEM WAS NOT FILED. It existed only in the message saying it was filed. AND IT IS WORSE THAN ONE ITEM: roughly 330 entries, c1-c318, recording every rule correction, merge trap, architecture cost and lane-correction-to-me of the day, ALL IN A PER-SESSION SQLITE TABLE NOBODY ELSE CAN READ, WHICH DIES WITH THIS SESSION.
So the thing I have spent all day telling four lanes - NOTHING IMPORTANT LIVES ONLY IN A CHAT, the opening rule of AGENTS.md - DESCRIBES MY OWN PRIMARY WORK PRODUCT.
THE LANE MECHANISM, which generalises: "IT IS A RACE BETWEEN DECIDING AND RECORDING - you decided it, said so, and the recording step is a separate action that has not happened yet." FILED IS A CLAIM ABOUT AN ARTEFACT AND I USED IT TO MEAN DECIDED.
WHAT IS NOT LOST: the lanes have each appended their own findings to docs/handoff.md, committed, now 292+ entries. What lives only here is THE COORDINATOR LAYER - the five revisions of the append-only rule, the four lying summary fields, the merge-train architecture costs, and the record of which lane corrected me and how.
ACTION: lands as a handoff entry plus backlog items when the queue is quiet. NOT during an open rebase window, because a commit from me conflicts the lane holding it - the same constraint the lane itself observed when it declined to file the item for me.
