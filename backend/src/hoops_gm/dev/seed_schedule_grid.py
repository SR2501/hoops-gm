"""Seed a local database from committed fixtures so the schedule grid is live.

**Why this exists.** ``GET /api/v1/leagues/{id}/schedule-grid/current`` fails
closed on missing, stale or unverifiable lineage — correctly, but that means
"it returns 409" proves nothing about whether it can ever return anything else.
The previous attempt at this endpoint was permanently unavailable and nobody
noticed, because no offline path existed that could take it to 200. This module
is that path.

Everything it uses is committed: the recorded ``ScheduleLeagueV2`` payload and
the recorded static team list under ``backend/tests/fixtures``. Nothing here
reaches the network, and every write goes through the same production importers
and calendar functions the real pipeline uses — a seed that took a shortcut
around ``import_schedule`` would prove the endpoint works against data the
producer would never have written.

Run it::

    cd backend
    python -m hoops_gm.dev.seed_schedule_grid --database-url sqlite:///./schedule_grid_demo.db
    DATABASE_URL=sqlite:///./schedule_grid_demo.db python -m hoops_gm
    curl http://127.0.0.1:8000/api/v1/leagues/1/schedule-grid/current

Re-running it against the same database is a no-op: every step is idempotent,
and the registered schedule version is a fingerprint of the persisted rows, so
an unchanged re-seed converges rather than advancing "current".
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.calendar import (
    activate_deadline_calendar,
    derive_deadline_calendar,
    project_scoring_periods,
)
from hoops_gm.core.config import Settings
from hoops_gm.db.base import Base
from hoops_gm.db.models.league import League
from hoops_gm.db.session import Database
from hoops_gm.ingest.importers import import_league_settings, import_schedule, import_teams
from hoops_gm.ingest.league_settings import (
    BRIDGE_SOURCE,
    LeagueSettingsDocument,
    PlayoffRules,
    SettingEvidence,
    SourcedSetting,
    parse_official_league_settings,
)
from hoops_gm.ingest.nba.parsers import parse_teams
from hoops_gm.ingest.nba.schedule import parse_schedule, scheduled_game_counts

EASTERN = ZoneInfo("America/New_York")

#: ``backend/tests/fixtures``. Resolved from this file so the command works
#: from a checkout regardless of the working directory. An installed wheel does
#: not ship the test fixtures; the seed says so rather than failing obscurely.
DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
SCHEDULE_FIXTURE = "nba_scheduleleaguev2_2026_27.json"
TEAMS_FIXTURE = "nba_static_teams.json"

SEASON = "2026-27"
SEASON_YEAR = 2026
LEAGUE_NAME = "Schedule grid demo league"
FANTRAX_LEAGUE_ID = "schedule-grid-demo"
CAPTURE_REF = "sha256:schedule-grid-demo"

#: The last two weekly periods are marked as playoff weeks. The settings
#: contract has no way to say "authoritatively zero playoff periods" — an
#: unknown flag is refused rather than defaulted to False — so a demo calendar
#: has to name some.
PLAYOFF_PERIOD_COUNT = 2

#: Fixed so the settings snapshot, deadline calendar and scoring-period
#: projection carry the same lineage timestamps on every run. The NBA schedule
#: refresh does *not*: ``import_schedule`` stamps ``refreshed_at`` with the
#: wall clock, so that one field differs between two seeds. Its *version* is a
#: fingerprint of the persisted rows and does converge.
SEEDED_AT = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class SeedResult:
    """What the seed put in the database, for the caller to assert against."""

    league_id: int
    season: str
    schedule_version: str
    resolved_game_count: int
    team_count: int
    period_count: int
    scheduled_team_games: int


def load_fixture(fixtures_dir: Path, name: str) -> Any:
    path = fixtures_dir / name
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} does not exist. This seed reads the committed adapter fixtures under "
            "backend/tests/fixtures, which an installed wheel does not ship; run it from a "
            "checkout, or pass --fixtures-dir."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def resolved_schedule_payload(payload: Any) -> Any:
    """The recorded payload with the still-unassigned Cup games dropped.

    The fixture deliberately contains two Emirates NBA Cup games whose teams
    the NBA has not drawn yet, and ``import_schedule`` refuses a cohort that
    does not account for every game the source reported. Dropping them here
    mirrors ``tests/test_schedule.py``; editing the fixture instead would
    destroy the upstream-drift evidence the Adapter gate keeps it for.
    """

    for game_date in payload["leagueSchedule"]["gameDates"]:
        game_date["games"] = [
            game
            for game in game_date["games"]
            if game["homeTeam"]["teamId"] != 0 and game["awayTeam"]["teamId"] != 0
        ]
    return payload


def weekly_periods(first_game: date, last_game: date) -> list[tuple[int, date, date, bool]]:
    """Monday-to-Sunday fantasy weeks spanning every scheduled game date.

    Derived from the fixture's own games rather than hard-coded, so the grid
    still covers the season if the fixture is re-recorded with different dates.
    """

    start = first_game - timedelta(days=first_game.weekday())
    end = last_game + timedelta(days=6 - last_game.weekday())
    windows: list[tuple[int, date, date, bool]] = []
    cursor = start
    number = 1
    while cursor <= end:
        windows.append((number, cursor, cursor + timedelta(days=6), False))
        cursor += timedelta(days=7)
        number += 1
    playoff_from = len(windows) - PLAYOFF_PERIOD_COUNT + 1
    return [
        (period_number, period_start, period_end, period_number >= playoff_from)
        for period_number, period_start, period_end, _ in windows
    ]


def settings_document(periods: list[tuple[int, date, date, bool]]) -> LeagueSettingsDocument:
    """A settings document carrying exactly those period windows.

    Built through ``parse_official_league_settings`` so the demo snapshot has
    the same shape and evidence discipline as a real captured one, then given
    an explicit observed playoff rule — the projection refuses to turn an
    unknown playoff flag into ``False``.
    """

    payload: dict[str, object] = {
        "seasonYear": SEASON_YEAR,
        "startDate": min(start for _, start, _, _ in periods).isoformat(),
        "endDate": max(end for _, _, end, _ in periods).isoformat(),
        "scoringPeriods": [
            {
                "number": number,
                "startDate": datetime.combine(start, time.min, tzinfo=EASTERN).isoformat(),
                "endDate": datetime.combine(end, time(23, 59, 59), tzinfo=EASTERN).isoformat(),
            }
            for number, start, end, _ in periods
        ],
    }
    playoff_numbers = tuple(number for number, _, _, is_playoff in periods if is_playoff)
    return parse_official_league_settings(
        payload,
        source_league_id=FANTRAX_LEAGUE_ID,
        capture_ref=CAPTURE_REF,
    ).model_copy(
        update={
            "playoffs": SourcedSetting(
                value=PlayoffRules(period_numbers=playoff_numbers),
                evidence=(
                    SettingEvidence(
                        source=BRIDGE_SOURCE,
                        status="observed",
                        source_path="League Rules > Playoffs",
                        capture_ref=f"bridge_payload:{FANTRAX_LEAGUE_ID}",
                    ),
                ),
            )
        }
    )


def _league(session: Session) -> League:
    league = session.scalar(select(League).where(League.fantrax_league_id == FANTRAX_LEAGUE_ID))
    if league is not None:
        return league
    league = League(
        name=LEAGUE_NAME,
        season=SEASON,
        fantrax_league_id=FANTRAX_LEAGUE_ID,
        scoring_type="h2h_categories",
        draft_type="auction",
    )
    session.add(league)
    session.flush()
    return league


def seed_schedule_grid(
    session: Session, *, fixtures_dir: Path = DEFAULT_FIXTURES_DIR
) -> SeedResult:
    """Bring one database to the exact state the schedule grid requires.

    Order is load-bearing. The deadline calendar cites the current schedule
    refresh and the current settings snapshot by version, so both have to exist
    first; the scoring-period projection then cites the activated calendar.
    """

    import_teams(session, parse_teams(load_fixture(fixtures_dir, TEAMS_FIXTURE)))
    parsed = parse_schedule(
        resolved_schedule_payload(load_fixture(fixtures_dir, SCHEDULE_FIXTURE)),
        season=SEASON,
    )
    import_schedule(session, parsed)

    league = _league(session)
    game_dates = [record.game.game_date for record in parsed.games]
    periods = weekly_periods(min(game_dates), max(game_dates))
    document = settings_document(periods)
    import_league_settings(
        session,
        league=league,
        document=document,
        source_payload_sha256=sha256(document.canonical_json().encode()).hexdigest(),
        observed_at=SEEDED_AT,
    )

    calendar = derive_deadline_calendar(session, league, derived_at=SEEDED_AT).calendar
    activate_deadline_calendar(session, league, calendar.version)
    projection = project_scoring_periods(session, league, projected_at=SEEDED_AT)

    counts = scheduled_game_counts(session, league_id=league.id, season=SEASON)
    return SeedResult(
        league_id=league.id,
        season=SEASON,
        schedule_version=projection.lineage.schedule_version,
        resolved_game_count=len(parsed.games),
        team_count=len({row.team_id for row in counts}),
        period_count=len(periods),
        scheduled_team_games=sum(row.games for row in counts),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--database-url",
        default="sqlite:///./schedule_grid_demo.db",
        help="SQLAlchemy URL to seed. Defaults to a throwaway local SQLite file.",
    )
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=DEFAULT_FIXTURES_DIR,
        help="Directory holding the committed NBA fixtures.",
    )
    args = parser.parse_args(argv)

    database = Database.from_settings(
        Settings(environment="development", database_url=args.database_url, _env_file=None)
    )
    try:
        # Idempotent, and a no-op against a database Alembic already built.
        # Migrations remain the production path; this only spares a developer
        # one extra step on a throwaway file.
        Base.metadata.create_all(database.engine)
        with database.session() as session:
            result = seed_schedule_grid(session, fixtures_dir=args.fixtures_dir)
    finally:
        database.dispose()

    print(
        json.dumps(
            {
                "database_url": args.database_url,
                "league_id": result.league_id,
                "season": result.season,
                "schedule_version": result.schedule_version,
                "resolved_game_count": result.resolved_game_count,
                "team_count": result.team_count,
                "period_count": result.period_count,
                "scheduled_team_games": result.scheduled_team_games,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
