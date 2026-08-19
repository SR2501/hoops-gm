"""Historical injury-report backfill: candidate derivation, plan, run, resume.

Every test here is offline: fetching and parsing are injected at seams
(``fetch_and_parse``) so no test needs a real PDF or a real network call —
the same seam ``client.py``'s own ``opener`` uses for the transport layer.
The one real fixture PDF this project keeps
(``nba_injury_report_2025-11-01_0530pm.pdf``) is reused for a single test that
exercises ``default_fetch_and_parse`` end-to-end against a fake transport, to
prove the seam is wired correctly, not to build a corpus.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, select

from hoops_gm.db.models.enums import InjuryReportStatus, SeasonType
from hoops_gm.db.models.identity import NbaTeam, Player
from hoops_gm.db.models.injury_report import (
    CURRENT_EVIDENCE_SCHEMA_VERSION,
    LEGACY_EVIDENCE_SCHEMA_VERSION,
    InjuryReportEntry,
)
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.injury_report import backfill as backfill_module
from hoops_gm.ingest.injury_report.backfill import (
    CURRENT_COVERAGE_SCHEMA_VERSION,
    LEGACY_COVERAGE_SCHEMA_VERSION,
    NO_CACHE,
    BackfillBudgetExceeded,
    BackfillGame,
    CandidateCoverage,
    Checkpoint,
    CoverageReport,
    CoverageScopeMismatch,
    ExpectedGameCoverage,
    IncompleteExpectedGameCoverage,
    IncompleteScheduleCoverage,
    MissingTipoffGame,
    ReportCandidate,
    SuspectedSourceBlock,
    _coverage_merge_key,
    _expected_coverage_matches_scope,
    _expected_schedule_season_type_label,
    _floor_to_quarter_hour_et,
    _merge_coverage,
    _persist_coverage,
    build_plan,
    candidate_report_timestamps,
    coverage_for_games,
    default_coverage_path,
    default_expected_coverage_path,
    default_fetch_and_parse,
    enforce_expected_game_coverage,
    enforce_full_tipoff_coverage,
    enforce_request_budget,
    exclusion_cascade,
    games_to_backfill,
    main,
    render_exclusion_cascade,
    render_observation_coverage,
    run_backfill,
    select_canonical_pregame_observations,
    write_coverage_report,
    write_expected_game_coverage,
)
from hoops_gm.ingest.injury_report.client import ReportNotAvailable, report_url
from hoops_gm.ingest.injury_report.models import InjuryReportEntryRecord, InjuryReportParseResult
from hoops_gm.ingest.injury_report.parser import ENDPOINT, SOURCE
from hoops_gm.ingest.nba.models import NbaGameRecord
from hoops_gm.ingest.rawstore import RawPayloadStore

pytestmark = pytest.mark.adapter_contract

EASTERN = ZoneInfo("America/New_York")
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_PDF = FIXTURES / "nba_injury_report_2025-11-01_0530pm.pdf"


def _et(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=EASTERN)


def _seed_teams(session: Any) -> dict[str, int]:
    kings = NbaTeam(nba_team_id=1610612758, abbreviation="SAC", name="Sacramento Kings")
    bucks = NbaTeam(nba_team_id=1610612749, abbreviation="MIL", name="Milwaukee Bucks")
    session.add_all([kings, bucks])
    session.flush()
    return {"SAC": kings.id, "MIL": bucks.id}


def _seed_game(
    session: Any,
    *,
    nba_game_id: str,
    game_date: date,
    tipoff_utc: datetime | None,
    home_team_id: int,
    away_team_id: int,
    season: str = "2025-26",
    season_type: SeasonType = SeasonType.REGULAR,
) -> NbaGame:
    game = NbaGame(
        nba_game_id=nba_game_id,
        season=season,
        season_type=season_type,
        game_date=game_date,
        tipoff_utc=tipoff_utc,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
    )
    session.add(game)
    session.flush()
    return game


def _entry(
    *,
    report_timestamp: datetime,
    team_raw: str = "Sacramento Kings",
    player_name_raw: str = "Murray, Keegan",
    status: InjuryReportStatus = InjuryReportStatus.OUT,
    matchup_raw: str = "SAC@MIL",
    game_date: date = date(2025, 11, 1),
) -> InjuryReportEntryRecord:
    return InjuryReportEntryRecord(
        report_timestamp=report_timestamp,
        game_date=game_date,
        game_time_raw="05:00 (ET)",
        matchup_raw=matchup_raw,
        team_raw=team_raw,
        player_name_raw=player_name_raw,
        status_raw=status.value.title(),
        status=status,
    )


# ==========================================================================
# Candidate derivation
# ==========================================================================


def test_candidate_timestamps_are_evening_before_and_game_day_no_invention() -> None:
    candidates = candidate_report_timestamps(date(2025, 11, 2))
    by_anchor = {c.anchor: c for c in candidates}
    assert by_anchor["evening_before"].report_timestamp == _et(2025, 11, 1, 17, 30)
    assert by_anchor["game_day"].report_timestamp == _et(2025, 11, 2, 13, 0)
    assert all(c.report_date == date(2025, 11, 2) for c in candidates)


def test_candidate_timestamps_use_near_tip_offsets_in_the_fifteen_minute_era() -> None:
    """Post-2025-12-22: a fixed 13:00 ET guess is replaced by tip-off-relative offsets.

    ``report_url`` does not round to the source's own 15-minute marks in this
    era (see ``client.py``), so a single fixed wall-clock anchor is a blind
    exact-minute gamble. The bounded ``NEAR_TIP_OFFSETS`` set, anchored to
    the date's own earliest applicable tip-off, replaces it.
    """
    tipoff = _et(2025, 12, 25, 22, 0)  # in the 15-minute era
    candidates = candidate_report_timestamps(date(2025, 12, 25), earliest_tipoff_utc=tipoff)
    by_anchor = {c.anchor: c for c in candidates}

    assert "game_day" not in by_anchor  # the fixed-clock guess is not used in this era
    assert by_anchor["evening_before"].report_timestamp == _et(2025, 12, 24, 17, 30)
    near_tip_anchors = {c.anchor for c in candidates if c.anchor.startswith("near_tip_")}
    assert near_tip_anchors == {"near_tip_150", "near_tip_90", "near_tip_45", "near_tip_15"}
    for candidate in candidates:
        if candidate.anchor.startswith("near_tip_"):
            expected_lead = int(candidate.anchor.removeprefix("near_tip_"))
            assert candidate.anchor_offset_minutes == expected_lead
            assert candidate.report_timestamp == tipoff - timedelta(minutes=expected_lead)
            # No-lookahead: every near-tip candidate is strictly before tip-off.
            assert candidate.report_timestamp < tipoff
        else:
            assert candidate.anchor_offset_minutes is None


def test_candidate_timestamps_align_near_tip_offsets_to_the_source_15_minute_grid() -> None:
    """A non-grid-aligned tip-off (19:10 ET) must not produce off-grid candidates.

    Round-4 correction (independent review, point 4): the 15-minute-era URL
    is an exact-minute match against the source's own ``:00``/``:15``/``:30``/
    ``:45`` grid. A fixed offset subtracted from a non-grid-aligned tip-off
    (here, 19:10, not on the grid) lands on an off-grid minute the source can
    never have published at, no matter how close the guess is in real time.
    Every near-tip candidate must be floored to the grid, strictly before
    tip-off, never rounded forward past it.
    """
    tipoff = _et(2025, 12, 25, 19, 10)  # 15-minute era, deliberately off-grid
    candidates = candidate_report_timestamps(date(2025, 12, 25), earliest_tipoff_utc=tipoff)
    near_tip = [c for c in candidates if c.anchor.startswith("near_tip_")]
    assert near_tip  # precondition: the 15-minute-era branch actually ran

    for candidate in near_tip:
        assert candidate.report_timestamp.minute in (0, 15, 30, 45)
        assert candidate.report_timestamp.second == 0
        # No-lookahead, preserved even after flooring: never at or after tip-off.
        assert candidate.report_timestamp < tipoff

    by_anchor = {c.anchor: c.report_timestamp for c in near_tip}
    # 19:10 - 150m = 16:40 -> floored to 16:30; etc. Computed independently
    # here (not by calling the function under test) to actually pin the values.
    assert by_anchor["near_tip_150"] == _et(2025, 12, 25, 16, 30)
    assert by_anchor["near_tip_90"] == _et(2025, 12, 25, 17, 30)
    assert by_anchor["near_tip_45"] == _et(2025, 12, 25, 18, 15)
    assert by_anchor["near_tip_15"] == _et(2025, 12, 25, 18, 45)


def test_candidate_timestamps_align_near_tip_offsets_for_a_second_off_grid_tipoff() -> None:
    """A second non-aligned tip-off (19:40 ET), to guard against a single-case fluke."""
    tipoff = _et(2025, 12, 26, 19, 40)
    candidates = candidate_report_timestamps(date(2025, 12, 26), earliest_tipoff_utc=tipoff)
    near_tip = [c for c in candidates if c.anchor.startswith("near_tip_")]
    for candidate in near_tip:
        assert candidate.report_timestamp.minute in (0, 15, 30, 45)
        assert candidate.report_timestamp < tipoff

    by_anchor = {c.anchor: c.report_timestamp for c in near_tip}
    assert by_anchor["near_tip_150"] == _et(2025, 12, 26, 17, 0)
    assert by_anchor["near_tip_90"] == _et(2025, 12, 26, 18, 0)
    assert by_anchor["near_tip_45"] == _et(2025, 12, 26, 18, 45)
    assert by_anchor["near_tip_15"] == _et(2025, 12, 26, 19, 15)


def test_floor_to_quarter_hour_et_floors_never_rounds() -> None:
    """Unit-level pin for the grid-alignment primitive itself."""
    assert _floor_to_quarter_hour_et(_et(2025, 12, 25, 18, 44)) == _et(2025, 12, 25, 18, 30)
    assert _floor_to_quarter_hour_et(_et(2025, 12, 25, 18, 45)) == _et(2025, 12, 25, 18, 45)
    assert _floor_to_quarter_hour_et(_et(2025, 12, 25, 18, 0)) == _et(2025, 12, 25, 18, 0)


def test_candidate_timestamps_collapse_near_tip_offsets_that_floor_to_the_same_grid_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two distinct offsets that floor to the same instant collapse to one candidate.

    Regression for the dedup mechanism itself: with the project's real
    ``NEAR_TIP_OFFSETS`` (150/90/45/15 minutes, each a multiple of 15) two
    offsets can never collide against a real tip-off, since the minimum gap
    between them (30 minutes) exceeds the maximum distortion flooring can
    introduce (under 15 minutes) — this test monkeypatches a closer offset
    pair to actually exercise the collision path, which is otherwise
    unreachable with the shipped constants.
    """
    import hoops_gm.ingest.injury_report.backfill as backfill_module

    monkeypatch.setattr(
        backfill_module,
        "NEAR_TIP_OFFSETS",
        (timedelta(minutes=25), timedelta(minutes=16)),
    )
    tipoff = _et(2025, 12, 25, 19, 0)
    candidates = candidate_report_timestamps(date(2025, 12, 25), earliest_tipoff_utc=tipoff)
    near_tip = [c for c in candidates if c.anchor.startswith("near_tip_")]

    # 19:00 - 25m = 18:35 -> floors to 18:30; 19:00 - 16m = 18:44 -> also floors to 18:30.
    assert len(near_tip) == 1
    assert near_tip[0].report_timestamp == _et(2025, 12, 25, 18, 30)
    # The larger (more conservative) lead time keeps its label rather than
    # being silently replaced by the later-processed, shorter-lead offset.
    assert near_tip[0].anchor == "near_tip_25"
    assert near_tip[0].anchor_offset_minutes == 25


def test_candidate_timestamps_fall_back_to_game_day_anchor_without_a_known_tipoff() -> None:
    """A 15-minute-era date with no ingested tip-off yet cannot be tip-off-relative.

    Falls back to the legacy fixed-clock guess rather than silently omitting
    a second candidate — a strictly worse guess is preferable to giving up,
    and the caller still gets ``evening_before`` in either case.
    """
    candidates = candidate_report_timestamps(date(2025, 12, 25), earliest_tipoff_utc=None)
    by_anchor = {c.anchor for c in candidates}
    assert by_anchor == {"evening_before", "game_day"}


# ==========================================================================
# Games in scope / missing tip-off
# ==========================================================================


def test_games_to_backfill_splits_ready_from_missing_tipoff(session: Any) -> None:
    teams = _seed_teams(session)
    ready_game = _seed_game(
        session,
        nba_game_id="0022500100",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    missing_game = _seed_game(
        session,
        nba_game_id="0022500101",
        game_date=date(2025, 11, 2),
        tipoff_utc=None,
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)

    assert [g.game_id for g in ready] == [ready_game.id]
    assert [g.game_id for g in missing] == [missing_game.id]


def test_games_to_backfill_filters_by_season_type_and_date_range(session: Any) -> None:
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="playoff-1",
        game_date=date(2026, 5, 1),
        tipoff_utc=_et(2026, 5, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
        season_type=SeasonType.PLAYOFFS,
    )
    in_range = _seed_game(
        session,
        nba_game_id="regular-in-range",
        game_date=date(2025, 12, 1),
        tipoff_utc=_et(2025, 12, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    _seed_game(
        session,
        nba_game_id="regular-out-of-range",
        game_date=date(2026, 1, 1),
        tipoff_utc=_et(2026, 1, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )

    ready, _ = games_to_backfill(
        session,
        season="2025-26",
        season_type=SeasonType.REGULAR,
        start=date(2025, 11, 15),
        end=date(2025, 12, 15),
    )

    assert [g.game_id for g in ready] == [in_range.id]


# ==========================================================================
# Plan: applicability (no lookahead) and cache awareness
# ==========================================================================


def test_plan_excludes_a_candidate_that_would_look_ahead_of_every_game_that_date(
    session: Any,
) -> None:
    """A noon tip-off on the game date makes the 13:00 ET anchor pointless.

    Uses a legacy-era date (before 2025-12-22) deliberately: this test is
    about the fixed-clock ``game_day`` anchor, which only applies pre-boundary
    — see ``test_plan_uses_near_tip_candidates_in_the_fifteen_minute_era``
    for the era this date would otherwise fall into.

    Exercises "games with no expected [game-day] report": the plan must not
    invent a request whose own timestamp is already after every game it could
    possibly apply to.
    """
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="legacy-early",
        game_date=date(2025, 12, 10),
        tipoff_utc=_et(2025, 12, 10, 12, 0),  # noon ET, before the 13:00 anchor
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )

    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)

    anchors_for_date = {
        pf.candidate.anchor for pf in plan.fetches if pf.candidate.report_date == date(2025, 12, 10)
    }
    assert anchors_for_date == {"evening_before"}


def test_plan_selection_around_tipoff_splits_applicability_per_game(session: Any) -> None:
    """Two legacy-era games on one date: only the later one is reachable by the game-day anchor."""
    teams = _seed_teams(session)
    early = _seed_game(
        session,
        nba_game_id="early-tip",
        game_date=date(2025, 12, 10),
        tipoff_utc=_et(2025, 12, 10, 12, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    late = _seed_game(
        session,
        nba_game_id="late-tip",
        game_date=date(2025, 12, 10),
        tipoff_utc=_et(2025, 12, 10, 22, 0),
        home_team_id=teams["SAC"],
        away_team_id=teams["MIL"],
    )

    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)

    game_day = next(
        pf
        for pf in plan.fetches
        if pf.candidate.report_date == date(2025, 12, 10) and pf.candidate.anchor == "game_day"
    )
    assert set(game_day.applicable_game_ids) == {late.id}
    evening_before = next(
        pf
        for pf in plan.fetches
        if pf.candidate.report_date == date(2025, 12, 10)
        and pf.candidate.anchor == "evening_before"
    )
    assert set(evening_before.applicable_game_ids) == {early.id, late.id}


def test_plan_reports_missing_tipoff_games_loudly_rather_than_skipping_silently(
    session: Any,
) -> None:
    teams = _seed_teams(session)
    missing = _seed_game(
        session,
        nba_game_id="no-tipoff-yet",
        game_date=date(2025, 11, 5),
        tipoff_utc=None,
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )

    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)

    assert [mg.game_id for mg in plan.missing_tipoff] == [missing.id]
    assert not any(pf.candidate.report_date == date(2025, 11, 5) for pf in plan.fetches)


def test_plan_marks_a_candidate_already_cached(session: Any, tmp_path: Path) -> None:
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="cached-game",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    store = RawPayloadStore(tmp_path)
    evening_before = _et(2025, 11, 1, 17, 30)
    store.put(
        source=SOURCE, endpoint=ENDPOINT, params={"url": report_url(evening_before)}, body=b"%PDF-x"
    )

    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR, store=store)

    evening_before_fetch = next(
        pf
        for pf in plan.fetches
        if pf.candidate.report_date == date(2025, 11, 2) and pf.candidate.anchor == "evening_before"
    )
    assert evening_before_fetch.already_cached is True
    game_day_fetch = next(
        pf
        for pf in plan.fetches
        if pf.candidate.report_date == date(2025, 11, 2) and pf.candidate.anchor == "game_day"
    )
    assert game_day_fetch.already_cached is False
    assert len(plan.to_fetch) == 1


def test_build_plan_anchors_near_tip_candidates_to_the_dates_own_earliest_tipoff(
    session: Any,
) -> None:
    """A 15-minute-era date's near-tip candidates use that date's real games, not a fixed clock."""
    teams = _seed_teams(session)
    early = _seed_game(
        session,
        nba_game_id="fifteen-min-early",
        game_date=date(2025, 12, 25),
        tipoff_utc=_et(2025, 12, 25, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    late = _seed_game(
        session,
        nba_game_id="fifteen-min-late",
        game_date=date(2025, 12, 25),
        tipoff_utc=_et(2025, 12, 25, 22, 0),
        home_team_id=teams["SAC"],
        away_team_id=teams["MIL"],
    )

    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)

    that_date = [pf for pf in plan.fetches if pf.candidate.report_date == date(2025, 12, 25)]
    anchors = {pf.candidate.anchor for pf in that_date}
    assert "game_day" not in anchors  # fixed-clock guess is not used in this era
    assert {"near_tip_150", "near_tip_90", "near_tip_45", "near_tip_15"} <= anchors

    # Anchored to the EARLIEST game that date (19:00), not the later one.
    near_tip_45 = next(pf for pf in that_date if pf.candidate.anchor == "near_tip_45")
    assert near_tip_45.candidate.report_timestamp == _et(2025, 12, 25, 19, 0) - timedelta(
        minutes=45
    )
    # No lookahead: this candidate is applicable to both games (before both tip-offs).
    assert set(near_tip_45.applicable_game_ids) == {early.id, late.id}


# ==========================================================================
# Fail-closed tipoff coverage
# ==========================================================================


def test_enforce_full_tipoff_coverage_refuses_an_incomplete_range_by_default(
    session: Any,
) -> None:
    """22 reachable games out of 527 requested must not look cohort-ready."""
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="has-tipoff",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    _seed_game(
        session,
        nba_game_id="missing-tipoff",
        game_date=date(2025, 11, 2),
        tipoff_utc=None,
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )

    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)
    assert len(plan.missing_tipoff) == 1

    with pytest.raises(IncompleteScheduleCoverage):
        enforce_full_tipoff_coverage(plan)

    # An explicit, disclosed override is the only way past the gate.
    enforce_full_tipoff_coverage(plan, allow_missing=1)  # does not raise


def test_enforce_full_tipoff_coverage_passes_a_fully_scheduled_range(session: Any) -> None:
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="fully-scheduled",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )

    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)
    enforce_full_tipoff_coverage(plan)  # does not raise: nothing is missing


# ==========================================================================
# Request budget
# ==========================================================================


def test_enforce_request_budget_raises_before_any_network_call(session: Any) -> None:
    teams = _seed_teams(session)
    for i in range(5):
        _seed_game(
            session,
            nba_game_id=f"budget-{i}",
            game_date=date(2025, 11, 1) + timedelta(days=i),
            tipoff_utc=_et(2025, 11, 1, 19, 0) + timedelta(days=i),
            home_team_id=teams["MIL"],
            away_team_id=teams["SAC"],
        )

    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)
    assert len(plan.to_fetch) > 1

    with pytest.raises(BackfillBudgetExceeded):
        enforce_request_budget(plan, max_requests=1)

    enforce_request_budget(plan, max_requests=len(plan.to_fetch))  # does not raise


def test_enforce_request_budget_counts_every_candidate_when_forcing_refetch(
    session: Any, tmp_path: Path
) -> None:
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="force-refetch",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    store = RawPayloadStore(tmp_path)
    evening_before = _et(2025, 11, 1, 17, 30)
    store.put(
        source=SOURCE, endpoint=ENDPOINT, params={"url": report_url(evening_before)}, body=b"%PDF-x"
    )

    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR, store=store)
    assert len(plan.to_fetch) == 1  # one of the two is cached

    # Without forcing, the cached one does not count toward the budget.
    enforce_request_budget(plan, max_requests=1)
    # Forcing counts every candidate, cached or not.
    with pytest.raises(BackfillBudgetExceeded):
        enforce_request_budget(plan, max_requests=1, force_refetch=True)


# ==========================================================================
# Checkpoint / resume
# ==========================================================================


def test_checkpoint_settles_fetched_and_not_available_but_not_error(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    checkpoint = Checkpoint.load(path)
    fetched = ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30))
    missing = ReportCandidate(date(2025, 11, 3), "game_day", _et(2025, 11, 3, 13, 0))
    errored = ReportCandidate(date(2025, 11, 4), "game_day", _et(2025, 11, 4, 13, 0))

    checkpoint.record(fetched, "fetched")
    checkpoint.record(missing, "not_available")
    checkpoint.record(errored, "error", "contract drift")

    assert checkpoint.is_settled(fetched)
    assert checkpoint.is_settled(missing)
    assert not checkpoint.is_settled(errored)  # retried on resume


def test_checkpoint_persists_to_disk_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.json"
    candidate = ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30))
    Checkpoint.load(path).record(candidate, "fetched")

    reloaded = Checkpoint.load(path)
    assert reloaded.is_settled(candidate)


def test_checkpoint_key_changes_when_the_resolved_timestamp_changes(tmp_path: Path) -> None:
    """A corrected tip-off changes a near-tip candidate's identity, not just its value.

    Round-4 regression (independent review, point 1): the same
    ``(report_date, anchor)`` pair can name a genuinely different URL once a
    date's earliest tip-off is corrected or newly ingested, since a
    ``near_tip_*`` candidate's ``report_timestamp`` is derived from it. Keying
    only on ``(date, anchor)`` let a stale settled entry silently vouch for a
    URL it was never actually checked against. The fix must make the *old*
    settled entry stop matching once the resolved instant changes, so the
    corrected candidate is treated as genuinely new and gets fetched.
    """
    path = tmp_path / "checkpoint.json"
    checkpoint = Checkpoint.load(path)

    original_tip = _et(2025, 12, 25, 19, 0)
    original = candidate_report_timestamps(date(2025, 12, 25), earliest_tipoff_utc=original_tip)
    original_near_15 = next(c for c in original if c.anchor == "near_tip_15")
    checkpoint.record(original_near_15, "fetched")
    assert checkpoint.is_settled(original_near_15)

    # The schedule is corrected: the game actually tips off 45 minutes later.
    corrected_tip = original_tip + timedelta(minutes=45)
    corrected = candidate_report_timestamps(date(2025, 12, 25), earliest_tipoff_utc=corrected_tip)
    corrected_near_15 = next(c for c in corrected if c.anchor == "near_tip_15")

    # Same date, same anchor label -- but a genuinely different resolved instant.
    assert corrected_near_15.report_timestamp != original_near_15.report_timestamp
    assert corrected_near_15.anchor == original_near_15.anchor
    assert corrected_near_15.report_date == original_near_15.report_date

    reloaded = Checkpoint.load(path)
    assert not reloaded.is_settled(corrected_near_15), (
        "a corrected tip-off must not inherit settled status from the stale instant"
    )
    # The stale entry itself, if re-checked verbatim, is of course still there --
    # this is not about losing data, only about a *different* candidate not
    # matching it.
    assert reloaded.is_settled(original_near_15)


