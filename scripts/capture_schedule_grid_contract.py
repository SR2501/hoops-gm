"""Write or check the backend-owned schedule-grid contract specimen."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
CONTRACT = REPO_ROOT / "frontend" / "src" / "test" / "fixtures" / "schedule-grid.contract.json"


def _response_document() -> dict[str, Any]:
    sys.path.insert(0, str(BACKEND_SRC))

    from hoops_gm.api.routes.schedule_grid import (
        PendingScheduleGameLineage,
        ScheduleGridCount,
        ScheduleGridLineage,
        ScheduleGridPeriod,
        ScheduleGridResponse,
        ScheduleGridTeam,
        ScheduleRefreshLineage,
        ScoringPeriodProjectionLineage,
        VersionedRowLineage,
    )

    response = ScheduleGridResponse(
        league_id=1,
        season="2026-27",
        lineage=ScheduleGridLineage(
            schedule=ScheduleRefreshLineage(
                refresh_id=11,
                version="schedule-contract-v1",
                refreshed_at=datetime(2026, 9, 6, tzinfo=UTC),
                source_game_count=3,
                resolved_game_count=1,
                persisted_team_row_count=2,
                unresolved_game_ids=[],
                pending_game_ids=["pending-dated", "pending-undated"],
                pending_games=[
                    PendingScheduleGameLineage(
                        nba_game_id="pending-dated",
                        game_date=date(2026, 12, 4),
                        game_label="Emirates NBA Cup",
                        game_sub_label="Quarterfinal",
                        game_subtype="in-season-knockout",
                        date_absence_reason="",
                    ),
                    PendingScheduleGameLineage(
                        nba_game_id="pending-undated",
                        game_date=None,
                        game_label="",
                        game_sub_label="",
                        game_subtype="",
                        date_absence_reason="not_offered",
                    ),
                ],
            ),
            scoring_period_projection=ScoringPeriodProjectionLineage(
                refresh_id=12,
                version="period-contract-v1",
                refreshed_at=datetime(2026, 9, 6, tzinfo=UTC),
            ),
            deadline_calendar=VersionedRowLineage(id=13, version=1),
            settings_snapshot=VersionedRowLineage(id=14, version=1),
        ),
        teams=[
            ScheduleGridTeam(
                team_id=15,
                nba_team_id=1610612737,
                abbreviation="ATL",
                name="Atlanta Hawks",
            )
        ],
        periods=[
            ScheduleGridPeriod(
                period_number=1,
                start_date=date(2026, 10, 19),
                end_date=date(2026, 10, 25),
                is_playoff=False,
            )
        ],
        counts=[ScheduleGridCount(period_number=1, team_id=15, games=1)],
    )
    return response.model_dump(mode="json")


def _read_document(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _serialized(document: object) -> str:
    return f"{json.dumps(document, ensure_ascii=False, indent=2)}\n"


def _strict_equal(recorded: object, actual: object) -> bool:
    """Compare JSON values without Python's bool/int/float coercion."""

    if type(recorded) is not type(actual):
        return False
    if isinstance(recorded, dict) and isinstance(actual, dict):
        return recorded.keys() == actual.keys() and all(
            _strict_equal(recorded[key], actual[key]) for key in recorded
        )
    if isinstance(recorded, list) and isinstance(actual, list):
        return len(recorded) == len(actual) and all(
            _strict_equal(recorded_item, actual_item)
            for recorded_item, actual_item in zip(recorded, actual, strict=True)
        )
    return recorded == actual


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail when the contract has drifted")
    mode.add_argument("--write", action="store_true", help="rewrite the committed contract")
    args = parser.parse_args(argv)

    actual = _response_document()
    if args.check:
        try:
            recorded = _read_document(CONTRACT)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"could not read {CONTRACT}: {exc}", file=sys.stderr)
            return 2
        if not _strict_equal(recorded, actual):
            print(
                "schedule-grid contract drifted; inspect the response-model change, then run "
                "python scripts/capture_schedule_grid_contract.py --write",
                file=sys.stderr,
            )
            return 1
        return 0

    CONTRACT.write_text(_serialized(actual), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
