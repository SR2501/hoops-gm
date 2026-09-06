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

## What this table is not

**It is not a quality ranking.** All five arms — two fast-tier, one `gpt-5.6-sol`,
one `claude-opus-4.8`, one `claude-sonnet-5` — scored **6/6 on the core mutation
battery with zero harness failures**, and all five caught a deliberately wrong
brief. On the build task the models were indistinguishable. The task was not hard
enough to discriminate, and that is a finding rather than a failed trial.

So the rows above are separated by **speed, cost and a single judgment item** —
not by whether the work came out right. Anyone citing this file as evidence that
one model writes better code is citing it for something it does not say.

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
