# Mock draft capture

Run mocks now. Record them here. The value evaporates if they aren't captured in a usable shape.

**Running a mock *with* the userscript loaded is a different experiment** and is
described in [instrumented-capture.md](instrumented-capture.md). Do not run both
in one session: a blind mock is only blind if nothing observed it.

## Why blind mocks matter more than they sound

A "blind" mock is one run **without the tool** — before it exists, or with it deliberately not consulted. It is not a degraded version of an instrumented rehearsal. It is a different experiment, and three of its properties cannot be recovered later:

1. **It is the uncontaminated control group.** R38 records the circularity risk: once we bid using our own model's values, the corpus contains our own output and the feedback loop self-reinforces. A mock run before the tool exists is *definitionally* clean. It is the only market evidence that can never be accused of echoing us.

2. **It is the counterfactual.** Without a record of how drafting went *without* the tool, there is no baseline to measure the tool against. "Did this actually help?" becomes unanswerable. That measurement is only available before the tool is used, and never again.

3. **It captures the other managers, not just you.** Nine to eleven other people bidding real dollars on real players is exactly the AAV evidence R37 needs — and it starts accumulating immediately, at zero cost, off the critical path.

There is a fourth, quieter benefit: **it is requirements-gathering under real time pressure.** Every moment of *"I wish I knew X right now"* during a live auction is a specification for the overlay, discovered by experience rather than imagined at a desk.

## Schedule value

The rehearsal window is 5–18 October, the tightest part of the plan. Every blind mock run before then is corpus that does not have to be gathered inside it. If the build slips, the market data still exists.

## What to capture, per mock

Copy `TEMPLATE.md` to `YYYY-MM-DD-site.md` and fill it in — ten minutes afterwards, while it is fresh.

**League configuration is mandatory, not optional.** AAV does not transfer between configurations (R39): a $200 budget in a 12-team league with 13 roster spots produces entirely different dollar values than $100 in a 10-team with 10 spots. Without the config, the prices cannot be normalised and are unusable.

## Known limitation, recorded honestly

Mock auction participants behave differently from real ones. Some autodraft, some disengage, some bid carelessly because nothing is at stake. Expect mock clearing prices to be **noisier and probably softer** than a real draft, particularly late as people lose interest.

This does not make the data worthless — it makes it a *source with a characteristic bias*, which is exactly how the blending layer already treats every other source. Record the site and the apparent engagement level so calibration can weight accordingly.

## Where this data goes

| Consumer | Uses |
|---|---|
| `mock-ingestion` | Imports results through the identity layer |
| `aav-empirical` | Aggregates clearing prices into an AAV source of its own |
| `auction-inflation` | Observed price movement as money leaves the board |
| `opponent-calibration` | Tunes simulated opponents from real behaviour |
| `model-vs-market` | The divergence report, once our own values exist |
| `overlay-auction-panel` | The "I wish I knew X" notes are its requirements |
