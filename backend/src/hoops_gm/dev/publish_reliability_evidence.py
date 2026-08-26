"""Make an already-ingested season's store able to serve the reliability route.

**This is not a demo seed and it refuses to behave like one.** Every other
module in ``hoops_gm.dev`` builds a fabricated cohort and refuses to run
against real ingested data. This one is the exact inverse: it derives nothing
it can invent, requires a real ``nba_games`` ledger, and refuses anything else.

It exists because ``compute_reliability_scorecards`` needs three things in one
store and an NBA box-score backfill leaves only two of them. The backfill in
``hoops_gm.ingest.backfill`` writes ``nba_games``, ``player_game_logs`` and
``player_participation``; it writes no ``team_schedule`` rows and registers no
``refresh_runs``. So a store can hold a complete, correct season of
observations and still be unable to produce a single scorecard —
``_source_snapshot`` selects ``team_schedule`` first and refuses an empty
result before it reads anything else.

**Why the schedule is derived rather than fetched.** For a *completed* regular
season the played-game ledger and the schedule are the same set of games, so
``nba_games`` already contains the schedule; re-fetching ``ScheduleLeagueV2``
would add an external dependency to obtain facts that are already local. The
derivation is exact only under that condition, which is why
:func:`require_complete_regular_season` refuses anything else — see its
docstring for the defect that condition excludes.

**Derived, and the refresh row says so.** ``import_schedule`` stamps
``refresh_runs.source``, and its default names ``nba_api:ScheduleLeagueV2`` —
an endpoint this command never calls. It is passed :data:`DERIVED_SOURCE`
instead. A lineage row that names the wrong producer is not a cosmetic defect:
it is the row that answers "where did this schedule come from" after everyone
who knew has gone.

Usage::

    cd backend
    $env:PYTHONPATH = "$PWD\\src"
    python -m hoops_gm.dev.publish_reliability_evidence \\
        --database-url sqlite:///C:/path/to/hoops_gm.db --season 2025-26
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from hoops_gm.availability.reliability import ReliabilityCohortClaim, publish_reliability_cohorts
from hoops_gm.core.config import Settings
from hoops_gm.db.models.enums import GameStatus, SeasonType
from hoops_gm.db.models.identity import NbaTeam
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.db.session import Database
from hoops_gm.dev.seed_schedule_grid import redacted_url
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.importers import import_schedule
from hoops_gm.ingest.nba.models import NbaGameRecord
from hoops_gm.ingest.nba.schedule import ScheduleGameRecord, ScheduleParseResult

#: What ``refresh_runs.source`` says about a cohort built by this command.
#: Deliberately names both the producer and the table it was read from, so an
#: operator reading the row can tell it apart from a real schedule import
#: without consulting anything else.
DERIVED_SOURCE = "hoops_gm.dev.publish_reliability_evidence:nba_games"

#: An NBA regular season: 30 teams, 82 games each, 1,230 games. Constants
#: rather than a shape read off the data, because the whole point of the check
#: in :func:`require_complete_regular_season` is to compare the ledger against
#: something it did not produce.
REGULAR_SEASON_TEAMS = 30
REGULAR_SEASON_GAMES_PER_TEAM = 82
REGULAR_SEASON_GAMES = REGULAR_SEASON_TEAMS * REGULAR_SEASON_GAMES_PER_TEAM // 2


class DerivationRefused(RuntimeError):
    """The persisted ledger cannot honestly stand in for a schedule."""


@dataclass(frozen=True)
class PublishResult:
    """What was derived, and the exact claim a run may now be computed from.

    The claim is carried whole rather than re-flattened into version strings,
    because ``compute_reliability_scorecards`` takes a
    :class:`ReliabilityCohortClaim` and a caller that had to rebuild one from
    parts would be a second reader of the same producer — the split that let
    ``schedule_grid`` read keys its producer never wrote.
    """

    season: str
    games: int
    team_schedule_rows_created: int
    team_schedule_rows_updated: int
    claim: ReliabilityCohortClaim


def require_complete_regular_season(session: Session, *, season: str) -> list[NbaGame]:
    """Return the season's final games, or refuse to derive a schedule from them.

    **The defect this excludes, named.** A played game that is absent from
    ``nba_games`` does not show up downstream as a missing row. It shows up as
    a *present* row carrying a wrong value: ``build_schedule_density`` sets
    ``is_back_to_back`` from the gap to the previous game in the derived
    schedule, so a hole in the ledger silently converts a back-to-back into a
    day of rest. Nothing in the reliability chain can see that — the row is
    there, the type is right, the number is a plausible ``False`` — and
    ``back_to_back`` evidence is one of the five quantities the scorecard
    exists to report.

    **A reading in which this check passes and that defect is present.** It
    would need the ledger to be missing a played game *and* to hold a
    compensating extra one, on both affected teams, leaving every team on
    exactly 82 and the total on exactly 1,230. An importer that only inserts
    what a source returned does not fabricate games, so that reading requires
    hand-editing rows — which is outside what any check here claims to cover.
    Short of that, an incomplete ledger cannot satisfy both counts.

    That is also why the counts are constants and not, say, ``max`` over the
    per-team tallies: a check derived from the data it is checking agrees with
    a truncated ledger as readily as with a complete one.
    """

    games = list(
        session.scalars(
            select(NbaGame)
            .where(
                NbaGame.season == season,
                NbaGame.season_type == SeasonType.REGULAR,
                NbaGame.status == GameStatus.FINAL,
            )
            .order_by(NbaGame.game_date, NbaGame.nba_game_id)
        )
    )
    if not games:
        raise DerivationRefused(
            f"season {season!r} has no final regular-season games in nba_games; "
            "run the box-score backfill before publishing reliability evidence"
        )
    per_team: dict[int, int] = {}
    for game in games:
        for team_id in (game.home_team_id, game.away_team_id):
            per_team[team_id] = per_team.get(team_id, 0) + 1
    wrong = sorted(
        (team_id, played)
        for team_id, played in per_team.items()
        if played != REGULAR_SEASON_GAMES_PER_TEAM
    )
    if len(games) != REGULAR_SEASON_GAMES or len(per_team) != REGULAR_SEASON_TEAMS or wrong:
        raise DerivationRefused(
            f"season {season!r} holds {len(games)} final regular-season game(s) across "
            f"{len(per_team)} team(s); deriving a schedule from the played-game ledger is "
            f"only exact for a complete regular season ({REGULAR_SEASON_GAMES} games, "
            f"{REGULAR_SEASON_TEAMS} teams, {REGULAR_SEASON_GAMES_PER_TEAM} each). "
            f"Off-count teams: {wrong[:5]}"
        )
    return games


def schedule_from_played_games(session: Session, *, season: str) -> ScheduleParseResult:
    """Build the schedule cohort a completed season's ledger already implies.

    Returns a ``ScheduleParseResult`` — a *value* of the shape the schedule
    parser produces — rather than writing rows, so the persistence, the
    read-back check and the refresh registration all stay inside
    ``import_schedule``. Developer tooling builds state through the production
    writers; this is the input, not a second writer.

    **Scores and tip-off are carried through, and that is load-bearing.**
    ``import_schedule`` calls ``import_games``, which assigns
    ``game.home_score = record.home_score`` unconditionally for a row it
    already has. A record built from identity fields alone would therefore
    blank the score on every game in the ledger while leaving ``status``
    ``final`` — a store that still looks complete and is not. Reading them off
    the persisted row makes that write a no-op instead.
    """

    games = require_complete_regular_season(session, season=season)
    teams = {team.id: team for team in session.scalars(select(NbaTeam))}
    missing = sorted(
        {
            team_id
            for game in games
            for team_id in (game.home_team_id, game.away_team_id)
            if team_id not in teams
        }
    )
    if missing:
        raise DerivationRefused(
            f"season {season!r} references nba_teams row id(s) {missing} that are not in the "
            "database; import teams before publishing reliability evidence"
        )
    records = tuple(
        ScheduleGameRecord(
            game=NbaGameRecord(
                nba_game_id=game.nba_game_id,
                season=game.season,
                season_type=game.season_type.value,
                game_date=game.game_date,
                home_team_id=teams[game.home_team_id].nba_team_id,
                away_team_id=teams[game.away_team_id].nba_team_id,
                home_score=game.home_score,
                away_score=game.away_score,
                tipoff_utc=game.tipoff_utc,
            ),
            home_nba_team_id=teams[game.home_team_id].nba_team_id,
            away_nba_team_id=teams[game.away_team_id].nba_team_id,
            home_tricode=teams[game.home_team_id].abbreviation,
            away_tricode=teams[game.away_team_id].abbreviation,
        )
        for game in games
    )
    return ScheduleParseResult(
        season=season,
        games=records,
        unresolved_game_ids=(),
        source_game_count=len(records),
        pending_games=(),
    )


def publish_reliability_evidence(
    session: Session,
    *,
    season: str,
    as_of_date: date | None = None,
    published_at: datetime | None = None,
) -> PublishResult:
    """Derive the schedule cohort, then publish the reliability claim over it.

    Both halves are here, in this order, because neither has an honest
    done-condition of its own. ``_source_snapshot`` requires that *every* final
    game in the window has exactly its two ``team_schedule`` rows — a join
    condition between the two tables, not a property of either — so "the rows
    landed" establishes nothing on its own, and the only thing that verifies it
    is publishing a claim over the result.

    ``as_of_date`` defaults to the last final game's date, which for a
    completed season means the whole season. It is not defaulted to *today*:
    a date past the end of the season would resolve the same window while
    quietly making the source fingerprint depend on when the command was run.
    """

    parsed = schedule_from_played_games(session, season=season)
    counts = import_schedule(session, parsed, source=DERIVED_SOURCE)
    resolved_as_of = as_of_date or max(record.game.game_date for record in parsed.games)
    claim = publish_reliability_cohorts(
        session,
        season=season,
        as_of_date=resolved_as_of,
        refreshed_at=published_at or datetime.now(UTC),
    )
    return PublishResult(
        season=season,
        games=len(parsed.games),
        team_schedule_rows_created=counts.created,
        team_schedule_rows_updated=counts.updated,
        claim=claim,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="SQLAlchemy URL of an already-ingested store. No default: unlike the demo "
        "seeds this command only makes sense against real data, and a default would "
        "make the destructive-sounding word 'publish' point somewhere invisible.",
    )
    parser.add_argument("--season", required=True, help='Season label, e.g. "2025-26".')
    parser.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
        default=None,
        help="Window end. Defaults to the season's last final game.",
    )
    args = parser.parse_args(argv)

    database: Database | None = None
    try:
        database = Database.from_settings(
            Settings(environment="development", database_url=args.database_url, _env_file=None)
        )
        with database.session() as session:
            result = publish_reliability_evidence(
                session, season=args.season, as_of_date=args.as_of_date
            )
    except DerivationRefused as exc:
        print(f"refusing to publish: {exc}", file=sys.stderr)
        return 2
    except (SQLAlchemyError, SourceContractError, ValueError) as exc:
        print(f"publish failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 3
    finally:
        if database is not None:
            database.dispose()

    print(
        json.dumps(
            {
                "database_url": redacted_url(args.database_url),
                "season": result.season,
                "season_type": result.claim.season_type.value,
                "games": result.games,
                "team_schedule_rows_created": result.team_schedule_rows_created,
                "team_schedule_rows_updated": result.team_schedule_rows_updated,
                "schedule_version": result.claim.schedule_version,
                "source_version": result.claim.source_version,
                "derivation_version": result.claim.derivation_version,
                "window_start": result.claim.window_start.isoformat(),
                "as_of_date": result.claim.as_of_date.isoformat(),
                "schedule_source": DERIVED_SOURCE,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
