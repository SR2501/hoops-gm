# OPEN: What we walk into 18 October with

**Raised:** 2026-09-05 by `architect`
**Status:** Open. Decision 2 accepted on 2026-09-06; Decision 1 and the three owner actions remain unresolved.
**Risks:** R35, R37, R40

---

## The short version

**The valuation half of draft day cannot ship as specified.** The board half —
the thing you named as the one thing that must work — is unaffected and is now
the whole deadline.

Nothing has gone wrong. The governance did exactly what it was built to do: it
refused to produce a confident, plausible, wrong availability number. But the
*consequence* of that refusal has never been written down, and you have never
been asked what to do about it. That is what this document is for, with 29 days
to the rehearsal boundary rather than three.

---

## What cannot ship, and the mechanism

`draft-day-synthesis` — one versioned run on the morning of 18 October producing
our own rankings and dollar values end-to-end — needs this chain:

```
availability-model -> expected-games -> zscore-engine -> gscore-engine
  -> risk-adjusted-valuation -> auction-values -> draft-day-synthesis
```

**`availability-model` is fit-vetoed, by a protocol you accepted on 2026-09-01.**
Your acceptance of availability preregistration v1 explicitly left
`FIT_VETOED_PREREQUISITES` binding. Its `PROCEED_COMMON` gate requires:

- **four direct seasonal censuses.** 2023-24 and 2024-25 currently hold *zero*
  protocol-eligible observations.
- **`unknown_share <= 0.05`**, overall and per season. This is not failing — it
  is **not calculable**. There is no independent roster-interval evidence to
  compute a denominator from.

The last point is the hard one, and it is not a matter of effort.
`nba-official-transactions` was built, is live, and works — 9,777 rows back to
2015. Its own boundary section states it emits **no player-game rows**. The NBA
publishes no structured contract-expiration, retirement, or assignment event,
and there is a documented counterexample: James Wiseman's release is recorded in
the Pacers' own 2025-12-26 notice and is **absent from the central archive**.

So the denominator cannot be built from what we ingest, and no amount of
schedule pressure changes that. Six items sit behind it, five of them Model-gated.

**Check this cheaply if you want to:** `docs/models/availability-model-preregistration-v1-PROPOSED.md`
section 22 and the `PROCEED_COMMON` block; the "What this does not establish"
section of `docs/adapters/nba-official-transactions.md`.

---

## What this does *not* touch

**Your Q15 — "the live draft board with picks and budgets tracked
automatically" — depends on none of the above.** Its chain is:

```
fantrax-auction-capture -> draft-board-feed-integration -> draft-tracker
```

That chain is blocked on **one thing, and it is yours**: a real Fantrax NBA
auction room seen through the userscript. Every auction field name in
`FIELD_ALIASES` — `amount`, `bid`, `salary`, `price`, `winningBid` — is a guess.
The snake mock ran with `isAuction=false`, so nominations, bids, prices and
budget derivation have **never been observed even once**. The same guessing
already produced `teamId` where Fantrax actually sends `draftTeamId`, and one
afternoon on a snake mock found a defect that would have emptied the board.

---

## Decision 1 — accept or decline ADR-021

`docs/decisions/ADR-021-draft-day-without-availability.md` proposes that draft
day ships:

1. the live board (Q15);
2. our own per-game projections and category values, **unadjusted for
   durability**;
3. published seed AAV beside them, never blended (this is ADR-017);
4. a durability panel showing **observed games played with its unknown share
   published** — an observation, displayed beside the value, never fused into it.

Point 4 is the compromise worth understanding. You would see who missed games
and how much we don't know, without the tool pretending it has modelled why. It
fits nothing, so it does not touch the veto you accepted.

**What you lose:** fragile stars and durable ones will look the same in the
dollar value itself. That is the thing this project exists to fix, and on
18 October it will not be fixed. Saying so on the screen is the whole point.

## Decision 2 — ADR-017 accepted on 2026-09-06

The owner approved proceeding without waiting for mock-draft price data,
keeping our player valuations and published market prices separate. See
`docs/decisions/ADR-017-auction-pricing-without-mock-corpus.md` for the exact
question, answer and acceptance scope. The delivery architect must remove the
obsolete market-data prerequisites from the auction path; recording acceptance
does not itself change the backlog dependencies or implement the recommender.

ADR-021 remains `Proposed`. The owner instead requested live, strategy-aware
3-5-player suggestions with visible health/load-management effects, using BBM
projections as a baseline; a descriptive durability panel alone does not meet
that requirement. The current ADR statuses are in `docs/decisions/README.md`.

---

## Three actions only you can take, with expiry dates

These are the items where a lost day is **unrecoverable**. None is agent work.

| Action | Outstanding since | Why it expires |
|---|---|---|
| **One Fantrax NBA auction room** through at least one nomination and sale, userscript loaded, per `docs/mocks/instrumented-capture.md` | 2026-08-22 | Lobbies open early October. The gap between first auction payload seen and 18 October could be **days**, with no slack to fix what it finds. This is the only blocker on your Q15. |
| **One blind ESPN NBA auction mock**, by hand, per `docs/mocks/TEMPLATE.md`, without this tool | 2026-08-26 | ESPN is running them **now**. Auction lobbies are seasonal: a mock not run in September cannot be run in November. It is also the uncontaminated control group — running it *with* the tool destroys it. |
| **Basketball Monster workbooks**, one per named projection source, per the exact export contract in the 2026-09-05 coordinator handoff | 2026-09-04 | Projections rank above reliability in your own answers, and are now the *only* input to draft-day values. |

**There is no fallback for the first one, confirmed 2026-09-05.** The retiring
coordinator session was asked directly what auction evidence it held and
answered: none. No private NBA auction-room capture, payload, nomination, sale,
price, participant or source-column evidence exists anywhere outside the
repository. Everything positive on the board path is snake and explicitly
non-transferable — ADR-020 records 49/49 captures with no observable `/fxpa`,
42 parsed rendered-board captures and a completed **216-pick football snake**
board, and `draft-feed-what-thirteen-rounds-could-not-establish.md` records
where that stops. None of it establishes NBA auction identity, nomination, sale,
clearing price, or source-column binding.

**One step in that capture is easy to skip and invalidates the rest.**
`docs/mocks/instrumented-capture.md:113-116` requires watching
`capture_order_disputed`: if the browser's capture order and arrival order
disagree, **neither reading applies**. The first auction room must be driven
through at least one *completed sale* with that check exercised — a room joined
and left before a sale settles does not answer the question.

`preseason-news-ingest` must also be working **before 5 October**, not during
it — the season opens after the draft, so the per-game injury report covers
nothing on the day it matters most. That one is ours, not yours.

---

## What I could not verify

- **That the durability panel in ADR-021 point 4 is safely computable.** It
  reports a rate over *confirmed-observed* games with the unknown share beside
  it, which is what makes it honest — but nobody has driven it against the store,
  and the same player-specific silence that blocks the denominator
  (`player_id` 893, 2154, 5109) will appear in it. If the unknown share is large
  enough that the panel misleads, it should not ship, and that is a Model-gate
  question I have not put to `quant`.
- **That four censuses plus a roster-interval source is genuinely unreachable by
  4 October**, as opposed to merely unreached. I read the adapter's own boundary
  statement and the protocol's gate; I did not independently survey what other
  sources exist. If you know of one that publishes dated roster starts and ends
  including contract expiry, this whole document is wrong and that is the best
  possible outcome.
- **Whether you would rather have a durability-adjusted number you distrust than
  none at all.** I have assumed not, on the strength of the protocol you
  accepted four days ago. It is your call and I may have read it too strictly.
