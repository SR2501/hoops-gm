"""Fetch the published season schedule from ``ScheduleLeagueV2`` and import it.

    cd backend
    python -m hoops_gm.ingest.schedule_import 2026-27 --dry-run
    python -m hoops_gm.ingest.schedule_import 2026-27

Until this existed there was no committed command that loaded a real season's
forward schedule. ``ingest/backfill.py`` covers *completed* games, and
``import_schedule`` is a library function with no operator entry point, so the
first step of standing up a real database was the one step nothing described.

## Why it takes no ``--database-url``

It reads :class:`~hoops_gm.core.config.Settings` — the same source
``ingest/backfill.py`` uses — so the connection URL never appears in ``argv``
and can never be echoed. This is deliberate rather than incidental. Two
separate defects in this repository leaked a credential through exactly that
flag: one printed it verbatim, and one leaked libpq's ``password`` query
argument past ``render_as_string(hide_password=True)``, which masks
``URL.password`` and nothing else. Guarding the flag failed twice; removing it
removes the class. ``test_schedule_import.py`` asserts the parser still exposes
no such option, so it stays removed.

## Throttling, retry, caching

All inherited from :class:`~hoops_gm.ingest.nba.client.NbaStatsClient`: one
request per 1.1 seconds (just under the ~1 req/s ``stats.nba.com`` tolerates),
three attempts with exponential backoff on transport failure, and every
response captured under ``data/raw``. This command makes **one** request. A
capture younger than ``--max-age-hours`` is used instead of a request, so
re-running after a refusal costs nothing upstream.

## What it does when the source misbehaves

Nothing is written and the exit code says which kind of wrong it was. A
changed payload shape, or a cohort that does not account for every game the
source reported, exits ``2``. A source that is unreachable after retries exits
``3``. Every refusal leaves the database untouched — ``import_schedule``
fails closed inside a savepoint — so the correct response to any non-zero exit
is to read the message, not to inspect for partial writes.

## Pending games

Under ADR-013 a game the source publishes with its teams explicitly
undecided — the Emirates NBA Cup knockout bracket — is recorded as *pending*
and does not block the import. The summary prints them by id with their
labels, because "six games are pending" and "six games are pending and all six
are Cup quarterfinals and semifinals" are different claims, and only the
second one supports treating pending as "not yet decided".
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from sqlalchemy.exc import SQLAlchemyError

from hoops_gm.core.config import get_settings
from hoops_gm.db.session import Database
from hoops_gm.ingest.errors import SourceContractError, SourceUnavailable
from hoops_gm.ingest.importers import import_schedule, import_teams
from hoops_gm.ingest.nba.client import NbaStatsClient
from hoops_gm.ingest.nba.parsers import parse_teams
from hoops_gm.ingest.nba.schedule import ScheduleParseResult, parse_schedule
from hoops_gm.ingest.rawstore import RawPayloadStore

from .backfill import DEFAULT_RAW_ROOT

#: The season schedule is republished as fixtures firm up, so a stale capture
#: is a real hazard here in a way a completed box score is not. Twelve hours
#: matches ``NbaStatsClient.SEASON_MAX_AGE`` and is overridable per run.
DEFAULT_MAX_AGE_HOURS: Final = 12.0

EXIT_OK: Final = 0
#: The source contradicted its own contract, or the cohort did not account for
#: every game it reported. Nothing was written.
EXIT_SOURCE_CONTRACT: Final = 2
#: The source could not be reached after the client's retries.
EXIT_SOURCE_UNAVAILABLE: Final = 3
#: The database refused the write for a reason that is not about the source.
EXIT_DATABASE: Final = 4
#: **The import succeeded and something in it needs a human.** Not a refusal:
#: rows are written and the cohort is registered. Reserved for the pending-date
#: causes the parser itself classifies as a fault rather than an undecided
#: bracket — `unreadable` and `implausible`. `not_offered` and
#: `irreconcilable` stay exit 0, because those are the source declining to
#: commit, which is the case this whole command exists to tolerate.
#:
#: It exists because the alternative was exit 0 and a stderr paragraph: a
#: schema change on our read path would have been reported only by a nightly
#: live smoke that is allowed to fail and does not run in CI.
EXIT_IMPORTED_WITH_FAULT: Final = 5

#: Absence causes that mean *investigate*, not *wait*.
_FAULT_ABSENCE_REASONS: Final = frozenset({"unreadable", "implausible"})


@dataclass(frozen=True)
class ScheduleImportSummary:
    """What one run observed and, unless it was a dry run, wrote."""

    season: str
    source_game_count: int
    resolved_game_count: int
    pending_game_ids: tuple[str, ...]
    pending_game_labels: tuple[str, ...]
    pending_game_ids_without_a_date: tuple[str, ...]
    pending_game_date_absence: tuple[tuple[str, str], ...]
    first_game_date: str
    last_game_date: str
    dry_run: bool
    teams_created: int = 0
    teams_updated: int = 0
    schedule_created: int = 0
    schedule_updated: int = 0

    def as_json(self) -> str:
        return json.dumps(
            {
                "season": self.season,
                "dry_run": self.dry_run,
                "source_game_count": self.source_game_count,
                "resolved_game_count": self.resolved_game_count,
                "pending_game_count": len(self.pending_game_ids),
                "pending_game_ids": list(self.pending_game_ids),
                "pending_game_labels": list(self.pending_game_labels),
                # Reported even when empty, and named for what it is. A pending
                # game whose date the source did not give is recorded with
                # `game_date: null` rather than refusing, so without this line
                # the operator running the importer on draft morning would see
                # six pending Cup games and no indication that one of them
                # cannot be placed in a week. The nightly live smoke catches it
                # too, but a day later and only on `main`.
                "pending_game_ids_without_a_date": list(self.pending_game_ids_without_a_date),
                # Which of three causes, per game. `not_offered` means the
                # source has not committed to a date and the right response is
                # to wait; `unreadable` means it gave one we could not parse,
                # and the right response is to investigate. Reporting only the
                # ids would tell an operator to wait in a case where they
                # should be looking at the payload.
                "pending_game_date_absence": dict(self.pending_game_date_absence),
                "first_game_date": self.first_game_date,
                "last_game_date": self.last_game_date,
                "teams_created": self.teams_created,
                "teams_updated": self.teams_updated,
                "schedule_rows_created": self.schedule_created,
                "schedule_rows_updated": self.schedule_updated,
            },
            indent=2,
        )


def fetch_and_parse(
    client: NbaStatsClient, *, season: str, max_age_hours: float
) -> ScheduleParseResult:
    """One throttled, cached request, parsed. No writes."""

    payload = client.schedule_league(season=season, max_age=timedelta(hours=max_age_hours))
    return parse_schedule(payload, season=season)


def summarise(parsed: ScheduleParseResult, *, dry_run: bool) -> ScheduleImportSummary:
    dates = sorted(record.game.game_date for record in parsed.games)
    labels = sorted(
        {
            " ".join(part for part in (game.game_label, game.game_sub_label) if part)
            or game.game_subtype
            or "(unlabelled)"
            for game in parsed.pending_games
        }
    )
    return ScheduleImportSummary(
        season=parsed.season,
        source_game_count=parsed.source_game_count,
        resolved_game_count=len(parsed.games),
        pending_game_ids=parsed.pending_game_ids,
        pending_game_labels=tuple(labels),
        # One filter, deriving both fields. An earlier version computed the
        # count from `game_date is None` and the detail from a non-empty
        # reason -- two predicates the lineage reader enforces as equivalent
        # but which nothing enforced here, so a mismatch would have printed
        # "3 game(s) carry no usable date" beside two listed ids.
        pending_game_date_absence=(
            absence := tuple(
                (game.nba_game_id, game.date_absence_reason)
                for game in parsed.pending_games
                if game.game_date is None
            )
        ),
        pending_game_ids_without_a_date=tuple(game_id for game_id, _ in absence),
        first_game_date=dates[0].isoformat() if dates else "",
        last_game_date=dates[-1].isoformat() if dates else "",
        dry_run=dry_run,
    )


def import_season_schedule(
    database: Database, parsed: ScheduleParseResult, *, client: NbaStatsClient
) -> ScheduleImportSummary:
    """Import teams then the schedule, in one transaction.

    Teams first, and unconditionally: ``import_schedule`` refuses a cohort
    referencing an NBA team the database does not hold, so against a fresh
    database a schedule-only command would always fail and always for a reason
    the operator then has to go and fix by hand. The team list is the packaged
    static one, so this adds no request and no throttle wait.
    """

    summary = summarise(parsed, dry_run=False)
    with database.session() as session:
        teams = import_teams(session, parse_teams(client.static_teams()))
        schedule = import_schedule(session, parsed)
    return ScheduleImportSummary(
        season=summary.season,
        source_game_count=summary.source_game_count,
        resolved_game_count=summary.resolved_game_count,
        pending_game_ids=summary.pending_game_ids,
        pending_game_labels=summary.pending_game_labels,
        pending_game_ids_without_a_date=summary.pending_game_ids_without_a_date,
        pending_game_date_absence=summary.pending_game_date_absence,
        first_game_date=summary.first_game_date,
        last_game_date=summary.last_game_date,
        dry_run=False,
        teams_created=teams.created,
        teams_updated=teams.updated,
        schedule_created=schedule.created,
        schedule_updated=schedule.updated,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hoops_gm.ingest.schedule_import",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("season", help="season in NBA form, e.g. 2026-27")
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=DEFAULT_MAX_AGE_HOURS,
        help=(
            "reuse a capture younger than this instead of requesting. "
            f"Default {DEFAULT_MAX_AGE_HOURS}h; pass 0 to force a live request."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch, parse and report; write nothing",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    client = NbaStatsClient(store=RawPayloadStore(DEFAULT_RAW_ROOT))
    database: Database | None = None
    try:
        parsed = fetch_and_parse(
            client, season=args.season, max_age_hours=max(args.max_age_hours, 0.0)
        )
        if args.dry_run:
            summary = summarise(parsed, dry_run=True)
        else:
            database = Database.from_settings(get_settings())
            summary = import_season_schedule(database, parsed, client=client)
    except SourceUnavailable as exc:
        print(f"{args.season}: source unavailable after retries: {exc}", file=sys.stderr)
        return EXIT_SOURCE_UNAVAILABLE
    except SourceContractError as exc:
        # Covers both a changed payload shape and a cohort that does not
        # account for every game the source reported. Nothing was written in
        # either case: `import_schedule` runs its writes inside a savepoint and
        # the completeness refusal precedes them.
        print(f"{args.season}: refused, nothing written: {exc}", file=sys.stderr)
        return EXIT_SOURCE_CONTRACT
    except SQLAlchemyError as exc:
        print(f"{args.season}: database error, nothing written: {exc}", file=sys.stderr)
        return EXIT_DATABASE
    finally:
        if database is not None:
            database.dispose()

    print(summary.as_json())
    if summary.pending_game_ids_without_a_date:
        detail = ", ".join(
            f"{game_id} ({why})" for game_id, why in summary.pending_game_date_absence
        )
        print(
            f"\n{len(summary.pending_game_ids_without_a_date)} pending game(s) carry no usable "
            f"date: {detail}. They cannot be attributed to a scoring period until the source "
            "publishes one. 'not_offered' means the source has not committed to a date and "
            "there is nothing to do; 'unreadable' means it published a value this parser could "
            "not read, which is a fault to investigate rather than a decision to wait for.",
            file=sys.stderr,
        )
    if summary.pending_game_ids:
        print(
            f"\n{len(summary.pending_game_ids)} game(s) are published without teams and were "
            "recorded as pending, not imported: "
            f"{', '.join(summary.pending_game_labels)}. Counts for the periods holding them "
            "are provisional and can move either way once the source assigns teams: a drawn "
            "bracket adds games, and a rescheduled fixture moves one out of its week "
            "(ADR-013).",
            file=sys.stderr,
        )
    faults = [
        game_id
        for game_id, why in summary.pending_game_date_absence
        if why in _FAULT_ABSENCE_REASONS
    ]
    if faults:
        print(
            f"\nThe import succeeded, but {len(faults)} pending game(s) carry a date this "
            f"parser treats as a fault rather than an undecided bracket: {', '.join(faults)}. "
            "Investigate the payload before trusting the pending set. Exiting "
            f"{EXIT_IMPORTED_WITH_FAULT} to say so; nothing was rolled back.",
            file=sys.stderr,
        )
        return EXIT_IMPORTED_WITH_FAULT
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
