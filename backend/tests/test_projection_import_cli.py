"""The operator command that imports a projection CSV from disk.

Every test drives ``main`` or the module's own functions rather than
reimplementing them: the thing under test is a command someone runs at a
terminal, and a test that reconstructs its steps proves only that the
reconstruction works.

The cohort these tests import against is built by
``hoops_gm.dev.seed_projections.build_demo_csv`` from canonical players, for the
same reason the seed does it that way — resolution then succeeds by
construction, so a test asserting an exit code is asserting the exit code rather
than the resolver's luck on a hand-written name.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import func, select

from hoops_gm.core.config import Settings
from hoops_gm.db.models.identity import PlayerExternalId
from hoops_gm.db.models.projections import Projection, ProjectionImport
from hoops_gm.db.session import Database
from hoops_gm.dev.seed_projections import (
    PLAYERS_FIXTURE,
    POSITIONS_FIXTURE,
    SEEDED_AT,
    build_demo_csv,
    unique_named_players,
)
from hoops_gm.dev.seed_schedule_grid import DEFAULT_FIXTURES_DIR, load_fixture
from hoops_gm.ingest.importers import import_nba_players, import_player_positions
from hoops_gm.ingest.nba.parsers import parse_common_all_players, parse_player_index
from hoops_gm.ingest.projections.import_csv import (
    EXIT_DATABASE,
    EXIT_IMPORTED_INCOMPLETE,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_UNREADABLE_FILE,
    build_parser,
    main,
)

SEASON = "2026-27"
COHORT = 12


@pytest.fixture
def seeded(
    database: Database, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> Iterator[Database]:
    """A database holding canonical players, with ``get_settings`` pointed at it.

    The command takes no ``--database-url``, so pointing it at the throwaway
    database is done the only way an operator could: through ``Settings``.
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
    monkeypatch.setattr("hoops_gm.ingest.projections.import_csv.get_settings", lambda: settings)
    yield database


def demo_csv(database: Database, *, limit: int = COHORT) -> bytes:
    with database.session() as session:
        return build_demo_csv(unique_named_players(session, limit=limit))


def write_csv(tmp_path: Path, content: bytes, name: str = "projections.csv") -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def row_counts(database: Database) -> tuple[int, int, int]:
    """``(projections, projection_imports, basketball-monster crosswalk links)``."""
    with database.session() as session:
        return (
            session.scalar(select(func.count()).select_from(Projection)) or 0,
            session.scalar(select(func.count()).select_from(ProjectionImport)) or 0,
            session.scalar(
                select(func.count())
                .select_from(PlayerExternalId)
                .where(PlayerExternalId.source == "basketball_monster")
            )
            or 0,
        )


def test_the_command_exposes_no_database_url_option() -> None:
    """The leak class is removed, not re-guarded, and this is what keeps it removed.

    Two defects in this repository leaked a credential through a
    ``--database-url`` flag: one printed it verbatim, and one leaked libpq's
    ``password`` query argument past ``render_as_string(hide_password=True)``,
    which masks ``URL.password`` and nothing else. This command reads
    ``Settings`` instead, so there is no URL in ``argv`` to print. A future edit
    that reintroduces the convenience flag reintroduces the class, and fails
    here.
    """
    options = {option for action in build_parser()._actions for option in action.option_strings}

    assert not any("database" in option or "url" in option for option in options), options
    assert options == {
        "-h",
        "--help",
        "--source",
        "--display-name",
        "--scoring-type",
        "--report-dir",
        "--dry-run",
    }


