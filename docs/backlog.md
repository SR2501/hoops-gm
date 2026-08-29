# Build backlog

Generated from the planning session on 2026-08-17. **This is the authoritative task list** - it lived only in a chat session before this, which is exactly what `docs/handoff.md` exists to prevent.

**67 done - 0 blocked - 122 pending - 189 total**

(Recomputed from the status markers in this finished file, never
reconciled from two headers; the `###` headings and the status markers
correspond 1:1, with no duplicate item names. Neither side of a
rebase conflict is a usable input here, because each was computed before
the other lane's items landed.)

**The numbers that used to sit in the paragraph above were removed on
2026-08-23**, by the `demo-one-command` lane, and the reason is the paragraph
immediately below this one. It says *"the count above is no longer restated
anywhere in this file"*, and that was false: the block above restated it twice
(`140 ### headings and 140 markers`) while `scripts/backlog_graph.py` checks
only the header line, so the prose copy was exactly the unguarded second copy
this file warns about — instantiated in the file that warns about it. It
survived because a rebase conflict on the header does not touch prose two lines
below, and `scripts/resolve_doc_conflicts.py` recomputes the header
unconditionally and the parenthetical never. The property is worth stating and
the integers were not; both tools still enforce the property.)

(Recomputed from the status markers in this finished file, never reconciled from
two headers. **The count above is no longer restated anywhere in this file**, and
that is deliberate: a second copy of it is what a rebase updates one of - and the
prose copy is the one nothing guards. It is checked on every push by
`scripts/backlog_graph.py`, which counts the items it actually parses and fails if
the header disagrees with them, so the header and the graph cannot drift apart.
That check landed at `b49c6e6`; before it, the header was checked by nothing, and
any report of it passing describes a run that never read line 5. **CI checks the
header. Nothing fixes it.** The repair is `scripts/resolve_doc_conflicts.py:382`,
which recomputes unconditionally — but only when a human invokes it, which is
during a conflict, so a header wrong on a branch that merges cleanly was repaired
by nothing and, until `b49c6e6`, caught by nothing either.
Uniqueness and the 1:1 heading-to-marker correspondence are enforced by the same
tool rather than asserted here. Neither side of a rebase conflict is ever a usable input here, because
each was computed before the other lane's items landed - one lane measured main at
39/71/111 and its own branch at 40/69/110 when the truth was 40/71/112, so no
reconciliation could have reached the answer. The position lane sharpened
`player-position-eligibility` without closing it: the NBA-position half landed, the
Fantrax-eligibility half did not, so that marker stays `pending`.

**And on 2026-08-21 the resolver's own output was the unusable input.** Rebasing
`projections-ui` onto merged `main`, `scripts/resolve_doc_conflicts.py` printed a
recomputed header twice in one rebase — `118` at the first conflict and `115` at
the second — and its resolution **silently dropped the three items the import-CLI
lane had just added** (`projections-import-cli`,
`projection-import-process-concurrency`, `projections-seed`) while leaving both
header blocks behind. It exited successfully. Taking its number would have shipped
a file that had lost three entries and disagreed with itself about how many it
held. Found by diffing this file's slug set against `origin/main`'s, which is the
only check that catches a *dropped* item — a recount of the finished file agrees
with itself perfectly after a deletion. **Recount the total, and separately
compare the slug set against your own merge base; the first cannot see what the
second is for.** Against `origin/main` rather than the merge base it reports
another lane's merges as your deletions the moment your base has moved — and it
agrees exactly with the correct check when run right after a rebase, because the
two are the same commit at that instant, which is why it survives. The blend-recipe
lane rebased onto `fc23239` under that rule and the pair
behaved exactly as described: the recount moved 118 -> 120 and could not have
seen a loss, while the slug diff independently confirmed
zero of main's 118 entries were dropped and exactly two were added. The script
was not run on this file.

**The `aav-source` lane ran the pair twice on 2026-08-22 and the second run is the
instructive one.** Before rebasing, both checks agreed trivially: the recount moved
45/76 -> 46/75 with the total unchanged at 122, and the slug diff found 122 on both
sides, zero added, zero dropped — expected, because the lane closed a marker rather
than adding an item. Recorded even so, because a lane that reports the pair only when
it disagrees is a lane whose silence is ambiguous.

Then `main` moved to `642bdb6` and the rebase conflicted on this header. **Neither
side was usable and both were wrong**, exactly as the paragraph above predicts: `HEAD`
said 129 total and the branch said 122, and the answer — 46/1/82/129 — is on neither
side, because each was computed before the other landed. It came from recounting the
resolved file. The lane then added `hashtag-projection-profile-verification` in the
same unit, taking it to 46/1/83/130 — recounted again afterwards rather than
incremented, because an arithmetic step on a number you just recounted is a new copy
with the same failure mode as the old one.

**And the number arrived in a message was wrong in a third way.** The coordinator
relayed `main` as "128 items, 45 done / 1 blocked / 82 pending"; recounting
`origin/main:docs/backlog.md` directly gives **45/1/83/129**, and that file's own
header agrees with itself. Off by one on both total and pending. Nobody erred
carelessly — the number was simply restated somewhere that cannot recount itself,
which is the failure this header exists to prevent, arriving through chat rather
than through a rebase. **Recount from the file; a number in a message is a copy, and
a copy is stale on arrival.** The diff also asserts `origin/main`'s slug set parses
non-empty **before** comparing, because a diff against zero slugs reports "nothing
dropped" for the same reason an empty set reports anything you ask of it.

**A dependency edge can be dangling and nothing said so.** Tracing the auction
chain on 2026-08-21 to rule on sequencing turned up
`schedule-cohort-fingerprint-list` depending on `injury-report-backfill`, which
was not a slug in this file — the item is `injury-report-historical-backfill`.
**Resolved to that item on 2026-08-21 and no longer dangling**, when
`scripts/backlog_graph.py` landed and made it a CI failure rather than a note.
The resolution is a judgement, not a derivation: `injury-conversion-cohort-population`
is the plausible wrong answer, and the two are distinguishable only by reading
what each item says. It changed no readiness outcome, because both candidates
are `done`. Recorded because it is the same shape as the counts: **the graph
is only as trustworthy as the last time someone resolved every edge against the
slug set**, and until `adr-index-consistency-test` has a sibling doing that
here, nothing does. That sibling is now filed as `backlog-dependency-graph`.
**Built on 2026-08-21** as `scripts/backlog_graph.py`, so it now runs on every
push rather than when a lane goes looking for something else - and this edge
was indeed its first finding.

The governance unit of 2026-08-21 added seven items and ran the pair as
prescribed: the recount moved 122 -> 129, and the slug diff against
`origin/main` independently confirmed zero of main's 122 entries were dropped
and exactly seven added. **The status split needed a third pass**, because the
first two matched `done|pending|blocked` anywhere in the marker line and one
`pending` item's note contains the word "blocked" - so the split summed to 130
against 129 headings and disagreed with the total sitting beside it. Match the
marker **token**, not the word, and check the split sums to the total: that
addition is the only thing that caught it.

The parenthetical above said "114 headings and 114 markers" while the header two
lines up said 115, because a rebase updated one and not the other - the prose
restating a number is exactly as staleable as the number. This total moved three
times in one day (114, 115, 118), which is the argument for never restating it
elsewhere: `README.md` carried an absolute item count that was stale by
construction, and now describes the file instead.)

The uniqueness check earns its place: resolving this rebase by taking both sides
of a hunk left a bare duplicate `schedule-grid-ui` heading whose body had been
replaced, and *both* status header blocks. The totals disagreed with each other
in the same file, and only a count of unique slugs against markers found it.)

### `absence-splits` - Computing with/without absence splits

- [x] **done**
- **Depends on:** `participation-ledger`

Historical production splits per player pairing when a teammate is absent.
Implemented as descriptive observation-layer evidence, not a causal or
decision-bearing model. `without` requires an explicit observed non-play row.
Missing rows are never inferred: R35 remains unresolved until authoritative,
versioned historical roster intervals and per-game ingestion-completeness
evidence both exist. Complete run cohorts, provenance, sample sizes,
uncertainty, schedule lineage, and volume-aware makes/attempts are persisted.
Sparse splits never become recommendations here; `contingent-value` must pass
the Model gate before using them in a decision.

### `adapter-contract-tests` - Adding contract tests for external adapters

- [x] **done**
- **Depends on:** `ci-pipeline`, `fantrax-private-adapter`, `nba-stats-ingest`

Recorded fixtures and CI contract tests for every external adapter so upstream schema drift from stats.nba.com or /fxpa/req fails loudly in CI rather than at lineup lock.

### `agent-definitions` - Authoring the seven agent definitions

- [x] **done**
- **Depends on:** `governance-docs`

Invocable agent definitions in .github/agents/: architect, data-engineer, quant, backend, frontend, bridge, safety. Each states role, owned scope, explicit non-goals, applicable gates, and escalation triggers. quant is separate from data-engineer because statistical correctness and resilient I/O are different failure modes. safety is separate from bridge because self-approval is what guardrails exist to prevent.

### `backend-skeleton` - Building the FastAPI backend skeleton

- [x] **done**
- **Depends on:** `repo-scaffold`

FastAPI app in backend/ with pydantic settings/config, structured logging, /health endpoint. Wire pytest, ruff, mypy.

### `backlog-dependency-graph` - Computing this file's dependency graph in CI

- [x] **done** - Built 2026-08-21 as `scripts/backlog_graph.py` and merged in #65, running on
  every push. **The critical path is twelve deep, not the ten this item estimates**; the ten
  deepest chains all terminate at the same lane, which is the finding the item was filed to
  get and which hand-tracing got wrong by two levels. It also now checks this file's own
  headline count against the items it parses, after a rebase updated one copy of that number
  and not the other.
- **Depends on:** `ci-pipeline`

Parse every `###` item heading and every `- **Depends on:**` line in this file, resolve
each dependency token against the slug set, and fail CI on any token that names no item. Print
the longest path through the graph and the ready set (pending items whose dependencies are all
done). Filed on 2026-08-21 because reading 122 items in file order produced three distinct
failures in one day that a graph would have surfaced in seconds: a dangling edge
(`schedule-cohort-fingerprint-list` → `injury-report-backfill`, which is not a slug here — the
item is `injury-report-historical-backfill`), prose asserting an item was blocked while its
machine-readable edge said ready, and a ten-deep critical path nobody could see. Sibling to
`adr-index-consistency-test`, which does the equivalent job for the ADR index; until this
exists, nothing resolves an edge here except a human who happened to trace one. Keep it a
script, not a gate on prose: it checks the machine-readable edges only, and the prose
disagreeing with them is a finding it should report rather than adjudicate.

### `boxscore-date-plausibility-bound` - Bounding box-score game dates against an independent source

- [ ] **pending**
- **Depends on:** `nba-stats-ingest`, `participation-ledger`

Assert every derived `game_date` against something the box-score payload does not supply
itself. `gameEt` carries a `Z` suffix and is **not** UTC — it is Eastern time wearing a UTC
marker, five hours off its sibling `gameTimeUTC` in the same object — so a timezone-aware
parse of it is correct in form and wrong in meaning, shifting the date for every game tipping
after 7pm Eastern, which is most of them. `player_participation` joins on that date, so the
availability model would absorb the error as real signal. Cross-check against `gameTimeUTC`,
the schedule endpoint's own date for the same `game_id`, and a plausibility bound (no NBA game
tips outside a known daily window in Eastern time); fail loudly on disagreement rather than
preferring either field. See the `AGENTS.md` house rule on self-describing fields: check the
claim against something independent.

### `bridge-capture` - Capturing Fantrax data via the bridge

- [x] **done**
- **Depends on:** `userscript-foundation`

Intercept window.fetch and XMLHttpRequest against /fxpa/req, normalize the payloads and POST them to the backend. Persist raw payloads to bridge_payloads for replay and debugging.

### `bridge-handshake-endpoint` - Adding the backend bridge handshake endpoint

- [x] **done**

The userscript calls POST /api/v1/bridge/handshake and that endpoint validates the shared secret, returns the protocol version, and rejects unauthenticated requests.

### `ci-billing-blocked` - Restoring GitHub Actions (owner-only)

- [x] **done**

The outage began around 12:58Z on 2026-08-17 after a last green run at
12:56Z, when the account-wide private-repository Actions quota was exhausted.
Resolved the same day by the owner making the repository public, deliberately
accepting that the strategy became visible and noting the repository's
portfolio value. Public repositories are exempt from the Actions quota and
receive free secret scanning, push protection, and CodeQL. CI was restored and
PR #3 merged the scheduled live-smoke repair. The incident analysis and
corrected quota diagnosis remain in `docs/governance/OPEN-ci-billing.md`.

### `ci-pipeline` - Setting up the CI pipeline

- [x] **done**
- **Depends on:** `backend-skeleton`, `frontend-skeleton`

GitHub Actions running lint, type-check and tests for both backend and frontend on push and PR.

### `cli-help-no-side-effects` - Making `--help` print help rather than start a server

- [ ] **pending**
- **Depends on:** `backend-skeleton`

`python -m hoops_gm --help` starts the server instead of printing usage, because the module
entrypoint hands off to the runner before any argument parsing happens. `--help` is the one
command a stranger runs to find out what a program does and the one command that must have no
side effects; here it binds a port. Parse arguments first, dispatch second, and add a test
asserting `--help` exits 0, prints usage to stdout, and binds nothing.

### `db-foundation` - Establishing the database foundation

- [x] **done**
- **Depends on:** `backend-skeleton`

SQLAlchemy setup with Alembic migrations and session management. Implement core schema: players, player_external_ids, nba_teams, leagues, fantasy_teams, rosters. SQLite for dev, keep Postgres seam clean.

### `deadline-model` - Modelling the league deadline calendar

- [x] **done**
- **Depends on:** `league-settings-ingest`, `schedule-ingest`

Originally scoped to compute every future deadline from the ingested settings: per-player lineup locks at each tipoff, waiver claim cutoffs, waiver clear moments, games-cap thresholds, trade deadline, playoff roster deadlines. `league-settings-ingest` already verified that Fantrax's official `getLeagueInfo` supplies only roster limits and scoring-period boundaries — lineup lock, waivers, trade deadline, playoffs and keeper rules are absent from every source observed so far. Computing any of those from ingested settings would mean inventing them, so this unit delivered the smallest honest contract instead: `league_deadline_calendars`, one immutable, versioned row per league joining an exact `LeagueSettingsSnapshot` with an exact schedule refresh cohort, exposing season bounds and scoring-period boundaries as real timezone-aware instants while carrying lineup lock, waivers, trade deadline, playoffs and keepers forward as explicit unknowns (or their bridge-sourced values, verbatim, when the settings snapshot already has them). Fails closed on missing or mismatched lineage at both derivation and activation time — including when scoring periods themselves are unknown (no `[]` fallback), on out-of-order season/period bounds, and on duplicate period numbers; A→B→A activation cycling is supported by re-deriving over lineage that reverts to prior content. `trade_deadline.deadline_at`/`keepers.deadline_at` are validated offset-aware ISO 8601 at the ingest domain-type boundary, and the read endpoint is loopback-only (bridge-derived values, not a public dashboard fact). A `notification-engine`/`lineup-optimizer` consumer that actually needs a computed lineup-lock instant per game still has no source for one — that gap is real, not an oversight, and stays open until a bridge capture or a new official field closes it. `LeagueDeadlineCalendar` remains the authoritative source-truth calendar; `ScoringPeriod` is now its fail-closed current Eastern-date materialization with separate keyed refresh lineage — see `scoring-period-projection`.

### `demo-db-alembic-stamp` - Stamping demo and seed databases with an Alembic revision

- [ ] **pending**
- **Depends on:** `db-foundation`

Databases created by the demo and seed paths (`projections_demo.db` among them) are built by
`create_all` and carry no row in `alembic_version`, so they are permanently stranded: Alembic
cannot upgrade them because it does not know where they start, and the only remedy is to
delete and rebuild. That is tolerable for a throwaway demo file and not tolerable the first
time one holds something the owner wanted to keep. Stamp `head` at creation, and add a test
asserting every database the seed paths produce reports a revision.

### `draft-append-error-classification` - Distinguishing permanent from retryable storage failures on draft append

- [x] **done**
- **Depends on:** `draft-format-abstraction`

The draft-event append path wraps its insert in a blanket `except` that maps **every** storage
failure to a retryable error code, so a conforming client retries a permanent failure forever
— a uniqueness or foreign-key violation is not transient and no amount of retrying resolves
it. Discriminate on the constraint that failed (which requires the dialect's own error
attributes, not the message text) and return permanent for integrity violations, retryable
only for connection and serialisation failures. Found on 2026-08-21 by a tripwire, not a test:
1,373 tests passed and none of them entered the handler, so a code review, a mutation matrix
and a green PostgreSQL run all cleared it simultaneously — see the *prove a test reaches the
code at all* bullet in the Code gate, which this item is the reason for.

**Landed 2026-08-21 in PR #64, and it diverges from the remedy above in two ways worth
recording, because "done" should not be read as "done exactly as written".** `_violated_constraint`
reads psycopg's `diag.constraint_name` on PostgreSQL as prescribed, but **falls back to message
text on SQLite**, which exposes no structured constraint name at all — it names the constraint
for `CHECK`, names the columns instead for `UNIQUE`, and names nothing for `FOREIGN KEY`. Where
the dialect will not say, the handler returns `None` and the caller treats it as **permanent**,
the safe direction. And the one integrity violation deliberately kept *retryable* is
`uq_draft_events_draft_sequence`: the sequence is computed as `max + 1` in Python, so a duplicate
means a concurrent writer won the race and re-reading then re-appending genuinely does succeed.
Driven, not assumed — 48 barrier-synchronised attempts on PostgreSQL 16.9 produced 13 wins and 35
retryable refusals with no duplicates and a contiguous sequence.

### `draft-format-abstraction` - Abstracting snake and auction draft formats

- [x] **done**
- **Depends on:** `scoring-profiles`

Immutable snake, linear, and auction configuration is derived exclusively from
the current `League.draft_type`, `team_count`, `roster_size`, and
`auction_budget` facts. Unknown formats, missing or nonpositive roster shape,
missing/nonpositive/non-finite auction budgets, and budgets attached to ordered
drafts all fail closed. Snake and linear expose explicit one-indexed
round/pick/team-slot ordering; auction exposes only its stated per-team budget
and roster shape because current league facts do not establish nomination or
bidding order. No historical defaults, market evidence, valuation, price,
inflation, scarcity, recommendation, API, or persistence behavior enters this
Code-gate-only layer.

### `fantrax-official-adapter` - Building the official Fantrax API adapter

- [x] **done**
- **Depends on:** `db-foundation`

Client for fantrax.com/fxea/general/: getPlayerIds, getAdp, getLeagues, getLeagueInfo, getDraftPicks. Handle userSecretId auth where required.

### `fantrax-private-adapter` - Integrating fantraxapi for private league reads

- [x] **done**
- **Depends on:** `fantrax-official-adapter`

Integrate the fantraxapi package (pin the version) for private-league reads via the FANTRAXUSER cookie. Encrypted cookie storage at rest plus a re-login flow on expiry. Sync rosters, standings and matchups.

### `frontend-skeleton` - Building the React frontend skeleton

- [x] **done**
- **Depends on:** `repo-scaffold`

Vite + React + TypeScript in frontend/. Routing, typed API client, layout shell, component conventions.

### `governance-docs` - Writing the governance artifacts

- [x] **done**
- **Depends on:** `repo-create`

AGENTS.md as the single entry point (roster, rules, gates). docs/governance/ownership.md (module to owning agent matrix), gates.md (the four readiness gates), owner-decisions.md (what only the owner decides), risks.md (live risk register covering ToS exposure, upstream fragility, model risk, seasonal deadlines).

### `governance-table-shape-check` - Asserting the shape of the governance register tables in CI

- [ ] **pending**
- **Depends on:** `ci-pipeline`, `governance-docs`

Render `docs/governance/risks.md` through a GFM renderer and assert every row in every table
has the column count its header declares, **and** that the Owner cell of each risk row is one of
the seven agent names in `.github/agents/` (or `owner`, or a short combination). The second
assertion is the one with a demonstrated catch: on 2026-08-21 six rows — R49, R50, R51, R53, R54
and R57 — had their amendment prose sitting inside the Owner cell, up to **4,827 characters** in
R51, so the Mitigation column rendered empty and the Owner column rendered as an essay. Every
one of those rows was structurally valid, which is why cell counting missed them and why the
length-and-membership assertion is the part that matters. Render rather than split on `|`: two
lanes disagreed the same night about whether R58 was malformed, both having counted cells with
hand-written pipe splitters, and R58 legitimately carries `\|` escapes inside a code span that
GFM handles and neither splitter did. Cheap and fast; `gh api -X POST /markdown` is sufficient
and needs no new dependency.

### `handoff-log` - Initialising the handoff log

- [x] **done**
- **Depends on:** `repo-create`

Create docs/handoff.md as an append-only log. Seed with current state, locked decisions, and the first entry. Every agent finishing work appends: what changed, what is now true, what it could not verify and why (mandatory field), and who is next.

### `injury-report-historical-backfill` - Bounded, resumable operator workflow for backfilling historical NBA injury reports

- [x] **done**
- **Depends on:** `injury-report-ingest`

Bounded, resumable operator tool (`hoops_gm.ingest.injury_report.backfill`) that fetches and imports historical NBA official injury-report captures from the NBA's archived CDN into durable per-game evidence, so `injury-status-conversion` has more than the single committed fixture to build against once a genuinely representative cohort exists. Candidate report timestamps are derived per calendar date from exact ingested `nba_games.tipoff_utc` values and the documented publication cadence: `evening_before` (17:30 ET the day prior) in both URL eras, plus an era-conditional game-day strategy — a single fixed 13:00 ET guess pre-2025-12-22 (safe there because the legacy URL truncates to the hour and the masthead check tolerates 45 minutes of drift), and four bounded, tip-off-anchored, 15-minute-grid-aligned offsets (150/90/45/15 minutes before the date's earliest tip-off, floored to the source's own quarter-hour marks so a non-grid-aligned tip-off like 19:10 ET does not push every candidate off-grid) from 2025-12-22 onward, where the URL is an exact-minute match with no drift tolerance. No lookahead is enforced twice (plan time and read time). The natural key (`report_timestamp, team_raw, player_name_raw, game_date`), checkpoint identity that includes the exact resolved timestamp (not just date+anchor, so a corrected tip-off cannot silently reuse a stale candidate's settled status), and two fail-closed gates — `enforce_full_tipoff_coverage` and an independent `enforce_expected_game_coverage` against the official `LeagueGameFinder` schedule (migrations `0013`/`0014`) — prevent a same-player back-to-back split across two game dates from colliding, and prevent running against a requested or incidentally-ingested game scope (e.g. 22 of 527 games) as though it were cohort-ready. Reuses the existing `InjuryReportClient`/parser/importer — two schema changes (natural key; evidence schema version). Checkpointed (cache-independent) and idempotent so an interrupted run resumes, including across a mid-write import/commit failure and mid-flight tip-off correction. A 403 is never checkpointed as settled — recorded under its own permanent `"forbidden"` status and retried indefinitely across every future run, regardless of streak length or process boundary; a streak still raises an early-abort optimization, but checkpoint correctness never depends on it. Durable per-run `CoverageReport` evidence (persisted even on an aborted run, keyed on the exact requested timestamp so a corrected tip-off cannot silently reuse stale coverage, and bound to an exact evidence schema version so an incompatible legacy, unrecognized-future, or malformed-current artifact is quarantined for read-only classification but makes persistence fail loudly without rewriting the original bytes) is classified against the database's *current* tip-off and game identity — re-read fresh on every `coverage_for_games` call, never a possibly-stale caller snapshot — and matched by each candidate's stable NBA game identifier (`applicable_nba_game_ids`), never a reusable surrogate database id; coverage evidence recorded before this stable-identity fix is stamped a legacy coverage-schema version and excluded from `submitted_zero_listed` classification entirely rather than trusted against whichever game holds its old surrogate id today. An unresolved (unattributable) report row vetoes a clean `submitted_zero_listed` claim only for the same-date games whose current tip-off is strictly after that row's own report timestamp — never date-wide — and this `unresolved_evidence` outcome outranks the coarser `legacy_excluded` when both apply to the same game. A full `exclusion_cascade` denominator breakdown (expected → ingested-with-tipoff → candidate-scoped → attempted → recovered → resolved-game → resolved-player → status-listed, split by legacy vs. trusted evidence schema so a pre-fix row is never silently counted as trusted), and a network-free `observations` CLI command expose per-game outcome (`observed` / `no_candidate_coverage` / `not_yet_submitted_only` / `submitted_zero_listed` / `legacy_excluded` / `missing_tipoff`) so the falsifiable coverage gap is checkable per game and per cascade stage, not asserted as an aggregate rate. Rows written before the natural-key/versioning fix are stamped a legacy evidence-schema version and excluded from every trust-dependent cascade stage and canonical-observation query by default. `CanonicalPregameObservation.lead_time_minutes` is the realized per-game `tipoff_utc - report_timestamp`, distinct from a `ReportCandidate`'s `anchor_offset_minutes` (the anchor's shared, intended offset for the date) — the two were conflated before round-5 review and are now separately named and computed. `ExpectedGameCoverage`/`CoverageReport` are bound to the exact requested season/season_type/date range and rejected if mismatched. Coverage classification also forces a fresh (`populate_existing`) re-read of each game's tip-off inside `coverage_for_games`'s own read scope, closing a residual ORM identity-map staleness gap where an already-loaded session object could otherwise retain a pre-correction value even after a separate session's committed fix; rejects an *unrecognized future* `evidence_schema_version` exactly like a legacy one (not merely anything below current); rejects evidence whose `report_date` no longer matches a rescheduled game's current `game_date`, or whose `CoverageReport.season`/`season_type` does not match the game's current schedule scope; emits a retracted-tip-off game exactly once (not duplicated across the ready/newly-missing paths); and keeps a resolved-but-currently-out-of-scope `game_id` (e.g. its own game's tip-off was itself retracted) bound to that one game rather than fanning the conservative unattributable-row veto onto unrelated same-date games. `coverage_for_games` now reads every classification-relevant game field (stable id, local id, date, tip-off, season, season_type, both teams' abbreviations) in exactly one `SELECT`, deriving `select_canonical_pregame_observations`'s tip-off lookups from that same snapshot rather than a second, separately-timed query a schedule correction could land between — proven immune to a real mid-call commit via a `before_cursor_execute` engine hook against a genuine second database connection. Persisted coverage is now bound to an exact evidence schema version (bumped to 3) and each candidate's own self-described `season`/`season_type`, not merely per-game schedule scope: a whole-file scope mismatch against the current request raises rather than silently rewriting the file under the wrong label, an individual out-of-scope candidate is excluded even inside an otherwise-matching file, and the merge key itself now also carries the canonical masthead timestamp and applicable stable game-id set so two genuinely distinct fetched records sharing every other field still coexist rather than one silently overwriting the other. Checkpoint settlement identity now also carries the settled scope's stable NBA game ids, so a genuine `--allow-missing-tipoff` partial day — where a later-ingested same-day game's tip-off is *later* than the date's already-known earliest and therefore never changes the near-tip candidate's resolved instant or checkpoint key — is correctly reprocessed on resume (idempotently) rather than trusted forever under the narrower, stale settled scope.

**What "done" means here, precisely — and what it does not:** this item closes the *bounded, resumable operator workflow* (the tool, its fail-closed gates, its checkpoint/coverage durability and idempotency, and its test coverage) as scoped and reviewed. It does **not** mean a representative, conversion-ready historical cohort has been populated against the live archive. Per `docs/handoff.md`, the only live-archive run performed against this tool produced a deliberately small, non-representative sample (22 of 527 games, spanning a handful of dates) used to validate the tool's own mechanics, not to seed `injury-status-conversion`. Populating an actual multi-date, multi-game cohort large and diverse enough to be evidence-ready for that downstream item is separate, unstarted work — running this tool at scale against the live archive, within its own rate-limit and request-budget bounds — and is now tracked as its own explicit backlog item, `injury-conversion-cohort-population`, precisely so `injury-status-conversion` cannot appear structurally ready merely because every dependency it lists here is done. `injury-status-conversion` remains explicitly blocked until that cohort exists and is independently reviewed.


### `injury-report-ingest` - Ingesting NBA official injury reports

- [x] **done**
- **Depends on:** `player-identity`

Ingest the NBA official injury report (day-before release plus game-day updates) with full status history per player per game: OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, AVAILABLE.

### `injury-report-plan-budget-inert` - Making `plan` report the request budget it already accepts

- [ ] **pending**
- **Depends on:** `injury-report-historical-backfill`

**An operator should not have to read `main()` to learn which of two commands
enforces an argument they both accept.** That is the whole specification.

`hoops_gm.ingest.injury_report.backfill plan` defines `--max-requests`, parses
it, and never enforces it: `enforce_request_budget` is called on the `run` path
only. Driven on `1912a3d`, not reasoned —

    plan 2025-26 --start 2025-10-21 --end 2026-04-12 --max-requests 1 --no-cache
    plan: season=2025-26 candidates=640 to_fetch=640 already_cached=0
    exit 0

A budget of **1** against **640** candidates exits **0**. `run` with the same
arguments exits 1. So step 5 of the operator recipe committed in `#92` carries
`--max-requests 820` into a command that discards it.

This is the exact inverse of the defect `#92` closed, and the inversion is the
point. There, the arguments were **load-bearing but invisible**, so their
absence silently degraded the manifest. Here the argument is **visible but
inert**, so its presence advertises a pre-flight check that did not happen.
`plan` is precisely the command an operator runs to find out whether a budget is
survivable *before* spending requests, and it currently answers "yes"
unconditionally.

The obvious objection is right and does not dissolve the item: `plan` **is** a
preview and should not abort. That makes the fix smaller rather than
unnecessary. Either `plan` reports the budget verdict without acting on it — one
line, naming the limit and whether `to_fetch` exceeds it — or `operator_commands`
stops emitting the flag on the `plan` step. Not both, and the first is better,
because a preview that cannot answer the question it is run to answer is not
much of a preview.

Note the near miss this leaves standing: `enforce_full_tipoff_coverage` is the
*other* guard on the `run` path, and it fires **before** the budget. Whatever
`plan` reports must not imply it has cleared coverage too, or this item's fix
recreates this item's defect one guard along.

`data-engineer` owns it. Disprovable in one command if this reading is wrong.

### `league-settings-ingest` - Ingesting full league settings and rules

- [x] **done**
- **Depends on:** `db-foundation`, `fantrax-official-adapter`

Versioned, source-attributed settings snapshots covering lineup locks, waivers, games caps, roster/IR limits, scoring periods, trade deadlines, playoffs, and keeper rules. Verified live that official `getLeagueInfo` supplies roster and scoring-period configuration but omits the other rule families; omissions remain explicit unknowns and may be filled only by lower-priority read-only bridge evidence. Historical 2025-26 values never default 2026-27 rules, and a season-coherence guard rejects importing the observed 2025 payload into a 2026-27 league.

### `nba-stats-ingest` - Ingesting NBA stats via nba_api

- [x] **done**
- **Depends on:** `db-foundation`

nba_api adapter with ~1 req/s throttling, required stats.nba.com headers, retry and caching. Use V3 endpoints. Backfill teams, games, player game logs, plus inactive lists and DNP reasons, across multiple seasons for availability model training.

### `participation-ledger` - Building the player participation ledger

- [x] **done**
- **Depends on:** `nba-stats-ingest`, `player-identity`

Historical per-player, per-game participation reconstructed from box scores and inactive lists, with normalized reason codes: played, DNP-CD, injury (with body part), rest/load management, personal, suspension, G-League, inactive. Multi-season for model training.

### `per-run-metric-delta` - Printing each per-run number beside its previous value

- [ ] **pending**
- **Depends on:** `ci-pipeline`

Store the previous run's per-run numbers (suite duration, slow-test durations, collected test
count, fixture sizes) and print each one next to its predecessor with the delta. **Not a
threshold assertion**, deliberately: a threshold recreates the cry-wolf guard the moment the
number is legitimately allowed to grow, and the whole point is that no individual value here
is alarming. `ProjectionsTable.recorded.test.tsx` climbed 3,177 → 3,309 → 3,376 → 3,714 →
4,298 ms toward a 5,000 ms limit, printed every run, directly above a summary a lane quoted
four separate times — every number passing, only the sequence alarming, and nothing computed
the difference. It should fail nothing and judge nothing; it exists so the monotone climb is
visible without anyone holding five runs in their head.

### `player-identity` - Resolving cross-source player identity

- [x] **done**
- **Depends on:** `fantrax-official-adapter`, `nba-stats-ingest`

Crosswalk resolver joining Fantrax IDs, NBA IDs and projection-CSV name strings. Fantrax exposes no NBA.com player id, so there is no anchor pair; matches begin with normalized name + team + position and retain per-field three-valued evidence, confidence, and manual overrides. Ship an unmatched-players report and a manual-override UI. Highest-risk foundational item - needs its own test suite.

### `player-position-nba` - Ingesting the NBA-published player position

- [x] **done** - Landed 2026-08-20 in #48.
- **Depends on:** *(nothing)*

### `player-position-fantrax` - Ingesting Fantrax position eligibility

- [ ] **pending**
- **Depends on:** `player-identity`

### `player-position-eligibility` - Ingesting player position and Fantrax position eligibility

- [ ] **pending** — *umbrella; the landed half is now `player-position-nba` and only `player-position-fantrax` is outstanding*
- **Depends on:** `player-position-nba`, `player-position-fantrax`

**The dependency deliberately does not point at `player-identity` for the whole item.** `player-identity` specifies matching on "normalized name + team + **position**" — with no position data in the project, that third field did not exist, so ordering all position work behind identity would have left the highest-risk foundational item permanently short of one of the three fields it was specified to use. The NBA-position half needed no crosswalk and landed first; only Fantrax eligibility, which is per-player-per-league, needs the crosswalk.

#### NBA-position half — done (2026-08-20)

`PlayerIndex` supplies the NBA's listed position for every player in one request, and it is persisted on `players.primary_position` with source, season and observed-at lineage (migration 0016). Contract tests, live smoke and the full evidence are in `docs/adapters/nba-stats.md`. R7's third matching key is now real: crosswalk position evidence went from 576 `UNKNOWN` and nothing else to 531 `AGREE` / 35 `DISAGREE` / 10 `UNKNOWN`.

**It is coarse, and this does not close the draft-board requirement.** The vocabulary is `G/F/C` plus hybrids, with **no `PG`/`SG`/`SF`/`PF` on any NBA endpoint checked** — `PlayerIndex`, `CommonPlayerInfo` and `CommonTeamRoster` all agree, and `PlayerIndex` rejects a `PlayerPosition=PG` filter with `{"PlayerPosition": ["Invalid parameters"]}`. It separates a centre from a guard. It cannot express a Fantrax lineup slot.