def test_run_backfill_refetches_after_a_mid_flight_tipoff_correction(
    session: Any, tmp_path: Path
) -> None:
    """End-to-end: a settled near-tip candidate is re-fetched after its tip-off moves.

    Exercises the same scenario as the unit-level checkpoint-key test above,
    but through ``run_backfill`` and a real ``NbaGame`` row, to prove the
    fix actually changes resumed behavior, not just the key's string value.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="tipchange-0",
        game_date=date(2025, 12, 25),
        tipoff_utc=_et(2025, 12, 25, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)
    checkpoint_path = tmp_path / "checkpoint_tipchange.json"
    checkpoint = Checkpoint.load(checkpoint_path)

    script: dict[datetime, InjuryReportParseResult | Exception] = {
        pf.candidate.report_timestamp: ReportNotAvailable(
            "not published", source=SOURCE, endpoint=ENDPOINT, status_code=404
        )
        for pf in plan.fetches
    }
    fetcher = _ScriptedFetcher(script)
    result = run_backfill(session, plan=plan, fetch_and_parse=fetcher, checkpoint=checkpoint)
    assert len(result.not_available) == len(plan.fetches)
    first_run_calls = set(fetcher.calls)

    # The schedule is corrected after the fact.
    game.tipoff_utc = _et(2025, 12, 25, 19, 45)
    session.flush()

    resumed_checkpoint = Checkpoint.load(checkpoint_path)
    resumed_plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)
    resumed_script: dict[datetime, InjuryReportParseResult | Exception] = {
        pf.candidate.report_timestamp: ReportNotAvailable(
            "not published", source=SOURCE, endpoint=ENDPOINT, status_code=404
        )
        for pf in resumed_plan.fetches
    }
    resumed_fetcher = _ScriptedFetcher(resumed_script)
    resumed_result = run_backfill(
        session, plan=resumed_plan, fetch_and_parse=resumed_fetcher, checkpoint=resumed_checkpoint
    )
    # The near-tip candidates whose resolved instant changed must be genuinely
    # re-fetched, not silently skipped as already-settled.
    near_tip_candidates_after = [
        pf.candidate for pf in resumed_plan.fetches if pf.candidate.anchor.startswith("near_tip_")
    ]
    changed_near_tip = [
        c for c in near_tip_candidates_after if c.report_timestamp not in first_run_calls
    ]
    assert changed_near_tip, "expected at least one near-tip candidate to actually change"
    for candidate in changed_near_tip:
        assert candidate.report_timestamp in resumed_fetcher.calls, (
            f"{candidate.report_timestamp} changed after the tip-off correction and "
            "must be genuinely re-fetched"
        )
        assert candidate not in resumed_result.skipped_settled, (
            "a stale settled entry must not vouch for a candidate it never actually checked"
        )


# ==========================================================================
# run_backfill: fetch/import, missing vs contract drift, resume, atomicity
# ==========================================================================


class _ScriptedFetcher:
    """A fake ``fetch_and_parse`` driven by a per-timestamp script."""

    def __init__(self, script: dict[datetime, InjuryReportParseResult | Exception]) -> None:
        self.script = script
        self.calls: list[datetime] = []

    def __call__(self, report_timestamp: datetime) -> InjuryReportParseResult:
        self.calls.append(report_timestamp)
        outcome = self.script[report_timestamp]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _plan_with_two_candidates(session: Any) -> Any:
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="run-1",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    return build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)


def test_run_backfill_imports_a_fetched_report_and_commits(session: Any, tmp_path: Path) -> None:
    plan = _plan_with_two_candidates(session)
    evening_before = next(pf for pf in plan.fetches if pf.candidate.anchor == "evening_before")
    game_day = next(pf for pf in plan.fetches if pf.candidate.anchor == "game_day")

    result_payload = InjuryReportParseResult(
        report_timestamp=evening_before.candidate.report_timestamp,
        source_url="https://example.invalid/fixture",
        entries=(_entry(report_timestamp=evening_before.candidate.report_timestamp),),
    )
    fetcher = _ScriptedFetcher(
        {
            evening_before.candidate.report_timestamp: result_payload,
            game_day.candidate.report_timestamp: ReportNotAvailable(
                "no report", source=SOURCE, endpoint=ENDPOINT
            ),
        }
    )
    checkpoint = Checkpoint.load(tmp_path / "checkpoint.json")

    result = run_backfill(session, plan=plan, fetch_and_parse=fetcher, checkpoint=checkpoint)

    assert len(result.fetched) == 1
    assert len(result.not_available) == 1
    assert not result.failures
    assert result.totals.created == 1
    rows = session.scalars(select(InjuryReportEntry)).all()
    assert len(rows) == 1


def test_run_backfill_counts_missing_and_contract_drift_separately(
    session: Any, tmp_path: Path
) -> None:
    plan = _plan_with_two_candidates(session)
    evening_before = next(pf for pf in plan.fetches if pf.candidate.anchor == "evening_before")
    game_day = next(pf for pf in plan.fetches if pf.candidate.anchor == "game_day")

    fetcher = _ScriptedFetcher(
        {
            evening_before.candidate.report_timestamp: ReportNotAvailable(
                "no report", source=SOURCE, endpoint=ENDPOINT
            ),
            game_day.candidate.report_timestamp: SourceContractError(
                "unexpected shape", source=SOURCE, endpoint=ENDPOINT
            ),
        }
    )
    checkpoint = Checkpoint.load(tmp_path / "checkpoint.json")

    result = run_backfill(session, plan=plan, fetch_and_parse=fetcher, checkpoint=checkpoint)

    assert len(result.not_available) == 1
    assert len(result.failures) == 1
    assert "unexpected shape" in result.failures[0][1]
    # A missing report is never counted as a failure.
    assert result.failures[0][0].anchor == "game_day"


def test_run_backfill_partial_failure_does_not_lose_the_successful_half(
    session: Any, tmp_path: Path
) -> None:
    """Failure atomicity: one bad candidate does not cost the other."""
    plan = _plan_with_two_candidates(session)
    evening_before = next(pf for pf in plan.fetches if pf.candidate.anchor == "evening_before")
    game_day = next(pf for pf in plan.fetches if pf.candidate.anchor == "game_day")

    good = InjuryReportParseResult(
        report_timestamp=evening_before.candidate.report_timestamp,
        source_url="https://example.invalid/fixture",
        entries=(_entry(report_timestamp=evening_before.candidate.report_timestamp),),
    )
    fetcher = _ScriptedFetcher(
        {
            evening_before.candidate.report_timestamp: good,
            game_day.candidate.report_timestamp: SourceContractError(
                "boom", source=SOURCE, endpoint=ENDPOINT
            ),
        }
    )
    checkpoint = Checkpoint.load(tmp_path / "checkpoint.json")

    result = run_backfill(session, plan=plan, fetch_and_parse=fetcher, checkpoint=checkpoint)

    assert result.totals.created == 1
    assert len(result.failures) == 1
    # The successful import survived the later failure's rollback.
    rows = session.scalars(select(InjuryReportEntry)).all()
    assert len(rows) == 1


def test_run_backfill_resumes_by_skipping_already_settled_candidates(
    session: Any, tmp_path: Path
) -> None:
    plan = _plan_with_two_candidates(session)
    evening_before = next(pf for pf in plan.fetches if pf.candidate.anchor == "evening_before")
    game_day = next(pf for pf in plan.fetches if pf.candidate.anchor == "game_day")

    checkpoint = Checkpoint.load(tmp_path / "checkpoint.json")
    checkpoint.record(
        evening_before.candidate,
        "fetched",
        applicable_nba_game_ids=evening_before.applicable_nba_game_ids,
    )

    payload = InjuryReportParseResult(
        report_timestamp=game_day.candidate.report_timestamp,
        source_url="https://example.invalid/fixture",
        entries=(_entry(report_timestamp=game_day.candidate.report_timestamp),),
    )
    fetcher = _ScriptedFetcher({game_day.candidate.report_timestamp: payload})

    result = run_backfill(session, plan=plan, fetch_and_parse=fetcher, checkpoint=checkpoint)

    assert evening_before.candidate in result.skipped_settled
    # The already-settled candidate was never re-requested.
    assert evening_before.candidate.report_timestamp not in fetcher.calls
    assert len(result.fetched) == 1


def test_run_backfill_force_refetch_bypasses_cache_and_checkpoint(
    session: Any, tmp_path: Path
) -> None:
    """``--no-cache``/``force_refetch`` must actually force a re-fetch.

    A candidate that is both already cached (``build_plan`` marked it
    ``already_cached=True``, so it is excluded from ``plan.to_fetch``) and
    already checkpointed as settled must still be fetched and re-imported
    when the caller asks to force it — otherwise the flag that exists
    precisely to override those two independent layers would do nothing.
    """
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="force-refetch-run",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    store = RawPayloadStore(tmp_path / "raw")
    evening_before_ts = _et(2025, 11, 1, 17, 30)
    store.put(
        source=SOURCE,
        endpoint=ENDPOINT,
        params={"url": report_url(evening_before_ts)},
        body=b"%PDF-x",
    )

    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR, store=store)
    cached_fetch = next(pf for pf in plan.fetches if pf.candidate.anchor == "evening_before")
    assert cached_fetch.already_cached  # precondition: this is the one the cache already has
    assert cached_fetch not in plan.to_fetch

    checkpoint = Checkpoint.load(tmp_path / "checkpoint.json")
    checkpoint.record(
        cached_fetch.candidate,
        "fetched",
        applicable_nba_game_ids=cached_fetch.applicable_nba_game_ids,
    )  # precondition: already settled too

    payload = InjuryReportParseResult(
        report_timestamp=cached_fetch.candidate.report_timestamp,
        source_url="https://example.invalid/fixture",
        entries=(_entry(report_timestamp=cached_fetch.candidate.report_timestamp),),
    )
    game_day = next(pf for pf in plan.fetches if pf.candidate.anchor == "game_day")
    fetcher = _ScriptedFetcher(
        {
            cached_fetch.candidate.report_timestamp: payload,
            game_day.candidate.report_timestamp: ReportNotAvailable(
                "no report", source=SOURCE, endpoint=ENDPOINT
            ),
        }
    )

    result = run_backfill(
        session, plan=plan, fetch_and_parse=fetcher, checkpoint=checkpoint, force_refetch=True
    )

    # The cached, already-settled candidate was genuinely re-requested.
    assert cached_fetch.candidate.report_timestamp in fetcher.calls
    assert cached_fetch.candidate in result.fetched
    assert cached_fetch.candidate not in result.skipped_settled


def test_run_backfill_converges_duplicate_mastheads_from_two_candidates(
    session: Any, tmp_path: Path
) -> None:
    """Two different requested instants resolving to the identical masthead
    (legacy-era hour truncation) must converge onto one set of rows, not
    duplicate them — proving the orchestration layer relies on the existing
    natural-key import rather than defeating it.
    """
    plan = _plan_with_two_candidates(session)
    evening_before = next(pf for pf in plan.fetches if pf.candidate.anchor == "evening_before")
    game_day = next(pf for pf in plan.fetches if pf.candidate.anchor == "game_day")

    # Both candidates resolve to the identical masthead-stamped capture.
    shared_masthead = _et(2025, 11, 1, 17, 0)
    shared_payload = InjuryReportParseResult(
        report_timestamp=shared_masthead,
        source_url="https://example.invalid/fixture",
        entries=(_entry(report_timestamp=shared_masthead),),
    )
    fetcher = _ScriptedFetcher(
        {
            evening_before.candidate.report_timestamp: shared_payload,
            game_day.candidate.report_timestamp: shared_payload,
        }
    )
    checkpoint = Checkpoint.load(tmp_path / "checkpoint.json")

    result = run_backfill(session, plan=plan, fetch_and_parse=fetcher, checkpoint=checkpoint)

    assert result.totals.created == 1
    assert result.totals.updated == 1  # the second import converges, not duplicates
    rows = session.scalars(select(InjuryReportEntry)).all()
    assert len(rows) == 1


def test_run_backfill_processes_a_cached_candidate_that_was_never_checkpointed(
    session: Any, tmp_path: Path
) -> None:
    """A crash between ``store.put()`` and ``checkpoint.record()`` must not lose the candidate.

    ``already_cached`` is budget/rendering metadata only — it must never gate
    whether ``run_backfill`` processes a candidate. Only the checkpoint's own
    settled-outcome gate decides that. A candidate whose raw PDF is already
    on disk (``build_plan`` marked it ``already_cached=True``) but has no
    checkpoint entry at all (never reached "fetched") must still be fetched
    and imported on this run — not silently skipped forever because a cache
    hit looked, on the surface, like "nothing to do here".
    """
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="cached-no-checkpoint",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    store = RawPayloadStore(tmp_path / "raw")
    evening_before_ts = _et(2025, 11, 1, 17, 30)
    store.put(
        source=SOURCE,
        endpoint=ENDPOINT,
        params={"url": report_url(evening_before_ts)},
        body=b"%PDF-x",
    )

    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR, store=store)
    cached_fetch = next(pf for pf in plan.fetches if pf.candidate.anchor == "evening_before")
    assert cached_fetch.already_cached  # precondition: build_plan sees the cache hit
    assert cached_fetch not in plan.to_fetch  # ...and the legacy budget view would skip it

    # No checkpoint.record() call at all for this candidate — simulating a crash
    # between the raw store write and the checkpoint write.
    checkpoint = Checkpoint.load(tmp_path / "checkpoint.json")
    assert not checkpoint.is_settled(cached_fetch.candidate)

    payload = InjuryReportParseResult(
        report_timestamp=cached_fetch.candidate.report_timestamp,
        source_url="https://example.invalid/fixture",
        entries=(_entry(report_timestamp=cached_fetch.candidate.report_timestamp),),
    )
    game_day = next(pf for pf in plan.fetches if pf.candidate.anchor == "game_day")
    fetcher = _ScriptedFetcher(
        {
            cached_fetch.candidate.report_timestamp: payload,
            game_day.candidate.report_timestamp: ReportNotAvailable(
                "no report", source=SOURCE, endpoint=ENDPOINT
            ),
        }
    )

    result = run_backfill(session, plan=plan, fetch_and_parse=fetcher, checkpoint=checkpoint)

    assert cached_fetch.candidate.report_timestamp in fetcher.calls
    assert cached_fetch.candidate in result.fetched
    assert result.totals.created == 1
    assert checkpoint.is_settled(cached_fetch.candidate)


def test_run_backfill_resumes_a_candidate_that_previously_failed_to_parse_despite_being_cached(
    session: Any, tmp_path: Path
) -> None:
    """A cached-but-unsettled candidate (prior parse error) must be retried, not skipped.

    The candidate's raw bytes are on disk (a genuine cache hit), but its
    checkpoint status is ``"error"`` from a previous run's contract-drift
    failure — that status is not in the settled set, so a resumed run must
    call ``fetch_and_parse`` again rather than trusting the stale cache state
    to mean "already handled".
    """
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="cached-after-parse-error",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    store = RawPayloadStore(tmp_path / "raw")
    evening_before_ts = _et(2025, 11, 1, 17, 30)
    store.put(
        source=SOURCE,
        endpoint=ENDPOINT,
        params={"url": report_url(evening_before_ts)},
        body=b"%PDF-x",
    )

    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR, store=store)
    cached_fetch = next(pf for pf in plan.fetches if pf.candidate.anchor == "evening_before")
    assert cached_fetch.already_cached

    checkpoint = Checkpoint.load(tmp_path / "checkpoint.json")
    checkpoint.record(cached_fetch.candidate, "error", "contract drift on the prior attempt")
    assert not checkpoint.is_settled(cached_fetch.candidate)  # "error" is retried, not settled

    payload = InjuryReportParseResult(
        report_timestamp=cached_fetch.candidate.report_timestamp,
        source_url="https://example.invalid/fixture",
        entries=(_entry(report_timestamp=cached_fetch.candidate.report_timestamp),),
    )
    game_day = next(pf for pf in plan.fetches if pf.candidate.anchor == "game_day")
    fetcher = _ScriptedFetcher(
        {
            cached_fetch.candidate.report_timestamp: payload,
            game_day.candidate.report_timestamp: ReportNotAvailable(
                "no report", source=SOURCE, endpoint=ENDPOINT
            ),
        }
    )

    result = run_backfill(session, plan=plan, fetch_and_parse=fetcher, checkpoint=checkpoint)

    assert cached_fetch.candidate.report_timestamp in fetcher.calls
    assert cached_fetch.candidate in result.fetched
    assert checkpoint.is_settled(cached_fetch.candidate)


def test_run_backfill_does_not_checkpoint_as_settled_when_the_commit_fails(
    session: Any, tmp_path: Path
) -> None:
    """A commit failure must never look like a settled, successful fetch.

    Simulates a kill-window between the import and the durable commit: if
    ``session.commit()`` raises, the checkpoint must record an *unsettled*
    ``"error"`` (not ``"fetched"``) so a resumed run retries the candidate,
    and the failed transaction must be rolled back rather than left dangling.
    """
    plan = _plan_with_two_candidates(session)
    evening_before = next(pf for pf in plan.fetches if pf.candidate.anchor == "evening_before")
    game_day = next(pf for pf in plan.fetches if pf.candidate.anchor == "game_day")

    payload = InjuryReportParseResult(
        report_timestamp=evening_before.candidate.report_timestamp,
        source_url="https://example.invalid/fixture",
        entries=(_entry(report_timestamp=evening_before.candidate.report_timestamp),),
    )
    fetcher = _ScriptedFetcher(
        {
            evening_before.candidate.report_timestamp: payload,
            game_day.candidate.report_timestamp: ReportNotAvailable(
                "no report", source=SOURCE, endpoint=ENDPOINT
            ),
        }
    )
    checkpoint = Checkpoint.load(tmp_path / "checkpoint.json")

    real_commit = session.commit
    calls = {"n": 0}

    def _failing_commit() -> None:
        calls["n"] += 1
        raise RuntimeError("simulated commit failure (dropped connection)")

    session.commit = _failing_commit
    try:
        result = run_backfill(session, plan=plan, fetch_and_parse=fetcher, checkpoint=checkpoint)
    finally:
        session.commit = real_commit

    assert calls["n"] == 1
    assert evening_before.candidate not in result.fetched
    assert any("commit failed" in why for _, why in result.failures)
    # Never checkpointed as settled — a resumed run must retry it.
    assert not checkpoint.is_settled(evening_before.candidate)

    # A genuine resumed run (with a working commit) now succeeds and persists data.
    resumed_fetcher = _ScriptedFetcher({evening_before.candidate.report_timestamp: payload})
    resumed_plan = plan  # same plan; the game_day candidate is already settled as not_available
    checkpoint.record(
        game_day.candidate,
        "not_available",
        applicable_nba_game_ids=game_day.applicable_nba_game_ids,
    )
    resumed_result = run_backfill(
        session, plan=resumed_plan, fetch_and_parse=resumed_fetcher, checkpoint=checkpoint
    )
    assert evening_before.candidate in resumed_result.fetched
    rows = session.scalars(select(InjuryReportEntry)).all()
    assert len(rows) == 1


def test_run_backfill_does_not_checkpoint_as_settled_when_the_import_flush_fails(
    session: Any, tmp_path: Path
) -> None:
    """Round-11 review point 4: an import-time flush failure must never look settled either.

    ``import_injury_report_entries`` calls ``session.flush()`` internally,
    *before* ``run_backfill`` ever reaches its own ``session.commit()``.
    Before this fix, that flush sat entirely outside any try/except in
    ``run_backfill``: an exception from it propagated straight out of the
    whole function, aborting every other candidate in the plan too --
    rather than being handled as this one candidate's recorded, unsettled
    failure the way a commit failure already was.

    This is a genuine, real database constraint violation -- not a mocked
    commit: ``player_name_raw`` is a real ``NOT NULL`` column
    (``injury_report_entries.player_name_raw``), enforced by SQLite (and
    Postgres) regardless of foreign-key pragma settings. Passing ``None``
    for it (bypassing the frozen dataclass's type hint, which Python does
    not enforce at runtime) makes the importer's own internal flush raise a
    real ``IntegrityError`` at flush-time, exercising the actual database
    engine's constraint enforcement.
    """
    plan = _plan_with_two_candidates(session)
    evening_before = next(pf for pf in plan.fetches if pf.candidate.anchor == "evening_before")
    game_day = next(pf for pf in plan.fetches if pf.candidate.anchor == "game_day")

    broken_entry = _entry(
        report_timestamp=evening_before.candidate.report_timestamp,
        player_name_raw=cast(Any, None),
    )
    payload = InjuryReportParseResult(
        report_timestamp=evening_before.candidate.report_timestamp,
        source_url="https://example.invalid/fixture",
        entries=(broken_entry,),
    )
    fetcher = _ScriptedFetcher(
        {
            evening_before.candidate.report_timestamp: payload,
            game_day.candidate.report_timestamp: ReportNotAvailable(
                "no report", source=SOURCE, endpoint=ENDPOINT
            ),
        }
    )
    checkpoint = Checkpoint.load(tmp_path / "checkpoint.json")

    result = run_backfill(session, plan=plan, fetch_and_parse=fetcher, checkpoint=checkpoint)

    assert evening_before.candidate not in result.fetched
    assert any("import/commit failed" in why for _, why in result.failures)
    # Never checkpointed as settled -- a resumed run must retry it.
    assert not checkpoint.is_settled(evening_before.candidate)
    # The failed flush must not leave a half-written row visible: rollback
    # is real, not merely reported.
    rows = session.scalars(select(InjuryReportEntry)).all()
    assert len(rows) == 0
    # The other candidate in the same run (game_day, a genuine 404) is
    # entirely unaffected -- one candidate's flush failure does not abort
    # the run.
    assert game_day.candidate in result.not_available

    # A genuine resumed run with a valid entry now succeeds and persists data.
    good_entry = _entry(report_timestamp=evening_before.candidate.report_timestamp)
    good_payload = InjuryReportParseResult(
        report_timestamp=evening_before.candidate.report_timestamp,
        source_url="https://example.invalid/fixture",
        entries=(good_entry,),
    )
    resumed_fetcher = _ScriptedFetcher({evening_before.candidate.report_timestamp: good_payload})
    resumed_result = run_backfill(
        session, plan=plan, fetch_and_parse=resumed_fetcher, checkpoint=checkpoint
    )
    assert evening_before.candidate in resumed_result.fetched
    rows = session.scalars(select(InjuryReportEntry)).all()
    assert len(rows) == 1


class _CrashAfterCoverage(RuntimeError):
    """Simulates a hard crash immediately after coverage was durably persisted."""


def test_run_backfill_persists_coverage_durably_before_settling_a_fetched_candidate(
    session: Any, tmp_path: Path
) -> None:
    """Round-6 review point 1: coverage must be durable *before* settlement.

    Coverage previously only lived in an in-memory list, written to disk
    once, in bulk, at the very end of a run -- a crash between
    ``checkpoint.record(..., "fetched")`` and that end-of-run write left a
    permanently settled candidate with no coverage record at all, since a
    settled candidate is skipped (without regenerating coverage) on every
    future resume. This simulates a crash immediately after
    ``persist_coverage`` succeeds but before ``checkpoint.record`` can run,
    and proves: (1) the coverage record was already durable at the moment
    of the crash: it survives even though the checkpoint never settled; (2)
    resuming re-processes the unsettled candidate without creating a
    duplicate DB row or a duplicate coverage record.
    """
    plan = _plan_with_two_candidates(session)
    evening_before = next(pf for pf in plan.fetches if pf.candidate.anchor == "evening_before")
    game_day = next(pf for pf in plan.fetches if pf.candidate.anchor == "game_day")

    payload = InjuryReportParseResult(
        report_timestamp=evening_before.candidate.report_timestamp,
        source_url="https://example.invalid/fixture",
        entries=(_entry(report_timestamp=evening_before.candidate.report_timestamp),),
    )
    fetcher = _ScriptedFetcher(
        {
            evening_before.candidate.report_timestamp: payload,
            game_day.candidate.report_timestamp: ReportNotAvailable(
                "no report", source=SOURCE, endpoint=ENDPOINT
            ),
        }
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    coverage_path = tmp_path / "coverage.json"
    checkpoint = Checkpoint.load(checkpoint_path)

    def crash_after_persisting(cov: CandidateCoverage) -> None:
        _persist_coverage(coverage_path, "2025-26", SeasonType.REGULAR, [cov])
        if cov.outcome == "fetched":
            raise _CrashAfterCoverage("simulated crash right after the durable coverage write")

    with pytest.raises(_CrashAfterCoverage):
        run_backfill(
            session,
            plan=plan,
            fetch_and_parse=fetcher,
            checkpoint=checkpoint,
            persist_coverage=crash_after_persisting,
        )

    # The crash happened before checkpoint.record for the fetched candidate.
    assert not checkpoint.is_settled(evening_before.candidate)
    # But its coverage was already durable at the moment of the simulated crash.
    on_disk = CoverageReport.from_json(coverage_path.read_text(encoding="utf-8"))
    fetched_records = [c for c in on_disk.candidates if c.outcome == "fetched"]
    assert len(fetched_records) == 1
    assert (
        fetched_records[0].requested_timestamp
        == evening_before.candidate.report_timestamp.isoformat()
    )
    # The import itself was already committed too (it happens before coverage
    # is even built) -- this is not lost, only not yet marked settled.
    rows = session.scalars(select(InjuryReportEntry)).all()
    assert len(rows) == 1

    # Resume with a clean (non-crashing) fetcher and persist_coverage.
    resumed_checkpoint = Checkpoint.load(checkpoint_path)
    resumed_fetcher = _ScriptedFetcher(
        {
            evening_before.candidate.report_timestamp: payload,
            game_day.candidate.report_timestamp: ReportNotAvailable(
                "no report", source=SOURCE, endpoint=ENDPOINT
            ),
        }
    )
    resumed_result = run_backfill(
        session,
        plan=plan,
        fetch_and_parse=resumed_fetcher,
        checkpoint=resumed_checkpoint,
        persist_coverage=lambda cov: _persist_coverage(
            coverage_path, "2025-26", SeasonType.REGULAR, [cov]
        ),
    )

    assert evening_before.candidate in resumed_result.fetched
    assert resumed_checkpoint.is_settled(evening_before.candidate)
    # No duplicate import row: import_injury_report_entries is idempotent by
    # natural key.
    rows_after_resume = session.scalars(select(InjuryReportEntry)).all()
    assert len(rows_after_resume) == 1
    # No duplicate coverage record: _persist_coverage merges by the same key
    # the checkpoint uses.
    merged_on_disk = CoverageReport.from_json(coverage_path.read_text(encoding="utf-8"))
    merged_fetched = [c for c in merged_on_disk.candidates if c.outcome == "fetched"]
    assert len(merged_fetched) == 1


def test_run_backfill_persists_coverage_durably_before_settling_a_404_candidate(
    session: Any, tmp_path: Path
) -> None:
    """Round-6 review point 1, the 404 (``not_available``) case.

    Same durability invariant as the fetched case above: coverage for a 404
    outcome must be durable before ``checkpoint.record(..., "not_available")``
    settles it, so a crash between the two never leaves a settled candidate
    with no coverage evidence at all.
    """
    plan = _plan_with_two_candidates(session)
    evening_before = next(pf for pf in plan.fetches if pf.candidate.anchor == "evening_before")
    game_day = next(pf for pf in plan.fetches if pf.candidate.anchor == "game_day")

    fetcher = _ScriptedFetcher(
        {
            evening_before.candidate.report_timestamp: ReportNotAvailable(
                "no report", source=SOURCE, endpoint=ENDPOINT, status_code=404
            ),
            game_day.candidate.report_timestamp: ReportNotAvailable(
                "no report", source=SOURCE, endpoint=ENDPOINT, status_code=404
            ),
        }
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    coverage_path = tmp_path / "coverage.json"
    checkpoint = Checkpoint.load(checkpoint_path)

    def crash_after_persisting(cov: CandidateCoverage) -> None:
        _persist_coverage(coverage_path, "2025-26", SeasonType.REGULAR, [cov])
        if cov.outcome == "not_available" and cov.anchor == "evening_before":
            raise _CrashAfterCoverage("simulated crash right after the durable coverage write")

    with pytest.raises(_CrashAfterCoverage):
        run_backfill(
            session,
            plan=plan,
            fetch_and_parse=fetcher,
            checkpoint=checkpoint,
            persist_coverage=crash_after_persisting,
        )

    assert not checkpoint.is_settled(evening_before.candidate)
    on_disk = CoverageReport.from_json(coverage_path.read_text(encoding="utf-8"))
    not_available_records = [c for c in on_disk.candidates if c.outcome == "not_available"]
    assert len(not_available_records) == 1
    assert (
        not_available_records[0].requested_timestamp
        == evening_before.candidate.report_timestamp.isoformat()
    )

    resumed_checkpoint = Checkpoint.load(checkpoint_path)
    resumed_fetcher = _ScriptedFetcher(
        {
            evening_before.candidate.report_timestamp: ReportNotAvailable(
                "no report", source=SOURCE, endpoint=ENDPOINT, status_code=404
            ),
            game_day.candidate.report_timestamp: ReportNotAvailable(
                "no report", source=SOURCE, endpoint=ENDPOINT, status_code=404
            ),
        }
    )
    resumed_result = run_backfill(
        session,
        plan=plan,
        fetch_and_parse=resumed_fetcher,
        checkpoint=resumed_checkpoint,
        persist_coverage=lambda cov: _persist_coverage(
            coverage_path, "2025-26", SeasonType.REGULAR, [cov]
        ),
    )

    assert evening_before.candidate in resumed_result.not_available
    assert resumed_checkpoint.is_settled(evening_before.candidate)
    merged_on_disk = CoverageReport.from_json(coverage_path.read_text(encoding="utf-8"))
    merged_not_available = [c for c in merged_on_disk.candidates if c.outcome == "not_available"]
    # game_day is now also processed on resume (never reached before the
    # simulated crash) -- both candidates get exactly one coverage record
    # each, no duplicates for either.
    assert len(merged_not_available) == 2
    evening_before_records = [
        c
        for c in merged_not_available
        if c.requested_timestamp == evening_before.candidate.report_timestamp.isoformat()
    ]
    assert len(evening_before_records) == 1, (
        "no duplicate coverage record for the resumed candidate"
    )


def test_run_backfill_does_not_abort_on_a_single_404_but_does_on_a_403_streak(
    session: Any, tmp_path: Path
) -> None:
    """A 403 is not treated the same as a 404: a streak of them aborts the run.

    A 404 is the documented, ordinary "nothing published here" outcome and
    must never abort a run no matter how many occur. A *consecutive run* of
    403s, however, looks like a WAF or rate-limit block rather than dozens of
    coincidentally pre-season-style refusals, and must raise
    ``SuspectedSourceBlock`` instead of quietly recording each one as
    confirmed absence.
    """
    teams = _seed_teams(session)
    for i in range(4):
        _seed_game(
            session,
            nba_game_id=f"streak-{i}",
            game_date=date(2025, 11, 1) + timedelta(days=i),
            tipoff_utc=_et(2025, 11, 1, 19, 0) + timedelta(days=i),
            home_team_id=teams["MIL"],
            away_team_id=teams["SAC"],
        )
    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)
    checkpoint = Checkpoint.load(tmp_path / "checkpoint.json")

    # Every candidate 404s ("not published") -- must never abort, however many.
    script_404: dict[datetime, InjuryReportParseResult | Exception] = {
        pf.candidate.report_timestamp: ReportNotAvailable(
            "not published", source=SOURCE, endpoint=ENDPOINT, status_code=404
        )
        for pf in plan.fetches
    }
    fetcher_404 = _ScriptedFetcher(script_404)
    result = run_backfill(
        session,
        plan=plan,
        fetch_and_parse=fetcher_404,
        checkpoint=checkpoint,
        max_forbidden_streak=3,
    )
    assert len(result.not_available) == len(plan.fetches)
    assert not result.failures

    # Now a fresh run where every candidate 403s -- must abort once the streak hits 3.
    checkpoint_403 = Checkpoint.load(tmp_path / "checkpoint_403.json")
    script_403: dict[datetime, InjuryReportParseResult | Exception] = {
        pf.candidate.report_timestamp: ReportNotAvailable(
            "forbidden", source=SOURCE, endpoint=ENDPOINT, status_code=403
        )
        for pf in plan.fetches
    }
    fetcher_403 = _ScriptedFetcher(script_403)
    with pytest.raises(SuspectedSourceBlock):
        run_backfill(
            session,
            plan=plan,
            fetch_and_parse=fetcher_403,
            checkpoint=checkpoint_403,
            max_forbidden_streak=3,
        )
    # Aborted after exactly the third consecutive 403, not the whole plan.
    assert len(fetcher_403.calls) == 3


def test_run_backfill_does_not_settle_a_403_streak_that_triggered_the_abort(
    session: Any, tmp_path: Path
) -> None:
    """The 403s that *caused* the abort must not be checkpointed as settled.

    Regression for a real gap: the streak guard raised ``SuspectedSourceBlock``
    but still checkpointed every 403 -- including the ones in the aborting
    streak -- as settled ``"not_available"`` before raising. A resumed run
    (after whatever blocked us clears) would then silently skip exactly the
    candidates the abort was trying to protect, treating a suspected WAF or
    rate-limit block as confirmed "no report" forever.
    """
    teams = _seed_teams(session)
    for i in range(4):
        _seed_game(
            session,
            nba_game_id=f"noseattle-{i}",
            game_date=date(2025, 11, 1) + timedelta(days=i),
            tipoff_utc=_et(2025, 11, 1, 19, 0) + timedelta(days=i),
            home_team_id=teams["MIL"],
            away_team_id=teams["SAC"],
        )
    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)
    checkpoint_path = tmp_path / "checkpoint_403_unsettled.json"
    checkpoint = Checkpoint.load(checkpoint_path)

    script_403: dict[datetime, InjuryReportParseResult | Exception] = {
        pf.candidate.report_timestamp: ReportNotAvailable(
            "forbidden", source=SOURCE, endpoint=ENDPOINT, status_code=403
        )
        for pf in plan.fetches
    }
    fetcher_403 = _ScriptedFetcher(script_403)
    with pytest.raises(SuspectedSourceBlock):
        run_backfill(
            session,
            plan=plan,
            fetch_and_parse=fetcher_403,
            checkpoint=checkpoint,
            max_forbidden_streak=3,
        )

    # Reload from disk -- this is exactly what a resumed run would see.
    reloaded = Checkpoint.load(checkpoint_path)
    streak_candidates = [pf.candidate for pf in plan.fetches[:3]]
    for candidate in streak_candidates:
        assert not reloaded.is_settled(candidate), (
            f"{candidate.report_timestamp} was checkpointed as settled despite "
            "belonging to the 403 streak that triggered the abort"
        )


def test_run_backfill_retries_403s_from_an_aborted_streak_on_resume(
    session: Any, tmp_path: Path
) -> None:
    """A resumed run must re-fetch (not skip) candidates from an aborted 403 streak."""
    teams = _seed_teams(session)
    for i in range(3):
        _seed_game(
            session,
            nba_game_id=f"resume403-{i}",
            game_date=date(2025, 11, 1) + timedelta(days=i),
            tipoff_utc=_et(2025, 11, 1, 19, 0) + timedelta(days=i),
            home_team_id=teams["MIL"],
            away_team_id=teams["SAC"],
        )
    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)
    checkpoint_path = tmp_path / "checkpoint_403_resume.json"
    checkpoint = Checkpoint.load(checkpoint_path)

    script_403: dict[datetime, InjuryReportParseResult | Exception] = {
        pf.candidate.report_timestamp: ReportNotAvailable(
            "forbidden", source=SOURCE, endpoint=ENDPOINT, status_code=403
        )
        for pf in plan.fetches
    }
    fetcher_403 = _ScriptedFetcher(script_403)
    with pytest.raises(SuspectedSourceBlock):
        run_backfill(
            session,
            plan=plan,
            fetch_and_parse=fetcher_403,
            checkpoint=checkpoint,
            max_forbidden_streak=3,
        )

    # Whatever blocked us clears; the resumed run sees ordinary 404s.
    checkpoint = Checkpoint.load(checkpoint_path)
    script_404: dict[datetime, InjuryReportParseResult | Exception] = {
        pf.candidate.report_timestamp: ReportNotAvailable(
            "not published", source=SOURCE, endpoint=ENDPOINT, status_code=404
        )
        for pf in plan.fetches
    }
    fetcher_404 = _ScriptedFetcher(script_404)
    result = run_backfill(
        session,
        plan=plan,
        fetch_and_parse=fetcher_404,
        checkpoint=checkpoint,
        max_forbidden_streak=3,
    )
    # None were skipped as already-settled -- every candidate was really retried.
    assert not result.skipped_settled
    assert len(fetcher_404.calls) == len(plan.fetches)
    assert len(result.not_available) == len(plan.fetches)


def test_run_backfill_never_settles_a_403_even_below_the_abort_threshold(
    session: Any, tmp_path: Path
) -> None:
    """A short 403 run that never reaches the streak threshold still never settles.

    Round-4 correction (independent review): round 3 settled a short 403 run
    as confirmed "not published" once it stayed below ``max_forbidden_streak``.
    That is wrong for the same reason a long streak is wrong -- a 403 can be a
    WAF/rate-limit response at any length, not just when it happens to run
    long enough to trip the abort heuristic. The streak guard is now purely an
    early-abort optimization; it has no bearing on whether any individual 403
    is ever checkpointed as settled. **No** 403 is ever settled, regardless of
    streak length or how many separate invocations occur.
    """
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="short403-0",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)
    assert len(plan.fetches) == 2
    checkpoint_path = tmp_path / "checkpoint_403_short.json"
    checkpoint = Checkpoint.load(checkpoint_path)

    script_403: dict[datetime, InjuryReportParseResult | Exception] = {
        pf.candidate.report_timestamp: ReportNotAvailable(
            "forbidden", source=SOURCE, endpoint=ENDPOINT, status_code=403
        )
        for pf in plan.fetches
    }
    fetcher_403 = _ScriptedFetcher(script_403)
    result = run_backfill(
        session,
        plan=plan,
        fetch_and_parse=fetcher_403,
        checkpoint=checkpoint,
        max_forbidden_streak=3,
    )
    # Never treated as "not available" -- a 403 is not a confirmed absence.
    assert not result.not_available
    assert len(result.forbidden) == 2
    assert not result.failures

    reloaded = Checkpoint.load(checkpoint_path)
    for pf in plan.fetches:
        assert not reloaded.is_settled(pf.candidate), (
            f"{pf.candidate.report_timestamp} was checkpointed as settled despite being a 403"
        )


def test_run_backfill_403_never_settles_across_separate_invocations(
    session: Any, tmp_path: Path
) -> None:
    """A 403 recorded in one CLI invocation stays unsettled in the next.

    Regression for the cross-process/cross-invocation concern raised in
    round-4 review point 5: repeatedly running the backfill as separate
    processes (e.g. once per date, as an operator plausibly would) must never
    accumulate into an accidental settled "not published" for a candidate
    that only ever received 403s, no matter how many separate ``run_backfill``
    calls touch it.
    """
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="repeat403-0",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)
    checkpoint_path = tmp_path / "checkpoint_403_repeat.json"

    for _ in range(5):
        checkpoint = Checkpoint.load(checkpoint_path)
        script_403: dict[datetime, InjuryReportParseResult | Exception] = {
            pf.candidate.report_timestamp: ReportNotAvailable(
                "forbidden", source=SOURCE, endpoint=ENDPOINT, status_code=403
            )
            for pf in plan.fetches
        }
        fetcher_403 = _ScriptedFetcher(script_403)
        result = run_backfill(
            session,
            plan=plan,
            fetch_and_parse=fetcher_403,
            checkpoint=checkpoint,
            max_forbidden_streak=99,  # well above this plan's 2 candidates
        )
        # Every invocation genuinely re-fetches -- nothing was skipped as settled.
        assert not result.skipped_settled
        assert len(fetcher_403.calls) == len(plan.fetches)

    reloaded = Checkpoint.load(checkpoint_path)
    for pf in plan.fetches:
        assert not reloaded.is_settled(pf.candidate)


def test_run_backfill_persists_coverage_gathered_before_a_403_abort(
    session: Any, tmp_path: Path
) -> None:
    """Coverage evidence from before an abort is not lost with the exception.

    Round-4 review point 2: ``SuspectedSourceBlock`` must carry every
    candidate's coverage gathered before the abort (successes and all), not
    just silently drop it, so a caller can persist durable evidence even on
    this failure path.
    """
    teams = _seed_teams(session)
    good_game = _seed_game(
        session,
        nba_game_id="cov403-good",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    for i in range(3):
        _seed_game(
            session,
            nba_game_id=f"cov403-bad-{i}",
            game_date=date(2025, 11, 2) + timedelta(days=i),
            tipoff_utc=_et(2025, 11, 2, 19, 0) + timedelta(days=i),
            home_team_id=teams["MIL"],
            away_team_id=teams["SAC"],
        )
    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)
    checkpoint = Checkpoint.load(tmp_path / "checkpoint_cov403.json")

    good_candidates = [pf for pf in plan.fetches if good_game.id in pf.applicable_game_ids]
    bad_candidates = [pf for pf in plan.fetches if good_game.id not in pf.applicable_game_ids]
    script: dict[datetime, InjuryReportParseResult | Exception] = {
        pf.candidate.report_timestamp: ReportNotAvailable(
            "not published", source=SOURCE, endpoint=ENDPOINT, status_code=404
        )
        for pf in good_candidates
    }
    script.update(
        {
            pf.candidate.report_timestamp: ReportNotAvailable(
                "forbidden", source=SOURCE, endpoint=ENDPOINT, status_code=403
            )
            for pf in bad_candidates
        }
    )
    fetcher = _ScriptedFetcher(script)
    with pytest.raises(SuspectedSourceBlock) as excinfo:
        run_backfill(
            session,
            plan=plan,
            fetch_and_parse=fetcher,
            checkpoint=checkpoint,
            max_forbidden_streak=3,
        )
    partial = excinfo.value.partial_result
    assert partial is not None
    # The 404s that happened before the abort are not lost with the exception.
    assert len(partial.not_available) == len(good_candidates)
    # Coverage evidence spans every candidate actually attempted before abort,
    # both the settled ones and the forbidden ones that triggered it.
    covered_timestamps = {c.requested_timestamp for c in partial.coverage}
    attempted_timestamps = {ts.isoformat() for ts in fetcher.calls}
    assert covered_timestamps == attempted_timestamps
    assert len(covered_timestamps) < len(plan.fetches), (
        "expected the abort to stop before exhausting the whole plan"
    )


def test_run_backfill_partial_day_missing_tipoff_then_later_tipoff_resumes_and_expands_scope(
    session: Any, tmp_path: Path
) -> None:
    """Round-10 review point 3: settlement identity must be sensitive to
    expanded applicable-game scope, not just ``(date, anchor, resolved
    timestamp)``.

    Run 1 is a genuine ``--allow-missing-tipoff`` partial day: game A
    already has a tip-off; game B on the same date does not yet.
    ``build_plan`` can only anchor the date's near-tip candidates to game
    A's tip-off, and the near-tip-15 candidate settles covering only game
    A.

    Game B then gains a tip-off *later* than game A's -- the date's
    earliest tip-off (what near-tip candidates anchor to) does not change,
    so the near-tip-15 candidate's resolved instant, and therefore its
    checkpoint key, is provably identical across both plan builds. Naively
    keying settlement on that alone would report this candidate as already
    settled forever, even though the exact URL it names now also applies to
    game B and was already fetched. This proves resume instead detects the
    expanded scope, reprocesses the (idempotent) candidate, and both games
    end up correctly, cleanly covered.
    """
    teams = _seed_teams(session)
    game_a = _seed_game(
        session,
        nba_game_id="partial-day-a",
        game_date=date(2025, 12, 25),
        tipoff_utc=_et(2025, 12, 25, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    game_b = _seed_game(
        session,
        nba_game_id="partial-day-b",
        game_date=date(2025, 12, 25),
        tipoff_utc=None,  # missing at plan time -- a genuine partial day
        home_team_id=teams["SAC"],
        away_team_id=teams["MIL"],
    )

    # --- Run 1: only game A is ready; game B is reported missing. ---
    plan1 = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)
    assert [mg.game_id for mg in plan1.missing_tipoff] == [game_b.id]
    near_tip1 = next(pf for pf in plan1.fetches if pf.candidate.anchor == "near_tip_15")
    assert near_tip1.applicable_nba_game_ids == (game_a.nba_game_id,)

    def _zero_listed_payload(report_timestamp: datetime) -> InjuryReportParseResult:
        return InjuryReportParseResult(
            report_timestamp=report_timestamp,
            source_url="https://example.invalid/fixture",
            entries=(),  # a clean, zero-listed submission
        )

    # Every candidate this date's plan produces (evening_before plus all four
    # near-tip offsets) is before both games' tip-offs, so all of them --
    # not just near-tip-15 -- have a genuinely expanded scope once game B's
    # tip-off is known. Script a clean zero-listed answer for every one of
    # them; only the assertions below single out near-tip-15.
    checkpoint_path = tmp_path / "checkpoint.json"
    coverage_path = tmp_path / "coverage.json"
    checkpoint = Checkpoint.load(checkpoint_path)
    fetcher1 = _ScriptedFetcher(
        {
            pf.candidate.report_timestamp: _zero_listed_payload(pf.candidate.report_timestamp)
            for pf in plan1.fetches
        }
    )
    result1 = run_backfill(session, plan=plan1, fetch_and_parse=fetcher1, checkpoint=checkpoint)
    assert near_tip1.candidate in result1.fetched
    assert checkpoint.is_settled(near_tip1.candidate, applicable_nba_game_ids=(game_a.nba_game_id,))
    _persist_coverage(coverage_path, "2025-26", SeasonType.REGULAR, result1.coverage)

    # --- Game B gains a tip-off *later* than game A's: the date's earliest
    # tip-off, and therefore this near-tip candidate's resolved instant, is
    # unchanged. ---
    game_b.tipoff_utc = _et(2025, 12, 25, 19, 30)
    session.flush()

    plan2 = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)
    assert not plan2.missing_tipoff
    near_tip2 = next(pf for pf in plan2.fetches if pf.candidate.anchor == "near_tip_15")
    assert near_tip2.candidate.report_timestamp == near_tip1.candidate.report_timestamp
    assert set(near_tip2.applicable_nba_game_ids) == {game_a.nba_game_id, game_b.nba_game_id}

    # A naive (date, anchor, resolved timestamp)-only identity would report
    # this as already settled and skip it forever; the recorded scope from
    # run 1 does not cover game B, so it must not be considered settled.
    assert not checkpoint.is_settled(
        near_tip2.candidate, applicable_nba_game_ids=near_tip2.applicable_nba_game_ids
    )

    fetcher2 = _ScriptedFetcher(
        {
            pf.candidate.report_timestamp: _zero_listed_payload(pf.candidate.report_timestamp)
            for pf in plan2.fetches
        }
    )
    result2 = run_backfill(session, plan=plan2, fetch_and_parse=fetcher2, checkpoint=checkpoint)
    assert near_tip2.candidate not in result2.skipped_settled
    assert near_tip2.candidate in result2.fetched
    # Reprocessing is idempotent: the same zero-listed payload creates no
    # rows either time, proving this is a clean reprocess, not a crash or a
    # duplicate.
    assert result2.totals.created == 0
    _persist_coverage(coverage_path, "2025-26", SeasonType.REGULAR, result2.coverage)

    # The settled scope now covers both games.
    assert checkpoint.is_settled(near_tip2.candidate, applicable_nba_game_ids=(game_a.nba_game_id,))
    assert checkpoint.is_settled(near_tip2.candidate, applicable_nba_game_ids=(game_b.nba_game_id,))

    # And coverage now correctly classifies both games as a clean
    # submission -- game B is no longer stuck at `no_candidate_coverage`
    # just because it was missing a tip-off at plan-build time.
    coverage_report = CoverageReport.from_json(coverage_path.read_text(encoding="utf-8"))
    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    game_coverage = coverage_for_games(
        session, ready=ready, missing_tipoff=missing, coverage_report=coverage_report
    )
    by_game_id = {gc.game_id: gc for gc in game_coverage}
    assert by_game_id[game_a.id].outcome == "submitted_zero_listed"
    assert by_game_id[game_b.id].outcome == "submitted_zero_listed"


# ==========================================================================
# Canonical pregame observation selection (no lookahead, no fitting)
# ==========================================================================


def test_select_canonical_pregame_observations_picks_latest_before_tipoff(session: Any) -> None:
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="canon-1",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    player = Player(
        full_name="Keegan Murray", normalized_name="keegan murray", current_team_id=teams["SAC"]
    )
    session.add(player)
    session.flush()

    earlier = InjuryReportEntry(
        report_timestamp=_et(2025, 11, 1, 17, 30),
        game_date=date(2025, 11, 1),
        game_time_raw="07:00 (ET)",
        matchup_raw="SAC@MIL",
        team_raw="Sacramento Kings",
        team_id=teams["SAC"],
        game_id=game.id,
        player_name_raw="Murray, Keegan",
        player_id=player.id,
        status_raw="Questionable",
        status=InjuryReportStatus.QUESTIONABLE,
        source_url="https://example.invalid/fixture",
    )
    later_pregame = InjuryReportEntry(
        report_timestamp=_et(2025, 11, 1, 18, 30),
        game_date=date(2025, 11, 1),
        game_time_raw="07:00 (ET)",
        matchup_raw="SAC@MIL",
        team_raw="Sacramento Kings",
        team_id=teams["SAC"],
        game_id=game.id,
        player_name_raw="Murray, Keegan",
        player_id=player.id,
        status_raw="Out",
        status=InjuryReportStatus.OUT,
        source_url="https://example.invalid/fixture",
    )
    after_tipoff = InjuryReportEntry(
        report_timestamp=_et(2025, 11, 1, 20, 0),  # after tip-off: must never be canonical
        game_date=date(2025, 11, 1),
        game_time_raw="07:00 (ET)",
        matchup_raw="SAC@MIL",
        team_raw="Sacramento Kings",
        team_id=teams["SAC"],
        game_id=game.id,
        player_name_raw="Murray, Keegan",
        player_id=player.id,
        status_raw="Active",
        status=InjuryReportStatus.AVAILABLE,
        source_url="https://example.invalid/fixture",
    )
    session.add_all([earlier, later_pregame, after_tipoff])
    session.flush()

    observations = select_canonical_pregame_observations(session, game_ids=[game.id])

    assert len(observations) == 1
    obs = observations[0]
    assert obs.status is InjuryReportStatus.OUT  # the later pregame row, not the after-tipoff one
    assert obs.report_timestamp == _et(2025, 11, 1, 18, 30)


def test_select_canonical_pregame_observations_excludes_exact_tipoff_boundary(
    session: Any,
) -> None:
    """A report timestamped exactly at tip-off is lookahead, not pregame.

    The comparison in ``select_canonical_pregame_observations`` is a strict
    ``<``, not ``<=``: a masthead stamped at the literal instant the game
    locks is exactly as much lookahead as one stamped a second later, and
    must never be selected as the canonical pregame observation.
    """
    teams = _seed_teams(session)
    tipoff = _et(2025, 11, 1, 19, 0)
    game = _seed_game(
        session,
        nba_game_id="canon-boundary",
        game_date=date(2025, 11, 1),
        tipoff_utc=tipoff,
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    player = Player(
        full_name="Keegan Murray", normalized_name="keegan murray", current_team_id=teams["SAC"]
    )
    session.add(player)
    session.flush()

    pregame = InjuryReportEntry(
        report_timestamp=_et(2025, 11, 1, 18, 30),
        game_date=date(2025, 11, 1),
        game_time_raw="07:00 (ET)",
        matchup_raw="SAC@MIL",
        team_raw="Sacramento Kings",
        team_id=teams["SAC"],
        game_id=game.id,
        player_name_raw="Murray, Keegan",
        player_id=player.id,
        status_raw="Questionable",
        status=InjuryReportStatus.QUESTIONABLE,
        source_url="https://example.invalid/fixture",
    )
    exactly_at_tipoff = InjuryReportEntry(
        report_timestamp=tipoff,  # exactly equal to tip-off, not after it
        game_date=date(2025, 11, 1),
        game_time_raw="07:00 (ET)",
        matchup_raw="SAC@MIL",
        team_raw="Sacramento Kings",
        team_id=teams["SAC"],
        game_id=game.id,
        player_name_raw="Murray, Keegan",
        player_id=player.id,
        status_raw="Out",
        status=InjuryReportStatus.OUT,
        source_url="https://example.invalid/fixture",
    )
    session.add_all([pregame, exactly_at_tipoff])
    session.flush()

    observations = select_canonical_pregame_observations(session, game_ids=[game.id])

    assert len(observations) == 1
    obs = observations[0]
    # The exact-tipoff row is excluded; the strictly-earlier row wins.
    assert obs.report_timestamp == _et(2025, 11, 1, 18, 30)
    assert obs.status is InjuryReportStatus.QUESTIONABLE


def test_select_canonical_pregame_observations_ignores_not_yet_submitted(session: Any) -> None:
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="canon-2",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    unsubmitted = InjuryReportEntry(
        report_timestamp=_et(2025, 11, 1, 17, 30),
        game_date=date(2025, 11, 1),
        game_time_raw="07:00 (ET)",
        matchup_raw="SAC@MIL",
        team_raw="Sacramento Kings",
        game_id=game.id,
        player_name_raw="",
        status_raw="NOT YET SUBMITTED",
        status=InjuryReportStatus.NOT_YET_SUBMITTED,
        source_url="https://example.invalid/fixture",
    )
    session.add(unsubmitted)
    session.flush()

    observations = select_canonical_pregame_observations(session, game_ids=[game.id])

    assert observations == ()


def test_select_canonical_pregame_observations_empty_game_ids_is_a_noop(session: Any) -> None:
    assert select_canonical_pregame_observations(session, game_ids=[]) == ()


def test_select_canonical_pregame_observations_collapses_spelling_variants_by_player_id(
    session: Any,
) -> None:
    """Round-5 point 7: two captures spelling one real player differently collapse to one.

    A resolved ``player_id`` is the canonical identity for the collapse key,
    not the raw name string -- two report captures of the same real player,
    one spelled ``"Murray, Keegan"`` and a later one spelled
    ``"Murray,Keegan"`` (a parsing variant), must not double-count the
    player-game surface.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="collapse-0",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    player = Player(
        full_name="Keegan Murray", normalized_name="keegan murray", current_team_id=teams["SAC"]
    )
    session.add(player)
    session.flush()
    session.add_all(
        [
            InjuryReportEntry(
                report_timestamp=_et(2025, 10, 31, 17, 30),
                game_date=date(2025, 11, 1),
                game_time_raw="07:00 (ET)",
                matchup_raw="SAC@MIL",
                team_raw="Sacramento Kings",
                game_id=game.id,
                player_id=player.id,
                player_name_raw="Murray, Keegan",
                status_raw="Questionable",
                status=InjuryReportStatus.QUESTIONABLE,
                source_url="https://example.invalid/fixture-a",
            ),
            InjuryReportEntry(
                report_timestamp=_et(2025, 11, 1, 13, 0),
                game_date=date(2025, 11, 1),
                game_time_raw="07:00 (ET)",
                matchup_raw="SAC@MIL",
                team_raw="Sacramento Kings",
                game_id=game.id,
                player_id=player.id,
                player_name_raw="Murray,Keegan",  # spelling variant, same resolved player
                status_raw="Out",
                status=InjuryReportStatus.OUT,
                source_url="https://example.invalid/fixture-b",
            ),
        ]
    )
    session.flush()

    observations = select_canonical_pregame_observations(session, game_ids=[game.id])

    # One canonical player-game, not two -- the later (closer to tipoff) row wins.
    assert len(observations) == 1
    assert observations[0].player_id == player.id
    assert observations[0].status is InjuryReportStatus.OUT
    assert observations[0].report_timestamp == _et(2025, 11, 1, 13, 0)


