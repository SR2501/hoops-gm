"""The reliability route: one operational proof, and one test per refusal.

**The acceptance test calls the route.** ``compute_reliability_scorecards``
already had unit coverage before this endpoint existed and none of it could
tell whether the computation was reachable over HTTP — the gap this unit
closes is exactly the one a coverage number passes vacuously. So the assertion
that matters here is a 200 from ``GET /api/v1/reliability/scorecards`` with a
non-empty ``scorecards`` list, computed from rows a production writer put in
the store the route reads.

**The success-path state is published by ``publish_reliability_cohorts``**,
which is ``quant``'s producer and the same function
``hoops_gm.dev.publish_reliability_evidence`` calls. This file never writes a
``refresh_runs`` row for the reliability cohort itself. It does write
``team_schedule`` rows directly, and that is a real narrowing worth stating:
the full derive-the-schedule path is driven at 1,230-game scale in
``test_publish_reliability_evidence.py``, and repeating it per refusal here
would buy nothing and cost a second each.

Most refusal tests start from that same genuinely-serving state and break
exactly one thing, so a 409 is evidence the broken thing caused it rather than
evidence the endpoint was never reachable. Two do not, and saying "every"
would be false: the not-published case has an empty store by construction,
because "nothing has published a claim" has no valid state to break.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from hoops_gm.api.routes.reliability import EVIDENCE_SEASON, published_claim
from hoops_gm.availability import OBSERVED_COVERAGE_STATUS, publish_reliability_cohorts
from hoops_gm.availability.reliability import (
    RELIABILITY_SOURCE_KEY,
    ReliabilityCohortClaim,
)
from hoops_gm.db.lineage import (
    SCHEDULE_COMPLETENESS_SUMMARY_KEY,
    record_refresh,
    schedule_content_version,
)
from hoops_gm.db.models import (
    DnpReason,
    ExternalSource,
    GameStatus,
    NbaGame,
    NbaTeam,
    ParticipationOutcome,
    Player,
    PlayerGameLog,
    PlayerParticipation,
    RefreshArtifactType,
    RefreshRun,
    SeasonType,
    TeamScheduleEntry,
)

URL = "/api/v1/reliability/scorecards"
AS_OF = date(2026, 1, 8)
GAME_DATES = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 8))


def _error_of(response: Any) -> str:
    return str(response.json()["error"])


def _cohort(session: Session) -> tuple[Player, Player]:
    """A tiny but genuinely coherent season: two teams, three games, two players.

    The third game is the day after the second, so ``build_schedule_density``
    marks it a back-to-back and the ``back_to_back`` evidence on the wire is
    computed rather than empty.
    """

    home = NbaTeam(nba_team_id=1610612737, abbreviation="HOM", name="Home")
    away = NbaTeam(nba_team_id=1610612738, abbreviation="AWY", name="Away")
    session.add_all([home, away])
    session.flush()

    games = []
    for index, game_date in enumerate(GAME_DATES, start=1):
        game = NbaGame(
            season=EVIDENCE_SEASON,
            season_type=SeasonType.REGULAR,
            nba_game_id=f"00225{index:05d}",
            game_date=game_date,
            status=GameStatus.FINAL,
            home_team_id=home.id,
            away_team_id=away.id,
            home_score=110,
            away_score=100,
        )
        session.add(game)
        session.flush()
        session.add_all(
            [
                TeamScheduleEntry(
                    season=EVIDENCE_SEASON,
                    season_type=SeasonType.REGULAR,
                    game_id=game.id,
                    team_id=home.id,
                    opponent_team_id=away.id,
                    game_date=game_date,
                    is_home=True,
                ),
                TeamScheduleEntry(
                    season=EVIDENCE_SEASON,
                    season_type=SeasonType.REGULAR,
                    game_id=game.id,
                    team_id=away.id,
                    opponent_team_id=home.id,
                    game_date=game_date,
                    is_home=False,
                ),
            ]
        )
        games.append(game)
    session.flush()

    available = Player(full_name="Iron Man", normalized_name="ironman")
    fragile = Player(full_name="Glass Cannon", normalized_name="glasscannon")
    session.add_all([available, fragile])
    session.flush()

    for index, game in enumerate(games):
        session.add(_log(available, game, home, seconds=1800 + index * 120))
        if index == 0:
            session.add(_log(fragile, game, away, seconds=2100))
        else:
            session.add(
                PlayerParticipation(
                    player_id=fragile.id,
                    game_id=game.id,
                    team_id=away.id,
                    outcome=ParticipationOutcome.INACTIVE,
                    reason=DnpReason.INJURY_OR_ILLNESS,
                    raw_comment="",
                    source=ExternalSource.NBA,
                    inactive_list_available=True,
                )
            )
    session.flush()
    _register_schedule(session)
    return available, fragile


def _log(player: Player, game: NbaGame, team: NbaTeam, *, seconds: int) -> PlayerGameLog:
    return PlayerGameLog(
        player_id=player.id,
        game_id=game.id,
        team_id=team.id,
        seconds_played=seconds,
        field_goals_made=5,
        field_goals_attempted=10,
        three_pointers_made=2,
        three_pointers_attempted=5,
        free_throws_made=4,
        free_throws_attempted=5,
        points=20,
        offensive_rebounds=1,
        defensive_rebounds=4,
        rebounds=5,
        assists=4,
        steals=1,
        blocks=1,
        turnovers=2,
        personal_fouls=2,
        plus_minus=0,
    )


def _register_schedule(session: Session) -> None:
    """The verifiable schedule refresh ``publish_reliability_cohorts`` requires.

    Written with the completeness block ``import_schedule`` writes, read back
    off the rows just persisted, because ``_require_current`` re-derives the
    content version and refuses a summary that disagrees with the table.
    """

    entries = session.scalars(
        select(TeamScheduleEntry).where(TeamScheduleEntry.season == EVIDENCE_SEASON)
    ).all()
    game_count = len({entry.game_id for entry in entries})
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key="nba-schedule",
        version=schedule_content_version(session, season=EVIDENCE_SEASON),
        source="test:canonical-schedule",
        season=EVIDENCE_SEASON,
        summary={
            SCHEDULE_COMPLETENESS_SUMMARY_KEY: {
                "season": EVIDENCE_SEASON,
                "season_type": "regular",
                "source_game_count": game_count,
                "resolved_game_count": game_count,
                "unresolved_game_ids": [],
                "persisted_team_row_count": len(entries),
            }
        },
        refreshed_at=datetime(2026, 1, 9, tzinfo=UTC),
    )


def _serving_store(app: FastAPI) -> ReliabilityCohortClaim:
    with app.state.database.session() as session:
        _cohort(session)
        claim = publish_reliability_cohorts(session, season=EVIDENCE_SEASON, as_of_date=AS_OF)
        session.commit()
    return claim


def test_the_route_serves_scorecards_computed_from_the_store_it_reads(
    app: FastAPI, client: TestClient
) -> None:
    """The unit's done-condition, asserted through HTTP.

    Not "``compute_reliability_scorecards`` returns something" — that was
    already true and already tested while five quantities sat unexposed. This
    asserts the computation is reachable, which is the only thing that was
    missing.
    """

    claim = _serving_store(app)

    response = client.get(URL)

    assert response.status_code == 200, response.json()
    body = response.json()
    assert len(body["scorecards"]) == 2
    assert body["counts"] == {
        "scorecards": 2,
        "scheduled_team_games": 6,
        "schedule_context_team_games": 6,
        "final_games": 3,
        "player_game_logs": 4,
        "participation_rows": 2,
    }
    fragile = min(body["scorecards"], key=lambda card: card["production"]["played_games"])
    assert fragile["availability"]["overall"] == {
        "direct_play": 1,
        "direct_non_play": 2,
        "explicit_unknown": 0,
        "observed_opportunities": 3,
        "observed_play_rate": pytest.approx(1 / 3),
        "observed_non_play_rate": pytest.approx(2 / 3),
        "coverage_status": OBSERVED_COVERAGE_STATUS,
        "opportunity_coverage": None,
    }
    assert fragile["availability"]["back_to_back"]["direct_non_play"] == 1
    assert body["lineage"]["source_version"] == claim.source_version


def test_a_scorecard_names_the_player_it_is_about(app: FastAPI, client: TestClient) -> None:
    """596 opaque integers are not an exposed quantity.

    The defect excluded: a consumer receives the cohort and cannot render a
    single row of it. This is not hypothetical — when this route first returned
    200 against the owner's real store it produced 596 scorecards keyed only on
    ``player_id``, and no other route could resolve them. The one endpoint
    carrying player names, ``/leagues/{league_id}/projections/current``, is
    league-scoped, and that store has zero leagues.

    The reading in which this assertion is false and the defect present is a
    payload carrying ids alone, which is exactly what shipped for one commit.
    The second half drives the null branch. It does so with a *blank*
    ``full_name``, not a deleted ``players`` row — an earlier draft of this
    docstring said "a scorecard whose ``players`` row has gone", which review
    showed is unreachable: the ``player_game_logs`` and ``player_participation``
    foreign keys are ``ondelete="CASCADE"`` and SQLite enforcement is on, so
    deleting the player deletes the evidence the scorecard is built from. The
    branch that genuinely produces null is the ``if full_name`` filter in
    ``_player_names``. Either way the assertion is the same: report ``None``
    rather than inventing a name, because a stringified id in a name field is a
    placeholder no downstream reader can tell from a real one.
    """

    _serving_store(app)

    body = client.get(URL).json()

    by_name = {card["player_name"]: card for card in body["scorecards"]}
    assert set(by_name) == {"Iron Man", "Glass Cannon"}
    assert by_name["Glass Cannon"]["production"]["played_games"] == 1

    with app.state.database.session() as session:
        orphaned = session.scalars(select(Player).where(Player.full_name == "Glass Cannon")).one()
        orphaned.full_name = ""
        session.commit()

    after = client.get(URL).json()
    nameless = [card for card in after["scorecards"] if card["player_name"] is None]
    assert len(nameless) == 1, (
        "a scorecard with no resolvable name did not report null, so the name "
        "is not being joined and the assertion above excludes nothing"
    )


def test_the_season_the_evidence_is_from_is_named_rather_than_inferred(
    app: FastAPI, client: TestClient
) -> None:
    """A durability figure whose season is ambiguous is the ``gameEt`` shape.

    The defect excluded is a consumer rendering last season's durability beside
    a 2026-27 roster with nothing in the payload to say so. A reading in which
    this passes and the defect is present would need the consumer to receive
    ``season`` and ignore it — which is outside what a response schema can
    exclude, and is why the field is at the top level and in ``lineage`` rather
    than in a comment.
    """

    _serving_store(app)

    body = client.get(URL).json()

    assert body["season"] == EVIDENCE_SEASON == "2025-26"
    assert body["season_type"] == "regular"
    assert body["lineage"]["season"] == EVIDENCE_SEASON
    assert body["lineage"]["as_of_date"] == AS_OF.isoformat()
    assert body["lineage"]["window_start"] == GAME_DATES[0].isoformat()


def test_the_season_is_not_a_query_parameter(app: FastAPI, client: TestClient) -> None:
    """An unknown query parameter changes nothing, so no caller can widen it."""

    _serving_store(app)

    assert client.get(URL, params={"season": "2026-27"}).json()["season"] == EVIDENCE_SEASON
    assert URL not in {
        path
        for path, spec in client.get("/openapi.json").json()["paths"].items()
        if any(
            parameter.get("name") == "season"
            for operation in spec.values()
            for parameter in operation.get("parameters", [])
        )
    }


def test_the_wire_carries_evidence_counts_and_not_seventy_thousand_row_ids(
    app: FastAPI, client: TestClient
) -> None:
    """``RateEvidence`` holds every contributing row id; the response must not.

    The defect excluded is an order-of-magnitude payload for evidence no screen
    renders. The counts below are the same evidence at the resolution a reader
    uses, so this is a narrowing of the response, not a loss of it.
    """

    _serving_store(app)

    body = client.get(URL).json()

    overall = body["scorecards"][0]["availability"]["overall"]
    assert "game_log_ids" not in overall
    assert "participation_ids" not in overall
    assert overall["direct_play"] + overall["direct_non_play"] == overall["observed_opportunities"]
    assert "_ids" not in json.dumps(body)


def test_the_published_claim_is_read_back_exactly(app: FastAPI, client: TestClient) -> None:
    """The round-trip that keeps this route's reader honest.

    ``published_claim`` reconstructs a claim from ``refresh_runs`` rows a
    different module wrote. ``schedule_grid`` shipped a consumer-side reader of
    a producer's summary once and it read flat keys the producer never wrote,
    which made the endpoint permanently unavailable while its tests asserted
    200 three times. The protection here is that the reader's output is
    compared against the producer's return value, so a renamed summary key
    fails this test rather than degrading the route.

    The reading in which this passes and that defect is present would require
    ``publish_reliability_cohorts`` and ``published_claim`` to be wrong in the
    same direction — which is what comparing against the producer, rather than
    against a literal written in this file, is what excludes.
    """

    claim = _serving_store(app)

    with app.state.database.session() as session:
        assert published_claim(session, season=EVIDENCE_SEASON) == claim
    assert client.get(URL).status_code == 200


def test_refuses_a_store_where_nothing_has_published_a_claim(client: TestClient) -> None:
    response = client.get(URL)

    assert response.status_code == 409
    assert _error_of(response) == "reliability_not_published"
    assert "publish_reliability_evidence" in response.json()["detail"]


def test_refuses_a_published_claim_whose_summary_does_not_state_its_cohort(
    app: FastAPI, client: TestClient
) -> None:
    """A refresh row that exists but does not say what it published."""

    _serving_store(app)
    with app.state.database.session() as session:
        session.execute(
            update(RefreshRun)
            .where(RefreshRun.artifact_key == RELIABILITY_SOURCE_KEY)
            .values(summary={"claim": "descriptive direct observations"})
        )
        session.commit()

    response = client.get(URL)

    assert response.status_code == 409
    assert _error_of(response) == "reliability_incomplete_evidence"
    assert "does not state the cohort it published" in response.json()["detail"]


def test_refuses_when_the_rows_moved_under_the_published_claim(
    app: FastAPI, client: TestClient
) -> None:
    """Republishing is the operator action, which is why this is its own code."""

    _serving_store(app)
    with app.state.database.session() as session:
        log = session.scalars(select(PlayerGameLog).order_by(PlayerGameLog.id).limit(1)).one()
        log.seconds_played = 42
        session.commit()

    response = client.get(URL)

    assert response.status_code == 409
    assert _error_of(response) == "reliability_not_current"


def test_refuses_when_a_schedule_row_is_deleted_under_the_published_claim(
    app: FastAPI, client: TestClient
) -> None:
    """Deleting a schedule row refuses at the schedule cohort check, before the join.

    **The refusal is real but an earlier draft named the wrong mechanism inside
    it.** It said the deletion "moves the schedule fingerprint, and is caught
    there". The fingerprint does move — and the code never gets as far as
    comparing it. ``verify_refresh`` raises ``ValueError`` first on the
    completeness arithmetic, because the stored evidence claims 6 persisted team
    rows while 5 are present, and ``_require_current`` converts that to
    ``cannot verify``. The ``is_current`` fingerprint comparison is unreachable
    for this input.

    Driven, not read: the response detail is ``cannot verify current
    schedule:nba-schedule cohort for season 2025-26``, and an independent review
    bypassed both the ``is_current`` and version comparisons with all tests still
    passing. The detail is asserted below rather than only the error code,
    because ``reliability_not_current`` is shared by at least three distinct
    mechanisms and the code alone pins none of them.

    This test previously claimed to drive the home/away coverage join at
    ``reliability.py:508`` and accepted either ``reliability_not_current`` or
    ``reliability_inputs_refused``. An independent review drove it: the input
    only ever produces the **former**, because ``_require_current(SCHEDULE)`` at
    ``:357`` runs before ``_source_snapshot`` at ``:383``. So the assertion could
    not fail for the reason it named, and the docstring's "the schedule row count
    is still even" was false as well — the fixture goes from 6 rows to 5.

    Split into two tests rather than tightened in place, because both mechanisms
    are real and each needs an input that reaches it. The coverage join is
    driven by :func:`test_refuses_a_final_game_with_no_schedule_coverage_at_all`.
    """

    _serving_store(app)
    with app.state.database.session() as session:
        last = max(
            session.scalars(select(NbaGame)).all(), key=lambda game: (game.game_date, game.id)
        )
        entry = session.scalars(
            select(TeamScheduleEntry)
            .where(TeamScheduleEntry.game_id == last.id, TeamScheduleEntry.is_home.is_(False))
            .limit(1)
        ).one()
        session.delete(entry)
        session.commit()

    response = client.get(URL)

    assert response.status_code == 409
    assert _error_of(response) == "reliability_not_current"
    assert response.json()["detail"] == (
        "cannot verify current schedule:nba-schedule cohort for season 2025-26"
    ), "the error code is shared by several mechanisms; the detail is what pins this one"


def test_refuses_a_final_game_with_no_schedule_coverage_at_all(
    app: FastAPI, client: TestClient
) -> None:
    """The join condition between ``team_schedule`` and ``nba_games``.

    This is the check with no honest done-condition on either table alone, and
    the reason this unit was not split: a final game in the window must have
    exactly its two schedule rows, which is a property of neither table.

    The input has to be chosen so the *earlier* refusals do not fire first.
    Adding a final ``nba_games`` row with no schedule rows leaves every existing
    ``team_schedule`` row untouched, so ``schedule_content_version`` does not
    move and ``_require_current(SCHEDULE)`` still passes — the request reaches
    ``:508`` and is refused there. That is exactly the state an ingest closing
    green on "rows landed" leaves behind: a game the schedule does not cover.
    """

    _serving_store(app)
    with app.state.database.session() as session:
        covered = session.scalars(select(NbaGame).order_by(NbaGame.game_date)).first()
        assert covered is not None
        session.add(
            NbaGame(
                season=EVIDENCE_SEASON,
                season_type=SeasonType.REGULAR,
                nba_game_id="0022599999",
                game_date=covered.game_date,
                status=GameStatus.FINAL,
                home_team_id=covered.home_team_id,
                away_team_id=covered.away_team_id,
                home_score=101,
                away_score=99,
            )
        )
        session.commit()

    response = client.get(URL)

    assert response.status_code == 409
    assert _error_of(response) == "reliability_inputs_refused", response.json()
    assert "exact home/away" in response.json()["detail"]
