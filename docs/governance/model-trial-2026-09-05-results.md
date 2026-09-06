# Model trial — results, 2026-09-05

**Read `model-trial-2026-09-05-preregistration.md` first.** The design, the
battery, the traps and the verdict rule were all fixed before any arm ran, and
the digests are recorded there. This file only reads results off that rule.

**Companion:** `model-trial-2026-09-05-judgment-items.md` (Task 2 stimuli and
recorded answers, `sha256 a27e83e5…`), `model-use-2026-09-05.md` (the
observational analysis that refused to answer this question and asked for this
trial).

**This file is frozen evidence, not live guidance.** It records one trial on one
day. The standing recommendation it fed — which model to run which lane on, and
what would change that — is `model-selection.md`, which is updated in place. If
the two ever disagree, `model-selection.md` is current and this file is history.

---

## 1. The answer, first

**The pre-registered rule returns *no change*.** No model won the build task,
because **every model completed it correctly**. All five arms scored 6/6 CORE
with the clean-tree veto passed and zero harness failures.

**The build task could not tell these models apart.** That is a real outcome,
not a failed experiment, and it is the first thing worth knowing: for
small, well-specified, in-repo work of this shape, the model choice did not
change whether the work got done or whether it was correct.

**Two things did separate them, and neither was what the rule was watching.**

| | Finding | Robust to the noise floor? |
|---|---|---|
| **Cost per task** | `claude-sonnet-5` did the same work for **~2.8× less** than the current default | **Yes** — 2.8× against a 33% within-model spread |
| **Judgment** | `gpt-5.6-sol-fast` missed the same item **on both runs**; the other three models caught it | **Yes**, but rests on **one item** |

Both point away from the current default. **Neither was pre-registered as
decision-bearing, so neither licenses a switch on its own** — that is precisely
the post-hoc reasoning this trial existed to avoid. Recommendation in §6.

---

## 2. Results table

| Arm | Model | CORE | `B8` | EXT | Judgment | Cost (AIU) | Wall (s) | Turns |
|---|---|---|---|---|---|---|---|---|
| A1 | `gpt-5.6-sol-fast` | 6/6 | PASS | 0/2 | 6/8 | 461.8 | 143 | 22 |
| A2 | `gpt-5.6-sol-fast` | 6/6 | PASS | 0/2 | 6/8 | 616.2 | 186 | 35 |
| A3 | `claude-opus-4.8` | 6/6 | PASS | 0/2 | **8/8** | 537.1 | 436 | 56 |
| A4 | `gpt-5.6-sol` | 6/6 | PASS | 0/2 | **8/8** | **303.1** | 238 | 34 |
| A5 | `claude-sonnet-5` | 6/6 | PASS | 0/2 | **8/8** | **189.6** | 295 | 57 |

**Cost, wall and turn figures were re-pulled after each arm reported idle**, for
the same reason §4 exists. The first pull caught A3 and A5 mid-run and
understated them — A3 by 19% (452.8 → 537.1 AIU). A1, A2 and A4 were already
final and are unchanged, so **the noise floor in §3 is unaffected**.

**A5 was the last to settle, and it kept spending after it reported idle.** It
was still accruing when the provisional version of this table was written (54 →
55 → 57 events, 179.7 → 182.6 → 189.6 AIU), and the last of that movement
happened *after* its idle signal arrived, so even the completion signal was not
the moment the numbers stopped. The figures above were taken once two pulls 105
seconds apart agreed. **Its artifact was never in doubt** — script and test bytes
have been identical since 17:30 across six checks — and its 6/6 was re-run
against those final bytes after the idle signal, the same treatment A4 got.

**`EXT 0/2` across the board is a pass, not a failure.** The backlog item asks
for machine-readable edges only. Every arm stayed inside that, and the rubric
declined to reward gold-plating for exactly this reason.

**A5's row is a re-score.** Its first score was 1/6 with 5 harness failures. That
score was taken while the arm was still working, which is my error, not its; see
§4.

