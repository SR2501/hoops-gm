"""Historical backfill of the NBA official injury report.

    python -m hoops_gm.ingest.injury_report.backfill plan 2025-26 --start 2025-11-01 \
        --end 2025-11-07
    python -m hoops_gm.ingest.injury_report.backfill run 2025-26 --start 2025-11-01 \
        --end 2025-11-07

## The problem this solves

Only one injury-report PDF is committed as a fixture (2025-11-01 05:30 PM ET),
because a contract test needs exactly one real capture, not a corpus. That
single snapshot cannot make ``injury-status-conversion`` (``docs/backlog.md``)
evidence-ready: a model card claiming a calibrated conversion rate needs many
report-to-outcome pairs across many dates, not one. This module is the
bounded, resumable *data-engineering* tool that populates that historical
cohort — it fetches and persists observed report rows only. Computing or
reporting any status-to-outcome rate is out of scope; that is
``injury-status-conversion`` itself, a ``quant`` model-gated deliverable.

## Deriving candidate report timestamps without lookahead

The report is not published on a fixed schedule an API exposes — it is a
document, published irregularly through the day (see
``hoops_gm.ingest.injury_report.client``). This tool cannot ask "what times
was a report published on this date"; it can only *guess* plausible instants
and let ``ReportNotAvailable`` (HTTP 403/404) tell it when a guess was wrong,
exactly as the live-smoke tests already do for single dates.

**The two URL eras tolerate a wrong guess very differently, and the
candidate strategy is era-conditional because of it** — see
``client.report_url``/``client.is_fifteen_minute_era``:

* **Legacy era (before 2025-12-22): the URL always truncates to the hour**,
  and the parser separately tolerates up to 45 minutes of masthead drift
  between the requested instant and the file actually returned. A fixed
  clock-time guess anywhere within about 45 minutes of an actual capture
  reliably lands on it. Two fixed guesses per date: ``evening_before``
  (17:30 ET the day before — the pre-December-2025 documented policy,
  5:00 PM local the day before a game) and ``game_day`` (13:00 ET the date
  itself — a cheap opportunistic second guess, not independently documented
  for this era but free to try since it costs one extra request).
* **15-minute era (2025-12-22 onward): the URL is an exact-minute match with
  no drift tolerance at all.** ``report_url`` does not round to the nearest
  quarter-hour; it formats the requested minute verbatim, so a request for a
  minute the source did not publish at 404s before any body — even a body
  whose masthead would otherwise have been "close enough" — is ever read.
  **An earlier revision of this module used a single fixed clock-time guess
  here too (13:00 ET), on the theory that the 45-minute masthead tolerance
  would forgive it. That is wrong: the tolerance is a post-fetch sanity check
  against whichever exact file the URL named, and cannot recover a URL that
  never resolved.** Found by independent review, corrected here: for a date
  known to fall in this era with at least one ingested game, candidates
  anchor to that date's own *earliest applicable tip-off instant* instead of
  a wall-clock time — :data:`NEAR_TIP_OFFSETS`, a small bounded set of fixed
  offsets before it (2h30m, 1h30m, 45m, 15m) — plus ``evening_before``,
  which still applies unconditionally in both eras (the 2025-12-20 memo
  documents an *additional* game-day cadence, not a repeal of the existing
  evening-before requirement, and the two independently pinned archived
  timestamps this project already relies on — ``2025-11-01 17:30 ET`` and
  ``2026-01-15 17:30 ET``, see ``test_live_smoke.py`` — both land inside it,
  the second one *in* the 15-minute era). Anchoring to the game rather than
  the clock is still bounded (five requests per date, not a sweep of the
  afternoon) and is the only way remaining to land near an actual file once
  the URL itself demands an exact minute.

  **A fixed offset before tip-off is still not enough by itself.** A
  non-grid-aligned tip-off (e.g. 19:10 or 19:40 ET, not 19:00/19:15/...)
  moves every offset-derived candidate off the exact ``:00``/``:15``/``:30``/
  ``:45`` minute the source's URL requires — the offset instant can then
  never match a real masthead no matter how close it lands to an actual
  publication. Found by independent review a second time: every near-tip
  candidate is floored to the prior 15-minute grid mark (see
  :func:`_floor_to_quarter_hour_et`), never rounded forward past its own
  offset or past tip-off itself (no lookahead). Two offsets that floor to
  the same grid mark collapse to one request rather than two.

Neither anchor is a claim that a report *exists* at that instant for every
date — most of the calendar has no report at all, which is the ordinary case
documented on ``ReportNotAvailable`` — only that it is the most defensible
instant to *ask* the source about.

**The falsifiable limitation**: this tool can only recover reports published
close enough to one of its anchors — within roughly 45 minutes in the legacy
era, or within one of the exact :data:`NEAR_TIP_OFFSETS` minutes in the
15-minute era. A report published at, say, 3:00 AM ET as an emergency update
(an injury discovered overnight), or at a 15-minute-era minute mark none of
the near-tip offsets happens to land on, is not reachable by this scheme and
is not claimed to be. That gap is real, is disclosed here and in
``docs/adapters/nba-injury-report.md``, and is not something a wider anchor
set can fully close either: this is a document with no published schedule,
and no number of anchors turns that into a documented one.

**Real evidence gathered so far is tool-validation evidence, not a
representative or complete cohort.** A handful of dates deliberately chosen
because they were already known to be reachable proves the mechanism works;
it does not establish what fraction of an arbitrary date range's reports this
scheme actually recovers. See ``coverage_for_games`` and the ``observations``
CLI subcommand for the honest, per-game accounting this distinction needs,
and do not read any single run's "N canonical observations" count as a
recovery rate.

**No lookahead, enforced twice.** A candidate timestamp only ever applies to
a game whose ``tipoff_utc`` is strictly *after* it — checked once here, when
deciding which games a fetched report is even relevant to, and checked again,
independently, by :func:`select_canonical_pregame_observations` at read time
against the row's resolved ``game_id``. The second check does not trust the
first: a game's ``tipoff_utc`` can be corrected after this plan was built
(the schedule postponing or moving a tip-off), and re-deriving the gate from
the row's own foreign key rather than trusting a precomputed set is what
keeps a later schedule correction from leaving a stale, wrong observation
looking canonical.

## Durable coverage evidence: what "N observations" does and does not mean

A raw count of canonical observations conflates several genuinely different
situations, corrected across three rounds of independent review:

* **A game-level "observed" outcome is not a player-game surface.** One
  player's canonical row proves a game was covered at all, not how much of
  its full injury-report surface this tool actually recovered — see
  :class:`ExclusionCascade`'s ``canonical_player_games``/
  ``canonical_player_games_player_resolved``, computed *after* collapsing
  observations by resolved ``player_id`` so spelling variants of the same
  real player across separate captures never double-count.
* **"No observation" is not one thing.** :func:`coverage_for_games`
  distinguishes a real observation; a legacy-schema row this tool cannot
  trust regardless of its status (``legacy_excluded``); a team that only
  ever said ``NOT_YET_SUBMITTED`` before tip-off; a masthead that was
  genuinely fetched and covered this game's window but never mentioned it —
  the parser emits no row at all for a team with zero listed injuries, so
  this is the only way to see "submitted, clean" (``submitted_zero_listed``)
  rather than "never attempted" (``no_candidate_coverage``); and a game this
  tool cannot reason about at all because its tip-off was never ingested
  (``missing_tipoff``).
* **A stage that counts only what a prior filter already resolved cannot
  show loss.** :func:`exclusion_cascade`'s raw-entry stages scope by the
  calendar dates in scope, not by ``game_id`` — the earlier version filtered
  by ``game_id.in_(...)`` before counting how many entries *resolved* a
  ``game_id``, which can never show anything but 100%. A bounded sample of
  exactly which rows failed to resolve is persisted alongside the count.
* **Coverage evidence must be bound to the exact request it answers.**
  :func:`_expected_coverage_matches_scope` and ``exclusion_cascade``'s
  ``start``/``end`` filtering stop a persisted expected-slate file or
  accumulated coverage report from a *different* season/range being
  silently presented as if it answered the current one.
* **An anchor's offset is not a game's realized lead time.** Every game on a
  shared report date anchors to that date's single earliest tip-off (see
  ``build_plan``), so a later game's true
  ``tipoff_utc - report_timestamp`` is strictly larger than the anchor
  offset that produced the candidate. ``ReportCandidate.anchor_offset_minutes``
  / ``CandidateCoverage.anchor_offset_minutes`` name the anchor's intent;
  ``CanonicalPregameObservation.lead_time_minutes`` is the realized,
  per-game value downstream stratification must use instead.

None of this computes or reports a rate — see the module-level warning above.

## Everything else is already solved and reused, not reinvented

* **Fetch, rate-limit, retry, cache** — :class:`~hoops_gm.ingest.injury_report
  .client.InjuryReportClient` unchanged. This module never touches
  ``urllib`` directly.
* **Canonical masthead dedupe** — already structural. Two different
  requested candidate instants that resolve to the same underlying PDF
  converge on the same natural key
  (``report_timestamp, team_raw, player_name_raw, game_date``) inside
  ``import_injury_report_entries``; nothing new is needed here beyond calling
  that importer the normal way.
* **Parsing** — :func:`~hoops_gm.ingest.injury_report.parser
  .parse_injury_report_pdf` unchanged.
* **Persistence** — :func:`~hoops_gm.ingest.importers.import_injury_report_entries`
  unchanged; every fetched capture's full entry set is imported (not merely
  the single canonical row later selected), so ``injury_report_entries``
  keeps the entire observed status history, not just the pregame snapshot.

## Bounded, resumable, honest about failure

* ``build_plan`` never touches the network; it only reads already-ingested
  games and checks local cache freshness, so an operator can see the exact
  request count *before* deciding to run it.
* **The ``run`` command additionally verifies an independent expected-game
  slate before any injury-report HTTP call** —
  :func:`enforce_expected_game_coverage`, using one cached, throttled
  ``LeagueGameFinder`` request (the same endpoint
  ``hoops_gm.ingest.backfill`` already uses to ingest a season's games).
  ``build_plan``'s own tip-off gate (:func:`enforce_full_tipoff_coverage`)
  can only ever see games already present in this project's database — it
  cannot detect a game that was never ingested at all, so a small,
  incidentally-ingested subset of a much larger range could otherwise pass
  "by construction". Found by independent review; see
  :class:`IncompleteExpectedGameCoverage`.
* ``enforce_request_budget`` refuses to run a plan whose live-fetch count
  exceeds an explicit cap, rather than silently making an unbounded number of
  requests to a CDN this project is a guest on.
* A JSON checkpoint file records each candidate's outcome as it completes, so
  an interrupted run resumes by skipping already-settled candidates rather
  than re-deriving or re-requesting them — the cache and the natural-key
  import already make a re-request cheap and idempotent, but avoiding the
  request entirely is strictly better manners toward an undocumented CDN path.
  The checkpoint's identity includes the exact resolved ``report_timestamp``,
  not merely the date and anchor label, so a later-corrected tip-off cannot
  leave a stale entry vouching for a URL it was never actually checked
  against — see :meth:`Checkpoint.key`.
* A per-candidate failure is caught, recorded and does not abort the run —
  the same failure-atomicity pattern ``backfill_season`` already uses for
  per-game failures — but ``ReportNotAvailable`` (missing, the ordinary case)
  and any other :class:`~hoops_gm.ingest.errors.SourceError` (drift — a
  changed filename format, a body that stopped being a PDF, an unrecognized
  status) are counted and reported *separately*, because conflating "this
  timestamp had no report" with "the source's contract broke" is precisely
  the silent-degradation failure mode ADR-h2 (``docs/handoff.md`` house
  rules) warns against. An HTTP 403 is a third case, distinct from both: it
  is never checkpointed as settled, in any run, because a 403 can be a
  WAF/rate-limit response rather than confirmed absence — see
  :func:`run_backfill`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Final, Protocol, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from hoops_gm.core.config import get_settings
from hoops_gm.db.models.enums import InjuryReportStatus, SeasonType
from hoops_gm.db.models.identity import NbaTeam
from hoops_gm.db.models.injury_report import CURRENT_EVIDENCE_SCHEMA_VERSION, InjuryReportEntry
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.db.session import Database
from hoops_gm.ingest.errors import SourceError
from hoops_gm.ingest.importers import ImportCounts, import_injury_report_entries
from hoops_gm.ingest.injury_report.client import (
    DEFAULT_MAX_AGE,
    InjuryReportClient,
    ReportNotAvailable,
    is_fifteen_minute_era,
    report_url,
)
from hoops_gm.ingest.injury_report.models import InjuryReportParseResult
from hoops_gm.ingest.injury_report.parser import ENDPOINT, SOURCE, parse_injury_report_pdf
from hoops_gm.ingest.nba import NbaGameRecord, NbaStatsClient, parse_league_game_finder
from hoops_gm.ingest.rawstore import RawPayloadStore

EASTERN: Final = ZoneInfo("America/New_York")

#: Applies unconditionally in both URL eras — see the module docstring.
EVENING_BEFORE_ET: Final = time(17, 30)
#: Legacy-era only: a cheap opportunistic second fixed-clock guess. The
#: legacy URL's hour-truncation plus the parser's 45-minute masthead-drift
#: tolerance make this useful; neither holds in the 15-minute era, where
#: :data:`NEAR_TIP_OFFSETS` is used instead.
GAME_DAY_ET: Final = time(13, 0)
#: 15-minute-era only: fixed offsets before a date's earliest applicable
#: tip-off instant, replacing the single fixed-clock ``GAME_DAY_ET`` guess.
#: See the module docstring for why a wall-clock anchor stopped working once
#: the URL became an exact-minute match with no drift tolerance. Bounded —
#: four requests per date, not a sweep of the whole afternoon.
NEAR_TIP_OFFSETS: Final[tuple[timedelta, ...]] = (
    timedelta(minutes=150),
    timedelta(minutes=90),
    timedelta(minutes=45),
    timedelta(minutes=15),
)

DEFAULT_RAW_ROOT: Final = Path("data") / "raw"
DEFAULT_CHECKPOINT_DIR: Final = Path("data") / "reports"
DEFAULT_MAX_REQUESTS: Final = 250
#: Refuse to run against a requested game scope with any missing tip-off by
#: default — see :func:`enforce_full_tipoff_coverage`.
DEFAULT_ALLOW_MISSING_TIPOFF: Final = 0
#: Consecutive HTTP 403s (not 404s) before a run aborts rather than treating
#: each one as ordinary "not published" — see :func:`run_backfill` and
#: ``client.ReportNotAvailable``.
DEFAULT_MAX_FORBIDDEN_STREAK: Final = 3

#: A live fetch is forced rather than reusing any local capture, however
#: recent — the CLI's ``--no-cache`` flag. Distinct from *not attaching* a
#: store at all, which would also stop the raw capture being written at all.
NO_CACHE: Final = timedelta(0)

#: :class:`CandidateCoverage`/:class:`CoverageReport` JSON schema version.
#: Bumped to 2 for round-7 review point 3: version 1 persisted
#: ``applicable_game_ids`` as the sole evidence identity, a surrogate
#: ``NbaGame.id`` that a DB rebuild/reingestion can reuse for an entirely
#: different game. A version-1 record cannot be trusted to say which game it
#: actually covers and is excluded (not silently matched) by
#: :func:`coverage_for_games` — see :data:`LEGACY_COVERAGE_SCHEMA_VERSION`.
#: Bumped to 3 for round-10 review point 2: a version-2 candidate carries no
#: ``season``/``season_type`` of its own, only the enclosing
#: :class:`CoverageReport`'s -- ``_persist_coverage`` merging by
#: ``(report_date, anchor, requested_timestamp)`` alone could not detect a
#: stored candidate that actually belongs to a different season/season_type
#: than the one it is being merged into, silently laundering it into the
#: caller's trusted scope on rewrite. A version-3 record self-describes its
#: own season/season_type, exactly like every other exact-match scope field
#: this version already requires; an older record is excluded rather than
#: silently trusted with a guessed scope.
CURRENT_COVERAGE_SCHEMA_VERSION: Final[int] = 3
#: Any persisted candidate lacking ``evidence_schema_version`` (every record
#: written before this fix) is treated as this version, never silently
#: upgraded.
LEGACY_COVERAGE_SCHEMA_VERSION: Final[int] = 1


# --------------------------------------------------------------------------
# Candidate report timestamps
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportCandidate:
    """One guessed report instant for one calendar date, and why."""

    report_date: date
    anchor: str  # "evening_before" | "game_day" | "near_tip_<N>"
    #: Timezone-aware (Eastern, the wall clock the source itself is
    #: published in); compared against ``NbaGame.tipoff_utc`` via normal
    #: aware-datetime comparison, never converted to a naive value.
    report_timestamp: datetime
    #: Minutes before the date's earliest applicable tip-off this candidate
    #: *intended* to land, for a ``near_tip_*`` anchor; ``None`` for a
    #: fixed-clock anchor (``evening_before``/``game_day``), which is not
    #: tip-off relative. Durable evidence for the coverage report — see
    #: :class:`CandidateCoverage`.
    #:
    #: **This is the anchor's offset, not any one game's realized lead
    #: time.** Every game sharing a report date anchors to that date's
    #: single *earliest* tip-off (see :func:`build_plan`), so a later game
    #: on the same date has a strictly larger realized
    #: ``tipoff_utc - report_timestamp`` than this number suggests — round-5
    #: review point 5. The per-game realized value lives on
    #: ``CanonicalPregameObservation.lead_time_minutes`` instead, computed
    #: against that specific game's own tip-off.
    anchor_offset_minutes: int | None = None


def _floor_to_quarter_hour_et(instant: datetime) -> datetime:
    """Floor to the prior (or exact) 15-minute Eastern wall-clock mark.

    The 15-minute-era URL is an **exact-minute match** against a
    ``:00``/``:15``/``:30``/``:45`` grid (see ``client.report_url`` — no
    drift tolerance at the transport layer). A candidate computed as a
    fixed offset before a non-grid-aligned tip-off (e.g. 19:10 or 19:40 ET)
    lands on a minute the source can never have published at, and was
    silently unable to match any real masthead. Floors, never rounds, so
    the candidate never moves *later* than the offset intended — rounding
    forward could push a near-tip candidate past its own offset or even
    past tip-off itself, which would be a lookahead bug, not merely an
    imprecise guess.
    """
    eastern = instant.astimezone(EASTERN)
    floored_minute = (eastern.minute // 15) * 15
    return eastern.replace(minute=floored_minute, second=0, microsecond=0)


def candidate_report_timestamps(
    report_date: date, *, earliest_tipoff_utc: datetime | None = None
) -> tuple[ReportCandidate, ...]:
    """The anchor instants that might carry a report relevant to this date.

    ``evening_before`` (the day prior at 17:30 ET) is tried for every date in
    both URL eras. What is tried *in addition* depends on which URL era the
    date falls in — see the module docstring for why a single fixed
    wall-clock guess is unsafe in the 15-minute era:

    * If ``report_date`` is in the 15-minute era (2025-12-22 onward) *and*
      ``earliest_tipoff_utc`` is known, a bounded set of
      :data:`NEAR_TIP_OFFSETS` candidates anchored to that instant, each
      floored to the source's exact 15-minute grid (see
      :func:`_floor_to_quarter_hour_et`) — not the raw offset instant, which
      the source can never publish at unless tip-off itself happens to be
      grid-aligned. Two offsets that floor to the same grid mark collapse to
      one candidate (the larger, more conservative lead time keeps its
      label) rather than requesting the identical URL twice.
    * Otherwise (legacy era, or the era is unknown because no game's
      tip-off has been ingested for this date yet), the original fixed
      ``game_day`` guess (13:00 ET the date itself).
    """
    evening_before = ReportCandidate(
        report_date,
        "evening_before",
        datetime.combine(report_date - timedelta(days=1), EVENING_BEFORE_ET, tzinfo=EASTERN),
    )

    if earliest_tipoff_utc is not None and is_fifteen_minute_era(earliest_tipoff_utc):
        by_aligned_instant: dict[datetime, ReportCandidate] = {}
        for offset in NEAR_TIP_OFFSETS:
            aligned = _floor_to_quarter_hour_et(earliest_tipoff_utc - offset)
            if aligned >= earliest_tipoff_utc:
                continue  # pragma: no cover - degenerate; flooring only moves earlier
            anchor_offset_minutes = int(offset.total_seconds() // 60)
            by_aligned_instant.setdefault(
                aligned,
                ReportCandidate(
                    report_date,
                    f"near_tip_{anchor_offset_minutes}",
                    aligned,
                    anchor_offset_minutes=anchor_offset_minutes,
                ),
            )
        return (evening_before, *by_aligned_instant.values())

    game_day = ReportCandidate(
        report_date, "game_day", datetime.combine(report_date, GAME_DAY_ET, tzinfo=EASTERN)
    )
    return (evening_before, game_day)


# --------------------------------------------------------------------------
# Games in scope
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BackfillGame:
    """One already-ingested game this tool can attach a canonical report to."""

    game_id: int
    nba_game_id: str
    game_date: date
    tipoff_utc: datetime


@dataclass(frozen=True)
class MissingTipoffGame:
    """A game in scope whose tip-off instant has not been ingested yet.

    Reported loudly rather than silently skipped or guessed: schedule ingest
    is this tool's precondition, not something it duplicates, and a game
    missing here means the source schedule ingest has not finished, not that
    it never had a tip-off.
    """

    game_id: int
    nba_game_id: str
    game_date: date


def games_to_backfill(
    session: Session,
    *,
    season: str,
    season_type: SeasonType,
    start: date | None = None,
    end: date | None = None,
) -> tuple[tuple[BackfillGame, ...], tuple[MissingTipoffGame, ...]]:
    """Already-ingested games in scope, split by whether ``tipoff_utc`` is known.

    Exact schedule lineage: this reads ``nba_games`` rows for one explicit
    ``(season, season_type)`` — never inferred, never mixed across a season
    boundary — which are exactly the rows ``hoops_gm.ingest.backfill`` and
    ``hoops_gm.ingest.nba.schedule`` already ingested and are the sole source
    of truth this tool trusts for "what games happened and when they tipped".
    """
    stmt = select(NbaGame).where(NbaGame.season == season, NbaGame.season_type == season_type)
    if start is not None:
        stmt = stmt.where(NbaGame.game_date >= start)
    if end is not None:
        stmt = stmt.where(NbaGame.game_date <= end)

    ready: list[BackfillGame] = []
    missing: list[MissingTipoffGame] = []
    for game in session.scalars(stmt.order_by(NbaGame.game_date, NbaGame.nba_game_id)):
        if game.tipoff_utc is None:
            missing.append(
                MissingTipoffGame(
                    game_id=game.id, nba_game_id=game.nba_game_id, game_date=game.game_date
                )
            )
        else:
            ready.append(
                BackfillGame(
                    game_id=game.id,
                    nba_game_id=game.nba_game_id,
                    game_date=game.game_date,
                    tipoff_utc=game.tipoff_utc,
                )
            )
    return tuple(ready), tuple(missing)


# --------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannedFetch:
    """One candidate this plan intends to check, and which games it covers."""

    candidate: ReportCandidate
    applicable_game_ids: tuple[int, ...]
    #: Stable NBA game identifiers for the same games ``applicable_game_ids``
    #: names by surrogate DB id — see :data:`CURRENT_COVERAGE_SCHEMA_VERSION`.
    applicable_nba_game_ids: tuple[str, ...]
    already_cached: bool


@dataclass(frozen=True)
class BackfillPlan:
    """A fully-derived, network-free plan: what would be fetched and why."""

    season: str
    season_type: SeasonType
    fetches: tuple[PlannedFetch, ...]
    missing_tipoff: tuple[MissingTipoffGame, ...]

    @property
    def to_fetch(self) -> tuple[PlannedFetch, ...]:
        return tuple(f for f in self.fetches if not f.already_cached)

    def render(self) -> str:
        lines = [
            f"plan: season={self.season} season_type={self.season_type.value} "
            f"candidates={len(self.fetches)} to_fetch={len(self.to_fetch)} "
            f"already_cached={len(self.fetches) - len(self.to_fetch)}"
        ]
        for pf in self.fetches:
            state = "cached" if pf.already_cached else "fetch"
            lines.append(
                f"  [{state}] {pf.candidate.report_date} {pf.candidate.anchor:14s} "
                f"{pf.candidate.report_timestamp.isoformat()} "
                f"-> {len(pf.applicable_game_ids)} game(s)"
            )
        if self.missing_tipoff:
            lines.append(
                f"\n  {len(self.missing_tipoff)} game(s) excluded: no ingested tip-off instant "
                "(ingest the schedule/box-score summary for these first):"
            )
            for mg in self.missing_tipoff[:20]:
                lines.append(f"    {mg.nba_game_id} {mg.game_date}")
            if len(self.missing_tipoff) > 20:
                lines.append(f"    ... and {len(self.missing_tipoff) - 20} more")
        return "\n".join(lines)


def build_plan(
    session: Session,
    *,
    season: str,
    season_type: SeasonType = SeasonType.REGULAR,
    start: date | None = None,
    end: date | None = None,
    store: RawPayloadStore | None = None,
) -> BackfillPlan:
    """Derive the full candidate set for a season/date range. No network calls.

    Candidate applicability (no lookahead) is decided here per-game against
    each game's own ``tipoff_utc``; a candidate with an empty
    ``applicable_game_ids`` for every game in scope is still recorded so the
    plan is honest about *why* a date has only some of its candidates
    applicable, but it is never counted toward the request budget or fetched
    by ``run_backfill``. Each date's near-tip candidates (15-minute era, see
    :func:`candidate_report_timestamps`) anchor to that date's own earliest
    applicable tip-off among the games actually in scope here.
    """
    ready, missing = games_to_backfill(
        session, season=season, season_type=season_type, start=start, end=end
    )
    by_date: dict[date, list[BackfillGame]] = {}
    for game in ready:
        by_date.setdefault(game.game_date, []).append(game)

    fetches: list[PlannedFetch] = []
    for report_date in sorted(by_date):
        games_that_date = by_date[report_date]
        earliest_tipoff = min(g.tipoff_utc for g in games_that_date)
        for candidate in candidate_report_timestamps(
            report_date, earliest_tipoff_utc=earliest_tipoff
        ):
            applicable_games = [
                g for g in games_that_date if candidate.report_timestamp < g.tipoff_utc
            ]
            if not applicable_games:
                continue
            cached = False
            if store is not None:
                cached = (
                    store.fresh(
                        source=SOURCE,
                        endpoint=ENDPOINT,
                        params={"url": report_url(candidate.report_timestamp)},
                        max_age=DEFAULT_MAX_AGE,
                    )
                    is not None
                )
            fetches.append(
                PlannedFetch(
                    candidate=candidate,
                    applicable_game_ids=tuple(g.game_id for g in applicable_games),
                    applicable_nba_game_ids=tuple(g.nba_game_id for g in applicable_games),
                    already_cached=cached,
                )
            )

    return BackfillPlan(
        season=season, season_type=season_type, fetches=tuple(fetches), missing_tipoff=missing
    )


class BackfillBudgetExceeded(RuntimeError):
    """A plan's live-fetch count exceeds the explicit request budget."""


