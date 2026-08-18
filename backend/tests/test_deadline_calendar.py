"""``league_deadline_calendars``: the versioned join of settings + schedule lineage.

Covers both the ORM contract and the deriving/activating service
(``hoops_gm.calendar.deadline_calendar``). Nothing here computes a trade
deadline, a waiver cutoff or a lineup lock -- Fantrax has never been observed
to supply those, and this module's whole point is to carry that absence
forward honestly rather than inventing a plausible value. See
``db/models/deadline_calendar.py`` and ``calendar/deadline_calendar.py`` for
the full rationale.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.app import create_app
from hoops_gm.calendar.deadline_calendar import (
    DeadlineCalendarLineageError,
    DeadlineCalendarStaleActivationError,
    activate_deadline_calendar,
    current_deadline_calendar,
    derive_deadline_calendar,
)
from hoops_gm.core.config import Settings
from hoops_gm.db.base import Base
from hoops_gm.db.lineage import record_refresh
from hoops_gm.db.models import League, LeagueDeadlineCalendar, LeagueSettingsSnapshot
from hoops_gm.db.models.enums import RefreshArtifactType
from hoops_gm.ingest.importers import import_league_settings
from hoops_gm.ingest.league_settings import (
    BRIDGE_SOURCE,
    OFFICIAL_SOURCE,
    LeagueSettingsDocument,
    PlayoffRules,
    ScoringPeriodBoundary,
    ScoringPeriodRules,
    SettingEvidence,
    SourcedSetting,
    TradeDeadlineRules,
    parse_official_league_settings,
)

SEASON = "2025-26"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _official_payload() -> dict[str, object]:
    return {
        "seasonYear": 2025,
        "startDate": "2025-10-21",
        "endDate": "2026-03-15",
        "rosterInfo": {
            "positionConstraints": {"G": {"maxActive": 4}},
            "maxTotalPlayers": 14,
            "maxTotalActivePlayers": 10,
            "maxTotalReservePlayers": 4,
        },
        "scoringPeriods": [
            {
                "number": 1,
                "startDate": "2026-10-20T00:00:00-04:00",
                "endDate": "2026-10-25T23:59:59-04:00",
            },
            {
                # Crosses the DST transition inside one season: the source's
                # own boundary, not something this module may reinterpret.
                "number": 2,
                "startDate": "2026-10-26T00:00:00-04:00",
                "endDate": "2026-11-01T23:59:59-05:00",
            },
            {
                # An All-Star / combined-week style gap: 14 days wide rather
                # than the usual 7. Nothing in this module may assume a
                # uniform cadence.
                "number": 3,
                "startDate": "2026-11-02T00:00:00-05:00",
                "endDate": "2026-11-15T23:59:59-05:00",
            },
        ],
    }


def _document(**overrides: object) -> LeagueSettingsDocument:
    document = parse_official_league_settings(
        _official_payload(),
        source_league_id="league-1",
        capture_ref="sha256:abc",
    )
    return document.model_copy(update=overrides) if overrides else document


def _known_trade_deadline(deadline_at: str) -> SourcedSetting[TradeDeadlineRules]:
    return SourcedSetting(
        value=TradeDeadlineRules(deadline_at=deadline_at),
        evidence=(
            SettingEvidence(
                source=BRIDGE_SOURCE,
                status="observed",
                source_path="League Rules > Trade Deadline",
                capture_ref="bridge_payload:1",
            ),
        ),
    )


def _known_playoffs(period_numbers: tuple[int, ...]) -> SourcedSetting[PlayoffRules]:
    return SourcedSetting(
        value=PlayoffRules(period_numbers=period_numbers),
        evidence=(
            SettingEvidence(
                source=OFFICIAL_SOURCE,
                status="observed",
                source_path="$.scoringPeriods[*].isPlayoffs",
                capture_ref="sha256:abc",
            ),
        ),
    )


def _known_scoring_periods(
    *periods: tuple[int, str, str],
) -> SourcedSetting[ScoringPeriodRules]:
    return SourcedSetting(
        value=ScoringPeriodRules(
            periods=tuple(
                ScoringPeriodBoundary(period_number=number, start_at=start_at, end_at=end_at)
                for number, start_at, end_at in periods
            )
        ),
        evidence=(
            SettingEvidence(
                source=OFFICIAL_SOURCE,
                status="observed",
                source_path="$.scoringPeriods",
                capture_ref="sha256:abc",
            ),
        ),
    )


def _league(session: Session, *, fantrax_league_id: str = "league-1") -> League:
    league = League(name="Test League", season=SEASON, fantrax_league_id=fantrax_league_id)
    session.add(league)
    session.flush()
    return league


def _write_settings(
    session: Session,
    league: League,
    document: LeagueSettingsDocument,
    *,
    observed_at: datetime | None = None,
) -> LeagueSettingsSnapshot:
    import_league_settings(
        session,
        league=league,
        document=document,
        source_payload_sha256=_sha256(document.canonical_json()),
        observed_at=observed_at or datetime(2026, 8, 17, tzinfo=UTC),
    )
    [snapshot] = (
        session.query(LeagueSettingsSnapshot)
        .filter(LeagueSettingsSnapshot.league_id == league.id)
        .order_by(LeagueSettingsSnapshot.version.desc())
        .limit(1)
        .all()
    )
    return snapshot


def _register_schedule(
    session: Session, *, version: str = "sched-1", refreshed_at: datetime | None = None
) -> None:
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        version=version,
        season=SEASON,
        source="test",
        refreshed_at=refreshed_at or datetime(2026, 8, 18, tzinfo=UTC),
    )


# --------------------------------------------------------------------------
# ORM contract
# --------------------------------------------------------------------------


def test_the_table_is_registered_and_created(session: Session) -> None:
    inspector = inspect(session.get_bind())
    assert "league_deadline_calendars" in inspector.get_table_names()
    assert "league_deadline_calendars" in Base.metadata.tables


def _bare_calendar(
    league: League, snapshot: LeagueSettingsSnapshot, **overrides: object
) -> LeagueDeadlineCalendar:
    values: dict[str, object] = {
        "league_id": league.id,
        "version": 1,
        "schema_version": "1",
        "season": SEASON,
        "settings_snapshot_id": snapshot.id,
        "settings_snapshot_version": snapshot.version,
        "schedule_version": "sched-1",
        "schedule_refreshed_at": datetime(2026, 8, 18, tzinfo=UTC),
        "season_start_date": date(2025, 10, 21),
        "season_end_date": date(2026, 3, 15),
        "scoring_periods": [],
        "unsupported_rules": {},
        "derived_at": datetime(2026, 8, 19, tzinfo=UTC),
    }
    values.update(overrides)
    return LeagueDeadlineCalendar(**values)


def test_a_duplicate_version_for_the_same_league_is_rejected(session: Session) -> None:
    league = _league(session)
    snapshot = _write_settings(session, league, _document())
    session.add(_bare_calendar(league, snapshot, version=1))
    session.flush()

    session.add(_bare_calendar(league, snapshot, version=1, schedule_version="sched-2"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_season_end_date_must_not_precede_start_date(session: Session) -> None:
    league = _league(session)
    snapshot = _write_settings(session, league, _document())
    session.add(
        _bare_calendar(
            league,
            snapshot,
            season_start_date=date(2026, 3, 15),
            season_end_date=date(2025, 10, 21),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_only_one_row_may_be_current_at_a_time(session: Session) -> None:
    league = _league(session)
    snapshot = _write_settings(session, league, _document())
    session.add(_bare_calendar(league, snapshot, version=1, current_for_league=league.id))
    session.flush()

    session.add(
        _bare_calendar(
            league, snapshot, version=2, schedule_version="sched-2", current_for_league=league.id
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_the_current_marker_must_match_its_own_league(session: Session) -> None:
    league_a = _league(session, fantrax_league_id="league-a")
    league_b = _league(session, fantrax_league_id="league-b")
    snapshot = _write_settings(session, league_a, _document(source_league_id="league-a"))
    session.add(_bare_calendar(league_a, snapshot, current_for_league=league_b.id))

    with pytest.raises(IntegrityError):
        session.flush()


def test_deleting_the_league_cascades_to_its_calendars(session: Session) -> None:
    league = _league(session)
    snapshot = _write_settings(session, league, _document())
    session.add(_bare_calendar(league, snapshot))
    session.flush()

    session.delete(league)
    session.flush()

    assert session.query(LeagueDeadlineCalendar).count() == 0


def test_deleting_the_settings_snapshot_cascades_to_calendars_referencing_it(
    session: Session,
) -> None:
    league = _league(session)
    snapshot = _write_settings(session, league, _document())
    session.add(_bare_calendar(league, snapshot))
    session.flush()

    session.delete(snapshot)
    session.flush()

    assert session.query(LeagueDeadlineCalendar).count() == 0


# --------------------------------------------------------------------------
# derive_deadline_calendar
# --------------------------------------------------------------------------


def test_deriving_fails_closed_when_no_settings_snapshot_exists(session: Session) -> None:
    league = _league(session)
    _register_schedule(session)

    with pytest.raises(DeadlineCalendarLineageError, match="no league-settings snapshot"):
        derive_deadline_calendar(session, league)


def test_deriving_fails_closed_when_no_schedule_refresh_exists(session: Session) -> None:
    league = _league(session)
    _write_settings(session, league, _document())

    with pytest.raises(DeadlineCalendarLineageError, match="no registered schedule refresh"):
        derive_deadline_calendar(session, league)


def test_deriving_fails_closed_on_a_season_mismatch(session: Session) -> None:
    """A snapshot cannot normally disagree with its own league (importer guards
    that at write time -- see ``import_league_settings``), but this module must
    not *trust* that guard blindly: it re-checks identity itself against
    whatever row is actually current, in case the two ever drift apart (a
    league's season is edited after the fact, a snapshot is copied between
    fixtures, etc.). Write the mismatched row directly, bypassing the importer,
    to exercise that defense.
    """
    league = League(name="Wrong Season League", season="2024-25", fantrax_league_id="league-1")
    session.add(league)
    session.flush()
    document = _document()
    session.add(
        LeagueSettingsSnapshot(
            league_id=league.id,
            version=1,
            schema_version=str(document.schema_version),
            settings=document.model_dump(mode="json"),
            source_summary={},
            source_payload_sha256=_sha256("mismatched"),
            observed_at=datetime(2026, 8, 17, tzinfo=UTC),
        )
    )
    session.flush()
    _register_schedule(session)

    with pytest.raises(DeadlineCalendarLineageError, match="identity mismatch"):
        derive_deadline_calendar(session, league)


def test_deriving_fails_closed_when_official_scoring_periods_are_omitted(
    session: Session,
) -> None:
    """A production-realistic gap: the official ``getLeagueInfo`` response
    simply never included ``scoringPeriods`` (a normal, non-error absence at
    the parsing layer -- see ``_parse_scoring_periods``). A calendar derived
    from that has no scoring-period boundaries to expose, so it must raise
    rather than silently persist ``[]`` as if zero periods were confirmed.
    """
    league = _league(session)
    payload = _official_payload()
    del payload["scoringPeriods"]
    document = parse_official_league_settings(
        payload, source_league_id="league-1", capture_ref="sha256:abc"
    )
    assert document.scoring_periods.is_known is False
    _write_settings(session, league, document)
    _register_schedule(session)

    with pytest.raises(DeadlineCalendarLineageError, match="scoring_periods is unknown"):
        derive_deadline_calendar(session, league)

    assert session.query(LeagueDeadlineCalendar).count() == 0


def test_deriving_fails_closed_when_season_end_precedes_start(session: Session) -> None:
    league = _league(session)
    _write_settings(
        session,
        league,
        _document(source_start_date="2026-03-15", source_end_date="2025-10-21"),
    )
    _register_schedule(session)

    with pytest.raises(DeadlineCalendarLineageError, match="season_end_date"):
        derive_deadline_calendar(session, league)

    assert session.query(LeagueDeadlineCalendar).count() == 0


def test_deriving_fails_closed_on_duplicate_scoring_period_numbers(session: Session) -> None:
    league = _league(session)
    _write_settings(
        session,
        league,
        _document(
            scoring_periods=_known_scoring_periods(
                (1, "2026-10-20T00:00:00-04:00", "2026-10-25T23:59:59-04:00"),
                (1, "2026-10-26T00:00:00-04:00", "2026-11-01T23:59:59-04:00"),
            )
        ),
    )
    _register_schedule(session)

    with pytest.raises(DeadlineCalendarLineageError, match="duplicate scoring_periods"):
        derive_deadline_calendar(session, league)

    assert session.query(LeagueDeadlineCalendar).count() == 0


def test_deriving_fails_closed_when_a_scoring_period_end_does_not_follow_its_start(
    session: Session,
) -> None:
    league = _league(session)
    _write_settings(
        session,
        league,
        _document(
            scoring_periods=_known_scoring_periods(
                (1, "2026-10-20T00:00:00-04:00", "2026-10-20T00:00:00-04:00"),
            )
        ),
    )
    _register_schedule(session)

    with pytest.raises(DeadlineCalendarLineageError, match="must be after start_at"):
        derive_deadline_calendar(session, league)

    assert session.query(LeagueDeadlineCalendar).count() == 0


def test_season_bounds_are_taken_verbatim_from_settings(session: Session) -> None:
    league = _league(session)
    _write_settings(session, league, _document())
    _register_schedule(session)

    result = derive_deadline_calendar(session, league)

    assert result.created is True
    assert result.calendar.season_start_date == date(2025, 10, 21)
    assert result.calendar.season_end_date == date(2026, 3, 15)


def test_scoring_period_boundaries_preserve_timezone_offsets_across_a_dst_transition(
    session: Session,
) -> None:
    league = _league(session)
    _write_settings(session, league, _document())
    _register_schedule(session)

    result = derive_deadline_calendar(session, league)
    periods = {p["period_number"]: p for p in result.calendar.scoring_periods}

    assert periods[1]["start_at"] == "2026-10-20T00:00:00-04:00"
    assert periods[2]["end_at"] == "2026-11-01T23:59:59-05:00"


def test_a_combined_week_gap_passes_through_without_a_cadence_assumption(
    session: Session,
) -> None:
    league = _league(session)
    _write_settings(session, league, _document())
    _register_schedule(session)

    result = derive_deadline_calendar(session, league)
    periods = {p["period_number"]: p for p in result.calendar.scoring_periods}
    combined_week = periods[3]

    start = datetime.fromisoformat(str(combined_week["start_at"]))
    end = datetime.fromisoformat(str(combined_week["end_at"]))
    assert (end - start).days >= 13


def test_playoff_flag_is_none_not_false_when_the_source_never_said(session: Session) -> None:
    league = _league(session)
    _write_settings(session, league, _document())
    _register_schedule(session)

    result = derive_deadline_calendar(session, league)

    assert all(period["is_playoff"] is None for period in result.calendar.scoring_periods)


def test_playoff_flag_is_populated_when_the_source_supplied_it(session: Session) -> None:
    league = _league(session)
    _write_settings(session, league, _document(playoffs=_known_playoffs((3,))))
    _register_schedule(session)

    result = derive_deadline_calendar(session, league)
    periods = {p["period_number"]: p for p in result.calendar.scoring_periods}

    assert periods[1]["is_playoff"] is False
    assert periods[3]["is_playoff"] is True


def test_unsupported_rules_stay_explicit_unknowns_when_absent(session: Session) -> None:
    league = _league(session)
    _write_settings(session, league, _document())
    _register_schedule(session)

    result = derive_deadline_calendar(session, league)
    unsupported = result.calendar.unsupported_rules

    for field in ("lineup_lock", "waivers", "trade_deadline", "keepers"):
        entry = unsupported[field]
        assert isinstance(entry, dict)
        assert entry["value"] is None
        assert entry["evidence"], f"{field} must still carry evidence explaining the absence"


def test_a_bridge_supplied_trade_deadline_flows_through_unaltered(session: Session) -> None:
    league = _league(session)
    _write_settings(
        session,
        league,
        _document(trade_deadline=_known_trade_deadline("2027-02-11T23:59:00-05:00")),
    )
    _register_schedule(session)

    result = derive_deadline_calendar(session, league)
    trade_deadline = result.calendar.unsupported_rules["trade_deadline"]

    assert isinstance(trade_deadline, dict)
    assert trade_deadline["value"] == {"deadline_at": "2027-02-11T23:59:00-05:00"}


def test_a_naive_scoring_period_timestamp_is_rejected(session: Session) -> None:
    league = _league(session)
    payload = _official_payload()
    scoring_periods = payload["scoringPeriods"]
    assert isinstance(scoring_periods, list)
    first_period = scoring_periods[0]
    assert isinstance(first_period, dict)
    first_period["startDate"] = "2026-10-20T00:00:00"  # no offset: naive
    document = parse_official_league_settings(
        payload, source_league_id="league-1", capture_ref="sha256:abc"
    )
    _write_settings(session, league, document)
    _register_schedule(session)

    with pytest.raises(DeadlineCalendarLineageError, match="naive timestamp"):
        derive_deadline_calendar(session, league)


def test_deriving_again_over_unchanged_lineage_is_idempotent(session: Session) -> None:
    league = _league(session)
    _write_settings(session, league, _document())
    _register_schedule(session)

    first = derive_deadline_calendar(session, league)
    second = derive_deadline_calendar(session, league)

    assert first.calendar.id == second.calendar.id
    assert second.created is False
    assert session.query(LeagueDeadlineCalendar).count() == 1


def test_new_schedule_lineage_opens_the_next_version_without_altering_the_prior_row(
    session: Session,
) -> None:
    league = _league(session)
    _write_settings(session, league, _document())
    _register_schedule(session, version="sched-1")

    first = derive_deadline_calendar(session, league)
    _register_schedule(session, version="sched-2", refreshed_at=datetime(2026, 8, 19, tzinfo=UTC))
    second = derive_deadline_calendar(session, league)

    assert second.created is True
    assert second.calendar.version == first.calendar.version + 1
    assert second.calendar.schedule_version == "sched-2"
    # the prior row is untouched
    session.refresh(first.calendar)
    assert first.calendar.schedule_version == "sched-1"


# --------------------------------------------------------------------------
# activate_deadline_calendar / current_deadline_calendar
# --------------------------------------------------------------------------


def test_current_deadline_calendar_is_none_before_any_activation(session: Session) -> None:
    league = _league(session)
    _write_settings(session, league, _document())
    _register_schedule(session)
    derive_deadline_calendar(session, league)

    assert current_deadline_calendar(session, league) is None


def test_activation_makes_a_calendar_current(session: Session) -> None:
    league = _league(session)
    _write_settings(session, league, _document())
    _register_schedule(session)
    derived = derive_deadline_calendar(session, league)

    activated = activate_deadline_calendar(session, league, derived.calendar.version)

    assert activated.id == derived.calendar.id
    current = current_deadline_calendar(session, league)
    assert current is not None
    assert current.id == derived.calendar.id


def test_activating_an_unknown_version_fails_closed(session: Session) -> None:
    league = _league(session)
    _write_settings(session, league, _document())
    _register_schedule(session)
    derive_deadline_calendar(session, league)

    with pytest.raises(DeadlineCalendarLineageError, match="no deadline calendar version"):
        activate_deadline_calendar(session, league, 99)


def test_a_to_b_to_a_activation_cycle(session: Session) -> None:
    league = _league(session)
    _write_settings(session, league, _document())
    _register_schedule(session, version="sched-1", refreshed_at=datetime(2026, 8, 18, tzinfo=UTC))
    v1 = derive_deadline_calendar(session, league).calendar
    activate_deadline_calendar(session, league, v1.version)
    assert current_deadline_calendar(session, league).id == v1.id  # type: ignore[union-attr]

    _register_schedule(session, version="sched-2", refreshed_at=datetime(2026, 8, 19, tzinfo=UTC))
    v2 = derive_deadline_calendar(session, league).calendar
    activate_deadline_calendar(session, league, v2.version)
    assert current_deadline_calendar(session, league).id == v2.id  # type: ignore[union-attr]

    # Reactivating v1 while sched-2 is still current must fail closed: its
    # own recorded schedule lineage ("sched-1") is no longer the season's
    # current schedule.
    with pytest.raises(DeadlineCalendarStaleActivationError):
        activate_deadline_calendar(session, league, v1.version)
    assert current_deadline_calendar(session, league).id == v2.id  # type: ignore[union-attr]

    # Schedule content genuinely returns to "sched-1" (re-registered as the
    # season's current refresh again) -- now reactivating v1 is legitimate.
    _register_schedule(session, version="sched-1", refreshed_at=datetime(2026, 8, 20, tzinfo=UTC))
    activate_deadline_calendar(session, league, v1.version)

    current = current_deadline_calendar(session, league)
    assert current is not None
    assert current.id == v1.id
    session.refresh(v2)
    assert v2.current_for_league is None


def test_activation_fails_closed_when_settings_lineage_has_moved_on(session: Session) -> None:
    league = _league(session)
    _write_settings(session, league, _document())
    _register_schedule(session)
    v1 = derive_deadline_calendar(session, league).calendar

    # A new settings snapshot supersedes the one v1 was derived from.
    _write_settings(
        session,
        league,
        _document(trade_deadline=_known_trade_deadline("2027-02-11T23:59:00-05:00")),
        observed_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    with pytest.raises(DeadlineCalendarStaleActivationError):
        activate_deadline_calendar(session, league, v1.version)


# --------------------------------------------------------------------------
# HTTP contract
# --------------------------------------------------------------------------


def test_current_deadline_calendar_endpoint_returns_404_before_activation(
    app: FastAPI, client: TestClient
) -> None:
    with app.state.database.session() as session:
        league = _league(session)
        league_id = league.id

    response = client.get(f"/api/v1/leagues/{league_id}/deadline-calendar/current")

    assert response.status_code == 404


def test_current_deadline_calendar_endpoint_returns_the_active_calendar(
    app: FastAPI, client: TestClient
) -> None:
    with app.state.database.session() as session:
        league = _league(session)
        league_id = league.id
        _write_settings(session, league, _document())
        _register_schedule(session)
        derived = derive_deadline_calendar(session, league)
        activate_deadline_calendar(session, league, derived.calendar.version)

    response = client.get(f"/api/v1/leagues/{league_id}/deadline-calendar/current")

    assert response.status_code == 200
    body = response.json()
    assert body["season"] == SEASON
    assert body["season_start_date"] == "2025-10-21"
    unsupported = body["unsupported_rules"]
    assert unsupported["trade_deadline"]["value"] is None


def test_deadline_calendar_contract_is_advertised_in_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/leagues/{league_id}/deadline-calendar/current" in paths


def test_current_deadline_calendar_endpoint_rejects_a_non_loopback_caller(
    tmp_path: Path,
) -> None:
    """A real client is exempted only by an actual loopback address; the
    ``environment == "test"`` escape hatch every other test in this file
    relies on (via the default ``app``/``client`` fixtures) exists purely
    because Starlette's ``TestClient`` reports a synthetic ``testclient``
    host. This test proves the guard itself, not the escape hatch, by using
    a non-``test`` environment the way ``test_userscript_serving.py`` does.
    """
    settings = Settings(
        environment="development",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        bridge_secret_path=tmp_path / "bridge_secret",
        _env_file=None,
    )
    app = create_app(settings)
    with TestClient(app) as non_local_client:
        Base.metadata.create_all(app.state.database.engine)
        with app.state.database.session() as session:
            league = _league(session)
            league_id = league.id

        response = non_local_client.get(f"/api/v1/leagues/{league_id}/deadline-calendar/current")

    assert response.status_code == 403
    assert response.json()["error"] == "deadline_calendar_local_only"
