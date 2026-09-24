# Explicit projection-series selection

Implementation contract, 18 September 2026. A series selection chooses the
current exact import within that series. It does not activate a global pointer,
pin an old import, establish vendor authenticity or admit a new CSV format.

## Three identities

| Identity | Meaning |
|---|---|
| `ProjectionSource.source` | Existing publisher/player-ID namespace, such as `basketball_monster`. Still unique; Josh and Bonus are not new identity providers. |
| `ProjectionImport.series_key` | Operator-declared forecast series within the publisher, for example `josh` or `bonus`. |
| `ProjectionImport.id` | Exact imported version, with its original time, raw-content hash and parsing-profile identity. |

The import natural key is
`(source_id, series_key, season, content_sha256, profile_version_id)`.
The same bytes can therefore be distinct Josh and Bonus imports without
duplicating canonical players or repurposing a parsing-profile version.
Crosswalk authority remains provider-wide; process and database writer locks
retain their existing provider and provider/season scopes.

Keys are 1-64 lowercase ASCII letters, digits, underscores or hyphens, starting
with a letter or digit. No trimming or case coercion is performed. A named
series has a nonblank display label of at most 128 characters. Labels are
operator declarations, not independently verified vendor provenance.

Historical imports are migrated to `legacy`, displayed as
**Unspecified legacy series** with `provenance: legacy_unspecified`. No filename,
timestamp or parsing profile is used to infer Josh/Bonus ancestry. `legacy`
has no stored variant label and remains a selectable bucket; it counts toward
ambiguity just like a named series. Named descriptors use
`provenance: operator_declared`.

## Import and release

The importer and CLI accept optional `series_key` / `series_display_name`
and `--series-key` / `--series-display-name`, respectively. Omitting the key
with no imports in the requested provider/season creates `legacy`; one recorded
series selects that series; more than one refuses before content/default
mutation. An explicit new key creates a named series. Its omitted label
defaults to the literal key, not a guessed vendor label.

Exact-version lookup precedes label inheritance. Replaying an existing import
with an omitted label retains **that import's original label, ID and import
time**, even if a newer version has a different label. Only a genuinely new
version inherits the newest label. An explicit conflicting label on an exact
replay refuses. The same rule applies to unique-violation race recovery.

A named import's scoring declaration is stored on that import and does not
update the provider default. This is intentional isolation, not a claim that
the former provider-default behavior was already isolated. Release precedence
remains non-null import declaration, else provider default, else null. Null
means missing declaration evidence, not certified scoring compatibility.
Intentional legacy/provider-default updates keep their existing shared effect;
scoring-type and H2H-each-category refusals are unchanged.

Currentness is ordered by `imported_at DESC, id DESC` within provider, season
and series. Select the newest candidate, then release or refuse it. An invalid
newest import never causes an older valid import or another series to be used.
Exact-ID `release_projection_import` already identifies a series and does not
acquire omitted-selection ambiguity. Josh and Bonus still cannot be blended
as two different publishers.

The CLI summary includes the exact import ID, series descriptor and parsing
profile definition hash. Named-series unresolved reports include series key
and import ID in their filename; the legacy report basename is unchanged.
None of this changes CSV parsing, units, normalization, season admission or
manual acquisition policy. A dry run still executes the writer and rolls back;
it is not read-only inspection or permission to touch a real store.

## HTTP contract

| Endpoint | Selection |
|---|---|
| `GET /api/v1/leagues/{league_id}/projections/current` | Optional `source` (defaults to BBM), optional `series_key`. |
| `GET /api/v1/drafts/{draft_id}/production-candidates` | Required `source`, optional `series_key`. Uses the draft's actual league and season. |
| `GET /api/v1/leagues/{league_id}/projections/series` | Recorded inventory for optional `source` (defaults to BBM). |
| `GET /api/v1/drafts/{draft_id}/projection-series` | Recorded inventory for required `source`, using the draft's actual context. |

Omitted single-series numerical calls remain compatible. With no imports,
omission keeps the existing source-not-imported refusal. Omitted multi-series
calls refuse rather than selecting whichever series was imported last.

Both catalogs return `league_id`, `season`, `source`, nullable
`source_display_name`, `selection_required` and `series`; the draft catalog
also returns `draft_id`. Each series entry has `key`, `display_name`,
`provenance` and `latest_import`. That import has `import_id`, `imported_at`,
`content_sha256`, `profile_id`, `profile_version`,
`profile_definition_sha256` and nullable `original_filename`.

Inventory is sorted by key and includes the newest **recorded candidate**, even
when its release would refuse. It performs no release or scoring, publishes no
normalized-value hash and is not an admission claim. An empty catalog has no
series and `selection_required: false`.