# --------------------------------------------------------------------------
# Expected-game slate (independent of what is already in this project's DB)
# --------------------------------------------------------------------------


class IncompleteExpectedGameCoverage(RuntimeError):
    """The official schedule has games this project never ingested at all.

    :func:`enforce_full_tipoff_coverage` can only ever compare games already
    present in ``nba_games`` — it is structurally blind to a game that was
    never ingested into this project's own database in the first place, so
    a small, incidentally-ingested subset of a much larger requested range
    could pass that gate "by construction" (22 games having an ingested
    tip-off out of a 527-game season is not evidence the season is
    cohort-ready if the other 505 were never even fetched). This exception
    is raised instead, from an *independent* source of truth — the same
    official ``LeagueGameFinder`` endpoint ``hoops_gm.ingest.backfill``
    already uses to ingest a season's games in the first place, cached and
    throttled by :class:`~hoops_gm.ingest.nba.client.NbaStatsClient` the
    normal way — before any injury-report HTTP call.

    ``coverage`` carries the full evidence computed before raising (what was
    expected, what was missing) so a caller can persist it durably even on
    this failure path, the same reasoning as
    ``SuspectedSourceBlock.partial_result``.
    """

    def __init__(self, message: str, *, coverage: ExpectedGameCoverage) -> None:
        super().__init__(message)
        self.coverage = coverage


@dataclass(frozen=True)
class ExpectedGameCoverage:
    """Durable evidence: the official schedule vs. what this project ingested.

    Persisted to disk (see :func:`write_expected_game_coverage`) so an
    operator — or the ``observations`` CLI's exclusion cascade — can answer
    "was the requested range's schedule actually complete" without a live
    network call every time.
    """

    season: str
    season_type: str
    start: str | None  # ISO date
    end: str | None  # ISO date
    expected_count: int
    ingested_count: int
    #: ``(nba_game_id, game_date)`` for every officially-scheduled game in
    #: range this project's own database has no row for at all — a strictly
    #: stronger gap than :class:`MissingTipoffGame`, which requires the game
    #: to already exist locally.
    missing: tuple[tuple[str, str], ...] = ()

    def to_json(self) -> str:
        return json.dumps(
            {
                "season": self.season,
                "season_type": self.season_type,
                "start": self.start,
                "end": self.end,
                "expected_count": self.expected_count,
                "ingested_count": self.ingested_count,
                "missing": [list(pair) for pair in self.missing],
            },
            indent=2,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, text: str) -> ExpectedGameCoverage:
        raw = json.loads(text)
        return cls(
            season=raw["season"],
            season_type=raw["season_type"],
            start=raw.get("start"),
            end=raw.get("end"),
            expected_count=raw["expected_count"],
            ingested_count=raw["ingested_count"],
            missing=tuple((pair[0], pair[1]) for pair in raw.get("missing", [])),
        )


def _expected_coverage_matches_scope(
    coverage: ExpectedGameCoverage | None,
    *,
    season: str,
    season_type: SeasonType,
    start: date | None,
    end: date | None,
) -> bool:
    """Whether persisted expected-slate evidence matches *this exact* request.

    Round-5 review point 4: :func:`default_expected_coverage_path` is keyed
    only on ``(season, season_type)``, not ``(start, end)``, so a November
    ``run`` followed by a March ``observations`` call for the same season
    would otherwise silently present November's expected-slate evidence
    (``expected_count``/``missing``) as if it answered the March question.
    The persisted file always carries the exact range it was computed
    against; this is a plain equality check against the current request, not
    a re-fetch.
    """
    if coverage is None:
        return False
    return (
        coverage.season == season
        and coverage.season_type == season_type.value
        and coverage.start == (start.isoformat() if start else None)
        and coverage.end == (end.isoformat() if end else None)
    )


#: Injected at this seam (mirrors :data:`FetchAndParse`) so a test double
#: never needs a real ``NbaStatsClient`` or a real network call.
ExpectedGameFetcher = Callable[[str, str], Sequence[NbaGameRecord]]


