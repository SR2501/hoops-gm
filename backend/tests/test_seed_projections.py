"""Seeding a database until the projections endpoint can answer 200.

The acceptance test here is the **200**, driven through the real application,
not that the seed command runs. ``seed_schedule_grid`` exists because an
endpoint was permanently unavailable and nobody noticed; asserting that a seed
completes would reproduce exactly that blind spot one module over.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from hoops_gm.db.models.enums import ExternalSource, MatchMethod
from hoops_gm.db.models.identity import Player, PlayerExternalId
from hoops_gm.db.models.league import League
from hoops_gm.db.models.projections import Projection, ProjectionImport
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.db.session import Database
from hoops_gm.dev.seed_projections import (
    DEMO_COHORT_SIZE,
    DEMO_SOURCE_ID_PREFIX,
    PLAYERS_FIXTURE,
    build_demo_csv,
    seed_projections,
    unique_named_players,
)
from hoops_gm.dev.seed_schedule_grid import DEFAULT_FIXTURES_DIR, DemoSeedRefused, load_fixture
from hoops_gm.ingest.importers import import_nba_players
from hoops_gm.ingest.nba.parsers import parse_common_all_players
from hoops_gm.ingest.projections.importer import import_projection_csv
from hoops_gm.ingest.projections.profiles import BASKETBALL_MONSTER_2026_27_HEADERS

SEASON = "2026-27"
COHORT = 8


def test_the_seeded_database_makes_the_endpoint_answer_200(client: TestClient) -> None:
    """The deliverable, driven end to end through the real route.

    Before this existed ``/projections/current`` had never returned 200 outside
    a unit test: it fails closed on an unimported source, so
    ``projections_source_not_imported`` was the only answer any person had ever
    seen from it. A `frontend` lane cannot capture a fixture from an endpoint
    that has never answered.
    """
    database: Database = client.app.state.database  # type: ignore[attr-defined]
    with database.session() as session:
        result = seed_projections(session, cohort_size=COHORT)

    response = client.get(f"/api/v1/leagues/{result.league_id}/projections/current")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["season"] == "2026-27"
    assert body["source"] == "basketball_monster"
    assert len(body["projections"]) == COHORT
    assert len(body["players"]) == COHORT
    # The endpoint's own guarantee: the two arrays describe one player set, and
    # the cohort size matches what the lineage claims was persisted.
    assert {player["player_id"] for player in body["players"]} == {
        row["player_id"] for row in body["projections"]
    }
    assert body["lineage"]["projection_import"]["projection_count"] == COHORT


def test_the_seeded_players_carry_the_labels_a_screen_needs(client: TestClient) -> None:
    """Real names, teams and positions, because the resolver had to match on them.

    A seed that invented names would resolve nothing; a seed that bypassed the
    resolver would prove the endpoint works against rows the producer would
    never have written. So the names on screen are necessarily real, and this
    pins that they arrive labelled rather than as bare ids.
    """
    database: Database = client.app.state.database  # type: ignore[attr-defined]
    with database.session() as session:
        result = seed_projections(session, cohort_size=COHORT)

    body = client.get(f"/api/v1/leagues/{result.league_id}/projections/current").json()

    assert all(player["full_name"].strip() for player in body["players"])
    assert any(player["team_abbreviation"] for player in body["players"])
    assert any(player["primary_position"] for player in body["players"])


def test_the_uniqueness_filter_excludes_a_shared_name(database: Database) -> None:
    """The filter the seed's "by construction" claim rests on, exercised directly.

    **The committed fixture cannot exercise this.** All 580 players in
    ``nba_commonallplayers_current.json`` normalise to 580 distinct keys, so
    against that fixture ``== 1`` and ``>= 1`` select the identical set — a
    mutation flipping the comparison was **NOT CAUGHT** by the seed-level test,
    which was passing for a reason unrelated to the filter. The guard is
    genuinely defensive: same-named players exist in the NBA and this snapshot
    happens to contain none.

    So the case is constructed. A second canonical player sharing a normalised
    name must remove **both** rows from the cohort, not just the later one:
    Basketball Monster publishes no team or position column, so a shared name
    is unresolvable in either direction and both would be refused as ambiguous.
    """
    with database.session() as session:
        first = Player(
            full_name="Casey Twin",
            normalized_name="twin|casey",
            first_name="casey",
            last_name="twin",
        )
        second = Player(
            full_name="Casey Twin",
            normalized_name="twin|casey",
            first_name="casey",
            last_name="twin",
        )
        solo = Player(
            full_name="Solo Player",
            normalized_name="player|solo",
            first_name="solo",
            last_name="player",
        )
        session.add_all([first, second, solo])
        session.flush()

        cohort = unique_named_players(session, limit=10)

    names = {player.normalized_name for player in cohort}
    assert "player|solo" in names
    assert "twin|casey" not in names
    assert len(cohort) == 1


def test_the_seed_refuses_a_database_holding_a_real_import(database: Database) -> None:
    """The blocking finding from two independent reviews, pinned.

    ``require_safe_demo_target`` inspects ``leagues`` and the parsed
    ``nba_games`` cohort. It has never heard of ``projection_imports`` or
    ``player_external_ids`` — the tables this module writes — so a database
    holding the owner's real paid import but no league row passes it cleanly.

    What happened then: the demo import became the newest for its source and
    season, ``_owns_current_source_crosswalk`` returned ``True``,
    ``import_resolutions`` rewrote the **source-wide current view**, and every
    real ``player_external_ids`` row had ``current_for_source`` retracted to
    ``NULL`` while ``synthetic-demo-*`` became the current crosswalk. The seed
    exited 0 and printed ``identities_accepted: 60`` while doing it.

    This asserts the refusal fires **and that the real crosswalk survives it**,
    because a refusal that raises after writing would still have done the harm.
    """
    with database.session() as setup:
        import_nba_players(
            setup, parse_common_all_players(load_fixture(DEFAULT_FIXTURES_DIR, PLAYERS_FIXTURE))
        )
    with database.session() as setup:
        real_rows = build_demo_csv(unique_named_players(setup, limit=4)).decode().splitlines()
        header, body = real_rows[0], real_rows[1:]
        real_csv = "\n".join(
            [header, *(row.replace(DEMO_SOURCE_ID_PREFIX, "bbm-real-") for row in body)]
        )
        import_projection_csv(
            setup,
            source=ExternalSource.BASKETBALL_MONSTER,
            display_name="Basketball Monster 2026-27",
            season=SEASON,
            csv_bytes=(real_csv + "\n").encode("utf-8"),
            original_filename="owner-real-export.csv",
        )

    def current_bbm_links() -> set[str]:
        with database.session() as check:
            return set(
                check.scalars(
                    select(PlayerExternalId.external_id).where(
                        PlayerExternalId.source == ExternalSource.BASKETBALL_MONSTER,
                        PlayerExternalId.current_for_source.is_not(None),
                    )
                )
            )

    before = current_bbm_links()
    assert before and all(key.startswith("bbm-real-") for key in before), before

    with pytest.raises(DemoSeedRefused, match="did not create"), database.session() as session:
        seed_projections(session, cohort_size=COHORT)

    assert current_bbm_links() == before
    with database.session() as check:
        assert check.scalar(select(func.count()).select_from(ProjectionImport)) == 1


def test_the_refusal_happens_before_anything_is_written(database: Database) -> None:
    """The ordering claim, pinned — because the outcome claim does not pin it.

    "It refuses before anything is written" is stated in three docstrings and
    the handoff, and is explicitly contrasted with the two later refusals that
    *do* fire after writes. Nothing established it: a review moved
    ``require_safe_projection_target`` from the first statement of
    ``seed_projections`` to immediately after ``import_projection_csv``, ran the
    full suite, and got **1316 passed**. It then reproduced the entire original
    blocker — real crosswalk retracted, ``synthetic-demo-*`` current — through a
    raw session, which is how five tests in this file call the function.

    The reason the sibling test cannot see it: it asserts *committed* state, and
    ``Database.session()`` rolls back on exception, so a guard that writes and
    then refuses is rescued by the caller and looks identical to one that
    refused first. This uses a raw ``session_factory()`` session and asserts
    **inside it, before any rollback**, so the caller cannot do the guard's job
    for it.
    """
    with database.session() as setup:
        import_nba_players(
            setup, parse_common_all_players(load_fixture(DEFAULT_FIXTURES_DIR, PLAYERS_FIXTURE))
        )
    with database.session() as setup:
        rows = build_demo_csv(unique_named_players(setup, limit=4)).decode().splitlines()
        real = "\n".join(
            [rows[0], *(r.replace(DEMO_SOURCE_ID_PREFIX, "bbm-real-") for r in rows[1:])]
        )
        import_projection_csv(
            setup,
            source=ExternalSource.BASKETBALL_MONSTER,
            display_name="Basketball Monster 2026-27",
            season=SEASON,
            csv_bytes=(real + "\n").encode("utf-8"),
            original_filename="owner-real-export.csv",
        )

    session = database.session_factory()
    try:
        with pytest.raises(DemoSeedRefused):
            seed_projections(session, cohort_size=COHORT)

        # Read through the *same* session, before any rollback. If the guard had
        # moved after the writers, these would be non-zero here even though a
        # committed-state assertion would still pass.
        assert session.scalar(select(func.count()).select_from(League)) == 0
        assert session.scalar(select(func.count()).select_from(NbaGame)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(PlayerExternalId)
                .where(
                    PlayerExternalId.source == ExternalSource.BASKETBALL_MONSTER,
                    PlayerExternalId.external_id.startswith(DEMO_SOURCE_ID_PREFIX),
                )
            )
            == 0
        )
    finally:
        session.rollback()
        session.close()


def test_the_seed_refuses_a_stray_crosswalk_entry_with_no_import(database: Database) -> None:
    """The crosswalk is checked directly, not inferred from the import table.

    A ``player_external_ids`` row can outlive the import that created it, and
    ``_owns_current_source_crosswalk`` reads that table rather than
    ``projection_imports``. Checking only for a foreign import would be a guard
    whose scope is narrower than the harm — which is the exact defect the whole
    refusal exists to correct, so it must not be reintroduced one table over.
    """
    with database.session() as setup:
        player = Player(
            full_name="Real Person",
            normalized_name="person|real",
            first_name="real",
            last_name="person",
        )
        setup.add(player)
        setup.flush()
        setup.add(
            PlayerExternalId(
                player_id=player.id,
                source=ExternalSource.BASKETBALL_MONSTER,
                current_for_source=ExternalSource.BASKETBALL_MONSTER.value,
                external_id="bbm-real-42",
                external_name="Real Person",
                normalized_name="person|real",
                confidence=0.85,
                match_method=MatchMethod.NORMALIZED_NAME,
            )
        )

    with pytest.raises(DemoSeedRefused, match="crosswalk entry"), database.session() as session:
        seed_projections(session, cohort_size=COHORT)


def test_re_seeding_is_not_refused_by_its_own_output(database: Database) -> None:
    """The negative control: the refusal must not make the seed single-use.

    Without this, a guard that refuses *everything* would pass the two tests
    above and look like protection while breaking the documented workflow of
    re-seeding the demo database.
    """
    with database.session() as session:
        first = seed_projections(session, cohort_size=COHORT)
    with database.session() as session:
        second = seed_projections(session, cohort_size=COHORT)

    assert first.content_sha256 == second.content_sha256


def test_the_seed_resolves_every_row_it_writes(database: Database) -> None:
    """Resolution by construction is the claim; this is what makes it checkable.

    Basketball Monster's contract publishes no team and no position column, so
    a name is the only evidence the resolver has: 0.70, promoted to exactly
    ``AUTO_ACCEPT_CONFIDENCE`` by the unique-name bonus. A name shared with a
    second canonical player is refused as ambiguous instead and produces no
    row. If the uniqueness filter stops filtering, this goes red.
    """
    with database.session() as session:
        result = seed_projections(session, cohort_size=COHORT)

    assert result.identities_accepted == COHORT
    assert result.identities_unresolved == 0
    assert result.projections_written == COHORT

    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Projection)) == COHORT
        assert session.scalar(select(func.count()).select_from(ProjectionImport)) == 1


def test_the_generated_csv_matches_the_verified_profile_header_exactly(
    database: Database,
) -> None:
    """A demo file the real importer would refuse proves nothing about the real importer."""
    with database.session() as session:
        seed_projections(session, cohort_size=COHORT)
        header = (
            build_demo_csv(unique_named_players(session, limit=COHORT)).decode().splitlines()[0]
        )

    assert header.split(",") == list(BASKETBALL_MONSTER_2026_27_HEADERS)


def test_re_seeding_converges_on_one_import(database: Database) -> None:
    """The generated cohort is deterministic, so its bytes hash the same."""
    with database.session() as session:
        first = seed_projections(session, cohort_size=COHORT)
    with database.session() as session:
        second = seed_projections(session, cohort_size=COHORT)

    assert first.content_sha256 == second.content_sha256
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ProjectionImport)) == 1
        assert session.scalar(select(func.count()).select_from(Projection)) == COHORT


def test_the_default_cohort_is_not_a_realistic_league(database: Database) -> None:
    """Pinned so nobody reads a fixture captured from this as league-scale evidence.

    Sixty rows is enough to scroll and sort and is not a projection cohort. The
    number is stated in the docstring a reader sees; this makes the statement
    fail if the constant drifts away from it.
    """
    assert DEMO_COHORT_SIZE == 60
    with database.session() as session:
        result = seed_projections(session)
    assert result.cohort_size == DEMO_COHORT_SIZE
    assert result.cohort_size < 200
