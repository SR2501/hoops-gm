# What thirteen review rounds could not establish about the draft feed

**Recovered 2026-08-27 from the only surviving copy**, a PR-body draft in a
temp directory. PR #104's body was collapsed to fit GitHub's 65,536-character
limit, and the per-round *Could not verify* blocks went with it. The lane that
wrote them believed they were preserved verbatim in `docs/handoff.md`; they
were not - checked with a matcher whose positive control found 3 of 3 known
phrases, and 0 of 16 shingles from these blocks.

**Why this file exists rather than an archive of the whole body.** The verdicts
of those rounds are on `main` already, in the tests and the handoff. What was
only in the body is the record of what each round *failed* to settle - and this
unit gates `draft-tracker`, which the owner named as the one thing that must
work on 18 October.

The blocks are reproduced as written, in order. Nothing is edited; where a
later round superseded an earlier caveat, both are here and the later one wins.

---

## Could not verify

1. **That the recogniser fires on a real Fantrax draft room.** It never has. Every key in `FIELD_ALIASES` is a guess inherited from `parse_draft_picks`. The seat anchor makes a wrong guess produce zero rows rather than wrong rows — but "safe" here means "the board stays empty and the owner keeps typing", which is the thing this unit exists to prevent.


2. **What `getDraftPicks` actually returns.** Results, or tradeable future picks. Unresolvable without a league id.


3. **That the seat anchor excludes a prior season's draft for the same league.** It does not. A correctly-read block about last year's draft, for a league whose team ids are unchanged, would be accepted. The discriminator would have to be a date field, and every date field here is one of the self-describing values this project has already been burned by.


4. **The savepoint path on Postgres.** Migration `0020` was exercised up/down/up on an isolated Postgres 16.9 database, but the per-row `begin_nested()` added in `2bf5a0c` was exercised on SQLite only. That is the dialect difference the savepoint exists for — on Postgres a failed statement poisons the transaction until the savepoint is rolled back — so it is the fix I would most want re-run against Postgres before draft night.


5. **That halting on an out-of-turn pick is right rather than merely safe.** Skipping desynchronises silently; halting stops a live board. I chose the loud failure — but **this is arguably yours to decide, not mine.**


6. **Whether two sources earn their complexity at all**, given finding 1. If the official source never produces anything, the independence guard protects against a defect that cannot occur. Left in because it costs nothing at runtime and adding it later — after the first screen reports corroboration it did not have — is the pattern this project keeps paying for.

## Could not verify

- **The enumeration checks that a bound exists and matches its column — not that the coercer is wired to it.** A guard can be correct and uncalled. The per-rule mutations cover the wiring, and the derived test covers the bounds; **nothing covers both at once**, so a future refactor that stops calling `_as_text` would leave both checks green. Named rather than closed badly.
- **Whether any of the seven bounds is reachable from a real Fantrax payload.** Unestablished, because no real draft-room payload has ever been observed. `locator` is the likeliest — it needs only long key names, and Fantrax uses them. `Decimal("1.9")` is provably *not* reachable from the bridge: `body_json` is a JSON column and the insert fails because `Decimal` is not serialisable. It was fixed anyway, because it is the same generator as the High beside it, one type away.
- **Whether six rounds is convergence.** It is not. Round 5 was the first round clean of the previous round's fixes, and round 6 withdrew that evidence. The trend has not turned.
- **A gate that runs one suite against two engines only discriminates on inputs that differ between them.** The `player_label` defect was invisible to the Postgres job for that reason alone. That is an ADR-001 observation, not a fact about this PR, and it is with `architect`.

## Could not verify, still

- **Whether any of this fires on a real draft-room payload.** No real Fantrax draft payload has ever been seen by anyone on this project; every fixture is constructed. The correct wording is **not disproved, unestablished**.
- **Whether `NaN`, `Infinity`, fractional or non-ASCII-digit values are reachable from a real payload at all.** Unestablished for the same reason. The fixes are cheap and fail closed, which is why they were made anyway.
- **My own instrumentation, three times over on this unit.** The mutation harness silently covered only single-line anchors on one run, because the working tree is CRLF and the anchors were written with `\n`. It was caught only by the harness's own rule — refuse a verdict unless the anchor appears exactly once — which reported `anchor appears 0 times` rather than a false pass. Each of the three was found by a self-check, not by reasoning.


