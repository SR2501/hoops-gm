"""Record the fixtures the Adapter gate contract tests run against.

    python -m hoops_gm.ingest.record_fixtures --all

**Refreshing a fixture is a deliberate act, not a way to make a test pass.**
ADR-006 is explicit: regenerating a fixture to silence a failing contract test
defeats the entire mechanism, because the contract test exists to tell us the
upstream changed. If a contract test goes red, find out what changed and say so
in ``docs/handoff.md`` — then refresh, and say that too.

This script exists so that refreshing is reproducible and auditable rather than
a sequence of ad-hoc commands somebody once ran. Every fixture is written with
a manifest entry recording when it was captured, from which endpoint, with what
parameters, and — for the trimmed ones — exactly what was removed.

**Some fixtures are trimmed, and that is recorded rather than hidden.** A
season of ``PlayerGameLogs`` is 26,306 rows and ``CommonAllPlayers`` is 5,205;
committing those in full would add tens of megabytes to a repository for no
extra assurance. Trimming only ever removes whole rows from the end of a result
set. **No value is ever edited**, no row is synthesised, and the original row
count is recorded in the manifest so a contract test can assert against the
real scale even when it parses the trimmed copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"

#: A completed game from 2024-25 with both a DNP and a DND comment, chosen so
#: the participation parser is exercised on real reason text rather than on an
#: all-played box score.
FIXTURE_GAME_ID = "0022400306"

#: A real neutral-site game whose two LeagueGameFinder rows repeat the same
#: canonical matchup. Its summary supplies independent home/away team IDs.
FIXTURE_RECONCILIATION_GAME_ID = "0022400633"

#: A mid-season 2025-26 game. This one exists specifically to pin the finding
#: that ``BoxScoreSummaryV2``'s inactive list is empty for every 2025-26 date
#: after opening night while V3's is correct. A contract test asserts a
#: **non-zero** inactive count here — asserting merely that the call succeeded
#: would have passed throughout the period when the data was silently gone.
FIXTURE_MIDSEASON_GAME_ID = "0022500560"
FIXTURE_MIDSEASON_GAME_DATE = "2026-01-12"

#: Seasons the fixtures are captured for.
FIXTURE_STATS_SEASON = "2024-25"
FIXTURE_CURRENT_SEASON = "2026-27"
_LEAGUE_SETTINGS_RETAINED_SECTIONS = frozenset(
    {
        "draftSettings",
        "draftType",
        "endDate",
        "poolSettings",
        "rosterInfo",
        "rosterPeriods",
        "scoringPeriods",
        "scoringSystem",
        "seasonYear",
        "startDate",
    }
)


def _write(name: str, payload: Any, *, meta: dict[str, Any]) -> None:
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_ROOT / name
    path.write_text(json.dumps(payload, indent=1, sort_keys=False), encoding="utf-8")
    manifest = _load_manifest()
    manifest[name] = {
        "captured_at": datetime.now(UTC).isoformat(),
        "byte_size": _canonical_byte_size(path),
        **meta,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"  wrote {name} ({path.stat().st_size:,} bytes on disk)")


def _canonical_byte_size(path: Path) -> int:
    """Size of the file's canonical (LF) bytes, not the working tree's.

    ``path.stat().st_size`` counts CRLF on a Windows checkout while Git stores
    LF, so a recorded size is unreproducible on any other platform — the exact
    checkout-dependence PR #30 had to correct in the cohort manifest's source
    fingerprints, found again here by independent review. This value equals
    ``git cat-file -s`` for any file Git stores with LF endings.

    Entries recorded before this fix retain their working-tree sizes until their
    fixture is next re-recorded; the values are stale, not silently corrected,
    because rewriting them without re-capturing would assert a size for bytes
    nobody re-read.
    """
    return len(path.read_bytes().replace(b"\r\n", b"\n"))


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        return {}
    loaded = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _trim_result_set(payload: dict[str, Any], keep: int) -> tuple[dict[str, Any], dict[str, int]]:
    """Keep the first ``keep`` rows of each result set, recording the originals."""
    trimmed = json.loads(json.dumps(payload))
    original: dict[str, int] = {}
    for entry in trimmed.get("resultSets", []):
        rows = entry.get("rowSet")
        if isinstance(rows, list):
            original[entry.get("name", "?")] = len(rows)
            entry["rowSet"] = rows[:keep]
    return trimmed, original


def _select_league_game_finder_games(
    payload: dict[str, Any], game_ids: list[str]
) -> tuple[dict[str, Any], dict[str, int]]:
    """Retain complete game groups in explicit order from a real source payload."""
    selected = json.loads(json.dumps(payload))
    original: dict[str, int] = {}
    for entry in selected.get("resultSets", []):
        rows = entry.get("rowSet")
        headers = entry.get("headers")
        if not isinstance(rows, list) or not isinstance(headers, list):
            continue
        original[entry.get("name", "?")] = len(rows)
        if entry.get("name") != "LeagueGameFinderResults":
            continue
        try:
            game_id_index = headers.index("GAME_ID")
        except ValueError as exc:
            raise ValueError("LeagueGameFinder fixture source lacks GAME_ID") from exc
        by_game_id: dict[str, list[Any]] = {}
        for row in rows:
            if not isinstance(row, list) or game_id_index >= len(row):
                raise ValueError("LeagueGameFinder fixture source has a malformed row")
            by_game_id.setdefault(str(row[game_id_index]), []).append(row)
        retained: list[Any] = []
        for game_id in game_ids:
            game_rows = by_game_id.get(game_id)
            if game_rows is None:
                raise ValueError(f"LeagueGameFinder fixture source lacks game {game_id}")
            if len(game_rows) != 2:
                raise ValueError(
                    f"LeagueGameFinder fixture game {game_id} has {len(game_rows)} rows, not 2"
                )
            retained.extend(game_rows)
        entry["rowSet"] = retained
    return selected, original


def _league_game_finder_fixture_ids(
    payload: dict[str, Any], *, boundary_rows: int, required_game_ids: tuple[str, ...]
) -> list[str]:
    """Choose only complete groups from a row boundary, then append required games."""
    table = next(
        (
            entry
            for entry in payload.get("resultSets", [])
            if entry.get("name") == "LeagueGameFinderResults"
        ),
        None,
    )
    if not isinstance(table, dict):
        raise ValueError("LeagueGameFinder fixture source lacks its result set")
    headers = table.get("headers")
    rows = table.get("rowSet")
    if not isinstance(headers, list) or not isinstance(rows, list):
        raise ValueError("LeagueGameFinder fixture result set is malformed")
    try:
        game_id_index = headers.index("GAME_ID")
    except ValueError as exc:
        raise ValueError("LeagueGameFinder fixture source lacks GAME_ID") from exc
    all_counts: dict[str, int] = {}
    boundary_counts: dict[str, int] = {}
    boundary_order: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or game_id_index >= len(row):
            raise ValueError("LeagueGameFinder fixture source has a malformed row")
        game_id = str(row[game_id_index])
        all_counts[game_id] = all_counts.get(game_id, 0) + 1
        if index < boundary_rows:
            boundary_counts[game_id] = boundary_counts.get(game_id, 0) + 1
            if game_id not in boundary_order:
                boundary_order.append(game_id)
    selected = [
        game_id
        for game_id in boundary_order
        if all_counts[game_id] == 2 and boundary_counts[game_id] == 2
    ]
    for game_id in required_game_ids:
        if game_id not in selected:
            selected.append(game_id)
    return selected


# --------------------------------------------------------------------------
# Fantrax official
# --------------------------------------------------------------------------


def record_fantrax() -> None:
    from hoops_gm.ingest.fantrax_official import FantraxOfficialClient

    print("fantrax_official:")
    client = FantraxOfficialClient()

    payload = client.fetch_json("getPlayerIds", {"sport": "NBA"}, max_age=_never())
    _write(
        "fantrax_getplayerids_nba.json",
        payload,
        meta={
            "source": "fantrax_official",
            "endpoint": "getPlayerIds",
            "params": {"sport": "NBA"},
            "trimmed": False,
            "note": (
                "Committed in full. The whole point of this fixture is the row mix — "
                "player rows alongside the 30 team entities that risk R24 is about — "
                "so trimming it would remove the thing it exists to test."
            ),
        },
    )

    payload = client.fetch_json("getAdp", {"sport": "NBA"}, max_age=_never())
    _write(
        "fantrax_getadp_nba.json",
        payload,
        meta={
            "source": "fantrax_official",
            "endpoint": "getAdp",
            "params": {"sport": "NBA"},
            "trimmed": False,
        },
    )

    # Fantrax returns this error envelope under HTTP 200, so it is a real
    # response and belongs in the fixtures exactly like a successful one.
    payload = client.fetch_json("getLeagueInfo", {}, max_age=_never())
    _write(
        "fantrax_getleagueinfo_missing_league_id.json",
        payload,
        meta={
            "source": "fantrax_official",
            "endpoint": "getLeagueInfo",
            "params": {},
            "trimmed": False,
            "note": (
                "Returned with HTTP status 200. A client that trusts the status code "
                "parses this error envelope as data."
            ),
        },
    )

    payload = client.fetch_json("getAdp", {"sport": "NBA", "limit": 5}, max_age=_never())
    _write(
        "fantrax_getadp_nba_limit5.json",
        payload,
        meta={
            "source": "fantrax_official",
            "endpoint": "getAdp",
            "params": {"sport": "NBA", "limit": 5},
            "trimmed": False,
            "note": "limit=5 returns 4 rows. The limit is off by one; verified for 1, 2, 3, 5, 10.",
        },
    )


def _sanitize_league_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove whole identity-bearing sections without editing retained values."""
    return {
        key: value for key, value in payload.items() if key in _LEAGUE_SETTINGS_RETAINED_SECTIONS
    }


