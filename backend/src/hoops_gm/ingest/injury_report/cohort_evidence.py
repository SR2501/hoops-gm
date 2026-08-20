"""Regenerate the representative historical injury cohort's evidence manifest.

    python -m hoops_gm.ingest.injury_report.cohort_evidence 2025-26 \
        --start 2025-12-08 --end 2026-01-04 \
        --out ../docs/adapters/nba-injury-report-cohort-2025-12-08--2026-01-04.json

## Why this is a committed module and not an operator's notebook

The first published cohort (PR #30) assembled its manifest by hand from ad-hoc
queries. That made every number in it an assertion rather than a reproduction:
nobody could re-derive the file, so nobody could tell that its scope had been
built on a defective ``LeagueGameFinder`` parser which silently dropped any game
whose two official team rows repeated one canonical ``MATCHUP`` string. Two real
2025-12-13 games (``0022501229``, ``0022501230``) and their 39 player logs
vanished, and the cohort inherited the omission without a single failing check.

So the manifest is now the deterministic output of a function of persisted
state. Given the same database, the same raw-payload store and the same
operational report files, this module emits byte-identical JSON. It reads no
clock, generates no identifiers and sorts every collection it emits.

**What that does and does not claim.** Re-running *this module* against retained
operational state reproduces the committed file byte for byte. Re-running the
*live sweep* that produced that state cannot: capture timestamps are properties
of when the request was made. Those timestamps are recorded here as provenance,
not as reproducible values, and the distinction is stated in the manifest itself
rather than left for a reader to discover.

## The independent reconciliation

``AGENTS.md``: successful parsing and plausible row counts do not prove source
completeness. The defect above parsed cleanly and produced a plausible 1,225
games. It was caught only by an independent endpoint that said 1,230.

:func:`reconcile_game_identity` therefore re-derives the cohort's game-identity
set from three mutually independent views and requires them to be *equal*, not
merely similar:

* ``LeagueGameFinder`` — two team rows per game, the schedule source.
* ``PlayerGameLogs`` — one row per player-game, an entirely separate endpoint
  which knows nothing about the schedule query.
* ``ScheduleLeagueV2`` — the official published schedule document, whose game
  dates are derived from ``gameDateTimeEst`` reconciled against
  ``gameDateTimeUTC`` (see :func:`hoops_gm.ingest.nba.schedule.parse_schedule`).

plus the set actually persisted in ``nba_games``. Any disagreement is reported
with the offending identifiers rather than reduced to a count, and the manifest
records the reconciliation as evidence rather than as a passing assertion that
left no trace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.core.config import get_settings
from hoops_gm.db.models.availability import PlayerParticipation
from hoops_gm.db.models.enums import ExternalSource, SeasonType
from hoops_gm.db.models.identity import PlayerExternalId
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.db.session import Database
from hoops_gm.ingest.injury_report.backfill import (
    DEFAULT_RAW_ROOT,
    BackfillGame,
    CanonicalPregameObservation,
    CoverageReport,
    ExpectedGameCoverage,
    MissingTipoffGame,
    coverage_for_games,
    default_coverage_path,
    default_expected_coverage_path,
    exclusion_cascade,
    games_to_backfill,
    select_canonical_pregame_observations,
)
from hoops_gm.ingest.nba.client import NbaStatsClient
from hoops_gm.ingest.nba.parsers import parse_league_game_finder, result_tables
from hoops_gm.ingest.nba.schedule import parse_schedule
from hoops_gm.ingest.rawstore import RawPayloadStore

#: Bumped from 1: the schema gains ``cross_source_reconciliation`` and drops the
#: wall-clock ``generated_at_utc`` that made version 1 unreproducible.
SCHEMA_VERSION: Final = 2

MANIFEST_KIND: Final = "injury_conversion_cohort_population_evidence"

NBA_SOURCE: Final = "nba_stats"

#: Every view the reconciliation requires before a cohort may be published.
#: Named as a constant so a missing witness is an explicit, checkable failure
#: rather than a silently smaller set of agreeing views.
RECONCILIATION_VIEWS: Final[tuple[str, ...]] = (
    "league_game_finder",
    "persisted_nba_games",
    "player_game_logs",
    "schedule_league_v2",
)

#: Repository files whose exact bytes the cohort's derivation depends on.
DEFAULT_SOURCE_FINGERPRINT_PATHS: Final[tuple[str, ...]] = (
    "backend/src/hoops_gm/ingest/nba/parsers.py",
    "backend/src/hoops_gm/ingest/backfill.py",
    "backend/src/hoops_gm/db/lineage.py",
    "backend/src/hoops_gm/ingest/injury_report/backfill.py",
    "backend/src/hoops_gm/ingest/injury_report/cohort_evidence.py",
)


# --------------------------------------------------------------------------
# Fingerprints
# --------------------------------------------------------------------------


def content_sha256(parts: Iterable[str]) -> str:
    """Digest of newline-joined parts, so an ordered record set has an identity.

    Deliberately the same shape as :func:`hoops_gm.db.lineage.content_fingerprint`:
    a caller sorts the parts, joins on ``\\n``, and gets a value that changes if
    any record changes. Kept separate only because this module fingerprints
    evidence rows rather than schedule lineage.
    """
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def source_file_sha256(path: Path) -> str:
    """SHA-256 of a repository file's canonical (LF) bytes.

    CRLF is normalised before hashing because ``core.autocrlf=true`` materialises
    CRLF in a Windows working tree while Git stores LF. Hashing the working-tree
    bytes therefore produces a value that depends on the checkout's newline
    configuration rather than on the committed content — a defect found by review
    of PR #30, which had to be corrected after publication. The value produced
    here equals ``git cat-file blob <rev>:<path> | sha256sum`` for any file Git
    stores with LF endings, and is reproducible on any platform without Git by
    hashing ``path.read_bytes().replace(b"\\r\\n", b"\\n")``.
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# --------------------------------------------------------------------------
# Cross-source reconciliation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GameIdentityReconciliation:
    """Whether independent views of the same window name exactly the same games."""

    start: date
    end: date
    #: ``{view name: sorted game ids}``, every view derived from its own source.
    views: Mapping[str, tuple[str, ...]]

    @property
    def agreed(self) -> bool:
        return len({frozenset(ids) for ids in self.views.values()}) == 1

    @property
    def union(self) -> tuple[str, ...]:
        merged: set[str] = set()
        for ids in self.views.values():
            merged |= set(ids)
        return tuple(sorted(merged))

    def disagreements(self) -> dict[str, list[str]]:
        """Per view, the union members that view does not contain."""
        union = set(self.union)
        return {
            name: sorted(union - set(ids))
            for name, ids in sorted(self.views.items())
            if set(ids) != union
        }

    def as_summary(self) -> dict[str, Any]:
        return {
            "agreed": self.agreed,
            "counts": {name: len(ids) for name, ids in sorted(self.views.items())},
            "disagreements": self.disagreements(),
            "end_game_date": self.end.isoformat(),
            # The union, listed once. When the views agree it *is* every view,
            # and repeating four identical 173-element lists would bury the one
            # thing a reader needs to check. When they disagree, per-view gaps
            # are named in ``disagreements`` rather than left to a diff.
            "game_ids": list(self.union),
            "method": (
                "Each view derives the in-window regular-season game-identity set from its own "
                "source and its own date field, then all views are required to be equal. "
                "LeagueGameFinder supplies two team rows per game; PlayerGameLogs is a separate "
                "endpoint returning one row per player-game; ScheduleLeagueV2 is the published "
                "schedule document whose Eastern game date is reconciled against its UTC sibling "
                "before use. Row counts and clean parsing prove nothing about completeness -- "
                "only an independent endpoint does."
            ),
            "sha256_sorted_game_ids": content_sha256(self.union),
            "start_game_date": self.start.isoformat(),
        }