def test_select_canonical_pregame_observations_keeps_unresolved_rows_distinct_by_raw_name(
    session: Any,
) -> None:
    """Without a resolved ``player_id``, two different raw names never merge."""
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="collapse-1",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    session.add_all(
        [
            InjuryReportEntry(
                report_timestamp=_et(2025, 10, 31, 17, 30),
                game_date=date(2025, 11, 1),
                game_time_raw="07:00 (ET)",
                matchup_raw="SAC@MIL",
                team_raw="Sacramento Kings",
                game_id=game.id,
                player_id=None,
                player_name_raw="Murray, Keegan",
                status_raw="Questionable",
                status=InjuryReportStatus.QUESTIONABLE,
                source_url="https://example.invalid/fixture-a",
            ),
            InjuryReportEntry(
                report_timestamp=_et(2025, 10, 31, 17, 30),
                game_date=date(2025, 11, 1),
                game_time_raw="07:00 (ET)",
                matchup_raw="SAC@MIL",
                team_raw="Sacramento Kings",
                game_id=game.id,
                player_id=None,
                player_name_raw="Fox, De'Aaron",
                status_raw="Out",
                status=InjuryReportStatus.OUT,
                source_url="https://example.invalid/fixture-a",
            ),
        ]
    )
    session.flush()

    observations = select_canonical_pregame_observations(session, game_ids=[game.id])

    assert {obs.player_name_raw for obs in observations} == {"Murray, Keegan", "Fox, De'Aaron"}