def record_fantrax_league_settings() -> None:
    """Record a successful getLeagueInfo response without names or entity data."""
    from hoops_gm.ingest.fantrax_official import FantraxOfficialClient
    from hoops_gm.ingest.rawstore import RawPayloadStore

    league_id = os.environ.get("HOOPS_GM_FANTRAX_LEAGUE_ID")
    if not league_id:
        raise SystemExit("HOOPS_GM_FANTRAX_LEAGUE_ID is required; a userSecretId is not used")

    print("fantrax_official getLeagueInfo:")
    store = RawPayloadStore(Path("data/raw"))
    client = FantraxOfficialClient(store=store)
    params = {"leagueId": league_id}
    payload = client.fetch_json("getLeagueInfo", params, max_age=_never())
    if not isinstance(payload, dict):
        raise TypeError("getLeagueInfo fixture source must be a JSON object")

    capture = store.latest(source="fantrax_official", endpoint="getLeagueInfo", params=params)
    if capture is None:
        raise RuntimeError("getLeagueInfo response was not captured")
    raw = capture.read_bytes()
    removed = sorted(set(payload) - _LEAGUE_SETTINGS_RETAINED_SECTIONS)
    _write(
        "fantrax_getleagueinfo_settings_sanitized.json",
        _sanitize_league_settings(payload),
        meta={
            "captured_at": capture.fetched_at.isoformat(),
            "source": "fantrax_official",
            "endpoint": "getLeagueInfo",
            "params": {"leagueId": "<redacted-non-secret-league-id>"},
            "trimmed": False,
            "sanitized": True,
            "original_byte_size": len(raw),
            "original_sha256": hashlib.sha256(raw).hexdigest(),
            "original_top_level_keys": sorted(payload),
            "removed_sections": removed,
            "retained_sections": sorted(_LEAGUE_SETTINGS_RETAINED_SECTIONS),
            "note": (
                "Identity-bearing sections were removed whole. No retained source "
                "value was edited. The endpoint succeeded without userSecretId."
            ),
        },
    )


