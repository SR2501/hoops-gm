# Model selection

**Standing file. Update it in place; do not date-stamp a copy.** The dated files
in this directory are *evidence* and are immutable once written. This file is the
only one that carries a live recommendation, so a reader who lands here does not
have to work out which analysis is current.

- **Last revisited:** 2026-09-06 — `gpt-6-astra` evaluated and **not adopted**
- **Evidence:** `model-trial-2026-09-05-results.md` (controlled, five arms),
  `model-use-2026-09-05.md` (observational, confounded — see the banner on it),
  and the sixth-arm figures in *"GPT-6, measured rather than assumed"* below

---

## Current guidance

| Lane | Model | Why | Evidence strength |
|---|---|---|---|
| **Execution** — build a thing, change a thing | `gpt-5.6-sol-fast` *(unchanged default)* | Fastest by a clear margin; completed the trial task correctly on both runs | Pre-registered rule returned **no change**; speed confirmed twice |
| **Review and judgment** — notice a defect rather than produce a change | `gpt-5.6-sol` | Caught the judgment item the fast tier missed on both its runs, at 1.8× lower cost, with the smallest submission of five | **One item.** Suggestive, not established |
| **Cost-sensitive bulk work** | `claude-sonnet-5` — candidate only, do not promote today | Did identical work for 2.8× less than the sol-fast mean | Real, but **not pre-registered as decision-bearing** |
| **Newest available** | `gpt-6-astra` — **evaluated, not adopted** | Ties the top score on the judgment battery and costs **3.4× `gpt-5.6-sol`** for it | Same four items, same rubric — see below |

**The one durable finding behind the review row:** `gpt-5.6-sol-fast` missed the
item twice, identically, while `gpt-5.6-sol` caught it. That isolates the **fast
tier**, not the GPT family — which is why a same-family, non-fast arm was in the
trial. Do not restate this as "GPT misses things."

---

## GPT-6, measured rather than assumed

`gpt-6-astra` became available on 2026-09-06 and was run against the **same
hashed judgment battery** the five trial arms took
(`model-trial-2026-09-05-judgment-items.md`, fixed before any arm ran). Same four
stimuli, same rubric, answers unchanged. This is the cleanest comparison
available anywhere in this project, because the input is byte-identical rather
than merely similar.

It scored **8/8** — including `J2`, the item the fast tier missed identically on
both of its runs. It also correctly called the `J4` control **sound**, so it is
not simply answering "defective" to everything.

Per-run figures on that battery, from `assistant_usage_events`:

| Model | AIU | Output tokens | Wall (s) | Score |
|---|---|---|---|---|
| `gpt-5.6-sol` | **12.3** | 413 | 13.0 | **8/8** |
| `claude-sonnet-5` | 16.3 | 2,003 | 23.0 | 8/8 |
| `gpt-5.6-sol-fast` | 18.5 *(mean of 2)* | 225 | **6.1** | 6/8 |
| `claude-opus-4.8` | 39.8 | 1,706 | 23.2 | 8/8 |
| `gpt-6-astra` | **41.5** | 333 | 9.4 | **8/8** |

**The verdict is that GPT-6 changes nothing here, and the reason is cost, not
quality.** Four models reach 8/8. `gpt-5.6-sol` reaches it for 12.3 AIU;
`gpt-6-astra` reaches it for 41.5. On this evidence GPT-6 is the most expensive
model in the set and buys nothing the incumbent review model does not already
deliver. **Revisit if a task appears that `gpt-5.6-sol` actually fails**, since
that is the only condition under which paying 3.4× is rational.

Worth noting for its own sake: GPT-6 answered in **333 output tokens**, against
1,706 for `opus-4.8` and 2,003 for `sonnet-5` at the same score. It is
strikingly terse. Terseness is not cheapness here — the cost is in the reasoning,
not the prose — but it does mean its output is quick to read and hard to hide a
hedge in.

