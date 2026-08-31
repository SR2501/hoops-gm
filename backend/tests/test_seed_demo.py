"""One database, three screens — driven, not asserted about.

The failure this module guards against is not that a seed crashes. It is that
three seeds each succeed into three different files, one backend serves one
file, and the dashboard shows a working draft board beside two ``409`` pages.
Every test here therefore drives the **real routes all three screens call**,
against **one** database seeded by **one** command. Asserting that
``seed_demo`` returns without raising would reproduce the original blind spot
exactly: it is the composition, not any individual seeder, that had never been
exercised.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hoops_gm.core.config import Settings
from hoops_gm.db.models.availability import PlayerParticipation
from hoops_gm.db.models.draft import Draft, DraftEvent
from hoops_gm.db.models.enums import (
    DraftEventType,
    DraftToolUsage,
    DraftType,
    GameStatus,
    ParticipationOutcome,
)
from hoops_gm.db.models.identity import NbaTeam, Player
from hoops_gm.db.models.league import League
from hoops_gm.db.models.projections import Projection
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.db.session import Database
from hoops_gm.dev.seed_demo import (
    FRONTEND_LEAGUE_ID,
    looks_like_a_previous_demo_seed,
    main,
    seed_demo,
)
from hoops_gm.dev.seed_draft import CanonicalDraftPlayer, seed_drafts
from hoops_gm.dev.seed_schedule_grid import (
    FANTRAX_LEAGUE_ID,
    LEAGUE_NAME,
    SEASON,
    DemoSeedRefused,
)
from hoops_gm.identity.names import normalize_name

#: Small on purpose. The cohort size is orthogonal to everything under test
#: here — what is under test is that three screens read one database — and the
#: full 60 costs seconds per test for no extra coverage.
COHORT = 8


def test_one_seeded_database_answers_all_three_screens(client: TestClient) -> None:
    """The deliverable, end to end: one seed, three routes, three 200s.

    This is the assertion the demo did not have. Each of the three seeders
    already had a test proving *its own* endpoint could answer; none of them
    could see that the other two were pointed at different files, because a
    test that seeds one database and reads one endpoint is true either way.
    """

    database: Database = client.app.state.database  # type: ignore[attr-defined]
    with database.session() as session:
        result = seed_demo(session, cohort_size=COHORT)

    league_id = result.projections.league_id

    schedule = client.get(f"/api/v1/leagues/{league_id}/schedule-grid/current")
    projections = client.get(f"/api/v1/leagues/{league_id}/projections/current")
    drafts = client.get("/api/v1/drafts")

    assert schedule.status_code == 200, schedule.text
    assert projections.status_code == 200, projections.text
    assert drafts.status_code == 200, drafts.text

    # Presence, counted — not the absence of an error word. Both working
    # screens legitimately render copy containing "not": the schedule says
    # "this season is not fully scheduled" (the ADR-013 pending affordance) and
    # projections says "we have not computed our own projections yet". A scan
    # for failure words returns true on a correct demo.
    assert len(schedule.json()["teams"]) == 30
    assert len(projections.json()["projections"]) == COHORT
    assert len(drafts.json()["drafts"]) == 2


def test_both_mock_drafts_are_listed_with_the_selections_the_seed_recorded(
    client: TestClient,
) -> None:
    """The draft screen's own numbers, from the same database as the other two.

    ``/api/v1/drafts`` derives ``selections_made`` from the log on every
    request rather than storing it, so this also pins that the seeded log is
    one the deriver accepts — a seed writing rows directly could produce a
    state no recorder could reach.
    """

    database: Database = client.app.state.database  # type: ignore[attr-defined]
    with database.session() as session:
        result = seed_demo(session, cohort_size=COHORT)

    listed = client.get("/api/v1/drafts").json()["drafts"]
    by_id = {draft["id"]: draft for draft in listed}

    assert by_id[result.drafts.auction_draft_id]["format"]["draft_type"] == "auction"
    assert (
        by_id[result.drafts.auction_draft_id]["selections_made"] == result.drafts.auction_selections
    )
    assert by_id[result.drafts.snake_draft_id]["format"]["draft_type"] == "snake"
    assert by_id[result.drafts.snake_draft_id]["selections_made"] == result.drafts.snake_selections


def test_the_composed_auction_and_projection_responses_join_end_to_end(
    client: TestClient,
) -> None:
    """The existing category page receives joinable inputs from one composed seed.

    Two individually valid 200 responses are insufficient: before this change
    every auction holding carried ``player_id=None``, so the category model joined
    0 of 7 selections and ranked no seat. This drives the exact draft-state and
    current-projections routes that page combines, then performs its ID join.
    """

    database: Database = client.app.state.database  # type: ignore[attr-defined]
    with database.session() as session:
        result = seed_demo(session, cohort_size=COHORT)

    draft_response = client.get(f"/api/v1/drafts/{result.drafts.auction_draft_id}")
    assert draft_response.status_code == 200, draft_response.text
    draft_state = draft_response.json()

    projections_response = client.get(
        f"/api/v1/leagues/{draft_state['league_id']}/projections/current"
    )
    assert projections_response.status_code == 200, projections_response.text
    current_projections = projections_response.json()

    projection_ids = {row["player_id"] for row in current_projections["projections"]}
    holdings = [
        holding
        for participant in draft_state["participants"]
        for holding in participant["holdings"]
    ]
    joined_players = sum(
        holding["player_id"] is not None and holding["player_id"] in projection_ids
        for holding in holdings
    )
    ranked_seats = sum(
        any(
            holding["player_id"] is not None and holding["player_id"] in projection_ids
            for holding in participant["holdings"]
        )
        for participant in draft_state["participants"]
    )

    assert len(holdings) == result.drafts.auction_selections == 7
    assert draft_state["unresolved_player_count"] == 0
    assert joined_players == len(holdings)
    assert joined_players > 0
    assert ranked_seats == 7
    assert ranked_seats > 0

    with database.session() as session:
        exact_cohort_ids = set(
            session.scalars(
                select(Projection.player_id).where(
                    Projection.projection_import_id == result.projections.projection_import_id
                )
            )
        )
        player_events = session.execute(
            select(DraftEvent.event_type, DraftEvent.player_id).where(
                DraftEvent.draft_id == result.drafts.auction_draft_id,
                DraftEvent.event_type.in_((DraftEventType.NOMINATION, DraftEventType.SALE)),
            )
        ).all()

    assert exact_cohort_ids == projection_ids
    assert player_events
    assert all(player_id is not None for _, player_id in player_events)
    assert {player_id for _, player_id in player_events} <= exact_cohort_ids


def test_the_standalone_draft_seed_keeps_its_invented_names_unresolved(
    client: TestClient,
) -> None:
    """Canonical IDs are an opt-in composition seam, not new standalone semantics."""

    database: Database = client.app.state.database  # type: ignore[attr-defined]
    with database.session() as session:
        result = seed_drafts(session)

    response = client.get(f"/api/v1/drafts/{result.auction_draft_id}")
    assert response.status_code == 200, response.text
    state = response.json()
    holdings = [
        holding for participant in state["participants"] for holding in participant["holdings"]
    ]

    assert len(holdings) == result.auction_selections == 7
    assert state["unresolved_player_count"] == 7
    assert all(holding["player_id"] is None for holding in holdings)

    with database.session() as session:
        events = list(
            session.scalars(
                select(DraftEvent)
                .where(DraftEvent.draft_id == result.auction_draft_id)
                .order_by(DraftEvent.sequence)
            )
        )

    assert all(event.player_id is None for event in events)
    assert (
        sum(
            event.player_label is not None
            for event in events
            if event.event_type is DraftEventType.SALE
        )
        == 4
    )


def test_a_short_canonical_auction_sequence_refuses_before_any_draft_write(
    database: Database,
) -> None:
    """A supplied canonical cohort is complete or the draft seed writes nothing."""
    with pytest.raises(DemoSeedRefused) as refusal, database.session() as session:
        canonical = [
            Player(
                full_name=f"Canonical {number}",
                normalized_name=normalize_name(f"Canonical {number}").key,
            )
            for number in range(1, 7)
        ]
        session.add_all(canonical)
        session.flush()
        players = tuple(
            CanonicalDraftPlayer(player_id=player.id, player_label=player.full_name)
            for player in canonical
        )
        seed_drafts(session, auction_players=players)

    assert "requires 7 canonical players" in str(refusal.value)
    assert "received 6" in str(refusal.value)
    assert "partial category board" in str(refusal.value)
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(Player)) == 0
        assert session.scalar(select(func.count()).select_from(League)) == 0
        assert session.scalar(select(func.count()).select_from(Draft)) == 0
        assert session.scalar(select(func.count()).select_from(DraftEvent)) == 0


def test_the_dashboard_league_is_the_one_both_screens_are_hardcoded_to(
    database: Database,
) -> None:
    """``SchedulePage.tsx`` and ``ProjectionsPage.tsx`` both read league 1.

    Neither takes the id from a route parameter or a picker, so on a fresh
    database the schedule league has to *be* league 1 or the dashboard fetches
    two leagues that do not exist. Pinned here because the mechanism producing
    it is insertion order, which is silent: nothing in the backend would notice
    the id drifting, and the symptom is two 404s with no explanation.
    """

    with database.session() as session:
        result = seed_demo(session, cohort_size=COHORT)

    assert result.projections.league_id == FRONTEND_LEAGUE_ID

    with database.session() as session:
        # The draft leagues take later ids. Asserted as an inequality as well
        # as through the constant above, because that is the property that
        # survives the seed being run into a database that already holds rows.
        draft_league_ids = set(
            session.scalars(select(League.id).where(League.fantrax_league_id.is_(None))).all()
        )
    assert draft_league_ids and min(draft_league_ids) > FRONTEND_LEAGUE_ID


def test_seeding_drafts_first_makes_the_composed_seed_refuse(database: Database) -> None:
    """Why ``seed_drafts`` runs last, driven rather than reasoned about.

    The draft seed creates leagues with ``fantrax_league_id IS NULL``, which is
    the first arm of ``require_safe_demo_target``'s foreign-league refusal. So
    the wrong order does not merely produce a worse demo — it produces a
    database the schedule and projections screens can never be seeded into at
    all, and the message names a league rather than an ordering.
    """

    with database.session() as session:
        seed_drafts(session)

    with pytest.raises(DemoSeedRefused) as refusal, database.session() as session:
        seed_demo(session, cohort_size=COHORT)

    assert "which this seed did not create" in str(refusal.value)


def test_a_refusal_after_the_first_writes_rolls_them_back(database: Database) -> None:
    """One session, so a late refusal rolls the early writes back with it.

    Composing the seeders at the shell instead — three processes, three
    transactions — is what produced the half-seeded files this module replaces:
    the schedule commits, the draft seed refuses, and the operator is left with
    a database that is neither empty nor usable and no signal saying which.

    **Which refusal fires is the whole test, and the obvious way to write this
    tests nothing.** Planting an arbitrary foreign league makes
    ``require_safe_demo_target`` refuse *before any write at all*, so the
    database is unchanged for a reason that has nothing to do with rollback and
    the assertions below pass vacuously. The refusal has to arrive from
    ``seed_drafts``, after ``seed_projections`` has written the schedule, the
    players and the projection rows into this session.

    So the planted league is deliberately **the seed's own** — matching
    ``FANTRAX_LEAGUE_ID`` and ``SEASON``, which ``_league`` adopts and
    ``require_safe_demo_target`` accepts — carrying a draft named without the
    ``[demo] `` prefix. That is the one arrangement where everything written by
    the first seeder is on the floor when the second one refuses.
    """

    with database.session() as session:
        league = League(
            fantrax_league_id=FANTRAX_LEAGUE_ID,
            name=LEAGUE_NAME,
            season=SEASON,
            scoring_type="h2h_categories",
            draft_type="auction",
            team_count=12,
            roster_size=13,
        )
        session.add(league)
        session.flush()
        session.add(
            Draft(
                league_id=league.id,
                name="A mock the owner actually recorded",
                is_mock=True,
                tool_usage=DraftToolUsage.BLIND,
                draft_type=DraftType.AUCTION,
                team_count=12,
                roster_size=13,
                # `ck_drafts_auction_budget_matches_format` requires it. Left
                # off first and the insert failed, which is the schema doing
                # its job: even a planted row has to be one the recorder could
                # have produced.
                auction_budget=Decimal("200.00"),
            )
        )

    with pytest.raises(DemoSeedRefused) as refusal, database.session() as session:
        seed_demo(session, cohort_size=COHORT)

    # Attribution: this must be the draft seed's refusal, which fires after the
    # projection writes, not the schedule seed's, which fires before them.
    assert "did not create" in str(refusal.value)
    assert "scratch database" in str(refusal.value)

    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(NbaGame)) == 0
        assert session.scalar(select(func.count()).select_from(Projection)) == 0
        # The planted draft is still the only one, and the planted league the
        # only league: nothing the first seeder wrote survived.
        assert session.scalar(select(func.count()).select_from(Draft)) == 1
        assert session.scalar(select(func.count()).select_from(League)) == 1


def test_re_running_against_its_own_output_refuses(database: Database) -> None:
    """The composed seed is reproducible from empty, not idempotent.

    Each seeder converges on re-run on its own; the composition does not,
    because ``seed_drafts`` leaves ``[demo] `` leagues that
    ``require_safe_demo_target`` is written to refuse. Pinned so the
    documentation's "delete the file and run it again" is a checked statement
    rather than a guess about a command nobody ran twice.
    """

    with database.session() as session:
        seed_demo(session, cohort_size=COHORT)

    with pytest.raises(DemoSeedRefused), database.session() as session:
        seed_demo(session, cohort_size=COHORT)


def test_the_repeat_run_hint_fires_on_our_own_output_and_not_on_a_real_league(
    database: Database,
) -> None:
    """The diagnostic distinguishes the two databases that produce one message.

    ``require_safe_demo_target`` says the same thing whether it found the
    operator's real league or the seed's own draft leagues, and those two
    situations want opposite advice: one is "delete the file", the other is
    "you nearly clobbered your season". Both arms are driven here — asserting
    only the true case would leave a hint that fires on everything, which is
    worse than no hint.
    """

    with database.session() as session:
        assert looks_like_a_previous_demo_seed(session) is False

    with database.session() as session:
        seed_demo(session, cohort_size=COHORT)

    with database.session() as session:
        assert looks_like_a_previous_demo_seed(session) is True

    with database.session() as session:
        session.add(
            League(
                fantrax_league_id="real-league",
                name="The owner's actual league",
                season="2026-27",
                scoring_type="h2h_categories",
                draft_type="auction",
                team_count=12,
                roster_size=13,
                is_active=True,
            )
        )

    with database.session() as session:
        assert looks_like_a_previous_demo_seed(session) is False


def _plant_finished_game(session: Session, *, nba_game_id: str, day: int) -> NbaGame:
    """A 2025-26 game with the two teams the schema insists on.

    ``nba_games.home_team_id`` and ``away_team_id`` are NOT NULL, so a bare
    row will not insert — the planted evidence has to be a game a real ingest
    could actually have written, which is the point of planting it at all.
    """

    teams = session.scalars(select(NbaTeam).order_by(NbaTeam.id).limit(2)).all()
    if len(teams) < 2:
        for index in (1, 2):
            session.add(
                NbaTeam(
                    nba_team_id=1610612700 + index,
                    abbreviation=f"T{index}",
                    name=f"Test Team {index}",
                )
            )
        session.flush()
        teams = session.scalars(select(NbaTeam).order_by(NbaTeam.id).limit(2)).all()
    game = NbaGame(
        nba_game_id=nba_game_id,
        season="2025-26",
        game_date=date(2025, 10, day),
        status=GameStatus.FINAL,
        home_team_id=teams[0].id,
        away_team_id=teams[1].id,
    )
    session.add(game)
    session.flush()
    return game


def test_the_seed_refuses_a_real_store_that_holds_no_league(database: Database) -> None:
    """The gap found on 2026-08-23, reproduced from the real store's own shape.

    The owner's local database at ``hoops-gm-data/hoops_gm.db`` holds **0
    leagues** and **1,230 games, all 2025-26**, so both of
    ``require_safe_demo_target``'s original checks passed it cleanly — one keys
    on ``leagues``, the other only on *this* season's cohort. Driven against a
    migrated copy of it, the composed seed exited **0** and wrote 3 leagues, 2
    drafts, 10 synthetic 2026-27 games and 60 ``synthetic-demo-*`` rows that
    became the current Basketball Monster crosswalk, beside a 43,037-row
    participation ledger.

    The real store escaped only because its schema was at ``0016`` and
    ``seed_drafts`` crashed on a missing ``drafts`` table. **That is protection
    by accident**, and migrating the store removes it.

    This plants the two signals separately, because either can occur without
    the other and a test planting both at once would pass with one check
    deleted.
    """

    with database.session() as session:
        player = Player(
            full_name="Ledger Subject",
            normalized_name=normalize_name("Ledger Subject").key,
            first_name="Ledger",
            last_name="Subject",
        )
        session.add(player)
        game = _plant_finished_game(session, nba_game_id="0022500001", day=21)
        session.flush()
        session.add(
            PlayerParticipation(
                player_id=player.id,
                game_id=game.id,
                team_id=game.home_team_id,
                outcome=ParticipationOutcome.PLAYED,
            )
        )

    with pytest.raises(DemoSeedRefused) as refusal, database.session() as session:
        seed_demo(session, cohort_size=COHORT)

    # Attribution: the participation ledger is checked first, so that is the
    # refusal this must be. Naming the *other* season instead would mean the
    # ledger check never ran.
    assert "player_participation" in str(refusal.value)

    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(League)) == 0
        assert session.scalar(select(func.count()).select_from(Draft)) == 0
        assert session.scalar(select(func.count()).select_from(Projection)) == 0
        # The planted 2025-26 game is the only one: no 2026-27 cohort was
        # registered over the top of a real season.
        assert session.scalar(select(func.count()).select_from(NbaGame)) == 1


def test_the_seed_refuses_a_store_holding_another_season_with_no_ledger(
    database: Database,
) -> None:
    """The second signal alone, because a store can have games and no ledger.

    An identity-backfill-only store is exactly that shape. Separated from the
    test above so deleting either check leaves one test red rather than none —
    a single test planting both signals passes with either half removed.
    """

    with database.session() as session:
        _plant_finished_game(session, nba_game_id="0022500002", day=22)

    with pytest.raises(DemoSeedRefused) as refusal, database.session() as session:
        seed_demo(session, cohort_size=COHORT)

    assert "'2025-26'" in str(refusal.value)

    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(NbaGame)) == 1
        assert session.scalar(select(func.count()).select_from(League)) == 0


def test_the_cli_prints_proof_grouped_by_screen_and_exits_zero(
    database: Database, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """``main`` and ``proof`` end to end, because nothing else reaches them.

    Every other test here calls ``seed_demo`` directly, which means the command
    a human actually types — argument parsing, the ``_env_file=None`` choice,
    the printed proof — was covered by nothing. A seed whose *library* function
    works and whose *command* does not is the same class of gap as an endpoint
    that has never returned 200.

    The database URL comes from the ``settings`` fixture rather than a literal,
    so this runs against Postgres when ``TEST_DATABASE_URL`` is set. The
    ``database`` fixture has already built the schema, so
    ``create_schema_only_on_a_fresh_database`` correctly declines to issue DDL
    and the seed proceeds on ``require_safe_demo_target``'s judgement alone.
    """

    exit_code = main(["--database-url", settings.database_url, "--cohort-size", str(COHORT)])

    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["schedule_screen"]["league_id"] == FRONTEND_LEAGUE_ID
    assert printed["projections_screen"]["projections_written"] == COHORT
    assert printed["projections_screen"]["identities_unresolved"] == 0
    assert printed["draft_screen"]["auction_selections"] > 0
    assert printed["draft_screen"]["snake_selections"] > 0
    assert printed["frontend_expects_league_id"] == FRONTEND_LEAGUE_ID


def test_the_cli_refuses_a_short_composed_cohort_without_leaving_partial_state(
    database: Database, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """The operator sees a refusal, not a successful six-selection demo."""

    exit_code = main(["--database-url", settings.database_url, "--cohort-size", "6"])

    assert exit_code == 2
    stderr = capsys.readouterr().err
    assert "refused:" in stderr
    assert "requires 7 canonical players" in stderr
    assert "received 6" in stderr
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(NbaGame)) == 0
        assert session.scalar(select(func.count()).select_from(Projection)) == 0
        assert session.scalar(select(func.count()).select_from(League)) == 0
        assert session.scalar(select(func.count()).select_from(Draft)) == 0


def test_the_cli_exits_two_and_names_the_repeat_run_on_a_second_go(
    database: Database, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """The second thing anyone does with a seed command is run it twice.

    The refusal they get names *a league*, which reads like "your data is in
    danger" rather than "you already did this". Driven here so the sentence
    that tells them the difference cannot quietly stop being printed.
    """

    assert main(["--database-url", settings.database_url, "--cohort-size", str(COHORT)]) == 0
    capsys.readouterr()

    exit_code = main(["--database-url", settings.database_url, "--cohort-size", str(COHORT)])

    assert exit_code == 2
    stderr = capsys.readouterr().err
    assert "refused:" in stderr
    assert "reproducible from empty rather than idempotent" in stderr
    assert "Delete the database and run this command again" in stderr