def test_canonical_pregame_observation_lead_time_is_realized_not_the_anchor_offset(
    session: Any,
) -> None:
    """Round-5 point 5: a later game's realized lead time exceeds the anchor's offset.

    Two games share one report date; ``build_plan`` anchors every near-tip
    candidate to the date's single *earliest* tip-off (see
    ``test_build_plan_anchors_near_tip_candidates_to_the_dates_own_earliest_tipoff``).
    A report filed once, before both tip-offs, therefore has a strictly
    *larger* realized lead time against the later game than the anchor offset
    that produced the shared candidate implies.
    """
    teams = _seed_teams(session)
    early_game = _seed_game(
        session,
        nba_game_id="lead-early",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    late_game = _seed_game(
        session,
        nba_game_id="lead-late",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 22, 0),
        home_team_id=teams["SAC"],
        away_team_id=teams["MIL"],
    )
    report_timestamp = _et(2025, 10, 31, 17, 30)
    session.add_all(
        [
            InjuryReportEntry(
                report_timestamp=report_timestamp,
                game_date=date(2025, 11, 1),
                game_time_raw="07:00 (ET)",
                matchup_raw="SAC@MIL",
                team_raw="Sacramento Kings",
                game_id=early_game.id,
                player_name_raw="Murray, Keegan",
                status_raw="Out",
                status=InjuryReportStatus.OUT,
                source_url="https://example.invalid/fixture",
            ),
            InjuryReportEntry(
                report_timestamp=report_timestamp,
                game_date=date(2025, 11, 1),
                game_time_raw="10:00 (ET)",
                matchup_raw="MIL@SAC",
                team_raw="Milwaukee Bucks",
                game_id=late_game.id,
                player_name_raw="Antetokounmpo, Giannis",
                status_raw="Out",
                status=InjuryReportStatus.OUT,
                source_url="https://example.invalid/fixture",
            ),
        ]
    )
    session.flush()

    observations = select_canonical_pregame_observations(
        session, game_ids=[early_game.id, late_game.id]
    )
    by_game = {obs.game_id: obs for obs in observations}

    early_lead = by_game[early_game.id].lead_time_minutes
    late_lead = by_game[late_game.id].lead_time_minutes
    assert early_lead == int((_et(2025, 11, 1, 19, 0) - report_timestamp).total_seconds() // 60)
    assert late_lead == int((_et(2025, 11, 1, 22, 0) - report_timestamp).total_seconds() // 60)
    assert late_lead > early_lead, (
        "the later game's realized lead time must exceed the earlier game's -- "
        "both share one report, but the later game's own tipoff is further away"
    )


# ==========================================================================
# Per-game observation coverage: durable evidence, not a bare count
# ==========================================================================


def test_coverage_for_games_distinguishes_observed_no_coverage_unsubmitted_and_missing(
    session: Any,
) -> None:
    """The four outcomes a bare observation count conflates, told apart.

    Four games, one of each: a real canonical observation; a game no fetched
    candidate ever covered; a game whose only pre-tipoff row was
    ``NOT_YET_SUBMITTED``; and a game with no ingested tip-off at all.
    """
    teams = _seed_teams(session)
    observed_game = _seed_game(
        session,
        nba_game_id="cov-observed",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    no_coverage_game = _seed_game(
        session,
        nba_game_id="cov-no-coverage",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    unsubmitted_game = _seed_game(
        session,
        nba_game_id="cov-unsubmitted",
        game_date=date(2025, 11, 3),
        tipoff_utc=_et(2025, 11, 3, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    missing_game = _seed_game(
        session,
        nba_game_id="cov-missing-tipoff",
        game_date=date(2025, 11, 4),
        tipoff_utc=None,
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )

    player = Player(
        full_name="Keegan Murray", normalized_name="keegan murray", current_team_id=teams["SAC"]
    )
    session.add(player)
    session.flush()

    session.add(
        InjuryReportEntry(
            report_timestamp=_et(2025, 11, 1, 17, 30),
            game_date=date(2025, 11, 1),
            game_time_raw="07:00 (ET)",
            matchup_raw="SAC@MIL",
            team_raw="Sacramento Kings",
            team_id=teams["SAC"],
            game_id=observed_game.id,
            player_name_raw="Murray, Keegan",
            player_id=player.id,
            status_raw="Questionable",
            status=InjuryReportStatus.QUESTIONABLE,
            source_url="https://example.invalid/fixture",
        )
    )
    session.add(
        InjuryReportEntry(
            report_timestamp=_et(2025, 11, 3, 17, 30),
            game_date=date(2025, 11, 3),
            game_time_raw="07:00 (ET)",
            matchup_raw="SAC@MIL",
            team_raw="Sacramento Kings",
            game_id=unsubmitted_game.id,
            player_name_raw="",
            status_raw="NOT YET SUBMITTED",
            status=InjuryReportStatus.NOT_YET_SUBMITTED,
            source_url="https://example.invalid/fixture",
        )
    )
    session.flush()

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(session, ready=ready, missing_tipoff=missing)
    by_game_id = {gc.game_id: gc for gc in coverage}

    assert by_game_id[observed_game.id].outcome == "observed"
    assert by_game_id[observed_game.id].observation_count == 1
    assert by_game_id[no_coverage_game.id].outcome == "no_candidate_coverage"
    assert by_game_id[unsubmitted_game.id].outcome == "not_yet_submitted_only"
    assert by_game_id[missing_game.id].outcome == "missing_tipoff"

    rendered = render_observation_coverage(coverage)
    assert "observed: 1" in rendered
    assert "no_candidate_coverage: 1" in rendered
    assert "not_yet_submitted_only: 1" in rendered
    assert "missing_tipoff: 1" in rendered


def test_coverage_for_games_distinguishes_legacy_excluded_from_submitted_zero_listed(
    session: Any,
) -> None:
    """Round-5 points 2 and 3: two more genuinely different "no observation" cases.

    ``legacy_excluded`` -- a legacy-schema row exists before tip-off, even
    one with a real listed status (not ``NOT_YET_SUBMITTED``), and must never
    be reported as ``not_yet_submitted_only``: this tool cannot trust *what*
    a legacy row says, only that a pre-migration-0014 row exists at all.

    ``submitted_zero_listed`` -- a masthead was fetched and its
    ``applicable_game_ids`` covered a game's window, but the parser emitted no
    row for it at all (the ordinary "team submitted, nothing to report"
    signal). Requires ``CoverageReport`` evidence; without it, this game
    would otherwise be indistinguishable from ``no_candidate_coverage``.
    """
    teams = _seed_teams(session)
    legacy_game = _seed_game(
        session,
        nba_game_id="cov-legacy",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    zero_listed_game = _seed_game(
        session,
        nba_game_id="cov-zero-listed",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    session.add(
        InjuryReportEntry(
            report_timestamp=_et(2025, 10, 31, 17, 30),
            game_date=date(2025, 11, 1),
            game_time_raw="07:00 (ET)",
            matchup_raw="SAC@MIL",
            team_raw="Sacramento Kings",
            game_id=legacy_game.id,
            player_name_raw="Murray, Keegan",
            status_raw="Questionable",  # a real listed status, not NOT_YET_SUBMITTED
            status=InjuryReportStatus.QUESTIONABLE,
            source_url="https://example.invalid/fixture",
            import_schema_version=LEGACY_EVIDENCE_SCHEMA_VERSION,
        )
    )
    session.flush()

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage_report = CoverageReport(
        season="2025-26",
        season_type="regular",
        candidates=[
            CandidateCoverage.from_candidate(
                ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
                season="2025-26",
                season_type="regular",
                applicable_game_ids=(zero_listed_game.id,),
                applicable_nba_game_ids=(zero_listed_game.nba_game_id,),
                outcome="fetched",
                canonical_report_timestamp=_et(2025, 11, 1, 17, 30),
                entries_total=0,
            )
        ],
    )
    coverage = coverage_for_games(
        session, ready=ready, missing_tipoff=missing, coverage_report=coverage_report
    )
    by_game_id = {gc.game_id: gc for gc in coverage}

    assert by_game_id[legacy_game.id].outcome == "legacy_excluded"
    assert by_game_id[zero_listed_game.id].outcome == "submitted_zero_listed"

    rendered = render_observation_coverage(coverage)
    assert "legacy_excluded: 1" in rendered
    assert "submitted_zero_listed: 1" in rendered


def test_coverage_for_games_does_not_let_an_unresolved_listed_entry_become_zero_listed(
    session: Any,
) -> None:
    """Round-6 review point 2: exact coordinator reproduction.

    A masthead was fetched and its ``applicable_game_ids`` covered this
    game's window with zero *resolved* rows -- but a real, pre-tipoff,
    listed-status (``OUT``) row for this exact team/date exists whose
    ``game_id`` never resolved (a home/away tricode mismatch or similar).
    The old ``game_id.in_(...)``-scoped query made that row invisible,
    letting the game fall through to the clean ``submitted_zero_listed``
    claim. A clean zero-listed claim is only correct when no unresolved
    evidence could apply -- this row unambiguously matches this game by
    date + tricode pair, so it must veto the clean claim outright.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="cov-unresolved-listed",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    # A real, listed, pre-tipoff status -- but game_id never resolved.
    session.add(
        InjuryReportEntry(
            report_timestamp=_et(2025, 11, 2, 17, 30),
            game_date=date(2025, 11, 2),
            game_time_raw="07:00 (ET)",
            matchup_raw="SAC@MIL",
            team_raw="Sacramento Kings",
            game_id=None,
            player_name_raw="Murray, Keegan",
            status_raw="Out",
            status=InjuryReportStatus.OUT,
            source_url="https://example.invalid/fixture",
        )
    )
    session.flush()

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage_report = CoverageReport(
        season="2025-26",
        season_type="regular",
        candidates=[
            CandidateCoverage.from_candidate(
                ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
                season="2025-26",
                season_type="regular",
                applicable_game_ids=(game.id,),
                applicable_nba_game_ids=(game.nba_game_id,),
                outcome="fetched",
                canonical_report_timestamp=_et(2025, 11, 1, 17, 30),
                entries_total=0,
            )
        ],
    )
    coverage = coverage_for_games(
        session, ready=ready, missing_tipoff=missing, coverage_report=coverage_report
    )
    by_game_id = {gc.game_id: gc for gc in coverage}

    assert by_game_id[game.id].outcome == "unresolved_evidence", (
        "a real listed pre-tipoff row this tool cannot resolve must never be "
        "silently dropped in favour of a clean submitted_zero_listed claim"
    )
    assert by_game_id[game.id].outcome != "submitted_zero_listed"

    rendered = render_observation_coverage(coverage)
    assert "unresolved_evidence: 1" in rendered


def test_coverage_for_games_vetoes_zero_listed_for_a_genuinely_unattributable_row(
    session: Any,
) -> None:
    """Round-6 review point 2: the conservative fallback when even date+tricode fails.

    A current-schema, listed-status, unresolved row whose matchup cannot be
    matched to *any* single ``ready`` game (garbled/unknown tricodes) still
    must not let a same-date game claim a clean zero-listed submission --
    the evidence *could* apply to it and must not be silently dropped.
    """
    teams = _seed_teams(session)
    zero_listed_game = _seed_game(
        session,
        nba_game_id="cov-unattributable-veto",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    session.add(
        InjuryReportEntry(
            report_timestamp=_et(2025, 11, 2, 17, 30),
            game_date=date(2025, 11, 2),
            game_time_raw="07:00 (ET)",
            matchup_raw="XYZ@ABC",  # unresolvable -- no team matches these tricodes
            team_raw="Unresolvable Team",
            game_id=None,
            player_name_raw="Someone, Unresolved",
            status_raw="Questionable",
            status=InjuryReportStatus.QUESTIONABLE,
            source_url="https://example.invalid/fixture",
        )
    )
    session.flush()

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage_report = CoverageReport(
        season="2025-26",
        season_type="regular",
        candidates=[
            CandidateCoverage.from_candidate(
                ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
                season="2025-26",
                season_type="regular",
                applicable_game_ids=(zero_listed_game.id,),
                applicable_nba_game_ids=(zero_listed_game.nba_game_id,),
                outcome="fetched",
                canonical_report_timestamp=_et(2025, 11, 1, 17, 30),
                entries_total=0,
            )
        ],
    )
    coverage = coverage_for_games(
        session, ready=ready, missing_tipoff=missing, coverage_report=coverage_report
    )
    by_game_id = {gc.game_id: gc for gc in coverage}

    assert by_game_id[zero_listed_game.id].outcome == "unresolved_evidence"
    assert by_game_id[zero_listed_game.id].outcome != "submitted_zero_listed"


def test_coverage_for_games_revalidates_canonical_timestamp_against_current_tipoff(
    session: Any,
) -> None:
    """Round-6 review point 3: a tip-off correction can move a masthead past tip.

    A fetched candidate's ``canonical_report_timestamp`` was strictly
    pre-tip when it was fetched, but the game's tip-off is later corrected
    to an earlier instant, retroactively making that same masthead
    post-tip. Stale coverage must not go on proving a clean
    ``submitted_zero_listed`` claim once it can no longer be shown to
    predate the game it claims to cover.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="cov-stale-tipoff",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    canonical_ts = _et(2025, 11, 2, 18, 30)  # pre-tip against the *original* 19:00 tip-off
    coverage_report = CoverageReport(
        season="2025-26",
        season_type="regular",
        candidates=[
            CandidateCoverage.from_candidate(
                ReportCandidate(date(2025, 11, 2), "near_tip_30", canonical_ts),
                season="2025-26",
                season_type="regular",
                applicable_game_ids=(game.id,),
                applicable_nba_game_ids=(game.nba_game_id,),
                outcome="fetched",
                canonical_report_timestamp=canonical_ts,
                entries_total=0,
            )
        ],
    )

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage_before = coverage_for_games(
        session, ready=ready, missing_tipoff=missing, coverage_report=coverage_report
    )
    assert {gc.game_id: gc for gc in coverage_before}[game.id].outcome == "submitted_zero_listed"

    # The schedule is corrected: the game actually tipped off *before* the
    # masthead's own canonical timestamp -- the fetched evidence is now stale.
    game.tipoff_utc = _et(2025, 11, 2, 18, 0)
    session.flush()

    ready_after, missing_after = games_to_backfill(
        session, season="2025-26", season_type=SeasonType.REGULAR
    )
    coverage_after = coverage_for_games(
        session, ready=ready_after, missing_tipoff=missing_after, coverage_report=coverage_report
    )
    assert {gc.game_id: gc for gc in coverage_after}[game.id].outcome != "submitted_zero_listed", (
        "stale post-tip coverage must not go on proving a clean submission claim "
        "after a tip-off correction"
    )
    assert {gc.game_id: gc for gc in coverage_after}[game.id].outcome == "no_candidate_coverage"


def test_coverage_for_games_stale_and_corrected_coverage_can_coexist(session: Any) -> None:
    """Round-6 review point 3: one stale candidate must not veto another valid one.

    Two fetched candidates apply to the same game: one now stale (its
    canonical timestamp is post-tip after a correction) and one still
    genuinely pre-tip. The stale one is excluded, but the still-valid one
    must still support ``submitted_zero_listed`` -- staleness is assessed
    per candidate, not per game.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="cov-stale-and-valid",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 18, 0),  # already corrected/current
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    stale_ts = _et(2025, 11, 2, 18, 30)  # now *after* the corrected tip-off -- stale
    valid_ts = _et(2025, 11, 1, 17, 30)  # evening-before -- still genuinely pre-tip
    coverage_report = CoverageReport(
        season="2025-26",
        season_type="regular",
        candidates=[
            CandidateCoverage.from_candidate(
                ReportCandidate(date(2025, 11, 2), "near_tip_30", stale_ts),
                season="2025-26",
                season_type="regular",
                applicable_game_ids=(game.id,),
                applicable_nba_game_ids=(game.nba_game_id,),
                outcome="fetched",
                canonical_report_timestamp=stale_ts,
                entries_total=0,
            ),
            CandidateCoverage.from_candidate(
                ReportCandidate(date(2025, 11, 2), "evening_before", valid_ts),
                season="2025-26",
                season_type="regular",
                applicable_game_ids=(game.id,),
                applicable_nba_game_ids=(game.nba_game_id,),
                outcome="fetched",
                canonical_report_timestamp=valid_ts,
                entries_total=0,
            ),
        ],
    )

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(
        session, ready=ready, missing_tipoff=missing, coverage_report=coverage_report
    )
    assert {gc.game_id: gc for gc in coverage}[game.id].outcome == "submitted_zero_listed"


# ==========================================================================
# Round-7 adversarial regressions: current-DB tipoff, per-game unresolved
# applicability, and stable NBA-game-id evidence identity
# ==========================================================================


def test_coverage_for_games_uses_current_db_tipoff_not_stale_caller_snapshot(
    session: Any,
) -> None:
    """Round-7 review point 1: a stale ``ready`` snapshot must not launder post-tip evidence as
    clean.

    ``ready`` is ordinarily built by an earlier ``games_to_backfill`` call
    and can go stale before ``coverage_for_games`` runs -- a schedule
    correction landing in between must not let evidence that is genuinely
    post-tip against the *current* database value still be trusted as
    pre-tip because the caller's own snapshot disagrees. This game's
    current DB tip-off is 19:00 (already corrected); the caller's snapshot
    still thinks it is 20:00. A masthead at 19:30 is pre-tip against the
    stale snapshot but post-tip against the corrected, current value.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="race-current-tipoff",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),  # corrected/current
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    stale_ready = (
        BackfillGame(
            game_id=game.id,
            nba_game_id=game.nba_game_id,
            game_date=game.game_date,
            tipoff_utc=_et(2025, 11, 2, 20, 0),  # the caller's own stale snapshot
        ),
    )
    canonical_ts = _et(2025, 11, 2, 19, 30)  # pre-tip vs stale 20:00, post-tip vs current 19:00
    coverage_report = CoverageReport(
        season="2025-26",
        season_type="regular",
        candidates=[
            CandidateCoverage.from_candidate(
                ReportCandidate(date(2025, 11, 2), "near_tip_30", canonical_ts),
                season="2025-26",
                season_type="regular",
                applicable_game_ids=(game.id,),
                applicable_nba_game_ids=(game.nba_game_id,),
                outcome="fetched",
                canonical_report_timestamp=canonical_ts,
                entries_total=0,
            )
        ],
    )

    coverage = coverage_for_games(
        session, ready=stale_ready, missing_tipoff=(), coverage_report=coverage_report
    )
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[game.id].outcome != "submitted_zero_listed", (
        "a stale caller-supplied tip-off snapshot must not launder "
        "post-tip evidence (against the corrected, current DB tip-off) "
        "as a clean submitted_zero_listed claim"
    )
    assert by_game_id[game.id].outcome == "no_candidate_coverage"


def _seed_staggered_games(session: Any) -> tuple[Any, Any]:
    """Two same-date games with staggered tip-offs, for per-game veto tests."""
    teams = _seed_teams(session)
    early = _seed_game(
        session,
        nba_game_id="stagger-early",
        game_date=date(2025, 11, 5),
        tipoff_utc=_et(2025, 11, 5, 18, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    gsw = NbaTeam(nba_team_id=1610612744, abbreviation="GSW", name="Golden State Warriors")
    den = NbaTeam(nba_team_id=1610612743, abbreviation="DEN", name="Denver Nuggets")
    session.add_all([gsw, den])
    session.flush()
    late = _seed_game(
        session,
        nba_game_id="stagger-late",
        game_date=date(2025, 11, 5),
        tipoff_utc=_et(2025, 11, 5, 20, 0),
        home_team_id=gsw.id,
        away_team_id=den.id,
    )
    return early, late


def _unattributable_row(
    *,
    report_timestamp: datetime,
    status: InjuryReportStatus = InjuryReportStatus.OUT,
    import_schema_version: int = CURRENT_EVIDENCE_SCHEMA_VERSION,
) -> InjuryReportEntry:
    """A row that can never resolve to a single game by id or tricode.

    ``matchup_raw`` names two teams (``PHX@LAL``) that are never seeded
    among the games in scope, so date+tricode matching finds zero
    candidates -- genuinely unattributable, not merely unresolved-by-id.
    """
    return InjuryReportEntry(
        report_timestamp=report_timestamp,
        game_date=date(2025, 11, 5),
        game_time_raw="07:00 (ET)",
        matchup_raw="PHX@LAL",
        team_raw="Phoenix Suns",
        game_id=None,
        player_name_raw="Doe, Jane",
        status_raw=status.value.title(),
        status=status,
        source_url="https://example.invalid/fixture",
        import_schema_version=import_schema_version,
    )


def test_coverage_for_games_unattributable_row_before_both_tipoffs_vetoes_both_games(
    session: Any,
) -> None:
    """Round-7 review point 2: a row strictly before every candidate's tip-off vetoes all of
    them."""
    early, late = _seed_staggered_games(session)
    session.add(_unattributable_row(report_timestamp=_et(2025, 11, 5, 17, 0)))
    session.flush()

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(session, ready=ready, missing_tipoff=missing)
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[early.id].outcome == "unresolved_evidence"
    assert by_game_id[late.id].outcome == "unresolved_evidence"


def test_coverage_for_games_unattributable_row_between_tipoffs_vetoes_only_the_later_game(
    session: Any,
) -> None:
    """Round-7 review point 2: a row cannot veto a game it demonstrably post-dates.

    Published at 19:00 -- after the early game's 18:00 tip-off but before
    the late game's 20:00 -- it can only still plausibly concern the late
    game.
    """
    early, late = _seed_staggered_games(session)
    session.add(_unattributable_row(report_timestamp=_et(2025, 11, 5, 19, 0)))
    session.flush()

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(session, ready=ready, missing_tipoff=missing)
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[early.id].outcome != "unresolved_evidence", (
        "a row published after the early game's tip-off cannot be pregame "
        "evidence for it, and must not veto it"
    )
    assert by_game_id[late.id].outcome == "unresolved_evidence"


def test_coverage_for_games_unattributable_row_after_both_tipoffs_vetoes_neither_game(
    session: Any,
) -> None:
    """Round-7 review point 2: a row published after every candidate's tip-off vetoes nothing."""
    early, late = _seed_staggered_games(session)
    session.add(_unattributable_row(report_timestamp=_et(2025, 11, 5, 21, 0)))
    session.flush()

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(session, ready=ready, missing_tipoff=missing)
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[early.id].outcome != "unresolved_evidence"
    assert by_game_id[late.id].outcome != "unresolved_evidence"


def test_coverage_for_games_unattributable_not_yet_submitted_row_still_vetoes(
    session: Any,
) -> None:
    """Round-7 review point 2: ``NOT_YET_SUBMITTED`` proves genuine uncertainty too.

    Before round 7, an unattributable row's status was excluded from the
    veto whenever it was ``NOT_YET_SUBMITTED``. That was backwards: an
    ambiguous row that itself proves nothing has even been submitted yet is
    at least as strong a reason to withhold a clean claim as a listed
    status would be.
    """
    early, late = _seed_staggered_games(session)
    session.add(
        _unattributable_row(
            report_timestamp=_et(2025, 11, 5, 17, 0),
            status=InjuryReportStatus.NOT_YET_SUBMITTED,
        )
    )
    session.flush()

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(session, ready=ready, missing_tipoff=missing)
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[early.id].outcome == "unresolved_evidence"
    assert by_game_id[late.id].outcome == "unresolved_evidence"


def test_coverage_for_games_unattributable_legacy_row_does_not_veto(session: Any) -> None:
    """Round-7 review point 2: only current-schema unresolved evidence participates in the veto.

    A legacy row's natural-key collision risk (pre-migration-0013) already
    makes it untrustworthy on its own terms; it must not also be smuggled
    back in as an unattributable-row veto, which would give legacy data
    more power over the outcome than current-schema data earns.
    """
    early, late = _seed_staggered_games(session)
    session.add(
        _unattributable_row(
            report_timestamp=_et(2025, 11, 5, 17, 0),
            import_schema_version=LEGACY_EVIDENCE_SCHEMA_VERSION,
        )
    )
    session.flush()

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(session, ready=ready, missing_tipoff=missing)
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[early.id].outcome != "unresolved_evidence"
    assert by_game_id[late.id].outcome != "unresolved_evidence"


def test_coverage_for_games_unresolved_evidence_outranks_legacy_excluded(session: Any) -> None:
    """Round-7 review point 2: current unresolved evidence must not be masked by legacy_excluded.

    A game with both a legacy, attributable row *and* separate,
    current-schema, unattributable evidence that genuinely still concerns
    it must report ``unresolved_evidence`` -- the more specific, stronger
    caveat -- not the coarser ``legacy_excluded``, which would understate
    what is actually uncertain about this game's evidence.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="legacy-and-unresolved",
        game_date=date(2025, 11, 6),
        tipoff_utc=_et(2025, 11, 6, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    # A legacy, attributable row -- resolved game_id, real listed status.
    session.add(
        InjuryReportEntry(
            report_timestamp=_et(2025, 11, 6, 17, 0),
            game_date=date(2025, 11, 6),
            game_time_raw="07:00 (ET)",
            matchup_raw="SAC@MIL",
            team_raw="Sacramento Kings",
            game_id=game.id,
            player_name_raw="Murray, Keegan",
            status_raw="Out",
            status=InjuryReportStatus.OUT,
            source_url="https://example.invalid/fixture",
            import_schema_version=LEGACY_EVIDENCE_SCHEMA_VERSION,
        )
    )
    # A separate, current-schema, unattributable row for the same date,
    # strictly pre-tip for this game.
    session.add(
        InjuryReportEntry(
            report_timestamp=_et(2025, 11, 6, 18, 0),
            game_date=date(2025, 11, 6),
            game_time_raw="07:00 (ET)",
            matchup_raw="PHX@LAL",
            team_raw="Phoenix Suns",
            game_id=None,
            player_name_raw="Doe, Jane",
            status_raw="Out",
            status=InjuryReportStatus.OUT,
            source_url="https://example.invalid/fixture",
        )
    )
    session.flush()

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(session, ready=ready, missing_tipoff=missing)
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[game.id].outcome == "unresolved_evidence", (
        "current-schema unresolved evidence must outrank legacy_excluded, not be masked by it"
    )


def test_coverage_for_games_stable_nba_id_prevents_reused_surrogate_id_transfer(
    session: Any,
) -> None:
    """Round-7 review point 3: a reused surrogate DB id must not transfer stale coverage.

    After a DB rebuild/reingestion, ``NbaGame.id`` can be reassigned to an
    unrelated game. This candidate's ``applicable_game_ids`` happens to
    name the *current* game's surrogate id, but its
    ``applicable_nba_game_ids`` names a wholly different, no-longer-live
    NBA game -- proving the record actually covers something else.
    Matching must go through the stable identifier, never the reused
    surrogate one.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="current-game-after-rebuild",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    canonical_ts = _et(2025, 11, 1, 17, 30)  # genuinely pre-tip
    coverage_report = CoverageReport(
        season="2025-26",
        season_type="regular",
        candidates=[
            CandidateCoverage.from_candidate(
                ReportCandidate(date(2025, 11, 2), "evening_before", canonical_ts),
                season="2025-26",
                season_type="regular",
                # Surrogate id matches this game's id purely by coincidence
                # of DB rebuild/reassignment -- it must not be trusted alone.
                applicable_game_ids=(game.id,),
                applicable_nba_game_ids=("deleted-game-before-rebuild",),
                outcome="fetched",
                canonical_report_timestamp=canonical_ts,
                entries_total=0,
            )
        ],
    )

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(
        session, ready=ready, missing_tipoff=missing, coverage_report=coverage_report
    )
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[game.id].outcome != "submitted_zero_listed", (
        "a coverage record naming a different, stale stable NBA game id "
        "must not be trusted for this game merely because its surrogate "
        "DB id happens to match after a rebuild/reassignment"
    )
    assert by_game_id[game.id].outcome == "no_candidate_coverage"


def test_coverage_for_games_legacy_evidence_schema_version_is_excluded_fail_closed(
    session: Any,
) -> None:
    """Round-7 review point 3: pre-fix coverage evidence is never trusted, even if it looks valid.

    A ``CandidateCoverage`` record persisted before round-7's stable-identity
    fix is stamped ``LEGACY_COVERAGE_SCHEMA_VERSION`` on load (see
    ``CoverageReport.from_json``). Even when its ``applicable_nba_game_ids``
    happens to match the current game and its timestamp is genuinely
    pre-tip, it must still be excluded -- the schema-version gate is
    unconditional, not a fallback used only when identity looks ambiguous.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="legacy-coverage-schema",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    canonical_ts = _et(2025, 11, 1, 17, 30)
    candidate = ReportCandidate(date(2025, 11, 2), "evening_before", canonical_ts)
    legacy_coverage = CandidateCoverage(
        report_date=candidate.report_date.isoformat(),
        anchor=candidate.anchor,
        era="legacy",
        anchor_offset_minutes=candidate.anchor_offset_minutes,
        requested_timestamp=candidate.report_timestamp.isoformat(),
        applicable_game_ids=(game.id,),
        applicable_nba_game_ids=(game.nba_game_id,),
        outcome="fetched",
        canonical_report_timestamp=canonical_ts.isoformat(),
        entries_total=0,
        evidence_schema_version=LEGACY_COVERAGE_SCHEMA_VERSION,
    )
    coverage_report = CoverageReport(
        season="2025-26", season_type="regular", candidates=[legacy_coverage]
    )

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(
        session, ready=ready, missing_tipoff=missing, coverage_report=coverage_report
    )
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[game.id].outcome != "submitted_zero_listed", (
        "legacy-schema coverage evidence must be excluded unconditionally, "
        "even when its stable id and timestamp look valid"
    )
    assert by_game_id[game.id].outcome == "no_candidate_coverage"


# ==========================================================================
# Round-9 adversarial regressions: ORM identity-map staleness, full
# schedule-scope binding, and duplicate/leaked coverage output
# ==========================================================================


def test_coverage_for_games_uses_database_current_tipoff_despite_retained_orm_identity(
    database: Any,
) -> None:
    """Round-9 review point 1: a second session's committed correction must win even when
    this session's own identity map still holds the pre-correction row.

    Round-7 added a fresh re-query for the "current DB tipoff" instead of
    trusting the caller's snapshot -- but a plain re-query is not
    automatically a fresh *read*. By default SQLAlchemy leaves an
    already-identity-mapped instance's attributes untouched when a query's
    result row names the same primary key, rather than overwriting them
    with the fresh row. ``expire_on_commit=False`` (this project's session
    configuration) means even this session's own commit does not clear
    that staleness. Only ``populate_existing=True`` forces a real
    repopulation, which is what this proves is in place.
    """
    with database.session() as seed_session:
        teams = _seed_teams(seed_session)
        game = _seed_game(
            seed_session,
            nba_game_id="identity-map-race",
            game_date=date(2025, 11, 2),
            tipoff_utc=_et(2025, 11, 2, 19, 0),
            home_team_id=teams["MIL"],
            away_team_id=teams["SAC"],
        )
        game_id = game.id
        nba_game_id = game.nba_game_id

    classify_session = database.session_factory()
    try:
        # Load the game into classify_session's own identity map at its
        # original 19:00 tip-off, then commit. expire_on_commit=False means
        # the loaded attributes survive the commit unexpired -- exactly
        # like a long-lived session that already touched this row once for
        # an unrelated reason.
        stale = classify_session.get(NbaGame, game_id)
        assert stale is not None
        assert stale.tipoff_utc == _et(2025, 11, 2, 19, 0)
        classify_session.commit()

        # A wholly separate session corrects the tip-off and commits.
        # classify_session never itself re-reads this row in between.
        with database.session() as correcting_session:
            row = correcting_session.get(NbaGame, game_id)
            assert row is not None
            row.tipoff_utc = _et(2025, 11, 2, 20, 0)

        # 19:30 is post-tip against the stale 19:00 value classify_session
        # still has cached, but strictly pre-tip against the corrected
        # 20:00 -- the two are cleanly distinguishable outcomes.
        canonical_ts = _et(2025, 11, 2, 19, 30)
        coverage_report = CoverageReport(
            season="2025-26",
            season_type="regular",
            candidates=[
                CandidateCoverage.from_candidate(
                    ReportCandidate(date(2025, 11, 2), "near_tip_30", canonical_ts),
                    season="2025-26",
                    season_type="regular",
                    applicable_game_ids=(game_id,),
                    applicable_nba_game_ids=(nba_game_id,),
                    outcome="fetched",
                    canonical_report_timestamp=canonical_ts,
                    entries_total=0,
                )
            ],
        )
        ready = (
            BackfillGame(
                game_id=game_id,
                nba_game_id=nba_game_id,
                game_date=date(2025, 11, 2),
                tipoff_utc=_et(2025, 11, 2, 19, 0),  # the caller's own snapshot, also stale
            ),
        )

        coverage = coverage_for_games(
            classify_session, ready=ready, missing_tipoff=(), coverage_report=coverage_report
        )
        by_game_id = {gc.game_id: gc for gc in coverage}
        assert by_game_id[game_id].outcome == "submitted_zero_listed", (
            "classification must see the other session's committed tip-off "
            "correction, not this session's own already-loaded, stale copy"
        )
    finally:
        classify_session.rollback()
        classify_session.close()


def test_coverage_for_games_reads_one_atomic_snapshot_despite_a_correction_committed_mid_call(
    database: Any,
) -> None:
    """Round-10 review point 1: classification must derive every decision
    from one authoritative snapshot, not several sequential queries a
    concurrent commit could land between.

    The prior implementation issued an initial ``NbaGame`` query to build
    ``games_by_id`` and a *second*, later query (inside
    ``select_canonical_pregame_observations``, solely to build tip-offs)
    that could disagree with the first if a schedule correction landed
    between them -- game X's trust-classification could see an old
    tip-off while game Y's observation lead-time, computed moments later
    in the same call, already saw a new one. Collapsing both reads into
    one ``SELECT`` (see the module docstring above ``coverage_for_games``)
    makes that structurally impossible: there is no second statement left
    for anything to land between.

    This proves both halves of that claim with a real second connection,
    not a mock or a manually-sequenced "before" write:

    1. it counts the actual game-state ``SELECT`` statements this call
       issues (matched by the unique ``home_abbr`` column label only this
       query selects) and asserts there is exactly one;
    2. it registers a ``before_cursor_execute`` hook that -- fired by the
       engine itself as that exact statement is about to run, not by test
       code sequenced before calling ``coverage_for_games`` -- has a
       wholly separate session commit a tip-off correction for one game
       and retract another game's tip-off entirely, genuinely *during*
       this call's execution. Because both games are named in the very
       same single statement, the one classification call can only ever
       see one self-consistent instant of both facts together -- never
       old-X-with-new-Y, new-X-with-old-Y, or the caller's stale snapshot.
    """
    with database.session() as seed_session:
        teams = _seed_teams(seed_session)
        game_x = _seed_game(
            seed_session,
            nba_game_id="atomic-snapshot-x",
            game_date=date(2025, 11, 10),
            tipoff_utc=_et(2025, 11, 10, 19, 0),
            home_team_id=teams["MIL"],
            away_team_id=teams["SAC"],
        )
        game_y = _seed_game(
            seed_session,
            nba_game_id="atomic-snapshot-y",
            game_date=date(2025, 11, 10),
            tipoff_utc=_et(2025, 11, 10, 19, 0),
            home_team_id=teams["SAC"],
            away_team_id=teams["MIL"],
        )
        game_x_id, game_x_nba_id = game_x.id, game_x.nba_game_id
        game_y_id, game_y_nba_id = game_y.id, game_y.nba_game_id

    classify_session = database.session_factory()
    statement_count = 0
    corrected = False

    def _correct_mid_statement(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        nonlocal statement_count, corrected
        if "home_abbr" not in statement:
            return  # not the classification snapshot query -- ignore
        statement_count += 1
        if corrected:
            return
        corrected = True
        # A wholly separate session, triggered by the engine itself right
        # as the classification statement is about to run -- not sequenced
        # by test code before calling coverage_for_games.
        with database.session() as correcting_session:
            gx = correcting_session.get(NbaGame, game_x_id)
            gy = correcting_session.get(NbaGame, game_y_id)
            assert gx is not None
            assert gy is not None
            gx.tipoff_utc = _et(2025, 11, 10, 20, 0)  # corrected, an hour later
            gy.tipoff_utc = None  # retracted entirely, mid-call

    event.listen(database.engine, "before_cursor_execute", _correct_mid_statement)
    try:
        # The caller's own `ready` snapshot is stale in both directions and
        # must be ignored -- classification derives everything fresh from
        # its own single query.
        ready = (
            BackfillGame(
                game_id=game_x_id,
                nba_game_id=game_x_nba_id,
                game_date=date(2025, 11, 10),
                tipoff_utc=_et(2025, 11, 10, 19, 0),
            ),
            BackfillGame(
                game_id=game_y_id,
                nba_game_id=game_y_nba_id,
                game_date=date(2025, 11, 10),
                tipoff_utc=_et(2025, 11, 10, 19, 0),
            ),
        )
        canonical_ts = _et(2025, 11, 10, 19, 30)
        coverage_report = CoverageReport(
            season="2025-26",
            season_type="regular",
            candidates=[
                CandidateCoverage.from_candidate(
                    ReportCandidate(date(2025, 11, 10), "near_tip_30", canonical_ts),
                    season="2025-26",
                    season_type="regular",
                    applicable_game_ids=(game_x_id, game_y_id),
                    applicable_nba_game_ids=(game_x_nba_id, game_y_nba_id),
                    outcome="fetched",
                    canonical_report_timestamp=canonical_ts,
                    entries_total=0,
                )
            ],
        )
        game_coverage = coverage_for_games(
            classify_session,
            ready=ready,
            missing_tipoff=(),
            coverage_report=coverage_report,
        )
    finally:
        event.remove(database.engine, "before_cursor_execute", _correct_mid_statement)
        classify_session.rollback()
        classify_session.close()

    # Exactly one statement read this call's entire view of both games'
    # state -- there is no second query left for a correction to land
    # between.
    assert statement_count == 1

    by_game_id = {gc.game_id: gc for gc in game_coverage}
    # game_x: the single snapshot query executes *after* the mid-call
    # commit (the hook fires immediately before cursor.execute), so it
    # sees the corrected 20:00 tip-off -- 19:30 is strictly pre-tip
    # against it, a clean submission.
    assert by_game_id[game_x_id].outcome == "submitted_zero_listed"
    # game_y: its tip-off was retracted in that very same commit. The one
    # snapshot query reads that too, in the same statement -- game_y is
    # reported honestly as missing_tipoff, not left holding the stale,
    # pre-correction 19:00 value the caller's `ready` snapshot still shows.
    assert by_game_id[game_y_id].outcome == "missing_tipoff"


def test_coverage_for_games_single_snapshot_promotes_a_newly_tipped_off_missing_game(
    database: Any,
) -> None:
    """Round-11 review point 1: the one-statement snapshot must cover
    ``missing_tipoff`` too, not just ``ready``.

    Every prior revision scoped its single authoritative ``SELECT`` to
    ``ready``'s game ids only, so a game the caller had already classified
    as ``missing_tipoff`` (no tip-off known when ``games_to_backfill`` ran)
    was invisible to that snapshot -- even if a tip-off was ingested for it
    moments later, genuinely *during* this call. This proves the fix with a
    real second connection and the same ``before_cursor_execute`` hook
    technique as the sibling atomic-snapshot test above: the correcting
    session commits a brand-new tip-off for a game the caller still
    believes has none, right as the classification statement is about to
    run, and a canonical observation already exists for it. The single
    snapshot must see the new tip-off and promote the game out of
    ``missing_tipoff`` into full classification within this same call --
    not defer to the caller's now-stale ``missing_tipoff`` partition.
    """
    with database.session() as seed_session:
        teams = _seed_teams(seed_session)
        game = _seed_game(
            seed_session,
            nba_game_id="promoted-missing-tipoff",
            game_date=date(2025, 11, 12),
            tipoff_utc=None,  # genuinely no tip-off yet, per the caller's snapshot
            home_team_id=teams["MIL"],
            away_team_id=teams["SAC"],
        )
        game_id, game_nba_id = game.id, game.nba_game_id
        # A canonical observation already sitting in the database, strictly
        # before the tip-off the correcting session is about to commit --
        # invisible to any classification that never re-queries this game.
        seed_session.add(
            InjuryReportEntry(
                report_timestamp=_et(2025, 11, 12, 17, 30),
                game_date=date(2025, 11, 12),
                game_time_raw="07:00 (ET)",
                matchup_raw="SAC@MIL",
                team_raw="Sacramento Kings",
                game_id=game_id,
                player_name_raw="Fox, De'Aaron",
                status_raw="Out",
                status=InjuryReportStatus.OUT,
                source_url="https://example.invalid/fixture",
            )
        )
        seed_session.commit()

    classify_session = database.session_factory()
    statement_count = 0
    corrected = False

    def _promote_mid_statement(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        nonlocal statement_count, corrected
        if "home_abbr" not in statement:
            return  # not the classification snapshot query -- ignore
        statement_count += 1
        if corrected:
            return
        corrected = True
        with database.session() as correcting_session:
            g = correcting_session.get(NbaGame, game_id)
            assert g is not None
            g.tipoff_utc = _et(2025, 11, 12, 19, 0)  # newly ingested, mid-call

    event.listen(database.engine, "before_cursor_execute", _promote_mid_statement)
    try:
        # The caller's own classification is stale in exactly the direction
        # this review point names: it still believes this game has no
        # tip-off at all.
        missing = (
            MissingTipoffGame(
                game_id=game_id, nba_game_id=game_nba_id, game_date=date(2025, 11, 12)
            ),
        )
        game_coverage = coverage_for_games(
            classify_session,
            ready=(),
            missing_tipoff=missing,
            coverage_report=None,
        )
    finally:
        event.remove(database.engine, "before_cursor_execute", _promote_mid_statement)
        classify_session.rollback()
        classify_session.close()

    # Exactly one statement covered this game's state -- the promotion is
    # visible within the same single snapshot, not a second query.
    assert statement_count == 1

    by_game_id = {gc.game_id: gc for gc in game_coverage}
    assert game_id in by_game_id, "the promoted game must still appear exactly once"
    assert by_game_id[game_id].outcome == "observed", (
        "a game the caller believed had no tip-off, but that the one "
        "authoritative snapshot shows now has one, must be promoted out of "
        "missing_tipoff and classified against its real evidence -- not "
        "left reporting the caller's now-stale missing_tipoff forever"
    )
    assert by_game_id[game_id].observation_count == 1


def test_coverage_for_games_resolved_out_of_scope_row_does_not_leak_to_unrelated_game(
    session: Any,
) -> None:
    """Round-9 review point 4: a resolved game_id must stay bound to its own game.

    ``early``'s own tip-off is retracted after the plan snapshot was
    built, so it is no longer live in ``games_by_id`` by the time
    classification runs. A row *resolved* to ``early``'s ``game_id`` --
    not merely date+tricode matched -- must not fan out across the date
    the way a genuinely unattributable row does: it names one specific
    game, and that game having since gone missing is not evidence about
    ``late``, an unrelated later game on the same date.
    """
    early, late = _seed_staggered_games(session)
    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)

    # early's own tip-off is retracted after the plan snapshot was taken.
    early.tipoff_utc = None
    session.flush()

    # Resolved to early's own game_id, strictly before late's tip-off.
    # Under the pre-fix logic, a row whose game_id fails to resolve to a
    # currently-live game was treated as fully unattributable and vetoed
    # every same-date game it pre-dated -- including late, which this row
    # says nothing about.
    session.add(
        InjuryReportEntry(
            report_timestamp=_et(2025, 11, 5, 17, 0),
            game_date=date(2025, 11, 5),
            game_time_raw="06:00 (ET)",
            matchup_raw="SAC@MIL",
            team_raw="Sacramento Kings",
            game_id=early.id,
            player_name_raw="Murray, Keegan",
            status_raw="Out",
            status=InjuryReportStatus.OUT,
            source_url="https://example.invalid/fixture",
        )
    )
    session.flush()

    coverage = coverage_for_games(session, ready=ready, missing_tipoff=missing)
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[early.id].outcome == "missing_tipoff"
    assert by_game_id[late.id].outcome != "unresolved_evidence", (
        "a row resolved to a specific (now-missing) game must not fan out "
        "and veto an unrelated same-date game"
    )


def test_coverage_for_games_retracted_tipoff_game_is_emitted_exactly_once(session: Any) -> None:
    """Round-9 review point 3: a retracted-tipoff game must appear exactly once in the result.

    Before the fix, ``games_by_id.get(g.game_id)`` returning ``None`` in
    the ``ready`` results loop emitted an inline ``missing_tipoff`` record
    *and* the same game was emitted again via the separate
    ``newly_missing`` loop, inflating counts.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="retracted-once",
        game_date=date(2025, 11, 8),
        tipoff_utc=_et(2025, 11, 8, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    ready = (
        BackfillGame(
            game_id=game.id,
            nba_game_id=game.nba_game_id,
            game_date=game.game_date,
            tipoff_utc=_et(2025, 11, 8, 19, 0),  # the caller's now-stale snapshot
        ),
    )
    # Retract the tip-off after the caller's snapshot was built.
    game.tipoff_utc = None
    session.flush()

    coverage = coverage_for_games(session, ready=ready, missing_tipoff=())
    matching = [gc for gc in coverage if gc.game_id == game.id]
    assert len(matching) == 1, (
        f"expected exactly one coverage row for a retracted-tipoff game, got {len(matching)}"
    )
    assert matching[0].outcome == "missing_tipoff"


def test_coverage_report_from_json_loads_real_legacy_serialized_text_as_legacy(
    session: Any,
) -> None:
    """Round-9 review point 2: a hand-written legacy JSON blob must load and classify as
    legacy-excluded.

    This is real, literal pre-round-7 file text -- missing
    ``applicable_nba_game_ids``/``evidence_schema_version`` entirely --
    not an object built with the current dataclass's own defaults, so it
    actually exercises ``from_json``'s defaulting path against what a real
    file on disk looks like.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="hand-written-legacy-json",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    canonical_ts = _et(2025, 11, 1, 17, 30)
    legacy_text = json.dumps(
        {
            "season": "2025-26",
            "season_type": "regular",
            "candidates": [
                {
                    "report_date": "2025-11-02",
                    "anchor": "evening_before",
                    "era": "legacy",
                    "anchor_offset_minutes": None,
                    "requested_timestamp": canonical_ts.isoformat(),
                    "applicable_game_ids": [game.id],
                    "outcome": "fetched",
                    "status_code": None,
                    "canonical_report_timestamp": canonical_ts.isoformat(),
                    "entries_total": 0,
                    "entries_not_yet_submitted": 0,
                    "entries_listed": 0,
                    "detail": "",
                    # Deliberately absent: applicable_nba_game_ids,
                    # evidence_schema_version -- exactly what a real
                    # pre-round-7 file on disk looks like.
                }
            ],
        }
    )
    coverage_report = CoverageReport.from_json(legacy_text)
    assert coverage_report.candidates[0].evidence_schema_version == LEGACY_COVERAGE_SCHEMA_VERSION
    assert coverage_report.candidates[0].applicable_nba_game_ids == ()

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(
        session, ready=ready, missing_tipoff=missing, coverage_report=coverage_report
    )
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[game.id].outcome != "submitted_zero_listed"
    assert by_game_id[game.id].outcome == "no_candidate_coverage"


def test_coverage_report_from_json_rejects_an_unrecognized_future_schema_version(
    session: Any,
) -> None:
    """Round-9 review point 2: a schema version newer than this code knows about is just as
    untrustworthy as a legacy one.

    Before this round the check was ``< CURRENT``, which would have
    trusted anything at or above current -- including a future version
    this code has never validated the shape of.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="future-schema-version",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    canonical_ts = _et(2025, 11, 1, 17, 30)
    future_version = CURRENT_COVERAGE_SCHEMA_VERSION + 1
    future_text = json.dumps(
        {
            "season": "2025-26",
            "season_type": "regular",
            "candidates": [
                {
                    "report_date": "2025-11-02",
                    "anchor": "evening_before",
                    "era": "legacy",
                    "anchor_offset_minutes": None,
                    "requested_timestamp": canonical_ts.isoformat(),
                    "applicable_game_ids": [game.id],
                    "applicable_nba_game_ids": [game.nba_game_id],
                    "outcome": "fetched",
                    "status_code": None,
                    "canonical_report_timestamp": canonical_ts.isoformat(),
                    "entries_total": 0,
                    "entries_not_yet_submitted": 0,
                    "entries_listed": 0,
                    "detail": "",
                    "evidence_schema_version": future_version,
                }
            ],
        }
    )
    coverage_report = CoverageReport.from_json(future_text)
    assert coverage_report.candidates[0].evidence_schema_version == future_version

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(
        session, ready=ready, missing_tipoff=missing, coverage_report=coverage_report
    )
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[game.id].outcome != "submitted_zero_listed", (
        "an unrecognized future schema version must not be trusted any more than a legacy one"
    )
    assert by_game_id[game.id].outcome == "no_candidate_coverage"


def test_coverage_for_games_rejects_evidence_whose_report_date_no_longer_matches_current_game(
    session: Any,
) -> None:
    """Round-9 review point 2: a reschedule that moves the same stable game id to a different
    date must not let evidence collected for its old report window prove a clean submission
    wherever the game is now.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="rescheduled-game",
        game_date=date(2025, 12, 15),  # current, corrected date -- moved from Nov 2
        tipoff_utc=_et(2025, 12, 15, 22, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    canonical_ts = _et(2025, 11, 1, 17, 30)  # trivially pre-tip against the new December date
    coverage_report = CoverageReport(
        season="2025-26",
        season_type="regular",
        candidates=[
            CandidateCoverage.from_candidate(
                # report_date names the *original* Nov 2 schedule window
                # this evidence was actually collected for.
                ReportCandidate(date(2025, 11, 2), "evening_before", canonical_ts),
                season="2025-26",
                season_type="regular",
                applicable_game_ids=(game.id,),
                applicable_nba_game_ids=(game.nba_game_id,),
                outcome="fetched",
                canonical_report_timestamp=canonical_ts,
                entries_total=0,
            )
        ],
    )

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(
        session, ready=ready, missing_tipoff=missing, coverage_report=coverage_report
    )
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[game.id].outcome != "submitted_zero_listed", (
        "evidence collected for a game's old date/report window must not "
        "transfer to the same stable id after it was rescheduled elsewhere"
    )
    assert by_game_id[game.id].outcome == "no_candidate_coverage"


def test_coverage_for_games_rejects_evidence_from_a_coverage_report_with_a_different_season(
    session: Any,
) -> None:
    """Round-9 review point 2: a stable NBA game id alone is not sufficient evidence identity --
    the CoverageReport's own season/season_type must also match this game's current one.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="wrong-season-binding",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
        season="2025-26",
        season_type=SeasonType.REGULAR,
    )
    canonical_ts = _et(2025, 11, 1, 17, 30)
    coverage_report = CoverageReport(
        season="2024-25",  # wrong season for this game
        season_type="regular",
        candidates=[
            CandidateCoverage.from_candidate(
                ReportCandidate(date(2025, 11, 2), "evening_before", canonical_ts),
                season="2024-25",
                season_type="regular",
                applicable_game_ids=(game.id,),
                applicable_nba_game_ids=(game.nba_game_id,),
                outcome="fetched",
                canonical_report_timestamp=canonical_ts,
                entries_total=0,
            )
        ],
    )

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(
        session, ready=ready, missing_tipoff=missing, coverage_report=coverage_report
    )
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[game.id].outcome != "submitted_zero_listed", (
        "a CoverageReport built for a different season must not prove a "
        "clean submission just because the stable game id happens to match"
    )
    assert by_game_id[game.id].outcome == "no_candidate_coverage"


# ==========================================================================
# Durable coverage report: JSON round-trip
# ==========================================================================


def test_coverage_report_json_round_trips(tmp_path: Path) -> None:
    candidate = ReportCandidate(
        date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30), anchor_offset_minutes=None
    )
    coverage = CandidateCoverage.from_candidate(
        candidate,
        applicable_game_ids=(1, 2),
        season="2025-26",
        season_type="regular",
        applicable_nba_game_ids=("nba-1", "nba-2"),
        outcome="fetched",
        canonical_report_timestamp=_et(2025, 11, 1, 17, 30),
        entries_total=5,
        entries_not_yet_submitted=1,
    )
    report = CoverageReport(season="2025-26", season_type="regular", candidates=[coverage])

    path = tmp_path / "coverage.json"
    write_coverage_report(path, report)
    reloaded = CoverageReport.from_json(path.read_text(encoding="utf-8"))

    assert reloaded.season == "2025-26"
    assert len(reloaded.candidates) == 1
    reloaded_candidate = reloaded.candidates[0]
    assert reloaded_candidate.applicable_game_ids == (1, 2)
    assert reloaded_candidate.outcome == "fetched"
    assert reloaded_candidate.entries_listed == 4


def test_coverage_merge_key_includes_the_requested_timestamp_not_just_date_and_anchor() -> None:
    """Two candidates sharing ``(date, anchor)`` but a different resolved instant.

    Round-4 regression (independent review, point 8): merging coverage keyed
    only on ``(report_date, anchor)`` would let a changed near-tip candidate
    silently overwrite a previous, unrelated candidate's coverage record.
    Including ``requested_timestamp`` in the merge key means both persist as
    distinct records.
    """
    first = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 12, 25), "near_tip_15", _et(2025, 12, 25, 18, 45), 15),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(1,),
        applicable_nba_game_ids=("nba-1",),
        outcome="not_available",
        status_code=404,
    )
    second = CandidateCoverage.from_candidate(
        # Same date, same anchor label, but a genuinely different resolved
        # instant -- e.g. after a tip-off correction.
        ReportCandidate(date(2025, 12, 25), "near_tip_15", _et(2025, 12, 25, 19, 15), 15),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(1,),
        applicable_nba_game_ids=("nba-1",),
        outcome="fetched",
        canonical_report_timestamp=_et(2025, 12, 25, 19, 15),
    )
    assert _coverage_merge_key(first) != _coverage_merge_key(second)

    merged = _merge_coverage([first], [second])
    assert len(merged) == 2
    outcomes = {c.requested_timestamp: c.outcome for c in merged}
    assert outcomes[first.requested_timestamp] == "not_available"
    assert outcomes[second.requested_timestamp] == "fetched"


def test_coverage_merge_round_trips_through_persist_and_overwrites_only_the_same_candidate(
    tmp_path: Path,
) -> None:
    """A real merge-and-persist round trip: re-running only overwrites its own key."""
    path = tmp_path / "coverage.json"
    unrelated = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 11, 1), "evening_before", _et(2025, 10, 31, 17, 30)),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(1,),
        applicable_nba_game_ids=("nba-1",),
        outcome="not_available",
        status_code=404,
    )
    write_coverage_report(
        path, CoverageReport(season="2025-26", season_type="regular", candidates=[unrelated])
    )

    stale = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 12, 25), "near_tip_15", _et(2025, 12, 25, 18, 45), 15),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(2,),
        applicable_nba_game_ids=("nba-2",),
        outcome="forbidden",
        status_code=403,
    )
    existing = CoverageReport.from_json(path.read_text(encoding="utf-8"))
    merged_once = _merge_coverage(existing.candidates, [stale])
    write_coverage_report(
        path, CoverageReport(season="2025-26", season_type="regular", candidates=merged_once)
    )

    corrected = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 12, 25), "near_tip_15", _et(2025, 12, 25, 19, 15), 15),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(2,),
        applicable_nba_game_ids=("nba-2",),
        outcome="fetched",
        canonical_report_timestamp=_et(2025, 12, 25, 19, 15),
    )
    existing_again = CoverageReport.from_json(path.read_text(encoding="utf-8"))
    merged_twice = _merge_coverage(existing_again.candidates, [corrected])
    write_coverage_report(
        path, CoverageReport(season="2025-26", season_type="regular", candidates=merged_twice)
    )

    final = CoverageReport.from_json(path.read_text(encoding="utf-8"))
    # The unrelated candidate from run 1 is untouched; the stale (403) and
    # corrected (fetched) near_tip_15 candidates both survive as distinct
    # records rather than the corrected one silently replacing the stale one.
    assert len(final.candidates) == 3
    by_timestamp = {c.requested_timestamp: c.outcome for c in final.candidates}
    assert by_timestamp[unrelated.requested_timestamp] == "not_available"
    assert by_timestamp[stale.requested_timestamp] == "forbidden"
    assert by_timestamp[corrected.requested_timestamp] == "fetched"


