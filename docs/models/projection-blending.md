# Projection blending contract

**Owner:** quant
**Version:** 1
**Status:** active deterministic contract; no learned weighting model is active

## What it predicts

Nothing independently. Version 1 is a deterministic transformation of already
imported **per-game production rates** using explicit owner-configured
category-by-source weights. It does not estimate source accuracy, games played,
availability, expected games, value, rank, or a recommendation.

The output unit remains per game. FG% and FT% are represented by separately
blended made and attempted volume; raw percentages are never inputs or outputs.

## Inputs

- Exact current `ProjectionImport` identities released by
  `release_projection_import`, including source, season, source-file SHA-256,
  immutable parser-profile identity and definition SHA-256.
- A deterministic digest over every normalized per-game projection row in each
  release. This catches an in-place row edit even if the raw-file lineage was
  not changed with it.
- The league's exact active `LeagueScoringProfile`, including category kind,
  direction, and made/attempt components for ratio categories.
- Explicit user-configured source weights for every active scoring category.
  Raw configured weights and exact rational normalized weights are both retained
  in profile lineage.
- Optional manual replacements. Each is a separate immutable input with an id,
  player, league, season, category, actor, reason, UTC timestamp, and exact
  replacement production component(s).

Games-played assumptions are not inputs. They remain in
`source_games_played_assumptions`, which this service never queries.

Rankings, tiers, ADP, AAV, auction values, composite/fantasy values, valuation,
recommendations, market outcomes, mock outcomes, availability, and expected
games are rejected blend layers. The only accepted weight basis is
`user_configured`.

## Method

1. Release an exact verified import. The profile must be verified for the
   import's season, its denormalized profile lineage must match the immutable
   profile-version row, and it must be the newest import for that source and
   season.
2. Validate that all selected imports belong to distinct known sources, match
   the league season, and do not declare a scoring type incompatible with the
   active league profile.
3. Require the weight configuration to name every active scoring category and
   every selected source exactly. Weights must be finite, non-negative, and
   positive in total; normalization uses exact rational arithmetic. Every
   selected source must contribute positive weight somewhere.
4. Require identical player coverage across selected sources. A positively
   weighted missing category component fails the whole definition; weights are
   never silently renormalized around missing data.
5. For counting categories, blend the canonical per-game rate. For a ratio,
   apply the category's one normalized weight vector independently to made and
   attempted volume. Apply any manual replacement only after the source blend,
   retaining its override id on the category output.
6. Fingerprint canonical sorted source lineage, scoring semantics, raw and
   normalized weights, manual inputs, and deterministic output rows with
   SHA-256.

Profiles and activation pointers are immutable caller-owned domain values.
Definition does not activate. Activation revalidates every import and the active
scoring profile before returning a new catalog, so A -> B -> A is an ordinary
reactivation and a failed activation leaves the prior catalog unchanged.

No database tables, migration, API, or UI were added. The accepted schema has no
blend-profile persistence contract; choosing one requires architecture
arbitration rather than storing opaque state in an unrelated lineage table.

## Training window

Not applicable. Version 1 fits no parameters and makes no learned source-quality
claim. The owner-configured weights are configuration, not evidence that one
source is more accurate than another.

## Evaluation

There is no held-out accuracy or calibration result to report for version 1
because it is not a fitted or probabilistic model. Claiming source-accuracy
weights without an eligible held-out experiment would violate the Model gate
rather than satisfy it.

The executable evidence instead checks the contract's falsifiable mathematical
and lineage properties:

- order-invariant fingerprints and exact weight normalization;
- made/attempt volume blending rather than raw-percentage averaging;
- complete exclusion of games-played assumptions;
- rejection of terminal, market, mock, availability, expected-games, and
  unsupported learned-weight inputs;
- separate manual-override provenance;
- stale, duplicate, mixed-season, incompatible-scoring, missing-category, and
  in-place mutation failure;
- validate-before-register/activate atomicity and A -> B -> A currentness.

Any future learned weighting method is a new model version. Before it can enter
this contract, its worker must receive only independently released immutable
packages under the projection experiment sequestration protocol, freeze a
pre-registration before unblinding, and pass a time-ordered held-out evaluation.
Mock outcomes are permanently ineligible.

## What this model cannot see

- whether a projection source is systematically accurate or biased;
- trades, coaching or rotation changes after a source cutoff;
- undisclosed injuries, rest plans, personal matters, or front-office intent;
- whether a manual override is substantively correct;
- source copying or correlated errors between publishers — and **the correlation
  should be expected to be high, not merely possible.** Measured on ten seasons
  of NBA game logs, a naive Marcel-style baseline already reaches r² 0.71–0.89
  year over year on the volume per-36 categories (PTS, REB, AST, BLK, FG3M;
  0.50 on steals, the weakest of the seven), so the spread between sophisticated
  public systems is small because the information in public box scores is close
  to exhausted, not because anyone is copying. Every source in this contract
  reads the same box scores. **Blending N sources that share inputs and sit near
  a common ceiling buys far less error reduction than N independent opinions
  would**, and the weights cannot detect the difference. See
  [`projection-strategy.md`](projection-strategy.md);
- future availability or games played;
- whether a per-game blend improves valuation or fantasy outcomes.

The contract can prove where a number came from and reject forbidden inputs. It
cannot prove that the configured number is a good forecast.

## Known failure modes

- Exact complete-cohort matching is intentionally strict. A source with partial
  player coverage cannot be blended until its import is repaired or a narrower
  explicit cohort contract is designed.
- A source whose scoring assumption is absent is accepted when its canonical
  per-game fields completely satisfy the active category semantics. Missing
  metadata is therefore visible lineage, not evidence of compatibility.
- Import immutability is checked at release and use time, but there is no
  database trigger preventing an external writer from editing an import row.
  Such an edit makes existing releases stale; it does not preserve service.
- Profiles and activation state are not durable across process restart. That is
  an explicit boundary of this migration-free contract, not a hidden in-memory
  substitute for accepted persistence.
- Manual inputs are auditable but not independently validated for basketball
  truth. A well-formed override can still be wrong.

## Change log

| Version | Date | Change | Evaluation effect |
|---|---|---|---|
| 1 | 2026-08-19 | Initial deterministic per-game blending contract. | No learned-performance claim; contract invariants covered by focused tests. |
