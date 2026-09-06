# Pre-registration — model trial, 2026-09-05

**Status:** Fixed before any arm ran. Not to be edited after arm output is seen.
**Base commit:** `9ea09fc7aa5bc55811753bb8fb91725eda74e067`
**Raised by:** the owner, asking which models suit *our* context, time-boxed to
an hour or two.

This document exists because `docs/governance/model-use-2026-09-05.md` could not
answer the question from observational data: the model boundary coincided with a
backend→frontend work shift and no work-type spanned it at comparable volume.
A confound you cannot remove after the fact has to be designed out beforehand,
which means fixing the task, the scoring and the verdict rule **now**, in
advance, in one place.

The repository already has this discipline for models
(`availability-model-preregistration-v1`). This applies it to ourselves.

---

## 1. The question

Not *"which model is better."* That is unanswerable at this sample size and was
already refused once. The question is narrower and decidable:

> On one bounded, real hoops-gm task, do the candidate models differ **more than
> the same model differs from itself**, on (a) whether their tests catch defects
> they did not see, and (b) whether they are fooled by an anomaly whose
> explanation is written in the file they are reading?

---

## 2. Arms

All five run the same two tasks. Task 1 arms start from `9ea09fc` in isolated
worktrees with no cross-talk.

| Arm | Model | Role |
|---|---|---|
| A1 | `gpt-5.6-sol-fast` | Current default |
| A2 | `gpt-5.6-sol-fast` | **Noise floor** — same model, same prompt, second run |
| A3 | `claude-opus-4.8` | Prior default |
| A4 | `gpt-5.6-sol` | Separates model family from fast tier |
| A5 | `claude-sonnet-5` | Cost frontier |

**A2 is load-bearing.** Any between-model difference smaller than the A1–A2
spread is not a model difference.

**Reasoning effort is held constant at `medium` across all five arms** — the one
setting all four models support in common. Recorded here before launch; varying
it would reintroduce exactly the kind of confound this document exists to
prevent. Arms run in `autopilot` so none stalls on a question the others were
never asked.

---

## 3. Task 1 — build `adr-index-consistency-test`

A real `pending` backlog item whose only dependency (`ci-pipeline`) is `done`.
Arms receive the identical prompt recorded in `model-trial-2026-09-05-prompt.md`
and are told nothing that is not in the backlog item.

### The natural trap, recorded here so it cannot be claimed post hoc

Twenty ADR files exist: `001`–`015` and `017`–`021`. `docs/decisions/README.md`
has no table row for 016. Prose **below that table, in the same file**, states
016 is unwritten and deliberately reserved so that four coordinator-register
references keep resolving.

An arm that parses only the table sees a gap. An arm that reads the file sees a
reservation. **The predicted failure is a check that goes red on a clean tree,
or one that hardcodes an exception for 016 without stating why.**

### A second trap, found after launch and before any arm output

**Timestamped honestly: this was discovered while the arms were already running,
and before a single arm's output had been looked at.** It is recorded here
rather than folded silently into the results.

`docs/decisions/PLAIN-ENGLISH.md` opens with:

> **Frozen historical walkthrough.** This document covers ADR-001 through
> ADR-009 and is not extended for later decisions. The individual ADRs and
> `README.md` index are the current authoritative record.

But the backlog item commissioning this work — which the prompt calls *"the
authority on what this task is"* — describes it as a second index that "stops at
ADR-009" with "two indexes over one directory, drifting independently."
**The brief's premise is contradicted by the file, in the file's own first three
lines.** `PLAIN-ENGLISH.md` is not drifting; it is frozen and says so.

This needs no new battery entry: an arm that enforces full coverage across both
indexes produces a check that is red on a clean tree, which `B8` already vetoes.
What it adds is one **behavioural observation**, scored from the arm's own
report rather than from its code:

> **`T2` — did the arm say the brief was wrong?**

`AGENTS.md` requires disagreeing with the brief rather than complying quietly,
so an arm that notices and argues it is doing the thing this project asks for.
An arm that silently builds the narrower correct check is *right in code and
silent in report*, which scores between the two.