def _serialized_candidate(
    *,
    report_date: str,
    requested_timestamp: str,
    season: str,
    season_type: str,
    game_id: int = 1,
    nba_game_id: str = "nba-1",
    outcome: str = "fetched",
) -> dict[str, Any]:
    """A hand-built raw candidate dict, exactly the shape written to disk.

    Used (not :meth:`CandidateCoverage.from_candidate`) so the round-10
    scope-laundering regressions below exercise a genuine on-disk artifact
    -- the actual bytes ``_persist_coverage`` reads -- rather than an
    in-memory object constructed some other way.
    """
    return {
        "report_date": report_date,
        "anchor": "evening_before",
        "era": "fifteen_minute",
        "anchor_offset_minutes": None,
        "requested_timestamp": requested_timestamp,
        "applicable_game_ids": [game_id],
        "applicable_nba_game_ids": [nba_game_id],
        "outcome": outcome,
        "status_code": None,
        "canonical_report_timestamp": requested_timestamp if outcome == "fetched" else None,
        "entries_total": 0,
        "entries_not_yet_submitted": 0,
        "entries_listed": 0,
        "detail": "",
        "evidence_schema_version": CURRENT_COVERAGE_SCHEMA_VERSION,
        "season": season,
        "season_type": season_type,
    }


