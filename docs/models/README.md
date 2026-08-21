# Model cards

One card per model that produces a number a decision rests on. Required by the **Model gate** — see `docs/governance/gates.md`.

A model card is not documentation of the code. It is a statement of what the model claims, how well it actually performs on data it has not seen, and — critically — **what it cannot see at all**.

Projection-model experiments also follow the
[`projection experiment sequestration protocol`](../governance/projection-experiment-protocol.md):
workers receive only immutable released packages, and held-out outcomes remain
sealed until a pre-registration is frozen.

## Normative minimum

Every model card must cover the metadata and content below. A card may add
model-specific sections or use clearer model-specific headings, but this
minimum content must remain explicit.

```markdown
# <model name>

**Owner:** quant
**Version:** <n>
**Status:** <in development | active | retired>

## What it predicts
One sentence. Be precise about the unit and the window.

## Inputs
Every feature, and where it comes from. Note anything derived from another model,
since errors compound.

## Method
Enough that someone could rebuild it. Note what was tried and rejected.

## Training window
Which seasons, and why. Note any recency weighting.

## Evaluation
Held-out data only — never evaluate on what you fit on.
For probabilistic outputs, **calibration is the primary metric**: a reliability
diagram or binned calibration table. Accuracy alone is not sufficient and can be
actively misleading.

## What this model cannot see
Mandatory. Trades, coaching changes, undisclosed injuries, personal matters,
front-office intent, locker-room dynamics. Be specific and be honest — this
section is the most useful part of the card.

## Known failure modes
Where it is unreliable and why. Rookies, players returning from long absences,
mid-season role changes, small samples.

## Change log
Version, date, what changed, and the effect on evaluation results.
```

## Why calibration, not accuracy

A model that says 70% and is right 70% of the time is more useful for a lineup decision than a higher-accuracy model that is overconfident. The owner acts on these probabilities — an overconfident 90% that is really 65% produces bad starts and bad sits, and does so invisibly.

## Expected cards

- [`schedule-context.md`](schedule-context.md) — opponent context and blowout probability
- `availability.md` — per-game `p(play)`
- `injury-status-conversion.md` — report status → actual play rate
- `shutdown-risk.md` — late-season shutdown probability
- `baseline-production.md` — in-house per-game production model
- [`projection-blending.md`](projection-blending.md) — deterministic,
  user-configured per-game source blending; no learned source-quality claim
- `contingent-value.md` — usage redistribution on absence
- `auction-inflation.md` — live price movement during an auction

## Frozen pre-registrations

A pre-registration is not a model card and does not claim the Model gate. It is
the protocol — question, cohort, splits, metrics, decision rule, stopping rule —
committed **before** the held-out outcomes are examined, so that a later result
can be read against a plan nobody could have adjusted to fit it. A card reports
what happened; a pre-registration constrains what may be reported.

They live here beside the card they will eventually be read with, and they are
never amended in place: a change before any unblind is a new dated freeze naming
the prior one, and a change after an unblind creates a new version and may not be
presented as pre-registered.

- [`injury-status-conversion-preregistration.md`](injury-status-conversion-preregistration.md)
  — v2, frozen 2026-08-21. No model fitted; records that the committed
  2025-12-08..2026-01-04 cohort cannot satisfy the activation rule on arithmetic.
