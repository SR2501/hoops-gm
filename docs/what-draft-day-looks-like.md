# What draft day looks like

**Status: owner-reviewed on 2026-08-29.** The owner confirmed five architectural
consequences below and modified two: manual repair is a catastrophe-only
firebreak rather than forbidden, and mock observation informs valuation trust
without deciding it alone. Owner quotations remain verbatim; the implementation
consequences around them are labelled as rulings, not quotes.

---

## The decision he is actually making

> *"On draft day, games played is the aggregate of all this intra-year injury
> data. We're assuming those games are fully healthy. So the decision I'm making
> is: **is sixty games of player X worth more or less than seventy games of
> player Y?**"*

That is the question the tool exists to answer. Not "who is best" - **a
comparison between two players at different availability levels.**

## The thing that dominates it

> *"At the end of the day, **fifty games of an elite player is worth more than
> seventy or eighty games of a role player.** It's just good to have those
> numbers in your mind and in your head."*

**Owner-confirmed 2026-08-29: this is a ceiling on how much the availability
machinery is allowed to matter.** Availability adjusts a comparison between
comparable players. It does not overturn a talent gap. Any recommendation that
downgrades an elite player below a durable role player has almost certainly
over-weighted availability.

> *"I just don't want to put too much energy into that."*

**Owner-confirmed 2026-08-29: taken as scope guidance, not modesty.**

## Volatility is a separate dimension, not a tenth category

> *"The other factor is the volatility of a player based on their consistently
> played or not played games. I almost think that should be **a category of its
> own - not one of the nine**, but something I can **toggle on and off**, along
> with a weighted games played."*

Two distinct quantities, both **toggleable rather than baked in**:

1. **Weighted games played** - expected availability.
2. **Consistency volatility** - whether the games arrive predictably or in
   clumps.

They sit *beside* the nine scoring categories, never inside them. A player who
plays 60 games in a steady rhythm and one who plays 60 in two long stretches
separated by an absence are **different assets**, and the difference is not
visible in a games-played total.

## The real failure mode is portfolio shape, not a bad pick

> *"The most important thing is **not to draft a full team of injury-risk,
> high-risk high-reward players.** You definitely want two or three, because you
> have injury reserve slots."*

**The mistake this tool must prevent is not overpaying for one fragile star. It
is assembling a roster whose risk is concentrated.** And the correct number of
high-variance players is **not zero** - it is two or three.

## Why IR slots make risk an asset

> *"If those are filled with players I can expect to get production back from,
> not only is that production just waiting there on my bench for some time later
> in the season - it also **opens up slots for me to stream more players from the
> waiver wire** as players start to break out, grow into new roles, fill in for
> other injured players, and all sorts of other things that make valuable pickups
> important."*

Two separate returns from one slot, and the second is the one that gets missed:

1. **Deferred production** - a recovering player is stored value.
2. **Streaming capacity** - an occupied IR slot frees an active roster slot.

> *"**You can't do that if you have fifteen healthy guys who are just pretty good
> and reliable.**"*