def test_persist_coverage_raises_on_whole_file_season_mismatch(tmp_path: Path) -> None:
    """Round-10 review point 2: a persisted file's own declared ``season``.

    A stale artifact left over from an explicit ``--coverage-path`` override
    (or a hand-edited file) declaring a *different* season than this call's
    request must never be silently merged and rewritten under this call's
    label -- that would launder its candidates into evidence this run never
    actually gathered. ``_persist_coverage`` must raise, and must leave the
    file exactly as it was, not truncate or partially rewrite it.
    """
    path = tmp_path / "coverage.json"
    stale_file = {
        "season": "2024-25",
        "season_type": "regular",
        "candidates": [
            _serialized_candidate(
                report_date="2024-11-01",
                requested_timestamp=_et(2024, 10, 31, 17, 30).isoformat(),
                season="2024-25",
                season_type="regular",
                game_id=1,
                nba_game_id="nba-old-1",
            )
        ],
    }
    path.write_text(json.dumps(stale_file), encoding="utf-8")

    new_candidate = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(2,),
        applicable_nba_game_ids=("nba-2",),
        outcome="not_available",
        status_code=404,
    )

    with pytest.raises(CoverageScopeMismatch):
        _persist_coverage(path, "2025-26", SeasonType.REGULAR, [new_candidate])

    # Refusing to merge must not also silently truncate or rewrite the file.
    still_there = CoverageReport.from_json(path.read_text(encoding="utf-8"))
    assert still_there.season == "2024-25"
    assert len(still_there.candidates) == 1


def test_persist_coverage_raises_on_whole_file_season_type_mismatch(tmp_path: Path) -> None:
    """Round-10 review point 2: season alone is not the whole scope -- season_type must
    also agree, or the same laundering risk applies (a playoffs artifact merged into a
    regular-season request's coverage file, or vice versa).
    """
    path = tmp_path / "coverage.json"
    stale_file = {
        "season": "2025-26",
        "season_type": "playoffs",
        "candidates": [
            _serialized_candidate(
                report_date="2026-04-20",
                requested_timestamp=_et(2026, 4, 19, 17, 30).isoformat(),
                season="2025-26",
                season_type="playoffs",
            )
        ],
    }
    path.write_text(json.dumps(stale_file), encoding="utf-8")

    new_candidate = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(2,),
        applicable_nba_game_ids=("nba-2",),
        outcome="not_available",
        status_code=404,
    )

    with pytest.raises(CoverageScopeMismatch):
        _persist_coverage(path, "2025-26", SeasonType.REGULAR, [new_candidate])

    still_there = CoverageReport.from_json(path.read_text(encoding="utf-8"))
    assert still_there.season_type == "playoffs"
    assert len(still_there.candidates) == 1


def test_persist_coverage_excludes_a_candidate_whose_own_recorded_scope_disagrees(
    tmp_path: Path,
) -> None:
    """Round-10 review point 2, defense in depth.

    Even inside a file whose *top-level* declared scope matches this call's
    request, an individual candidate recorded with a *different* own
    ``(season, season_type)`` (a hand-edited file, or a bug in some other
    writer) must not be silently carried forward as current-scope evidence
    merely because the enclosing file's own label happens to match. The
    real load+merge+save path must exclude exactly that one candidate,
    not the whole file, and not raise -- this is a narrower, quieter
    failure mode than a whole-file mismatch, not a release-blocking one.
    """
    path = tmp_path / "coverage.json"
    mixed_file = {
        "season": "2025-26",
        "season_type": "regular",
        "candidates": [
            _serialized_candidate(
                report_date="2025-11-01",
                requested_timestamp=_et(2025, 10, 31, 17, 30).isoformat(),
                season="2024-25",  # disagrees with the enclosing file's own "2025-26"
                season_type="regular",
                game_id=1,
                nba_game_id="nba-mismatched-1",
            )
        ],
    }
    path.write_text(json.dumps(mixed_file), encoding="utf-8")

    new_candidate = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(2,),
        applicable_nba_game_ids=("nba-2",),
        outcome="not_available",
        status_code=404,
    )

    _persist_coverage(path, "2025-26", SeasonType.REGULAR, [new_candidate])

    result = CoverageReport.from_json(path.read_text(encoding="utf-8"))
    # The wrong-scope candidate is dropped from the rewritten file; only the
    # genuinely current-scope one survives. Never two -- and never the
    # mismatched one alone.
    assert len(result.candidates) == 1
    assert result.candidates[0].requested_timestamp == new_candidate.requested_timestamp
    assert result.candidates[0].applicable_nba_game_ids == ("nba-2",)


def test_persist_coverage_quarantines_an_unrecognized_future_schema_version_candidate(
    tmp_path: Path,
) -> None:
    """Round-11 review point 2: a future schema version must never be retained/rewritten.

    ``coverage_for_games`` already refuses to *trust* a candidate whose
    ``evidence_schema_version`` is not exactly current for classification --
    but before this fix, ``_persist_coverage`` itself would still read such
    a candidate back off disk, merge it unchanged, and rewrite it into this
    run's own "current" file, forever laundering it forward as if it were
    ordinary same-scope evidence. This is a genuine on-disk artifact (hand-
    built raw dict, not ``CandidateCoverage.from_candidate``) exercising the
    real load -> merge -> save path, with a schema version this code has
    never seen (``CURRENT_COVERAGE_SCHEMA_VERSION + 1``).
    """
    path = tmp_path / "coverage.json"
    future_candidate = _serialized_candidate(
        report_date="2025-11-01",
        requested_timestamp=_et(2025, 10, 31, 17, 30).isoformat(),
        season="2025-26",
        season_type="regular",
        game_id=1,
        nba_game_id="nba-future-1",
    )
    future_candidate["evidence_schema_version"] = CURRENT_COVERAGE_SCHEMA_VERSION + 1
    stale_file = {
        "season": "2025-26",
        "season_type": "regular",
        "candidates": [future_candidate],
    }
    path.write_text(json.dumps(stale_file), encoding="utf-8")

    new_candidate = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(2,),
        applicable_nba_game_ids=("nba-2",),
        outcome="not_available",
        status_code=404,
    )

    _persist_coverage(path, "2025-26", SeasonType.REGULAR, [new_candidate])

    result = CoverageReport.from_json(path.read_text(encoding="utf-8"))
    # The unrecognized-future-version candidate is quarantined out of the
    # rewritten file entirely -- not retained, not rewritten as current.
    assert len(result.candidates) == 1
    assert result.candidates[0].applicable_nba_game_ids == ("nba-2",)
    assert result.candidates[0].evidence_schema_version == CURRENT_COVERAGE_SCHEMA_VERSION


def test_persist_coverage_quarantines_a_legacy_pre_versioning_candidate_too(
    tmp_path: Path,
) -> None:
    """The same quarantine applies to a legacy (pre-round-7) record, not just future ones.

    A record predating ``evidence_schema_version`` entirely (defaulted by
    :meth:`CoverageReport.from_json` to :data:`LEGACY_COVERAGE_SCHEMA_VERSION`
    on load) must also never be carried forward into a freshly rewritten
    "current" file -- it was already excluded from classification trust,
    and round-11 closes the matching persistence-side gap.
    """
    path = tmp_path / "coverage.json"
    legacy_candidate = _serialized_candidate(
        report_date="2025-11-01",
        requested_timestamp=_et(2025, 10, 31, 17, 30).isoformat(),
        season="2025-26",
        season_type="regular",
        game_id=1,
        nba_game_id="nba-legacy-1",
    )
    # Simulate a genuinely pre-versioning record: the key is simply absent,
    # exactly as CoverageReport.from_json's own docstring describes.
    del legacy_candidate["evidence_schema_version"]
    stale_file = {
        "season": "2025-26",
        "season_type": "regular",
        "candidates": [legacy_candidate],
    }
    path.write_text(json.dumps(stale_file), encoding="utf-8")

    new_candidate = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(2,),
        applicable_nba_game_ids=("nba-2",),
        outcome="not_available",
        status_code=404,
    )

    _persist_coverage(path, "2025-26", SeasonType.REGULAR, [new_candidate])

    result = CoverageReport.from_json(path.read_text(encoding="utf-8"))
    assert len(result.candidates) == 1
    assert result.candidates[0].applicable_nba_game_ids == ("nba-2",)


