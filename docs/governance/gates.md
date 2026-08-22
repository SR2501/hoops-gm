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
- **A new guard needs a mutation check that reproduces the failure it guards against.** Reviewer-enforced, not CI-enforced — say so in the PR. Added 2026-08-20 after one lane was caught twice: its first mutation on a NULL-league guard passed while proving nothing, and weakening an import detector left the suite green because no module used the missed idiom. Its own conclusion, earned rather than reasoned to: *a mutation check that does not reproduce the bug is the same false comfort as a test that does not.* Construct the failure deliberately, then confirm the guard sees it.
- **The red must be attributable: assert the test is green *before* mutating, and assert the mutation actually applied.** Added the same night, after two lanes hit two different versions of the same hole. One harness reported `RED (guard works)` for a test name that did not exist — pytest exits non-zero on a collection error, so a mutation against a missing test is a red that proves nothing. Another wrote `` `n `` inside a single-quoted PowerShell string, so the replacement never matched, the file never changed, and the run was indistinguishable from a passing guard: **a mutation that does not apply looks exactly like a guard that works.** So: assert the target text is present, apply, assert the file changed, assert red, revert, assert green. "I mutated it and it went red" is not sufficient, and neither is "I mutated it and it stayed green."

  Worth knowing what this bullet is for. A reviewer narrowed one constant — `_TEAM_IDENTITY_FIELDS` — from four fields to one, and **224 tests stayed green**, so three quarters of that guard was unexercised, including the exact field a whole-object fixture had been committed to make visible.

  **And a harness whose anchors can rot is a harness that can quietly stop testing.** A third lane found two of its twenty-two mutation anchors had gone stale when it introduced a local variable, so the harness printed `SKIP` — and *in a list of twenty-two, a skip reads almost exactly like a catch*. It only failed loudly because that script happened to count skips as failures, which its author had not done deliberately. **A skipped mutation is a failure, not a neutral result**, and a harness that reports it as anything else degrades silently as the code moves underneath it.

  **Finally, red is not enough on its own: mutate the thing the docstring *names*, and check the failure matches the docstring's story.** A fourth lane had two mutation checks pass for reasons adjacent to the ones claimed — one reddened against the bug itself rather than the guard, another against a neighbouring condition. Both went red, both looked like evidence, and neither established what its docstring said it established. If a test claims to be pinned by a parked id, remove the parked id; if it stays green, the pin was something else. **And a red that any edit would produce is not attribution at all.** A mutation deleting a sub-condition in `_require_declared_season` survived a **1,247-test suite** — green everywhere except one fingerprint test, which fires on any byte change to the file and would fire for whitespace. It reddened, it looked like the suite catching a defect, and it established nothing about behaviour. **A file-digest check is the reassuring half of a test at file scope**: it is guaranteed to notice, and guaranteed not to tell you what it noticed. Discount it when reading a mutation result, and note the untested route there was the *likelier* drift — a payload keeping its envelope and losing one field is more probable than one losing the envelope.

  That paragraph is about a red arriving for the wrong reason. **The same attribution failure happens to greens, and nothing mutates a passing test.** A lane cited a guard as evidence its classifier handled epoch sentinels; the guard was catching a year-0001 value only because `America/New_York` ran on −04:56 local mean time before 1883, so the value misses reconciliation by four minutes. The source's *actual* placeholder convention is 1900, which reconciles exactly and would have passed. The guard had never done the job it was credited with, and it was one year from being asked. **A guard that passes for a reason other than the one claimed is indistinguishable from one that works, until the neighbouring case arrives** — so when a passing test is offered as evidence of a property, state which line establishes it. The cleanest instance is a *test*, not a guard: one named `accepts a null game_date but still refuses one that is simply absent` omitted the sibling **reason** field as well as the date, so the refusal came from the missing reason. The assertion passed, the name described exactly the right thing, it had passed review, and the mutation widening the date check went **uncaught**. Reading could not have found it — only a mutation aimed at the check the test *claims* to exercise. That is why `NOT CAUGHT` must be a failure rather than a curiosity: it is the only signal that distinguishes a test from a test-shaped object. See R55 in `risks.md` for the other half: what an agreeing check can establish at all.

  **And the green-before-mutating rule earns its place twice over.** It was written to stop a mutation that proves nothing; it has also twice stopped a *test asserting something false* from being committed, because the assertion failed before the mutation ran. One lane's new test claimed a season string of `9993-94` would be treated leniently; it would not, because that season builds a valid window that 2026 is legitimately outside. Neither use was anticipated when the rule was written, and the second is the more valuable: a mutation that proves nothing is merely useless, while a committed test encoding a false claim misleads for as long as it stays green.

- **Before any of that, prove a test reaches the code at all.** Added 2026-08-21, and it is the precondition the three bullets above assume. A marker placed inside an `IntegrityError` handler and *proven to fire* by driving a real violation through it reported `TRIPWIRE ABSENT` against **1,373 passing tests** — so a blanket `except` mapping every storage failure to a *retryable* code, meaning a conforming client retries a permanent error forever, survived a code review, a mutation matrix **and** a green PostgreSQL run simultaneously. The suite had *does not contradict*; it never had *reaches*. **A mutation matrix over a branch no test enters is a matrix of unreachable mutations**, scored as caught by whatever the harness counts as non-zero. Insert the tripwire, prove it fires, run the suite, remove it. **And a matrix run on one dialect cannot vouch for code that branches on dialect** — a mutation disabling constraint-name discrimination survived on SQLite, where it is unreachable, and was caught on Postgres. The surviving row was the only thing that said the matrix had a blind spot, which is the second reason `NOT CAUGHT` must be a failure rather than a curiosity.

- **Read the rendered result, not only the diff.** A section inserted by anchoring on a heading consumed that heading, orphaning the paragraph beneath it so *“Recorded here because they cost a session to find”* had no antecedent for “they”. **The diff looked correct**; only the rendered document showed the break. Anchor edits on surrounding prose rather than on a heading, and read the result.

- **A reviewer that mutates code needs its own worktree.** Reviewer-enforced, not CI-enforced. Reviewer sub-agents share the author's tree by default, and mutation is a write. On one unit a reviewer's narrowed constant was left behind after its run and was caught only by the test written for that constant; one of its writes landed mid-run and produced a `JSONDecodeError` in an unrelated suite that read exactly like a real failure; and its own mutation was clobbered by an author write, **briefly reporting a false green**. Both directions produce a result that means nothing, and only one of them looks wrong. Use a detached worktree for any review that writes. **And the author side of the same rule: do not start work while a review is outstanding.** One lane edited files mid-review three times after being asked to hold the tree still, and **the reviewers disclosed it every time rather than the author** — which makes it a habit rather than a lapse, and the fix is not intending harder. A verdict on a tree that moved underneath it is not a verdict, and the author is the only party who can tell whether it moved.

Enforced by CI, except the three bullets marked otherwise.

---

## Adapter gate

**Applies to:** anything calling an external source — `nba_api`, `cdn.nba.com`, Fantrax official API, `fantraxapi`, injury reports, projection CSVs.

- **Recorded fixture committed.** A real captured response, checked in.
- **Capture raw bytes — a recording that has been through a serialiser is not a recording.** Added 2026-08-21. One lane's first fixture went through PowerShell's JSON round-trip, which parsed `imported_at` into a `DateTime` and re-emitted it as `08/21/2026 15:57:03`: US locale, no timezone, no sub-second precision. **Every structural assertion would have passed**, because the shape survives — and what the capture tool destroyed was precisely the field class this project has already been bitten by (`gameEt`, in `AGENTS.md`). A recording exists to be evidence of what a producer emitted; anything that parses and re-emits substitutes its own representation for the producer's. Same family as an AST comparison that cannot see comments: **a transformation that preserves what you are checking and destroys what you are not.**
- **Contract test** asserting the parser still works against that fixture. Runs in CI, offline, always.
- **Live smoke test** hitting the real source, marked so it may fail without blocking a merge — but it must fail *loudly and visibly*, never silently.
- Throttling and retry documented for the source's known limits (`stats.nba.com` ~1 req/s; Fantrax read-only, low frequency).
- Failure behaviour is explicit: what the system does when the source is down, changed, or returns garbage.

**Why:** `/fxpa/req` is undocumented internal infrastructure and can change without notice. The contract test is how we find out in CI instead of at 11:59pm on lineup lock.

---

## Model gate

**Applies to:** anything producing a number a decision rests on — `p(play)`, reliability metrics, projections, blending, z-score, G-score, risk-adjusted valuation, auction dollar values, inflation, contingent value.

- **Backtest against held-out data.** Never evaluate on data the model was fit on.
- **Report calibration, not just accuracy.** For probabilistic outputs this is the primary metric. A model that says 70% and is right 70% of the time is more useful for lineup decisions than a higher-accuracy model that is overconfident. Reliability diagrams or binned calibration tables.
- **Model card in `docs/models/`** — inputs, method, training window, evaluation results, known failure modes.
- **State what the model cannot see.** Trades, coaching changes, undisclosed injuries, personal matters, front-office intent. Be explicit about the blind spots.
- **Version the output.** Every stored number records the model version and inputs that produced it.

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

## What gates cannot catch

Added 2026-08-20, after three lanes and thirteen review rounds produced roughly fifteen
real defects, **none of which any gate would have caught**. Lint, types, and a full green
suite were green throughout and would have stayed green through all of them.

The shape they shared: *something that reads correctly and does nothing, or means something
other than what its consumer assumes.* A guard bypassed for exactly the row it was written
to catch. Tests that wrote state in a shape no real producer writes. A docstring claiming
coverage its matcher lacked. An alarm asserting over a file that could only change by hand.
Copy that was true of one condition and false of the next one raising the same code.

Two things follow, and neither is a new gate.

**A gate is a check, and R54 applies to gates too** — a gate can go green while asking a
question adjacent to the one that matters. Adding a fifth would add another thing capable
of that. These failures do not have a mechanical shape; the honest thing is to say so here
rather than to grow the apparatus.

**What actually caught them was a person re-deriving.** Executing rather than reading: a
static enumeration of 44 lock sites declared a lock ordering sound, and instrumenting the
lock and running the code found the inversion in four lines of trace. Driving a real
refusal rather than reasoning about it: of six conditions driven end to end, four falsified
copy that had already passed review.

**And a review suggestion can be the dangerous thing.** Later the same night, a reviewer
proposed an all-or-none CHECK constraint over four new columns — well argued, precedented
by an existing table's volume-pair CHECKs, and accepted by the author. Implementing it
turned the migration suite red on a test that looked unrelated. It was not: SQLite cannot
add a CHECK in place, so the migration needs `batch_alter_table`, which **rebuilds the
table by copying, dropping the original and renaming** — and ten foreign keys point into
`players`, eight of them `ON DELETE CASCADE`, including the crosswalk itself, game logs,
participation and projections. **On a real database that migration silently deletes a
season of ingested data.** In the suite it surfaced as one surviving row where one was
expected.

Neither reviewer nor author could have reasoned to it; running it took four minutes. And
the reason is not that the reviewer was careless — **the suggestion was correct about the
invariant and wrong only about the cost, and the cost was invisible from the code under
review.** The reviewer was reading a model file and a migration; the danger lived in ten
`ON DELETE CASCADE` foreign keys in *other* model files, plus a SQLite implementation
detail. No amount of care reading that diff surfaces it.

So two rules, the second more useful to whoever writes the next migration:

- **A suggestion is a hypothesis until it has been run**, and its blast radius is not
  bounded by how well it was argued.
- **A migration's risk is bounded by what references the table, not by what the migration
  says.**

Keep both halves of what happened. While briefly active, that same constraint caught a real
defect — a seed writing a position with no provenance, a shape no real producer can write.
**A check can be simultaneously right about its invariant and unshippable.**

So, alongside the gate matching your work: **state what each check can and cannot observe
at the point you write it**, and **re-derive any number or mechanism appearing in prose, at
the moment you write it, from the code beside it.** The failure modes and their evidence are
recorded as R49–R58 in `risks.md` — deliberately in one place, because a lesson restated in
two files drifts in one of them.

### Three questions no gate asks, because no gate looks at scope of application

Added 2026-08-21. One lane produced four defects in one unit that were **not logic errors**. None shipped — every one was found in review and fixed before merge, across eight rounds; this section is evidence the structure caught them, not that it let them through.
Each guard was written *correctly* and then applied to one of the two places it belonged; a
reviewer found the other every time. The plausibility bound went on the lenient path and not
the strict one — and the strict one persists a value that joins `player_participation`. An
invariant was enforced on read and not on construction, so a record could be written that no
reader will accept. `OverflowError` was absorbed on one branch and not its sibling, so the
one shape that bypassed the exit-code channel was the shape that unit had just added an exit
code to make trustworthy.

The fourth was the inverse and is why this is two questions rather than one. A guard caught
`ValueError` so that an odd season string could never decide whether a real schedule imports
— and the new window construction was placed **outside** that `try`, where `date()` raises
`ValueError` for a year outside 1..9999. The guard silently stopped covering what it was
written for, in the commit that removed the same class two functions away.

So, when you write or move a guard, ask all three:

- **Where else is this true?** A fix written while reasoning about one branch does not get
  asked this by anything in the process.
- **What was already protecting this line, and is it still?** New code placed inside a
  function is not automatically inside the guarantees that function was making.
- **And when you *correct* something, where does the correction's reasoning hold?** Added
  2026-08-21 after a fourth instance on a single branch, every one of which named a mark, a
  field or a direction and then reached one member of a symmetric pair: a middot wrapped in
  `<code>` mid-sentence while the em dash defined beside it was not. The two questions above
  are asked of original writing, and nothing asks them of corrections — **which is worse,
  because a correction arrives with the confidence of having just been right about
  something.** The same shape outside code: a guard's circularity blocked one unit, was
  correctly worked around, and blocked the next unit the same day without being anticipated.
  So when a guard blocks you, **enumerate its full scope once and record the list**, and the
  next unit meets a known constraint instead of a surprise.

None of the three is a gate and none should become one: a checklist item gets ticked, which is how
a guard comes to pass for the wrong reason. They are questions to ask while writing.

### Verifying a change did what you think

Added 2026-08-21. Three lanes independently recorded the **outputs** of throwaway verification
tools and none of the procedures, so each method died with its session while its results stayed
in the handoff reading like evidence. Two are worth keeping, and both exist because a check
succeeded against the wrong thing.

**Resolving a conflict: verify, then stage.** One lane committed `<<<<<<< HEAD` into
`docs/handoff.md`. Its resolver raised on a block whose HEAD side was empty; it ran `git add`
anyway, because resolve-and-stage were two steps in one command and only the second exit status
was read. `rebase --continue` then committed the markers, and it was found by grepping the
*commit*, not the working tree. **Staging is not resolution.** A resolver must assert no marker
survives *before* it stages anything and exit non-zero otherwise — and note the file it landed
in is append-only, so nobody would have re-read it.

**Patching for a mutation: scope the patch to the definition.** A naive string replacement hit
`_projection_rows` when the target was `_games_played_claims`, because `.order_by(Projection.player_id)`
appears in both. The mutation "worked" against the wrong function and nearly read as evidence.
Slice the source between `def target(` and the next `def `, patch only that span, assert the
patch applied, run the *targeted* test, restore.

Both are the same failure as the mutation bullets above — success inferred from an adjacent
signal — which is why they are here rather than in a tools directory. **A tool rebuilt from an
accurate description gets re-read; a committed script gets run without being understood.**

**That rule governs safety, not evidence, and the distinction cost a lane its strongest
number.** A mutation harness reporting *33 of 33 caught* lived outside the repository for nine
review rounds, so **no reviewer could ever check the figure that carried the unit**. Its failure
direction is silent — a broken harness reports success — which by the rule above argues for
describing it. That is the wrong conclusion. **If a tool's output is cited as evidence, it must
be in the repository regardless of failure direction, because the citation is what is being
audited.** Describe a tool you want re-derived; commit a tool whose numbers appear in a review.

**And the question that found seven holes in one verification script, which is the most
reusable thing on this page:** *for each thing this file compares, what is the key set, and is
it asserted or assumed?* All seven answered **assumed**. The last one had a visible
consequence: overwriting one non-zero count row with a duplicate of a zero row left the
cardinality intact, so a row-counting density check passed and a comparison iterating the rows
it received never looked up the vanished pair — and on the screen a real count became the
marker meaning *the backend sent no count*. **Two independent checks shared one proxy.** Assert
membership of every key set a comparison depends on, not its size.

**And capture both baselines before the rebase, not after.** `Compare-Object` needs something
to compare against, and after a bad merge the pre-state is gone. Every lane on 2026-08-21 ran
its slug diff *after* finishing and got away with it only because `origin/main` was still
fetchable — which does not hold when the thing you must diff against is your own pre-rebase
branch. **A check you can only run when nothing went wrong is not a check.**

### Rounds have a cost, and the cost is prose

One unit on 2026-08-21 ran six review rounds. It found **two behavioural defects a user
would have seen** — both in the ADR-002 spine, both found by a reviewer executing a claim
rather than reading it, neither catchable by any gate. Everything else the rounds found was
prose, and **most of that prose was created by the rounds that fixed the two.**

That is not an argument for fewer rounds; the two defects were worth all six. It is an
argument about how corrections are written. Each round tends to add a corrected restatement
beside the wrong one rather than replacing it, so a phrase fixed in round four survived in
three other files findable with one grep, and two documents claimed a refusal family had
eight members in the very commit that recounted it to nine.

**State a mechanism once, where readership is most durable, and reference it elsewhere.**
A corrected restatement is a new copy that can go stale independently, and lint, formatting
and type-checking read none of it — a reviewer on that unit caught a blank line splitting a
governance table so its last two rows rendered as literal pipe text, with ruff, format and
mypy all green over it.

**And know which argument actually lets you stop.** Another unit the same night ran eight
rounds, every one of which found something real, and the lane's first reason for stopping was
diminishing returns: the severity gradient was steep — season-killer, then a poisoned
availability denominator, then an unreachable season string beginning with a year ≤ 5 — and
the remaining risk sat in one function it had characterised exhaustively. All true, and it
does not terminate: there is always one more round with some expected value.

The argument that terminates is different. **Once a round begins finding defects in code the
previous round wrote, a further round examines the previous fix** — and that regress does not
end on evidence, because each round genuinely produces some. It ends only on judgement. Round
eight found a defect in a guard round seven had added; a ninth would have examined round
eight's. Stop there, and say that is why.

**And the two shapes are not exclusive within one series, which is why the stop call belongs outside it.** A nine-round unit was mostly the *converging* kind — wrong artifact, wrong field, wrong operand, wrong cardinality, wrong key set, each round a strictly smaller and more structural class in the **original** work. But two of its rounds were the thrashing kind: a one-directional key comparison fixed in one commit and reintroduced one function later, and a claim that went over-stated, then over-corrected, then right. **A series can converge and thrash at the same time, and the author cannot reliably tell which is dominant from inside it.** Have someone outside the series make the stop call.

Two corollaries, both earned the same night:

- **Do not push a prose improvement onto a head the coordinator is about to merge.** One lane
  declined to, on the grounds that it would restart the PostgreSQL runs three other lanes were
  queued behind, to sharpen a paragraph whose substance was already recorded. That is this
  section's rule arriving at the moment it is most expensive.
- **The cost applies to governance itself.** This entry was written alongside nine others in
  one night; three were folded into others before landing and one shrank to two sentences,
  after reading this file rather than recalling having written it.

### A true signal with no consumer

Added 2026-08-21. **One test, one number, three separate opportunities, no reader.**

`ProjectionsTable.recorded.test.tsx` was *deterministically* over a 5,000 ms budget rather
than flaky, so the pass was the lucky run — and **a guard that fails slowly reads as green**,
because a re-run converts an assertion that never completed into a permanent green check.
Vitest printed the slow-test line every run: **3,177 → 3,309 → 3,376 → 3,714 → 4,298 ms**,
climbing monotonically, directly above the suite total a lane quoted four separate times. And
CI had been red across three heads for hours. Each number is unremarkable and passing; only
the sequence is alarming, and nothing computes a delta.

The same shape at every scale that day. A warning about tip-off provenance sat correct and
unread in the field it described. A note saying the availability model was blocked lived in
prose while the machine-readable `Depends on` edge said ready. A comment explaining that a
marker-looking line is *content, not structure* sat one function away from the function that
needed it, in the same commit. The ten-deep critical path through 122 backlog items was found
by writing a twenty-line script while looking for something else.

**The mitigation is tooling, not discipline, and that is the entire point of this section.**
Asking people to read more is the one remedy this failure is immune to — every signal here was
already visible to anyone who looked. So two items are *filed* rather than written up:
`backlog-dependency-graph` resolves every `Depends on` token against the slug set and prints
the longest path in CI, and `per-run-metric-delta` prints each per-run number beside its
previous value. Note what the second deliberately is not: **a threshold recreates the cry-wolf
guard the moment the number is legitimately allowed to grow** (R62), so it prints the delta,
makes no judgement, and fails nothing.

One correction is worth keeping, because it is instructive. The slow test was first read as a
display artefact — a push run failing while a `pull_request` run passed on the same head — and
history showed an earlier head red on *both* event types. Two true statements (the checks
table did show a pass; that head did split) were generalised into a conclusion neither
supports, which is R61 arriving inside the message that filed R61. **The real finding was the
simpler one: a signal with no consumer is not a signal, and fixing the checks table would not
have touched it.**

### A coupling between trees that nothing here can see

Added 2026-08-21. `frontend/src/test/fixtures/make_pending_date_payloads.py` imports
`parse_teams` and `parse_schedule` from the backend package and `weekly_periods` from
`dev/seed_schedule_grid.py`. A PR modified `parsers.py` and **nothing detected the coupling**:
git reported no conflict because the frontend lane does not edit that file, the frontend gate
does not run Python, the backend gate does not know the frontend imports it, and the
mergeability label read CLEAN throughout. It did not bite — `parsers.py` added two definitions
and altered none — and the gap is that nothing would have told either lane if it had.

The same blind spot across *time* rather than language. A README told a reader to run
`python -m hoops_gm.dev.seed_projections`, a module that existed only on an unmerged sibling
branch. Every gate passed, because the README was **accurate about the tree it was written in
and false about the tree it merges into**, and nothing we run checks a claim at the moment it
becomes false: CI tests the branch, and the branch is correct.

- **Name the coupling in both places, because no tool here will.** A cross-language import is
  a dependency no gate in this repository can see.
- **A file list answers *what will conflict*, not *what will break*.** One PR was sized by
  file count and re-sized by the lane according to what its own code reaches into, which was
  the question that mattered.
- **When a lane builds against an unmerged sibling, the dependency is written in three places,
  chosen by who hits it**: beside the command for the operator, in the backlog entry for
  whoever picks the task up, and in the handoff for the mechanism. A dependency that lives in
  a working directory but in nobody's *ordering* is invisible until somebody runs the command.
- **A held lane arrives with its exposure already narrowed.** Holding a producing lane until
  every consumer has reported costs near zero; not holding it means the consumer debugs alone
  against code whose author is gone. What made it cheap once was a coupling discoverable in
  one grep, so the held lane supplied the raw source hash of the coupled function *including
  comments*, its module-level bound names before and after with none lost, and the consumer's
  exact import sequence run against merged `main`. That is an exclusion the consumer can act
  on — *if your verifier reddens, it is not this* — rather than a reassurance it must
  re-derive.

### Naming a defect class is not a mitigation

Added 2026-08-21, and placed last because it governs everything above it.

Three lanes shipped fresh instances of classes they had personally written down hours earlier,
on the same day. A disclosure scanner descended dicts and **stopped at lists**, so a planted
defect inside a list was invisible and the file stayed green — written in the same sitting as
the entry recording that lesson. A mutation harness published two fictional matrices the same
afternoon its author recorded that a check must assert it found something. The coordinator
wrote down *ran one gate and reported another* in the morning and committed it twice within
four hours: once running `pytest` and not `ruff format`, once running `mypy --strict` on a
script and reporting *strict mypy clean* while eighteen unannotated test functions sat outside
the path it had checked.

**Only a mechanism helps.** The fix that worked on the scanner was two unit tests pinning the
list descent *directly* rather than leaving it implied by a higher-level test. Not more care,
and not a reminder. Every rule on this page with no mechanism behind it should be read as a
description of something that will happen again.

**Which makes this the least reliable section in the repository, and it should say so.** It is
the one part with nothing executable underneath it, and the class it documents is *believing
that having written something down changes behaviour*. If a rule here matters, the useful next
step is to find the cheapest mechanism that enforces it and file that — the way the two items
in *A true signal with no consumer* were filed instead of written up.

---

## Gate discipline

- Gates are not paperwork; if one is not catching anything, say so and change it.
- Failing a gate is information, not failure. Record it in `docs/handoff.md`.
- No gate may be waived by the agent whose work it applies to.
- **Gate assignment and gate satisfaction are both self-reported claims.** The rule above
  imagines waiving as an *act* — someone deciding to skip. It also happens as an *argument*: a
  true, well-reasoned, good-faith case for a narrower gate, which is far more persuasive than
  a skip and leaves a defensible paper trail. One lane assigned Code gate only, and every
  premise was true; `blending` is named on the Model gate's applies-to line and the bullet
  that bit was *version the output*. **The list was checked. The bullets were not.** So: name
  the module on the applies-to line, then **walk every bullet under that gate and say which
  artifact satisfies it** — that failure dies at *version the output*, because no artifact
  could have been named for it. And the tell is a trap rather than a reassurance: the correct
  gate there cost almost nothing (a model-card revision, no backtest), which reads as evidence
  the gate does not apply. **A gate whose expensive bullets are inapplicable looks like a gate
  that does not apply**, and those are not the same thing.
- **State the veto's unit, then the gate's, and assert the gate's is at least as strict.** A
  pre-unblind admissibility gate measured *canonical observations* while the activation veto
  it pre-empts measures *direct outcomes*, a strict subset — so it would have passed the exact
  case it exists to catch. A gate whose unit is looser than the veto it pre-empts removes only
  what the veto would have removed anyway.
- **"Gates green" has to mean all of them: run the CI-equivalent command set, or nothing.**
  Twice in one day it meant *the gates I remembered*.
- **The could-not-verify field states what was not checked and, separately, whether the reason
  it is believed harmless was *driven* or *reasoned*.** `AGENTS.md` makes the field mandatory,
  so lanes are disciplined about enumerating gaps and nothing disciplines the justification
  attached to each. *"I could not verify X"* is checkable and gets checked; *"and I believe X
  is unreachable"* is a load-bearing claim arriving in the same breath, wearing the humility
  of the section around it, and nobody reviews it because a disclosure reads as an admission
  rather than an assertion. **"Reachable, driven, harmless" and "believed unreachable" are
  different claims and only one of them is evidence** — prefer the first, and where only the
  second is available, say so in those words.
