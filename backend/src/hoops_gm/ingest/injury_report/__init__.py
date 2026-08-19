"""NBA official injury report adapter.

A published PDF, not an API: no documented schema, published irregularly
through the day, and captured whole because a document is the unit of raw
evidence here (ADR-006) the way a JSON payload is for the other sources.

The historical backfill (``hoops_gm.ingest.injury_report.backfill``) is
deliberately **not** re-exported here: it imports ``hoops_gm.ingest
.importers``, which itself imports ``hoops_gm.ingest.injury_report.models``
— re-exporting it from this package's own ``__init__`` would make importing
``importers`` require this package to finish initializing while this package
is itself waiting on ``importers`` to finish, an import cycle. Import it
directly: ``from hoops_gm.ingest.injury_report.backfill import build_plan``,
exactly as ``hoops_gm.ingest.backfill`` is never re-exported from
``hoops_gm.ingest`` either, for the same reason.
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
