"""Import one projection CSV from disk — the operator entry point.

    cd backend
    python -m hoops_gm.ingest.projections.import_csv 2026-27 bbm-2026-27.csv --dry-run
    python -m hoops_gm.ingest.projections.import_csv 2026-27 bbm-2026-27.csv

Until this existed, :func:`~hoops_gm.ingest.projections.importer.import_projection_csv`
was a library function with no caller outside the test suite. There is no HTTP
write path for projections either — the projections route is read-only by
decision — so the only way the owner's paid Basketball Monster export reached
the database was for someone to write Python at a REPL. The API that serves
this table shipped before anything filled it.

## Why it takes no ``--database-url``

Same reason ``ingest/schedule_import.py`` does not: two separate defects in
this repository leaked a credential through exactly that flag, one printing it
verbatim and one leaking libpq's ``password`` query argument past
``render_as_string(hide_password=True)``. Guarding the flag failed twice;
removing it removes the class. :class:`~hoops_gm.core.config.Settings` supplies
the URL, and ``test_projection_import_cli.py`` asserts the parser still exposes
no such option.

## Why nothing from the file is printed

The Basketball Monster export is paid content. Its rows are deliberately absent
from this repository — only its hashes are committed — and a command that
echoes rows into a terminal is the first step to them arriving in a paste. The
summary is counts, identifiers and digests. No rate, no player name from the
file, and no raw cell value reaches stdout or the log.

The one exception is the unresolved-players report, which is the whole point of
adjudicating a crosswalk: it carries source names, and it is written to a file
under gitignored ``data/`` rather than printed.

## ``--dry-run`` runs the real import and rolls back

Not a parse-only preview. The number that decides whether an import is usable
is *how many players resolved*, and identity resolution needs a database. A
preview computed differently from the real thing is not a rehearsal. So a dry
run opens the transaction, does the whole import, reports it, and rolls back —
which means it holds SQLite's write reservation for its duration and can make a
concurrent real import wait. That is stated in ``--help`` so someone who hits
the wait understands it rather than reporting a hang.

Profile verification is **not** relaxed for a dry run. An unverified profile
refuses in both modes, so a green dry run cannot promise an import that then
refuses.

## ``raw_payload_ref`` is not set, deliberately

:meth:`~hoops_gm.ingest.rawstore.RawPayloadStore.put` hard-codes a
``.json.gz`` filename and models an HTTP capture with an endpoint and request
params. Putting a CSV through it would name a CSV ``.json.gz`` and invent a
request that never happened. The operator's own file is the raw evidence, and
``ProjectionImport.content_sha256`` binds the import to its exact bytes, so the
honest structure is to record no reference and say why here.

## Exit codes

``0`` imported and every row in the file is in the cohort. ``2`` refused —
unverified profile, bad encoding, unreadable file, or a parse that found
nothing usable; nothing written. ``3`` the file could not be read from disk.
``4`` the database refused the write; nothing written. ``5`` **imported, and
the cohort is smaller than the file.**

``5`` exists because the alternative is exit ``0`` on an import where a hundred
players silently failed to match, which is the confident, plausible, wrong
result this project is built around avoiding. Its two causes — rows the parser
rejected, and players the crosswalk could not resolve — imply the same operator
action, *open the report*, which is why they share one code; the printed counts
say which of the two happened.

## ADR-002

The summary prints ``assumed_games_played`` figures only as their own field and
never multiplies one by a rate. That product recovers the source's published
seasonal total, and that fusion belongs at ``expected-games``. The only
arithmetic in this module is ``len()`` and subtraction of counts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sqlalchemy.exc import SQLAlchemyError

from hoops_gm.core.config import get_settings
from hoops_gm.db.models.enums import ExternalSource, ScoringType
from hoops_gm.db.session import Database
from hoops_gm.identity import report as identity_report
from hoops_gm.ingest.projections.importer import (
    ProjectionEncodingError,
    ProjectionImportOutcome,
    import_projection_csv,
)
from hoops_gm.ingest.projections.parser import ProjectionProfileError
from hoops_gm.ingest.projections.profiles import PROFILES_BY_SOURCE, PROJECTION_IMPORT_SOURCES

EXIT_OK: Final = 0
#: The source, the profile or the file's own content was refused. Nothing written.
EXIT_REFUSED: Final = 2
#: The CSV could not be read from disk at all.
EXIT_UNREADABLE_FILE: Final = 3
#: The database refused the write for a reason that is not about the file.
EXIT_DATABASE: Final = 4
#: Imported, and the cohort is smaller than the file. Not a refusal: rows are
#: written and the import is on record. See the module docstring.
EXIT_IMPORTED_INCOMPLETE: Final = 5

#: Where the adjudication CSV lands, under gitignored ``data/``. Mirrors the
#: crosswalk backfill's ``data/reports/unmatched_players.csv``.
DEFAULT_REPORT_DIR: Final = Path("data/reports/projections")

#: Only sources the importer will accept as a *source*. Derived from
#: ``PROJECTION_IMPORT_SOURCES`` intersected with the profiles registry — the
#: same two conditions ``import_projection_csv`` enforces at its top — so this
#: cannot drift into offering an identity-anchor namespace like ``nba`` or
#: ``fantrax``, which the importer rejects outright.
#:
#: **It is deliberately not "sources that can write production", and an earlier
#: comment here said that and was wrong.** The importer has a third condition,
#: ``verified_for_season``, that this set does not mirror: ``fantasypros`` and
#: ``hashtag`` are ``verified=False`` and therefore refuse for *every* season,
#: in both modes. They stay offered because parse-preview against them is a
#: real use and the refusal message is the useful answer; ``--source``'s help
#: text says so.
_SOURCE_CHOICES: Final = tuple(
    sorted(source.value for source in PROJECTION_IMPORT_SOURCES if source in PROFILES_BY_SOURCE)
)

#: NBA season form: four digits, a hyphen, and the last two digits of the
#: following year. ``[0-9]`` rather than ``\d`` because ``\d`` is Unicode-aware
#: and accepted Arabic-Indic digits; used with ``fullmatch`` rather than
#: ``match`` because ``$`` matches *before* a trailing newline, so ``match``
#: accepted ``"2026-27\n"`` and returned it verbatim into
#: ``projection_imports.season``. Both found by driving the validator rather
#: than by reading it.
_SEASON_PATTERN: Final = re.compile(r"([0-9]{4})-([0-9]{2})")


def nba_season(value: str) -> str:
    """Validate a season argument, as an ``argparse`` ``type=``.

    Nothing downstream constrains this string. ``parse_projection_csv`` takes
    ``season`` and immediately discards it, and the only other check is
    membership in a profile's ``verified_seasons`` — which ``MANUAL_PROFILE``
    satisfies with a wildcard, so under ``--source manual`` *any* string was
    accepted.

    That mattered twice. A typo'd ``2026-2027`` imported successfully and exited
    ``0``, producing a cohort keyed to a season no reader would ever query — the
    confident, plausible, wrong result arriving through the operator's fingers
    rather than through the data. And the value is interpolated into the
    unresolved-report filename beside a ``mkdir(parents=True)``, so a review
    drove ``season="../../pwned"`` and watched the report land a directory above
    ``--report-dir``, creating a literal ``manual-..`` directory on the way.

    Not a privilege boundary — it is the operator's own machine and his own
    argument — which is why this is a ``type=`` and not a security control. The
    point is that the sibling ``schedule_import.py`` never builds a path from
    ``season``, so this module is the first to do it and inherits no protection
    from that precedent.
    """

    match = _SEASON_PATTERN.fullmatch(value)
    if match is None:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not an NBA season; expected the form 2026-27"
        )
    start, end = int(match.group(1)), match.group(2)
    if f"{(start + 1) % 100:02d}" != end:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a consecutive NBA season; {start} should be followed by "
            f"{(start + 1) % 100:02d}"
        )
    return value


@dataclass(frozen=True)
class ProjectionImportSummary:
    """What one run parsed and, unless it was a dry run, wrote.

    Deliberately carries no value from the file. Every field is a count, an
    identifier, a digest or a flag.
    """

    season: str
    source: str
    display_name: str
    profile_id: str
    profile_version: str
    content_sha256: str
    original_filename: str
    dry_run: bool
    import_created: bool
    total_rows: int
    rejected_rows: int
    accepted: int
    needs_review: int
    unmatched: int
    warnings: int
    created: int
    updated: int
    skipped: int
    superseded: int
    #: How many rows in the file did not end up as a projection, for either
    #: reason. The two causes are reported separately above; this is the number
    #: exit code 5 turns on.
    rows_not_in_cohort: int
    report_path: str | None

    def as_json(self) -> str:
        return json.dumps(
            {
                "season": self.season,
                "source": self.source,
                "display_name": self.display_name,
                "dry_run": self.dry_run,
                "profile_id": self.profile_id,
                "profile_version": self.profile_version,
                "content_sha256": self.content_sha256,
                "original_filename": self.original_filename,
                "import_created": self.import_created,
                "total_rows": self.total_rows,
                "rejected_rows": self.rejected_rows,
                "identities_accepted": self.accepted,
                "identities_needing_review": self.needs_review,
                "identities_unmatched": self.unmatched,
                "parser_warnings": self.warnings,
                "projections_created": self.created,
                "projections_updated": self.updated,
                "projections_skipped": self.skipped,
                "projections_superseded": self.superseded,
                "rows_not_in_cohort": self.rows_not_in_cohort,
                "unresolved_report": self.report_path,
            },
            indent=2,
        )


def summarise(
    outcome: ProjectionImportOutcome,
    *,
    dry_run: bool,
    original_filename: str,
    report_path: Path | None,
) -> ProjectionImportSummary:
    """Reduce one outcome to counts. Reads no cell value from the file."""

    parsed = outcome.parse_result
    identities = outcome.identity_report
    return ProjectionImportSummary(
        season=outcome.projection_import.season,
        source=outcome.projection_source.source.value,
        display_name=outcome.projection_source.display_name,
        profile_id=outcome.projection_import.profile_id,
        profile_version=outcome.projection_import.profile_version,
        content_sha256=outcome.projection_import.content_sha256,
        original_filename=original_filename,
        dry_run=dry_run,
        import_created=outcome.import_created,
        total_rows=parsed.total_rows,
        rejected_rows=parsed.rejected_count,
        accepted=len(identities.accepted),
        needs_review=len(identities.needs_review),
        unmatched=len(identities.unmatched),
        warnings=len(parsed.warnings),
        created=outcome.counts.created,
        updated=outcome.counts.updated,
        skipped=outcome.counts.skipped,
        superseded=outcome.counts.superseded,
        # Counted against what the *file* declared, never against the rows that
        # survived parsing. A denominator filtered by the condition it is
        # measuring cannot measure it — see R57.
        rows_not_in_cohort=parsed.total_rows - (outcome.counts.created + outcome.counts.updated),
        report_path=str(report_path) if report_path is not None else None,
    )


def write_unresolved_report(
    outcome: ProjectionImportOutcome,
    *,
    report_dir: Path,
    source: ExternalSource,
    season: str,
) -> Path | None:
    """Write the tail a human has to adjudicate, or nothing if there is none.

    Returns the path written, or ``None`` when every source row resolved. An
    empty file would read as "the report is there and it is fine", which is the
    same shape as a check that reports success on no data at all.
    """

    unresolved = [
        *outcome.identity_report.needs_review,
        *outcome.identity_report.unmatched,
    ]
    if not unresolved:
        return None

    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{source.value}-{season}-unresolved.csv"
    path.write_text(identity_report.to_csv(unresolved), encoding="utf-8")
    return path


def run_import(
    database: Database,
    *,
    csv_bytes: bytes,
    source: ExternalSource,
    display_name: str,
    season: str,
    original_filename: str,
    assumed_scoring_type: ScoringType | None,
    report_dir: Path,
    dry_run: bool,
) -> ProjectionImportSummary:
    """Import inside one transaction, rolling back when this is a dry run.

    The dry run does the **real** work and discards it, rather than previewing a
    parse: identity resolution is the part an operator needs to see and it
    cannot happen without a session. The rollback is asserted by a test that
    counts rows in three tables afterwards, not by trusting this context
    manager.
    """

    session = database.session_factory()
    try:
        outcome = import_projection_csv(
            session,
            source=source,
            display_name=display_name,
            season=season,
            csv_bytes=csv_bytes,
            original_filename=original_filename,
            assumed_scoring_type=assumed_scoring_type,
        )
        # The report is written from the in-memory outcome before either
        # branch, so a dry run still hands over the adjudication list it just
        # computed. Nothing about the report depends on the rows persisting.
        report_path = write_unresolved_report(
            outcome,
            report_dir=report_dir,
            source=source,
            season=season,
        )
        summary = summarise(
            outcome,
            dry_run=dry_run,
            original_filename=original_filename,
            report_path=report_path,
        )
        if dry_run:
            session.rollback()
        else:
            session.commit()
        return summary
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hoops_gm.ingest.projections.import_csv",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "season",
        type=nba_season,
        help="season in NBA form, e.g. 2026-27",
    )
    parser.add_argument("csv_path", type=Path, help="path to the projection CSV on disk")
    parser.add_argument(
        "--source",
        choices=_SOURCE_CHOICES,
        default=ExternalSource.BASKETBALL_MONSTER.value,
        help=(
            "which projection publisher this file came from. Default "
            f"{ExternalSource.BASKETBALL_MONSTER.value}. **Not every choice can write "
            "production**: only a profile verified for the requested season may, and "
            "fantasypros and hashtag are unverified examples that refuse for every "
            "season in both modes. They are offered because the refusal is the useful "
            "answer and parse-preview against them is a real use."
        ),
    )
    parser.add_argument(
        "--display-name",
        default=None,
        help="human label for the source row; defaults to the built-in profile's name",
    )
    parser.add_argument(
        "--scoring-type",
        choices=tuple(scoring.value for scoring in ScoringType),
        default=None,
        help=(
            "the scoring format this file's numbers were published for, when the source "
            "states one. Recorded as provenance; nothing computes with it here."
        ),
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help=(
            "where to write the unresolved-players CSV a human adjudicates. "
            f"Default {DEFAULT_REPORT_DIR.as_posix()}/ (gitignored)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "do the real import, report it, and roll back. Identity resolution runs, so the "
            "match counts are the ones a real import would produce. It holds the database "
            "write lock for its duration, so a concurrent real import will wait."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    source = ExternalSource(args.source)
    profile = PROFILES_BY_SOURCE[source]
    display_name = args.display_name or profile.display_name
    scoring_type = ScoringType(args.scoring_type) if args.scoring_type else None

    try:
        csv_bytes = args.csv_path.read_bytes()
    except OSError as exc:
        print(f"{args.csv_path}: could not be read: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE_FILE

    database: Database | None = None
    try:
        database = Database.from_settings(get_settings())
        summary = run_import(
            database,
            csv_bytes=csv_bytes,
            source=source,
            display_name=display_name,
            season=args.season,
            original_filename=args.csv_path.name,
            assumed_scoring_type=scoring_type,
            report_dir=args.report_dir,
            dry_run=args.dry_run,
        )
    except (ProjectionProfileError, ProjectionEncodingError) as exc:
        # Covers an unverified or mismatched profile, a header the profile does
        # not recognise, non-UTF-8 bytes, and a parse that found no usable
        # production row. Nothing was written in any of them: each raises
        # before or inside the transaction `run_import` rolls back.
        #
        # Deliberately not `ValueError`, which is the base of both. The
        # importer raises a bare `ValueError` for a profile/source mismatch and
        # for a source with no built-in profile, and neither is reachable from
        # here — `source` comes from `PROFILES_BY_SOURCE` and no profile is
        # passed. Catching the base class would report a genuine bug anywhere
        # under `import_projection_csv` as "refused, nothing written", which is
        # a reassuring sentence for a reason that is not true.
        print(f"{args.season}: refused, nothing written: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except SQLAlchemyError as exc:
        print(f"{args.season}: database error, nothing written: {exc}", file=sys.stderr)
        return EXIT_DATABASE
    finally:
        if database is not None:
            database.dispose()

    print(summary.as_json())

    if summary.warnings:
        print(
            f"\n{summary.warnings} parser warning(s). The rows were imported; something about "
            "them deserves a look — most often a percentage-only column that could not be "
            "volume-weighted, or a makes/attempts pair that does not reconcile with a "
            "published percentage.",
            file=sys.stderr,
        )

    if summary.report_path is not None:
        print(
            f"\n{summary.needs_review + summary.unmatched} source row(s) did not resolve to a "
            f"player and are listed in {summary.report_path}. Ambiguous rows are printed first "
            "there because they are the dangerous ones: a wrong match produces confident, "
            "plausible, wrong numbers everywhere downstream.",
            file=sys.stderr,
        )

    if summary.rows_not_in_cohort:
        print(
            f"\n{summary.rows_not_in_cohort} of {summary.total_rows} row(s) in the file are not "
            f"in the imported cohort: {summary.rejected_rows} were rejected by the parser and "
            f"{summary.needs_review + summary.unmatched} did not resolve to a player. The "
            f"import is on record either way. Exiting {EXIT_IMPORTED_INCOMPLETE} to say the "
            "cohort is smaller than the file rather than reporting success on a partial load.",
            file=sys.stderr,
        )
        return EXIT_IMPORTED_INCOMPLETE
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
