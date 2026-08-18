"""NBA official injury report adapter.

A published PDF, not an API: no documented schema, published irregularly
through the day, and captured whole because a document is the unit of raw
evidence here (ADR-006) the way a JSON payload is for the other sources.
"""

from hoops_gm.ingest.injury_report.client import (
    DEFAULT_MAX_AGE,
    DEFAULT_MIN_INTERVAL_SECONDS,
    InjuryReportClient,
    ReportNotAvailable,
    report_url,
)
from hoops_gm.ingest.injury_report.models import (
    InjuryReportEntryRecord,
    InjuryReportParseResult,
    InjuryReportStatus,
)
from hoops_gm.ingest.injury_report.parser import (
    ENDPOINT,
    HEADER_LABELS,
    SOURCE,
    parse_injury_report_pdf,
)

__all__ = [
    "DEFAULT_MAX_AGE",
    "DEFAULT_MIN_INTERVAL_SECONDS",
    "ENDPOINT",
    "HEADER_LABELS",
    "SOURCE",
    "InjuryReportClient",
    "InjuryReportEntryRecord",
    "InjuryReportParseResult",
    "InjuryReportStatus",
    "ReportNotAvailable",
    "parse_injury_report_pdf",
    "report_url",
]