**Four caveats, because this is a small instrument:**

1. **Isolation is weaker for this arm than for the five.** The original arms had
   no repository access. `gpt-6-astra` ran as a sub-agent with tools available
   and was *instructed* not to use them; it declared it used none. The recorded
   answers are in this repository, so that declaration is load-bearing and is a
   self-report. Treat 8/8 as an upper bound in a way the original five are not.
2. **Input tokens are not comparable across model families.** The identical
   prompt measured ~31.9K tokens for the GPT arms and ~57.0K for the Claude arms.
   Compare AIU, never token counts, across families.
3. **Wall-clock for a sub-agent includes scheduling**, so the seconds column
   ranks roughly and should not be read to two significant figures.
4. **Four items.** This separates gross differences and nothing finer, and three
   of the four did not discriminate at all. A tie at 8/8 means "not separated by
   this instrument", not "equal".

## The review comparison, the only controlled read this project has taken

Every prior comparison here shares a defect: the *inputs differed*. Two runs of the
same model on the same build task differed 59% on turns and 33% on cost, so
comparing two models across two different tasks measures noise. Reviews escape
this. Two reviewers on one frozen diff differ **only** by model, so the experiment
rides on the review step, never the build step.

**Run 2026-09-06 on PR #166 (`schedule-grid-contract`), identical diff, identical
prompt, both as `code-review` sub-agents.**

| | `gpt-5.6-sol` | `gpt-6-astra` |
|---|---|---|
| Findings | 2 | 2 |
| Severities | Medium, Medium | Medium, Medium |
| Found the material bug | **yes** | **yes** |
| Wall clock | 543 s | **320 s** |
| Evidence style | reasoned from `dict.__eq__` | **executed a reproduction** |

**Both found the same material bug, independently: Python's `==` conflates scalar
types, so `True == 1` and `False == 0` leave a wire-type change invisible to a
contract gate built to catch exactly that.** Neither missed it. They differed only
in how they reached and dressed it.

- `gpt-5.6-sol` was **broader on the defect**: it cited *both* call sites (the
  script and the backend test, so a partial fix is visible), and it caught the
  third confusion `1 == 1.0` that GPT-6 did not mention.
- `gpt-6-astra` was **stronger on evidence**: it did not argue the bug, it ran it —
  *"Reproduced without modifying files: the generated value became `True`, the
  recorded value remained `1`, their documents compared equal, and `main(['--check'])`
  returned 0."* That is a claim stated so it can be disproved in one command.
- Their second findings were the **same class, different instantiation** — a
  handwritten frontend type pinned to one specimen. GPT-6 reached for
  `game_label` widening to `str | None`; `gpt-5.6-sol` named the actual closed
  domain (`""`, `"not_offered"`) and proposed an enum manifest, which is the more
  actionable of the two.

I sized the bug myself rather than accept either report: **16 int and 1 bool field
in the fixture, 8 of them live today** because their value is exactly `0` or `1`,
including `periods[0].is_playoff` and `counts[0].games`.

### What this changes

**Stop paying for dual review by default.** Both models found the finding that
mattered, so one reviewer of either model would have caught it. Dual review bought
a sharper *description* here, not a caught defect, and description is the cheap
part. Reserve two reviewers for changes where a miss is expensive and irreversible
— the write path, anything the owner acts on at the draft — and run one elsewhere.

**This does not rank the models.** One diff, two findings each, complete overlap on
what mattered. It says the instrument did not separate them on quality, which is
the same verdict the judgment battery reached at 8/8, reached now by a second and
independent route. Break the tie on cost and latency, both measured.

### Cost is not attributable, and the instrument is why

I tried to price the two reviews and **could not**. Sub-agent usage rolls up under
the *parent* session's `session_id` in `assistant_usage_events`, and several agents
of the same model ran concurrently tonight, so no grouping separates the review
from the judgment battery sharing its model. The aggregate figures are real but
answer a different question than the one asked.

