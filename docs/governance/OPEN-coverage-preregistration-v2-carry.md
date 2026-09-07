# OPEN — what must be carried into a coverage preregistration v2

**Status:** open, unowned. Not a decision. Nothing here may be applied to v1.

`docs/models/participation-opportunity-coverage-preregistration.md` was frozen and
merged as PR #165 at `a0b78d8`, frozen head `3267da0`. Its own section 7 says a
changed date, population rule, threshold or predicate requires a v2.

**Everything below was learned after that merge.** It is recorded here, outside the
frozen document, precisely so that it cannot be retro-fitted into v1 and made to
look preregistered. Amending a preregistration after discovering it cannot be
satisfied is the exact move the author/custodian separation exists to prevent, and
it would destroy the artifact's value retroactively rather than improve it. The
author was asked to make two of these clarifications directly and **declined, for
that reason**. That refusal was correct and is the reason this file exists.

---

## 1. Four defects for v2 to fix

**a. The document cannot express its own precommitted failure state.** Section 4
types the counts as nonnegative integers with exact division, while section 5
contemplates an evidence failure in which no count exists. There is no way to say
"not calculable" in the shape section 4 demands. Found by the report lane when it
tried to comply with both at once.

**b. The empty set returns PROCEED.** `unknown * 100 <= total * 5` evaluates
`0 <= 0` → **true**. A report emitting zeroes would render as coverage passing,
which is the strongest possible false green: produced by having no data at all.
v2 must require a non-vacuity precondition on the predicate itself, not merely on
the prose around it. `scripts/check_append_only.py` already prints a `VACUOUS`
marker for this exact hazard and is the convention to copy.

**c. Criterion 2 is materially larger than the backlog's shorthand for it.**
`docs/backlog.md` characterises the coverage report as "descriptive counting over
existing rows, nothing fitted." It cannot be, until an independent denominator
exists. The source registry, reconstruction contract, canonical roster-interval
and schedule manifests, independent reproduction, ancestry and cohort-key digest
are not report ornamentation — they are the mechanism that makes the counted thing
a reproducible at-risk cohort rather than a denominator inferred from
participation silence. The backlog wording should be corrected to match.
**The backlog half of this is done, 2026-09-06, `architect`.** `docs/backlog.md`
no longer calls the coverage report "descriptive counting over existing rows"; it
now names the registry, contract, manifests, reproduction, ancestry and digest as
the mechanism rather than ornamentation, keeps *nothing fitted* (which is what
makes it a Code gate rather than a Model gate) and cites this section. **The defect
itself stays open**: correcting a shorthand is not fixing v2, and (a), (b) and (d)
are untouched. Recorded here so the same correction is not made twice, and so that
"open" continues to mean the v2 document, not the pointer to it.

**d. The evidence cites by line range into a living file, which freezes that file
above the range.** `participation-opportunity-coverage-v1-evidence-gap.json` cites
`docs/backlog.md` lines 3623-3661 by hashing those exact line *positions*, and
`test_evidence_citations_are_bound_to_the_exact_committed_files` re-hashes them. So
any insertion above line 3623 shifts the block and breaks a Model gate while leaving
the quoted prose completely untouched — and `docs/backlog.md` is the most-edited
document in the repository, the one every lane appends an item to.

Demonstrated rather than predicted, on 2026-09-06: a 36-line append beside an item
near the top of the file broke the citation, was reverted in `431de99e`, and re-landed
below the cited range in `9ac853fd`. Only the line *count* above the range matters, so
in-place edits of equal length are safe — the pointer left at the original item and the
header recount are both same-line-count rewrites for that reason. That is a subtle
rule to have to know, and nothing states it at the point of edit.

The evidence must not be re-recorded to follow such a move: it is frozen, and this
document forbids retrofitting into v1. So the constraint is real for v1's lifetime and
the remedy is placement, not adjustment.

**v2 should cite content, not position** — copy the quoted text into the evidence file
and hash that, or address it by a stable anchor such as the item heading. Either
decouples an unrelated edit from a Model gate. The interim mitigation added the same
day is a failure message naming the file, the range, the shifting mechanism and where
to put content instead; it converts a mystifying hash diff into an instruction, but it
does not remove the coupling.

**And note what CI does and does not measure on `main` — corrected, because the first
version of this paragraph was wrong.** It claimed this gate does not run on `main`,
that a push to `main` gets CodeQL and no backend suite, and that the broken citation
was caught only by a local run. All three are false. Measured across the six
consecutive `main` commits pushed on 2026-09-06:

| Commit | Check runs | Backend suite |
| --- | --- | --- |
| `ddc82476` | 3 | not run |
| `90ab3d83` | 14 | **failure** |
| `431de99e` | 14 | success |
| `8139df6d` | **0** | not run |
| `9ac853fd` | 3 | not run |
| `79dab9d0` | 14 | success |

**CI caught the break.** `90ab3d83` records `Backend — lint, type-check, tests` and
`Backend — the same suite against Postgres` both as `failure`. The local run found it
first only because it finished first; the revert landed before anyone read the remote
result, and the claim that CI had missed it was then asserted without checking. That is
the same failure this document is about, committed in the paragraph describing it.