---

## Could not verify

- **Whether the recogniser fires at all on a real draft-room payload.** No real Fantrax draft payload has been seen by anyone on this project. **Not disproved, unestablished.**
- **Whether `name` is the team name in real `draftPicks` records.** If it is, every board row shows the seat's name instead of the player's — **on both paths, with the sources agreeing**, and nothing reporting a problem.
- **Whether the three seam tests describe a reachable payload.** They pin what the parser *does* with values no observed Fantrax response has contained. They are a statement about the code path, not about Fantrax.
- **Whether round nine finds a defect inside round eight's fixes.** Eight for eight. The previous could-not-verify — that nothing covered bound-and-wiring at once — turned out to be concealing three live defects, which is the argument against treating any remaining one as merely theoretical.

**The deliverable is unchanged and not softened: the failure is loud and diagnosable in minutes. A live feed remains unestablished.**

---

## Could not verify — round nine

- **Whether the recogniser fires at all on a real draft-room payload.** No real Fantrax draft payload has been observed by anyone on this project. **Not disproved, unestablished.**
- **Whether the parser-seam tests describe a reachable payload.** They pin what the parser *does*, not what Fantrax *sends*.
- **The guard-wiring hole is narrowed, not closed.** The two new mutations show the AST guard reads the real call site, but **nothing proves a correct-and-uncalled coercer would be caught.** Round eight found three live defects hiding behind a could-not-verify I had written myself — which is the argument against treating any remaining one as merely theoretical.
- **The Adapter gate's live-smoke half converts `pytest` exit 5 into a green** (`c339`, not mine), so the Adapter claim rests on the recorded-fixture half only.

**The deliverable is unchanged and not softened: the failure is loud and diagnosable in minutes. A live feed remains unestablished.**

---

## Could not verify — round ten

- **Two labels for one player arriving with no external id at all.** There is no signal in the payload to detect that with, and nothing here claims to.
- **Whether the recogniser fires at all on a real Fantrax draft-room payload.** **Not disproved, unestablished.**
- **Ten rounds, ten findings.** No convergence evidence stands. Rounds 2, 3, 4, 7, 8, 9 and 10 each found a defect *inside* the previous round's fixes.

**The deliverable is unchanged and not softened: the failure is loud and diagnosable in minutes. A live feed remains unestablished.**

---

## Could not verify — round eleven

- **An id that is readable but *wrong*** — a source publishing one player's id against another player's name. Nothing here detects that, and nothing here claims to.
- **Two labels for one player arriving with no external id at all.** There is no signal.
- **Whether the recogniser fires at all on a real Fantrax draft-room payload.** **Not disproved, unestablished.**
- **Eleven rounds, eleven findings.** Rounds 2, 3, 4, 7, 8, 9, 10 and 11 each found a defect *inside* the previous round's fixes. No convergence evidence stands.

**The deliverable is unchanged and not softened: the failure is loud and diagnosable in minutes. A live feed remains unestablished.**

## Could not verify — round twelve

- **The general "unenforced rules are red" check does not exist**, only the one
  named guard above.
- Whether the recogniser fires at all on a **real Fantrax draft-room payload**
  remains **not disproved, unestablished**. No such payload has ever been
  observed.
- An id that is **readable but wrong** — one player's id against another's name
  — is still undetectable, and the applied-history check makes it *slightly
  worse*: a wrong id now blocks a correct pick.
- Two labels for one player with **no external id anywhere** still has no
  signal at all.
- `identity_already_applied` is recoverable only in the sense that
  `blocked_reason` is recomputed each run. **If the source never republishes
  the original label, the corrected pick stays blocked until the owner types
  it.**

**Twelve rounds, twelve findings. No convergence evidence stands**, and I am
not going to claim any.