# --------------------------------------------------------------------------
# nba_api
# --------------------------------------------------------------------------


def record_nba() -> None:
    from hoops_gm.ingest.nba import NbaStatsClient

    print("nba_stats:")
    client = NbaStatsClient()

    _write(
        "nba_static_teams.json",
        client.static_teams(),
        meta={
            "source": "nba_stats",
            "endpoint": "static.teams",
            "params": {},
            "trimmed": False,
            "note": "Packaged with nba_api; no network call.",
        },
    )

    payload = client.common_all_players(season=FIXTURE_CURRENT_SEASON, only_current=True)
    _write(
        "nba_commonallplayers_current.json",
        payload,
        meta={
            "source": "nba_stats",
            "endpoint": "CommonAllPlayers",
            "params": {"season": FIXTURE_CURRENT_SEASON, "is_only_current_season": 1},
            "trimmed": False,
            "note": (
                "Current-season rosters, which is what the crosswalk must match against. "
                "Matching against a historical season manufactures a team disagreement for "
                "every player who moved in the offseason."
            ),
        },
    )

    payload = client.league_game_finder(season=FIXTURE_STATS_SEASON)
    fixture_game_ids = _league_game_finder_fixture_ids(
        payload,
        boundary_rows=120,
        required_game_ids=(FIXTURE_GAME_ID,),
    )
    trimmed, original = _select_league_game_finder_games(payload, fixture_game_ids)
    _write(
        "nba_leaguegamefinder_trimmed.json",
        trimmed,
        meta={
            "source": "nba_stats",
            "endpoint": "LeagueGameFinder",
            "params": {
                "season_nullable": FIXTURE_STATS_SEASON,
                "season_type_nullable": "Regular Season",
            },
            "trimmed": True,
            "original_row_counts": original,
            "kept_rows_per_result_set": len(fixture_game_ids) * 2,
            "note": (
                "Whole rows removed; only complete two-row game groups are retained. "
                f"Required cross-endpoint game {FIXTURE_GAME_ID} is included. No value edited."
            ),
        },
    )
    reconciliation, original = _select_league_game_finder_games(
        payload,
        [FIXTURE_RECONCILIATION_GAME_ID, "0022401188"],
    )
    _write(
        "nba_leaguegamefinder_reconciliation.json",
        reconciliation,
        meta={
            "source": "nba_stats",
            "endpoint": "LeagueGameFinder",
            "params": {
                "season_nullable": FIXTURE_STATS_SEASON,
                "season_type_nullable": "Regular Season",
            },
            "trimmed": True,
            "original_row_counts": original,
            "kept_rows_per_result_set": 4,
            "note": (
                "Whole real rows retained for one ordinary reciprocal game and one game "
                "where both team rows repeat the same canonical MATCHUP. No value edited."
            ),
        },
    )
    playoff_payload = client.league_game_finder(
        season=FIXTURE_STATS_SEASON,
        season_type="Playoffs",
    )
    playoff_game_ids = _league_game_finder_fixture_ids(
        playoff_payload,
        boundary_rows=4,
        required_game_ids=(),
    )
    playoff_trimmed, playoff_original = _select_league_game_finder_games(
        playoff_payload,
        playoff_game_ids,
    )
    _write(
        "nba_leaguegamefinder_playoffs.json",
        playoff_trimmed,
        meta={
            "source": "nba_stats",
            "endpoint": "LeagueGameFinder",
            "params": {
                "season_nullable": FIXTURE_STATS_SEASON,
                "season_type_nullable": "Playoffs",
            },
            "trimmed": True,
            "original_row_counts": playoff_original,
            "kept_rows_per_result_set": len(playoff_game_ids) * 2,
            "note": "Whole real rows retained as complete playoff game groups. No value edited.",
        },
    )
    _write(
        f"nba_boxscoresummaryv3_{FIXTURE_RECONCILIATION_GAME_ID}_reconciliation.json",
        client.box_score_summary(FIXTURE_RECONCILIATION_GAME_ID),
        meta={
            "source": "nba_stats",
            "endpoint": "BoxScoreSummaryV3",
            "params": {"game_id": FIXTURE_RECONCILIATION_GAME_ID},
            "trimmed": False,
            "note": (
                "Independent home/away anchor for the repeated-canonical "
                "LeagueGameFinder matchup fixture."
            ),
        },
    )

    payload = client.player_game_logs(season=FIXTURE_STATS_SEASON)
    trimmed, original = _trim_result_set(payload, keep=200)
    _write(
        "nba_playergamelogs_trimmed.json",
        trimmed,
        meta={
            "source": "nba_stats",
            "endpoint": "PlayerGameLogs",
            "params": {"season_nullable": FIXTURE_STATS_SEASON},
            "trimmed": True,
            "original_row_counts": original,
            "kept_rows_per_result_set": 200,
            "note": "Whole rows removed from the end. No value edited.",
        },
    )

    for game_id, label in (
        (FIXTURE_GAME_ID, ""),
        (FIXTURE_MIDSEASON_GAME_ID, "_midseason"),
    ):
        _write(
            f"nba_boxscoretraditionalv3_{game_id}{label}.json",
            client.box_score_traditional(game_id),
            meta={
                "source": "nba_stats",
                "endpoint": "BoxScoreTraditionalV3",
                "params": {"game_id": game_id},
                "trimmed": False,
            },
        )
        _write(
            f"nba_boxscoresummaryv3_{game_id}{label}.json",
            client.box_score_summary(game_id),
            meta={
                "source": "nba_stats",
                "endpoint": "BoxScoreSummaryV3",
                "params": {"game_id": game_id},
                "trimmed": False,
                "note": (
                    "Inactive lists live under homeTeam.inactives / awayTeam.inactives. "
                    "BoxScoreSummaryV2 returns an empty InactivePlayers table for this "
                    "game; V3 returns the real one."
                    if label
                    else "Inactive lists under homeTeam.inactives / awayTeam.inactives."
                ),
            },
        )


