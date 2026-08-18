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
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"

#: A completed game from 2024-25 with both a DNP and a DND comment, chosen so
#: the participation parser is exercised on real reason text rather than on an
#: all-played box score.
FIXTURE_GAME_ID = "0022400306"

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
        "byte_size": path.stat().st_size,
        **meta,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"  wrote {name} ({path.stat().st_size:,} bytes)")


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
    payload = client.fetch_json("getLeagueInfo", params)
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
    trimmed, original = _trim_result_set(payload, keep=120)
    _write(
        "nba_leaguegamefinder_trimmed.json",
        trimmed,
        meta={
            "source": "nba_stats",
            "endpoint": "LeagueGameFinder",
            "params": {"season_nullable": FIXTURE_STATS_SEASON},
            "trimmed": True,
            "original_row_counts": original,
            "kept_rows_per_result_set": 120,
            "note": "Whole rows removed from the end. No value edited.",
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


def _never() -> Any:
    from datetime import timedelta

    return timedelta(0)


COMMANDS: dict[str, Callable[[], None]] = {
    "fantrax": record_fantrax,
    "fantrax-league-settings": record_fantrax_league_settings,
    "nba": record_nba,
}
ALL_COMMANDS = ("fantrax", "nba")


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
