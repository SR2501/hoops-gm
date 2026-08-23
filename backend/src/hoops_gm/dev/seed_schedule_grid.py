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

The recorded payload is imported **unmodified**, including the two Emirates
NBA Cup games it publishes with no teams assigned. Those are recorded as
pending under ADR-013 rather than filtered out, so the demo database exercises
the pending path — a screen that must distinguish "no games this week" from
"not scheduled yet" can be driven locally instead of mocked. Until ADR-013 this
module carried a filter and a reconciliation function whose only purpose was to
get past a refusal that no longer exists; both were retired with it.

Run it::

    cd backend
    python -m hoops_gm.dev.seed_schedule_grid --database-url sqlite:///./schedule_grid_demo.db
    DATABASE_URL=sqlite:///./schedule_grid_demo.db python -m hoops_gm
    curl http://127.0.0.1:8000/api/v1/leagues/1/schedule-grid/current

Re-running it against the same database converges rather than advancing
"current": every step is idempotent at the row level, and the registered
schedule version is a fingerprint of the persisted rows, so an unchanged
re-seed re-registers the same version. It is not a strict no-op —
``import_schedule`` stamps ``refreshed_at`` with the wall clock, so that one
field moves.

It refuses to run against a database holding any league it did not create, or
any game for this season outside the fixture cohort. That guard is the point:
``nba_teams``, ``nba_games`` and ``team_schedule`` are global and the
``nba-schedule`` refresh is season-scoped with no league dimension, so a
ten-game fixture aimed at a working database would become the current
registered cohort for every consumer keyed to schedule version.

Schema is built with ``Base.metadata.create_all`` rather than Alembic, so the
demo database is model-built, not migration-built — the exact divergence the
migration tests exist to catch. Fine for a throwaway file, wrong for anything
else.

A relative SQLite path is anchored to the repo root rather than the working
directory (``Settings._resolve_relative_sqlite_path``), so the command above
writes ``<repo>/schedule_grid_demo.db``. ``*.db`` is gitignored.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import inspect, or_, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from hoops_gm.calendar import (
    activate_deadline_calendar,
    derive_deadline_calendar,
    project_scoring_periods,
)
from hoops_gm.core.config import Settings
from hoops_gm.db.base import Base
from hoops_gm.db.models.availability import PlayerParticipation
from hoops_gm.db.models.league import League
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.db.session import Database
from hoops_gm.ingest.errors import SourceContractError
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
#: Deliberately not shaped like a real capture reference. Everything this
#: module writes into a settings snapshot is synthetic, and the one field a
#: reader would use to tell the difference should say so.
CAPTURE_REF = "synthetic:schedule-grid-demo"

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
    """What the seed put in the database, for the caller to assert against.

    ``pending_game_ids`` names the games the recorded payload publishes with
    no teams assigned. They are imported as pending rather than filtered out
    (ADR-013), so the demo database exercises the pending path instead of
    hiding it: ``source_game_count`` exceeds ``resolved_game_count`` here by
    exactly these games, which is what a consumer will see against the real
    2026-27 season too.
    """

    league_id: int
    season: str
    schedule_version: str
    source_game_count: int
    pending_game_ids: tuple[str, ...]
    resolved_game_count: int
    team_count: int
    period_count: int
    scheduled_team_games: int


class DemoSeedRefused(RuntimeError):
    """The target database, or the fixture, is not safe to seed from."""


