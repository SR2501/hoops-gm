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

**Two guards here are not reachable by a request racing nothing, and are driven
anyway.** A guard nobody has made fire is an untested assertion, so each is
driven by a real committed write from a second connection landing inside the
read window — the mutation changes only *timing*, never the loader's result.
The unlabelled-player guard is genuinely unreachable through the route, a
foreign key seeing to that, and is driven directly against its helper.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Thread
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from hoops_gm.api.routes import projections as projections_route
from hoops_gm.api.routes.projections import ProjectionRates, _projection_players
from hoops_gm.app import create_app
from hoops_gm.core.config import Settings
from hoops_gm.db.base import Base
from hoops_gm.db.models.enums import ExternalSource, FieldEvidence, MatchMethod
from hoops_gm.db.models.identity import NbaTeam, Player, PlayerExternalId
from hoops_gm.db.models.league import League
from hoops_gm.db.models.projections import Projection, ProjectionImport, ProjectionSource
from hoops_gm.identity.names import normalize_name
from hoops_gm.ingest.projections import CANONICAL_STAT_FIELDS, import_projection_csv
from hoops_gm.projections.blending import (
    InvalidBlendProfileError,
    LayerPurityError,
    MissingProjectionDataError,
    ProjectionBlendError,
    StaleProjectionInputError,
    UnknownProjectionInputError,
    release_projection_import,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "projections"
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
        # A seeded position carries the provenance a real import writes. The
        # sibling helper in test_projection_importer.py was corrected for this
        # and this one was missed, which matters more here: this fixture backs
        # the only path where the persisted column reaches a user. Seeding a
        # position with no source, season or observed-at is a shape no real
        # producer can write, and there is no database constraint to catch it
        # (see revision 0016 for why the CHECK was reverted).
        primary_position_source="nba:PlayerIndex" if position else None,
        primary_position_season="2026-27" if position else None,
        primary_position_observed_at=(datetime(2026, 8, 20, tzinfo=UTC) if position else None),
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
    seed_player(session, nba_id=1, name="Player Alpha", team_abbreviation="BOS", position="F")
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
    # Bumped 1 -> 2 when ``verification_strength`` entered the hashed profile
    # definition. Kept as a literal on purpose: this assertion is the alarm
    # that makes a version bump visible, and replacing it with
    # ``BASKETBALL_MONSTER_PROFILE.version`` would silence exactly that.
    assert lineage["profile_version"] == "2"
    assert lineage["original_filename"] == BBM_FIXTURE
    assert lineage["projection_count"] == 2
    assert (lineage["row_count"], lineage["matched_count"], lineage["rejected_count"]) == (2, 2, 0)
    assert (lineage["needs_review_count"], lineage["unmatched_count"]) == (0, 0)
    for digest in ("content_sha256", "profile_definition_sha256", "projection_values_sha256"):
        assert len(lineage[digest]) == 64

    assert [player["full_name"] for player in body["players"]] == list(FIXTURE_PLAYERS)
    assert [player["team_abbreviation"] for player in body["players"]] == ["BOS", "DEN"]
    assert [player["primary_position"] for player in body["players"]] == ["F", "C"]

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


def test_the_audit_counts_actually_partition_the_file(app: FastAPI, client: TestClient) -> None:
    """A docstring calling five numbers a partition invites a screen to add them up.

    Driven over an import whose terms are genuinely different — one row matched,
    one unmatched, one rejected before identity resolution ever ran — because a
    fixture where the terms are zero satisfies the sum trivially and would
    satisfy it under a broken importer too. Review required the ``rejected``
    term specifically, since it is the one that partitions the file *before* the
    other three partition what survived. Nothing in the schema enforces this:
    ``projection_imports`` carries only five ``>= 0`` checks.
    """

    lines = load_bytes(BBM_FIXTURE).split(b"\n")
    header, alpha, gamma = lines[0], lines[1], lines[2]
    # A third data row the parser must refuse outright: a non-numeric games
    # value, which is fatal before any crosswalk lookup happens.
    rejected_row = gamma.replace(b"Gamma,Player,78", b"Broken,Player,not-a-number")
    mixed = b"\n".join(
        [header, alpha, gamma.replace(b"Gamma,Player", b"Nameless,Nobody"), rejected_row, b""]
    )

    with app.state.database.session() as session:
        league_id = _seed_league(session)
        _seed_fixture_players(session)
        _import_bbm(session, csv_bytes=mixed)

    lineage = client.get(PROJECTIONS_URL.format(league_id=league_id)).json()["lineage"][
        "projection_import"
    ]

    parts = (
        lineage["rejected_count"],
        lineage["matched_count"],
        lineage["needs_review_count"],
        lineage["unmatched_count"],
    )
    assert parts == (1, 1, 0, 1), "the terms must differ, and rejected must be non-zero"
    assert lineage["row_count"] == sum(parts) == 3
    assert lineage["projection_count"] == 1


def test_the_blending_error_family_is_pinned(client: TestClient, seeded: int) -> None:
    """A future subclass must not join a shared code without someone deciding.

    ``_released_import`` deliberately catches ``ProjectionBlendError`` last so a
    new refusal is a typed 409 rather than an untyped 500. The cost is that the
    enumeration justifying one shared summary for
    ``projections_incomplete_evidence`` is true today and nothing re-runs it.
    Pinning the subclass set converts that unexamined inheritance into the kind
    of wrongness a test catches: adding a subclass fails here and forces a
    deliberate mapping decision.
    """

    assert set(ProjectionBlendError.__subclasses__()) == {
        UnknownProjectionInputError,
        StaleProjectionInputError,
        InvalidBlendProfileError,
        MissingProjectionDataError,
        LayerPurityError,
    }
    # None of them subclasses another, so the specific handlers in
    # `_released_import` cannot be shadowed by the family catch below them.
    for error in ProjectionBlendError.__subclasses__():
        assert error.__subclasses__() == []


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


def test_the_write_after_regime_depends_on_primary_key_stability(
    app: FastAPI, client: TestClient, seeded: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The claim "behaves identically on both dialects" was wrong, and this pins why.

    A write landing after the row load is shadowed by the route's own strong
    references **only while the row primary keys are unchanged**. A re-import
    replaces every key, so the second release loads fresh instances and the
    request is refused instead. That is unconditional on PostgreSQL, whose
    ``SERIAL`` never recycles, and conditional on SQLite, which does.

    Both branches are asserted here so the difference is a fact in the suite
    rather than a sentence in a docstring: the guarantee is unconditional, the
    behaviour is not.
    """

    # Regime 2: in-place edit, keys untouched -> shadowed, older snapshot served.
    unmutated = projections_route._projection_rows

    def edit_only(session: Session, *, import_id: int) -> list[Projection]:
        rows = unmutated(session, import_id=import_id)
        worker = app.state.database.session_factory()
        try:
            worker.execute(
                update(Projection)
                .where(Projection.projection_import_id == import_id)
                .values(assists_per_game=9.0)
            )
            worker.commit()
        finally:
            worker.close()
        return rows

    monkeypatch.setattr(projections_route, "_projection_rows", edit_only)
    shadowed = client.get(PROJECTIONS_URL.format(league_id=seeded))
    assert shadowed.status_code == 200
    assert 9.0 not in [p["assists_per_game"] for p in shadowed.json()["projections"]]

    # Regime 3: the same edit behind a re-import that replaces the keys ->
    # refused. What stops SQLite recycling the ids is a row from *another*
    # import surviving the delete, which keeps max(rowid) above the freed range;
    # the explicit id=900 makes that margin unambiguous rather than incidental.
    # Verified by mutation: remove this block and the case collapses into
    # regime 2 and returns 200.
    with app.state.database.session() as session:
        seed_player(session, nba_id=99, name="Spare Parker", team_abbreviation="NYK", position="G")
        other = import_projection_csv(
            session,
            source=ExternalSource.MANUAL,
            display_name="Manual",
            season=SEASON,
            csv_bytes=b"player_name,points_per_game\nSpare Parker,10.0\n",
        ).projection_import
        session.execute(
            update(Projection).where(Projection.projection_import_id == other.id).values(id=900)
        )
        assert session.scalar(select(func.max(Projection.id))) == 900

    def reimport_then_edit(session: Session, *, import_id: int) -> list[Projection]:
        rows = unmutated(session, import_id=import_id)
        worker = app.state.database.session_factory()
        try:
            _import_bbm(worker)
            # A value the first release did not see. Phase 1 already committed
            # 9.0, so reusing it would leave the digest unchanged and the test
            # would pass for the wrong reason.
            worker.execute(
                update(Projection)
                .where(Projection.projection_import_id == import_id)
                .values(assists_per_game=5.5)
            )
            worker.commit()
        finally:
            worker.close()
        return rows

    monkeypatch.setattr(projections_route, "_projection_rows", reimport_then_edit)
    refused = client.get(PROJECTIONS_URL.format(league_id=seeded))
    assert refused.status_code == 409
    assert _error_of(refused) == "projections_inconsistent_cohort"


def test_a_byte_identical_reimport_mid_read_does_not_empty_the_assumptions(
    app: FastAPI, client: TestClient, seeded: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The identity ABA, which the value ABA analysis missed entirely.

    ``_import_projection_rows`` deletes and re-inserts the whole row cohort even
    for a byte-identical re-import, so ``Projection.id`` changes while the import
    id, the rates, the row count and the digest all stay identical. Keying the
    assumptions lookup on the captured surrogate keys therefore produced a **200
    with an empty array** — which this response documents as "the source said
    nothing", when Basketball Monster published 70 and 78. A lie, not a blank,
    in the one array carrying the ADR-002 thesis.

    **Forcing the ids apart is the point of this test.** SQLite recycles the top
    free rowid, so in a database holding one import the re-inserted rows land
    back on the same ids and the defect is invisible — the shape every other test
    in this file builds. PostgreSQL's ``SERIAL`` never recycles, so it fires
    unconditionally there. What prevents recycling here is a row from *another*
    import surviving the delete and keeping ``max(rowid)`` above the freed range;
    the explicit ``id=900`` makes that margin unambiguous. That reproduces on
    SQLite what the Postgres seam does anyway, which is the whole reason ADR-001
    keeps that seam.
    """

    before = client.get(PROJECTIONS_URL.format(league_id=seeded)).json()
    assert [c["assumed_games_played"] for c in before["source_games_played_assumptions"]] == [
        70.0,
        78.0,
    ]

    with app.state.database.session() as session:
        # A row that SURVIVES the re-import, so SQLite cannot recycle ids 1 and
        # 2 back. It has to belong to a *different* import, because
        # `_import_projection_rows` deletes every row of the import it is
        # rewriting — an earlier version of this test parked and then deleted a
        # row of the same import, which left `max(rowid)` unchanged and made the
        # test pass against the very bug it was written for.
        spare = seed_player(
            session, nba_id=99, name="Spare Parker", team_abbreviation="NYK", position="G"
        )
        other_import = import_projection_csv(
            session,
            source=ExternalSource.MANUAL,
            display_name="Manual",
            season=SEASON,
            csv_bytes=b"player_name,points_per_game\nSpare Parker,10.0\n",
        ).projection_import
        session.execute(
            update(Projection)
            .where(Projection.projection_import_id == other_import.id)
            .values(id=900)
        )
        assert session.scalar(select(func.max(Projection.id))) == 900
        assert spare.id is not None

    unmutated = projections_route._projection_rows

    def reimport_identical_bytes_first(session: Session, *, import_id: int) -> list[Projection]:
        rows = unmutated(session, import_id=import_id)
        worker = app.state.database.session_factory()
        try:
            _import_bbm(worker)
            worker.commit()
        finally:
            worker.close()
        return rows

    monkeypatch.setattr(projections_route, "_projection_rows", reimport_identical_bytes_first)
    response = client.get(PROJECTIONS_URL.format(league_id=seeded))

    assert response.status_code == 200
    body = response.json()
    lineage = body["lineage"]["projection_import"]
    # The re-import converged on the same import row, so nothing the digest
    # covers moved — which is exactly why the surrogate-key version escaped.
    assert lineage["import_id"] == before["lineage"]["projection_import"]["import_id"]
    assert (
        lineage["projection_values_sha256"]
        == before["lineage"]["projection_import"]["projection_values_sha256"]
    )
    claims = body["source_games_played_assumptions"]
    assert claims, "an empty array here means 'the source said nothing', which would be false"
    assert [c["assumed_games_played"] for c in claims] == [70.0, 78.0]
    assert {c["player_id"] for c in claims} == {p["player_id"] for p in body["players"]}


def test_a_row_whose_season_drifted_from_its_import_is_refused(
    app: FastAPI, client: TestClient, seeded: int
) -> None:
    """The family member review found missing from the route's own enumeration.

    Operationally it looks different from the rest — a denormalised column on a
    stored row drifting from its parent reads like data repair rather than
    re-import — which is why it tests ``architect``'s splitting rule. It does
    not break it: re-importing the same bytes rewrites the whole row cohort, so
    the remedy still converges at *produce a good import*, and the code stays
    shared.
    """

    assert client.get(PROJECTIONS_URL.format(league_id=seeded)).status_code == 200

    with app.state.database.session() as session:
        session.execute(update(Projection).values(season="2019-20"))

    response = client.get(PROJECTIONS_URL.format(league_id=seeded))

    assert response.status_code == 409
    assert _error_of(response) == "projections_incomplete_evidence"


def test_makes_exceeding_attempts_is_refused(app: FastAPI, client: TestClient, seeded: int) -> None:
    """The ninth member, called unreachable through two review rounds.

    The CHECK constraint ``fg3_made_within_attempted`` evaluates
    ``made <= attempted + 0.001`` in IEEE-754 double, while
    ``blending._validate_shooting_values`` compares exact ``Fraction(str(value))``
    against ``Fraction(1, 1000)``. Same constant, different arithmetic, so a band
    about one ULP wide inserts cleanly and then fails validation.

    The values below are review's, reproduced rather than re-derived. Practical
    data risk is nil; the point is that "the CHECK blocks it" was a stated
    mechanism nobody had run, which is the habit this file exists to break.
    """

    assert client.get(PROJECTIONS_URL.format(league_id=seeded)).status_code == 200

    with app.state.database.session() as session:
        session.execute(
            update(Projection).values(
                three_pointers_attempted_per_game=20.45098885,
                three_pointers_made_per_game=20.451988850000003,
            )
        )

    response = client.get(PROJECTIONS_URL.format(league_id=seeded))

    assert response.status_code == 409
    assert _error_of(response) == "projections_incomplete_evidence"
    assert "makes greater than attempts" in response.json()["detail"]


def test_a_half_present_three_point_pair_is_refused(
    app: FastAPI, client: TestClient, seeded: int
) -> None:
    """The seventh member, reachable only for three-pointers.

    ``projections`` has ``fg_volume_pair_complete`` and ``ft_volume_pair_complete``
    CHECK constraints and **no** ``fg3_volume_pair_complete``, so this is the one
    made/attempted pair that can be broken in the database at all. Driving it
    pins both facts: that the refusal works, and that the asymmetry is real
    rather than a reading of the model file.
    """

    assert client.get(PROJECTIONS_URL.format(league_id=seeded)).status_code == 200

    with app.state.database.session() as session:
        session.execute(update(Projection).values(three_pointers_attempted_per_game=None))

    response = client.get(PROJECTIONS_URL.format(league_id=seeded))

    assert response.status_code == 409
    assert _error_of(response) == "projections_incomplete_evidence"


# --------------------------------------------------------------------------
# Guards driven by real committed writes landing mid-request
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
    app: FastAPI, client: TestClient, seeded: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real committed DELETE lands between the release and the row load.

    Review's objection to the earlier version was right: monkeypatching the
    loader to slice a row off reproduces "the loader returned fewer rows", not
    "the database changed underneath the request", which is the failure the
    guard exists for. So the mutation here changes only *timing* — the loader
    still loads whatever is there — and a second connection really commits a
    delete in the window. Nothing about the route's logic is patched.

    Without the guard this returns 200 with one player's rates beside
    ``projection_count: 2``: a success-shaped partial answer.
    """

    unmutated = projections_route._projection_rows
    assert len(client.get(PROJECTIONS_URL.format(league_id=seeded)).json()["projections"]) == 2

    def delete_one_row_first(session: Session, *, import_id: int) -> list[Projection]:
        worker = app.state.database.session_factory()
        try:
            victim = worker.scalar(
                select(Projection.id)
                .where(Projection.projection_import_id == import_id)
                .order_by(Projection.player_id.desc())
                .limit(1)
            )
            worker.execute(delete(Projection).where(Projection.id == victim))
            worker.commit()
        finally:
            worker.close()
        return unmutated(session, import_id=import_id)

    monkeypatch.setattr(projections_route, "_projection_rows", delete_one_row_first)
    response = client.get(PROJECTIONS_URL.format(league_id=seeded))

    assert response.status_code == 409
    assert _error_of(response) == "projections_inconsistent_cohort"
    assert "2" in response.json()["detail"] and "1" in response.json()["detail"]


def test_a_cohort_that_moved_under_the_read_is_refused(
    app: FastAPI, client: TestClient, seeded: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure the cardinality check could never see: a same-size edit.

    Also a real committed write from a second connection, for the same reason.
    A rate changes, the row count does not. Without the re-release comparison
    this returns 200 with the *post-write* rates beside the *pre-write*
    ``projection_values_sha256`` — the lineage block failing to describe the
    numbers next to it, which is exactly what review demonstrated at the head
    before this guard existed.
    """

    unmutated = projections_route._projection_rows
    before = client.get(PROJECTIONS_URL.format(league_id=seeded)).json()
    assert before["projections"][0]["assists_per_game"] != 9.0

    def edit_a_rate_first(session: Session, *, import_id: int) -> list[Projection]:
        worker = app.state.database.session_factory()
        try:
            worker.execute(
                update(Projection)
                .where(Projection.projection_import_id == import_id)
                .values(assists_per_game=9.0)
            )
            worker.commit()
        finally:
            worker.close()
        return unmutated(session, import_id=import_id)

    monkeypatch.setattr(projections_route, "_projection_rows", edit_a_rate_first)
    response = client.get(PROJECTIONS_URL.format(league_id=seeded))

    assert response.status_code == 409
    assert _error_of(response) == "projections_inconsistent_cohort"
    assert (
        before["lineage"]["projection_import"]["projection_values_sha256"]
        in response.json()["detail"]
    )


def test_an_import_that_disappears_mid_request_is_refused(
    app: FastAPI, client: TestClient, seeded: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The third `projections_not_current` raiser, which review found undriven.

    It was marked ``# pragma: no cover`` on the belief that the canonical
    release had just loaded the row. With no lock and a weakly-referencing
    identity map, ``session.get`` is a real query and a concurrent delete can
    miss it. Driven with a real committed delete rather than reasoned about,
    and the pragma is gone.
    """

    unmutated = projections_route._projection_rows

    def delete_the_import_first(session: Session, *, import_id: int) -> list[Projection]:
        rows = unmutated(session, import_id=import_id)
        worker = app.state.database.session_factory()
        try:
            worker.execute(delete(ProjectionImport).where(ProjectionImport.id == import_id))
            worker.commit()
        finally:
            worker.close()
        return rows

    monkeypatch.setattr(projections_route, "_projection_rows", delete_the_import_first)
    response = client.get(PROJECTIONS_URL.format(league_id=seeded))

    assert response.status_code == 409
    assert _error_of(response) == "projections_not_current"


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
# Concurrency, without a lock
# --------------------------------------------------------------------------


def test_a_read_writes_nothing(app: FastAPI, client: TestClient) -> None:
    """The route takes no lock, so it must also take no write.

    The rejected alternative acquired SQLite's write reservation with an
    ``UPDATE``, which mutates ``updated_at`` through ``TimestampMixin``'s
    ``onupdate`` and made every dashboard poll a writer. This pins the property
    that replaced it: a read leaves the source row exactly as it found it, on
    the success path and on a refusal alike.

    **The refusal half is deliberately a late one.** Review caught an earlier
    version asking for an unimported source, which refuses *before* the source
    row is ever touched — so the assertion held for a reason unrelated to the
    property, which is a vacuous pass wearing a coverage claim. This one breaks
    the import's profile verification instead, so the refusal happens after the
    source row and the import row have both been read.
    """

    with app.state.database.session() as session:
        league_id = _seed_league(session)
        _seed_fixture_players(session)
        _import_bbm(session)

    def source_row() -> tuple[Any, Any]:
        probe = app.state.database.session_factory()
        try:
            row = probe.execute(
                select(ProjectionSource.updated_at, ProjectionSource.display_name)
            ).one()
            return (row[0], row[1])
        finally:
            probe.close()

    before = source_row()
    assert client.get(PROJECTIONS_URL.format(league_id=league_id)).status_code == 200
    assert source_row() == before

    with app.state.database.session() as session:
        session.execute(update(ProjectionImport).values(profile_verified=False))
    after_break = source_row()

    response = client.get(PROJECTIONS_URL.format(league_id=league_id))
    assert response.status_code == 409
    assert _error_of(response) == "projections_incomplete_evidence"
    assert source_row() == after_break


def test_concurrent_reads_all_succeed(app: FastAPI, client: TestClient) -> None:
    """Four overlapping polls, which the write-reservation design could not promise.

    On SQLite a reservation-holding read is a writer, so concurrent polls
    contend for the single writer and one can be told ``database is locked``.
    Taking no lock removes that entirely, and this pins it rather than assuming
    it.
    """

    with app.state.database.session() as session:
        league_id = _seed_league(session)
        _seed_fixture_players(session)
        _import_bbm(session)

    statuses: list[int] = []

    def poll() -> None:
        statuses.append(client.get(PROJECTIONS_URL.format(league_id=league_id)).status_code)

    threads = [Thread(target=poll, daemon=True) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not [thread for thread in threads if thread.is_alive()]
    assert statuses == [200, 200, 200, 200]


def test_a_read_never_blocks_the_owners_import(app: FastAPI, client: TestClient) -> None:
    """The reason the lock was removed, asserted rather than asserted-in-prose.

    A hand-run ``import_projection_csv`` must not fail because a dashboard tab
    is polling. Under the rejected write-reservation design this writer was told
    ``database is locked`` — that behaviour was driven, and it is what made the
    trade wrong for a single-user local tool whose writer is a person at a
    keyboard.
    """

    with app.state.database.session() as session:
        league_id = _seed_league(session)
        _seed_fixture_players(session)
        _import_bbm(session)

    barrier = Barrier(2, timeout=30)
    failures: list[str] = []
    statuses: list[int] = []

    def poll() -> None:
        barrier.wait()
        for _ in range(3):
            statuses.append(client.get(PROJECTIONS_URL.format(league_id=league_id)).status_code)

    def owner_import() -> None:
        worker = app.state.database.session_factory()
        try:
            barrier.wait()
            _import_bbm(worker, csv_bytes=load_bytes(BBM_FIXTURE).replace(b",2415,", b",2390,"))
            worker.commit()
        except Exception as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
        finally:
            worker.rollback()
            worker.close()

    threads = [Thread(target=poll, daemon=True), Thread(target=owner_import, daemon=True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not [thread for thread in threads if thread.is_alive()]
    assert failures == [], "a concurrent read must never make the owner's import fail"
    assert statuses and set(statuses) <= {200, 409}


def test_a_concurrent_import_never_serves_a_lineage_that_does_not_describe_its_rates(
    app: FastAPI, client: TestClient
) -> None:
    """The property that replaced the lock, driven under real contention.

    **The writer re-imports byte-identical bytes on purpose.** An earlier version
    imported *different* bytes, which creates a new ``ProjectionImport``, so the
    reader lost the *currency* race instead — review ran the body eight times and
    got ``projections_not_current`` seven of them, meaning the test named after
    ``_assert_cohort_is_stable`` almost never reached its content assertion.
    Byte-identical content converges on the same import row, so a 200 is the
    common outcome and the content claim is actually checked. It is also the
    exact race that produced the empty-assumptions defect.

    Review's other objection was that on a 200 this asserted only cardinality —
    the same blind spot as the guard it was meant to exercise. It now re-releases
    the served import and compares the **digest**, and checks the assumptions
    array is still populated.
    """

    with app.state.database.session() as session:
        league_id = _seed_league(session)
        _seed_fixture_players(session)
        _import_bbm(session)

    barrier = Barrier(2, timeout=30)
    responses: list[Any] = []

    def reader() -> None:
        barrier.wait()
        responses.append(client.get(PROJECTIONS_URL.format(league_id=league_id)))

    def writer() -> None:
        worker = app.state.database.session_factory()
        try:
            barrier.wait()
            _import_bbm(worker)
            worker.commit()
        finally:
            worker.rollback()
            worker.close()

    threads = [Thread(target=reader, daemon=True), Thread(target=writer, daemon=True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    stuck = [thread.name for thread in threads if thread.is_alive()]
    assert not stuck, f"threads still running after 60s, which is the deadlock case: {stuck}"

    assert len(responses) == 1
    response = responses[0]
    assert response.status_code in {200, 409}
    if response.status_code != 200:
        assert _error_of(response).startswith("projections_")
        return

    body = response.json()
    lineage = body["lineage"]["projection_import"]
    assert len(body["projections"]) == lineage["projection_count"]
    # The assumptions array is the one the identity race emptied. Absent means
    # "the source said nothing", and Basketball Monster said 70 and 78.
    assert [c["assumed_games_played"] for c in body["source_games_played_assumptions"]] == [
        70.0,
        78.0,
    ]

    # The content claim: whatever was served, its digest is the digest of the
    # rates that came with it. Re-released through the canonical function so
    # this test does not re-implement the normalisation either.
    verify = app.state.database.session_factory()
    try:
        current = release_projection_import(
            verify,
            import_id=lineage["import_id"],
            source=ExternalSource.BASKETBALL_MONSTER,
        )
        assert current.projection_values_sha256 == lineage["projection_values_sha256"]
        assert current.projection_count == len(body["projections"])
    finally:
        verify.close()
