"""Parser for the NBA official injury report PDF.

The report is a **document**, not an API: a fixed-width, ruled table rendered
to PDF, published the evening before a slate and updated through game day.
There is no JSON, so this module leans on the page's own drawn ruling lines
rather than trusting word positions alone.

**Why geometry, not raw text extraction.** A naive text extraction reads each
PDF word as its own line, in an order that does not match the visual table:
Team, Matchup and Game Date are each printed once per group and left to imply
they apply to every row below until the next label, and — the finding that
matters most here — the ``Reason`` cell's line height *drives* the row's
total height, so a short cell (Player Name, Current Status) that shares a row
with a two-line wrapped Reason is vertically **centred** inside that row
rather than top-aligned with it. Reading words by ascending ``top`` alone
therefore interleaves one player's second Reason line with the *next*
player's Name — verified against a real captured report on 2026-08-17, where
"Injury/Illness - Left Thumb; UCL" (Murray, Keegan's reason, wrapped) prints
*above* "Murray, Keegan" itself, not below it.

**What actually works.** The report draws real horizontal ruling lines
between rows, but only under the Player Name / Current Status / Reason
columns — Game Date / Game Time / Matchup / Team are merged cells that do not
get one, because they are forward-filled across several rows. Column
divider lines are drawn once, on the first page only; continuation pages
share the same absolute coordinates (same fixed page size) but draw no
verticals at all. So: derive column x-boundaries from page 1's own header
labels (self-verifying — if the labels are not exactly the seven expected,
this is upstream drift and the loud failure is exactly the point), reuse them
for every page, and use each page's own horizontal ruling lines as row
boundaries. Every physical text line inside a cell's y-range is joined with a
space, which is what correctly reassembles a wrapped multi-line Reason without
merging two different players' text.

A page footer ("Page N of M") overlaps the last row's y-range because no
ruling line is drawn beneath it; its own "Page" token is used to clip the
final row before it swallows footer text into the Team/Player Name columns.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from typing import Any, Final
from zoneinfo import ZoneInfo

from hoops_gm.db.models.enums import InjuryReportStatus
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.injury_report.models import InjuryReportEntryRecord, InjuryReportParseResult

SOURCE: Final = "nba_injury_report"
ENDPOINT: Final = "InjuryReportPdf"
EASTERN: Final = ZoneInfo("America/New_York")

#: The seven columns the report has always carried, in order, lower-cased and
#: space-stripped. Anchoring on this exact sequence is deliberate: it is the
#: whole contract, and any deviation — a renamed, reordered, added or removed
#: column — must fail loudly rather than silently misalign every field to its
#: neighbour.
HEADER_LABELS: Final[tuple[str, ...]] = (
    "gamedate",
    "gametime",
    "matchup",
    "team",
    "playername",
    "currentstatus",
    "reason",
)

#: The report's own vocabulary, lower-cased. Five official designations plus
#: the one marker that means "no designation was filed yet" — see
#: :class:`~hoops_gm.db.models.enums.InjuryReportStatus`.
_STATUS_MAP: Final[dict[str, InjuryReportStatus]] = {
    "out": InjuryReportStatus.OUT,
    "doubtful": InjuryReportStatus.DOUBTFUL,
    "questionable": InjuryReportStatus.QUESTIONABLE,
    "probable": InjuryReportStatus.PROBABLE,
    "available": InjuryReportStatus.AVAILABLE,
}
_NOT_YET_SUBMITTED: Final = "not yet submitted"

_MASTHEAD_RE: Final = re.compile(r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4})$")
_TIME_RE: Final = re.compile(r"^(?P<time>\d{1,2}:\d{2})$")
_AMPM_RE: Final = re.compile(r"^(AM|PM)$", re.IGNORECASE)

#: How far apart two words in the same header phrase may sit (points). Chosen
#: from the real report: within-phrase gaps ("Game" -> "Date") are ~2.8pt,
#: while the narrowest cross-column gap ("Status" -> "Reason") is ~12.8pt.
_HEADER_PHRASE_GAP_PT: Final = 8.0
#: A word's x-position tolerance when grouping physical lines within a cell.
_LINE_TOP_ROUND_PT: Final = 1.0
#: How close a horizontal ruling line's x0 must sit to the Player Name
#: column's left edge to count as a row boundary.
_ROW_LINE_X_TOLERANCE_PT: Final = 3.0
#: Fraction of page height beyond which a "Page" token is treated as the
#: footer rather than as data.
_FOOTER_ZONE_FRACTION: Final = 0.8


def parse_injury_report_pdf(
    pdf_bytes: bytes, *, report_timestamp: datetime, source_url: str
) -> InjuryReportParseResult:
    """Parse one captured PDF into typed entries.

    ``report_timestamp`` must be timezone-aware; it is cross-checked against
    the PDF's own "Injury Report: MM/DD/YY HH:MM (AM|PM)" masthead so that a
    caller cannot silently attribute one report's content to another
    timestamp's row (e.g. a stale cache key).
    """
    if report_timestamp.tzinfo is None:
        raise ValueError("report_timestamp must be timezone-aware")

    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - dependency is required in `ingest` extra
        raise RuntimeError(
            "pdfplumber is required to parse the injury report; install the "
            "'ingest' extra (`pip install hoops-gm-backend[ingest]`)"
        ) from exc

    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            if not pdf.pages:
                raise _contract("PDF has no pages")
            _verify_masthead(pdf.pages[0], report_timestamp)
            col_bounds = _find_column_bounds(pdf.pages[0])

            game_date = ""
            game_time = ""
            matchup = ""
            team = ""
            entries: list[InjuryReportEntryRecord] = []

            for page in pdf.pages:
                row_tops = _find_row_bounds(page, col_bounds)
                if not row_tops:
                    raise _contract(f"page {page.page_number} has no row ruling lines")
                footer_tops = [
                    w["top"]
                    for w in page.extract_words(x_tolerance=1.5)
                    if w["text"] == "Page" and w["top"] > page.height * _FOOTER_ZONE_FRACTION
                ]
                bottom = min(footer_tops) - 2 if footer_tops else page.height - 10
                top_margin = row_tops[0] - 40
                ys = [max(top_margin, 0.0), *row_tops, bottom]

                for i in range(len(ys) - 1):
                    y0, y1 = ys[i], ys[i + 1]
                    row = [
                        _cell_text(page, col_bounds[c], col_bounds[c + 1], y0, y1)
                        for c in range(len(col_bounds) - 1)
                    ]
                    if all(not c for c in row):
                        continue
                    if [c.lower() for c in row[:3]] == ["game date", "game time", "matchup"]:
                        continue  # the header row itself, re-detected on the data grid

                    if row[0]:
                        game_date = row[0]
                    if row[1]:
                        game_time = row[1]
                    if row[2]:
                        matchup = row[2]
                    if row[3]:
                        team = row[3]
                    player_name_raw, status_raw, reason_raw = row[4], row[5], row[6]

                    if not player_name_raw and not status_raw:
                        if reason_raw.strip().lower() == _NOT_YET_SUBMITTED:
                            entries.append(
                                InjuryReportEntryRecord(
                                    report_timestamp=report_timestamp,
                                    game_date=_parse_game_date(game_date),
                                    game_time_raw=game_time,
                                    matchup_raw=matchup,
                                    team_raw=team,
                                    player_name_raw="",
                                    status_raw="",
                                    status=InjuryReportStatus.NOT_YET_SUBMITTED,
                                    reason_raw=reason_raw,
                                )
                            )
                            continue
                        # An empty data row with no recognisable marker. Rows are
                        # only ever blank filler between the header and the
                        # first entry, already screened out above by the
                        # "all empty" check; anything else here is unexpected.
                        continue

                    entries.append(
                        InjuryReportEntryRecord(
                            report_timestamp=report_timestamp,
                            game_date=_parse_game_date(game_date),
                            game_time_raw=game_time,
                            matchup_raw=matchup,
                            team_raw=team,
                            player_name_raw=player_name_raw,
                            status_raw=status_raw,
                            status=_parse_status(status_raw),
                            reason_raw=reason_raw,
                        )
                    )
    except SourceContractError:
        raise
    except Exception as exc:
        raise SourceContractError(
            f"failed to parse the injury report PDF ({type(exc).__name__}: {exc})",
            source=SOURCE,
            endpoint=ENDPOINT,
        ) from exc

    return InjuryReportParseResult(
        report_timestamp=report_timestamp, source_url=source_url, entries=tuple(entries)
    )


def _verify_masthead(page: Any, report_timestamp: datetime) -> None:
    """Confirm the PDF's own masthead names the timestamp it was requested for."""
    # Restricted to the top of the page: the masthead is always the first
    # thing printed, and without this bound a Game Date value from the data
    # grid below (which matches the same date pattern) could be mistaken for
    # the masthead's own date if word order ever stopped being top-to-bottom.
    words = [w for w in page.extract_words(x_tolerance=1.5) if w["top"] < page.height * 0.15]
    date_text = time_text = ampm_text = None
    for i, word in enumerate(words):
        if date_text is None and _MASTHEAD_RE.match(word["text"]):
            date_text = word["text"]
            continue
        if date_text is not None and time_text is None and _TIME_RE.match(word["text"]):
            time_text = word["text"]
            if i + 1 < len(words) and _AMPM_RE.match(words[i + 1]["text"]):
                ampm_text = words[i + 1]["text"].upper()
            break
    if not date_text or not time_text or not ampm_text:
        raise _contract("could not find the 'Injury Report: <date> <time> <AM|PM>' masthead")

    try:
        parsed = datetime.strptime(f"{date_text} {time_text} {ampm_text}", "%m/%d/%y %I:%M %p")
    except ValueError as exc:
        raise _contract(
            f"masthead date/time did not parse: {date_text} {time_text} {ampm_text}"
        ) from exc

    masthead_eastern = parsed.replace(tzinfo=EASTERN)
    requested_eastern = report_timestamp.astimezone(EASTERN)
    # A tolerance, not an exact match. Verified live 2026-08-17: the legacy
    # hourly filename era names a file "01PM" for a report whose own masthead
    # reads "1:30 PM" -- the filename only ever encodes the hour, and the
    # report is consistently published at :30 past it. An exact-minute
    # comparison would reject every legacy-era fetch as a "mismatched
    # capture" when nothing has actually gone wrong.
    if abs(masthead_eastern - requested_eastern) > timedelta(minutes=45):
        raise _contract(
            f"masthead reports {masthead_eastern.isoformat()} but "
            f"{requested_eastern.isoformat()} was requested; a stale or mismatched "
            "capture is being read"
        )


