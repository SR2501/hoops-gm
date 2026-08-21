"""The projections API: one operational proof, and one test per refusal.

The shape of this file follows ``test_schedule_grid_api.py``, and for the same
reason. Every piece of database state the success path reads —
``projection_sources``, ``projection_profile_versions``, ``projection_imports``,
``projections`` and ``source_games_played_assumptions``, with all of their
fingerprints and audit counts — is written by the production writer
``import_projection_csv`` from the committed Basketball Monster fixture, and
never by this file. Refusal tests then start from that same genuinely valid
state and break exactly one thing, so a 409 is evidence that the broken thing
caused it rather than evidence the endpoint was never reachable at all.

**One deliberate deviation, stated rather than glossed.** ``players`` are seeded
by a local helper, not by ``import_nba_players``. The committed Basketball
Monster fixture is a privacy-safe synthetic derivative naming two synthetic
players, so no real NBA roster fixture can contain them, and writing a
substitute CSV naming real players would replace the one file whose column
mapping carries verified evidence. The helper mirrors what ``import_nba_players``
produces and matches ``test_projection_importer.py``'s. Players are an input to
the crosswalk rather than anything this endpoint verifies.

**Two guards here cannot be reached through the route and are driven anyway.**
The currency guard and the cohort-cardinality guard both sit behind a lock that
is supposed to make them impossible, which is exactly why an assertion that they
work is worthless until something has made them fire. Each is driven by a
mutation that reproduces the failure it exists to catch: a selector that
disagrees with the canonical definition of "current", and a row load that
returns fewer rows than the release digested.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Session

from hoops_gm.api.routes import projections as projections_route
from hoops_gm.api.routes.projections import (
    ProjectionRates,
    _projection_players,
    _source_lock_statement,
)
from hoops_gm.app import create_app
from hoops_gm.core.config import Settings
from hoops_gm.db.base import Base
from hoops_gm.db.models.enums import ExternalSource, FieldEvidence, MatchMethod
from hoops_gm.db.models.identity import NbaTeam, Player, PlayerExternalId
from hoops_gm.db.models.league import League
from hoops_gm.db.models.projections import Projection, ProjectionImport
from hoops_gm.identity.names import normalize_name
from hoops_gm.ingest.projections import CANONICAL_STAT_FIELDS, import_projection_csv

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "projections"
#: ``postgresql.dialect`` is untyped in SQLAlchemy's stubs. Built once here so
#: the annotation lives in one place rather than at every compile site.
POSTGRES_DIALECT: Dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
BBM_FIXTURE = "basketball_monster_sample.csv"
SEASON = "2026-27"
PROJECTIONS_URL = "/api/v1/leagues/{league_id}/projections/current"

#: The two synthetic players the committed Basketball Monster fixture names, in
#: the "Last,First" order its header declares.
FIXTURE_PLAYERS = ("Player Alpha", "Player Gamma")


def _error_of(response: Any) -> str:
    code: str = response.json()["error"]
    return code


def load_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def seed_player(
    session: Session,
    *,
    nba_id: int,
    name: str,
    team_abbreviation: str,
    position: str,
) -> Player:
    """A canonical player with an NBA crosswalk link.

    Mirrors what ``import_nba_players`` produces, kept minimal for the reason in
    the module docstring.
    """

    team = session.scalar(select(NbaTeam).where(NbaTeam.abbreviation == team_abbreviation))
    if team is None:
        team = NbaTeam(
            nba_team_id=1000 + nba_id,
            abbreviation=team_abbreviation,
            name=f"{team_abbreviation} Team",
        )
        session.add(team)
        session.flush()
    player = Player(
        full_name=name,
        normalized_name=normalize_name(name).key,
        primary_position=position,
        current_team_id=team.id,
    )
    session.add(player)
    session.flush()
    session.add(
        PlayerExternalId(
            player_id=player.id,
            source=ExternalSource.NBA,
            current_for_source=ExternalSource.NBA.value,
            external_id=str(nba_id),
            external_name=name,
            normalized_name=normalize_name(name).key,
            external_team=team_abbreviation,
            confidence=1.0,
            match_method=MatchMethod.ANCHOR_ID,
            name_evidence=FieldEvidence.AGREE,
        )
    )
    session.flush()
    return player


def _seed_league(session: Session, *, season: str = SEASON) -> int:
    league = League(
        name="Projections League",
        season=season,
        fantrax_league_id=f"projections-{season}",
        scoring_type="h2h_categories",
        draft_type="auction",
    )
    session.add(league)
    session.flush()
    return league.id


def _seed_fixture_players(session: Session) -> None:
    seed_player(session, nba_id=1, name="Player Alpha", team_abbreviation="BOS", position="SF")
    seed_player(session, nba_id=3, name="Player Gamma", team_abbreviation="DEN", position="C")


def _import_bbm(session: Session, *, season: str = SEASON, csv_bytes: bytes | None = None) -> int:
    outcome = import_projection_csv(
        session,
        source=ExternalSource.BASKETBALL_MONSTER,
        display_name="Basketball Monster",
        season=season,
        csv_bytes=csv_bytes if csv_bytes is not None else load_bytes(BBM_FIXTURE),
        original_filename=BBM_FIXTURE,
    )
    return outcome.projection_import.id


def _seed(app: FastAPI) -> int:
    """Bring the app's database to a genuinely servable state; return the league id."""

    with app.state.database.session() as session:
        league_id = _seed_league(session)
        _seed_fixture_players(session)
        _import_bbm(session)
        return league_id


