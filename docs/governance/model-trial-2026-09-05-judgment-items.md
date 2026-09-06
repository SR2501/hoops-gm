# Model trial — Task 2 judgment items

**Status:** stimuli and recorded answers, fixed 2026-09-05 **before any Task 2
arm was run**. Companion to `model-trial-2026-09-05-preregistration.md`.

Four artifacts. Each arm is shown one stimulus at a time with **no repository
access**, and asked what it establishes. Ground truth is not my opinion: three of
the four answers are already written down in `gates.md`, from incidents that cost
this project real sessions to find.

**Scored on verdict *and* named mechanism**, 1 point each, 8 available. A verdict
without a mechanism scores half, because the house rule is to state a claim in
the form that lets someone disprove it cheaply, and "this looks wrong" arrives at
the right answer for no reason — the rhetorical-convenience failure `AGENTS.md`
warns about.

**`J4` is the control and is not decoration.** Without it, an arm that answers
"defective" to everything scores full marks on `J1`–`J3`. In a review lane a
confident false positive costs about what a miss costs, and `J4` is the only item
that measures it.

## Provenance, stated plainly

| Item | Source | Verbatim? |
|---|---|---|
| `J1` | `e317694^` — `schedule.py`, resolved-game branch | **Yes**, real pre-fix code |
| `J2` | `gates.md` line 26, recorded defect | **No — reconstructed** to the description |
| `J3` | `gates.md` line 24, recorded mutation result | **No — reconstructed** as a result table |
| `J4` | `e317694` — the same branch after the fix | **Yes**, real post-fix code |

`J2` and `J3` are reconstructions and are labelled as such rather than passed off
as extracts. The incidents are real and recorded; the exact bytes were not
recovered, and saying so costs nothing next to implying an extract I do not have.

The commit message of `e317694` is itself the strongest evidence `J1` is a real
defect and not a puzzle I built: *"A resolved game whose EST and UTC fields both
carry a 1900 epoch placeholder reconciles exactly — 1900's Eastern offset really
is −05:00 — and was parsed and persisted with game_date 1900-01-01. **Verified
before the fix.**"*

---

## J1 — the guard credited with catching an epoch sentinel

**Shown to the arm:**

> This parser reads a sports schedule feed. Each resolved game carries two
> tipoff fields: `gameDateTimeEst`, a wall-clock time in US Eastern, and
> `gameDateTimeUTC`. The feed is known to emit placeholder timestamps for games
> whose time is not yet decided.
>
> ```python
> utc_tipoff = _parse_utc(raw_game, "gameDateTimeUTC", game_id)
> eastern_tipoff = _parse_eastern_wall_clock(raw_game, "gameDateTimeEst", game_id)
> if eastern_tipoff.astimezone(UTC) != utc_tipoff:
>     raise _contract(
>         f"{game_id} has inconsistent EST/UTC tipoff fields: "
>         f"{eastern_tipoff.isoformat()} != {utc_tipoff.isoformat()}"
>     )
> game_day = eastern_tipoff.date()
> ```
>
> A review cited this block as evidence that the parser refuses epoch
> placeholder dates, noting that a placeholder dated year 0001 is rejected here.
> The rejection was confirmed by hand. **Does this block establish that the
> parser refuses epoch placeholders?**

**Recorded answer: no — defective, and it has never done the job it is credited
with.**

The year-0001 value is refused by an accident of the timezone database, not by
the check's logic. `America/New_York` ran on **local mean time, −04:56**, before
1883, so a year-0001 pair misses reconciliation by four minutes. The feed's
*actual* placeholder convention is **1900**, whose Eastern offset really is
−05:00, so a 1900 pair reconciles exactly and is persisted as a real game date.

**Mechanism required for full marks:** the refusal comes from a pre-1883 LMT
offset, not from placeholder detection; a placeholder *pair* agrees, so
reconciliation is structurally incapable of catching one.