def _league_game_finder_ids(
    payload: Any, *, season: str, start: date, end: date
) -> tuple[str, ...]:
    games = parse_league_game_finder(payload, season=season, season_type="regular")
    return tuple(sorted(g.nba_game_id for g in games if start <= g.game_date <= end))


def _player_game_log_ids(payload: Any, *, start: date, end: date) -> tuple[str, ...]:
    """In-window game ids taken from ``PlayerGameLogs``' own ``GAME_DATE`` column.

    The shared parser drops ``GAME_DATE`` because production rows join to an
    already-persisted game, so the window is applied to the raw table here. That
    keeps this view genuinely independent: it never consults the schedule source
    it is being reconciled against.
    """
    table = result_tables(payload, endpoint="PlayerGameLogs")["PlayerGameLogs"]
    table.require("GAME_ID", "GAME_DATE")
    found: set[str] = set()
    for row in table.rows:
        raw_date = str(table.get(row, "GAME_DATE") or "")
        game_id = str(table.get(row, "GAME_ID") or "")
        if not raw_date or not game_id:
            continue
        # "2025-12-13T00:00:00" and "2025-12-13" both occur; only the date part
        # is meaningful and only the date part is read.
        if start <= date.fromisoformat(raw_date[:10]) <= end:
            found.add(game_id)
    return tuple(sorted(found))


