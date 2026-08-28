# ADR-018: `p(play)` calibration is displayed beside the number it grades

- **Status:** Proposed
- **Date:** 2026-08-27
- **Deciders:** owner (ruled the substance on 2026-08-27; accepts), architect (proposes)
- **Supersedes:** nothing. **Amends:** nothing.

## Context

`docs/models/injury-status-conversion-preregistration-v3-PROPOSED.md` was put to
the owner as a binary. **Bind it** and v3 §4's Change B becomes §8 condition 9:
calibration-in-the-large restricted to the held-out `questionable`, `probable`
and `doubtful` rows must clear 0.10 or the model does not activate. **Decline
it** and v3 §7 applies — the same figure is computed post-hoc, published beside
the model and gates nothing: *"the second one stops being a brake and becomes a
footnote."*

He took neither:

> *"Why not just make a visible confidence score on your confidence score? If
> it's too complicated I'll tell you to flatten or remove it, but we get nothing
> if we don't try."*

## Decision

**The restricted calibration figure becomes a displayed quantity — not a gate
input, and not a footnote in a document.** For implementers:

1. Compute it exactly as v3 §4 specifies: CITL and the §7 binned table over
   held-out rows carrying `questionable`, `probable` or `doubtful` only. The
   computation is unchanged; only its consumer is.
2. **Render it adjacent to every displayed `p(play)`-derived quantity**, on the
   same screen. A grade behind a click is the footnote this ruling rejects.
3. Carry the **model version** and the **`n` it was computed over**. Below v3
   §6's floor of 30 held-out direct outcomes for a status it renders as a count
   and a refusal, never as a grade.
4. **It blocks nothing.** No activation, valuation, recommendation or bid may be
   refused on its value. Q7 governs: advise everywhere, override nowhere.
5. **One control flattens it, one removes it** — owner-facing, the same shape as
   the volatility toggle. Visible by default.

## Rejected

**Bind (the auto-brake).** A gate that stops an activation is the model-shaped
version of a tool that refuses a pick, which Q7 rules out.

**Decline-as-footnote (v3 §7).** Correct, computed, and read by nobody at 8pm on
18 October.

## The claim this rests on, stated as a claim

A score the owner can ignore **is** what §7 calls a footnote. The asserted
difference is only that a footnote in a document is invisible while a badge
beside the number is not. **Nothing has tested whether that difference survives
a live auction.**

## What would flip this

The owner saying flatten or remove — his own words license it. Or a rehearsal in
which he bids past a badge reading badly without pausing: the badge has then
been shown not to work, and the choice returns to bind-or-footnote as an owner
decision rather than as an inference from this one.

## Consequences

v3 stays `Proposed`, v2 governs, and §8 keeps eight conditions and gains no
ninth. **The restricted figure is now load-bearing for a screen**, so it cannot
be dropped as merely post-hoc. v3's Change A (the era sensitivity) is untouched
here and still owed an answer.
