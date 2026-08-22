"""The operator command that imports a published auction-value table.

Every test drives ``main`` rather than reassembling its steps. A test that
reconstructs a command's internals proves the reconstruction works, and this
command had **zero** statements executed by any test before this file existed —
a hundred and twenty-four lines that were green because nothing entered them.

The cohort is seeded from the same canonical NBA fixtures the projection CLI
tests use, so an assertion about an exit code is an assertion about the exit
code rather than about the resolver's luck with a hand-written name.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Table, func, select

from hoops_gm.core.config import Settings
from hoops_gm.db.models.market import (
    AuctionValueImport,
    AuctionValueSource,
    PublishedAuctionValue,
)
from hoops_gm.db.session import Database
from hoops_gm.dev.seed_projections import (
    PLAYERS_FIXTURE,
    POSITIONS_FIXTURE,
    SEEDED_AT,
    unique_named_players,
)
from hoops_gm.dev.seed_schedule_grid import DEFAULT_FIXTURES_DIR, load_fixture
from hoops_gm.ingest.auction_values.import_csv import (
    EXIT_DATABASE,
    EXIT_IMPORTED_NOT_BENCHMARKABLE,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_UNREADABLE_FILE,
    build_parser,
    main,
)
from hoops_gm.ingest.importers import import_nba_players, import_player_positions
from hoops_gm.ingest.nba.parsers import parse_common_all_players, parse_player_index

SEASON = "2026-27"
AS_OF = "2026-08-21"
COHORT = 12


@pytest.fixture
def seeded(
    database: Database, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> Iterator[Database]:
    """Canonical players, with ``get_settings`` pointed at the throwaway database.

    The command takes no ``--database-url`` — deliberately, since that flag
    leaked a credential twice in this repository — so this is the only route an
    operator has, and therefore the only honest route for a test.
    """
    with database.session() as session:
        import_nba_players(
            session, parse_common_all_players(load_fixture(DEFAULT_FIXTURES_DIR, PLAYERS_FIXTURE))
        )
        import_player_positions(
            session,
            parse_player_index(
                load_fixture(DEFAULT_FIXTURES_DIR, POSITIONS_FIXTURE), season=SEASON
            ),
            observed_at=SEEDED_AT,
        )
    monkeypatch.setattr("hoops_gm.ingest.auction_values.import_csv.get_settings", lambda: settings)
    yield database


def cohort_csv(database: Database, *, limit: int = COHORT) -> bytes:
    """A manual-profile table naming players that really exist in this database.

    Built from the seeded cohort for the same reason the projection CLI tests
    build theirs that way: otherwise an exit code of 5 could mean "the guard
    fired" or "the names were spelled wrong", and the test could not tell.
    """
    with database.session() as session:
        players = unique_named_players(session, limit=limit)
        assert players, "no canonical players seeded, so this file would resolve nothing"
        lines = ["Player,Value"]
        lines.extend(f"{player.full_name},${20 + index}" for index, player in enumerate(players))
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_csv(tmp_path: Path, content: bytes, name: str = "auction.csv") -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def base_argv(csv_path: Path, tmp_path: Path) -> list[str]:
    """A fully stated basis. Individual tests override one field at a time."""
    return [
        "manual-auction-values",
        SEASON,
        AS_OF,
        str(csv_path),
        "--budget",
        "200",
        "--budget-evidence",
        "stated",
        "--teams",
        "12",
        "--teams-evidence",
        "stated",
        "--roster",
        "13",
        "--roster-evidence",
        "stated",
        "--scoring",
        "h2h_categories",
        "--scoring-evidence",
        "stated",
        "--categories",
        "9",
        "--categories-evidence",
        "stated",
        "--report-dir",
        str(tmp_path / "reports"),
    ]


def counts(database: Database) -> tuple[int, int, int]:
    """``(sources, imports, published values)``."""
    with database.session() as session:
        return (
            session.scalar(select(func.count()).select_from(AuctionValueSource)) or 0,
            session.scalar(select(func.count()).select_from(AuctionValueImport)) or 0,
            session.scalar(select(func.count()).select_from(PublishedAuctionValue)) or 0,
        )


# --------------------------------------------------------------------------
# The argument surface itself
# --------------------------------------------------------------------------


def test_every_basis_evidence_flag_is_required() -> None:
    """Not "has a sensible default". Required.

    The parser is the outermost place an assumed basis could enter, and an
    assumed basis is what makes two incomparable numbers look comparable.
    """
    parser = build_parser()
    required = {
        action.dest for action in parser._actions if action.required and action.option_strings
    }
    assert required == {
        "budget_evidence",
        "teams_evidence",
        "roster_evidence",
        "scoring_evidence",
        "categories_evidence",
    }


def test_the_command_exposes_no_database_url_flag() -> None:
    """The class of defect removed rather than guarded."""
    options = {opt for action in build_parser()._actions for opt in action.option_strings}
    assert not any("database" in opt or "dsn" in opt or "url" in opt for opt in options)


def test_an_unknown_profile_is_rejected_by_the_parser(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["not-a-profile", SEASON, AS_OF, str(tmp_path / "x.csv")])


# --------------------------------------------------------------------------
# Refusals, before anything is written
# --------------------------------------------------------------------------


def test_a_non_iso_as_of_date_is_refused(seeded: Database, tmp_path: Path) -> None:
    path = write_csv(tmp_path, cohort_csv(seeded))
    argv = base_argv(path, tmp_path)
    argv[2] = "21 August 2026"

    assert main(argv) == EXIT_REFUSED
    assert counts(seeded) == (0, 0, 0)


def test_a_value_given_alongside_unestablished_evidence_is_refused(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ "I do not know" and "$200" are not both true at once."""
    path = write_csv(tmp_path, cohort_csv(seeded))
    argv = base_argv(path, tmp_path)
    argv[argv.index("--budget-evidence") + 1] = "unestablished"

    assert main(argv) == EXIT_REFUSED
    assert "omit the value" in capsys.readouterr().err
    assert counts(seeded) == (0, 0, 0)


