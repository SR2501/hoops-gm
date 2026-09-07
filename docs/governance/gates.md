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
- **A green check does not describe the head you are merging. It describes a merge commit, and that merge commit can be stale.** Added 2026-09-06 after `#168` merged with strict mypy failing and took `main` down with it. GitHub runs pull-request checks against `refs/pull/N/merge` — your head merged into `main` *as `main` stood at that moment* — not against your head. So a check can be **green on a merge commit that no longer exists**, and **red on a merge you never made**. Both happened the same morning: `#168` most plausibly went in on a merge ref computed before something else landed, and `#169` then failed on three errors in `#168`'s file, frozen into a merge ref computed after `#168` landed and before the fix. Lane 6 had touched none of it.

  Two consequences. **Re-running CI does not refresh a stale merge ref** — it re-runs against the same merge commit and reproduces the same failure, which reads exactly like a real failure in your own work. Push to the branch, or rebase, to force recomputation. And **"green CI on the real head" means confirming the `main` side of the merge ref is current**, not merely that the checks are green. The cheap check: `git merge-base --is-ancestor origin/main refs/pull/N/merge`.

  **That check is strict, and strictly applied it never converges** — `main` moves, so every push invalidates every open pull request and a busy morning would spend itself re-running. The rule that actually works: the merge ref's `main` side must include everything that **could change the result**. A behavioural commit — source, test, config, dependency — invalidates it and you re-run. A documentation-only commit does not. Judge it by what landed, not by the SHA being equal, and when you cannot tell, re-run. State which you concluded and why, because "it was only docs" is exactly the sentence that precedes a bad merge.

  The cost is the argument. One skipped two-minute check produced red pull requests on **four** lanes that had introduced no defect, on a morning with 41 days to an immovable draft. A gate that only the careful respect is not a gate; this one is cheap enough that there is no excuse, and its failure mode is other people's time rather than your own.
- **On `main`, a green run describes the tip and no other commit.** Added 2026-09-06 with the architect ruling on `ci-main-signal-lost-in-queue`. `ci.yml` sets `cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}`, which is **false on main**: main runs queue instead of cancelling the one in flight, and GitHub holds at most one run pending per concurrency group, so a third push cancels the *pending* run before it ever starts a job. The observable consequence is that commits reach `main` carrying **no CI record of their own** - `02f527e9` did exactly that on the day this was written, cancelled while pending with zero jobs started, and three more did it the night the item was filed.

  **And the loss is invisible, because it renders as a green tick.** Verified on `02f527e9` rather than assumed: `gh api repos/SR2501/hoops-gm/commits/<sha>/check-runs` returns **three check runs, all successful**, and every one is a CodeQL `Analyze` job. A run cancelled while pending starts no jobs, and **check runs are created per job**, so the cancelled CI run contributed nothing whatever to the commit - no red mark, no skipped entry, no trace. The same query against `5bf3ffa7`, whose CI did run, returns **fourteen**. Both commits display as green and they differ only in a count nobody reads. This is the "state the denominator" rule above biting on the gate's own signal, and it is why the flip condition recorded with the ruling in `docs/backlog.md` under `ci-main-signal-lost-in-queue` is stated as *attributable* rather than *green*: **revisit the decision when the tip of `main` is found carrying no successful CI run once that run has settled.** A tip whose run is still queued is the ordinary state and not the trigger - three consecutive commits sat exactly that way on 2026-09-06 while this paragraph was being written. **The cheap observation, because a flip condition nobody can observe is decoration:** compare the check-run names on the tip against the CI job set - CodeQL on its own is three, a real CI run is fourteen.

  Related, and the reason the workflow inventory in my own notes was wrong: **CodeQL here is default setup, not a file.** `gh api repos/SR2501/hoops-gm/code-scanning/default-setup` reports `configured`, on push and weekly. Listing `.github/workflows/` finds two files and under-counts what actually runs on every push, which also means the runner-contention argument below is being made against a pool already carrying two workflows per push rather than one.

  So *"CI was green on commit X"* is a sentence this repository cannot support for an arbitrary X, and a run sitting `pending` for a quarter of an hour on main is queueing working correctly rather than a hang - which matters, because the symptom reads as one. **This was accepted deliberately rather than tolerated:** the obvious alternative, dropping the concurrency group for pushes to main, multiplies main's runner demand by the push rate, and this pool is already observed to saturate and evict queued runs as evidence-free reds. What the choice costs is bisect over CI history, which is worth little to one developer and would be worth a great deal to a team. `test_the_main_concurrency_rule_cannot_invert_unnoticed` pins the rule in both directions, because the item's sharpest finding was that this behaviour had been believed to be the exact opposite of what it is and nothing detected that.
- **The gate is a set of outcomes, not a set of commands, and the commands as written elsewhere do not run on this machine.** Added 2026-09-06. Five trial arms were handed a task prompt specifying `ruff check scripts` and `ruff format --check scripts` from the repo root. **Bare `ruff` is not on `PATH` here**; all three arms that reported on it hit `The term 'ruff' is not recognized` and substituted `python -m ruff`. The sharp version of the observation, which came from the arm rather than from me: an agent that distinguished only *zero* from *non-zero* exit status would have **misread a PATH failure as a lint result** — the gate would report on a command that never ran, which is the same false comfort as a mutation that never applied. The same trap covers `pytest` and `mypy`. Use `python -m <tool>`; and a gate step must fail because the tool ran and objected, never because the tool was absent. Two further local traps in this repository: a stale editable install can point `hoops_gm` at a deleted worktree, so pin the source with `cd backend; $env:PYTHONPATH = (Resolve-Path 'src').Path`; and Python 3.12 here lacks `mypy` and carries a legacy `httpx` that turns a Starlette deprecation into an import error, so use 3.14 locally. **None of this substitutes for CI**, which is the only run on the platform the project actually targets.
- **Three commands on this machine report success or failure about something other than what you asked.** Added 2026-09-06 from four lane debriefs taken before archiving; each trap below was hit independently by at least two lanes, which is why they are recorded as mechanisms rather than anecdotes.

  **The editable install resolves into a *live sibling worktree*, and that is worse than the deleted-worktree case above.** A deleted target raises `ModuleNotFoundError` and is loud. A live sibling silently supplies **another lane's bytes**, so the suite runs to completion and reports a result that is confidently about the wrong source tree. Measured cost on one night: a cp1252 regression that failed *despite* its own fix being correct; an 80-failure run misread as a possible `main` regression; and - the expensive one - a lane that concluded Alembic's `command.stamp` was defective and **replaced working code with a lower-level substitute**, then withdrew the conclusion once the tracebacks showed the import origin. It is the only trap here that has caused a correct implementation to be rewritten. Pin the source before any pytest or mypy run whose result you intend to believe: `cd backend; $env:PYTHONPATH = (Resolve-Path 'src').Path`.

  **`python -m mypy backend/src` from the repository root does not load `backend/pyproject.toml`.** It emits roughly fifteen third-party and Pydantic errors that look like real type failures and are artefacts of missing configuration. The valid form is `cd backend; python -m mypy`. A lane that reported the root-run output would be reporting a config failure as a type-check result.

  **`gh pr merge` can exit non-zero *after the server-side merge has already succeeded*.** Two lanes hit this independently. The remote merge completes; the local post-merge step then fails to check out or delete the branch because the main worktree owns `main`. The failure is real and is about the local checkout, not the merge. Retrying blindly reports "already merged" and wastes a cycle; concluding the merge failed is worse, because the change is on `main` while the record says it is not. Confirm with `gh pr view <N> --json state,mergeCommit` before believing the exit code, and note that the concise attributable check for a PR's overall state is `gh pr view --json headRefOid,statusCheckRollup,mergeStateStatus` rather than watching individual runs.
- **A check must state the denominator it counted against.** Added 2026-09-06, at the request of a backlog item that had already recorded four instances and asked for the rule to be named here. The debriefs taken before archiving that night added three more, so the count is seven and the interval between them is hours, not weeks.

  Verified directly: a mutation harness whose regex matched nothing printed `SURVIVED`; a `-k` selector silently deselected the very test it was invoking and reported green; `check_append_only.py` compares `HEAD` against `merge-base(origin/main, HEAD)`, so once a branch is pushed it compares the file to itself and prints `appended +0` - proven by running it on `main` and watching base and head bytes come back identical; the secret scanner prints `No secrets found in N tracked files` where `N` is the count *enumerated* before five `continue` branches, so three tracked `.gz` API captures are counted and never read; and I reported a pull request merge-ready from 22 job outcomes across two workflow runs when the pull request carried 26 checks, one of them still running.

  Reported by their lanes and **not verified by me from the diff**: the schedule-grid contract artefact compares one constructed Pydantic instance rather than a live HTTP response, so a handler returning a bare dict, or middleware reshaping the serialised output, drifts while the check stays green - and because values are pinned as single specimens it cannot see a widened domain (`str` becoming `str | None`) or a new enum member absent from the specimen. The demo sanity gate pins twelve measures with set-equality between the doc table and the generated map, which is a genuinely exact denominator *for those twelve* - while the proof JSON literals near the top of `docs/demo.md`, the full-season line, the browser evidence counts and any separately ingested Reliability store are outside it, and a wrong value inside a permitted range passes by design. The Alembic stamp test proves the seed CLI exits zero, that a non-`None` head is discovered and that `alembic_version` equals it - it does **not** compare the seeded schema to the migration-built schema, so it inherits its meaning from a separate migration gate and would bless drift with a confident head if that gate were ever skipped.

  The rule is not that narrow checks are bad - every one of these is worth having. It is that **the headline sentence must name the population**, because `No secrets found in 586 tracked files` and `no secrets in the 583 files I could decode` differ by exactly the three files most likely to hold a credential, and only one of those sentences lets a reader see it. Where a gate's meaning depends on another gate, say which one, so that skipping the second does not silently hollow out the first.
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

**Write conclusions with their scope attached.** Not *"the package has 13 ways in"* but *"at
`74c8ba4`, 13"*. This does not prevent overstatement — nothing cheap does. It makes the
claim **decay visibly**: the next reader checks the commit and disagrees in seconds, without
anyone having needed to catch it when written. It converts an undetectable error into an
**expiring** one, which is the class this project already knows how to handle. `Could not
verify` already enforces exactly this for one field; the same discipline belongs in prose,
where every recorded overstatement so far has lived.

