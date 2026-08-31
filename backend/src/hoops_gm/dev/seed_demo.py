"""One command that brings **one** database to the state every screen needs.

**Why this exists.** The three seeders under this package compose, and until
2026-08-22 nobody had run them in one order. The demo state lived in three
separate SQLite files, one backend serves one file, and the owner opened the
dashboard to a working draft board next to two ``409`` error pages. Nothing was
broken; the composition simply existed only as commands someone happened to
know.

That is the failure this module closes, and it is a *documentation* failure
with a code-shaped fix: the composed order is now a committed artefact rather
than an oral tradition. ``docs/demo.md`` is the other half.

Run it::

    cd backend
    python -m hoops_gm.dev.seed_demo --database-url sqlite:///./demo_all.db
    DATABASE_URL=sqlite:///./demo_all.db python -m hoops_gm

Then ``/schedule``, ``/projections`` and ``/draft`` all answer from that one
file.

**The order is not a preference.**

* :func:`~hoops_gm.dev.seed_projections.seed_projections` already composes
  :func:`~hoops_gm.dev.seed_schedule_grid.seed_schedule_grid` internally, so
  running the schedule seed first is *redundant, not required*. It is harmless
  — that seed converges on re-run — but a runbook that lists it as a third
  mandatory step is describing a constraint that does not exist.
* :func:`~hoops_gm.dev.seed_draft.seed_drafts` must come **last**, and this one
  is real. It creates two ``[demo] `` leagues with ``fantrax_league_id IS
  NULL``, which is precisely the first arm of ``require_safe_demo_target``'s
  refusal — so a database seeded with drafts first makes the schedule seed
  refuse, and neither the schedule nor the projections screen can ever be
  driven against it.
* The frontend hardcodes ``LEAGUE_ID = 1`` in both ``SchedulePage.tsx`` and
  ``ProjectionsPage.tsx``. On a fresh database the schedule league is inserted
  first and therefore *is* league 1. Seeding drafts first would give league 1 to
  a mock draft configuration with no schedule attached — a second, quieter
  reason the order is load-bearing, and one that produces a wrong screen rather
  than a refusal.
* The composed auction receives the exact canonical players written by the
  synthetic projection import. The standalone draft command remains unresolved
  by design; only this composition supplies IDs, and it supplies no name match.

**Everything it writes is synthetic except the player names**, and the names
have to be real because the identity resolver matches on them. See the two
modules it composes for the full statement; the warning is repeated on stderr
here so nobody has to go looking.

**One session, so the whole thing is atomic.** If the draft seed refuses, the
projections and schedule writes roll back with it and the database is left
exactly as it was found. Composing at the CLI level instead — three processes,
three transactions — is what produced the partially-seeded databases this
module replaces.

**Reproducible from empty, not idempotent.** Re-running this against its own
output *refuses*, and the refusal names a league rather than an ordering: the
draft seed's ``[demo] `` leagues carry ``fantrax_league_id IS NULL``, which is
the first arm of ``require_safe_demo_target``. Each individual seeder converges
on re-run; their composition does not, because the later one leaves rows the
earlier one is written to refuse. Delete the database file and run the command
again — that is the supported repeat, and :func:`looks_like_a_previous_demo_seed`
exists so the refusal says so instead of reading as data loss.

Schema is built with ``Base.metadata.create_all`` rather than Alembic, so the
result is model-built rather than migration-built. Fine for a throwaway file,
wrong for anything else.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from hoops_gm.core.config import Settings
from hoops_gm.db.models.identity import Player
from hoops_gm.db.models.league import League
from hoops_gm.db.models.projections import Projection
from hoops_gm.db.session import Database
from hoops_gm.dev.seed_draft import (
    DEMO_PREFIX,
    CanonicalDraftPlayer,
    DraftSeedResult,
    seed_drafts,
)
from hoops_gm.dev.seed_projections import (
    DEMO_COHORT_SIZE,
    ProjectionsSeedResult,
    seed_projections,
)
from hoops_gm.dev.seed_schedule_grid import (
    DEFAULT_FIXTURES_DIR,
    FANTRAX_LEAGUE_ID,
    DemoSeedRefused,
    create_schema_only_on_a_fresh_database,
    redacted_url,
)
from hoops_gm.ingest.errors import SourceContractError

#: The league id both dashboard screens are hardcoded to. Not enforced here —
#: it is a consequence of insertion order on a fresh database — but printed, so
#: a database that came out otherwise is visible rather than a mystery 409.
FRONTEND_LEAGUE_ID = 1


@dataclass(frozen=True)
class DemoSeedResult:
    """What one composed seed put in one database.

    Kept as the two sub-results rather than a flattened bag of counts: each
    already documents what its own numbers mean, and re-copying them here would
    create a second place for them to drift.
    """

    projections: ProjectionsSeedResult
    drafts: DraftSeedResult


def seed_demo(
    session: Session,
    *,
    fixtures_dir: Path = DEFAULT_FIXTURES_DIR,
    cohort_size: int = DEMO_COHORT_SIZE,
) -> DemoSeedResult:
    """Seed schedule, projections and drafts into one session, in one order.

    ``seed_projections`` runs first because it composes the schedule seed and
    because both dashboard screens read league 1; ``seed_drafts`` runs last
    because its ``[demo] `` leagues would make the schedule seed's foreign-league
    refusal fire. See the module docstring for why each of those is a
    constraint rather than a habit.
    """

    projections = seed_projections(session, fixtures_dir=fixtures_dir, cohort_size=cohort_size)
    auction_players = tuple(
        CanonicalDraftPlayer(player_id=player_id, player_label=player_label)
        for player_id, player_label in session.execute(
            select(Projection.player_id, Player.full_name)
            .join(Player, Player.id == Projection.player_id)
            .where(Projection.projection_import_id == projections.projection_import_id)
            .order_by(Projection.player_id)
        )
    )
    drafts = seed_drafts(session, auction_players=auction_players)
    return DemoSeedResult(projections=projections, drafts=drafts)


def looks_like_a_previous_demo_seed(session: Session) -> bool:
    """Is every league in this database one of ours?

    Called only after a refusal has already fired, purely to decide whether to
    add a sentence to the message. It changes no guard and grants no
    permission: the refusal stands either way, and the worst this can do is
    offer the wrong advice to someone whose real league happens to be named
    ``[demo] ...``.

    It earns its place because the second thing anyone does with a seed command
    is run it twice, and the refusal they get names *a league* — which reads
    like "your data is in danger", not like "you already did this". The
    supported repeat is to delete the file, and nothing said so.
    """

    leagues = session.execute(select(League.name, League.fantrax_league_id)).all()
    if not leagues:
        return False
    return all(
        fantrax_league_id == FANTRAX_LEAGUE_ID or name.startswith(DEMO_PREFIX)
        for name, fantrax_league_id in leagues
    )


def proof(result: DemoSeedResult, *, database_url: str) -> dict[str, object]:
    """The counts a reader can check a running dashboard against.

    Grouped by screen rather than by seeder, because "which screen is wrong" is
    the question someone asks when they open the dashboard, and a flat list of
    counts does not answer it.
    """

    return {
        "database_url": redacted_url(database_url),
        "schedule_screen": {
            "league_id": result.projections.league_id,
            "season": result.projections.season,
            "schedule_version": result.projections.schedule_version,
        },
        "projections_screen": {
            "league_id": result.projections.league_id,
            "cohort_size": result.projections.cohort_size,
            "projections_written": result.projections.projections_written,
            "identities_accepted": result.projections.identities_accepted,
            "identities_unresolved": result.projections.identities_unresolved,
            "content_sha256": result.projections.content_sha256,
        },
        "draft_screen": {
            "auction_draft_id": result.drafts.auction_draft_id,
            "auction_selections": result.drafts.auction_selections,
            "auction_last_sequence": result.drafts.auction_last_sequence,
            "snake_draft_id": result.drafts.snake_draft_id,
            "snake_selections": result.drafts.snake_selections,
            "snake_last_sequence": result.drafts.snake_last_sequence,
        },
        # Printed rather than asserted. The dashboard reads league 1 from a
        # constant in two .tsx files, so a database whose schedule league came
        # out as anything else serves two 404s and no explanation.
        "frontend_expects_league_id": FRONTEND_LEAGUE_ID,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--database-url",
        default="sqlite:///./demo_all.db",
        help=(
            "SQLAlchemy URL to seed. Defaults to a throwaway local SQLite file. "
            "A relative sqlite path is anchored to the repo root, not the working "
            "directory, so the default lands at <repo>/demo_all.db."
        ),
    )
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=DEFAULT_FIXTURES_DIR,
        help=(
            "Directory holding all four committed NBA fixtures: the ScheduleLeagueV2 "
            "payload, the static team list, CommonAllPlayers and PlayerIndex. One "
            "directory supplies all of them — pointing this at a directory holding "
            "only a schedule capture fails on the missing player fixture."
        ),
    )
    parser.add_argument(
        "--cohort-size",
        type=int,
        default=DEMO_COHORT_SIZE,
        help=(
            f"how many players the synthetic projection cohort carries. Default "
            f"{DEMO_COHORT_SIZE}. Not a realistic league-wide cohort at any value."
        ),
    )
    args = parser.parse_args(argv)

    # `_env_file=None`, matching seed_schedule_grid and seed_draft: this command
    # takes its target as a flag, and a repo-root .env carrying the owner's real
    # DATABASE_URL must not be able to redirect it. seed_projections.main does
    # not pass it, which is harmless there only because it always passes an
    # explicit database_url too.
    database: Database | None = None
    try:
        database = Database.from_settings(
            Settings(environment="development", database_url=args.database_url, _env_file=None)
        )
        create_schema_only_on_a_fresh_database(database)
        with database.session() as session:
            result = seed_demo(
                session,
                fixtures_dir=args.fixtures_dir,
                cohort_size=args.cohort_size,
            )
    except DemoSeedRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        # A second, separate read, after the seeding session has already been
        # rolled back and closed. Reusing that session would ask the question
        # of a transaction that has just been discarded.
        #
        # Wrapped, because this is a diagnostic and a diagnostic must never be
        # the thing that fails: a half-built schema reaches this handler via
        # the seed's own refusal, and a `SELECT` against a missing table here
        # would replace a clear refusal with an unhandled traceback.
        repeat_run = False
        if database is not None:
            try:
                with database.session() as session:
                    repeat_run = looks_like_a_previous_demo_seed(session)
            except SQLAlchemyError:
                repeat_run = False
        if repeat_run:
            print(
                "\nEvery league in that database was created by this seed, so this is "
                "almost certainly a second run against its own output. The composed "
                "seed is reproducible from empty rather than idempotent: the draft "
                "seed leaves leagues the schedule seed is written to refuse. Delete "
                "the database and run this command again.",
                file=sys.stderr,
            )
        return 2
    except FileNotFoundError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except (SQLAlchemyError, SourceContractError, ValueError) as exc:
        # The traceback as well as the message, for the reason
        # seed_schedule_grid gives at length: `ValueError` is a superclass of
        # `json.JSONDecodeError` and `SQLAlchemyError` covers our own bugs, so a
        # genuine defect lands here and one line of English is strictly less
        # than a stack trace.
        print(f"seed failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 3
    finally:
        if database is not None:
            database.dispose()

    print(json.dumps(proof(result, database_url=args.database_url), indent=2))
    print(
        "\nEvery projection number, seat, selection and price above is invented. Only "
        "the player names are real, because the projection identity resolver and the "
        "draft category join need canonical players. A screenshot taken from any of "
        "these screens proves shape and nothing else.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
