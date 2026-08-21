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
`_profile_content_sha256`. The **recipe** — sources, per-category weights, manual overrides, target
scoring profile — is owner-authored and should survive a refresh. The **binding** — the exact
`ReleasedProjectionImport`, including `import_id` and `projection_values_sha256` — is correctly
killed by any refresh, because `_assert_import_is_current` refuses a superseded import. Persisting
the profile whole writes that weld into a migration: the owner imports a fresh Basketball Monster
CSV on draft morning and his weights become *unusable*, not stale.

## Decision

**Persist the recipe. Keep the binding transient and recompute the blend on read.**

1. **Shape.** Immutable versioned recipe rows plus their per-category weights, activated by a
   nullable-sentinel column — `UniqueConstraint(league_id, name, version)`,
   `CheckConstraint(version >= 1)`, bare `UniqueConstraint(active_league_id)`, exactly as
   `LeagueScoringProfile` does. Not a partial index: `test_portability.py`'s dialect-branch
   pattern matches `sqlite_where=`/`postgresql_where=` and would reject one. **That guard walks
   `src/hoops_gm` only, so the migration is uncovered** — the constraint has to be honoured there
   deliberately.

2. **Production only.** No games-played, expected-games, availability, seasonal-total, or
   rate-times-count column, asserted by a schema test. `source_games_played_assumptions` stays
   unreferenced. The fusion seam remains `expected-games` (ADR-002).

3. **Enumerate the keys**, per ADR-014 — a guarantee is only as wide as the set someone enumerated:

   | Key | What pins it |
   |---|---|
   | `league_id` | nothing; the recipe is CASCADE-scoped to the league |
   | `scoring_profile_id` | co-stored `scoring_profile_sha256` |
   | source | the `ExternalSource` enum value — **never `projection_sources.id`**, a re-seedable surrogate |
   | `version` | surviving rows, so `name:vN:sha12` is a label and **never an FK target** |
   | `player_id` on an override | **nothing** — see below |

   `players.id` is a surrogate with no natural key and `normalized_name` is deliberately non-unique.
   Source rows are digested *by* `player_id`, so a crosswalk remap is caught there — an override is
   not, and would silently follow the integer to a different player. **Store `full_name` and
   `normalized_name` as observed at authoring and refuse the override on mismatch.**

4. **No stored blend output yet.** It flips when the first durable artifact takes a foreign key to a
   blend result.

5. **Widening `weight_basis` past `user_configured` must require a migration**, so learned weights
   cannot arrive as a data edit.

## Consequences

The screen gets per-game rate against per-game rate, durably. It does not get parity with a
published seasonal total: that needs `expected-games`, and reconstructing it by multiplying a rate
by the source's assumption is a two-line ADR-002 violation that looks like a feature.

A moved import makes the read refuse rather than block, retryable per ADR-014. **Past numbers are
not reproducible once an import is superseded** — acceptable only while nothing stores one, which is
what clause 4's trigger watches.

## Rejected

**Persisting `BlendProfile` whole** — welds both lifetimes into a migration; the draft-morning
failure above.
**An opaque JSON blob in an existing lineage table** — the layer-purity test cannot inspect what it
cannot read.
**Materialising blended rows now** — a cache of a deterministic function, and a stored per-game row
is one multiplication from looking like a valuation.
**Config-file recipes** — real user state, belonging with the lineage it is derived from.

## What would flip this

Measured recompute latency too slow for the draft board, which would justify materialisation early —
**that claim must name the cohort size and the measured time**, so a reviewer can re-run it.
Otherwise clause 4's trigger, which is an event rather than a judgement.