# --------------------------------------------------------------------------
# Cohort-window cross-source reconciliation
# --------------------------------------------------------------------------

#: The window the representative historical injury cohort is drawn from.
FIXTURE_COHORT_SEASON = "2025-26"
FIXTURE_COHORT_START = "2025-12-08"
FIXTURE_COHORT_END = "2026-01-04"

#: Games chosen to make the cohort's game-identity reconciliation checkable
#: offline, in this order: one date before the window, the window's first date,
#: the two neutral-site 2025-12-13 games whose ``LeagueGameFinder`` rows repeat
#: one canonical ``MATCHUP`` string (the pair PR #37's parser fix recovered and
#: the invalidated cohort silently dropped, taking the whole of 2025-12-13 with
#: them because they are the *only* two games on that date), the window's last
#: date, and one date after it. Boundary games are included precisely because a
#: windowing bug is invisible in a fixture that contains no boundary.
FIXTURE_COHORT_GAME_IDS = (
    "0022500357",  # 2025-12-07, before the window
    "0022500364",  # 2025-12-08, first in-window date
    "0022501229",  # 2025-12-13, repeated canonical MATCHUP "NYK @ ORL"
    "0022501230",  # 2025-12-13, repeated canonical MATCHUP "SAS @ OKC"
    "0022500494",  # 2026-01-04, last in-window date
    "0022500502",  # 2026-01-05, after the window
)