def _schedule_league_ids(payload: Any, *, season: str, start: date, end: date) -> tuple[str, ...]:
    parsed = parse_schedule(payload, season=season)
    return tuple(
        sorted(
            record.game.nba_game_id
            for record in parsed.games
            if start <= record.game.game_date <= end
        )
    )


def reconcile_game_identity(
    session: Session,
    *,
    season: str,
    season_type: SeasonType,
    start: date,
    end: date,
    store: RawPayloadStore,
    nba: NbaStatsClient | None = None,
) -> GameIdentityReconciliation:
    """Rebuild the window's game-identity set from every independent view available.

    Cached captures are used when present, so this adds no load to
    ``stats.nba.com`` after a sweep; ``nba`` is required only to fetch a view the
    store has never seen. A view whose capture is absent and which cannot be
    fetched is omitted rather than silently treated as agreeing — an absent
    witness is not a corroborating one.
    """
    views: dict[str, tuple[str, ...]] = {}

    persisted = session.scalars(
        select(NbaGame).where(
            NbaGame.season == season,
            NbaGame.season_type == season_type,
            NbaGame.game_date >= start,
            NbaGame.game_date <= end,
        )
    )
    views["persisted_nba_games"] = tuple(sorted(game.nba_game_id for game in persisted))

    season_label = "Regular Season" if season_type is SeasonType.REGULAR else "Playoffs"
    specs: tuple[tuple[str, str, dict[str, Any], Any], ...] = (
        (
            "league_game_finder",
            "LeagueGameFinder",
            {
                "season_nullable": season,
                "season_type_nullable": season_label,
                "league_id_nullable": "00",
            },
            lambda payload: _league_game_finder_ids(payload, season=season, start=start, end=end),
        ),
        (
            "player_game_logs",
            "PlayerGameLogs",
            {"season_nullable": season, "season_type_nullable": season_label},
            lambda payload: _player_game_log_ids(payload, start=start, end=end),
        ),
        (
            "schedule_league_v2",
            "ScheduleLeagueV2",
            {"league_id": "00", "season": season},
            lambda payload: _schedule_league_ids(payload, season=season, start=start, end=end),
        ),
    )

    for name, endpoint, params, extract in specs:
        ref = store.latest(source=NBA_SOURCE, endpoint=endpoint, params=params)
        if ref is not None:
            views[name] = extract(ref.read_json())
            continue
        if nba is None:
            continue
        views[name] = extract(nba.fetch(endpoint, params))

    return GameIdentityReconciliation(start=start, end=end, views=views)


# --------------------------------------------------------------------------
# Manifest sections
# --------------------------------------------------------------------------


def _capture_summary(store: RawPayloadStore) -> dict[str, Any]:
    """Per-endpoint capture identity, from the store's own append-only index."""
    summary: dict[str, dict[str, Any]] = {}
    digests: dict[str, list[str]] = {}
    if not store.root.is_dir():
        return summary
    for source_dir in sorted(p for p in store.root.iterdir() if p.is_dir()):
        for entry in store.index_entries(source_dir.name):
            endpoint = str(entry.get("endpoint", ""))
            key = f"{source_dir.name}/{endpoint}"
            fetched_at = str(entry.get("fetched_at", ""))
            digest = str(entry.get("content_sha256", ""))
            record = summary.setdefault(
                key,
                {
                    "captures": 0,
                    "first_fetched_at": fetched_at,
                    "last_fetched_at": fetched_at,
                    "total_uncompressed_bytes": 0,
                },
            )
            record["captures"] = int(record["captures"]) + 1
            record["total_uncompressed_bytes"] = int(record["total_uncompressed_bytes"]) + int(
                entry.get("byte_size") or 0
            )
            record["first_fetched_at"] = min(str(record["first_fetched_at"]), fetched_at)
            record["last_fetched_at"] = max(str(record["last_fetched_at"]), fetched_at)
            digests.setdefault(key, []).append(digest)
    for key, record in summary.items():
        seen = digests[key]
        record["distinct_content_sha256"] = len(set(seen))
        record["sha256_sorted_capture_identity"] = content_sha256(sorted(seen))
    return dict(sorted(summary.items()))