@pytest.fixture
def seeded(app: FastAPI, client: TestClient) -> int:
    """A seeded database behind a live client.

    ``client`` is requested before seeding: its fixture drops and recreates the
    schema, so seeding first would be silently erased.
    """

    return _seed(app)


def _development_app(tmp_path: Path, test_database_url: str | None) -> FastAPI:
    """An app outside ``environment="test"``, on whichever database CI is using.

    ``require_loopback_host``'s escape hatch is keyed on the test environment,
    so the 403 path can only be reached from an app configured as
    ``development``.
    """

    return create_app(
        Settings(
            environment="development",
            database_url=test_database_url or f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
            bridge_secret_path=tmp_path / "bridge_secret",
            _env_file=None,
        )
    )


# --------------------------------------------------------------------------
# The operational proof
# --------------------------------------------------------------------------


def test_current_projections_serves_the_imported_cohort_with_its_lineage(
    client: TestClient, seeded: int
) -> None:
    """A real 200 over state the production importer wrote."""

    response = client.get(PROJECTIONS_URL.format(league_id=seeded))

    assert response.status_code == 200
    body = response.json()
    assert body["league_id"] == seeded
    assert body["season"] == SEASON
    assert body["source"] == "basketball_monster"

    lineage = body["lineage"]["projection_import"]
    assert lineage["source"] == "basketball_monster"
    assert lineage["season"] == SEASON
    assert lineage["profile_id"] == "basketball-monster-2026-27"
    assert lineage["profile_version"] == "1"
    assert lineage["original_filename"] == BBM_FIXTURE
    assert lineage["projection_count"] == 2
    assert (lineage["row_count"], lineage["matched_count"], lineage["rejected_count"]) == (2, 2, 0)
    assert (lineage["needs_review_count"], lineage["unmatched_count"]) == (0, 0)
    for digest in ("content_sha256", "profile_definition_sha256", "projection_values_sha256"):
        assert len(lineage[digest]) == 64

    assert [player["full_name"] for player in body["players"]] == list(FIXTURE_PLAYERS)
    assert [player["team_abbreviation"] for player in body["players"]] == ["BOS", "DEN"]
    assert [player["primary_position"] for player in body["players"]] == ["SF", "C"]

    alpha = body["projections"][0]
    assert alpha["minutes_per_game"] == pytest.approx(2415 / 70)
    assert alpha["field_goals_made_per_game"] == pytest.approx(602 / 70)
    assert alpha["field_goals_attempted_per_game"] == pytest.approx(1225 / 70)
    assert alpha["rebounds_per_game"] == pytest.approx((70 + 427) / 70)