`T2` was added after launch. It is scored from reports, cannot change any
battery outcome, and is reported separately so a reader can discount it.

### A third trap, same protocol: found before any arm output was read

`docs/decisions/README.md` contains **two tables**, not one. The index table is
`| link | title | status | consequence |`. Below it sits an *amendments* table
with a different shape — `| link | what changed | date | author |`.

Both carry rows matching `| [0NN](ADR-...)`. At the base commit that yields
**24 bracketed rows against 19 ADR files on disk**, with `002`, `007` and `019`
appearing twice and `020` three times.

A check that regexes the whole file sees four duplicate ADR numbers and five
surplus rows, and **goes red on a clean tree**. The correct reading scopes
parsing to the index table.

This needed no new battery entry either — `B8` catches it. What it changes is
how much weight `B8` carries: a single boolean now discriminates **three**
independent ways of misreading this corpus (the 016 reservation, the frozen
walkthrough, and the two-table structure). That is not a coincidence to be
smoothed over in the write-up; it is the reason `B8` is a veto rather than one
row among eight.

It also mattered to the harness itself. The first battery draft anchored `B2`
on the ADR-021 row, which does not exist at the base commit, and the harness
**refused to score it** rather than reporting a silent pass — the exactly-once
anchor rule doing precisely the job `gates.md` describes. The anchor moved to
ADR-018, the one late row appearing exactly once.

---

## 4. The battery — fixed here, implemented by the script

Applied to a scratch worktree, never to an arm's tree. Each entry names the
mutation and the verdict a correct test must return.

**CORE — any defensible design must catch:**

| ID | Mutation | Correct verdict |
|---|---|---|
| `B1` | Delete the README row for an ADR that exists *(the real 2026-08-21 defect)* | FAIL |
| `B2` | Add a README row for `ADR-042`, which has no file | FAIL |
| `B4` | Repoint an existing README link to a filename that does not exist | FAIL |
| `B5` | Rename an ADR file so its number no longer matches any row | FAIL |
| `B6` | Copy an ADR file to a second file bearing a duplicate number | FAIL |
| `B8` | **No mutation. Clean tree.** | **PASS** |

**EXTENDED — a disciplined minimal design may decline these:**

| ID | Mutation | Correct verdict |
|---|---|---|
| `B3` | Change a README `Status` cell so it contradicts the ADR's own `Status:` line | FAIL |
| `B7` | Add a `PLAIN-ENGLISH.md` entry for an ADR that does not exist | FAIL |

`B3` and `B7` are scored separately and **carry no penalty when declined**. The
backlog item says to check machine-readable edges only and to report rather than
adjudicate prose; the house preference is the smallest structure that honestly
supports the requirement. A rubric that rewarded gold-plating would measure the
opposite of what this project wants.

### Harness rules, inherited from `gates.md` rather than reinvented

- An anchor not found **exactly once** is a HARNESS FAILURE, not a catch.
- A crash, import error or collection error is a HARNESS FAILURE, not a catch.
- Only a genuine test failure counts as CAUGHT.
- A skip is a FAILURE, not a neutral result.
- Baseline asserted green before mutating; tree asserted byte-identical after.

**`B8` is a veto.** A test that is red on a clean tree is not a test, and no
count of caught mutations redeems it.

### Harness validated in both directions before any arm output was read

The battery was run against two throwaway probes in a scratch worktree at
`9ea09fc`: a test that always passes and a test that always fails.

| Probe | CORE | EXTENDED | harness failures | `B8` | outcome |
|---|---|---|---|---|---|
| always-passes | 1/6 | 0/2 | 0 | PASS | scores only the clean-tree control |
| always-fails | 5/6 | 2/2 | 0 | FAIL | ***VETOED*** |