Both numerical responses add a top-level `series` descriptor. Their
`lineage.projection_import` adds `series_key` and the literal
`release_schema_version: projection-import-release-series-v1`.
The projections response also exposes `source_display_name`. Exact import
lineage in a successful response, not potentially older catalog metadata, is
the authority for the displayed cohort.

All errors retain `{error, detail, request_id}`. New cases:

| HTTP | Condition | Code |
|---|---|---|
| 409 | Numerical request omits a key with multiple recorded series | `projections_series_required` / `production_candidates_series_required` |
| 404 | Explicit key has no import in the requested provider/season | `projections_series_not_imported` / `production_candidates_series_not_imported` |
| 422 | Blank, noncanonical or repeated `series_key` | `validation_error` |
| 409 | Catalog contains malformed stored series evidence | `projection_series_incomplete_evidence` |

Existing numerical evidence/refusal codes remain in force. Only
`projections_inconsistent_cohort` or
`production_candidates_inconsistent_snapshot` is retried, once. Selection
errors are terminal until corrected; no invalid explicit selection falls back.
The existing lock-free consistency bracket rechecks the **original selection**:
an omitted request becoming ambiguous during the read refuses, while an
explicit Josh request is not superseded merely because Bonus was imported.
This is not a guarantee to detect every moved-and-reverted state or ORM snapshot.

## Browser scope

Both screens load a resource-scoped series catalog. Zero series explains that
none are imported; one may be selected automatically; multiple series require
an explicit choice. Numerical requests after selection send the key explicitly.
Refreshing the catalog does not silently replace an explicit selection.

The cold loader/cache scope includes release-domain namespace, resource,
season, provider and series. Changing that scope clears the old rows immediately
and ignores late abandoned responses. A failed refresh of the **same** scope
may retain a whole last-good payload with its own series/import lineage, visibly
stale; new labels must never be wrapped around old rows.

Strict clients reconcile request/response resource, season, provider, series,
release domain and existing hash links. A well-formed wrong-series HTTP200 or an
old unversioned payload is a contract failure, not a candidate to repair locally.
Publisher, declared series and exact import ID/time/file accompany the rows;
profile and content hashes remain inspectable. Import time is not vendor
as-of validation.

Production candidates retain full-reference scoring before draft exclusions,
backend ordering, projection-relative limitations and no current-source
calibration claim. Source games-played assumptions remain separate from rates
and scores. There is no strategy, top-k policy, availability fusion or dollar
valuation in the selector.

## Migration and evidence boundary

Revision `0024` adds the two import columns, scoped unique key and lookup index.
Before its SQLite parent-table rebuild it verifies the complete physical
revision-0023 FK-descendant closure. The affected descendants are `projections`
and `source_games_played_assumptions`; FKs stay enabled. Complete child rows are
staged and restored with original IDs and column values inside the physical
transaction, with equality and FK checks. Unexpected descendants refuse before
rebuild. PostgreSQL uses native ALTER operations rather than a parent rebuild.
A downgrade refuses before mutation if any named series would be lost.

`test_projection_series_migration.py` exercises the populated upgrade,
all-legacy downgrade, lossy-downgrade refusal, complete physical closure and
injected-failure rollback. Its external-database path must actually execute on
PostgreSQL in existing CI; SQLite results cannot supply that evidence.
The existing Postgres job has a focused verbose step naming every case, with a
required PostgreSQL URL check and fixture assertion of the actual engine
dialect, before its unchanged full-suite step. A skipped case is not evidence.
Original source stores are never migration-test targets.

The immutable [blending card](models/projection-blending.md) describes the
**predecessor** source/season-wide currentness contract. This implementation
supersedes that release-selection description with currentness within series;
it does not rewrite the card's historical evidence. The release-domain tag and
series key, including for `legacy`, intentionally change downstream
profile/blend-result/score identity hashes. Raw-content, parsing-profile and
normalized-rate hashes retain their existing meanings. Old content-bound
profiles are refused, not rehashed or retagged into the successor; profile
integrity validation remains pure and performs no database I/O.

Request compatibility therefore does **not** imply old lineage-hash equality
or old strict-client JSON compatibility. Deploy the backend/OpenAPI and strict
client changes together. The original
[production model card](models/zscore-production.md) and experiment evidence
remain bound to their original bytes. Fixed-input synthetic numerical
equivalence is an engineering check, not new statistical evidence, Josh/Bonus
forecast calibration or Model PASS. Any conditional carry-forward of the
previous limited descriptive numerical-method evidence requires independent
exact-tree review and a named Model-impact disposition.