Added 2026-08-23. The rule above is narrower than the defect class it sits under, and the
narrowing was found while writing this paragraph — by checking the examples rather than
citing them from a summary. **Of the recorded overstatements, some lose a scope and some do
not**, and only the first kind is addressed here:

- *"zero `sqlite3.connect`, checked at `74c8ba4`"* became *"zero `sqlite3.connect` in
  `backend/src`"*. **The commit vanished**, and one merge later the sentence was false. This
  rule addresses it.
- *"the smoke test passes against committed fixtures"* became *"passes on a real export"*.
  **What it was run against vanished.** This rule addresses it.
- *"the census stays green at 12 sites while the package has 13 ways in"*. **The count was
  right and dated; `ways in` overstated a capability** — the escaped site builds
  `file:...?mode=ro` and can neither create a store nor write into one. Nothing was
  unscoped. **This rule would not have touched it**, and only re-deriving what the code does
  did.

So: attaching scope converts *one* recognisable sub-class from undetectable to expiring. The
sub-class where a correctly-scoped observation is described in a stronger word than the
mechanism supports is untouched by it, and remains what it was — caught by a second reader
re-deriving, or not caught at all.

Keep that limit attached, because the alternative is this defect performing itself again.
**It cannot be claimed that this would have caught any of the four**; every one was caught by
another agent whose expectation was violated, and nothing here catches the ones that quietly
agree with us. What it claims is weaker and defensible: where a scope is attached, the claim
becomes **falsifiable in seconds by the next reader**. That is not prevention, and it should
not be written up as prevention.

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

**Diff against your own merge base, and beware the moment two methods agree.** Diffing a slug set
against `origin/main` reports another lane's merges as your deletions once your base has moved —
seven false drops in one case. What makes it survive is worse than the bug: run it immediately
after a rebase and it agrees exactly with the correct check, because the merge base *is*
`origin/main` at that instant. **A method whose correctness depends on state that has not moved
yet agrees with the right one precisely while it cannot mislead you**, so *"two methods agreed"*
is weak evidence unless you can say what would make them diverge. Cross-checking is this page's
most-recommended remedy and this is its limit.

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

**And the harder limb, committed by the author of this section's source material: a mechanism
can exist, be walked past, and nothing fails.** `.github/agents/` holds seven agent definitions
carrying reading lists, non-goals and done criteria, and the session-creation call takes an
`agent` parameter that loads them; every lane on 2026-08-21 was launched without it, with a
hand-written approximation in the prompt instead — which **grew longer with each launch** as the
day's lessons accumulated, and that is what made it feel sufficient. Nothing failed, which is
the whole difficulty: a substitute that works emits no signal, exactly like a recount that stays
internally consistent after a deletion. **When this repository has a mechanism for a thing,
prose describing that mechanism is not that mechanism** — and using the mechanism feels like
more effort rather than less, which is why nobody catches it. **And the rule above is
insufficient on its own, because a mechanism can itself be prose asserting an enforcement**:
`.github/agents/frontend.md` stated *"surface parity is a hard rule, enforced by test"*, and no
such test exists — `surface-parity-tests` is pending behind three pending dependencies, and the
one non-dashboard surface in the tree (`userscript/`) is capture-only, so the test is not merely
unwritten but **unwritable, since there is no second decision surface to compare against**.
`plan.md` and `bridge.md` carried the same claim. So *use the mechanism rather than prose
describing it* is right and incomplete; **a definition is not self-verifying, and an enforcement
claim is checkable in one grep** — do that before relying on it. And grep **even when the file
appears to hedge**: proximity is not comparison. Two files invite a diff; one file invites reading
in order, and the confident sentence arrives first — `frontend.md` carried both versions eleven
lines apart, and the hedge is what a careful reader finds *after* acting on the unhedged one.
**The same grep is what makes a correction complete**, because a claim is corrected in the
document that argues it while the files merely *citing* it go untouched — and those are invisible
from inside the document, which is why the fix feels finished. Correcting one of parity's three
sites would have left two; after any correction, grep the distinctive phrase or numeral across
`docs/` and fix every copy or say why one differs.

**Rhetorical convenience has no gate, and on 2026-09-06 one agent made the same move four
times in one day.** The shape is constant: *reach for the artefact or the assertion that is
easiest to name, or that sounds most serious, rather than the one actually in play.* (1)
`direct_url.json` was made the authoritative signal for an editable install because pip
documents it — when `_editable_impl_*.pth` is what actually mutates `sys.path`, and a stale
one had been serving another worktree's bytes underneath a green guard. (2) A counterfactual
sha256 was published as proof that a manifest generator resolves by path; the hex came from a
local ref named `pr171`, a stale fetch, while the branch actually on disk produced the
manifest's own value — so there was no counterfactual, only a ref chosen because its name
matched the pull request. (3) An evidence artifact showing that admitted sources cannot
construct *one protocol's* denominator was reported as proof that purchasing a feed was the
only route to a calibrated forecast, and that such work could not finish before 18 October.
It addresses neither question.

**Note which of those a machine caught.** The first was caught by the live environment and the
second by its author eleven minutes after pushing; both were claims about bytes, and bytes can
be re-read. The third was unfalsifiable by any test in this repository and was caught by a peer
session reading the argument. That asymmetry is the case for a separate review thread existing
at all, and it is why this section cannot be replaced by a fifth gate: the failures that reach
the owner are the ones no runner can execute.

**And precision is not evidence.** What carried the second one past its author's own review was
a full sha256. An exact value signals that *something* was measured without saying what, and it
reads as more rigorous than the hedge it displaced — the hedge being, in that case, correct.
Treat an unexplained exact number inside an argument as an unsupported claim wearing a lab coat,
and ask which command produced it before crediting it.

**The fourth instance is the one with a mechanism behind it, because the corrective already
existed and went unread.** `docs/handoff.md:37185` — written the same day, by the thread that
owns owner intent — records that neither *"nobody gives that away free"* nor *"a calibrated
model cannot be ready by draft day"* was established, and `:37215` warns specifically against
treating the availability veto as proof that every other path is impossible. Instance (3)
asserted both, hours later. Its author had read the file's tail and appended **fifteen further
entries after that line** without ever reading it. `AGENTS.md` instructs every agent to read
`docs/handoff.md`; the file is **38,139 lines and 473 entries across 20 dates, 41 of them dated
2026-09-06 alone**. That instruction is not followable as literally written, so what everyone
actually does is read the tail — and the tail is not where the ruling on your particular claim
lives. Writing it down and reading it have become separate problems, and only the first has a
rule.