def test_coverage_merge_key_distinguishes_records_differing_only_in_canonical_masthead() -> None:
    """Round-11 review point 3: same requested instant, a later attempt resolves
    a *different* canonical masthead timestamp (e.g. a corrected publish).

    Before this fix, ``_coverage_merge_key`` did not include
    ``canonical_report_timestamp`` at all, so the second, corrected fetch
    would silently overwrite the first's evidence under an identical key --
    even though both are real, distinct trusted evidence.
    """
    first = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(1,),
        applicable_nba_game_ids=("nba-1",),
        outcome="fetched",
        canonical_report_timestamp=_et(2025, 11, 1, 17, 30),
        entries_total=2,
    )
    second = CandidateCoverage.from_candidate(
        # Identical requested instant/date/anchor -- but the masthead this
        # time resolved to a different (corrected) canonical timestamp.
        ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(1,),
        applicable_nba_game_ids=("nba-1",),
        outcome="fetched",
        canonical_report_timestamp=_et(2025, 11, 1, 17, 45),
        entries_total=3,
    )
    assert _coverage_merge_key(first) != _coverage_merge_key(second)

    merged = _merge_coverage([first], [second])
    assert len(merged) == 2, "distinct canonical mastheads must coexist, not overwrite"
    by_canonical = {c.canonical_report_timestamp: c.entries_total for c in merged}
    assert by_canonical[first.canonical_report_timestamp] == 2
    assert by_canonical[second.canonical_report_timestamp] == 3


def test_coverage_merge_key_distinguishes_records_differing_only_in_applicable_game_scope() -> None:
    """Same requested instant and canonical masthead, but a different applicable game set.

    Before this fix, ``_coverage_merge_key`` had no game-scope fingerprint,
    so a re-fetch that resolved a *different* set of applicable games (a
    schedule change between attempts) would silently overwrite the earlier
    attempt's evidence for a now-different set of games.
    """
    first = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(1,),
        applicable_nba_game_ids=("nba-1",),
        outcome="fetched",
        canonical_report_timestamp=_et(2025, 11, 1, 17, 30),
    )
    second = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(1, 2),
        applicable_nba_game_ids=("nba-1", "nba-2"),
        outcome="fetched",
        canonical_report_timestamp=_et(2025, 11, 1, 17, 30),
    )
    assert _coverage_merge_key(first) != _coverage_merge_key(second)

    merged = _merge_coverage([first], [second])
    assert len(merged) == 2, "distinct applicable game scopes must coexist, not overwrite"
    by_scope = {c.applicable_nba_game_ids: c.outcome for c in merged}
    assert by_scope[("nba-1",)] == "fetched"
    assert by_scope[("nba-1", "nba-2")] == "fetched"


def test_coverage_merge_key_dedupes_a_truly_identical_re_fetch() -> None:
    """A re-fetch identical in requested instant, canonical masthead, *and* game
    scope must still correctly dedupe to a single record -- round-11's fix must
    not turn ordinary idempotent re-fetches into unbounded duplicate growth.
    """
    original = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(1,),
        applicable_nba_game_ids=("nba-1",),
        outcome="fetched",
        canonical_report_timestamp=_et(2025, 11, 1, 17, 30),
        entries_total=5,
    )
    identical_re_fetch = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(1,),
        applicable_nba_game_ids=("nba-1",),
        outcome="fetched",
        canonical_report_timestamp=_et(2025, 11, 1, 17, 30),
        entries_total=5,
    )
    assert _coverage_merge_key(original) == _coverage_merge_key(identical_re_fetch)

    merged = _merge_coverage([original], [identical_re_fetch])
    assert len(merged) == 1


# ==========================================================================
# Expected-game-slate gate: fails closed before any injury-report HTTP call
# ==========================================================================


def test_enforce_expected_game_coverage_passes_when_the_official_schedule_matches(
    session: Any,
) -> None:
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="0022500900",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    expected = [
        NbaGameRecord(
            nba_game_id="0022500900",
            season="2025-26",
            season_type="regular",
            game_date=date(2025, 11, 1),
            home_team_id=teams["MIL"],
            away_team_id=teams["SAC"],
        )
    ]
    ready, missing_tipoff = games_to_backfill(
        session, season="2025-26", season_type=SeasonType.REGULAR
    )
    coverage = enforce_expected_game_coverage(
        season="2025-26",
        season_type=SeasonType.REGULAR,
        start=None,
        end=None,
        expected=expected,
        ready=ready,
        missing_tipoff=missing_tipoff,
    )
    assert coverage.expected_count == 1
    assert coverage.ingested_count == 1
    assert coverage.missing == ()
    assert [g.game_id for g in ready] == [game.id]


def test_enforce_expected_game_coverage_fails_closed_on_a_game_never_ingested(
    session: Any,
) -> None:
    """The core round-4 point-3 regression: 22/527 must not look cohort-ready.

    ``games_to_backfill``/``enforce_full_tipoff_coverage`` can only ever see
    games already present in this project's database. A game the official
    schedule lists but this project never ingested at all is invisible to
    both -- this gate is the only thing that can catch it, from an
    independent source of truth.
    """
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="0022500900",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    # The official schedule has a second game this project never ingested.
    expected = [
        NbaGameRecord(
            nba_game_id="0022500900",
            season="2025-26",
            season_type="regular",
            game_date=date(2025, 11, 1),
            home_team_id=teams["MIL"],
            away_team_id=teams["SAC"],
        ),
        NbaGameRecord(
            nba_game_id="0022500901",
            season="2025-26",
            season_type="regular",
            game_date=date(2025, 11, 1),
            home_team_id=teams["SAC"],
            away_team_id=teams["MIL"],
        ),
    ]
    ready, missing_tipoff = games_to_backfill(
        session, season="2025-26", season_type=SeasonType.REGULAR
    )
    with pytest.raises(IncompleteExpectedGameCoverage) as excinfo:
        enforce_expected_game_coverage(
            season="2025-26",
            season_type=SeasonType.REGULAR,
            start=None,
            end=None,
            expected=expected,
            ready=ready,
            missing_tipoff=missing_tipoff,
        )
    # The evidence is carried on the exception, so a caller can persist it
    # durably even on this failure path (mirrors SuspectedSourceBlock).
    coverage = excinfo.value.coverage
    assert coverage.expected_count == 2
    assert coverage.ingested_count == 1
    assert coverage.missing == (("0022500901", "2025-11-01"),)


def test_enforce_expected_game_coverage_respects_an_explicit_allow_missing_games(
    session: Any,
) -> None:
    """A deliberately partial run must say so explicitly, not accidentally pass."""
    teams = _seed_teams(session)
    expected = [
        NbaGameRecord(
            nba_game_id="0022500901",
            season="2025-26",
            season_type="regular",
            game_date=date(2025, 11, 1),
            home_team_id=teams["SAC"],
            away_team_id=teams["MIL"],
        )
    ]
    ready, missing_tipoff = games_to_backfill(
        session, season="2025-26", season_type=SeasonType.REGULAR
    )
    coverage = enforce_expected_game_coverage(
        season="2025-26",
        season_type=SeasonType.REGULAR,
        start=None,
        end=None,
        expected=expected,
        ready=ready,
        missing_tipoff=missing_tipoff,
        allow_missing_games=1,
    )
    assert coverage.missing == (("0022500901", "2025-11-01"),)


def test_enforce_expected_game_coverage_filters_to_the_requested_date_range(
    session: Any,
) -> None:
    """A game outside ``--start``/``--end`` must not count against the gate."""
    teams = _seed_teams(session)
    expected = [
        NbaGameRecord(
            nba_game_id="0022500950",
            season="2025-26",
            season_type="regular",
            game_date=date(2025, 12, 1),  # outside the requested range below
            home_team_id=teams["SAC"],
            away_team_id=teams["MIL"],
        )
    ]
    ready, missing_tipoff = games_to_backfill(
        session, season="2025-26", season_type=SeasonType.REGULAR
    )
    coverage = enforce_expected_game_coverage(
        season="2025-26",
        season_type=SeasonType.REGULAR,
        start=date(2025, 11, 1),
        end=date(2025, 11, 30),
        expected=expected,
        ready=ready,
        missing_tipoff=missing_tipoff,
    )
    assert coverage.expected_count == 0
    assert coverage.missing == ()


def test_enforce_expected_game_coverage_fails_closed_on_an_empty_whole_season_slate() -> None:
    """Round-5 point 6: an empty ``expected`` (before range filtering) never passes.

    A real NBA season is never zero games -- this is the signature of a
    wrong ``--season`` string, an unmapped/unsupported ``--season-type``, or
    an upstream API/parsing failure, and must fail closed rather than
    vacuously satisfy the gate with nothing to compare against.
    """
    with pytest.raises(IncompleteExpectedGameCoverage) as excinfo:
        enforce_expected_game_coverage(
            season="2025-26",
            season_type=SeasonType.REGULAR,
            start=None,
            end=None,
            expected=(),
            ready=(),
            missing_tipoff=(),
        )
    assert excinfo.value.coverage.expected_count == 0


def test_enforce_expected_game_coverage_fails_closed_on_empty_in_range_slate_with_ingested_games(
    session: Any,
) -> None:
    """Round-5 point 6: zero in-range expected games while this project has ingested some.

    A whole-season ``expected`` that is non-empty but has zero games in the
    requested range, while this project's own database already has games
    there, is a scope mismatch (wrong season-type label, wrong range against
    the official schedule) -- not a legitimately empty range.
    """
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="0022500900",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    expected = [
        NbaGameRecord(
            nba_game_id="0022509999",
            season="2025-26",
            season_type="regular",
            game_date=date(2026, 3, 1),  # entirely outside the requested range below
            home_team_id=teams["SAC"],
            away_team_id=teams["MIL"],
        )
    ]
    ready, missing_tipoff = games_to_backfill(
        session, season="2025-26", season_type=SeasonType.REGULAR
    )
    with pytest.raises(IncompleteExpectedGameCoverage) as excinfo:
        enforce_expected_game_coverage(
            season="2025-26",
            season_type=SeasonType.REGULAR,
            start=date(2025, 11, 1),
            end=date(2025, 11, 30),
            expected=expected,
            ready=ready,
            missing_tipoff=missing_tipoff,
        )
    assert excinfo.value.coverage.expected_count == 0


def test_expected_schedule_season_type_label_rejects_preseason_and_play_in() -> None:
    """Round-5 point 6: v1 only maps REGULAR and PLAYOFFS; guessing is refused."""
    assert _expected_schedule_season_type_label(SeasonType.REGULAR) == "Regular Season"
    assert _expected_schedule_season_type_label(SeasonType.PLAYOFFS) == "Playoffs"
    with pytest.raises(ValueError, match="not yet supported"):
        _expected_schedule_season_type_label(SeasonType.PRESEASON)
    with pytest.raises(ValueError, match="not yet supported"):
        _expected_schedule_season_type_label(SeasonType.PLAY_IN)


def test_expected_coverage_matches_scope_rejects_a_different_date_range() -> None:
    """Round-5 point 4: persisted evidence for one range must not answer another."""
    november = ExpectedGameCoverage(
        season="2025-26",
        season_type="regular",
        start="2025-11-01",
        end="2025-11-30",
        expected_count=100,
        ingested_count=100,
        missing=(),
    )
    assert _expected_coverage_matches_scope(
        november,
        season="2025-26",
        season_type=SeasonType.REGULAR,
        start=date(2025, 11, 1),
        end=date(2025, 11, 30),
    )
    # A March request must not be silently answered by November's evidence.
    assert not _expected_coverage_matches_scope(
        november,
        season="2025-26",
        season_type=SeasonType.REGULAR,
        start=date(2026, 3, 1),
        end=date(2026, 3, 31),
    )
    # A different season-type against the same range must not match either.
    assert not _expected_coverage_matches_scope(
        november,
        season="2025-26",
        season_type=SeasonType.PLAYOFFS,
        start=date(2025, 11, 1),
        end=date(2025, 11, 30),
    )
    assert not _expected_coverage_matches_scope(
        None,
        season="2025-26",
        season_type=SeasonType.REGULAR,
        start=date(2025, 11, 1),
        end=date(2025, 11, 30),
    )


# ==========================================================================
# Exclusion cascade: the full expected -> observed denominator
# ==========================================================================


