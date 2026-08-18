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
from hoops_gm.ingest.injury_report.models import InjuryReportEntryRecord
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


def test_a_reason_wrapped_across_a_page_break_is_reattached_not_truncated() -> None:
    """FAILS IF the tail of a page-spanning wrapped Reason goes missing again.

    Found while fixing the "silently skip an unrecognised row" defect
    (independent review, blocking finding 3): "Toppin, Obi"'s row is the
    last one on page 2, and its Reason wraps to a second physical line that
    the report renders past page 2's own bottom margin -- it reappears at
    the very top of page 3, alone, with every other column blank. Before
    this fix that orphaned continuation was silently dropped (the same
    `continue` the new loud-raise now replaces for genuinely unrecognised
    rows), truncating the real reason from "...Stress Fracture" to
    "...Stress". It must now be reattached to the entry it belongs to.
    """
    result = parse_injury_report_pdf(
        load_pdf(), report_timestamp=REPORT_TIMESTAMP, source_url="https://example.invalid/fixture"
    )
    toppin = next(e for e in result.entries if e.player_name_raw == "Toppin, Obi")
    assert toppin.reason_raw == "Injury/Illness - Right Foot; Stress Fracture"


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


def test_parse_result_is_stamped_with_the_masthead_instant_not_the_request_instant() -> None:
    """FAILS IF the parser starts persisting the caller's request instant.

    ``report_timestamp`` is only ever a request hint: the masthead check
    tolerates up to 45 minutes of drift from it, and the legacy hourly-
    filename era (``client.report_url``) truncates a request to the hour
    before this function ever sees it. Two different in-tolerance requests
    for the same PDF (here, 20 minutes on either side of the real 5:30 PM
    masthead) must therefore resolve to the identical canonical timestamp —
    the masthead's own instant — not to each request's own, different one.
    """
    early = REPORT_TIMESTAMP - timedelta(minutes=20)
    late = REPORT_TIMESTAMP + timedelta(minutes=20)
    assert early != late  # the bug this guards against needs them distinct

    early_result = parse_injury_report_pdf(
        load_pdf(), report_timestamp=early, source_url="https://example.invalid/fixture"
    )
    late_result = parse_injury_report_pdf(
        load_pdf(), report_timestamp=late, source_url="https://example.invalid/fixture"
    )

    assert early_result.report_timestamp == late_result.report_timestamp
    assert early_result.report_timestamp == REPORT_TIMESTAMP
    assert all(e.report_timestamp == REPORT_TIMESTAMP for e in early_result.entries)
    assert all(e.report_timestamp == REPORT_TIMESTAMP for e in late_result.entries)


def test_import_converges_two_nearby_legacy_requests_into_one_history_row(session: Any) -> None:
    """FAILS IF nearby legacy-era request instants create false history.

    Before the masthead-canonicalization fix, two callers requesting "the
    report near 5:30pm" at 20 minutes early and 20 minutes late both fetched
    the identical legacy-era PDF but each stamped its own request instant as
    ``report_timestamp`` — and because that field is part of
    ``injury_report_entries``'s natural key, each import created its own
    duplicate row set for what was really one report capture. Both requests
    must now converge on a single set of rows keyed by the masthead's own
    instant.
    """
    early = REPORT_TIMESTAMP - timedelta(minutes=20)
    late = REPORT_TIMESTAMP + timedelta(minutes=20)
    early_result = parse_injury_report_pdf(
        load_pdf(), report_timestamp=early, source_url="https://example.invalid/fixture-early"
    )
    late_result = parse_injury_report_pdf(
        load_pdf(), report_timestamp=late, source_url="https://example.invalid/fixture-late"
    )

    first = import_injury_report_entries(
        session, early_result.entries, source_url=early_result.source_url
    )
    second = import_injury_report_entries(
        session, late_result.entries, source_url=late_result.source_url
    )

    assert first.created == len(early_result.entries)
    assert second.created == 0
    assert second.updated == len(late_result.entries)

    rows = session.scalars(select(InjuryReportEntry)).all()
    assert len(rows) == len(early_result.entries)


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


class _FakeCroppedPage:
    """A ``page.within_bbox(...)`` double: just the words inside the crop."""

    def __init__(self, words: list[dict[str, Any]]) -> None:
        self._words = words

    def extract_words(self, x_tolerance: float = 1.5) -> list[dict[str, Any]]:
        return self._words