Wall clock is trustworthy because the agent runtime reports it per agent: GPT-6 was
**1.7× faster** on identical input. Cost is not, and is recorded here as unknown
rather than estimated. **Do not fill this gap by apportioning; measure it by running
the two arms at different times, alone.** That is the change needed before this
table can carry a cost column.

**It is not a quality ranking.** All five arms — two fast-tier, one `gpt-5.6-sol`,
one `claude-opus-4.8`, one `claude-sonnet-5` — scored **6/6 on the core mutation
battery with zero harness failures**, and all five caught a deliberately wrong
brief. On the build task the models were indistinguishable. The task was not hard
enough to discriminate, and that is a finding rather than a failed trial.

So the rows above are separated by **speed, cost and a single judgment item** —
not by whether the work came out right. Anyone citing this file as evidence that
one model writes better code is citing it for something it does not say.

**It is not a clean measure of task cost.** Asked separately on 2026-09-06, before
archiving, three arms independently reported losing turns to the *same* three
environment obstacles: `ruff`/`pytest`/`mypy` absent from `PATH`, a stale editable
install failing as `ModuleNotFoundError: No module named 'hoops_gm.app'`, and a
whole-file write to `docs/handoff.md` normalising historical CR bytes into a
150-line phantom diff that had to be undone. Every arm paid all three. So the
absolute AIU and turn figures include a floor of friction belonging to **this
machine**, not to the task and not to the model. Those obstacles are now written
down in `.github/skills/standup-hoops-gm/SKILL.md`, which means a rerun would be
cheaper for every arm and **the absolute numbers here are not comparable to any
future measurement taken after that fix.**

The relative ordering is more robust than the absolute figures, because the
friction was common — but only partly. The arms diverged in what they did
*around* it: A2 read every ADR and the full plan before writing; A4 additionally
probed a second Python installation. That is arm-specific effort, not a shared
floor, and it is the most likely explanation for the 59% turn gap between the two
runs of the *same* model — the divergence this trial's noise floor is built on.
**Recorded as the leading hypothesis, not as the cause; nobody instrumented it.**

## What would change this

- **A trial designed around cost from the start**, on a task hard enough to
  produce a correctness spread. `claude-sonnet-5` is the obvious first arm. Until
  then its 2.8× stays an observation, because promoting a finding to
  decision-bearing *after* seeing it is the post-hoc move the trial existed to
  avoid.
- **A second judgment item discriminating the fast tier.** One item is thin. Three
  of the four items failed to discriminate at all.
- **Any result from a statistical-core task.** Everything here was measured on
  doc-governance tooling. It says nothing about the availability model, valuation
  or backtests — the work where "confident, plausible, wrong" is the documented
  hazard — and nothing about the write path.

---

## How to measure this again

These outlive any model name and cost real time to learn.

1. **Run two arms of the same model, or you have no noise floor.** This is the
   single most important design choice. The duplicate arm showed a **59% spread
   in turns and 33% in cost** between two runs of the *same* model on the *same*
   task. Without it, every between-model difference in the table would have looked
   real.
2. **Never compare models by turn count.** See above: turns are dice.
3. **Per-turn cheapness is not per-task cheapness.** They can point opposite ways
   and did here — the fast tier took the *fewest* turns and spent the *most* per
   task. Normalise by the unit of work you actually care about.
4. **Fix the rubric and hash it before any arm runs**, and score blind. Amend only
   with a timestamped, in-document justification, and never after reading an arm's
   output.
5. **Validate the harness in both directions** — against something that must pass
   and something that must fail — before trusting a single score. Two harness bugs
   were found this way, one of which silently classified *every genuine catch* as a
   harness failure and would have made the whole trial read inconclusive.