def test_exclusion_cascade_reports_none_for_unknown_stages_rather_than_zero(
    session: Any,
) -> None:
    """No persisted expected-slate or coverage-report evidence -> explicit unknown."""
    teams = _seed_teams(session)
    _seed_game(
        session,
        nba_game_id="cascade-0",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    ready, missing_tipoff = games_to_backfill(
        session, season="2025-26", season_type=SeasonType.REGULAR
    )
    game_coverage = coverage_for_games(session, ready=ready, missing_tipoff=missing_tipoff)

    cascade = exclusion_cascade(
        session, ready=ready, missing_tipoff=missing_tipoff, game_coverage=game_coverage
    )
    assert cascade.expected_games is None
    assert cascade.missing_from_ingest is None
    assert cascade.candidates_attempted is None
    assert cascade.candidates_forbidden is None
    assert cascade.candidates_not_available is None
    assert cascade.mastheads_recovered is None
    assert cascade.ingested_games == 1
    assert cascade.ingested_with_tipoff == 1
    assert cascade.games_observed == 0

    rendered = render_exclusion_cascade(cascade)
    assert "unknown (not yet computed)" in rendered
    assert "no expected-game-slate evidence" in rendered
    assert "no coverage-report evidence" in rendered


def test_exclusion_cascade_full_denominator_with_expected_and_coverage_evidence(
    session: Any,
) -> None:
    """With both evidence sources present, every stage renders a real count."""
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="cascade-1",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    player = Player(
        full_name="Keegan Murray", normalized_name="keegan murray", current_team_id=teams["SAC"]
    )
    session.add(player)
    session.flush()
    session.add(
        InjuryReportEntry(
            report_timestamp=_et(2025, 11, 1, 17, 30),
            game_date=date(2025, 11, 1),
            game_time_raw="07:00 (ET)",
            matchup_raw="SAC@MIL",
            team_raw="Sacramento Kings",
            game_id=game.id,
            player_id=player.id,
            player_name_raw="Murray, Keegan",
            status_raw="Out",
            status=InjuryReportStatus.OUT,
            source_url="https://example.invalid/fixture",
        )
    )
    session.flush()

    ready, missing_tipoff = games_to_backfill(
        session, season="2025-26", season_type=SeasonType.REGULAR
    )
    game_coverage = coverage_for_games(session, ready=ready, missing_tipoff=missing_tipoff)

    expected = ExpectedGameCoverage(
        season="2025-26",
        season_type="regular",
        start=None,
        end=None,
        expected_count=1,
        ingested_count=1,
        missing=(),
    )
    coverage_report = CoverageReport(
        season="2025-26",
        season_type="regular",
        candidates=[
            CandidateCoverage.from_candidate(
                ReportCandidate(date(2025, 11, 1), "evening_before", _et(2025, 10, 31, 17, 30)),
                season="2025-26",
                season_type="regular",
                applicable_game_ids=(game.id,),
                applicable_nba_game_ids=(game.nba_game_id,),
                outcome="fetched",
                canonical_report_timestamp=_et(2025, 11, 1, 17, 30),
                entries_total=1,
            ),
            CandidateCoverage.from_candidate(
                ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
                season="2025-26",
                season_type="regular",
                applicable_game_ids=(),
                applicable_nba_game_ids=(),
                outcome="forbidden",
                status_code=403,
            ),
        ],
    )

    cascade = exclusion_cascade(
        session,
        ready=ready,
        missing_tipoff=missing_tipoff,
        game_coverage=game_coverage,
        expected=expected,
        coverage_report=coverage_report,
    )
    assert cascade.expected_games == 1
    assert cascade.missing_from_ingest == 0
    assert cascade.ingested_games == 1
    assert cascade.ingested_with_tipoff == 1
    assert cascade.candidates_attempted == 2
    assert cascade.candidates_forbidden == 1
    assert cascade.candidates_not_available == 0
    assert cascade.mastheads_recovered == 1
    assert cascade.entries_in_scope == 1
    assert cascade.entries_resolved_game_id == 1
    assert cascade.entries_resolved_player_id == 1
    assert cascade.entries_not_yet_submitted == 0
    assert cascade.entries_status_listed == 1
    assert cascade.games_observed == 1
    assert cascade.canonical_player_games == 1
    assert cascade.canonical_player_games_player_resolved == 1
    assert cascade.entries_legacy_excluded == 0
    assert cascade.games_legacy_excluded == 0
    assert cascade.unresolved_game_id_sample == ()

    rendered = render_exclusion_cascade(cascade)
    assert "unknown" not in rendered


def test_exclusion_cascade_unresolved_game_id_stage_is_not_tautological(session: Any) -> None:
    """Round-5 point 1: the raw-entry query must scope by date, not by ``game_id``.

    The earlier version filtered raw entries by ``InjuryReportEntry.game_id
    .in_(game_ids)`` *before* counting how many entries resolved a
    ``game_id`` -- every row that query can return already has a non-null
    ``game_id`` by construction, so the stage could never show anything but
    100%. This regression seeds one entry whose ``game_id`` never resolved
    at all (a masthead's team name failed to match this project's roster)
    and asserts the cascade actually shows the loss.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="unresolved-0",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    # A resolved row for the same date -- the "healthy" half of the stage.
    session.add(
        InjuryReportEntry(
            report_timestamp=_et(2025, 10, 31, 17, 30),
            game_date=date(2025, 11, 1),
            game_time_raw="07:00 (ET)",
            matchup_raw="SAC@MIL",
            team_raw="Sacramento Kings",
            game_id=game.id,
            player_name_raw="Murray, Keegan",
            status_raw="Out",
            status=InjuryReportStatus.OUT,
            source_url="https://example.invalid/fixture",
        )
    )
    # An entry on the same report date whose game_id never resolved.
    session.add(
        InjuryReportEntry(
            report_timestamp=_et(2025, 10, 31, 17, 30),
            game_date=date(2025, 11, 1),
            game_time_raw="07:00 (ET)",
            matchup_raw="XYZ@ABC",  # unresolvable matchup -- no team matched
            team_raw="Unresolvable Team",
            game_id=None,
            player_name_raw="Someone, Unresolved",
            status_raw="Questionable",
            status=InjuryReportStatus.QUESTIONABLE,
            source_url="https://example.invalid/fixture",
        )
    )
    session.flush()

    ready, missing_tipoff = games_to_backfill(
        session, season="2025-26", season_type=SeasonType.REGULAR
    )
    game_coverage = coverage_for_games(session, ready=ready, missing_tipoff=missing_tipoff)
    cascade = exclusion_cascade(
        session, ready=ready, missing_tipoff=missing_tipoff, game_coverage=game_coverage
    )

    assert cascade.entries_in_scope == 2
    assert cascade.entries_resolved_game_id == 1, (
        "the tautological version could never show anything but entries_in_scope here"
    )
    assert len(cascade.unresolved_game_id_sample) == 1
    assert cascade.unresolved_game_id_sample[0] == (
        "2025-11-01",
        "XYZ@ABC",
        "Unresolvable Team",
        "Someone, Unresolved",
    )

    rendered = render_exclusion_cascade(cascade)
    assert "Someone, Unresolved" in rendered


def test_exclusion_cascade_excludes_legacy_rows_from_every_trusted_stage_consistently(
    session: Any,
) -> None:
    """Round-5 point 3: a legacy row must never leak into stages 11-16 as trusted.

    A legacy row with a real listed status (``QUESTIONABLE``, not
    ``NOT_YET_SUBMITTED``) must not be mislabelled ``entries_not_yet_submitted``
    or counted in ``entries_in_scope``/``entries_resolved_player_id`` -- it is
    counted exactly once, in ``entries_legacy_excluded``/``games_legacy_excluded``.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="legacy-cascade-0",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    player = Player(
        full_name="Keegan Murray", normalized_name="keegan murray", current_team_id=teams["SAC"]
    )
    session.add(player)
    session.flush()
    session.add(
        InjuryReportEntry(
            report_timestamp=_et(2025, 10, 31, 17, 30),
            game_date=date(2025, 11, 1),
            game_time_raw="07:00 (ET)",
            matchup_raw="SAC@MIL",
            team_raw="Sacramento Kings",
            game_id=game.id,
            player_id=player.id,
            player_name_raw="Murray, Keegan",
            status_raw="Questionable",  # a real status, not NOT_YET_SUBMITTED
            status=InjuryReportStatus.QUESTIONABLE,
            source_url="https://example.invalid/fixture",
            import_schema_version=LEGACY_EVIDENCE_SCHEMA_VERSION,
        )
    )
    session.flush()

    ready, missing_tipoff = games_to_backfill(
        session, season="2025-26", season_type=SeasonType.REGULAR
    )
    game_coverage = coverage_for_games(session, ready=ready, missing_tipoff=missing_tipoff)
    cascade = exclusion_cascade(
        session, ready=ready, missing_tipoff=missing_tipoff, game_coverage=game_coverage
    )

    assert cascade.entries_legacy_excluded == 1
    assert cascade.games_legacy_excluded == 1
    # None of the trusted-schema stages may count this row at all.
    assert cascade.entries_in_scope == 0
    assert cascade.entries_resolved_game_id == 0
    assert cascade.entries_resolved_player_id == 0
    assert cascade.entries_not_yet_submitted == 0, (
        "a legacy row's real QUESTIONABLE status must never be mislabelled "
        "NOT_YET_SUBMITTED just because it predates the natural-key fix"
    )
    assert cascade.entries_status_listed == 0
    assert cascade.games_observed == 0
    assert cascade.canonical_player_games == 0


def test_exclusion_cascade_filters_candidates_to_the_requested_date_range(session: Any) -> None:
    """Round-5 point 4/8: candidates outside ``start``/``end`` must not count.

    ``coverage_report`` is season/season_type-scoped, not date-range-scoped
    (see ``_merge_coverage``), so it can accumulate candidates from many past
    runs over different windows. Without filtering, a March run's cascade
    could silently include November's candidates in its own denominator.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="range-filter-0",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    ready, missing_tipoff = games_to_backfill(
        session, season="2025-26", season_type=SeasonType.REGULAR
    )
    game_coverage = coverage_for_games(session, ready=ready, missing_tipoff=missing_tipoff)
    coverage_report = CoverageReport(
        season="2025-26",
        season_type="regular",
        candidates=[
            CandidateCoverage.from_candidate(
                ReportCandidate(date(2025, 11, 1), "evening_before", _et(2025, 10, 31, 17, 30)),
                season="2025-26",
                season_type="regular",
                applicable_game_ids=(game.id,),
                applicable_nba_game_ids=(game.nba_game_id,),
                outcome="fetched",
                canonical_report_timestamp=_et(2025, 10, 31, 17, 30),
                entries_total=1,
            ),
            # A candidate from an unrelated, much earlier run over March.
            CandidateCoverage.from_candidate(
                ReportCandidate(date(2026, 3, 1), "evening_before", _et(2026, 2, 28, 17, 30)),
                season="2025-26",
                season_type="regular",
                applicable_game_ids=(),
                applicable_nba_game_ids=(),
                outcome="not_available",
                status_code=404,
            ),
        ],
    )

    cascade_november = exclusion_cascade(
        session,
        ready=ready,
        missing_tipoff=missing_tipoff,
        game_coverage=game_coverage,
        coverage_report=coverage_report,
        start=date(2025, 11, 1),
        end=date(2025, 11, 30),
    )
    assert cascade_november.candidates_attempted == 1
    assert cascade_november.candidates_not_available == 0
    assert cascade_november.mastheads_recovered == 1

    cascade_march = exclusion_cascade(
        session,
        ready=ready,
        missing_tipoff=missing_tipoff,
        game_coverage=game_coverage,
        coverage_report=coverage_report,
        start=date(2026, 3, 1),
        end=date(2026, 3, 31),
    )
    assert cascade_march.candidates_attempted == 1
    assert cascade_march.candidates_not_available == 1
    assert cascade_march.mastheads_recovered == 0


# ==========================================================================
# Evidence-schema versioning: legacy rows excluded from canonical selection
# ==========================================================================


def test_select_canonical_pregame_observations_excludes_legacy_schema_rows_by_default(
    session: Any,
) -> None:
    """A row stamped ``LEGACY_EVIDENCE_SCHEMA_VERSION`` cannot vouch for itself.

    Round-4 point 7: a row whose last write predates migration 0013's
    natural-key fix cannot be proven, after the fact, free of the
    back-to-back collision that fix corrects. The default query must refuse
    to treat it as trustworthy evidence.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="legacy-0",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    legacy_entry = InjuryReportEntry(
        report_timestamp=_et(2025, 11, 1, 17, 30),
        game_date=date(2025, 11, 1),
        game_time_raw="07:00 (ET)",
        matchup_raw="SAC@MIL",
        team_raw="Sacramento Kings",
        game_id=game.id,
        player_name_raw="Murray, Keegan",
        status_raw="Out",
        status=InjuryReportStatus.OUT,
        source_url="https://example.invalid/fixture",
        import_schema_version=LEGACY_EVIDENCE_SCHEMA_VERSION,
    )
    session.add(legacy_entry)
    session.flush()

    assert select_canonical_pregame_observations(session, game_ids=[game.id]) == ()

    included = select_canonical_pregame_observations(
        session, game_ids=[game.id], include_legacy=True
    )
    assert len(included) == 1
    assert included[0].player_name_raw == "Murray, Keegan"


def test_select_canonical_pregame_observations_includes_current_schema_rows_by_default(
    session: Any,
) -> None:
    """The ordinary case: a row written under the fixed key needs no override."""
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="current-0",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    entry = InjuryReportEntry(
        report_timestamp=_et(2025, 11, 1, 17, 30),
        game_date=date(2025, 11, 1),
        game_time_raw="07:00 (ET)",
        matchup_raw="SAC@MIL",
        team_raw="Sacramento Kings",
        game_id=game.id,
        player_name_raw="Murray, Keegan",
        status_raw="Out",
        status=InjuryReportStatus.OUT,
        source_url="https://example.invalid/fixture",
    )
    session.add(entry)
    session.flush()

    assert entry.import_schema_version == CURRENT_EVIDENCE_SCHEMA_VERSION
    observations = select_canonical_pregame_observations(session, game_ids=[game.id])
    assert len(observations) == 1


def test_run_backfill_upgrades_a_legacy_row_when_genuinely_re_imported(
    session: Any, tmp_path: Path
) -> None:
    """A legacy row touched by a real re-import is automatically upgraded.

    No separate backfill migration/script is needed for this part: the
    importer writes ``CURRENT_EVIDENCE_SCHEMA_VERSION`` on every create *and*
    update, so the fixed natural key finding and updating an old row is
    itself proof the row is no longer suspect.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="upgrade-0",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    report_timestamp = _et(2025, 10, 31, 17, 30)  # matches this date's "evening_before" candidate
    legacy_entry = InjuryReportEntry(
        report_timestamp=report_timestamp,
        game_date=date(2025, 11, 1),
        game_time_raw="07:00 (ET)",
        matchup_raw="SAC@MIL",
        team_raw="Sacramento Kings",
        game_id=game.id,
        player_name_raw="Murray, Keegan",
        status_raw="Questionable",
        status=InjuryReportStatus.QUESTIONABLE,
        source_url="https://example.invalid/fixture",
        import_schema_version=LEGACY_EVIDENCE_SCHEMA_VERSION,
    )
    session.add(legacy_entry)
    session.flush()

    plan = build_plan(session, season="2025-26", season_type=SeasonType.REGULAR)
    target = next(pf for pf in plan.fetches if pf.candidate.report_timestamp == report_timestamp)
    checkpoint = Checkpoint.load(tmp_path / "checkpoint_upgrade.json")
    payload = InjuryReportParseResult(
        report_timestamp=report_timestamp,
        source_url="https://example.invalid/fixture-updated",
        entries=(_entry(report_timestamp=report_timestamp, status=InjuryReportStatus.OUT),),
    )
    script: dict[datetime, InjuryReportParseResult | Exception] = {
        pf.candidate.report_timestamp: ReportNotAvailable(
            "not published", source=SOURCE, endpoint=ENDPOINT, status_code=404
        )
        for pf in plan.fetches
    }
    script[report_timestamp] = payload
    fetcher = _ScriptedFetcher(script)
    result = run_backfill(session, plan=plan, fetch_and_parse=fetcher, checkpoint=checkpoint)
    assert target.candidate in result.fetched

    session.refresh(legacy_entry)
    assert legacy_entry.import_schema_version == CURRENT_EVIDENCE_SCHEMA_VERSION
    # Confirmed the real re-import touched this exact row (not a duplicate) --
    # the status changed to match the newly "fetched" payload.
    assert legacy_entry.status is InjuryReportStatus.OUT


# ==========================================================================
# default_fetch_and_parse: the seam wired to the real parser + a real fixture
# ==========================================================================


class _FakeClient:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[tuple[datetime, timedelta | None]] = []

    def fetch(self, report_timestamp: datetime, *, max_age: timedelta | None = None) -> bytes:
        self.calls.append((report_timestamp, max_age))
        return self.body


def test_default_fetch_and_parse_wires_the_real_parser_to_a_fake_transport() -> None:
    fake = _FakeClient(FIXTURE_PDF.read_bytes())
    fetch_and_parse = default_fetch_and_parse(fake, no_cache=True)

    requested = _et(2025, 11, 1, 17, 30)
    parsed = fetch_and_parse(requested)

    assert fake.calls == [(requested, NO_CACHE)]
    assert parsed.report_timestamp == requested
    assert len(parsed.entries) > 0


def test_default_fetch_and_parse_uses_normal_caching_window_when_not_forced() -> None:
    fake = _FakeClient(FIXTURE_PDF.read_bytes())
    fetch_and_parse = default_fetch_and_parse(fake, no_cache=False)

    fetch_and_parse(_et(2025, 11, 1, 17, 30))

    assert fake.calls[0][1] is None  # let the client apply its own default max_age


# ==========================================================================
# main(): end-to-end CLI gate ordering and coverage persistence
#
# ``main`` is ``# pragma: no cover - operator tool`` in the module itself
# (it is the thin argparse/wiring layer every other test exercises through
# its constituent functions), but round-5 review requires proving the gate
# *ordering* and the coverage-persistence-on-failure paths actually work
# when driven the way an operator really invokes them -- through the CLI
# entry point, not just the functions it calls. Network and NBA-stats seams
# are monkeypatched at the module level (``backfill_module``), the same
# seams ``default_expected_game_fetcher``/``default_fetch_and_parse``
# already exist for; no test here makes a real HTTP call.
# ==========================================================================


def _fake_expected_game_fetcher_factory(
    expected_games: Sequence[NbaGameRecord],
) -> Any:
    def factory(nba: Any) -> Any:
        def fetch(season: str, season_type_label: str) -> Sequence[NbaGameRecord]:
            return expected_games

        return fetch

    return factory


def _fake_fetch_and_parse_factory(
    outcome_for: Callable[[datetime], InjuryReportParseResult | Exception],
) -> Any:
    """``outcome_for(report_timestamp) -> InjuryReportParseResult | Exception``."""

    def factory(client: Any, *, no_cache: bool = False) -> Any:
        def fetch(report_timestamp: datetime) -> InjuryReportParseResult:
            outcome = outcome_for(report_timestamp)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return fetch

    return factory


def _commit_game(database: Any, **kwargs: Any) -> NbaGame:
    """Seed and commit a game on its own session, so ``main``'s own fresh
    ``Database.from_settings(settings)`` connection (a separate connection
    against the same SQLite file) can actually see it."""
    with database.session() as seed_session:
        game = _seed_game(seed_session, **kwargs)
        seed_session.commit()
        game_id = game.id
    with database.session() as read_session:
        result: NbaGame | None = read_session.get(NbaGame, game_id)
        assert result is not None
        return result


def test_main_observations_discards_scope_mismatched_expected_coverage_evidence(
    database: Any,
    settings: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Round-5 point 4: a persisted November file must not answer a March request."""
    monkeypatch.setattr(backfill_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        backfill_module, "Database", SimpleNamespace(from_settings=lambda settings: database)
    )
    monkeypatch.setattr(backfill_module, "DEFAULT_CHECKPOINT_DIR", tmp_path / "reports")

    november = ExpectedGameCoverage(
        season="2025-26",
        season_type="regular",
        start="2025-11-01",
        end="2025-11-30",
        expected_count=5,
        ingested_count=5,
        missing=(),
    )
    write_expected_game_coverage(
        default_expected_coverage_path("2025-26", SeasonType.REGULAR), november
    )

    rc = main(
        [
            "observations",
            "2025-26",
            "--start",
            "2026-03-01",
            "--end",
            "2026-03-31",
        ]
    )
    captured = capsys.readouterr()

    assert rc == 0
    assert "Discarding it" in captured.err
    assert "no expected-game-slate evidence" in captured.out


def test_main_run_fails_closed_on_an_unsupported_season_type_before_any_http_call(
    database: Any,
    settings: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Round-5 point 6, exercised through the CLI: preseason must fail closed.

    No expected-game-fetcher or fetch-and-parse seam is patched here at all
    -- if this test ever reached either one, it would attempt a real network
    call and fail loudly, which is exactly the gate-ordering property this
    test is proving: the season-type check runs *before* both.
    """
    monkeypatch.setattr(backfill_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        backfill_module, "Database", SimpleNamespace(from_settings=lambda settings: database)
    )
    monkeypatch.setattr(backfill_module, "DEFAULT_RAW_ROOT", tmp_path / "raw")
    monkeypatch.setattr(backfill_module, "DEFAULT_CHECKPOINT_DIR", tmp_path / "reports")

    rc = main(["run", "2025-26", "--season-type", "preseason"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "not yet supported" in captured.err


def test_main_run_persists_expected_game_coverage_on_gate_failure(
    database: Any,
    settings: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Round-5 point 6 gate-ordering + persistence, through the real CLI entry point.

    A game the official schedule lists but this project never ingested must
    abort ``run`` before any injury-report HTTP call, *and* the evidence of
    exactly which game was missing must land on disk even on this failure
    path -- mirroring ``SuspectedSourceBlock``'s existing partial-persistence
    guarantee.
    """
    teams_holder: dict[str, int] = {}
    with database.session() as seed_session:
        teams_holder.update(_seed_teams(seed_session))
        seed_session.commit()
    game = _commit_game(
        database,
        nba_game_id="0022500900",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams_holder["MIL"],
        away_team_id=teams_holder["SAC"],
    )

    monkeypatch.setattr(backfill_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        backfill_module, "Database", SimpleNamespace(from_settings=lambda settings: database)
    )
    monkeypatch.setattr(backfill_module, "DEFAULT_RAW_ROOT", tmp_path / "raw")
    monkeypatch.setattr(backfill_module, "DEFAULT_CHECKPOINT_DIR", tmp_path / "reports")
    expected_games = [
        NbaGameRecord(
            nba_game_id="0022500900",
            season="2025-26",
            season_type="regular",
            game_date=date(2025, 11, 1),
            home_team_id=teams_holder["MIL"],
            away_team_id=teams_holder["SAC"],
        ),
        NbaGameRecord(
            nba_game_id="0022500901",  # never ingested by this project at all
            season="2025-26",
            season_type="regular",
            game_date=date(2025, 11, 1),
            home_team_id=teams_holder["SAC"],
            away_team_id=teams_holder["MIL"],
        ),
    ]
    monkeypatch.setattr(
        backfill_module,
        "default_expected_game_fetcher",
        _fake_expected_game_fetcher_factory(expected_games),
    )

    rc = main(["run", "2025-26"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "never ingested" in captured.err

    persisted = ExpectedGameCoverage.from_json(
        default_expected_coverage_path("2025-26", SeasonType.REGULAR).read_text(encoding="utf-8")
    )
    assert persisted.expected_count == 2
    assert persisted.ingested_count == 1
    assert persisted.missing == (("0022500901", "2025-11-01"),)
    del game  # only used to seed the DB row


def test_main_run_end_to_end_succeeds_and_persists_coverage(
    database: Any,
    settings: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The full happy-path gate order: plan -> expected-slate -> tip-off ->
    budget -> checkpointed run -> durable coverage, all through ``main``."""
    teams_holder: dict[str, int] = {}
    with database.session() as seed_session:
        teams_holder.update(_seed_teams(seed_session))
        seed_session.commit()
    _commit_game(
        database,
        nba_game_id="0022500900",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams_holder["MIL"],
        away_team_id=teams_holder["SAC"],
    )

    monkeypatch.setattr(backfill_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        backfill_module, "Database", SimpleNamespace(from_settings=lambda settings: database)
    )
    monkeypatch.setattr(backfill_module, "DEFAULT_RAW_ROOT", tmp_path / "raw")
    monkeypatch.setattr(backfill_module, "DEFAULT_CHECKPOINT_DIR", tmp_path / "reports")
    expected_games = [
        NbaGameRecord(
            nba_game_id="0022500900",
            season="2025-26",
            season_type="regular",
            game_date=date(2025, 11, 1),
            home_team_id=teams_holder["MIL"],
            away_team_id=teams_holder["SAC"],
        )
    ]
    monkeypatch.setattr(
        backfill_module,
        "default_expected_game_fetcher",
        _fake_expected_game_fetcher_factory(expected_games),
    )

    def _outcome_for(report_timestamp: datetime) -> InjuryReportParseResult:
        return InjuryReportParseResult(
            report_timestamp=report_timestamp,
            source_url="https://example.invalid/fixture",
            entries=(_entry(report_timestamp=report_timestamp),),
        )

    monkeypatch.setattr(
        backfill_module,
        "default_fetch_and_parse",
        _fake_fetch_and_parse_factory(_outcome_for),
    )

    rc = main(["run", "2025-26"])
    captured = capsys.readouterr()

    assert rc == 0, captured.err

    coverage_report = CoverageReport.from_json(
        default_coverage_path("2025-26", SeasonType.REGULAR).read_text(encoding="utf-8")
    )
    assert len(coverage_report.candidates) > 0
    assert all(c.outcome == "fetched" for c in coverage_report.candidates)

    with database.session() as check_session:
        rows = list(
            check_session.scalars(
                select(InjuryReportEntry).where(InjuryReportEntry.player_name_raw != "")
            )
        )
    assert len(rows) > 0


def test_main_run_persists_coverage_gathered_before_a_403_abort(
    database: Any,
    settings: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Gate-ordering + coverage persistence on the ``SuspectedSourceBlock`` path.

    Mirrors the existing ``run_backfill``-level regression
    (``test_run_backfill_persists_coverage_gathered_before_a_403_abort``) one
    layer up, through the real CLI entry point: an abort must not discard
    the coverage evidence ``main`` is responsible for writing to disk.
    """
    teams_holder: dict[str, int] = {}
    with database.session() as seed_session:
        teams_holder.update(_seed_teams(seed_session))
        seed_session.commit()
    _commit_game(
        database,
        nba_game_id="0022500900",
        game_date=date(2025, 11, 1),
        tipoff_utc=_et(2025, 11, 1, 19, 0),
        home_team_id=teams_holder["MIL"],
        away_team_id=teams_holder["SAC"],
    )

    monkeypatch.setattr(backfill_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        backfill_module, "Database", SimpleNamespace(from_settings=lambda settings: database)
    )
    monkeypatch.setattr(backfill_module, "DEFAULT_RAW_ROOT", tmp_path / "raw")
    monkeypatch.setattr(backfill_module, "DEFAULT_CHECKPOINT_DIR", tmp_path / "reports")
    expected_games = [
        NbaGameRecord(
            nba_game_id="0022500900",
            season="2025-26",
            season_type="regular",
            game_date=date(2025, 11, 1),
            home_team_id=teams_holder["MIL"],
            away_team_id=teams_holder["SAC"],
        )
    ]
    monkeypatch.setattr(
        backfill_module,
        "default_expected_game_fetcher",
        _fake_expected_game_fetcher_factory(expected_games),
    )

    def _always_forbidden(report_timestamp: datetime) -> Exception:
        return ReportNotAvailable("forbidden", source=SOURCE, endpoint=ENDPOINT, status_code=403)

    monkeypatch.setattr(
        backfill_module,
        "default_fetch_and_parse",
        _fake_fetch_and_parse_factory(_always_forbidden),
    )

    rc = main(["run", "2025-26", "--max-forbidden-streak", "1"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "UNSETTLED" in captured.err or "403" in captured.err

    coverage_report = CoverageReport.from_json(
        default_coverage_path("2025-26", SeasonType.REGULAR).read_text(encoding="utf-8")
    )
    assert len(coverage_report.candidates) > 0
    assert any(c.outcome == "forbidden" for c in coverage_report.candidates)


# ==========================================================================
# Round-11 follow-up: a realistic future schema version must be quarantined
# *before* CoverageReport.from_json ever attempts to build the current
# CandidateCoverage shape from its raw dict -- not only after, at
# classification/persistence time. Bumping evidence_schema_version alone
# (as the original round-11 tests did) never actually exercised the crash:
# a genuine future version would plausibly add a field this code has never
# seen, or rename/drop one it currently requires with no default, and the
# old ``CandidateCoverage(**c)`` unpacked the *entire* raw dict regardless
# of version, crashing with TypeError before either downstream check could
# run.
# ==========================================================================


def test_from_json_survives_future_schema_with_an_added_field() -> None:
    """A future version that adds a field must not crash the loader.

    This is the realistic shape a future schema version would plausibly
    take -- new evidence, not merely a bumped integer. Before this fix,
    ``CoverageReport.from_json`` unpacked the raw dict's every key
    (including the unknown one) as a keyword argument to
    ``CandidateCoverage`` regardless of its ``evidence_schema_version``,
    raising ``TypeError: unexpected keyword argument`` and crashing the
    entire load.
    """
    future_candidate = _serialized_candidate(
        report_date="2025-11-01",
        requested_timestamp=_et(2025, 10, 31, 17, 30).isoformat(),
        season="2025-26",
        season_type="regular",
    )
    future_candidate["evidence_schema_version"] = CURRENT_COVERAGE_SCHEMA_VERSION + 1
    future_candidate["confidence_score"] = 0.87  # a field this code has never seen
    raw = {
        "season": "2025-26",
        "season_type": "regular",
        "candidates": [future_candidate],
    }

    # Must not raise -- this exact shape crashed before this fix.
    report = CoverageReport.from_json(json.dumps(raw))

    assert len(report.candidates) == 1
    quarantined = report.candidates[0]
    assert quarantined.evidence_schema_version == CURRENT_COVERAGE_SCHEMA_VERSION + 1
    # Never trusted as real evidence once quarantined.
    assert quarantined.outcome != "fetched"
    assert quarantined.season == ""
    assert quarantined.season_type == ""


def test_from_json_survives_future_schema_with_a_renamed_field() -> None:
    """A future version that renames/drops a currently-required field must not crash either.

    ``report_date`` has no default in ``CandidateCoverage`` -- a future
    version renaming it (here to ``report_date_v4``) previously raised a
    *different* ``TypeError`` (missing required positional argument) in
    addition to the unexpected-keyword one for the new name. Inspecting
    ``evidence_schema_version`` before ever attempting construction closes
    both failure modes at once, because a non-current version is never
    unpacked into the dataclass at all.
    """
    future_candidate = _serialized_candidate(
        report_date="2025-11-01",
        requested_timestamp=_et(2025, 10, 31, 17, 30).isoformat(),
        season="2025-26",
        season_type="regular",
    )
    future_candidate["evidence_schema_version"] = CURRENT_COVERAGE_SCHEMA_VERSION + 1
    future_candidate["report_date_v4"] = future_candidate.pop("report_date")
    raw = {
        "season": "2025-26",
        "season_type": "regular",
        "candidates": [future_candidate],
    }

    report = CoverageReport.from_json(json.dumps(raw))

    assert len(report.candidates) == 1
    assert report.candidates[0].evidence_schema_version == CURRENT_COVERAGE_SCHEMA_VERSION + 1
    assert report.candidates[0].outcome != "fetched"


def test_persist_coverage_survives_future_schema_with_an_added_field(
    tmp_path: Path,
) -> None:
    """The real load -> merge -> save path in ``_persist_coverage`` must survive too.

    The original round-11 quarantine test only ever bumped
    ``evidence_schema_version`` on an otherwise-unchanged raw dict, so it
    never actually exercised a future version that also *adds* a field --
    the realistic shape, and the exact one that crashed
    ``CoverageReport.from_json`` (called internally by ``_persist_coverage``
    to read ``existing``) before this fix.
    """
    path = tmp_path / "coverage.json"
    future_candidate = _serialized_candidate(
        report_date="2025-11-01",
        requested_timestamp=_et(2025, 10, 31, 17, 30).isoformat(),
        season="2025-26",
        season_type="regular",
        game_id=1,
        nba_game_id="nba-future-added-field",
    )
    future_candidate["evidence_schema_version"] = CURRENT_COVERAGE_SCHEMA_VERSION + 1
    future_candidate["confidence_score"] = 0.87
    stale_file = {
        "season": "2025-26",
        "season_type": "regular",
        "candidates": [future_candidate],
    }
    path.write_text(json.dumps(stale_file), encoding="utf-8")

    new_candidate = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(2,),
        applicable_nba_game_ids=("nba-2",),
        outcome="not_available",
        status_code=404,
    )

    # Must not raise -- the real on-disk artifact this run reads back.
    _persist_coverage(path, "2025-26", SeasonType.REGULAR, [new_candidate])

    result = CoverageReport.from_json(path.read_text(encoding="utf-8"))
    # Quarantined out of the rewritten file entirely -- not retained, not
    # rewritten as current, and the loader never crashed on the way there.
    assert len(result.candidates) == 1
    assert result.candidates[0].applicable_nba_game_ids == ("nba-2",)
    assert result.candidates[0].evidence_schema_version == CURRENT_COVERAGE_SCHEMA_VERSION


def test_persist_coverage_survives_future_schema_with_a_renamed_field(
    tmp_path: Path,
) -> None:
    """Same real ``_persist_coverage`` path, but the future version renames a required field.

    ``anchor`` has no default -- renaming it (here to ``anchor_kind``)
    previously raised a missing-required-argument ``TypeError`` from deep
    inside ``_persist_coverage``'s own ``existing`` load, aborting the
    entire persist call (and thus this run's whole checkpoint/coverage
    write) rather than quarantining just the one incompatible record.
    """
    path = tmp_path / "coverage.json"
    future_candidate = _serialized_candidate(
        report_date="2025-11-01",
        requested_timestamp=_et(2025, 10, 31, 17, 30).isoformat(),
        season="2025-26",
        season_type="regular",
        game_id=1,
        nba_game_id="nba-future-renamed-field",
    )
    future_candidate["evidence_schema_version"] = CURRENT_COVERAGE_SCHEMA_VERSION + 1
    future_candidate["anchor_kind"] = future_candidate.pop("anchor")
    stale_file = {
        "season": "2025-26",
        "season_type": "regular",
        "candidates": [future_candidate],
    }
    path.write_text(json.dumps(stale_file), encoding="utf-8")

    new_candidate = CandidateCoverage.from_candidate(
        ReportCandidate(date(2025, 11, 2), "evening_before", _et(2025, 11, 1, 17, 30)),
        season="2025-26",
        season_type="regular",
        applicable_game_ids=(2,),
        applicable_nba_game_ids=("nba-2",),
        outcome="not_available",
        status_code=404,
    )

    _persist_coverage(path, "2025-26", SeasonType.REGULAR, [new_candidate])

    result = CoverageReport.from_json(path.read_text(encoding="utf-8"))
    assert len(result.candidates) == 1
    assert result.candidates[0].applicable_nba_game_ids == ("nba-2",)


def test_coverage_for_games_survives_future_schema_with_an_added_field(
    session: Any,
) -> None:
    """End-to-end through the ``observations`` CLI's real load path.

    ``main``'s ``observations`` subcommand reads a persisted coverage file
    via ``CoverageReport.from_json`` and feeds the result straight into
    ``coverage_for_games`` -- the same crash this closes would have taken
    down that CLI path too, for the same realistic added-field future
    version. This proves the exact chain survives, and that the
    quarantined record is never trusted for a clean-submission claim once
    it does.
    """
    teams = _seed_teams(session)
    game = _seed_game(
        session,
        nba_game_id="future-schema-added-field",
        game_date=date(2025, 11, 2),
        tipoff_utc=_et(2025, 11, 2, 19, 0),
        home_team_id=teams["MIL"],
        away_team_id=teams["SAC"],
    )
    canonical_ts = _et(2025, 11, 1, 17, 30)
    future_candidate_raw = _serialized_candidate(
        report_date="2025-11-02",
        requested_timestamp=canonical_ts.isoformat(),
        season="2025-26",
        season_type="regular",
        game_id=game.id,
        nba_game_id=game.nba_game_id,
        outcome="fetched",
    )
    future_candidate_raw["evidence_schema_version"] = CURRENT_COVERAGE_SCHEMA_VERSION + 1
    future_candidate_raw["confidence_score"] = 0.99
    raw_report = {
        "season": "2025-26",
        "season_type": "regular",
        "candidates": [future_candidate_raw],
    }

    # The exact sequence the ``observations`` CLI subcommand runs: parse
    # the persisted JSON, then classify against it. Must not raise.
    coverage_report = CoverageReport.from_json(json.dumps(raw_report))

    ready, missing = games_to_backfill(session, season="2025-26", season_type=SeasonType.REGULAR)
    coverage = coverage_for_games(
        session, ready=ready, missing_tipoff=missing, coverage_report=coverage_report
    )
    by_game_id = {gc.game_id: gc for gc in coverage}
    assert by_game_id[game.id].outcome != "submitted_zero_listed", (
        "an unrecognized future schema version must never be trusted for a "
        "clean-submission claim, even after surviving the load"
    )
    assert by_game_id[game.id].outcome == "no_candidate_coverage"
