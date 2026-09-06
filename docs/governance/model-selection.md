# Model selection

**Standing file. Update it in place; do not date-stamp a copy.** The dated files
in this directory are *evidence* and are immutable once written. This file is the
only one that carries a live recommendation, so a reader who lands here does not
have to work out which analysis is current.

- **Last revisited:** 2026-09-05
- **Evidence:** `model-trial-2026-09-05-results.md` (controlled, five arms),
  `model-use-2026-09-05.md` (observational, confounded — see the banner on it)

---

## Current guidance

| Lane | Model | Why | Evidence strength |
|---|---|---|---|
| **Execution** — build a thing, change a thing | `gpt-5.6-sol-fast` *(unchanged default)* | Fastest by a clear margin; completed the trial task correctly on both runs | Pre-registered rule returned **no change**; speed confirmed twice |
| **Review and judgment** — notice a defect rather than produce a change | `gpt-5.6-sol` | Caught the judgment item the fast tier missed on both its runs, at 1.8× lower cost, with the smallest submission of five | **One item.** Suggestive, not established |
| **Cost-sensitive bulk work** | `claude-sonnet-5` — candidate only, do not promote today | Did identical work for 2.8× less than the sol-fast mean | Real, but **not pre-registered as decision-bearing** |

**The one durable finding behind the review row:** `gpt-5.6-sol-fast` missed the
item twice, identically, while `gpt-5.6-sol` caught it. That isolates the **fast
tier**, not the GPT family — which is why a same-family, non-fast arm was in the
trial. Do not restate this as "GPT misses things."

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
