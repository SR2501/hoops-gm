"""The operator command that loads a real season's forward schedule.

Every test drives ``main`` or the module's own functions rather than
reimplementing them, because the thing under test is a command an operator
runs at a terminal, and a test that reconstructs its steps proves only that
the reconstruction works.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from hoops_gm.core.config import Settings
from hoops_gm.db.base import Base
from hoops_gm.db.models.identity import NbaTeam
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.db.session import Database
from hoops_gm.ingest.nba.client import NbaStatsClient
from hoops_gm.ingest.schedule_import import (
    EXIT_DATABASE,
    EXIT_OK,
    EXIT_SOURCE_CONTRACT,
    EXIT_SOURCE_UNAVAILABLE,
    build_parser,
    fetch_and_parse,
    import_season_schedule,
    main,
    summarise,
)

pytestmark = pytest.mark.adapter_contract

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PENDING_FIXTURE = "nba_scheduleleaguev2_2026_27_pending_knockout.json"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_client(payload: Any) -> NbaStatsClient:
    """A client whose transport returns a recorded payload, with no store.

    ``store=None`` so nothing is read from or written to ``data/raw`` during
    the suite, and the throttle never sleeps because ``endpoint_factory``
    returns immediately.
    """

    class Endpoint:
        def get_dict(self) -> Any:
            return payload

    return NbaStatsClient(endpoint_factory=lambda endpoint, **kwargs: Endpoint())


def failing_client(exc: Exception) -> NbaStatsClient:
    def factory(endpoint: str, **kwargs: Any) -> Any:
        raise exc

    return NbaStatsClient(
        endpoint_factory=factory,
        retry_policy=_no_retry(),
    )


def _no_retry() -> Any:
    from hoops_gm.ingest.retry import RetryPolicy

    return RetryPolicy(attempts=1)


@pytest.fixture
def prepared(database: Database) -> Iterator[Database]:
    """A schema-built throwaway database the command can write into."""
    yield database


def test_the_command_exposes_no_database_url_option() -> None:
    """The leak class is removed, not re-guarded, and this is what keeps it removed.

    Two defects in this repository leaked a credential through a
    ``--database-url`` flag: one printed it verbatim, and one leaked libpq's
    ``password`` query argument past ``render_as_string(hide_password=True)``,
    which masks ``URL.password`` and nothing else. This command reads
    ``Settings`` instead, so there is no URL in ``argv`` to print. A future
    edit that reintroduces the convenience flag reintroduces the class, and
    fails here.
    """
    options = {option for action in build_parser()._actions for option in action.option_strings}

    assert not any("database" in option or "url" in option for option in options), options
    assert options == {"-h", "--help", "--max-age-hours", "--dry-run"}


def test_dry_run_reports_the_real_cohort_and_writes_nothing(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A dry run must not be able to touch a database even if one is configured."""
    monkeypatch.setattr(
        "hoops_gm.ingest.schedule_import.NbaStatsClient",
        lambda **kwargs: fixture_client(load(PENDING_FIXTURE)),
    )

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a dry run must not construct a Database")

    monkeypatch.setattr("hoops_gm.ingest.schedule_import.Database.from_settings", refuse)
    capsys.readouterr()

    assert main(["2026-27", "--dry-run"]) == EXIT_OK

    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["dry_run"] is True
    assert body["source_game_count"] == 24
    assert body["resolved_game_count"] == 18
    assert body["pending_game_count"] == 6
    assert body["pending_game_ids"] == [
        "0022601201",
        "0022601202",
        "0022601203",
        "0022601204",
        "0022601229",
        "0022601230",
    ]
    assert body["pending_game_labels"] == [
        "Emirates NBA Cup Quarterfinal",
        "Emirates NBA Cup Semifinal",
    ]
    assert body["pending_game_ids_without_a_date"] == []
    assert body["first_game_date"] == "2026-10-20"
    assert body["last_game_date"] == "2027-04-11"
    assert body["teams_created"] == 0
    assert body["schedule_rows_created"] == 0
    # The pending set is named on stderr too, because the operator has to see
    # it without piping stdout through a JSON reader.
    assert "Emirates NBA Cup Quarterfinal" in captured.err