def _select_rows_by_game_id(
    payload: dict[str, Any], *, result_set: str, game_ids: Sequence[str]
) -> tuple[dict[str, Any], dict[str, int]]:
    """Retain whole rows for named games, editing no value."""
    selected = json.loads(json.dumps(payload))
    original: dict[str, int] = {}
    wanted = set(game_ids)
    for entry in selected.get("resultSets", []):
        rows = entry.get("rowSet")
        headers = entry.get("headers")
        if not isinstance(rows, list) or not isinstance(headers, list):
            continue
        original[entry.get("name", "?")] = len(rows)
        if entry.get("name") != result_set:
            continue
        index = headers.index("GAME_ID")
        entry["rowSet"] = [row for row in rows if str(row[index]) in wanted]
    return selected, original


def _select_schedule_game_dates(
    payload: dict[str, Any], *, game_ids: Sequence[str]
) -> tuple[dict[str, Any], int]:
    """Retain only the ``gameDates`` entries holding the named games."""
    selected = json.loads(json.dumps(payload))
    league_schedule = selected.get("leagueSchedule")
    if not isinstance(league_schedule, dict):
        raise ValueError("ScheduleLeagueV2 fixture source lacks leagueSchedule")
    dates = league_schedule.get("gameDates")
    if not isinstance(dates, list):
        raise ValueError("ScheduleLeagueV2 fixture source lacks gameDates")
    original = sum(len(entry.get("games") or ()) for entry in dates)
    wanted = set(game_ids)
    retained = []
    for entry in dates:
        games = [game for game in (entry.get("games") or ()) if str(game.get("gameId")) in wanted]
        if games:
            retained.append({**entry, "games": games})
    league_schedule["gameDates"] = retained
    return selected, original