def test_a_two_hundred_guarantees_its_own_density_invariant(
    client: TestClient, seeded: int
) -> None:
    """The two things the response model promises on any 200, asserted rather than assumed."""

    body = client.get(PROJECTIONS_URL.format(league_id=seeded)).json()

    player_ids = [player["player_id"] for player in body["players"]]
    rate_ids = [rates["player_id"] for rates in body["projections"]]
    assert player_ids == sorted(player_ids)
    assert rate_ids == player_ids
    assert len(set(rate_ids)) == len(rate_ids)
    assert len(body["projections"]) == body["lineage"]["projection_import"]["projection_count"]


def test_the_source_games_played_assumption_stays_out_of_every_rate_object(
    client: TestClient, seeded: int
) -> None:
    """ADR-002's separation, kept in the wire format and not only in the schema.

    The Basketball Monster fixture publishes a ``games`` column, so the
    assumption genuinely exists here — a version of this test against a source
    that published none would pass while proving nothing.
    """

    body = client.get(PROJECTIONS_URL.format(league_id=seeded)).json()

    claims = body["source_games_played_assumptions"]
    assert [claim["player_id"] for claim in claims] == [
        player["player_id"] for player in body["players"]
    ]
    assert [claim["assumed_games_played"] for claim in claims] == [70.0, 78.0]
    assert [claim["assumed_games_played_raw"] for claim in claims] == ["70", "78"]

    forbidden = {
        "games",
        "games_played",
        "assumed_games_played",
        "expected_games",
        "rank",
        "aav",
        "value",
        "composite_value",
        "z_score",
        "g_score",
    }
    for rates in body["projections"]:
        assert forbidden.isdisjoint(rates)
    assert forbidden.isdisjoint(body)


def test_the_response_carries_exactly_the_canonical_per_game_fields(
    client: TestClient, seeded: int
) -> None:
    """A field added to the schema and the profile registry cannot be missing here.

    The same parity discipline ``test_projection_importer.py`` applies between
    ``CANONICAL_STAT_FIELDS`` and the ``projections`` table, extended to the
    wire format so the API cannot silently stop publishing a category.
    """

    model_fields = set(ProjectionRates.model_fields) - {"player_id"}
    assert model_fields == set(CANONICAL_STAT_FIELDS)

    body = client.get(PROJECTIONS_URL.format(league_id=seeded)).json()
    for rates in body["projections"]:
        assert set(rates) == set(CANONICAL_STAT_FIELDS) | {"player_id"}


def test_blend_lineage_is_an_explicit_null_rather_than_an_absent_key(
    client: TestClient, seeded: int
) -> None:
    """Nothing persists a blend, so the response says so instead of omitting it."""

    body = client.get(PROJECTIONS_URL.format(league_id=seeded)).json()

    assert "blend" in body["lineage"]
    assert body["lineage"]["blend"] is None


# --------------------------------------------------------------------------
# Refusals reachable end to end
# --------------------------------------------------------------------------


def test_a_non_local_caller_is_refused(tmp_path: Path, test_database_url: str | None) -> None:
    app = _development_app(tmp_path, test_database_url)
    with TestClient(app, client=("203.0.113.7", 51234)) as client:
        Base.metadata.drop_all(app.state.database.engine)
        Base.metadata.create_all(app.state.database.engine)
        league_id = _seed(app)

        response = client.get(PROJECTIONS_URL.format(league_id=league_id))

    assert response.status_code == 403
    assert _error_of(response) == "projections_local_only"
    assert "projections" not in response.json()


def test_a_genuine_loopback_peer_outside_the_test_environment_is_served(
    tmp_path: Path, test_database_url: str | None
) -> None:
    app = _development_app(tmp_path, test_database_url)
    with TestClient(app, client=("127.0.0.1", 5173)) as client:
        Base.metadata.drop_all(app.state.database.engine)
        Base.metadata.create_all(app.state.database.engine)
        league_id = _seed(app)

        response = client.get(PROJECTIONS_URL.format(league_id=league_id))

    assert response.status_code == 200
    assert len(response.json()["projections"]) == 2


