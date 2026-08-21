# ADR-015 — The blend recipe is durable; its binding to imports is transient

**Status:** Proposed
**Date:** 2026-08-21
**Originated by:** `architect`, from `quant`'s scoping of the projections screen

## Context

The blend contract is complete — `projections/blending.py` normalises exact-rational per-category
weights, blends made/attempt volume for ratio categories, and rejects terminal layers. Only
*durability* is missing: `BlendCatalog` is a caller-owned value, so the owner's authored weights die
at process exit and "our number" cannot be shown beside a source's.

`BlendProfile` welds two things with different lifetimes into one identity, both inside
`_profile_content_sha256`. The **recipe** — sources, per-category weights, target scoring profile —
is owner-authored and should survive a refresh. The **binding** — the exact
`ReleasedProjectionImport`, including `import_id` and `projection_values_sha256` — is correctly
killed by any refresh: review drove a newer import in and both `blend_projections` and
`blend_active_projections` raised `StaleProjectionInputError` while `current_blend_profile` still
returned the profile. Active pointer intact, computation impossible, no automatic re-derivation.
Persisting the profile whole writes that weld into a migration, and the owner's weights become
*unusable*, not stale, the morning he imports a fresh CSV.

This supersedes `plan.md:517`'s `blend_profiles` sketch and defers its `blended_projections`.

## Decision

**Persist the recipe. Keep the binding transient and recompute the blend on read.**

1. **Shape.** Immutable versioned rows plus their per-category weights, activated by a
   nullable-sentinel column: `UniqueConstraint(league_id, name, version)`,
   `CheckConstraint(version >= 1)`, `CheckConstraint(active_league_id IS NULL OR active_league_id =
   league_id)`, and `UniqueConstraint(active_league_id, name)`. **That last one is deliberately not
   `LeagueScoringProfile`'s bare single-column unique**, which permits one active row per *league*;
   `BlendCatalog.active` is keyed on `(league_id, name)` and two differently-named recipes may be
   active at once, so copying that constraint would silently narrow existing behaviour. Not a
   partial index: `test_portability.py`'s dialect-branch pattern matches
   `sqlite_where=`/`postgresql_where=`. **That guard walks `src/hoops_gm` only, so the migration is
   uncovered** and must honour it deliberately.

2. **Re-run the definition-time validators on hydration.** `_validate_source_selection`,
   `_normalize_category_weights` and the `weight_basis` layer-purity raise each have exactly one
   call site, inside `define_blend_profile`; neither `blend_projections` nor
   `_assert_profile_current` re-runs them. Today an in-memory identity check is what guarantees
   every profile reaching the blend was validated. **A table replaces that check, so hydration must
   re-validate or the guarantee is gone.** This is the largest structural consequence of persisting
   anything here. Add `CheckConstraint(weight_basis = 'user_configured')` too: `portable_enum` is
   VARCHAR, `WeightBasis` already carries `learned_accuracy` and `mock_calibrated`, and without the
   constraint widening is an `UPDATE`, not a migration.

3. **Reference the scoring profile by `(league_id, name)` plus a category-content fingerprint**, and
   re-resolve to whatever is active at read time. Storing `scoring_profile_id` would reproduce the
   failure this ADR exists to prevent: `derive_scoring_profile` mints a new version for a
   byte-identical re-ingest against a new snapshot row, activation repoints, and the recipe dies on
   a settings refresh that changed no scoring rule. Refuse only when category content actually
   moved.

4. **Production only.** No games-played, expected-games, availability, seasonal-total,
   rate-times-count, **or cohort/player-filter column** — the last because filtering the pool by
   durability moves every downstream z-score through its denominator without any prohibited column
   existing. Asserted by schema test. The fusion seam remains `expected-games` (ADR-002).

5. **No manual overrides in this unit.** They are the only recipe component carrying a
   decision-bearing number, and the only one whose key nothing pins: `players.id` is a surrogate,
   `normalized_name` is documented non-unique *because* collisions must stay resolvable, so a
   name-based remedy is blindest on exactly the population that generates the risk. A persisted
   override is also indistinguishable from a durability-shaded rate, which `expected-games` would
   then multiply by `p(play)` — availability counted twice, by the owner's own hand. Deferred to
   `blend-override-persistence` with an identity remedy that is not the name.

6. **Enumerate the keys**, per ADR-014 — a guarantee is only as wide as the set someone enumerated:

   | Key | What pins it |
   |---|---|
   | `league_id` | nothing; the recipe is CASCADE-scoped to the league |
   | scoring profile | `(league_id, name)` + category-content fingerprint, re-resolved per clause 3 |
   | source | the `ExternalSource` enum value — **never `projection_sources.id`**, a re-seedable surrogate |
   | `version` | surviving rows, so `name:vN:sha12` is a label and **never an FK target** |

7. **No stored blend output.** `test_portability.py`'s `not_yet` set holds `blend_profiles` and
   `blended_projections` on adjacent lines; **remove only the first.** The second is this clause's
   sole enforcement, and deleting both is the natural edit. It flips when a migration adds a column
   holding a value computed downstream of a blend — a greppable schema event, which the earlier
   "first foreign key to a blend result" could not be, since clause 7 forbids the table such a key
   would point at.

## Consequences

**A row becomes the thing that must be trusted, in place of an in-memory identity check.** Today
nothing reaches `blend_projections` without having passed `define_blend_profile`'s validators,
because `activate_blend_profile` compares the profile against the registry object. A table has no
such guarantee: a hydrated profile is whatever the row says. Layer purity is what stops aggregates
flowing backwards under ADR-008, and after this change **it is enforced by clause 2's re-validation
or it is not enforced at all**. This is the consequence an implementer must not discover after the
migration.

The screen gets per-game rate against per-game rate, durably. It does not get parity with a
published seasonal total: that needs `expected-games`, and reconstructing it by multiplying a rate
by the source's assumption is a two-line ADR-002 violation that looks like a feature.

A moved import makes the read refuse rather than block, typed and retryable per ADR-014.
Recompute-on-read mints the release in the request that consumes it, so `projection_values_sha256`
becomes a within-request check and **the cross-time in-place-edit detection the model card
advertises is given up** — an editor of a projection row is caught at the next read, not across it.
Past numbers stay unreproducible once an import is superseded, which clause 7's trigger watches.

## Rejected

**Persisting `BlendProfile` whole** — welds both lifetimes into a migration.
**An opaque JSON blob in an existing lineage table** — the layer-purity test cannot inspect what it
cannot read.
**Materialising blended rows now** — a cache of a deterministic function, one multiplication from
looking like a valuation.
**Config-file recipes** — real user state, belonging with its lineage.

## What would flip this

Measured recompute latency too slow for the draft board, justifying materialisation early — **that
claim must name the cohort size and the measured time**, so a reviewer can re-run it. Nothing in the
repository records either today. Otherwise clause 7's trigger, which is an event rather than a
judgement.