---

## 3. The noise floor is the load-bearing number

A1 and A2 are the same model, same prompt, same commit, run twice. Everything
they disagree about is dice.

| Measure | A1 | A2 | Within-model spread |
|---|---|---|---|
| CORE | 6/6 | 6/6 | **0** |
| Judgment | 6/8 | 6/8 | **0** — and the *same* item, missed the same way |
| Cost (AIU) | 461.8 | 616.2 | **33%** |
| Wall (s) | 143 | 186 | 30% |
| Turns | 22 | 35 | **59%** |

**So: turn counts are not evidence here.** A 59% within-model spread swallows
every between-model turn difference in the table. Any report comparing models by
turns taken — including one I might have written from this data — would have
been measuring the dice.

**Cost differences below ~33% are also not evidence.** `claude-opus-4.8` at 537.1
sits *inside* the sol-fast band and is indistinguishable from it on cost.
`gpt-5.6-sol` (1.8× cheaper) and `claude-sonnet-5` (2.8× cheaper) are outside
it.

**Correctness had no spread at all** — which is the same thing as saying the task
was too easy to discriminate.

---

## 4. I scored an arm that was still working

**This section was originally a finding about A5. It is now a finding about me,
and it is the most useful thing in this document.**

At 17:20 I scored A5 at 1/6 CORE with 5 harness failures. Its test produced
`2 failed … 1 error` on every mutated tree: the assertion was a real, correctly
attributed catch — `AssertionError: ADR-018-…md: no row in the '## Index' table
links to it (direction 1: every ADR file needs an index row)` — while a *different*
test's teardown raised `UnicodeDecodeError: 'utf-8' codec can't decode byte 0x97`
from a `subprocess` call, decoding the child's cp1252 output as UTF-8.

I wrote that up as a shipped Windows portability defect, and reasoned at length
about how CI on Linux would never have caught it.

**A5 then edited the file at 17:30 and fixed it.** Re-scored against its final
submission: **6/6 CORE, `B8` PASS, zero harness failures.** Its `subprocess.run`
now pins `encoding="utf-8"`. I have **not** isolated which edit removed the error
— non-ASCII bytes remain in both files — and I am recording the observation
rather than inventing the mechanism.

### The mistake, stated so it is cheap to check

**I inferred "finished" from "quiet for thirteen minutes".** I had no completion
signal for any arm. I had file mtimes, and I treated a gap in them as an end
state. The arm was mid-run, and the one thing I scored it down for was a defect
it was in the middle of fixing.

The correct procedure — obvious in hindsight, and now the rule for any repeat —
is to score only after an explicit idle signal per arm, and to **re-verify input
bytes immediately before scoring and immediately after**, so a mid-flight change
is detected rather than assumed absent. The re-check that caught this was
prompted by an unrelated idle notification arriving for a *different* arm after I
had already published; without that accident the wrong finding would have stood.

**That rule is sufficient for artifacts and insufficient for usage figures**, as
A5 went on to demonstrate: it kept accruing cost rows *after* reporting idle
(see §8). Bytes settle when the arm stops writing; the usage table settles some
time later. Two different signals, and the second one needs its own check —
agreement between successive pulls, not the idle notification.

**A1–A4 are unaffected and did not need re-scoring**: their script and test bytes
are identical to the copies scored (14,239 / 16,645 / 32,683 / 11,003 bytes), and
the battery is deterministic, so identical inputs give identical results. Only A5
moved.

**What survives.** Nothing about the models changed; the correction removed the
*only* quality difference the build task had produced, which strengthens rather
than weakens §1's headline: the build task genuinely could not tell these models
apart. It also means the trial's cheapest arm no longer carries a defect, which
matters for §6.

---

## 5. What the traps established

**Trap 1 — ADR-016 is reserved, not missing. All five cleared it.** Every arm
passed `B8`, so no arm shipped a contiguity check that goes red on a clean tree.

**Trap 2 — the brief was wrong about `PLAIN-ENGLISH.md`. All five caught it.**
The backlog item describes it as a drifting second index; the file's own banner
declares it a frozen ADR-001–009 walkthrough. Every arm read the banner, believed
the file over the brief, and said so in writing. A3, unprompted: *"deliberately
selective and self-declares as frozen at ADR-009 in its own header"*.

That is the `AGENTS.md` rule about disagreeing with a wrong brief, observed
unanimously and therefore **not a discriminator**. It is still the single most
reassuring result in this trial.

**Trap 3 — the README's second table. No arm went red on it**, since all passed
`B8`.

**Scope: no arm edited `docs/decisions/`.** The item asks for a test, not an
edit, and nobody "fixed" the ADR-016 gap. A1, A2 and A4 updated `backlog.md`
and/or `handoff.md`; A5 also wired the check into `ci.yml`; A3 touched no docs at
all. All defensible readings of the same instruction.

### I nearly published a false negative here

My first pass reported that A3 and A5 had *not* noticed the frozen banner. That
was wrong, and it was my bug: I passed `-SimpleMatch` with the pattern
`PLAIN-ENGLISH|PLAIN_ENGLISH`, so PowerShell searched for a **literal pipe
character** and found nothing. The command succeeded, returned `0`, and the zero
looked like a finding.

Recorded because it is the exact failure mode this project keeps hitting and
`gates.md` keeps cataloguing: **a well-formed command returning a confidently
wrong answer.** It was caught only because "two of five silently ignored the most
interesting thing in the corpus" was surprising enough to re-check. A less
surprising wrong number would have shipped.

---

## 6. Verdict and recommendation

**Read mechanically off the pre-registered rule: no change to the default.**
Nothing won CORE, so the switch condition is not met.

**But the rule was aimed at the wrong quantity, and I should say so rather than
stop at a clean answer.** It assumed correctness would discriminate. It did not.
The two measures that *did* discriminate — cost per task and the judgment item —
both survive the noise floor and both point away from `gpt-5.6-sol-fast`:

- It was the **most expensive per task** of the five, which directly contradicts
  the natural reading of the earlier per-turn finding. **Per-turn cheapness and
  per-task cheapness are different quantities**, and the earlier report's
  ~1.8×-cheaper-per-turn is not evidence of cheaper work. It took fewer turns and
  spent more.
- It was **fastest**, consistently, confirming the earlier finding on wall clock.
- It **missed the judgment item twice, identically**, where the other three
  models all caught it. `gpt-5.6-sol` catching it isolates the **fast tier**
  rather than the model family — the reason A4 was in the trial at all.

**Recommended, and deliberately smaller than the evidence would allow:**

1. **Keep `gpt-5.6-sol-fast` as the default for execution lanes.** It is fastest,
   it completed the task correctly twice, and speed is worth real money on a
   deadline 43 days out.
2. **Prefer `gpt-5.6-sol` for review and judgment lanes** — anything where the
   job is to notice a defect rather than produce a change. It caught the item the
   fast tier missed, at 1.8× lower cost, with the tidiest submission in the
   trial.
3. **Do not switch the default to `claude-sonnet-5` on this evidence**, despite
   it being 2.8× cheaper and despite its final submission being as clean as every
   other. The cost finding was **not pre-registered as decision-bearing**, and
   promoting it to one after seeing the numbers is exactly the post-hoc move this
   trial existed to avoid. It is the strongest candidate for the *next* trial —
   one aimed at cost from the start, on a task hard enough to discriminate.

---

## 7. The artifact

**A4 (`gpt-5.6-sol`) is the review candidate**, and it is a candidate, not a
merge. Its Code gate is verified green against its **final** bytes, re-run after
its idle signal arrived — `ruff check`, `ruff format --check`, `mypy`, `pytest`
(9 passed) — it is the smallest submission of the five at 11.0 KB for script and
test together (against 14.2, 16.6, 19.1 and 32.7 KB), it scored 6/6 CORE with
`B8` passed, and no defect was found in it.

It has **not** been reviewed on its merits, only scored by the battery. Winning a
trial is not a gate. `adr-index-consistency-test` stays `pending` until it goes
through normal review.

All five arm worktrees are left in place for inspection rather than deleted. The
scratch worktree the battery mutated has been removed.

---

## 8. Could not verify

- **I scored one arm mid-flight and published the wrong finding about it** (§4).
  Corrected before this file was final, but only because an unrelated idle
  notification prompted a re-check. **No arm's completion was ever confirmed by a
  signal; "quiet for thirteen minutes" was the whole basis.** A1–A4 were
  re-verified byte-identical after the fact, so their scores stand, but that is a
  reconstruction rather than a guarantee I had at the time.
- **All five arms reported idle, and every score was taken after that signal.**
  Script and test bytes were identical across six checks spanning 17:20–17:43
  (A1 14,239 / A2 16,645 / A3 32,683 / A4 11,003 / A5 19,126). A4 (the
  candidate) and A5 (the arm I mis-scored) each had their result re-run against
  final bytes *after* their idle signal: A4's Code gate green (`ruff`, `mypy`,
  `pytest` 9 passed), A5's battery 6/6 CORE with `B8` PASS and zero harness
  failures.
- **The idle signal is not the moment the numbers stop.** A5 kept accruing usage
  after reporting idle (55 → 57 events, 182.6 → 189.6 AIU), so cost figures were
  only taken once two pulls 105 seconds apart agreed. **This is the same class of
  error as §4** — inferring completion from a signal that does not mean it — and
  it is recorded because the first version of this table shipped A5's cost as
  settled when it was not.
- **One task, one shape.** Doc-governance tooling. It says nothing about the
  statistical core, where "confident, plausible, wrong" is the documented hazard,
  and nothing about the write path.
- **The judgment gap rests on a single item (`J2`).** Three of four items failed
  to discriminate. n=1 item is an observation, not a measurement, and the
  headline finding of §1 should be read with that in front of it.
- **Task 2 arms were told not to use tools; I did not verify compliance.** No
  answer cited a repository file, which is weak evidence, not proof.
- **Task 2 arms were blind to the repository**, so their scores are a **lower
  bound**. §5 is the direct evidence for that caveat: with the repo open, the
  same fast-tier model that missed `J2` caught the wrong brief, twice.
- **`J1` and `J4` were shown to the same arm in sequence**, so an arm could infer
  `J4` is the fix for `J1`. Identical across arms, and the priming runs toward
  over-flagging `J4`, which makes the control harder rather than easier — but it
  is a design flaw and the labels `DEFECTIVE` and `ESTABLISHES NOTHING` were not
  defined crisply enough to separate cleanly. I accepted both as "does not
  establish the claim" **after** seeing that A3 and A5 used them
  interchangeably. That is a post-hoc scoring decision and should be discounted
  accordingly; it did not change any arm's total.
- **Two runs is a crude noise floor.** A1/A2 showed the spread is *zero* on
  correctness and *large* on turns. It cannot prove any spread is small.
- **Code gate verified only for A4.** The other four were scored by the battery
  and not gate-checked end to end.
- **Cost figures are `total_nano_aiu` from the local session store**, summed by
  `session_id`. I did not independently reconcile them against billing.
- **I designed the battery knowing all three traps.** Fixed and hashed before any
  arm ran, and amended only before any arm output was read, with each amendment
  timestamped in the pre-registration. **That is a procedural guarantee, not a
  structural one.**
- **Two harness bugs were found during validation** (§ pre-registration). The
  second — a doubled `-q` suppressing pytest's summary line — would have
  classified **every genuine catch as a broken harness** and made the whole trial
  read as inconclusive for a reason having nothing to do with any model. It was
  caught only because the battery was deliberately run against a known-failing
  probe. **A harness that is only ever run on the data it is meant to judge has
  not been tested.**
