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

  **Finally, red is not enough on its own: mutate the thing the docstring *names*, and check the failure matches the docstring's story.** A fourth lane had two mutation checks pass for reasons adjacent to the ones claimed — one reddened against the bug itself rather than the guard, another against a neighbouring condition. Both went red, both looked like evidence, and neither established what its docstring said it established. If a test claims to be pinned by a parked id, remove the parked id; if it stays green, the pin was something else.

Enforced by CI, except the two bullets marked otherwise.

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
recorded as R49–R54 in `risks.md` — deliberately in one place, because a lesson restated in
two files drifts in one of them.

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

---

## Gate discipline

- Gates are not paperwork; if one is not catching anything, say so and change it.
- Failing a gate is information, not failure. Record it in `docs/handoff.md`.
- No gate may be waived by the agent whose work it applies to.