def test_an_unknown_league_is_refused(client: TestClient) -> None:
    response = client.get(PROJECTIONS_URL.format(league_id=999999))

    assert response.status_code == 404
    assert _error_of(response) == "projections_league_not_found"


def test_an_identity_anchor_namespace_is_not_a_projection_source(
    client: TestClient, seeded: int
) -> None:
    """``nba`` is a valid ``ExternalSource`` and passes FastAPI validation.

    It is not a projection publisher, so the narrower membership question has to
    be asked by the route and answered with its own code — otherwise the caller
    gets ``projections_source_not_imported`` and goes looking for a CSV to
    import that could never exist.
    """

    response = client.get(
        PROJECTIONS_URL.format(league_id=seeded), params={"source": ExternalSource.NBA.value}
    )

    assert response.status_code == 400
    assert _error_of(response) == "projections_source_unsupported"


def test_an_unknown_source_value_is_a_validation_error(client: TestClient, seeded: int) -> None:
    response = client.get(PROJECTIONS_URL.format(league_id=seeded), params={"source": "espn"})

    assert response.status_code == 422
    assert _error_of(response) == "validation_error"


def test_a_source_that_was_never_registered_is_refused(client: TestClient, seeded: int) -> None:
    """Basketball Monster is imported; FantasyPros has never been."""

    response = client.get(
        PROJECTIONS_URL.format(league_id=seeded),
        params={"source": ExternalSource.FANTASYPROS.value},
    )

    assert response.status_code == 409
    assert _error_of(response) == "projections_source_not_imported"


def test_a_season_with_no_import_is_refused(app: FastAPI, client: TestClient) -> None:
    """The source is registered and has rows — for another season."""

    with app.state.database.session() as session:
        _seed_fixture_players(session)
        _import_bbm(session)
        other_league_id = _seed_league(session, season="2027-28")

    response = client.get(PROJECTIONS_URL.format(league_id=other_league_id))

    assert response.status_code == 409
    assert _error_of(response) == "projections_source_not_imported"


def test_an_import_that_matched_nobody_is_refused(app: FastAPI, client: TestClient) -> None:
    """A real CSV whose every row failed identity resolution.

    Reachable without breaking anything: the file parses, the import row is
    written with its full lineage, and ``projections`` stays empty because no
    canonical player matches. The fix is in the crosswalk, not the file, and the
    code has to say so distinguishably from a malformed import.
    """

    unmatched_csv = (
        load_bytes(BBM_FIXTURE)
        .replace(b"Alpha,Player", b"Nobody,Nameless")
        .replace(b"Gamma,Player", b"Absent,Nameless")
    )
    with app.state.database.session() as session:
        league_id = _seed_league(session)
        import_id = _import_bbm(session, csv_bytes=unmatched_csv)
        assert (
            session.scalar(select(Projection).where(Projection.projection_import_id == import_id))
            is None
        )

    response = client.get(PROJECTIONS_URL.format(league_id=league_id))

    assert response.status_code == 409
    assert _error_of(response) == "projections_incomplete"


def test_an_import_whose_profile_lost_its_verification_is_refused(
    app: FastAPI, client: TestClient, seeded: int
) -> None:
    """Seed a genuinely servable cohort, then break exactly one thing."""

    assert client.get(PROJECTIONS_URL.format(league_id=seeded)).status_code == 200

    with app.state.database.session() as session:
        session.execute(update(ProjectionImport).values(profile_verified=False))

    response = client.get(PROJECTIONS_URL.format(league_id=seeded))

    assert response.status_code == 409
    assert _error_of(response) == "projections_incomplete_evidence"


def test_an_import_whose_stored_rate_went_negative_is_refused(
    app: FastAPI, client: TestClient, seeded: int
) -> None:
    """The same code, reached by a different member of its family.

    Worth driving separately: this is what makes ``projections_incomplete_evidence``
    a family rather than a single fact, and it is why the route tells consumers
    not to render one fixed sentence for it.
    """

    assert client.get(PROJECTIONS_URL.format(league_id=seeded)).status_code == 200

    with app.state.database.session() as session:
        session.execute(update(Projection).values(assists_per_game=-1.0))

    response = client.get(PROJECTIONS_URL.format(league_id=seeded))

    assert response.status_code == 409
    assert _error_of(response) == "projections_incomplete_evidence"