**The index already exists and nothing points at it.** `grep -n '^## 2026-' docs/handoff.md`
returns 473 subject lines, eighty times smaller than the file, needing no new artifact and unable
to go stale because it is derived rather than maintained. Grep it for your subject *before*
asserting something the project may already have ruled on — the same move as the correction-grep
above, run before the claim instead of after it. **That sentence was wrong when first written,
which makes five.** It said `'^## '` and 473, asserted rather than run; the loose pattern returns
**477**, because the file opens with a two-line format template and two entries use `##` for an
internal subheading, breaking the one-heading-per-entry invariant the count depends on. It was
caught by running the command while checking the paragraph three lines above it, which is the
only reason this one cost nothing. **A number inside an argument is worth exactly the command
that produced it, and if you cannot name that command you are quoting your own expectation.** **What it will not tell you is who ruled.** Two
sessions currently write entries headed `- architect -`, interleaved in one file (`:37331`,
`:37362`, `:37384`, `:37457` are the decision thread's; `:37876` onward are the delivery
thread's), so a heading fixes date and subject but not authority. Add the role to new headings
if that matters; do not rewrite 473 existing ones to backfill it, because the attribution is
recoverable from the prose and the diff would be larger than the problem.

**Which makes this the least reliable section in the repository, and it should say so.** It is
the one part with nothing executable underneath it, and the class it documents is *believing
that having written something down changes behaviour*. If a rule here matters, the useful next
step is to check whether a mechanism for it already exists — and only then, if none does, to
find the cheapest one that enforces it and file that, the way the two items in *A true signal
with no consumer* were filed instead of written up.

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

### The import you got is not the tree you are in

Added 2026-09-06, found live rather than reasoned about. From the main checkout at
`4b5e72f6`, `import hoops_gm` resolved to
`copilot-worktrees/hoops-gm/sr2501-bookish-barnacle/backend/src/hoops_gm` - another
worktree, on the unmerged and **red** #171 branch. The editable install is a
machine-global singleton: whichever worktree last ran `pip install -e` owns the name
for every checkout on the machine, including the canonical one. This is the mechanism
behind three false diagnoses in a single night, one of which got as far as replacing
working code - a lane concluded `alembic`'s `command.stamp` was defective and rewrote
it before withdrawing the claim.

It is worse than the already-documented deleted-worktree case, and the asymmetry is the
point: a **deleted** target raises `ModuleNotFoundError`, which is loud and immediately
suspicious, while a **live sibling** silently supplies another branch's bytes and every
failure it produces looks like a real bug in your own change.

- **Verify by content, not by path.** `module.__file__` tells you what the loader
  resolved, which is necessary and not sufficient - it cannot distinguish a correct
  path from a correct path serving stale or partially-installed bytes. Assert the
  code you are running, not its address.

  **Do not reuse the probe below; derive a fresh one.** On 2026-09-02
  `hasattr(parsers, "_EARLIEST_PLAUSIBLE_TIPOFF_HOUR")` returned `True` while
  mis-pointed and `False` from `main`. Both halves of that have since expired:
  two sibling worktrees descended from the same work and *both* carried the
  symbol, and then #171 merged (`b96f4782`) and put it on `main` as well, so it
  now returns `True` everywhere. **A content probe has a shelf life measured in
  merges.** It must discriminate the trees that are candidates *today*, and
  merging is what silently retires one. Cheaper and stable: compare
  `git rev-parse HEAD:<path>` in each candidate tree - blob ids are content
  addresses that cannot go stale, and if two candidates share a blob then no
  content probe over that file can separate them, which is itself the answer.

  **The same durability question applies to how prose cites code, and there the
  answer is free.** `docs/` carries **245** `path:line` citations across 16 files.
  120 are in `handoff.md`, where they are frozen historical claims and must not be
  corrected - the entry is a record of what was true when it was written. The rest
  are read as current guidance, and a line number drifts on the next edit above it,
  silently pointing at whatever moved into its place. **Cite the expression as the
  address and the line as a hint**: `--repo-root` defaults to `Path("..")` is still
  findable by grep after any drift, where a bare `:1581` is not. No checker is
  proposed - the durable form costs nothing to write, and a test over 245 citations
  would be more machinery than the failure it prevents, which is one wasted grep.
- **The blast radius is evidence, not only tests.** `capture_schedule_grid_contract.py`
  and `capture_openapi.py` both import the package. Regenerating either from the main
  checkout while mis-pointed would have recorded another branch's tree *as* `main`'s
  contract - the drift detector faithfully capturing the drift, and committing it as
  the reference everything later is compared against.
- **No gate can ever see this.** CI installs per job into a clean environment, so it is
  green on the branch and green on `main`; the discrepancy exists only on the
  developer's machine. This is the rare failure where local evidence outranks CI, and
  where "but CI is green" is not merely weak, it is structurally incapable of speaking
  to the question.
- **Fix applied, and its limit.** `cd backend; python -m pip install -e . --no-deps`
  repointed it; full-suite `--collect-only` then exited 0 with zero import errors and
  no `PYTHONPATH` pinning. That fixes today's instance, **not the class**: the next
  `pip install -e .` from any worktree re-hijacks every checkout, silently. Pinning
  `PYTHONPATH` protects a command; it does not protect a machine. Per-worktree virtual
  environments are the structural fix and are not in place, which is why this trap has
  now recurred often enough to be documented three times and fixed once.
- **A guard now exists, and its worth is entirely local.**
  `backend/tests/test_import_provenance.py` resolves the package **in a subprocess
  with `PYTHONPATH` stripped** and fails when the answer is not the tree the test
  file lives in. Both halves matter: a subprocess sees what a fresh command sees
  rather than what an already-configured interpreter has, and stripping
  `PYTHONPATH` removes the mask that hides the hijack from the very tests meant to
  catch it - our own invocation pins it, so an in-process check passes through the
  path entry while the mis-pointed install waits underneath. Proved against the
  real condition rather than a simulated one: repointing the `.pth` at the sibling
  worktree makes it fire and name both trees, and restores byte-identical. Six
  mutants, six caught. What it does **not** change: **CI still cannot see the
  hijack**, and the test is green there whatever the developer's machine looks
  like, because CI installs from the checkout it is testing - a test whose entire
  value is realised outside CI, which is unusual enough to say out loud.
  Per-worktree virtual environments remain the structural fix; this only makes the
  class **loud** instead of silent.
- **The first version of that guard read `direct_url.json`, and was wrong within
  the hour.** It is recorded here rather than quietly rewritten, because the
  mistake is more instructive than the fix. `direct_url.json` is pip's record of
  the last install's *intent*; the file that actually puts a directory on
  `sys.path` is `_editable_impl_hoops_gm_backend.pth`. **They can disagree, and
  here they did**: the metadata named the main checkout while the `.pth` named
  `sr2501-bookish-barnacle`, an unmerged branch, because a stale `.pth` outlived a
  later reinstall. So the main checkout was executing another branch's bytes while
  a brand-new test asserting import provenance sat green beside it. This is
  `AGENTS.md`'s *validation of form cannot catch errors of meaning* with a
  different field: well-formed, accurate about what pip was told, and not an answer
  to the question asked. **A declaration is not an effect.** Where a mechanism has
  a record and a runtime artefact, test the artefact, and if you test the record,
  test that the two agree - the disagreement is the bug's actual signature.
- **The consequence reached a live session, and the correction was worse than the
  error.** Warning the session regenerating #171's manifest, I offered
  `hasattr(parsers, "_EARLIEST_PLAUSIBLE_TIPOFF_HOUR")` as the content probe, from
  this file. It cannot discriminate here: the symbol was present on *both*
  candidate trees, since both descend from the same #171 work, and hours later
  #171 merged and put it on `main` too. The probe would have returned `True` and
  told a session running foreign bytes that it was fine. **A content check is only
  decisive against the candidates that are actually in play**, and the ones in play
  are whichever worktrees exist today, not the two the original incident happened
  to involve.
- **The #171 hazard did not land, and my first explanation of why was wrong.**
  What is verified: the merged manifest records
  `79cd1b9332a181fb633583403d47fd8897a8a6e573fc42a440d5823ddf85d8a7` for
  `parsers.py`, which is the LF-normalised hash of `main`'s file. **The manifest is
  correct.** What is *not* established is any claim about how the generator
  resolves sources, and I published one anyway.

  The error is worth more than the finding. I asserted a sharp counterfactual -
  that import resolution would have recorded `49e4ec50...` - and derived it from
  the local ref `pr171`. But the hijacking `.pth` named a **directory**, so the
  bytes actually served were whatever sat on disk there, and `pr171` was a stale
  fetch pointing at `f781a402`, an earlier state of the same pull request. The
  directory in question, `sr2501-bookish-barnacle`, is checked out to
  `sr2501-boxscore-date-plausibility-bound` - **the #171 branch itself**, carrying
  the very commit that refreshed the manifest. Its on-disk `parsers.py`
  LF-normalises to `79cd1b93...`, the same value. Import and path resolution
  therefore agree here. **There is no counterfactual, and the experiment cannot
  distinguish the two.**

  This is the same mistake as reading `direct_url.json` instead of the `.pth`,
  committed twice in one session, the second time while writing the bullet above
  warning against it: **choosing the artefact that is easy to name over the one
  actually in play.** `direct_url.json` because it is documented; `pr171` because
  it is named after the pull request. Note what made it persuasive - a full
  sha256. **Precision is not evidence.** A hex string makes a claim look
  checked, and this one was checked against the wrong object. When a hijack is
  defined by a path, resolve the path; a ref that shares its name is a different
  object that happens to sound right.

  **Settled afterwards by reading the generator, which is what should have
  happened first.** `cohort_evidence.py:1287` fingerprints
  `repo_root / relative`; the package is never imported to locate its own
  sources. It does resolve by path. The conclusion was right and the reason was
  invented, and those are different things - a correct answer reached from a
  fabricated counterfactual will not survive the next question asked of it.
- **The equivalent defect one layer over is `cwd`, and no import guard can see
  it.** `cohort_evidence.py:1581` defaults `--repo-root` to `Path("..")`, a
  *relative* path resolved against the working directory. Run the generator from
  the wrong tree's `backend/` and it fingerprints that tree, with `sys.path`
  entirely correct and no import involved. `_source_fingerprints` refuses when a
  declared source is missing under the given root, which catches a root pointing
  somewhere unrelated - and catches nothing when the wrong root **also contains
  the file**, which is exactly the sibling-worktree case and the only one that
  occurs here. **Generators that fingerprint sources should take an absolute root
  derived from their own location, or refuse a relative one**; the failure is
  silent, well-formed, and lands in the artefact everything later is compared
  against.
- **A hash comparison is only meaningful if both sides normalise alike, and on
  Windows the default tool does not.** Checking the above, `Get-FileHash` on the
  working copy returned `f2b85835...` against the manifest's `79cd1b93...` and
  looked exactly like the defect being hunted. `parsers.py` is stored LF and
  checked out CRLF, 55,883 bytes on disk against 54,596 in the object store; the
  manifest hashes LF-normalised content, which is the right choice because it
  makes the fingerprint platform-stable. The mismatch was the measurement, not the
  artefact - the same shape as `gameEt`: a well-formed value answering a question
  adjacent to the one asked.


### Ahead-of-origin is not a measure of unmerged work

**Recorded 2026-09-06, after it produced a false rescue and an owner-facing
report that had to be retracted.**

Sweeping ten worktrees before archiving them, one branch reported
`git rev-list --count origin/main..<branch>` = 3. Read as "three commits of
unmerged work", it looked like content about to be destroyed. It was not.
`git cherry origin/main <branch>` marked all three `-`, and every file in the
delta was byte-identical to `main`. The work had merged hours earlier.

**Why the number lies.** This repository squash-merges. A squash rewrites a
branch's commits into one new commit with a new hash, so the originals are
never ancestors of `main`. **Every fully merged branch in a squash-merging
repository reports a non-zero ahead-count, permanently.** The count measures
SHA reachability, which after a squash is guaranteed to disagree with content
presence. It is not a weak signal; for this workflow it is a broken one.

**Use patch-equivalence instead.**

    git cherry origin/main <branch>     # '-' already present, '+' genuinely absent
    git diff origin/main <branch> -- <delta paths>

`git cherry` compares patch-ids rather than hashes, so it survives the rewrite.
A content diff of the changed files answers the same question and is the check
to reach for when you are about to destroy something.

**The trap has a matching twin, already recorded above:** a clean working tree
(`dirty=0`) says nothing about whether commits exist elsewhere. So the two
obvious pre-deletion checks fail in opposite directions - `dirty` under-reports
risk, ahead-count over-reports it. Neither is a safety check. Only comparing
content is.

**What this cost:** a preserved remote ref nobody needed, a backlog item filed
for gates and review that were never required, and a false claim in a commit
message and an owner report. What it would have cost to avoid: one command.


### A paraphrase of a gate is a new gate, and nobody reviewed it

**Recorded 2026-09-06. Found by a lane, in the coordinator's own instructions -
mine.**

A lane reported its Code gate green and it was not. It had not run `mypy` at
all. It was not a stale-head read and it was not carelessness: **the kickoff
prompt I wrote listed the Code gate as exactly three commands** - `ruff check`,
`ruff format --check`, `pytest` - and the lane ran precisely those and got
green. `gates.md` defines the Code gate as lint clean, **type-check clean**,
tests green. *Type-check clean was dropped in the restatement.* The lane
followed the instruction it was given. The instruction was wrong.

**The general form.** Restating a gate in a prompt creates a second definition
that looks authoritative, travels further than the original, and is reviewed by
nobody. The lane cannot tell a complete restatement from a lossy one, because
the paraphrase is the only version it sees. Every lane briefed from that prompt
inherits the same hole, silently and identically.

**This entry is an instance of the one above it.** *Naming a defect class is not
a mitigation* - and the class was already named here, in the entry about running
one gate and reporting another. It was written down, and I committed it anyway,
in the act of briefing lanes on how not to. A rule the person writing the
prompts does not re-read is not a control; it is a record of an intention.

**Damage, bounded rather than assumed.** `ci.yml:96` runs `mypy` inside the
`backend` job, so the full gate ran on every pull request regardless of what any
prompt said, and no merge could bypass it. `main` verified directly at
`b8fb1916`: `Success: no issues found in 267 source files`. The cost was wasted
cycles and one false local green, not merged defects. **The mitigation held
because of how CI was designed, not because of any care taken here** - if the
dropped item had been one CI does not independently enforce, this would read
differently.

**The obligation, both directions.** A lane treats a handed-down command list as
a starting point and re-derives from this file before reporting green. Whoever
writes the prompt **cites the gate rather than restating it** - a path and a
section name, never a command list. The prompt is allowed to say which gate
applies. It is not allowed to say what the gate is.


### A green check is a verdict on a tree, and you must prove it is yours

**Recorded 2026-09-06 from two lane debriefs, both executed.**

Two independent ways a passing CI result describes something other than the code
you are about to merge. Neither reports an error; both look exactly like success.

**1. The watched merge ref goes stale under you.** `gh pr checks --watch` exits
successfully for the merge ref it *began* watching, even if `main` has since
moved. The green is real and it is about a tree that no longer exists. The
mechanical check, which is cheap and should be run immediately before every
merge: fetch `refs/pull/<N>/merge`, read its parents with
`git rev-parse '<ref>^@'`, and **require current `origin/main` to be one of
them**. If it is not, the result is stale and re-running the same ref cannot fix
it - only a push or rebase recomputes the integration bytes.

**2. A run is not the check set.** `gh run view` and `gh run watch` observe **one
workflow run**. A lane generalised two runs' 22 outcomes to a pull request that
had **26** checks, and reported readiness on a denominator that was missing four.
Merge readiness must come from `gh pr checks <N> --json name,state,workflow`,
with every returned row accounted for - and **a permitted skip is not a
success**, it is a row that must be counted and named as skipped.

**Why these belong together.** Both are the same error wearing different
clothing: *a true statement about a smaller thing than the one you are deciding
about.* The watch result is true of an old tree; the run result is true of a
subset of checks. Neither is a lie, and neither is an answer to "may I merge
this".

### Zero and false are values, and a predicate that accepts them counts nothing

**Recorded 2026-09-06. Two mechanisms, both found by the lane that wrote the
predicate, before either shipped.**

**`bool` is a subclass of `int`.** `isinstance(True, int)` is `True`, so a field
validator admitting "any integer" admits `True` as the count **1** and `False` as
the count **0**. A denominator of `True` satisfies a type check and then
satisfies almost any ratio. The predicate now uses `type(value) is int`
deliberately, and `type(value) in (int, float)` for shares, precisely to refuse
booleans.

**A zero-filled report passes a ratio bound vacuously.** With every count set to
`0`, the coverage test `0 * 100 <= 0 * 5` is **true**, so a report describing no
data at all reads as fully compliant. The fix is not a better bound: counts must
remain `null` when the denominator does not exist, and evaluation must **raise
before the arithmetic**, emitting a not-evaluable status rather than a pass.

**This is the fourth confirmed member of the vacuity family** and the first
caught before it shipped, which is the whole point of writing the others down.
The others: `check_append_only` comparing a file to itself after a push; an
empty slate satisfying `enforce_expected_game_coverage` under a mislabelled
`"Playoffs"` season; the secret-scan positive control. **The shape is always a
predicate that is satisfiable by absence** - and it is never visible in the
predicate's own result, only in its denominator.

### A status format that varies defeats the tool that reads it, including you

**Recorded 2026-09-06, after getting this wrong in the act of checking it.**

`docs/decisions/` carries two spellings of the same field: `**Status:** Proposed`
and `- **Status:** Proposed`. Recounting ADR statuses to correct a figure in an
owner report, I used a pattern anchored on the first form, and it silently
skipped every file using the second - then matched an **amendment's** status
line further down those files instead. The result was a confident wrong count
that also invented a defect ("ADR-017 has no Status line") in a file whose line
3 plainly reads `- **Status:** Proposed`.

The number reported to the owner was **8 Proposed ADRs**. The true figure,
re-derived by reading the first `Status` line of every file, is **6** - ADR-014,
015, 017, 018, 019, 021 - plus Proposed *amendments* inside ADR-008 and ADR-019,
which are a different thing and must be counted separately because they are
accepted independently. `ADR-016` does not exist at all; the sequence has a gap.

**Two rules, and the second is the one that keeps being learned.** Normalise the
field so one pattern matches all of it. And **a derived count is a claim about a
file, so read the file**: the failure here was not the regex, it was reporting a
regex's output as a property of the corpus without opening a single one of the
twenty documents it described. `scripts/check_adr_index.py` is still unshipped
and five working implementations sit in trial tags; it would have caught the
format split, the numbering gap, and a hand-edited index row on the same run.


### Two thresholds shipped in one night, both chosen, neither derived

**Recorded 2026-09-06 from two lane debriefs. Both lanes volunteered it; neither
was caught by a gate, because no gate looks.**

- `preseason-news-ingest` ships a **336-hour** freshness bound. Its author:
  *"chosen, not derived"* - it preserves an existing 14-day judgement so the
  production command and the live smoke do not disagree. It is a stalled-source
  alarm, not a claim that 13-day-old news is decision-current.
- `vitest-explicit-timeout` ships a **10,000 ms** per-test timeout. Its author:
  *"chosen, not derived... should not be described as empirically calibrated."*

Both are defensible, both are documented, and both are honest **because the
authors said so unprompted**. That is the problem. A number reaches production
through the Code gate with no obligation to declare its provenance, so the only
thing standing between a placeholder and a load-bearing constant is whether its
author happens to mention it in prose nobody is required to read.

**Why this is not pedantry.** A chosen threshold and a derived one are
indistinguishable in the diff, in the tests, and in the config file. They differ
only in what happens when the world moves: the derived one degrades predictably,
the chosen one is wrong in a direction nobody characterised. `10_000 ms` picked
against a quiet machine is wrong the first time CI is busy. `336` hours near an
auction admits a latest item that is operationally useless while exiting zero.

**The rule.** A constant that gates a decision, a refusal, or a report carries a
one-line provenance note at its definition: **derived** (and from what) or
**chosen** (and what evidence would derive it). This is deliberately not a new
gate - the Model gate already demands calibration for numbers a decision rests
on, and these sit just outside it. **If a third one lands, make it a gate**, and
note that the reason to hesitate is that a provenance comment nobody enforces is
itself a chosen threshold on how much process is worth it.

### A timeout only bounds what has already started

**Recorded 2026-09-06.** Vitest's `testTimeout` starts counting when Vitest
starts a test. An infinite loop in **module import, test collection, or worker
startup** happens before that timer exists and hangs the process indefinitely -
the per-test timeout cannot fire because no test is running.

What actually catches it is the enclosing CI job's `timeout-minutes`, which is
why PR #175's ceiling on all 11 jobs and PR #174's per-test bound are **not
redundant**. They cover disjoint failure regions: the job timeout is the only
backstop for pre-execution hangs, and the test timeout is the only thing that
localises a hang to a named test. Neither substitutes for the other, and a
reviewer who treats the second as covered by the first will remove the wrong one.

**The general shape:** every timeout has a *start condition*, and failures before
that condition are invisible to it. When adding one, state what must already
have happened for it to be able to fire.


### "Docs-only" means safe, except where the doc is the gate

**Recorded 2026-09-06, from applying the stale-merge-ref check above to PR #171
and then nearly waving the result through.**

The check fired correctly: #171's `refs/pull/171/merge` had parents `61f3dd72`
and `65f5d5dc`, while `origin/main` had moved to `de5762b7`. Five commits of
drift, so any CI verdict on that ref describes an integration that no longer
exists, and the branch must be rebased before merge so the ref recomputes.

The tempting next step is to measure the drift and dismiss it. I did measure it:
**seven files changed, all under `docs/`, zero executable or test files.** By the
usual reading that makes the stale ref harmless - no code moved, so no test
outcome can change, so re-running would produce the same green.

**That reading is wrong here, and the reason generalises.** One of those seven
files is `docs/decisions/ADR-019-cohort-fingerprint-boundary.md` - *the document
that defines the gate blocking #171*. Main's drift changed the rule the pull
request is being judged against, while changing nothing the test suite executes.
The CI result would indeed be identical; the **merge decision** would not.

**So separate the two questions instead of collapsing them.** *Would re-running
change the checks?* is answered by whether executable files moved. *Would
re-deriving change whether I may merge?* is answered by whether any governing
document moved. In a project whose gates live in Markdown, a docs-only diff is
exactly the diff most likely to change the second answer while leaving the first
untouched - and a reviewer who has learned to skim past `docs/` will see a green
tick and a harmless diff and merge against a rule that changed underneath them.


### A shell check that fails prints nothing, and nothing reads as clean

**Recorded 2026-09-06. Fifth confirmed member of the vacuity family, and the
first at command level rather than inside a predicate. It happened to me, inside
the verification step, which is the worst available place for it.**

I was checking whether PR #171 regenerates the cohort manifest - the one thing
that would corrupt the evidence ADR-019 rides on. The check was:

    $hits = git diff --name-only $mb..origin/BRANCH | Where-Object { ... }
    if ($hits) { $hits } else { "NONE - manifest untouched by this branch" }

It printed **`NONE - manifest untouched by this branch`**, and that is the answer
I wanted. It was also meaningless. PowerShell parsed `$mb..origin/BRANCH` as a
property access on `$mb`, so `git diff` received a malformed argument, printed
its usage text to stderr and exited non-zero. `$hits` was empty because **the
command never ran**, not because the branch is clean. Re-run correctly, the
answer happens to be the same - two files, zero manifest files - which is exactly
why this is dangerous: a wrong method that agrees with the truth teaches you to
trust the method.

**The four earlier members were predicates satisfiable by absence. This one is a
command whose failure is indistinguishable from its success**, because both
produce no output and the conditional only tests output. Every `if (-not $x)`,
`if ($x.Count -eq 0)` and empty-list-means-clean shape in a verification step has
this hole.

**The fix is two assertions before the conditional, not a more careful pipeline.**
Assert the command succeeded (`$LASTEXITCODE -eq 0`, and `throw` if not, because
a failed check is not a passing check), then assert the *unfiltered* collection is
non-empty, because a diff of a branch with commits on it cannot legitimately be
empty. Only then is an empty *filtered* set evidence of anything. The rewritten
form threw on both conditions and returned a count I could stand behind.

**The general shape: never let the absence of output be the success signal.**
Prove the instrument ran and saw something before you believe what it did not
see.


### The append-only gate is non-vacuous in exactly one window: after commit, before push

**Recorded 2026-09-06. This closes a previously abstract entry with a concrete
procedure, discovered by running the gate at the wrong moment twice in a row.**

`scripts/check_append_only.py` compares `docs/handoff.md` at the merge-base
against the same file at `HEAD`. Both are **committed** blobs. The working tree is
never consulted. That gives three moments and only one of them tells you anything:

- **Before committing** the gate reports `appended: +0` no matter what is sitting
  unstaged in the tree. I had just written 4,186 bytes and it printed `+0`,
  `CONTAINMENT: True`, `OK`. Every field was green and none of them described my
  change.
- **After pushing**, `merge-base` and `HEAD` converge on the same commit, so the
  file is compared to itself and the gate is green for the same empty reason.
- **After committing and before pushing**, `merge-base` is still `origin/main`
  while `HEAD` carries the new commit. Re-run in that window the same gate
  reported `+4186`, `CONTAINMENT: True`, `CR 312 -> 312`, which is a claim about
  the change and can be false.

**So the sequence is `commit` -> `check_append_only.py` -> `push`, and running it
anywhere else is theatre.** A green from the other two moments is not weak
evidence, it is no evidence: the number it prints is `+0` because there is nothing
in the comparison, and `+0` bytes appended trivially satisfies append-only.

Note the script is honest about a second, separate vacuity in its own negative
controls - it prints `NEG truncated base: True, and VACUOUS / 200 bytes vs base
2421278`, telling you that control passes for a trivial size reason rather than
because containment logic worked. **A tool that labels its own weak checks is
doing the thing this whole file exists to encourage**; the fix is to keep that
label visible, not to quietly make the control pass.


### Disclosing that evidence is unreachable is not preserving it

**Recorded 2026-09-06, found by resolving every file path cited in
`docs/models/*.md` rather than reading the cards. 13 cards, 39 path citations,
2 unresolved.**

`docs/models/injury-status-conversion-preregistration.md` is committed in `main`
and cites `backend/tests/model_evidence/injury_status_conversion_v1_rows.json`.
**That file is not in `main`.** It exists on one unpushed local branch,
`sr2501-injury-status-conversion` at `3285e647`, at 594,951 bytes and 1,934
records carrying status, participation outcome, game date, lead time and
exclusion reason for a **shipped** model whose module, evidence JSON, model card
and backtest are all in `main`.

**The document already says so, and says it well** - it discloses that the rows
"were never pushed" and that "no reader with only `origin` could have found it".
That is the honest-limitation habit working exactly as intended, and the author
deserves the credit. **The defect is not concealment. It is that disclosure and
preservation were treated as the same act.** A written note that something is
unreachable does not make it reachable; it makes the *loss* legible after the
fact, which is worth much less than the note appears to be worth when you read it.

**Concretely: one pruned worktree destroys the row-level evidence behind a model
that is already making decisions, and the surviving artifact is a paragraph
describing what used to be checkable.** Nothing in the repository would fail. The
backtest reads `injury_status_conversion_v1.json`, which is present, so the suite
stays green and the model gate stays satisfied while its held-out rows cease to
exist.

**Why nothing caught it.** No check resolves the paths a model card cites, so a
card can name a file that was never committed and render identically to one that
was - the same defect class the ADR index item exists to close for
`docs/decisions/`, unaddressed one directory over. The 39-citation scan above is
about twenty lines and found this on its first run.

**Do not fix this by reflex.** The rows unblind the held-out split, and this
repository is public, so pushing them preserves the evidence and destroys the
blind permanently. That tension is real and the resolution is owner-only, which
is precisely why it must be surfaced as a decision rather than settled by whoever
notices it first.


### A count can be true and describe a different population than the one it implies

The secret scanner prints `No secrets found in 586 tracked files`. It did not
examine 586 files. `N` is the length of `tracked_files()` - the enumeration - and
is fixed before allowlists, suffix skips, non-file entries and decode failures
remove candidates from the read set. Three tracked gzip fixtures -
`nba_gleague_transactions.json.gz`, `nba_player_movement.json.gz` and
`rotowire_nba_news.xml.gz` - count toward 586; `.gz` is not in `SKIP_SUFFIXES`;
`read_text("utf-8")` raises `UnicodeDecodeError`; the handler continues silently.
**A real secret in any of them is counted and never read**, and those files are
recorded captures from external APIs, which is precisely where a credential would
arrive if one ever did.

The number is not wrong. The sentence around it is. Nothing in the output
distinguishes *enumerated* from *examined*, so the reassurance scales with the
repository while the coverage does not, and the gap widens every time a binary
fixture is added.

**Rule: a headline count must name the population it counts, and a scan must
report skips as a separate number rather than folding them into the total.**
`586 enumerated, 3 unreadable, 583 examined` is the honest form and costs one
line. Filed as `secret-scan-counts-what-it-did-not-read`, which records the
verified counts. This is the sixth member of the vacuity family and the first
where the predicate is not satisfiable by absence - it is satisfiable by
*silence*.

### A red test is not evidence unless the red is attributable

Mutation-testing the secret-scan fixture isolation meant pointing the test back
at the committed fixture and confirming it fails. It failed twice for the wrong
reason: first at `mkdir(..., exist_ok=False)` with `FileExistsError`, then, once
that was relaxed, at same-file `shutil.copyfile` with `SameFileError`. Both reds
look exactly like a passing mutation check. Neither one exercised the
checkout-safety boundary the test exists to enforce.

The fix was ordering: assert `not fixture.is_relative_to(REPO_ROOT)` *before* any
filesystem operation, so the mutation trips that assertion rather than an
incidental error further down. Only then is the red attributable.

**Rule: when mutation-testing, read the failure, not the exit code, and record
which assertion fired.** A mutation that dies during setup has tested your setup.

### A cited line range is not stable under edits it does not contain

The opportunity-coverage evaluator hashes cited line ranges after LF
normalisation, which makes a citation portable across CRLF checkouts and immune
to appends *beyond* the range. It is not immune to insertion *before* it:
inserting one line above a cited passage leaves the passage byte-identical and
changes which bytes the fixed numeric range selects, so the digest fails.

**Stability was justified for exactly one file and one reason** -
`docs/backlog.md` is append-only and the cited passage precedes the append point.
That argument does not generalise. A citation into any file that can be edited
above the cited lines will break for reasons unrelated to its content.

A sharper limit sits underneath it: normalisation rewrites only CRLF and lone CR,
while `bytes.splitlines()` also splits on vertical tab and form feed. A cited
file containing either is indexed differently by the helper than by an editor
counting newlines, and nothing prohibits such a file.

**Rule: cite by content where content is stable, and by line range only where the
file's own contract forbids edits above the citation - and name that contract in
the citation.**

### Validating the shape of provenance is not validating the provenance

The same evaluator requires five 64-hex digests and two 40-hex commit
identifiers, lowercase, correctly typed, arithmetically reconciled. A report
satisfying every one of those constraints can still be fabricated: the hashes
need match no artifact, the commits need not exist, the freeze commit need not be
an ancestor, and the two reconstruction implementations need never have run. The
evaluator opens no file, recomputes no hash and queries no ref.

That is a defensible boundary for a *predicate evaluator*. It has to be stated
where the guarantee is read, because "provenance validated" and "provenance
checked against the repository" are the same words to a tired reader at 3am.

**Rule: a validator that checks form must say so in its own output.** This is the
house rule about self-describing fields - `gameEt` claiming a `Z` it does not
have - turned around and applied to artifacts we produce ourselves.

### A denominator reconstructed from the numerator flatters itself

Rejected during the coverage preregistration, and worth keeping precisely because
it is the attractive wrong answer. Roster membership is the missing denominator;
box scores and appearance rows are present, and reconstructing membership from
appearances is one query away. It yields a coverage report with a reassuringly
small `unknown` share - because every player it can see played, and every player
it cannot see has been defined out of the population rather than counted as
unknown.

**The unknown share is the exact quantity the preregistration exists to
constrain.** Deriving the denominator from the observed events makes that number
a function of observation rather than of truth. The result is not merely
optimistic; it cannot come out badly, which is what disqualifies it.

**Rule: a denominator must come from a source that does not depend on the outcome
being measured.** Where no such source exists, the honest report is `null`, not a
small number. That is why the evidence-gap artifact carries
`proceed_opportunity_coverage: null` and not `false`.

### The command that reports a merge can fail after the merge succeeded

`gh pr merge 174 --squash --delete-branch` returned a local error - `main` was
checked out in another worktree, so post-merge local cleanup could not run -
*after* the API merge had already completed. The natural response, retrying,
would have operated on an already-merged PR. The correct response is to read
remote state before touching anything.

**Rule: after any failed write against a remote, query the remote's state before
retrying.** The failure mode is a two-phase command that succeeds remotely and
fails locally, where the error text describes only the half that failed. The same
call requested remote-branch deletion: the flag was passed, the deletion was
never observed, and those are different facts.


### A specimen validates the domain it chose, not the domain the model allows

The schedule-grid contract artefact serialises one hardcoded
`ScheduleGridResponse` and compares it with a recursive `_strict_equal` that
requires `type(recorded) is type(actual)`. That is a real improvement over
ordinary equality, which would have accepted `false -> 0` and `1 -> 1.0` silently
because `False == 0` and dict equality delegates recursively - the same
`bool`-is-an-`int` hazard recorded above, arriving this time through `==` rather
than through `isinstance`.

**What a specimen cannot see is a widening.** Change `game_label: str` to
`str | None` and the specimen still chooses a string, so the bytes are identical
and the check stays green. The handwritten TypeScript equality stays green too,
because it describes the domain the specimen *chose*, not the domain the model
now *allows*. The frontend meets its first `null` in a browser - which is the
exact failure the artefact was built to prevent. Adding an enum member the
specimen does not carry behaves the same way: green until it is emitted live.

Two further limits, worth stating because a consumer will assume otherwise. The
artefact never drives HTTP, so a route returning a bare dict, or middleware
reshaping the body after the response model is constructed, leaves
model-to-fixture agreement green. And no shape artefact can catch a semantic
change that preserves type - `games` beginning to mean *remaining* games rather
than *scheduled* games stays an integer, and stays green.

**Rule: a fixture-based contract test's coverage is its specimen's value set, not
its model's type domain, and the two drift apart silently.** Derive the specimen
from the model - both branches of every optional, every member of every enum -
and fail when the model declares something the specimen never exercises. Filed as
`schedule-grid-contract-domain-coverage`.


### The assertion can be right while the sentence reporting it is wrong

Recording the findings above, my own script printed `CRLF=0` for a file that had
1,043 of them and `CR 312 -> 11` for a file whose CR count had not moved. Both
numbers came from `b'\\r\\n'` inside an f-string - a four-byte literal
backslash-r-backslash-n, not a line ending. The *assertions* in the same script
used correct escapes and passed, so the file was never in danger. The
human-readable output was simply lying, and it lied in the direction of alarm.

This is the seventh member of the vacuity family and the first where the check
succeeded and the *report* failed. It is more dangerous than it looks in both
directions: had the escapes broken the other way, a corrupted file would have
printed a reassuring number produced by an expression that never examined it.

**Rule: a byte-level claim must be confirmed by a tool other than the one that
wrote the bytes.** Two minutes with an independent counter turned a suspected
2.4 MB corruption into a typo. Do not fix the file until the second tool agrees
that the file is broken.


### A citation check fails on correct documentation unless it can tell absence from disclosure

**Recorded 2026-09-06 while closing item 1 of `model-card-citation-resolution`.
This is the inverse of the vacuity family and had never been looked for here.**

Broadening the citation scan - every `.json`, `.md`, `.py` or `.csv`-shaped
string across all 13 cards in `docs/models/`, 87 distinct paths - reported
**11 unresolved**. Exactly **one** was a real defect: the v1 rows file, landed
at `41563ab5`. The other ten were not defects, and two of them were the precise
*opposite* of one:

- `injury-status-conversion-literature.md` cites
  `nba-injury-report-2025-26-status-census.json`, which is uncommitted **on
  purpose**. The card says so in the same sentence that cites it, gives the
  reason - publishing a second, disagreeing 2025-26 canonical count beside the
  committed cohort file with no reconciliation would make the disagreement
  permanent and undated - and then states the disagreement numerically so a
  reader can check it. That is the honest-limitation house rule working.
- The "unresolved" path in `injury-status-conversion.md` is
  `$env:HOOPS_GM_DATA\cohort-merged-2025-26.db.merge-receipt.json`: a
  command-line argument inside a recorded PowerShell block, naming a file in the
  owner's local data directory. It was never a repository citation.
- Seven more are `docs/models/README.md` index entries for cards not yet
  written, and one, `-PROPOSED.md`, is a filename *fragment* the regex split.

The scan's precision against real defects was **1 in 11**. Filing all eleven
would have manufactured ten phantom items - and two of them would have demanded
that a card **stop disclosing an absence it was right to disclose**. The check
would have punished the exact behaviour it exists to encourage.

**The rule: a resolution check must distinguish a path cited as evidence from
one named as absent, named as local, or named as planned.** Requiring every
filename-shaped string to resolve makes honest disclosure unrepresentable, which
is a worse outcome than the gap it closes.

Both failure directions cost the same hours. A predicate satisfiable without
doing the work wastes them silently; a predicate that fails without a fault
wastes them loudly, and additionally teaches whoever fixes it to write worse
documentation. Only the first has had a name in this file until now.

### A framing caught before it is written is not a retraction

**Recorded 2026-09-06.** Preparing the owner decision on whether to land the v1
rows, I had assembled the tradeoff as *"publishing preserves the evidence but
permanently destroys the blind."* Reading the file and its preregistration
disproved it: the rows carry no player name, no free-text reason and no source
URL, the contamination is **already disclosed by the author**, and the
preregistration's own words are that publishing is what lets a reader *discount*
it. The claim was the rhetorical-convenience failure `AGENTS.md` names - reaching
for the objection that sounds most serious rather than the one that can be
evidenced.

**Corrected the same day, and the correction is the more useful half.** The
paragraph that stood here said the framing was never written down, on the
evidence that `gates.md`, `handoff.md` and `backlog.md` do not contain it, and
it closed by recommending exactly that check. Both halves were wrong. The claim
**was** written - as the lead paragraph of the owner-facing executive summary
for 2026-09-06, which is the single most-read owner sentence this project
produces in a day. So this is a retraction, and it has now been made there.

The failure is not that three files were too few. It is that the search set was
drawn from **where claims are usually recorded** rather than **where this claim
was actually communicated**. A claim addressed to the owner lives in
owner-facing artifacts, and in this project those sit deliberately *outside* the
repository because it is public - so a repository-only grep cannot see the one
place the claim did the damage. That is the same denominator error as counting
tracked files and calling it the working tree: the method was sound and the set
it ran over was the wrong set.

**The check, restated so it would have worked:** before writing "never said",
list the audiences the claim was addressed to, then search each audience's
artifacts. If it was told to the owner, the owner-facing file is the *first*
place to look, not a place omitted because it is untracked. A grep that returns
nothing is evidence about its search path and nothing else.

### A dependency edge that resolves can still be incoherent

**Recorded 2026-09-06.** `docs/backlog.md` had `overlay-auction-panel` and
`rehearsal-harness` both depending on `blind-mocks`. Every reference resolved,
`test_backlog_graph.py` was green, and the edges had survived every prior audit.
They were nonetheless **contradictions**: `blind-mocks` states that it
*"explicitly requires the mock be run **without** this tool"*, while the overlay
panel renders a live nomination and the rehearsal harness exists to measure
whether that overlay sufficed. Neither can be satisfied by a room our tool is
absent from. The real prerequisite for both is Fantrax auction *payload shape* -
`fantrax-auction-capture`, which the backlog already held distinct at 1312-1315.

**The graph checker cannot catch this and should not be extended to try.** It
verifies that a named dependency *exists*; coherence is a claim about two items'
contents. The cheap check is to read the prerequisite's own constraints, not just
its name - and the tell is a prerequisite phrased as *without*, *blind*,
*uncontaminated* or *held out*, because a constraint of that shape usually
excludes some of its own dependents. Cost here: an owner-facing ask that
requested work already completed on 2026-08-28.

### A caveat is a claim with a shelf life, and `done` items are where they rot

**Recorded 2026-09-06.** Asked for the single highest-leverage owner blocker, I
cited `draft-tracker-bridge-feed`'s caveat that *"neither source has ever
returned a real draft payload"*. It was true when written and false when cited:
ADR-020 records 49 of 49 captures, 42 boards parsed correctly and a completed
216-pick draft, on **2026-08-28, nine days earlier**. The caveat sat on an item
marked **done**, and a done item is precisely what nobody re-reads when the world
changes - so its caveats decay silently while reading as current evidence.

**Two instances, one shape.** In the same message I described the owner's offer
to paste observations manually as covering *draft state*; he offered it for
**public news**. Both errors take a record of one thing and use it as evidence
for another, and neither is detectable by any gate - a citation is well-formed
whether or not it still holds, exactly like the `gameEt` field that is
timezone-correct and wrong. **Before citing a caveat as a live blocker, check
what has landed since it was written.** For a `done` item that means reading the
ADRs and captures dated after it, not the item.

### A test whose two possible answers are the same value has not been run

**Recorded 2026-09-06.** Asked to establish whether the cohort manifest resolves
its fingerprint sources by path or through the imported package - the step that
decides whether an editable-install hijack corrupts the artefact - I forced
imports into a sibling worktree, set `--repo-root` to my own, and got my own
tree's hash back. I nearly reported it as the disproof. It establishes nothing:
the sibling was `sr2501-bookish-barnacle`, whose `parsers.py` is **byte-identical
to mine**, so "resolved by path" and "resolved by import" predict the *same*
hash. The test would have produced that value whichever mechanism was in force.

**The fix is to establish the discriminant before the test, not after.** Repeated
against `main` *as it stood before #171 merged*, whose copy then differed
(`721e0238…` against `79cd1b93…`), the two outcomes are finally distinguishable,
and the answer is unambiguous: imports resolved to `main`, the fingerprint
computed was the repo-root tree's. Resolution is by path, via
`repo_root / relative`, so **the editable-install hijack cannot reach the
fingerprints**. It does not follow that nothing can: the `cwd` residual recorded
in the *"The import you got is not the tree you are in"* bullets above is a
different mechanism reaching the same artefact, since `--repo-root` defaults to
a relative `Path("..")` and a wrong working directory fingerprints a sibling
worktree with `sys.path` entirely correct. Import resolution is answered here;
root resolution is not.

That anchor is load-bearing, because a discriminant named by a moving ref decays.
The merge has since put the byte-identical file on `main`, so re-running the same
comparison against `main` *today* is vacuous again, in precisely the way this
entry warns about. Name the two byte-states you are separating, not the two
branch names that happened to carry them.

This is the same family as **"Before any of that, prove a test reaches the code
at all"**, in the Code gate list near the top of this file, arriving from the
other side: there the branch was never entered, here it was entered but both
branches return the same answer. **State what result would falsify the claim, and
confirm the candidates actually differ, before running anything.** A green whose
greenness is guaranteed regardless of the mechanism under test is not evidence
about the mechanism.

### `git checkout <ref> -- <path>` stages the file, and the result reads as ordinary

**Recorded 2026-09-06.** Running a control regeneration meant briefly swapping in
`main`'s copy of the file under edit. `git checkout origin/main -- <path>`
restores the working tree **and writes the index**, so after restoring my own copy
the file sat at `MM`: index holding `main`'s bytes, working tree holding mine. A
commit at that moment would have silently recorded `main`'s version of the file I
was actively editing, with the diff looking plausible and every gate green.

Reproduced deliberately in a scratch repository rather than recalled:

```
git checkout main -- file.txt        -> status 'M ', worktree = MAIN VERSION
(restore my copy to the working tree) -> status 'MM'
git show :file.txt                   -> MAIN VERSION   <- what a commit records
git reset -q HEAD -- file.txt        -> status clean, worktree edit intact
```

**Two things make it worse than a normal footgun.** The tell is `MM`, which is
one column away from the `M` of an ordinary dirty file and invisible to anyone
scanning `git status` quickly - only `git show :<path>` reveals the divergence.
And the obvious recovery is the wrong one: `git reset --hard` discards the working
tree, verified here to destroy an uncommitted edit outright. Use `git reset HEAD
-- <path>` or `git restore --staged <path>`, both of which touch only the index,
then confirm the working tree survived by content rather than by `git status`.

### Hashing a fingerprinted file by hand on Windows disagrees with the manifest, and the symptom points at the wrong culprit

**Recorded 2026-09-06.** `source_file_sha256` hashes **LF-canonical** bytes -
`read_bytes().replace(b"\r\n", b"\n")` - deliberately, so that `core.autocrlf=true`
cannot make a fingerprint depend on a checkout's newline configuration. A Windows
working tree materialises CRLF, so `Get-FileHash` and `sha256sum` on the same file
return a different digest: `f2b85835…` against the manifest's `79cd1b93…`.

**The hazard is not the mismatch, it is what the mismatch resembles.** Spot-check
a fingerprint by hand while an editable-install hijack is suspected and the
disagreement reads exactly like the hijack - wrong tree, stale manifest, another
branch's bytes - and sends the reader after a fault that is not there. It is a
false positive shaped like the true positive being hunted for at that moment.

Compare against `git cat-file blob <rev>:<path> | sha256sum`, which agrees by
construction, or hash the blob and normalise in the same step. The stronger form
verifies a committed manifest **without importing `hoops_gm` at all**: read every
recorded path with `git show <ref>:<path>`, hash it locally, compare. That check
is import-independent by construction, so it cannot be fooled by whatever tree
`import` resolves to - which is the property you want when the import path is
precisely what is in doubt. Run against `origin/main` after #171 merged, all six
recorded fingerprints matched.

### `resolve_doc_conflicts.py` destroys every CRLF in the file it is run on, and its own guard cannot see it

**Recorded 2026-09-06.** The tool lanes are told to run on a `docs/handoff.md`
conflict strips **all 312 CRLF pairs** from the file. Observed while rebasing a
docs-only PR onto `cefa313a`: an append that should have been `+159 / -0` became
`+456 / -312`, and the byte-prefix check went `CONTAINMENT False`. That is the
signature of a catastrophic append-only breach, produced by the tool run to
resolve the append - the same line-ending hazard recorded in *"Hashing a
fingerprinted file by hand on Windows disagrees with the manifest"* above, which
concerns how CRLF is treated when a file is **read for hashing**, now arriving
from the read that precedes a **write**.

**The mechanism is the read, not the write.** The writes are already defended:
`write_text(..., newline="\n")` in both `resolve_append_only` and
`resolve_backlog` (lines 258 and 459 today) carries a comment calling that
keyword load-bearing, and it is. But the reads are plain
`read_text(encoding="utf-8")` - one in `resolve_append_only`, one in
`resolve_backlog`, one in `surviving_markers`, one in `main`'s handoff scan
(212, 265, 480 and 565 today) - and Python's default text mode is **universal
newlines**, which translates `\r\n` to `\n` on the way *in*. The CR is gone
before the defended write ever sees it, and the write then faithfully commits
the loss. Measured directly: `read_text()` yields a string with no `\r`;
`read_text(newline="")` yields one that keeps it. **The line numbers here are a
convenience and the symbol names are the citation** - `scripts/` has no
edits-above contract, so per the rule earlier in this file a bare range into it
would go stale silently.

**Git is not the culprit, which is worth stating because `core.autocrlf=true` is
set here and makes it look guilty.** Reproduced in a scratch repository with
`autocrlf=true`: a blob committed with CRLF still had exactly its CRLF in the
working tree immediately after a conflicted `git rebase`, before any helper ran.
The merge machinery preserves them; the helper removes them.

**The existing guard is vacuous in this direction.**
`test_writes_preserve_lf_and_do_not_flip_the_file_to_crlf` asserts on bytes,
which is right, and asserts `count(b"\r\n") == 0` after the call - but its
fixture *starts* at zero CRLF, asserted as a precondition on the line above. A
fixture with no CRLF cannot show CRLF being destroyed, so "preserves LF" and
"strips every CR" predict the identical `0`. It guards LF-to-CRLF and is blind
to CRLF-to-LF. **This is the same-value-both-branches shape from the first entry
in this section, sitting inside the guard for this very bug class** - the fix
and its test were built facing one direction, and the mirror image walked in
behind them.

**The fix is `newline=""` on the two reads that feed a write - 212 and 265 - and
not on the other two.** I originally wrote "those four reads", which ships a
regression; `architect` caught it and I have since measured it. Lines 480 and 565
feed `surviving_markers()`, the tree-wide refusal to stage while any conflict
marker remains, and its `is_conflict_marker` (line 183) tests three markers with
`startswith` but the separator with **exact equality** - `line ==
CONFLICT_SEPARATOR`, where the constant is `"======="` (line 59). Under
`newline=""` every line retains its `\r`, so the separator arrives as
`"=======\r"` and compares unequal. Measured: the three `startswith` markers
still match, and `is_conflict_marker("=======\r")` returns **False**. With
`core.autocrlf=true` and `.gitattributes` pinning only one frontend fixture,
that is effectively every file in the tree, so the one-liner would silently
remove a quarter of what the guard detects. The same equality appears at 114 and
at 231, where `mode` never advances past `base`, so a CRLF conflict block instead
dies at the `sys.exit("unterminated conflict block; refusing to write")` on 249 -
fail-safe rather than silent, but still broken. **So the reads at 480 and 565
must not change until those three comparisons are made ending-agnostic, or the
marker scan is done on bytes.**

That correction is an instance of *"A failure message is the least-exercised line
in a green suite"*, the last entry in this section: this entry catches a read
that silently drops `\r`, and the fix it first prescribed silently dropped a
marker class. A test that would catch the original defect needs a fixture
containing CRLF, since that is the discriminant the current one lacks. Filed, not
fixed: `scripts/` is not `data-engineer`'s to change unilaterally, and the
prescription above is now two changes rather than one.

### A refused `git rebase --continue` leaves you detached, and `push HEAD:branch` hides it completely

**Recorded 2026-09-06.** `git rebase` detaches HEAD onto its target before
replaying anything. If `--continue` then **refuses** - it does that when the
resolved file is not staged, printing *"You must edit all merge conflicts and
then mark them as resolved"* - you are left sitting on a detached HEAD with the
conflict apparently resolved. Committing from there is the natural next move and
it is wrong: the commit lands off the branch entirely, and **the branch ref does
not move.** Reproduced in a scratch repository: branch at `015d05e` before,
`015d05e` after, HEAD at `48cd02e`.

**What makes it survive is the push.** `git push origin HEAD:branch` pushes the
commit rather than the branch ref, so it succeeds, the remote branch advances,
and the pull request updates and reads entirely normal. Every downstream signal
is correct. The only thing wrong is the *local* branch ref, which now silently
lags the remote - so `git checkout <branch>` hands back the superseded commit and
looks like an ordinary checkout while doing it. This went unnoticed here across
two pushes and one full gate run, and surfaced only because a later rebase
reported *"Successfully rebased and updated detached HEAD"* - a success message,
naming the defect in its last two words.

**A second copy of the same failure was still on disk from it.** The abandoned
rebase left `.git/worktrees/<name>/rebase-merge`, which makes the *next* rebase
refuse outright with *"I am stopping in case you still have something valuable
there."* That refusal is correct and it is the only loud symptom the whole
sequence produces. Check `stopped-sha` and `orig-head` in that directory against
your pushed head before deleting it; here both were the superseded commit, so
nothing was lost.

**Check `git rev-parse --abbrev-ref HEAD` after any rebase that did not end
cleanly, and compare the branch ref to `HEAD` and to the remote.** A green gate
run proves the *tree* is right and says nothing about which ref points at it.

### A failure message is the least-exercised line in a green suite and the most trusted line in a red one

**Recorded 2026-09-06.** `architect` observed this after a lane discarded a
*correct* manifest regeneration: the fingerprint test's failure message still
instructed ADR-019's superseded absolute rule - *"any other moved leaf stops for
quant, pre-unblind"* - so the lane, having regenerated properly from the data
root, read the 35 environment leaves that `quant` had already certified as not
its own, concluded it was in the stop case, and threw away good work. The
message was wrong for a day and the suite was green for all of it.

**The mechanism is that Python never evaluates a passing assert's message.**
Verified here, and it is stronger than "nobody read it": `assert True, marker()`
does not call `marker`, and `assert True, undefined_name_here` **passes** - a
message referencing a name that does not exist is green indefinitely and raises
`NameError` only at the moment of failure, replacing the diagnostic you needed
with a crash. Confirmed under pytest's assertion rewriting as well as bare
Python, since the rewriting is where one might reasonably expect different
behaviour.

**That combination is what makes it worse than an ordinary stale comment.** A
stale comment is read by someone browsing, in a neutral state, free to doubt it.
A failure message has exactly one reader: a person who has just been stopped by
a gate, is in the worst position to evaluate what they are told, and is reading
prose that carries the authority of the test itself. It is the repository's most
persuasive text and its least tested. The lane did not fail to think - it
correctly followed an instruction that had been superseded underneath it.

**The fix is to pin the message with a test that fails when the rule changes**,
which `architect` did in `8240f6f9`
(`test_the_fingerprint_failure_message_instructs_the_current_rule`,
mutation-checked).

**This trap caught me while I was writing this entry, which is the best evidence
in it.** I read the corrected message out of `origin/main` without fetching
first, and described it as current. It was already superseded: `ddc82476`
replaced its CWD clause, because *"regenerate from the data root, never from
`backend/`"* was itself an overclaim - `operational_artifacts` honours an
explicit `--report-dir`, and ADR-019 records `backend/` with an absolute
`--report-dir` reproducing the committed manifest exactly. Differentially the
requirement is that **both runs share a working directory**, not that a
particular one is used. So the first repair of a stale instruction introduced a
weaker form of the same fault, and my summary of that repair inherited it -
three generations of the error in one day. **Fetch before quoting a ref, and
cite the commit you actually read rather than the branch name**; `origin/main`
names no byte-state and was four commits stale in my working copy at the moment
I quoted it.

**What was checked here and what was not.** `ADR-\d{3}` appears **317 times
across 89 `.py` files** under `backend/src`, `backend/tests` and `scripts/`
(regex `ADR-\d{3}` over `rglob("*.py")` in those three roots, counted
2026-09-06). I first wrote "145 ADR citations", which was reproducible by no
counting method `architect` or I could construct, and named no command - the
defect this file objects to earlier under the citation rule. The only other
rule-bearing ADR-019 claim reachable from code is the published closure count of
*34 files*, recounted by `scripts/fingerprint_closure.py`; run today it reports
34, so that one has not drifted. **But that script's own docstring says it
"Reports; does not gate"**, so a future drift there would sit green in exactly
the same way. The remaining mentions were not audited for staleness, and no
general guard exists - this is one pinned message and one unpinned reporter, not
a solved class.

This is the sibling of *"a test whose two possible answers are the same value"*
above. There, a green is guaranteed regardless of the mechanism under test; here,
a green is guaranteed regardless of whether the prose is true. **Both are places
where the suite is green because nothing was asked, not because something was
answered.**


### A comparison whose operands share a source is vacuous before the test is written

Three instances on 2026-09-06, in three unrelated subsystems, none found by looking
for the others.

1. A by-path resolution test run in a tree where both candidate answers held the
   same value - the entry above.
2. A script written to confirm review fixes had landed: three of eleven predicates
   reported FAIL, every one a false alarm. The fixes **retract old wording in
   place**, so a string-presence check maps *"asserts X"* and *"retracts X"* onto
   the same result. Had its author trusted it, three correct things would have been
   "re-fixed".
3. `game_date` in ingest - the *conditional* case, and the most instructive of the
   three. `_persist_schedule_cohort` calls `import_games` and then writes
   `team_schedule.game_date` from the same `record.game.game_date`. But
   `import_games` sets `nba_games.game_date` **only on insert**, so the two stored
   columns hold independently derived parses when a box-score import created the
   game row first, and one parse copied twice when the schedule import created it.
   Nothing pins the ordering.

The entry above names the **symptom** - the two answers coincide, so the assertion
cannot fail. This names the **cause**, which is checkable before the test exists:
*trace each operand back to where its value entered the process; if the paths meet,
the comparison cannot discriminate however the test is written.* Different fetch,
different parse, or different process - one of those must hold, and if none does,
say so in the test's own docstring rather than leaving the next reader to assume
independence.

**Instance 3 is why this is not only a rule about tests - and it carries a second
lesson, because the first draft of this entry got it wrong.** There is no bad test
in ingest yet; the hazard sits in the schema waiting for one, since `import_games`
fixes `game_date` on whichever import arrives first and discards the other
derivation uncompared. What is lost is not the date, it is the detector.

But the first version of this paragraph said the cross-check *"cannot fail however
it is written"*, and that is false: it is vacuous only under schedule-first
ordering. **A comparison can be vacuous conditionally** - and then the sharper
problem is that the *passing* result is precisely the one that cannot distinguish
the two cases. Agreement between the columns is equally consistent with "derived
independently and agreed" and with "one parse written into two columns";
disagreement is informative, agreement is not. Such a test raises no false alarms
and silently loses all of its power under an ordering nobody declared, which is
worse than a test that is always vacuous, because it will have passed honestly at
least once. The fix is not a better assertion but a better operand: take the
schedule value from the payload parse, which does not depend on ordering at all.

That correction was made about an hour after publishing, by reading `importers.py`
instead of the summary of it I had written the same evening - inside an entry whose
subject is checks that claim more than they verify. It generalises the same way
`boxscore-bound-message-overclaim` does: **an unqualified "cannot" in prose is the
same defect as an over-wide assertion in code**, and neither of them has a gate.

**Instance 2 adds the polarity case.** A string-presence predicate is vacuous in
*both* directions: it cannot distinguish a claim from its retraction, so negating
it does not rescue it. When the thing being checked is prose, the check must locate
the sentence, not merely find the substring somewhere in the file.

- **A red that has been explained is still a red, and `test_import_provenance`
  spent 2026-09-06 being explained rather than read.** Added 2026-09-06. The
  import-hijack *mechanism* is already recorded three times above; this is not
  that. It is about what happened to its detector.

  Tonight, from the **canonical checkout** at `88b71053`, a full backend suite
  died in collection importing
  `copilot-worktrees/hoops-gm/sr2501-silver-dollop/backend/src/hoops_gm` - a
  **live concurrent session's** worktree, neither stale nor deleted. That is
  precisely the defect `backend/tests/test_import_provenance.py` exists to
  catch. In the hours before it, the same test's red had twice been reported as
  *"the known environmental red, already named with its mechanism"*, and I had
  myself watched it **pass** in this checkout and cited that pass as confirming
  the red was worktree-specific. It is not worktree-specific; the singleton
  moves, so a pass means only *"not hijacked at this instant"*.

  **The mechanism explanation was true, and that is what made it dangerous.** A
  correct diagnosis of one firing became standing permission to skip reading the
  next. The same red is emitted by the benign case and the real one, so the red
  alone cannot distinguish them - only the resolved path can. This is the
  shared-operand family again: two candidate causes collapsed onto one
  observation, and the habit of explaining it removed the one read that
  separates them.

  **The expensive branch is the one that did not happen tonight.** This run
  failed loudly only because the two trees had drifted incompatibly - a
  `DEMO_PLAYER_IDS` symbol present in one and absent in the other. Had they been
  compatible, the suite would have gone **green**, and I would have published
  *"full local suite green at `88b71053`"* about a tree I was not testing. A
  green suite under a hijack is strictly worse than a red one, and nothing in
  this file previously said so.

  **The cheap remedy, which is a reporting rule rather than a tool.** A suite
  result is a claim about a commit only if the run either pinned the source
  (`cd backend; $env:PYTHONPATH = (Resolve-Path 'src').Path`) or reports
  `test_import_provenance`'s own outcome from that same run. Absent one of
  those, *"the suite is green at X"* names a commit it has not tested. Per-
  worktree virtual environments remain the structural fix and remain absent;
  this entry does not reduce the case for them, it is the fourth documented
  instance and the first where the detector itself was the casualty.

  **Amended the same night, after running it rather than reasoning about it.**
  The paragraph above implied a pinned run could come back green. It cannot, and
  the reason is deliberate design: the guard calls `resolve_in_clean_process()`,
  which resolves the package in a **subprocess with `PYTHONPATH` stripped**, so
  the mitigation is structurally incapable of silencing it. A full pinned suite
  on this machine at `88b71053` produced **exactly one failure, and it was the
  guard** - every other test ran against the intended tree. That signature is
  what a *correct* pinned run looks like while the machine-global install points
  elsewhere; read as a bare "1 failed" it looks like the pin did not work, and
  the next person will re-pin to no effect.

  **The reason it must be reported separately rather than folded into the
  suite's verdict** is that the two reds have different subjects. The guard's
  red is a statement about **the machine**; every other red is a statement about
  **the commit**. One observation, two possible subjects - the same collapse
  this file records elsewhere - and a reader who sees a single tally cannot tell
  which one they are being told about. So report it as two claims: *"the suite
  is green at X, source pinned"* and *"the machine's editable install currently
  serves Y"*. Neither sentence is derivable from the other.

## Neither form of `git diff` answers "does the trunk already have this?"

**Recorded 2026-09-06 by `architect`, after getting this wrong three times in
one day — twice on my own work, once on someone else's.** The mechanism is
not obscure, but the failure mode is: every wrong reading produced a confident,
plausible, actionable conclusion, and two of the three would have caused real
damage if acted on.

**`git diff A..B` (two-dot)** shows what would turn A's tree into B's. When B
is merely stale, that renders as mass deletion and **looks exactly like a
revert**. Twice today I read it that way: once concluding four commits were
unmerged when they were byte-identical to `main`, and once nearly opening a
blocking review finding that PR #179 was reverting three of my commits. In a
two-dot diff, a path's *absence* means identity, not deletion.

**`git diff A...B` (three-dot)** shows `merge-base(A,B)..B` — what the branch
did since it diverged. That includes changes **A has since acquired
independently**, so a non-empty three-dot diff does *not* mean A lacks the
content. This is the half I got wrong even after correcting the first half, and
it is the more dangerous one, because three-dot is what you reach for once you
know two-dot is misleading.

**`git log A..B` lists commits unique by SHA, not by content.** A rebased,
cherry-picked or squash-merged equivalent counts as unique. `git merge-base
--is-ancestor` inherits this: it answers a question about ancestry, which is
not the question about content.

**The reliable test is to attempt the application.** `git cherry-pick -n <c>`
leaving an empty index proves the content is already present, because that
operation accounts for what the target already has. Nothing that only *reads*
the two trees can tell you this.

**The instance that shows why the distinction is load-bearing.** The archived
session `sr2501-demo-stamp-sanity-gate` left a branch on origin at `2b905ebe`.
`git log main..branch` reported **2 unique commits**; `git diff main...branch`
reported **3 files, +22 lines**; `merge-base --is-ancestor` said **not
contained**. Three independent signals, all pointing at unmerged work. All
three were misleading: every substantive line was already on `main`, each
exactly once. Cherry-picking the first produced an empty index. Cherry-picking
the second produced **a duplicate definition of a function `main` already
had** — so acting on the signal would not have been a harmless no-op, it would
have shipped a silent redefinition into a test module.

**Why this belongs in a gates file rather than a wiki.** The question "is there
unmerged work at risk?" gets asked at exactly the moment sessions are being
archived and worktrees pruned, which is when a false positive is expensive and
a false negative is unrecoverable. There is no CI job for reading a diff.

