"""Adapter gate: the NBA official injury report PDF.

Fixture: a real captured report from 2025-11-01 05:30 PM ET, chosen because it
exercises every case the parser handles — 14 matchups over 7 pages, a reason
that wraps across two physical lines, and a same-team "NOT YET SUBMITTED"
marker for two teams whose report had not been filed as of this capture.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from hoops_gm.db.models.enums import InjuryReportStatus, SeasonType
from hoops_gm.db.models.identity import NbaTeam, Player
from hoops_gm.db.models.injury_report import InjuryReportEntry
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.importers import import_injury_report_entries, import_teams
from hoops_gm.ingest.injury_report import (
    InjuryReportClient,
    ReportNotAvailable,
    parse_injury_report_pdf,
    report_url,
)
from hoops_gm.ingest.nba.models import NbaTeamRecord

pytestmark = pytest.mark.adapter_contract

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EASTERN = ZoneInfo("America/New_York")
REPORT_TIMESTAMP = datetime(2025, 11, 1, 17, 30, tzinfo=EASTERN)
FIXTURE_PDF = FIXTURES / "nba_injury_report_2025-11-01_0530pm.pdf"


def load_pdf() -> bytes:
    return FIXTURE_PDF.read_bytes()


# ==========================================================================
# URL construction
# ==========================================================================


def test_report_url_uses_the_hourly_legacy_format_before_the_15_minute_era() -> None:
    url = report_url(REPORT_TIMESTAMP)
    assert url == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-11-01_05PM.pdf"


def test_report_url_uses_15_minute_granularity_after_the_format_change() -> None:
    url = report_url(datetime(2026, 1, 15, 17, 30, tzinfo=EASTERN))
    assert (
        url == "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-01-15_05_30PM.pdf"
    )


def test_report_url_rejects_a_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        report_url(datetime(2025, 11, 1, 17, 30))


# ==========================================================================
# Parsing
# ==========================================================================


def test_parses_every_matchup_and_a_wrapped_multiline_reason() -> None:
    result = parse_injury_report_pdf(
        load_pdf(), report_timestamp=REPORT_TIMESTAMP, source_url="https://example.invalid/fixture"
    )

    matchups = {e.matchup_raw for e in result.entries}
    assert len(matchups) == 14
    assert "SAC@MIL" in matchups

    murray = next(e for e in result.entries if e.player_name_raw == "Murray, Keegan")
    assert murray.status is InjuryReportStatus.OUT
    assert murray.reason_raw == "Injury/Illness - Left Thumb; UCL Injury Recovery"
    assert murray.game_date == date(2025, 11, 1)
    assert murray.team_raw == "Sacramento Kings"
    assert murray.matchup_raw == "SAC@MIL"


def test_not_yet_submitted_rows_are_present_but_excluded_from_player_entries() -> None:
    result = parse_injury_report_pdf(
        load_pdf(), report_timestamp=REPORT_TIMESTAMP, source_url="https://example.invalid/fixture"
    )

    unsubmitted = [e for e in result.entries if e.status is InjuryReportStatus.NOT_YET_SUBMITTED]
    assert len(unsubmitted) == 5
    assert {e.team_raw for e in unsubmitted} == {
        "Oklahoma City Thunder",
        "Charlotte Hornets",
        "San Antonio Spurs",
        "Phoenix Suns",
        "Los Angeles Lakers",
    }
    assert all(e.player_name_raw == "" for e in unsubmitted)
    assert all(e not in result.player_entries for e in unsubmitted)


def test_page_footer_text_never_leaks_into_a_data_row() -> None:
    result = parse_injury_report_pdf(
        load_pdf(), report_timestamp=REPORT_TIMESTAMP, source_url="https://example.invalid/fixture"
    )
    for entry in result.entries:
        assert "Page" not in entry.team_raw
        assert "Page" not in entry.player_name_raw


def test_the_report_timestamp_is_cross_checked_against_the_pdf_masthead() -> None:
    """FAILS IF the parser stops verifying it fetched the report it thinks it did."""
    wrong_timestamp = REPORT_TIMESTAMP + timedelta(hours=1)
    with pytest.raises(SourceContractError, match="masthead"):
        parse_injury_report_pdf(
            load_pdf(),
            report_timestamp=wrong_timestamp,
            source_url="https://example.invalid/fixture",
        )


def test_parser_rejects_a_naive_report_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_injury_report_pdf(
            load_pdf(),
            report_timestamp=datetime(2025, 11, 1, 17, 30),
            source_url="https://example.invalid/fixture",
        )


def test_parser_rejects_a_document_with_a_different_column_layout() -> None:
    """FAILS IF the report's column layout changed and the parser did not notice.

    Exercises the header-anchoring logic directly rather than mangling the
    real PDF's bytes: the report's content stream is compressed, so a raw
    byte substitution does not reliably change what actually renders.
    """
    from hoops_gm.ingest.injury_report.parser import _find_column_bounds

    class FakePage:
        width = 842.0

        def extract_words(self, x_tolerance: float = 1.5) -> list[dict[str, Any]]:
            # "Matchup" renamed to "Matchxxx" -- the header no longer matches
            # the expected fixed sequence of seven column labels.
            return [
                {"text": "Game", "x0": 23.1, "x1": 50.2, "top": 107.7},
                {"text": "Date", "x0": 53.0, "x1": 75.0, "top": 107.7},
                {"text": "Game", "x0": 119.6, "x1": 146.6, "top": 107.7},
                {"text": "Time", "x0": 149.4, "x1": 172.7, "top": 107.7},
                {"text": "Matchxxx", "x0": 200.0, "x1": 241.8, "top": 107.7},
                {"text": "Team", "x0": 264.2, "x1": 290.0, "top": 107.7},
                {"text": "Player", "x0": 425.0, "x1": 454.1, "top": 107.7},
                {"text": "Name", "x0": 456.9, "x1": 484.7, "top": 107.7},
                {"text": "Current", "x0": 585.7, "x1": 621.3, "top": 107.7},
                {"text": "Status", "x0": 624.1, "x1": 653.3, "top": 107.7},
                {"text": "Reason", "x0": 666.1, "x1": 699.9, "top": 107.7},
            ]

    with pytest.raises(SourceContractError, match="Matchup"):
        _find_column_bounds(FakePage())


def test_parser_rejects_an_unrecognised_status_value() -> None:
    """FAILS IF an unrecognised Current Status silently passes through.

    The report's status vocabulary is closed (OUT, DOUBTFUL, QUESTIONABLE,
    PROBABLE, AVAILABLE); this guards against silently accepting a sixth.
    """
    from hoops_gm.ingest.injury_report.parser import _parse_status

    with pytest.raises(SourceContractError, match="unrecognised Current Status"):
        _parse_status("Rehabbing")


# ==========================================================================
# Transport
# ==========================================================================


def test_client_translates_a_404_into_report_not_available() -> None:
    import urllib.error
    from email.message import Message

    class FailingOpener:
        def __call__(self, request: Any, timeout: float) -> Any:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", Message(), None)

    client = InjuryReportClient(opener=FailingOpener())
    with pytest.raises(ReportNotAvailable):
        client.fetch(REPORT_TIMESTAMP)


def test_client_rejects_a_200_body_that_is_not_a_pdf() -> None:
    """FAILS IF an HTML error page served under HTTP 200 is treated as data."""

    class FakeResponse:
        status = 200
        headers: ClassVar[dict[str, str]] = {"Content-Type": "text/html"}

        def read(self) -> bytes:
            return b"<html>not a pdf</html>"

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    def opener(request: Any, timeout: float) -> Any:
        return FakeResponse()

    client = InjuryReportClient(opener=opener)
    with pytest.raises(SourceContractError, match="PDF magic"):
        client.fetch(REPORT_TIMESTAMP)


# ==========================================================================
# Import
# ==========================================================================


def test_import_is_idempotent_and_resolves_team_game_and_player(session: Any) -> None:
    result = parse_injury_report_pdf(
        load_pdf(),
        report_timestamp=REPORT_TIMESTAMP,
        source_url="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-11-01_05PM.pdf",
    )

    import_teams(
        session,
        [
            NbaTeamRecord(1610612758, "SAC", "Sacramento Kings"),
            NbaTeamRecord(1610612749, "MIL", "Milwaukee Bucks"),
        ],
    )
    teams = {t.nba_team_id: t.id for t in session.scalars(select(NbaTeam))}
    game = NbaGame(
        nba_game_id="0022500100",
        season="2025-26",
        season_type=SeasonType.REGULAR,
        game_date=date(2025, 11, 1),
        home_team_id=teams[1610612749],
        away_team_id=teams[1610612758],
    )
    session.add(game)
    player = Player(
        full_name="Keegan Murray",
        normalized_name="keegan murray",
        current_team_id=teams[1610612758],
    )
    session.add(player)
    session.flush()

    first = import_injury_report_entries(session, result.entries, source_url=result.source_url)
    second = import_injury_report_entries(session, result.entries, source_url=result.source_url)

    assert first.created == len(result.entries)
    assert second.updated == len(result.entries)
    assert second.created == 0

    rows = session.scalars(select(InjuryReportEntry)).all()
    assert len(rows) == len(result.entries)

    murray_row = next(r for r in rows if r.player_name_raw == "Murray, Keegan")
    assert murray_row.player_id == player.id
    assert murray_row.team_id == teams[1610612758]
    assert murray_row.game_id == game.id
    assert murray_row.status is InjuryReportStatus.OUT

    unmatched = [r for r in rows if r.player_name_raw and r.player_id is None]
    # Every player besides Keegan Murray is genuinely absent from the tiny
    # crosswalk seeded above, so they are expected to stay unresolved rather
    # than guessed at.
    assert len(unmatched) == len(result.player_entries) - 1


def test_import_never_guesses_a_player_id_for_an_ambiguous_normalized_name(session: Any) -> None:
    result = parse_injury_report_pdf(
        load_pdf(),
        report_timestamp=REPORT_TIMESTAMP,
        source_url="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2025-11-01_05PM.pdf",
    )
    murray = next(e for e in result.entries if e.player_name_raw == "Murray, Keegan")

    # Two different players share a normalized name and neither is on the
    # matchup's team -- an ambiguity the importer must not resolve by guessing.
    session.add_all(
        [
            Player(full_name="Keegan Murray A", normalized_name="keegan murray"),
            Player(full_name="Keegan Murray B", normalized_name="keegan murray"),
        ]
    )
    session.flush()

    import_injury_report_entries(session, [murray], source_url="https://example.invalid/fixture")
    row = session.scalars(select(InjuryReportEntry)).one()
    assert row.player_id is None