class _FakeBadRowPage:
    """A synthetic page producing exactly one malformed data row: no player
    name, no status, and a Reason that is not the NOT YET SUBMITTED marker.

    Built from real word/edge geometry rather than mangled PDF bytes (the
    real fixture's content stream is compressed, so a byte substitution does
    not reliably change what renders) -- the same approach
    ``test_parser_rejects_a_document_with_a_different_column_layout`` already
    uses for ``_find_column_bounds``, extended here to drive the *entire*
    parser end to end so the raise is proven at the public entry point, not
    just in an internal helper.
    """

    page_number = 1
    height = 800.0
    width = 800.0

    def __init__(self) -> None:
        # "Injury Report: 11/01/25 5:30 PM" -- matches REPORT_TIMESTAMP.
        masthead: list[dict[str, Any]] = [
            {"text": "11/01/25", "x0": 10.0, "x1": 60.0, "top": 5.0},
            {"text": "5:30", "x0": 70.0, "x1": 90.0, "top": 5.0},
            {"text": "PM", "x0": 95.0, "x1": 110.0, "top": 5.0},
        ]
        # The seven-column header, positioned so word-gap grouping produces
        # exactly `parser.HEADER_LABELS`.
        header: list[dict[str, Any]] = [
            {"text": "Game", "x0": 0.0, "x1": 30.0, "top": 100.0},
            {"text": "Date", "x0": 32.0, "x1": 55.0, "top": 100.0},
            {"text": "Game", "x0": 100.0, "x1": 130.0, "top": 100.0},
            {"text": "Time", "x0": 132.0, "x1": 155.0, "top": 100.0},
            {"text": "Matchup", "x0": 200.0, "x1": 240.0, "top": 100.0},
            {"text": "Team", "x0": 280.0, "x1": 310.0, "top": 100.0},
            {"text": "Player", "x0": 400.0, "x1": 430.0, "top": 100.0},
            {"text": "Name", "x0": 432.0, "x1": 455.0, "top": 100.0},
            {"text": "Current", "x0": 560.0, "x1": 600.0, "top": 100.0},
            {"text": "Status", "x0": 602.0, "x1": 630.0, "top": 100.0},
            {"text": "Reason", "x0": 700.0, "x1": 740.0, "top": 100.0},
        ]
        # The one malformed data row: a Game Date re-print and a Reason, but
        # no Player Name, no Current Status -- and the Reason text is not the
        # recognised "NOT YET SUBMITTED" marker.
        bad_row: list[dict[str, Any]] = [
            {"text": "11/01/2025", "x0": 0.0, "x1": 60.0, "top": 230.0},
            {"text": "SomethingWeird", "x0": 700.0, "x1": 750.0, "top": 230.0},
        ]
        self._all_words: list[dict[str, Any]] = masthead + header + bad_row
        # One row-boundary ruling line under the Player Name column
        # (x0 == that column's derived left edge), producing exactly one row
        # split so the bad row lands in its own segment.
        self.edges: list[dict[str, Any]] = [{"orientation": "h", "x0": 396.0, "top": 250.0}]

    def extract_words(self, x_tolerance: float = 1.5) -> list[dict[str, Any]]:
        return self._all_words

    def within_bbox(self, bbox: tuple[float, float, float, float]) -> _FakeCroppedPage:
        x0, y0, x1, y1 = bbox
        words = [w for w in self._all_words if x0 <= w["x0"] < x1 and y0 <= w["top"] < y1]
        return _FakeCroppedPage(words)


