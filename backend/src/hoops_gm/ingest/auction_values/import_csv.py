"""Import one published auction-value table from disk — the operator entry point.

    cd backend
    python -m hoops_gm.ingest.auction_values.import_csv \\
        hashtag-auction-values 2026-27 2026-08-21 hashtag.csv \\
        --budget 200 --budget-evidence stated \\
        --teams 12 --teams-evidence stated \\
        --roster 13 --roster-evidence stated \\
        --scoring h2h_categories --scoring-evidence stated \\
        --categories 9 --categories-evidence stated \\
        --dry-run

## Why it takes no ``--database-url``

Same reason ``ingest/projections/import_csv.py`` does not: two separate defects
in this repository leaked a credential through exactly that flag. Guarding it
failed twice; removing it removes the class.
:class:`~hoops_gm.core.config.Settings` supplies the URL.

## Why nothing from the file is printed

Every source in this set forbids redistribution of its content, and a command
that echoes rows into a terminal is the first step to them arriving somewhere
they should not. The summary is counts, identifiers and digests. The
unresolved-name report carries source names and is written under gitignored
``data/`` rather than printed.

## The basis flags are mandatory and there is no default

This is the whole point of the unit. A $200 budget and a $260 budget produce
different dollars for the same player and both look like money; an 8-category
value and a 9-category value are different quantities that share a
:class:`ScoringType`. Anything that makes two incomparable numbers look
comparable is the defect being designed against, so:

* every basis field needs a value **and** an evidence grade;
* ``unestablished`` is a legitimate answer and requires the value to be
  omitted — it is an investigated absence, which is evidence, not a blank;
* ``inferred`` requires ``--basis-note`` saying what it was inferred from.

Nothing here converts a foreign basis to ours. Proportional scaling and
scaling only the surplus above the per-slot reserve give materially different
dollars for the same player, and choosing between them is a modelling decision
a number then rests on. It belongs to ``auction-values`` under the Model gate.

## ``--dry-run`` runs the real import and rolls back

Not a parse-only preview: the number that decides whether an import is usable
is how many players resolved, and resolution needs a database.

## Exit codes

``0`` imported, every parsed value written, and the source is admissible as
independent market evidence. ``2`` refused — unknown profile, bad encoding,
unusable parse, or an incomplete basis; nothing written. ``3`` the file could
not be read from disk. ``4`` the database refused the write. ``5``
**imported, but not usable as an independent benchmark** — either the cohort
is smaller than the file, or the circularity guard refuses the source, or the
basis is unestablished.

``5`` is not a failure of the import. The rows are on record and queryable;
what it says is that this source cannot be used to measure our disagreement
against. Printing the reason is the point — a refusal whose cause is unclear is
the one that gets loosened.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from sqlalchemy.exc import SQLAlchemyError

from hoops_gm.core.config import get_settings
from hoops_gm.db.models.enums import BasisEvidence, ScoringType
from hoops_gm.db.session import Database
from hoops_gm.ingest.auction_values.importer import (
    AuctionImportOutcome,
    BasisDeclaration,
    BasisIncomplete,
    import_auction_value_csv,
)
from hoops_gm.ingest.auction_values.parser import AuctionValueProfileError
from hoops_gm.ingest.auction_values.profiles import AUCTION_VALUE_PROFILES
from hoops_gm.market.independence import assess_benchmark_admissibility

EXIT_OK: Final = 0
EXIT_REFUSED: Final = 2
EXIT_UNREADABLE_FILE: Final = 3
EXIT_DATABASE: Final = 4
#: Imported, but not usable as an independent benchmark. See the docstring.
EXIT_IMPORTED_NOT_BENCHMARKABLE: Final = 5

DEFAULT_REPORT_DIR: Final = Path("data/reports/auction_values")

_PROFILE_CHOICES: Final = tuple(sorted(p.profile_id for p in AUCTION_VALUE_PROFILES))
_EVIDENCE_CHOICES: Final = tuple(member.value for member in BasisEvidence)
_SCORING_CHOICES: Final = tuple(member.value for member in ScoringType)


def _basis_pair(
    name: str, raw_value: str | None, raw_evidence: str
) -> tuple[str | None, BasisEvidence]:
    evidence = BasisEvidence(raw_evidence)
    if evidence is BasisEvidence.UNESTABLISHED and raw_value is not None:
        raise BasisIncomplete(
            f"--{name} was given a value but --{name}-evidence says unestablished; "
            "omit the value, or say where the value came from"
        )
    if evidence is not BasisEvidence.UNESTABLISHED and raw_value is None:
        raise BasisIncomplete(
            f"--{name} is required when --{name}-evidence is {evidence.value!r}. "
            "There is no default: an assumed basis is the defect this importer exists to stop"
        )
    return raw_value, evidence


def _build_basis(args: argparse.Namespace) -> BasisDeclaration:
    budget_raw, budget_evidence = _basis_pair("budget", args.budget, args.budget_evidence)
    teams_raw, teams_evidence = _basis_pair("teams", args.teams, args.teams_evidence)
    roster_raw, roster_evidence = _basis_pair("roster", args.roster, args.roster_evidence)
    scoring_raw, scoring_evidence = _basis_pair("scoring", args.scoring, args.scoring_evidence)
    categories_raw, categories_evidence = _basis_pair(
        "categories", args.categories, args.categories_evidence
    )

    try:
        budget = Decimal(budget_raw) if budget_raw is not None else None
    except InvalidOperation:
        raise BasisIncomplete(f"--budget {budget_raw!r} is not a decimal amount") from None

    return BasisDeclaration(
        budget=budget,
        budget_evidence=budget_evidence,
        team_count=int(teams_raw) if teams_raw is not None else None,
        team_count_evidence=teams_evidence,
        roster_size=int(roster_raw) if roster_raw is not None else None,
        roster_size_evidence=roster_evidence,
        scoring_type=ScoringType(scoring_raw) if scoring_raw is not None else None,
        scoring_type_evidence=scoring_evidence,
        category_count=int(categories_raw) if categories_raw is not None else None,
        category_count_evidence=categories_evidence,
        note=args.basis_note,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hoops_gm.ingest.auction_values.import_csv",
        description=(
            "Import a published auction-value table into the market layer. Stores what a "
            "source published, with its basis and lineage. Derives nothing."
        ),
    )
    parser.add_argument("profile", choices=_PROFILE_CHOICES, help="which source's table this is")
    parser.add_argument("season", help='season in "2026-27" form')
    parser.add_argument(
        "as_of_date",
        help="the source's own publication date, ISO format. Not the date you downloaded it",
    )
    parser.add_argument("csv_path", type=Path, help="path to the transcribed table")

    basis = parser.add_argument_group(
        "basis",
        "What the published dollars mean. Mandatory, non-defaultable, and each value "
        "paired with how you came to know it.",
    )
    for flag, help_text in (
        ("budget", "auction budget per team the list was built for"),
        ("teams", "number of teams"),
        ("roster", "roster size"),
        ("scoring", "scoring format"),
        ("categories", "number of scoring categories (8-cat and 9-cat are not comparable)"),
    ):
        choices = _SCORING_CHOICES if flag == "scoring" else None
        basis.add_argument(f"--{flag}", choices=choices, help=help_text)
        basis.add_argument(
            f"--{flag}-evidence",
            choices=_EVIDENCE_CHOICES,
            required=True,
            help=(
                f"how the {flag} basis was established. 'unestablished' is a real answer and "
                f"requires --{flag} to be omitted"
            ),
        )
    basis.add_argument(
        "--basis-note",
        help="required whenever any basis field is 'inferred': say what it was inferred from",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "run the real import and roll back. Holds SQLite's write reservation for the "
            "duration, so a concurrent real import will wait"
        ),
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="where the unresolved-name report is written (gitignored data/ by default)",
    )
    return parser


def _write_unresolved_report(
    outcome: AuctionImportOutcome, report_dir: Path, stem: str
) -> Path | None:
    rows = [
        (resolution.source_record.raw_name, bucket, resolution.reason)
        for bucket, resolutions in (
            ("needs_review", outcome.identity_report.needs_review),
            ("unmatched", outcome.identity_report.unmatched),
        )
        for resolution in resolutions
    ]
    if not rows:
        return None
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{stem}-unresolved.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("source_player_name", "bucket", "reason"))
        writer.writerows(rows)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        as_of = date.fromisoformat(args.as_of_date)
    except ValueError:
        print(f"as_of_date {args.as_of_date!r} is not an ISO date", file=sys.stderr)
        return EXIT_REFUSED

    try:
        basis = _build_basis(args)
    except (BasisIncomplete, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    try:
        csv_bytes = args.csv_path.read_bytes()
    except OSError as exc:
        print(f"could not read {args.csv_path}: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE_FILE

    database = Database.from_settings(get_settings())
    try:
        with database.session() as session:
            try:
                outcome = import_auction_value_csv(
                    session,
                    profile_id=args.profile,
                    season=args.season,
                    as_of_date=as_of,
                    csv_bytes=csv_bytes,
                    basis=basis,
                    original_filename=args.csv_path.name,
                )
            except (AuctionValueProfileError, BasisIncomplete, ValueError) as exc:
                session.rollback()
                print(f"refused: {exc}", file=sys.stderr)
                return EXIT_REFUSED

            admissibility = assess_benchmark_admissibility(session, outcome.auction_import)
            report_path = _write_unresolved_report(
                outcome, args.report_dir, f"{args.profile}-{args.season}-{as_of.isoformat()}"
            )

            parsed_values = len(outcome.parsed.rows)
            print(f"source            : {outcome.source_row.slug}")
            print(
                f"profile           : {outcome.auction_import.profile_id} "
                f"v{outcome.auction_import.profile_version}"
            )
            print(f"content sha256    : {outcome.auction_import.content_sha256}")
            print(f"as of             : {outcome.auction_import.as_of_date}")
            print(f"rows in file      : {outcome.auction_import.row_count}")
            print(f"values parsed     : {parsed_values}")
            print(f"values written    : {outcome.values_written}")
            print(f"players matched   : {outcome.auction_import.matched_count}")
            print(f"needs review      : {outcome.auction_import.needs_review_count}")
            print(f"unmatched         : {outcome.auction_import.unmatched_count}")
            print(f"rows rejected     : {outcome.auction_import.rejected_count}")
            if report_path is not None:
                print(f"unresolved report : {report_path}")
            print()
            print(admissibility.explain())

            incomplete = outcome.values_written < parsed_values
            if args.dry_run:
                session.rollback()
                print("\ndry run: rolled back, nothing written")
            if incomplete or not admissibility.admissible:
                return EXIT_IMPORTED_NOT_BENCHMARKABLE
            return EXIT_OK
    except SQLAlchemyError as exc:
        print(f"database refused the write: {type(exc).__name__}", file=sys.stderr)
        return EXIT_DATABASE
    finally:
        # Not housekeeping. Without this the engine's pooled connection is
        # closed by the garbage collector instead, which on SQLite surfaces as
        # an unraisable exception during interpreter or test teardown and
        # leaves the database file locked on Windows.
        database.dispose()


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