def _expected_schedule_season_type_label(season_type: SeasonType) -> str:
    """Map to the official ``LeagueGameFinder`` ``season_type_nullable`` label.

    **v1 only supports REGULAR and PLAYOFFS.** The previous mapping —
    ``"Regular Season" if season_type is REGULAR else "Playoffs"`` — silently
    collapsed ``PRESEASON`` and ``PLAY_IN`` to ``"Playoffs"``. Querying the
    official schedule for e.g. preseason games under the ``"Playoffs"`` label
    returns an empty (or wrong) slate, and an empty ``expected`` sequence
    used to pass :func:`enforce_expected_game_coverage` vacuously — the exact
    fail-closed guarantee that gate exists to provide, defeated by a mapping
    bug upstream of it (round-5 review point 6). Raising here instead means
    a caller cannot silently run those two season types through an
    expected-slate check they were never actually validated against; extend
    this mapping deliberately, with its own test, before trusting it for a
    preseason or play-in range.
    """
    if season_type is SeasonType.REGULAR:
        return "Regular Season"
    if season_type is SeasonType.PLAYOFFS:
        return "Playoffs"
    raise ValueError(
        f"expected-game-slate fetching is not yet supported for season_type="
        f"{season_type.value!r} -- only 'regular' and 'playoffs' are mapped to "
        "LeagueGameFinder's season_type_nullable labels. Refusing to guess a label for "
        "preseason/play-in rather than silently reusing the 'Playoffs' slate."
    )


def default_expected_game_fetcher(nba: NbaStatsClient) -> ExpectedGameFetcher:
    def _fetch(season: str, season_type_label: str) -> Sequence[NbaGameRecord]:
        payload = nba.league_game_finder(season=season, season_type=season_type_label)
        internal_type = "regular" if season_type_label == "Regular Season" else "playoffs"
        return parse_league_game_finder(payload, season=season, season_type=internal_type)

    return _fetch


def enforce_expected_game_coverage(
    *,
    season: str,
    season_type: SeasonType,
    start: date | None,
    end: date | None,
    expected: Sequence[NbaGameRecord],
    ready: Sequence[BackfillGame],
    missing_tipoff: Sequence[MissingTipoffGame],
    allow_missing_games: int = 0,
) -> ExpectedGameCoverage:
    """Fail loudly, before any injury-report HTTP call, against an independent slate.

    ``expected`` is the official schedule for this ``(season, season_type)``
    (ordinarily ``default_expected_game_fetcher``'s output — one cached,
    throttled ``LeagueGameFinder`` request, not one request per game).
    ``allow_missing_games`` is the same kind of explicit, disclosed escape
    hatch as ``enforce_full_tipoff_coverage``'s ``allow_missing`` — never the
    default, so a deliberately partial run must say so.

    **Two additional fail-closed checks (round-5 review point 6), both
    raised before any per-game comparison:**

    * ``expected`` itself (the whole season, before ``--start``/``--end``
      filtering) is empty. A real NBA season is never zero games; this is
      almost always a wrong ``--season`` string, an unmapped
      ``--season-type`` (see :func:`_expected_schedule_season_type_label`),
      or an API/parsing failure upstream — never a legitimately empty slate.
    * ``expected`` has zero games *in the requested range* while this
      project's own database already has ingested game(s) there. The
      official schedule disagreeing with games this project itself already
      ingested from the NBA schedule is a scope mismatch (season string,
      season-type label, or an upstream failure), not evidence the range is
      genuinely empty.
    """
    if not expected:
        raise IncompleteExpectedGameCoverage(
            f"the official {season}/{season_type.value} schedule (LeagueGameFinder, whole "
            "season, before any --start/--end filtering) returned zero games. A real NBA "
            "season is never empty -- this is almost certainly a wrong --season string, an "
            "unsupported --season-type label, or an API/parsing failure, not a legitimately "
            "empty expected slate. Refusing to treat an empty response as passing evidence.",
            coverage=ExpectedGameCoverage(
                season=season,
                season_type=season_type.value,
                start=start.isoformat() if start else None,
                end=end.isoformat() if end else None,
                expected_count=0,
                ingested_count=0,
                missing=(),
            ),
        )

    ingested_ids = {g.nba_game_id for g in ready} | {g.nba_game_id for g in missing_tipoff}
    in_range = [
        g
        for g in expected
        if (start is None or g.game_date >= start) and (end is None or g.game_date <= end)
    ]
    if not in_range and (ready or missing_tipoff):
        raise IncompleteExpectedGameCoverage(
            f"the official {season}/{season_type.value} schedule shows zero games in the "
            f"requested range {start}..{end}, but this project's own database already has "
            f"{len(ready) + len(missing_tipoff)} ingested game(s) there. That disagreement "
            "means a --season/--season-type scope mismatch against the official schedule "
            "endpoint (or an upstream failure), not a legitimately empty range.",
            coverage=ExpectedGameCoverage(
                season=season,
                season_type=season_type.value,
                start=start.isoformat() if start else None,
                end=end.isoformat() if end else None,
                expected_count=0,
                ingested_count=0,
                missing=(),
            ),
        )

    missing = tuple(
        (g.nba_game_id, g.game_date.isoformat())
        for g in sorted(in_range, key=lambda g: (g.game_date, g.nba_game_id))
        if g.nba_game_id not in ingested_ids
    )
    coverage = ExpectedGameCoverage(
        season=season,
        season_type=season_type.value,
        start=start.isoformat() if start else None,
        end=end.isoformat() if end else None,
        expected_count=len(in_range),
        ingested_count=len(in_range) - len(missing),
        missing=missing,
    )
    if len(missing) > allow_missing_games:
        raise IncompleteExpectedGameCoverage(
            f"{len(missing)} game(s) in the official {season}/{season_type.value} schedule for "
            f"the requested range were never ingested into this project's database at all "
            f"(not merely missing a tip-off instant), exceeding "
            f"--allow-missing-games={allow_missing_games}. Ingest the season's games first "
            "(hoops_gm.ingest.backfill), narrow --start/--end to a range that is actually "
            "fully ingested, or pass an explicit --allow-missing-games to run a deliberately "
            "partial (and disclosed) subset.",
            coverage=coverage,
        )
    return coverage


def default_expected_coverage_path(season: str, season_type: SeasonType) -> Path:
    safe_season = season.replace("/", "-")
    name = f"injury_backfill_{safe_season}_{season_type.value}_expected_games.json"
    return DEFAULT_CHECKPOINT_DIR / name


def write_expected_game_coverage(path: Path, coverage: ExpectedGameCoverage) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(coverage.to_json(), encoding="utf-8")
    tmp.replace(path)  # atomic on the same volume, on POSIX and Windows alike


class IncompleteScheduleCoverage(RuntimeError):
    """The requested game scope has games with no ingested tip-off instant.

    Raised before any network call so a caller cannot mistake a small,
    incidentally-reachable subset of a requested range for a complete,
    cohort-ready backfill of that whole range. 22 games having an ingested
    tip-off out of 527 requested is not evidence the requested range is
    ready — it is evidence the other 505 need their schedule ingested first,
    or that ``--start``/``--end`` should be narrowed to what is actually
    fully covered, or that a deliberately partial run needs an explicit,
    disclosed override.
    """


def enforce_full_tipoff_coverage(plan: BackfillPlan, *, allow_missing: int = 0) -> None:
    """Fail loudly, before any network call, if scheduling coverage is incomplete.

    ``allow_missing`` is an explicit, disclosed escape hatch (the CLI's
    ``--allow-missing-tipoff``) for a deliberately partial run — it is never
    the default, so a caller cannot silently run a bounded demonstration
    subset and have it look, in the plan/run output, like the entire
    requested range was covered.
    """
    if len(plan.missing_tipoff) > allow_missing:
        raise IncompleteScheduleCoverage(
            f"{len(plan.missing_tipoff)} game(s) in the requested range have no ingested "
            f"tip-off instant, exceeding --allow-missing-tipoff={allow_missing}. Ingest their "
            "schedule/box-score summary first, narrow --start/--end to a range that is "
            "actually fully covered, or pass an explicit --allow-missing-tipoff to run a "
            "deliberately partial (and disclosed) subset."
        )


def enforce_request_budget(
    plan: BackfillPlan, *, max_requests: int, force_refetch: bool = False
) -> None:
    """Fail loudly, before any network call, if the plan is too large.

    ``force_refetch`` mirrors ``--no-cache``: every candidate becomes a live
    request regardless of local cache state, so the budget must be checked
    against the full candidate count, not just the currently-uncached ones.
    """
    count = len(plan.fetches) if force_refetch else len(plan.to_fetch)
    if count > max_requests:
        raise BackfillBudgetExceeded(
            f"plan requires {count} live request(s), exceeding --max-requests={max_requests}; "
            "narrow --start/--end or raise the cap explicitly"
        )


# --------------------------------------------------------------------------
# Checkpoint
# --------------------------------------------------------------------------

#: Outcomes that mean "this candidate is settled"; an "error" outcome is
#: deliberately excluded so a resumed run retries it rather than treating a
#: prior failure as permanent.
_SETTLED_OUTCOMES: Final = frozenset({"fetched", "not_available"})


@dataclass
class Checkpoint:
    """Per-candidate progress, persisted so a crashed run can resume.

    A second, independent layer of protection on top of the raw-payload cache
    (avoids re-requesting an unpublished timestamp from the network) and the
    natural-key import (avoids re-processing already-imported rows) — a
    resumed run without this file would still be correct, only slower.
    """

    path: Path
    #: Each entry's ``applicable_nba_game_ids`` is a ``list[str]``, everything
    #: else a ``str`` -- see round-10 review point 3 in :meth:`is_settled`.
    _state: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Checkpoint:
        state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        return cls(path=path, _state=state)

    @staticmethod
    def key(candidate: ReportCandidate) -> str:
        """Identity for one settled candidate.

        Includes the *exact resolved* ``report_timestamp``, not merely
        ``(report_date, anchor)``. A near-tip anchor's actual instant is
        derived from a date's earliest ingested tip-off (see
        :func:`candidate_report_timestamps`); if that tip-off is later
        corrected or newly ingested, the *same* ``(date, anchor)`` pair now
        names a genuinely different URL. Keying on ``(date, anchor)`` alone
        would let a stale settled entry silently vouch for a URL it was
        never actually checked against. Embedding the resolved timestamp
        means a changed instant simply misses the old key — the candidate
        is unsettled again and is correctly re-fetched, rather than trusted
        under a mismatch. See the round-4 review finding in docs/handoff.md.
        """
        return (
            f"{candidate.report_date.isoformat()}:{candidate.anchor}:"
            f"{candidate.report_timestamp.isoformat()}"
        )

    def is_settled(
        self, candidate: ReportCandidate, *, applicable_nba_game_ids: Sequence[str] = ()
    ) -> bool:
        """Whether this exact candidate is already resolved for this scope.

        **Round-10 review point 3.** ``(date, anchor, resolved timestamp)``
        alone is not the whole identity of what was actually settled: a
        ``--allow-missing-tipoff`` run can settle a candidate against only
        the games with an ingested tip-off *at the time*. Near-tip anchors
        resolve to a date's own *earliest* applicable tip-off
        (:func:`candidate_report_timestamps`), so a later same-day game
        gaining a tip-off afterward does not change this candidate's
        resolved timestamp at all — the same key still matches on resume.
        Without this check, that game's coverage would stay
        ``no_candidate_coverage`` forever, even though the exact URL this
        candidate names was already fetched (or already confirmed
        ``not_available``) and genuinely does apply to it now.

        The entry's own recorded ``applicable_nba_game_ids`` — the stable
        NBA game ids :func:`run_backfill` actually passed to
        :meth:`record` when this candidate was settled — is compared
        against the ids supplied here. Any id present now but absent from
        what was recorded means the settled scope is stale: report
        unsettled so ``run_backfill`` reprocesses this candidate.
        Reprocessing is idempotent either way — a "fetched" candidate's
        payload is already cached by the raw-payload store (no new network
        request), re-import is idempotent by natural key, and a
        "not_available" candidate simply stays not_available — only the
        recorded scope changes, expanding coverage to the new game.

        A settled entry recorded with an **empty** scope is either a
        genuine zero-game candidate (never actually produced by
        :func:`build_plan`, which only ever plans candidates with at least
        one applicable game) or, far more likely, a legacy entry that
        predates this field entirely. Trusting it as covering an
        arbitrary non-empty current scope would silently upgrade an
        artifact this code cannot actually verify; it is only considered
        settled here when the current request is *also* empty.
        """
        entry = self._state.get(self.key(candidate))
        if entry is None or entry.get("status") not in _SETTLED_OUTCOMES:
            return False
        settled_scope = set(entry.get("applicable_nba_game_ids", ()))
        if not settled_scope:
            return not applicable_nba_game_ids
        return set(applicable_nba_game_ids) <= settled_scope

    def record(
        self,
        candidate: ReportCandidate,
        status: str,
        detail: str = "",
        *,
        applicable_nba_game_ids: Sequence[str] = (),
    ) -> None:
        self._state[self.key(candidate)] = {
            "status": status,
            "detail": detail,
            "report_timestamp": candidate.report_timestamp.isoformat(),
            "applicable_nba_game_ids": sorted(applicable_nba_game_ids),
        }
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._state, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)  # atomic on the same volume, on POSIX and Windows alike


def default_checkpoint_path(season: str, season_type: SeasonType) -> Path:
    safe_season = season.replace("/", "-")
    return DEFAULT_CHECKPOINT_DIR / f"injury_backfill_{safe_season}_{season_type.value}.json"


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------

#: Injected at this seam so orchestration tests never need a real PDF or a
#: real network call — see ``client.py``'s own ``opener`` seam for the same
#: reasoning at the transport layer.
FetchAndParse = Callable[[datetime], InjuryReportParseResult]


class _ReportFetcher(Protocol):
    """Structural type for the transport ``default_fetch_and_parse`` needs.

    Matches :class:`InjuryReportClient` by shape rather than by name, so a
    test double never has to subclass the real client just to satisfy mypy.
    """

    def fetch(self, report_timestamp: datetime, *, max_age: timedelta | None = None) -> bytes: ...


def default_fetch_and_parse(client: _ReportFetcher, *, no_cache: bool = False) -> FetchAndParse:
    def _fetch(report_timestamp: datetime) -> InjuryReportParseResult:
        body = client.fetch(report_timestamp, max_age=NO_CACHE if no_cache else None)
        return parse_injury_report_pdf(
            body, report_timestamp=report_timestamp, source_url=report_url(report_timestamp)
        )

    return _fetch