#### Fantrax-eligibility half — outstanding, and it is a different quantity

**Fantrax's stated eligibility is the only authoritative source. It is read, never derived.** Whatever Fantrax says a player is eligible at *is* what he is eligible at, because that is what the lineup validator enforces on draft night. There is no computation that outranks it.

Everything below is **the owner's expectation, recorded with its provenance and to be confirmed nearer the season** — not established fact. A threshold written down as fact when it was someone's recollection is how a wrong number becomes load-bearing.

* **The player pages are the source of truth, not necessarily the API.** The pages are a UI surface and `getPlayerIds` is an endpoint; they may disagree, and if they do, *the pages win*. Capture both and compare rather than assuming the convenient one is authoritative — the same discipline that caught `gameEt` and `MATCHUP`.
* **It updates on a cadence — believed weekly.** So a stored eligibility value needs a **staleness window**, not merely a timestamp: the system must be able to say "this is as of Tuesday and may be up to seven days behind". Freshness is part of the contract, not metadata.
* **It is monotonic and time-dependent.** Eligibility never decreases, and eligibility on draft day is not eligibility in March. Any stored value carries an **as-of** date; a snapshot without one silently becomes wrong.
* **The owner's general expectation of the rule** is that starting at a position **5 times** grants eligibility there, never lost. He is explicit that other sites and leagues differ and that **Fantrax does not abide by it 100%**, so *there will at times be a rule/logical mismatch that takes some catching up*.
* **Therefore anything derived from starts is a prediction of a third party's behaviour, not a reading of eligibility.** Counting starts and presenting the output as eligibility would be modelling an undocumented, not-strictly-followed policy and dressing it as fact — the confident, plausible, wrong number `AGENTS.md` opens with. If it is ever built it belongs to `quant` behind the **Model gate**, labelled as an expectation with its calibration stated, and it may never be displayed as eligibility or used to construct a lineup Fantrax would reject.
* **The divergence is the product, not a nuisance.** The useful framing keeps the two claims separate: *"Fantrax lists him at G. He has started at forward 4 times, and the usual pattern suggests F eligibility is due; pages update about weekly."* One read, one inferred, never blended. A player four starts from gaining eligibility is exactly the league-specific, time-sensitive fact Basketball Monster does not provide, and it matters at the draft and on waivers.
* **Adaptability is a stated design requirement.** The owner: *a lot of the rules in these leagues require very dynamic tools.* That argues against hard-coding league rules as constants, and for holding them as data with provenance and building things that **detect divergence** rather than assume conformance. It applies well beyond position eligibility.

**A checkable lead, verified offline against the committed fixture on 2026-08-20:** `getPlayerIds` already carries a `position` field per row, and the parser already reads it to separate the 30 franchise entities (`position: "Tm"`) from the 1,788 players. The player values *are* fine-grained — `SG` 486, `PG` 345, `SF` 339, `PF` 310, `C` 246, plus a small tail of `F` 31, `G` 30 and one `Default`. **But it is a single value per row, not a multi-position eligibility set**, and Fantrax eligibility is routinely multi-slot. So this is plausibly the *primary* position rather than the eligibility list, and that is the first thing to check against a player page. Do not assume the convenient reading.

**There is probably an ADR here** — where eligibility truth lives, what freshness it carries, and how divergence is surfaced without being resolved — but that is for the lane that builds it, with evidence from a real capture.

The `injury-conversion-cohort-population` waiver of its own "positions" criterion was one downstream consequence of the NBA-position gap, now closed.

### `playoff-schedule` - Analysing fantasy playoff week schedules

- [x] **done**
- **Depends on:** `schedule-density`

Game counts for the fantasy playoff weeks specifically, surfaced during the draft and at the trade deadline rather than discovered in March. `playoff_scheduled_game_counts` exposes a league-scoped, ordered scoring-period x active-NBA-team grid from `scoring_periods.is_playoff` and `team_schedule`, including explicit zero-game rows, one required schedule-refresh cohort on every row, and no duplicate week table. Schedule lineage currently versions the NBA calendar only: `league-settings-ingest` now versions source settings and `deadline-model` versions their authoritative calendar, but `scoring-period-projection` must project and cascade that lineage into `ScoringPeriod` and this count grid before consumers may treat a changed playoff flag or boundary as invalidating an older result. This first pass is calendar fact only (game counts); a value-weighted second pass happens once `strength-of-schedule` exists in Phase 5 (ADR-011) — do not compute opponent-quality-weighted schedule strength here.

### `refresh-lineage` - Recording schedule/projection/model refresh provenance

- [x] **done**
- **Depends on:** `schedule-ingest`