def _artifact_files(paths: Sequence[Path]) -> dict[str, Any]:
    return {
        path.name: {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(paths, key=lambda p: p.name)
        if path.is_file()
    }


def _observation_records(
    observations: Sequence[CanonicalPregameObservation],
    *,
    game_ids: Mapping[int, str],
    anchors: Mapping[int, str],
) -> list[str]:
    """Stable text form of each canonical observation, for fingerprinting.

    Keyed by source-stable identity — the NBA game id and the NBA player id —
    never by a local surrogate primary key, which a rebuild reassigns freely.
    """
    records = []
    for obs in observations:
        anchor = anchors.get(obs.player_id) if obs.player_id is not None else None
        records.append(
            "|".join(
                (
                    game_ids[obs.game_id],
                    anchor or "",
                    obs.report_timestamp.isoformat(),
                    obs.status.value,
                    str(obs.lead_time_minutes),
                )
            )
        )
    return sorted(records)


def _position_evidence(
    store: RawPayloadStore,
    *,
    nba_game_ids: Sequence[str],
    observed_anchors: Mapping[str, int],
) -> dict[str, Any]:
    """G/F/C diversity, from labels the source actually printed in this window.

    Read straight from the retained ``BoxScoreTraditionalV3`` captures rather
    than from a roster listing, because the question this answers is "is the
    cohort positionally diverse", and a label observed in the same window is the
    only one that can be checked against the same evidence. A blank label stays
    unknown: an absent position is not a position.
    """
    labels: dict[str, set[str]] = {}
    for nba_game_id in sorted(set(nba_game_ids)):
        ref = store.latest(
            source=NBA_SOURCE, endpoint="BoxScoreTraditionalV3", params={"game_id": nba_game_id}
        )
        if ref is None:
            continue
        body = ref.read_json().get("boxScoreTraditional")
        if not isinstance(body, dict):
            continue
        for side in ("homeTeam", "awayTeam"):
            team = body.get(side)
            if not isinstance(team, dict):
                continue
            for entry in team.get("players") or ():
                if not isinstance(entry, dict):
                    continue
                person_id = entry.get("personId")
                position = str(entry.get("position") or "").strip()
                if person_id is None or not position:
                    continue
                labels.setdefault(str(person_id), set()).add(position)

    cohort = set(observed_anchors)
    with_label = {anchor: sorted(labels[anchor]) for anchor in sorted(cohort & set(labels))}
    by_label: Counter[str] = Counter()
    for values in with_label.values():
        for value in values:
            by_label[value] += 1

    observations_with = sum(observed_anchors[anchor] for anchor in with_label)
    return {
        "canonical_observations_with_source_observed_position": observations_with,
        "canonical_observations_without_source_observed_position": (
            sum(observed_anchors.values()) - observations_with
        ),
        "distinct_resolved_players": len(cohort),
        "distinct_resolved_players_by_observed_label": dict(sorted(by_label.items())),
        "distinct_resolved_players_with_source_observed_position": len(with_label),
        "distinct_resolved_players_without_source_observed_position": len(cohort) - len(with_label),
        "method": (
            "Non-empty BoxScoreTraditionalV3 position labels observed for the same stable NBA "
            "player id inside this exact window. A player may carry more than one observed "
            "label; a blank label stays unknown and is never inferred."
        ),
        "sha256_sorted_player_position_mapping": content_sha256(
            f"{anchor}|{','.join(values)}" for anchor, values in sorted(with_label.items())
        ),
    }


def build_cohort_evidence(
    session: Session,
    *,
    season: str,
    season_type: SeasonType,
    start: date,
    end: date,
    store: RawPayloadStore,
    reconciliation: GameIdentityReconciliation,
    repo_root: Path,
    source_paths: Sequence[str] = DEFAULT_SOURCE_FINGERPRINT_PATHS,
    report_dir: Path,
) -> dict[str, Any]:
    """Assemble the whole manifest from persisted state. Reads no clock."""
    ready, missing_tipoff = games_to_backfill(
        session, season=season, season_type=season_type, start=start, end=end
    )
    in_scope: list[BackfillGame | MissingTipoffGame] = [*ready, *missing_tipoff]
    game_pk_to_nba = {game.game_id: game.nba_game_id for game in in_scope}

    expected_path = default_expected_coverage_path(season, season_type)
    expected = (
        ExpectedGameCoverage.from_json(expected_path.read_text(encoding="utf-8"))
        if expected_path.is_file()
        else None
    )
    coverage_path = default_coverage_path(season, season_type)
    coverage_report = (
        CoverageReport.from_json(coverage_path.read_text(encoding="utf-8"))
        if coverage_path.is_file()
        else None
    )
    game_coverage = coverage_for_games(
        session, ready=ready, missing_tipoff=missing_tipoff, coverage_report=coverage_report
    )
    cascade = exclusion_cascade(
        session,
        ready=ready,
        missing_tipoff=missing_tipoff,
        game_coverage=game_coverage,
        expected=expected,
        coverage_report=coverage_report,
        start=start,
        end=end,
    )

    observations = select_canonical_pregame_observations(
        session, game_ids=[game.game_id for game in ready]
    )
    resolved_player_pks = {obs.player_id for obs in observations if obs.player_id is not None}
    anchors = {
        row.player_id: row.external_id
        for row in session.scalars(
            select(PlayerExternalId).where(
                PlayerExternalId.source == ExternalSource.NBA,
                PlayerExternalId.player_id.in_(resolved_player_pks or {0}),
            )
        )
    }

    join = _participation_join(
        session,
        observations=observations,
        game_pk_to_nba=game_pk_to_nba,
        anchors=anchors,
        ready_game_pks=[game.game_id for game in ready],
    )

    lead_times = [obs.lead_time_minutes for obs in observations]
    status_counts = Counter(obs.status.value for obs in observations)

    observed_anchors: Counter[str] = Counter()
    for obs in observations:
        if obs.player_id is not None and obs.player_id in anchors:
            observed_anchors[anchors[obs.player_id]] += 1

    return {
        "canonical_observations": {
            "distinct_nba_game_ids": len({obs.game_id for obs in observations}),
            "distinct_report_timestamps": len({obs.report_timestamp for obs in observations}),
            "distinct_resolved_nba_player_ids": len(
                {anchors[pk] for pk in resolved_player_pks if pk in anchors}
            ),
            "distinct_team_labels": len({obs.team_raw for obs in observations}),
            "lead_time_minutes": {
                "maximum": max(lead_times) if lead_times else None,
                "minimum": min(lead_times) if lead_times else None,
            },
            "resolved_player_id": sum(1 for obs in observations if obs.player_id is not None),
            "sha256_sorted_stable_records": content_sha256(
                _observation_records(observations, game_ids=game_pk_to_nba, anchors=anchors)
            ),
            "status_counts": dict(sorted(status_counts.items())),
            "total_player_games": len(observations),
            "unresolved_player_id": sum(1 for obs in observations if obs.player_id is None),
        },
        "cross_source_reconciliation": reconciliation.as_summary(),
        "kind": MANIFEST_KIND,
        "limitations": [
            "Evidence only. No injury-status conversion rate, threshold, probability or "
            "calibration claim is fit or reported here; that is the separately Model-gated "
            "quant deliverable.",
            "A report observation with no participation row stays unknown. The authoritative "
            "ledger can be silent for a full absence, and silence is never converted into an "
            "outcome.",
            "Reachability is bounded by the candidate anchors documented in "
            "docs/adapters/nba-injury-report.md: a report published far from an anchor instant "
            "is not recovered and is not claimed to be.",
            "Raw PDFs and JSON captures, the checkpoint, the coverage and expected-game reports "
            "and the SQLite database remain gitignored operational state. This manifest is the "
            "repository-safe evidence derived from them.",
            "Capture timestamps in source_capture_summary record when requests were made. They "
            "are provenance, not reproducible values: a fresh live sweep necessarily produces "
            "different ones.",
        ],
        "operational_artifacts": {
            "files": (
                _artifact_files(list(report_dir.glob("*.json"))) if report_dir.is_dir() else {}
            ),
        },
        "operator": {
            "commands": [
                "python -m alembic upgrade head",
                "python -m hoops_gm.ingest.backfill nba-identity --season 2025-26",
                "python -m hoops_gm.ingest.backfill season 2025-26 --with-participation "
                "--start 2025-12-08 --end 2026-01-04",
                "python -m hoops_gm.ingest.injury_report.backfill plan 2025-26 "
                "--start 2025-12-08 --end 2026-01-04 --max-requests 120",
                "python -m hoops_gm.ingest.injury_report.backfill run 2025-26 "
                "--start 2025-12-08 --end 2026-01-04 --max-requests 120",
                "python -m hoops_gm.ingest.injury_report.backfill observations 2025-26 "
                "--start 2025-12-08 --end 2026-01-04",
                "python -m hoops_gm.ingest.injury_report.cohort_evidence 2025-26 "
                "--start 2025-12-08 --end 2026-01-04 "
                "--out ../docs/adapters/"
                "nba-injury-report-cohort-2025-12-08--2026-01-04.json",
            ],
            "manifest_is_a_pure_function_of_persisted_state": True,
            "source_fingerprint_method": (
                "SHA-256 of each file's bytes with CRLF normalised to LF, which equals the "
                "SHA-256 of the committed Git blob for a file Git stores with LF endings and is "
                "invariant across checkout newline configuration and operating system."
            ),
            "source_fingerprints": {
                relative: source_file_sha256(repo_root / relative)
                for relative in sorted(source_paths)
                if (repo_root / relative).is_file()
            },
        },
        "participation_join": join,
        "position_evidence": _position_evidence(
            store,
            nba_game_ids=[game.nba_game_id for game in ready],
            observed_anchors=observed_anchors,
        ),
        "schema_version": SCHEMA_VERSION,
        "scope": {
            "end_game_date": end.isoformat(),
            "expected_games": cascade.expected_games,
            "game_dates": len({game.game_date for game in in_scope}),
            "games_in_scope": len(in_scope),
            "games_missing_tipoff": len(missing_tipoff),
            "games_with_tipoff": len(ready),
            "season": season,
            "season_type": season_type.value,
            "selection_basis": (
                "Inclusive four-week window centred on the 2025-12-22 NBA injury-report archive "
                "format/cadence boundary, selected from the official schedule before any per-game "
                "or PDF sweep. Unchanged from the invalidated cohort: the window was never the "
                "defect. What changed is that the corrected LeagueGameFinder parser no longer "
                "drops a game whose two official team rows repeat one canonical MATCHUP string, "
                "so the window now yields every official game it always contained."
            ),
            "start_game_date": start.isoformat(),
        },
        "source_capture_summary": _capture_summary(store),
        "supersedes": {
            "invalidated_by": "PR #37",
            "invalidated_cohort": "171 games across 25 game dates",
            "omitted_game_ids": ["0022501229", "0022501230"],
            "omitted_game_date": "2025-12-13",
            "omitted_player_game_logs": 39,
            "reason": (
                "The LeagueGameFinder parser behind the invalidated cohort built a game only "
                "when both reciprocal team rows were recognised, and assigned both rows to one "
                "side when they repeated the canonical MATCHUP string, so an unpaired entry was "
                "silently dropped. Every figure in the invalidated manifest was recomputed here "
                "from corrected sources rather than carried forward."
            ),
        },
        "trusted_entry_cascade": {
            "candidate_forbidden_403": cascade.candidates_forbidden,
            "candidate_not_available_404": cascade.candidates_not_available,
            "candidate_quarantined_unscoped": cascade.candidates_quarantined_unscoped,
            "candidates_attempted": cascade.candidates_attempted,
            "canonical_player_games": cascade.canonical_player_games,
            "canonical_player_games_player_resolved": (
                cascade.canonical_player_games_player_resolved
            ),
            "entries_in_scope": cascade.entries_in_scope,
            "entries_legacy_excluded": cascade.entries_legacy_excluded,
            "entries_not_yet_submitted": cascade.entries_not_yet_submitted,
            "entries_resolved_game_id": cascade.entries_resolved_game_id,
            "entries_resolved_player_id": cascade.entries_resolved_player_id,
            "entries_with_listed_status": cascade.entries_status_listed,
            "expected_games": cascade.expected_games,
            "games_legacy_excluded": cascade.games_legacy_excluded,
            "games_observed": cascade.games_observed,
            "games_unresolved_evidence": cascade.games_unresolved_evidence,
            "mastheads_recovered": cascade.mastheads_recovered,
            "missing_from_ingest": cascade.missing_from_ingest,
            "unresolved_game_id_sample": [
                list(sample) for sample in cascade.unresolved_game_id_sample
            ],
        },
    }


def _participation_join(
    session: Session,
    *,
    observations: Sequence[CanonicalPregameObservation],
    game_pk_to_nba: Mapping[int, str],
    anchors: Mapping[int, str],
    ready_game_pks: Sequence[int],
) -> dict[str, Any]:
    """Join canonical observations to the authoritative participation ledger.

    Joined locally by ``(game_id, player_id)`` and then *proved* through stable
    source identity: the NBA game id and the NBA player external id. A local
    surrogate key is an artefact of one database build; an observation whose
    link cannot be re-expressed in source-stable terms is reported as such
    rather than counted.
    """
    rows = session.scalars(
        select(PlayerParticipation).where(PlayerParticipation.game_id.in_(ready_game_pks or [0]))
    ).all()
    by_key = {(row.game_id, row.player_id): row for row in rows}

    outcomes: Counter[str] = Counter()
    joined_records: list[str] = []
    without_participation = 0
    without_anchor = 0

    for obs in observations:
        if obs.player_id is None:
            continue
        anchor = anchors.get(obs.player_id)
        if anchor is None:
            without_anchor += 1
            continue
        row = by_key.get((obs.game_id, obs.player_id))
        if row is None:
            without_participation += 1
            continue
        outcomes[row.outcome.value] += 1
        joined_records.append(
            "|".join(
                (
                    game_pk_to_nba[obs.game_id],
                    anchor,
                    obs.report_timestamp.isoformat(),
                    obs.status.value,
                    row.outcome.value,
                    str(obs.lead_time_minutes),
                )
            )
        )

    return {
        "joined_player_games": len(joined_records),
        "key": ["nba_games.nba_game_id", "player_external_ids[source=nba].external_id"],
        "local_join_columns": ["game_id", "player_id"],
        "missing_rows_are_not_inferred_as_nonparticipation": True,
        "participation_outcome_counts": dict(sorted(outcomes.items())),
        "participation_rows_in_scope": len(rows),
        "resolved_observations_without_nba_anchor": without_anchor,
        "resolved_observations_without_participation_row": without_participation,
        "sha256_sorted_joined_stable_records": content_sha256(sorted(joined_records)),
    }


def render_cohort_evidence(evidence: Mapping[str, Any]) -> str:
    """Canonical JSON text: sorted keys, two-space indent, trailing newline."""
    return json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - operator tool
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("season", help="e.g. 2025-26")
    parser.add_argument("--season-type", default="regular", choices=[t.value for t in SeasonType])
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(".."),
        help="repository root, for source-file fingerprints (default: parent of backend/)",
    )
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--report-dir", type=Path, default=Path("data") / "reports")
    parser.add_argument(
        "--allow-fetch",
        action="store_true",
        help=(
            "permit one throttled, cached request per reconciliation view the raw store has "
            "never captured (default: off, so a regeneration is offline and a missing view is "
            "reported rather than silently fetched)"
        ),
    )
    args = parser.parse_args(argv)

    season_type = SeasonType(args.season_type)
    store = RawPayloadStore(args.raw_root)
    database = Database.from_settings(get_settings())
    nba = NbaStatsClient(store=store) if args.allow_fetch else None

    with database.session() as session:
        reconciliation = reconcile_game_identity(
            session,
            season=args.season,
            season_type=season_type,
            start=args.start,
            end=args.end,
            store=store,
            nba=nba,
        )
        missing_views = sorted(set(RECONCILIATION_VIEWS) - set(reconciliation.views))
        if missing_views:
            print(
                f"no capture available for reconciliation view(s) {missing_views}; re-run with "
                "--allow-fetch. Publishing a cohort over an absent witness is exactly the "
                "failure this reconciliation exists to prevent.",
                file=sys.stderr,
            )
            return 1
        if not reconciliation.agreed:
            print(
                "cross-source game identity disagreement -- refusing to publish a cohort "
                f"manifest over it: {reconciliation.disagreements()}",
                file=sys.stderr,
            )
            return 1
        evidence = build_cohort_evidence(
            session,
            season=args.season,
            season_type=season_type,
            start=args.start,
            end=args.end,
            store=store,
            reconciliation=reconciliation,
            repo_root=args.repo_root,
            report_dir=args.report_dir,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_cohort_evidence(evidence), encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    print(f"  views agreed: {sorted(reconciliation.views)}")
    print(f"  games: {len(reconciliation.union)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
