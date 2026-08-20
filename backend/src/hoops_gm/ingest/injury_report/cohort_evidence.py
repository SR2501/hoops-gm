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
set from four views and requires them to be equal **as sets, not as counts** — a
count check passes a window that is the right size and the wrong membership,
which is exactly what a mislabelled timezone produces.

**Read :data:`VIEW_INDEPENDENCE` before treating four agreeing views as four
independent witnesses.** They are not, and an earlier revision of this docstring
said they were. ``persisted_nba_games`` is the same ``LeagueGameFinder`` bytes
through the same parser, so it is a persistence check. ``player_game_logs`` was
already required equal to ``LeagueGameFinder`` at season scope before any row was
written, so its season-level agreement is guaranteed by construction; what it
independently witnesses is the windowing, decided from a column the schedule
query never supplied. ``ScheduleLeagueV2`` is the only view independent of the
ingest path, and it is the one that could actually have caught the omission.

That is a smaller claim than "four independent sources agree", and it is the
true one. A witness that cannot disagree is not a witness, and saying so is
cheaper than discovering it later.
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

#: **What each view is actually independent of.** An earlier revision of this
#: module claimed all four "derive from their own source". Two of them do not,
#: and independent review caught the overstatement — which matters, because the
#: whole point of the reconciliation is that a witness which cannot disagree is
#: not a witness. Recorded in the manifest so a reader is not left to infer the
#: relationships from the ingest code.
VIEW_INDEPENDENCE: Final[dict[str, str]] = {
    "league_game_finder": (
        "The schedule source itself. The set the other three are checked against, not an "
        "independent check on it."
    ),
    "persisted_nba_games": (
        "NOT source-independent. These rows were written from the same LeagueGameFinder capture "
        "through the same parser, so this view cannot disagree except via a persistence defect. "
        "Retained as a persistence check, which is a real but different claim from corroboration."
    ),
    "player_game_logs": (
        "A separate endpoint windowed by its own GAME_DATE, but its season-level agreement with "
        "LeagueGameFinder was already required by backfill_season before any row was written "
        "(_require_matching_season_game_ids), so season-scope agreement here is guaranteed by "
        "construction. What it independently witnesses is the *windowing*: which of those games "
        "fall inside the requested dates, decided from a column the schedule query never supplied."
    ),
    "schedule_league_v2": (
        "The only view independent of the ingest path. A separate endpoint, separately captured, "
        "whose Eastern game date is derived from gameDateTimeEst reconciled against its UTC "
        "sibling. This is the witness that could actually have caught the omission."
    ),
}

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
    """Whether the views of one window name exactly the same games.

    Not "whether independent views agree" — see :data:`VIEW_INDEPENDENCE`. Two
    of the four cannot disagree except via a persistence defect or a bypassed
    ingest gate, and describing them as independent was a claim this module had
    to retract.
    """

    start: date
    end: date
    #: ``{view name: sorted game ids}``. See :data:`VIEW_INDEPENDENCE` for what
    #: each view is and is not independent of — they are **not** four
    #: independent sources, and an earlier version of this comment said they
    #: were.
    views: Mapping[str, tuple[str, ...]]

    @property
    def agreed(self) -> bool:
        """Whether every view names the same games.

        Deliberately says nothing about whether they named *any*. Four views
        that all found nothing agree perfectly and witness nothing, so
        :meth:`witnessed` is a separate question and both are checked before a
        cohort is published — see :func:`main`. Found by independent review:
        before that split, a mistyped ``--start``/``--end`` would have written a
        manifest asserting agreement across four sources over zero games, with
        exit code 0.
        """
        return len({frozenset(ids) for ids in self.views.values()}) == 1

    @property
    def witnessed(self) -> bool:
        """Whether any view actually named a game. An empty witness corroborates nothing."""
        return bool(self.union)

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
            "independence": dict(sorted(VIEW_INDEPENDENCE.items())),
            "method": (
                "All views are required to be equal as SETS, not as counts -- a count check "
                "passes a window that is the right size and the wrong membership. Each view "
                "applies the window using its own date field, but they are NOT four independent "
                "sources: persisted_nba_games derives from the database, written from the same "
                "LeagueGameFinder payload and parser this reconciliation reads, and "
                "player_game_logs was already required equal to LeagueGameFinder at season "
                "scope before any row was written. Read 'independence' below before treating "
                "four agreeing views as four witnesses; only schedule_league_v2 is independent "
                "of the ingest path. Row counts and clean parsing prove nothing about "
                "completeness."
            ),
            "sha256_sorted_game_ids": content_sha256(self.union),
            "start_game_date": self.start.isoformat(),
            "witnessed": self.witnessed,
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
    """Rebuild the window's game-identity set from every view the store can supply.

    Cached captures are used when present, so this adds no load to
    ``stats.nba.com`` after a sweep; ``nba`` is required only to fetch a view the
    store has never seen. A view whose capture is absent and which cannot be
    fetched is omitted rather than silently treated as agreeing — an absent
    witness is not a corroborating one. See :data:`VIEW_INDEPENDENCE` for what
    each view is and is not independent of; they are not four independent
    sources.
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

    **An unresolved observation falls back to its raw reported name.** With an
    empty anchor instead, two different unresolved players in the same game, on
    the same report, with the same status collided: independent review measured
    11 such collisions across 1,948 observations, so substituting one unresolved
    player for another would not have changed the fingerprint. The count was
    never wrong — duplicates are preserved — but a fingerprint that cannot see a
    substitution is weaker than the name "stable records" promises. The raw name
    is the only identity an unresolved row has, which is precisely why
    :func:`_canonical_observation_key` uses it too.
    """
    records = []
    for obs in observations:
        anchor = anchors.get(obs.player_id) if obs.player_id is not None else None
        identity = f"nba:{anchor}" if anchor is not None else f"raw:{obs.player_name_raw}"
        records.append(
            "|".join(
                (
                    game_ids[obs.game_id],
                    identity,
                    obs.team_raw,
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
) -> dict[str, Any]:
    """What ``BoxScoreTraditionalV3``'s ``position`` field actually is.

    **This section reports a source finding, not a positional distribution, and
    the change is deliberate.** The invalidated cohort published
    ``distinct_resolved_players_by_observed_label`` as evidence that the cohort
    was positionally diverse. It was not evidence of that, and could never have
    been: the endpoint emits ``position`` for exactly five players per team per
    game — the starting lineup — always in the sequence ``F, F, C, G, G``. Every
    other player carries ``""``.

    So the label is a *lineup slot*, not a player attribute. A distribution over
    it is forced to roughly 2F : 2G : 1C for any cohort whatsoever, which is why
    the invalidated manifest reported 76 : 76 : 43 and why that number could not
    have distinguished a diverse cohort from a skewed one. Worse for this
    cohort specifically: an injury cohort's most central players are the ones
    least likely to have started, so "no label" was systematically the *injured*
    players, and calling them position-unknown read a knowable fact ("did not
    start") as missing evidence.

    This is the ``AGENTS.md`` failure mode exactly — a well-formed, type-correct,
    non-null field that lies about what it denotes. Nothing about parsing it was
    wrong. Found by independent review of the regeneration.

    The counts below are derived, not asserted, so a reader can disprove the
    finding cheaply: if the endpoint ever starts labelling every player,
    ``labelled_players_per_team`` stops being ``[5]`` and
    ``distinct_label_sequences`` stops being a single ``F,F,C,G,G``.
    """
    per_team_counts: Counter[int] = Counter()
    sequences: Counter[str] = Counter()
    games_with_capture = 0
    games_without_capture: list[str] = []

    for nba_game_id in sorted(set(nba_game_ids)):
        ref = store.latest(
            source=NBA_SOURCE, endpoint="BoxScoreTraditionalV3", params={"game_id": nba_game_id}
        )
        body = ref.read_json().get("boxScoreTraditional") if ref is not None else None
        if not isinstance(body, dict):
            # Counted, never skipped silently. The raw store is prunable
            # operational state, and a shrinking denominator caused by a pruned
            # capture must not look like a finding about the source.
            games_without_capture.append(nba_game_id)
            continue
        games_with_capture += 1
        for side in ("homeTeam", "awayTeam"):
            team = body.get(side)
            if not isinstance(team, dict):
                continue
            labels = [
                str(entry.get("position") or "").strip()
                for entry in team.get("players") or ()
                if isinstance(entry, dict) and str(entry.get("position") or "").strip()
            ]
            per_team_counts[len(labels)] += 1
            sequences[",".join(labels)] += 1

    return {
        "distinct_label_sequences": dict(sorted(sequences.items())),
        "finding": (
            "BoxScoreTraditionalV3 emits a non-empty position only for the five starters of "
            "each team, always in the sequence F,F,C,G,G. The field denotes a starting-lineup "
            "slot, not a player attribute, so a distribution over it is forced to 2F:2G:1C for "
            "any cohort and cannot establish positional diversity. A blank is 'did not start "
            "this game', which is knowable, not 'position unknown'."
        ),
        "games_without_box_score_capture": sorted(games_without_capture),
        "games_with_box_score_capture": games_with_capture,
        "labelled_players_per_team": dict(sorted(per_team_counts.items())),
        "positional_diversity_established": False,
        "supersedes": (
            "The invalidated cohort's position_evidence section reported 167 of 363 players "
            "with an observed G/F/C label (C 43, F 76, G 76) and 196 as position-unknown. Those "
            "figures are a starting-lineup artifact and must not be used as evidence of cohort "
            "composition."
        ),
        "what_would_be_needed": (
            "A source that prints a position for every player on a roster, ingested as its own "
            "adapter under the Adapter gate. Not attempted here."
        ),
    }


def _reason_evidence(
    observations: Sequence[CanonicalPregameObservation],
) -> dict[str, Any]:
    """What the reports gave as *reasons*, not just as statuses.

    Independent review flagged the omission, and my own brief is explicit about
    it: capture reason codes, not just box scores, because the availability
    engine depends on them and because the first normalisation will be wrong and
    need re-deriving. A cohort published as availability evidence that
    summarises 1,508 ``out`` rows without saying that some of them are two-way
    G League assignments rather than injuries is under-describing itself.

    Reported as the raw leading category the source printed, deliberately
    un-normalised beyond splitting on the source's own separator. AGENTS.md:
    do not trust stated DNP reasons. These are retained as evidence of what was
    said, never as facts about an injury, and nothing downstream should treat
    "Rest" and "left knee soreness" as different claims about the world merely
    because the report spelled them differently.
    """
    categories: Counter[str] = Counter()
    empty = 0
    placeholder = 0
    for obs in observations:
        raw = obs.reason_raw.strip()
        if not raw:
            empty += 1
            continue
        # The source writes "Injury/Illness - Left knee soreness"; the leading
        # token before the first " - " is the category it chose.
        head = raw.split(" - ", 1)[0].strip()
        if head == "-":
            placeholder += 1
        categories[head] += 1
    return {
        "caveat": (
            "Raw source text, grouped by the category the report itself printed before its own "
            "' - ' separator. Not a normalised code, not a clinical claim, and not evidence that "
            "a stated reason is the real one -- 'Rest' is routinely laundered as a minor ailment."
        ),
        "observations_with_empty_reason_text": empty,
        # Distinct from the above, and reported separately because reporting only
        # the former published a `0` beside a visible "-" bucket of 14 and invited
        # a reader to conclude every observation carried a stated reason. The
        # report prints a literal "-" as its own placeholder for "none given".
        "observations_with_placeholder_reason": placeholder,
        "stated_reason_categories": dict(sorted(categories.items())),
        # Sub-counts sum to their category. An earlier version counted only
        # observations containing " - ", so `Rest` published a single detail
        # against a category of 9 and `Not With Team` published an empty object
        # against 23 — the same collapse-a-distinction-the-artifact-cannot-expose
        # shape this whole section was created to fix. Bare rows are counted
        # under an explicit bucket rather than dropped.
        "stated_reason_subcategories": {
            head: _published_subcategories(observations, head=head)
            for head in sorted(_LOW_CARDINALITY_REASON_HEADS & set(categories))
        },
    }


def _published_subcategories(
    observations: Sequence[CanonicalPregameObservation], *, head: str
) -> dict[str, Any]:
    """One head's detail counts, or a summary when the tail stops being a vocabulary."""
    details = Counter(
        raw.split(" - ", 1)[1].strip() if " - " in raw else _REASON_NO_DETAIL
        for raw in (obs.reason_raw.strip() for obs in observations)
        if raw.split(" - ", 1)[0].strip() == head
    )
    if len(details) > _MAX_PUBLISHED_SUBCATEGORIES:
        return {
            "_distinct_values": len(details),
            "_not_published": (
                "this head's detail field has become free text rather than a vocabulary; "
                "publishing it would commit unbounded source prose"
            ),
            "_total": sum(details.values()),
        }
    return dict(sorted(details.items()))


#: Bucket for an observation whose reason is a bare category with no detail.
_REASON_NO_DETAIL: Final = "(no detail given)"


#: Reason categories whose second field is expected to be a small closed
#: vocabulary. ``Injury/Illness`` is deliberately excluded: its tail is free
#: clinical text with 256 distinct values in this window alone, and enumerating
#: it would put a per-player medical narrative in a committed artifact for no
#: analytic gain.
#:
#: **The allowlist asserts low cardinality; :data:`_MAX_PUBLISHED_SUBCATEGORIES`
#: measures it.** Independent review pointed out that the allowlist alone is a
#: claim, not a check — a future season in which ``Not With Team`` or
#: ``Personal Reasons`` grows a free-text tail would dump it into the manifest
#: under a constant asserting it could not. A head whose observed detail
#: vocabulary exceeds the cap is collapsed to a count instead, so the artifact
#: says how many distinct values there were rather than listing them.
_LOW_CARDINALITY_REASON_HEADS: Final[frozenset[str]] = frozenset(
    {
        "G League",
        "Not With Team",
        "Personal Reasons",
        "Rest",
        "League Suspension",
        "Team Suspension",
        "Coach's Decision",
        "Concussion Protocol",
        "Return to Competition Reconditioning",
    }
)

#: Above this many distinct detail values, a head's tail is not a vocabulary and
#: is not published as one.
_MAX_PUBLISHED_SUBCATEGORIES: Final = 12


@dataclass(frozen=True)
class TipoffReconciliation:
    """Whether two endpoints agree on *when* each game started.

    Separate from :class:`GameIdentityReconciliation` because it answers a
    different question, and it carries the same ``agreed``/``witnessed`` split
    for the same reason: 173 games whose instants were never compared agree
    perfectly and witness nothing. An earlier version of this section returned
    a bare ``agreed`` boolean and reintroduced exactly the defect the identity
    reconciliation had already been corrected for — found by independent review,
    in the same commit that documented why it was wrong.
    """

    compared: int
    absent: tuple[str, ...]
    disagreements: Mapping[str, Mapping[str, str]]
    checked: bool = True
    unavailable_reason: str | None = None

    @property
    def agreed(self) -> bool:
        return not self.disagreements

    @property
    def witnessed(self) -> bool:
        return self.compared > 0

    def as_summary(self) -> dict[str, Any]:
        return {
            "agreed": self.agreed,
            "checked": self.checked,
            "disagreements": {k: dict(v) for k, v in sorted(self.disagreements.items())},
            "games_compared": self.compared,
            "games_without_both_instants": list(self.absent),
            "method": (
                "nba_games.tipoff_utc, ingested from BoxScoreSummaryV3, compared against "
                "ScheduleLeagueV2's gameDateTimeUTC for the same game. Two separately captured "
                "endpoints in this build. Every lead time and the pre-tipoff selection itself "
                "depend on this instant, so an unchecked shift would move every number in the "
                "cohort silently. Note the independence here is operational rather than "
                "structural: hoops_gm.ingest.importers.import_schedule can also write "
                "tipoff_utc from ScheduleLeagueV2, and has no production caller today, but "
                "nothing records the provenance of a persisted instant -- so if that path ever "
                "acquires one, this becomes a comparison of one endpoint against itself."
            ),
            "unavailable_reason": self.unavailable_reason,
            "witnessed": self.witnessed,
        }


def _tipoff_reconciliation(
    session: Session,
    *,
    season: str,
    season_type: SeasonType,
    start: date,
    end: date,
    store: RawPayloadStore,
) -> TipoffReconciliation:
    """Check the *instants*, not only the identities.

    Every lead time in this cohort, and the pre-tipoff selection that defines a
    canonical observation at all, rests on ``nba_games.tipoff_utc`` — which
    ``backfill_season`` takes from ``BoxScoreSummaryV3`` alone. The
    game-identity reconciliation checks four views of *which games exist* and
    never checked *when they started*, even though ``ScheduleLeagueV2``'s
    ``gameDateTimeUTC`` is already parsed a few lines away.

    A silent tip-off shift moves every lead time and can flip a row across the
    pre-tipoff boundary, turning a post-game row into evidence.
    """
    ref = store.latest(
        source=NBA_SOURCE, endpoint="ScheduleLeagueV2", params={"league_id": "00", "season": season}
    )
    if ref is None:
        return TipoffReconciliation(
            compared=0,
            absent=(),
            disagreements={},
            checked=False,
            unavailable_reason="no ScheduleLeagueV2 capture retained",
        )

    published = {
        record.game.nba_game_id: record.game.tipoff_utc
        for record in parse_schedule(ref.read_json(), season=season).games
    }
    persisted = session.scalars(
        select(NbaGame).where(
            NbaGame.season == season,
            NbaGame.season_type == season_type,
            NbaGame.game_date >= start,
            NbaGame.game_date <= end,
        )
    )

    compared = 0
    absent: list[str] = []
    disagreements: dict[str, dict[str, str]] = {}
    for game in persisted:
        expected = published.get(game.nba_game_id)
        if expected is None or game.tipoff_utc is None:
            absent.append(game.nba_game_id)
            continue
        compared += 1
        if expected != game.tipoff_utc:
            disagreements[game.nba_game_id] = {
                "box_score_summary_v3": game.tipoff_utc.isoformat(),
                "schedule_league_v2": expected.isoformat(),
            }

    return TipoffReconciliation(
        compared=compared,
        absent=tuple(sorted(absent)),
        disagreements=disagreements,
    )


def build_cohort_evidence(
    session: Session,
    *,
    season: str,
    season_type: SeasonType,
    start: date,
    end: date,
    store: RawPayloadStore,
    reconciliation: GameIdentityReconciliation,
    tipoffs: TipoffReconciliation,
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
        "cross_source_tipoff_reconciliation": tipoffs.as_summary(),
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
        ),
        "reason_evidence": _reason_evidence(observations),
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

    **The join itself is on local surrogate keys** — ``(game_id, player_id)`` —
    and the manifest's ``local_join_columns`` has always said so. An earlier
    version of this docstring claimed the links were then "proved" through
    stable source identity, which overstated what happens: the NBA game id and
    the NBA player external id are *required to exist* for a row to be counted,
    and they are what the fingerprint is rendered from, but they do not perform
    or re-verify the join. Independent review caught the overstatement. Stating
    the weaker true mechanism is worth more than a defence that reads well and
    is not there.

    ``PlayerParticipation`` carries a unique constraint on
    ``(player_id, game_id)``, so the surrogate join cannot fan out or lose a row
    within one database build. What it cannot survive is a rebuild that
    reassigns surrogate ids between the two sides — which is why the fingerprint
    is source-keyed even though the join is not.
    """
    rows = session.scalars(
        select(PlayerParticipation).where(PlayerParticipation.game_id.in_(ready_game_pks or [0]))
    ).all()
    by_key = {(row.game_id, row.player_id): row for row in rows}

    outcomes: Counter[str] = Counter()
    joined_records: list[str] = []
    joined_lead_times: list[int] = []
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
        joined_lead_times.append(obs.lead_time_minutes)
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
        # Reported separately from the canonical figure on purpose. The
        # canonical maximum is driven by a single observation that has no
        # participation row and is therefore NOT in this set, so quoting only
        # the canonical maximum would send a consumer of the *joined* evidence
        # looking for a tail that is absent from the data they actually use.
        # Found by independent review.
        "joined_lead_time_minutes": {
            "maximum": max(joined_lead_times) if joined_lead_times else None,
            "minimum": min(joined_lead_times) if joined_lead_times else None,
        },
        "join_is_on_local_surrogate_keys": True,
        "key_rendered_in_fingerprint": [
            "nba_games.nba_game_id",
            "player_external_ids[source=nba].external_id",
        ],
        "local_join_columns": ["game_id", "player_id"],
        "missing_rows_are_not_inferred_as_nonparticipation": True,
        "participation_outcome_counts": dict(sorted(outcomes.items())),
        "participation_rows_in_scope": len(rows),
        "resolved_observations_without_nba_anchor": without_anchor,
        "resolved_observations_without_participation_row": without_participation,
        "sha256_sorted_joined_stable_records": content_sha256(sorted(joined_records)),
    }


def refusal_reason(
    reconciliation: GameIdentityReconciliation,
    tipoffs: TipoffReconciliation,
) -> str | None:
    """Why this cohort may not be published, or ``None`` if it may.

    Extracted from :func:`main` so the refusal is testable. Independent review
    pointed out that ``main`` carries ``# pragma: no cover`` and had no test, so
    the exit-1 refusal that this module, ``docs/adapters/nba-stats.md`` and the
    handoff all advertise as the safety property was itself never exercised. A
    guard nobody runs is a comment, in exactly the way an unchecked fingerprint
    is.

    Each refusal is a separate question and is checked separately: a witness can
    be absent, present-but-disagreeing, or present-and-empty, and only the
    middle one is what "disagreement" ordinarily means. The tip-off checks were
    added a round later and were initially reported without blocking anything,
    which meant a disagreement about *when every game started* published with
    exit 0 — caught by review, and the reason they are enforced here rather than
    merely summarised.

    ``tipoffs`` is required rather than defaulted. It was optional when first
    introduced, and an optional guard is an omissible one: nothing tested that
    the call site passed it, because ``main`` is ``pragma: no cover``. Required
    is the difference between a guard and a suggestion.
    """
    missing = sorted(set(RECONCILIATION_VIEWS) - set(reconciliation.views))
    if missing:
        return (
            f"no capture available for reconciliation view(s) {missing}; re-run with "
            "--allow-fetch. Publishing a cohort over an absent witness is exactly the failure "
            "this reconciliation exists to prevent."
        )
    if not reconciliation.agreed:
        return (
            "cross-source game identity disagreement -- refusing to publish a cohort manifest "
            f"over it: {reconciliation.disagreements()}"
        )
    if not reconciliation.witnessed:
        return (
            f"every reconciliation view found zero games in "
            f"{reconciliation.start}..{reconciliation.end}. Views that all found nothing agree "
            "perfectly and witness nothing; check the requested window and that the raw store "
            "holds captures covering it."
        )
    if not tipoffs.checked:
        return (
            f"tip-off instants could not be reconciled ({tipoffs.unavailable_reason}). Every "
            "lead time and the pre-tipoff selection rest on that instant, so it is not "
            "published unchecked."
        )
    if not tipoffs.agreed:
        return (
            "BoxScoreSummaryV3 and ScheduleLeagueV2 disagree about when games started -- "
            "refusing to publish, because every lead time and the pre-tipoff selection depend "
            f"on that instant: {dict(tipoffs.disagreements)}"
        )
    if not tipoffs.witnessed:
        return (
            f"zero tip-off instants were compared across {len(tipoffs.absent)} in-scope games. "
            "Instants that were never compared agree perfectly and witness nothing."
        )
    return None


def render_cohort_evidence(evidence: Mapping[str, Any]) -> str:
    """Canonical JSON text: sorted keys, two-space indent, trailing newline."""
    return json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - operator tool
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("season", help="e.g. 2025-26")
    parser.add_argument(
        "--season-type",
        default=SeasonType.REGULAR.value,
        choices=[SeasonType.REGULAR.value],
        help=(
            "regular season only. The reconciliation requires ScheduleLeagueV2, which exposes "
            "only 002-prefixed regular-season game ids, so a playoff scope could never assemble "
            "the full set of views. Offered as a single choice rather than as an option that "
            "parses and then fails."
        ),
    )
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
        tipoffs = _tipoff_reconciliation(
            session,
            season=args.season,
            season_type=season_type,
            start=args.start,
            end=args.end,
            store=store,
        )
        refusal = refusal_reason(reconciliation, tipoffs)
        if refusal is not None:
            print(refusal, file=sys.stderr)
            return 1
        evidence = build_cohort_evidence(
            session,
            season=args.season,
            season_type=season_type,
            start=args.start,
            end=args.end,
            store=store,
            reconciliation=reconciliation,
            tipoffs=tipoffs,
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
