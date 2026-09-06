# OPEN — `adr-index-consistency-test` has five candidate implementations, none merged

**Status:** open. Not blocked on the owner. Needs one reviewer-hour, not a decision.

**Raised:** 2026-09-06 by `architect`, from five trial sessions before archiving them.

---

## What exists

The 2026-09-05 model trial had five arms build the same backlog item. All five
passed the local Code gate. **Winning a trial is not a gate**, so none was merged;
each is preserved at a named commit so the work is not lost:

| Arm | Model | Branch | Commit |
|---|---|---|---|
| A1 | `gpt-5.6-sol-fast` | `sr2501-adr-index-consistency-test-97c` | `72ade0b` |
| A2 | `gpt-5.6-sol-fast` | `sr2501-adr-index-consistency-test-330` | `c76ab20` |
| A3 | `claude-opus-4.8` | `sr2501-adr-index-consistency-test-c62` | `b818cd9` |
| A4 | `gpt-5.6-sol` | `sr2501-adr-index-consistency` | `0f38b2e` |
| A5 | `claude-sonnet-5` | `sr2501-adr-index-consistency-test` | `db07b1e` |

**A4 is the suggested starting point** — cheapest arm, 8/8 on judgment, tidiest
submission. That is a reason to read it first, not a reason to merge it.

## What the arms converged on, unprompted

Three arms, asked separately, gave the same answer to the one question the
backlog explicitly delegated to the implementer: **`PLAIN-ENGLISH.md` is out of
scope.** Each cited the file's own opening banner — it declares itself a *"frozen
historical walkthrough"* covering ADR-001 to ADR-009, states it is not extended,
and names README and the individual ADRs as authoritative.

Independent convergence on a delegated judgement is weak evidence the reading is
right. It is not proof, and the opposite reading has a real consequence worth
stating: requiring one entry per ADR would convert a deliberately frozen document
into a second maintained index. That is a documentation decision, not a test
change, and it should be decided as one.

## Known gaps a reviewer must check before merging

Reported by the arms themselves, unprompted, and **not visible in the diff**:

1. **Displayed number vs linked filename — closed by A3 only, open in the other
   four.** A row displaying `[014]` while linking to a real `ADR-015-*.md` passes
   both directional checks in A1, A2, A4 and A5, because coverage keys on the
   resolved filename. **A3 (`b818cd9`) does not have this gap.** It keys
   Direction-1 coverage on the row's *label* number and emits a distinct
   `index-row-number-mismatch` defect whose message names the cause: *"what a
   rename that moved the target but not the label produces"*.

   This corrects an earlier version of this note, which recorded the gap as
   common to all five. It was wrong, and it mattered: it would have steered
   selection toward an arm that has the defect. Verified 2026-09-06 by reading
   each arm's script rather than its report — A3 emits **12** defect codes
   against the others' smaller sets, and its script is 16.5 KB against A4's
   5.7 KB. That size difference is mostly this.
2. **`ADR_FILE_RE` matches `ADR-0\d{2}` only.** An eventual `ADR-100` falls
   silently outside the file set. Defensible today — README's own format line
   says `ADR-00N` — and it is the first future boundary to review.
3. **Reference-style Markdown links fail closed**, as would `<...>`-wrapped
   destinations. The parser handles the current inline-link table form only. A
   wholesale change away from a table yields "no ADR rows" rather than an error.
4. **URL fragments are not validated.** `ADR-001-local-first.md#missing-heading`
   passes if the file exists.
5. **No semantic comparison** of title, status or summary against ADR bodies, and
   **non-contiguous numbering is tolerated** — ADR-016 is deliberately reserved.
6. **No mutation testing was run** on any arm. Positive controls exist (missing
   row, broken target, malformed row, missing Index section, empty ADR set,
   cwd-independent resolution); attribution was never measured.
7. **Enforcement rides the existing backend pytest suite**, not a named CI job.
   That follows the sibling convention the prompt asked for. A reviewer may
   prefer a discoverable job; that is added scope, not a defect.

## What none of them proved

**Hosted CI never ran on any arm** — all five were left uncommitted by
instruction. Every green result is Windows / Python 3.14 with the worktree pinned
on `PYTHONPATH`, not Ubuntu / Python 3.12 / Postgres. That is the single largest
unverified claim across all five.

## Next action

**Read A3 (`b818cd9`), not A4.** It is the only arm without gap 1, and gap 1 is
the one that changes what the checker catches rather than how it reads. Check the
remaining gaps against it, run the gate on CI rather than locally, and open a
normal PR.

## Two things only A3 could tell us

Recorded 2026-09-06 when A3 was asked, before archiving, what it held that the
commit does not show.

**The `## Index` scoping is load-bearing, not stylistic.** README's
`## Amendments awaiting acceptance` table reuses the *identical*
`| [NNN](target) |` row syntax. A checker that scanned the whole README for
ADR-shaped rows would invent duplicate-row defects for ADR-002, 007, 019 and 020
and **fail the clean live file today**. All five arms happened to scope to
`## Index`; only A3 reported knowing why. Anyone rewriting this from scratch with
a whole-file regex ships something broken on first run.

**The task prompt's own Code gate does not execute on this machine.** It
specifies `ruff check scripts` and `ruff format --check scripts` from the repo
root; bare `ruff` is not on `PATH` here, so both fail with
`The term 'ruff' is not recognized`. A3's sharp observation: an arm that ran them
verbatim and distinguished only zero from non-zero could **misread a PATH failure
as a lint result**. Fix the wording in the gate doc, not just in each arm's head.

**A premise in the backlog item is false.** The item justifies worrying about
`PLAIN-ENGLISH.md` by saying a reader cannot tell "stops at ADR-009 on purpose"
from "stopped by accident". The file's own header already self-declares as a
frozen historical walkthrough, so the reader can tell. The scope decision the item
delegates therefore rests partly on a premise the item got wrong — worth fixing
when the item is next edited, because the next builder will inherit the same
false framing.

*The environment obstacles all five arms hit — `PATH`, the stale editable
install, the `docs/handoff.md` byte hazard — are recorded in
`.github/skills/standup-hoops-gm/SKILL.md` and should not cost anyone turns again.*