def test_evidence_without_a_value_is_refused(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(tmp_path, cohort_csv(seeded))
    argv = base_argv(path, tmp_path)
    del argv[argv.index("--budget") : argv.index("--budget") + 2]

    assert main(argv) == EXIT_REFUSED
    assert "There is no default" in capsys.readouterr().err
    assert counts(seeded) == (0, 0, 0)


def test_an_inferred_basis_without_a_note_is_refused(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(tmp_path, cohort_csv(seeded))
    argv = base_argv(path, tmp_path)
    argv[argv.index("--teams-evidence") + 1] = "inferred"

    assert main(argv) == EXIT_REFUSED
    assert "requires a note" in capsys.readouterr().err


def test_a_non_numeric_budget_is_refused(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(tmp_path, cohort_csv(seeded))
    argv = base_argv(path, tmp_path)
    argv[argv.index("--budget") + 1] = "two hundred"

    assert main(argv) == EXIT_REFUSED
    assert "not a decimal amount" in capsys.readouterr().err


def test_a_missing_file_is_reported_as_unreadable(seeded: Database, tmp_path: Path) -> None:
    assert main(base_argv(tmp_path / "absent.csv", tmp_path)) == EXIT_UNREADABLE_FILE
    assert counts(seeded) == (0, 0, 0)


def test_a_file_with_no_value_column_is_refused_without_writing(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(tmp_path, b"Player,Team\nSomebody Somewhere,BOS\n")

    assert main(base_argv(path, tmp_path)) == EXIT_REFUSED
    assert "no value column" in capsys.readouterr().err
    assert counts(seeded) == (0, 0, 0)


# --------------------------------------------------------------------------
# The successful path, and the path that succeeds but is not benchmarkable
# --------------------------------------------------------------------------


def test_a_clean_import_of_an_independent_source_exits_zero(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(tmp_path, cohort_csv(seeded))

    assert main(base_argv(path, tmp_path)) == EXIT_OK

    sources, imports, values = counts(seeded)
    assert (sources, imports, values) == (1, 1, COHORT)
    out = capsys.readouterr().out
    assert "admissible as independent market evidence" in out
    assert "NOT admissible" not in out


def test_no_row_from_the_file_is_echoed_to_the_terminal(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """These publishers forbid redistribution; a command that prints rows is step one.

    Checked against a player name the file really contains, so this fails if
    someone adds a per-row print — rather than against a literal nobody emits.
    """
    with seeded.session() as session:
        sample_name = unique_named_players(session, limit=1)[0].full_name
    path = write_csv(tmp_path, cohort_csv(seeded))

    assert main(base_argv(path, tmp_path)) == EXIT_OK
    captured = capsys.readouterr()
    assert sample_name not in captured.out
    assert sample_name not in captured.err


def test_an_unestablished_basis_imports_but_exits_five_with_its_reason(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 5 is not a failed import. The rows are on record and queryable.

    What it reports is that this list cannot be used to measure our
    disagreement against, and it prints why — a refusal whose cause is unclear
    is the one that gets loosened.
    """
    path = write_csv(tmp_path, cohort_csv(seeded))
    argv = base_argv(path, tmp_path)
    argv[argv.index("--budget-evidence") + 1] = "unestablished"
    del argv[argv.index("--budget") : argv.index("--budget") + 2]

    assert main(argv) == EXIT_IMPORTED_NOT_BENCHMARKABLE

    sources, imports, values = counts(seeded)
    assert (sources, imports, values) == (1, 1, COHORT), "exit 5 must still have imported"
    out = capsys.readouterr().out
    assert "NOT admissible as independent market evidence" in out
    assert "basis_unestablished" in out
    assert "basis_budget" in out


def test_unresolved_names_exit_five_and_are_written_to_a_report_not_printed(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The cohort is smaller than the file, so the benchmark is partial.

    The unresolved names go to a gitignored report because they are source
    content; the terminal gets a count and a path.
    """
    payload = cohort_csv(seeded) + b"Nonexistent Playerperson,$15\n"
    path = write_csv(tmp_path, payload)

    assert main(base_argv(path, tmp_path)) == EXIT_IMPORTED_NOT_BENCHMARKABLE

    captured = capsys.readouterr()
    assert "Nonexistent Playerperson" not in captured.out

    reports = list((tmp_path / "reports").glob("*-unresolved.csv"))
    assert len(reports) == 1
    report_text = reports[0].read_text(encoding="utf-8")
    assert "source_player_name,bucket,reason" in report_text
    assert "Nonexistent Playerperson" in report_text

    _, _, values = counts(seeded)
    assert values == COHORT, "the unresolvable row must not have been imported"


def test_no_report_is_written_when_every_name_resolved(seeded: Database, tmp_path: Path) -> None:
    """The negative half. Otherwise "a report exists" proves nothing."""
    path = write_csv(tmp_path, cohort_csv(seeded))

    assert main(base_argv(path, tmp_path)) == EXIT_OK
    assert not (tmp_path / "reports").exists()


def test_dry_run_resolves_against_the_database_and_writes_nothing(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not a parse-only preview.

    The number that decides whether an import is usable is how many players
    resolved, and resolution needs a database — so the dry run does the real
    work and throws it away.
    """
    path = write_csv(tmp_path, cohort_csv(seeded))

    assert main([*base_argv(path, tmp_path), "--dry-run"]) == EXIT_OK

    out = capsys.readouterr().out
    assert "dry run: rolled back, nothing written" in out
    assert f"players matched   : {COHORT}" in out
    assert counts(seeded) == (0, 0, 0)


def test_reimporting_the_same_file_converges(seeded: Database, tmp_path: Path) -> None:
    path = write_csv(tmp_path, cohort_csv(seeded))

    assert main(base_argv(path, tmp_path)) == EXIT_OK
    assert main(base_argv(path, tmp_path)) == EXIT_OK
    assert counts(seeded) == (1, 1, COHORT)


def test_a_database_failure_is_reported_without_leaking_its_message(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ``except SQLAlchemyError`` handler, proved to be reachable.

    Before this test the handler was green and unentered — three lines no test
    walked into, which says nothing whatever about whether they work. A passing
    suite around an unreached branch is the sharpest form of the empty-check
    failure, because reading the code does not reveal it.

    Driven by dropping the table the importer writes to, which is a real
    schema-drift failure rather than a patched exception. Only the exception
    *type* is printed: a driver message can carry the connection string.
    """
    path = write_csv(tmp_path, cohort_csv(seeded))
    values_table = PublishedAuctionValue.__table__
    assert isinstance(values_table, Table)
    values_table.drop(seeded.engine)

    assert main(base_argv(path, tmp_path)) == EXIT_DATABASE

    captured = capsys.readouterr()
    assert "database refused the write" in captured.err
    assert "published_auction_values" not in captured.err, (
        "the handler must report the exception type, not the driver's message"
    )
