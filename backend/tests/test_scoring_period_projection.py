"""Authoritative deadline-calendar projection into ``scoring_periods``."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.calendar import (
    ScoringPeriodProjectionError,
    ScoringPeriodReplacementConflictError,
    StaleScoringPeriodProjectionError,
    activate_deadline_calendar,
    derive_deadline_calendar,
    project_scoring_periods,
    require_current_scoring_period_projection,
    scoring_period_artifact_key,
)
from hoops_gm.db.lineage import (
    NBA_SCHEDULE_ARTIFACT_KEY,
    SCHEDULE_COMPLETENESS_SUMMARY_KEY,
    current_refresh,
    record_refresh,
    schedule_content_version,
)
from hoops_gm.db.models import (
    FantasyTeam,
    League,
    LeagueDeadlineCalendar,
    LeagueSettingsSnapshot,
    Matchup,
    NbaGame,
    NbaTeam,
    RefreshRun,
    ScoringPeriod,
    TeamScheduleEntry,
)
from hoops_gm.db.models.enums import RefreshArtifactType, SeasonType
from hoops_gm.ingest.importers import import_league_settings
from hoops_gm.ingest.league_settings import (
    BRIDGE_SOURCE,
    LeagueSettingsDocument,
    PlayoffRules,
    SettingEvidence,
    SourcedSetting,
    parse_official_league_settings,
)

SEASON = "2026-27"
LEAGUE_ID = "league-period-projection"
DEFAULT_PERIODS = (
    (1, "2026-10-20T04:00:00+00:00", "2026-10-26T03:59:59+00:00"),
    (2, "2026-10-26T04:00:00+00:00", "2026-11-02T04:59:59+00:00"),
)


def _league(session: Session) -> League:
    league = League(
        name="Projection test league",
        season=SEASON,
        fantrax_league_id=LEAGUE_ID,
    )
    session.add(league)
    session.flush()
    return league


def _known_playoffs(*period_numbers: int) -> SourcedSetting[PlayoffRules]:
    return SourcedSetting(
        value=PlayoffRules(period_numbers=period_numbers),
        evidence=(
            SettingEvidence(
                source=BRIDGE_SOURCE,
                status="observed",
                source_path="League Rules > Playoffs",
                capture_ref="bridge_payload:period-test",
            ),
        ),
    )


def _document(
    *,
    periods: tuple[tuple[int, str, str], ...] = DEFAULT_PERIODS,
    playoff_numbers: tuple[int, ...] | None = (2,),
) -> LeagueSettingsDocument:
    payload: dict[str, object] = {
        "seasonYear": 2026,
        "startDate": "2026-10-20",
        "endDate": "2027-04-11",
        "scoringPeriods": [
            {"number": number, "startDate": start_at, "endDate": end_at}
            for number, start_at, end_at in periods
        ],
    }
    document = parse_official_league_settings(
        payload,
        source_league_id=LEAGUE_ID,
        capture_ref="sha256:period-test",
    )
    if playoff_numbers is None:
        return document
    return document.model_copy(update={"playoffs": _known_playoffs(*playoff_numbers)})


def _write_settings(
    session: Session,
    league: League,
    document: LeagueSettingsDocument,
    *,
    observed_at: datetime,
) -> LeagueSettingsSnapshot:
    import_league_settings(
        session,
        league=league,
        document=document,
        source_payload_sha256=hashlib.sha256(document.canonical_json().encode()).hexdigest(),
        observed_at=observed_at,
    )
    snapshot = session.scalar(
        select(LeagueSettingsSnapshot)
        .where(LeagueSettingsSnapshot.league_id == league.id)
        .order_by(LeagueSettingsSnapshot.version.desc())
        .limit(1)
    )
    assert snapshot is not None
    return snapshot


def _register_schedule(
    session: Session,
    *,
    version: str = "schedule-v1",
    refreshed_at: datetime = datetime(2026, 8, 18, tzinfo=UTC),
) -> RefreshRun:
    return record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version=version,
        source="test",
        season=SEASON,
        refreshed_at=refreshed_at,
    )


def _register_verified_schedule(session: Session) -> RefreshRun:
    home = NbaTeam(nba_team_id=1610612801, abbreviation="HME", name="Home")
    away = NbaTeam(nba_team_id=1610612802, abbreviation="AWY", name="Away")
    session.add_all([home, away])
    session.flush()
    game = NbaGame(
        nba_game_id="0022600001",
        season=SEASON,
        season_type=SeasonType.REGULAR,
        game_date=date(2026, 10, 20),
        home_team_id=home.id,
        away_team_id=away.id,
    )
    session.add(game)
    session.flush()
    session.add_all(
        [
            TeamScheduleEntry(
                season=SEASON,
                season_type=SeasonType.REGULAR,
                game_id=game.id,
                team_id=home.id,
                opponent_team_id=away.id,
                game_date=game.game_date,
                is_home=True,
            ),
            TeamScheduleEntry(
                season=SEASON,
                season_type=SeasonType.REGULAR,
                game_id=game.id,
                team_id=away.id,
                opponent_team_id=home.id,
                game_date=game.game_date,
                is_home=False,
            ),
        ]
    )
    session.flush()
    version = schedule_content_version(session, season=SEASON)
    return record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version=version,
        source="test",
        season=SEASON,
        summary={
            SCHEDULE_COMPLETENESS_SUMMARY_KEY: {
                "season": SEASON,
                "season_type": "regular",
                "source_game_count": 1,
                "resolved_game_count": 1,
                "unresolved_game_ids": [],
                "persisted_team_row_count": 2,
            }
        },
        refreshed_at=datetime(2026, 8, 18, tzinfo=UTC),
    )


def _mutate_schedule_date_without_changing_row_count(session: Session, game: NbaGame) -> None:
    game.game_date += timedelta(days=1)
    for entry in session.scalars(
        select(TeamScheduleEntry).where(TeamScheduleEntry.game_id == game.id)
    ):
        entry.game_date = game.game_date
    session.flush()


def _activate_current_calendar(
    session: Session,
    league: League,
    document: LeagueSettingsDocument,
    *,
    observed_at: datetime = datetime(2026, 8, 17, tzinfo=UTC),
) -> tuple[LeagueSettingsSnapshot, LeagueDeadlineCalendar]:
    snapshot = _write_settings(
        session,
        league,
        document,
        observed_at=observed_at,
    )
    derived = derive_deadline_calendar(session, league).calendar
    activated = activate_deadline_calendar(session, league, derived.version)
    return snapshot, activated


def test_projection_uses_eastern_dates_and_records_exact_lineage(session: Session) -> None:
    league = _league(session)
    schedule = _register_schedule(session)
    snapshot, calendar = _activate_current_calendar(session, league, _document())
    projected_at = datetime(2026, 8, 19, 12, tzinfo=UTC)

    result = project_scoring_periods(session, league, projected_at=projected_at)
    rows = tuple(
        session.scalars(
            select(ScoringPeriod)
            .where(ScoringPeriod.league_id == league.id)
            .order_by(ScoringPeriod.period_number)
        )
    )

    assert [(row.period_number, row.start_date, row.end_date, row.is_playoff) for row in rows] == [
        (1, date(2026, 10, 20), date(2026, 10, 25), False),
        (2, date(2026, 10, 26), date(2026, 11, 1), True),
    ]
    assert result.created == 2
    assert result.replaced == 0
    assert result.lineage.deadline_calendar_id == calendar.id
    assert result.lineage.deadline_calendar_version == calendar.version
    assert result.lineage.settings_snapshot_id == snapshot.id
    assert result.lineage.settings_snapshot_version == snapshot.version
    assert result.lineage.schedule_refresh_id == schedule.id
    assert result.lineage.schedule_version == schedule.version
    assert result.lineage.projection_refreshed_at == projected_at
    assert require_current_scoring_period_projection(session, league) == result.lineage

    refresh = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=scoring_period_artifact_key(league.id),
        season=SEASON,
    )
    assert refresh is not None
    assert refresh.id == result.lineage.projection_refresh_id
    assert refresh.summary["settings_snapshot_id"] == snapshot.id
    assert refresh.summary["nba_schedule_refresh_id"] == schedule.id
    assert refresh.summary["periods"] == [
        {
            "period_number": 1,
            "start_date": "2026-10-20",
            "end_date": "2026-10-25",
            "is_playoff": False,
        },
        {
            "period_number": 2,
            "start_date": "2026-10-26",
            "end_date": "2026-11-01",
            "is_playoff": True,
        },
    ]


def test_projection_refuses_to_infer_unknown_playoff_flags(session: Session) -> None:
    league = _league(session)
    _register_schedule(session)
    _activate_current_calendar(
        session,
        league,
        _document(playoff_numbers=None),
    )

    with pytest.raises(
        ScoringPeriodProjectionError,
        match="no authoritative playoff flag",
    ):
        project_scoring_periods(session, league)

    assert session.scalars(select(ScoringPeriod)).all() == []
    assert (
        current_refresh(
            session,
            RefreshArtifactType.SCHEDULE,
            artifact_key=scoring_period_artifact_key(league.id),
            season=SEASON,
        )
        is None
    )


def test_unchanged_projection_is_a_row_level_noop(session: Session) -> None:
    league = _league(session)
    _register_schedule(session)
    _activate_current_calendar(session, league, _document())

    first = project_scoring_periods(
        session,
        league,
        projected_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    first_ids = tuple(
        session.scalars(
            select(ScoringPeriod.id)
            .where(ScoringPeriod.league_id == league.id)
            .order_by(ScoringPeriod.period_number)
        )
    )
    second = project_scoring_periods(
        session,
        league,
        projected_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    second_ids = tuple(
        session.scalars(
            select(ScoringPeriod.id)
            .where(ScoringPeriod.league_id == league.id)
            .order_by(ScoringPeriod.period_number)
        )
    )

    assert second.created == 0
    assert second.replaced == 0
    assert second_ids == first_ids
    assert second.lineage.projection_version == first.lineage.projection_version
    assert second.lineage.projection_refresh_id == first.lineage.projection_refresh_id
    assert second.lineage.projection_refreshed_at > first.lineage.projection_refreshed_at


def test_changed_calendar_replaces_rows_and_preserves_projection_history(
    session: Session,
) -> None:
    league = _league(session)
    _register_schedule(session)
    _, first_calendar = _activate_current_calendar(session, league, _document())
    first = project_scoring_periods(
        session,
        league,
        projected_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    changed = _document(
        periods=(
            (1, "2026-10-20T04:00:00+00:00", "2026-10-25T03:59:59+00:00"),
            (2, "2026-10-25T04:00:00+00:00", "2026-11-02T04:59:59+00:00"),
        )
    )
    _, second_calendar = _activate_current_calendar(
        session,
        league,
        changed,
        observed_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    with pytest.raises(StaleScoringPeriodProjectionError, match="do not match"):
        require_current_scoring_period_projection(session, league)

    second = project_scoring_periods(
        session,
        league,
        projected_at=datetime(2026, 8, 21, tzinfo=UTC),
    )
    current_periods = session.scalars(
        select(ScoringPeriod)
        .where(ScoringPeriod.league_id == league.id)
        .order_by(ScoringPeriod.period_number)
    ).all()
    history = session.scalars(
        select(RefreshRun)
        .where(
            RefreshRun.artifact_type == RefreshArtifactType.SCHEDULE,
            RefreshRun.artifact_key == scoring_period_artifact_key(league.id),
        )
        .order_by(RefreshRun.id)
    ).all()

    assert second.created == 2
    assert second.replaced == 2
    assert current_periods[0].end_date == date(2026, 10, 24)
    assert current_periods[1].start_date == date(2026, 10, 25)
    assert second.lineage.projection_version != first.lineage.projection_version
    assert second.lineage.deadline_calendar_id == second_calendar.id
    assert [row.version for row in history] == [
        first.lineage.projection_version,
        second.lineage.projection_version,
    ]
    session.refresh(first_calendar)
    assert first_calendar.scoring_periods[0]["end_at"] == "2026-10-26T03:59:59+00:00"


def test_changed_projection_refuses_to_delete_referenced_matchups(session: Session) -> None:
    league = _league(session)
    _register_schedule(session)
    _activate_current_calendar(session, league, _document())
    first = project_scoring_periods(session, league)
    period = session.scalar(
        select(ScoringPeriod).where(
            ScoringPeriod.league_id == league.id,
            ScoringPeriod.period_number == 1,
        )
    )
    assert period is not None
    home = FantasyTeam(league_id=league.id, name="Home")
    away = FantasyTeam(league_id=league.id, name="Away")
    session.add_all([home, away])
    session.flush()
    session.add(
        Matchup(
            scoring_period_id=period.id,
            home_team_id=home.id,
            away_team_id=away.id,
        )
    )
    session.flush()
    original_rows = tuple(
        session.scalars(
            select(ScoringPeriod)
            .where(ScoringPeriod.league_id == league.id)
            .order_by(ScoringPeriod.period_number)
        )
    )

    changed = _document(
        periods=(
            (1, "2026-10-21T04:00:00+00:00", "2026-10-26T03:59:59+00:00"),
            (2, "2026-10-26T04:00:00+00:00", "2026-11-02T04:59:59+00:00"),
        )
    )
    _activate_current_calendar(
        session,
        league,
        changed,
        observed_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    with pytest.raises(
        ScoringPeriodReplacementConflictError,
        match="matchups reference",
    ):
        project_scoring_periods(session, league)

    assert (
        tuple(
            session.scalars(
                select(ScoringPeriod)
                .where(ScoringPeriod.league_id == league.id)
                .order_by(ScoringPeriod.period_number)
            )
        )
        == original_rows
    )
    refresh = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=scoring_period_artifact_key(league.id),
        season=SEASON,
    )
    assert refresh is not None
    assert refresh.version == first.lineage.projection_version


def test_retrograde_refresh_refuses_changed_projection_before_replacing_rows(
    session: Session,
) -> None:
    league = _league(session)
    _register_schedule(session)
    _activate_current_calendar(session, league, _document())
    first = project_scoring_periods(
        session,
        league,
        projected_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    original_rows = [
        (row.period_number, row.start_date, row.end_date, row.is_playoff)
        for row in session.scalars(
            select(ScoringPeriod)
            .where(ScoringPeriod.league_id == league.id)
            .order_by(ScoringPeriod.period_number)
        )
    ]
    changed = _document(
        periods=(
            (1, "2026-10-20T04:00:00+00:00", "2026-10-25T03:59:59+00:00"),
            (2, "2026-10-25T04:00:00+00:00", "2026-11-02T04:59:59+00:00"),
        )
    )
    _activate_current_calendar(
        session,
        league,
        changed,
        observed_at=datetime(2026, 8, 21, tzinfo=UTC),
    )

    with pytest.raises(ScoringPeriodProjectionError, match="precedes"):
        project_scoring_periods(
            session,
            league,
            projected_at=datetime(2026, 8, 19, tzinfo=UTC),
        )

    assert [
        (row.period_number, row.start_date, row.end_date, row.is_playoff)
        for row in session.scalars(
            select(ScoringPeriod)
            .where(ScoringPeriod.league_id == league.id)
            .order_by(ScoringPeriod.period_number)
        )
    ] == original_rows
    refresh = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=scoring_period_artifact_key(league.id),
        season=SEASON,
    )
    assert refresh is not None
    assert refresh.version == first.lineage.projection_version


def test_projection_rejects_a_stale_active_calendar_after_settings_change(
    session: Session,
) -> None:
    league = _league(session)
    _register_schedule(session)
    _activate_current_calendar(session, league, _document())
    project_scoring_periods(session, league)
    _write_settings(
        session,
        league,
        _document(
            periods=(
                (1, "2026-10-21T04:00:00+00:00", "2026-10-26T03:59:59+00:00"),
                (2, "2026-10-26T04:00:00+00:00", "2026-11-02T04:59:59+00:00"),
            )
        ),
        observed_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    with pytest.raises(ScoringPeriodProjectionError, match="stale settings snapshot"):
        project_scoring_periods(session, league)


def test_projection_rejects_a_stale_active_calendar_after_schedule_refresh(
    session: Session,
) -> None:
    league = _league(session)
    _register_schedule(session)
    _activate_current_calendar(session, league, _document())
    project_scoring_periods(session, league)
    _register_schedule(
        session,
        version="schedule-v2",
        refreshed_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    with pytest.raises(ScoringPeriodProjectionError, match="stale NBA schedule"):
        require_current_scoring_period_projection(session, league)


def test_projection_wraps_malformed_schedule_evidence_in_its_domain_error(
    session: Session,
) -> None:
    league = _league(session)
    schedule = _register_schedule(session)
    _activate_current_calendar(session, league, _document())
    schedule.summary = {
        SCHEDULE_COMPLETENESS_SUMMARY_KEY: {
            "season": SEASON,
            "season_type": "regular",
            "source_game_count": 0,
            "resolved_game_count": 0,
            "unresolved_game_ids": [],
            "persisted_team_row_count": 0,
        }
    }
    session.flush()

    with pytest.raises(
        ScoringPeriodProjectionError,
        match=r"schedule evidence.*malformed.*impossible all-zero refresh",
    ):
        project_scoring_periods(session, league)


def test_projection_paths_reject_a_same_row_count_schedule_mutation(session: Session) -> None:
    league = _league(session)
    schedule = _register_verified_schedule(session)
    _activate_current_calendar(session, league, _document())
    project_scoring_periods(session, league)
    game = session.scalar(select(NbaGame).where(NbaGame.season == SEASON))
    assert game is not None
    assert session.query(TeamScheduleEntry).count() == 2

    _mutate_schedule_date_without_changing_row_count(session, game)
    assert session.query(TeamScheduleEntry).count() == 2

    with pytest.raises(ScoringPeriodProjectionError, match=r"schedule evidence.*stale"):
        project_scoring_periods(session, league)
    with pytest.raises(ScoringPeriodProjectionError, match=r"schedule evidence.*stale"):
        require_current_scoring_period_projection(session, league)
    assert schedule.version != schedule_content_version(session, season=SEASON)


def test_current_projection_rejects_manual_row_mutation(session: Session) -> None:
    league = _league(session)
    _register_schedule(session)
    _activate_current_calendar(session, league, _document())
    project_scoring_periods(session, league)
    period = session.scalar(
        select(ScoringPeriod).where(
            ScoringPeriod.league_id == league.id,
            ScoringPeriod.period_number == 1,
        )
    )
    assert period is not None
    period.end_date = date(2026, 10, 24)
    session.flush()

    with pytest.raises(StaleScoringPeriodProjectionError, match="do not match"):
        require_current_scoring_period_projection(session, league)


def test_projection_rejects_inclusive_date_overlap_after_eastern_conversion(
    session: Session,
) -> None:
    league = _league(session)
    _register_schedule(session)
    document = _document(
        periods=(
            (1, "2026-10-20T04:00:00+00:00", "2026-10-25T04:30:00+00:00"),
            (2, "2026-10-25T05:00:00+00:00", "2026-11-02T04:59:59+00:00"),
        )
    )
    _activate_current_calendar(session, league, document)

    with pytest.raises(
        ScoringPeriodProjectionError,
        match="overlaps period 1",
    ):
        project_scoring_periods(session, league)


def test_projection_requires_timezone_aware_projected_at(session: Session) -> None:
    league = _league(session)

    with pytest.raises(ValueError, match="projected_at must be timezone-aware"):
        project_scoring_periods(
            session,
            league,
            projected_at=datetime(2026, 8, 19),
        )