def record_cohort_reconciliation() -> None:
    """Capture the three additional views the cohort's identity set is checked against.

    Not "the views it is proved by": only ``ScheduleLeagueV2`` is independent of
    the ingest path. See ``VIEW_INDEPENDENCE`` in
    ``hoops_gm.ingest.injury_report.cohort_evidence``.
    """
    from hoops_gm.ingest.nba import NbaStatsClient

    print("nba_stats cohort reconciliation:")
    client = NbaStatsClient()
    base_note = (
        "Whole real rows/objects retained for six named games spanning both window "
        "boundaries and the two neutral-site 2025-12-13 games. No value edited."
    )
    league_game_finder_note = (
        f"{base_note} Rows are regrouped so each game's two rows are adjacent and games appear "
        "in the order named above; the row set is identical to the source's, only its order "
        "differs, and the parser is order-independent by construction (a contract test reverses "
        "the row set and asserts the same result). Verified 2026-08-20: the source's own row "
        "order is NOT stable across requests -- two captures minutes apart returned the same "
        "twelve rows in a different order -- so a byte diff between re-recordings of this "
        "fixture is expected and is not evidence the payload changed."
    )

    payload = client.league_game_finder(season=FIXTURE_COHORT_SEASON)
    trimmed, original = _select_league_game_finder_games(payload, list(FIXTURE_COHORT_GAME_IDS))
    _write(
        "nba_leaguegamefinder_cohort_window_2025_26.json",
        trimmed,
        meta={
            "source": "nba_stats",
            "endpoint": "LeagueGameFinder",
            "params": {
                "season_nullable": FIXTURE_COHORT_SEASON,
                "season_type_nullable": "Regular Season",
            },
            "trimmed": True,
            "original_row_counts": original,
            "kept_rows_per_result_set": len(FIXTURE_COHORT_GAME_IDS) * 2,
            "note": league_game_finder_note,
        },
    )

    payload = client.player_game_logs(season=FIXTURE_COHORT_SEASON)
    trimmed, original = _select_rows_by_game_id(
        payload, result_set="PlayerGameLogs", game_ids=FIXTURE_COHORT_GAME_IDS
    )
    kept_logs = sum(
        len(entry.get("rowSet") or ())
        for entry in trimmed.get("resultSets", [])
        if entry.get("name") == "PlayerGameLogs"
    )
    _write(
        "nba_playergamelogs_cohort_window_2025_26.json",
        trimmed,
        meta={
            "source": "nba_stats",
            "endpoint": "PlayerGameLogs",
            "params": {"season_nullable": FIXTURE_COHORT_SEASON},
            "trimmed": True,
            "original_row_counts": original,
            "kept_rows_per_result_set": kept_logs,
            "note": (
                f"{base_note} This endpoint carries its own GAME_DATE, which is what makes it "
                "an independent witness to the window rather than a restatement of the schedule "
                "query."
            ),
        },
    )

    payload = client.schedule_league(season=FIXTURE_COHORT_SEASON)
    trimmed_schedule, original_games = _select_schedule_game_dates(
        payload, game_ids=FIXTURE_COHORT_GAME_IDS
    )
    _write(
        "nba_scheduleleaguev2_cohort_window_2025_26.json",
        trimmed_schedule,
        meta={
            "source": "nba_stats",
            "endpoint": "ScheduleLeagueV2",
            "params": {"league_id": "00", "season": FIXTURE_COHORT_SEASON},
            "trimmed": True,
            "original_row_counts": {"leagueSchedule.gameDates.games": original_games},
            "kept_rows_per_result_set": len(FIXTURE_COHORT_GAME_IDS),
            "note": (
                f"{base_note} Only the gameDates entries holding the named games are retained, "
                "and within each retained entry only the named games -- 2025-12-08 had a full "
                "slate and appears here with one game. Each retained game object is the "
                "source's own, unmodified."
            ),
        },
    )