@dataclass(frozen=True)
class CandidateCoverage:
    """Durable, structured evidence for one attempted candidate.

    Written alongside the checkpoint (see :func:`write_coverage_report`) so
    an operator — or a later ``quant`` consumer building on this table — can
    answer "how much of the requested range is actually covered, and by
    what" without re-deriving it from console output or a one-off script.
    Nothing here computes a rate; it is denominator evidence only.
    """

    report_date: str  # ISO date
    anchor: str
    era: str  # "legacy" | "fifteen_minute"
    #: The anchor's *intended* offset (see ``ReportCandidate.anchor_offset_minutes``)
    #: -- not any one game's realized lead time. Renamed from ``lead_minutes``
    #: in round 5 to stop it being read as a per-game value.
    anchor_offset_minutes: int | None
    requested_timestamp: str  # ISO instant, the anchor actually requested
    applicable_game_ids: tuple[int, ...]
    #: Stable NBA game identifiers for the same games ``applicable_game_ids``
    #: names by surrogate DB id. This is what :func:`coverage_for_games`
    #: actually trusts for a ``submitted_zero_listed`` claim — round-7 review
    #: point 3. ``applicable_game_ids`` is retained only for human-readable
    #: display; a DB rebuild/reingestion can reuse a surrogate id for a
    #: wholly unrelated game, so it is never itself durable evidence
    #: identity.
    applicable_nba_game_ids: tuple[str, ...]
    outcome: str  # "fetched" | "not_available" | "forbidden" | "error" | "skipped_settled"
    status_code: int | None = None
    canonical_report_timestamp: str | None = None  # ISO, only when fetched
    entries_total: int = 0
    entries_not_yet_submitted: int = 0
    entries_listed: int = 0
    detail: str = ""
    #: See :data:`CURRENT_COVERAGE_SCHEMA_VERSION`. Any record persisted
    #: before round-7's stable-identity fix predates this field entirely;
    #: :meth:`CoverageReport.from_json` stamps those as
    #: :data:`LEGACY_COVERAGE_SCHEMA_VERSION` on load, never silently as
    #: current.
    evidence_schema_version: int = CURRENT_COVERAGE_SCHEMA_VERSION
    #: This candidate's own ``(season, season_type)`` -- round-10 review
    #: point 2. Not merely inherited from the enclosing
    #: :class:`CoverageReport`: a record loaded from disk and merged into a
    #: *different* :class:`CoverageReport` must be checked against its own
    #: recorded scope, not silently re-labelled with whatever scope it
    #: happens to be merged into. Empty string for anything predating this
    #: field (never a real season string), so it is never mistaken for a
    #: match against a current request.
    season: str = ""
    season_type: str = ""

    @classmethod
    def from_candidate(
        cls,
        candidate: ReportCandidate,
        *,
        applicable_game_ids: tuple[int, ...],
        applicable_nba_game_ids: tuple[str, ...],
        outcome: str,
        season: str,
        season_type: str,
        status_code: int | None = None,
        canonical_report_timestamp: datetime | None = None,
        entries_total: int = 0,
        entries_not_yet_submitted: int = 0,
        detail: str = "",
    ) -> CandidateCoverage:
        era = "fifteen_minute" if is_fifteen_minute_era(candidate.report_timestamp) else "legacy"
        return cls(
            report_date=candidate.report_date.isoformat(),
            anchor=candidate.anchor,
            era=era,
            anchor_offset_minutes=candidate.anchor_offset_minutes,
            requested_timestamp=candidate.report_timestamp.isoformat(),
            applicable_game_ids=applicable_game_ids,
            applicable_nba_game_ids=applicable_nba_game_ids,
            outcome=outcome,
            status_code=status_code,
            canonical_report_timestamp=(
                canonical_report_timestamp.isoformat()
                if canonical_report_timestamp is not None
                else None
            ),
            entries_total=entries_total,
            entries_not_yet_submitted=entries_not_yet_submitted,
            entries_listed=entries_total - entries_not_yet_submitted,
            detail=detail,
            season=season,
            season_type=season_type,
        )


#: Every field name :class:`CandidateCoverage` currently knows about. Used
#: by :meth:`CoverageReport.from_json` (round-11 follow-up) to strip any
#: stray key from a raw on-disk dict *before* it ever reaches the dataclass
#: constructor — a genuine future schema version may add fields this code
#: has never seen, and passing those through as keyword arguments would
#: crash with ``TypeError: unexpected keyword argument`` rather than being
#: quarantined.
_CANDIDATE_COVERAGE_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    f.name for f in fields(CandidateCoverage)
)


def _quarantined_incompatible_schema_candidate(
    evidence_schema_version: object,
) -> CandidateCoverage:
    """A safe placeholder for a record whose schema version is not current.

    Round-11 follow-up review point 1: before this fix, ``from_json`` always
    unpacked a raw candidate's *entire* dict as keyword arguments to
    :class:`CandidateCoverage`, trusting that its shape matched the current
    dataclass exactly. That is true for a current-version record, but never
    guaranteed for a legacy (pre-versioning) one or — the crash this closes
    — a realistic *future* version: one that adds a field this code has
    never seen raises ``TypeError`` at construction, and one that renames or
    drops a currently-required field (``report_date``, ``anchor``, etc.)
    raises a missing-argument ``TypeError`` instead. Either crashes the
    entire load, taking down ``observations`` and ``_persist_coverage``
    alike, rather than being quarantined.

    This function never attempts to interpret the incompatible record's
    shape at all — not even to opportunistically read fields that happen to
    share a name with the current schema, since a future version could
    repurpose a field name to mean something else entirely. It builds an
    inert, self-consistent placeholder carrying only the raw
    ``evidence_schema_version`` value through unchanged (even if it is not
    an ``int``, e.g. a malformed or missing-then-defaulted value), plus safe
    defaults for every other field. ``outcome`` is stamped as a sentinel
    that is not ``"fetched"``, and ``season``/``season_type`` as ``""`` —
    both already excluded by every existing trust check
    (:func:`coverage_for_games`'s ``candidate.outcome != "fetched"`` guard,
    :func:`_persist_coverage`'s ``(season, season_type)`` filter, and both
    functions' ``evidence_schema_version == CURRENT_COVERAGE_SCHEMA_VERSION``
    checks), so this placeholder is quarantined the same way an in-shape
    incompatible-version record already was — it just no longer crashes the
    loader on the way there.
    """
    return CandidateCoverage(
        report_date="",
        anchor="",
        era="",
        anchor_offset_minutes=None,
        requested_timestamp="",
        applicable_game_ids=(),
        applicable_nba_game_ids=(),
        outcome="quarantined_incompatible_schema_version",
        evidence_schema_version=cast(int, evidence_schema_version),
        season="",
        season_type="",
    )


@dataclass
class CoverageReport:
    """The full set of :class:`CandidateCoverage` records for one run.

    Persisted as JSON next to the checkpoint file — a reproducible,
    committed artifact a caller can read with the ``observations`` CLI
    subcommand, replacing an uncommitted one-off script as the
    operator-facing way to answer "what did this backfill actually cover".
    """

    season: str
    season_type: str
    candidates: list[CandidateCoverage] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "season": self.season,
                "season_type": self.season_type,
                "candidates": [vars(c) for c in self.candidates],
            },
            indent=2,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, text: str) -> CoverageReport:
        """Load persisted coverage, quarantining any non-current record.

        A record written before round-7's stable-identity fix has no
        ``applicable_nba_game_ids``/``evidence_schema_version`` keys at all
        — its JSON simply predates them. Defaulting the former to ``()`` and
        the latter to :data:`LEGACY_COVERAGE_SCHEMA_VERSION` here (rather
        than letting an absent key silently read as "current") is what lets
        :func:`coverage_for_games` fail closed on it instead of trusting a
        surrogate-id match that may no longer identify the same game.

        **Round-10 review point 2**: a record written before this round's
        fix (schema version 2 or earlier) has no per-candidate
        ``season``/``season_type`` keys either — default both to ``""``,
        never a guessed real value, so :func:`_persist_coverage` can never
        mistake a reconstructed default for genuine recorded scope.

        **Round-11 follow-up review point 1**: ``evidence_schema_version``
        is inspected *before* any attempt to build the current
        :class:`CandidateCoverage` shape from a raw candidate's dict — not
        only after, as a previous fix assumed. A record whose version is not
        exactly :data:`CURRENT_COVERAGE_SCHEMA_VERSION` (legacy, or a future
        version this code has never seen) is routed to
        :func:`_quarantined_incompatible_schema_candidate` instead, which
        never interprets that record's other fields at all. Only a
        current-version record's keys are unpacked into the dataclass
        constructor, and even then filtered to
        :data:`_CANDIDATE_COVERAGE_FIELD_NAMES` first, so a stray extra key
        can never reach the constructor and crash it either. Every
        incompatible record this loads is already excluded from every trust
        check downstream (:func:`coverage_for_games`,
        :func:`_persist_coverage`) — this only stops the loader itself from
        crashing before either ever runs.
        """
        raw = json.loads(text)
        candidates: list[CandidateCoverage] = []
        for c in raw["candidates"]:
            raw_version = c.get("evidence_schema_version", LEGACY_COVERAGE_SCHEMA_VERSION)
            if raw_version != CURRENT_COVERAGE_SCHEMA_VERSION:
                candidates.append(_quarantined_incompatible_schema_candidate(raw_version))
                continue
            known = {k: v for k, v in c.items() if k in _CANDIDATE_COVERAGE_FIELD_NAMES}
            candidates.append(
                CandidateCoverage(
                    **{
                        **known,
                        "applicable_game_ids": tuple(c["applicable_game_ids"]),
                        "applicable_nba_game_ids": tuple(c.get("applicable_nba_game_ids", ())),
                        "evidence_schema_version": raw_version,
                        "season": c.get("season", ""),
                        "season_type": c.get("season_type", ""),
                    }
                )
            )
        return cls(season=raw["season"], season_type=raw["season_type"], candidates=candidates)


def default_coverage_path(season: str, season_type: SeasonType) -> Path:
    safe_season = season.replace("/", "-")
    name = f"injury_backfill_{safe_season}_{season_type.value}_coverage.json"
    return DEFAULT_CHECKPOINT_DIR / name


def write_coverage_report(path: Path, report: CoverageReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(report.to_json(), encoding="utf-8")
    tmp.replace(path)  # atomic on the same volume, on POSIX and Windows alike


class SuspectedSourceBlock(RuntimeError):
    """A streak of consecutive HTTP 403s looks like a block, not "not published".

    Raised instead of silently recording every one of them as ordinary
    absence — though as of round 4, *no* 403 is ever recorded as ordinary
    absence regardless of streak length; see ``run_backfill`` and
    :data:`FORBIDDEN_OUTCOME`. This exception remains purely an early-abort
    optimization: a long run of 403s against in-season dates this tool is
    actually requesting is exactly what a WAF response or a rate-limit block
    dressed as a client error would look like, and there is no reason to
    keep burning the request budget against a source that looks blocked.
    ``partial_result`` carries every candidate's coverage evidence gathered
    before the abort, so a caller can persist it durably instead of losing
    it — see the round-4 review finding that an abort discarded all
    in-memory coverage for the run.
    """

    def __init__(self, message: str, *, partial_result: BackfillRunResult | None = None) -> None:
        super().__init__(message)
        self.partial_result = partial_result


@dataclass
class BackfillRunResult:
    """What a run actually did — the evidence a PR report is built from."""

    fetched: list[ReportCandidate] = field(default_factory=list)
    not_available: list[ReportCandidate] = field(default_factory=list)
    #: HTTP 403 responses. Never settled in the checkpoint (see
    #: ``run_backfill``) — distinct from :attr:`not_available` (404, or a
    #: 403 independently known-expected), which *is* confirmed absence.
    forbidden: list[ReportCandidate] = field(default_factory=list)
    skipped_settled: list[ReportCandidate] = field(default_factory=list)
    failures: list[tuple[ReportCandidate, str]] = field(default_factory=list)
    totals: ImportCounts = field(default_factory=ImportCounts)
    coverage: list[CandidateCoverage] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"  fetched: {len(self.fetched)}  not_available: {len(self.not_available)}  "
            f"forbidden (unsettled): {len(self.forbidden)}  "
            f"skipped (already settled): {len(self.skipped_settled)}  "
            f"failed: {len(self.failures)}",
            f"  imported: {self.totals}",
        ]
        if self.forbidden:
            lines.append("")
            lines.append(
                f"  {len(self.forbidden)} candidate(s) returned HTTP 403 and were left "
                "UNSETTLED (never recorded as confirmed absence — a 403 may be a WAF/rate-limit "
                "response, not evidence nothing was published). They will be retried on the next "
                "run. Investigate before trusting this range's coverage:"
            )
            for candidate in self.forbidden[:20]:
                lines.append(f"    {candidate.report_date} {candidate.anchor}")
            if len(self.forbidden) > 20:
                lines.append(f"    ... and {len(self.forbidden) - 20} more")
        if self.failures:
            lines.append("")
            lines.append(f"  {len(self.failures)} FAILURES (contract drift, not 'missing'):")
            for candidate, why in self.failures[:20]:
                lines.append(f"    {candidate.report_date} {candidate.anchor}: {why}")
            if len(self.failures) > 20:
                lines.append(f"    ... and {len(self.failures) - 20} more")
        return "\n".join(lines)