def _find_column_bounds(page: Any) -> list[float]:
    words = page.extract_words(x_tolerance=1.5)
    matchup_hits = [w["top"] for w in words if w["text"] == "Matchup"]
    if not matchup_hits:
        raise _contract("could not locate the 'Matchup' header to anchor column boundaries")
    header_top = matchup_hits[0]
    header_words = sorted(
        (w for w in words if abs(w["top"] - header_top) < 2), key=lambda w: w["x0"]
    )

    phrases: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for word in header_words:
        if current is not None and word["x0"] - current["x1"] < _HEADER_PHRASE_GAP_PT:
            current["x1"] = word["x1"]
            current["text"] += word["text"]
        else:
            current = {"x0": word["x0"], "x1": word["x1"], "text": word["text"]}
            phrases.append(current)

    found = tuple(p["text"].lower() for p in phrases)
    if found != HEADER_LABELS:
        raise _contract(
            f"unexpected header row {found!r}; expected {HEADER_LABELS!r}. The report's "
            "column layout has changed"
        )
    bounds = [p["x0"] - 4 for p in phrases]
    bounds.append(page.width - 19)
    return bounds


def _find_row_bounds(page: Any, col_bounds: list[float]) -> list[float]:
    """Row-boundary y-positions, from ruling lines under Player Name onward."""
    player_name_left = col_bounds[4]
    return sorted(
        {
            round(edge["top"], 1)
            for edge in page.edges
            if edge["orientation"] == "h"
            and abs(edge["x0"] - player_name_left) < _ROW_LINE_X_TOLERANCE_PT
        }
    )