A small `refresh_runs` registry and `/api/v1/lineage` contract recording when a schedule, projection, or model artifact was last (re)computed at a given version, and letting a downstream consumer check whether its claimed `schedule_version`/`model_version`/`projection_version` cohort is still current, stale, or unregistered. `import_schedule` stamps a content-fingerprinted schedule refresh as a side effect. Deliberately does not compute anything the registry describes — not SOS convergence (ADR-011), not p(play), not a projection blend — it only makes an existing versioning claim (ADR-009's `model_version`/`schedule_version` columns on `opponent_context`/`off_night_slates`) mechanically checkable. `quant` owns stamping its own rows consistently with what this reports as current and owns registering projection/model refreshes when those exist; this item does not modify the already-merged `schedule_context` schema.

### `reliability-metrics` - Building player reliability and consistency metrics

- [x] **done**
- **Depends on:** `participation-ledger`, `schedule-context`, `schedule-density`

V1 is the smallest scorecard current data can support honestly. It exposes
directly observed play/non-play evidence, a monthly observed trend, and observed
B2B sit evidence with counts and `incomplete_r35` coverage; missing and unknown
rows never become absences. Played-game production remains separate and reports
minutes CV, per-category sample SD, empirical p20/p80, and volume-weighted FG/FT
impact. A chronological three-season study rejected player-level
blowout-minutes suppression because calibration reversed sign in one bin, and no
composite grade has a defensible target, so neither field exists at runtime.
Results are computed on demand with schedule/source/derivation lineage; no
schema, API, or UI was added.

### `repo-create` - Creating the repo and pushing the handoff commit

- [x] **done**

Create SR2501/hoops-gm on GitHub and push the initial commit carrying docs/plan.md plus all governance artifacts, so nothing important lives only in a chat transcript. This is the chat-to-repo handoff.

### `repo-scaffold` - Creating the hoops-gm repo and monorepo layout

- [x] **done**
- **Depends on:** `agent-definitions`, `handoff-log`, `seed-adrs`

Create SR2501/hoops-gm on GitHub. Set up monorepo: backend/, frontend/, userscript/, docs/, docker-compose.yml, .github/workflows/. Add licence, README, .gitignore, .env.example.

### `schedule-context` - Building opponent and slate context

- [x] **done**
- **Depends on:** `nba-stats-ingest`, `schedule-ingest`

Versioned off-night slate percentiles, opponent pace, volume-correct
per-category defensive profiles, and held-out-calibrated blowout likelihood.
Descriptive schedule/box-score facts are separated from the decision-bearing
probability. Every output binds schedule/source/model cohorts and rejects stale
or mismatched currentness. The released model is loaded only from its packaged,
gate-passed artifact; training and holdout sources have separate fingerprints.
Regular-season context rejects partial team-minute box scores and refuses runs
below the persisted 95% fixture-coverage threshold. Garbage-time minutes
suppression remains null because
blowout calibration alone does not validate its magnitude; it belongs to
`reliability-metrics` once player-minutes evidence exists.

### `schedule-density` - Modelling schedule density

- [x] **done**
- **Depends on:** `schedule-ingest`

Back-to-backs, 3-in-4 / 4-in-5 / 4-in-6 stretches, rest-day differentials, road-trip length and structure. Direct input to the availability model.

### `schedule-grid-early` - Exposing the current raw schedule grid

- [x] **done**
- **Depends on:** `scoring-period-projection`

Loopback-only `GET /api/v1/leagues/{league_id}/schedule-grid/current` over
`scheduled_game_counts`: the complete ordered active-team x scoring-period raw
count matrix including explicit zeroes, plus the `teams` and `periods` a
browser screen needs to label its own rows and columns, plus the exact current
NBA schedule, scoring-period projection, deadline-calendar and
settings-snapshot lineage. `teams` and `periods` are read inside the same
transaction and lock scope as `counts`, so a screen can never render one
lineage's numbers against another lineage's headers. No classifications,
rankings, recommendations or schedule recomputation cross this boundary
(ADR-009).

Completeness evidence comes from `db/lineage.py`'s `verify_refresh` and
`schedule_completeness` — the canonical verifier the producer stamps against —
never from a second reader in the route. Missing, stale, unverifiable or
self-contradicting evidence, a wholly zero grid, an empty grid, a non-loopback
caller and an unknown league each fail closed with a typed code in
`ErrorResponse.error` and no partial data. (`X-Bridge-Error` is the internal
route-to-handler transport, not a response header: `api/app.py` consumes it and
returns the code in the body — verified, not assumed.)
`schedule_grid_incomplete_evidence` is a **family**: some members mean "the
refresh cannot state what it imported", others mean "it states what it imported
perfectly well, but that is not the cohort this grid counts". A consumer
rendering one fixed sentence for the code will be wrong for the second kind, and
must not substring-match `detail`, which is free-form prose rather than a
contract surface. Splitting the code or adding a machine-readable discriminator
is an open `architect` + `frontend` decision.

Operational, not merely safe: `python -m hoops_gm.dev.seed_schedule_grid`
brings a local database to a verified state offline from the committed NBA
fixtures, through the production importers, and the endpoint returns a real
200 against it (see `backend/README.md`). The first attempt at this item was
fail-closed but permanently unavailable, which is why the seed path is part of
the deliverable rather than a convenience.

### `projections-api-early` - Exposing the imported per-game projection cohort

- [x] **done**
- **Depends on:** `csv-importer`, `projection-blending`

Loopback-only `GET /api/v1/leagues/{league_id}/projections/current`, with
`?source=` defaulting to Basketball Monster: the per-game production rates one
projection source published, exactly as the importer decomposed them, plus the
`players` labels a browser screen needs and every fingerprint behind the numbers
— the CSV bytes, the parsing recipe, and the digest over the stored normalised
rates that changes when a row is edited in place while the other two look
untouched. The foundation of the draft board. Browser-*reachable*, not
browser-visible: the screen is `projections-ui`'s, below. That entry has since
shipped, so the sentence this paragraph used to end with — that `schedule-grid-ui`
is the only thing in this repository a person can look at — is no longer true and
was corrected by the lane that falsified it rather than left to go stale.

Descriptive only. No valuation, z-score, G-score, ranking, auction price, risk
adjustment, availability fusion or recommendation crosses this boundary — those
are `quant`'s behind the Model gate (ADR-002, ADR-008). The only arithmetic in
the route is `len()`.

**A client must not multiply a rate by `assumed_games_played`.** That number is
not merely a games-played figure: for a season-total source it is the exact
divisor the importer used to produce the rates beside it, so the product
recovers the source's published seasonal total to within floating-point
rounding. The ADR-002 decomposition is reversible at the wire by a two-line join, and doing
that join is the fusion ADR-002 permits only at `expected-games`, which is not
built. Display the assumption; do not compute with it.

**It serves the *imported* cohort, not a blended one, and `lineage.blend` is a
typed key that is always `null`.** `projection-blending` computes a blend from a
`BlendCatalog` that is an explicitly caller-owned in-memory value —
`define_blend_profile` and `activate_blend_profile` each return a *new* catalog
because the accepted schema has no blend tables, by design. So no blend profile,
activation pointer or source weights are persisted for any HTTP request to read,
and serving a blend would mean the route choosing weights itself. The key exists
so a consumer renders "not blended" from a fact rather than from a key it failed
to find; at the JSON level it is also where a blend would surface, though the
declared type is `None` rather than `BlendLineage | None`, so that is a schema
change and not a fill-in. Persisting blend profiles is a separate `architect` +
`quant` unit, and is on the path to the owner's stated requirement of seeing
Basketball Monster and our own numbers side by side during the draft.

ADR-002's separation is in the wire format, not only in the schema: the source's
own games-played assumption is a separate top-level array, never a key inside a
rate object, mirroring the one-to-one table it comes from, and a test asserts
`games`/`expected_games`/`rank`/`aav`/`z_score`/`g_score` appear in no rate
object and at no top level. No shooting percentage is ever computed — makes and
attempts only.

Currency, profile verification and row validity come from
`blending.release_projection_import`, the canonical function the rest of the
pipeline already trusts, never from a second reader in the route; the route's
own "which import" query is a *selector* the canonical release arbitrates, so
drift in the definition of "current" fails closed rather than serving a
superseded cohort. Eight typed codes in `ErrorResponse.error`:
`projections_local_only`, `projections_league_not_found`,
`projections_source_unsupported`, `projections_source_not_imported`,
`projections_not_current`, `projections_incomplete`,
`projections_incomplete_evidence` and `projections_inconsistent_cohort`.

`projections_incomplete_evidence` is a **family of nine driven members** —
unverified import row, unverified profile-version row, season outside verified
scope, self-contradicting immutable lineage, a negative rate, a non-finite rate,
a half-present three-point made/attempted pair (the only pair with no CHECK
constraint), a row whose denormalised season drifted from its import, and makes
exceeding attempts. That last was called *unreachable* through two review rounds
on the ground that the CHECK constraints block it at the same `+0.001` tolerance
the validator uses; the constant is the same but the arithmetic is not — the
CHECK is IEEE-754 double, the validator compares exact `Fraction`s — so a band
about one ULP wide inserts and then fails validation. Driven. It stays one code
under `architect`'s rule — *split when two members imply different operator
actions; keep one when every member implies the same one* — because re-importing
rewrites the whole row cohort and so repairs every member. **This enumeration was
short at five, then at eight, before it was nine**, and each recount came from
someone walking the raise sites rather than reading the previous list. A consumer
must render a summary true of every member and must not substring-match `detail`,
which is free-form prose. `test_the_blending_error_family_is_pinned` fails if
`ProjectionBlendError` gains a subclass, so convergence is decided rather than
inherited.

Guaranteed on any 200 or refused instead: `players` and `projections` describe
the same `player_id` set, each exactly once, both ordered; and
`len(projections) == lineage.projection_import.projection_count`.
`source_games_played_assumptions` is deliberately sparse and absent never means
zero.

**The route takes no lock, and that is the decision rather than the omission.**
An earlier version took the importer's `projection_sources` row `FOR UPDATE` and
claimed both dialects serialized; review drove it and the SQLite half was false,
because pysqlite emits `BEGIN` only before DML and SQLAlchemy drops `FOR UPDATE`
— a concurrent writer committed straight through the reader and produced a 200
whose rates were post-write beside a pre-write digest. Adding SQLite's write
reservation fixed that and cost more than it bought: every read became a writer,
so concurrent polls serialized against each other (measured at 2.05s and 4.17s,
with an untyped 500 for the loser of a slower pair) and an open dashboard tab
could make a hand-run import fail with `database is locked`; it also mutated
`updated_at` through `TimestampMixin`. Instead every read is **bracketed between
two runs of the canonical release**.

**What that detects, stated at the strength it was driven at.** A write landing
*before* the rows are loaded is caught. One landing *after* them is caught only
if it replaced the row primary keys — an in-place edit is shadowed by the route's
own strong references and a consistent *older* snapshot is served, while a
re-import replaces every key and is seen. That last is dialect-dependent:
PostgreSQL's `SERIAL` never recycles, SQLite can. The guarantee is unconditional
either way — the rates and the lineage block beside them always describe the same
cohort state — but the behaviour is not, and two earlier versions of this entry
said otherwise (first "refuses if anything moved", then "identically on both
dialects"). Freshness is not promised. `projections_inconsistent_cohort` is the only retryable
code of the eight; a client retries once and keeps the last good payload rather
than clearing the view. Driven with real committed writes from a second
connection, with monkeypatching confined to *timing* rather than to the loader's
result.

### `release-digests-assumptions` - Bringing the games-played assumptions inside the release digest

- [ ] **pending**
- **Depends on:** `projections-api-early`

`ReleasedProjectionImport` digests the `projections` rows and deliberately never selects
`source_games_played_assumptions`, so `projections-api-early`'s assumptions array is the
one part of that response outside the guarantee the endpoint makes about itself. The
array is joined on `projection_import_id` and subset-checked against the players carried,
which makes a claim for an uncarried player inexpressible — but a *changed* assumption is
not detected, and the array's documented semantics ("a missing entry means the source
said nothing") are a strong claim with nothing pinning them.

Found by `architect` reviewing the fix for the defect it enables: a byte-identical
re-import mid-read served a 200 with an **empty** assumptions array, reporting that
Basketball Monster published no games-played assumption when it published 70 and 78. The
route-level fix closes that instance; this closes the class, by making the array inherit
the same mechanism that already catches a rate edit instead of borrowing its credibility.

A producer-contract change in `hoops_gm.projections.blending`, not an API change. ADR-002
is the constraint that makes it delicate: the assumption must be digested *alongside* the
rates as separate evidence, never folded into `projection_values_sha256`, or the
separation the table exists to enforce is lost at the fingerprint. On completion, retire
the exemption stated on `CurrentProjectionsResponse` and amend ADR-014.

### `projections-ui` - Putting the imported projections on screen

- [x] **done**
- **Depends on:** `projections-api-early`

The draft board's first surface: every player in the current Basketball Monster
cohort with their per-game rates, at `/projections`. Consumes
`projections-api-early`'s endpoint and renders exactly what it returns — no
ranking, no valuation, no z-score or G-score, no availability weighting and no
"who should I draft" judgement, all of which are `quant`'s behind the Model gate.

**Three contract obligations the endpoint cannot enforce for it.** First, the
source's games-played assumption may be *displayed* and must never be multiplied
by a rate: that number is the divisor the importer used, so the product recovers
Basketball Monster's published seasonal total, and doing that join is the fusion
ADR-002 permits only at `expected-games`. Rendering "projected season total" from
this payload is an ADR-002 violation that is two lines long and looks like a
feature. Second, `projections_inconsistent_cohort` is retryable and means a
concurrent import moved the cohort — retry once and keep the last good payload on
screen, because an empty board mid-auction is worse than a slightly stale one.
The other seven codes are terminal and need a human. Third,
`projections_incomplete_evidence` is a family of nine members with one shared
remedy, so its copy must be true of all of them and must not substring-match
`detail`.

`source_games_played_assumptions` is sparse: absent means the source said
nothing, never zero, and must render distinguishably from a stated value — the
same distinction `schedule-grid-ui` spent four review rounds getting right.
Position eligibility is *not* available: this project ingests no Fantrax position
data, and `player-position-eligibility` is still pending, so a draft board cannot
filter or group by position yet. `players[].primary_position` is NBA's own label
and is nullable.

**Sparsity is unreachable for the source this screen requests, which changed the
copy.** Basketball Monster's `required_production_fields` is set-equal to
`CANONICAL_STAT_FIELDS` in both directions, and `parser.py:293-296` refuses a row
on *any* missing required value — so a row with no games figure has no divisor,
nulls its 14 `SEASON_TOTAL` columns and (via `parser.py:448-450`) the 2 derived
fields, and is dropped. Every stored Basketball Monster row therefore carries an
assumption *and* a value for every rate. Sparsity is reachable only through
per-game profiles such as `MANUAL_PROFILE`, which this screen never requests. So
the screen states that an absence marker *should not appear* rather than
implying routine sparseness, and `backend/tests/test_projection_vocabulary_pin.py`
is what keeps that claim true — nothing enforced the set-equality before it.

The same care does **not** extend to the Team and Pos columns: those labels come
from our own player record, so their absence says nothing about what the source
published, and they carry a different marker. Shipped sharing one marker, caught
in review against the recorded fixture in the same commit.

### `projections-import-cli` - Giving the owner a command that imports his projection CSV

- [x] **done**
- **Depends on:** `csv-importer`

`python -m hoops_gm.ingest.projections.import_csv <season> <path>` — the
operator surface `csv-importer` never had. The importer was a library function
with no `main` and there is no HTTP write path for projections, so the owner's
paid Basketball Monster export could only reach the database if somebody wrote
Python at a REPL, and `projections-api-early` shipped an endpoint over a table
nothing filled. Reads `Settings`, so there is no `--database-url` to leak — both
prior credential leaks in this repository were leaks *of that flag*, and a test
pins the option set. Prints no rate, no player row and no cell value from the
file: the export is paid content and a terminal scrollback is a paste away.
Source names reach only the unresolved-players CSV under gitignored
`data/reports/projections/`. `raw_payload_ref` stays unset with the reason
recorded — `RawPayloadStore.put` hard-codes `.json.gz` and models an HTTP
capture, so a CSV through it would invent a request; `content_sha256` already
binds the import to its exact bytes.

`--dry-run` is a **rehearsal, not a preview**: it runs the real import including
identity resolution and rolls back, because "how many of my 550 players matched"
is the number that decides whether an import is usable and it needs a session. It
therefore holds the write lock for its duration and says so in `--help`. It does
not relax profile verification, so a green dry run cannot promise an import that
then refuses. The rollback is asserted by counting three tables, not by trusting
a context manager.

Exit `5` means **imported, and the cohort is smaller than the file**. Its two
causes — parser-rejected rows and unresolved identities — imply the same action,
so they share one code under `architect`'s rule, with counts that discriminate.
The alternative was exit `0` on an import where a hundred players silently failed
to match. Also closes `projection-import-process-concurrency`, below.

### `projection-import-process-concurrency` - Making the projection import lock real

- [x] **done**
- **Depends on:** `csv-importer`

R58. `import_projection_csv` guarded a repeat import with `SELECT ... FOR UPDATE`
on `projection_sources`, which serialised nothing on SQLite: pysqlite emits
`BEGIN` only before DML and a repeat import of an unchanged source emits none
before that statement, and SQLAlchemy's SQLite dialect renders no `FOR UPDATE`
text at all. Replaced by `db.lineage.lock_projection_source_scope`, delegating to
`lock_refresh_scope` so `db/lineage.py` stays the only module reaching
`acquire_transaction_lock` — two lock-order recorders monkeypatch that one name,
and the first version of the fix blinded them and was caught by the test that
exists to notice. Taken before the source row is read rather than after, since
the old clause closed the window later than it opened. Registers no
`refresh_runs` row: a lock scope is not a published refresh, and `quant` owns
registering those.

**Filed here because R58 said it was filed and it was not** — it existed in the
risk row's mitigation text and in no backlog entry, which is the check nobody
runs on their own register. Closed with the severity honestly narrowed: the
window was real, but four concurrent processes at a barrier against one SQLite
file with the lock disabled converged correctly on every round, with identical
bytes and with divergent cohorts. SQLite serialises writers at the file level
once DML begins. The corruption the 🟡 implied was never reproduced.

### `projections-seed` - Making the projections endpoint answer 200 offline

- [x] **done**
- **Depends on:** `projections-api-early`, `projections-import-cli`

`python -m hoops_gm.dev.seed_projections`. `/projections/current` had never
returned 200 outside pytest: it fails closed on an unimported source, and
`seed_schedule_grid` seeds no players and no projections, so
`projections_source_not_imported` was the only answer anybody had ever seen from
it — the same blind spot that made the previous schedule endpoint permanently
unavailable with nobody noticing. `projections-ui` could not drive its screen or
capture a fixture.

**The committed Basketball Monster fixture cannot do this**, which is the finding
that shaped the unit: its two rows are named *Player Alpha* and *Player Gamma*,
they match no canonical player, so the importer accepts zero resolutions and
`release_projection_import` raises. Seeding it through the real importer produces
a new refusal, not a 200. It stays untouched — it is Adapter-gate evidence of the
column contract and is doing that job. (The population they fail to match is
`nba_commonallplayers_current.json`, which `import_nba_players` reads;
`nba_playerindex_current.json` only supplies positions and creates no players.
Three docstrings named the wrong one, and a reviewer noted *both* files contain
an "Alpha" — Alpha Diallo — so a reader checking the claim by grepping the name
got a hit either way, while the normalised key `alpha|player` matches nothing.)

The demo CSV is generated **in memory at seed time** from the canonical players
the same run imported, in the verified profile's exact committed header order,
and goes through `import_projection_csv` unmodified — `seed_schedule_grid`'s
production-importer standard, applied to a second importer. No committed CSV, on
purpose: a checked-in file of real NBA names beside real captures would read as
one. Names are real because Basketball Monster publishes no team or position
column, so a name is the resolver's only evidence; only players whose normalised
name is unique are used, so each row lands at exactly `AUTO_ACCEPT_CONFIDENCE`
and resolution succeeds by construction rather than by luck. **The numbers are
invented** and the docstring says so first: nothing derived from the cohort is a
projection anyone should look at, and a fixture captured from it proves shape and
nothing else.

### `demo-one-command` - One command, one database, three screens

- [x] **done**
- **Depends on:** `projections-seed`, `draft-format-abstraction`, `schedule-grid-ui`

The three dev seeders always composed and **nobody had run them in one order**.
Demo state lived in three separate SQLite files, one backend serves one file, so
the owner opened the dashboard on 2026-08-22 to a working draft board beside two
`409` error pages. Nothing was broken. The composition existed only as commands
someone happened to know, which is the failure mode `AGENTS.md` names first:
*nothing important lives only in a chat.*

`python -m hoops_gm.dev.seed_demo` is that composition, `docs/demo.md` is the
runbook, and `backend/tests/test_seed_demo.py` drives all three routes against
**one** seeded database. That last part is the regression test for the whole
item: each seeder already had a test proving its own endpoint could answer, and
a test that seeds one database and reads one endpoint is green whether or not
the other two are pointed somewhere else.

Three corrections to the reconstruction this unit started from, each driven:

- **`seed_schedule_grid` before `seed_projections` is redundant, not required.**
  `seed_projections` already composes it. Only `seed_draft`-last is a real
  constraint, and it is a hard one — its `[demo] ` leagues carry
  `fantrax_league_id IS NULL`, which is the first arm of
  `require_safe_demo_target`, so a drafts-first database can never have the
  other two screens seeded into it at all.
- **Real-scale schedule and projections are not mutually exclusive.** The
  refusal that suggested they were (*"already holds 2026-27 game `0022600004`,
  which is outside the fixture cohort"*) fires when the schedule seed runs
  against a live capture and the projection seed is then run against the
  *committed* fixture — two cohorts, correctly refused. Give both the same
  `--fixtures-dir` and it is one cohort. Driven 2026-08-23: one database with
  1,200 imported games, 2,400 team-schedule rows, 30 teams, 25 periods, 60
  projection rows and 2 drafts, exit 0, schedule version byte-identical to the
  real-season-only seed. **`require_safe_demo_target` was not touched**; it was
  satisfied honestly. The projections themselves remain synthetic — all that
  changed is the schedule they sit beside.
- **The composition is reproducible from empty, not idempotent.** Re-running it
  refuses, because the draft seed leaves rows the schedule seed is written to
  refuse, and the message names a league — which reads like data loss rather
  than a repeat. `looks_like_a_previous_demo_seed` adds the sentence that tells
  the two apart. It grants no permission and changes no guard.

Mutation evidence in `scripts/mutate_seed_demo.py`: 11 mutations, 11 caught, 0
survived, 0 harness failures. M07 — a `session.commit()` between the two
seeders, which is exactly what composing them at the shell does — is the only
one that distinguishes "one atomic session" from "the refusal happened to fire
before anything was written", and it reddens exactly one test.

**A real store slipped every guard, and closing it was the larger half of this
unit.** The owner's database at `hoops-gm-data/hoops_gm.db` holds 0 leagues and
1,230 games all in 2025-26, so the league check and the cohort check both passed
it; the crosswalk is entirely `nba`-source, so the projection check passed too.
Driven against a migrated copy, the composed seed exited **0** and wrote 3
leagues, 2 drafts, 10 synthetic games and 60 `synthetic-demo-*` rows that became
the current Basketball Monster crosswalk, beside a 43,037-row participation
ledger. It escaped in reality only because its schema is at `0016` and
`seed_drafts` crashes on a missing table — protection by accident, removed by
one `alembic upgrade head`. `_require_no_real_ingest` closes it on two signals
no seeder writes: any `player_participation` row, and any `nba_games` row for
another season.

**On the dependency list.** `hoops_gm.dev.seed_draft` landed under
`draft-tracker`, which is still **pending** for the bridge feed — so this item
does *not* depend on it, and an edge to it would have been a false claim that
this rests on a live draft feed. The recorded relationship is here in prose
rather than as an edge, and the real edge is to `draft-format-abstraction`,
which is what the draft seeder drives its events through.

### `schedule-grid-pending-periods` - Showing that a scoring period is not fully scheduled

- [x] **done**
- **Depends on:** `schedule-grid-ui`

ADR-013 lets a refresh register with games the source published without
deciding their teams, so the grid can now show a count that is honest and
incomplete at the same time. A scoring period containing one is marked `TBD` in
its header with a dashed column rule, and a notice states the only thing the
data supports: *this period contains N games whose teams are not yet decided, so
any count in this column may rise*.

This also depends on the backend emitting `lineage.schedule.pending_game_ids`
and `pending_games`, which is the `data-engineer` lane implementing ADR-013 and
had no backlog slug when this was written. `architect` is creating one; this
item's dependency list should gain it.

The wire types were **optional** on the client (`pending_game_ids?`,
`pending_games?`) while the backend lane was unmerged, and the absence was
rendered as its own statement. That lane merged as `28bd480`, so the tolerance
is gone: both fields are required, the "cannot say" notice is deleted, and the
boundary refuses a response without the block. **Closed.**

Three further follow-ups, each with a trigger, recorded here because prose
nothing prompts anyone to revisit is how a screen keeps asserting something it
once checked:

- **The caption's make-up-game clause expires.** It says those games have not
  been released. When the NBA releases them it becomes false, and no
  client-side condition can detect that — nothing in the payload distinguishes
  80 games published because the bracket is open from 82 published. `frontend`
  owns it; the trigger is the Emirates NBA Cup knockout resolving in December.
  The re-ingest clause beside it does not expire.
- **`grid-integrity` still carries `role="status"`.** The two ADR-013 notices
  dropped theirs, because a region present at first paint that describes data
  rather than announcing a change belongs in no polite queue. The same argument
  applies to `grid-integrity` and it was left alone only to avoid changing an
  already-reviewed surface inside an unrelated diff. `frontend` owns both, so
  this is a note to itself and belongs in a tracker rather than a comment.
- **Neither ADR-013 notice announces on refresh.** Dropping `role="status"` is
  right on load and leaves a refresh that takes the pending set from empty to
  non-empty silent. The fix is a region that is empty at mount and live
  thereafter, if the cost is ever judged worth it.
- **`irreconcilable` was classified as wait-class on an inference, and ADR-013
  has now decided it.** The screen split absence causes into wait
  (`not_offered`, `irreconcilable`) and investigate (`unreadable`,
  `implausible`), mirroring the producer's `_FAULT_ABSENCE_REASONS`, which
  excludes `irreconcilable` so the import stays exit 0. That was a
  reconstruction rather than a rule: an exit code answers *should this import
  fail*, and the screen answers *should a human look*.

  **Resolved: `irreconcilable` is a fault.** `architect` ruled it from the live
  feed rather than by argument — the alarm-fatigue objection to widening the
  fault set is a claim about volume, and all six real pending games carry a
  date and an empty reason, so every fault reason fires zero times today. The
  caveat is recorded in ADR-013: if that stops being true, revisit the row
  rather than letting an operator learn to ignore the channel.

  `code-review` supplied the sharper argument, which is about drift and which
  frequency data cannot retire: the producer's own docstring says an epoch
  placeholder pair **reconciles perfectly** for 1900 (`-05:00`) and fails only
  by accident for year 0001, because `America/New_York` ran on `-04:56` local
  mean time before 1883 — so one phenomenon lands in `implausible`,
  `irreconcilable` or `unreadable` depending on a nineteenth-century offset and
  the hour. **The cleaner repair is upstream in `_FAULT_ABSENCE_REASONS`**, and
  that is `data-engineer`'s to weigh; the client no longer depends on it either
  way, because it enumerates the *wait* set and defaults everything else to
  investigate.
- **`.grid-scroll`'s `18rem` budget is now short by a block.** The constant was
  written for four things above the grid; the pending notice is a fifth and is
  present in every shipping state. Measured at a 720px viewport with scroll at
  zero and the lineage collapsed, the first count sits at 583px against a 270px
  budget — five of thirty teams visible, and `tfoot`'s league totals reachable
  only through the inner scroll. The comment now says so. The fix is the one
  that comment already names, a flex column with `min-height: 0`, rather than a
  larger magic number; it is a whole-screen layout change and does not belong in
  a pending-games diff. `frontend` owns it.
- **The caption is the table's accessible name, now 407 characters.** Announced
  on every entry into the table rather than once in document order. Attaching
  the caveat to the table is right in principle — a reader arriving by table
  navigation never heard the page paragraph — but the clean split is name for
  the identifying clause and `aria-describedby` for the caveat. Not done here
  because `aria-describedby` is announced unreliably on `table`, so the trade is
  not obviously favourable and no one has tested either with a real screen
  reader. `frontend` owns it; the trigger is anyone testing this screen with AT.
- **The pending block distinguishes *absent* from *empty*, and the screen cannot.**
  A completeness block written before ADR-013 has no `pending_games` key at all —
  confirmed on the real pre-merge refresh, which carried `source: 1200`,
  `resolved: 1200` and the key **absent rather than empty**. Reading it as `()`
  is sound (`lineage.py:222-225`: the old contract required
  `source == resolved`, so the pending set was necessarily empty), and the
  client is right to render an affirmative zero. But the two states the screen
  deliberately collapses — *this refresh had no pending games* and *this refresh
  predates the concept* — **are still distinguishable in the stored block**. No
  change today: the collapse is correct for a reader who only needs to know
  whether any count may rise. Recorded because a later reader wanting refresh
  provenance has more to work with than the response shows.
- **The mutation harness should be committed, and the reason overturns the rule
  that kept it out.** Governance said *commit a tool whose failure mode is loud;
  describe a tool whose failure mode is silent* — and a mutation harness fails
  silently, since a broken one reports success. That conclusion is wrong here.
  **Loud/silent governs safety; it does not govern evidence.** *33 of 33 caught*
  was cited in every one of this unit's nine review rounds and **no reviewer
  could ever check it**, because the thing producing it was outside the
  repository. Stating the limitation each round is what made it invisible rather
  than what excused it. The rule now reads: **if a tool's output is cited as
  evidence, it belongs in the repository regardless of failure direction, because
  the citation is what is being audited.** Deliberately not done in this PR — the
  unit stopped at `architect`'s ruling, and adding a tool at round ten is how
  round eleven happens. It carries a preflight that treats a rotted anchor as a
  failure, and 33 mutations plus a separate driver for the `--verify` holes; both
  live in session state today. `frontend` owns it; the trigger is the next unit
  that would cite a mutation count in a review.
- **`ScheduleGridTable.recorded.test.tsx` still asserts `counts` completeness by
  length**, `teams.length * periods.length`, which is the proxy that let a real
  count row be replaced by a duplicate zero row and render as `·`. `--verify`
  now catches that case by comparing the key set, so the tree is not blind to
  it; this assertion is a second check sharing the retired proxy. Not changed
  here because it was not driven end to end, and quietly editing an assertion is
  how this file got into trouble. `frontend` owns it.
  closes two problems.** `make_pending_date_payloads.py` is a Python script under
  `frontend/src/test/fixtures/` that imports `backend/src` to make *frontend*
  fixtures, so it belongs to neither side. The cost is measurable rather than
  aesthetic: the only ruff config is `backend/pyproject.toml` and CI runs
  `ruff check .` with `working-directory: backend`, so nothing in this repository
  lints, formats or type-checks the file where it sits. Separately, nothing in CI
  pins `input -> reason`; `--verify` is a script a person runs, and the clean
  version is a backend test importing the derived payloads and asserting the four
  reasons. **That test requires the derivation to live under `backend/`, so doing
  the gate does the move.** Filed as one item rather than two, because two items
  with one fix diverge — one gets done and the other stays open describing a
  solved problem. `data-engineer` owns it; the trigger is the next touch of the
  schedule-ingestion lane, not "any change to `_pending_game_date`", which only
  someone already thinking about this file would notice. `architect` holds only
  the ruling that it moves. One thing to fold in when it moves: `team_id` and
  the lineage fingerprint fields are the only response values `--verify` cannot
  derive, because both need a database. Everything else — pending records,
  period windows, team labels, all 630 count rows, the lineage counters — is
  derived from the producer and compared.

**Period-scoped, never cell-scoped.**
A pending game carries `teamId: 0` with
every naming field null, so no team can be named and none is. A per-cell "this
team has an unscheduled game" badge would invent the one attribution the source
withheld; the recorded contract test asserts every cell in a pending column
carries the same state and the same accessible name as a cell anywhere else.

Three states are now kept apart where there were two: `0` is a real count,
`·` is data the backend did not send, and a `TBD` column is the source not
having decided. Each has its own colour, marker and wording, and `+?` is
deliberately not reused for pending — it means a sum is short because data is
missing, which is a different claim. A pending block that is *absent* is a
fourth statement, "this response cannot say", and is never read as "nothing is
pending". The lineage panel gains the pending count and lists each game's id,
date and labels, because ADR-013 reverts to refusing if the pending set stops
being explicable as an undetermined bracket and a bare count shows nothing to
check that against.

The four non-empty `date_absence_reason` values fire zero times against the live
source, so both recorded fixtures covering them were produced by driving the
in-tree importer with authored source payloads. Those payloads are derived by
`frontend/src/test/fixtures/make_pending_date_payloads.py` rather than
remembered: `--verify` re-runs the producer's own classifier over them and
asserts the four reasons, and both fixtures were regenerated end to end through
it — seed, serve, capture — differing from the committed bytes in one leaf,
`refreshed_at`. This exists because the fixtures first landed with the inputs
uncommitted, which made *input -> reason* a claim nothing could check; one of the
two payloads had already been overwritten by the time a reviewer said so.

### `schedule-grid-ui` - Putting the raw schedule grid on screen

- [x] **done**
- **Depends on:** `schedule-grid-early`

Teams down, fantasy scoring periods across, scheduled game counts in the cells,
at `/schedule`. Consumes `schedule-grid-early`'s endpoint and renders exactly
what it returns: no availability weighting, no opponent quality, no colour scale
and no light/heavy judgement (ADR-009).

`games: 0` renders as `0`; a `counts` row the backend never sent renders as its
own marked cell and is counted in a visible notice. A blank cell can never mean
either, which is the failure mode this screen exists to avoid. Totals that are
short a period are marked on screen rather than only in screen-reader text, so
a partial sum cannot be read as a complete one. Each of the five documented
refusal codes gets its own explanation and next step, read from the response
body, on both the cold-load and the failed-refresh path. Schedule lineage —
version, refresh id, raw `refreshed_at`, source/resolved/persisted counts — is
on the page rather than in devtools, and the cohort's age is reported against
ADR-012's weekly re-ingest cadence.

The per-period league sum and the per-team mean satisfy the amendment's
league-wide baseline clause. The team-versus-own-distribution clause is
deliberately not implemented here — see `schedule-grid-reference-distribution`.

### `schedule-ingest` - Ingesting the NBA season schedule

- [x] **done**
- **Depends on:** `nba-stats-ingest`

Season schedule ingestion, fantasy week definitions, and per-week scheduled game counts per team. Foundation for schedule density and the availability model. Extended 2026-08-20 under ADR-013 with the pending/failure distinction and an operator command (`python -m hoops_gm.ingest.schedule_import 2026-27`), which is what makes the real 2026-27 season loadable: 1,206 source entries, 1,200 resolved across 30 teams at 80 games each, six Emirates NBA Cup knockout fixtures recorded as pending. Pending means the source published an explicitly absent identity block — `teamId: 0` with every naming field null; a zero id beside *any* populated naming field is a resolution failure and still refuses the cohort. Two gaps it exposed are filed as `schedule-pending-persistence` and `schedule-cohort-fingerprint-list`.

### `scoring-period-projection` - Deriving `ScoringPeriod` from the active deadline calendar

- [x] **done**
- **Depends on:** `deadline-model`, `schedule-density`

`LeagueDeadlineCalendar` remains the immutable, versioned authority.
`project_scoring_periods` is the sole production writer for the older
`ScoringPeriod` table: it validates the active calendar against the current
league-settings snapshot and keyed NBA schedule refresh, rejects unknown
playoff evidence, converts every boundary to `America/New_York` before taking
its inclusive date, and records a deterministic keyed refresh containing the
exact settings, calendar, schedule, and projected-period cohorts. Changed
materializations replace only unreferenced rows; matchup references fail closed,
while immutable calendars and refresh summaries preserve replacement history.
`scheduled_game_counts` and `playoff_scheduled_game_counts` now validate that
both the materialized rows and projection lineage match current inputs before
returning counts, and each result carries all four cohort identifiers and
versions. The existing schema supports this contract honestly, so no migration
or reserved revision number was used. This remains calendar fact only: no
opponent-quality, availability, or model math is added.

### `scoring-profiles` - Abstracting scoring profiles for multi-format support

- [x] **done**
- **Depends on:** `db-foundation`, `league-settings-ingest`

Scoring-profile abstraction so points and roto formats can slot in later without rewriting the valuation engine. H2H 9-cat is the first concrete profile. Implemented: `league_scoring_profiles`/`league_scoring_categories` (already scaffolded in `db-foundation`) gained `settings_snapshot_id` (source attribution to a `LeagueSettingsSnapshot` version) and `active_league_id` (a nullable, uniquely-constrained self-FK replacing the old `is_active` boolean, enforcing "at most one active profile per league" as a database constraint with no dialect branching -- see `db/models/league.py`, migration `0012`). `LeagueSettingsDocument` (`ingest/league_settings.py`) now carries `scoring_type`/`scoring_categories` as first-class sourced fields (document `schema_version` 2; migration `0012` backfills every pre-existing snapshot row with an explicit, honestly-evidenced *absent* observation for both, never a guess), parsed by the same `getLeagueInfo` importer that produces roster limits and scoring periods, so a scoring profile's lineage is genuinely tied to a specific settings snapshot rather than an independently-supplied argument. `hoops_gm.scoring.profiles.build_scoring_profile` derives a profile exclusively from a league's current settings snapshot -- no caller-supplied category list -- mapping on the Fantrax `code` (fixture-verified, fail closed on unmapped/duplicate/non-unit-weight/malformed-shape categories) to a canonical 9-category vocabulary (AST, BLK, PTS, REB, ST, 3PTM, TO, FG%, FT%); percentage categories are stored as made/attempted component pairs, never a raw percentage. `scoring_type` is derived from the snapshot's own discriminator via a verified mapping, never defaulted, with evidence citing whichever of the two possible source fields actually won under official-priority precedence. Content-fingerprint idempotency means re-deriving from an unchanged snapshot returns the existing profile row unchanged; reactivating a version whose content matches the *current* snapshot after cycling through another (A -> B -> A) mints a new version carrying A's content but the current snapshot's own FK -- never repointing an existing row's snapshot reference, which would rewrite historical lineage. Activation (`activate_scoring_profile_version`) revalidates exact league binding, current-snapshot freshness, and a non-empty category set before touching whatever profile is active, and is a separate, explicit, two-phase deactivate-then-activate step. A production seam (`derive_scoring_profile` / `scoring-profile` CLI subcommand) runs this end to end from an ingested settings snapshot to an explicit, opt-in activation. No rankings/AAV/market evidence enter this layer (ADR-008); no projection, availability or valuation math is computed here (ADR-002 stays intact -- this is configuration, not production or `p(play)`). Model gate does not apply: nothing decision-bearing is computed or backtested, only Code and Adapter gates. See `docs/handoff.md` for the full entry, including the remediation rounds that made the settings snapshot the sole source of scoring lineage, fixed the A -> B -> A activation dead-end, and backfilled schema v2 for pre-existing snapshots.

### `seed-adrs` - Seeding ADRs from decisions already made

- [x] **done**
- **Depends on:** `governance-docs`

Write ADR-001 to ADR-007 as Proposed: local-first with Postgres seam; separate production from expected games played; G-score default for H2H; Fantrax read via API and write only via browser bridge; supervised-by-default automation; adapters isolated behind contract tests; availability modelled before valuation. Agents may not mark their own ADRs Accepted.

### `userscript-foundation` - Building the Tampermonkey userscript foundation

- [x] **done**
- **Depends on:** `backend-skeleton`

Userscript build pipeline, @match rules for fantrax.com, shared-secret handshake with the backend, and GM_xmlhttpRequest transport to localhost (bypasses CORS and page CSP).

---

## Blocked

### `fantrax-auction-capture` - Capturing a Fantrax auction draft room before the real one

- [ ] **pending**
- **Depends on:** `bridge-capture`

**The snake capture on 2026-08-28 tested half the recogniser. This is the other
half, and it is calendar-blocked rather than unavailable.** Fantrax will run NBA
auction mocks closer to the season; they simply have not started. That makes this
a *scheduling* problem with a known resolution, not an open question.

**What the snake mock could not touch.** It ran with `isAuction=false`, so
nominations, bids, prices, budget derivation and everything Route B rewrote on
2026-08-27 remain **completely unobserved**. `FIELD_ALIASES["amount"]` guesses
`amount`, `bid`, `salary`, `price`, `winningBid` — five names, none confirmed
against a real payload, and the same guessing that produced `teamId` where
Fantrax sends `draftTeamId`.

**The schedule risk, stated plainly because it is the point of filing this
early.** One afternoon on a snake mock found a defect that would have emptied the
board — a missing team alias, invisible to every test. The auction path carries
*more* guessed field names than the snake path did, has had a substantial
behaviour change land since (Route B), and has never been driven at all. If a
Fantrax auction mock only opens in early October, the window between "first
auction payload seen" and 18 October could be **days**, with no slack to fix what
it reveals.

**So this is not a task to schedule; it is a trigger to watch.** The moment
Fantrax auction lobbies open, run one — ahead of any other capture, ahead of
polish, and treat whatever it refuses as the highest-priority defect in the
project. `docs/mocks/instrumented-capture.md` is the procedure; record the format
as auction and note that identity results transfer only if the mock is NBA.

**Distinct from `blind-mocks`, and they must not be merged.** That item wants
*uncontaminated market prices* and is satisfied by ESPN today. This one wants
*Fantrax payload shape* and can only ever be satisfied by Fantrax. Running one
does not discharge the other.

### `blind-mocks` - Running blind mocks when auction lobbies open

- [ ] **pending**

**UNBLOCKED 2026-08-28.** The block below rested on a premise that has stopped
being true: the owner reports **ESPN is running live NBA auction mocks now**,
while Fantrax has none. Everything this item asks for is platform-agnostic — it
never named Fantrax — so ESPN satisfies it in full.

**Run them on ESPN, capture by hand with `docs/mocks/TEMPLATE.md`, and do not
build collection tooling.** Three reasons, and the third is the one that decides
it: a scraper for a platform the owner does not draft on is throwaway code while
`draft-board-dom-parser` is the critical path to 4 October; the item's own method
is a manual capture form; and it explicitly requires the mock be run **without
this tool**, so automation aimed at *our* side of the loop is beside the point.

**This is perishable.** Auction lobbies are seasonal, the corpus only accumulates
while they are open, and prices sharpen as the season approaches. A mock not run
in September cannot be run in November.

**Do not let the tool near it.** R38's circularity risk is the whole reason this
is the control group: once bidding is informed by our own values, the corpus
contains our own output and stops being independent evidence.

EXTERNALLY BLOCKED 2026-08-17 (superseded, kept for the record): the owner found no site currently offering live mocks, including auction mocks. Do not manufacture simulated clearing prices and call them market evidence. When auction lobbies open, run observation-only mocks without this tool and capture each using docs/mocks/TEMPLATE.md. They remain the uncontaminated control group for R38, the counterfactual baseline for measuring whether the tool helps, and the empirical AAV evidence R37 needs. League configuration is mandatory on every capture.

---

## Pending

### `aav-blending` - Blending AAV across sources with per-source weights

- [ ] **pending**
- **Depends on:** `aav-empirical`, `aav-source`, `hashtag-projection-profile-verification`, `layer-purity`

AUCTION CRITICAL (R37). Weighted blend of seed AAV sources plus the empirical corpus source, reusing projection-blending machinery rather than a second implementation. Versioned so every dollar value traces to its inputs. Manual per-source weight overrides supported, since the owner has priors about which sources are good.

### `aav-calibration` - Scoring AAV sources against observed clearing prices

- [ ] **pending**
- **Depends on:** `aav-blending`, `aav-empirical`

AUCTION CRITICAL (R37/R38). Once the corpus is large enough, measure each seed source error against what players actually cleared for, and re-weight on evidence rather than assertion. Expect the empirical source weight to rise as the corpus grows and seed weights to differentiate sharply. GUARD AGAINST CIRCULARITY (R38): mock participants price from the same public AAV we seed from, so early clearing prices echo the seeds rather than independently testing them, and if we bid using our own model the corpus is contaminated with our own output. Record per mock whether our model drove our bidding; treat model-driven mocks as separate evidence; run early mocks observation-only.

### `aav-empirical` - Deriving empirical AAV from the mock corpus

- [ ] **pending**
- **Depends on:** `blind-mocks`, `draft-format-abstraction`, `mock-ingestion`

AUCTION CRITICAL (R37, track B). Every auction mock yields real clearing prices for real players. Aggregate into an AAV source in its own right - unlike published seeds it reflects THIS format and player pool. Also yields observed inflation curves, which is a separate quantity from baseline AAV and feeds auction-inflation directly.

### `aav-source` - Sourcing and importing seed auction values

- [x] **done**
- **Depends on:** `csv-importer`, `fantrax-official-adapter`

AUCTION CRITICAL (R37, track A). Import published AAV from whatever sources the owner finds, through the generic CSV importer rather than a bespoke path. MUST normalise to this league budget pool, team count and roster size before anything downstream uses it (R39) - a $200/12-team/13-spot league produces entirely different dollar values than $100/10-team/10-spot, and a raw import is silently wrong. Capture each source assumed scoring format too; most published AAV targets points leagues or default 9-cat.

**AMENDED 2026-08-22, boundary ruling.** This entry originally said "each source is a row in projection_sources with its own weight". That is superseded: seed AAV lives in its own market-layer tables (`auction_value_sources`, `auction_value_source_inputs`, `auction_value_imports`, `published_auction_values`, `data_layer = 'market'`), reusing the CSV importer's *patterns* and not its tables. Recorded here so nobody re-derives the discarded design from the older sentence.

Three grounds, each independently checkable and each sufficient. (1) `ProjectionSource` carries a CHECK listing projection publishers; Yahoo, FantraxHQ, RotoWire and ESPN publish no projections, so admitting them means widening a projection-layer constraint to hold non-projection publishers. (2) `ingest/projections/profiles.py` `TERMINAL_HEADER_ALIASES` already lists `aav`, `auction value` and `dollar value` - the projection parser was **built to refuse exactly this quantity**. (3) ADR-008 is Accepted and `plan.md` line 305 is explicit: a seeded AAV is market evidence, not a valuation input. This entry predates that ADR being accepted; **the ADR wins**.

Also settled while building, and load-bearing for `aav-blending`:

- **R39 is split.** Disclosure is this item's half and is done: basis is mandatory, non-defaultable, and records per field whether it was *stated by the source* or *inferred by us*. The conversion half - proportional vs surplus-above-reserve scaling produce materially different dollars for the same player - is a Model-gate act and belongs to `auction-values`/`quant`. This item deliberately does not convert.
- **Circularity is a refusal, not a warning** (`hoops_gm.market.independence`), and the rule is *refuse unless lineage is established and disjoint* rather than *refuse when lineage intersects*. Those differ on the case that matters: the first version cleared a source with no recorded lineage at all, because the overlap test examined an empty set and found no overlap. Three verdicts, not two - overlapping lineage refuses (`circular_lineage`), unrecorded lineage refuses (`lineage_unestablished`), established disjoint lineage passes with a `derivation_unestablished` caveat when the method is unknown. Refused as *independent evidence* only: not refused import, not refused display. Proved end-to-end against a real Basketball Monster projection import; the Hashtag arm is not reachable today because `import_projection_csv` refuses an unverified profile and only BBM is verified, so that path refuses Hashtag one step earlier - see `hashtag-projection-profile-verification`.
- **Basketball Monster is disqualified as a benchmark** for as long as BBM projections are in our blend: its auction values are a deterministic z-score transform of the BBM projections we already import. It is registered anyway so the guard has something real to refuse - though note there is no `basketball_monster` *profile*, so the refusal is reachable at the source level where independence is assessed, and not through the import path.
- **`value_kind` is per row, not per source.** Yahoo publishes a projected value and an observed average cost in the same table.
- **`basis_category_count` exists because `ScoringType` cannot express category count.** 8-cat and 9-cat are both `h2h_categories` and are not comparable. FantraxHQ is 8-cat; the owner's league is 9-cat.
- **A duplicated player row is refused, not de-duplicated.** The ingest mechanism is an operator hand-transcribing an HTML table, so a repeated row is routine input rather than a pathological one. Two rows for one player and value kind are two published claims; choosing between them would invent market evidence, so the import fails naming the player and both line numbers.
- **`AuctionValueImport.notes` has no writer.** The column exists and nothing populates it, which is a field a later consumer will assume is populated. Left in place deliberately rather than dropped - `auction-values` is the plausible first writer - but recorded here so its emptiness is a known state rather than a discovery.

See `docs/adapters/published-auction-values.md`.

### `action-protocol` - Defining the automation action protocol

- [ ] **pending**
- **Depends on:** `bridge-overlay`

Typed action schema, backend command queue, userscript-side executor, and result reporting back to the backend.

### `adherence-experiment` - Measuring list adherence across mocks

- [ ] **pending**
- **Depends on:** `blind-mocks`, `list-perturbation`, `mock-ingestion`

Owner will follow the list, so list reliability is the product. Measure adherence per decision (~13 per auction, 10 mocks = ~130 observations). Track overall rate and where deviation clusters by position, price tier and draft stage. Separate systematic deviation (bias to guard against) from situational deviation (real information the model lacks, therefore a feature). Cannot measure whether a deviation was correct - mocks do not play out and scoring against the list own valuation is circular.

### `adr-007-era-figure-population` - Naming which population ADR-007's era figures count

- [ ] **pending**
- **Depends on:** `injury-conversion-cohort-population`

`docs/decisions/ADR-007-availability-in-spine.md:62` records **1.596 / 0.917
`doubtful` per date, short-lead against legacy**, and calls the direction "the
opposite direction from what three of us had jointly predicted". That figure is
cited when arguing the reporting-era boundary bites hardest on the scarcest
status. **It does not state which population it counts.** That omission is the
whole of this item, and it is smaller than it looked for most of 2026-08-23.

**CORRECTED 2026-08-23, `data-engineer`, after an independent `quant` review:
the figures replicate exactly, and the earlier "non-replication" recorded here
was a comparison against a quantity ADR-007 never measured.** They are not
*unresolved* `doubtful` counts. They are the **canonical `doubtful` base rate
per game date** - every canonical `doubtful` observation, direct plus
identity-unresolved, over that era's game dates - and they fall out of the
widened cohort to four significant figures:

```
legacy      53 direct + 2 unresolved =  55 /  60 dates = 0.916667   ADR-007: 0.917
short-lead 164 direct + 2 unresolved = 166 / 104 dates = 1.596154   ADR-007: 1.596
                                       221 / 164 dates = canonical status_counts.doubtful
```

Three things agree at once and that is what makes the reading safe: both ratios
match to 4 s.f. **independently**, and their numerators sum to **221**, the
whole-cohort canonical `doubtful` total, over **164**, the whole-cohort game
date count. A mislabelling that reproduced two ratios *and* closed the total
would be a remarkable coincidence.

**So the previously recorded 0.019 vs 0.033 was not a rival measurement of the
same thing.** It divided `unresolved_identity_exclusions_by_era_and_status`
by `game_dates_by_era` - the *exclusion* rate - and compared it to a base rate.
The "fiftyfold gap" was the ratio between an exclusion count and a population
count, which is not a discrepancy but a definition. **And the "reversal" was
never a reversal:** 2/104 against 2/60 rests on Poisson counts of **2**, where
one row flips the direction and the 95% interval on a count of 2 runs roughly
0.24-7.2. It could not have supported a direction claim in either direction.

**What actually remains open is narrow: nobody has located ADR-007's own
derivation.** The replication is strong enough to make the reading near-certain,
but "the numbers fall out of a later cohort" is not the same as "here is the
computation that produced them", and this item stays `pending` for that reason
alone. Whoever holds the four-week artifact should confirm the population and
add the clause to line 62. **Agents write `Proposed` only; an ADR edit that
changes its recorded meaning is an owner decision.**

**The mundane explanation for the era gap needs no anomaly.** The short-lead
regime files more often and closer to tip, so it captures transient `doubtful`
designations that the hourly regime resolved or never published. A higher
`doubtful` base rate per date under more frequent, later filing is the expected
result, not a surprising one. ADR-007's "opposite direction" alarm is
empirically spurious.

**Two artifacts still carry the withdrawn framing and are not this lane's to
edit.** `cohort_admissibility.py` emits
`direct_outcomes_by_report_era.adr_007_replication_note` containing the string
`DOES NOT REPLICATE HERE`; that string is committed into
`docs/adapters/nba-injury-report-cohort-admissibility-2025-26.json` and pinned
by `test_the_adr_007_figure_does_not_replicate_and_that_is_recorded`
(`backend/tests/test_cohort_admissibility.py:216`). Correcting them means
regenerating the section 2 admissibility evidence, which is the artifact the
unblind decision rests on, so it is filed rather than done here. **The finding
above is the evidence; the edit is mechanical.**

**What is unaffected.** The era **composition** finding is a different mechanism
and stands: development is 68% legacy in direct outcomes while selection and
holdout are 100% short-lead. The claim withdrawn by the coordinator on
2026-08-23 is narrower - that era-dependent *exclusion* concentrates on
`doubtful`. It does not: 2 rows in each era, with unresolved exclusions landing
overwhelmingly on `out` (74 legacy, 45 short-lead).

### `adr-index-consistency-test` - Testing that the decision log's two indexes cannot drift

- [ ] **pending**
- **Depends on:** `ci-pipeline`

`docs/decisions/README.md` was found missing rows for ADR-013 and ADR-014 on
2026-08-21, and `PLAIN-ENGLISH.md` stops at ADR-009 so ADR-010 through ADR-015
are absent from it. Two indexes over one directory, drifting independently,
neither with a test.

The item is a test, not an edit. Editing both today leaves them drifting next
week, and "I checked it by hand this time" is a claim with a one-rebase
half-life — it has now been made by two lanes on two different days.

Assert **both directions**, because only one of them is visible to a human
reading the table:

1. every `docs/decisions/ADR-0NN-*.md` has a row in the `README.md` index;
2. every index row's relative link resolves to a file that exists.

The second is the one a rename breaks and a reader cannot see: a plausible title
beside a broken relative link is indistinguishable from a working one in
rendered Markdown until it is clicked. The ADR-015 row was verified by a
reviewer resolving the link, not by its author reading the table.

Decide as part of the item whether `PLAIN-ENGLISH.md` is in scope. It is a
different kind of index — prose, not a table, and deliberately selective — so
requiring an entry per ADR may be wrong. If it is out of scope, say so in the
file itself, because a reader currently cannot tell "stops at 009 on purpose"
from "stopped at 009 by accident".

Worth recording why this is filed rather than fixed: the two missing rows were
found because a merge conflict happened to land on adjacent lines of that table.
**That is a detector with no coverage guarantee** — it fires only when two lanes
touch the same table in the same window. Two of the three index defects found
that day surfaced by accident.

Gate: Code gate.

### `auction-budget-manager` - Building the auction budget manager

- [ ] **pending**
- **Depends on:** `auction-values`, `draft-tracker`

AUCTION IS THE CONFIRMED FORMAT (2026-08-17) - this is now critical path, not insurance. Max bid computed as budget minus the $1-per-unfilled-slot reserve, recomputed continuously. Budget burn rate tracked against roster construction shape (stars-and-scrubs vs balanced) so the shape is deliberate rather than accidental.

### `auction-inflation` - Building the live auction inflation tracker

- [ ] **pending**
- **Depends on:** `aav-empirical`, `aav-source`, `auction-values`, `draft-tracker`

AUCTION IS THE CONFIRMED FORMAT (2026-08-17) - this is now critical path, not insurance. Track inflation continuously as money leaves the board and restate prices for the remaining pool. If the top tier goes over value, everything after deflates. This is the single largest edge available in an auction and most managers only eyeball it.

### `auction-nomination` - Building the nomination strategy engine

- [ ] **pending**
- **Depends on:** `auction-budget-manager`, `auction-inflation`

AUCTION IS THE CONFIRMED FORMAT (2026-08-17) - this is now critical path, not insurance. Recommend who to nominate and when: drain opponent budgets on players you do not want while they still have money, and surface your targets once opponents are budget-constrained.

### `auction-values` - Deriving auction dollar values

- [ ] **pending**
- **Depends on:** `aav-blending`, `aav-source`, `draft-format-abstraction`, `risk-adjusted-valuation`

AUCTION IS THE CONFIRMED FORMAT (2026-08-17) - this is now critical path, not insurance. Convert risk-adjusted G-score to dollar values via value over replacement scaled to the league total budget pool, accounting for roster size and the minimum-bid reserve.

### `automation-audit` - Building the automation audit log

- [ ] **pending**
- **Depends on:** `action-protocol`

Persist every planned and executed action with timestamp, trigger, inputs, recommendation and outcome. Review UI so runs can be inspected and diffed after the fact.

### `automation-guardrails` - Implementing automation guardrails

- [ ] **pending**
- **Depends on:** `action-protocol`

Mandatory guardrails for all write actions: kill switch (incl. auto-halt on backend disconnect), dry-run default for new action types, roster/position/IR/lock validity precheck, scope caps, confidence floor with escalation, availability-freshness check (never auto-set on stale injury data), and human-paced execution.

### `autonomous-mode` - Implementing opt-in autonomous mode

- [ ] **pending**
- **Depends on:** `supervised-mode`

Explicit per-session opt-in allowing the userscript to action decisions directly - N draft rounds or a lineup set - bounded by every guardrail. Isolated in one swappable module.

### `availability-backtest` - Backtesting the availability model

- [ ] **pending**
- **Depends on:** `availability-model`

Backtest harness scoring the availability model against held-out seasons. Scores calibration explicitly, not just accuracy - a well-calibrated 70% is more useful for lineup decisions than an overconfident model with a better raw hit rate.

### `availability-model` - Building the per-game availability model

- [ ] **pending** - **2026-08-21, `quant`: blocked on the same missing populated database as `injury-status-conversion`, and independently of it.** `p(play)` needs direct non-play labels at scale from `player_participation`, and `docs/models/reliability-metrics.md` already records why the historical `PlayerGameLogs` evidence cannot substitute: it "contains appearances but not complete non-appearance labels, so there is no honest held-out target." Under R35 a missing row is never an absence, so the labels cannot be manufactured from silence. Schedule density is available as a pure-calendar computation; the labels are not. So this item is blocked by two separate routes - its `injury-status-conversion` dependency, and its own need for participation labels - and closing only the first would not unblock it.
- **Depends on:** `injury-status-conversion`, `participation-ledger`, `participation-ledger-population`, `schedule-density`

Per-player p(play) for each scheduled game, conditioned on B2B/density, rest days, road trips, age, career and recent minutes load, injury history and body part recurrence, current report status (via its conversion rate), and team playoff/tanking situation. Aggregates to expected games over any window (RoS, fantasy week, playoff weeks). Persists driver features for explainability.

### `baseline-model` - Building an in-house projection model

- [ ] **pending**
- **Depends on:** `nba-stats-ingest`, `projection-blending`

Own per-game production model from historical logs, accounting for minutes,
usage and role. Exposed as another source inside the blending layer. Its
experiments must follow the
[`projection experiment sequestration protocol`](governance/projection-experiment-protocol.md):
the model worker receives only independently released immutable packages,
freezes the experiment before held-out outcomes are unblinded, and may never use
mock outcomes as production or availability evidence.

**Scope narrowed, 2026-08-22 —
[`docs/models/projection-strategy.md`](models/projection-strategy.md).** Measured
on ten seasons of game logs, a naive carry-forward predicts season-total points
better than a careful rate × minutes × games decomposition (r² 0.611 vs 0.576),
because games-played error swamps everything downstream of it, and a naive
Marcel already reaches r² **0.50–0.89** on per-36 rates — 0.71–0.89 on the volume
categories, with steals at 0.50 and turnovers at 0.66 as the weak tail. **This
should not be built as a production source before draft day.** Build the
Marcel/SPS baseline only as a measuring stick — to quantify how much of any
projection set is reproducible from public box scores — and ship consensus rates
**and consensus minutes** fused with our own games-played number instead. The
unblocked work with the larger payoff is `participation-ledger-population`.

**Amended 2026-08-22 —
[`docs/models/consensus-reproducibility.md`](models/consensus-reproducibility.md).**
The measuring stick was built and run against a commercial projection set.
Consensus **rates** are largely reproducible from public box scores (r²
0.726–0.947 across the eleven scored rate categories; "per game" there is a unit,
not a scope), but consensus **minutes** amplify rather than regress relative to a
naive baseline, which is information no box score contains — so consume those
too. **Their `games` column agrees at only r² 0.284–0.504 and carries 2.5
effective levels in the rotation cohort against minutes' 14.9** — that, not the
minutes result, is why the ADR-002 seam falls at **games, not minutes**. Amended
2026-08-23: the three figures must be quoted together, because quoting the rates
range alone next to a seam claim reads as a games claim, and did.

### `behavioural-baseline` - Modelling the owner own drafting tendencies

- [ ] **pending**
- **Depends on:** `adherence-experiment`, `blind-mocks`, `mock-ingestion`

From the blind mock captures, identify systematic tendencies worth flagging live: overpaying at particular positions, chasing after a loss, freezing, finishing with budget unspent, neglecting a category until too late. A tool that says you are bidding 8 dollars over your own model on centers, and you did this in three of the last five mocks, is more useful than one that only prices players. Requires enough captures to distinguish tendency from noise.

### `bias-guardrails` - Warning on known bias patterns during the draft

- [ ] **pending**
- **Depends on:** `adherence-experiment`, `behavioural-baseline`, `overlay-auction-panel`

Once adherence data shows systematic tendencies, surface them live in the overlay - for example that the current bid is well over list on a position the owner has consistently overpaid for across prior mocks. Requires enough captures to distinguish tendency from noise. Read-only advisory, not a block.

### `blend-override-persistence` - Persisting manual projection overrides safely

- [ ] **pending**
- **Depends on:** `blend-recipe-persistence`, `player-identity`

Split out of `blend-recipe-persistence` by ADR-015 clause 5, because overrides
are the only recipe component that carries a decision-bearing number and the
only one whose key nothing pins. A `ManualProjectionOverride` names a
`player_id`; `players.id` is a surrogate with no natural key and
`normalized_name` is documented as deliberately non-unique *because* collisions
must stay resolvable — so storing the observed name and refusing on mismatch is
blindest on exactly the population that generates the risk. The identity remedy
must therefore not be the name: use `birth_date`, or the `player_external_ids`
row identity observed at authoring.

Two further hazards that only appear once overrides are durable, both of which
this item must close before it is done:

- **A persisted override is indistinguishable from a durability-shaded rate.**
  "His true per-game scoring is 24.1" and "I'll shade him to 22 because he'll
  only play 55 games" are both `points_per_game`, and `expected-games` would
  then multiply the second by our own `p(play)` — availability counted twice,
  R41's mechanism with the owner's own hand as the aggregator, after which no
  query separates "he is good" from "he is durable" for that player. The remedy
  is definitional and belongs in the model card: an override replaces a per-game
  rate **at normal health and role**, and no schema test can detect one that
  does not.
- **A bare ratio can reach the output on the hydration path.** On the read path
  `blend_projections` takes `values` verbatim and the only re-check is
  `_validate_shooting_values`, which iterates `fg`/`fg3`/`ft` and ignores field
  names it does not recognise. The check that an override supplies exactly the
  category's `production_fields` lives in `_validate_manual_overrides`, which is
  definition-path only. A ratio category on assists or turnovers is expressible,
  so a persisted single bare ratio would flow untouched into the blended output
  — the naive-percentage bug arriving through the one door nobody was watching.

Refusal must be a **read refusal**, typed and retryable per ADR-014. Dropping
the override and blending anyway fails unsafe: the screen would show an
uncorrected number the owner believes is corrected.

Gate: **Code gate and Model gate** — the model card's Inputs section currently
describes overrides as transient values, and that claim changes here.

### `blend-recipe-persistence` - Persisting the blend recipe so the owner's weights survive a restart

- [ ] **pending**
- **Depends on:** `csv-importer`, `projection-blending`

ADR-015. `projection-blending` is complete but not durable: `BlendCatalog` is a
caller-owned in-memory value, so owner-authored per-category weights die at
process exit and there is no persistent "our number" to put beside a source's.
Persist the **recipe** — selected sources, per-category weights, target scoring
profile — and keep the **binding** to specific `ReleasedProjectionImport`
records transient, recomputing the blend on read. Persisting `BlendProfile`
whole would weld both lifetimes into a migration, and the failure that produces
is a fresh Basketball Monster CSV on draft morning making the owner's weights
unusable rather than stale. Supersedes `plan.md:517`'s `blend_profiles`; its
`blended_projections` stays deferred.

Gate: **Code gate and Model gate.** The Model gate is satisfied by a revision of
`docs/models/projection-blending.md` and an explicit inputs-versioning
statement — **not** by a backtest or a calibration table. `gates.md` names
`blending` in the Model gate's applies-to list, and no gate may be waived by the
agent whose work it applies to, so the earlier Code-gate-only argument was wrong
even though its premises were right: version 1 does fit no parameters and there
is no held-out experiment to run, which is why the backtest and calibration
bullets are inapplicable rather than skipped. The bullets that do bite are
"version the output — every stored number records the model version and inputs
that produced it", which the recipe *is* the inputs half of, and the model
card's own "not durable across process restart" failure mode, which this item
retires. The Adapter gate does not apply — no external source is called. The
*fitted-model* half of the Model gate attaches the moment `weight_basis` widens
past `user_configured`, which is why criterion 9 makes that widening a
migration.

Acceptance criteria, each falsifiable:

1. A recipe defined, activated and read back **after a process restart** yields
   a byte-identical `content_sha256` and an identical `BlendResult` fingerprint.
2. Importing a **newer** CSV for a selected source leaves the recipe active and
   readable, and the blend against the new import succeeds without the owner
   re-authoring weights. This is the criterion that fails if anyone persists the
   binding.
3. Re-ingesting **byte-identical league settings** leaves the recipe active and
   blendable. `derive_scoring_profile` mints a new profile version for a new
   snapshot row even when content is unchanged, and activation repoints, so a
   recipe storing `scoring_profile_id` dies here. Store `(league_id, name)` plus
   a category-content fingerprint and re-resolve at read.
4. A `BlendProfile` hydrated from the tables and passed straight to
   `blend_projections` is **re-validated**, not trusted.
   `_validate_source_selection`, `_normalize_category_weights` and the
   `weight_basis` layer-purity raise each have exactly one call site today —
   inside `define_blend_profile` — and the in-memory registry identity check is
   what currently guarantees they ran. A table replaces that check. Driven by
   constructing a profile that would fail each validator and asserting the read
   path refuses it.
5. `blended_projections` is **still** in `test_portability.py`'s `not_yet` set
   after this lands, and no table holds a blended per-game value. `not_yet`
   holds `blend_profiles` and `blended_projections` on adjacent lines; only the
   first may be removed, and the second is the assertion that no output is
   stored.
6. A schema test asserts the recipe tables carry no games-played,
   expected-games, availability or seasonal-total column, no column derived by
   multiplying a rate by a count, and **no cohort or player-filter column** —
   the last because filtering the pool by durability moves every downstream
   z-score through its denominator (ADR-002).
7. At most one active recipe per `(league_id, name)` is enforced **by the
   database**, demonstrated by a failing insert, on both SQLite and PostgreSQL —
   *and* two differently-named recipes can be active in one league at once,
   demonstrated by a succeeding insert. `BlendCatalog.active` is keyed on
   `(league_id, name)`, so `LeagueScoringProfile`'s bare
   `UniqueConstraint(active_league_id)` is the **wrong** constraint here and
   would silently narrow existing behaviour; use
   `UniqueConstraint(active_league_id, name)` plus the companion
   `CheckConstraint(active_league_id IS NULL OR active_league_id = league_id)`.
   A partial index needs `sqlite_where=`/`postgresql_where=`, which
   `test_portability.py`'s dialect-branch pattern matches — that guard walks
   `src/hoops_gm` only, so it will **not** catch the same keyword in the
   migration.
8. The recipe stores each source as its `ExternalSource` enum value, not
   `projection_sources.id`; a re-seed that changes that row's id leaves the
   recipe resolvable.
9. `weight_basis` is constrained to `user_configured` **by the database**, so
   widening it is a migration rather than an `UPDATE`. `portable_enum` is
   VARCHAR on both dialects and `WeightBasis` already carries
   `learned_accuracy`, `market_calibrated` and `mock_calibrated`.
10. Redefining an identical recipe after deactivation reproduces the same
    `content_sha256` while producing a new `version`, pinning that version is
    history-dependent and the digest is not.

Manual overrides are **out of scope** — see `blend-override-persistence`.

Each new guard needs a mutation that reproduces the failure it guards against,
asserted green before mutating and asserted to have actually applied. `quant`
owns the recipe/binding split in `projections/blending.py` and the model-card
update; `backend` owns the tables, migration and any route — the same seam
already recorded for the scoring profile in `ownership.md`.

### `bridge-overlay` - Building the in-page recommendation overlay

- [ ] **pending**
- **Depends on:** `punt-builds`, `userscript-foundation`

Shadow-DOM overlay rendering hoops-gm recommendations directly on Fantrax pages, so decisions surface where they are made.

### `openapi-recorded-drift-check` - Giving the recorded OpenAPI document a capture script and a drift check

- [ ] **pending**
- **Depends on:** `backend-skeleton`, `frontend-skeleton`

**`frontend/src/test/openapi.recorded.json` silently stopped describing the API
on 2026-08-28 and nothing failed.** The only guard on it,
`openapiEnums.recorded.test.ts`, partitions **enums** — and a newly added boolean
property is not an enum, so the recording drifted with every check green. Its own
test docstring already names manual re-recording as a real limit.

**The comparison that makes this a gap rather than a preference:** the draft
fixtures have both halves — `scripts/capture_draft_fixtures.py` regenerates them
and its `--check` mode fails on drift, with a `_refusal()` helper that raises
when a case stops refusing so a fixture cannot quietly become a lie. The
OpenAPI recording has neither half. Two schema-touching units landed in one week
(#120, #122) and only the second was noticed, by hand.

**Acceptance:** a script that flattens both the served `app.openapi()` and the
committed file to `dotted.path[index]` → leaf-value maps and reports **added /
removed / changed** as three sorted key lists, plus a `--check` mode wired into
CI. The re-recorder must **round-trip the committed file first and refuse to
write if re-serialising does not reproduce it byte for byte**, so a reformat
cannot be committed as though it were a content change.

**Method already established, and it worked once.** The lane that found this
wrote exactly that checker as a one-shot, used it to show its own change was
**3 added / 0 removed / 0 changed, all three its own** — which is what made
re-recording defensible rather than a blind snapshot absorbing inherited drift —
and then deleted it. Roughly twenty lines. **The procedure survived only because
it was asked for before that session was archived**, which is the argument for
the pre-archive question rather than for this item.

### `userscript-served-version-check` - Failing when the served bridge build is older than the source

- [ ] **pending**
- **Depends on:** `userscript-foundation`

**Found live on 2026-08-28.** The owner asked whether his browser showing
`0.5.0` and "no update available" was correct. It was correct and it was wrong:
`userscript/package.json` and its lock both declared **0.5.1**, while
`userscript/dist/hoops-gm.user.js` — the exact bytes
`GET /bridge/userscript.user.js` serves — still said **0.5.0** and was built on
**18 August**, ten days earlier. Someone bumped the version and never ran
`npm run build`, so he had been running a bridge that predated the
*"Harden bridge capture durability"* work, on the code path he is about to
exercise in a mock draft.

**Nothing could have told him.** `dist/` is gitignored, so CI never sees the
artifact and cannot compare it to the source that declares it. `build.mjs`
already refuses when `package.json` and `package-lock.json` disagree, which is
the adjacent check — but **nothing catches "bumped and never built"**, and the
auto-update path then works perfectly and faithfully serves a stale file.
Tampermonkey reports "no update available" because that is literally true of the
bytes it fetched.

**Acceptance:** a check that fails when the `@version` in the built artifact does
not match `package.json`, plus a route- or startup-level assertion so the backend
refuses to serve — or loudly marks — a build older than the source it declares.
The first half is cheap and can run in CI against a build step; the second is the
half that helps on draft day, because the person who needs to know is looking at
a browser, not at CI.

**This is the third distinct way the bridge fails silently**, alongside an
unpaired script and a refused envelope, and all three look identical from the
Fantrax page: nothing happens. See `bridge-status-strip`, which surfaces the
other two.

### `draft-board-dom-parser` - Reading the draft board from the rendered page, because nothing else can

- [x] **done**
- **Depends on:** `bridge-capture`, `draft-tracker-bridge-feed`

**This became the critical path to 4 October on 2026-08-28, when both automatic
alternatives were falsified within four hours of each other.**

1. **The bridge cannot read `/fxpa/req`.** Service-worker originated; no browser
   API or Tampermonkey grant can observe it. 49 of 49 live payloads confirm, and
   Cache Storage — the last escape route — was verified absent on a live draft
   room.
2. **The official API returns nothing.** `getDraftPicks` on a *completed*
   216-pick draft answered `{"currentDraftPicks":[]}` — HTTP 200, 24 bytes,
   unauthenticated, no error. See `official-getdraftpicks-live-verification`.

So the only remaining source of live pick data is the **rendered DOM**, which the
userscript already captures automatically as `rendered-view` snapshots. That is
capture path 2, and it is now load-bearing rather than a *"lower-confidence
fallback"* as `capture.js:71-74` describes it.

**The evidence to build against already exists and does not require another live
draft.** 49 snapshots spanning an entire 18-round draft — 174-250 KB each,
including the board at every stage — are held outside this repository because
they carry the owner's league. Whoever takes this must ask him for them; do not
go looking, and do not commit them.

**What is already known about the parse, from a first pass:**

- The snapshots contain team names and player names as text.
- A naive regex for board cells finds nothing **only because of a leading
  space**: `>12-7<` matches zero times and `> 12-7<` matches once, because
  Angular renders `<mark class="ng-star-inserted"> 12-7</mark>`. An earlier
  version of this item said *"Angular's markup does not expose the coordinates
  that way"* and that was **false** — the first half was a measurement, the
  second was an inference presented as observation, and it was written into a
  lane brief marked do-not-re-derive. The lane measured it anyway and corrected
  it. Coordinates are exposed exactly there.
- Console logging on the live page shows the client's own model, which is a
  guide to what the DOM must encode: `round`, `pickNumberTemp`, `overallPick`,
  `draftTeamId`, `cellTeamId`, `scorerId`. **`pickNumber` is `undefined` on every
  line** — a parser that trusts it reads nothing.
- `overallPick` and `pickNumberTemp` are independent: one monotonic to 216, one
  resetting each round.

**Acceptance:** given a captured snapshot, produce the picks it contains —
seat, player, round, overall — and **verify the count against ground truth the
owner watched happen**. A parser that returns a plausible number is worthless
here; the owner's Q12 answer is *"shows me picks that already happened or misses
one"*, and a miscount produces no error code.

**Two hazards to design against rather than discover:**

- **Markup drift.** Fantrax ships a new Angular build whenever they like, and a
  selector-based parser breaks silently. The parse must **refuse loudly** when it
  cannot find what it expects, never return a short list. Nothing in the DOM
  announces its own version, so the refusal is the only signal available.
- **Snapshot staleness under tab throttling.** Snapshots fire on
  `MutationObserver` and `setTimeout`, both throttled in hidden tabs. A parse is
  only as current as its snapshot, and the strip in `bridge-status-strip` is
  where that must be visible.

**Landed at `backend/src/hoops_gm/draft/feed/board_dom.py`.** The board is
recoverable and the first pass's central claim about it was wrong: Angular does
render the coordinates, as `<mark> 12-7</mark>`, and the regex that found zero
searched for `>12-7<` without the leading space. Real DOM work was still
required, but for a different reason - the coordinate says round and
pick-within-round, never the seat, which is the column the cell sits in.

**Why the count can be trusted.** Fantrax renders the *whole* grid from the
moment the room loads: all 216 cells carry their coordinate before a single
pick is made, verified across 42 board-bearing captures where the cell count was
216 in every one while picks climbed 0 -> 216. The board is **not virtualised**,
so the parse can require the coordinates to cover `rounds x seats` exactly once
and a missing cell becomes evidence of damage rather than of scrolling. Driven
against all 49 real captures: 42 parsed, 7 refused - and the 7 are exactly the
snapshots of other pages - with 0 disagreements against an independent count.

**The arithmetic is corroborated from outside the parser.** The chat pane
announces each pick as `drafted - 16-4 [184]`, which is Fantrax's own overall
number computed in a different subtree. `(round - 1) * seats + pick_in_round`
agreed with it **749 times out of 749**.

**Three findings that change other lanes:**

1. **A 250,000-character snapshot is not large enough to be comfortable.** The
   finished 216-pick board occupied 208 KB of `AUTO_SNAPSHOT_MAX_CHARS`, leaving
   42 KB. 22 of 42 board-bearing captures were truncated; every one happened to
   be cut past the board. A longer league loses the tail, and the picks that
   survive the cut look exactly like a complete board. See
   `bridge-snapshot-budget`.
2. **Manual export is not capped.** The three owner-triggered exports ran to
   727 KB. On draft day it is the only capture path that cannot lose the board.
3. **A seat's displayed name is not an identity.** Four seats changed name
   mid-session as owners joined and Fantrax's `Mock Drafter N` placeholder was
   replaced. The DOM carries no team id at all - `draftTeamId` and `cellTeamId`
   are console vocabulary and appear nowhere in the markup - so the column
   ordinal is the only stable key there is.

**Not wired into the feed.** `recognise_bridge_payload` still does not read a
snapshot's contents. Turning a board reading into an `ObservedInstant` means
deciding its transport, its provenance and what it means for two readings of the
same board to corroborate each other, and that is a contract question rather
than a parsing one. See `draft-board-feed-integration`.

### `bridge-snapshot-budget` - The snapshot cap is one league size away from eating the board

- [x] **done**
- **Depends on:** `draft-board-dom-parser`

`AUTO_SNAPSHOT_MAX_CHARS` is 250,000 in `userscript/src/capture.js`. On the
recorded 12-team, 18-round football draft the finished board rendered to
**208 KB**, so the cut landed 42 KB past it and nothing was lost. That margin is
the whole safety story, and it was not designed - it is where the number
happened to fall.

**22 of the 42 board-bearing captures were truncated.** The cap is reached
routinely, not exceptionally.

**Why this is not merely a bigger-number problem.** `buildDomSnapshotHtml` builds the
payload as `html.slice(0, limit)` followed by the marker, so the cut lands
mid-tag and the marker is folded into an attribute value rather than parsed as a
comment. Every truncated capture on record would read as untruncated to a
comment-based check; `board_dom.py` scans the raw string instead. Raising the
cap without fixing that leaves the same blind spot at a higher number.

**The board is also not first in the document.** It is preceded by the navbar
and status bar and followed by the chat pane, so what gets cut depends on
layout, not on how much of it matters.

**Acceptance:** either the cap accommodates the owner's real league with
evidence of the margin, or the snapshot is scoped to the board subtree rather
than the page, or truncation is reported to the backend as a first-class field
rather than inferred from a marker. `board_dom.py` already refuses a board cut
mid-grid, so this is about not reaching that state on draft night.

**Landed in `userscript/src/capture.js`.** Automatic captures on Fantrax draft
routes now clone only `.league-draft-board`, the smallest observed subtree that
contains both parser-required anchors: `.league-draft-board__header` and
`.league-draft-board__body`. Navbar/status markup before the board no longer
spends the unchanged 250,000-character cap. Optional chat corroboration is
appended only when it fits after the complete board, so it can never cut the
grid; when it also fits, omission carries a distinct auxiliary marker so the
parser does not mislabel later board drift as truncation. A near-cap board wins
over even that metadata. The detached board clone is refused before transport
if either anchor is absent or the board itself is over budget, and the refusal
reaches the visible bridge status strip. Non-draft snapshots still use the
broader page roots, but truncation now backs up to a complete tag while tracking
comment and quoted-attribute state, so the marker cannot land inside an
attribute. The backend accepts the new terminal comment and the recorded legacy
mid-attribute marker, but visible marker words cannot spoof truncation. A
board-build refusal remains visible until a safe `rendered-view` delivery or
duplicate clears it; unrelated manual/RPC success cannot hide the automatic
board failure. The served userscript version is bumped to 0.5.3 so an installed
0.5.2 can actually receive these fixes.

Focused userscript tests reproduce the prior mid-attribute marker hazard, prove
unrelated page markup is excluded, prove an over-budget board is never sent
partially, and prove a missing parser header is loud. This closes the capture
budget defect demonstrated by the recorded football snake board; it establishes
nothing about the owner's NBA auction DOM, which has not been observed.

### `draft-board-feed-integration` - Joining a board reading to the draft feed

- [ ] **pending**
- **Depends on:** `draft-board-dom-parser`

`board_dom.parse_draft_board` returns picks; `draft/feed/` records
`ObservedInstant`s with provenance and reconciles them. Nothing joins the two,
deliberately, because the join is a contract decision and not a parsing one.

**The questions it has to answer**, none of which the parser is entitled to
decide on its own:

- **What is a board reading's `transport`?** `SourceTransport` distinguishes
  bridge from official. A rendered snapshot is the bridge, but it is not the RPC
  body, and `recognise.py` exists partly to keep those apart.
- **What is its `artifact_key`?** For an RPC capture that is the userscript's
  `dedupe_key`. Two snapshots taken a minute apart with no pick in between are
  the *same* board seen twice and must not read as corroboration; two different
  captures of the same pick from different paths should.
- **Does a board reading corroborate an RPC reading?** They cannot currently
  disagree, because there are no RPC readings. If `getDraftPicks` ever starts
  answering, they will.
- **What happens when a later snapshot holds fewer picks than an earlier one?**
  It should not, but SPA navigation, a re-render and a throttled tab are all
  ways it might, and "the board went backwards" needs a defined answer.

**All four are answered by ADR-020 (2026-08-28, `Proposed`).** Read it rather
than this summary; it records why one of its own reasons is false. In short:
transport stays `BRIDGE_CAPTURE` with `board_dom` in `recogniser`; `artifact_key`
digests the parsed board, not the HTML; liveness comes from `freshness_of`'s
existing `contact_at`; a newer board that has lost a pick is stored and published
as `board_regression` and retracts nothing.

**Two acceptance criteria that exist because the ADR asserts them and nothing
else would carry them:**

- The divergence in ADR-020 decision 2 **must be written into
  `observations.py`'s `InstantProvenance` docstring**, which today says
  `artifact_key` "identifies the **bytes**" without qualification. An ADR that
  contradicts a docstring and leaves the docstring standing has produced the
  false-guarantee shape this repository keeps finding.
- A test must **fail on the old behaviour**, not merely pass on the new: two
  snapshots of one unchanged board, differing in HTML, must produce one
  observation and one `artifact_key`. Byte-keying passes any test that only
  asserts the new code works.
- **Pin column-major document order against
  `backend/tests/fixtures/fantrax_draft_board_complete.html`.** ADR-020's
  amendment rests on it and it is currently held by nothing: coordinate marks run
  `1-1, 2-12, 3-1 … 18-12` for seat 1 before `1-2` appears, and column *i* begins
  with `1-i`. Both were measured across all 42 board-bearing captures and both
  reproduce from the committed fixture, so **no private capture is needed**.
- **Pin "the header precedes the body in document order" as a *separate*
  property.** It is not the same claim as column-major, and it is the one
  actually doing the work: `seat_column_mismatch` at `board_dom.py:462` refuses
  before the cover check at `:554` is ever reached, which is why
  `coordinate_grid_incomplete` fired **0 times in 771 in-board cuts** while
  `seat_column_mismatch` fired 705. A redesign could preserve either property and
  break the other. **A test asserting only "it refuses" passes while pinning the
  wrong mechanism**, and the mechanism is what the next reader relies on.

### `append-only-docs-line-ending-check` - Failing when an append introduces CRLF into an LF file

- [ ] **pending**
- **Depends on:** `frontend-skeleton`

**Observed 2026-08-28, in a merge the coordinator performed.** `docs/handoff.md`
went from **0 CRLF to 149** in one merge. Measured blob-to-blob: `39ea327` had
2,006,082 bytes and zero CRLF; `fb35201` had 2,015,243 bytes and 149. Every other
byte in that 2 MB file is LF.

**Every gate passed.** `check_doc_terminators.py` reads the file and asserts only
that it **ends** with a newline (`data.endswith(b"\n")`, line 87) — it says
nothing about the line endings inside. `check_append_only.py` asserts byte-prefix
containment against the merge-base, and CRLF in the *appended* region leaves the
prefix untouched, so containment holds. Neither is wrong; **both have a domain
narrower than the hazard**, which is `c350` in yet another place.

**Why it matters rather than being cosmetic.** `predict_union.py` counts entries
with `^## \d{4}-\d{2}-\d{2}` anchored at a line start, and the trailing-newline
gate exists because a welded heading is *"present, uncounted, and completely
unremarkable in a diff"*. Mixed line endings are the same hazard by a different
route: they are invisible in a rendered diff, they propagate to the next append,
and this file is read by counting tools.

**The consequence that makes it urgent rather than tidy-up.** These documents are
append-only. **A defect in appended bytes may not be repairable**, because the
repair would alter bytes the containment check requires to survive. Whether it is
actually forbidden here is **not established** — a worktree test was
inconclusive, because `check_append_only.py` reads committed blobs and never
examined the uncommitted change. Establish that first: if normalisation is
permitted, do it once and add the check; if it is not, the check is the *only*
remedy and every future append inherits the mixed file.

**Acceptance:** the existing terminator gate grows a second assertion — an
append-only document contains no CRLF — with the same `CHECKED` tuple, so it
covers `handoff.md`, `backlog.md` and `coordinator-register.md` together. Prove
it by injection: add a CRLF, watch the gate name the file and go red, remove it,
watch it pass. A gate that cannot be made to fail is worth nothing, and this one
already shipped with a coverage hole once — the register was missing from
`CHECKED` from the day the script was written until 2026-08-28.

**Not the fault of the lane that introduced it.** It was writing on Windows,
where `Add-Content` and most editors default to CRLF, and nothing told it
otherwise. That is precisely the argument for a mechanical check rather than a
convention.

**Read the bytes, not a pipeline's rendering of them — this bit the coordinator
on 2026-08-28 while checking exactly this defect.** Counting CR with`git cat-file blob <sha>:docs/handoff.md | Out-String` reported **31,400 before
and 31,481 after** an append that in fact introduced **zero** CR. PowerShell
normalises line endings crossing the pipeline, so the instrument was rewriting
the sample it measured. The byte-faithful count — redirect through
`cmd.exe`, then `[System.IO.File]::ReadAllBytes` — is **149 before and 149
after**. Had the first reading been believed, it would have looked like an
81-line regression and provoked a "repair" of bytes that were already correct, in
an append-only file where that repair breaks containment.

So the check must read blobs in binary and must be **proved against a known
non-zero case**: inject a CRLF, confirm the count moves by exactly the number
injected. A counter that cannot be shown to move is not evidence that nothing
moved. Note also that `check_append_only.py` already reports
`CR in base blob` / `CR in head blob` correctly, so it is the working reference
implementation to copy rather than a second thing to write.

**Done on 2026-08-28, in `check_append_only.py` rather than the terminator
gate.** The two counts were already printed and never compared; the gate now
fails when `head_cr > base_cr`, with a seeded-CRLF control asserting the counter
moves. Proved both directions on a throwaway branch: clean `main` passes with
`CR added by HEAD: 0`, and an injected three-CR append reports exactly 3 and
exits 1.

**It is a delta, not "contains no CRLF", and that is deliberate.**
`docs/handoff.md` already carries 149 and the file is append-only, so a
zero-tolerance gate would be red on `main` from the day it landed — and a gate
that is red on `main` is one everybody learns to route around. What remains open
is only the original 149, not the mechanism.

**A second instance landed the same day, from the same lane as the first**, and
was caught in review rather than by CI because the gate did not exist yet: PR
#130's handoff entry carried **171 new CR** with containment intact and every
gate green.

**Still open: there is no `.gitattributes` in this repository at all.** Line
ending handling therefore depends entirely on each machine's `core.autocrlf`,
which is an unstated per-machine dependency and the most likely reason CRLF
reaches blobs here at all. **Adding `* text=auto eol=lf` is not a safe fix and
must not be done casually** — git would then want to normalise the existing 149
on the next commit touching `docs/handoff.md`, which alters bytes
`check_append_only.py` requires to survive and converts a cosmetic defect into a
blocking one. Any `.gitattributes` must exclude the append-only documents
explicitly. **This mechanism is reasoned, not tested**; establish it on a
throwaway branch before acting on it.

### `board-dimensions-per-draft` - A board is only short-and-clean if nothing remembers how big it was

- [x] **done**
- **Depends on:** `draft-board-dom-parser`, `source-board-evidence-api`

`board_dom.py:475-484` derives `rounds` from the rendered cell count, so a
**uniformly short** board is rectangular, has a complete coordinate cover, and
parses clean with `is_complete=True`. Measured: 12 columns cut to 14 cells
reports **168 picks of 216 as a finished 12x14 draft**.

Nothing structural catches it. The chat cross-check does - and the chat pane is
absent on the `/draft/board` route, where captures 0043-0047 hold 157-205 picks
and no chat at all. The owner navigated to that route mid-draft.

**Not currently reachable**, because the board is column-major and a byte cut
drops whole columns, which `seat_column_mismatch` refuses. The point is that the
safety comes from Fantrax's *layout* rather than from our *check*, and only one
of those is ours. A virtualised board, a partial re-render, or a redesign
separates them.

**Acceptance:** board dimensions are a property of the draft, not of the
snapshot. Once an 18-round board has been observed for a draft, a 14-round
reading refuses. A parser sees one snapshot and cannot know 14 is wrong, so this
is a feed-level check. Also rename or document `is_complete`: it means "every
rendered cell is filled", not "the draft is over".

### `capture-corpus-verifier` - The headline parser figure can be re-derived, or it is a claim

- [ ] **pending**
- **Depends on:** `draft-board-dom-parser`

`docs/handoff.md` records the board parser as **42 parsed / 7 refused / 0
mismatches over 49 real captures**, and that number is currently re-derivable by
exactly one thing: a scratch script in a session directory that dies with the
session. ADR-019's amendment already settles what that means - *a derived number
with no tool that re-derives it from the thing it describes is a claim, not a
measurement* - and this is the most load-bearing number the draft board has.

The lane's `verify_real.py` is the tool. It drives the parser over every capture
and cross-checks each against an independently written count **and** against the
chat pane's own arithmetic, which is the part that makes it evidence rather than
the parser agreeing with itself. Rescued to
`hoops-gm-private/lane-artifacts/2026-08-28-draft-board-dom-parser/`.

**Acceptance:** committed under `scripts/` taking `--captures-dir`, following the
same convention as the schedule seed's `--fixtures-dir` - tool in the repository,
data outside it, no vendor payload ever committed. It cannot run in CI and should
not pretend to; it is a command a human runs against a corpus, and it prints the
three figures plus any disagreement by capture name. The same run should also
report the guard split on a truncation sweep, because ADR-020's amendment now
rests on 705/61/0 and nothing re-derives that either.

### `diff-scanned-against-real-values` - Grep a branch's own diff for values only a real capture could contain

- [ ] **pending**
- **Depends on:** `draft-board-dom-parser`

`check_no_secrets.py` passes on a league id and is right to - a league id is not a
credential. But `b2gyornvms4606iv` is on `main` in two append-only files, and
those files may not be repairable at all. The rule that was broken exists only as
an instruction to lanes, and **no gate implements it**.

The lane's `grep_diff_for_real_data.py` inverts the usual direction: instead of
matching patterns that look secret, it reads **actual values out of the private
capture corpus** - league ids, team ids, scorer ids, player names - and greps
every file the branch touches for them. It found a real scorer id sitting in a
docstring that two separate fixture scanners were structurally blind to, because
they scanned fixtures and the value was in prose.

**Acceptance:** committed under `scripts/`, taking `--captures-dir` and a diff
range, defaulting to `origin/main...HEAD`. **Position-aware matching is
mandatory** - the lane recorded that naive substring matching false-positives on
`NE`, because DST scorer names are two-letter pro-team codes that occur inside
ordinary words. Prove it by injection against a known-clean branch: plant one
real id, watch it named, remove it, watch it pass. Whether this becomes a gate is
`coordinator-rules-distillation`'s call, not this item's; land the tool first.

### `field-name-guess-audit` - Auditing every field name guessed from a format rather than read from one
- [ ] **pending**
- **Depends on:** `draft-tracker-bridge-feed`, `fantrax-official-adapter`

**Three instances found on 2026-08-28, all in one afternoon, all invisible to a
green test suite:**

| where | guessed | actual |
|---|---|---|
| `recognise.py` `FIELD_ALIASES["team_external_id"]` | `teamId`, `fantasyTeamId`, `franchiseId`, `teamID` | **`draftTeamId`**, `cellTeamId` |
| `parsers.py:365` | `payload.get("draftPicks") or payload.get("picks")` | **`currentDraftPicks`** |
| *(control)* `FIELD_ALIASES["player_external_id"]` | `playerId`, **`scorerId`**, `fantasyPlayerId` | `scorerId` — **correct** |

The control matters: this is not "all guesses are wrong". It is that **a guess
made from reading a format is right at about the rate you would expect from
reading a format**, and nothing in this repository distinguishes a verified name
from a guessed one at the point of use.

**Why tests cannot catch this class.** Every fixture behind these names was
constructed from the same reading that produced the names. A contract test then
proves the parser agrees with our assumption, which is exactly what ADR-006
rejects. `docs/adapters/fantrax-private.md:31-38` already says this in prose
about parsers; the finding is that it applies equally to *field names inside*
parsers that do exist.

**Acceptance:** an inventory of every externally-sourced field name in
`ingest/` and `draft/feed/`, each marked **verified against a real payload** or
**guessed**, with the verified ones naming the artifact that verified them. Then
a mechanical check that a name cannot silently move from one category to the
other — the shape `fingerprint_closure.py` uses for a different question.

**Deliberately not proposed as a fifth gate.** `coordinator-rules-distillation`
owns whether register rules become gates, and adding one on the strength of a
single afternoon is the over-correction this project's own register warns about.
An inventory that makes the distinction *visible* is the smaller, reversible
step, and it is enough to stop the next instance shipping unnoticed.

### `official-getdraftpicks-live-verification` - Establishing whether the official API can carry the draft board

- [x] **done** — *smoked live 2026-08-28. **The answer is no.** The endpoint is
  reachable and unauthenticated, and it returned an empty list for a completed
  216-pick draft.*
- **Depends on:** `fantrax-official-adapter`

**Result, in the form that lets someone disprove it.** `GET /fxea/general/getDraftPicks?leagueId=b2gyornvms4606iv`,
no `userSecretId`, returned **HTTP 200**, `Content-Type: text/plain`, **24
bytes**:

```json
{"currentDraftPicks":[]}
```

`sha256:b5811c858f69d6f11a9f6e0d5a878d9622edd21fe1d6f202a9d2bf5cfb915fca`,
observed at `2026-08-28T19:01:40.124943+00:00`, recorded byte-exact as
`backend/tests/fixtures/fantrax_getdraftpicks_completed_snake_empty.json`. The
league held a **completed 18-round, 12-team snake draft** — 216 selections. The
endpoint reported none of them. One request, no retry, no other league id, no
parameter adjustment.

**Which failure class this is.** Not authentication: no 401/403, no error
envelope, and the read succeeded with only a non-secret `leagueId`, so **no owner
credentials decision is required** and an empty list cannot be blamed on not
being logged in. Not transport: a clean 200 with well-formed JSON. It is an
empty draft — plus, separately, a shape nobody anticipated.

**The second, independent finding.** The container key is `currentDraftPicks`.
`parse_draft_picks` was looking for `draftPicks` or `picks` and would have
matched neither. That did *not* cause the zero — the list is empty under its real
name too — but had the endpoint been publishing selections all along, the parser
would have returned zero of them and the feed would have reported a healthy,
*silent* source. Green tests, empty board. Fixed by adding the observed key ahead
of the two guesses, which are kept: one real payload names one key and does not
disprove the others. Key selection is now by presence rather than by a truthy
`or` chain, which would step past an empty-but-present list to a later key.

**What this did not settle, and could not.** `fantraxapi==1.0.1` models a draft
pick as `round` + `year` + `origOwnerTeam` — a **tradeable future pick asset**,
not a selection. A completed draft has no unused picks left, so *both* readings
predict the empty list that was observed, and the key name `currentDraftPicks` is
weak evidence for the asset reading and nothing more. Every per-record field name
remains a guess, because **no populated row has ever been seen on this path**.
One hypothesis was left deliberately untested: the league is NFL and the request
sends no `sport` parameter — trying one would have been adjusting the request
until it succeeded.

**Consequence.** Both automatic pick-tracking paths are now negative — the bridge
cannot read `/fxpa/req` at all, and the official API does not carry the board. See
`draft-board-dom-parser`, which this result promoted to the critical path for
4 October. The one consolation is real: the endpoint is reachable and needs no
credentials, so if it ever populates, polling it is cheap.

### `draft-feed-team-alias-draftteamid` - Admitting the team id Fantrax actually sends

- [ ] **pending**
- **Depends on:** `draft-tracker-bridge-feed`

**Found in the first instrumented capture, 2026-08-28, on a live Fantrax draft
room.** `FIELD_ALIASES["team_external_id"]` is `("teamId", "fantasyTeamId",
"franchiseId", "teamID")`. Fantrax emits **`draftTeamId`** on every
`processScorerDrafted` and **`cellTeamId`** on every `Board cell MATCHED`.
Neither is in the tuple.

**Consequence if unchanged.** `recognise.py`'s own contract: a record with no
resolvable buyer disqualifies the entire list it is in. So every pick refuses as
`no_seat_anchor`, the board stays empty, and freshness still reports the
transport healthy. That is the owner's Q12 answer — *"it loses track of the
draft"* — reached by an alias nobody could check until a real draft existed.

**The player alias was right and must not be touched.** `scorerId` is in the
tuple and is exactly what Fantrax sends; it entered from `fantraxapi`'s NHL
heritage and the vocabulary really is scorer-shaped across sports. An earlier
reading of a compressed screenshot claimed it was `scoreId` and wrong — that was
a misreading, corrected before anything was edited.

**Add, do not replace.** The existing names may be correct for the official
`fxea` path, which is a different recogniser (`_OFFICIAL_RECOGNISER =
"fxea.getDraftPicks.v1"`). This item widens the bridge path only.

**Evidence is console vocabulary, not wire format.** `[DRAFT.STORE]` lines are
emitted by Fantrax's own client and it may rename on ingest. **Confirm against a
captured body before editing**, and if no body can confirm it, say so in the
change rather than asserting the shape. Captures are in the owner's private
folder, not in this repository.

**Acceptance:** a recorded fixture built from a real capture, a contract test
that fails against the current tuple and passes after, and an explicit statement
of which recogniser the widening applies to.

### `bridge-drop-cache-storage-poller` - Removing a five-second poll of a store that is permanently empty

- [x] **done**
- **Depends on:** `bridge-capture`

`capture.js` ran `setInterval(pollCacheStorage, 5000)` on every Fantrax league
page. Capture path 1 was **verified empty on a live draft room** on 2026-08-28:
the origin's Cache Storage holds five `ngsw:` entries, all Angular
service-worker *asset* groups, and no data group. `/fxpa/req` responses are
never written there, so the poll could never find anything.

Removed in 0.5.2, and the reasoning was kept where the code used to be: the
hypothesis, the observed cache names, the `assetGroups`/`dataGroups` mechanism
that explains them, and the one condition under which re-testing is worthwhile.
The four-path commentary now reads path 1 as verified-absent rather than
unverified. The IndexedDB note stands unchanged — still unimplemented, still a
documented option.

`"cache-storage"` remains a valid `hoops-gm.bridge-payload.v1` source and is
still accepted by the isolated-world receiver. Removing the producer is
bridge-local; retiring a schema value the backend validates and stored payloads
may carry is a contract change `backend` owns.

**The three tests it replaced are worth recording as a failure of testing.**
Two of them asserted that nothing was published — for a hidden tab and for a
rejecting `caches.keys()` — and **both kept passing after the poller was
deleted**, because publishing nothing is exactly what absent code does. Only
the third failed. A green result that survives the removal of the code it
covers is not evidence, so the replacements assert the absence directly: that
`window.caches` is never read even when a matching `/fxpa/req` entry is offered,
that no recurring timer is installed, and that the finding is still in the
source.

### `bridge-status-strip` - Showing, on the Fantrax page, whether the bridge is alive

- [x] **done**
- **Depends on:** `userscript-foundation`, `bridge-capture`

Shipped in 0.5.2. A shadow-DOM strip in the bottom-left corner of any Fantrax
league page reporting the running `@version`, paired or not, envelopes the
backend acknowledged, how many were dropped as byte-identical, when the last
capture happened, which path produced it, and the last refusal reason.

**It closes all four silent failures**, which was the argument for it: an
unpaired script, a refused envelope, a stale build and a draft that has not
started were previously indistinguishable from the Fantrax page. The refusal
reason existed nowhere before this — `forward()`'s `catch` discarded the error,
which is what made "backend unreachable", "bridge is not paired" and "HTTP 401"
render identically as nothing happening.

Constraints, all of them tested: closed shadow root; every style written
through the CSSOM rather than a `<style>` element or `style` attribute, because
a `style-src` CSP on fantrax.com would block those two and leave an invisible
strip; `pointer-events: none`, so it is structurally incapable of swallowing a
click meant for the draft board; `textContent` rather than markup, with
secret-shaped tokens redacted from refusal text; and **no timer of its own** —
it rides the rendered-view watcher's existing one-second context check and
suppresses DOM writes when its rendered text is unchanged. Adding a status
interval immediately after removing the Cache Storage interval would have been
a wash.

**It deliberately does not show picks the feed recognised**, which the original
item listed. That number is draft-scoped: it needs a `draft_id` for
`GET /drafts/{id}/feed`, and the userscript has no honest way to learn one. A
Fantrax league page URL carries Fantrax's *external* league id while
`GET /drafts` returns our *internal* `league_id`, so the two cannot be joined in
the browser, and guessing "the newest draft" would render a confident number for
the wrong draft. Surfacing it needs a backend contract `backend` owns, not a
heuristic in the bridge. Filed as `bridge-status-strip-feed-counts`.

No price, value, suggested bid or ranking, and a test asserts the rendered text
carries none of that vocabulary — so the drift into `bridge-overlay`'s territory,
which carries the Model gate, fails loudly rather than quietly.

### `bridge-status-strip-feed-counts` - Showing recognised picks on the strip, once a draft can be identified from the browser

- [ ] **pending**
- **Depends on:** `bridge-status-strip`, `draft-tracker-bridge-feed`

`bridge-status-strip` shipped without the one field its own description asked
for: picks the feed actually recognised, and the refusal reason the *feed*
returned as opposed to the one the *transport* returned. Both are draft-scoped
and need `GET /drafts/{draft_id}/feed`, whose `observation_count`,
`applied_count`, `blocked` and `skipped` fields already carry exactly the right
information.

**The blocker is identity, not plumbing.** The userscript knows the Fantrax page
URL, which carries Fantrax's external league id. `GET /drafts` returns
`DraftSummary.league_id`, which is our internal database id. Nothing served to
the browser joins the two, so the strip cannot resolve a draft without guessing
— and a strip confidently reporting another draft's pick count during a live
draft is worse than one reporting nothing.

**Acceptance:** a local-only read that maps a Fantrax external league id to a
draft, decided and owned by `backend` as a REST contract rather than
reverse-engineered in the userscript, plus the strip consuming it. If the answer
is that the owner should just pass a league id in GM storage at pairing time,
that is a smaller and more reversible answer and should win — but it is still
`backend`'s call, because the strip would then be asserting a linkage nothing
validates.

**Do not solve this by polling every draft.** `GET /drafts` loads every draft's
full state to build its summaries, and the strip would be calling it on a timer
during the one hour where the backend has real work to do.

### `contingent-value` - Building the contingent value graph

- [ ] **pending**
- **Depends on:** `absence-splits`

Usage-redistribution graph: when player X sits, who gains, in which categories, and by how much. Powers stock movement, waiver targeting, and draft handcuff awareness.

### `csv-importer` - Building the generic projection CSV importer

- [x] **done**
- **Depends on:** `player-identity`

Reusable, versioned CSV importer with exact-byte lineage, immutable
source-season profiles, fail-closed identity resolution and exact-output
reconciliation. Basketball Monster's 2026-27 contract is verified against
private paid-export evidence whose hashes are committed without its rows or
path; the committed fixture preserves the exact headers/order/dialect with
synthetic values. The source's season totals are divided by its separately
persisted `games` assumption, with PTS and REB derivations recorded explicitly.
FantasyPros and Hashtag remain unverified parse-preview examples and cannot
write production until they independently earn source evidence. Blending and
expected-games fusion remain separate tasks.

### `dashboard-evidence-views` - Building the dashboard evidence views

- [ ] **pending**
- **Depends on:** `draft-recommender`, `frontend-skeleton`, `risk-adjusted-valuation`

The reasoning behind every overlay recommendation: full category math, punt-fit breakdown, durability and shutdown detail, contingent-value implications, schedule context, and live inflation state in auction. The overlay shows the decision, the dashboard shows why.

### `deployment` - Preparing deployment and the Postgres migration path

- [ ] **pending**
- **Depends on:** `multi-user`

Docker Compose setup, SQLite to Postgres migration path, and a backup/restore runbook.

### `draft-day-synthesis` - Building the draft-morning final synthesis

- [ ] **pending**
- **Depends on:** `auction-values`, `layer-purity`, `risk-adjusted-valuation`

One versioned, reproducible run on the morning of 18 October producing our own rankings and dollar values end-to-end from our own projections and availability, with no external ranking anywhere in the lineage (ADR-008). The version is recorded so it is always knowable exactly which numbers we walked in with. Must be rehearsed during the mock window, not attempted for the first time on the day.

### `draft-recommender` - Building the draft recommendation engine

- [ ] **pending**
- **Depends on:** `contingent-value`, `draft-format-abstraction`, `draft-tracker`, `playoff-schedule`, `punt-builds`, `schedule-ingest`, `shutdown-risk`

DEPRIORITISED - league confirmed auction on 2026-08-17. Snake is retained for multi-format support and for ingesting snake mock corpora, but is no longer a draft-day deliverable. Snake-format recommendations: value over replacement against pick slot, ADP value and reach, positional scarcity, tier cliffs, with durability, shutdown and handcuff flags from the availability engine. Per ADR-012, also exposes per-week game-count distribution (from `schedule-ingest`, not a model) as a first-class schedule-volume input: two-game/five-game weeks, front/back-loaded schedules, and roster fit, distinct from `strength-of-schedule`'s opponent-quality weighting.

### `draft-simulator` - Building the mock draft simulator

- [ ] **pending**
- **Depends on:** `auction-nomination`, `draft-recommender`, `opponent-calibration`

Mock drafts for both snake and auction against calibrated opponent models, including durability-weighted and stars-and-scrubs strategies. Used to pressure-test builds before the real thing.

### `draft-tracker-persistence` - The recorded draft log, its derivation and its API

- [x] **done** - Landed 2026-08-21 in #64: `drafts`, `draft_participants` and
  `draft_events` (migration `0017`), an ordered append-only event log as the only
  stored fact, with every board and roster derived from it.
- **Depends on:** `draft-format-abstraction`

### `draft-tracker-screen` - The draft board on screen

- [x] **done** - Landed 2026-08-22 in #66, with the recorder's own guidance in #77.
- **Depends on:** `draft-tracker-persistence`, `frontend-skeleton`

### `draft-tracker-bridge-feed` - Feeding the tracker from the bridge and official API

- [x] **done** - Landed 2026-08-26. The tracker reads the board from the bridge and, where it answers, the official API. Provenance is recorded per instant, freshness is computed on the server clock, and a disagreement between the two sources is reported and never resolved. Ordering is by publication time rather than arrival, and where those two disagree about which reading is current the feed refuses both rather than preferring either clock. Open caveats: neither source has ever returned a real draft payload, so the recogniser is fail-closed by design and may recognise nothing until one mock draft is run with the userscript loaded; **a record whose player id is present but unreadable is counted at ingest and is not surfaced on `GET`, so the board can be silently short a player with every channel reading clean** (confirmed High, filed not fixed - the route is to carry it as `skipped_reason`, which crosses into the recogniser's contract); and whether the refusal above fires on real captures is unknown, because it depends on the userscript setting `captured_at` consistently.
- **Depends on:** `draft-tracker-persistence`, `bridge-capture`, `fantrax-official-adapter`

### `draft-feed-unreadable-id-surfacing` - Surfacing records whose player id cannot be read

- [x] **done** - Landed 2026-08-28. The recogniser's contract changed as this item directed: a record whose `player_external_id` is present and unreadable now becomes an instant carrying `skipped_reason`, written at ingest rather than derived later. It reaches `GET` through the existing `skipped` tally, is never pending and so never applied, and is permanent. Migration `0021` widens `feed_names_a_player` to admit a row naming no player **only** while it carries a reason, so the invariant that anything applicable names a player is unchanged. **The refused row stores no player label either, not only no id**, which goes beyond the letter of the route and is the load-bearing choice: `_player_label`'s fallback is documented as safe only once `_player_identity` has succeeded, which on a refused record it has not; and a row naming nobody has no `matching_key`, so "never joins identity matching" holds by construction rather than by a rule a later change could narrow. The cost is stated rather than hidden - the screen says a record at seat `t2` could not be identified, and does not name the player. The same silence is closed on the official path, where a record with a refused or absent identity was dropped at `if not (player_external_id or player_label)`. **Open caveat:** a list whose records are *all* unreadable is still refused as a list and reported on `POST` only, because nothing about such a list establishes it was a pick log, and writing rows for it would put unfounded refusals on the status screen. See `docs/handoff.md`.
- **Depends on:** `draft-tracker-bridge-feed`

The board must not be able to be marked done while a captured pick can vanish
silently. That rule outlived this item: `draft-tracker` stays `pending` after
this closed, because `architect` found a second way a pick can vanish -
`draft/state.py`'s budget check derives every seat's bank from one scalar, and
the owner has told us his league's budgets differ per team.

### `draft-feed-burned-row-recovery` - Letting a skipped observation be retried

- [ ] **pending** - Filed 2026-08-28 by `backend` while landing `per-team-auction-budgets` Route B, and **driven rather than reasoned about**: `test_a_refusal_that_survives_still_burns_its_row_permanently` in `backend/tests/test_draft_feed.py` watches a `draft_roster_full` refusal burn a row and stay burned across a re-ingest.
- **Depends on:** `draft-tracker-bridge-feed`

**Acceptance:** an observation skipped for a reason the owner has since resolved
returns to `pending` and is retried, without the identical capture having to
arrive under a new artifact key.

**The mechanism, named so it can be disproved in ninety seconds.**
`apply_observations` in `backend/src/hoops_gm/draft/feed/service.py` sets
`row.skipped_reason` on the `except DraftLogError` branch. `pending` in the same
function is built by filtering `row.skipped_reason is None`. **No assignment of
`skipped_reason = None` exists anywhere in the package** - grep it. So a skip is
permanent, and re-ingesting the same capture dedupes on the artifact key against
the burned row instead of retrying it.

Two branches already work around this rather than through it, which is the
evidence that it is a defect and not a design: the `draft_pick_out_of_turn` halt
deliberately sets `blocked_reason` instead, and so does the contradicted-key
path, each with a comment saying in as many words that `skipped_reason` is never
cleared. Two special cases avoiding a general behaviour is the shape of a
general behaviour being wrong.

**Route B removed the worst input to it and nothing else.**
`draft_budget_exceeded` was the one refusal that fired on a *correct* capture -
it burned a real pick because our budget scalar was wrong. That code no longer
exists. `draft_roster_full`, `draft_player_already_taken` and the rest still
burn, and each of those is resolvable by hand: the owner voids the entry that
filled the roster, re-runs, and the observation waiting behind it is silently
gone rather than applied.

**Not in scope for the lane that filed it**, which had a hard calendar
constraint and an owner-approved unit that did not include this. Rows burned
before this lands stay burned; a recovery path would have to decide whether to
clear them retroactively, and that is a decision about data the owner may have
already reconciled by hand.

### `draft-tracker` - Building the live draft tracker

- [ ] **pending** — *umbrella; **all nine dependencies are done as of 2026-08-28.** The `per-team-auction-budgets` edge was dropped by owner ruling that day. What remains is not a dependency but an open question: whether picks can be tracked automatically at all — see `official-getdraftpicks-live-verification`*
- **Depends on:** `draft-tracker-persistence`, `draft-tracker-screen`, `draft-tracker-bridge-feed`, `draft-feed-unreadable-id-surfacing`, `bridge-capture`, `draft-format-abstraction`, `fantrax-official-adapter`, `frontend-skeleton`

Live draft state for both snake and auction: pick-by-pick board or nomination board, plus roster construction view. Fed by the bridge and official API.

**What landed, and why this stays open.** The persistence and API half is done:
`drafts`, `draft_participants` and `draft_events` (migration `0017`), where an
ordered, append-only event log is the only stored fact and every board, roster,
spend figure and turn is re-derived from it on each read. The format is
snapshotted onto the draft from `draft-format-abstraction` at creation and never
re-read from the league, so a later league edit cannot move a recorded price;
the league's current format is published alongside as `league_format_drift`
rather than silently reconciled. `GET /api/v1/drafts`, `GET /api/v1/drafts/{id}`,
`GET /api/v1/drafts/{id}/events` and the two `POST`s are loopback-only, and there
is deliberately no `PUT`, `PATCH` or `DELETE` anywhere on the surface -
corrections are recorded as `void` events, which is what makes `last_sequence` a
complete version token and lets a read take no lock (ADR-014). A mock auction and
a mock snake draft are recorded end to end by `hoops_gm.dev.seed_draft`.

Three things this does **not** do, each of which is why the marker is still
`pending` rather than `done`. There is no screen - that is the stacked
`frontend` lane, and this item's own description asks for a board and a roster
construction view. Nothing feeds the log automatically: every event arrives
because a person posted it, so "fed by the bridge and official API" is
unstarted. And the log stores only what happened - no price estimate, no
inflation, no recommendation, no `p(play)` - which is correct scope here but
means the item's downstream readers (`auction-budget-manager`,
`auction-inflation`, `draft-recommender`, `live-draft-availability`) are
unblocked on their *input*, not served by it.

**The screen landed on 2026-08-21** (`frontend` lane): a recording panel, a seat
board with roster construction and per-seat spend, and the full log with
correction affordances, at `/draft` and `/draft/:draftId`. It renders no
decision number of any kind. Two findings from building against the live API are
worth carrying forward. **The tail-only correction limitation is positional, not
structural** - the brief described it as "the last sale of a nominated lot", but
driving a void at all 27 seeded events against a fresh database each time
measured **4 of 27 voidable, and 2 of those were not the tail**. The screen
therefore offers a guaranteed "Undo" only on the highest sequence and a
"Try to void" everywhere else, rather than hiding the other 26. And
`remaining_budget` is budget minus *spent*, so a seat holding a live high bid
still shows its full remaining budget; the screen renders the live bid as a
visibly second, differently-coloured claim rather than reconciling the two into
a number the backend never sent.

What is still missing for the 18 October auction is the feed and the setup:
see `draft-setup-screen` for the second.

### `fixture-drift-gate` - Fail CI when a recorded fixture stops matching the backend

- [ ] **pending**
- **Depends on:** `draft-tracker`

`scripts/capture_draft_fixtures.py --check` re-drives every payload the draft
board's tests are recorded against and reports drift. It is not wired into CI,
because the Python gate runs with `working-directory: backend` and this needs the
app importable alongside the frontend fixtures - a job-shape change that is not a
frontend lane's to make unilaterally.

It should be. On 2026-08-21 the draft-tracker base moved from `5ec3d0f` to
`ce4c603` carrying two message-correctness fixes, and two of six recorded refusals
immediately held text the backend no longer produces - including a re-wrap that
asserted something untrue about the log. **The frontend suite stayed green
throughout**, because a recording cannot notice that it is old. It was caught by
hand, by one lane happening to re-drive the API after a rebase.

That is the same shape as the tripwire finding: not a wrong assertion, an
*unentered* comparison. The fixtures are the frontend's only contact with the
contract, and nothing checks they still describe it.

**The script lands with the draft board; the CI wiring is `backend`'s**, since
`.github/workflows/` is theirs and this is a job-shape change. And the hole is not
the draft board's alone - this repository holds recorded fixtures in at least
three places, and every one of them is a copy of another tree's behaviour that
git reports no conflict on, because neither lane edits the other's file. The
frontend gate does not run the backend; the backend gate does not know the
fixtures exist. Wiring this one is worth doing on its own terms, but the general
form is the thing to fix.

### `draft-log-virtualisation` - The draft log is fifteen screens and violates the five-second rule

- [ ] **pending**
- **Depends on:** `draft-tracker`

`.github/agents/frontend.md` says *design for one screen* and *if a view cannot be
read in five seconds during a pick clock, it belongs in an evidence view*. The
draft board's event log renders every event unvirtualised. On the seeded demo that
is **170 entries across roughly fifteen screens**, and a real auction is larger.

State it as the violation it is rather than as a refinement: **finding one row
among 170 under an auction clock is exactly what that rule forbids.** The acute
half was fixed in the board's first unit - the Record control and the stale
warning are pinned and visible at every scroll position, verified at 21 of them -
so the screen is recordable now and the log is legible and merely long. That is
why this is filed rather than rushed into that PR at 1am. It is not why it is
acceptable.

Recorded honestly: the frontend lane located a specific entry during browser
verification by calling `scrollIntoView` from a console. **The owner will not have
that.** Nobody has yet driven a search for a known entry under time pressure, so
the size of the problem is argued, not measured - and measuring it is probably the
first half of this task.

Wants a decision about what the log is *for* during recording, which is not
obviously the same thing it is for afterwards. Likely candidates: windowing with a
jump-to-sequence control, collapsing the settled majority behind a count, or
splitting the recent tail from the full history entirely. That decision belongs to
a calm hour, not to a merge.

### `draft-board-affordance-styling` - The void button's styling makes a claim the button does not

- [ ] **pending**
- **Depends on:** `draft-tracker`

The draft log offers two corrections. **Undo** is guaranteed and is painted as a
solid orange fill at weight 600. **Try to void** may be refused and is painted as
a dashed, transparent outline in `rgb(152, 161, 179)`.

`Try to void` is attemptable *because a refused void writes nothing* - a fact
about the backend, driven against a seeded log whose `last_sequence` was 170
before a refused attempt and 170 after. **It was then styled to look like the
least consequential thing on the screen.** So the visual weight encodes
*"unimportant"* when the property that is actually true is *"free to try"*. Those
are different claims, and the screen renders the wrong one.

The predicted symptom is **the owner reporting that "the void button was greyed
out"** - which is the form the report will arrive in and does not obviously point
at the cause. It is not disabled. The fix is a hover or active state that proves
it is live, rather than more colour at rest, which would cost the contrast that
makes the single Undo legible.

**That contrast is the thing not to break while fixing this.** There is exactly
one Undo among twelve `Try to void` buttons, and the scarcity carries more of the
distinction than any single visual channel does. This was not visible to the lane
that built it, which was comparing two buttons rather than looking at a screen.

**The tooltip asymmetry is an accident that works, and must not be normalised.**
`Try to void` carries the caveat in a `title`; `Undo` has none. That was not
designed as a contrast - the caveat was written onto the button that needed one.
It is load-bearing anyway: a caveat on both would flatten them. **The predictable
failure is a later tidy-up adding a tooltip to `Undo` for consistency**, which
would remove a distinction nobody recorded as deliberate.

Both halves of this item are the same shape, which is why they are one item: a
place where the property and its rendering disagree, and where a later
consistency pass would break the thing that currently works. The styling says
*unimportant* and means *free*; the tooltip asymmetry looks *inconsistent* and is
*correct*.


### `draft-setup-screen` - Creating a draft and its seats from the browser

- [ ] **pending**
- **Depends on:** `draft-tracker`, `frontend-skeleton`

`POST /api/v1/drafts` exists and takes a league, a name, a `tool_usage`
declaration and the full participant list, but nothing in the browser calls it.
Today the only way to bring a draft into being is `hoops_gm.dev.seed_draft`, a
development CLI that invents synthetic seats, or a hand-written POST. The draft
board at `/draft` deliberately does not offer creation: it is built to be used
under an auction clock, and a twelve-seat setup form is a calm, once-per-draft
task that would enlarge that surface for no benefit at the moment it matters.

This is small but it is on the critical path, because the owner cannot record
his mock auction - or the real draft on **18 October 2026** - without a draft to
record into. Needs seat names, per-seat budget for an auction, draft order for a
snake, and the `is_mock` / `tool_usage` declaration surfaced honestly rather than
defaulted past, since `tool_usage` is the field that records how much help was
used and is the one a leaguemate would care about.

### `secret-scan-fixture-isolation` - Making the secret scan safe to run concurrently

- [ ] **pending**
- **Depends on:** `backend-skeleton`

`backend/tests/test_secret_scan.py` plants a fake credential **into the real
committed fixture `backend/tests/fixtures/nba_static_teams.json`** and restores
it in a `finally`. Two consequences, both observed rather than theorised. Any
concurrent reader of that fixture — the schedule-grid seed, `test_importers.py`,
a second pytest process in the same worktree — can read it mid-mutation and fail
with a `JSONDecodeError` that looks like flakiness in an unrelated test; this
cost one lane an hour and produced two successive wrong explanations before an
independent reviewer caught the failure in the act. And a hard kill inside that
window leaves a credential-shaped string sitting in a tracked fixture. Copy the
fixture to `tmp_path` and plant there, or point the scanner at a temporary tree.

### `error-code-observability` - Logging the error code, not just the status

- [ ] **pending**
- **Depends on:** `backend-skeleton`

`api/middleware.py` logs `status_code` and `app.py`'s HTTP exception handler
logs nothing, so every typed refusal reads identically in the log. The schedule
grid made this concrete: four of its five refusals are `409`, and
`schedule_grid_not_current` and `schedule_grid_incomplete_evidence` demand
different operator actions — re-import versus a refresh that can never populate
the contract — yet an operator reading logs cannot tell them apart. Log the
`ErrorResponse.error` code alongside the status. App-wide and pre-existing;
surfaced here because this is the first route whose codes carry distinct
operator actions.

### `expected-games` - Fusing production with expected games played

- [ ] **pending**
- **Depends on:** `availability-model`, `layer-purity`, `projection-blending`

Combine per-game production projections with the availability model expected games. The seam that makes durability visible in every downstream number and prevents systematically overvaluing fragile stars.

### `games-cap-tracker` - Tracking games-played caps against the schedule

- [ ] **pending**
- **Depends on:** `league-settings-ingest`, `schedule-density`

Where the league caps games per week or per position, burning the cap early strands roster spots later. Track games used and remaining against the cap alongside the schedule grid, so streaming and lineup decisions account for it rather than discovering the cap after it binds.

### `gscore-engine` - Implementing the G-score engine for H2H

- [ ] **pending**
- **Depends on:** `zscore-engine`

G-score per arXiv 2307.02188, absorbing both production variance and availability variance into the same framework. Default valuation scheme for H2H leagues.

### `hashtag-projection-profile-verification` - Verifying the Hashtag Basketball projection profile so it can be imported

- [x] **done**
- **Depends on:** `csv-importer`

Owned by `data-engineer`. Done: `HASHTAG_PROFILE` is v2 and `verified=True`, so
`import_projection_csv` now accepts Hashtag projections. See
`docs/adapters/hashtag-projections.md` for the verification record.

**The source publishes no CSV export.** The page is rendered HTML and the owner's
workflow is copy-paste, so the BBM pattern - hash an immutable downloaded file -
does not transfer. `verified=True` here means *the contract was observed on the
live page*: header sequence, cell dialect, and three reconciliations. **That is a
strictly weaker claim than BBM's file hash** and the metadata says so; the field
name does not distinguish them.

**The defect the verification found was silent, not loud.** Hashtag publishes
makes and attempts inside the percentage cell - `0.573 (10.5/18.3)` - while v1
declared `FG%`/`FT%` as percentage-fallback, whose semantics are *no volume
published*. A repaired import would have parsed cleanly and discarded every
shooting volume, which is the volume-weighting bug `AGENTS.md` calls the most
common in homebrew tools. `CompositeShootingColumn` extracts and reconciles it.

**Scoring format is not verified, deliberately.** Per-category rates are
format-independent; only `TOTAL` depends on format and ADR-008 already forbids it,
so the profile refuses the column rather than checking a claim that cannot fail.

**The `aav-source` independence guard now fires on Hashtag**, as that item
predicted, and its test drives a real import rather than a hand-built row.

### `injury-conversion-cohort-population` - Populating a representative historical injury-report/participation cohort

- [x] **done** - Regenerated 2026-08-20 from corrected sources after PR #37 invalidated the 2026-08-19 artifact, through five rounds of independent exact-head review (evidence, code, extract privacy). The corrected bounded cohort is 173 games across 26 game dates in `2025-12-08..2026-01-04`, including `0022501229` and `0022501230` on 2025-12-13 and their 39 production logs. Every count and fingerprint was recomputed; nothing was carried forward. The manifest is the deterministic output of a committed generator (`hoops_gm.ingest.injury_report.cohort_evidence`) rather than hand-assembled; it **refuses to publish** unless four views of the window name exactly the same games as sets *and* two endpoints agree on all 173 tip-off instants, and it publishes a map of which views are actually independent of the ingest path (only `ScheduleLeagueV2` is). **The item's own "multiple positions" criterion is explicitly waived, with cause:** review established that `BoxScoreTraditionalV3.position` is emitted only for the five starters, always as `F,F,C,G,G`, so it is a lineup slot rather than a player attribute and positional composition cannot be established from any source this project currently ingests. Establishing it needs a new adapter under the Adapter gate and is not a precondition for the observation-layer cohort. Team, date, status and stated-reason diversity are established. The 2026-08-19 artifact remains preserved in history and stays non-consumable.
- **Depends on:** `injury-report-historical-backfill`, `participation-ledger`

Run the bounded, resumable `injury-report-historical-backfill` operator tool at scale against the live NBA official injury-report archive — within its own rate-limit and request-budget bounds — to populate an actual multi-date, multi-game historical cohort of canonical pregame observations joined against the participation ledger's realized outcomes: large and diverse enough (multiple teams, positions, report statuses, and a genuine calendar span, not a handful of adjacent dates) to be evidence-ready for `injury-status-conversion`. Tracked as its own explicit dependency, separate from the operator tool itself, precisely because "the tool exists and passes its tests" and "a representative cohort has been populated with it" are different claims — conflating them is what let `injury-status-conversion` appear structurally ready (every backlog dependency it listed marked done) while the cohort it actually needs did not exist. The only live-archive run performed to date produced a deliberately small, non-representative sample (22 of 527 games, spanning a handful of dates) used to validate the backfill tool's own mechanics, not to seed this item. Done only once that representative cohort exists, is committed as real fetched evidence (never fabricated or extrapolated), and has been independently reviewed for actual representativeness — team/date/status-code coverage, no lookahead, and no selection bias toward easy-to-fetch dates.

**2026-08-23, `data-engineer`: the widened cohort exists as evidence, and it is admissible.** Full 2025-26 regular season, 164 game dates, built by a **cross-store** join because no single store holds both halves — the durable ledger has participation and no reports, the report sweep has 69,922 reports and no participation. Held-out direct outcomes are `out` 2,963, `questionable` 335, `available` 467, `probable` 92, **`doubtful` 83** against a floor of 30, so every status clears and `doubtful` is binding at 2.77x. Evidence at `docs/adapters/nba-injury-report-cohort-admissibility-2025-26.json`, generated by the committed `hoops_gm.ingest.injury_report.cohort_admissibility`. **No live-source spend: both stores were already on disk and the run makes zero external requests**, which is what the owner decision above was reserving. Two things the arithmetic could not see are declared in the artifact pre-unblind rather than discovered after: the held-out range is late February to mid-April, **the end-of-season shutdown window, which is not the regime the tool is used in**; and the `FIFTEEN_MINUTE_ERA_START` reporting boundary falls inside the cohort, leaving development 68% legacy while selection and holdout are **100%** short-lead. The 50/25/25 boundaries are deliberately **not** moved — §4 already names choosing different proportions because these are inconvenient as the worse reason. The contract test this item asked `data-engineer` for exists, and its scope is the **whole committed disclosure surface** rather than the manifest: scoped to the manifest it would have missed `participation-ledger-2025-26-coverage.json`, which publishes an outcome marginal and sat outside the old glob entirely.

**2026-08-24, `data-engineer`: the artifact now exists, and #85 delivered a verdict rather than a cohort.** `git show --stat fa705b5` carries no manifest and no fingerprint - the admissibility module concluded the widened window *was* admissible without regenerating it. The regenerated cohort is `docs/adapters/nba-injury-report-cohort-2025-10-21--2026-04-12.json`: full 2025-26 regular season, 1,230 games across 164 game dates, 13,789 canonical observations, 13,598 joined against the ledger, fingerprint `8e1986229b3644daa1f7bffa3ce2362e8cfb438da4b1085c0803aebe53f8176e`. Every count recomputed, nothing carried forward, **zero external requests**. It reconciles with #85 **exactly** on all five status counts and on the whole exclusion cascade. Because no single store holds both halves, it is built through a committed, tested merge tool (`hoops_gm.ingest.injury_report.merge_stores`) that copies reports **into** the ledger and emits a receipt - direction measured, not assumed: merging the other way produces a manifest whose tip-off reconciliation compares `ScheduleLeagueV2` with itself and reports `agreed: true`, which no reader could detect because nothing recorded the provenance of a persisted instant. `participation_outcome_counts` is **withheld** pending `quant`'s ruling against the blind, since a widened manifest is a superset of the committed four-week one and publishing both yields the added dates' marginal by subtraction. Two privacy leaks were found by reading the generated artifact rather than by any test - 50 rows of real player names in `unresolved_game_id_sample`, a field the five-round "extract privacy" review saw only while it was **empty**, and the operator's home directory embedded three times through the receipt's store paths - both now withheld and pinned by tests proved load-bearing by experiment. **The four-week manifest no longer reproduces** and is frozen with a recorded reason rather than regenerated; that is a finding for the coordinator, not a resolution taken here.

**2026-08-21, `quant`: this cohort is representative but not large enough to activate the model it was built for, and the shortfall is arithmetic rather than a review finding.** `injury-status-conversion`'s activation rule needs at least 30 held-out **direct outcomes** for every status; whole-cohort canonical `doubtful` is **21** and `probable` is **59**, direct outcomes are a subset of canonical observations, and a chronological holdout is a subset of the cohort, so no split can reach the floor. That does not retract this item - it delivered the representative cohort it was scoped to deliver, and the floor is a downstream requirement nobody had checked against it. It does mean **a re-run of the same four weeks buys a model that cannot activate.** Widening is an owner decision on live-source spend and is not taken here. Two requirements for whoever runs it: the window must be wide enough that every status clears the floor inside the declared holdout (a planning figure of roughly 4.5x the current width follows from v1's 32% holdout share, but it is an estimate and probably an underestimate, since December reporting is not April reporting and late-season shutdowns inflate `out` without inflating `doubtful` - the gate is the measured count, never the multiplier); and the manifest must publish **per-status direct-outcome counts by game date, plus exclusion classes by status**, so any chronological split is checkable before unblinding. That disclosure is deliberately partition-agnostic - publishing counts by a declared partition would write an availability-layer parameter into an observations-layer artifact, a backward flow under ADR-008 - and it carries one invariant: **the pre-unblind disclosure surface adds no outcome-keyed field at any granularity, in any manifest version**, beyond the single whole-cohort `participation_outcome_counts` already present. A granularity rule ("outcome counts stay whole-cohort") was tried first and rejected by both reviewers as necessary but not sufficient: git makes cross-manifest differencing free, and widening the same window produces cohort B superset of cohort A with both committed, so the added dates' outcome marginal falls out by subtraction. `data-engineer` owns a contract test pinning the outcome-keyed field set to a frozen allow-list.
### `cohort-canonical-count-reconciliation` - Reconciling two canonical 2025-26 observation counts that differ by 30

- [ ] **pending** - Opened 2026-08-24 by `data-engineer` while recovering the stranded branch `sr2501-injury-report-history` (tip `dbad3b3`, no PR, 188 commits behind `main`). That branch carries `docs/adapters/nba-injury-report-2025-26-status-census.json`, an independently computed census of the same population as the committed `docs/adapters/nba-injury-report-cohort-2025-10-21--2026-04-12.json`. **The two disagree, and the census was deliberately not landed** - a second contradictory 2025-26 canonical count sitting in `docs/adapters/` with no reconciliation is worse than none, and landing it would make the disagreement permanent and undated. The numbers, so the disagreement is dated with them attached rather than described: census **13,819** canonical observations against the manifest's **13,789**; resolved **13,684** against **13,654**; unresolved **135** against **135**, identical; games **1,230** against **1,227**; and by status, `available` 1,491/1,489, `doubtful` **221/221**, `out` 10,478/10,453, `probable` **435/435**, `questionable` 1,194/1,191. **The whole 30-observation gap sits in resolved rows, and entirely in the legacy era** - census legacy 4,280 against 4,250, short-lead identical. `doubtful` and `probable`, the two statuses the §2 activation floor actually binds on, agree exactly, which is why this does not block `injury-status-conversion`.

  **The first mechanism offered for it was tidy and wrong, and that is recorded here on purpose.** 1,230 - 1,227 = 3 games at roughly ten observations each is about 30, which fits the arithmetic and nothing else: the manifest's `unresolved_game_id_sample` games are 2026-01-08 `MIA@CHI`, which is *short-lead* era, while the gap is entirely legacy. It was killed by **implausibility, not by verification** - the same detector that caught the `-495..+660` tip-off offset - and no test would have caught it.

  **The better mechanism is a difference in selection basis, which makes this a definitional gap rather than a data defect.** `cohort_evidence.py:915` selects over `ready` only - `select_canonical_pregame_observations(session, game_ids=[game.game_id for game in ready])` - while `in_scope` is `[*ready, *missing_tipoff]`. The manifest therefore drops games with no resolved tip-off; the census counted `games_with_tipoff: 1230`. If that is the whole story the two artefacts are both correct over different populations and the fix is a documented definition, not a regeneration. **It is not proven to account for all 30**, and the all-legacy localisation still does not fit cleanly under it, so both halves stand until someone measures it. Done when the gap is either fully attributed to the selection basis with the per-game arithmetic shown, or attributed to something else; either way the winning definition is stated in `docs/adapters/nba-injury-report.md` and the census is landed or discarded on that basis.
- **Depends on:** `injury-conversion-cohort-population`

Neither number may be preferred for being newer. The census predates the manifest by two days and was computed by a different code path over a store that has not changed since; recency is evidence about authorship order and nothing else. This item exists because the alternative - resolving it silently in favour of the committed artefact - is how a real degradation would pass here with every number looking right.

**2026-08-27, `data-engineer`: the interim decision is now enforced, and the item stays open.** Nothing prevented the held-back census from simply being committed. Measured: place `nba-injury-report-2025-26-status-census.json` into `docs/adapters/` and run `test_cohort_admissibility.py`, `test_cohort_evidence.py` and `test_injury_report_archive_reach.py` - **133 tests pass**, because the census carries no outcome-keyed field and the §2 disclosure guard correctly has no opinion about it. `backend/tests/test_status_census_reconciliation.py` now closes that, as a **reconciliation rather than a banned filename**: it selects on the artifact's own `kind` discriminator rather than its name, compares its whole-season totals against the committed manifest, and passes the moment the two agree. It therefore permits exactly the outcome this item is open for - attribute the 30, then land the census - and blocks only the undated-disagreement one. It prejudges neither artifact: it fails on *disagreement*, not on the census existing. **This does not close the item.** The 30 are still unattributed and the all-legacy localisation still does not fit the selection-basis hypothesis. Adjudicated as `c349` in `docs/governance/coordinator-register.md`; the branch `origin/sr2501-injury-report-history` (`dbad3b3`) holds the only copy of the census and **must not be deleted**. One correction to the record above: this item says the branch is "188 commits behind `main`", which does not reproduce - `git rev-list --count origin/sr2501-injury-report-history..origin/main` is **64**, and no total-commit or symmetric-difference count yields 188 either.

  **2026-08-27, `data-engineer`, and this reopens the mechanism this item recorded as killed.** The paragraph above rejects the selection-basis hypothesis because `unresolved_game_id_sample` is 2026-01-08 `MIA@CHI`, short-lead, while the gap is all legacy. **That is the wrong field.** `unresolved_game_id_sample` is unresolved *player identity*; the games dropped for want of a tip-off are `0022500259`, `0022500260`, `0022500261`, named identically by `cross_source_tipoff_reconciliation.games_without_both_instants` and by `store_assembly.receipt.cross_store_nba_games_reconciliation.tipoff_utc.absent_in_participation_ledger`, and dated by a third artifact: `participation-ledger-2025-26-coverage.json` reports `games_unobserved: 3` with `unobserved_dates` all **2025-11-19** - **legacy era**. The all-legacy localisation is therefore what the hypothesis predicts, not evidence against it. Corroborating but not proving: 30 over 3 games is **10.0 observations per game**; and differencing the census's `status_counts_by_game_date` against the committed `direct_outcome_counts_by_game_date` puts 2025-11-19 **top of all 164 dates at +30**, next is +17, mean 1.35. **Still not closed** - that excess is canonical-minus-direct and so mixes the dropped games with ordinary exclusions on the same date, and no committed artifact publishes the manifest's canonical count for 2025-11-19. Done when someone recomputes that one number. The irony is recorded on purpose: this item says the first mechanism "was killed by **implausibility, not by verification**", and the second was killed the same way, off a field nobody re-read.

### `injury-status-conversion` - Modelling injury status conversion rates

- [ ] **pending** - Protocol frozen 2026-08-21 at `docs/models/injury-status-conversion-preregistration.md`; **no model is fitted and no number is emitted.** Two findings block the fit, both re-derived from the committed cohort manifest rather than from prose. **(1)** The manifest publishes canonical `status_counts` and joined `participation_outcome_counts` as two separate marginals with **no status x outcome contingency**, so no conversion rate is fittable from anything on `main`. (Row-level data for the *invalidated* v1 cohort is reachable on the local-only branch `sr2501-injury-status-conversion`, which is why the freeze carries a contamination disclosure; it is superseded and non-consumable, and the **corrected** cohort has no row-level artifact anywhere.) The corrected row-level outcomes live only in the gitignored database and raw store, which the coordinator searched for across nine worktrees plus the owner's main checkout: the one real database holds **0 rows** in both `player_participation` and `player_game_logs`. **CORRECTED 2026-08-22: that search was exhaustive over the wrong domain and its conclusion is false.** The participation ledger is populated - 43,037 rows over 596 players across 1,227 of 1,230 games - at `C:\Users\steverones\hoops-gm-data\hoops_gm.db`, which sits *outside every checkout* and so was in none of the ten places searched. The 0-row reading was a true statement about `C:\Users\steverones\hoops-gm\hoops_gm.db`, a different file with the same basename, because `backend/src/hoops_gm/core/config.py:94` anchors the default relative SQLite path to each checkout's own root. See `participation-ledger-population` and `docs/adapters/participation-ledger-store.md`. **This changes what is reachable, and changes nothing about whether this item can proceed:** finding (2) below is arithmetic on the committed cohort manifest and is untouched by where the rows live. Whether a status x outcome contingency is now derivable is a separate question that has not been driven, and is `quant`'s to answer under the frozen protocol rather than something to assume from a row count. **(2)** More decisively, the activation rule requires at least 30 held-out direct outcomes for every status, and whole-cohort `doubtful` is **21**. Direct outcomes are a subset of canonical observations and a chronological holdout is a subset of the cohort, so **21 < 30 unconditionally** - activation fails on arithmetic before any outcome is examined, and `probable` at 59 would need the holdout to hold more than half the `probable` observations. **The `2025-12-08..2026-01-04` cohort can therefore never activate this model**, so regenerating it as-is would spend a full live archive sweep on a guaranteed veto. The freeze turns this into a pre-unblind admissibility gate: per-status direct-outcome counts are inputs rather than outcome values, so a cohort that cannot activate is refused *before* an unblind is spent. Resuming needs a widened cohort - see `injury-conversion-cohort-population`. **CORRECTED 2026-08-23, `data-engineer`: finding (2) no longer blocks, and this item stays `pending` because clearing a blocker is not the same as doing the work.** The widened cohort exists and passes §2: full 2025-26 regular season, 164 game dates, held-out direct `doubtful` **83** against the floor of 30, every status clear. Evidence at `docs/adapters/nba-injury-report-cohort-admissibility-2025-26.json`; the check is `hoops_gm.ingest.injury_report.cohort_admissibility` and counts **inputs only** - no fit, no unblind, and the frozen protocol untouched. Finding (1) is also narrowed but **not** settled: a status x outcome contingency is now *derivable* by whoever holds both stores, and deriving it is the unblind itself, so it remains `quant`'s call under the freeze rather than a step anyone else may take. **Three things `quant` must handle before fitting, none of which any count reveals.** The held-out range is `2026-03-02..2026-04-12`, **the end-of-season shutdown window, which is not the regime the tool is used in** - owner-ruled a stated limitation rather than a reason to move the window, and it must reach the model card **verbatim**. The `FIFTEEN_MINUTE_ERA_START` boundary falls inside the cohort, leaving development 68% legacy against selection and holdout at **100%** short-lead, so the fit would rest substantially on a regime the holdout contains none of; §7 needs era as a pre-registered sensitivity, which only `quant` may add. And ADR-007's `1.596`/`0.917` `doubtful` era figures **replicate exactly on this cohort, and the earlier "does not replicate" reading recorded against them was a comparison against a quantity ADR-007 never measured** - they are the canonical `doubtful` base rate per game date (legacy 55/60 = 0.9167, short-lead 166/104 = 1.5962, summing to the canonical total 221 over 164 dates), not unresolved-identity counts; the `0.019`/`0.033` figures divided exclusions by dates and so compared an exclusion rate to a base rate, and their apparent reversal rests on Poisson counts of 2 where the 95% interval runs ~0.24-7.2. Corrected 2026-08-23 by `data-engineer` after an independent `quant` review. The open end is narrow and stays open: ADR-007's own derivation has not been located, so the population is near-certain rather than confirmed. See `adr-007-era-figure-population`. **2026-08-23, `quant`: the evaluation machinery and the model card now exist, and the fit still has not happened - deliberately.** `hoops_gm.availability.calibration` implements §7's binned table, Wilson intervals, calibration-in-the-large, observation-weighted ECE, Brier, clipped log loss, monotonic-reversal detection and a paired bootstrap, plus **subgroup-restricted calibration as a first-class operation**; it was developed and verified entirely against synthetic cohorts with known calibration properties, by an author who has read no outcome, and 44 deliberate corruptions of it were each driven red - 14 of mine, 4 that an independent non-`quant` reviewer wrote and which **survived** the suite as it stood, 5 more from his second pass against the fixes, 7 from a third pass of which 4 again survived, 10 from a fourth pass of which **7 survived**, and 10 from a fifth of which **4 survived** - a survivor sequence of 4, 5, 4, 7, 4 that is **not converging**, which is stated here because a later lane reading only the total would draw the opposite conclusion from it. **The fifth pass's headline was not a mutation at all: a gate reported from the wrong command.** The lane checked `mypy src` (121 files) and reported "mypy clean" while the gate CI runs is bare `mypy` (195 files, tests included), under which the branch had five errors and would have failed CI - a second instance of a failure mode `gates.md` already records by name, so **quote the file count with the gate** and a narrower run cannot be reported as the wider one. Its three real survivors share a generator distinct from the earlier passes: **a guard exists and is correct, and the only test pinning it uses the one input on which a broken guard still returns the right answer** - duplicate detection keyed on `observation_id` but only ever driven by repeating *the same object*, so `id(row)` passed the whole suite; a `Band.observations` field that no assertion anywhere read, giving the rule **a field no assertion reads is not data, it is decoration**; and a rule applied at one of the two places it names, which is the dunder enumeration it replaced one level up. A fourth item is a caution about method rather than code: **`delattr` cannot model “this method was never defined”** on a heap type, so both the lane and its reviewer produced wrong counterfactual matrices for a CPython slot question before either built fresh classes and got the same answer. **Two of the four first-round fixes were themselves incomplete**, which is the argument for re-reviewing a fix rather than only the thing it fixed: nested `restrict()` dropped the inherited pairs, so a doubly-narrowed payload under-reported what had been excluded; and because a restricted cohort is a mutable list, `extend` moved the rows while the marker stood still, letting an `out`-dominated rate be recorded as `doubtful` - this project's headline failure mode arriving through an ordinary list method. Restriction markers are now verified against the rows rather than believed, and the third pass named the shape the whole sequence shares: **each fix lands on the case that was driven and leaves the generalisation untested**, so when a fix introduces a new dimension - a second pair, a count, a precedence - the test belongs at n=2 rather than n=1. That pass also found a second instance of a symmetry class worth carrying past this module: a declared sign or order is pinned only if some test observes it through a path that does not symmetrise it, because `abs`, a square and a product of two sign-flipping factors all destroy exactly the information the convention asserts. The fourth pass produced two shapes the first three did not, both worth carrying past this module. **A false guarantee is not a disclosed residual:** both docstrings promised that multiplicity-changing container operations return a plain `list`, and `+=`, `extend`, slice-assignment and `append`/`insert` of a row taken from the cohort itself all kept the marker while doubling `n` - which is precisely what moves a Wilson half-width from 0.1052 to 0.0752 and manufactures a guarantee. The fix is **not** the reviewer's own suggestion of enumerating each overridden dunder's in-place twin, good rule though that is: duplicate `observation_id`s are refused where the cohort becomes a number, which covers routes nobody enumerated. **And a declared convention the code does not implement is worse than an undeclared one**, because a later reader has a written assurance and no reason to check: the bootstrap declared resampling by observation id while resampling row positions, which narrows the interval in the direction that flatters the candidate. Checking the reviewer's payloads rather than accepting them also found one that is simply **false** (`rc *= 2` drops the marker, for a CPython operator-fallback reason nothing had recorded - a guard that holds by accident), and a numeral error four passes had read without recomputing (0.0745 is the Wald `1/sqrt(2)` scaling; a Wilson interval does not obey it, and the value is 0.0752). `docs/models/injury-status-conversion.md` is the card skeleton with every results field reading `NOT YET COMPUTED - blind in force`. Two things this settles that a later fit therefore cannot choose: the estimator conventions are pinned in `DECLARED_CONVENTIONS` **before** anyone can see which way they push (Wilson without continuity correction is the *stricter* arm and was taken knowingly), and a restricted report is structurally forbidden from claiming `PREREGISTERED_V2`, since v2 §7 pre-registers a pooled table only. One finding bears on the pending v3 decision and is stronger than v3 §4's own argument: §5's `three_band_jeffreys` pools `out` with `doubtful` at **2,963 to 83** held out, so under distinct-emitted-probability binning the two share a bin *whatever* their rates - a theorem about the partition, not an artefact of the numbers chosen - and no pooled statistic can separate them while the `doubtful` cell is ~86 points wrong. **Corrected after independent review, and the correction matters.** An earlier form of this note said such a model "clears **every** computable pooled condition", which overstated it twice: the exact CITL 0.0 and ECE 0.0 are *definitional* for a model emitting its own evaluation-set band rates rather than measurements, and a real fit's band rate comes from a different partition, so condition 5 does bite - the `unlikely` band's 3,046 observations give a Wilson half-width of ~0.0073, and a displacement of 0.01 fails it while `doubtful` stays ~85 points out. The defensible statement is that **a three-band model whose emitted band probability lands within ~0.7pp of the held-out band rate clears every pooled condition while `doubtful` is ~86 points wrong.** Condition 5 also protects a status that gets its own bin, but less than first stated: at the blind-safe worst case `p_hat = 0.5`, `questionable` (n=335) is 0.0532 and `available` (n=467) 0.0452, both inside 0.10, while `probable` (n=92) is **0.1001** and `doubtful` (n=83) **0.1052**, both outside - which means a 0.10 guarantee **cannot be issued blind** for the latter two, not that they are unprotected; the half-width actually reaches 0.10 only for `probable` at `p_hat` in [0.478, 0.522] and `doubtful` at [0.349, 0.651], both windows centred on a coin flip. The earlier ~0.054 came from a synthetic realised rate and should not have been attached to a real status. Dilution is therefore not the whole story; **pooled-band masking is, and only subgroup restriction sees it.** Driven on synthetic data in `backend/tests/test_calibration_machinery.py`; it is a claim about what the condition set can detect, not about the real fit, which remains unread. **The gate label:** this unit was filed as Code-gate-only because nothing is fitted; an independent reviewer argued Code + Model from `gates.md`'s leading clause, I accepted the correction, and the **architect then upheld Code only** on two grounds - you cannot hold data out from a formula, so a deterministic scorer's honest discharge is verification against analytically known values plus driven corruption; and `gates.md`'s "reliability metrics" is a **word collision**, naming the player-consistency model in `docs/models/reliability-metrics.md` rather than a reliability *diagram*. The ambiguity is filed as a defect in `gates.md` itself. **The forward-binding half is pinned by test:** when this machinery later produces v2 §7's held-out table, *that* report is Model-gated and this module is load-bearing inside it - nothing here pre-discharges it. **One arithmetic discrepancy in v3 §6 is reported rather than copied, and the label on it was wrong in both documents:** §6's own 18.6% G League share of `doubtful`, applied to the held-out 83, gives ~68 and 2.25x headroom over condition 6's floor of 30, not the "~74" and "2.5x" §6 states. **CORRECTED 2026-08-23, from a `data-engineer` lane's reviewer:** removing a G League share removes G League and leaves `Rest`, a coach's decision on the same footing as the Two-Way recall whose removal §6 endorses, so both §6's figure and this note's were **non-G-League**, not health-only; this note inherited §6's label while disputing §6's number. **And the correction is not yet safe to paste:** the reported held-out reason breakdown (`Injury/Illness 68, G League 10, Rest 4, Concussion Protocol 1, Reconditioning 1`) sums to **84** against the published **83**, so non-G-League is 74 from the breakdown and 73 from the published count - and **74 is exactly the figure under correction**, the first account of it needing no error, which means replacing it with 73 swaps the base silently. **The extra row is now explained, and not the way this note first guessed.** `scripts/cohort_predictor_crosses.py` (#97, on `main`) states that the reason breakdown is over the **canonical** selection while the published 83 is the **direct** count, the two differing by the participation join (13,789 vs 13,598 cohort-wide). The 84th row is one canonical `doubtful` row with no participation outcome, not a double-categorised row, so direct non-G-League is **bracketed in [73, 74]** by two committed integers and a subset relation - derived, not hedged. This also means 74 is the **canonical** non-G-League count rather than a rival base, so v3 §6's sentence carries two population errors and only one was being corrected. **A second error underneath it:** 18.6% is cohort-wide and does not transfer - the direct held-out share is 10/83 = 12.05% - so this note's ~68 was five rows low *and* rested on a transfer it never stated. All four readings clear the floor of 30 by more than 2x, so no verdict moves. Any health-reason restriction is **reason-derived and approximate** in any case: 7 of 97 `Rest` rows carry "Left Knee - Injury Management", so stated reasons misclassify in both directions, and `AGENTS.md`'s rule that rest is laundered as ailment is true but incomplete. The 41/221 share itself is quoted from v3 and is **not** derivable from anything on `main`, since the manifest carries no status-by-reason cross; neither is the breakdown, so every figure here is conditional on it as reported. **2026-08-23, later the same day: two more gate-reporting instances and a near-miss that would have voided the mutation evidence entirely.** Closing this lane's own "could not verify" - that some third command might still be reported narrowly - found two, in opposite directions. `ruff format --check .` **is** a CI gate (`.github/workflows/ci.yml:62`, no `continue-on-error`) and the lane had inherited a belief that it was not; both of its source files failed it, so the branch and only the branch would have broken CI, and formatting them then moved four mutation anchors, which the harness reported as **harness failures rather than survivors**. The mirror instance is the one worth carrying: run from the **repository root**, those same commands report 15 lint errors and 13 unformatted files, because every Python job in `ci.yml` declares a working directory of `backend`, `frontend` or `userscript`. **A gate quoted without its working directory is as unquotable as one quoted without its file count**, and this direction fails as a *false alarm* - acting on it means editing other lanes' files during a merge freeze. It also exposes a structural fact that is nobody's defect and somebody's decision: **no CI job lints or type-checks `scripts/`, and no job executes `scripts/mutate_calibration.py`**, so every mutation harness in this repository - the artifacts several backlog items cite as their evidence - sits outside the gate that evidence is for. **(Corrected 2026-08-26, twice over. The type-check half was false when written: `backend/pyproject.toml` sets `[tool.mypy] files = ["src", "tests", "../scripts"]` on purpose and `ci.yml`'s backend job runs a bare `mypy`, so `scripts/` has been type-checked in CI throughout - driven by planting a `return "not an int"` in `scripts/predict_union.py`, which makes that bare `mypy` fail across 201 source files. The lint half was true and is now closed: a repo-root `ruff.toml` extends the backend rule set over `scripts/`, the backend job runs `ruff check scripts` and `ruff format --check scripts` from the repo root, and `scripts/eslint.config.js` covers the two JavaScript probes that no gate reached at all. **The surviving clause is the one that matters**: `mutate_calibration.py` is still executed by no job, so its verdicts remain ungated and its correctness still depends on somebody remembering to run it.)** (Corrected after review: the first version of this sentence said no job *runs* `scripts/` and that every Python job declares a working directory, and both are false - `ci.yml` executes `backlog_graph.py`, `check_no_secrets.py` and `run_metrics.py` across four jobs, and `backlog-graph` and `secrets` declare no working directory. The narrow claim carries the point; the broad one was reached by generalising from the single job that had been read, and the same generalisation is what excused not reading the others.) **The near-miss is the more transferable half.** The obvious fix for stale anchors is to assert them in tests; written into `test_calibration_machinery.py`, which is *the module the harness runs*, they would have failed under every mutation - because the mutated line no longer matches its own anchor - and the harness scores any failure as CAUGHT. All 44 mutations would have been marked caught by the anchor test rather than by the detectors, and the printed `44 caught, 0 survived` would have established nothing. Driven with M02 applied before being fixed, and moved to `backend/tests/test_mutation_harness_integrity.py`. The rule: **any test added to the module a mutation harness targets makes that harness weaker, and the weakening is invisible in its output** - the false-zero shape presenting as the reassuring number. Five anchor pathologies were then each driven red, one of which passed at first because the *driver* failed to apply, which is the rule that harness states about itself catching its own author. Counts at that point: module tests 127, harness-integrity tests 4, **44 mutations, 44 caught, 0 survived, 0 harness failures**. **Audit closed the same day, clean, with one caveat the totals hide.** Each of the 44 mutations was applied in turn and the *names* of the failing tests recorded, to answer whether any test in the harness's target module fails merely because a mutation is applied: **zero false catches**, and the module's only text-asserting test is a catcher for none of the 44. But **19 of the 44 are pinned by exactly one test**, so deleting any one silently unpins a mutation while the harness still reports 44 caught - the same false-zero shape one level up, and the reason a dropped test name from `scripts/test_name_diff.py` is worth reporting every time. **(Corrected 2026-08-26. Both figures above were stated in the present tense about a set that had already changed underneath them: the audit was a throwaway covering `M01`-`M44`, eleven more mutations were added afterwards, and nothing re-ran it. Re-measured at `28d0d88` over all 55: **27 pinned by exactly one test**, 72 distinct tests catch something, and the widest catcher accounts for 5 - so no test catches every mutation and the anchor pathology is absent, which is the mechanical half of "zero false catches". Twenty of those 27 are in the original `M01`-`M44`, against the nineteen recorded; the extra one is not attributable from here, and the counting unit is one candidate, since this figure now counts test *functions* and the throwaway's unit was never written down. The audit is no longer a throwaway - `scripts/mutate_calibration.py` reports both figures on every run, because a `--catchers` mode would have had the same failure mode as the defect: nobody opting in.)** The fix that produced the audit had its own hole, found before review reported: the anchor reader resolved its path constants last-wins, so a rebound name would have made it check the wrong file and report every anchor present; rebinding is now refused, three cases driven red. It had already refused f-strings, concatenations and nested tuples - **four exotic forms defended, the mundane one missed**. Full suite **1918 passed, 32 deselected**, prediction of 1918 stated first. And an inherited figure corrected: the full suite takes **9m23s**, not the ~3 hours this lane had been quoting and planning around. **Sixth and seventh reviews, eleven survivors across the two.** The headline is that a guard which enumerates syntactic forms is always one form behind: the rebinding refusal added last commit caught the one form its author had driven and let four siblings through, one of which the reviewer had already reported. It is now a predicate over a single `ast.walk` rather than a list of statement shapes. Also: four *published* dataclass fields that no assertion read, including `brier_score`, which could be doubled with 127 tests green; `len(MUTATIONS)` shown not to be load-bearing, since entries can be appended where the reader cannot see them and one mutation's content can be substituted for another's under a fresh name; and a declaration-twin audit over all ten `DECLARED_CONVENTIONS`, since a test that asserts a convention *string* verifies the sentence rather than the behaviour. All ten have a caught implementation mutation; seven are now permanent. 55 mutations, 55 caught.
- **Depends on:** `injury-report-ingest`, `injury-report-historical-backfill`, `injury-conversion-cohort-population`, `participation-ledger`

Empirical conversion of report status to actual play rate, segmented by team, player and game context. QUESTIONABLE is not a coin flip and varies meaningfully by source - this rate is itself a modelled quantity.

### `layer-purity` - Enforcing layer purity in the schema and tests

- [x] **done**
- **Depends on:** `db-foundation`, `projection-blending`

ADR-008 / R41. Every stored quantity records which layer it belongs to (observation, projection, availability, valuation, terminal). A test rejects any flow from a higher layer into a lower one - make it inexpressible rather than merely documented, the same pattern used for the Postgres seam. Specifically: no ranking, AAV or composite value may be an input to any earlier layer at any weight. External aggregates may only appear on the comparison side of model-vs-market, never in a blend.

DONE. `backend/src/hoops_gm/db/layers.py` holds the ordering, the per-table assignment and the flow rule; `db/models/__init__.py` calls `validate_layers` at the one point `Base.metadata` is complete, so an unlayered table or a backwards foreign key is an **ImportError**, not a test somebody might skip. Membership comes from two closed sets rather than a pattern over spellings: every mapped table must be assigned, and every declared foreign key is a flow. `data_layer_registry` (migration 0019) stores the same fact in the database, seeded from a literal snapshot so a new table's layer goes through review rather than following the code silently. The flow rule is an explicit 17-edge `PERMITTED_FLOWS` set, **not** a comparison of ranks: an independent review showed the rank version permitted `valuation -> market`, `availability -> market` and `projections -> market`, each of which is R38 (our own fused value laundered back as somebody else's evidence). Clause 3 is a statement about which edges exist, and no total order can express "A must not reach B" while also placing A before B. `LAYER_RANK` survives only as a descriptive label on the stored row. A second review then showed that the layer edge `observations -> market`, meant as "identity only", admitted all 29 observations tables including `draft_events` - prices our own recommendations can have moved - so the edge is narrowed per-table by `MARKET_IDENTITY_SOURCES`, which fails on a stale entry. The same review defeated two guards that asked how an import was *spelled* rather than what it did: the validator could be shadowed by a local no-op of the same name with every gate green, and a commented-out import satisfied the module-coverage check. Both now ask the artefact - a subprocess imports the package and looks for what is unmapped. A third review found ten more, two blocking, all the same class: **half the import-time enforcement was never driven through the import**, so rebinding `validate_layers` to the assignment half alone disabled the whole flow check with 62 tests green; and the stale-identity branch written to close the second review had no test at all, so replacing its generator with `[]` was invisible. Both are now parametrised over both halves. The same review showed the registry recorded only `layer_rank`, which leaves the discredited **rank comparison** as the sole rule expressible in SQL - so 0019 also creates and seeds `data_layer_flows`, the 17 permitted edges as rows, compared against `PERMITTED_FLOWS` by reading the migrated store rather than the migration literal so a future migration may still change the rule. **Scope, stated: verified at `f3e2c53` and re-verified unchanged after rebasing onto `5926850`, this rejects backwards flow among 41 tables and 62 declared foreign keys, of which 0 were violations, and only 5 of those 62 are cross-layer at all - the guard constrains almost nothing that exists today and exists to fail on arrival when `expected-games` and the valuation chain land.** It reads declared foreign keys only: a value copied between layers in Python leaves no key and is invisible to it, which is pinned as `FLOW_SCAN_LIMIT`; and it assigns whole tables, so a market quantity on a non-market table (`draft_events.amount`) is out of reach, pinned as `GRAIN_LIMIT`. One review finding is **open**: whether `source_games_played_assumptions` belongs at `market` rather than `projections` - the second review argues the real answer is a separate `SOURCE_PROJECTIONS` layer for imported estimates, which would make "the availability model never blends this" a mechanism rather than a convention. Needs `quant` or the architect. Three independent reviews found twenty-nine findings between them and the rate did not fall; a fourth exact-head review then found seven more, two blocking. Both blocking ones were **mirrors of round-three fixes that had been mutation-proved in one direction only** - deleting the *assignment* half of `validate_layers` left both arms of the both-halves test green, because the flow half also raises for an unassigned table; and the model/migration CHECK comparison read `0019`'s literal rather than what `upgrade()` built from it, so widening the constraint at the call site was invisible. A third was factual rather than structural: `FLOW_SCAN_LIMIT` named two columns as live instances of the defect it describes and all ten are foreign-system identifiers, which three passes missed because the reproducible count beside the claim made the claim look checked. All seven closed; six mutation-proved with the reviewer's own mutations.

### `lineup-autoset` - Implementing scheduled lineup auto-set

- [ ] **pending**
- **Depends on:** `automation-guardrails`, `deadline-model`, `injury-report-ingest`, `lineup-optimizer`

Scheduled auto-set with a pre-lock injury-report refresh and evaluation pass, routed through the automation guardrails.

### `lineup-optimizer` - Building the lineup optimizer

- [ ] **pending**
- **Depends on:** `availability-model`, `punt-builds`, `schedule-density`, `schedule-ingest`

Optimal daily/weekly lineups from projections x p(play), schedule density, category needs and roster eligibility rules.

### `list-perturbation` - Building perturbed lists for blind testing

- [ ] **pending**
- **Depends on:** `aav-blending`

Generate test lists with known distortions injected - shuffled tier, inflated position, planted overvalue at a specific slot - so adherence is measured against known ground truth rather than inferred. Owner must not know which list is perturbed at capture time; sealed record in docs/mocks/lists/ opened only afterwards. Mocks only, never a real draft. Perturbation records are terminal experimental metadata under ADR-008 and must never feed a model.

### `live-draft-availability` - Recomputing values from live availability during the draft

- [ ] **pending**
- **Depends on:** `contingent-value`, `draft-day-synthesis`, `draft-tracker`, `preseason-news-ingest`

News breaking mid-draft - a player out, suspended, a rotation change - updates the AVAILABILITY layer and the valuation and dollar values recompute downstream. It must not patch rankings directly: a hand-edited ranking is an aggregate with no lineage and reintroduces exactly the contamination ADR-008 prevents. Contingent value recomputes with it, so the overlay shows the beneficiaries as well as the casualty.

### `live-lock-advisor` - Exploiting per-player lock timing for late-slate decisions

- [ ] **pending**
- **Depends on:** `deadline-model`, `lineup-optimizer`, `live-matchup-state`

Fantrax locks each player individually at his own tipoff, so late-slate decisions can be made with early-slate results already in hand. If the early games leave the matchup needing blocks and comfortably ahead in assists, the correct late start changes. Combines live matchup state with remaining unlocked players to recommend the category-optimal late-game start. A category-management edge, not merely a punctuality one.

### `live-matchup-state` - Computing live matchup state

- [ ] **pending**
- **Depends on:** `availability-model`, `fantrax-private-adapter`, `live-poller`

Map live box scores onto my roster to produce per-category running totals versus my opponent, with availability-adjusted games remaining rather than raw scheduled counts.

### `live-poller` - Building the live game poller

- [ ] **pending**
- **Depends on:** `nba-stats-ingest`

Poller against cdn.nba.com/static/json/liveData/ scoreboard and boxscore endpoints. ~5s interval, active only while games are live, with backoff.

### `market-model` - Building the empirical market model

- [ ] **pending**
- **Depends on:** `aav-source`, `mock-ingestion`

Empirical ADP and auction price curves built from the 10+ mock corpus, reflecting real drafting behaviour rather than published estimates. NOTE: league is auction, so the corpus must be predominantly AUCTION mocks - snake mocks cannot calibrate inflation curves or budget behaviour.

### `mock-ingestion` - Ingesting external mock draft results

- [ ] **pending**
- **Depends on:** `draft-format-abstraction`, `player-identity`

Capture results from external mock sites (ESPN, Yahoo, FantasyPros, RTSports) via paste or CSV import, resolved through the player identity layer. Different DOM so no bridge rehearsal, but the results are the market corpus. NOTE: league is auction, so the corpus must be predominantly AUCTION mocks - snake mocks cannot calibrate inflation curves or budget behaviour.

### `model-vs-market` - Building the model-versus-market divergence report

- [ ] **pending**
- **Depends on:** `layer-purity`, `market-model`, `risk-adjusted-valuation`

Name where our valuation disagrees with the market. This is the edge stated explicitly: which players to target because the market underrates them, and which to let go because it does not.

### `multi-user` - Adding multi-user support

- [ ] **pending**
- **Depends on:** `db-foundation`

Auth, per-user Fantrax credentials and league scoping so one or two leaguemates can use the tool.

### `notification-engine` - Building the deadline notification engine

- [ ] **pending**
- **Depends on:** `deadline-model`

Read-only alerting, carrying none of ADR-005 write-path concerns. Configurable lead times per deadline type. Contextual rather than chronological - "lineup locks in 30 minutes and two of your players are on teams already ruled out" beats a bare countdown. Actionable, linking to the relevant view. Quiet hours and severity tiers so the system stays worth listening to. Scheduler must be PLUGGABLE (R42) so the host decision can be made separately.

### `opponent-calibration` - Calibrating simulated opponents from mock behaviour

- [ ] **pending**
- **Depends on:** `blind-mocks`, `market-model`

Tune the draft simulator opponent models from observed behaviour in the mock corpus rather than invented priors, for both snake and auction. NOTE: league is auction, so the corpus must be predominantly AUCTION mocks - snake mocks cannot calibrate inflation curves or budget behaviour.

### `overlay-auction-panel` - Building the auction overlay panel

- [ ] **pending**
- **Depends on:** `auction-budget-manager`, `auction-inflation`, `blind-mocks`, `bridge-overlay`

AUCTION IS THE CONFIRMED FORMAT (2026-08-17) - this is now critical path, not insurance. Auction draft surface: current nomination, inflation-adjusted max bid, value versus standing bid, budget and slots remaining, tier-exhaustion alerts. Optimised for a seconds-long bid clock - one number, big and unambiguous.

### `overlay-draft-panel` - Building the draft-day overlay panel

- [ ] **pending**
- **Depends on:** `bridge-overlay`, `draft-recommender`

DEPRIORITISED - league confirmed auction on 2026-08-17. Snake is retained for multi-format support and for ingesting snake mock corpora, but is no longer a draft-day deliverable. Snake draft surface: compact, collapsible, keyboard-toggled Shadow-DOM panel docked in the Fantrax draft room, positioned so it never obscures the draft board or player list. Must be sufficient to make a pick without leaving the tab. Fantrax must be the visible active tab during a draft because Chrome throttles background-tab timers to ~1/min after 5 minutes hidden, stalling Fantrax own draft polling.

### `participation-ledger-population` - Populating the participation ledger at season scale

- [x] **done** - Driven 2026-08-22 and **the count is inseparable from its
  store**, because that separation is what made this item's status disputed
  within `main` itself. The ledger holds **43,037 participation rows over 596
  players across 1,227 of 1,230 final games** (164 game dates, 26,651 box
  scores, schema `0016`) at
  `C:\Users\steverones\hoops-gm-data\hoops_gm.db`. Committed census:
  `docs/adapters/participation-ledger-2025-26-coverage.json`; narrative and
  rebuild recipe: `docs/adapters/participation-ledger-store.md`.
  **Both prior reports were correct.** A handoff entry reporting the ledger
  populated and this file's `injury-status-conversion` entry reporting "the one
  real database holds **0 rows**" had queried two different SQLite files that
  share the basename `hoops_gm.db`:
  `backend/src/hoops_gm/core/config.py:94` anchors the default relative SQLite
  path to `REPO_ROOT`, so every worktree resolves the identical
  `sqlite:///./hoops_gm.db` to a **different, separately-empty file**. The
  coordinator's search across nine worktrees plus the main checkout could not
  have found the real store, which sits *outside every checkout* so that
  `git worktree remove` cannot destroy hours of throttled fetching. **Exhaustive
  over the wrong domain** - and a verified absence is a statement about the
  places you looked, not about the world.
  The gaps are the three 2025-11-19 games `0022500259`/`0022500260`/`0022500261`,
  which carry no `boxScoreSummary` body at source while neighbouring
  `0022500258` does; under R35 they contribute no rows and nothing is inferred
  from their silence. Coverage is **measured, not assumed**: absences are 16,447
  explicit rows (`inactive` 10,937, `did_not_play` 4,426, `did_not_dress` 1,007,
  `not_with_team` 77) rather than missing ones, and `inactive_list_available` is
  true for all 43,037, so no row stands in silently for an endpoint that stopped
  reporting. The tip-off contamination proxy was re-derived independently at
  **1,227 == 1,227, clean**.
  The repair for the underlying defect is `hoops_gm.availability.coverage`:
  `LedgerCoverage` holds the counts and the `StoreIdentity` as fields of one
  frozen record, so **there is no public path to a count in that module without
  the path it was read from**, and an unmigrated store is reported by name
  rather than as a bare `no such table` traceback.
- **Depends on:** `participation-ledger`, `nba-stats-ingest`

**The critical path of the entire auction chain, and until this item existed the
backlog said otherwise.** `availability-model` needs per-game participation
labels. `participation-ledger` is marked `done`, `schedule-density` is `done`,
and `injury-status-conversion` therefore shows **zero open dependencies** — the
graph reports it ready to start. It is not: the ledger's *ingest path* exists
and the ledger is not *populated* at season scale, and nothing downstream can be
fit against labels that have not been fetched.

**This is the second instance of one pattern, and the first is three items
away.** `injury-conversion-cohort-population` exists as its own item for exactly
this reason, and its text names the failure: conflating "the tool exists and
passes its tests" with "a representative cohort has been populated with it" is
what let `injury-status-conversion` appear structurally ready — every dependency
it listed marked `done` — while the cohort it actually needs did not exist. The
identical conflation was sitting one layer down in `participation-ledger`, and
it survived because the fix last time was a new item rather than a rule.

**The rule, since it will recur:** on any item whose product is a populated
table, `done` means *the path works*, not *the data is there*. Those are
separate claims with separate evidence and they need separate items. Check every
remaining ingest item against it rather than waiting for the third instance.

**Why it is sequenced first rather than by dependency order.** Its cost is
wall-clock, not effort — participation ingest was independently measured to
dominate injury-report fetching by roughly 4x in elapsed time, under a
throttle that cannot be raised without changing our posture toward the source.
Effort-bound work can be parallelised across lanes; a fetch budget cannot.
Draft day does not move, and on 2026-08-21 it was 58 days out.

Done when the ledger holds a genuine multi-season cohort, its coverage is
measured rather than assumed, and gaps are explicit rows rather than absent ones
— `availability-model` must be able to tell "he did not play" from "we have no
observation", which is the distinction the whole availability thesis rests on.

Gate: Adapter gate — this runs the existing ingest against the live source at
scale. No new model.

### `preseason-news-ingest` - Ingesting preseason availability news for draft day

- [ ] **pending**
- **Depends on:** `injury-report-ingest`, `player-identity`

R40. The NBA official injury report is published per-game and the season opens AFTER the 18 October draft, so injury-report-ingest covers nothing on the day it matters most. Build a separate path for preseason reporting, training-camp news, suspensions and Fantrax player notes. Must be working before the rehearsal window opens on 5 October, not during it.

### `projection-blending` - Implementing configurable projection blending

- [x] **done**
- **Depends on:** `csv-importer`

Migration-free domain/service contract over exact current verified imports:
category-wise normalized user weights, deterministic immutable profile/output
fingerprints, separate auditable manual replacements, explicit activation with
A -> B -> A currentness, and fail-closed lineage/category/cohort validation.
Ratio categories blend made/attempt volume. Games played, availability,
expected games, rankings, market/mock outcomes, valuation and recommendations
cannot enter. No learned source-accuracy path exists without a preregistered
held-out experiment. Profile persistence/API/UI remain an architecture decision.

### `punt-builds` - Modelling punt builds

- [ ] **pending**
- **Depends on:** `gscore-engine`, `risk-adjusted-valuation`

Punt-config modelling with recomputed rankings per build, side-by-side comparison, and fit-to-my-current-roster scoring. Operates on risk-adjusted values.

### `rehearsal-harness` - Building the instrumented rehearsal harness

- [ ] **pending**
- **Depends on:** `blind-mocks`, `draft-day-synthesis`, `draft-simulator`, `surface-parity-tests`

Instruments the Fantrax dress-rehearsal mocks (no fewer than 10): per pick, whether the overlay alone sufficed, when the dashboard was opened and what was checked, time-to-decision, and recommendation take rate. Produces an evidence-based answer on whether a second monitor is actually needed and identifies anything repeatedly checked elsewhere that belongs in the overlay. NOTE: league is auction, so the corpus must be predominantly AUCTION mocks - snake mocks cannot calibrate inflation curves or budget behaviour.

### `reliability-ui` - Building the reliability UI

- [ ] **pending**
- **Depends on:** `frontend-skeleton`, `reliability-metrics`

Durability scorecards, B2B sit patterns, availability trend charts, and a roster-level fragility summary.

### `risk-adjusted-valuation` - Implementing risk-adjusted valuation

- [ ] **pending**
- **Depends on:** `gscore-engine`, `reliability-metrics`

Durability discount/premium layered over raw value. Separate total-value and per-game-value views so the fragile-star tradeoff is explicit rather than hidden in one number.

**Carries a registered obligation from `hashtag-projection-profile-verification` (2026-08-26).** `ProjectionImportOutcome.verification` reports per-source findings — including `scoring_identity` failures and every check that returned `NOT_RUN` — and **nothing in the codebase reads it**. This item must either consume it or state in its model card that it deliberately does not. An unread field and a field nobody needs look identical from the outside, and this project has now found that shape three times in a week; an explicit refusal is a finding, an unnoticed orphan is not. The `NOT_RUN` findings matter most: a clean return is not a clean bill, and the most common reason a check does not run is that the source did not publish what it needs.

### `schedule-cohort-fingerprint-list` - Restoring what the injury cohort manifest watches

- [ ] **pending**
- **Depends on:** `injury-report-historical-backfill`

`DEFAULT_SOURCE_FINGERPRINT_PATHS` in `ingest/injury_report/cohort_evidence.py` omits `backend/src/hoops_gm/ingest/nba/schedule.py`, which the generator directly calls (`parse_schedule`, for the `schedule_league_v2` reconciliation view — the cohort's only genuinely independent witness). Found 2026-08-20 when one change touched that file and `db/lineage.py` together: the alarm fired on the file outside the derivation and stayed **silent** on the file inside it, which is a false green, not merely a coarse one.

**The removal half is already done; only the addition is left, and only it needs a regeneration.** The untrue `db/lineage.py` entry was deleted from the manifest's `source_fingerprints` rather than refreshed, because deleting narrows an over-claim while refreshing would assert the cohort was derived with bytes it was not. The constant itself still lists `db/lineage.py` and was deliberately left alone: editing `cohort_evidence.py` stales that file's own digest, and it *is* in the derivation, so the same false-claim problem simply moves one file over. Both edits therefore belong to the regeneration, together: drop `db/lineage.py` from the constant, add `ingest/nba/schedule.py`, regenerate against the cohort database.

**Consequence to carry until then, stated because it is easy to miss:** with the entry deleted, edits to `db/lineage.py` are **no longer watched at all** by the cohort provenance alarm. That is the correct trade — the alarm was watching a file outside the derivation and missing one inside it, so it was giving a false green on the file that matters — but it means the watch set is now four files, not five, and a lane touching `db/lineage.py` will get no signal rather than a misleading one. Nothing is lost that was true; something misleading was removed.

**The removal does not survive a regeneration.** `build_manifest` computes `source_fingerprints` from the constant, not from the previous manifest, so the next regeneration re-adds `db/lineage.py` from `DEFAULT_SOURCE_FINGERPRINT_PATHS` and silently undoes the narrowing above. The deletion is a property of one stored manifest, not of the code that produces manifests — which is why both edits belong to the regeneration together and neither is safe to do alone.

**Derivation method, recorded because a standard reconstructible only from prose describing its results is not a standard.** The watch set is the set of files the generator's own call graph reaches, computed in three steps. (1) Take a **docstring-stripped AST diff** between revisions, so a comment or docstring edit is not counted as a source change. (2) Compute the **static call-graph closure seeded from the manifest's own `operator.commands`** — start from the entrypoints the manifest declares rather than from a hand-listed root, and walk both `ast.Call` nodes and bare `ast.Name` references (a function passed as a value is reached without ever being called at the call site), resolving each through a **per-module alias table** built from that module's imports, because `from x import y as z` makes the local name unrecoverable otherwise. (3) Intersect the closure against the set of **altered** files — not the union of added and altered, which is the trap that inflates the answer.

Three traps in it, all of which produced a wrong answer once. A file **added** in a revision is reached by the closure and has no previous digest, so unioning it with the altered set reports a fingerprint change that did not happen. A module imported purely for a type annotation is in the import table and not in the call graph, and including it re-creates the over-claim this item exists to remove. And the closure is only as good as the seed: seeding from a hand-written root list reproduces exactly the omission (`ingest/nba/schedule.py`) that was found by accident, which is why it seeds from `operator.commands`.

**Pinned files, so the next lane does not re-derive the set:** `ingest/injury_report/cohort_evidence.py`, `ingest/injury_report/manifest.py`, `ingest/nba/schedule.py`, and the two generator modules named in `operator.commands`. That is the intended post-regeneration watch set; anything else appearing in it means the closure walked somewhere unexpected and the difference is the finding.

### `schedule-grid-contract-artefact` - Failing CI when the schedule grid response shape drifts

- [ ] **pending**
- **Depends on:** `schedule-grid-early`, `schedule-grid-ui`

**Precondition for the next frontend increment against this API**, not an
open-ended improvement. Named that way deliberately so it cannot quietly become
permanent.

Nothing currently ties the frontend's wire assumptions to the backend's actual
output. `frontend/src/api/endpoints.ts` hand-writes the response contract, and
`frontend/src/test/fixtures/schedule-grid-current.recorded.json` is a snapshot
captured by hand from a running service — so it catches drift only when someone
thinks to re-record, which is to say exactly when nobody is looking for it. Both
sides can be internally green and mutually wrong.

Owned by `backend`, because the artefact has to be produced where the response
model lives: a backend test serialises a real `ScheduleGridResponse` to a
committed JSON file, and the frontend suite loads that file instead of a
recording. One artefact, both sides, fails in CI on drift rather than in a
browser. Gate: Code.

Deferred from 2026-08-20 by the coordinator with the mechanism stated: building
it while backend PR #38 was in final review would have restarted the review
clock on an otherwise-ready head, and the risk it mitigates has no active source
until the next increment is scheduled against this contract.

### `schedule-grid-refusal-discriminant` - Distinguishing nine conditions that share one refusal code

- [ ] **pending**
- **Depends on:** `schedule-grid-early`, `schedule-grid-ui`

`schedule_grid_incomplete_evidence` is raised from nine places in
`backend/src/hoops_gm/api/routes/schedule_grid.py`, on four different objects:
the refresh's completeness evidence, the cohort it describes, the league's team
rows, and the league's scoring calendar. They call for different operator
actions — a refresh that cannot state its completeness needs the schedule
re-importing, while a scoring period the league has no row for needs the
calendar corrected, and re-importing the schedule will never create one.

A consumer given only the code cannot tell which. The dashboard currently names
all three families in one message and defers to the backend's `detail` prose for
which applies, which is honest but is the weakest form of the information: it
cannot be branched on, and it puts the burden on the reader at the moment they
are least able to carry it.

This has already produced two defects on the frontend, both caught in review
rather than by any test. Copy written against one condition asserted that the
refresh "cannot state what it imported" and was rendered directly above a
backend detail saying it had stated it and imported a playoffs cohort. The
correction then asserted a single remedy — re-import the schedule — which is a
confident, wrong instruction for the three conditions rooted in the league's own
data. Each was true of the condition it was written against.

Owned by `backend`. Either split the code so each family has its own, or add a
machine-readable discriminant to the error body alongside `error`. Gate: Code.
The frontend must not recover specificity by matching on `detail` text — that is
the form-over-meaning coupling `AGENTS.md` warns about and would break silently
on a reword.

### `schedule-grid-reference-distribution` - Comparing a team's period count against its own normal

- [ ] **pending**
- **Depends on:** `schedule-grid-ui`

ADR-012's 2026-08-17 amendment requires a team's raw scheduled-game count be
shown against **both** the league-wide period baseline and *that team's normal
distribution*. `schedule-grid-ui` ships the first and deliberately defers the
second; without this item the amendment is half-implemented and nothing outside
this line says so.

Owned by `quant`, not `frontend`, because "normal" is not arithmetic. It
requires choosing a reference set — whether to include fantasy playoff periods,
partial first and last periods, and the league-wide sparse periods (In-Season
Tournament, All-Star break) that the same amendment singles out as special. A
baseline that includes All-Star week depresses the mean and makes a genuinely
sparse week read as ordinary; excluding it needs a rule for what counts as
league-wide sparse, and that rule is a threshold. The amendment ties the output
to trade targeting, so it is a number a decision rests on.

**Gate:** Model, not Adapter. Needs held-out evaluation of whether the deviation
measure identifies the periods it claims to, a model card in `docs/models/`, and
an explicit statement of what the reference set cannot see. Until then the grid
shows the raw row, which is itself the team's distribution laid out in order —
the missing piece is the quantified comparison, not the evidence.

### `schedule-pending-persistence` - Making the pending set verifiable

- [ ] **pending**
- **Depends on:** `schedule-ingest`

`schedule_content_version` fingerprints persisted `team_schedule` rows, and a pending game has none, so the registered version does not cover the pending set: two cohorts differing only in which games are pending share a version. Measured rather than reasoned to — the demo seed's 10-source cohort and its 12-source, 2-pending successor both fingerprint to `9bcac1c60490b41a`, and `test_the_schedule_version_does_not_change_when_only_the_pending_set_changes` pins it. Consequently `verify_refresh` detects a forged *resolved* cohort but not a forged pending list, and a consumer must not cache the pending set keyed on the schedule version alone. Closing it means persisting pending games as first-class rows — schema, migration, and a fingerprint spanning both populations. The gap is narrow and self-closing per game as the Cup bracket is drawn, which is why it was filed rather than added to the ADR-013 unit.

### `schedule-ui` - Building the schedule tracker UI

- [ ] **pending**
- **Depends on:** `availability-model`, `frontend-skeleton`, `playoff-schedule`, `schedule-ingest`

Games-per-week grid showing availability-adjusted expected games (scheduled games x p(play)) rather than raw counts, plus streaming windows and fantasy playoff week planning.

### `scorecard-ui` - Building the live scorecard UI

- [ ] **pending**
- **Depends on:** `frontend-skeleton`, `live-matchup-state`

Live scorecard fed by SSE: category-by-category win/loss/margin, games remaining, and projected final with confidence bands derived from production and availability variance.

### `shutdown-risk` - Modelling late-season shutdown risk

- [ ] **pending**
- **Depends on:** `availability-model`, `playoff-schedule`

Shutdown/tanking risk for the fantasy playoff weeks: team elimination probability crossed with player age, minutes load, injury status and contract situation. Priced into draft and deadline decisions months ahead.

### `stock-watch` - Building the stock watch dashboard

- [ ] **pending**
- **Depends on:** `contingent-value`, `frontend-skeleton`, `injury-report-ingest`, `risk-adjusted-valuation`

Live value-mover dashboard: injury news lands, affected players are recomputed via the contingent value graph, and the UI surfaces who moved, why, and whether they are available in your league.

### `streaming-engine` - Building the off-night streaming engine

- [ ] **pending**
- **Depends on:** `games-cap-tracker`, `lineup-optimizer`, `schedule-context`

Streaming recommendations for light NBA slates, targeting your weakest categories and ranked by expected marginal category impact rather than generic player value.

### `strength-of-schedule` - Building strength of schedule, weighted by opponent quality

- [ ] **pending**
- **Depends on:** `schedule-context`, `gscore-engine`

Per-team/per-week strength of schedule, weighting scheduled opponents by quality (via `opponent_context`'s per-category defensive profiles) and expressing the result relative to league average. Deliberately sequenced in Phase 5, not alongside `schedule-density`/`schedule-context` in Phase 3/4, because it needs a settled valuation to weight the schedule by (ADR-011) — building it earlier would mean weighting by a placeholder value that gets thrown away once real projections land. Feeds `draft-recommender`, gives `games-cap-tracker` and `playoff-schedule` a second, value-weighted pass beyond raw game counts, and (draft-day only) `auction-values`, using projected rather than known opponent quality since the season hasn't started.

### `supervised-mode` - Implementing supervised decision mode

- [ ] **pending**
- **Depends on:** `automation-audit`, `automation-guardrails`

Default mode: backend computes a recommendation, overlay highlights it in the Fantrax UI, user clicks to confirm. Covers both lineup and draft decisions.

### `surface-parity-tests` - Enforcing surface parity

- [ ] **pending**
- **Depends on:** `dashboard-evidence-views`, `overlay-auction-panel`, `overlay-draft-panel`

Test-enforced rule that no draft-critical decision is available in only one surface: anything the overlay recommends must be inspectable in the dashboard, and anything the dashboard supports must be actionable from the overlay.

**Three documents asserted this was already enforced.** On 2026-08-21 `plan.md`, `.github/agents/frontend.md` and `.github/agents/bridge.md` each stated parity enforcement in the present tense while this item sat pending behind three pending dependencies — there is no second surface to compare against, so the test is not merely unwritten but **unwritable**. All three now name this item and say plainly that parity is a convention until it closes. Recorded here rather than only in the handoff, because the next lane to read those files is the one who needs it: **when you write the test, the claims that were waiting on it are the three sentences to make true again.**

### `trade-evaluator` - Building the trade evaluator

- [ ] **pending**
- **Depends on:** `playoff-schedule`, `punt-builds`, `risk-adjusted-valuation`, `schedule-ingest`, `shutdown-risk`

Multi-asset trade evaluation: category deltas, punt-build impact, schedule and fantasy-playoff-week impact, rest-of-season value, and durability/shutdown risk on both sides. Per ADR-012, schedule impact explicitly includes the first-class per-week game-count shape (including two-game/five-game H2H periods, front/back-loaded weeks, and sparse league-wide In-Season Tournament/All-Star-break periods). Surface schedule-driven trade targets and high-value weeks rather than treating schedule as a generic rest-of-season adjustment.

### `trade-finder` - Building the trade finder

- [ ] **pending**
- **Depends on:** `trade-evaluator`

Scan league rosters for mutually beneficial trades from category surplus/deficit matching and differing risk tolerance between managers.

### `vitest-explicit-timeout` - Setting an explicit test timeout the metrics job can read

- [ ] **pending**
- **Depends on:** `ci-pipeline`

`scripts/run_metrics.py` prints each test duration against its baseline but
deliberately prints no headroom against the timeout, because `frontend/vite.config.ts`
sets no `testTimeout` and 5,000 ms is therefore vitest's *implicit default*.
Hard-coding that number here would be the `README.md` item-count failure with a
millisecond value in it: a constant copied out of someone else's tool, correct
on the day it was written and stale the day they change their default.

Set an explicit `testTimeout` in `vite.config.ts`, then have `run_metrics.py`
read it and print each duration as a fraction of the limit that actually
applies. The value becomes a decision this repository has made and can defend,
rather than one it inherited without noticing. Keep it printed, never asserted -
a headroom column that fails a build is the threshold this tooling exists to
avoid.

`frontend` owns it — it is their config and they will be in that file. The
script half is cross-boundary: no row in `docs/governance/ownership.md` covers
`scripts/`, so whoever picks this up should expect to agree that with
`architect` rather than infer it.

### `waiver-clear-monitor` - Monitoring waiver clears and free agent availability

- [ ] **pending**
- **Depends on:** `deadline-model`, `fantrax-private-adapter`, `notification-engine`, `risk-adjusted-valuation`

The single largest timing edge. When a player clears waivers he is first-come-first-served, and a useful player clearing at 3am goes to whoever is present. Compute exact clear moments from league settings, monitor the free agent pool, and alert on players clearing who match this roster category needs. Read-only; automatic claiming is a separate write-path item requiring safety review and owner enabling.

### `zscore-engine` - Implementing the 9-cat z-score engine

- [ ] **pending**
- **Depends on:** `expected-games`, `projection-blending`, `scoring-profiles`

Z-score valuation for FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO. Volume-weighted impact for percentage categories (not raw pct) and correct TO sign handling. League-context replacement level from league size x roster spots.



### `coordinator-register-triage` - Promoting every action in the coordinator register into a task

- [ ] **pending**

`docs/governance/coordinator-register.md` holds 320 findings and rules from the
coordination layer. **It is a record, not a task list**, and its `**Status:**`
field does not mean what it looks like - `pending` there means "recorded", not
"awaiting work", so `c292` *"collection is not execution"* is `pending` and is a
rule nobody will ever do.

Seven entries that named real, unscheduled work were promoted into this file on
2026-08-26. **Nobody has read the other 313 for the same property.** The
promotion was done by reading the entries the coordinator could recall, which is
the same sampling that let the register accumulate unlanded work in the first
place.

Read it end to end and promote anything that names an action somebody must take.
The property to look for is **not** in the heading and **not** in the status
field - three separate classifications on those were each wrong, once by an
order of magnitude. It is only visible in the body.

### `record-refresh-lineage-relabel` - Fixing record_refresh's in-place lineage relabel with the cohort regeneration

- [ ] **pending**
- **Depends on:** `schedule-cohort-fingerprint-list`

**Latent defect on `main`, pinned rather than fixed.** `record_refresh` relabels
the lineage source in place, so a refreshed record reports a provenance it did
not have. Promoted from coordinator register `c288`.

Routed to `data-engineer` **as a joint unit with the cohort manifest
regeneration** (`c301`): the manifest pins six source files by whole-file
SHA-256, so fixing the relabel invalidates the manifest, and regenerating the
manifest without the fix bakes the wrong lineage in. Doing either alone is worse
than doing neither - which is why this is one item and not two.

**Unblocked 2026-08-27 by ADR-019, with a procedure.** The blocker was never the
fix; it was that nobody had ruled whether a lane may regenerate another lane's
fingerprinted artefact, and a belief that regeneration needed live
`stats.nba.com` sweeps. Both are settled. Regeneration is one offline command
against stores already on disk - driven at the unmodified tree on 2026-08-27,
exit 0, no network, **1664 leaves, 0 added, 0 removed, 1 changed**, and the one
change is `operator.commands[8]` echoing the `--out` path.

The procedure: fix `record_refresh`, regenerate in the **same commit**, and
attach the `scripts/manifest_leaf_diff.py` transcript. If the only moved leaves
are under `operator.source_fingerprints` and `operator.commands`, no cohort
number moved and the change stands. **Any other moved leaf stops for `quant`,
pre-unblind.** `data-engineer` still owns the artefact and reviews; the leaf diff
is what makes the regeneration reviewable rather than trusted.

### `derived-value-merge-gate-audit` - Auditing which derived values auto-merge clean with no gate

- [ ] **pending**

**Open question with no owner**, promoted from coordinator register `c307`.

`docs/backlog.md`'s header is derived and recomputed; `docs/handoff.md`'s entry
count is derived and predicted. Both have a check. The question nobody has
answered is **which other derived values in this repository merge cleanly while
being wrong** - a value computed from a file that both sides of a merge appended
to will auto-merge into a number that matches neither side and fails nothing.

Enumerate them, then decide per value whether it needs a recount, a refusal, or
nothing. The enumeration is the deliverable; the fixes may each be small.

### `demo-sanity-numbers-gate` - Gating the sanity numbers published in docs/demo.md

- [ ] **pending**

Promoted from coordinator register `c308`. `docs/demo.md` publishes figures a
reader uses to decide whether their local demo came up correctly. **Nothing
checks them against what the demo actually produces**, so they can silently
invert: a reader whose demo is broken compares it against a number that is also
broken and concludes it is fine.

This is the "a check that can silently invert" shape. The cheap form is a test
that regenerates the demo and asserts the published figures, which also means
the figures cannot drift without someone noticing.

### `ci-head-verification-tool` - Verifying what CI actually did on one exact commit

- [x] **done** - Landed 2026-08-26 as `scripts/check_ci_gates.py` with
  `backend/tests/test_check_ci_gates.py`. Seven tests, six mutations driven red,
  zero escaped.

Promoted from coordinator register `c315`. Three GitHub summary fields were each
read as a result on 2026-08-26 and each was wrong: `mergeStateStatus=CLEAN` on a
pull request with **zero** checks on its head, `conclusion=failure` on a run
where **no job was ever assigned a runner**, and `conclusion=cancelled` on a run
with six jobs green and **zero** failed steps.

The tool reports gate count, gate names, failed-step count, and the
**skipped-versus-starved split** - `jobsWithRunner=9/10` cannot distinguish a
job skipped by design from one starved of a runner, and both have no runner. It
refuses a short SHA **before querying**, because `?head_sha=` returns an empty
set for one without complaining, and it proves its own query works against the
default-branch head before reporting an absence.

### `fingerprint-boundary-ruling` - Ruling where the injury cohort manifest's frozen boundary sits

- [x] **done** - Ruled 2026-08-27 by `architect` in
  `docs/decisions/ADR-019-cohort-fingerprint-boundary.md` (`Proposed`), with the
  entitlement limit written into `backend/tests/test_cohort_evidence.py` so it
  reaches a reader of the check rather than only a reader of the ADR.

Promoted from coordinator register `c283` and `c295`. Six source files are
frozen by whole-file SHA-256 in the injury cohort manifest, so an edit to any of
them invalidates the manifest's provenance and fails `test_cohort_evidence.py`.

Two things need deciding together: **which files the boundary should contain**,
and **what the fingerprint check is actually entitled to claim** - it passes for
whoever ran it, so it establishes that the bytes are unchanged and not that the
run was authorised. Blocks `record-refresh-lineage-relabel` in practice, and it
is why the console-encoding rule exempts `backend/src/`.

**What was ruled, and the measurement that reversed the premise.** The item was
filed on the belief that the set is over-inclusive - that `db/lineage.py` is a
general-purpose primitive with no business in injury-cohort provenance. An AST
walk of the generator's transitive `hoops_gm` import closure says otherwise:
**34 files in the closure, 3 of them fingerprinted**, and `db/lineage.py` is one
of the three. It is genuinely reached. The 31 that are not fingerprinted include
`db/models/availability.py`, `db/models/stats.py`, `db/models/identity.py` and
`ingest/rawstore.py` - the ORM and store code every cohort row is read through.
**The set is over-inclusive nowhere and under-inclusive by thirty-one files.**

So nothing was dropped. The ruling names two membership rationales instead of
merging them (`derivation` = the import closure; `provenance` = the store
producers the generator does not import), permits editing a fingerprinted file
in the same commit that regenerates the manifest with a `manifest_leaf_diff.py`
transcript attached, and stops for `quant` on any moved leaf outside
`operator.source_fingerprints` and `operator.commands`.

**Regeneration was driven rather than assumed**: offline, no network, exit 0,
**1664 leaves, 0 added, 0 removed, 1 changed**, and the one change is
`operator.commands[8]` echoing the `--out` path. The widening itself is
`cohort-fingerprint-closure-check`, filed separately because it changes the
manifest and is `data-engineer`'s artefact.

### `cohort-fingerprint-closure-check` - Checking the declared fingerprint set against the derivation closure

- [ ] **pending**
- **Depends on:** `fingerprint-boundary-ruling`

**Acceptance:** a test in `backend/tests/` AST-walks the cohort generator's
transitive `hoops_gm` import closure and fails when a closure file is absent
from `DEFAULT_SOURCE_FINGERPRINT_PATHS`; the manifest is regenerated with the
widened set and a `manifest_leaf_diff.py` transcript is attached showing no
cohort number moved.

Filed 2026-08-27 by `architect` under ADR-019. **Measured, not estimated:** the
closure is 34 files and 3 are fingerprinted, so **every manifest published so
far carries a provenance claim narrower than its own derivation.** That is true
on `main` today and this item is the repair.

**The measurement is now a committed tool, so this item starts from a report
rather than from a number in an ADR.** `scripts/fingerprint_closure.py` recounts
ADR-019's claim in one command and prints the 31 unfingerprinted closure files by
name; `backend/tests/test_fingerprint_closure.py` drives its resolution rules
against a synthetic package. **What remains here is the part the script
deliberately does not do**: fail. The script reports and exits 0, because a gate
that is red until the set is widened is a gate everyone learns to ignore. This
item is (a) the failing check and (b) the widened set plus a regeneration with a
`manifest_leaf_diff.py` transcript showing no cohort number moved.

The script also surfaced something prose had only narrated: the superseded
four-week manifest records **4** fingerprints while **6** are declared, missing
`db/lineage.py` and `merge_stores.py`. That is the exact declared-versus-recorded
divergence `_source_fingerprints`' docstring describes, and it is now visible
from a tool instead of from a comment. It is **not** a defect to repair - a
frozen manifest is supposed to describe the code that produced *it*.

The check belongs in `backend/tests/`, which is outside `backend/src/` and
therefore outside the fingerprint set - so the check costs no regeneration and
can land before the widening does. Land it in that order: a red check with a
known cause is a better artefact than a widened set nobody can re-derive.

**The trap in this item is its own domain.** An import-closure walk sees imports.
A file reached by a runtime plugin lookup, an entry point, or a string-named
module is invisible to it, and so is anything the generator shells out to. **34
is a floor, not a count.** The script prints that limit in its own output rather
than only in its docstring; keep that property in the test, because it is the
same shape as the defect the item repairs.

### `coordinator-rules-distillation` - Deciding whether the register's rules belong in gates.md

- [ ] **pending**
- **Depends on:** `coordinator-register-triage`

`docs/governance/coordinator-register.md` contains roughly 168 entries that are
durable rules rather than dated observations. **Whether they belong in
`gates.md` or `AGENTS.md` as governance, rather than in a register as history,
is a real question and it is deliberately deferred rather than dodged.**

The reason for deferring: landing the register unabridged is strictly reversible
and distilling it now is not, and a distillation performed inside the context
that produced it will drop exactly the entries whose value is not yet visible -
which is the register's own thesis about failures nobody thought to look for.

Filed as a task rather than left as a paragraph, because that distinction is the
finding that produced this whole group of items.

### `calibration-badge` - Displaying p(play)'s calibration quality beside the number it grades

- [ ] **pending**
- **Depends on:** `injury-status-conversion`, `reliability-ui`

**Acceptance:** every screen showing a `p(play)`-derived quantity shows, adjacent
to it, the restricted calibration grade of the model version that produced it,
carrying that version and its `n`; one control flattens it and one removes it;
no code path refuses anything on its value.

Filed 2026-08-27 by `architect` from an owner ruling of the same day, recorded in
`docs/decisions/ADR-018-calibration-displayed-beside-the-number.md`. Asked to
either bind preregistration v3 (a failed calibration check blocks model
activation) or decline it (the check becomes a post-hoc footnote per v3 §7), he
took neither: *"Why not just make a visible confidence score on your confidence
score? If it's too complicated I'll tell you to flatten or remove it, but we get
nothing if we don't try."*

The number displayed is v3 §4 Change B's figure - CITL and the §7 binned table
over held-out rows carrying `questionable`, `probable` or `doubtful` only. **The
computation is unchanged and the consumer is different**: it feeds a screen
instead of a gate. Below v3 §6's floor of 30 held-out direct outcomes for a
status it renders as a count and a refusal, never as a grade, because a badge
that reports a number it cannot support is worse than no badge.

**The dependency on `injury-status-conversion` is honest rather than
conservative.** The grade cannot be displayed before a grade exists, and a
placeholder badge showing a plausible value against no fitted model is exactly
the confident-and-wrong shape the Model gate exists to catch. There is no
earlier half worth landing: the UI work is small and the number is the item.

**What this item cannot settle.** A score the owner can ignore is what §7 calls a
footnote; the claimed difference is that a badge beside the number is visible
where a document is not, and nothing has tested that claim against a live
auction. ADR-018 records what would flip it.

## Named by the owner, filed 2026-08-27

The eight units below come from `docs/what-draft-day-looks-like.md`, section
*"Named by him, and not in the backlog"*. He asked for each of them; none had an
item, which made them invisible to `scripts/backlog_graph.py` and to every agent
that reads this file instead of that page.

**Filed without priorities, deliberately.** Sequencing is the coordinator's and
the owner's. What is recorded here is what each thing is, one acceptance
criterion, and the honest dependency edges - including where an edge makes an
item look further away than anyone would like.

### `league-category-table` - Ranking every team 1-to-N in every category

- [ ] **pending** - *the per-game-rate half shipped 2026-08-28 as `league-category-rate-table`; what remains is the fusion with expected games*
- **Depends on:** `draft-tracker`, `expected-games`, `projection-blending`, `frontend-skeleton`

**Acceptance:** for every seat in a live draft, a rank 1-to-N in each of the nine
categories on expected performance, updating as the board moves.

Asked for twice - Q4 (*"visibility on other teams' positional and categorical
needs"*) and Q9 (*"a tier list for all of the owners, based on expected
performance, 1 to X in rebounds"*). Q9 says what it is for: *"so I can see
categories I'm deficient in and excelling in"*, which is the input to his punt
decision, not a scoreboard.

**The rate-table half shipped on 2026-08-27** as
`league-category-rate-table`: every seat ranked 1-to-N on the sum of the
published per-game rates, with the screen stating in its own paragraph that this
is not expected performance. **What remains is exactly the `expected-games`
edge below** - the ranking is availability-blind, so a fragile star and a durable
one count identically, and the seat-level totals are not depth-adjusted either.

**The `expected-games` edge is the honest one and it is the expensive one.**
Ranking on per-game rates alone is a different quantity, and ADR-002 forbids
conflating the two. A per-game-rate table is a legitimate intermediate and must
be **labelled as a rate table**, never as expected performance - the moment it
says "expected" without games fused in, it is the exact error this project
exists to avoid.

### `rival-strategy-detection` - Detecting a rival converging on the same build

- [ ] **pending**
- **Depends on:** `draft-tracker`, `punt-builds`

**Acceptance:** names which rival seats overlap the owner's build, on which
categories, from board state alone, and updates as the board moves.

From Q4: *"There will be a point where I'm competing with another player who has
stumbled into the same build strategy - this might mean we're both willing to
overpay."* The consequence he named is a price effect, so the output is a
warning about contested categories rather than a profile of a rival.

**Read-only advisory.** It must not adjust a max bid on its own; that would move
a number he is watching for a reason he cannot see.

### `positional-scarcity-tipping-points` - Flagging when a category's supply thins

- [ ] **pending**
- **Depends on:** `draft-tracker`, `player-position-eligibility`, `zscore-engine`

**Acceptance:** flags the moment remaining supply of a category-bearing position
crosses a stated threshold, naming the category and the threshold, with the
remaining pool visible behind it.

From Q4: *"As the tier 1 point guards go off the board, it should be visible that
top assist makers or ball stealers may be at a premium."* The unit of scarcity is
**a category reached through a position**, not the position - centres thinning
matters because blocks thin with them.

**The threshold is the work.** A tipping point asserted without a definition is a
number the owner cannot argue with, and Q11 says he will believe a valuation by
observation. State the rule, show the pool.

### `out-of-position-production` - Valuing production a position does not usually supply

- [ ] **pending**
- **Depends on:** `player-position-eligibility`, `zscore-engine`

**Acceptance:** a per-player quantity measuring category production relative to
positional peers, displayed distinctly from scarcity and never summed into it.

Added unprompted the morning after the questionnaire: *"stats out of position are
especially valuable. That will almost certainly be included in ADP. Not sure how
to quantify that, but it is good to be aware of."*

**He named the trap himself** - he does not know how to quantify it, and neither
does this file. His guess that ADP already contains it is worth testing rather
than inheriting: if it does, this is a cross-check on ADP and not a new number.
Distinct from `positional-scarcity-tipping-points`, which is about supply over
time; this is about one player at one moment.

### `draft-conversation-agent` - An agent to talk choices through with

- [ ] **pending**
- **Depends on:** `dashboard-evidence-views`, `draft-tracker`

**Acceptance:** answers a free-text question about the live board using only
quantities the tool already computes, and names which ones it used.

From Q4: *"Essentially, having an agent to talk through the choices with is
probably ideal."* Q3 makes it affordable - two minutes a pick is enough to read,
not just glance.

**The constraint that makes this safe is the citation.** An agent that reasons
past the computed quantities is generating a number with no model card, no
backtest and no version, which the Model gate exists to stop. Bound it to
retrieval and explanation over things that already passed a gate.

### `over-policing-warning` - Warning on his self-named bad habit

- [ ] **pending**
- **Depends on:** `behavioural-baseline`, `auction-budget-manager`

**Acceptance:** flags when defensive bidding exceeds the owner's own measured
baseline rate, using his prior drafts as the comparison rather than a fixed
threshold.

From Q8: *"There needs to be some policing on picks going for way too cheap.
Sometimes you bid on someone just to play defense, then win some of those bids
accidentally. The bad habit would probably be over policing."*

**Filed separately from `bias-guardrails`, which is the generic machinery, because
this one has a definition problem the machinery does not solve.** A defensive bid
and a real bid are the same event in `draft_events` - intent is not recorded
anywhere and cannot be inferred from the log. Either the recorder gains a way to
mark intent at bid time, or the warning is a guess about his state of mind
dressed as a measurement. **That choice is the item.**

### `per-team-auction-budgets` - Giving each seat its own starting budget

- [ ] **pending** — **Route B landed 2026-08-28; Route A is what remains.** Seats still have no budget column. The pick-loss is gone: a sale above the assumed scalar is now recorded and flagged, not refused.
- **Depends on:** `draft-tracker-persistence`

**Acceptance:** each seat's starting budget is stored on the seat, and every
derivation reads it from there rather than from the single scalar on `Draft`;
no seat's winning bid can be dropped because another seat's budget was assumed.

**ARCHITECT RULING 2026-08-28 — the `draft-tracker` edge stays, on a new
justification.**

**SUPERSEDED THE SAME DAY BY THE OWNER. The edge is dropped.** The ruling below
named its own flip condition — *"if he says the shared scalar is close enough,
that he needs only his own bank tracked and reads the others off Fantrax, Q15 is
satisfied without Route A and the edge should be dropped"* — and asked that he be
put the question **before** Route A's migration was written rather than after.

He was asked, and answered: **"Yes 200 is close enough."**

So `draft-tracker` no longer depends on this item, and **all nine of its
dependencies are now done.** This item stays open as ordinary unbuilt work: seats
still have no budget column, and a seat whose real bank differs will still show a
figure derived from the shared scalar — now with `over_assumed_budget` flagging
it rather than a pick being lost, which is what Route B bought. It is no longer
on the critical path to draft day.

**What this ruling did not settle, and what replaced it as the open question.**
Dropping the budget edge does not make the board work. On the same day the first
instrumented capture established that the bridge **cannot** read Fantrax's
`/fxpa/req` at all — service-worker originated, and Cache Storage verified empty.
So "picks tracked automatically" is now contingent on
`official-getdraftpicks-live-verification` rather than on any budget question.
The reasoning below is kept because the argument it makes about Q15's two nouns
is still the right frame; only its conclusion was overtaken.

---
**The original justification is now false and the Route B lane said so rather
than quietly leaving it.** That edge was filed because a recorded sale could be
refused and the player never added to the board — Q12's *"misses one"*. Route B
removed that: the sale is admitted and the assumption is flagged instead. The
lane declined to drop the edge itself on the grounds that re-sequencing is
`architect`'s call and that removing a constraint while fixing the sentence
holding it up is the wrong half to do unilaterally. That was correct.

**Ruling: the edge stays, and the reason is Q15's second noun.** The owner's
answer to what must work on 18 October is *"the live draft board with picks **and
budgets** tracked automatically."* Picks are now tracked correctly. Budgets are
not: `Draft.auction_budget` is one scalar, his Q8 answer is *"slightly different
per team based on last years' final totals"*, and so every seat's remaining
figure is wrong for most seats by construction. The board reports **spend**
correctly and **remaining** against an assumption it knows is wrong — which is
why Route B publishes `over_assumed_budget` rather than hiding it.

So `draft-tracker` cannot honestly be called done while half of what the owner
named is derived from a number that does not describe his league.

**What would flip this.** If the owner says the shared scalar is close enough —
that he only needs *his own* bank tracked and can read the others off Fantrax —
then Q15 is satisfied without Route A and the edge should be dropped. That is
his call, not an inference from these words, and it is worth asking before Route
A's migration is written rather than after.

**Recorded rather than acted on:** nothing about the edge changes today, and
`draft-tracker` stays pending either way. What changed is that the justification
in force is now stated, so the next reader does not find a dependency resting on
a sentence that has been corrected out from under it.

**`draft-setup-screen` is downstream of this, not upstream, and the graph is what
established that.** The obvious edge - "you cannot set per-seat budgets until
there is a screen to set them on" - is false and creates a cycle:
`draft-tracker` -> `per-team-auction-budgets` -> `draft-setup-screen` ->
`draft-tracker`, which `scripts/backlog_graph.py` refused on 2026-08-27 the
moment the blocking edge above was added. The cycle is the tool telling the truth.
`POST /api/v1/drafts` already accepts the full participant list, and
`hoops_gm.dev.seed_draft` already creates seats without a browser, so the schema
and API half needs no screen. The screen must **carry** per-seat budgets when it
lands, and its existing edge on `draft-tracker` already sequences that.

From Q8: *"I think 200, but it's slightly different per team based on last years'
final totals."*

**This is a schema gap, not a feature, and it was verified rather than
inherited.** `DraftParticipant` carries `draft_id`, `team_slot`, `display_name`,
`owner_draft_id` and `fantasy_team_id` - **no budget column.** `auction_budget`
is one `Numeric(10, 2)` on `Draft` (`db/models/draft.py:120`), copied from
`League` at creation.

**And the scalar does not originate on `Draft` either.** `draft/formats.py:242`
copies it from `League.auction_budget` (`db/models/league.py:85`), which is
**also a single nullable scalar**. So the one-budget-per-league assumption is
baked in one level above the draft, and **a fix that only adds a column to
`DraftParticipant` leaves the league-level scalar as the only thing a seat can
be seeded from** - correct at the seat, still wrong at the source, and
discovered on the second pass by whoever implements it. That changes the shape
of the migration, so it is recorded here rather than found later.

#### The apply path, which is why this blocked rather than annoyed

**Everything in this section is history as of 2026-08-28.** It is kept because
the mechanism is the argument for Route A, and deleting it would leave the item
looking like a nicety. `_refuse_if_over_budget` (`draft/state.py:449-463`)
computed `remaining = fmt.auction_budget - board.spent_by(participant.id)` from
that one draft-wide scalar. **Three call sites, read rather than recalled:**

| line | enclosing function | what it refused |
|---|---|---|
| 427 | `_apply_nomination` | an opening bid |
| 493 | `_apply_bid` | a bid |
| **564** | **`_apply_sale`** | **a completed sale** |

**Line 564 sat three lines before `board.add(...)` at 567.** So a recorded sale
above the assumed scalar raised `draft_budget_exceeded` and **the player was
never added to the board.**

It was worse than a lost pick, and this half was established by grep and then
driven: `apply_observations` filed that refusal into `skipped_reason`, `pending`
is filtered on `skipped_reason IS NULL`, and **nothing in the package ever
clears that column**. So re-ingesting the identical capture deduped against the
burned row rather than retrying it. The pick was unrecoverable short of typing
it by hand — inside the feature whose purpose is to stop him typing.
`test_a_refusal_that_survives_still_burns_its_row_permanently` now drives that
burn on a refusal that remains, so the mechanism is a red test away rather than
a paragraph.

In his league the scalar is wrong for most seats by construction, so any seat
with a larger bank lost its winning bids from the moment its spend passed the
assumption. The board then silently lacked a player it watched being sold. Asked
what would make him abandon the tool mid-auction, the owner answered *"it loses
track of the draft - shows me picks that already happened or misses one"*; Q15
names *"the live draft board with picks and budgets tracked automatically"* as
the single thing that must work on 18 October. **That was that failure, inside
that feature.**

**The display derivation at `draft/state.py:671-682` is the lesser half, and it
is the half that is still wrong.** A wrong `remaining_budget` on screen is a
wrong number a human can notice — and now one the screen labels as ours rather
than as the seat's. A refused sale was a missing fact, and nothing on the screen
said so. Route B fixed the second and left the first.

**Recorded as a dependency edge on `draft-tracker` rather than as a caveat**, for
the reason `draft-feed-unreadable-id-surfacing` established: a caveat is text,
and `backlog_graph.py` fails on a dangling edge while a paragraph fails nothing.
**The edge is deliberately left in place, and its original justification is
spent.** It was added because a sale could vanish; that cannot happen now. Whether
`draft-tracker` should still wait on real per-seat budgets is a sequencing call
and belongs to `architect`, so this lane corrected the claim rather than quietly
dropping the constraint the claim was holding up.

#### Two routes. Route B is done; Route A is the open half.

**Route A - the schema change. STILL OPEN, and this item is it.**
`DraftParticipant` gains a budget column, set at draft creation, and the display
derivation reads it from the seat. Correct and complete; it is a migration, a
create-path change, a `draft-setup-screen` change and a backfill decision for
existing drafts. Note that the three refusal call sites in the table above are
**gone**, so Route A is now smaller than it was: there is nothing to re-point at
a per-seat column except the derivation at the end of `derive_state`, and Route A
should not reintroduce the refusal — the reason it was wrong is that a sale is a
fact, and that is true whether the budget is per-seat or not.

**Route B - stop refusing on the apply path, and report instead. DONE
2026-08-28.** `_refuse_if_over_budget` is deleted with all three call sites;
`remaining_budget` is signed; `ParticipantState.over_assumed_budget` /
`ParticipantOut.over_assumed_budget` is a first-class `bool`, `False` in an
ordered draft. The board screen renders a flagged seat as `$300.00 over` under
*past the budget this tool assumed*, with a note saying no pick is missing —
`$-300.00` under *left, of sales recorded* was the rendering this change would
otherwise have shipped. Consistent with ADR-014 (a read detects a moved cohort,
it does not lock to prevent one) and with Q7 (advise everywhere, override
nowhere).

**Route B did not make Route A unnecessary; it made the board correct while
Route A is built**, which matters because the calendar does not move. **Seats
still do not have their own budgets**, and every figure beside a seat is still
derived from one scalar that is wrong for most of them. What changed is that the
tool now says so instead of deleting the evidence.

### `owner-bias-feedback-loop` - Feeding his own tendencies back to him

- [ ] **pending**
- **Depends on:** `adherence-experiment`, `behavioural-baseline`

**Acceptance:** after a completed draft, reports where his decisions diverged
from the list and whether each divergence repeated a pattern from an earlier
draft.

From Q14, on what he always gets wrong: *"valuing injured and unreliable players
too highly, not knowing when to cut someone who is proven to have been a bad
pick, overall evaluation, and not feeding back on my own bias."*

**The only requested feature that improves with use, and it cannot begin until he
has drafted once.** It is also the one most exposed to Q7: he has said there will
always be one or two heart picks, and they are legitimate. A loop that scores
every deviation as an error will be wrong about the exception he explicitly
reserved. Separate systematic deviation from the deliberate kind, or it reports
his intent back to him as a defect.

## From the Basketball Monster export analysis, filed 2026-08-27

Four items from findings the coordinator derived on 2026-08-28 against the
owner's purchased projection exports. **The source files are private and are not
in this repository, and must not be.** What is recorded below is the shape of a
third-party export format, which is safe to publish and which the repository
already touches through
`backend/tests/fixtures/projections/basketball_monster_sample.csv`.

**Provenance, so the numbers are attributable:** every figure quoted below is the
coordinator's measurement, not mine. I did not re-derive them and cannot - the
inputs are outside the repository. Everything I *did* drive against this
checkout is marked as such.

### `projection-source-vintage-assertion` - Refusing an actuals file imported as a projection source

- [ ] **pending**
- **Depends on:** `projections-import-cli`, `participation-ledger`

**Acceptance:** a test feeds a prior-season actuals file to the projection
importer and shows it refuses, naming vintage as the reason.

**The finding.** `BBM_PlayerRankings.xls` and `BBM_Projections.xls` are near
schema-identical - both carry `Rank`, `Value`, `g`, `m/g`, `p/g` - and they
measure different things. Against an independent input, actual 2025-26 games
played from `player_participation`, the Rankings file's `g` reproduces the
ledger for **438/438 players within one game, MAE 0.12**; the Projections file's
`g` has **MAE 14.11**. The Rankings file is **last season's actuals**.
Differencing the two looks like a dramatic one-day revision - the #1 overall
appears to flip - and is not a revision at all.

**This is the `gameEt` class in a new place.** Well-formed, type-correct, and
lying about what it is. Nothing about the file's *form* could have caught it;
only a check of its *meaning* against an independent source did.

**Two things to build, and the second is the one that bites.** First, bind the
vintage to the filename or to an explicit operator declaration - **never infer it
from schema**, because the schemas do not distinguish. Second, assert it: if the
incoming `g` column reproduces the prior season's participation ledger to within
a game, the file is actuals and must be refused as a projection source.

**The existing guard does not cover this and may make it worse.**
`BASKETBALL_MONSTER_PROFILE` pins an exact header sequence
(`parser.py:115` refuses when `tuple(fieldnames) != profile.expected_headers`).
**Resolved 2026-08-27 by the coordinator, who holds the files: neither new export
matches it.** `BASKETBALL_MONSTER_2026_27_HEADERS` is the 22-column sequence
`player_id, last_name, first_name, games, minutes, ... , comments` - the header
row of the 19 August CSV. The 27 August projections export is **48 columns**
beginning `Own, Round, Rank, Adv ADP, ...`; the 26 August actuals export is **37
columns** beginning `Own, Round, Rank, Adv%, ...`. So the guard refuses the
actuals file **as schema drift**, which gives the wrong reason and invites the
next reader to widen the profile until it fits. A guard that gives the wrong
reason is worse than one that is silent.

**And no header check could ever be the answer, which is the load-bearing part of
this item.** The two exports are *the same Basketball Monster view configured
differently* - the actuals file is the projections file minus `Adv ADP`, `1W+-`,
`Note`, `Inj Risk`, `Josh`, `Kyle`, `Matt`, `Conf`, `Tier`, `Role` and `b2b`,
because BBM lets the user choose which columns to display. **A user who
configures the two pages alike gets two byte-identical schemas holding different
seasons.** Schema cannot separate them even in principle.

**So implement this as a value-level assertion, not a header tweak.** Bind the
vintage to the filename or an explicit operator declaration, then *check* that
declaration against the data: if the incoming `g` column reproduces the prior
season's participation ledger to within a game, the file is actuals and must be
refused as a projection source. Widening `expected_headers` is the plausible
wrong fix and it closes nothing.

**The ledger arm must not pass vacuously.** `participation-ledger-population` has
not run at scale, so the comparison has no data to run against yet. A check that
reports a pass over an empty ledger is this repository's signature defect -
report "could not compare" and fail closed, never green.

### `external-games-as-class-prior` - Consuming a vendor games column as a class label, never an estimate

- [ ] **pending**
- **Depends on:** `projection-blending`, `projections-import-cli`

**Acceptance:** the blend records a vendor `g` column as a prior or class label
with its level count, and no code path multiplies a rate by it or reads it as
expected games.

**The finding.** BBM's `g` is a four-level risk class, not a per-player estimate.
500 players hold only **35 distinct** games values, and the two dominant ones are
BBM's own injury-risk grade exactly: **`g=73` is Inj Risk `M` for 195/195 = 100%**
and **`g=68` is Inj Risk `H` for 105/105 = 100%**. Not a team effect (30 and 28
teams) and not a role effect (each mixes BN/ST/mST). The entire 19 -> 27 August
change, which superficially moved **432 of 500 players**, is BBM nudging two
class defaults up by two games each: 71 -> 73 for 193 players, 66 -> 68 for 99.

**So a games delta between two vendor exports is not new information about
players.** It is two numbers changing. Anything that treats such a delta as
signal - a stock-watch mover, a re-ranking, a "projection updated" notice - will
manufacture 432 events from two.

**Blending it as a per-player estimate imports four bits wearing the costume of
five hundred.** This is the strongest external evidence yet for ADR-002.

**What is already right, so nobody rebuilds it.** The importer already keeps this
out of expected games: `ProjectionSourceRow.assumed_games_played` is documented
as *"Not an expected-games number - that is the availability model's job"*, and
the value is written to `source_games_played_assumptions`, a separate table,
*"precisely so nothing downstream can reach it while reading a rate"*. This item
is an assertion and a recorded level count, not a redesign.

**No ADR-002 amendment is proposed, and that is a judgement rather than an
omission.** ADR-002's amendment of 2026-08-23 already records the tier structure
(`games` and minutes-per-game taking *"the same 18 distinct values"* in the
rotation cohort) and already names the flip condition as *"a source whose games
column carries a per-player opinion rather than a tier."* This finding
corroborates that amendment and identifies what the tier is; it changes nothing
an implementer builds that this item does not already state. A third governance
document restating evidence for a `Proposed` amendment the owner has not yet
read adds reading load and no decision. **Overturn this if you disagree - it is
one section, and the evidence is recorded here either way.**

### `evidence-panel-shows-inj-with-note` - Rendering a source's structured injury field beside its prose

- [ ] **pending**
- **Depends on:** `dashboard-evidence-views`

**Acceptance:** wherever the evidence panel renders a source's prose beside its
projection, the same source's structured injury field is rendered with it, or
neither is.

**The finding.** BBM's `Note` prose is not synchronised with its own numbers.
Only **19 of 509** players carry a structured `Inj` entry (the form
`Injured - torn acl (38g) - 1/10/2027`), and that entry is what moves a player
off his class default. Jordan Miller's games were cut **71 -> 21** while the Note
reads *"has done enough to keep earning opportunities."* **Glowing prose, fifty
games removed.**

Rendering the Note alone explains a number with text that contradicts it, which
is worse than rendering no explanation: the owner is told *why* and told wrong,
in a panel whose whole purpose is that he can check the reasoning. Q11 says he
will come to believe a valuation by observation, so an evidence panel that
misexplains one is spending the exact currency it exists to earn.

### `console-safety-for-runtime-names` - Surviving a non-ASCII player name on the owner's console

- [ ] **pending**
- **Depends on:** `projections-import-cli`

**Acceptance:** a refusal or report path carrying a name like `Nikola Jokic`
spelled with its diacritics reaches a cp1252 console legibly rather than raising,
and the guard covers runtime data rather than only source literals.

**The matching half is already done and needs no work - driven against this
checkout on 2026-08-27, not inherited.** `identity/names.py` NFKD-folds and drops
combining marks, and `normalize_name` maps the accented and ASCII spellings of
Jokic, Doncic, Schroder, Porzingis and Sengun to identical keys. A crosswalk item
would have been a duplicate.

**The console half is real and is a different claim.** Player names are *runtime
data*, and `backend/tests/test_console_encoding.py` walks **string literals**
under `scripts` and `backend/tests` only - so it cannot see a name that arrives
from a vendor file or the ledger and is interpolated into a message.
`import_csv.py` prints refusal text built from exception messages straight to
`sys.stderr` with no `reconfigure`, where `backlog_graph.py` guards its own
output with `_safe_stdout()` and `check_ci_gates.py` uses
`reconfigure(errors="replace")` for exactly this reason - its comment already
names the general form: *"those are not source literals, so that test cannot see
them."* The report file itself is safe; it is written with `encoding="utf-8"`.

**The prize is not the crash.** It is that a refusal is a user interface, and
this one fires when an import has failed and the owner is reading the console to
find out why.

### `cohort-manifest-leaf-count-discrepancy` - Explaining two different leaf counts for one manifest

- [ ] **pending**
- **Depends on:** `fingerprint-boundary-ruling`

**Acceptance:** the two counts below are reconciled to a named cause, or the
earlier one is shown to be a misreading; either way the answer is written down
rather than re-measured by the next person who notices.

Filed 2026-08-27 so this starts from evidence rather than from the memory of a
discrepancy. **Two measurements of `manifest_leaf_diff.py` against
`docs/adapters/nba-injury-report-cohort-2025-10-21--2026-04-12.json`:**

| date | leaves | context |
|---|---|---|
| 2026-08-26 | **1656** | coordinator register `c294`, regeneration with the `record_refresh` lineage fix applied, reporting exactly 1 differing leaf |
| 2026-08-27 | **1664** | `architect`, control regeneration at the unmodified tree, 0 added / 0 removed / 1 changed against the committed file |

**The manifest itself did not move.** `git log -- docs/adapters/nba-injury-report-cohort-2025-10-21--2026-04-12.json`
returns exactly one commit, `1912a3d` (#92). So the difference is in the
generator, in what was on disk when each ran, or in how one of the two counts was
read - **not** in the artefact.

**Narrowed 2026-08-28, and this is the part that makes the item cheap.** The
committed manifest reads **1664 leaves at `1912a3d` and 1664 today**, 0 added /
0 removed / 0 changed between them. So `1664` is the artefact's own count and
has been since it was published. **`1656` therefore describes something other
than the committed file** - most likely the regenerated output of that run,
which would mean that regeneration produced a manifest **8 leaves smaller** than
the one on disk.

**If that is what happened, "1 differing leaf" and "1656 leaves" cannot both be
right about the same pair of documents**, because a file 8 leaves short reports
8 *removed*, not 1 *changed*. One of the two numbers in `c294` is describing a
different comparison than the other.

**The obvious hypothesis was tested and it does not fit.**
`scripts/manifest_leaf_diff.py`'s own docstring records a section silently
emptying when the generator is run from `backend/` rather than the data root -
*"three files' sizes and hashes vanished from the manifest with nothing marking
their absence"*. That section is `operational_artifacts`, and it holds
**7 leaves** today (`directory_present`, plus `files` at 6 = three files x two
fields). Collapsed it would hold **2** (`directory_present`, plus `files` as an
empty container, which this tool counts as one leaf by design). **That is a loss
of 5, not 8.** So the emptying-section story is insufficient on its own, and the
next reader should not spend the hour I nearly did on it.

Reproduce the 1664 measurement:

```
python scripts/manifest_leaf_diff.py \
  docs/adapters/nba-injury-report-cohort-2025-10-21--2026-04-12.json \
  $env:TEMP\cohort-control-regen.json
```

`manifest_leaf_diff.py` accepts `<ref>:<path>` as well as a path on disk, so the
history side needs **nothing checked out**:

```
python scripts/manifest_leaf_diff.py \
  1912a3d:docs/adapters/nba-injury-report-cohort-2025-10-21--2026-04-12.json \
  docs/adapters/nba-injury-report-cohort-2025-10-21--2026-04-12.json
```

**Regenerating the comparison side, and the trap in it.** The control regen is:

```
cd backend
$env:PYTHONPATH="$PWD\src"
$env:DATABASE_URL="sqlite+pysqlite:///C:/Users/steverones/hoops-gm-data/cohort-merged-2025-26.db"
python -m hoops_gm.ingest.injury_report.cohort_evidence 2025-26 \
  --start 2025-10-21 --end 2026-04-12 --out $env:TEMP\cohort-control-regen.json \
  --repo-root .. --raw-root "C:\Users\steverones\hoops-gm-data\data\raw" \
  --report-dir "C:\Users\steverones\hoops-gm-data\data\reports" \
  --merge-receipt "C:\Users\steverones\hoops-gm-data\cohort-merged-2025-26.db.merge-receipt.json"
```

**`--raw-root` is the trap and it has already cost this project a wrong
conclusion.** Its default is `backend/data/raw`, **which does not exist**, and
that default is exactly what coordinator register `c294` records a lane
misreading as "regeneration requires live `stats.nba.com` calls" - a claim that
reached a docstring and was quoted back as grounds for a ruling before being
driven and found false. Pointed at `hoops-gm-data\data\raw` (3,045 files, 53.8 MB)
it runs offline, exit 0. **What makes it offline is that `--allow-fetch` is off
by default**, so a view the raw store never captured is *reported* rather than
fetched; nothing suppresses the network, the tool simply does not reach for it.
And `--report-dir` matters for the same reason the emptying section above does.

**`$env:TEMP\cohort-control-regen.json` is the artefact behind the 1664 count and
is a temp file.** It will not survive a reboot. If it matters, **regenerate it
with the command above rather than going looking for it** - the command is the
durable thing, which is the whole reason it is written here instead of a path.

**Eight leaves is small, and that is the reason to look rather than the reason
not to.** Both runs reported "1 changed" and used that to support a *negative*
claim - that no cohort number moved. A negative claim from a whole-leaf
comparison is only as good as the leaf set being the same set. This repository
has twice found a small unexplained delta to be load-bearing, and neither time
was it obvious in advance.

Cheapest first step, given the narrowing above: **stop counting and start naming.**
Diff the leaf *path sets* between the committed manifest and a fresh regen. Path
names say immediately whether a section appeared, emptied, or was never counted
the same way - and since `operational_artifacts` collapsing accounts for only 5
of the 8, the remaining 3 are somewhere a count can never point at.

### `league-category-rate-table` - The per-game-rate half of the live category table

- [x] **done** - Landed 2026-08-27 at `/draft/:draftId/categories`, linked from
  the draft board. 45 tests across three files, 15 mutations driven red with
  zero escaped.
- **Depends on:** `draft-tracker-screen`, `projections-ui`

**This is the intermediate `league-category-table` sanctions, not that item.**
#118 filed `league-category-table` the same night this was built, independently,
and its acceptance criterion is *"on expected performance"* - which this does not
meet and does not claim to. Its own wording is the ruling this item obeys: *"a
per-game-rate table is a legitimate intermediate and must be labelled as a rate
table, never as expected performance."* So it is named for what it is, marked
done for what it is, and `league-category-table` stays pending behind
`expected-games`. Two lanes reached that distinction separately on the same
night, which is worth more than either statement of it alone.

Named by the owner twice, unprompted, and it had no backlog item until now -
`docs/what-draft-day-looks-like.md` lists it first under "Named by him, and not
in the backlog". **Q4:** *"some way to show me that of the 4 teams who still
have not passed on a player, only one of them is really competitive in a top
category."* **Q9:** *"Who is winning each category - a tier list for all of the
owners, based on expected performance, 1 to X in rebounds. So I can see
categories I'm deficient in and excelling in."*

**Deliberately narrower than Q9, and this is the item's whole design
constraint.** Q9 asks for *expected performance*, which is per-game production
fused with expected games played. That fusion is permitted at exactly one seam
(`expected-games`, ADR-002) and that seam is not built; `p(play)` does not exist
either. So this screen ranks seats on **the sum of the per-game rates the
projection source published for the players each seat holds**, and says so on
screen in its own paragraph rather than letting the reader assume otherwise. The
whole page is `+` and `÷` over published fields, which is what keeps it behind
the **Code gate**. Adding a weighting, a spread, a z-score or an availability
adjustment makes it a Model-gate unit needing a held-out backtest reporting
calibration and a card in `docs/models/`.

Three limitations are surfaced on screen rather than corrected, because
correcting any of them means inventing a number:

- **Not depth-adjusted.** A seat holding five players outranks one holding three
  on a sum, for that reason alone. The joined-player count is drawn beside every
  seat name. Correcting it means projecting the players nobody has drafted.
- **Unranked is not last.** A seat with nothing joinable gets no rank, no tier
  and no colour. This is not hypothetical: **every holding in the seeded demo
  carries `player_id: null`**, because `seed_demo` invents draft names the
  identity crosswalk cannot match, so the all-unranked board is what a
  first-time reader meets. Nothing is matched by name, ever.
- **The nine categories are unverified.** They come from
  `docs/league/2025-26-rules-baseline.md`, which calls itself historical and not
  verified for 2026-27. The served OpenAPI document exposes nineteen paths and
  none carries league scoring configuration, so there is nothing to check them
  against until `league-settings-ingest`.

FG% and FT% are `Σ made ÷ Σ attempted` across the seat with the attempt volume
printed beside them, never a mean of player percentages - volume-weighted by
construction, which is the seat-level form of the bug `AGENTS.md` calls the most
common in homebrew tools. TO ranks in reverse.

### `draft-page-invalid-id-request` - Stopping the draft board requesting `/drafts/NaN`

- [ ] **pending**
- **Depends on:** `draft-tracker-screen`

`DraftPage.tsx` calls `useAsync` before the `isValidId` guard renders, so
`/draft/not-a-number` fires a `GET /api/v1/drafts/NaN` and then draws the
refusal. The screen looks correct either way; the wasted request is visible only
in the network log, which is why reading did not find it.

Found while building `league-category-table`, which copied the structure and
inherited the defect - caught there by a test asserting *no request was made*,
and fixed there by splitting the component so the hook only mounts for a valid
id (`CategoriesPage.tsx`). The same two-line split applies here. **It was not
done from that lane** because `DraftPage`'s fetcher carries the bundle-identity
comparison the polling skip depends on, and disturbing it to fix one wasted
request on a malformed URL is the wrong trade to make unreviewed under a
deadline.

Low impact: one request, on a URL nobody reaches by clicking. Worth fixing
because the same guard-after-the-hook shape will be copied again.

### `category-table-board-completeness` - Saying when a category ranking is computed over an incomplete board

- [ ] **pending**
- **Depends on:** `league-category-rate-table`, `draft-tracker-bridge-feed`

**Acceptance:** `/draft/:draftId/categories` states, per seat, how many feed
observations were skipped rather than applied, so a ranking over an incomplete
roster is visibly incomplete rather than merely wrong.

**The coupling, stated so it can be checked.** The category table ranks each
seat on the players it holds. `draft/state.py:449-463` derives every seat's
remaining bank from one draft-wide scalar, and the call site at 564 sits three
lines before `board.add(...)` on the **sale** path - so a legitimate winning
bid above the assumed figure is refused and the player never reaches the board.
`apply_observations` then files that refusal in `skipped_reason` and
`draft/feed/service.py:1223` records that nothing in the package ever clears
it, so re-ingesting the same capture dedupes against the burned row instead of
retrying.

**A seat can therefore be missing a player it actually won, and the ranking will
look perfectly well-formed.** Every guarantee the screen makes is about the join
between holdings and projections; none of them is about whether the holdings are
all the holdings. That is a claim the screen cannot make from what it reads.

**Why it was not just done.** The counts are on `GET /drafts/{id}/feed`
(`FeedStatus.skipped`), not on the draft state the page already fetches -
checked against the served OpenAPI document rather than assumed. Surfacing them
is a third request, its own retry policy, its own failure path for a draft with
no feed at all (which is every draft recorded by hand, including the one this
screen's fixture was captured from), and its own recorded fixture. That is
plumbing rather than a label, and it was filed rather than rushed at 23:00 on
the night the screen landed.

### `source-board-evidence-api` - Publishing the rendered board without inventing participant identity

- [x] **done**
- **Depends on:** `draft-board-dom-parser`

Added `GET /api/v1/drafts/{draft_id}/source-board`. It returns an explicit
`available`, `refused` or `no_reading` state; the latest successful parsed board
grouped by `source_seat`; mutable source labels; server-clock board and contact
freshness; regressions; and the exact-content undo blind spot. It returns no
participant ids or budgets. Board observations preserve source
round/pick/overall/player fields and a dedicated `source_seat` column, remain
`source_board_evidence_only`, and never append `draft_events`.

The state row is separate from pick observations because a refusal and a
zero-pick board otherwise both have zero pick rows. Keeping only observations
would reproduce the failure this endpoint exists to prevent: "could not read
the board" rendered as "the source board has no picks".

This does not complete `draft-board-feed-integration`. The existing
`/draft/{id}` page remains authoritative and event-backed, and its participant
columns and budgets remain unchanged. Source-column attribution still needs an
explicit by-construction binding, while auction and NBA board applicability
remain unestablished. `board-dimensions-per-draft` remains a separate follow-on.

### `source-board-evidence-panel` - Showing source columns beside the authoritative draft board

- [x] **done**
- **Depends on:** `source-board-evidence-api`

Add a read-only evidence panel to `/draft/:id` that consumes
`SourceBoardResponse` from `GET /api/v1/drafts/{draft_id}/source-board`. Render
picked players grouped by `source_seat`, with mutable labels visibly described
as labels rather than identity, plus board/contact age, named refusal state and
regressions. Do not merge source columns into `DraftParticipant`, do not show
budgets on the source panel, and do not imply that matching column positions
establish ownership.

**Acceptance:** `no_reading` and `refused` are distinct visible states rather
than empty boards; the exact-content undo blind spot and football-snake-only
evidence are visible; the existing event-backed `DraftSeats` board is unchanged.
