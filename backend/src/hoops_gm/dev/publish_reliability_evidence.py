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

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from hoops_gm.availability.reliability import ReliabilityCohortClaim, publish_reliability_cohorts
from hoops_gm.core.config import Settings
from hoops_gm.db.lineage import NBA_SCHEDULE_ARTIFACT_KEY, current_refresh
from hoops_gm.db.models.enums import GameStatus, RefreshArtifactType, SeasonType
from hoops_gm.db.models.identity import NbaTeam
from hoops_gm.db.models.schedule import TeamScheduleEntry
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

    ``team_schedule_rows`` is counted back out of the table rather than taken
    from :class:`ImportCounts`. It was originally a ``created``/``updated``
    pair read straight off the importer's return value, and that pair was a
    lie: ``_persist_schedule_cohort`` seeds its counts from ``import_games``
    before it touches ``team_schedule``, so ``updated`` counted **nba_games**
    rows. On the owner's real store it printed ``created 2460, updated 1230``
    for a table that ends up holding 2,460 rows — two tables summed into one
    object under a name that claims one of them.

    Nothing about that was ill-formed: both integers were correct counts of
    real writes, the JSON validated, and the number was wrong only if you knew
    which table each half came from. It is the same shape as ``gameEt`` — a
    self-describing field that is confidently, checkably about something other
    than what it says — and it was caught by comparing the printed number to
    ``select count(*) from team_schedule``, which is what
    ``test_the_row_count_names_the_table_it_counted`` now does every run.
    """

    season: str
    games: int
    team_schedule_rows: int
    schedule_derived: bool
    schedule_source: str | None
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

    **The derive step is skipped when a real schedule cohort already covers the
    season.** An independent review found that without this, running the real
    ``ingest/schedule_import.py`` and then this command silently *relabels* the
    lineage row: the derived cohort hashes to the same ``schedule_content_version``
    because the rows are identical, ``record_refresh`` is idempotent on that
    version, and it overwrites ``source`` in place. The single surviving row then
    claims the schedule was derived from ``nba_games`` when it came from
    ``ScheduleLeagueV2`` — a lie in the one row that answers "where did this
    schedule come from", with the true answer gone and no second row to notice.

    **``record_refresh`` still does that**, and this skip closes **one of the two
    directions** in which this PR created reach for it. Being precise about which,
    because an earlier draft claimed the hazard was simply "closed":

    *Publish after a real import* — closed. The skip means the derive branch runs
    only when the SCHEDULE scope for the season is empty, so ``record_refresh``
    necessarily takes the insert path and there is nothing to overwrite.

    *Real import after a publish* — **not closed, and it cannot be closed here.**
    ``ingest/schedule_import.py`` calls ``import_schedule`` with the default
    source; if a derived row already sits at the same content version it is
    relabelled to ``ScheduleLeagueV2``. The relabel is performed by the importer,
    not by this command, so no amount of skipping here prevents it.

    That direction is left open deliberately, and it is the benign one: the
    surviving label is *accurate*, because the real importer really did just
    write those rows. What is lost is the weaker derived label, not the true
    provenance — so it is not the "lie in the row" that motivated the finding
    above. It is still a loss of history, and it is recorded rather than fixed.

    Fixing the primitive edits a file fingerprinted by
    ``docs/adapters/nba-injury-report-cohort-2025-10-21--2026-04-12.json``, so
    the fix cannot land without regenerating that manifest.

    An earlier version of this docstring said that regeneration "needs live
    ``stats.nba.com`` calls". **That is false and this lane disproved it.** The
    generator refuses without ``--allow-fetch`` only when it cannot find the
    recorded captures, and the refusal seen here came from letting ``--raw-root``
    default to ``backend/data/raw``, which does not exist. Pointed at the real
    capture store the regeneration runs offline: ``--out`` to the committed path
    at an unmodified tree reproduces the manifest with an **empty git diff**, and
    with the primitive fixed exactly **one** of 1656 leaves moves — the
    ``db/lineage.py`` fingerprint. So the repair is available, and it is also
    positive evidence that the lineage change does not touch the cohort.

    It is not done here for a reason feasibility cannot settle: that manifest is
    ``data-engineer``'s artifact under the Adapter gate, and a manifest this lane
    regenerates **passes its own fingerprint check by construction**. Green would
    say the bytes agree, not that ``backend`` was entitled to republish another
    lane's evidence. The open defect is pinned by
    ``test_record_refresh_still_relabels_which_is_why_the_publisher_skips``. Do
    not remove this skip on the assumption the primitive is safe.

    Skipping is the right behaviour independent of that bug. This command exists
    to make a *box-score-backfilled* store servable; a store that already has a
    real schedule needs only the SOURCE and MODEL halves, and a derived schedule
    has strictly less provenance than the one it would overwrite.
    """

    existing_schedule = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        season=season,
    )
    derived = existing_schedule is None
    if derived:
        parsed = schedule_from_played_games(session, season=season)
        import_schedule(session, parsed, source=DERIVED_SOURCE)
        last_game_date = max(record.game.game_date for record in parsed.games)
        games = len(parsed.games)
    else:
        last_game_date = require_complete_regular_season(session, season=season)[-1].game_date
        games = _rows_for_season(session, season)

    resolved_as_of = as_of_date or last_game_date
    claim = publish_reliability_cohorts(
        session,
        season=season,
        as_of_date=resolved_as_of,
        refreshed_at=published_at or datetime.now(UTC),
    )
    persisted_rows = session.scalar(
        select(func.count())
        .select_from(TeamScheduleEntry)
        .where(TeamScheduleEntry.season == season)
    )
    # Read the source back off the refresh row rather than reporting the constant
    # this command *would* have written. On the skip branch it did not write one,
    # and the recorded provenance is the real importer's. Printing DERIVED_SOURCE
    # unconditionally made the operator-facing JSON claim a provenance the
    # database contradicted, on the very path added to protect that provenance.
    recorded = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        season=season,
    )
    return PublishResult(
        season=season,
        games=games,
        team_schedule_rows=persisted_rows or 0,
        schedule_derived=derived,
        schedule_source=recorded.source if recorded is not None else None,
        claim=claim,
    )


def _rows_for_season(session: Session, season: str) -> int:
    """Final regular-season game count, for the branch that derives nothing."""

    return len(require_complete_regular_season(session, season=season))


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
                "team_schedule_rows": result.team_schedule_rows,
                "schedule_derived": result.schedule_derived,
                "schedule_version": result.claim.schedule_version,
                "source_version": result.claim.source_version,
                "derivation_version": result.claim.derivation_version,
                "window_start": result.claim.window_start.isoformat(),
                "as_of_date": result.claim.as_of_date.isoformat(),
                "schedule_source": result.schedule_source,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