def test_it_imports_a_cohort_and_reports_it(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(tmp_path, demo_csv(seeded))
    capsys.readouterr()

    assert main([SEASON, str(path), "--report-dir", str(tmp_path / "reports")]) == EXIT_OK

    body = json.loads(capsys.readouterr().out)
    assert body["dry_run"] is False
    assert body["import_created"] is True
    assert body["total_rows"] == COHORT
    assert body["identities_accepted"] == COHORT
    assert body["projections_created"] == COHORT
    assert body["rows_not_in_cohort"] == 0
    assert body["unresolved_report"] is None

    projections, imports, _ = row_counts(seeded)
    assert (projections, imports) == (COHORT, 1)


def test_a_dry_run_reports_the_real_match_count_and_writes_nothing(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The rollback is asserted against three tables, not against the context manager.

    A dry run does the *real* import — identity resolution included, which is
    the number an operator actually wants — and discards it. That makes the
    rollback load-bearing rather than incidental, so it is checked by counting
    rows in every table the import writes: ``projections``,
    ``projection_imports`` and the ``player_external_ids`` links the crosswalk
    reconciliation writes. Trusting the ``with`` block would be the
    empty-verifier defect.
    """
    path = write_csv(tmp_path, demo_csv(seeded))
    before = row_counts(seeded)
    capsys.readouterr()

    assert main([SEASON, str(path), "--dry-run"]) == EXIT_OK

    body = json.loads(capsys.readouterr().out)
    assert body["dry_run"] is True
    # The preview is not a parse-only preview: it reports the resolution the
    # real import would perform.
    assert body["identities_accepted"] == COHORT
    assert body["projections_created"] == COHORT

    assert row_counts(seeded) == before == (0, 0, 0)


def test_a_dry_run_refuses_an_unverified_profile_exactly_as_a_real_run_does(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A green dry run must not promise an import that then refuses.

    FantasyPros' profile is a parse-preview example with no source evidence, so
    it may not write production. If ``--dry-run`` relaxed verification the
    rehearsal would pass and the performance would fail, which is the one thing
    a rehearsal must not do.
    """
    path = write_csv(tmp_path, demo_csv(seeded))

    for argv in (
        [SEASON, str(path), "--source", "fantasypros"],
        [SEASON, str(path), "--source", "fantasypros", "--dry-run"],
    ):
        capsys.readouterr()
        assert main(argv) == EXIT_REFUSED
        assert "not verified" in capsys.readouterr().err

    assert row_counts(seeded) == (0, 0, 0)


def test_bytes_that_are_not_utf8_are_refused_and_nothing_is_written(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(tmp_path, b"player_id,last_name\n\xff\xfe,Bad\n")
    capsys.readouterr()

    assert main([SEASON, str(path)]) == EXIT_REFUSED

    assert "UTF-8" in capsys.readouterr().err
    assert row_counts(seeded) == (0, 0, 0)


def test_a_missing_file_names_the_path_and_does_not_reach_the_database(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A separate code from a refusal, because it is a different mistake.

    Exit 2 means the file was read and rejected; exit 3 means there was no file
    to read. Collapsing them would tell someone who mistyped a path to go and
    look at their CSV.
    """
    missing = tmp_path / "not-here.csv"
    capsys.readouterr()

    assert main([SEASON, str(missing)]) == EXIT_UNREADABLE_FILE

    assert str(missing) in capsys.readouterr().err
    assert row_counts(seeded) == (0, 0, 0)


def test_unresolved_rows_exit_five_and_are_written_to_a_report(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 0 on a partial load is the failure this code exists to prevent.

    One row is renamed to somebody who is not in the crosswalk, so the file has
    twelve rows and the cohort has eleven. Reporting success there is the
    confident, plausible, wrong result the whole project is built around
    avoiding.
    """
    rows = demo_csv(seeded).decode("utf-8").splitlines()
    header, first, rest = rows[0], rows[1], rows[2:]
    fields = first.split(",")
    fields[1], fields[2] = "Nonexistentsurname", "Nobody"
    mutated = "\n".join([header, ",".join(fields), *rest]) + "\n"
    path = write_csv(tmp_path, mutated.encode("utf-8"))
    reports = tmp_path / "reports"
    capsys.readouterr()

    assert main([SEASON, str(path), "--report-dir", str(reports)]) == EXIT_IMPORTED_INCOMPLETE

    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["total_rows"] == COHORT
    assert body["identities_accepted"] == COHORT - 1
    assert body["rows_not_in_cohort"] == 1
    assert body["rejected_rows"] == 0

    report = reports / f"basketball_monster-{SEASON}-unresolved.csv"
    assert report.is_file()
    assert "Nobody" in report.read_text(encoding="utf-8")
    # The operator is told where to look without piping stdout through a reader.
    assert str(report) in captured.err

    projections, _, _ = row_counts(seeded)
    assert projections == COHORT - 1


def test_no_report_file_is_written_when_everything_resolved(
    seeded: Database, tmp_path: Path
) -> None:
    """An empty report reads as "the report is there and it is fine".

    That is the same shape as a check reporting success on no data at all, so
    the file is absent rather than empty when there is nothing to adjudicate.
    """
    path = write_csv(tmp_path, demo_csv(seeded))
    reports = tmp_path / "reports"

    assert main([SEASON, str(path), "--report-dir", str(reports)]) == EXIT_OK

    assert not (reports / f"basketball_monster-{SEASON}-unresolved.csv").exists()


def test_re_running_the_same_file_converges_rather_than_minting_a_version(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_csv(tmp_path, demo_csv(seeded))

    capsys.readouterr()
    assert main([SEASON, str(path)]) == EXIT_OK
    first = json.loads(capsys.readouterr().out)

    assert main([SEASON, str(path)]) == EXIT_OK
    second = json.loads(capsys.readouterr().out)

    assert first["import_created"] is True
    assert second["import_created"] is False
    assert first["content_sha256"] == second["content_sha256"]
    assert row_counts(seeded)[:2] == (COHORT, 1)


def test_no_value_from_the_file_reaches_stdout(
    seeded: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The export is paid content, and a terminal scrollback is a paste away.

    Checked against the file's own bytes rather than against a list of fields
    somebody remembered to add: every cell of every data row must be absent
    from stdout. The identifiers that *are* printed — the content hash, the
    profile id, the filename — are not values from inside the file.
    """
    content = demo_csv(seeded)
    path = write_csv(tmp_path, content)
    capsys.readouterr()

    assert main([SEASON, str(path)]) == EXIT_OK

    out = capsys.readouterr().out
    lines = content.decode("utf-8").splitlines()
    leaked = [
        cell
        for line in lines[1:]
        for cell in line.split(",")
        # Short numeric cells collide with counts by coincidence rather than by
        # leaking; a name or a long decimal appearing in stdout does not.
        if len(cell) > 4 and cell in out
    ]
    assert leaked == []


def test_a_database_failure_is_reported_as_one_and_writes_nothing(
    seeded: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A refusal about the database must not read as a refusal about the file."""
    from sqlalchemy.exc import OperationalError

    path = write_csv(tmp_path, demo_csv(seeded))

    def explode(*args: object, **kwargs: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection lost"))

    monkeypatch.setattr("hoops_gm.ingest.projections.import_csv.import_projection_csv", explode)
    capsys.readouterr()

    assert main([SEASON, str(path)]) == EXIT_DATABASE

    assert "database error" in capsys.readouterr().err
    assert row_counts(seeded) == (0, 0, 0)


def test_the_source_choices_are_exactly_the_sources_that_can_write_production() -> None:
    """The offered set is derived, so it cannot drift into offering a refusal.

    ``--source`` is built from ``PROJECTION_IMPORT_SOURCES`` intersected with
    the profiles registry, which is the same pair of conditions
    ``import_projection_csv`` enforces. A hand-maintained list would eventually
    offer an identity-anchor namespace that the importer then rejects as "not a
    projection CSV source" — a command offering an option that cannot work.
    """
    from hoops_gm.ingest.projections.profiles import PROFILES_BY_SOURCE, PROJECTION_IMPORT_SOURCES

    action = next(
        action for action in build_parser()._actions if "--source" in action.option_strings
    )

    assert set(action.choices or ()) == {
        source.value for source in PROJECTION_IMPORT_SOURCES if source in PROFILES_BY_SOURCE
    }
    assert action.default == "basketball_monster"
