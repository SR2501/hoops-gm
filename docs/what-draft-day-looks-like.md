# What draft day looks like

**Status: draft, captured from the owner's own words on 2026-08-26. Not yet
confirmed by him.** Everything below is his framing; the headings are mine.
Where I have inferred a consequence rather than quoted him, it is marked
**[architect inference]** so he can strike it.

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

**This is a ceiling on how much the availability machinery is allowed to
matter.** Availability adjusts a comparison between comparable players. It does
not overturn a talent gap. Any recommendation that downgrades an elite player
below a durable role player has almost certainly over-weighted availability.

> *"I just don't want to put too much energy into that."*

**Taken as scope guidance, not modesty.** [architect inference]

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

**[architect inference throughout this section - all of it is refusable.]**

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

## What is still missing from this page

The questions in
`files/what-draft-day-looks-like-QUESTIONS.md` that this did not answer:
the room and the screen, how fast the auction moves, what he wants visible at
his own nomination versus someone else's, his budget habits, what would make him
close the laptop, and **question 15** - if exactly one thing works on 18 October,
what is it.