def _cell_text(page: Any, x0: float, x1: float, y0: float, y1: float) -> str:
    cropped = page.within_bbox((x0, y0, x1, y1))
    words = cropped.extract_words(x_tolerance=1.5)
    lines: dict[float, list[str]] = {}
    for word in words:
        key = round(word["top"] / _LINE_TOP_ROUND_PT) * _LINE_TOP_ROUND_PT
        lines.setdefault(key, []).append(word["text"])
    ordered = [lines[k] for k in sorted(lines)]
    return " ".join(" ".join(line) for line in ordered).strip()


def _parse_game_date(raw: str) -> date:
    try:
        return datetime.strptime(raw, "%m/%d/%Y").date()
    except ValueError as exc:
        raise _contract(f"unparseable Game Date {raw!r}") from exc


def _parse_status(raw: str) -> InjuryReportStatus:
    key = raw.strip().lower()
    status = _STATUS_MAP.get(key)
    if status is None:
        raise _contract(
            f"unrecognised Current Status {raw!r}; the league's closed vocabulary "
            f"(OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, AVAILABLE) may have changed"
        )
    return status


def _contract(message: str) -> SourceContractError:
    return SourceContractError(message, source=SOURCE, endpoint=ENDPOINT)


#: Re-exported for convenience — a caller building UTC instants from Eastern
#: report timestamps does not need to import ``zoneinfo`` separately.
def eastern_to_utc(eastern_naive_or_aware: datetime) -> datetime:
    if eastern_naive_or_aware.tzinfo is None:
        return eastern_naive_or_aware.replace(tzinfo=EASTERN).astimezone(UTC)
    return eastern_naive_or_aware.astimezone(UTC)