def _require_no_real_ingest(session: Session) -> None:
    """Refuse a database carrying evidence of a real ingest, league or not.

    Two signals, checked independently because either can be present without
    the other — a store built by the identity backfill has players and no
    participation, and a store built by the participation loader has both.
    Neither is written by any module under ``hoops_gm.dev``, which is what
    makes their presence conclusive rather than suggestive:

    * **any ``player_participation`` row.** No seeder writes this table. It is
      the availability ledger, the thing this whole project is for.
    * **any ``nba_games`` row for a season other than this one.** Every seeder
      parses with ``season=SEASON``, so a different season cannot have come
      from here.

    Deliberately *not* keyed on ``players`` or ``nba_teams``: ``seed_projections``
    imports 580 players and ``import_teams`` writes 30 teams, so those tables
    are populated by a legitimate demo seed and refusing on them would refuse
    the seed's own output. The two signals above are the ones with no demo
    provenance at all.

    **A missing table is treated as holding no rows, which is why the
    existence check is here rather than a ``try``.** This function runs before
    ``create_schema_only_on_a_fresh_database`` has been allowed to do anything,
    and against a half-built schema — an operator's Alembic database behind
    head, which is the exact case
    ``test_seed_cli_leaves_no_schema_behind_when_it_refuses`` pins — a bare
    ``SELECT`` raises ``OperationalError`` and replaces a clear refusal with a
    traceback. Skipping an absent table is not a weakened guard: a table that
    does not exist cannot contain a row. It costs nothing on the case that
    motivated this, because the real store carries both tables.

    This runs before every other check and before any write, so a refusal here
    leaves the database exactly as it was found.
    """

    tables = set(inspect(session.get_bind()).get_table_names())

    if PlayerParticipation.__tablename__ in tables:
        participation = session.scalar(select(PlayerParticipation.id).limit(1))
        if participation is not None:
            raise DemoSeedRefused(
                "this database holds player_participation rows, the availability ledger, "
                "which no seeder writes. That makes it a real store rather than a throwaway, "
                "whether or not it holds a league: seeding would register a synthetic 2026-27 "
                "schedule cohort and a synthetic Basketball Monster crosswalk inside it. "
                "Nothing was written. Use a throwaway --database-url."
            )

    if NbaGame.__tablename__ in tables:
        foreign_season = session.scalar(
            select(NbaGame.season).where(NbaGame.season != SEASON).limit(1)
        )
        if foreign_season is not None:
            raise DemoSeedRefused(
                f"this database holds {foreign_season!r} games, and every seeder here only "
                f"ever writes {SEASON}. That makes it a real store rather than a throwaway. "
                "Nothing was written. Use a throwaway --database-url."
            )


def load_fixture(fixtures_dir: Path, name: str) -> Any:
    path = fixtures_dir / name
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} does not exist. This seed reads the committed adapter fixtures under "
            "backend/tests/fixtures, which an installed wheel does not ship; run it from a "
            "checkout, or pass --fixtures-dir."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def require_safe_demo_target(session: Session, *, cohort_game_ids: set[str]) -> None:
    """Refuse a database that holds anything this seed did not put there.

    **The seed's league scoping is illusory, and that is the whole reason this
    exists.** ``leagues``, the settings snapshot and ``scoring_periods`` are
    league-scoped, but ``import_teams`` and ``import_schedule`` write to
    ``nba_teams``, ``nba_games`` and ``team_schedule``, which are global, and
    register a *season*-scoped ``nba-schedule`` refresh carrying no league
    dimension at all. Pointed at a populated database, a ten-game fixture would
    become the current registered 2026-27 cohort for every consumer keyed to
    schedule version — the denominator of every expected-games number.

    ``import_schedule``'s exact-cohort read-back already refuses a season
    holding rows outside the parsed cohort, so a database carrying a real full
    season is protected by the producer. The gap closed here is the realistic
    one: a working database that is empty or only partly populated for this
    season but already holds the operator's real league.

    **A third gap was found on 2026-08-23 and is closed by the first check
    below: a real store holding no league at all.** Every check in this
    function used to key on ``leagues`` or on *this* season's ``nba_games``,
    and the owner's real local database — the one at
    ``hoops-gm-data/hoops_gm.db``, invisible to a checkout because the default
    relative SQLite path anchors to each worktree's own root — holds **0
    leagues** and **1,230 games, all 2025-26**. Both existing checks passed it
    cleanly. Driven against a migrated copy: the composed seed exited **0**
    and wrote 3 leagues, 2 drafts, 10 synthetic 2026-27 games and **60
    ``synthetic-demo-*`` rows that became the current Basketball Monster
    crosswalk**, into a database holding a 43,037-row participation ledger.

    That is the same harm ``require_safe_projection_target`` exists to prevent,
    arriving by the one route it cannot see: there was no *prior* Basketball
    Monster import to conflict with, so nothing refused. The store was
    protected only by its schema being at ``0016`` — ``seed_drafts`` crashed on
    a missing ``drafts`` table and the transaction rolled back. **Protection by
    accident is not protection**, and migrating that store to head removes it.

    This is the third instance of one shape in this file's history — *a guard
    whose scope is narrower than the harm* — and the first two were both closed
    by widening the evidence rather than the intent.
    """

    _require_no_real_ingest(session)

    # Selected as a row keyed on the non-nullable `League.id`, not as the
    # nullable `fantrax_league_id` alone. A league created before Fantrax
    # pairing has `fantrax_league_id IS NULL`, which is exactly the `or_()`'s
    # first arm — and scalar-selecting that column would return `None` for it,
    # making the refusal skip the one row it was written to catch.
    foreign_league = session.execute(
        select(League.id, League.fantrax_league_id, League.season)
        .where(
            or_(
                League.fantrax_league_id.is_(None),
                League.fantrax_league_id != FANTRAX_LEAGUE_ID,
                # A row carrying the demo id under another season is not this
                # seed's either. Without this the guard passed, `_league` adopted
                # it, and the failure surfaced later inside the settings import
                # as a season mismatch — safe, because nothing was written, but
                # the docstring above claimed a refusal it was not making.
                League.season != SEASON,
            )
        )
        .limit(1)
    ).first()
    if foreign_league is not None:
        league_id, fantrax_league_id, league_season = foreign_league
        raise DemoSeedRefused(
            f"this database already holds league {league_id} ({fantrax_league_id!r}, season "
            f"{league_season!r}), which this seed did not create. Seeding writes globally scoped "
            "nba_games/team_schedule rows and registers the season-scoped "
            f"{SEASON} schedule cohort for every consumer. Point --database-url at a throwaway "
            "database instead."
        )
    foreign_game = session.scalar(
        select(NbaGame.nba_game_id)
        .where(NbaGame.season == SEASON, NbaGame.nba_game_id.not_in(sorted(cohort_game_ids)))
        .limit(1)
    )
    if foreign_game is not None:
        raise DemoSeedRefused(
            f"this database already holds {SEASON} game {foreign_game!r}, which is outside the "
            "fixture cohort. Refusing before any write rather than after."
        )