def test_an_undated_pending_game_is_reported_to_the_operator(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The signal an operator needs at the moment of use, not a day later.

    A pending game whose date does not reconcile is recorded with no date
    rather than refusing the season. Without this line the operator running
    the importer on draft morning would see six pending Cup games and no
    indication that one of them cannot be placed in a week — the only signal
    would be the nightly live smoke, a day later and only on `main`.
    """
    payload = load(PENDING_FIXTURE)
    mutated = 0
    for game_date in payload["leagueSchedule"]["gameDates"]:
        for game in game_date["games"]:
            if game["gameId"] == "0022601229":
                game["gameDateTimeEst"] = "2026-12-08T00:30:00Z"
                mutated += 1
    assert mutated == 1

    monkeypatch.setattr(
        "hoops_gm.ingest.schedule_import.NbaStatsClient",
        lambda **kwargs: fixture_client(payload),
    )
    capsys.readouterr()

    assert main(["2026-27", "--dry-run"]) == EXIT_OK

    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["pending_game_count"] == 6, "the season survived the bad date"
    assert body["resolved_game_count"] == 18
    assert body["pending_game_ids_without_a_date"] == ["0022601229"]
    assert "carry no usable date" in captured.err
    assert "0022601229" in captured.err


def test_import_writes_teams_then_the_schedule_and_records_pending(prepared: Database) -> None:
    """Teams are imported unconditionally so a fresh database is not a dead end.

    ``import_schedule`` refuses a cohort referencing an NBA team the database
    does not hold, so a schedule-only command against an empty database would
    always fail, and always for a reason the operator then has to go and fix
    by hand.
    """
    client = fixture_client(load(PENDING_FIXTURE))
    parsed = fetch_and_parse(client, season="2026-27", max_age_hours=0.0)

    summary = import_season_schedule(prepared, parsed, client=client)

    assert summary.dry_run is False
    assert summary.teams_created == 30
    assert summary.source_game_count == 24
    assert summary.resolved_game_count == 18
    assert len(summary.pending_game_ids) == 6
    with prepared.session() as session:
        rows = session.scalars(select(TeamScheduleEntry)).all()
    assert len(rows) == 36, "two team_schedule rows per resolved game, none for pending"


def test_a_source_that_contradicts_its_contract_exits_two_and_writes_nothing(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reproduces the refusal an operator will actually hit: a named team with no id.

    Driven end to end against a real schema-built database, with the real
    ``import_season_schedule``. An earlier version of this test stubbed the
    import out and raised the exception itself, which proved only that the
    handler catches what the test threw — the producer played by the test,
    which is the shape this repository has repeatedly been caught by.
    """
    payload = load(PENDING_FIXTURE)
    mutated = 0
    for game_date in payload["leagueSchedule"]["gameDates"]:
        for game in game_date["games"]:
            if game["gameId"] == "0022601229":
                game["homeTeam"]["teamTricode"] = "LAL"
                mutated += 1
    assert mutated == 1

    monkeypatch.setattr(
        "hoops_gm.ingest.schedule_import.NbaStatsClient",
        lambda **kwargs: fixture_client(payload),
    )
    url = f"sqlite:///{(tmp_path / 'refused.db').as_posix()}"
    settings = Settings(environment="development", database_url=url, _env_file=None)
    monkeypatch.setattr("hoops_gm.ingest.schedule_import.get_settings", lambda: settings)
    built = Database.from_settings(settings)
    try:
        Base.metadata.create_all(built.engine)
    finally:
        built.dispose()
    capsys.readouterr()

    assert main(["2026-27"]) == EXIT_SOURCE_CONTRACT

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refused, nothing written" in captured.err
    assert "named but did not identify" in captured.err

    verify = Database.from_settings(settings)
    try:
        with verify.session() as session:
            assert session.scalars(select(TeamScheduleEntry)).all() == []
            assert session.scalars(select(NbaGame)).all() == []
            # Teams are written FIRST in that transaction, so this is the table
            # a leak would show in. The earlier version of this test checked
            # only the two written later, which is the wrong end of the
            # rollback to look at.
            assert session.scalars(select(NbaTeam)).all() == []
    finally:
        verify.dispose()


def test_an_unreachable_source_exits_three(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Distinct from a contract failure: retrying later could work."""
    monkeypatch.setattr(
        "hoops_gm.ingest.schedule_import.NbaStatsClient",
        lambda **kwargs: failing_client(ConnectionError("no route to host")),
    )
    capsys.readouterr()

    assert main(["2026-27", "--dry-run"]) == EXIT_SOURCE_UNAVAILABLE

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "source unavailable after retries" in captured.err


def test_a_database_error_exits_four(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A missing schema is not the source's fault and must not be reported as such."""
    monkeypatch.setattr(
        "hoops_gm.ingest.schedule_import.NbaStatsClient",
        lambda **kwargs: fixture_client(load(PENDING_FIXTURE)),
    )
    url = f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    monkeypatch.setattr(
        "hoops_gm.ingest.schedule_import.get_settings",
        lambda: Settings(environment="development", database_url=url, _env_file=None),
    )
    capsys.readouterr()

    assert main(["2026-27"]) == EXIT_DATABASE

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "database error, nothing written" in captured.err


def test_the_summary_never_prints_anything_resembling_a_connection_url() -> None:
    """The whole point of dropping the flag, asserted on the artefact operators read."""
    client = fixture_client(load(PENDING_FIXTURE))
    parsed = fetch_and_parse(client, season="2026-27", max_age_hours=0.0)

    rendered = summarise(parsed, dry_run=True).as_json()

    for marker in ("://", "password", "sslpassword", "@"):
        assert marker not in rendered, f"{marker!r} appears in the operator summary"


def test_the_client_is_asked_for_the_season_the_operator_named() -> None:
    """A season typo must reach the endpoint, not be silently defaulted."""
    calls: list[dict[str, Any]] = []

    class Endpoint:
        def get_dict(self) -> Any:
            return {"leagueSchedule": {"seasonYear": "2026-27", "gameDates": []}}

    def factory(endpoint: str, **kwargs: Any) -> Endpoint:
        calls.append({"endpoint": endpoint, **kwargs})
        return Endpoint()

    fetch_and_parse(NbaStatsClient(endpoint_factory=factory), season="2026-27", max_age_hours=0.0)

    assert calls == [
        {
            "endpoint": "ScheduleLeagueV2",
            "timeout": 60.0,
            "league_id": "00",
            "season": "2026-27",
        }
    ]