# --------------------------------------------------------------------------
# Guards the lock is supposed to make unreachable, driven by mutation
# --------------------------------------------------------------------------


def test_a_selector_that_disagrees_with_canonical_currency_is_refused(
    app: FastAPI,
    client: TestClient,
    seeded: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure: this route proposing an import the pipeline considers superseded.

    Reproduced rather than reasoned about. A second, newer import is created by
    the production writer, then the route's *selector* is mutated to keep
    proposing the older one — exactly the drift that would follow if the
    canonical definition of "current" changed underneath it. The canonical
    release is the arbiter and must refuse.
    """

    with app.state.database.session() as session:
        superseded_id = session.scalar(select(ProjectionImport.id))
        assert superseded_id is not None
        newer_id = _import_bbm(
            session,
            csv_bytes=load_bytes(BBM_FIXTURE).replace(b",2415,", b",2400,"),
        )
        assert newer_id != superseded_id

    # Unmutated, the route agrees with canonical currency and serves the newer import.
    body = client.get(PROJECTIONS_URL.format(league_id=seeded)).json()
    assert body["lineage"]["projection_import"]["import_id"] == newer_id

    monkeypatch.setattr(
        projections_route,
        "_current_import_candidate",
        lambda session, *, source_id, season: superseded_id,
    )
    response = client.get(PROJECTIONS_URL.format(league_id=seeded))

    assert response.status_code == 409
    assert _error_of(response) == "projections_not_current"
    assert "projections" not in response.json()


def test_a_row_cohort_shorter_than_the_release_is_refused(
    client: TestClient, seeded: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure: a body whose rates are not the rows the lineage block describes.

    Reproduced by mutating the row load to drop one row after the canonical
    release has already digested two. Without the guard this returns 200 with
    ``projection_count: 2`` beside a single player's rates — a success-shaped
    partial answer, which is the one thing this endpoint promises never to give.
    """

    unmutated = projections_route._projection_rows
    assert len(client.get(PROJECTIONS_URL.format(league_id=seeded)).json()["projections"]) == 2

    monkeypatch.setattr(
        projections_route,
        "_projection_rows",
        lambda session, *, import_id: unmutated(session, import_id=import_id)[:-1],
    )
    response = client.get(PROJECTIONS_URL.format(league_id=seeded))

    assert response.status_code == 409
    assert _error_of(response) == "projections_inconsistent_cohort"
    assert "2" in response.json()["detail"] and "1" in response.json()["detail"]


def test_an_unlabelled_player_is_refused_rather_than_rendered_blank(session: Session) -> None:
    """Driven against the helper, because a foreign key makes the route path unreachable.

    A short label list would render as unlabelled rows. Asserting the guard
    exists is worthless until something has made it fire, and only a hand-built
    ``Projection`` pointing at a player id with no row can.
    """

    orphan = Projection(projection_import_id=1, player_id=424242, season=SEASON)

    with pytest.raises(HTTPException) as refusal:
        _projection_players(session, [orphan])

    assert refusal.value.status_code == 409
    assert (refusal.value.headers or {})["X-Bridge-Error"] == "projections_inconsistent_cohort"
    assert "424242" in str(refusal.value.detail)


# --------------------------------------------------------------------------
# Locking
# --------------------------------------------------------------------------


def test_the_read_locks_the_row_the_importer_locks_first() -> None:
    """The lock is the importer's own, compiled where it is actually visible.

    ``import_projection_csv`` takes ``projection_sources`` ``FOR UPDATE`` before
    anything else; this read takes the same row and nothing after it, so its
    lock order is a strict prefix of the writer's and the two cannot deadlock.
    Compiled against PostgreSQL because SQLite never emits the clause — a test
    that only ran the statement on SQLite would pass with
    ``.with_for_update()`` deleted.
    """

    compiled = str(
        _source_lock_statement(ExternalSource.BASKETBALL_MONSTER).compile(dialect=POSTGRES_DIALECT)
    )

    assert "FROM projection_sources" in compiled
    assert compiled.rstrip().endswith("FOR UPDATE")


@pytest.fixture
def locked_rows() -> Iterator[list[str]]:
    """The table each row-locking statement targets, in execution order.

    Hooked at the ORM level and compiled against PostgreSQL *inside the
    listener*, rather than reading the SQL the local dialect happened to emit.
    That is the whole point: SQLite silently drops ``FOR UPDATE``, so a capture
    taken after dialect compilation would record an empty list on the
    development database and pass every ordering assertion vacuously — the
    "green while asking an adjacent question" failure this repository keeps
    finding. Compiling the *statement* makes the check mean the same thing on
    both dialects and lets it run everywhere.

    Targets rather than whole statements, because the importer locks its source
    row by ``id`` while this read locks it by ``source``. Comparing SQL text
    would compare predicates, which is not what "lock order" means.
    """

    captured: list[str] = []

    def record(state: Any) -> None:
        try:
            compiled = str(state.statement.compile(dialect=POSTGRES_DIALECT))
        except Exception:  # pragma: no cover - non-compilable statement, not a lock
            return
        if "FOR UPDATE" not in compiled.upper():
            return
        match = re.search(r"\bFROM\s+(\w+)", compiled, flags=re.IGNORECASE)
        captured.append(match.group(1) if match else compiled)

    event.listen(Session, "do_orm_execute", record)
    try:
        yield captured
    finally:
        event.remove(Session, "do_orm_execute", record)


def test_the_executed_lock_order_is_a_prefix_of_the_importers(
    app: FastAPI, client: TestClient, locked_rows: list[str]
) -> None:
    """Driven, not enumerated.

    The static version of this claim is the one the schedule-grid lane found to
    be wrong: an ordering does not exist until two functions are composed at
    runtime, and a 44-site enumeration declared an ABBA deadlock impossible
    while it was already there. So both paths are executed and their emitted
    lock sequences are compared.

    A prefix is the strongest ordering property available here and it is what
    makes deadlock impossible rather than unlikely: this read never asks for a
    lock the importer has not already taken, so there is no pair to invert.
    """

    with app.state.database.session() as session:
        league_id = _seed_league(session)
        _seed_fixture_players(session)
        _import_bbm(session)
    importer_locks = list(locked_rows)
    locked_rows.clear()

    assert client.get(PROJECTIONS_URL.format(league_id=league_id)).status_code == 200
    reader_locks = list(locked_rows)

    assert importer_locks[:2] == ["projection_sources", "projection_imports"]
    assert reader_locks == ["projection_sources"]
    assert importer_locks[: len(reader_locks)] == reader_locks


def test_a_concurrent_import_never_yields_an_untyped_failure(
    app: FastAPI, client: TestClient
) -> None:
    """Both paths run at once on whichever dialect the suite is using.

    Asserts the pair does not deadlock and that the reader either serves a
    self-consistent cohort or refuses with a documented code — never a 500, and
    never a body whose rates disagree with the count in its own lineage block.
    """

    with app.state.database.session() as session:
        league_id = _seed_league(session)
        _seed_fixture_players(session)
        _import_bbm(session)

    barrier = Barrier(2)

    def reader() -> Any:
        barrier.wait()
        return client.get(PROJECTIONS_URL.format(league_id=league_id))

    def writer() -> None:
        worker = app.state.database.session_factory()
        try:
            barrier.wait()
            _import_bbm(worker, csv_bytes=load_bytes(BBM_FIXTURE).replace(b",2415,", b",2390,"))
            worker.commit()
        finally:
            worker.rollback()
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        read_future = executor.submit(reader)
        write_future = executor.submit(writer)
        write_future.result(timeout=60)
        response = read_future.result(timeout=60)

    assert response.status_code in {200, 409}
    if response.status_code == 200:
        body = response.json()
        assert len(body["projections"]) == body["lineage"]["projection_import"]["projection_count"]
    else:
        assert _error_of(response).startswith("projections_")