def run_backfill(
    session: Session,
    *,
    plan: BackfillPlan,
    fetch_and_parse: FetchAndParse,
    checkpoint: Checkpoint,
    progress: Callable[[str], None] = print,
    force_refetch: bool = False,
    max_forbidden_streak: int = DEFAULT_MAX_FORBIDDEN_STREAK,
    persist_coverage: Callable[[CandidateCoverage], None] | None = None,
) -> BackfillRunResult:
    """Fetch and import every not-yet-settled candidate in the plan, in order.

    **Every candidate in the plan is processed, regardless of
    ``already_cached``.** Caching is the transport's job
    (:class:`~hoops_gm.ingest.injury_report.client.InjuryReportClient`
    already serves a fresh local capture without a network call), not a
    reason for this orchestration layer to skip importing a candidate — a
    candidate whose raw PDF was cached on disk but never reached
    ``checkpoint.record(..., "fetched")`` (a crash between the two) must
    still be processed on resume, or its data is silently never imported at
    all. Only the checkpoint's settled-outcome gate (or ``force_refetch``
    bypassing it) decides whether a candidate is skipped.

    **A successful import is committed *before* the checkpoint records it as
    settled, not after.** A commit is a database round-trip that can fail
    (a constraint violation, a dropped connection, a full disk) after the
    checkpoint write already happened; recording "fetched" first would leave
    the checkpoint permanently — and wrongly — believing this candidate is
    done when nothing was actually persisted. Committing first and only then
    checkpointing means a commit failure is caught, rolled back, and
    recorded as an *unsettled* ``"error"`` so a resumed run retries it
    instead of silently losing it forever.

    **Round-11 review point 4: the importer's own internal flush is inside
    this same boundary, not before it.**
    :func:`~hoops_gm.ingest.importers.import_injury_report_entries` calls
    ``session.flush()`` itself, and a flush can fail for the identical
    reasons a commit can. Before this fix, that call sat outside any
    try/except in this function: a flush-time failure propagated straight
    out of ``run_backfill`` and aborted the entire run, rather than being
    handled as this one candidate's recorded, unsettled failure. The import
    call and ``session.commit()`` now share one ``try``/``except`` — a
    failure from either path takes the identical rollback + failure-
    coverage + checkpoint-``"error"`` treatment, and every other candidate
    in the plan still runs to completion.

    **This candidate's ``CandidateCoverage`` evidence is durably persisted
    (via ``persist_coverage``, when supplied) *before* ``checkpoint.record``
    settles it** — round-6 review point 1. Coverage previously only
    accumulated in ``result.coverage`` (an in-memory list, written to disk
    once, in bulk, at end of run); a crash between a settling
    ``checkpoint.record`` call and that end-of-run write left a "settled"
    candidate with *no* coverage record on disk, permanently, because a
    settled candidate is skipped without regenerating coverage on the next
    resume. Persisting coverage first establishes the invariant "checkpoint
    says settled implies coverage is already durable": a crash between the
    two calls either leaves both durable (the checkpoint write completed)
    or leaves coverage durable but the checkpoint still unsettled (safe —
    the candidate is simply reprocessed on resume, which is idempotent by
    natural key for import and by merge key for coverage, so this produces
    no duplicate import and no evidence hole).

    One candidate's failure does not abort the run — the same failure-
    atomicity pattern ``backfill_season`` uses for a per-game failure.
    ``ReportNotAvailable`` is not a failure: it is recorded and the run
    continues; any other :class:`~hoops_gm.ingest.errors.SourceError` is
    recorded as a genuine failure and surfaced loudly in the summary.

    **A 404 is checkpointed as settled ("not_available") immediately. An
    HTTP 403 is never checkpointed as settled — ever, in any run.** Round 3
    buffered a 403 within a single invocation until its streak was known not
    to be an abort; round-4 review correctly rejected that as insufficient,
    because it does not survive across separate CLI invocations (e.g. one
    process per date) and still let a short, non-aborting streak settle as
    confirmed absence on nothing but this tool's own guess. The simplest
    honest policy: a 403 is recorded as :attr:`BackfillRunResult.forbidden`
    and the checkpoint status ``"forbidden"`` (deliberately excluded from
    :data:`_SETTLED_OUTCOMES`), so it is retried on every future run,
    indefinitely, until the source actually answers with a 200 or a 404. The
    CLI surfaces any non-empty ``forbidden`` list with a nonzero exit code so
    an operator investigates rather than silently trusting a blocked source.
    A run of consecutive 403s crossing ``max_forbidden_streak`` still raises
    :class:`SuspectedSourceBlock` to stop burning the request budget against
    what looks like a block — but this is now purely an early-abort
    optimization, not something checkpoint correctness depends on, because
    nothing about a 403 is ever settled either way.
    """
    result = BackfillRunResult()
    to_process = list(plan.fetches)
    consecutive_forbidden = 0

    def _record_coverage(cov: CandidateCoverage) -> None:
        result.coverage.append(cov)
        if persist_coverage is not None:
            persist_coverage(cov)

    for index, pf in enumerate(to_process, start=1):
        candidate = pf.candidate
        if not force_refetch and checkpoint.is_settled(
            candidate, applicable_nba_game_ids=pf.applicable_nba_game_ids
        ):
            result.skipped_settled.append(candidate)
            continue

        try:
            parsed = fetch_and_parse(candidate.report_timestamp)
        except ReportNotAvailable as exc:
            if exc.status_code == 403:
                consecutive_forbidden += 1
                result.forbidden.append(candidate)
                _record_coverage(
                    CandidateCoverage.from_candidate(
                        candidate,
                        applicable_game_ids=pf.applicable_game_ids,
                        applicable_nba_game_ids=pf.applicable_nba_game_ids,
                        outcome="forbidden",
                        status_code=exc.status_code,
                        season=plan.season,
                        season_type=plan.season_type.value,
                    )
                )
                checkpoint.record(
                    candidate,
                    "forbidden",
                    "HTTP 403 — left unsettled",
                    applicable_nba_game_ids=pf.applicable_nba_game_ids,
                )
                if consecutive_forbidden >= max_forbidden_streak:
                    raise SuspectedSourceBlock(
                        f"{consecutive_forbidden} consecutive HTTP 403 responses ending at "
                        f"{candidate.report_date} {candidate.anchor} "
                        f"({candidate.report_timestamp.isoformat()}); this looks like a WAF "
                        f"or rate-limit block, not {consecutive_forbidden} coincidental "
                        "'not published' dates. Aborting to stop spending the request budget "
                        "against what looks like a block. None of these 403s were recorded as "
                        "settled — they remain forbidden/unsettled and will be retried.",
                        partial_result=result,
                    ) from exc
            else:
                result.not_available.append(candidate)
                _record_coverage(
                    CandidateCoverage.from_candidate(
                        candidate,
                        applicable_game_ids=pf.applicable_game_ids,
                        applicable_nba_game_ids=pf.applicable_nba_game_ids,
                        outcome="not_available",
                        status_code=exc.status_code,
                        season=plan.season,
                        season_type=plan.season_type.value,
                    )
                )
                checkpoint.record(
                    candidate,
                    "not_available",
                    applicable_nba_game_ids=pf.applicable_nba_game_ids,
                )
                consecutive_forbidden = 0
            continue
        except SourceError as exc:
            session.rollback()
            result.failures.append((candidate, str(exc)))
            _record_coverage(
                CandidateCoverage.from_candidate(
                    candidate,
                    applicable_game_ids=pf.applicable_game_ids,
                    applicable_nba_game_ids=pf.applicable_nba_game_ids,
                    outcome="error",
                    status_code=getattr(exc, "status_code", None),
                    detail=str(exc),
                    season=plan.season,
                    season_type=plan.season_type.value,
                )
            )
            checkpoint.record(
                candidate, "error", str(exc), applicable_nba_game_ids=pf.applicable_nba_game_ids
            )
            consecutive_forbidden = 0
            continue

        consecutive_forbidden = 0
        try:
            # Round-11 review point 4: the import call flushes internally
            # (see ``import_injury_report_entries``'s own ``session.flush()``)
            # before this function's own commit is ever reached. A flush can
            # fail for the exact same reasons a commit can -- a constraint
            # violation, a dropped connection -- and before this fix, that
            # flush sat entirely outside any try/except here: an exception
            # from it propagated straight out of ``run_backfill``, aborting
            # the *entire* run rather than being handled as one candidate's
            # recorded, unsettled failure. Import and commit are now one
            # shared rollback + failure-coverage + checkpoint-error boundary,
            # so a flush-time failure is indistinguishable from a commit-time
            # one to every downstream consumer: this candidate is rolled
            # back, recorded as an unsettled "error", and safely retried on
            # resume -- and every other candidate in the plan still runs.
            counts = import_injury_report_entries(
                session, parsed.entries, source_url=parsed.source_url
            )
            session.commit()
        except Exception as exc:  # an import/flush/commit failure must never look "settled"
            session.rollback()
            result.failures.append((candidate, f"import/commit failed: {exc}"))
            _record_coverage(
                CandidateCoverage.from_candidate(
                    candidate,
                    applicable_game_ids=pf.applicable_game_ids,
                    applicable_nba_game_ids=pf.applicable_nba_game_ids,
                    outcome="error",
                    detail=f"import/commit failed: {exc}",
                    season=plan.season,
                    season_type=plan.season_type.value,
                )
            )
            checkpoint.record(
                candidate,
                "error",
                f"import/commit failed: {exc}",
                applicable_nba_game_ids=pf.applicable_nba_game_ids,
            )
            continue

        result.totals.created += counts.created
        result.totals.updated += counts.updated
        result.totals.skipped += counts.skipped
        result.fetched.append(candidate)
        not_yet_submitted = sum(
            1 for e in parsed.entries if e.status is InjuryReportStatus.NOT_YET_SUBMITTED
        )
        _record_coverage(
            CandidateCoverage.from_candidate(
                candidate,
                applicable_game_ids=pf.applicable_game_ids,
                applicable_nba_game_ids=pf.applicable_nba_game_ids,
                outcome="fetched",
                canonical_report_timestamp=parsed.report_timestamp,
                entries_total=len(parsed.entries),
                entries_not_yet_submitted=not_yet_submitted,
                season=plan.season,
                season_type=plan.season_type.value,
            )
        )
        # Coverage is durable (persist_coverage, above) before this call
        # settles the candidate -- round-6 review point 1.
        checkpoint.record(candidate, "fetched", applicable_nba_game_ids=pf.applicable_nba_game_ids)

        if index % 25 == 0:
            progress(f"    {index}/{len(to_process)} candidates — {result.totals}")

    return result


# --------------------------------------------------------------------------
# Canonical pregame observation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CanonicalPregameObservation:
    """The latest pregame-only report row for one player on one game.

    Purely a selection over already-persisted, already-observed rows — no
    fitting, no rate, no probability. Computing ``p(play)`` from this belongs
    to ``injury-status-conversion`` (``quant``, Model gate), not here.
    """

    game_id: int
    team_raw: str
    player_name_raw: str
    player_id: int | None
    report_timestamp: datetime
    status: InjuryReportStatus
    status_raw: str
    reason_raw: str
    #: ``tipoff_utc - report_timestamp`` in whole minutes, for *this specific
    #: game's* own tip-off — not the anchor's intended offset
    #: (``ReportCandidate.anchor_offset_minutes``/``CandidateCoverage.
    #: anchor_offset_minutes``). Every game on a shared report date anchors
    #: to that date's single earliest tip-off (see ``build_plan``), so a
    #: later game's realized lead time is strictly larger than the anchor
    #: offset that produced the candidate — round-5 review point 5. This is
    #: the value downstream stratification (by lead time, by cadence era)
    #: must use.
    lead_time_minutes: int
    source_url: str
    import_schema_version: int


def _canonical_observation_key(entry: InjuryReportEntry) -> tuple[int, str, int | str]:
    """Collapse key for one canonical observation: player-identity aware.

    When ``player_id`` has resolved, two rows that spell the same real
    player differently (a name-parsing variant across separate report
    captures) must collapse to one canonical player-game — round-5 review
    point 7. When it has not resolved, the raw ``player_name_raw`` is kept as
    the identity instead, so an unresolved player is never accidentally
    merged with an unrelated unresolved row of a different raw spelling, nor
    with a resolved one. The third element is deliberately either an ``int``
    or a ``str`` — never coerced to a common type — so a resolved id and an
    unresolved name can never compare equal by coincidence.
    """
    identity: int | str = entry.player_id if entry.player_id is not None else entry.player_name_raw
    return (entry.game_id, entry.team_raw, identity)  # type: ignore[return-value]