Full credit also for reaching the same place by a different route: a check that
compares two fields to each other can only detect *disagreement*, and two fields
carrying the same placeholder do not disagree.

---

## J2 — the test whose refusal comes from the wrong field

**Shown to the arm:**

> ```python
> def test_accepts_a_null_game_date_but_still_refuses_one_that_is_simply_absent():
>     accepted = parse_row({"game_date": None, "reason": "postponed"})
>     assert accepted.game_date is None
>
>     with pytest.raises(ContractError):
>         parse_row({"team": "BOS"})
> ```
>
> The test passed, the name describes the intended behaviour, and it was
> approved in review. **Does it establish that an absent `game_date` is
> refused?**

**Recorded answer: no — defective.**

The second payload omits the sibling `reason` field as well as `game_date`, so
the refusal is raised by the missing `reason` and the date check is never
exercised. Recorded consequence: a mutation widening the date check went
**uncaught** while this test stayed green.

**Mechanism required for full marks:** the "absent" fixture drops two fields, so
the raised error is not attributable to the one under test.

Reading could not have found this. Only a mutation aimed at the check the test
*claims* to exercise could — which is why `NOT CAUGHT` is a failure here rather
than a curiosity.

---

## J3 — the mutation that reddened only a fingerprint test

**Shown to the arm:**

> A sub-condition was deleted from `_require_declared_season`. The suite was run:
>
> | | |
> |---|---|
> | Tests run | 1,247 |
> | Failed | 1 |
> | Failing test | `test_season_module_fingerprint` |
>
> ```python
> def test_season_module_fingerprint():
>     digest = hashlib.sha256(SEASON_MODULE_PATH.read_bytes()).hexdigest()
>     assert digest == "b41f…"
> ```
>
> The result was reported as the suite catching the defect. **What does this
> establish about the behaviour of `_require_declared_season`?**

**Recorded answer: nothing.**

A file-digest check fires on any byte change and would fire for whitespace or a
comment. It is guaranteed to notice and guaranteed not to tell you what it
noticed — the reassuring half of a test, at file scope. The honest reading is
that the sub-condition **survived 1,247 tests**: the behaviour is untested.

**Mechanism required for full marks:** the digest is over file bytes, not
behaviour, so the red is not attributable to the deletion.

Credit also for the second-order point: the surviving row is the finding, and
the untested route is the *likelier* drift.

---

## J4 — control: the same code after the fix

**Shown to the arm:**

> The same parser as `J1`, with one addition:
>
> ```python
> game_day = eastern_tipoff.date()
> if not _plausible_season_date(game_day, season):
>     raise _contract(
>         f"{game_id} resolves to {game_day.isoformat()}, which is not in season "
>         f"{season}; its EST and UTC fields agree, so this is a plausible-looking "
>         "epoch placeholder rather than a parse error"
>     )
> ```
>
> where `_plausible_season_date` tests membership of an eleven-year window
> centred on the season, two-sided. **Does this establish that the parser
> refuses epoch placeholders?**

**Recorded answer: yes — sound.**

The bound is applied to the parsed date itself, so it does not depend on the two
fields disagreeing, and both observed sentinels (`0001-01-01`, `1900-01-01`) miss
the window by 125 and 2,025 years. Two-sided, so a far-future sentinel (`9999`)
is excluded too.

**Full marks require agreeing.** An arm may note that the window is enormous and
would not catch an off-by-one-season date — correct, and explicitly not this
check's job — but an arm that calls this **defective** has produced the false
positive `J4` exists to measure.

---

## What Task 2 cannot establish

- **Arms are blind to the repository**, so scores are a **lower bound** on what
  the same model does in a real lane with `gates.md` open.
- **Reading a defect and avoiding one are different skills.** This measures the
  first only.
- **Four items.** It separates gross differences and nothing finer.
- **I know every answer**, which is why the answers are fixed in this file before
  any arm runs. A procedural guarantee, not a structural one.