The second row is the point of the design. **A test that catches nothing real
scores 5 of 6 CORE and 2 of 2 EXTENDED**, and is rejected anyway, because it is
red on a clean tree. That is why `B8` is a veto rather than an eighth row: with
`B8` as an ordinary row, the worst possible submission would have out-scored a
careful one.

**Two harness bugs were found by this validation and fixed before any arm output
was read.** Both are recorded because a harness that is only ever run on the
data it is meant to judge has not been tested at all — the failure `gates.md`
documents at length, where a tool reported *33 of 33 caught* for nine review
rounds with nobody able to check it.

1. **`B2` was anchored on a README row that does not exist at `9ea09fc`.** I
   wrote the anchor against my own working tree, where ADR-021 is uncommitted.
   The harness reported HARNESS FAILURE rather than silently passing, which is
   the behaviour it was built for. Anchor moved to the ADR-018 row, which
   appears exactly once at the trial's base commit.
2. **The classifier read `-qq` output that no longer contained a summary line.**
   `backend/pyproject.toml` already sets `-q` in `addopts`; the harness added a
   second `-q`, which suppresses pytest's `N failed` line. Every genuine test
   failure was therefore classified HARNESS. **In a real run this would have
   scored every correct catch as a broken harness** — an error that would have
   made the whole trial read as inconclusive for a reason that had nothing to do
   with any model. The classifier is now exit-code-primary, so it survives a
   future `addopts` change as well.

---

## 5. Task 2 — the judgment arm

Read-only, no worktree, **no repository access**, because the answers are
recorded in `gates.md` and an arm that greps for them measures search rather
than judgment. This makes Task 2 a **lower bound** on in-lane performance.

| Item | Recorded answer |
|---|---|
| `J1` pre-fix year-0001 guard | **Defective** — catches only because `America/New_York` ran on −04:56 local mean time before 1883; the source's real placeholder convention is 1900, which reconciles exactly and passes |
| `J2` test named *"accepts a null game_date but still refuses one that is simply absent"* | **Defective** — omits the sibling `reason` field too, so the refusal comes from the wrong field |
| `J3` mutation reddening only a file-digest fingerprint test | **Establishes nothing about behaviour** — fires on any byte change, including whitespace |
| `J4` **control**, post-fix year-0001 handling | **Sound** — handles both `0001-01-01` and `1900-01-01` explicitly |

Scored on **verdict and named mechanism**. A correct verdict without a mechanism
scores half: arriving at the right answer for no stated reason is the
rhetorical-convenience failure `AGENTS.md` warns about, and it is not
distinguishable from a guess.

`J4` measures false positives. Without it, an arm that answers "defective" to
everything scores full marks, and in a review lane a confident false positive
costs as much as a miss.

---

## 6. Verdict rule — fixed now, read off mechanically later

Let `spread(A1,A2)` be the CORE-caught difference between the two same-model
runs, and `gap(X)` the CORE-caught difference between the best other arm and A1.

- **Switch the default** only if one model wins CORE, passes `B8`, and
  `gap(X) > spread(A1,A2)`.
- **No change** if `gap(X) <= spread(A1,A2)`.
- **Inconclusive** if arms diverge so widely on scope interpretation that they
  are not doing the same task, or if two or more arms fail `B8`.

Inconclusive is a permitted outcome and is not a failure of the trial. The
design is allowed to return nothing rather than manufacture a number.

---

## 7. What this cannot establish

- **One task, n=1.** Detects only large effects.
- **Two runs is a crude noise floor.** A2 can show the spread is large; it
  cannot show it is small.
- **It does not reach the statistical core**, where "confident, plausible,
  wrong" is the documented hazard. Quant work is evidence-blocked, so no arm can
  be asked to fit anything. Task 2 is *about* that class of error, which is
  closer, but reading a defect and avoiding one are different skills and only
  the first is measured.
- **I designed the battery knowing the trap.** It is fixed here, before any arm
  runs, and its digest is recorded below. That is a procedural guarantee, not a
  structural one.
- **Task 2 arms are blind to the repository**, so their scores understate what
  the same model does with `gates.md` in front of it.