**The real defect is erratic coverage, not absent coverage.** Concurrency cancellation
means a commit superseded before a runner picks it up is measured partially or not at
all — `8139df6d` has **zero** check runs of any kind. So history contains commits no
gate ever evaluated. That breaks `git bisect` against any gate, and it makes "`main` was
green at commit X" unfalsifiable for the commits it happens to skip. The tip is reliably
measured; the path to it is not.

The practical rule is unchanged and is worth keeping for a different reason than the one
first given: run the suite locally before calling a `main` tip green, because the remote
result for the commit you are standing on may not exist yet, or at all.

---

## 2. Season boundary provenance, which the frozen document does not enumerate

v1 records that provenance is mixed and that only 2022-23 came from search. It
does not name the files. It should, because one of these four is materially weaker
than the other three and a reader currently cannot tell which.

| Season | Window | Source | Independent corroboration |
|---|---|---|---|
| 2022-23 | 2022-10-18 – 2023-04-09 | **Web search citations only** | **None in-session.** Direct NBA press-release fetch returned **HTTP 403** |
| 2023-24 | 2023-10-24 – 2024-04-14 | `backend/tests/model_evidence/reliability_metrics_v2.json` (`source_cohorts.2023-24.first_game_date` / `last_game_date`) | `docs/adapters/participation-ledger-2023-24-coverage.json`, all 1,230 finals (does not print boundary dates) |
| 2024-25 | 2024-10-22 – 2025-04-13 | same committed reliability evidence fields | committed 1,230-final-game direct census |
| 2025-26 | 2025-10-21 – 2026-04-12 | same committed reliability evidence fields | committed full-season injury-report cohort record naming that exact 164-game-date window; direct census records 1,230 finals with three participation-source outages that do not move the boundary |

**Sources rejected, and why — worth keeping so nobody re-admits them.** An AI web
search claimed the 2025-26 schedule was "not yet officially announced as of
September 2026" and that the 2024-25 end date was unpublished. Both are
temporally impossible and contradicted by committed evidence fixing 2024-25 at
2025-04-13 and 2025-26 at 2026-04-12. Every later-season claim from that response
was discarded wholesale; only the 2022-23 boundary was retained, and only because
it was consistent across two independent citations. NBA.com's 2024-25 schedule
page also returned **HTTP 403**. Do not retry either URL unchanged.

**Also:** the ADR is `docs/decisions/ADR-002-production-vs-availability.md`. The
plausible-looking `ADR-002-separate-production-and-availability.md` does not exist.

---

## 3. The 2022-23 ceiling is load-bearing and must not be relaxed in v2

2022-23 is not a fitting target partition, so exempting it from the 5% per-season
ceiling looks harmless. It is not. The accepted availability protocol requires the
2025-26 Marcel comparison to use direct opportunity histories in each of the three
immediately prior seasons, so unknown opportunity mass in 2022-23 corrupts both
the trailing direct-history construction and the Marcel reference population used
to decide whether a contextual model earns its complexity. The merged v1 does
carry the Marcel rationale; it does not state this causal chain as plainly as it
should.

---

## 4. Why this is not one lane's opinion — and was not news

**The repository already established this before either lane ran**, and that is a
stronger position than two agents agreeing.
`docs/adapters/nba-official-transactions.md:165-207` states outright that the
increment "emits **no player-game rows**", that "the independent denominator does
not yet exist", that "neither the overall nor any per-season `unknown_share` is
calculable, and the protocol's `<=5%` gate remains unmet", and that
`FIT_VETOED_PREREQUISITES` remains binding. It also names the precise next
trigger. Anyone treating tonight's result as a surprise has not read that file.

Two independent confirmations arrived on top of it, from different evidence and
with no contact between them:

- The preregistration author, before any classification was attempted, declined to
  name a source list at all — calling an invented one "fake determinism" — and
  said the preregistration may legitimately stand as a permanent veto.
- The report lane then stopped before editing anything and cited that adapter
  document together with `docs/backlog.md:3508-3546`.

**The obvious fallback is already disproved, which is the most useful thing here.**
A six-team 2025-26 `CommonTeamRoster` feasibility probe found transient Conley
stints with Chicago and Charlotte, and Wiseman's Indiana stint, **absent** from
season-scoped responses. That endpoint cannot enumerate historical stints and its
nullable `HOW_ACQUIRED` prose cannot repair them. So "just pull the rosters" is
not an unexplored option; it was explored and it failed.

**What an adequate source would have to supply**, so that acquiring one is an item
with acceptance criteria rather than a wish — quoted from the adapter doc's own
trigger: complete opening membership; dated starts and ends **including contract
expiration**; assignment and recall; suspension; and same-day boundary handling,
**for all four seasons**. Note the CBA complication that makes this hard rather
than merely tedious: the 2017 and 2023 CBAs define a G League assignment interval
by when the player physically reports to the affiliate and when he reports back
after recall, and the transaction feed does not publish those reporting instants —
so an `Assigned` or `Recalled` notice cannot by itself establish game-specific NBA
eligibility.

Acquiring and validating such a source is Adapter-gate work and a separate backlog
item. If it requires a paid subscription it is an **owner-only decision**.