6. **"Idle" is not "settled", and they are two different signals.** Artifact bytes
   stop changing when an arm stops writing; its usage figures keep moving after
   that, including after the idle notification. Score artifacts on bytes verified
   before *and* after; take cost figures only once two pulls agree.
7. **Prefer natural traps to planted ones.** All four traps in this trial were
   found in the repository while writing the battery, not invented. A real
   inconsistency tests what a model does with this codebase; an invented one tests
   whether it can spot a puzzle.
8. **Keep one frozen instrument so a new model can be priced in minutes.** The
   hashed judgment battery cost about ten minutes to run against `gpt-6-astra`
   and produced a byte-identical comparison to five existing scores. A dated
   results file cannot do that; a fixed, reusable stimulus set can. **When a new
   model appears, run the battery before forming an opinion** — the answer here
   was the opposite of the expected one.
9. **Never compare token counts across model families.** The same prompt measured
   ~31.9K input tokens on GPT and ~57.0K on Claude. Only AIU is comparable, and
   only then as an unreconciled local estimate.
10. **A tie is not equality.** Four of six models reach 8/8 on the battery. That
    means the instrument does not separate them, not that they are the same.
    Break the tie on cost, which is measured, rather than on reputation, which is
    not.

## GPT-6 can own a session after all, checked by attempting it

**2026-09-06.** The overnight fan-out plan recorded a constraint that turned out
to be false, and recorded correctly that it was unverified: *"`gpt-6-astra` is
offered by the `task` sub-agent tool but **not** by `create_session`'s kickoff
model list. GPT-6 can review; it cannot own a lane. A schema read is not a live
check - confirm by attempting it, and fall back rather than assume."*

I attempted it. **The session was created and `gpt-6-astra` actually ran.**

The distinction that matters is between *accepted* and *silently downgraded to
the default*, because those are indistinguishable from the caller and only one of
them is safe. A silent fallback would be much the worse outcome: every future
comparison would be labelled GPT-6 and be something else, and the label is the
whole point of a controlled arm. So the check reads the runtime's own usage
record rather than the parameter I passed:

```sql
SELECT model, COUNT(*), SUM(input_tokens), SUM(output_tokens)
FROM assistant_usage_events WHERE session_id = '<probe session>'
```

It returns `gpt-6-astra`, one event, **38,133 input tokens, 5 output**. The five
output tokens are the single word the probe was asked to reply with, so the model
both ran and obeyed. The probe session was archived immediately after.

**This widens the option set and changes no recommendation.** The verdict above
stands untouched: GPT-6 ties at 8/8 and costs **3.4x** `gpt-5.6-sol` for the tie,
and the revisit condition is still "a task `gpt-5.6-sol` actually fails". Being
*able* to own a lane was never the reason we declined it. Read as permission to
staff a lane with GPT-6, this section has been read backwards.

**Two things to carry forward.**

1. **A tool description's enum is not authoritative about what the runtime
   accepts.** `create_session`'s documented model list omits `gpt-6-astra`; the
   runtime took it regardless. This is the same shape as the `open_canvas` result
   that echoed back the URL passed to it, recorded in
   `docs/governance/coordinator-register.md` - a check that reads the declaration
   instead of the effect cannot fail. Confirm by attempting, then read the effect
   from somewhere the caller does not control.
2. **A session costs about 38K input tokens before it does anything.** The
   probe's entire task was to emit one word, and it billed 38,133 input tokens of
   bootstrap context to do it. That is a floor per session spawn, not a variable
   cost, and it is a real input to fan-out sizing: eight lanes begin roughly 305K
   input tokens in the hole whatever they are asked to do. It argues for fewer,
   larger lanes over many trivial ones, and against spawning a session to answer
   a question a tool call could answer.

**Could not verify.** Whether the runtime would accept an outright invented model
name. I tested one *real* model that is absent from the enum, which shows the
enum is not exhaustive; it does not show the enum is unenforced. Those are
different claims and only the first is evidenced here.