# --------------------------------------------------------------------------
# NBA official injury report
# --------------------------------------------------------------------------

#: A real evening-before report from the 2025-26 season, chosen because it
#: exercises every case the parser handles: 14 matchups across 7 pages, a
#: player whose Reason wraps across two lines, and two teams (San Antonio,
#: Los Angeles Lakers) whose report had not been filed as of this capture —
#: a "NOT YET SUBMITTED" marker row rather than a player entry.
FIXTURE_INJURY_REPORT_TIMESTAMP_ET = "2025-11-01T17:30:00-04:00"


def record_injury_report() -> None:
    from datetime import datetime

    from hoops_gm.ingest.injury_report import InjuryReportClient

    print("injury_report:")
    client = InjuryReportClient()
    timestamp = datetime.fromisoformat(FIXTURE_INJURY_REPORT_TIMESTAMP_ET)
    body = client.fetch(timestamp, max_age=_never())
    name = "nba_injury_report_2025-11-01_0530pm.pdf"
    path = FIXTURE_ROOT / name
    path.write_bytes(body)
    manifest = _load_manifest()
    manifest[name] = {
        "captured_at": datetime.now(UTC).isoformat(),
        "byte_size": path.stat().st_size,
        "source": "nba_injury_report",
        "endpoint": "InjuryReportPdf",
        "params": {
            "url": "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-11-01_05PM.pdf"
        },
        "trimmed": False,
        "note": (
            "Real captured report, committed whole rather than trimmed: it is a "
            "7-page PDF (~79KB) and the parser's row-boundary logic depends on the "
            "full multi-page, multi-matchup, multi-line-reason and page-footer "
            "structure, including a same-team 'NOT YET SUBMITTED' marker row for "
            "two teams whose report had not been filed as of this capture."
        ),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"  wrote {name} ({path.stat().st_size:,} bytes)")


def _never() -> Any:
    from datetime import timedelta

    return timedelta(0)


COMMANDS: dict[str, Callable[[], None]] = {
    "cohort-reconciliation": record_cohort_reconciliation,
    "fantrax": record_fantrax,
    "fantrax-league-settings": record_fantrax_league_settings,
    "nba": record_nba,
    "injury_report": record_injury_report,
}
ALL_COMMANDS = ("fantrax", "nba", "cohort-reconciliation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="*", choices=sorted(COMMANDS), default=[])
    parser.add_argument("--all", action="store_true", help="record every source")
    args = parser.parse_args(argv)

    selected = list(ALL_COMMANDS) if args.all else args.sources
    if not selected:
        parser.error("name at least one source, or pass --all")

    print(
        "Refreshing a fixture is deliberate. If a contract test is red, find out what "
        "changed upstream and record it in docs/handoff.md before running this.\n"
    )
    for name in selected:
        COMMANDS[name]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