def select_canonical_pregame_observations(
    session: Session,
    *,
    game_ids: Sequence[int],
    include_legacy: bool = False,
    game_tipoffs: Mapping[int, datetime] | None = None,
) -> tuple[CanonicalPregameObservation, ...]:
    """The single latest pre-tipoff report row per ``(game, team, player)``.

    Re-derives the no-lookahead gate independently from each row's own
    ``game_id`` and the game's current ``tipoff_utc`` — it does not trust any
    plan computed earlier, so a schedule correction made after a report was
    imported cannot leave a stale, wrong row looking canonical. A player with
    only ``NOT_YET_SUBMITTED`` rows before tip-off (names no player, i.e.
    ``player_name_raw`` is empty) contributes no observation: that is
    genuinely "no report was ever filed before this game locked", not a
    status to guess at.

    **Rows collapse by resolved ``player_id`` when available** (see
    :func:`_canonical_observation_key`), so spelling variants of the same
    real player across separate report captures do not double-count the
    canonical player-game surface; unresolved rows retain their raw name as
    a distinct identity rather than being merged with anything.

    **Rows stamped ``LEGACY_EVIDENCE_SCHEMA_VERSION`` are excluded by
    default.** Those rows' *last write* predates migration 0013's natural-key
    fix and cannot be proven, after the fact, free of the back-to-back
    collision that fix corrects — the collision, if it happened, already
    silently overwrote the evidence that would show it did. Pass
    ``include_legacy=True`` only with an explicit, disclosed reason (e.g. a
    one-off audit of exactly which rows are legacy); the default keeps this
    function refusing to hand a downstream consumer evidence it cannot
    independently trust.

    **``game_tipoffs`` (round-10 review point 1).** :func:`coverage_for_games`
    passes its own already-read ``{game_id: tipoff_utc}`` snapshot here so
    this function's no-lookahead gate is decided against the *exact same*
    authoritative read as every other classification decision in that call,
    rather than this function issuing its own separately-timed ``NbaGame``
    query that a concurrent write could see differently. When omitted (the
    default, for this function's other, standalone caller) the mapping is
    re-derived here exactly as before.
    """
    if not game_ids:
        return ()
    if game_tipoffs is None:
        # ``populate_existing`` is load-bearing (round-9 review point 1): without
        # it, a game object already resident in this session's identity map --
        # loaded earlier in the same session, before some other session or
        # process committed a schedule correction -- is returned as-is, with
        # whatever stale attributes it already had, rather than refreshed from
        # this query's own result row. That would let the no-lookahead gate
        # below compare a masthead against a tip-off this session merely
        # remembers rather than the database's current value.
        game_tipoffs = {
            g.id: g.tipoff_utc
            for g in session.scalars(
                select(NbaGame)
                .where(NbaGame.id.in_(game_ids))
                .execution_options(populate_existing=True)
            )
            if g.tipoff_utc is not None
        }
    entries = session.scalars(
        select(InjuryReportEntry).where(InjuryReportEntry.game_id.in_(game_ids))
    )

    best: dict[tuple[int, str, int | str], InjuryReportEntry] = {}
    for entry in entries:
        if entry.status is InjuryReportStatus.NOT_YET_SUBMITTED or entry.game_id is None:
            continue
        if not include_legacy and entry.import_schema_version < CURRENT_EVIDENCE_SCHEMA_VERSION:
            continue
        tipoff = game_tipoffs.get(entry.game_id)
        if tipoff is None or entry.report_timestamp >= tipoff:
            continue
        key = _canonical_observation_key(entry)
        current = best.get(key)
        if current is None or entry.report_timestamp > current.report_timestamp:
            best[key] = entry

    observations = []
    for e in best.values():
        tipoff = game_tipoffs[e.game_id]  # type: ignore[index]  # filtered non-null above
        lead_time_minutes = int((tipoff - e.report_timestamp).total_seconds() // 60)
        observations.append(
            CanonicalPregameObservation(
                game_id=e.game_id,  # type: ignore[arg-type]  # filtered non-null above
                team_raw=e.team_raw,
                player_name_raw=e.player_name_raw,
                player_id=e.player_id,
                report_timestamp=e.report_timestamp,
                status=e.status,
                status_raw=e.status_raw,
                reason_raw=e.reason_raw,
                lead_time_minutes=lead_time_minutes,
                source_url=e.source_url,
                import_schema_version=e.import_schema_version,
            )
        )
    return tuple(observations)


# --------------------------------------------------------------------------
# Per-game observation coverage (evidence, not a rate)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GameObservationCoverage:
    """Why one game does or does not have a canonical pregame observation.

    Distinguishes outcomes that a bare observation count conflates. Listed
    in final precedence order — ``observed`` beats every other outcome;
    ``unresolved_evidence`` beats ``legacy_excluded`` (round-7 review point
    2: separate current-schema uncertainty must never be masked behind the
    coarser legacy caveat); ``legacy_excluded`` beats
    ``not_yet_submitted_only``; and so on down to ``no_candidate_coverage``.
    ``missing_tipoff`` is reported independently of this ladder, for a game
    this tool cannot reason about at all.

    * ``observed`` — a real, trusted canonical observation.
    * ``unresolved_evidence`` — current-schema, pre-tipoff, real evidence
      this tool cannot (yet) resolve to a canonical observation for this
      exact game: either its ``game_id`` never resolved and it was matched
      to this game only conservatively (by date + tricode pair), or it
      never matched any single game unambiguously but its own report
      timestamp is strictly before this game's *current* tip-off, so it
      remains a plausible candidate this row could concern (round-7 review
      point 2). This includes an unattributable ``NOT_YET_SUBMITTED`` row:
      ambiguity about which of several candidate games a pending
      submission belongs to is still genuine uncertainty, not evidence of
      a clean zero-listed submission for any one of them. A clean
      zero-listed claim is only made when no such evidence could apply to
      this specific game.
    * ``legacy_excluded`` — every pre-tipoff row for this game predates the
      natural-key fix (:data:`LEGACY_EVIDENCE_SCHEMA_VERSION`) and is
      untrustworthy, *regardless of its status*, and no separate
      current-schema unresolved evidence exists for this game either. A
      legacy row's status may be a real, listed status (e.g.
      ``QUESTIONABLE``) rather than ``NOT_YET_SUBMITTED`` — round-5 review
      point 3 requires this case never be mislabelled
      ``not_yet_submitted_only``, which would claim a team hadn't submitted
      when the truth is this tool cannot trust *what* it submitted.
    * ``not_yet_submitted_only`` — every trusted pre-tipoff row said
      ``NOT_YET_SUBMITTED``; no team ever filed a real status before
      tip-off.
    * ``submitted_zero_listed`` — a masthead was actually fetched under the
      current coverage schema, its ``canonical_report_timestamp`` was
      strictly before this game's *current* ``tipoff_utc``, and its
      candidate's stable ``applicable_nba_game_ids`` covered this game, but
      no row references this game at all. The parser never emits a row for
      a team with zero listed injuries (see ``parser.py``), so this is the
      only way to see "the report covered this game and had nothing to
      say" rather than "no candidate ever tried". Requires a
      :class:`CoverageReport` to be supplied; without one this outcome is
      never assigned (round-5 review point 2). Stale/post-tip coverage
      (e.g. after a tip-off correction), pre-round-7 coverage evidence
      keyed only by a reusable surrogate id, and an unrecognized future
      schema version never qualify (round-6 review point 3; round-7 review
      point 3; round-9 review point 2). Nor does evidence whose candidate
      ``report_date`` no longer matches this game's current ``game_date``,
      or whose ``(season, season_type)`` no longer matches the supplied
      :class:`CoverageReport` — a reschedule that moves the same stable
      game id to a different date/report window, or a coverage artifact
      built for the wrong season, must never let old evidence prove a
      clean submission for whatever the id currently names (round-9 review
      point 2).
    * ``no_candidate_coverage`` — no fetched candidate's window ever covered
      this game at all: a gap in this tool's own candidate strategy, not
      evidence about what the source published.
    * ``missing_tipoff`` — this tool cannot even reason about the game
      because its tip-off was never ingested, or (round-7 review point 1)
      its previously-ingested tip-off has since been retracted.

    The downstream ``quant`` join against ``player_participation`` needs
    this distinction, not just the observation rows themselves.
    """

    game_id: int
    nba_game_id: str
    game_date: date
    #: "observed" | "legacy_excluded" | "unresolved_evidence" |
    #: "not_yet_submitted_only" | "submitted_zero_listed" |
    #: "no_candidate_coverage" | "missing_tipoff"
    outcome: str
    observation_count: int = 0
    #: Realized ``tipoff_utc - report_timestamp`` (minutes) of every
    #: canonical observation contributing to this game's count — empty
    #: unless ``outcome == "observed"``. See
    #: ``CanonicalPregameObservation.lead_time_minutes``.
    lead_minutes: tuple[int, ...] = ()


def _matchup_tricodes(matchup_raw: str) -> tuple[str, str] | None:
    """Parse an ``"AWAY@HOME"`` matchup string into its two tricodes.

    Returns ``None`` for anything that doesn't split cleanly into exactly
    two non-empty parts -- this must be conservative, not best-effort:
    round-6 review point 2's unresolved-row matching only ever attributes a
    row to a game it can identify without ambiguity.
    """
    away, sep, home = matchup_raw.partition("@")
    if not sep or not away.strip() or not home.strip():
        return None
    return away.strip().upper(), home.strip().upper()


def coverage_for_games(
    session: Session,
    *,
    ready: Sequence[BackfillGame],
    missing_tipoff: Sequence[MissingTipoffGame],
    coverage_report: CoverageReport | None = None,
) -> tuple[GameObservationCoverage, ...]:
    """Classify every requested game's observation coverage. No network calls.

    ``ready`` and ``missing_tipoff`` are ordinarily a ``BackfillPlan``'s own
    ``games_to_backfill`` output for the same season/range, so the result
    accounts for every game the caller asked about, not just the ones that
    happened to get a canonical observation. ``coverage_report`` (ordinarily
    loaded from the persisted JSON artifact) is what lets ``observed``-zero
    games be split into ``submitted_zero_listed`` vs. ``no_candidate_coverage``
    — without it, that split cannot be made and every observed-zero game
    falls back to the coarser ``no_candidate_coverage``/``not_yet_submitted_only``
    distinction alone.

    **Never trust the caller's own tip-off snapshot (round-7 review point
    1).** ``ready`` is ordinarily built by an earlier ``games_to_backfill``
    call and can go stale between then and now — a schedule correction
    landing in that window, in this process or an earlier one, must not let
    post-tip evidence still prove a clean submission. Every game's identity
    and ``tipoff_utc`` are re-read fresh from the database here, within this
    function's own read scope, and only that freshly-read value is ever
    compared against a masthead timestamp. A game whose live row disappeared
    or whose tip-off has since been retracted is reported ``missing_tipoff``
    rather than classified against a value that no longer reflects the
    database. **A "fresh" re-query is not actually fresh unless it forces
    repopulation (round-9 review point 1):** every ``NbaGame`` query in this
    function passes ``execution_options(populate_existing=True))``, because
    without it an ORM entity this session already has resident in its own
    identity map — loaded earlier in this same session, before some other
    session or process committed the correction — is handed back with its
    original attributes rather than refreshed from this query's own result
    row.

    **Unresolved-row-safe, per-game, strictly-pre-tip classification
    (round-7 review point 2).** A row whose ``game_id`` never resolved (a
    home/away tricode mismatch, an unrecognized abbreviation, ...) is *not*
    invisible to this function the way it is to a plain ``game_id.in_(...)``
    filter: entries are queried by ``game_date`` instead, and any row
    without a resolved ``game_id`` is conservatively re-matched against
    ``ready`` by ``(game_date, {away_tricode, home_tricode})`` -- only when
    that combination identifies *exactly one* game in scope. A row that
    still cannot be attributed to a single game is current-schema evidence
    of *something* — including ``NOT_YET_SUBMITTED``, which still proves
    genuine uncertainty about whichever candidate game it actually concerns
    — but it vetoes ``submitted_zero_listed`` only for the same-date games
    it could still plausibly be about: those whose *current* tip-off is
    strictly after the row's own report timestamp. A report published after
    a game already tipped off cannot be pregame evidence for that game, so an
    ambiguous row must never veto a game it demonstrably cannot concern.
    ``unresolved_evidence`` also outranks ``legacy_excluded`` in the final
    precedence below, so a game with both a legacy row and *separate*
    current-schema unresolved evidence is never reported as merely
    ``legacy_excluded`` — that would mask the stronger, more specific
    current-schema uncertainty behind the coarser legacy caveat. **This
    conservative fan-out applies only when ``game_id`` never resolved at all
    (round-9 review point 4)** — a row whose ``game_id`` *does* resolve, but
    to a game no longer live in this scope (out of range entirely, or its
    own tip-off has since been retracted), is bound to that one game and is
    never spread across unrelated same-date games merely because this
    function currently has nothing to compare it against.

    **One authoritative snapshot, one statement (round-10 review point
    1).** Round-9 fixed ORM identity-map staleness *within* a single query
    via ``populate_existing``; that is not the same problem as this one.
    Under Postgres READ COMMITTED, two separate statements issued
    sequentially by this same function can each see a *different*
    committed snapshot if another session commits a write in between —
    the previous revision of this function issued exactly that shape of
    bug: an initial ``NbaGame`` query building ``games_by_id``, then a
    *second*, later ``NbaGame`` query (solely to build tricode pairs for
    unresolved-row matching) that could disagree with the first if a
    schedule correction landed between them. All classification-relevant
    fields — stable id, local id, date, tip-off, season, season_type, and
    both teams' abbreviations for tricode matching — are now read in
    **one** ``SELECT``, once, at the top of this function; every map below
    (``games_by_id``, ``games_by_nba_id``, ``game_scope_by_id``,
    ``games_by_date``, the tricode-pair index) is derived solely from that
    one immutable result set. No later ``NbaGame`` state is ever read.
    Selecting individual columns rather than full ``NbaGame`` entities also
    means there is no ORM identity map for a stale instance to hide in —
    ``populate_existing`` is moot here, not merely applied.

    **The one-statement snapshot must cover every requested game,
    including ones the caller believes are missing a tip-off (round-11
    review point 1).** Every previous revision of this function scoped its
    single ``SELECT`` to ``ready``'s game ids only, so a game the caller
    classified as ``missing_tipoff`` (no tip-off known when
    ``games_to_backfill`` ran) was never re-queried here at all -- even
    though this function's whole premise is that it, not the caller,
    decides what is currently true. A tip-off ingested between the
    caller's classification and this call would leave that game reported
    ``missing_tipoff`` forever within this invocation, and it would never
    be classified against real evidence. The snapshot query below covers
    the *union* of ``ready`` and ``missing_tipoff`` game ids, and every
    game's ready/missing status is derived solely from that one query's
    result -- a game the caller thought was missing but that now has a
    tip-off is promoted and fully classified exactly like any other ready
    game; a game the caller thought was ready but whose tip-off has since
    been retracted is (as before) reported ``missing_tipoff``. The
    caller's own partition into ``ready``/``missing_tipoff`` is treated as
    nothing more than "the requested scope" -- never as evidence of
    current tip-off state.
    """
    # Round-11 review point 1: the caller's ready/missing_tipoff partition
    # is only a *request* for which games to classify -- it is never
    # trusted as evidence of current tip-off state. Build the union of
    # both, ready first, so the one-statement snapshot below can promote a
    # now-tipped-off "missing" game or retract a now-tip-off-less "ready"
    # one, purely from what it reads.
    requested_games: list[tuple[int, str, date]] = []
    requested_ids: set[int] = set()
    for g in ready:
        if g.game_id not in requested_ids:
            requested_ids.add(g.game_id)
            requested_games.append((g.game_id, g.nba_game_id, g.game_date))
    for mg in missing_tipoff:
        if mg.game_id not in requested_ids:
            requested_ids.add(mg.game_id)
            requested_games.append((mg.game_id, mg.nba_game_id, mg.game_date))
    game_ids = tuple(requested_ids)

    # Round-7 review point 1: re-derive identity/tipoff fresh, in this
    # function's own read scope, rather than trusting `ready`'s snapshot.
    # Round-10 review point 1: exactly one statement for everything this
    # function needs to know about these games' current state -- see the
    # docstring above. `home_team_alias`/`away_team_alias` let both teams'
    # abbreviations come back in the same row as the game itself, so the
    # tricode-pair index below needs no separate query either. Round-11
    # review point 1: `game_ids` now covers `missing_tipoff` too, so a
    # game the caller thought had no tip-off is re-checked here as well.
    home_team_alias = aliased(NbaTeam)
    away_team_alias = aliased(NbaTeam)
    game_snapshot = (
        session.execute(
            select(
                NbaGame.id,
                NbaGame.nba_game_id,
                NbaGame.game_date,
                NbaGame.tipoff_utc,
                NbaGame.season,
                NbaGame.season_type,
                home_team_alias.abbreviation.label("home_abbr"),
                away_team_alias.abbreviation.label("away_abbr"),
            )
            .outerjoin(home_team_alias, home_team_alias.id == NbaGame.home_team_id)
            .outerjoin(away_team_alias, away_team_alias.id == NbaGame.away_team_id)
            .where(NbaGame.id.in_(game_ids))
        ).all()
        if game_ids
        else []
    )
    current_rows = {row.id: row for row in game_snapshot}

    games_by_id: dict[int, BackfillGame] = {}
    games_by_nba_id: dict[str, BackfillGame] = {}
    # Round-9 review point 2: each game's *current* (season, season_type) so
    # a fetched candidate's evidence can be bound to the exact schedule
    # window `coverage_report` was built for, not just a stable game id.
    game_scope_by_id: dict[int, tuple[str, str]] = {}
    # Round-11 review point 1: this is now every requested game the fresh
    # snapshot shows has no current tip-off -- whether the caller thought
    # it was `ready` (and it was since retracted) or already knew it as
    # `missing_tipoff` (and it still is). Either way it is derived solely
    # from `current_rows`, never from the caller's own partition.
    newly_missing: list[MissingTipoffGame] = []
    games_by_date: dict[date, list[BackfillGame]] = {}
    by_tricode_pair: dict[tuple[date, frozenset[str]], list[int]] = {}
    game_tipoffs: dict[int, datetime] = {}
    for game_id, caller_nba_id, caller_game_date in requested_games:
        snap_row = current_rows.get(game_id)
        if snap_row is None or snap_row.tipoff_utc is None:
            # Deleted, or its tip-off is (still, or newly) not live, per
            # this function's own fresh read -- not the caller's
            # classification. This tool cannot reason about pre/post-tip
            # evidence without a live tip-off -- report it the same honest
            # way as any other never-ingested tip-off rather than trusting
            # a value that no longer reflects the database. Prefer the
            # snapshot row's own (fresher) identity fields when the row
            # still exists; fall back to the caller's only if the row
            # itself is gone.
            newly_missing.append(
                MissingTipoffGame(
                    game_id=game_id,
                    nba_game_id=snap_row.nba_game_id if snap_row is not None else caller_nba_id,
                    game_date=snap_row.game_date if snap_row is not None else caller_game_date,
                )
            )
            continue
        current = BackfillGame(
            game_id=snap_row.id,
            nba_game_id=snap_row.nba_game_id,
            game_date=snap_row.game_date,
            tipoff_utc=snap_row.tipoff_utc,
        )
        games_by_id[current.game_id] = current
        games_by_nba_id[current.nba_game_id] = current
        game_scope_by_id[current.game_id] = (snap_row.season, snap_row.season_type.value)
        game_tipoffs[current.game_id] = current.tipoff_utc
        games_by_date.setdefault(current.game_date, []).append(current)
        # (date, {away, home}) -> the ready game ids sharing that exact
        # tricode pair, when unambiguous -- from this same snapshot row, not
        # a separate query.
        if snap_row.home_abbr is not None and snap_row.away_abbr is not None:
            key = (
                snap_row.game_date,
                frozenset({snap_row.home_abbr.upper(), snap_row.away_abbr.upper()}),
            )
            by_tricode_pair.setdefault(key, []).append(current.game_id)

    # Round-10 review point 1: shares this same snapshot's tip-offs rather
    # than issuing its own, separately-timed `NbaGame` query.
    observations = select_canonical_pregame_observations(
        session, game_ids=game_ids, game_tipoffs=game_tipoffs
    )
    observed_counts: dict[int, int] = {}
    observed_leads: dict[int, list[int]] = {}
    for obs in observations:
        observed_counts[obs.game_id] = observed_counts.get(obs.game_id, 0) + 1
        observed_leads.setdefault(obs.game_id, []).append(obs.lead_time_minutes)

    not_yet_submitted_ids: set[int] = set()
    legacy_ids: set[int] = set()
    unresolved_evidence_ids: set[int] = set()
    game_dates = set(games_by_date)
    if game_dates:
        rows = session.scalars(
            select(InjuryReportEntry).where(InjuryReportEntry.game_date.in_(game_dates))
        )
        for row in rows:
            game: BackfillGame | None = None
            if row.game_id is not None:
                game = games_by_id.get(row.game_id)
            else:
                tricodes = _matchup_tricodes(row.matchup_raw)
                if tricodes is not None:
                    candidates = by_tricode_pair.get((row.game_date, frozenset(tricodes)), [])
                    if len(candidates) == 1:
                        game = games_by_id.get(candidates[0])

            if game is None:
                if row.game_id is not None:
                    # Round-9 review point 4: a resolved `game_id` names one
                    # specific game. If that game is not currently live in
                    # scope -- entirely out of this request's range, or its
                    # own tip-off has since been retracted -- this row's
                    # evidence is bound to that one game and must never be
                    # treated as unattributable-and-conservatively-applied
                    # to every other game on the date. There is no live
                    # tip-off here to compare it against, so it simply
                    # cannot be classified; it must not contaminate
                    # unrelated same-date games.
                    continue
                # Genuinely unattributable (game_id never resolved at all,
                # and either no tricode match or an ambiguous one).
                # Current-schema evidence of *any* status -- including
                # NOT_YET_SUBMITTED, which still proves genuine uncertainty
                # about whichever of several candidate games it actually
                # concerns -- vetoes submitted_zero_listed only for the
                # specific same-date games it could still plausibly be
                # about: those whose current tip-off is strictly after this
                # row's own report timestamp. A report published after a
                # game already tipped off cannot be pregame evidence for
                # that game.
                if row.import_schema_version >= CURRENT_EVIDENCE_SCHEMA_VERSION:
                    for candidate_game in games_by_date.get(row.game_date, ()):
                        if row.report_timestamp < candidate_game.tipoff_utc:
                            unresolved_evidence_ids.add(candidate_game.game_id)
                continue
            if row.report_timestamp >= game.tipoff_utc:
                continue
            if row.import_schema_version < CURRENT_EVIDENCE_SCHEMA_VERSION:
                # Any legacy row at all makes this game's pre-tipoff history
                # untrustworthy -- including a legacy NOT_YET_SUBMITTED row,
                # which is equally subject to the pre-migration-0013
                # (report_timestamp, team_raw, player_name_raw) collision.
                legacy_ids.add(game.game_id)
            elif row.status is InjuryReportStatus.NOT_YET_SUBMITTED:
                not_yet_submitted_ids.add(game.game_id)
            elif row.game_id is None:
                # Matched conservatively via date+tricode, not a resolved
                # game_id: real, listed evidence exists, but this tool
                # cannot yet stand behind it as a canonical observation.
                # Never let it collapse into a clean "zero listed" claim.
                unresolved_evidence_ids.add(game.game_id)

    fetched_game_ids: set[int] = set()
    if coverage_report is not None:
        for candidate in coverage_report.candidates:
            if candidate.outcome != "fetched" or candidate.canonical_report_timestamp is None:
                continue
            if candidate.evidence_schema_version != CURRENT_COVERAGE_SCHEMA_VERSION:
                # Round-7 review point 3 required excluding anything below
                # current (a pre-fix record keyed only by surrogate
                # NbaGame.id). Round-9 review point 2 tightens this to an
                # *exact* match: an unrecognized future schema version is
                # just as untrustworthy as a legacy one -- this code has no
                # idea what fields a version it has never seen adds,
                # renames or repurposes, so silently accepting anything
                # ``>=`` current would trust a shape it cannot actually
                # validate. Fail closed on any version this code does not
                # explicitly know how to interpret, not just an older one.
                continue
            if (
                candidate.season != coverage_report.season
                or candidate.season_type != coverage_report.season_type
            ):
                # Round-10 review point 2 (defense in depth): a candidate's
                # own self-described scope must also agree with this
                # CoverageReport's scope, not only the current game's
                # DB-derived scope checked below. `_persist_coverage`
                # already refuses to merge/launder a wrong-scope candidate
                # into a persisted file, but an in-memory report built or
                # edited some other way should never be trusted here
                # either. A legacy candidate (``season == ""``, predating
                # this field) never matches a real scope and is correctly
                # excluded by this check too -- it is already excluded from
                # trust by the schema-version check above regardless.
                continue
            canonical_dt = datetime.fromisoformat(candidate.canonical_report_timestamp)
            candidate_report_date = date.fromisoformat(candidate.report_date)
            for nba_gid in candidate.applicable_nba_game_ids:
                game = games_by_nba_id.get(nba_gid)
                if game is None:
                    # Out of this requested scope, or no longer live --
                    # cannot revalidate here.
                    continue
                if game.game_date != candidate_report_date:
                    # Round-9 review point 2: a candidate's own report_date
                    # names the scheduled date its games were in scope for
                    # when this evidence was collected (see `build_plan`,
                    # which only ever groups a candidate with the games
                    # sharing that exact date). A stable NBA game id alone
                    # is not enough evidence identity -- if this game's
                    # *current* date differs, a reschedule moved it to a
                    # different date/report window while keeping the same
                    # id, and this evidence no longer describes the game's
                    # current slot. Do not let it prove a clean submission
                    # for whatever the id now points at.
                    continue
                season, season_type_value = game_scope_by_id.get(game.game_id, (None, None))
                if (
                    season != coverage_report.season
                    or season_type_value != coverage_report.season_type
                ):
                    # Round-9 review point 2: bind to the exact
                    # season/season_type this CoverageReport was built for,
                    # not global NBA game id uniqueness alone.
                    continue
                if canonical_dt < game.tipoff_utc:
                    fetched_game_ids.add(game.game_id)
                # else: stale/post-tip (e.g. a corrected tip-off moved this
                # masthead across tip since it was fetched) -- excluded, not
                # trusted for a clean-submission claim (round-6 review
                # point 3).

    results: list[GameObservationCoverage] = []
    for game_id, _caller_nba_id, _caller_game_date in requested_games:
        game = games_by_id.get(game_id)
        if game is None:
            # Round-9 review point 3, extended by round-11 review point 1:
            # this game's live tip-off is (still, or newly) missing per this
            # function's own fresh snapshot -- whether the caller thought it
            # was `ready` or already `missing_tipoff`. It is already
            # captured in `newly_missing` and emitted exactly once from that
            # list below. Emitting it again here as well would duplicate it
            # in the output and inflate every count derived from it.
            continue
        count = observed_counts.get(game.game_id, 0)
        if count > 0:
            outcome = "observed"
        elif game.game_id in unresolved_evidence_ids:
            outcome = "unresolved_evidence"
        elif game.game_id in legacy_ids:
            outcome = "legacy_excluded"
        elif game.game_id in not_yet_submitted_ids:
            outcome = "not_yet_submitted_only"
        elif game.game_id in fetched_game_ids:
            outcome = "submitted_zero_listed"
        else:
            outcome = "no_candidate_coverage"
        results.append(
            GameObservationCoverage(
                game_id=game.game_id,
                nba_game_id=game.nba_game_id,
                game_date=game.game_date,
                outcome=outcome,
                observation_count=count,
                lead_minutes=tuple(observed_leads.get(game.game_id, ())),
            )
        )
    # Round-11 review point 1: `newly_missing` is now the single, complete
    # source of every requested game the fresh snapshot shows has no
    # current tip-off -- it already covers both "caller thought it was
    # ready, but it was retracted" and "caller thought it was
    # missing_tipoff, and it still is". There is no longer a separate
    # pass-through loop over the caller's own `missing_tipoff` list: that
    # would re-trust the caller's now-superseded classification and could
    # also double-emit a game already captured in `newly_missing`.
    for mg in newly_missing:
        results.append(
            GameObservationCoverage(
                game_id=mg.game_id,
                nba_game_id=mg.nba_game_id,
                game_date=mg.game_date,
                outcome="missing_tipoff",
            )
        )
    return tuple(results)


def render_observation_coverage(coverage: Sequence[GameObservationCoverage]) -> str:
    by_outcome: dict[str, int] = {}
    for gc in coverage:
        by_outcome[gc.outcome] = by_outcome.get(gc.outcome, 0) + 1
    lines = [f"games in scope: {len(coverage)}"]
    for outcome in (
        "observed",
        "legacy_excluded",
        "unresolved_evidence",
        "not_yet_submitted_only",
        "submitted_zero_listed",
        "no_candidate_coverage",
        "missing_tipoff",
    ):
        lines.append(f"  {outcome}: {by_outcome.get(outcome, 0)}")
    gaps = [gc for gc in coverage if gc.outcome not in ("observed",)]
    if gaps:
        lines.append("")
        lines.append(f"  {len(gaps)} game(s) without a trusted canonical observation:")
        for gc in gaps[:30]:
            lines.append(f"    {gc.game_date} {gc.nba_game_id}: {gc.outcome}")
        if len(gaps) > 30:
            lines.append(f"    ... and {len(gaps) - 30} more")
    return "\n".join(lines)


@dataclass(frozen=True)
class ExclusionCascade:
    """The full expected -> observed denominator, not just per-game success.

    A game-level "observed" outcome is proven by as little as one player's
    canonical row — insufficient to know how much of a season's *player-game*
    surface was actually recovered. This cascade exposes every stage a
    player-game observation depends on, so "missing" is never conflated
    across stages: an official schedule gap is not the same claim as a game
    ingested-but-no-tipoff, which is not the same claim as no candidate ever
    covering a scheduled instant, which is not the same claim as a fetched
    masthead whose entry never resolved to a ``game_id``/``player_id``.

    ``expected_games``/``missing_from_ingest`` are ``None`` when no
    :class:`ExpectedGameCoverage` evidence has been persisted yet (the
    ``run`` command's expected-slate gate has never executed for this
    season/range) — reported as an explicit gap, not silently treated as
    zero.

    **All of stages 9-15 apply the same schema-trust filter**
    (``import_schema_version >= CURRENT_EVIDENCE_SCHEMA_VERSION``) —
    round-5 review point 3. A legacy row is excluded from every one of those
    counts, not just from canonical observation selection, and is instead
    counted once in ``entries_legacy_excluded``/``games_legacy_excluded`` so
    the exclusion is visible rather than silently shrinking a denominator.

    **Stage 10 (``entries_resolved_game_id``) is computed against entries
    scoped by report/game-date, not by ``game_id``** — round-5 review point
    1. Scoping the raw-entry query by ``game_id.in_(...)`` before counting
    how many entries *resolved* a ``game_id`` is tautological: every row
    that query returns already has a non-null ``game_id`` by construction,
    so the stage could never show loss. Entries are instead scoped by the
    calendar dates of the games in ``ready``/``missing_tipoff``, which
    includes rows whose ``game_id`` never resolved at all.
    ``unresolved_game_id_sample`` persists a bounded sample of exactly which
    rows failed to resolve, for the same reason the exclusion cascade exists
    at all: "missing" is not evidence without knowing why.
    """

    expected_games: int | None
    missing_from_ingest: int | None
    ingested_games: int
    ingested_with_tipoff: int
    candidates_attempted: int | None
    candidates_forbidden: int | None
    candidates_not_available: int | None
    mastheads_recovered: int | None
    entries_legacy_excluded: int
    games_legacy_excluded: int
    #: Games whose only pre-tipoff evidence is a real, listed-status row
    #: this tool could not resolve to a canonical observation (round-6
    #: review point 2) — distinct from ``games_legacy_excluded`` (untrusted
    #: schema) and from ``games_observed`` (resolved and canonical).
    games_unresolved_evidence: int
    entries_in_scope: int
    entries_resolved_game_id: int
    entries_resolved_player_id: int
    entries_not_yet_submitted: int
    entries_status_listed: int
    games_observed: int
    #: Canonical (deduplicated, player-identity-collapsed) player-game
    #: observations — distinct from ``entries_resolved_player_id``, which
    #: counts raw rows and can double-count spelling variants of the same
    #: real player. Round-5 review point 7.
    canonical_player_games: int
    canonical_player_games_player_resolved: int
    #: Bounded sample of ``(game_date, matchup_raw, team_raw,
    #: player_name_raw)`` for trusted-schema entries that never resolved a
    #: ``game_id`` — durable evidence for *why* stage 10 is not 100%, not
    #: just how much.
    unresolved_game_id_sample: tuple[tuple[str, str, str, str], ...] = ()


#: Bound on the persisted unresolved-entry sample, so a badly-drifted import
#: cannot make the cascade JSON unbounded.
_UNRESOLVED_SAMPLE_LIMIT: Final = 50


def exclusion_cascade(
    session: Session,
    *,
    ready: Sequence[BackfillGame],
    missing_tipoff: Sequence[MissingTipoffGame],
    game_coverage: Sequence[GameObservationCoverage],
    expected: ExpectedGameCoverage | None = None,
    coverage_report: CoverageReport | None = None,
    start: date | None = None,
    end: date | None = None,
) -> ExclusionCascade:
    """Compute the full exclusion cascade for a requested season/range.

    Read-only; no network calls. ``expected``/``coverage_report`` are
    ordinarily loaded from the persisted JSON artifacts
    :func:`write_expected_game_coverage`/:func:`write_coverage_report` write,
    not re-fetched here.

    ``start``/``end`` — the same requested range ``ready``/``missing_tipoff``
    were already filtered to by ``games_to_backfill`` — filter
    ``coverage_report.candidates`` to that range before computing stages 5-8.
    Without this, a ``coverage_report`` accumulated across many past runs
    over different date windows (the file is season/season_type-scoped, not
    date-range-scoped; see :func:`_merge_coverage`) would silently combine an
    unrelated prior range's candidates into *this* range's denominator —
    round-5 review point 4/8.
    """
    game_ids = tuple(g.game_id for g in ready)
    game_dates = {g.game_date for g in ready} | {g.game_date for g in missing_tipoff}
    entries: list[InjuryReportEntry] = (
        list(
            session.scalars(
                select(InjuryReportEntry).where(InjuryReportEntry.game_date.in_(game_dates))
            )
        )
        if game_dates
        else []
    )
    trusted = [e for e in entries if e.import_schema_version >= CURRENT_EVIDENCE_SCHEMA_VERSION]
    legacy = [e for e in entries if e.import_schema_version < CURRENT_EVIDENCE_SCHEMA_VERSION]

    resolved_game_id = sum(1 for e in trusted if e.game_id is not None)
    resolved_player_id = sum(1 for e in trusted if e.player_id is not None)
    not_yet_submitted = sum(1 for e in trusted if e.status is InjuryReportStatus.NOT_YET_SUBMITTED)
    status_listed = len(trusted) - not_yet_submitted
    unresolved_sample = tuple(
        (e.game_date.isoformat(), e.matchup_raw, e.team_raw, e.player_name_raw)
        for e in trusted
        if e.game_id is None
    )[:_UNRESOLVED_SAMPLE_LIMIT]

    games_observed = sum(1 for gc in game_coverage if gc.outcome == "observed")
    games_legacy_excluded = sum(1 for gc in game_coverage if gc.outcome == "legacy_excluded")
    games_unresolved_evidence = sum(
        1 for gc in game_coverage if gc.outcome == "unresolved_evidence"
    )

    canonical_observations = select_canonical_pregame_observations(session, game_ids=game_ids)
    canonical_player_games = len(canonical_observations)
    canonical_player_games_player_resolved = sum(
        1 for obs in canonical_observations if obs.player_id is not None
    )

    candidates_attempted: int | None = None
    candidates_forbidden: int | None = None
    candidates_not_available: int | None = None
    mastheads_recovered: int | None = None
    if coverage_report is not None:
        in_range_candidates = [
            c
            for c in coverage_report.candidates
            if (start is None or date.fromisoformat(c.report_date) >= start)
            and (end is None or date.fromisoformat(c.report_date) <= end)
        ]
        candidates_attempted = len(in_range_candidates)
        candidates_forbidden = sum(1 for c in in_range_candidates if c.outcome == "forbidden")
        candidates_not_available = sum(
            1 for c in in_range_candidates if c.outcome == "not_available"
        )
        mastheads_recovered = len(
            {
                c.canonical_report_timestamp
                for c in in_range_candidates
                if c.outcome == "fetched" and c.canonical_report_timestamp is not None
            }
        )

    return ExclusionCascade(
        expected_games=expected.expected_count if expected is not None else None,
        missing_from_ingest=len(expected.missing) if expected is not None else None,
        ingested_games=len(ready) + len(missing_tipoff),
        ingested_with_tipoff=len(ready),
        candidates_attempted=candidates_attempted,
        candidates_forbidden=candidates_forbidden,
        candidates_not_available=candidates_not_available,
        mastheads_recovered=mastheads_recovered,
        entries_legacy_excluded=len(legacy),
        games_legacy_excluded=games_legacy_excluded,
        games_unresolved_evidence=games_unresolved_evidence,
        entries_in_scope=len(trusted),
        entries_resolved_game_id=resolved_game_id,
        entries_resolved_player_id=resolved_player_id,
        entries_not_yet_submitted=not_yet_submitted,
        entries_status_listed=status_listed,
        games_observed=games_observed,
        canonical_player_games=canonical_player_games,
        canonical_player_games_player_resolved=canonical_player_games_player_resolved,
        unresolved_game_id_sample=unresolved_sample,
    )


def render_exclusion_cascade(cascade: ExclusionCascade) -> str:
    def _fmt(value: int | None) -> str:
        return "unknown (not yet computed)" if value is None else str(value)

    lines = [
        "exclusion cascade (denominator evidence, not a rate):",
        f"  1. expected games (official schedule):     {_fmt(cascade.expected_games)}",
        f"  2. missing from this project's ingest:     {_fmt(cascade.missing_from_ingest)}",
        f"  3. ingested games (any):                   {cascade.ingested_games}",
        f"  4. ingested games with a tip-off instant:  {cascade.ingested_with_tipoff}",
        f"  5. candidates attempted (HTTP):             {_fmt(cascade.candidates_attempted)}",
        f"  6. candidates forbidden (403, unsettled):   {_fmt(cascade.candidates_forbidden)}",
        f"  7. candidates not_available (404):          {_fmt(cascade.candidates_not_available)}",
        f"  8. mastheads recovered (fetched, distinct): {_fmt(cascade.mastheads_recovered)}",
        f"  9. entries legacy-excluded (rows):          {cascade.entries_legacy_excluded}",
        f" 10. games legacy-excluded:                   {cascade.games_legacy_excluded}",
        f" 10b. games with unresolved real evidence:    {cascade.games_unresolved_evidence}",
        f" 11. entries in scope, trusted schema (rows): {cascade.entries_in_scope}",
        f" 12. entries resolved to a game_id:            {cascade.entries_resolved_game_id}",
        f" 13. entries resolved to a player_id:          {cascade.entries_resolved_player_id}",
        f" 14. entries NOT_YET_SUBMITTED:                {cascade.entries_not_yet_submitted}",
        f" 15. entries with a listed status:             {cascade.entries_status_listed}",
        f" 16. games with a canonical observation:       {cascade.games_observed}",
        f" 17. canonical player-games (deduplicated):    {cascade.canonical_player_games}",
        f" 18. canonical player-games, player_id resolved: "
        f"{cascade.canonical_player_games_player_resolved}",
    ]
    if cascade.expected_games is None:
        lines.append(
            "\n  note: no expected-game-slate evidence found — run `backfill run` at least "
            "once for this exact season/season-type/date range (the `observations` command "
            "only reads what a prior `run` persisted; it never fetches) — stages 1-2 are "
            "unverified, not zero."
        )
    if cascade.candidates_attempted is None:
        lines.append(
            "\n  note: no coverage-report evidence found for this exact range — stages 5-8 "
            "are unverified, not zero."
        )
    if cascade.entries_legacy_excluded:
        lines.append(
            f"\n  note: {cascade.entries_legacy_excluded} row(s) / {cascade.games_legacy_excluded} "
            "game(s) excluded as legacy-schema evidence (predates migration 0013's "
            "natural-key fix) — see docs/handoff.md for the required re-capture/checkpoint "
            "reset before trusting these dates."
        )
    if cascade.unresolved_game_id_sample:
        lines.append(
            f"\n  {cascade.entries_in_scope - cascade.entries_resolved_game_id} trusted-schema "
            "entries never resolved a game_id; sample:"
        )
        for (
            game_date_iso,
            matchup_raw,
            team_raw,
            player_name_raw,
        ) in cascade.unresolved_game_id_sample:
            lines.append(f"    {game_date_iso} {matchup_raw} {team_raw}: {player_name_raw!r}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _coverage_merge_key(c: CandidateCoverage) -> tuple[str, str, str, str, str, str, str]:
    """Merge identity for persisted coverage: scope, date, anchor, requested instant,
    canonical masthead, and applicable game scope.

    ``(report_date, anchor)`` alone let a changed candidate (the same
    round-4 mutable-anchor problem :class:`Checkpoint` fixes) silently
    overwrite a previous, distinct candidate's coverage record under a
    plausible-looking but wrong key. Including ``requested_timestamp`` means
    a changed candidate merges as an *additional* record, not a silent
    replacement of unrelated evidence.

    **Round-10 review point 2**: also including ``(season, season_type)``
    means two candidates that otherwise share a date/anchor/timestamp but
    belong to different scopes (a wrong-scope artifact merged in by
    mistake, or a future date range genuinely reused across seasons) are
    never collapsed into a single record either.

    **Round-11 review point 3**: two ``fetched`` candidates can share every
    field above and still be genuinely distinct evidence -- the same
    requested instant can resolve to a *different* canonical masthead
    timestamp on a later attempt (a corrected publish, or a re-fetch after
    a transient drift), or to a *different* applicable game scope (the
    schedule changed between attempts). Neither ``canonical_report_timestamp``
    nor ``applicable_nba_game_ids`` was part of the key, so the later
    attempt's record silently overwrote the earlier one's -- even though
    both are real, previously-trusted evidence for potentially different
    games. Including the canonical masthead timestamp (``""`` for a
    candidate with none, e.g. a 404/403/error outcome) and a stable,
    order-independent fingerprint of the applicable NBA game id set means
    two records that differ in either dimension coexist as separate
    entries rather than one clobbering the other; two records that agree
    on every field -- including these two -- still correctly dedupe to one,
    since re-fetching identical evidence must stay idempotent rather than
    accumulating duplicates.
    """
    game_scope_fingerprint = ",".join(sorted(c.applicable_nba_game_ids))
    return (
        c.season,
        c.season_type,
        c.report_date,
        c.anchor,
        c.requested_timestamp,
        c.canonical_report_timestamp or "",
        game_scope_fingerprint,
    )


def _merge_coverage(
    existing: Sequence[CandidateCoverage], new: Sequence[CandidateCoverage]
) -> list[CandidateCoverage]:
    by_key = {_coverage_merge_key(c): c for c in existing}
    for c in new:
        by_key[_coverage_merge_key(c)] = c
    return list(by_key.values())


class CoverageScopeMismatch(RuntimeError):
    """Persisted coverage at this path does not match the requested scope.

    Round-10 review point 2: :func:`default_coverage_path` embeds
    ``(season, season_type)`` in the filename precisely so no two requests
    ever legitimately share a path. Seeing the file's own declared scope
    disagree with what this call is persisting for means the file was
    written for a different request (a stale artifact left over from an
    explicit path override, or hand-edited) — merging into it and
    rewriting it under this call's scope would silently launder its
    candidates into evidence this run never actually gathered. Raised
    rather than silently discarded or silently adopted, because this is a
    write path: an operator must resolve which scope is actually correct
    before this tool touches the file again.
    """


def _persist_coverage(
    coverage_path: Path,
    season: str,
    season_type: SeasonType,
    new_candidates: Sequence[CandidateCoverage],
) -> None:
    """Merge freshly-attempted candidates into whatever this path already holds.

    **Round-10 review point 2.** Two independent checks guard against
    caller-scope laundering:

    1. The *file's own* declared ``(season, season_type)`` must equal this
       call's, whenever it already holds any candidate — :class:`
       CoverageScopeMismatch` is raised otherwise rather than silently
       rewriting a differently-scoped file under this request's label.
    2. Even inside a correctly-scoped file, each *candidate's own* recorded
       ``(season, season_type)`` (round-10; empty string for anything
       persisted before this field existed) must also match before it is
       carried forward — a mismatch here should not be structurally
       possible once check 1 has passed, but is not assumed away. Any
       candidate that fails this is excluded from the rewritten file
       rather than silently trusted as current-scope evidence.

    **Round-11 review point 2: quarantine incompatible schema versions at
    this load+merge+save boundary too, not only at classification time.**
    :func:`coverage_for_games` already refuses to *trust* a candidate whose
    ``evidence_schema_version`` is not exactly
    :data:`CURRENT_COVERAGE_SCHEMA_VERSION` for a clean-submission claim —
    but before this fix, that was the *only* place a wrong version was
    ever checked. This function's own ``existing`` filter checked
    ``(season, season_type)`` alone, so a legacy record (predating this
    field, or any future record with a schema version this code has never
    seen and cannot validate) would still be read back, merged unchanged,
    and rewritten into the very file this run treats as its own current,
    trusted artifact for this scope — "quarantined" from classification,
    but never actually quarantined from the persisted evidence itself. An
    incompatible-version candidate is now dropped from ``existing`` here,
    at the moment it is read, so it can never be laundered forward into a
    freshly-rewritten "current" file again; it is not overwritten in place
    on disk (this function never rewrites a *different* path), simply
    excluded from every subsequent merge this tool performs.
    """
    existing: list[CandidateCoverage] = []
    if coverage_path.is_file():
        existing_report = CoverageReport.from_json(coverage_path.read_text(encoding="utf-8"))
        if existing_report.candidates and (
            existing_report.season != season or existing_report.season_type != season_type.value
        ):
            raise CoverageScopeMismatch(
                f"{coverage_path} holds coverage for season={existing_report.season!r} "
                f"season_type={existing_report.season_type!r}, not the requested "
                f"season={season!r} season_type={season_type.value!r}. Refusing to merge "
                "and rewrite it under this request's scope."
            )
        existing = [
            c
            for c in existing_report.candidates
            if c.season == season
            and c.season_type == season_type.value
            # Round-11 review point 2: a legacy or unrecognized-future
            # schema version is excluded here, not merely at classification
            # -- otherwise it is retained and rewritten into this run's
            # own "current" file forever, even though nothing ever trusts
            # it for evidence.
            and c.evidence_schema_version == CURRENT_COVERAGE_SCHEMA_VERSION
        ]
    merged = _merge_coverage(existing, new_candidates)
    write_coverage_report(
        coverage_path,
        CoverageReport(season=season, season_type=season_type.value, candidates=merged),
    )


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - operator tool
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("plan", "run"):
        sub = subparsers.add_parser(name, help=f"{name} the historical injury-report backfill")
        sub.add_argument("season", help="e.g. 2025-26")
        sub.add_argument("--season-type", default="regular", choices=[t.value for t in SeasonType])
        sub.add_argument("--start", type=_parse_date, default=None)
        sub.add_argument("--end", type=_parse_date, default=None)
        sub.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)
        sub.add_argument(
            "--no-cache",
            action="store_true",
            help="force a live re-fetch of every candidate, bypassing the local cache",
        )
        sub.add_argument("--checkpoint", type=Path, default=None)

    run_sub = subparsers.choices["run"]
    run_sub.add_argument(
        "--allow-missing-tipoff",
        type=int,
        default=DEFAULT_ALLOW_MISSING_TIPOFF,
        help=(
            "explicitly permit up to N in-range games with no ingested tip-off instant "
            "(default 0: refuse to run against an incompletely-scheduled range)"
        ),
    )
    run_sub.add_argument(
        "--allow-missing-games",
        type=int,
        default=0,
        help=(
            "explicitly permit up to N in-range games from the official schedule that this "
            "project never ingested at all (default 0: refuse to run against a range whose "
            "expected slate is incomplete, per an independent LeagueGameFinder check)"
        ),
    )
    run_sub.add_argument(
        "--max-forbidden-streak",
        type=int,
        default=DEFAULT_MAX_FORBIDDEN_STREAK,
        help="abort after this many consecutive HTTP 403 responses (suspected block, not absence)",
    )

    obs_sub = subparsers.add_parser(
        "observations",
        help="report durable per-game observation coverage for a season/range (no network)",
    )
    obs_sub.add_argument("season", help="e.g. 2025-26")
    obs_sub.add_argument("--season-type", default="regular", choices=[t.value for t in SeasonType])
    obs_sub.add_argument("--start", type=_parse_date, default=None)
    obs_sub.add_argument("--end", type=_parse_date, default=None)

    args = parser.parse_args(argv)
    season_type = SeasonType(args.season_type)
    settings = get_settings()
    database = Database.from_settings(settings)

    if args.command == "observations":
        with database.session() as session:
            ready, missing = games_to_backfill(
                session, season=args.season, season_type=season_type, start=args.start, end=args.end
            )

            expected_path = default_expected_coverage_path(args.season, season_type)
            expected = (
                ExpectedGameCoverage.from_json(expected_path.read_text(encoding="utf-8"))
                if expected_path.is_file()
                else None
            )
            if expected is not None and not _expected_coverage_matches_scope(
                expected,
                season=args.season,
                season_type=season_type,
                start=args.start,
                end=args.end,
            ):
                print(
                    f"\nwarning: persisted expected-game-slate evidence at {expected_path} was "
                    f"computed for season={expected.season} season_type={expected.season_type} "
                    f"start={expected.start} end={expected.end}, which does not match this exact "
                    f"request (season={args.season} season_type={season_type.value} "
                    f"start={args.start} end={args.end}). Discarding it rather than presenting "
                    "mismatched-scope evidence as if it answered this request — run `backfill "
                    "run` for this exact range to refresh it.",
                    file=sys.stderr,
                )
                expected = None

            coverage_path = default_coverage_path(args.season, season_type)
            coverage_report = (
                CoverageReport.from_json(coverage_path.read_text(encoding="utf-8"))
                if coverage_path.is_file()
                else None
            )
            game_coverage = coverage_for_games(
                session, ready=ready, missing_tipoff=missing, coverage_report=coverage_report
            )
            cascade = exclusion_cascade(
                session,
                ready=ready,
                missing_tipoff=missing,
                game_coverage=game_coverage,
                expected=expected,
                coverage_report=coverage_report,
                start=args.start,
                end=args.end,
            )
        print(render_observation_coverage(game_coverage))
        print()
        print(render_exclusion_cascade(cascade))
        return 0

    store = RawPayloadStore(DEFAULT_RAW_ROOT)

    with database.session() as session:
        plan = build_plan(
            session,
            season=args.season,
            season_type=season_type,
            start=args.start,
            end=args.end,
            store=store,
        )
        print(plan.render())

        if args.command == "plan":
            return 0

        # Independent expected-slate check, before any injury-report HTTP
        # call: enforce_full_tipoff_coverage below can only ever see games
        # already in this project's own database, so it cannot by itself
        # detect a game that was never ingested at all. One cached,
        # throttled LeagueGameFinder request (the same endpoint
        # hoops_gm.ingest.backfill already uses) against the official
        # schedule closes that gap.
        try:
            season_type_label = _expected_schedule_season_type_label(season_type)
        except ValueError as exc:
            print(f"\n{exc}", file=sys.stderr)
            return 1
        nba = NbaStatsClient(store=store)
        expected_games = default_expected_game_fetcher(nba)(args.season, season_type_label)
        ready, missing_tipoff = games_to_backfill(
            session, season=args.season, season_type=season_type, start=args.start, end=args.end
        )
        expected_coverage_path = default_expected_coverage_path(args.season, season_type)
        try:
            expected_coverage = enforce_expected_game_coverage(
                season=args.season,
                season_type=season_type,
                start=args.start,
                end=args.end,
                expected=expected_games,
                ready=ready,
                missing_tipoff=missing_tipoff,
                allow_missing_games=args.allow_missing_games,
            )
        except IncompleteExpectedGameCoverage as exc:
            # Persisted even on failure -- this is exactly the durable
            # evidence an operator needs to see *which* games are missing.
            write_expected_game_coverage(expected_coverage_path, exc.coverage)
            print(f"\n{exc}", file=sys.stderr)
            return 1
        write_expected_game_coverage(expected_coverage_path, expected_coverage)

        try:
            enforce_full_tipoff_coverage(plan, allow_missing=args.allow_missing_tipoff)
        except IncompleteScheduleCoverage as exc:
            print(f"\n{exc}", file=sys.stderr)
            return 1

        try:
            enforce_request_budget(
                plan, max_requests=args.max_requests, force_refetch=args.no_cache
            )
        except BackfillBudgetExceeded as exc:
            print(f"\n{exc}", file=sys.stderr)
            return 1

        checkpoint = Checkpoint.load(
            args.checkpoint or default_checkpoint_path(args.season, season_type)
        )
        client = InjuryReportClient(store=store)
        fetch_and_parse = default_fetch_and_parse(client, no_cache=args.no_cache)
        coverage_path = default_coverage_path(args.season, season_type)
        try:
            result = run_backfill(
                session,
                plan=plan,
                fetch_and_parse=fetch_and_parse,
                checkpoint=checkpoint,
                force_refetch=args.no_cache,
                max_forbidden_streak=args.max_forbidden_streak,
                persist_coverage=lambda cov: _persist_coverage(
                    coverage_path, args.season, season_type, [cov]
                ),
            )
        except SuspectedSourceBlock as exc:
            # Every candidate's coverage gathered before the abort is
            # persisted here -- an abort must not discard in-memory evidence
            # that was already gathered. See the round-4 review finding.
            if exc.partial_result is not None:
                _persist_coverage(
                    coverage_path, args.season, season_type, exc.partial_result.coverage
                )
            print(f"\n{exc}", file=sys.stderr)
            return 1

        _persist_coverage(coverage_path, args.season, season_type, result.coverage)

    print("\n" + result.render())
    if result.forbidden:
        print(
            f"\n{len(result.forbidden)} candidate(s) returned HTTP 403 and remain UNSETTLED — "
            "never recorded as confirmed absence. Investigate (rate limiting? a genuine block?) "
            "before trusting this date range's coverage; they will be retried automatically on "
            "the next run.",
            file=sys.stderr,
        )
        return 1
    if result.failures:
        print(
            f"\n{len(result.failures)} candidate(s) failed with contract drift, not a merely "
            "missing report. That is not fine — read the errors above before trusting this "
            "date range's report history.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
