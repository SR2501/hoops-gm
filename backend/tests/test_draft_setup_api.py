"""The read contract used to build an explicit draft creation request."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.app import create_app
from hoops_gm.core.config import Settings
from hoops_gm.db.base import Base
from hoops_gm.db.models.enums import DraftType
from hoops_gm.db.models.league import FantasyTeam, League
from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot
from hoops_gm.ingest.importers import import_league_settings
from hoops_gm.ingest.league_settings import parse_official_league_settings


def _league(
    session: Session,
    *,
    name: str = "Auction league",
    draft_type: DraftType = DraftType.AUCTION,
    roster_size: int = 13,
    budget: Decimal | None = Decimal("200.00"),
    team_names: tuple[str, ...] = ("Zulu", "alpha", "Beta"),
    team_count: int | None = None,
    owner_index: int | None = 0,
    with_settings: bool = False,
) -> League:
    league = League(
        fantrax_league_id=f"fantrax-{name.lower().replace(' ', '-')}",
        name=name,
        season="2026-27",
        draft_type=draft_type,
        team_count=len(team_names) if team_count is None else team_count,
        roster_size=roster_size,
        auction_budget=budget,
    )
    session.add(league)
    session.flush()
    for index, team_name in enumerate(team_names):
        session.add(
            FantasyTeam(
                league_id=league.id,
                fantrax_team_id=f"external-{league.id}-{index}",
                name=team_name,
                short_name=f"T{index}",
                owner_name=f"Owner {index}",
                is_owner_team=index == owner_index,
            )
        )
    session.flush()
    if with_settings:
        document = parse_official_league_settings(
            {
                "seasonYear": 2026,
                "startDate": "2026-10-20",
                "endDate": "2027-03-21",
                "rosterInfo": {"maxTotalPlayers": roster_size},
            },
            source_league_id=cast(str, league.fantrax_league_id),
            capture_ref=f"fixture:league-{league.id}",
        )
        counts = import_league_settings(
            session,
            league=league,
            document=document,
            source_payload_sha256=f"{league.id:064x}",
            observed_at=datetime(2026, 9, 5, 12, tzinfo=UTC),
        )
        assert counts.created == 1, (
            "The setup read must be exercised over a production-written snapshot."
        )
    session.commit()
    session.refresh(league)
    return league


def _setup(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/v1/drafts/setup")
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def test_setup_returns_an_explicit_empty_collection(client: TestClient) -> None:
    assert _setup(client) == {"leagues": []}


def test_setup_returns_one_production_persisted_auction_cohort(
    client: TestClient,
    session: Session,
) -> None:
    league = _league(session, with_settings=True)

    payload = _setup(client)

    assert payload == {
        "leagues": [
            {
                "league_id": league.id,
                "name": "Auction league",
                "season": "2026-27",
                "format": {
                    "draft_type": "auction",
                    "team_count": 3,
                    "roster_size": 13,
                    "total_roster_slots": 39,
                    "auction_budget": "200.00",
                },
                "owner_fantasy_team_id": next(
                    team.id for team in league.fantasy_teams if team.name == "Zulu"
                ),
                "fantasy_teams": [
                    {
                        "fantasy_team_id": next(
                            team.id for team in league.fantasy_teams if team.name == name
                        ),
                        "display_name": name,
                    }
                    for name in ("alpha", "Beta", "Zulu")
                ],
            }
        ]
    }
    assert set(payload["leagues"][0]["fantasy_teams"][0]) == {
        "fantasy_team_id",
        "display_name",
    }, "External Fantrax ids and owner metadata are not part of the setup contract."


def test_setup_orders_multiple_leagues_by_persisted_id_and_keeps_owner_unassigned(
    client: TestClient,
    session: Session,
) -> None:
    first = _league(session, name="First", team_names=("A", "B"))
    second = _league(
        session,
        name="Snake league",
        draft_type=DraftType.SNAKE,
        budget=None,
        team_names=("East", "West"),
        owner_index=None,
    )

    leagues = _setup(client)["leagues"]

    assert [row["league_id"] for row in leagues] == [first.id, second.id]
    assert leagues[1]["owner_fantasy_team_id"] is None
    assert leagues[1]["format"] == {
        "draft_type": "snake",
        "team_count": 2,
        "roster_size": 13,
        "total_roster_slots": 26,
        "auction_budget": None,
    }
    assert all(
        set(team) == {"fantasy_team_id", "display_name"}
        for league in leagues
        for team in league["fantasy_teams"]
    ), "Team array order must not masquerade as team_slot or source_seat."


@pytest.mark.parametrize(
    ("team_names", "team_count", "expected_error"),
    [
        (("Only one",), 2, "draft_participants_incomplete"),
        (("Owner one", "Owner two"), 2, "draft_multiple_owner_seats"),
        (("Named", "   "), 2, "draft_participant_name_required"),
    ],
    ids=["missing-team", "ambiguous-owner", "missing-display-name"],
)
def test_setup_refuses_incomplete_or_ambiguous_participant_evidence(
    client: TestClient,
    session: Session,
    team_names: tuple[str, ...],
    team_count: int,
    expected_error: str,
) -> None:
    owner_index = 0
    _league(
        session,
        team_names=team_names,
        team_count=team_count,
        owner_index=owner_index,
    )
    if expected_error == "draft_multiple_owner_seats":
        teams = session.scalars(select(FantasyTeam)).all()
        assert len(teams) == 2
        for team in teams:
            team.is_owner_team = True
        session.commit()

    response = client.get("/api/v1/drafts/setup")

    assert response.status_code == 422
    assert response.json()["error"] == expected_error


def test_setup_refuses_a_malformed_format_without_defaulting_it(
    client: TestClient,
    session: Session,
) -> None:
    _league(
        session,
        draft_type=DraftType.UNKNOWN,
        budget=None,
        team_names=("A", "B"),
    )

    response = client.get("/api/v1/drafts/setup")

    assert response.status_code == 422
    assert response.json()["error"] == "draft_format_invalid"


def test_setup_refuses_a_malformed_current_settings_snapshot(
    client: TestClient,
    session: Session,
) -> None:
    league = _league(session, with_settings=True)
    snapshot = session.scalar(
        select(LeagueSettingsSnapshot).where(LeagueSettingsSnapshot.league_id == league.id)
    )
    assert snapshot is not None
    snapshot.settings = {"schema_version": 2}
    session.commit()

    response = client.get("/api/v1/drafts/setup")

    assert response.status_code == 422
    assert response.json()["error"] == "draft_setup_settings_invalid"


def test_setup_refuses_a_mismatched_current_settings_schema_declaration(
    client: TestClient,
    session: Session,
) -> None:
    league = _league(session, with_settings=True)
    snapshot = session.scalar(
        select(LeagueSettingsSnapshot).where(LeagueSettingsSnapshot.league_id == league.id)
    )
    assert snapshot is not None
    snapshot.schema_version = "stale-schema"
    session.commit()

    response = client.get("/api/v1/drafts/setup")

    assert response.status_code == 422
    assert response.json()["error"] == "draft_setup_settings_invalid"


def test_setup_refuses_current_settings_for_a_stale_league_identity(
    client: TestClient,
    session: Session,
) -> None:
    league = _league(session, with_settings=True)
    snapshot = session.scalar(
        select(LeagueSettingsSnapshot).where(LeagueSettingsSnapshot.league_id == league.id)
    )
    assert snapshot is not None
    stale = dict(snapshot.settings)
    stale["source_league_id"] = "a-different-league"
    snapshot.settings = stale
    session.commit()

    response = client.get("/api/v1/drafts/setup")

    assert response.status_code == 422
    assert response.json()["error"] == "draft_setup_settings_stale"
    assert "source league identity" in response.json()["detail"]
    assert "a-different-league" not in response.json()["detail"]
    assert cast(str, league.fantrax_league_id) not in response.json()["detail"]


def test_setup_refuses_current_settings_for_a_stale_season(
    client: TestClient,
    session: Session,
) -> None:
    league = _league(session, with_settings=True)
    snapshot = session.scalar(
        select(LeagueSettingsSnapshot).where(LeagueSettingsSnapshot.league_id == league.id)
    )
    assert snapshot is not None
    stale = dict(snapshot.settings)
    stale["source_season_year"] = 2025
    snapshot.settings = stale
    session.commit()

    response = client.get("/api/v1/drafts/setup")

    assert response.status_code == 422
    assert response.json()["error"] == "draft_setup_settings_stale"
    assert "season" in response.json()["detail"]
    assert "2025-26" not in response.json()["detail"]
    assert league.season not in response.json()["detail"]


def test_setup_refuses_current_settings_that_contradict_the_frozen_roster_size(
    client: TestClient,
    session: Session,
) -> None:
    league = _league(session, with_settings=True)
    changed = parse_official_league_settings(
        {
            "seasonYear": 2026,
            "startDate": "2026-10-20",
            "endDate": "2027-03-21",
            "rosterInfo": {"maxTotalPlayers": 12},
        },
        source_league_id=cast(str, league.fantrax_league_id),
        capture_ref="fixture:changed-roster-size",
    )
    counts = import_league_settings(
        session,
        league=league,
        document=changed,
        source_payload_sha256="f" * 64,
        observed_at=datetime(2026, 9, 5, 13, tzinfo=UTC),
    )
    session.commit()
    assert counts.created == 1
    assert session.scalars(
        select(LeagueSettingsSnapshot.version)
        .where(LeagueSettingsSnapshot.league_id == league.id)
        .order_by(LeagueSettingsSnapshot.version)
    ).all() == [1, 2]

    response = client.get("/api/v1/drafts/setup")

    assert response.status_code == 422
    assert response.json()["error"] == "draft_setup_settings_stale"
    assert "roster size (12 in settings, 13 persisted)" in response.json()["detail"]


def test_setup_refusal_does_not_return_a_partial_multi_league_collection(
    client: TestClient,
    session: Session,
) -> None:
    _league(session, name="Valid", team_names=("A", "B"))
    invalid = _league(session, name="Invalid", team_names=("Only one",), team_count=2)

    response = client.get("/api/v1/drafts/setup")

    assert response.status_code == 422
    assert response.json()["error"] == "draft_participants_incomplete"
    assert str(invalid.id) in response.json()["detail"]


def test_setup_is_loopback_only(tmp_path: Path) -> None:
    settings = Settings(
        environment="development",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        bridge_secret_path=tmp_path / "bridge_secret",
        _env_file=None,
    )
    app = create_app(settings)
    with TestClient(app) as non_local_client:
        Base.metadata.create_all(app.state.database.engine)
        response = non_local_client.get("/api/v1/drafts/setup")

    assert response.status_code == 403
    assert response.json()["error"] == "drafts_local_only"


def test_setup_openapi_contract_exposes_only_the_required_read_fields(
    client: TestClient,
) -> None:
    document = cast(FastAPI, client.app).openapi()
    operation = document["paths"]["/api/v1/drafts/setup"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/DraftSetupResponse"
    }

    schemas = document["components"]["schemas"]
    assert set(schemas["DraftSetupLeagueOut"]["properties"]) == {
        "league_id",
        "name",
        "season",
        "format",
        "owner_fantasy_team_id",
        "fantasy_teams",
    }
    assert set(schemas["DraftSetupTeamOut"]["properties"]) == {
        "fantasy_team_id",
        "display_name",
    }