def weekly_periods(first_game: date, last_game: date) -> list[tuple[int, date, date, bool]]:
    """Monday-to-Sunday fantasy weeks spanning every scheduled game date.

    Derived from the fixture's own games rather than hard-coded, so the grid
    still covers the season if the fixture is re-recorded with different dates.
    That flexibility is exactly why the playoff slice is guarded: with two or
    fewer windows the naive slice marks the entire season as playoffs, and a
    re-recorded fixture trimmed to a short span would produce that silently.
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
    if len(windows) <= PLAYOFF_PERIOD_COUNT:
        raise DemoSeedRefused(
            f"{first_game}..{last_game} spans only {len(windows)} week(s); a demo calendar needs "
            f"more than {PLAYOFF_PERIOD_COUNT} so the playoff weeks are a tail rather than the "
            "whole season"
        )
    playoff_from = len(windows) - PLAYOFF_PERIOD_COUNT + 1
    return [
        (period_number, period_start, period_end, period_number >= playoff_from)
        for period_number, period_start, period_end, _ in windows
    ]


def settings_document(periods: list[tuple[int, date, date, bool]]) -> LeagueSettingsDocument:
    """A settings document carrying exactly those period windows.

    **Why this is hand-built rather than read from a recorded fixture**, given
    that ADR-006 rejects hand-written mocks: the recorded settings capture,
    ``tests/fixtures/fantrax_getleagueinfo_settings_sanitized.json``, is season
    **2025-26** (``seasonYear=2025``, 21 periods ending 2026-03-15). Its windows
    cannot contain a single 2026-27 game date, so seeding from it produces an
    all-zero grid and the endpoint refuses it. A recorded alternative was
    available and does not fit; that is the checkable reason, not a preference.

    Built through ``parse_official_league_settings`` so the snapshot has the
    same shape and evidence discipline as a real capture, then given an explicit
    playoff rule, because ``project_scoring_periods`` refuses to turn an unknown
    playoff flag into ``False``.

    **The playoff evidence is stamped ``observed`` and nothing was observed.**
    ``EvidenceStatus`` is ``Literal["observed", "absent"]`` and ``absent`` would
    make the projection fail closed, so there is no honest value available.
    ``source`` stays ``BRIDGE_SOURCE`` for the same reason: ``SettingSource`` is
    a three-value ``Literal`` in ``ingest/league_settings.py``, and widening it —
    the actual fix, and the one that module's own ``MIGRATION_SOURCE`` comment
    already establishes the precedent for — is ``data-engineer``'s to make, not
    this module's to force.

    What is within reach is making the row obviously synthetic to anything that
    reads it: ``capture_ref`` is a ``synthetic:`` reference matching no capture,
    ``source_path`` names this module rather than a Fantrax DOM path, and the
    league is keyed ``schedule-grid-demo`` so it can never reach a real one.
    Tracked as a follow-up for ``data-engineer``: add a ``synthetic`` source and
    switch this to it.
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
                        # Not a Fantrax DOM path. Naming the real producer is
                        # the difference between synthesized data that says so
                        # and synthesized data wearing a plausible provenance.
                        source_path="hoops_gm.dev.seed_schedule_grid (synthesized, never observed)",
                        capture_ref=f"{CAPTURE_REF}:playoffs",
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

    Order is load-bearing four times over. Parsing happens before any write so
    the target check can refuse before a row is touched. **The settings import
    runs before the schedule import**, because `import_league_settings` takes
    the league-settings scope and `import_schedule` takes `nba-schedule` —
    composed the other way round they acquire the two in the exact inverse of
    the order the route and the calendar functions use, and would deadlock a
    concurrent read of the endpoint on PostgreSQL. That the seed is developer
    tooling is not an exemption: it writes through the same locks, and the
    documented workflow is to re-seed the very database being served. Then the
    deadline calendar cites the current schedule refresh and settings snapshot
    by version, so both must exist first; and the scoring-period projection
    cites the activated calendar.
    """

    parsed = parse_schedule(load_fixture(fixtures_dir, SCHEDULE_FIXTURE), season=SEASON)
    require_safe_demo_target(
        session,
        cohort_game_ids={record.game.nba_game_id for record in parsed.games},
    )

    league = _league(session)

    # `import_league_settings` runs before `import_schedule` so the canonical
    # league-settings-before-nba-schedule lock order is a consequence of call
    # order, with no lineage primitive in developer tooling to be cargo-culted
    # as "dev tools take lineage locks". Nothing here needs the schedule first:
    # the period windows derive from `parsed`, which is already in memory.
    # The rule this expresses is narrower than any lock call would suggest —
    # *anything composing two production writers inherits their lock order and
    # must respect the global one.*
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

    import_teams(session, parse_teams(load_fixture(fixtures_dir, TEAMS_FIXTURE)))
    import_schedule(session, parsed)

    calendar = derive_deadline_calendar(session, league, derived_at=SEEDED_AT).calendar
    activate_deadline_calendar(session, league, calendar.version)
    projection = project_scoring_periods(session, league, projected_at=SEEDED_AT)

    counts = scheduled_game_counts(session, league_id=league.id, season=SEASON)
    return SeedResult(
        league_id=league.id,
        season=SEASON,
        schedule_version=projection.lineage.schedule_version,
        source_game_count=parsed.source_game_count,
        pending_game_ids=parsed.pending_game_ids,
        resolved_game_count=len(parsed.games),
        team_count=len({row.team_id for row in counts}),
        period_count=len(periods),
        scheduled_team_games=sum(row.games for row in counts),
    )


def redacted_url(database_url: str) -> str:
    """A URL safe to print, including credentials carried in query parameters.

    ``render_as_string(hide_password=True)`` masks ``URL.password`` and nothing
    else. libpq accepts ``password`` and ``sslpassword`` as query arguments and
    SQLAlchemy forwards them to the driver, so
    ``postgresql+psycopg://alice@host/db?password=...`` is a working credential
    that renders verbatim — into stdout, terminal scrollback and CI logs, which
    is the sink this exists to protect.
    """

    url = make_url(database_url)
    secret_keys = [key for key in url.query if "password" in key.lower()]
    if secret_keys:
        url = url.difference_update_query(secret_keys)
        url = url.update_query_dict(dict.fromkeys(secret_keys, "***"))
    return url.render_as_string(hide_password=True)


def create_schema_only_on_a_fresh_database(database: Database) -> None:
    """Build the schema, but only where there is none of ours to disturb.

    ``require_safe_demo_target`` runs inside a session and is rolled back on
    refusal — but DDL is not transactional in the same sense, and
    ``create_all`` ran *before* it. Against an operator's real Alembic-built
    database that is behind head, that added the missing model tables, the seed
    then refused, and the next ``alembic upgrade head`` failed with "relation
    already exists". The tool whose headline property is that it refuses to
    touch a real database had already written to it.

    So: if ``leagues`` exists, this database is not fresh and gets no DDL at
    all. Whether the seed may proceed is then entirely
    ``require_safe_demo_target``'s decision, and a genuinely half-built schema
    surfaces as a plain missing-table error rather than being silently
    completed.

    **PostgreSQL caveat, unverified here.** ``has_table`` resolves through
    ``search_path``. Against a database whose tables live in a non-default
    schema this reads ``False`` and ``create_all`` would build a shadow set in
    the default schema — the same "already wrote to a real database" failure
    this exists to close, arriving through schema resolution instead of
    ordering. No PostgreSQL was available to test it.
    """

    if inspect(database.engine).has_table(League.__tablename__):
        return
    Base.metadata.create_all(database.engine)


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

    # Engine construction is inside the `try`, not above it: a mistyped
    # `--database-url` is the commonest operator error here, and both of its
    # failure modes (`NoSuchModuleError` for an unknown dialect, `ArgumentError`
    # for an unparseable URL) are `SQLAlchemyError` subclasses raised by *this*
    # call. Building the engine outside meant the handler named exactly the
    # right exception and could never see it.
    database: Database | None = None
    try:
        database = Database.from_settings(
            Settings(environment="development", database_url=args.database_url, _env_file=None)
        )
        create_schema_only_on_a_fresh_database(database)
        with database.session() as session:
            result = seed_schedule_grid(session, fixtures_dir=args.fixtures_dir)
    except DemoSeedRefused as exc:
        print(f"refusing to seed: {exc}", file=sys.stderr)
        return 2
    except (SQLAlchemyError, SourceContractError, ValueError) as exc:
        # Two operator-error shapes reach here rather than `DemoSeedRefused`,
        # and both used to exit with a bare traceback: a database holding the
        # demo Fantrax id under a different season (`ValueError` from the
        # settings import) and a half-built schema (`OperationalError`). Neither
        # writes anything, so this is legibility rather than safety.
        #
        # **The traceback is printed as well as the message, not instead of
        # it.** `ValueError` is a superclass of `json.JSONDecodeError` and
        # `SQLAlchemyError` covers our own programming errors, so a genuine bug
        # can land here — and in a developer tool, one line of English is
        # strictly less than a stack trace. Suppressing it would buy legibility
        # by deleting the diagnostic, which is the trade this repository has
        # spent the day refusing everywhere else.
        print(f"seed failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 3
    finally:
        if database is not None:
            database.dispose()

    print(
        json.dumps(
            {
                # Masked: the flag accepts any SQLAlchemy URL, and a PostgreSQL
                # one carries a credential — in the userinfo *or* the query
                # string — that would otherwise land in terminal scrollback and
                # CI logs.
                "database_url": redacted_url(args.database_url),
                "league_id": result.league_id,
                "season": result.season,
                "schedule_version": result.schedule_version,
                # Three counts of two different populations, named so they
                # cannot be mistaken for each other. `source_game_count` is
                # what the recorded payload published; `pending_game_ids` are
                # the games in it with no teams assigned, which have no
                # `team_schedule` rows and are not counted in the grid. The
                # API's `lineage.schedule` block reports exactly these numbers.
                "games_recorded_in_fixture": result.source_game_count,
                "games_pending_no_teams_assigned": list(result.pending_game_ids),
                "games_imported_into_cohort": result.resolved_game_count,
                "api_lineage_schedule_source_game_count": result.source_game_count,
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