**A fully healthy roster is not the safe outcome. It is an illiquid one.**
[architect inference: this inverts the naive objective. "Maximise expected games
played" is the wrong target.]

## The summary, in his words

> *"So it's a strong balance. I need to have **realistic, near-accurate
> projections**, and I also need to be **mindful of injury health and volatility
> of player performance**. Got to balance the whole portfolio."*

---

## What this changes about what gets built

**Owner-confirmed 2026-08-29.**

1. **The draft recommender is a portfolio constructor, not a ranker.** It must
   be able to say *"you already have three high-variance players; this is your
   fourth"* - which requires it to know the shape of the roster so far, not just
   the value of the next player.
2. **IR slots are a modelled asset.** Their value is deferred production **plus**
   the streaming capacity they unlock. Nothing currently plans to model the
   second.
3. **Volatility is a first-class quantity with a toggle**, distinct from expected
   games. It needs its own definition, its own evidence, and a UI control.
4. **Availability has a ceiling on its influence**, and a recommendation that
   places a durable role player above an elite fragile one should be treated as
   a symptom rather than a result.
5. **"Maximise expected games played" is explicitly rejected as an objective.**

---

# The questionnaire, answered

**Captured 2026-08-26 and 2026-08-27, then owner-reviewed 2026-08-29.** Fourteen
of fifteen. Quoted text is the owner's; the unquoted consequences are the seven
rulings recorded below.

## Part 1 — The room

**Q1. Where are you sitting, and on what?**

> Laptop with at least one external monitor. Phone close by. Samsung tablet
> available if there is a reason. Expecting draft companion in an overlay or
> separate app with **realtime awareness of draft status so that I don't need to
> input all of that information**.

**Owner-modified 2026-08-29:** Automatic tracking remains load-bearing. Manual
pick or state repair is permitted only as a catastrophe firebreak so a capture
failure cannot ruin the draft. Build vigorously against needing it and fail
loudly before asking the owner to repair state. The existing draft recorder is
that emergency mechanism: it posts append-only pick, nomination, bid and sale
events, and the draft log records corrections as void events. It is not a normal
parallel workflow or a quiet fallback.

**Q2. Who else is in the room, and can they see your screen?**

> Remote — everyone's on their own machine, nobody sees my screen.

**Owner-confirmed 2026-08-29:** The remote room creates no discretion constraint.
Important warnings may be visually loud, but may not obscure Fantrax controls or
overwhelm the owner.

**Q3. How fast does the auction move?**

> Usually **2 minutes per pick** with a limited bank. Sometimes there is
> positional trading, but since we're auction this year, that should not be an
> issue.

**Owner-confirmed 2026-08-29:** A typical two-minute auction pace supports
readable evidence behind a recommendation. The old 8-30 second glance-only
constraint does not govern.

## Part 2 — The moment

**Q4. It's your nomination. What do you want on screen?**

> Per game and per 36 projections, sorting by position and category and team,
> **visibility on other teams' positional and categorical needs**, punt
> suggestions and awareness — if it's obvious another team is punting a
> category, it should be visible somewhere. Kind of the way BBM uses RED for
> poor performance and green for excellence; some way to show me that of the 4
> teams who still have not passed on a player, **only one of them is really
> competitive in a top category**.
>
> As the tier 1 point guards go off the board, it should be visible that **top
> assist makers or ball stealers may be at a premium**.
>
> There will be a point where I'm **competing with another player who has
> stumbled into the same build strategy** — this might mean we're both willing
> to overpay.
>
> There will also be **pivot opportunities** — if a player is priced well under
> projections.
>
> Essentially, **having an agent to talk through the choices with** is probably
> ideal.
>
> **Hard stop points during bidding, calculated at the time of a player
> nomination, with rationale included.**
>
> There may be times where I sit back and wait for players to go off the board
> to equalize money pool, or let players go so that I can **bully people with a
> bigger bank roll**. The mocks will help with some of this.

**Q5. Someone else nominates. Same screen?**

> Mostly the same, but the **hard stop / max bid matters more**.

**Q6. The single number you most want right**

> The **projections** are the most important thing. After per game / per 36
> would be the **reliability**. Games played being low isn't a non-starter — it
> just decreases the overall value. The most important number, if it can even be
> reliably projected, is probably the **player reliability metric**.
>
> Good production from an unreliable player is the most frustrating part of 2026
> fantasy basketball and the thing that makes so much maintenance necessary.
> **That said, if the system can manage the chaos for me and handles suggestions
> and lineup choices, then a lot of this is moot anyway.**

**Owner-confirmed 2026-08-29:** In-season lineup management changes the draft
cost of unreliability: a system that manages the chaos makes an unreliable player
less expensive to own. The lineup manager must not remain the first feature cut.

**Q7. When should the tool tell you you're wrong?**

> **Tell me loudly**, but understand this is fun and there will always be one or
> two **heart picks** that override head picks. They have to be the exception. A
> **red warning banner, with the category of warning or multiple categories
> listed**.

**Owner-confirmed 2026-08-29:** Advise everywhere, override nowhere. Warn loudly,
but never veto an owner draft pick. Fail-closed refusals for invalid or unsafe
automation are a distinct safety boundary and remain intact.

## Part 3 — Money

**Q8. Budget and habits**

> I think **200**, but it's **slightly different per team based on last years'
> final totals**. I like to bid later if I can maintain the discipline. There
> needs to be some **policing** on picks going for way too cheap. Sometimes you
> bid on someone just to play defense, then **win some of those bids
> accidentally**. **The bad habit would probably be over policing.**

**Q9. Halfway through and over budget**

> The **full draft board with vertical categories per team**. **Who is winning
> each category** — a **tier list for all of the owners, based on expected
> performance, 1 to X in rebounds**. So I can see categories I'm deficient in
> and excelling in. At some point **punt recommendations become more
> important**. **Deciding actively how many categories to compete in.**

**Q10. The worst thing that can happen**

> A roster full of injury risks — exactly what I said before.

## Part 4 — Trust

**Q11. What would make you believe a $34 valuation?**

> A little of both doesn't hurt. **We will probably refine as the mocks get
> worked.**

**Owner-modified 2026-08-29:** Early mocks and observed reactions carry
meaningful weight when refining valuation trust, but are neither the sole nor a
100% deciding instrument.

**Q12. What would make you close the laptop?**

> **It loses track of the draft — shows me picks that already happened or misses
> one.**

## Part 5 — The honest ones

**Q13. What do you already do well that the tool should not touch?**

> Nothing really — I want help with all of it.

**Q14. What do you always get wrong?**

> Definitely **valuing injured and unreliable players too highly**, and **not
> knowing when to cut someone who is proven to have been a bad pick**. Overall
> evaluation, and **not feeding back on my own bias**.

**Q15. If you could only have ONE thing working on 18 October**

> **The live draft board with picks and budgets tracked automatically.**

Added the following morning, unprompted:

> Another thing to include in the live draft support is **addressing positional
> need**. Usually going for categories means **leaning too far into Guards,
> Forwards or Centers**, and inevitably there will be some **positional players
> who slip**. On that same tier, **stats out of position are especially
> valuable**. That will almost certainly be included in ADP. Not sure how to
> quantify that, but it is good to be aware of.

---

## What Q15 changed

`draft-tracker` — the live board — does **not** sit behind the nine-item
valuation chain. `auction-budget-manager` depends on `draft-tracker`, not the
reverse. Six of its seven dependencies were already done when he answered; the
seventh, `draft-tracker-bridge-feed`, merged as #104 on 2026-08-27.

**Q12 is why #109 exists.** The draft feed merged with one known defect — a
record whose player id is unreadable is counted at ingest and never surfaced on
`GET`, so the board is silently short a player with every channel reading clean.
That is Q12 verbatim, so the fix is a **dependency edge** rather than a caveat:
`draft-tracker` cannot be marked done while it exists.

## Named by him, and not in the backlog

1. **A live league category table** — every team ranked 1-to-N in every category
   on expected performance. Asked for twice, in Q4 and Q9.
2. **Rival-strategy detection** — the other GM converging on his build.
3. **Positional scarcity tipping points.**
4. **Out-of-position production** — distinct from scarcity.
5. **An agent to talk choices through with** — a different surface from a
   dashboard.
6. **An over-policing warning** — his self-named bad habit.
7. **Per-team budgets.** Confirmed not representable: `DraftParticipant` has no
   budget column, `auction_budget` is one scalar on `Draft`, and
   `draft/state.py:680-682` derives every seat's remaining budget from it.
8. **A personal bias feedback loop** — from Q14. The only requested feature that
   improves with use, and it cannot begin until he has drafted once.

## Owner review

All seven architectural consequences were ruled on 2026-08-29: five confirmed
and two modified. No unresolved inference marker remains on this page.
