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

    Checked against the file's own bytes rather than a list of fields somebody
    remembered to add. **Only cells that parse as numbers are exempt**, and only
    because a short number genuinely does collide with a count by coincidence —
    ``60`` appearing in the summary says nothing about the file.

    An earlier version filtered on ``len(cell) > 4`` and justified it as
    excluding short *numeric* cells. It did not do that: a review's census over
    the 12-row demo file found it checked 59 of 138 cells and dropped 79,
    including ``'bam'`` — a real NBA first name, which is precisely the class
    the module docstring promises never reaches stdout. A leak of any name of
    four characters or fewer passed. The filter now matches its own rationale,
    so every name is checked at every length.
    """
    content = demo_csv(seeded)
    path = write_csv(tmp_path, content)
    capsys.readouterr()

    assert main([SEASON, str(path)]) == EXIT_OK

    out = capsys.readouterr().out
    lines = content.decode("utf-8").splitlines()

    def is_number(cell: str) -> bool:
        try:
            float(cell)
        except ValueError:
            return False
        return True

    checked = [
        cell for line in lines[1:] for cell in line.split(",") if cell and not is_number(cell)
    ]
    # The guard is only as good as its population: assert real names are in it,
    # so a future filter change that quietly empties it fails here rather than
    # passing over nothing.
    assert any(len(cell) <= 4 for cell in checked), checked
    assert len(checked) >= 2 * len(lines[1:])

    assert [cell for cell in checked if cell in out] == []


def test_the_source_choices_are_derived_from_the_registry_rather_than_hand_maintained(
    capsys: pytest.CaptureFixture[str], seeded: Database, tmp_path: Path
) -> None:
    """What the derivation actually buys, and what it does not.

    An earlier version of this test was named ``…are_exactly_the_sources_that
    _can_write_production`` and asserted set equality against **the identical
    expression the implementation uses**. It could only fail if someone
    hardcoded the list, and it could not distinguish "can write production" from
    "has a profile" — which is what its name claimed. R55's agreeing check.

    Two separate properties, established separately:

    * the offered set excludes identity-anchor namespaces, checked against the
      enum rather than against the implementation's own expression;
    * ``fantasypros`` is offered **and cannot write production**, driven through
      ``main`` — which is the fact the old name denied.
    """
    from hoops_gm.db.models.enums import ExternalSource

    action = next(
        action for action in build_parser()._actions if "--source" in action.option_strings
    )
    choices = set(action.choices or ())

    assert action.default == ExternalSource.BASKETBALL_MONSTER.value
    # Independent of `_SOURCE_CHOICES`' own derivation: no anchor namespace.
    assert ExternalSource.NBA.value not in choices
    assert ExternalSource.FANTRAX.value not in choices

    # And the half the old name got wrong: an offered source that always refuses.
    assert "fantasypros" in choices
    path = write_csv(tmp_path, demo_csv(seeded))
    capsys.readouterr()
    assert main([SEASON, str(path), "--source", "fantasypros"]) == EXIT_REFUSED
    assert "not verified" in capsys.readouterr().err


@pytest.mark.parametrize(
    "bad",
    ["2026-2027", "2026", "26-27", "2026-28", "2026_27", "../../pwned", ""],
    ids=[
        "four-digit-end",
        "no-end",
        "short-start",
        "non-consecutive",
        "underscore",
        "traversal",
        "empty",
    ],
)
def test_a_season_that_is_not_an_nba_season_is_rejected_before_anything_runs(
    bad: str, tmp_path: Path
) -> None:
    """Nothing downstream constrains ``season``, so the parser has to.

    ``parse_projection_csv`` discards it, and the only other check is membership
    in a profile's ``verified_seasons`` — which ``MANUAL_PROFILE`` satisfies with
    a wildcard. So under ``--source manual`` any string was accepted, written to
    ``projection_imports.season``, and interpolated into the report filename
    beside a ``mkdir(parents=True)``.

    A review drove ``season="../../pwned"`` and watched the report land a
    directory above ``--report-dir``, creating a literal ``manual-..`` directory
    on the way. Not a privilege boundary — the operator's own machine, his own
    argument — but the mundane half is worse in practice: a typo'd ``2026-2027``
    imported successfully, exited 0, and produced a cohort keyed to a season no
    reader would ever query.
    """
    path = write_csv(tmp_path, b"player_id,last_name\nx,y\n")

    with pytest.raises(SystemExit) as exit_info:
        main([bad, str(path), "--source", "manual"])

    assert exit_info.value.code == 2  # argparse's own usage-error code


def test_the_report_path_cannot_escape_the_report_dir(seeded: Database, tmp_path: Path) -> None:
    """The traversal half, pinned at the place it was reproduced.

    Complements the parametrized rejection above: that one proves argparse
    refuses, this one proves nothing outside ``--report-dir`` is ever created
    for an accepted season.
    """
    rows = demo_csv(seeded).decode("utf-8").splitlines()
    fields = rows[1].split(",")
    fields[1], fields[2] = "Nonexistentsurname", "Nobody"
    mutated = "\n".join([rows[0], ",".join(fields), *rows[2:]]) + "\n"
    path = write_csv(tmp_path, mutated.encode("utf-8"))
    reports = tmp_path / "reports"

    assert main([SEASON, str(path), "--report-dir", str(reports)]) == EXIT_IMPORTED_INCOMPLETE

    written = [p for p in tmp_path.rglob("*.csv") if p != path]
    assert written == [reports / f"basketball_monster-{SEASON}-unresolved.csv"], written


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


def test_a_source_the_importer_would_reject_as_a_namespace_is_never_offered() -> None:
    """The one thing the derivation genuinely buys, checked against the enum.

    ``nba`` and ``fantrax`` are identity-anchor namespaces; ``import_projection_csv``
    rejects them outright as "not a projection CSV source". Asserted against
    ``ExternalSource`` rather than against ``_SOURCE_CHOICES``' own expression,
    so this cannot become the agreeing check its predecessor was.
    """
    from hoops_gm.db.models.enums import ExternalSource

    action = next(
        action for action in build_parser()._actions if "--source" in action.option_strings
    )
    choices = set(action.choices or ())

    assert choices
    assert ExternalSource.NBA.value not in choices
    assert ExternalSource.FANTRAX.value not in choices