class _FakePdfDocument:
    def __init__(self, pages: list[Any]) -> None:
        self.pages = pages

    def __enter__(self) -> _FakePdfDocument:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_parser_raises_on_a_nonempty_row_with_no_player_status_or_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF a malformed nonempty row is silently dropped instead of raising.

    A row that names no player and no status, and whose Reason text is not
    the recognised "NOT YET SUBMITTED" marker, has no legitimate place in the
    report's structure -- every real row either names a player+status or is
    that one marker. Before this fix such a row was silently ``continue``-d
    past, indistinguishable from ordinary blank filler; that would hide
    exactly the kind of unnoticed PDF-extraction drift (a mis-detected row
    boundary, a shifted column, a new marker phrase) the Adapter gate exists
    to surface loudly. Exercises the full ``parse_injury_report_pdf`` entry
    point end to end against a synthetic page, not a directly-called private
    helper.
    """
    import pdfplumber

    page = _FakeBadRowPage()
    monkeypatch.setattr(pdfplumber, "open", lambda *_a, **_kw: _FakePdfDocument([page]))

    with pytest.raises(SourceContractError, match="no player name or status"):
        parse_injury_report_pdf(
            b"%PDF-fake",
            report_timestamp=REPORT_TIMESTAMP,
            source_url="https://example.invalid/fixture",
        )


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


def _seed_sac_at_mil_teams(session: Any) -> dict[int, int]:
    import_teams(
        session,
        [
            NbaTeamRecord(1610612758, "SAC", "Sacramento Kings"),
            NbaTeamRecord(1610612749, "MIL", "Milwaukee Bucks"),
        ],
    )
    session.flush()
    return {t.nba_team_id: t.id for t in session.scalars(select(NbaTeam))}


def test_import_resolves_the_home_team_from_a_partial_subset_containing_only_it(
    session: Any,
) -> None:
    """FAILS IF a partial subset misdirects a team to its opponent.

    A real defect found in independent review: resolving which tricode is
    "this" row's team from order-of-appearance within the imported batch
    means a caller importing only one team's rows (e.g. because the other
    team's report had not been filed yet) sees that lone team treated as
    whichever tricode happened to appear first -- here, that would wrongly
    resolve the home Bucks to the away Kings' tricode. Team resolution must
    not depend on any other row being present in the same import call.
    """
    teams = _seed_sac_at_mil_teams(session)

    home_only = InjuryReportEntryRecord(
        report_timestamp=REPORT_TIMESTAMP,
        game_date=date(2025, 11, 1),
        game_time_raw="05:00 (ET)",
        matchup_raw="SAC@MIL",
        team_raw="Milwaukee Bucks",
        player_name_raw="Lopez, Brook",
        status_raw="Out",
        status=InjuryReportStatus.OUT,
        reason_raw="Rest",
    )

    import_injury_report_entries(session, [home_only], source_url="https://example.invalid/fixture")
    row = session.scalars(select(InjuryReportEntry)).one()
    assert row.team_id == teams[1610612749]  # Milwaukee Bucks (home), not swapped to Sacramento


def test_import_does_not_swap_teams_when_entries_are_out_of_report_order(session: Any) -> None:
    """FAILS IF team resolution depends on which row of a matchup is imported first.

    The report always lists the away team's rows before the home team's, but
    nothing about the natural key or this importer should depend on that.
    Feeding the home team's entry before the away team's -- the reverse of
    the report's own order -- must still resolve each row to its own team,
    not swap them.
    """
    teams = _seed_sac_at_mil_teams(session)

    home_entry = InjuryReportEntryRecord(
        report_timestamp=REPORT_TIMESTAMP,
        game_date=date(2025, 11, 1),
        game_time_raw="05:00 (ET)",
        matchup_raw="SAC@MIL",
        team_raw="Milwaukee Bucks",
        player_name_raw="Lopez, Brook",
        status_raw="Out",
        status=InjuryReportStatus.OUT,
        reason_raw="Rest",
    )
    away_entry = InjuryReportEntryRecord(
        report_timestamp=REPORT_TIMESTAMP,
        game_date=date(2025, 11, 1),
        game_time_raw="05:00 (ET)",
        matchup_raw="SAC@MIL",
        team_raw="Sacramento Kings",
        player_name_raw="Murray, Keegan",
        status_raw="Out",
        status=InjuryReportStatus.OUT,
        reason_raw="Injury/Illness - Left Thumb",
    )

    # Home listed first, away second -- the reverse of the report's own order.
    import_injury_report_entries(
        session, [home_entry, away_entry], source_url="https://example.invalid/fixture"
    )

    rows = {r.player_name_raw: r for r in session.scalars(select(InjuryReportEntry)).all()}
    assert rows["Lopez, Brook"].team_id == teams[1610612749]  # Milwaukee Bucks stays Bucks
    assert rows["Murray, Keegan"].team_id == teams[1610612758]  # Sacramento Kings stays Kings
