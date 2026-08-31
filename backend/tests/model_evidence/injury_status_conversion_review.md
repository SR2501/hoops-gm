# Injury status conversion independent review record

**Date:** 2026-08-31
**Model:** `injury-status-conversion-v2-scoped-a-v1`
**Standing:** independent review evidence, not owner approval or merge approval

## Pre-unblind review

An independent `quant` reviewer read the frozen v2 protocol, v3 scoped
acceptance, calibration machinery, fit implementation, and synthetic tests
without opening the prepared merged store or either component store.

The reviewer independently checked the canonical player-game unit, direct
outcome mapping, exclusion cascade, chronological split, candidate order,
Jeffreys arithmetic, `0.005` advancement rule, final-refit boundary, calibration
conventions, paired bootstrap settings, eight activation predicates, v2
sensitivities, Change A treatment, and Change B's non-gating standing. It found
no blocker and judged the implementation safe to unblind under the frozen
protocol.

The review identified one non-computational naming ambiguity in the exclusion
bounds. The fields were renamed to
`play_rate_if_all_uncertain_do_not_play` and
`play_rate_if_all_uncertain_play` before outcome access. The model version was
also made explicit. Synthetic lint, type, and arithmetic checks were rerun
before the one-time fit.

## Post-unblind aggregate audit

A second independent `quant` review used only repository code, the emitted JSON,
tests, and documentation. It did not open an external database and did not
rerun the consumed holdout.

From published aggregate counts, the reviewer independently reproduced:

- all final and Change A Jeffreys estimates;
- held-out Brier, CITL, ECE, maximum calibration error, and log loss;
- every bin and status observed rate and Wilson inclusion verdict;
- the selection-Brier improvements and monotonic band ordering;
- all exclusion, lead-time, informative-status, and health-proxy totals; and
- all eight activation predicates, with Change B absent from activation and no
  condition 9.

All reproduced. The reviewer also confirmed that the 6,112 development rows
partition exactly into 4,166 legacy and 1,946 short-lead rows, and that both
Change A refits score the same 3,940-row short-lead holdout. It found no release
blocker and supported the backlog completion claim.

The audit found one one-character mismatch in the mandatory shutdown-window
quotation (`October-March` versus `October–March`). The model card was corrected
to the admissibility artifact's ASCII hyphen and an offline exact-equality test
was added.

## Could not verify

The finite 5,000-resample bootstrap interval cannot be re-derived from aggregate
bins because its seeded resamples require the individual observation order.
The reviewer verified its point estimate, direction, seed, resample count, gate
predicate, and committed value, but deliberately did not rerun the holdout.

Neither review validates transfer to 2026-27, removes the end-of-season shutdown
regime limitation, establishes within-player or within-game independence, or
turns ADR-018 from Proposed into Accepted. Neither review is model activation,
owner approval, or permission to merge.
